# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Archive a tagged release on Zenodo through its deposit API.

The GitHub–Zenodo integration is the usual way to do this, and it is how
v0.1.0–v0.2.2 were archived. It stopped working for this repository when the
repository was recreated on GitHub on 2026-09-14: Zenodo keeps repositories by
GitHub id, still holds the previous object under this name, refuses to enable
the recreated one (HTTP 403), and answered its first release event with "The
repository does not exist". Only Zenodo can repair that mapping. This script
does not need it. It deposits GitHub's source archive of the tag with the
metadata in the tag's own ``.zenodo.json``, dated by the tag, so the deposit is
a function of the tag. (GitHub does not promise byte-identical zipballs
forever, so the archive's SHA-256 in the summary fingerprints this deposit, not
the tag.)

Lineage. The concept DOI in the tag's ``CITATION.cff`` is the source of truth.
While it is still the placeholder, the deposit starts a new concept; once
``scripts/set_doi.py`` has written the minted concept DOI there, every later
release becomes a new version of that concept -- the shape the integration
would have produced.

Usage, with ``ZENODO_TOKEN`` in the environment (``.github/workflows/zenodo.yml``
is the caller)::

    python scripts/zenodo_deposit.py --tag v0.3.1            # leaves a draft
    python scripts/zenodo_deposit.py --tag v0.3.1 --publish  # publishes it

A draft is reused by the next run, so ``--publish`` after a dry run publishes
the deposition the dry run created rather than a second one; a draft this run
created is deleted again if a later call fails, so a failed run leaves nothing
behind. A version already published in the lineage is refused. Nothing here
prints the token.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
import yaml

ROOT = Path(__file__).resolve().parents[1]

PRODUCTION = "https://zenodo.org"
SANDBOX = "https://sandbox.zenodo.org"

#: Process exit codes, so the workflow log says which kind of thing went wrong.
EXIT_CONFIG = 2  # no token, tag/metadata disagreement, missing files
EXIT_ALREADY_ARCHIVED = 3  # this version is already published in the lineage
EXIT_API = 4  # Zenodo answered with an error
EXIT_NETWORK = 5  # GitHub or Zenodo could not be reached, or GitHub had no archive

#: What Zenodo requires of a software deposit, checked before anything is sent.
REQUIRED_METADATA = ("title", "description", "creators", "upload_type", "access_right", "license")


class ZenodoError(RuntimeError):
    """An error response from Zenodo, with its message and field errors."""

    def __init__(self, status: int, message: str, errors: list[dict[str, Any]]) -> None:
        detail = "; ".join(f"{e.get('field', '?')}: {e.get('message', '?')}" for e in errors)
        super().__init__(f"HTTP {status}: {message}" + (f" ({detail})" if detail else ""))
        self.status = status


class AlreadyArchived(RuntimeError):
    """The lineage already holds a published record of this version."""


class ArchiveError(RuntimeError):
    """GitHub did not serve the tag's source archive."""


class Zenodo:
    """The handful of deposit-API calls this script needs.

    ``session`` is injectable so the tests can script Zenodo's answers with a
    stand-in that has ``headers`` and ``request()``; the default is a real
    ``requests.Session`` carrying the bearer token.
    """

    def __init__(
        self, token: str, base_url: str = PRODUCTION, session: requests.Session | None = None
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._session = session if session is not None else requests.Session()
        self._session.headers.update(
            {"Authorization": f"Bearer {token}", "User-Agent": "bindsight-zenodo-deposit/1"}
        )

    def _call(self, method: str, url: str, **kwargs: Any) -> Any:
        if url.startswith("/"):
            url = self.base_url + url
        response = self._session.request(method, url, timeout=120, **kwargs)
        if response.status_code >= 400:
            try:
                body = response.json()
            except ValueError:
                body = {}
            raise ZenodoError(
                response.status_code,
                str(body.get("message", "no message")),
                list(body.get("errors", [])),
            )
        if response.status_code == 204:
            return None
        return response.json()

    def list_depositions(self, status: str) -> list[dict[str, Any]]:
        """The account's depositions with the given status, ``draft`` or ``published``."""
        out: list[dict[str, Any]] = self._call(
            "GET",
            "/api/deposit/depositions",
            params={"status": status, "size": 100, "all_versions": "true"},
        )
        return out

    def create_deposition(self, metadata: dict[str, Any]) -> dict[str, Any]:
        """Create a draft with its metadata in one call, so no empty draft ever exists."""
        out: dict[str, Any] = self._call(
            "POST", "/api/deposit/depositions", json={"metadata": metadata}
        )
        return out

    def get_deposition(self, deposition_id: int) -> dict[str, Any]:
        out: dict[str, Any] = self._call("GET", f"/api/deposit/depositions/{deposition_id}")
        return out

    def delete_deposition(self, deposition_id: int) -> None:
        """Delete an unpublished draft. Published records cannot be deleted."""
        self._call("DELETE", f"/api/deposit/depositions/{deposition_id}")

    def update_metadata(self, deposition_id: int, metadata: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = self._call(
            "PUT", f"/api/deposit/depositions/{deposition_id}", json={"metadata": metadata}
        )
        return out

    def latest_record(self, concept_recid: str) -> dict[str, Any]:
        """The newest published version of a concept, by search over its versions."""
        answer = self._call(
            "GET",
            "/api/records",
            params={
                "q": f'conceptrecid:"{concept_recid}"',
                "all_versions": "true",
                "sort": "mostrecent",
                "size": 1,
            },
        )
        hits = list(answer.get("hits", {}).get("hits", []))
        if not hits or str(hits[0].get("conceptrecid")) != concept_recid:
            raise ZenodoError(404, f"no published record found for concept {concept_recid}", [])
        record: dict[str, Any] = hits[0]
        return record

    def new_version(self, record_id: int) -> dict[str, Any]:
        answer = self._call(
            "POST", f"/api/deposit/depositions/{record_id}/actions/newversion", json={}
        )
        draft_url = str(answer["links"]["latest_draft"])
        out: dict[str, Any] = self._call("GET", draft_url)
        return out

    def list_files(self, deposition_id: int) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = self._call(
            "GET", f"/api/deposit/depositions/{deposition_id}/files"
        )
        return out

    def delete_file(self, deposition_id: int, file_id: str) -> None:
        self._call("DELETE", f"/api/deposit/depositions/{deposition_id}/files/{file_id}")

    def upload(self, bucket_url: str, name: str, path: Path) -> dict[str, Any]:
        with path.open("rb") as handle:
            out: dict[str, Any] = self._call("PUT", f"{bucket_url}/{name}", data=handle)
        return out

    def publish(self, deposition_id: int) -> dict[str, Any]:
        out: dict[str, Any] = self._call(
            "POST", f"/api/deposit/depositions/{deposition_id}/actions/publish", json={}
        )
        return out


# --- The tag's own view of itself ---------------------------------------------


def _git(*args: str) -> str:
    done = subprocess.run(
        ["git", *args], capture_output=True, text=True, encoding="utf-8", cwd=ROOT, check=False
    )
    if done.returncode != 0:
        raise FileNotFoundError(f"git {' '.join(args)}: {done.stderr.strip() or 'failed'}")
    return done.stdout


def read_at_tag(tag: str, relpath: str) -> str:
    """``git show <tag>:<path>`` -- the metadata as the tagged tree states it."""
    return _git("show", f"{tag}:{relpath}")


def date_of_tag(tag: str) -> str:
    """The tag's own date, YYYY-MM-DD: the tagger's for an annotated tag, else the commit's.

    A deposit dated by the tag is the same deposit whichever day it is made on;
    the release's published date, when the workflow has one, overrides this.
    """
    tagged = _git("for-each-ref", "--format=%(taggerdate:short)", f"refs/tags/{tag}").strip()
    if not tagged and not _git("tag", "--list", tag).strip():
        raise FileNotFoundError(f"no tag named {tag}")
    return tagged or _git("log", "-1", "--format=%cs", tag).strip()


def repository_from_citation(citation: dict[str, Any]) -> str:
    """``owner/name`` from CITATION.cff's ``repository-code`` URL."""
    url = str(citation.get("repository-code", "")).rstrip("/")
    prefix = "https://github.com/"
    if not url.startswith(prefix) or url.count("/") != 4:
        raise ValueError(f"CITATION.cff repository-code is not a GitHub repository URL: {url!r}")
    return url[len(prefix) :]


def concept_recid_from_citation(citation: dict[str, Any]) -> str | None:
    """The concept record id CITATION.cff cites, or None while it still cites the placeholder."""
    doi = str(citation.get("doi", "")).strip()
    if not doi or doi.endswith("PENDING"):
        return None
    prefix = "10.5281/zenodo."
    if not doi.startswith(prefix) or not doi[len(prefix) :].isdigit():
        raise ValueError(f"CITATION.cff doi is not a Zenodo concept DOI: {doi!r}")
    return doi[len(prefix) :]


def build_metadata(
    zenodo_json: dict[str, Any], tag: str, repository: str, publication_date: str
) -> dict[str, Any]:
    """Deposit metadata: ``.zenodo.json`` as the integration would read it, plus the release link."""
    metadata = dict(zenodo_json)
    missing = [key for key in REQUIRED_METADATA if not metadata.get(key)]
    if missing:
        raise ValueError(f".zenodo.json at {tag} lacks {', '.join(missing)}, which Zenodo requires")
    declared = str(metadata.get("version", ""))
    if declared != tag:
        raise ValueError(
            f".zenodo.json at {tag} declares version {declared!r}; refusing to archive it as {tag}"
        )
    metadata["publication_date"] = publication_date
    # Zenodo's licence vocabulary ids are lowercase (`agpl-3.0-or-later`); the
    # integration normalised the SPDX spelling in .zenodo.json, this sends the id.
    if "license" in metadata:
        metadata["license"] = str(metadata["license"]).lower()
    release_link = {
        "identifier": f"https://github.com/{repository}/tree/{tag}",
        "relation": "isSupplementTo",
        "resource_type": "software",
    }
    related = [dict(item) for item in metadata.get("related_identifiers", [])]
    if not any(item.get("identifier") == release_link["identifier"] for item in related):
        related.append(release_link)
    metadata["related_identifiers"] = related
    return metadata


def download_archive(
    repository: str, tag: str, into: Path, session: requests.Session | None = None
) -> Path:
    """GitHub's zipball of the tag -- the archive the integration would have deposited."""
    name = f"{repository.split('/')[1]}-{tag}.zip"
    target = into / name
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "bindsight-zenodo-deposit/1"}
    gh_token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if gh_token:
        headers["Authorization"] = f"Bearer {gh_token}"
    url = f"https://api.github.com/repos/{repository}/zipball/{tag}"
    http = session if session is not None else requests.Session()
    response = http.request("GET", url, headers=headers, timeout=300, allow_redirects=True)
    if response.status_code != 200:
        raise ArchiveError(f"GitHub answered HTTP {response.status_code} for the zipball of {tag}")
    target.write_bytes(response.content)
    return target


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --- The deposit itself ---------------------------------------------------------


@dataclass
class Outcome:
    deposition_id: int
    concept_recid: str | None
    draft_url: str
    published: bool
    doi: str | None
    concept_doi: str | None
    archive: str
    archive_sha256: str
    reused_draft: bool
    new_version_of: int | None


def _same_release(
    deposition: dict[str, Any], title: str, version: str, concept_recid: str | None
) -> bool:
    metadata = deposition.get("metadata") or {}
    if str(metadata.get("title")) != title or str(metadata.get("version")) != version:
        return False
    # Once the lineage is known, a match outside it is a different record.
    return concept_recid is None or str(deposition.get("conceptrecid")) == concept_recid


def deposit(
    client: Zenodo,
    *,
    tag: str,
    metadata: dict[str, Any],
    concept_recid: str | None,
    archive: Path,
    publish: bool,
) -> Outcome:
    title = str(metadata["title"])
    published = [
        d
        for d in client.list_depositions("published")
        if _same_release(d, title, tag, concept_recid)
    ]
    if published:
        record = published[0]
        published_doi = str((record.get("metadata") or {}).get("doi") or record.get("doi") or "?")
        raise AlreadyArchived(
            f"{tag} is already published on Zenodo as {published_doi}; nothing to do"
        )

    drafts = [
        d for d in client.list_depositions("draft") if _same_release(d, title, tag, concept_recid)
    ]
    new_version_of: int | None = None
    created_here = False
    if drafts:
        if len(drafts) > 1:
            ignored = ", ".join(str(d["id"]) for d in drafts[1:])
            print(
                f"warning: {len(drafts)} drafts of {tag} exist; using {drafts[0]['id']}, "
                f"leaving {ignored} for you to delete",
                file=sys.stderr,
            )
        draft = client.get_deposition(int(drafts[0]["id"]))
        reused = True
    elif concept_recid is not None:
        latest = client.latest_record(concept_recid)
        new_version_of = int(latest["id"])
        draft = client.new_version(new_version_of)
        created_here = True
        reused = False
    else:
        draft = client.create_deposition(metadata)
        created_here = True
        reused = False

    deposition_id = int(draft["id"])
    try:
        client.update_metadata(deposition_id, metadata)
        # Files: exactly one, the tag's archive. A reused draft may carry a
        # previous upload and a new version inherits the previous version's,
        # so everything already there goes first.
        for existing_file in client.list_files(deposition_id):
            client.delete_file(deposition_id, str(existing_file["id"]))
        bucket = str(draft["links"]["bucket"])
        client.upload(bucket, archive.name, archive)
    except Exception:
        if created_here:
            # Leave nothing behind that the next run could neither find nor reuse.
            try:
                client.delete_deposition(deposition_id)
                print(f"deleted the draft {deposition_id} this run created", file=sys.stderr)
            except (ZenodoError, requests.RequestException) as cleanup:
                print(
                    f"could not delete draft {deposition_id} after the failure: {cleanup}",
                    file=sys.stderr,
                )
        raise

    draft_url = str(draft["links"].get("html") or f"{client.base_url}/deposit/{deposition_id}")
    doi: str | None = None
    concept_doi: str | None = None
    if publish:
        record = client.publish(deposition_id)
        doi = str(record.get("doi") or (record.get("metadata") or {}).get("doi") or "") or None
        concept_doi = str(record.get("conceptdoi") or "") or None
    lineage = draft.get("conceptrecid")
    return Outcome(
        deposition_id=deposition_id,
        concept_recid=str(lineage) if lineage else concept_recid,
        draft_url=draft_url,
        published=publish,
        doi=doi,
        concept_doi=concept_doi,
        archive=archive.name,
        archive_sha256=sha256_of(archive),
        reused_draft=reused,
        new_version_of=new_version_of,
    )


def _summary(outcome: Outcome, metadata: dict[str, Any], tag: str) -> str:
    lines = [
        f"tag: {tag}",
        f"title: {metadata['title']}",
        f"version: {metadata['version']}",
        f"publication_date: {metadata['publication_date']}",
        f"license: {metadata.get('license')}",
        "related_identifiers: "
        + ", ".join(
            f"{r['relation']} {r['identifier']}" for r in metadata.get("related_identifiers", [])
        ),
        f"archive: {outcome.archive} sha256={outcome.archive_sha256}",
        f"deposition: {outcome.deposition_id} "
        + ("(draft reused" if outcome.reused_draft else "(created")
        + (f", new version of record {outcome.new_version_of}" if outcome.new_version_of else "")
        + ")",
        f"concept: {outcome.concept_recid or 'new'}",
    ]
    if outcome.published:
        lines.append(f"published: doi={outcome.doi} concept_doi={outcome.concept_doi}")
    else:
        lines.append(f"draft, not published: {outcome.draft_url}")
    return "\n".join(lines)


def _github_outputs(outcome: Outcome) -> None:
    """Hand the identifiers to the workflow, when there is one."""
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write(f"deposition_id={outcome.deposition_id}\n")
            handle.write(f"doi={outcome.doi or ''}\n")
            handle.write(f"concept_doi={outcome.concept_doi or ''}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--tag", required=True, help="the release tag to archive, e.g. v0.3.1")
    parser.add_argument(
        "--publish",
        action="store_true",
        help="publish the deposition (permanent); the default leaves a draft",
    )
    parser.add_argument(
        "--date", default=None, help="publication date, YYYY-MM-DD (default: the tag's own date)"
    )
    parser.add_argument(
        "--archive",
        type=Path,
        default=None,
        help="use this archive instead of downloading GitHub's zipball",
    )
    parser.add_argument(
        "--sandbox", action="store_true", help=f"deposit on {SANDBOX} instead of {PRODUCTION}"
    )
    args = parser.parse_args(argv)

    token = os.environ.get("ZENODO_TOKEN", "").strip()
    if not token:
        print(
            "ZENODO_TOKEN is not set: a Zenodo personal access token with the deposit:write "
            "and deposit:actions scopes is required",
            file=sys.stderr,
        )
        return EXIT_CONFIG

    try:
        citation = yaml.safe_load(read_at_tag(args.tag, "CITATION.cff"))
        zenodo_json = json.loads(read_at_tag(args.tag, ".zenodo.json"))
        repository = repository_from_citation(citation)
        concept_recid = concept_recid_from_citation(citation)
        publication_date = args.date or date_of_tag(args.tag)
        metadata = build_metadata(zenodo_json, args.tag, repository, publication_date)
    except (FileNotFoundError, ValueError, KeyError) as exc:
        print(f"cannot archive {args.tag}: {exc}", file=sys.stderr)
        return EXIT_CONFIG

    client = Zenodo(token, SANDBOX if args.sandbox else PRODUCTION)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            archive = (
                args.archive
                if args.archive is not None
                else download_archive(repository, args.tag, Path(tmp))
            )
            if not archive.is_file():
                print(f"archive not found: {archive}", file=sys.stderr)
                return EXIT_CONFIG
            outcome = deposit(
                client,
                tag=args.tag,
                metadata=metadata,
                concept_recid=concept_recid,
                archive=archive,
                publish=args.publish,
            )
    except AlreadyArchived as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_ALREADY_ARCHIVED
    except ArchiveError as exc:
        print(f"no archive to deposit: {exc}", file=sys.stderr)
        return EXIT_NETWORK
    except ZenodoError as exc:
        print(f"Zenodo refused: {exc}", file=sys.stderr)
        return EXIT_API
    except requests.RequestException as exc:
        print(f"network failure: {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_NETWORK
    except KeyError as exc:
        print(f"Zenodo's answer lacked a field this script relies on: {exc}", file=sys.stderr)
        return EXIT_API

    summary = _summary(outcome, metadata, args.tag)
    print(summary)
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as handle:
            handle.write("### Zenodo deposit\n\n```\n" + summary + "\n```\n")
    _github_outputs(outcome)
    return 0


if __name__ == "__main__":
    sys.exit(main())

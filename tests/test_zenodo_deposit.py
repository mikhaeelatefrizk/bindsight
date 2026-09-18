# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""``scripts/zenodo_deposit.py`` archives a release without the GitHub–Zenodo
integration, which cannot see this repository object since the repository was
recreated on 2026-09-14 (Zenodo answers the release event with "The repository
does not exist" and refuses to enable the recreated repository).

What is checked here is the shape of the deposit, against a scripted stand-in
for Zenodo's API: the metadata is the tag's own ``.zenodo.json`` plus the link
to the tag, dated by the tag; the lineage is whatever ``CITATION.cff`` cites; a
dry run leaves a draft that the publishing run reuses; a draft the run created
is deleted again when a later call fails; a version already published is
refused, and only within the lineage once it is known; a later release becomes
a new version of the cited concept with the inherited file replaced; Zenodo's
field errors reach the operator; and the token never appears in anything
printed. The workflow that calls the script is read as text, because it is
the thing that decides whether an unarchived release is a red run or a green
one.

No DOI is written as a literal anywhere in this module: the DOI-agreement
guard in ``tests/test_docs_claims.py`` reads every ``.py`` file, and a fixture
that looked like a concept DOI would be one more identifier for it to find.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
import zipfile
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "zenodo_deposit.py"
WORKFLOW = REPO / ".github" / "workflows" / "zenodo.yml"

#: Assembled at runtime so the file itself never contains a DOI-shaped token.
DOI_PREFIX = "10.5281/" + "zenodo."
CONCEPT_RECID = "4242001"
PLACEHOLDER = DOI_PREFIX + "PENDING"
REPOSITORY = "mikhaeelatefrizk/bindsight"
TAG_DATE = "2026-09-18"


@pytest.fixture(scope="module")
def mod() -> Any:
    spec = importlib.util.spec_from_file_location("_zenodo_deposit", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["_zenodo_deposit"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def zenodo_json() -> dict[str, Any]:
    return dict(json.loads((REPO / ".zenodo.json").read_text(encoding="utf-8")))


@pytest.fixture(scope="module")
def citation() -> dict[str, Any]:
    return dict(yaml.safe_load((REPO / "CITATION.cff").read_text(encoding="utf-8")))


@pytest.fixture(scope="module")
def tag(zenodo_json: dict[str, Any]) -> str:
    """The tag the working tree's metadata describes, so the fixtures cannot go stale."""
    return str(zenodo_json["version"])


@pytest.fixture
def archive(tmp_path: Path, tag: str) -> Path:
    path = tmp_path / f"bindsight-{tag}.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("bindsight/README.md", "a release archive\n")
    return path


@pytest.fixture
def metadata(mod: Any, zenodo_json: dict[str, Any], tag: str) -> dict[str, Any]:
    return dict(mod.build_metadata(zenodo_json, tag, REPOSITORY, TAG_DATE))


class _Response:
    def __init__(self, status_code: int, payload: Any = None) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> Any:
        if self._payload is None:
            raise ValueError("no body")
        return self._payload


class FakeZenodo:
    """Enough of the deposit API to script the flows the script relies on.

    Every call is recorded as ``(method, path)`` so a test can assert what was
    and was not attempted. ``fail`` maps ``(method, path-suffix)`` to a scripted
    error response.
    """

    def __init__(self) -> None:
        self.headers: dict[str, str] = {}
        self.calls: list[tuple[str, str]] = []
        self.depositions: dict[int, dict[str, Any]] = {}
        self.files: dict[int, list[dict[str, Any]]] = {}
        self.uploads: list[str] = []
        self.published: list[int] = []
        self.deleted: list[int] = []
        self.fail: dict[tuple[str, str], _Response] = {}
        self.next_id = 900

    def add(self, deposition_id: int, **extra: Any) -> dict[str, Any]:
        base = "https://zenodo.test"
        deposition = {
            "id": deposition_id,
            "submitted": False,
            "metadata": {},
            "links": {
                "bucket": f"{base}/api/files/bucket-{deposition_id}",
                "html": f"{base}/deposit/{deposition_id}",
            },
        }
        deposition.update(extra)
        self.depositions[deposition_id] = deposition
        return deposition

    def request(self, method: str, url: str, **kwargs: Any) -> _Response:
        path = re.sub(r"^https?://[^/]+", "", url)
        self.calls.append((method, path))
        for (fail_method, suffix), response in self.fail.items():
            if method == fail_method and path.endswith(suffix):
                return response
        m_dep = re.fullmatch(r"/api/deposit/depositions/(\d+)", path)
        m_files = re.fullmatch(r"/api/deposit/depositions/(\d+)/files", path)
        m_file = re.fullmatch(r"/api/deposit/depositions/(\d+)/files/([^/]+)", path)
        m_action = re.fullmatch(r"/api/deposit/depositions/(\d+)/actions/(\w+)", path)
        m_bucket = re.fullmatch(r"/api/files/bucket-(\d+)/(.+)", path)

        if method == "GET" and path == "/api/deposit/depositions":
            wanted = kwargs.get("params", {}).get("status") == "published"
            return _Response(
                200, [d for d in self.depositions.values() if bool(d["submitted"]) == wanted]
            )
        if method == "POST" and path == "/api/deposit/depositions":
            self.next_id += 1
            created = self.add(self.next_id, metadata=dict(kwargs["json"]["metadata"]))
            return _Response(201, created)
        if method == "GET" and m_dep:
            return _Response(200, self.depositions[int(m_dep.group(1))])
        if method == "PUT" and m_dep:
            dep = self.depositions[int(m_dep.group(1))]
            dep["metadata"] = dict(kwargs["json"]["metadata"])
            return _Response(200, dep)
        if method == "DELETE" and m_dep:
            self.deleted.append(int(m_dep.group(1)))
            del self.depositions[int(m_dep.group(1))]
            return _Response(204)
        if method == "GET" and path == "/api/records":
            concept = re.sub(r'^conceptrecid:"(.*)"$', r"\1", kwargs["params"]["q"])
            hits = [{"id": 55, "conceptrecid": concept, "metadata": {"version": "older"}}]
            return _Response(200, {"hits": {"hits": hits, "total": 1}})
        if method == "POST" and m_action and m_action.group(2) == "newversion":
            self.next_id += 1
            new_id = self.next_id
            self.add(new_id, conceptrecid=CONCEPT_RECID)
            # A new version inherits the previous version's file.
            self.files[new_id] = [{"id": "inherited-file", "filename": "old.zip"}]
            return _Response(
                201,
                {
                    "links": {
                        "latest_draft": f"https://zenodo.test/api/deposit/depositions/{new_id}"
                    }
                },
            )
        if method == "POST" and m_action and m_action.group(2) == "publish":
            dep_id = int(m_action.group(1))
            self.published.append(dep_id)
            dep = self.depositions[dep_id]
            dep["submitted"] = True
            return _Response(
                202, {"doi": DOI_PREFIX + str(dep_id), "conceptdoi": DOI_PREFIX + CONCEPT_RECID}
            )
        if method == "GET" and m_files:
            return _Response(200, list(self.files.get(int(m_files.group(1)), [])))
        if method == "DELETE" and m_file:
            dep_id = int(m_file.group(1))
            self.files[dep_id] = [
                f for f in self.files.get(dep_id, []) if f["id"] != m_file.group(2)
            ]
            return _Response(204)
        if method == "PUT" and m_bucket:
            dep_id = int(m_bucket.group(1))
            self.files.setdefault(dep_id, []).append(
                {"id": f"file-{len(self.uploads)}", "filename": m_bucket.group(2)}
            )
            self.uploads.append(m_bucket.group(2))
            return _Response(201, {"key": m_bucket.group(2)})
        return _Response(404, {"message": f"unscripted {method} {path}", "errors": []})


def _client(mod: Any, fake: FakeZenodo) -> Any:
    return mod.Zenodo("token-value-that-must-not-leak", "https://zenodo.test", session=fake)


def _deposit(mod: Any, fake: FakeZenodo, **kwargs: Any) -> Any:
    return mod.deposit(_client(mod, fake), **kwargs)


# --- Metadata and lineage -----------------------------------------------------------


def test_metadata_is_the_tags_zenodo_json_plus_the_release_link(
    mod: Any, zenodo_json: dict[str, Any], tag: str, metadata: dict[str, Any]
) -> None:
    assert metadata["title"] == zenodo_json["title"]
    assert metadata["version"] == tag
    assert metadata["publication_date"] == TAG_DATE
    # Zenodo's vocabulary id for the licence is lowercase; the SPDX spelling in
    # .zenodo.json is what the integration normalised, this sends the id.
    assert metadata["license"] == str(zenodo_json["license"]).lower()
    relations = {(r["relation"], r["identifier"]) for r in metadata["related_identifiers"]}
    assert ("isSupplementTo", f"https://github.com/{REPOSITORY}/tree/{tag}") in relations
    # Whatever .zenodo.json declares (the `continues` link to the previous
    # lineage, at the time of writing) survives untouched.
    for item in zenodo_json.get("related_identifiers", []):
        assert (item["relation"], item["identifier"]) in relations
    # Idempotent: building twice does not duplicate the release link.
    again = mod.build_metadata(metadata, tag, REPOSITORY, TAG_DATE)
    assert len(again["related_identifiers"]) == len(metadata["related_identifiers"])


def test_a_tag_the_metadata_does_not_declare_is_refused(
    mod: Any, zenodo_json: dict[str, Any]
) -> None:
    """Archiving v9.9.9 with metadata that says another version would publish a lie."""
    with pytest.raises(ValueError, match="declares version"):
        mod.build_metadata(zenodo_json, "v9.9.9", REPOSITORY, TAG_DATE)


def test_metadata_missing_what_zenodo_requires_is_refused_before_anything_is_sent(
    mod: Any, zenodo_json: dict[str, Any], tag: str
) -> None:
    """A deposit Zenodo would reject is refused here, with the field named, as a
    configuration error rather than a traceback."""
    incomplete = {k: v for k, v in zenodo_json.items() if k != "creators"}
    with pytest.raises(ValueError, match="lacks creators"):
        mod.build_metadata(incomplete, tag, REPOSITORY, TAG_DATE)


def test_the_lineage_is_whatever_citation_cff_cites(mod: Any, citation: dict[str, Any]) -> None:
    assert mod.repository_from_citation(citation) == REPOSITORY
    assert mod.concept_recid_from_citation({"doi": PLACEHOLDER}) is None
    assert mod.concept_recid_from_citation({}) is None
    assert mod.concept_recid_from_citation({"doi": DOI_PREFIX + CONCEPT_RECID}) == CONCEPT_RECID
    with pytest.raises(ValueError, match="not a Zenodo concept DOI"):
        mod.concept_recid_from_citation({"doi": "10.1000/something-else"})


def test_the_deposit_is_dated_by_the_tag(mod: Any, tag: str) -> None:
    """Two runs on different days must make the same deposit; the wall clock is not an input."""
    date = mod.date_of_tag(tag)
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", date), date
    with pytest.raises(FileNotFoundError):
        mod.date_of_tag("v0.0.0-no-such-tag")


# --- The deposit flows ----------------------------------------------------------------


def test_the_first_deposit_starts_a_new_concept_and_stops_at_a_draft(
    mod: Any, tag: str, metadata: dict[str, Any], archive: Path
) -> None:
    fake = FakeZenodo()
    outcome = _deposit(
        mod, fake, tag=tag, metadata=metadata, concept_recid=None, archive=archive, publish=False
    )
    assert ("POST", "/api/deposit/depositions") in fake.calls
    assert not any(p.endswith("/actions/newversion") for _, p in fake.calls)
    assert not any(p.endswith("/actions/publish") for _, p in fake.calls)
    assert fake.uploads == [archive.name]
    assert fake.depositions[outcome.deposition_id]["metadata"]["version"] == tag
    assert outcome.published is False
    assert outcome.doi is None
    assert outcome.reused_draft is False
    assert outcome.archive_sha256 == mod.sha256_of(archive)
    assert fake.deleted == []


def test_the_draft_is_created_with_its_metadata_in_one_call(
    mod: Any, tag: str, metadata: dict[str, Any], archive: Path
) -> None:
    """A draft that exists before it has a title is one the next run cannot recognise."""
    fake = FakeZenodo()
    _deposit(
        mod, fake, tag=tag, metadata=metadata, concept_recid=None, archive=archive, publish=False
    )
    created = fake.depositions[fake.next_id]
    assert created["metadata"]["title"] == metadata["title"]
    assert created["metadata"]["version"] == tag


def test_publish_reuses_the_draft_a_dry_run_left(
    mod: Any, tag: str, metadata: dict[str, Any], archive: Path
) -> None:
    """Otherwise a dry run followed by the real run would leave two records."""
    fake = FakeZenodo()
    draft = fake.add(501, metadata={"title": metadata["title"], "version": tag})
    fake.files[501] = [{"id": "stale-upload", "filename": "from-the-dry-run.zip"}]
    outcome = _deposit(
        mod, fake, tag=tag, metadata=metadata, concept_recid=None, archive=archive, publish=True
    )
    assert outcome.deposition_id == draft["id"]
    assert outcome.reused_draft is True
    assert ("POST", "/api/deposit/depositions") not in fake.calls
    assert ("DELETE", "/api/deposit/depositions/501/files/stale-upload") in fake.calls
    assert fake.uploads == [archive.name]
    assert fake.published == [501]
    assert outcome.doi == DOI_PREFIX + "501"
    assert outcome.concept_doi == DOI_PREFIX + CONCEPT_RECID


def test_drafts_are_asked_for_by_status(
    mod: Any, tag: str, metadata: dict[str, Any], archive: Path
) -> None:
    """Zenodo's listing takes an explicit status; a listing that omitted drafts would
    make every publish run create a second record."""
    fake = FakeZenodo()
    _deposit(
        mod, fake, tag=tag, metadata=metadata, concept_recid=None, archive=archive, publish=False
    )
    assert fake.calls[:2] == [
        ("GET", "/api/deposit/depositions"),
        ("GET", "/api/deposit/depositions"),
    ]


def test_a_version_already_published_is_refused(
    mod: Any, tag: str, metadata: dict[str, Any], archive: Path
) -> None:
    fake = FakeZenodo()
    fake.add(
        700,
        submitted=True,
        metadata={"title": metadata["title"], "version": tag, "doi": DOI_PREFIX + "700"},
    )
    with pytest.raises(mod.AlreadyArchived, match="already published"):
        _deposit(
            mod, fake, tag=tag, metadata=metadata, concept_recid=None, archive=archive, publish=True
        )
    assert fake.uploads == []
    assert fake.published == []


def test_the_published_check_is_scoped_to_the_lineage_once_it_is_known(
    mod: Any, tag: str, metadata: dict[str, Any], archive: Path
) -> None:
    """A record with the same title and version under another concept is not this one."""
    fake = FakeZenodo()
    fake.add(
        701,
        submitted=True,
        conceptrecid="1111111",
        metadata={"title": metadata["title"], "version": tag},
    )
    outcome = _deposit(
        mod,
        fake,
        tag=tag,
        metadata=metadata,
        concept_recid=CONCEPT_RECID,
        archive=archive,
        publish=False,
    )
    assert outcome.new_version_of == 55
    assert outcome.concept_recid == CONCEPT_RECID


def test_later_releases_are_new_versions_of_the_cited_concept(
    mod: Any, tag: str, metadata: dict[str, Any], archive: Path
) -> None:
    fake = FakeZenodo()
    outcome = _deposit(
        mod,
        fake,
        tag=tag,
        metadata=metadata,
        concept_recid=CONCEPT_RECID,
        archive=archive,
        publish=True,
    )
    assert ("GET", "/api/records") in fake.calls
    assert ("POST", "/api/deposit/depositions/55/actions/newversion") in fake.calls
    assert ("POST", "/api/deposit/depositions") not in fake.calls
    assert outcome.new_version_of == 55
    # The inherited file is gone and the tag's archive is the only file.
    assert [f["filename"] for f in fake.files[outcome.deposition_id]] == [archive.name]
    assert fake.published == [outcome.deposition_id]


def test_a_draft_this_run_created_is_deleted_when_a_later_call_fails(
    mod: Any, tag: str, metadata: dict[str, Any], archive: Path
) -> None:
    """A half-made draft with the right title would be reused; one without it would
    be invisible to the next run and pile up. Either way it must not survive."""
    fake = FakeZenodo()
    fake.fail[("PUT", f"/api/files/bucket-901/{archive.name}")] = _Response(
        500, {"message": "storage unavailable", "errors": []}
    )
    with pytest.raises(mod.ZenodoError, match="storage unavailable"):
        _deposit(
            mod, fake, tag=tag, metadata=metadata, concept_recid=None, archive=archive, publish=True
        )
    assert fake.deleted == [901]
    assert 901 not in fake.depositions
    assert fake.published == []


def test_a_reused_draft_is_not_deleted_when_a_later_call_fails(
    mod: Any, tag: str, metadata: dict[str, Any], archive: Path
) -> None:
    """The dry run's draft is the operator's; a failed publish run leaves it for them."""
    fake = FakeZenodo()
    fake.add(502, metadata={"title": metadata["title"], "version": tag})
    fake.fail[("PUT", f"/api/files/bucket-502/{archive.name}")] = _Response(
        500, {"message": "storage unavailable", "errors": []}
    )
    with pytest.raises(mod.ZenodoError):
        _deposit(
            mod, fake, tag=tag, metadata=metadata, concept_recid=None, archive=archive, publish=True
        )
    assert fake.deleted == []
    assert 502 in fake.depositions


# --- The command --------------------------------------------------------------------


def _run_main(
    mod: Any,
    monkeypatch: pytest.MonkeyPatch,
    fake: FakeZenodo,
    argv: list[str],
    *,
    token: str | None,
) -> int:
    def read_at_tag(_tag: str, relpath: str) -> str:
        return (REPO / relpath).read_text(encoding="utf-8")

    monkeypatch.setattr(mod, "read_at_tag", read_at_tag)
    monkeypatch.setattr(mod, "date_of_tag", lambda _tag: TAG_DATE)
    real = mod.Zenodo

    class Injected(real):  # type: ignore[misc,valid-type]
        def __init__(self, token: str, base_url: str = mod.PRODUCTION, session: Any = None) -> None:
            super().__init__(token, base_url, session=fake)

    monkeypatch.setattr(mod, "Zenodo", Injected)
    if token is None:
        monkeypatch.delenv("ZENODO_TOKEN", raising=False)
    else:
        monkeypatch.setenv("ZENODO_TOKEN", token)
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    return int(mod.main(argv))


def test_without_a_token_nothing_is_attempted(
    mod: Any,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tag: str,
    archive: Path,
) -> None:
    fake = FakeZenodo()
    code = _run_main(mod, monkeypatch, fake, ["--tag", tag, "--archive", str(archive)], token=None)
    assert code == mod.EXIT_CONFIG
    assert "ZENODO_TOKEN" in capsys.readouterr().err
    assert fake.calls == []


def test_a_dry_run_with_the_real_metadata_leaves_a_draft_and_names_it(
    mod: Any,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tag: str,
    archive: Path,
) -> None:
    fake = FakeZenodo()
    code = _run_main(mod, monkeypatch, fake, ["--tag", tag, "--archive", str(archive)], token="tok")
    out = capsys.readouterr().out
    assert code == 0, out
    assert "draft, not published" in out
    assert f"version: {tag}" in out
    assert f"publication_date: {TAG_DATE}" in out
    assert f"isSupplementTo https://github.com/{REPOSITORY}/tree/" in out
    assert fake.published == []


def test_the_token_never_reaches_stdout(
    mod: Any,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tag: str,
    archive: Path,
) -> None:
    secret = "zenodo-secret-token-9f3c"
    fake = FakeZenodo()
    code = _run_main(
        mod, monkeypatch, fake, ["--tag", tag, "--archive", str(archive), "--publish"], token=secret
    )
    captured = capsys.readouterr()
    assert code == 0, captured.err
    assert secret not in captured.out
    assert secret not in captured.err
    assert fake.headers["Authorization"] == f"Bearer {secret}"


def test_an_already_archived_tag_exits_with_its_own_code(
    mod: Any,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tag: str,
    archive: Path,
    zenodo_json: dict[str, Any],
) -> None:
    fake = FakeZenodo()
    fake.add(800, submitted=True, metadata={"title": zenodo_json["title"], "version": tag})
    code = _run_main(mod, monkeypatch, fake, ["--tag", tag, "--archive", str(archive)], token="tok")
    assert code == mod.EXIT_ALREADY_ARCHIVED
    assert "already published" in capsys.readouterr().err


def test_zenodos_field_errors_reach_the_operator(
    mod: Any,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tag: str,
    archive: Path,
) -> None:
    """A rejected metadata field must be named in the log, not swallowed as 'HTTP 400'."""
    fake = FakeZenodo()
    fake.fail[("POST", "/api/deposit/depositions")] = _Response(
        400,
        {
            "message": "Validation error.",
            "errors": [{"field": "metadata.license", "message": "Not a valid choice."}],
        },
    )
    code = _run_main(mod, monkeypatch, fake, ["--tag", tag, "--archive", str(archive)], token="tok")
    err = capsys.readouterr().err
    assert code == mod.EXIT_API
    assert "metadata.license" in err
    assert "Not a valid choice" in err


# --- The workflow that calls it ---------------------------------------------------


def test_the_workflow_archives_every_published_release_and_fails_without_the_token() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "scripts/zenodo_deposit.py" in text
    assert "secrets.ZENODO_TOKEN" in text
    assert re.search(r"release:\s*\n\s*types:\s*\[published\]", text), (
        "must run on every published release"
    )
    assert "fetch-tags: true" in text, "the script reads the tag's tree with git show"
    assert "continue-on-error" not in text, "an unarchived release must be a red run"
    assert not re.search(r"if:.*ZENODO_TOKEN", text), (
        "the token gates nothing; its absence fails the job"
    )
    assert "--publish" in text, "a manual run can stop at a draft"
    assert "inputs.publish" in text, "a manual run can stop at a draft"


def test_the_workflow_installs_only_what_the_script_imports() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    script = SCRIPT.read_text(encoding="utf-8")
    for dist, module in (("requests", "import requests"), ("pyyaml", "import yaml")):
        assert module in script
        assert dist in text

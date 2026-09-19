# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""RO-Crate exporter.

Bundles a finished bindsight run into a single ``.crate.zip`` that is
recognized by research data repositories, FAIR Digital Object Frameworks, and
the broader Research Object Crate ecosystem.

We emit the lightweight RO-Crate 1.1 metadata format
(https://www.researchobject.org/ro-crate/1.1/) — a single ``ro-crate-metadata.json``
at the crate root that catalogues every other file, plus a ``software.bib``
listing the upstream tools used. This is intentionally minimal: implementing
the full ``ro-crate-py`` library as a runtime dependency adds several
hundred KB of code for one JSON file.

Every payload file in the crate is byte-identical for runs with the same
manifest; the only varying field is ``datePublished`` in the metadata, which
records when the crate was packaged rather than anything about the run. So
this is a reproducibility primitive — depositing the crate in an archive that
mints identifiers gives one anybody can dereference to pull the exact artifacts
we packaged. Which archive is the depositor's choice; the crate names none.
"""

from __future__ import annotations

import json
import logging
import zipfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from bindsight import __version__

LOG = logging.getLogger(__name__)

RO_CRATE_CONTEXT = "https://w3id.org/ro/crate/1.1/context"


def export_ro_crate(
    run_dir: Path | str,
    out_path: Path | str | None = None,
) -> Path:
    """Bundle ``run_dir`` into an RO-Crate zip suitable for deposit.

    Args:
        run_dir: directory produced by ``bindsight discover`` (and optionally
            ``design``, ``validate``, ``rank``, ``report``).
        out_path: destination zip. Defaults to ``<run_dir>.crate.zip``.

    Returns:
        Path to the written zip.
    """
    run = Path(run_dir)
    if not run.exists():
        raise FileNotFoundError(f"run directory not found: {run}")
    out = Path(out_path) if out_path else run.parent / f"{run.name}.crate.zip"

    files = _collect_files(run)
    external = _external_inputs(run)
    metadata = _build_metadata(run, files, external)
    bibtex = _build_software_bib(run)

    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        # Required RO-Crate metadata file
        zf.writestr("ro-crate-metadata.json", json.dumps(metadata, indent=2))
        # Citation BibTeX
        zf.writestr("software.bib", bibtex)
        # Every artifact, preserving relative paths under the run root
        for f in files:
            arcname = f.relative_to(run).as_posix()
            zf.write(f, arcname)
        # The cohort the run consumed, which lives outside the run directory.
        for arcname, src in external:
            zf.write(src, arcname)

    LOG.info(
        "wrote RO-Crate: %s (%d run artifacts, %d carried-in inputs)",
        out,
        len(files),
        len(external),
    )
    return out


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
#: Single files, in canonical order.
_PIPELINE_FILES = (
    "config.yaml",
    # The cohort itself. These are the only artifacts carrying TCGA case and
    # sample barcodes, so without them an exported crate cannot answer the one
    # question the provenance chain exists to answer: which patients did this
    # binder come from? A crate that stops at the DEG table documents an
    # analysis, not its origin.
    "counts.tsv.gz",
    "counts.tsv",
    "design.tsv",
    "provenance.json",
    "deg/results.parquet",
    "targets/candidates.parquet",
    "epitopes/epitopes.parquet",
    "taxonomy/failure_taxonomy.parquet",
    "design/results.tar.gz",
    "design/metrics.jsonl",
    # Whether the ESM-2 pre-screen actually applied. It fails open, so a run
    # whose embedding died carries every design under a cache key that says it
    # kept the top k; this file is the only thing that distinguishes the two.
    "design/prescreen.txt",
    "validate/validated.parquet",
    "rank/ranking.parquet",
    "report.html",
    "run_manifest.jsonld",
)

#: Directory trees included wholesale. ``structures/`` is what makes the crate
#: self-contained — candidate and epitope tables reference those files, and
#: without them every structure reference in an exported crate dangles.
#: ``design/`` and ``validate/`` subtrees carry the per-target archives and the
#: per-binder validator output that the flat allowlist silently dropped.
_PIPELINE_TREES = (
    "structures",
    "design/_targets",
    "validate",
)

#: Skipped inside `_PIPELINE_TREES`; already listed individually above.
_TREE_EXCLUDE = frozenset({"validated.parquet"})


def _collect_files(run: Path) -> list[Path]:
    """Return the per-run artifacts to include in the crate, in canonical order.

    Zero-byte files are skipped: several stages write empty placeholders, and a
    crate should describe what a run produced, not what it reserved space for.
    """
    files: list[Path] = []
    seen: set[Path] = set()

    def _add(p: Path) -> None:
        if p in seen or not p.is_file():
            return
        try:
            if p.stat().st_size <= 0:
                return
        except OSError:  # pragma: no cover - race with a concurrent write
            return
        seen.add(p)
        files.append(p)

    for rel in _PIPELINE_FILES:
        _add(run / rel)

    for tree in _PIPELINE_TREES:
        base = run / tree
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*")):
            if p.name not in _TREE_EXCLUDE:
                _add(p)

    return files


def _resolve_recorded(path_str: str, run: Path) -> Path | None:
    """Resolve a manifest-recorded path to a file on this machine.

    Recorded paths are relative to the working directory the run was launched
    from, which is typically the repository root rather than the run directory,
    and they are written in the launching platform's separator style. So try the
    run directory first, then the working directory, then each ancestor. The run
    comes first because a run-relative name like ``counts.tsv`` must not be
    satisfied by an unrelated file of the same name sitting in the caller's
    working directory.

    Args:
        path_str: the path as the manifest recorded it.
        run: the run directory, used as the base for the upward search.

    Returns:
        The resolved file, or None if nothing matching exists.
    """
    raw = Path(_posix_key(path_str))
    if raw.is_absolute():
        return raw if raw.is_file() else None
    for base in (run, Path.cwd(), *run.parents):
        candidate = base / raw
        if candidate.is_file():
            return candidate
    return None


def _external_inputs(run: Path) -> list[tuple[str, Path]]:
    """Cohort inputs the run consumed from outside its own directory.

    The allowlist above names ``counts.tsv.gz`` and ``design.tsv`` because they
    are the only artifacts carrying TCGA case and sample barcodes — without them
    a crate cannot answer which patients a binder came from. But naming them was
    not enough: a run configured with ``inputs.counts`` pointing anywhere else
    keeps them outside the run directory, so the allowlist matched nothing and
    the crate shipped without a cohort. That was true of the provenance run this
    was written for; the exported crate stopped at the DEG table.

    The manifest already records every stage input by path and by sha256, so it
    is the authoritative list. Anything it names that resolves outside the run
    is carried in under ``inputs/``, keeping its basename so the recorded digest
    still identifies it. A ``provenance.json`` sitting beside a carried-in input
    comes too: it is the cohort's own record of how the sample set was
    assembled, and no stage declares it as an input.

    Args:
        run: the run directory.

    Returns:
        ``(arcname, source)`` pairs, in manifest order, deduplicated.
    """
    manifest_path = run / "run_manifest.jsonld"
    if not manifest_path.is_file():
        return []
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        LOG.warning("could not read %s (%s); the crate will carry no inputs", manifest_path, e)
        return []

    run_resolved = run.resolve()
    out: list[tuple[str, Path]] = []
    taken: set[str] = set()
    seen: set[Path] = set()
    for stage in manifest.get("stages", []) or []:
        for ref in stage.get("inputs") or []:
            recorded = ref.get("path")
            if not recorded:
                continue
            src = _resolve_recorded(str(recorded), run)
            if src is None:
                LOG.warning(
                    "input %s recorded by stage %s is not on this machine, so the "
                    "crate cannot carry it",
                    recorded,
                    stage.get("name", "?"),
                )
                continue
            src = src.resolve()
            if src in seen or src.is_relative_to(run_resolved):
                continue  # already inside the run, so the allowlist has it
            seen.add(src)
            arcname = f"inputs/{src.name}"
            if arcname in taken:  # two inputs sharing a basename
                arcname = f"inputs/{stage.get('name', 'stage')}-{src.name}"
            taken.add(arcname)
            out.append((arcname, src))

    # The cohort's own provenance document travels with the cohort. It records
    # how the sample set was assembled — the GDC project, the workflow, the
    # retrieval date, the cases requested against those actually obtained —
    # which is what lets a reader rebuild the cohort rather than merely read it.
    # It is not a stage input, so nothing in the manifest points at it.
    for cohort_dir in dict.fromkeys(src.parent for _, src in list(out)):
        doc = cohort_dir / "provenance.json"
        if not doc.is_file() or doc.resolve() in seen:
            continue
        seen.add(doc.resolve())
        arcname = "inputs/provenance.json"
        if arcname in taken:
            arcname = f"inputs/{cohort_dir.name}-provenance.json"
        taken.add(arcname)
        out.append((arcname, doc))
    return out


def _manifest_digests(manifest: dict[str, Any]) -> dict[str, str]:
    """Map run-relative artifact path -> sha256, as recorded in the manifest.

    The manifest already carries a verified digest for every declared input and
    output; the crate simply never carried them across, so a reader had no way
    to check integrity. Paths are normalised to their run-relative form because
    older manifests recorded absolute ones.
    """
    digests: dict[str, str] = {}
    for stage in manifest.get("stages", []) or []:
        for ref in [*(stage.get("inputs") or []), *(stage.get("outputs") or [])]:
            path = ref.get("path")
            sha = ref.get("sha256")
            if path and sha:
                # Keyed by the run-relative path, which is what the docstring
                # above promises. Keying on the basename made two files called
                # ``metrics.jsonl`` in different stages one entry, and left every
                # file whose basename the manifest did not record undigested.
                #
                # Separators are normalised the same way ``_resolve_recorded``
                # normalises them. ``Path(path).as_posix()`` is not enough: on
                # POSIX a backslash is an ordinary filename character, so a
                # manifest written on Windows -- which records
                # ``runs\join\deg\results.parquet`` -- produced a single-segment
                # key that no lookup in ``_digest_for`` could match. Every
                # ``sha256`` silently vanished from crates exported on Linux and
                # macOS, leaving the archive deposited as a run's integrity
                # record with no integrity record in it. The two functions
                # disagreeing about this is the whole defect.
                digests[_posix_key(path)] = sha
    return digests


def _posix_key(path_str: str) -> str:
    """A recorded path as a POSIX key, whatever platform recorded it.

    ``_resolve_recorded`` and ``_manifest_digests`` both consume manifest paths
    and must agree on what a separator is. They did not: one replaced
    backslashes, the other relied on ``Path.as_posix()``, which only converts
    separators on the platform whose separator they are. Both now call this.
    """
    return PurePosixPath(path_str.replace("\\", "/")).as_posix()


def _digest_for(digests: dict[str, str], wanted: str) -> str | None:
    """Find an artifact's recorded digest, precisely where possible.

    Three steps, narrowing to broadening:

    1. The exact run-relative path, which is what the map is keyed by.
    2. A recorded path that ends with it — manifests written before paths were
       normalised stored repository-relative ones such as
       ``runs/join/deg/results.parquet``.
    3. The basename, but **only when exactly one recorded path has it**. This map
       used to be keyed by basename outright, which silently merged two files
       called ``metrics.jsonl`` into one entry and attached whichever digest won
       to both. Requiring uniqueness keeps the convenience without the collision:
       an ambiguous basename yields no digest rather than a wrong one.
    """
    exact = digests.get(wanted)
    if exact is not None:
        return exact

    suffix_matches = [v for k, v in digests.items() if k.endswith("/" + wanted)]
    if len(suffix_matches) == 1:
        return suffix_matches[0]

    base = PurePosixPath(wanted).name
    by_base = [v for k, v in digests.items() if PurePosixPath(k).name == base]
    if len(by_base) == 1:
        return by_base[0]
    return None


def _build_metadata(
    run: Path, files: list[Path], external: list[tuple[str, Path]] | None = None
) -> dict[str, Any]:
    """Construct the RO-Crate 1.1 metadata document.

    Args:
        run: the run directory.
        files: artifacts inside the run, named by their run-relative path.
        external: ``(arcname, source)`` inputs carried in from outside it.
    """
    manifest_path = run / "run_manifest.jsonld"
    manifest = {}
    if manifest_path.exists():
        try:
            body = json.loads(manifest_path.read_text(encoding="utf-8"))
            body.pop("@context", None)
            manifest = body
        except (json.JSONDecodeError, OSError) as e:
            # `_external_inputs` logs this exact failure; this swallowed it with
            # a bare `pass`. The crate then shipped with an empty run id and no
            # sha256 on any file, and a consumer preparing a deposit could not
            # tell that from a run which genuinely recorded no digests.
            LOG.warning(
                "could not read %s (%s); the crate will carry no run identity and no file digests",
                manifest_path,
                e,
            )

    digests = _manifest_digests(manifest)
    file_entries: list[dict[str, object]] = []
    for p in files:
        entry: dict[str, object] = {
            "@id": p.relative_to(run).as_posix(),
            "@type": "File",
            "name": p.name,
            "contentSize": p.stat().st_size,
        }
        sha = _digest_for(digests, p.relative_to(run).as_posix())
        if sha:
            # schema.org has no sha256 term; this is the RO-Crate convention.
            entry["sha256"] = sha
        file_entries.append(entry)

    for arcname, src in external or []:
        input_entry: dict[str, object] = {
            "@id": arcname,
            "@type": "File",
            "name": src.name,
            "contentSize": src.stat().st_size,
            "description": (
                "Cohort input consumed by this run, carried into the crate from "
                "outside the run directory so the provenance chain reaches the "
                "patient barcodes it started from."
            ),
        }
        # A carried-in input lives outside the run, so it has no run-relative
        # path; the manifest recorded it however the run was launched. The
        # resolver's unambiguous-basename fallback is what matches it.
        sha = _digest_for(digests, src.name)
        if sha:
            input_entry["sha256"] = sha
        file_entries.append(input_entry)

    return {
        "@context": RO_CRATE_CONTEXT,
        "@graph": [
            {
                "@id": "ro-crate-metadata.json",
                "@type": "CreativeWork",
                "conformsTo": {"@id": "https://w3id.org/ro/crate/1.1"},
                "about": {"@id": "./"},
            },
            {
                "@id": "./",
                "@type": "Dataset",
                "name": manifest.get("name") or run.name,
                "description": (
                    "bindsight run output: ranked de novo protein binder candidates "
                    "produced from RNA-seq counts, with full PROV-O provenance."
                ),
                "datePublished": datetime.now(UTC).strftime("%Y-%m-%d"),
                "creator": {
                    "@type": "SoftwareApplication",
                    "name": "bindsight",
                    "version": __version__,
                    "url": "https://github.com/mikhaeelatefrizk/bindsight",
                    "license": "AGPL-3.0-or-later",
                },
                # software.bib is packaged and described below, so it belongs
                # here too: a conforming RO-Crate reader walks hasPart, and a
                # file absent from it is a file the crate does not declare.
                "hasPart": [{"@id": e["@id"]} for e in file_entries] + [{"@id": "software.bib"}],
                "bindsight:run_id": manifest.get("run_id", ""),
            },
            *file_entries,
            {
                "@id": "software.bib",
                "@type": "File",
                "name": "software.bib",
                "encodingFormat": "application/x-bibtex",
                "description": "BibTeX for every upstream tool this run depended on.",
            },
        ],
    }


#: The upstream tools each bindsight wrapper actually runs, so the crate credits
#: them instead of the wrapper. Licences are the ones LICENSING.md records (its
#: header states the date the upstream LICENSE files were last re-verified);
#: repository URLs and pins come from :mod:`bindsight.runners.tools`, so a bumped
#: pin moves the citation with it rather than leaving it behind.
#:
#: This exists because the manifest records one ``ToolRef`` per stage and that
#: ref is the wrapper. Crediting BSD-3 RFdiffusion and MIT ProteinMPNN as
#: "bindsight.design.rfdiff_mpnn, AGPL-3.0-or-later" is wrong twice: it drops the
#: attribution those licences require, and it asserts terms over work that is not
#: bindsight's to license.
def _upstream_tools() -> dict[str, tuple[dict[str, str], ...]]:
    """Wrapper tool name -> the upstream tools it invokes."""
    from bindsight.runners import tools as T
    from bindsight.validate.boltz2 import PINNED_BOLTZ2_VERSION

    return {
        "bindsight.design.rfdiff_mpnn": (
            {
                "name": "RFdiffusion",
                "license": "BSD-3-Clause",
                "url": T.RFDIFF_REPO,
                "version": T.RFDIFF_COMMIT,
            },
            {
                "name": "ProteinMPNN",
                "license": "MIT",
                "url": T.PROTEINMPNN_REPO,
                "version": T.PROTEINMPNN_COMMIT,
            },
        ),
        "bindsight.design.bindcraft": (
            {
                "name": "BindCraft",
                "license": "MIT",
                "url": T.BINDCRAFT_REPO,
                "version": T.BINDCRAFT_COMMIT,
            },
        ),
        "bindsight.design.boltzgen": (
            {
                "name": "BoltzGen",
                "license": "MIT",
                "url": T.BOLTZGEN_REPO,
                "version": T.BOLTZGEN_COMMIT,
            },
        ),
        "bindsight.validate.boltz2": (
            {
                "name": "Boltz-2",
                "license": "MIT",
                "url": "https://github.com/jwohlwend/boltz",
                "version": PINNED_BOLTZ2_VERSION,
            },
        ),
        "bindsight.validate.chai1r": (
            {
                "name": "Chai-1r",
                "license": "Apache-2.0",
                "url": "https://github.com/chaidiscovery/chai-lab",
                "version": T.CHAI_PIP,
            },
        ),
        "bindsight.validate.af2_ig": (
            {
                "name": "dl_binder_design (AF2 initial guess)",
                "license": "Inherits AF2 weights restriction",
                "url": T.DL_BINDER_DESIGN_REPO,
                "version": T.DL_BINDER_DESIGN_COMMIT,
            },
        ),
    }


def _build_software_bib(run: Path) -> str:
    """Produce a BibTeX block citing every upstream tool used in the run.

    Reads tool entries from the manifest's ``stages[*].tool`` entries and
    emits a ``@software`` BibTeX entry per unique (tool, version, license).
    """
    manifest_path = run / "run_manifest.jsonld"
    if not manifest_path.exists():
        return _DEFAULT_BIBTEX
    try:
        body = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return _DEFAULT_BIBTEX

    seen: set[tuple[str, str]] = set()
    entries: list[str] = [
        "% Auto-generated by bindsight export. Cite the tools you actually used.",
        "",
    ]
    upstream = _upstream_tools()
    cited: list[dict[str, str]] = []
    for stage in body.get("stages", []):
        tool = stage.get("tool", {})
        name = tool.get("name", "")
        version = tool.get("version", "")
        # The tools the wrapper ran, credited under their own names and licences.
        for entry in upstream.get(name, ()):
            if (entry["name"], entry["version"]) not in seen:
                seen.add((entry["name"], entry["version"]))
                cited.append(entry)
        if not name or (name, version) in seen:
            continue
        seen.add((name, version))
        key = name.replace("/", "_").replace(".", "_") + version.replace(".", "_")
        url = tool.get("repo_url", "")
        license_ = tool.get("license", "")
        cite = tool.get("citation", "")
        entries.append(
            f"@software{{{key},\n"
            f"  title = {{{name}}},\n"
            f"  version = {{{version}}},\n"
            f"  license = {{{license_}}},\n"
            f"  url = {{{url}}},\n" + (f"  doi = {{{cite}}},\n" if cite else "") + "}\n"
        )
    for entry in cited:
        key = (
            entry["name"].replace("/", "_").replace(".", "_").replace(" ", "_").replace("-", "_")
            + "_"
            + entry["version"].replace(".", "_")[:12]
        )
        entries.append(
            f"@software{{{key},\n"
            f"  title = {{{entry['name']}}},\n"
            f"  version = {{{entry['version']}}},\n"
            f"  license = {{{entry['license']}}},\n"
            f"  url = {{{entry['url']}}},\n"
            "}\n"
        )
    return "\n".join(entries) if len(entries) > 2 else _DEFAULT_BIBTEX


_DEFAULT_BIBTEX = """% bindsight run with no manifest entries detected.
@software{bindsight,
  title = {bindsight: a reproducible bridge from RNA-seq to de novo protein binder design},
  url = {https://github.com/mikhaeelatefrizk/bindsight},
  license = {AGPL-3.0-or-later}
}
"""

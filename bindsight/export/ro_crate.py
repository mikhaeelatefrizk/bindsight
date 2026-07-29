# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""RO-Crate exporter.

Bundles a finished bindsight run into a single ``.crate.zip`` that is
recognized by Zenodo, Figshare, FAIR Digital Object Frameworks, and the
broader Research Object Crate ecosystem.

We emit the lightweight RO-Crate 1.1 metadata format
(https://www.researchobject.org/ro-crate/1.1/) — a single ``ro-crate-metadata.json``
at the crate root that catalogues every other file, plus a ``software.bib``
listing the upstream tools used. This is intentionally minimal: implementing
the full ``ro-crate-py`` library as a runtime dependency adds several
hundred KB of code for one JSON file.

Every payload file in the crate is byte-identical for runs with the same
manifest; the only varying field is ``datePublished`` in the metadata, which
records when the crate was packaged rather than anything about the run. So
this is a reproducibility primitive — depositing the crate to Zenodo gives a
DOI that anyone can dereference to pull the exact artifacts we packaged.
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
    """Bundle ``run_dir`` into an RO-Crate zip suitable for Zenodo deposit.

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
    metadata = _build_metadata(run, files)
    bibtex = _build_software_bib(run, files)

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

    LOG.info("wrote RO-Crate: %s (%d files)", out, len(files))
    return out


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
#: Single files, in canonical order.
_PIPELINE_FILES = (
    "config.yaml",
    "deg/results.parquet",
    "targets/candidates.parquet",
    "epitopes/epitopes.parquet",
    "taxonomy/failure_taxonomy.parquet",
    "design/results.tar.gz",
    "design/metrics.jsonl",
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
                digests[PurePosixPath(Path(path).as_posix()).name] = sha
    return digests


def _build_metadata(run: Path, files: list[Path]) -> dict[str, Any]:
    """Construct the RO-Crate 1.1 metadata document."""
    manifest_path = run / "run_manifest.jsonld"
    manifest = {}
    if manifest_path.exists():
        try:
            body = json.loads(manifest_path.read_text(encoding="utf-8"))
            body.pop("@context", None)
            manifest = body
        except json.JSONDecodeError:
            pass

    digests = _manifest_digests(manifest)
    file_entries: list[dict[str, object]] = []
    for p in files:
        entry: dict[str, object] = {
            "@id": p.relative_to(run).as_posix(),
            "@type": "File",
            "name": p.name,
            "contentSize": p.stat().st_size,
        }
        sha = digests.get(p.name)
        if sha:
            # schema.org has no sha256 term; this is the RO-Crate convention.
            entry["sha256"] = sha
        file_entries.append(entry)

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
                "hasPart": [{"@id": e["@id"]} for e in file_entries],
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


def _build_software_bib(run: Path, files: list[Path]) -> str:
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
    for stage in body.get("stages", []):
        tool = stage.get("tool", {})
        name = tool.get("name", "")
        version = tool.get("version", "")
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
    return "\n".join(entries) if len(entries) > 2 else _DEFAULT_BIBTEX


_DEFAULT_BIBTEX = """% bindsight run with no manifest entries detected.
@software{bindsight,
  title = {bindsight: a reproducible bridge from RNA-seq to de novo protein binder design},
  url = {https://github.com/mikhaeelatefrizk/bindsight},
  license = {AGPL-3.0-or-later}
}
"""

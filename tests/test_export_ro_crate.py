# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the RO-Crate export module."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pandas as pd
import pytest

from bindsight.export import export_ro_crate
from bindsight.provenance import (
    InputRef,
    OutputRef,
    StageRecord,
    ToolRef,
    new_manifest,
)


def _make_run(tmp_path: Path) -> Path:
    """Build a minimal but valid run directory."""
    run = tmp_path / "run"
    (run / "deg").mkdir(parents=True)
    (run / "targets").mkdir(parents=True)

    pd.DataFrame({"gene_id": ["g1"], "log2fc": [3.0]}).to_parquet(
        run / "deg" / "results.parquet", index=False
    )
    pd.DataFrame({"uniprot_id": ["P04626"], "rank": [1]}).to_parquet(
        run / "targets" / "candidates.parquet", index=False
    )

    counts = run / "counts.tsv"
    counts.write_text("g\ts\n1\t10\n")
    m = new_manifest(name="export-test")
    m.append(
        StageRecord(
            name="deg",
            tool=ToolRef(
                name="pydeseq2",
                version="0.5.4",
                license="MIT",
                repo_url="https://github.com/owkin/PyDESeq2",
                citation="10.1093/bioinformatics/btad547",
            ),
            inputs=[InputRef(role="counts", path="counts.tsv", sha256="0" * 64, bytes=10)],
            outputs=[OutputRef(role="deg", path="deg/results.parquet", sha256="1" * 64, bytes=100)],
        )
    )
    m.stages[0].mark_completed()
    m.write(run / "run_manifest.jsonld")
    return run


def test_export_ro_crate_produces_valid_zip(tmp_path: Path) -> None:
    run = _make_run(tmp_path)
    out = export_ro_crate(run)
    assert out.exists()
    assert out.suffix == ".zip"

    with zipfile.ZipFile(out) as zf:
        names = set(zf.namelist())
        assert "ro-crate-metadata.json" in names
        assert "software.bib" in names
        assert "deg/results.parquet" in names
        assert "targets/candidates.parquet" in names
        assert "run_manifest.jsonld" in names

        # Metadata is valid JSON-LD
        meta = json.loads(zf.read("ro-crate-metadata.json"))
        assert "@context" in meta
        assert "@graph" in meta
        graph = meta["@graph"]
        assert any(node.get("@type") == "Dataset" for node in graph)

        # software.bib references the upstream tool used
        bib = zf.read("software.bib").decode()
        assert "pydeseq2" in bib.lower()
        assert "@software" in bib


def test_export_ro_crate_custom_out_path(tmp_path: Path) -> None:
    run = _make_run(tmp_path)
    out = export_ro_crate(run, tmp_path / "elsewhere" / "my.crate.zip")
    assert out == tmp_path / "elsewhere" / "my.crate.zip"
    assert out.exists()


def test_export_ro_crate_missing_run_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        export_ro_crate(tmp_path / "nope")


def test_export_ro_crate_omits_missing_artifacts(tmp_path: Path) -> None:
    """Crate only includes files that actually exist (graceful partial run)."""
    run = tmp_path / "skinny"
    (run / "deg").mkdir(parents=True)
    pd.DataFrame({"gene_id": ["g"], "log2fc": [1.0]}).to_parquet(
        run / "deg" / "results.parquet", index=False
    )
    out = export_ro_crate(run)
    with zipfile.ZipFile(out) as zf:
        names = set(zf.namelist())
        assert "deg/results.parquet" in names
        # No targets / epitopes — they shouldn't appear
        assert "targets/candidates.parquet" not in names


# ---------------------------------------------------------------------------
# The crate must reach the patients, not stop at the DEG table
# ---------------------------------------------------------------------------
def _make_run_with_external_counts(tmp_path: Path) -> tuple[Path, Path]:
    """A run whose cohort lives outside the run directory, as real runs do."""
    run = tmp_path / "run"
    (run / "deg").mkdir(parents=True)
    pd.DataFrame({"gene_id": ["g1"], "log2fc": [3.0]}).to_parquet(
        run / "deg" / "results.parquet", index=False
    )
    cohort = tmp_path / "study" / "kirc"
    cohort.mkdir(parents=True)
    counts = cohort / "counts.tsv.gz"
    counts.write_bytes(b"\x1f\x8b\x08\x00barcodes-live-here")
    design = cohort / "design.tsv"
    design.write_text("sample\tcase_barcode\tcondition\nT1\tTCGA-AA-0001\ttumor\n")

    m = new_manifest(name="external-inputs")
    m.append(
        StageRecord(
            name="deg",
            tool=ToolRef(
                name="pydeseq2",
                version="0.5.4",
                license="MIT",
                repo_url="https://github.com/owkin/PyDESeq2",
                citation="10.1093/bioinformatics/btad547",
            ),
            inputs=[
                InputRef(role="counts", path=str(counts), sha256="a" * 64, bytes=18),
                InputRef(role="design", path=str(design), sha256="b" * 64, bytes=52),
            ],
            outputs=[OutputRef(role="deg", path="deg/results.parquet", sha256="1" * 64, bytes=100)],
        )
    )
    m.stages[0].mark_completed()
    m.write(run / "run_manifest.jsonld")
    return run, counts


def test_the_crate_carries_a_cohort_stored_outside_the_run(tmp_path: Path) -> None:
    """Without the counts there are no case barcodes, and the chain breaks.

    The allowlist named counts.tsv.gz, but a run configured with inputs.counts
    pointing elsewhere keeps it outside the run directory, so the allowlist
    matched nothing and the exported crate stopped at the DEG table.
    """
    run, _ = _make_run_with_external_counts(tmp_path)
    out = export_ro_crate(run, tmp_path / "c.zip")
    with zipfile.ZipFile(out) as zf:
        names = set(zf.namelist())
        assert "inputs/counts.tsv.gz" in names
        assert "inputs/design.tsv" in names
        assert b"TCGA-AA-0001" in zf.read("inputs/design.tsv")


def test_a_carried_in_input_keeps_its_recorded_digest(tmp_path: Path) -> None:
    run, _ = _make_run_with_external_counts(tmp_path)
    out = export_ro_crate(run, tmp_path / "c.zip")
    with zipfile.ZipFile(out) as zf:
        graph = json.loads(zf.read("ro-crate-metadata.json"))["@graph"]
    entry = next(e for e in graph if e.get("@id") == "inputs/counts.tsv.gz")
    assert entry["sha256"] == "a" * 64
    assert entry["@type"] == "File"
    root = next(e for e in graph if e.get("@id") == "./")
    assert {"@id": "inputs/counts.tsv.gz"} in root["hasPart"]


def test_an_input_already_inside_the_run_is_not_duplicated(tmp_path: Path) -> None:
    """The allowlist already carries those; a second copy under inputs/ is noise."""
    from bindsight.export.ro_crate import _external_inputs

    run = _make_run(tmp_path)  # records counts.tsv at the run root
    assert _external_inputs(run) == []


def test_an_input_missing_from_this_machine_does_not_break_the_export(
    tmp_path: Path,
) -> None:
    """A crate that cannot be built at all is worse than one that says what is absent."""
    run, counts = _make_run_with_external_counts(tmp_path)
    counts.unlink()
    out = export_ro_crate(run, tmp_path / "c.zip")
    with zipfile.ZipFile(out) as zf:
        names = set(zf.namelist())
    assert "inputs/counts.tsv.gz" not in names
    assert "inputs/design.tsv" in names, "the input that is present must still travel"

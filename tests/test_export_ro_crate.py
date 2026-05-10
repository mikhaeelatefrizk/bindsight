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

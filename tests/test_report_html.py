# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the HTML report renderer."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from bindsight.provenance import (
    InputRef,
    OutputRef,
    StageRecord,
    ToolRef,
    new_manifest,
)
from bindsight.report.html import _df_to_records, render_run


def _make_run(tmp_path: Path) -> Path:
    """Build a minimal but realistic run directory for the renderer."""
    run = tmp_path / "run"
    (run / "deg").mkdir(parents=True)
    (run / "targets").mkdir(parents=True)
    (run / "epitopes").mkdir(parents=True)

    deg = pd.DataFrame(
        {
            "gene_id": ["ENSG00000141736", "ENSG00000146648", "ENSG00000142208"],
            "symbol": ["ERBB2", "EGFR", "AKT1"],
            "log2fc": [3.5, 2.8, 0.1],
            "lfc_se": [0.5, 0.5, 0.4],
            "stat": [7.0, 5.6, 0.25],
            "pvalue": [1e-10, 1e-7, 0.8],
            "padj": [1e-9, 1e-6, 0.95],
            "baseMean": [800.0, 600.0, 500.0],
            "contrast": ["condition__tumor_vs_normal"] * 3,
            "significant": [True, True, False],
        }
    )
    deg.to_parquet(run / "deg" / "results.parquet", index=False)

    candidates = pd.DataFrame(
        {
            "gene_id": ["ENSG00000141736", "ENSG00000146648"],
            "symbol": ["ERBB2", "EGFR"],
            "uniprot_id": ["P04626", "P00533"],
            "log2fc": [3.5, 2.8],
            "padj": [1e-9, 1e-6],
            "tractable_modalities": ["Antibody", "Antibody"],
            "open_targets_status": ["bundled_fallback", "bundled_fallback"],
            "n_safety_events": [2, 1],
            "is_surface": [True, True],
            "alphafold_structure_path": ["", ""],
            "has_alphafold_structure": [False, False],
            "rank": [1, 2],
            "rank_in_top_n": [True, True],
        }
    )
    candidates.to_parquet(run / "targets" / "candidates.parquet", index=False)

    epitopes = pd.DataFrame(
        {
            "gene_id": ["ENSG00000141736", "ENSG00000146648"],
            "symbol": ["ERBB2", "EGFR"],
            "uniprot_id": ["P04626", "P00533"],
            "structure_path": ["", ""],
            "site_id": [None, None],
            "chain": ["A", "A"],
            "residues": [[], []],
            "score": [None, None],
            "seed_pdb_path": [None, None],
            "epitope_status": ["surface_bind_not_configured"] * 2,
        }
    )
    epitopes.to_parquet(run / "epitopes" / "epitopes.parquet", index=False)

    # Manifest
    counts = run / "counts.tsv"
    counts.write_text("g\ts1\n1\t10\n")
    m = new_manifest(name="renderer-test")
    m.append(
        StageRecord(
            name="deg",
            tool=ToolRef(name="pydeseq2", version="0.5.4", license="MIT"),
            inputs=[InputRef(role="counts", path="counts.tsv", sha256="0" * 64, bytes=10)],
            outputs=[
                OutputRef(role="deg_table", path="deg/results.parquet", sha256="1" * 64, bytes=100)
            ],
        )
    )
    m.stages[0].mark_completed()
    m.append(
        StageRecord(
            name="discover",
            tool=ToolRef(name="bindsight/0.0.1.dev0", version="0.0.1.dev0", license="MIT"),
        )
    )
    m.stages[1].mark_completed()
    m.write(run / "run_manifest.jsonld")

    return run


def test_render_run_produces_self_contained_html(tmp_path: Path) -> None:
    run = _make_run(tmp_path)
    out = render_run(run)

    assert out.exists()
    assert out.name == "report.html"
    assert out.stat().st_size > 5000

    text = out.read_text(encoding="utf-8")
    assert "<title>bindsight report" in text
    assert ":root {" in text  # CSS embedded
    assert "data:image/png;base64," in text  # volcano embedded
    assert "ERBB2" in text  # candidate row rendered
    assert "P04626" in text
    # Limitations section is always rendered (honest scope of discovery).
    assert "<h2>Limitations</h2>" in text
    assert "cell-surface protein abundance" in text
    assert "infiltrating immune" in text


def test_render_run_handles_missing_optional_files(tmp_path: Path) -> None:
    """Renderer should not crash if some artifacts are missing."""
    run = tmp_path / "skinny"
    (run / "deg").mkdir(parents=True)
    out = render_run(run)
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    # No crash; report explains the empty state
    assert "<title>bindsight report" in text


def test_render_run_custom_out_path(tmp_path: Path) -> None:
    run = _make_run(tmp_path)
    custom_out = tmp_path / "elsewhere" / "my_report.html"
    out = render_run(run, custom_out)
    assert out == custom_out
    assert out.exists()


def test_df_to_records_handles_none() -> None:
    assert _df_to_records(None, ["x"]) == []


def test_df_to_records_formats_floats() -> None:
    df = pd.DataFrame({"a": [3.14159, 0.000001, 1.0]})
    rows = _df_to_records(df, ["a"])
    # All values formatted as %.3g
    assert isinstance(rows[0]["a"], str)
    assert "3.14" in rows[0]["a"]


def test_manifest_round_trip_through_renderer(tmp_path: Path) -> None:
    """The manifest written by the pipeline survives parsing in the renderer."""
    run = _make_run(tmp_path)
    out = render_run(run)
    manifest = json.loads((run / "run_manifest.jsonld").read_text(encoding="utf-8"))
    assert manifest["stages"][0]["name"] == "deg"
    text = out.read_text(encoding="utf-8")
    assert "deg" in text
    assert "pydeseq2" in text

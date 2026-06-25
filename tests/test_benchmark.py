# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the rediscovery-benchmark module + CLI command."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from click.testing import CliRunner

from bindsight.benchmark import (
    KnownAntigen,
    load_known_antigens,
    render_benchmark_html,
    run_benchmark,
    score_run,
)
from bindsight.cli import main


def _write_known(path: Path) -> Path:
    path.write_text(
        "symbol\tuniprot\ttumor_type\texpected_direction\n"
        "ERBB2\tP04626\tBRCA\tup\n"
        "EGFR\tP00533\tLUAD\tup\n"
        "CD33\tP20138\tAML\tup\n"
    )
    return path


def _make_run_dir(root: Path, uniprot_ranks: list[tuple[str, int, float]]) -> Path:
    """Create a run dir with a candidates.parquet of (uniprot, rank, log2fc)."""
    cand = pd.DataFrame(
        [
            {"symbol": u[:4], "uniprot_id": u, "rank": r, "log2fc": fc, "padj": 0.01}
            for (u, r, fc) in uniprot_ranks
        ]
    )
    (root / "targets").mkdir(parents=True, exist_ok=True)
    cand.to_parquet(root / "targets" / "candidates.parquet", index=False)
    return root


def test_load_known_antigens(tmp_path: Path) -> None:
    known = load_known_antigens(_write_known(tmp_path / "known.tsv"))
    assert len(known) == 3
    assert {k.symbol for k in known} == {"ERBB2", "EGFR", "CD33"}
    assert known[0].uniprot == "P04626"


def test_load_known_antigens_requires_columns(tmp_path: Path) -> None:
    bad = tmp_path / "bad.tsv"
    bad.write_text("symbol\tfoo\nERBB2\tx\n")
    with pytest.raises(ValueError, match="uniprot"):
        load_known_antigens(bad)


def test_score_run_ranks_and_recall(tmp_path: Path) -> None:
    known = [
        KnownAntigen("ERBB2", "P04626", "BRCA"),
        KnownAntigen("EGFR", "P00533", "LUAD"),
        KnownAntigen("CD33", "P20138", "AML"),
    ]
    run = _make_run_dir(
        tmp_path / "run1",
        [("P04626", 1, 5.0), ("P00533", 7, 3.0), ("Q9XXXX", 2, 4.0)],
    )
    score = score_run(run, known, ks=(5, 10))

    by_sym = {a["symbol"]: a for a in score.per_antigen}
    assert by_sym["ERBB2"]["found"] is True
    assert by_sym["ERBB2"]["rank"] == 1
    assert by_sym["ERBB2"]["in_top_5"] is True
    assert by_sym["EGFR"]["found"] is True
    assert by_sym["EGFR"]["rank"] == 7
    assert by_sym["EGFR"]["in_top_5"] is False  # rank 7 > 5
    assert by_sym["EGFR"]["in_top_10"] is True
    assert by_sym["CD33"]["found"] is False
    assert by_sym["CD33"]["rank"] is None

    assert score.n_found == 2
    assert score.recall_at[5] == pytest.approx(1 / 3)  # only ERBB2 in top5
    assert score.recall_at[10] == pytest.approx(2 / 3)  # ERBB2 + EGFR


def test_score_run_missing_candidates(tmp_path: Path) -> None:
    known = [KnownAntigen("ERBB2", "P04626")]
    empty = tmp_path / "empty"
    empty.mkdir()
    score = score_run(empty, known)
    assert score.n_found == 0
    assert score.per_antigen[0]["found"] is False


def test_render_html_contains_antigens(tmp_path: Path) -> None:
    known = [KnownAntigen("ERBB2", "P04626", "BRCA")]
    run = _make_run_dir(tmp_path / "r", [("P04626", 1, 5.0)])
    score = score_run(run, known)
    html = render_benchmark_html([score], known_source="known.tsv")
    assert "ERBB2" in html
    assert "recall@5" in html
    assert "<html" in html.lower()


def test_run_benchmark_writes_report(tmp_path: Path) -> None:
    known_path = _write_known(tmp_path / "known.tsv")
    run = _make_run_dir(tmp_path / "run1", [("P04626", 1, 5.0), ("P00533", 3, 3.0)])
    out = tmp_path / "report.html"
    written, scores = run_benchmark([run], known_path, out_html=out)
    assert written.exists()
    assert len(scores) == 1
    assert scores[0].n_found == 2


def test_cli_benchmark(tmp_path: Path) -> None:
    known_path = _write_known(tmp_path / "known.tsv")
    run = _make_run_dir(tmp_path / "run1", [("P04626", 1, 5.0)])
    out = tmp_path / "report.html"
    result = CliRunner().invoke(
        main,
        [
            "benchmark",
            str(run),
            "--known-antigens",
            str(known_path),
            "--out",
            str(out),
        ],
    )
    assert result.exit_code == 0, result.output
    assert out.exists()
    assert "recall@5" in result.output

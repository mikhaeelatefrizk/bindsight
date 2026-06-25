# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the three-way designer benchmark harness (mock backend, CPU only)."""

from __future__ import annotations

import json
from pathlib import Path

from bindsight.benchmark.designer_bench import (
    Target,
    _floats,
    _read_metrics,
    run_designer_benchmark,
    run_one_designer,
)


def test_read_metrics_and_floats(tmp_path: Path) -> None:
    p = tmp_path / "metrics.jsonl"
    p.write_text(
        json.dumps({"iptm": 0.7, "affinity_pred_value": -7.0})
        + "\n"
        + "\n"  # blank line tolerated
        + json.dumps({"iptm": 0.8, "affinity_pred_value": None})
        + "\n"
    )
    rows = _read_metrics(p)
    assert len(rows) == 2
    assert _floats(rows, "iptm") == [0.7, 0.8]
    # None / missing values are skipped, not coerced.
    assert _floats(rows, "affinity_pred_value") == [-7.0]


def test_read_metrics_missing_file(tmp_path: Path) -> None:
    assert _read_metrics(tmp_path / "nope.jsonl") == []


def test_run_one_designer_mock() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        score = run_one_designer(
            "rfdiff_mpnn",
            [Target("P04626", "ERBB2"), Target("P00533", "EGFR")],
            backend="mock",
            validator="boltz2",
            n_trajectories=4,
            seed=0,
            structures_dir=None,
            scratch=Path(tmp),
        )
    assert score.error is None
    assert score.designer == "rfdiff_mpnn"
    assert score.n_designs > 0
    assert score.mean_iptm is not None
    assert 0.0 <= score.success_rate <= 1.0  # type: ignore[operator]
    # Mock backend never spends money.
    assert score.cost_usd == 0.0
    assert len(score.per_target) == 2


def test_run_designer_benchmark_mock(tmp_path: Path) -> None:
    summary = run_designer_benchmark(
        out_dir=tmp_path / "out",
        backend="mock",
        designers=("rfdiff_mpnn", "bindcraft", "boltzgen"),
        validator="boltz2",
        targets=[Target("P04626", "ERBB2")],
        n_trajectories=2,
    )
    assert summary["is_mock"] is True
    assert {d["designer"] for d in summary["designers"]} == {
        "rfdiff_mpnn",
        "bindcraft",
        "boltzgen",
    }
    for d in summary["designers"]:
        assert d["error"] is None
        assert d["n_designs"] > 0

    # Artifacts written, and the mock result is clearly labelled synthetic.
    assert (tmp_path / "out" / "results.json").exists()
    md = (tmp_path / "out" / "RESULTS.md").read_text()
    assert "MOCK" in md
    assert "rfdiff_mpnn" in md

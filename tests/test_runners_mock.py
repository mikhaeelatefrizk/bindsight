# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the mock runner used in CI."""

from __future__ import annotations

import tarfile
from pathlib import Path

from bindsight.runners.mock import MockRunner


def test_mock_runner_round_trip(tmp_path: Path) -> None:
    runner = MockRunner()
    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text("# fake spec\n")
    results_dir = tmp_path / "results"
    handle = runner.submit(spec_path, results_dir=results_dir)
    status = runner.poll(handle)
    assert status.state == "succeeded"
    archive = runner.fetch(handle)
    assert archive.exists()
    with tarfile.open(archive, "r:gz") as tf:
        members = tf.getnames()
    # Realistically-shaped mock result so the whole pipeline runs E2E.
    assert "metrics.jsonl" in members
    assert any(m.startswith("validate/") for m in members)
    assert any(m.startswith("design/") for m in members)
    MockRunner.cleanup(archive)


def test_mock_runner_cost_estimate_is_zero() -> None:
    est = MockRunner().estimate_cost(spec_size=50)
    assert est.usd_estimate == 0.0
    assert est.gpu_hours == 0.0

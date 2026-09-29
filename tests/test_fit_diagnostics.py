# SPDX-License-Identifier: AGPL-3.0-or-later
"""Artificial engineering fixtures for fit records, never research evidence."""

import json
from pathlib import Path

import pytest

from bindsight.config import RunConfig
from bindsight.deg.diagnostics import (
    diagnostics_path,
    read_fit_diagnostics,
    write_fit_diagnostics,
)
from bindsight.pipelines.discover import _stage_deg
from bindsight.provenance import sha256_file
from bindsight.report.fit_diagnostics import fit_summary


def diagnostics() -> dict:
    return {
        "residual_degrees_of_freedom": 2,
        "convergence": {
            "_genewise_converged": {"not_converged": 2, "unreported": 1},
            "_MAP_converged": {"not_converged": 1, "unreported": 0},
            "_LFC_converged": {"not_converged": 0, "unreported": 0},
        },
        "dispersion_fallback_repairs": [
            {"n_failed": 2, "cr_reg": True, "prior_reg": False},
            {"n_failed": 1, "cr_reg": True, "prior_reg": True},
        ],
    }


def _table(tmp_path: Path) -> Path:
    table = tmp_path / "deg/results.parquet"
    table.parent.mkdir(parents=True)
    table.write_bytes(b"artificial table bytes for artifact identity tests")
    return table


def test_matching_fit_records_surface_low_df_nonconvergence_and_fallbacks(tmp_path: Path) -> None:
    table = _table(tmp_path)
    write_fit_diagnostics(table, diagnostics())
    summary = fit_summary(tmp_path)
    assert summary["available"] is True
    warnings = " ".join(summary["warnings"])
    assert "Residual degrees of freedom: 2 (below 3)" in warnings
    assert "Gene-wise dispersion: 2 genes" in warnings
    assert "convergence was unreported for 1 genes" in warnings
    assert "3 fits across 2 inference calls" in warnings
    assert "same gene more than once" in warnings
    assert "do not establish biological validity" in summary["scope"]


@pytest.mark.parametrize("damage", ["missing", "changed_table", "malformed", "empty"])
def test_missing_or_unmatched_fit_record_is_unknown(tmp_path: Path, damage: str) -> None:
    table = _table(tmp_path)
    write_fit_diagnostics(table, diagnostics())
    if damage == "missing":
        diagnostics_path(table).unlink()
    elif damage == "changed_table":
        table.write_bytes(b"a different output from a different fit")
    elif damage == "malformed":
        diagnostics_path(table).write_text("[]")
    else:
        write_fit_diagnostics(table, {})
    summary = fit_summary(tmp_path)
    assert summary["available"] is False
    assert summary["warnings"] == []
    assert "unavailable" in summary["details"][0]
    assert "0 recorded" not in " ".join(summary["details"])


def test_partial_diagnostics_do_not_invent_convergence_counts(tmp_path: Path) -> None:
    write_fit_diagnostics(_table(tmp_path), {"residual_degrees_of_freedom": 8})
    summary = fit_summary(tmp_path)
    assert summary["warnings"] == []
    assert "optimizer convergence counts were not recorded" in " ".join(summary["details"])
    assert "fallback use was not fully recorded" in " ".join(summary["details"])
    assert "0 recorded" not in " ".join(summary["details"])


def test_pipeline_persists_and_reuses_the_record_for_its_exact_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    counts, design = tmp_path / "counts.tsv", tmp_path / "design.tsv"
    counts.write_text("artificial engineering fixture\n")
    design.write_text("artificial engineering fixture\n")
    cfg = RunConfig.model_validate(
        {
            "name": "fit-test",
            "out_dir": tmp_path,
            "inputs": {"counts": counts, "design": design},
            "params": {
                "deg": {
                    "design_formula": "~ condition",
                    "contrast": ["condition", "case", "control"],
                }
            },
        }
    )
    table = tmp_path / "deg/results.parquet"
    calls = []

    def fake_fit(self, counts, design, out_path):
        calls.append(1)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"artificial bytes; no science is run in this regression")
        return {
            "n_samples": 6,
            "n_genes_tested": 10,
            "n_significant": 2,
            "fit_diagnostics": diagnostics(),
        }

    monkeypatch.setattr("bindsight.pipelines.discover.PyDESeq2Runner.run", fake_fit)
    fresh = _stage_deg(cfg, table)
    cached = _stage_deg(cfg, table)
    assert fresh.status == cached.status == "completed"
    assert cached.cache_status == "hit"
    assert len(calls) == 1
    assert read_fit_diagnostics(table) == diagnostics()
    for stage in (fresh, cached):
        recorded = next(ref for ref in stage.outputs if ref.role == "deg_fit_diagnostics")
        assert recorded.sha256 == sha256_file(diagnostics_path(table))

    # A leftover sidecar from a different table must not be newly attested.
    body = json.loads(diagnostics_path(table).read_text())
    body["deg_table_sha256"] = "0" * 64
    diagnostics_path(table).write_text(json.dumps(body))
    stale = _stage_deg(cfg, table)
    assert stale.cache_status == "hit"
    assert all(ref.role != "deg_fit_diagnostics" for ref in stale.outputs)
    assert read_fit_diagnostics(table) is None

"""Tests for the full-pipeline orchestrator."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from bindsight.config import RunConfig
from bindsight.pipelines import full_run as full_run_module

REPO_ROOT = Path(__file__).parent.parent
EXAMPLES = REPO_ROOT / "examples" / "demo"


@pytest.fixture
def demo_cfg(tmp_path: Path) -> RunConfig:
    from tests.conftest import write_mock_cohort

    cfg = RunConfig.from_yaml(EXAMPLES / "config.yaml")
    cfg.out_dir = tmp_path / "full_out"
    counts = tmp_path / "cache" / "counts.tsv.gz"
    design = tmp_path / "cache" / "design.tsv"
    write_mock_cohort(counts, design)
    cfg.inputs.counts = counts
    cfg.inputs.design = design
    cfg.inputs.download = None  # cohort already materialised above
    return cfg


def test_full_run_with_only_discover(offline_real_data, demo_cfg: RunConfig, tmp_path: Path) -> None:
    """Full run with no GPU artifacts: discover OK, design/validate skipped, report+crate produced."""
    fake_deg = pd.DataFrame(
        {
            "log2FoldChange": [3.5, 2.8, 0.1, 0.0, 0.05, -2.5, -2.8, 4.0, 3.0, 0.0],
            "lfcSE": [0.5] * 10,
            "stat": [7.0, 5.6, 0.25, 0.0, 0.1, -5.0, -5.6, 8.0, 6.0, 0.0],
            "pvalue": [1e-10, 1e-7, 0.8, 0.99, 0.95, 1e-8, 1e-9, 1e-11, 1e-9, 0.99],
            "padj": [1e-9, 1e-6, 0.95, 0.99, 0.95, 1e-7, 1e-8, 1e-10, 1e-8, 0.99],
            "baseMean": [800, 600, 500, 280, 240, 250, 260, 1000, 900, 250],
        },
        index=[
            "ENSG00000141736",
            "ENSG00000146648",
            "ENSG00000091831",
            "ENSG00000142208",
            "ENSG00000118260",
            "ENSG00000074706",
            "ENSG00000196712",
            "ENSG00000133703",
            "ENSG00000174775",
            "ENSG00000129965",
        ],
    )

    out = tmp_path / "full_out"
    with patch(
        "bindsight.deg.pydeseq2_runner.PyDESeq2Runner._run_pydeseq2",
        return_value=fake_deg,
    ):
        result = full_run_module.run(demo_cfg, out_dir=out)

    assert result.discover_ok is True
    assert result.design_ok is False  # no Colab artifacts present
    assert result.validate_ok is False
    assert result.rank_ok is False  # no validation, so nothing to rank
    assert result.report_path is not None
    assert result.report_path.exists()
    assert result.crate_path is not None
    assert result.crate_path.exists()


def test_full_run_skips_export_when_requested(offline_real_data, demo_cfg: RunConfig, tmp_path: Path) -> None:
    fake_deg = pd.DataFrame(
        {
            "log2FoldChange": [3.5, 2.8, 0.1, 0.0, 0.05, -2.5, -2.8, 4.0, 3.0, 0.0],
            "lfcSE": [0.5] * 10,
            "stat": [7.0, 5.6, 0.25, 0.0, 0.1, -5.0, -5.6, 8.0, 6.0, 0.0],
            "pvalue": [1e-10, 1e-7, 0.8, 0.99, 0.95, 1e-8, 1e-9, 1e-11, 1e-9, 0.99],
            "padj": [1e-9, 1e-6, 0.95, 0.99, 0.95, 1e-7, 1e-8, 1e-10, 1e-8, 0.99],
            "baseMean": [800, 600, 500, 280, 240, 250, 260, 1000, 900, 250],
        },
        index=[
            "ENSG00000141736",
            "ENSG00000146648",
            "ENSG00000091831",
            "ENSG00000142208",
            "ENSG00000118260",
            "ENSG00000074706",
            "ENSG00000196712",
            "ENSG00000133703",
            "ENSG00000174775",
            "ENSG00000129965",
        ],
    )

    out = tmp_path / "full_out2"
    with patch(
        "bindsight.deg.pydeseq2_runner.PyDESeq2Runner._run_pydeseq2",
        return_value=fake_deg,
    ):
        result = full_run_module.run(demo_cfg, out_dir=out, skip_report=True, skip_export=True)
    assert result.report_path is None
    assert result.crate_path is None


def test_full_run_picks_up_existing_validated_for_rank(offline_real_data, demo_cfg: RunConfig, tmp_path: Path) -> None:
    """If user dropped validate/validated.parquet from Colab, rank stage runs."""
    fake_deg = pd.DataFrame(
        {
            "log2FoldChange": [3.5, 2.8, 0.1, 0.0, 0.05, -2.5, -2.8, 4.0, 3.0, 0.0],
            "lfcSE": [0.5] * 10,
            "stat": [7.0, 5.6, 0.25, 0.0, 0.1, -5.0, -5.6, 8.0, 6.0, 0.0],
            "pvalue": [1e-10, 1e-7, 0.8, 0.99, 0.95, 1e-8, 1e-9, 1e-11, 1e-9, 0.99],
            "padj": [1e-9, 1e-6, 0.95, 0.99, 0.95, 1e-7, 1e-8, 1e-10, 1e-8, 0.99],
            "baseMean": [800, 600, 500, 280, 240, 250, 260, 1000, 900, 250],
        },
        index=[
            "ENSG00000141736",
            "ENSG00000146648",
            "ENSG00000091831",
            "ENSG00000142208",
            "ENSG00000118260",
            "ENSG00000074706",
            "ENSG00000196712",
            "ENSG00000133703",
            "ENSG00000174775",
            "ENSG00000129965",
        ],
    )
    out = tmp_path / "full_out3"
    out.mkdir(parents=True, exist_ok=True)
    (out / "validate").mkdir()
    pd.DataFrame(
        [
            {
                "binder_id": "b1",
                "target_uniprot": "P04626",
                "iptm": 0.8,
                "affinity_pred_value": -7.5,
            },
        ]
    ).to_parquet(out / "validate" / "validated.parquet", index=False)

    with patch(
        "bindsight.deg.pydeseq2_runner.PyDESeq2Runner._run_pydeseq2",
        return_value=fake_deg,
    ):
        result = full_run_module.run(demo_cfg, out_dir=out)
    assert result.validate_ok is True
    assert result.rank_ok is True
    assert (out / "rank" / "ranking.parquet").exists()

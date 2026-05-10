"""Tests for ``bindsight.deg.pydeseq2_runner``.

The cheap tests exercise the I/O + filtering layer with mocked pydeseq2 so
they run in CI without paying the pydeseq2 import cost. The ``slow`` test
runs the real pydeseq2 against the tiny fixture; it's skipped by default.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from bindsight.config import DEGParams
from bindsight.deg.pydeseq2_runner import PyDESeq2Runner


@pytest.fixture
def tiny_fixture(fixtures_dir: Path) -> tuple[Path, Path]:
    return fixtures_dir / "tiny_counts.tsv", fixtures_dir / "tiny_design.tsv"


@pytest.fixture
def deg_params() -> DEGParams:
    return DEGParams(
        design_formula="~ condition",
        contrast=["condition", "tumor", "normal"],
        fdr_threshold=0.5,  # lenient — tiny fixture has no real signal
        log2fc_threshold=0.5,
        min_replicates=2,
        min_count=0,
    )


def test_load_counts_and_design(tiny_fixture: tuple[Path, Path]) -> None:
    c_path, d_path = tiny_fixture
    counts = PyDESeq2Runner.load_counts(c_path)
    design = PyDESeq2Runner.load_design(d_path)
    assert counts.shape == (5, 6)  # 5 genes × 6 samples
    assert list(counts.columns) == [
        "tumor_1",
        "tumor_2",
        "tumor_3",
        "normal_1",
        "normal_2",
        "normal_3",
    ]
    assert design.loc["tumor_1", "condition"] == "tumor"


def test_low_count_filter_drops_appropriate_genes(deg_params: DEGParams) -> None:
    counts = pd.DataFrame(
        {
            "s1": [10, 10, 0],
            "s2": [10, 10, 0],
            "s3": [10, 10, 0],
        },
        index=["g_keep", "g_keep2", "g_drop"],
    )
    filtered = PyDESeq2Runner(deg_params)._low_count_filter(
        counts.assign()
    )  # min_count=0 → no drop
    assert len(filtered) == 3

    strict = DEGParams(
        design_formula="~ condition",
        contrast=["condition", "t", "n"],
        min_count=5,
        min_replicates=2,
    )
    filtered2 = PyDESeq2Runner(strict)._low_count_filter(counts)
    assert "g_drop" not in filtered2.index


def test_run_with_mocked_pydeseq2(
    tiny_fixture: tuple[Path, Path], deg_params: DEGParams, tmp_path: Path
) -> None:
    """Avoid the heavy pydeseq2 invocation in CI by mocking ``_run_pydeseq2``."""
    c_path, d_path = tiny_fixture
    runner = PyDESeq2Runner(deg_params)

    fake_results = pd.DataFrame(
        {
            "log2FoldChange": [3.5, 0.1, -0.2, 4.0, -3.1],
            "lfcSE": [0.5, 0.5, 0.5, 0.5, 0.5],
            "stat": [7.0, 0.2, -0.4, 8.0, -6.2],
            "pvalue": [1e-10, 0.8, 0.7, 1e-12, 1e-9],
            "padj": [1e-9, 0.95, 0.95, 1e-11, 1e-8],
            "baseMean": [800, 500, 300, 1000, 1500],
        },
        index=[
            "ENSG00000141736",
            "ENSG00000146648",
            "ENSG00000142208",
            "ENSG00000119535",
            "ENSG00000147889",
        ],
    )

    with patch.object(PyDESeq2Runner, "_run_pydeseq2", return_value=fake_results):
        out = tmp_path / "deg" / "results.parquet"
        metrics = runner.run(c_path, d_path, out)

    assert out.exists()
    df = pd.read_parquet(out)
    assert set(df.columns) >= {
        "gene_id",
        "log2fc",
        "lfc_se",
        "stat",
        "pvalue",
        "padj",
        "baseMean",
        "contrast",
        "significant",
    }
    assert metrics["n_genes_tested"] == 5
    # Three of five rows have |log2fc| >= 0.5 AND padj < 0.5
    assert metrics["n_significant"] == 3
    assert df["contrast"].iloc[0] == "condition__tumor_vs_normal"


def test_run_raises_on_mismatched_samples(
    tiny_fixture: tuple[Path, Path], deg_params: DEGParams, tmp_path: Path
) -> None:
    c_path, _ = tiny_fixture
    bad_design = tmp_path / "bad_design.tsv"
    bad_design.write_text("sample\tcondition\nfoo_1\ttumor\nfoo_2\tnormal\n")
    runner = PyDESeq2Runner(deg_params)
    with pytest.raises(ValueError, match="samples in common"):
        runner.run(c_path, bad_design, tmp_path / "deg" / "results.parquet")


# ---------------------------------------------------------------------------
# Slow real-pydeseq2 test (skipped by default)
# ---------------------------------------------------------------------------
@pytest.mark.slow
def test_real_pydeseq2_on_tiny_fixture(
    tiny_fixture: tuple[Path, Path], deg_params: DEGParams, tmp_path: Path
) -> None:
    """Run the real pydeseq2 against the tiny fixture. Skipped in CI."""
    c_path, d_path = tiny_fixture
    runner = PyDESeq2Runner(deg_params)
    out = tmp_path / "deg" / "results.parquet"
    metrics = runner.run(c_path, d_path, out)
    assert out.exists()
    assert metrics["n_genes_tested"] >= 1

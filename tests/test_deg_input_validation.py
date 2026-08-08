# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Input guards on the DEG stage.

DESeq2's negative-binomial model is only defined on raw integer counts, and its
dispersion estimate is only defined when both contrast levels are replicated.
Both used to be unchecked: a TPM matrix was truncated toward zero and a
5-tumour / 1-normal design ran to completion, in each case producing confident
p-values that mean nothing. These tests pin the guards, and pin the configured
FDR reaching pydeseq2's independent filtering.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pandas as pd
import pytest

from bindsight.config import DEGParams
from bindsight.deg.pydeseq2_runner import PyDESeq2Runner

_SAMPLES = ["tumor_1", "tumor_2", "tumor_3", "normal_1", "normal_2", "normal_3"]
_CONDITIONS = ["tumor"] * 3 + ["normal"] * 3


@pytest.fixture
def deg_params() -> DEGParams:
    return DEGParams(
        design_formula="~ condition",
        contrast=["condition", "tumor", "normal"],
        fdr_threshold=0.5,  # lenient — these matrices carry no real signal
        log2fc_threshold=0.5,
        min_replicates=2,
        min_count=0,
    )


def _write_counts(path: Path, values: dict[str, list[float]], samples: list[str]) -> Path:
    frame = pd.DataFrame(values, index=samples).T
    frame.index.name = "gene_id"
    frame.to_csv(path, sep="\t")
    return path


def _write_design(path: Path, samples: list[str], conditions: list[str], column: str) -> Path:
    pd.DataFrame(
        {column: conditions},
        index=pd.Index(samples, name="sample"),
    ).to_csv(path, sep="\t")
    return path


def _fake_results(gene_ids: list[str]) -> pd.DataFrame:
    n = len(gene_ids)
    return pd.DataFrame(
        {
            "log2FoldChange": [3.5] * n,
            "lfcSE": [0.5] * n,
            "stat": [7.0] * n,
            "pvalue": [1e-10] * n,
            "padj": [1e-9] * n,
            "baseMean": [800.0] * n,
        },
        index=gene_ids,
    )


# ---------------------------------------------------------------------------
# L4 — non-integer counts
# ---------------------------------------------------------------------------
def test_run_rejects_a_tpm_style_counts_matrix(deg_params: DEGParams, tmp_path: Path) -> None:
    """0.7 used to truncate to 0 and DESeq2 ran on it silently."""
    counts = _write_counts(
        tmp_path / "tpm_counts.tsv",
        {
            "ENSG00000141736": [0.7, 12.4, 9.0, 0.0, 1.0, 2.0],
            "ENSG00000146648": [3.9, 8.0, 7.0, 1.0, 2.0, 3.0],
        },
        _SAMPLES,
    )
    design = _write_design(tmp_path / "design.tsv", _SAMPLES, _CONDITIONS, "condition")
    runner = PyDESeq2Runner(deg_params)

    with pytest.raises(ValueError, match="non-integer") as exc:
        runner.run(counts, design, tmp_path / "deg" / "results.parquet")

    message = str(exc.value)
    # The error must name the likely cause, not merely refuse the input.
    assert "TPM/FPKM/normalised" in message
    assert "raw integer" in message
    # …and point at the offending cells.
    assert "ENSG00000141736/tumor_1=0.7" in message
    assert not (tmp_path / "deg" / "results.parquet").exists()


def test_run_rejects_non_integer_counts_before_any_deseq2_compute(
    deg_params: DEGParams, tmp_path: Path
) -> None:
    counts = _write_counts(
        tmp_path / "tpm_counts.tsv",
        {"ENSG00000141736": [0.7, 12.4, 9.0, 0.0, 1.0, 2.0]},
        _SAMPLES,
    )
    design = _write_design(tmp_path / "design.tsv", _SAMPLES, _CONDITIONS, "condition")

    with (
        patch.object(PyDESeq2Runner, "_run_pydeseq2") as run_deseq,
        pytest.raises(ValueError, match="non-integer"),
    ):
        PyDESeq2Runner(deg_params).run(counts, design, tmp_path / "out.parquet")
    run_deseq.assert_not_called()


def test_run_accepts_integral_float_counts(deg_params: DEGParams, tmp_path: Path) -> None:
    """Float-dtype matrices whose values are whole numbers must keep working."""
    gene_ids = ["ENSG00000141736", "ENSG00000146648"]
    counts = _write_counts(
        tmp_path / "float_counts.tsv",
        {
            gene_ids[0]: [1200.0, 1450.0, 1350.0, 120.0, 95.0, 110.0],
            gene_ids[1]: [5.0, 3.0, 5.0, 3.0, 5.0, 3.0],
        },
        _SAMPLES,
    )
    design = _write_design(tmp_path / "design.tsv", _SAMPLES, _CONDITIONS, "condition")
    runner = PyDESeq2Runner(deg_params)

    loaded = PyDESeq2Runner.load_counts(counts)
    assert loaded.to_numpy().dtype.kind == "f"  # genuinely float dtype, not int

    out = tmp_path / "deg" / "results.parquet"
    with patch.object(PyDESeq2Runner, "_run_pydeseq2", return_value=_fake_results(gene_ids)):
        metrics = runner.run(counts, design, out)

    assert out.exists()
    assert metrics["n_genes_tested"] == 2


# ---------------------------------------------------------------------------
# I5 — the configured FDR must drive pydeseq2's independent filtering
# ---------------------------------------------------------------------------
def test_configured_fdr_threshold_reaches_deseq_stats(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``alpha`` used to keep pydeseq2's 0.05 default whatever the config said."""
    import pydeseq2.dds
    import pydeseq2.default_inference
    import pydeseq2.ds

    gene_ids = ["ENSG00000141736", "ENSG00000146648"]
    captured: dict[str, Any] = {}

    class _FakeDeseqDataSet:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

        def deseq2(self) -> None:
            return None

    class _RecordingDeseqStats:
        # Mirrors the real signature, whose alpha defaults to 0.05 — so a runner
        # that forgets to pass it silently lands back on the wrong threshold.
        def __init__(
            self,
            dds: object,
            *,
            contrast: list[str],
            alpha: float = 0.05,
            quiet: bool = False,
        ) -> None:
            captured["alpha"] = alpha
            captured["contrast"] = contrast
            self.results_df = _fake_results(gene_ids)

        def summary(self) -> None:
            return None

    monkeypatch.setattr(pydeseq2.dds, "DeseqDataSet", _FakeDeseqDataSet)
    monkeypatch.setattr(pydeseq2.ds, "DeseqStats", _RecordingDeseqStats)
    monkeypatch.setattr(pydeseq2.default_inference, "DefaultInference", lambda: object())

    params = DEGParams(
        design_formula="~ condition",
        contrast=["condition", "tumor", "normal"],
        fdr_threshold=0.01,  # deliberately not pydeseq2's 0.05 default
        log2fc_threshold=0.5,
        min_replicates=2,
        min_count=0,
    )
    counts = _write_counts(
        tmp_path / "counts.tsv",
        {
            gene_ids[0]: [1200, 1450, 1350, 120, 95, 110],
            gene_ids[1]: [980, 1100, 1050, 200, 180, 220],
        },
        _SAMPLES,
    )
    design = _write_design(tmp_path / "design.tsv", _SAMPLES, _CONDITIONS, "condition")

    PyDESeq2Runner(params).run(counts, design, tmp_path / "deg" / "results.parquet")

    assert captured["alpha"] == pytest.approx(0.01)
    assert captured["contrast"] == ["condition", "tumor", "normal"]


# ---------------------------------------------------------------------------
# Per-level replicate guard — a total sample count is not a replication check
# ---------------------------------------------------------------------------
def test_run_rejects_an_unreplicated_contrast_level(deg_params: DEGParams, tmp_path: Path) -> None:
    """5 tumour + 1 normal clears 2*min_replicates in total, yet has no dispersion."""
    samples = [f"tumor_{i}" for i in range(1, 6)] + ["normal_1"]
    conditions = ["tumor"] * 5 + ["normal"]
    counts = _write_counts(
        tmp_path / "counts.tsv",
        {"ENSG00000141736": [1200, 1450, 1350, 1400, 1300, 120]},
        samples,
    )
    design = _write_design(tmp_path / "design.tsv", samples, conditions, "condition")

    with pytest.raises(ValueError, match="dispersion estimate") as exc:
        PyDESeq2Runner(deg_params).run(counts, design, tmp_path / "deg" / "results.parquet")

    message = str(exc.value)
    assert "condition='normal'" in message  # names the offending level
    assert "1 sample(s)" in message
    assert "min_replicates=2" in message
    # The total-sample check passed (6 >= 4); it is not what fired here.
    assert "samples in common" not in message


def test_unreplicated_level_is_caught_before_any_deseq2_compute(
    deg_params: DEGParams, tmp_path: Path
) -> None:
    samples = [f"tumor_{i}" for i in range(1, 6)] + ["normal_1"]
    conditions = ["tumor"] * 5 + ["normal"]
    counts = _write_counts(
        tmp_path / "counts.tsv",
        {"ENSG00000141736": [1200, 1450, 1350, 1400, 1300, 120]},
        samples,
    )
    design = _write_design(tmp_path / "design.tsv", samples, conditions, "condition")

    with (
        patch.object(PyDESeq2Runner, "_run_pydeseq2") as run_deseq,
        pytest.raises(ValueError, match="dispersion estimate"),
    ):
        PyDESeq2Runner(deg_params).run(counts, design, tmp_path / "out.parquet")
    run_deseq.assert_not_called()


def test_run_rejects_a_design_without_the_contrast_factor(
    deg_params: DEGParams, tmp_path: Path
) -> None:
    counts = _write_counts(
        tmp_path / "counts.tsv",
        {"ENSG00000141736": [1200, 1450, 1350, 120, 95, 110]},
        _SAMPLES,
    )
    design = _write_design(tmp_path / "design.tsv", _SAMPLES, _CONDITIONS, "group")

    with pytest.raises(ValueError, match="not a column of the design") as exc:
        PyDESeq2Runner(deg_params).run(counts, design, tmp_path / "deg" / "results.parquet")

    message = str(exc.value)
    assert "'condition'" in message  # names the missing factor
    assert "group" in message  # …and the columns that are actually there


def test_balanced_design_passes_the_replicate_guard(deg_params: DEGParams, tmp_path: Path) -> None:
    """The guard must not fire on a legitimate 3-vs-3 cohort."""
    gene_ids = ["ENSG00000141736"]
    counts = _write_counts(
        tmp_path / "counts.tsv",
        {gene_ids[0]: [1200, 1450, 1350, 120, 95, 110]},
        _SAMPLES,
    )
    design = _write_design(tmp_path / "design.tsv", _SAMPLES, _CONDITIONS, "condition")

    out = tmp_path / "deg" / "results.parquet"
    with patch.object(PyDESeq2Runner, "_run_pydeseq2", return_value=_fake_results(gene_ids)):
        metrics = PyDESeq2Runner(deg_params).run(counts, design, out)

    assert metrics["n_samples"] == 6
    assert out.exists()

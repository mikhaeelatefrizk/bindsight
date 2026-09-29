# SPDX-License-Identifier: AGPL-3.0-or-later
"""Numerical audit guards: deliberately corrupted tables must fail."""

from pathlib import Path

import numpy as np
import pandas as pd

from bindsight.config import DEGParams
from bindsight.deg.pydeseq2_runner import PyDESeq2Runner
from scripts.validate_real_counts import bh_adjust, compare_tables, compare_values


def test_audit_detects_changed_missingness_and_invalid_values() -> None:
    assert not compare_values([0.1, np.nan], [0.1, 0.2])["passed"]
    assert not compare_values([np.inf], [np.inf])["passed"]
    assert not compare_values([np.nan], [np.nan])["passed"]
    assert not compare_values([], [])["passed"]
    assert not compare_values([0.1], [0.3])["passed"]
    assert compare_values([0.1, np.nan], [0.1, np.nan])["passed"]


def test_bh_reconstruction_uses_monotone_adjustments_in_original_order() -> None:
    np.testing.assert_allclose(
        bh_adjust(np.array([0.03, 0.9, 0.01, 0.04])), [0.0533333333, 0.9, 0.04, 0.0533333333]
    )


def test_contrast_reversal_requires_equal_nondirectional_statistics() -> None:
    frame = pd.DataFrame(
        {
            "log2fc": [2.0],
            "lfc_se": [0.2],
            "stat": [10.0],
            "pvalue": [0.001],
            "padj": [0.02],
            "baseMean": [45.0],
            "significant": [True],
        },
        index=["G1"],
    )
    reversed_frame = frame.copy()
    reversed_frame[["log2fc", "stat"]] *= -1
    assert all(c["passed"] for c in compare_tables(frame, reversed_frame, reverse=True).values())
    reversed_frame.loc["G1", "lfc_se"] = 0.4
    assert not compare_tables(frame, reversed_frame, reverse=True)["lfc_se"]["passed"]


def test_inference_receives_same_observations_after_input_permutation(
    tmp_path: Path, monkeypatch
) -> None:
    samples = ["T3", "N2", "T1", "N3", "T2", "N1"]
    counts = pd.DataFrame(
        [[12, 15, 22, 18, 17, 10], [40, 12, 44, 15, 51, 16]], index=["G2", "G1"], columns=samples
    )
    design = pd.DataFrame(
        {"condition": ["tumor" if s.startswith("T") else "normal" for s in samples]}, index=samples
    )
    design_path = tmp_path / "design.tsv"
    design.to_csv(design_path, sep="\t")
    params = DEGParams(
        design_formula="~ condition",
        contrast=["condition", "tumor", "normal"],
        min_count=0,
        n_cpus=1,
    )
    received = []

    def capture(self, values, metadata):
        received.append((values.copy(), metadata.copy()))
        return pd.DataFrame(
            {
                "log2FoldChange": [0.0, 0.0],
                "lfcSE": [1.0, 1.0],
                "stat": [0.0, 0.0],
                "pvalue": [1.0, 1.0],
                "padj": [1.0, 1.0],
                "baseMean": [10.0, 10.0],
            },
            index=values.index,
        )

    monkeypatch.setattr(PyDESeq2Runner, "_run_pydeseq2", capture)
    for index, table in enumerate([counts, counts.iloc[::-1, ::-1]]):
        path = tmp_path / f"counts-{index}.tsv"
        table.to_csv(path, sep="\t")
        PyDESeq2Runner(params).run(path, design_path, tmp_path / f"result-{index}.parquet")
    pd.testing.assert_frame_equal(received[0][0], received[1][0])
    pd.testing.assert_frame_equal(received[0][1], received[1][1])
    for values, metadata in received:
        assert list(values.columns) == list(metadata.index)
        assert metadata.loc["T1", "condition"] == "tumor"
        assert values.loc["G1", "T1"] == 44

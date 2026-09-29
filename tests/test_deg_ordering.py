# SPDX-License-Identifier: AGPL-3.0-or-later
"""Invariant input representation without asserting estimator order stability."""

from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from bindsight.config import DEGParams
from bindsight.deg.pydeseq2_runner import INPUT_ORDERING_POLICY, PyDESeq2Runner


def _inputs() -> tuple[pd.DataFrame, pd.DataFrame]:
    counts = pd.DataFrame(
        [[15, 21, 34, 45, 68, 91], [7, 14, 8, 22, 9, 32], [3, 1, 5, 2, 4, 6]],
        index=["gene_c", "gene_a", "gene_b"],
        columns=["s1", "s2", "s3", "s4", "s5", "s6"],
    )
    design = pd.DataFrame(
        {
            "patient": ["p1", "p1", "p2", "p2", "p3", "p3"],
            "condition": ["normal", "tumor"] * 3,
            "unused_note": ["a", "b", "c", "d", "e", "f"],
        },
        index=counts.columns,
    )
    return counts, design


def _runner(formula: str = "~ condition") -> PyDESeq2Runner:
    return PyDESeq2Runner(
        DEGParams(
            design_formula=formula,
            contrast=["condition", "tumor", "normal"],
            min_count=0,
            min_replicates=2,
        )
    )


@pytest.mark.parametrize("formula", ["~ condition", "~ patient + condition"])
def test_reordering_and_bijective_sample_renaming_preserve_numerical_input(formula: str) -> None:
    counts, design = _inputs()
    original_counts, original_design = counts.copy(), design.copy()
    runner = _runner(formula)
    expected_counts, expected_design, diagnostics = runner._canonical_input_order(counts, design)
    renamed = dict(zip(counts.columns, ["z", "v", "y", "u", "x", "w"], strict=True))
    permutation = [4, 1, 5, 0, 3, 2]
    shuffled_counts = counts.iloc[::-1, permutation].rename(columns=renamed)
    shuffled_design = design.iloc[[1, 5, 3, 0, 2, 4]].rename(index=renamed)
    actual_counts, actual_design, actual_diagnostics = runner._canonical_input_order(
        shuffled_counts, shuffled_design
    )
    inverse = {value: key for key, value in renamed.items()}
    pd.testing.assert_frame_equal(actual_counts.rename(columns=inverse), expected_counts)
    pd.testing.assert_frame_equal(actual_design.rename(index=inverse), expected_design)
    assert actual_diagnostics == diagnostics
    pd.testing.assert_frame_equal(counts, original_counts)
    pd.testing.assert_frame_equal(design, original_design)


def test_tied_observations_preserve_alignment_without_sample_id_tiebreak() -> None:
    counts, design = _inputs()
    counts.loc[:, "s3"] = counts["s1"]
    # s1/s3 have the same modeled condition and complete count vector.
    runner = _runner()
    first_counts, first_design, _ = runner._canonical_input_order(counts, design)
    second_counts, second_design, _ = runner._canonical_input_order(
        counts.iloc[:, ::-1], design.iloc[::-1]
    )
    np.testing.assert_array_equal(first_counts.to_numpy(), second_counts.to_numpy())
    assert first_design.condition.tolist() == second_design.condition.tolist()
    for ordered_counts, ordered_design in [
        (first_counts, first_design),
        (second_counts, second_design),
    ]:
        assert ordered_counts.columns.tolist() == ordered_design.index.tolist()
        pd.testing.assert_frame_equal(ordered_design, design.loc[ordered_counts.columns])
        pd.testing.assert_frame_equal(
            ordered_counts, counts.loc[:, ordered_counts.columns].sort_index()
        )


def test_only_modeled_covariates_and_numeric_count_values_select_order() -> None:
    counts, design = _inputs()
    design["batch"] = ["a", "b", "a", "b", "a", "b"]
    design["age"] = [41, 52, 41, 52, 41, 52]
    runner = _runner("~ C(batch) + np.log(age) + condition")
    expected, _, diagnostics = runner._canonical_input_order(counts, design)
    changed = design.copy()
    changed["unused_note"] = list(reversed(design.unused_note.tolist()))
    changed["patient"] = ["unmodeled"] * len(changed)
    actual, _, _ = runner._canonical_input_order(counts.astype(float), changed)
    assert expected.columns.tolist() == actual.columns.tolist()
    assert diagnostics["modeled_covariates"] == ["age", "batch", "condition"]
    assert diagnostics["sample_identifiers_used"] is False


def test_run_records_policy_and_keeps_counts_and_metadata_paired(tmp_path: Path) -> None:
    counts, design = _inputs()
    counts_path, design_path = tmp_path / "counts.tsv", tmp_path / "design.tsv"
    counts.to_csv(counts_path, sep="\t")
    design.iloc[::-1].to_csv(design_path, sep="\t")
    fake = pd.DataFrame(
        {
            column: np.ones(len(counts))
            for column in ["log2FoldChange", "lfcSE", "stat", "pvalue", "padj", "baseMean"]
        },
        index=counts.index,
    )
    runner = _runner("~ patient + condition")
    with patch.object(runner, "_run_pydeseq2", return_value=fake) as fit:
        metrics = runner.run(counts_path, design_path, tmp_path / "result.parquet")
    fitted_counts, fitted_design = fit.call_args.args
    assert fitted_counts.columns.tolist() == fitted_design.index.tolist()
    pd.testing.assert_frame_equal(fitted_design, design.loc[fitted_counts.columns])
    pd.testing.assert_frame_equal(fitted_counts, counts.loc[:, fitted_counts.columns].sort_index())
    policy = metrics["fit_diagnostics"]["input_ordering"]
    assert policy["policy"] == INPUT_ORDERING_POLICY
    assert "does not establish backend row-order stability" in policy["limitation"]

# SPDX-License-Identifier: AGPL-3.0-or-later
"""Synthetic unit fixtures protect the real-data comparison's input accounting."""

from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from scripts.compare_deseq2_reference import numeric_comparison, run, validate_table


def table() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "gene_id": ["gene_b", "gene_a", "gene_c"],
            "baseMean": [10.0, 20.0, 30.0],
            "log2fc": [2.0, 0.5, -3.0],
            "lfc_se": [0.2, 0.3, 0.4],
            "stat": [10.0, 1.66, -7.5],
            "pvalue": [0.001, 0.1, 0.002],
            "padj": [0.003, 0.1, 0.003],
            "significant": [True, False, True],
        }
    )


def inputs(
    tmp_path: Path, r: pd.DataFrame, py: pd.DataFrame, *, compressed: bool = False
) -> tuple[Path, Path]:
    reference = tmp_path / "reference"
    reference.mkdir()
    r = r.rename(columns={"log2fc": "log2FoldChange", "lfc_se": "lfcSE"})
    r.to_csv(reference / ("results.tsv.gz" if compressed else "results.tsv"), sep="\t", index=False)
    (reference / "metadata.json").write_text(
        '{"purpose": "synthetic unit fixture"}', encoding="utf-8"
    )
    py_path = tmp_path / "python.parquet"
    py.to_parquet(py_path, index=False)
    return reference, py_path


def test_exact_gene_alignment_and_gzip_hash(tmp_path: Path) -> None:
    r = table()
    py = r.iloc[::-1].copy()
    py.loc[py.gene_id == "gene_a", "significant"] = True
    reference, python_results = inputs(tmp_path, r, py, compressed=True)
    report = run(reference, python_results, tmp_path / "comparison")

    assert report["same_tested_gene_set"] is True
    assert report["n_shared_genes"] == 3
    assert report["numeric"]["log2fc"]["absolute_difference_max"] == 0
    assert report["significance"]["disagree"] == 1
    assert report["significance"]["Python_only"] == 1
    assert report["significance"]["agreement_fraction"] == pytest.approx(2 / 3)
    expected = hashlib.sha256(
        gzip.decompress((reference / "results.tsv.gz").read_bytes())
    ).hexdigest()
    assert report["reference_results_sha256"] == expected
    rows = pd.read_csv(tmp_path / "comparison" / "significance-disagreements.tsv", sep="\t")
    assert rows.gene_id.tolist() == ["gene_a"]


def test_mismatching_gene_sets_fail_without_creating_output(tmp_path: Path) -> None:
    py = table()
    py.loc[0, "gene_id"] = "other_gene"
    reference, python_results = inputs(tmp_path, table(), py)
    output = tmp_path / "comparison"
    with pytest.raises(ValueError, match="Tested gene sets must match exactly"):
        run(reference, python_results, output)
    assert not output.exists()


@pytest.mark.parametrize(
    "bad_ids", [["a", "a", "b"], ["a", " ", "b"], ["a", None, "b"], ["a", " b", "c"], ["a", 1, "b"]]
)
def test_malformed_gene_ids_are_rejected(bad_ids: list[Any]) -> None:
    frame = table()
    frame["gene_id"] = bad_ids
    with pytest.raises(ValueError, match="gene_id"):
        validate_table(frame, "fixture")


@pytest.mark.parametrize("bad_flag", ["False", None, 0])
def test_missing_or_ambiguous_decisions_are_rejected(bad_flag: Any) -> None:
    frame = table()
    frame["significant"] = pd.Series([True, bad_flag, False], dtype=object)
    with pytest.raises(ValueError, match="significant values"):
        validate_table(frame, "fixture")


@pytest.mark.parametrize("directory", [True, False])
def test_existing_output_is_never_overwritten(tmp_path: Path, directory: bool) -> None:
    output = tmp_path / "existing"
    if directory:
        output.mkdir()
        sentinel = output / "comparison.json"
    else:
        sentinel = output
    sentinel.write_text("preserve historical evidence", encoding="utf-8")
    # Reject before reading even nonexistent inputs, preserving every existing byte.
    with pytest.raises(FileExistsError, match="Refusing to overwrite"):
        run(tmp_path / "absent_reference", tmp_path / "absent.parquet", output)
    assert sentinel.read_text(encoding="utf-8") == "preserve historical evidence"


def test_missing_and_zero_probabilities_keep_full_denominator(tmp_path: Path) -> None:
    r, py = table(), table()
    r["pvalue"] = [0.0, np.nan, 0.2]
    py["pvalue"] = [0.0, 0.1, 0.1]
    r["padj"] = py["padj"] = np.nan
    r["baseMean"] = py["baseMean"] = 10.0
    reference, python_results = inputs(tmp_path, r, py)
    report = run(reference, python_results, tmp_path / "comparison")
    raw = report["numeric"]["pvalue"]
    transformed = report["numeric"]["minus_log10_pvalue"]
    assert raw["n_total"] == 3
    assert raw["n_shared_finite"] == 2
    assert raw["missing_in_R_only"] == 1
    assert transformed["n_total"] == 3
    assert transformed["n_shared_finite"] == 1
    assert transformed["n_excluded_nonfinite"] == 2
    assert transformed["R_zero_values"] == transformed["Python_zero_values"] == 1
    assert transformed["R_original_missing"] == 1
    assert transformed["absolute_difference_max"] == pytest.approx(np.log10(2))
    assert report["significance"]["n_compared"] == 3
    assert report["numeric"]["padj"]["missing_in_both"] == 3
    assert report["numeric"]["padj"]["absolute_difference_max"] is None
    assert report["numeric"]["baseMean"]["pearson_correlation"] is None
    assert len(report["largest_p_differences"]) == 2
    assert (
        json.loads((tmp_path / "comparison" / "comparison.json").read_text())["n_shared_genes"] == 3
    )


def test_nonfinite_counts_and_difference_quantiles_are_explicit() -> None:
    result = numeric_comparison(
        pd.Series([0.0, 1.0, 2.0, np.inf, np.nan]),
        pd.Series([1.0, 3.0, 5.0, 4.0, np.nan]),
    )
    assert result["n_total"] == 5
    assert result["n_shared_finite"] == 3
    assert result["n_excluded_nonfinite"] == 2
    assert result["infinite_in_R"] == 1
    assert result["missing_in_both"] == 1
    assert result["absolute_difference_median"] == 2.0
    assert result["absolute_difference_p90"] == pytest.approx(2.8)
    assert result["absolute_difference_max"] == 3.0

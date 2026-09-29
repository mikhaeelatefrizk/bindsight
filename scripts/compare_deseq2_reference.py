# SPDX-License-Identifier: AGPL-3.0-or-later
"""Describe cross-implementation differences, without post-hoc pass thresholds.

All input genes must match exactly. Numeric summaries use jointly finite values;
their denominators and excluded values are reported explicitly. Significance
agreement uses the supplied boolean decisions for every gene, including rows
with missing numerical results. Neither implementation is biological ground truth.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

NUMERIC_COLUMNS = ("baseMean", "log2fc", "lfc_se", "stat", "pvalue", "padj")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def numeric_comparison(a: pd.Series, b: pd.Series) -> dict[str, Any]:
    x, y = a.to_numpy(float), b.to_numpy(float)
    if len(x) != len(y):
        raise ValueError("Numeric comparisons require equally sized, aligned inputs")
    finite = np.isfinite(x) & np.isfinite(y)
    difference = np.abs(x[finite] - y[finite])
    result: dict[str, Any] = {
        "n_total": len(x),
        "n_shared_finite": int(finite.sum()),
        "n_excluded_nonfinite": int((~finite).sum()),
        "missing_in_R_only": int((np.isnan(x) & ~np.isnan(y)).sum()),
        "missing_in_Python_only": int((~np.isnan(x) & np.isnan(y)).sum()),
        "missing_in_both": int((np.isnan(x) & np.isnan(y)).sum()),
        "infinite_in_R": int(np.isinf(x).sum()),
        "infinite_in_Python": int(np.isinf(y).sum()),
        "absolute_difference_median": None,
        "absolute_difference_p90": None,
        "absolute_difference_p95": None,
        "absolute_difference_p99": None,
        "absolute_difference_max": None,
        "pearson_correlation": None,
    }
    if finite.any():
        result.update(
            absolute_difference_median=float(np.median(difference)),
            absolute_difference_p90=float(np.quantile(difference, 0.90)),
            absolute_difference_p95=float(np.quantile(difference, 0.95)),
            absolute_difference_p99=float(np.quantile(difference, 0.99)),
            absolute_difference_max=float(difference.max()),
        )
        if finite.sum() >= 2 and np.ptp(x[finite]) > 0 and np.ptp(y[finite]) > 0:
            correlation = float(np.corrcoef(x[finite], y[finite])[0, 1])
            if np.isfinite(correlation):
                result["pearson_correlation"] = correlation
    return result


def validate_table(frame: pd.DataFrame, label: str) -> pd.DataFrame:
    required = {"gene_id", "significant", *NUMERIC_COLUMNS}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"{label} is missing required columns: {sorted(missing)}")
    if frame.empty:
        raise ValueError(f"{label} has no genes")
    ids = frame["gene_id"]
    valid_ids = ids.map(lambda value: isinstance(value, str) and bool(value.strip()))
    if not valid_ids.all():
        raise ValueError(f"{label} gene_id values must be nonblank, nonmissing strings")
    if not ids.eq(ids.str.strip()).all():
        raise ValueError(f"{label} gene_id values must not contain surrounding whitespace")
    if ids.duplicated().any():
        duplicates = ids.loc[ids.duplicated()].head(5).tolist()
        raise ValueError(f"{label} gene_id values must be unique; examples: {duplicates}")
    if not frame["significant"].map(lambda value: isinstance(value, (bool, np.bool_))).all():
        raise ValueError(f"{label} significant values must be nonmissing booleans")
    result = frame.copy()
    for column in NUMERIC_COLUMNS:
        try:
            result[column] = pd.to_numeric(result[column], errors="raise").astype(float)
        except (TypeError, ValueError) as error:
            raise ValueError(f"{label} {column} must contain numeric or missing values") from error
    result["significant"] = result["significant"].astype(bool)
    return result.set_index("gene_id")


def log_probability_comparison(a: pd.Series, b: pd.Series) -> dict[str, Any]:
    positive_a, positive_b = np.isfinite(a) & (a > 0), np.isfinite(b) & (b > 0)
    # Keep the complete gene index so the excluded denominator cannot disappear.
    result = numeric_comparison(-np.log10(a.where(positive_a)), -np.log10(b.where(positive_b)))
    result["filter"] = (
        "Transform only finite positive values; zeros and other excluded values become missing in this transformed summary. See raw probability summary for original missingness."
    )
    for label, series in (("R", a), ("Python", b)):
        result[f"{label}_zero_values"] = int((series == 0).sum())
        result[f"{label}_negative_values"] = int((series < 0).sum())
        result[f"{label}_original_missing"] = int(series.isna().sum())
        result[f"{label}_original_infinite"] = int(np.isinf(series).sum())
    return result


def run(reference: Path, python_results: Path, out_dir: Path) -> dict[str, Any]:
    """Compare two saved tables and create an exclusively new output directory."""
    if out_dir.exists() or out_dir.is_symlink():
        raise FileExistsError(f"Refusing to overwrite existing output: {out_dir}")
    rpath = reference / "results.tsv"
    if not rpath.exists():
        rpath = reference / "results.tsv.gz"
    reference_bytes = (
        gzip.decompress(rpath.read_bytes()) if rpath.suffix == ".gz" else rpath.read_bytes()
    )
    r = validate_table(
        pd.read_csv(rpath, sep="\t", dtype={"gene_id": str}).rename(
            columns={"log2FoldChange": "log2fc", "lfcSE": "lfc_se"}
        ),
        "R",
    )
    py = validate_table(pd.read_parquet(python_results), "Python")
    r_ids, py_ids = set(r.index), set(py.index)
    if r_ids != py_ids:
        raise ValueError(
            "Tested gene sets must match exactly; "
            f"R-only: {len(r_ids - py_ids)} {sorted(r_ids - py_ids)[:5]}; "
            f"Python-only: {len(py_ids - r_ids)} {sorted(py_ids - r_ids)[:5]}"
        )
    gene_ids = sorted(r_ids)
    r, py = r.loc[gene_ids], py.loc[gene_ids]
    disagree = r.significant != py.significant
    numeric = {column: numeric_comparison(r[column], py[column]) for column in NUMERIC_COLUMNS}
    for column in ("pvalue", "padj"):
        numeric[f"minus_log10_{column}"] = log_probability_comparison(r[column], py[column])
    report: dict[str, Any] = {
        "schema": "bindsight-r-reference-comparison/2",
        "purpose": "Independent implementation comparison, without declaring either implementation biological ground truth or changing tolerances after results",
        "comparison_script_sha256": digest(Path(__file__)),
        "reference_results_sha256": hashlib.sha256(reference_bytes).hexdigest(),
        "reference_file_sha256": digest(rpath),
        "python_results_sha256": digest(python_results),
        "reference_metadata": json.loads((reference / "metadata.json").read_text(encoding="utf-8")),
        "same_tested_gene_set": True,
        "n_shared_genes": len(gene_ids),
        "row_policy": {
            "alignment": "Unique, nonblank string gene IDs and exactly equal full gene sets required; sorted by gene ID; no intersection or gene filtering",
            "numeric": "Each metric uses jointly finite values only, with its full and excluded denominators reported",
            "correlation": "Null when fewer than two jointly finite values, either input is constant, or correlation is nonfinite; high correlation does not establish equivalence",
            "significance": "All input genes, using each table's supplied boolean significant column, including genes with missing p or adjusted p; thresholds are not recomputed",
            "largest_differences": "Top 10 p and top 100 LFC rows with finite absolute differences only; ties retain gene-ID order; JSON nonfinite cells are null",
        },
        "numeric": numeric,
        "significance": {
            "n_compared": len(gene_ids),
            "R": int(r.significant.sum()),
            "Python": int(py.significant.sum()),
            "both": int((r.significant & py.significant).sum()),
            "R_only": int((r.significant & ~py.significant).sum()),
            "Python_only": int((~r.significant & py.significant).sum()),
            "neither": int((~r.significant & ~py.significant).sum()),
            "disagree": int(disagree.sum()),
            "agree": int((~disagree).sum()),
            "agreement_fraction": float((~disagree).mean()),
        },
    }
    paired = r.add_suffix("_R").join(py.add_suffix("_Python"))
    paired["abs_lfc_difference"] = abs(paired.log2fc_R - paired.log2fc_Python)
    paired["abs_se_difference"] = abs(paired.lfc_se_R - paired.lfc_se_Python)
    paired["abs_p_difference"] = abs(paired.pvalue_R - paired.pvalue_Python)
    largest_p = (
        paired.loc[np.isfinite(paired.abs_p_difference)]
        .sort_values("abs_p_difference", ascending=False, kind="stable")
        .head(10)
    )
    largest_lfc = (
        paired.loc[np.isfinite(paired.abs_lfc_difference)]
        .sort_values("abs_lfc_difference", ascending=False, kind="stable")
        .head(100)
    )
    report["largest_p_differences"] = (
        largest_p.reset_index()
        .replace({np.nan: None, np.inf: None, -np.inf: None})
        .to_dict("records")
    )
    serialized = json.dumps(report, indent=2, allow_nan=False) + "\n"
    # Validate and serialize everything before reserving the output directory.
    # exist_ok=False also protects against another writer creating it meanwhile.
    out_dir.mkdir(parents=True, exist_ok=False)
    with (out_dir / "comparison.json").open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(serialized)
    paired.loc[disagree].to_csv(
        out_dir / "significance-disagreements.tsv", sep="\t", mode="x", lineterminator="\n"
    )
    largest_lfc.to_csv(
        out_dir / "largest-lfc-differences.tsv", sep="\t", mode="x", lineterminator="\n"
    )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--r", "--reference", dest="reference", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True, help="New, nonexistent output directory")
    args = parser.parse_args(argv)
    report = run(args.reference, args.python, args.out)
    print(
        json.dumps(
            {
                key: report[key]
                for key in ("same_tested_gene_set", "n_shared_genes", "significance", "numeric")
            },
            indent=2,
            allow_nan=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

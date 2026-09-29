# SPDX-License-Identifier: AGPL-3.0-or-later
"""Check numerical consistency on supplied real counts without generating data.

This is an execution and numerical audit, not biological validation or a comparison
with the independent R DESeq2 implementation. Five fresh fits check repeatability,
contrast reversal, sample-order and sample-identifier invariance. Scalar Wald probabilities and BH
adjustments are independently reconstructed from the resulting tables.
"""

from __future__ import annotations

import argparse
import base64
import gc
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bindsight.config import DEGParams  # noqa: E402
from bindsight.deg.pydeseq2_runner import PyDESeq2Runner  # noqa: E402

RTOL = 1e-6
ATOL = 1e-8
NUMERIC = ["log2fc", "lfc_se", "stat", "pvalue", "padj", "baseMean"]


def digest(path: Path) -> str:
    """Hash an input or artifact without loading the whole file at once."""
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def compare_values(observed: Any, expected: Any) -> dict[str, Any]:
    """Report discrepancies and enforce tolerances chosen before execution."""
    observed = np.asarray(observed, dtype=float)
    expected = np.asarray(expected, dtype=float)
    if observed.shape != expected.shape:
        return {"passed": False, "reason": "different shapes"}
    finite = np.isfinite(observed) & np.isfinite(expected)
    valid = bool(finite.any()) and not (np.isinf(observed).any() or np.isinf(expected).any())
    return {
        "passed": bool(
            valid and np.allclose(observed, expected, rtol=RTOL, atol=ATOL, equal_nan=True)
        ),
        "n_compared": int(finite.sum()),
        "max_absolute_difference": float(np.max(np.abs(observed[finite] - expected[finite])))
        if finite.any()
        else None,
        "missing_mask_equal": bool(np.array_equal(np.isnan(observed), np.isnan(expected))),
    }


def bh_adjust(values: np.ndarray[Any, Any]) -> np.ndarray[Any, Any]:
    """Reconstruct Benjamini-Hochberg without calling the inference library."""
    order = np.argsort(values)
    adjusted = values[order] * len(values) / np.arange(1, len(values) + 1)
    adjusted = np.minimum(1.0, np.minimum.accumulate(adjusted[::-1])[::-1])
    result = np.empty_like(adjusted)
    result[order] = adjusted
    return np.asarray(result, dtype=float)


def audit_table(frame: pd.DataFrame, params: DEGParams) -> dict[str, Any]:
    """Check table arithmetic, preserving independent filtering and missingness."""
    p_rows = frame["pvalue"].notna()
    adjusted_rows = frame["padj"].notna()
    expected_p = [math.erfc(abs(float(s)) / math.sqrt(2)) for s in frame.loc[p_rows, "stat"]]
    expected_sig = (frame["padj"].fillna(1) < params.fdr_threshold) & (
        frame["log2fc"].abs() >= params.log2fc_threshold
    )
    finite_stats = frame["stat"].notna() & frame["lfc_se"].gt(0)
    probabilities = frame.loc[:, ["pvalue", "padj"]]
    return {
        "nonempty_unique_gene_ids": {"passed": bool(len(frame) and frame.index.is_unique)},
        "positive_finite_standard_errors": {
            "passed": bool(
                len(frame) and (np.isfinite(frame["lfc_se"]) & frame["lfc_se"].gt(0)).all()
            )
        },
        "probabilities_in_unit_interval": {
            "passed": bool(
                ((probabilities >= 0) & (probabilities <= 1) | probabilities.isna()).all().all()
            )
        },
        "wald_statistic": compare_values(
            frame.loc[finite_stats, "stat"],
            frame.loc[finite_stats, "log2fc"] / frame.loc[finite_stats, "lfc_se"],
        ),
        "two_sided_wald_probability": compare_values(frame.loc[p_rows, "pvalue"], expected_p),
        "bh_on_independently_retained_genes": compare_values(
            frame.loc[adjusted_rows, "padj"],
            bh_adjust(frame.loc[adjusted_rows, "pvalue"].to_numpy(dtype=float)),
        ),
        "significance_rule": {"passed": bool(frame["significant"].equals(expected_sig))},
    }


def compare_tables(
    left: pd.DataFrame, right: pd.DataFrame, *, reverse: bool = False
) -> dict[str, Any]:
    """Compare the same genes, flipping only directional statistics when asked."""
    if not left.index.equals(right.index):
        return {"gene_ids": {"passed": False}}
    result = {}
    for column in NUMERIC:
        sign = -1 if reverse and column in {"log2fc", "stat"} else 1
        result[column] = compare_values(left[column] * sign, right[column])
    result["significance_decisions"] = {
        "passed": bool(left["significant"].equals(right["significant"])),
        "changed": int((left["significant"] != right["significant"]).sum()),
        "gained": int((~left["significant"] & right["significant"]).sum()),
        "lost": int((left["significant"] & ~right["significant"]).sum()),
    }
    return result


def run(args: argparse.Namespace) -> dict[str, Any]:
    """Fit supplied observations five times, then persist a reviewable audit."""
    counts_path, design_path, config_path = (
        args.counts.resolve(),
        args.design.resolve(),
        args.config.resolve(),
    )
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    settings = dict(config["params"]["deg"])
    settings["n_cpus"] = args.cpus
    params = DEGParams.model_validate(settings)
    counts = PyDESeq2Runner.load_counts(counts_path)
    design = PyDESeq2Runner.load_design(design_path, params.categorical_factors)
    if not counts.index.is_unique or not counts.columns.is_unique or not design.index.is_unique:
        raise ValueError("Validation requires unique gene and sample identifiers")
    if set(counts.columns) != set(design.index):
        raise ValueError("Validation requires identical count and design sample sets")
    # Refuse an existing output directory: a repeat audit must retain the old evidence.
    args.out.mkdir(parents=True, exist_ok=False)
    reordered_counts = args.out / "sample_order_reversed.tsv"
    counts.loc[:, list(reversed(counts.columns))].to_csv(
        reordered_counts, sep="\t", lineterminator="\n"
    )
    # A consistent bijection changes identifiers only, reversing identifier sort.
    # Earlier label-based canonicalization exposed backend row-order sensitivity.
    # The current observation-based policy must preserve numerical input here;
    # passing this wrapper check does not prove backend row-order stability.
    rename = {sample: f"audit-{i:04d}" for i, sample in enumerate(reversed(sorted(counts.columns)))}
    relabelled_counts, relabelled_design = (
        args.out / "relabelled_counts.tsv",
        args.out / "relabelled_design.tsv",
    )
    counts.rename(columns=rename).to_csv(relabelled_counts, sep="\t", lineterminator="\n")
    design.rename(index=rename).to_csv(relabelled_design, sep="\t", lineterminator="\n")
    sources = [
        Path(__file__).resolve(),
        ROOT / "bindsight/deg/pydeseq2_runner.py",
        ROOT / "bindsight/config.py",
        ROOT / "bindsight/deg/inference.py",
    ]
    snapshot = {
        p.relative_to(ROOT).as_posix(): {
            "sha256": digest(p),
            "base64": base64.b64encode(p.read_bytes()).decode("ascii"),
        }
        for p in sources
    }
    (args.out / "source_snapshot.json").write_text(
        json.dumps(snapshot, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    report: dict[str, Any] = {
        "schema": "bindsight-real-counts-validation/1",
        "started_at": datetime.now(UTC).isoformat(),
        "purpose": "Numerical consistency on real supplied observations; not independent biological validation",
        "tolerances": {"relative": RTOL, "absolute": ATOL},
        "inputs": {
            "counts": {"name": counts_path.name, "sha256": digest(counts_path)},
            "design": {"name": design_path.name, "sha256": digest(design_path)},
            "config": {"name": config_path.name, "sha256": digest(config_path)},
        },
        "parameters": params.model_dump(mode="json"),
        "n_input_genes": len(counts),
        "n_samples": len(design),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "versions": {
            name: importlib.metadata.version(name)
            for name in [
                "pydeseq2",
                "numpy",
                "scipy",
                "pandas",
                "pyarrow",
                "formulaic",
                "formulaic-contrasts",
                "anndata",
                "joblib",
                "scikit-learn",
            ]
        },
        "numeric_thread_environment": {
            name: os.environ.get(name)
            for name in ["OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"]
        },
        "git_revision": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "git_working_tree_dirty": subprocess.run(
            ["git", "diff", "--quiet", "HEAD"], cwd=ROOT, check=False
        ).returncode
        != 0,
        "source_sha256": {name: value["sha256"] for name, value in snapshot.items()},
        "source_snapshot_sha256": digest(args.out / "source_snapshot.json"),
        "fits": {},
        "checks": {},
    }
    tables = {}
    for name in [
        "forward",
        "repeat",
        "reverse_contrast",
        "reverse_sample_order",
        "relabel_samples",
    ]:
        print(f"Running {name} with {args.cpus} CPU worker(s)...", flush=True)
        fit_params = params.model_copy(deep=True)
        if name == "reverse_contrast":
            factor, numerator, denominator = fit_params.contrast
            fit_params.contrast = [factor, denominator, numerator]
        source = reordered_counts if name == "reverse_sample_order" else counts_path
        metadata_path = design_path
        if name == "relabel_samples":
            source, metadata_path = relabelled_counts, relabelled_design
        output = args.out / f"{name}.parquet"
        started = time.perf_counter()
        metrics = PyDESeq2Runner(fit_params).run(source, metadata_path, output)
        report["fits"][name] = {
            **metrics,
            "seconds": round(time.perf_counter() - started, 3),
            "sha256": digest(output),
        }
        table = pd.read_parquet(output).set_index("gene_id").sort_index()
        tables[name] = table
        report["checks"][f"{name}_arithmetic"] = audit_table(table, fit_params)
        gc.collect()
    for name in ["repeat", "reverse_contrast", "reverse_sample_order", "relabel_samples"]:
        report["checks"][name] = compare_tables(
            tables["forward"], tables[name], reverse=name == "reverse_contrast"
        )
    report["checks"]["source_stability"] = {
        "unchanged": {
            "passed": all(
                digest(ROOT / name) == value["sha256"] for name, value in snapshot.items()
            )
        }
    }
    report["passed"] = all(
        check["passed"] for group in report["checks"].values() for check in group.values()
    )
    report["finished_at"] = datetime.now(UTC).isoformat()
    return report


def main() -> int:
    """Run only on user-supplied observations, with a bounded CPU default."""
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ["counts", "design", "config", "out"]:
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--cpus", type=int, default=1)
    args = parser.parse_args()
    report = run(args)
    path = args.out / "validation.json"
    path.write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"{'PASS' if report['passed'] else 'FAIL'}: {path}", flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

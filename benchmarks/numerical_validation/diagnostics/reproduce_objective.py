# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Re-evaluate dispersion objectives from a saved real fit without refitting it.

The negative-binomial likelihood is evaluated with scipy.stats.nbinom rather
than PyDESeq2's likelihood function, and its MAP objective is minimized with
scipy.optimize.minimize_scalar. The upstream grid and scalar failure paths are
also evaluated for comparison. This reproduces the objective diagnosis; it is
not a new cohort fit or an independent implementation of the whole pipeline.
"""

from __future__ import annotations

import argparse
import json
from importlib.metadata import version
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from pydeseq2 import utils
from pydeseq2.grid_search import grid_fit_alpha
from scipy.optimize import minimize_scalar
from scipy.stats import nbinom

HERE = Path(__file__).resolve().parent
ORIGINAL = HERE.parent / "results" / "original_three"


def reproduce(saved: Path = HERE, original_directory: Path = ORIGINAL) -> dict[str, Any]:
    """Evaluate the ten largest original sample-order discrepancies."""
    fit = json.loads((saved / "fit.json").read_text(encoding="utf-8"))
    inspected = fit["versions"]["pydeseq2"]
    if inspected != "0.5.4" or version("pydeseq2") != inspected:
        raise RuntimeError("This diagnosis requires the saved PyDESeq2 0.5.4 implementation")
    with np.load(saved / "dds_arrays.npz", allow_pickle=False) as loaded:
        arrays = {name: loaded[name] for name in loaded.files}
    var = pd.read_parquet(saved / "dds_var.parquet")
    results = pd.read_parquet(saved / "results.parquet").rename(
        columns={"log2FoldChange": "log2fc", "lfcSE": "lfc_se"}
    )
    original = pd.read_parquet(original_directory / "forward.parquet").set_index("gene_id")
    reversed_ = pd.read_parquet(original_directory / "reverse_sample_order.parquet").set_index(
        "gene_id"
    )
    difference = (original.pvalue - reversed_.pvalue).abs().sort_values(ascending=False)
    failed = ~var._MAP_converged
    record: dict[str, Any] = {
        "original_forward_exact": bool(
            np.array_equal(
                results.loc[original.index, original.columns[:6]],
                original.iloc[:, :6],
                equal_nan=True,
            )
        ),
        "n_map_failed": int(failed.sum()),
        "n_gene_wise_failed": int((~var._genewise_converged).sum()),
        "n_map_failed_final_used": int((failed & ~var._outlier_genes).sum()),
        "prior_disp_var": fit["uns"]["prior_disp_var"],
        "sources": [
            "https://raw.githubusercontent.com/scverse/PyDESeq2/v0.5.4/pydeseq2/utils.py",
            "https://raw.githubusercontent.com/scverse/PyDESeq2/v0.5.4/pydeseq2/grid_search.py",
            "https://github.com/scverse/PyDESeq2/releases/tag/v0.5.4",
        ],
        "genes": {},
    }
    if not record["original_forward_exact"]:
        raise ValueError("Saved diagnostic fit does not match the original result table")
    for gene in difference.index[:10]:
        i = int(np.flatnonzero(arrays["genes"] == gene)[0])
        arguments: dict[str, Any] = {
            "counts": arrays["counts"][:, i],
            "design_matrix": arrays["design_matrix"],
            "mu": arrays["mu_hat"][:, i],
            "alpha_hat": float(var.loc[gene, "fitted_dispersions"]),
            "min_disp": fit["min_disp"],
            "max_disp": fit["max_disp"],
            "prior_disp_var": record["prior_disp_var"],
            "cr_reg": True,
            "prior_reg": True,
        }
        regularized = float(np.exp(grid_fit_alpha(**arguments)))
        unregularized = float(np.exp(grid_fit_alpha(**(arguments | {"prior_reg": False}))))
        direct, converged = utils.fit_alpha_mle(**arguments)
        reversed_arguments = arguments | {
            k: arguments[k][::-1].copy() for k in ["counts", "design_matrix", "mu"]
        }
        direct_reversed, reversed_converged = utils.fit_alpha_mle(**reversed_arguments)

        def loss(log_alpha: float, args: dict[str, Any] = arguments) -> float:
            alpha = np.exp(log_alpha)
            size = 1 / alpha
            likelihood = -nbinom.logpmf(args["counts"], size, size / (size + args["mu"])).sum()
            weights = args["mu"] / (1 + args["mu"] * alpha)
            cox_reid = (
                0.5
                * np.linalg.slogdet((args["design_matrix"].T * weights) @ args["design_matrix"])[1]
            )
            prior = (log_alpha - np.log(args["alpha_hat"])) ** 2 / (2 * args["prior_disp_var"])
            return float(likelihood + cox_reid + prior)

        reference = minimize_scalar(
            loss,
            bounds=(np.log(arguments["min_disp"]), np.log(arguments["max_disp"])),
            method="bounded",
        )
        record["genes"][gene] = {
            "original_p": float(original.loc[gene, "pvalue"]),
            "reordered_p": float(reversed_.loc[gene, "pvalue"]),
            "map_converged": bool(var.loc[gene, "_MAP_converged"]),
            "outlier_uses_genewise": bool(var.loc[gene, "_outlier_genes"]),
            "saved_final_dispersion": float(var.loc[gene, "dispersions"]),
            "saved_map_dispersion": float(var.loc[gene, "MAP_dispersions"]),
            "unregularized_grid": unregularized,
            "regularized_grid": regularized,
            "independent_map_optimum": float(np.exp(reference.x)),
            "independent_map_optimum_converged": bool(reference.success),
            "map_loss_at_saved": loss(np.log(var.loc[gene, "MAP_dispersions"])),
            "map_loss_at_regularized_grid": loss(np.log(regularized)),
            "map_loss_at_independent_optimum": float(reference.fun),
            "single_gene_original": {"dispersion": float(direct), "converged": bool(converged)},
            "single_gene_reversed": {
                "dispersion": float(direct_reversed),
                "converged": bool(reversed_converged),
            },
        }
    return record


def main() -> int:
    """Write a new comparison artifact while preserving the recorded proof."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path, help="A new, nonexistent JSON file")
    args = parser.parse_args()
    if args.out.exists():
        parser.error("--out already exists; choose a new path to preserve the previous evidence")
    record = reproduce()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(record, indent=2, allow_nan=False) + "\n")
    print(f"Recorded {len(record['genes'])} objective comparisons: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

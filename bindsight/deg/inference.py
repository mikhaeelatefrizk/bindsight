# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Preserve regularization and the mean floor at PyDESeq2 inference boundaries.

Upstream ``utils.fit_alpha_mle`` passes only the first six arguments to
``grid_fit_alpha`` when scipy's optimizer fails. The grid then defaults to no
MAP prior, even when the caller requested one. This adapter uses the supported
inference extension point and repeats only failed grid searches with the actual
regularization settings. Optimizer convergence flags remain unchanged.

PyDESeq2's IRLS solver intentionally returns unthresholded predicted means, but
the dispersion and Wald stages use them without restoring ``min_mu``. R DESeq2
1.52.0 ``R/core.R:estimateDispersionsGeneEst`` floors means before dispersion
estimation. ``src/DESeq2.cpp:fitBeta`` floors means before weights and covariance
(lines 324-326, 431-455 in the official 1.52.0 source archive). Apply that floor
only at these two inference boundaries; retain the inherited IRLS output.

Inspected upstream release: scverse/PyDESeq2 v0.5.4, commit
4426e4db990db1c511de3b1b9b7a514989663dad, ``pydeseq2/utils.py`` and
``pydeseq2/grid_search.py``. This correction does not establish equivalence to
R DESeq2 or independently validate the fitted biological model. R source:
https://bioconductor.org/packages/3.23/bioc/src/contrib/DESeq2_1.52.0.tar.gz
SHA256: 8c91699286336350e66eec132ce6fdf5bb4af78e2a4d015a5a61224f62a95984.
No installed files or module globals are modified.
"""

from __future__ import annotations

from importlib.metadata import version
from typing import Any, Literal

import numpy as np
from pydeseq2.default_inference import DefaultInference
from pydeseq2.grid_search import grid_fit_alpha

TESTED_PYDESEQ2_VERSION = "0.5.4"
DEFAULT_MIN_MU = 0.5
INFERENCE_ADAPTER_REVISION = "pydeseq2-0.5.4-regularization-and-mean-floor-v1"


class RegularizedInference(DefaultInference):  # type: ignore[misc]
    """Restore the mean floor and regularized dispersion fallback objective."""

    def __init__(
        self,
        joblib_verbosity: int = 0,
        batch_size: int = 128,
        n_cpus: int | None = None,
        backend: str = "loky",
        *,
        min_mu: float = DEFAULT_MIN_MU,
    ) -> None:
        installed = version("pydeseq2")
        if installed != TESTED_PYDESEQ2_VERSION:
            raise RuntimeError(
                "The inference corrections are verified only for "
                f"pydeseq2=={TESTED_PYDESEQ2_VERSION}; found {installed}. "
                "Install the pinned scientific environment from envs/constraints.txt "
                "or review the correction against the new upstream release."
            )
        if not np.isfinite(min_mu) or min_mu <= 0:
            raise ValueError("min_mu must be finite and strictly positive")
        self.min_mu = float(min_mu)
        super().__init__(
            joblib_verbosity=joblib_verbosity,
            batch_size=batch_size,
            n_cpus=n_cpus,
            backend=backend,
        )
        self.dispersion_fallback_repairs: list[dict[str, int | bool]] = []
        self.mean_floor_applications: list[dict[str, str | int | float]] = []

    def _floor_mu(self, mu: np.ndarray[Any, Any], stage: str) -> np.ndarray[Any, Any]:
        """Floor a local inference input without changing retained fitted means."""
        n_below = int(np.count_nonzero(mu < self.min_mu))
        self.mean_floor_applications.append(
            {"stage": stage, "min_mu": self.min_mu, "n_values_below_floor": n_below}
        )
        return np.maximum(mu, self.min_mu) if n_below else mu

    def alpha_mle(
        self,
        counts: np.ndarray[Any, Any],
        design_matrix: np.ndarray[Any, Any],
        mu: np.ndarray[Any, Any],
        alpha_hat: np.ndarray[Any, Any],
        min_disp: float,
        max_disp: float,
        prior_disp_var: float | None = None,
        cr_reg: bool = True,
        prior_reg: bool = False,
        optimizer: Literal["BFGS", "L-BFGS-B"] = "L-BFGS-B",
    ) -> tuple[np.ndarray[Any, Any], np.ndarray[Any, Any]]:
        """Floor dispersion means and retain the prior if optimization fails."""
        mu = self._floor_mu(mu, "dispersion")
        estimates, converged = super().alpha_mle(
            counts=counts,
            design_matrix=design_matrix,
            mu=mu,
            alpha_hat=alpha_hat,
            min_disp=min_disp,
            max_disp=max_disp,
            prior_disp_var=prior_disp_var,
            cr_reg=cr_reg,
            prior_reg=prior_reg,
            optimizer=optimizer,
        )
        failed = np.flatnonzero(~np.asarray(converged, dtype=bool))
        self.dispersion_fallback_repairs.append(
            {"n_failed": len(failed), "cr_reg": cr_reg, "prior_reg": prior_reg}
        )
        if len(failed):
            estimates = estimates.copy()
            for i in failed:
                estimates[i] = np.exp(
                    grid_fit_alpha(
                        counts=counts[:, i],
                        design_matrix=design_matrix,
                        mu=mu[:, i],
                        alpha_hat=alpha_hat[i],
                        min_disp=min_disp,
                        max_disp=max_disp,
                        prior_disp_var=prior_disp_var,
                        cr_reg=cr_reg,
                        prior_reg=prior_reg,
                    )
                )
        return np.asarray(estimates), np.asarray(converged)

    def wald_test(
        self,
        design_matrix: np.ndarray[Any, Any],
        disp: np.ndarray[Any, Any],
        lfc: np.ndarray[Any, Any],
        mu: np.ndarray[Any, Any],
        ridge_factor: np.ndarray[Any, Any],
        contrast: np.ndarray[Any, Any],
        lfc_null: float | np.ndarray[Any, Any],
        alt_hypothesis: Literal["greaterAbs", "lessAbs", "greater", "less"] | None = None,
    ) -> tuple[np.ndarray[Any, Any], np.ndarray[Any, Any], np.ndarray[Any, Any]]:
        """Use the configured minimum mean in Wald covariance weights."""
        pvalues, statistics, standard_errors = super().wald_test(
            design_matrix=design_matrix,
            disp=disp,
            lfc=lfc,
            mu=self._floor_mu(mu, "wald"),
            ridge_factor=ridge_factor,
            contrast=contrast,
            lfc_null=lfc_null,
            alt_hypothesis=alt_hypothesis,
        )
        return np.asarray(pvalues), np.asarray(statistics), np.asarray(standard_errors)

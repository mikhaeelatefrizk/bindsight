# SPDX-License-Identifier: AGPL-3.0-or-later
"""Regression checks for the upstream dispersion fallback objective."""

from __future__ import annotations

import math
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

pytest.importorskip("pydeseq2")

from pydeseq2 import utils
from scipy.optimize import minimize_scalar
from scipy.stats import nbinom

from bindsight.deg import inference


def arguments():
    design = np.column_stack([np.ones(6), [0, 0, 0, 1, 1, 1]])
    counts = np.array([[18, 18], [20, 20], [19, 19], [25, 25], [27, 27], [23, 23]])
    mu = np.array([[19, 19], [19, 19], [19, 19], [25, 25], [25, 25], [25, 25]])
    return {
        "counts": counts,
        "design_matrix": design,
        "mu": mu,
        "alpha_hat": np.array([0.4, 0.4]),
        "min_disp": 1e-8,
        "max_disp": 10.0,
        "prior_disp_var": 0.25,
        "cr_reg": True,
        "prior_reg": True,
    }


def test_failed_map_grid_preserves_prior_objective(monkeypatch):
    """Forced failure must minimize the MAP loss, not unregularized likelihood."""
    args = arguments()
    previous = np.array([0.07, 1e-8])
    converged = np.array([True, False])
    superclass = Mock(return_value=(previous, converged))
    monkeypatch.setattr(inference.DefaultInference, "alpha_mle", superclass)
    adapter = inference.RegularizedInference(n_cpus=1)
    estimates, flags = adapter.alpha_mle(**args)

    y = args["counts"][:, 1]
    mu = args["mu"][:, 1]
    design = args["design_matrix"]

    def map_loss(log_alpha):
        alpha = np.exp(log_alpha)
        size = 1 / alpha
        likelihood = -nbinom.logpmf(y, size, size / (size + mu)).sum()
        weights = mu / (1 + mu * alpha)
        cox_reid = 0.5 * np.linalg.slogdet((design.T * weights) @ design)[1]
        prior = (log_alpha - np.log(0.4)) ** 2 / (2 * 0.25)
        return likelihood + cox_reid + prior

    reference = minimize_scalar(map_loss, bounds=(np.log(1e-8), np.log(10)), method="bounded")
    assert reference.success
    # The upstream two-stage grid is approximate; compare its objective with an
    # independently evaluated scalar optimum, not with the same grid function.
    assert abs(np.log(estimates[1]) - reference.x) < 0.01
    assert map_loss(np.log(estimates[1])) < map_loss(np.log(previous[1])) - 100
    assert estimates[0] == previous[0]
    np.testing.assert_array_equal(previous, [0.07, 1e-8])
    np.testing.assert_array_equal(flags, [True, False])
    assert adapter.dispersion_fallback_repairs == [
        {"n_failed": 1, "cr_reg": True, "prior_reg": True}
    ]
    superclass.assert_called_once_with(**args, optimizer="L-BFGS-B")


def test_real_upstream_failure_path_drops_prior_but_adapter_preserves_it(monkeypatch):
    """Exercise the actual 0.5.4 failure branch, without replacing alpha_mle."""
    monkeypatch.setattr(utils, "minimize", lambda *args, **kwargs: SimpleNamespace(success=False))
    args = arguments()
    upstream, upstream_flags = inference.DefaultInference(n_cpus=1).alpha_mle(**args)
    corrected, corrected_flags = inference.RegularizedInference(n_cpus=1).alpha_mle(**args)
    assert np.all(upstream < 1e-5)
    assert np.all(corrected > 0.1)
    np.testing.assert_array_equal(upstream_flags, [False, False])
    np.testing.assert_array_equal(corrected_flags, upstream_flags)


@pytest.mark.parametrize(("cr_reg", "prior_reg"), [(False, False), (True, True)])
def test_failed_fallback_forwards_requested_regularization(monkeypatch, cr_reg, prior_reg):
    args = arguments() | {"cr_reg": cr_reg, "prior_reg": prior_reg}
    monkeypatch.setattr(
        inference.DefaultInference,
        "alpha_mle",
        Mock(return_value=(np.array([0.1, 0.2]), np.array([True, False]))),
    )
    grid = Mock(return_value=np.log(0.3))
    monkeypatch.setattr(inference, "grid_fit_alpha", grid)
    result, flags = inference.RegularizedInference(n_cpus=1).alpha_mle(**args)
    assert result == pytest.approx([0.1, 0.3])
    np.testing.assert_array_equal(flags, [True, False])
    kwargs = grid.call_args.kwargs
    assert grid.call_count == 1
    assert kwargs["cr_reg"] is cr_reg
    assert kwargs["prior_reg"] is prior_reg
    assert kwargs["prior_disp_var"] == args["prior_disp_var"]
    assert kwargs["alpha_hat"] == args["alpha_hat"][1]
    np.testing.assert_array_equal(kwargs["counts"], args["counts"][:, 1])


def test_successful_upstream_fits_do_not_run_grid(monkeypatch):
    values = np.array([0.1, 0.2])
    flags = np.array([True, True])
    monkeypatch.setattr(inference.DefaultInference, "alpha_mle", Mock(return_value=(values, flags)))
    grid = Mock(side_effect=AssertionError("successful fits must remain unchanged"))
    monkeypatch.setattr(inference, "grid_fit_alpha", grid)
    actual, converged = inference.RegularizedInference(n_cpus=1).alpha_mle(**arguments())
    np.testing.assert_array_equal(actual, values)
    np.testing.assert_array_equal(converged, flags)
    grid.assert_not_called()


def test_unknown_pydeseq2_version_is_not_silently_adapted(monkeypatch):
    monkeypatch.setattr(inference, "version", lambda name: "0.5.5")
    with pytest.raises(RuntimeError, match=r"verified only for pydeseq2==0\.5\.4"):
        inference.RegularizedInference(n_cpus=1)


@pytest.mark.parametrize("min_mu", [0.5, 1.0])
def test_dispersion_mean_floor_reaches_optimizer_and_fallback_without_mutation(monkeypatch, min_mu):
    args = arguments()
    original_mu = np.array([[0.01, 0.1], [0.2, 0.3], [0.5, 1], [2, 2], [3, 3], [4, 4]])
    unchanged = original_mu.copy()
    args["mu"] = original_mu
    superclass = Mock(return_value=(np.array([0.1, 0.2]), np.array([True, False])))
    monkeypatch.setattr(inference.DefaultInference, "alpha_mle", superclass)
    grid = Mock(return_value=np.log(0.3))
    monkeypatch.setattr(inference, "grid_fit_alpha", grid)
    inference.RegularizedInference(n_cpus=1, min_mu=min_mu).alpha_mle(**args)
    np.testing.assert_array_equal(superclass.call_args.kwargs["mu"], np.maximum(unchanged, min_mu))
    np.testing.assert_array_equal(grid.call_args.kwargs["mu"], np.maximum(unchanged[:, 1], min_mu))
    np.testing.assert_array_equal(original_mu, unchanged)


def test_sparse_dispersion_fallback_matches_independent_floored_map_objective(monkeypatch):
    monkeypatch.setattr(utils, "minimize", lambda *args, **kwargs: SimpleNamespace(success=False))
    design = np.column_stack([np.ones(6), [0, 0, 0, 1, 1, 1]])
    counts = np.array([0, 0, 1, 1, 3, 2])
    means = np.array([0.02, 0.1, 0.4, 0.5, 2, 3])
    fitted, flags = inference.RegularizedInference(n_cpus=1).alpha_mle(
        counts=counts[:, None],
        design_matrix=design,
        mu=means[:, None],
        alpha_hat=np.array([0.4]),
        min_disp=1e-8,
        max_disp=10,
        prior_disp_var=0.25,
        cr_reg=True,
        prior_reg=True,
    )

    def loss(log_alpha):
        alpha = np.exp(log_alpha)
        floored = np.maximum(means, 0.5)
        weights = floored / (1 + alpha * floored)
        return (
            -nbinom.logpmf(counts, 1 / alpha, 1 / (1 + alpha * floored)).sum()
            + 0.5 * np.linalg.slogdet((design.T * weights) @ design)[1]
            + (log_alpha - np.log(0.4)) ** 2 / (2 * 0.25)
        )

    reference = minimize_scalar(loss, bounds=(np.log(1e-8), np.log(10)), method="bounded")
    assert reference.success
    assert abs(np.log(fitted[0]) - reference.x) < 0.01
    assert not flags[0]
    np.testing.assert_array_equal(means, [0.02, 0.1, 0.4, 0.5, 2, 3])


def test_wald_floor_matches_independent_covariance_formula():
    design = np.column_stack([np.ones(6), [0, 0, 0, 1, 1, 1]])
    means = np.array([0.02, 0.1, 0.4, 0.5, 2, 3])
    coefficients = np.array([0.2, 0.3])
    contrast = np.array([0.0, 1.0])
    ridge = np.eye(2) * 1e-6
    alpha = 0.4
    adapter = inference.RegularizedInference(n_cpus=1)
    pvalues, statistics, errors = adapter.wald_test(
        design_matrix=design,
        disp=np.array([alpha]),
        lfc=coefficients[None, :],
        mu=means[:, None],
        ridge_factor=ridge,
        contrast=contrast,
        lfc_null=0.0,
    )
    # Independently assemble X'WX and the ridge sandwich covariance from the
    # explicitly floored means used by R's fitBeta, rather than reuse utils.wald_test.
    weights = np.diag(1 / (1 / np.maximum(means, 0.5) + alpha))
    information = design.T @ weights @ design
    inverse = np.linalg.inv(information + ridge)
    covariance = inverse @ information @ inverse
    expected_se = float(np.sqrt(contrast @ covariance @ contrast))
    expected_stat = float((contrast @ coefficients) / expected_se)
    expected_p = math.erfc(abs(expected_stat) / math.sqrt(2))
    assert errors[0] == pytest.approx(expected_se, rel=1e-12)
    assert statistics[0] == pytest.approx(expected_stat, rel=1e-12)
    assert pvalues[0] == pytest.approx(expected_p, rel=1e-12)
    np.testing.assert_array_equal(means, [0.02, 0.1, 0.4, 0.5, 2, 3])
    assert adapter.mean_floor_applications == [
        {"stage": "wald", "min_mu": 0.5, "n_values_below_floor": 3}
    ]


@pytest.mark.parametrize("min_mu", [0.0, -1.0, np.nan, np.inf])
def test_invalid_mean_floor_is_rejected(min_mu):
    with pytest.raises(ValueError, match="finite and strictly positive"):
        inference.RegularizedInference(n_cpus=1, min_mu=min_mu)


def test_raw_irls_behavior_remains_inherited():
    assert inference.RegularizedInference.irls is inference.DefaultInference.irls

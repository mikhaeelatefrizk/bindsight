# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the GPU cost estimator."""

from __future__ import annotations

import pytest

from bindsight.cost import (
    GPU_PRICE_USD_PER_HOUR,
    PRICE_TABLE_VERSION,
    estimate,
    estimate_full_run,
)


def test_price_table_version_is_set() -> None:
    assert PRICE_TABLE_VERSION
    assert "." in PRICE_TABLE_VERSION


def test_modal_a100_known_price() -> None:
    """Pin Modal A100-40GB price; bumping requires updating the test on purpose."""
    assert GPU_PRICE_USD_PER_HOUR[("modal", "A100-40GB")] == pytest.approx(3.09)


def test_free_tier_backends_are_zero() -> None:
    for be in ("colab", "kaggle", "local_docker", "mock"):
        for gpu_type in ("T4", "P100", "A100-40GB", "RTX4090", "mock"):
            key = (be, gpu_type)
            if key in GPU_PRICE_USD_PER_HOUR:
                price = GPU_PRICE_USD_PER_HOUR[key]
                # colab pro A100 is the one paid colab option
                if (be, gpu_type) != ("colab", "A100-40GB"):
                    assert price == pytest.approx(0.0), f"{key} should be free"


# ---------------------------------------------------------------------------
# estimate() — design
# ---------------------------------------------------------------------------
def test_estimate_design_modal_a100_rfdiff() -> None:
    """5 targets × 50 trajectories of rfdiff_mpnn on Modal A100 ≈ 5–10 USD."""
    e = estimate(backend="modal", stage="design", plugin="rfdiff_mpnn", n_units=250)
    # 250 units × 45s/unit / 3600 = 3.125 hr. × $3.09/hr ≈ $9.66
    assert 5.0 < (e.usd_estimate or 0.0) < 15.0
    assert e.gpu_hours > 0
    assert e.gpu_type == "A100-40GB"


def test_estimate_design_colab_t4_is_free() -> None:
    e = estimate(backend="colab", stage="design", plugin="rfdiff_mpnn", n_units=10)
    assert e.usd_estimate == pytest.approx(0.0)
    # T4 is 4× slower than A100 reference.
    assert e.gpu_hours > 0


def test_estimate_design_bindcraft_more_expensive_than_rfdiff() -> None:
    """BindCraft is ~5× slower per trajectory than RFdiff+MPNN."""
    rfdiff = estimate(backend="modal", stage="design", plugin="rfdiff_mpnn", n_units=10)
    bind = estimate(backend="modal", stage="design", plugin="bindcraft", n_units=10)
    assert (bind.usd_estimate or 0) > (rfdiff.usd_estimate or 0)


# ---------------------------------------------------------------------------
# estimate() — validate
# ---------------------------------------------------------------------------
def test_estimate_validate_boltz2_modal() -> None:
    e = estimate(backend="modal", stage="validate", plugin="boltz2", n_units=250)
    # 250 × 20s / 3600 = 1.39 hr × $3.09 ≈ $4.29
    assert 2.0 < (e.usd_estimate or 0.0) < 10.0


def test_estimate_validate_af2_ig_slower() -> None:
    boltz = estimate(backend="modal", stage="validate", plugin="boltz2", n_units=10)
    af2 = estimate(backend="modal", stage="validate", plugin="af2_ig", n_units=10)
    assert (af2.usd_estimate or 0) > (boltz.usd_estimate or 0)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
def test_estimate_unknown_backend_raises() -> None:
    with pytest.raises(ValueError, match="unknown backend"):
        estimate(backend="aws_lol", stage="design", plugin="rfdiff_mpnn", n_units=1)


def test_estimate_unknown_designer_raises() -> None:
    with pytest.raises(ValueError, match="unknown design plugin"):
        estimate(backend="modal", stage="design", plugin="not_a_designer", n_units=1)


def test_estimate_unknown_validator_raises() -> None:
    with pytest.raises(ValueError, match="unknown validate plugin"):
        estimate(backend="modal", stage="validate", plugin="not_a_validator", n_units=1)


def test_estimate_unknown_gpu_raises() -> None:
    with pytest.raises(ValueError, match="unknown GPU type"):
        estimate(
            backend="modal",
            stage="design",
            plugin="rfdiff_mpnn",
            n_units=1,
            gpu_type="GTX1080",
        )


# ---------------------------------------------------------------------------
# Mock backend always free + zero hours
# ---------------------------------------------------------------------------
def test_mock_backend_is_zero_cost() -> None:
    e = estimate(backend="mock", stage="design", plugin="rfdiff_mpnn", n_units=1000)
    assert e.usd_estimate == pytest.approx(0.0)
    assert e.gpu_hours == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# estimate_full_run
# ---------------------------------------------------------------------------
def test_estimate_full_run_combines() -> None:
    d, v, c = estimate_full_run(
        backend="modal",
        designer="rfdiff_mpnn",
        validator="boltz2",
        n_targets=5,
        n_trajectories=50,
    )
    assert c.gpu_hours == pytest.approx(d.gpu_hours + v.gpu_hours)
    assert (c.usd_estimate or 0) == pytest.approx((d.usd_estimate or 0) + (v.usd_estimate or 0))
    # 5 targets × 50 trajectories total; should be in the $20-50 range on Modal A100.
    assert 5.0 < (c.usd_estimate or 0) < 50.0


def test_estimate_full_run_local_docker_is_free() -> None:
    _d, _v, c = estimate_full_run(
        backend="local_docker",
        designer="rfdiff_mpnn",
        validator="boltz2",
        n_targets=5,
        n_trajectories=50,
    )
    assert c.usd_estimate == pytest.approx(0.0)

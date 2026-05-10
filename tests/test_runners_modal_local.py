"""Tests for Modal + LocalDocker + Kaggle runner stubs."""

from __future__ import annotations

from pathlib import Path

import pytest

from xpr2bind.runners.kaggle import KaggleRunner
from xpr2bind.runners.local_docker import LocalDockerRunner
from xpr2bind.runners.modal_runner import ModalRunner


def test_modal_cost_estimate_works_today() -> None:
    """Cost estimator works for Modal even though live submit is v0.1.0-rc2."""
    r = ModalRunner(designer="rfdiff_mpnn", gpu_type="A100-40GB")
    cost = r.estimate_cost(spec_size=50)
    assert cost.backend == "modal"
    assert cost.gpu_type == "A100-40GB"
    assert (cost.usd_estimate or 0) > 0


def test_modal_submit_raises_in_v0_0_x(tmp_path: Path) -> None:
    r = ModalRunner()
    with pytest.raises(NotImplementedError, match=r"v0\.1\.0-rc2"):
        r.submit(tmp_path / "spec.json", results_dir=tmp_path / "r")


def test_local_docker_cost_is_free() -> None:
    r = LocalDockerRunner(gpu_type="A100-40GB")
    cost = r.estimate_cost(spec_size=100)
    assert cost.usd_estimate == pytest.approx(0.0)


def test_local_docker_submit_returns_handle_with_instructions(tmp_path: Path) -> None:
    """Submit returns a handle (does not raise) so users can see the docker command."""
    r = LocalDockerRunner()
    handle = r.submit(tmp_path / "spec.json", results_dir=tmp_path / "r")
    assert handle.backend == "local_docker"


def test_kaggle_cost_is_free() -> None:
    r = KaggleRunner()
    cost = r.estimate_cost(spec_size=50)
    assert cost.usd_estimate == pytest.approx(0.0)

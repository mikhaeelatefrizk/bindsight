"""Tests for the Modal + LocalDocker + Kaggle runners (real, CPU-only seams)."""

from __future__ import annotations

import sys
import tarfile
from pathlib import Path

import pytest

from bindsight.runners.kaggle import KaggleRunner
from bindsight.runners.local_docker import LocalDockerRunner
from bindsight.runners.modal_runner import ModalRunner


# ---------------------------------------------------------------------------
# Cost estimates (work without a GPU)
# ---------------------------------------------------------------------------
def test_modal_cost_estimate() -> None:
    r = ModalRunner(designer="rfdiff_mpnn", gpu_type="A100-40GB")
    cost = r.estimate_cost(spec_size=50)
    assert cost.backend == "modal"
    assert cost.gpu_type == "A100-40GB"
    assert (cost.usd_estimate or 0) > 0


def test_local_docker_cost_is_free() -> None:
    r = LocalDockerRunner(gpu_type="A100-40GB")
    assert r.estimate_cost(spec_size=100).usd_estimate == pytest.approx(0.0)


def test_kaggle_cost_is_free() -> None:
    assert KaggleRunner().estimate_cost(spec_size=50).usd_estimate == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Guards: clean error when the optional client isn't installed
# ---------------------------------------------------------------------------
def test_modal_guard_raises_clean_error_without_modal(monkeypatch, tmp_path) -> None:
    """ModalRunner.submit raises a clear 'install the runners extra' error."""
    monkeypatch.setitem(sys.modules, "modal", None)  # force ImportError on `import modal`
    spec = tmp_path / "spec.json"
    spec.write_text("{}")
    r = ModalRunner()
    with pytest.raises(RuntimeError, match=r"runners.*extra"):
        r.submit(spec, results_dir=tmp_path / "r")


def test_kaggle_guard_raises_clean_error_without_kaggle(monkeypatch, tmp_path) -> None:
    monkeypatch.setitem(sys.modules, "kaggle", None)
    monkeypatch.setitem(sys.modules, "kaggle.api", None)
    r = KaggleRunner()
    with pytest.raises(RuntimeError, match=r"runners.*extra"):
        r.submit(tmp_path / "spec.json", results_dir=tmp_path / "r")


# ---------------------------------------------------------------------------
# LocalDocker native mode — real submit/poll/fetch with job_exec mocked
# ---------------------------------------------------------------------------
def test_local_docker_native_e2e(tmp_path: Path, monkeypatch) -> None:
    """Native mode runs `python -m bindsight.runners.job_exec`; here that's a
    tiny stub that writes a results tarball, so submit→fetch round-trips."""
    spec_dir = tmp_path / "spec"
    spec_dir.mkdir()
    (spec_dir / "spec.json").write_text("{}")
    results = tmp_path / "results"

    real_popen = __import__("subprocess").Popen

    def fake_popen(cmd, *a, **k):
        # cmd: [python, -m, bindsight.runners.job_exec, <spec>, <out.tar.gz>]
        assert cmd[1:3] == ["-m", "bindsight.runners.job_exec"]
        out = Path(cmd[4])
        out.parent.mkdir(parents=True, exist_ok=True)
        with tarfile.open(out, "w:gz") as tf:
            marker = out.parent / "metrics.jsonl"
            marker.write_text('{"binder_id":"b0"}\n')
            tf.add(marker, arcname="metrics.jsonl")
        # a trivially-finished real process
        return real_popen([sys.executable, "-c", "pass"])

    monkeypatch.setattr("bindsight.runners.local_docker.subprocess.Popen", fake_popen)
    r = LocalDockerRunner(native=True)
    handle = r.submit(spec_dir / "spec.json", results_dir=results)
    assert handle.backend == "local_docker"
    out = r.fetch(handle)
    assert out.exists()
    assert r.poll(handle).state == "succeeded"


def test_local_docker_missing_docker_binary(tmp_path: Path, monkeypatch) -> None:
    """Docker mode surfaces a clean error when the docker binary is absent."""

    def boom(*a, **k):
        raise FileNotFoundError("docker")

    monkeypatch.setattr("bindsight.runners.local_docker.subprocess.Popen", boom)
    r = LocalDockerRunner(native=False)
    with pytest.raises(RuntimeError, match="docker not found"):
        r.submit(tmp_path / "spec.json", results_dir=tmp_path / "r")

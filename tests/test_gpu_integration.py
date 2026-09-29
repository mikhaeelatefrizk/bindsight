# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Offline regression checks for GPU plumbing, never model execution."""

from __future__ import annotations

import json
from contextlib import nullcontext
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from bindsight import cli, plugins
from bindsight.runners import boltz_compat, job_exec, modal_runner, tools
from bindsight.runners.local_docker import LocalDockerRunner


def _upstream_predict(model: str = "boltz2") -> dict[str, object]:
    # The exact pinned upstream expression checked by the compatibility shim.
    return dict(precision=32 if model == "boltz1" else "bf16-mixed")


def _torch(capability: tuple[int, int], *, available: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        cuda=SimpleNamespace(
            is_available=lambda: available,
            device_count=lambda: 1,
            get_device_capability=lambda index: capability,
        )
    )


def _boltz() -> SimpleNamespace:
    return SimpleNamespace(predict=SimpleNamespace(callback=_upstream_predict), Trainer=Mock())


def test_turing_uses_fp32_without_changing_other_trainer_settings() -> None:
    module = _boltz()
    trainer = module.Trainer
    assert boltz_compat.configure_precision(module, _torch((7, 5)), boltz_version="2.0.3") == "32"
    module.Trainer(precision="bf16-mixed", accelerator="gpu", devices=1)
    trainer.assert_called_once_with(precision=32, accelerator="gpu", devices=1)


def test_ampere_keeps_upstream_trainer() -> None:
    module = _boltz()
    trainer = module.Trainer
    assert (
        boltz_compat.configure_precision(module, _torch((8, 0)), boltz_version="2.0.3")
        == "bf16-mixed"
    )
    assert module.Trainer is trainer


def test_boltz_compatibility_refuses_unknown_version_or_source() -> None:
    with pytest.raises(RuntimeError, match="requires boltz=="):
        boltz_compat.configure_precision(_boltz(), _torch((7, 5)), boltz_version="2.0.4")
    changed = _boltz()
    changed.predict.callback = lambda: None
    with pytest.raises(RuntimeError, match="differs"):
        boltz_compat.configure_precision(changed, _torch((7, 5)), boltz_version="2.0.3")


def test_boltz_compatibility_reports_cpu_torch_before_prediction() -> None:
    with pytest.raises(RuntimeError, match="CUDA-enabled PyTorch"):
        boltz_compat.configure_precision(
            _boltz(), _torch((7, 5), available=False), boltz_version="2.0.3"
        )


def test_separate_boltz_interpreter_keeps_compatibility_shim(monkeypatch) -> None:
    monkeypatch.delenv("BINDSIGHT_BOLTZ_BIN", raising=False)
    monkeypatch.setenv("BINDSIGHT_BOLTZ_PYTHON", "/opt/boltz/bin/python")
    command = tools.build_boltz_cmd(yaml_path=Path("input.yaml"), out_dir=Path("out"))
    assert command[:4] == [
        "/opt/boltz/bin/python",
        "-m",
        "bindsight.runners.boltz_compat",
        "predict",
    ]


def test_default_cpu_image_is_refused_before_launch(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("BINDSIGHT_LOCAL_NATIVE", raising=False)
    monkeypatch.delenv("BINDSIGHT_LOCAL_IMAGE", raising=False)
    launch = Mock(side_effect=AssertionError("must not launch a CPU image"))
    monkeypatch.setattr("bindsight.runners.local_docker.subprocess.Popen", launch)
    for plugin in ("rfdiff_mpnn", "boltz2"):
        verdict, reason = plugins.plugin_support("local_docker", plugin)
        assert verdict == plugins.UNSUPPORTED
        assert "CPU-only" in reason
    with pytest.raises(RuntimeError, match="CPU-only"):
        LocalDockerRunner().submit(tmp_path / "spec.json", results_dir=tmp_path / "out")
    launch.assert_not_called()
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("mode", ["native", "custom_image"])
def test_explicit_local_environment_is_untested_not_claimed_ready(monkeypatch, mode) -> None:
    monkeypatch.delenv("BINDSIGHT_LOCAL_NATIVE", raising=False)
    monkeypatch.delenv("BINDSIGHT_LOCAL_IMAGE", raising=False)
    if mode == "native":
        monkeypatch.setenv("BINDSIGHT_LOCAL_NATIVE", "1")
    else:
        monkeypatch.setenv("BINDSIGHT_LOCAL_IMAGE", "example.invalid/cuda:pinned")
    assert LocalDockerRunner().configuration_issue() is None
    assert plugins.plugin_support("local_docker", "boltz2")[0] == plugins.UNTESTED


@pytest.mark.parametrize("preexisting", [False, True])
def test_native_setup_installs_se3_package_into_design_interpreter(
    tmp_path, monkeypatch, preexisting
) -> None:
    calls = []
    if preexisting:
        (tmp_path / "RFdiffusion").mkdir()

    def clone(repo, commit, destination):
        destination.mkdir(parents=True, exist_ok=True)
        if destination.name == "RFdiffusion":
            req = destination / "env/SE3Transformer/requirements.txt"
            req.parent.mkdir(parents=True, exist_ok=True)
            req.write_text("e3nn==0.3.3\n", encoding="utf-8")
        return destination

    monkeypatch.setattr(job_exec, "_git_clone", clone)
    monkeypatch.setattr(job_exec, "_verify_checkpoint", lambda *args: "hash")

    def run(command):
        calls.append(command)
        if "-c" in command:
            raise RuntimeError("previous setup left se3_transformer missing")

    monkeypatch.setattr(job_exec, "_run", run)
    monkeypatch.setenv("BINDSIGHT_DESIGN_PYTHON", "/opt/se3/bin/python")
    job_exec._ensure_rfdiff_mpnn(tmp_path)
    installs = [command for command in calls if "pip" in command]
    assert len(installs) == 3
    assert all(command[0] == "/opt/se3/bin/python" for command in installs)
    assert installs[1][-1] == str(tmp_path / "RFdiffusion/env/SE3Transformer")
    assert "--no-deps" in installs[1]


@pytest.mark.parametrize("mode", ["design", "revalidate"])
def test_selected_gpu_reaches_the_runner(tmp_path, monkeypatch, mode) -> None:
    (tmp_path / "config.yaml").write_text(
        "params:\n  design:\n    gpu_type: T4\n", encoding="utf-8"
    )
    monkeypatch.setattr(cli, "_top_targets", lambda run: [{}])
    monkeypatch.setattr(cli, "_design_spec_params_from_run", lambda run: (42, 50, 100))
    monkeypatch.setattr(cli, "_working_tree_wheel", lambda *args: None)
    monkeypatch.setattr(plugins, "get_designer", lambda name: object())
    captured = {}

    def get_runner(name, **kwargs):
        captured.update(kwargs)
        raise RuntimeError("stop before submission")

    monkeypatch.setattr(plugins, "get_runner", get_runner)
    if mode == "design":
        launch = partial(
            cli._launch_design,
            tmp_path,
            backend="modal",
            designer="rfdiff_mpnn",
            validator="boltz2",
            trajectories=1,
        )
    else:
        launch = partial(cli._launch_revalidate, tmp_path, backend="modal", validator="boltz2")
    with pytest.raises(RuntimeError, match="stop before submission"):
        launch()
    assert captured["gpu_type"] == "T4"


def test_backends_refuse_a_gpu_selection_they_would_silently_replace() -> None:
    from bindsight.runners.kaggle import KaggleRunner

    with pytest.raises(ValueError, match="requests a T4"):
        KaggleRunner(gpu_type="A100-40GB")
    with pytest.raises(ValueError, match="Unsupported Modal GPU"):
        modal_runner.ModalRunner(gpu_type="not-a-card")


def test_modal_revalidation_preserves_nested_binders(tmp_path, monkeypatch) -> None:
    """Run both payload packing and remote staging using a local Modal stub."""

    class Image:
        @classmethod
        def from_registry(cls, *args, **kwargs):
            return cls()

        def apt_install(self, *args):
            return self

        def pip_install(self, *args):
            return self

    class App:
        def __init__(self, name):
            pass

        def function(self, **kwargs):
            return lambda function: SimpleNamespace(remote=function)

        def run(self):
            return nullcontext()

    monkeypatch.setattr(
        modal_runner, "_require_modal", lambda: SimpleNamespace(Image=Image, App=App)
    )
    monkeypatch.setattr(modal_runner, "_ATEXIT_CLEANUP", lambda path: None)
    remote = tmp_path / "remote"
    remote.mkdir()
    monkeypatch.setattr("tempfile.mkdtemp", lambda **kwargs: str(remote))
    spec_dir = tmp_path / "spec"
    (spec_dir / "design").mkdir(parents=True)
    (spec_dir / "target.pdb").write_text("target", encoding="utf-8")
    (spec_dir / "design/binder.fasta").write_text(">binder\nAGGV\n", encoding="utf-8")
    spec_path = spec_dir / "spec.json"
    spec_path.write_text(
        json.dumps(
            {"extra_params": {"mode": "validate_only", "target_structure_name": "target.pdb"}}
        ),
        encoding="utf-8",
    )

    def run_job(spec, work, *, tarball):
        assert spec["extra_params"]["mode"] == "validate_only"
        assert (work / "design/binder.fasta").read_text() == ">binder\nAGGV\n"
        assert (work / "target.pdb").read_text() == "target"
        tarball.write_bytes(b"test result")
        return tarball

    monkeypatch.setattr(job_exec, "run_job", run_job)
    runner = modal_runner.ModalRunner()
    handle = runner.submit(spec_path, results_dir=tmp_path / "results")
    assert runner.fetch(handle).read_bytes() == b"test result"

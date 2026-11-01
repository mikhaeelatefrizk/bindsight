# SPDX-License-Identifier: AGPL-3.0-or-later
"""Meaningful CPU controls around the separately GPU-tested scientific runtime."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from packaging.requirements import Requirement

from bindsight.runners import gpu_recipe as pins
from bindsight.runners import gpu_runtime as runtime
from bindsight.runners import tools


@pytest.fixture
def provisioning(tmp_path, monkeypatch):
    root = tmp_path / "runtime"
    wheel = tmp_path / "bindsight-0.3.8-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("bindsight/__init__.py", "__version__ = '0.3.8'\n")
    commands = []
    downloads = []
    monkeypatch.setattr(runtime.sys, "platform", "linux")
    monkeypatch.setattr(
        runtime,
        "devices",
        lambda: [{"index": 0, "memory_mib": 15360, "compute_capability": [7, 5]}],
    )
    monkeypatch.setattr(runtime, "command", lambda argv, env: commands.append(argv))

    def download(url, destination, expected, **kwargs):
        downloads.append(url)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"fixture")
        return expected

    def uv(destination, **kwargs):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"fixture")
        return destination

    def completed(argv, **kwargs):
        if "rev-parse" in argv:
            commit = (
                tools.PROTEINMPNN_COMMIT if "ProteinMPNN" in str(argv[2]) else tools.RFDIFF_COMMIT
            )
            return SimpleNamespace(stdout=commit + "\n")
        return SimpleNamespace(stdout="fixture==1\n")

    monkeypatch.setattr(runtime, "download", download)
    monkeypatch.setattr(runtime, "download_verified_uv", uv)
    monkeypatch.setattr(runtime.subprocess, "run", completed)
    monkeypatch.setattr(runtime, "patch_e3nn_constants_loader", lambda site: {"fixture": "patch"})
    monkeypatch.setattr(runtime, "verify_managed_checkout", lambda *args: None)
    monkeypatch.setattr(
        runtime, "prepare_boltz_assets", lambda cache: {"fixture": "verified assets"}
    )
    monkeypatch.setattr(
        runtime,
        "prepare_boltz_runtime_wheel",
        lambda directory: (
            directory / "boltz-2.0.3+bindsight.1-py3-none-any.whl",
            {"fixture": "metadata patch"},
        ),
    )
    monkeypatch.setattr(
        runtime,
        "smoke",
        lambda root, env, **kwargs: {
            "boltz": {"boltz": pins.BOLTZ_RUNTIME_VERSION, "cuda_tested": kwargs["require_cuda"]}
        },
    )
    return root, wheel, commands, downloads


@pytest.mark.parametrize("mode", pins.MODES)
@pytest.mark.parametrize("check_only", [True, False])
def test_provision_uses_exact_interpreters_and_preserves_mode_boundary(
    provisioning, mode, check_only
):
    root, wheel, commands, downloads = provisioning
    result = runtime.provision(root, source=wheel, mode=mode, check_only=check_only)
    assert result["source_identity"]["sha256"] == hashlib.sha256(wheel.read_bytes()).hexdigest()
    assert result["cuda_tested"] is not check_only
    assert bool(result["boltz_assets"]) is not check_only
    assert (root / "ready.json").exists() is not check_only
    assert (result["design_python"] is not None) is (mode == "design_and_validate")
    created = [argv for argv in commands if "venv" in argv]
    assert len(created) == (2 if mode == "design_and_validate" else 1)
    for argv in created:
        assert argv[argv.index("--python") + 1] == "3.11.18"
        assert "--managed-python" in argv
    installs = [argv for argv in commands if "pip" in argv and "install" in argv]
    for argv in installs:
        assert argv[0] == str(root / "uv")
        assert "--no-config" in argv
        assert runtime.CERTIFI_REQUIREMENT in argv
        assert argv[argv.index("--python") + 1] in {
            str(root / "se3/bin/python"),
            str(root / "boltz/bin/python"),
        }
        assert "-r" not in argv  # No unbounded upstream training requirements.
    if mode == "validate_only":
        assert not any("RFdiffusion" in " ".join(argv) for argv in commands)
        assert not any("se3/bin/python" in " ".join(argv).replace("\\", "/") for argv in commands)
        assert not set(downloads).intersection(tools.RFDIFF_WEIGHTS.values())
    else:
        assert any(pins.SE3_DGL_WHEEL in argv for argv in installs)
        assert any("hydra-core==1.3.8" in argv for argv in installs)
        assert set(downloads).intersection(tools.RFDIFF_WEIGHTS.values()) == (
            set() if check_only else set(tools.RFDIFF_WEIGHTS.values())
        )
    assert any(
        pins.TORCH_WHEEL in argv and any("boltz-2.0.3+bindsight.1" in arg for arg in argv)
        for argv in installs
    )
    biopython = [
        Requirement(argument)
        for argv in installs
        for argument in argv
        if argument.startswith("biopython")
    ]
    assert len(biopython) == 1
    assert "1.86" not in biopython[0].specifier  # GHSA-x3vf-39hj-gxr4.
    assert "1.88" in biopython[0].specifier
    assert not any("python=3.9" in argv for argv in commands)


def test_receipt_environment_is_allowlisted_and_removes_host_python_config(tmp_path, monkeypatch):
    for key in ("API_TOKEN", "PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "PYTHONUSERBASE"):
        monkeypatch.setenv(key, "host-only-secret")
    overrides = runtime.execution_overrides(tmp_path, 0)
    assert "host-only-secret" not in json.dumps(overrides)
    assert overrides["BOLTZ_CACHE"] == str(tmp_path / "boltz-cache")
    env = runtime.execution_environment(tmp_path, 0)
    assert env["API_TOKEN"] == "host-only-secret"  # Host authentication stays only in memory.
    assert not {"PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "PYTHONUSERBASE"}.intersection(env)


def test_constants_patch_is_scoped_idempotent_and_rejects_tampering(tmp_path, monkeypatch):
    folder = tmp_path / "e3nn/o3"
    folder.mkdir(parents=True)
    loader = folder / "_wigner.py"
    original = b"import torch, os\n_Jd, _W3j_flat, _W3j_indices = torch.load(os.path.join(os.path.dirname(__file__), 'constants.pt'))\n"
    constants = folder / "constants.pt"
    constants.write_bytes(b"audited fixture")
    loader.write_bytes(original)
    monkeypatch.setattr(pins, "E3NN_LOADER_SHA256", hashlib.sha256(original).hexdigest())
    monkeypatch.setattr(
        pins, "E3NN_CONSTANTS_SHA256", hashlib.sha256(constants.read_bytes()).hexdigest()
    )
    receipt = runtime.patch_e3nn_constants_loader(tmp_path)
    assert "with torch.serialization.safe_globals([slice]):" in loader.read_text()
    assert "weights_only=True" in loader.read_text()
    assert "weights_only=False" not in loader.read_text()
    assert runtime.patch_e3nn_constants_loader(tmp_path) == receipt
    loader.write_bytes(loader.read_bytes() + b"# unreviewed change")
    with pytest.raises(RuntimeError, match="loader differs"):
        runtime.patch_e3nn_constants_loader(tmp_path)
    loader.write_bytes(original)
    constants.write_bytes(b"tampered constants")
    with pytest.raises(RuntimeError, match="constants differ"):
        runtime.patch_e3nn_constants_loader(tmp_path)


def test_model_receipt_does_not_claim_cached_models_were_used(tmp_path):
    root, evidence = tmp_path / "runtime", tmp_path / "evidence"
    model = root / "boltz-cache/boltz2_conf.ckpt"
    model.parent.mkdir(parents=True)
    model.write_bytes(b"cached model")
    receipt = runtime.collect_model_weights(root, evidence)
    assert receipt["model_weights"][0]["present"] is True
    assert receipt["model_weights"][0]["used"] is False
    commands = evidence / "attempt-1/commands"
    commands.mkdir(parents=True)
    (commands / "1.json").write_text(
        json.dumps(
            {
                "outcome": "ok",
                "returncode": 0,
                "argv": ["python", "-m", "bindsight.runners.boltz_compat", "predict", "input.yaml"],
            }
        )
    )
    assert runtime.collect_model_weights(root, evidence)["model_weights"][0]["used"] is True


def test_environment_reset_removes_legacy_runtime_but_preserves_models(tmp_path):
    root = tmp_path / "managed"
    old = root / "se3/lib/python3.9/site-packages"
    old.mkdir(parents=True)
    (old / "old.py").write_text("obsolete")
    model = root / "tools/RFdiffusion/models/Base_ckpt.pt"
    model.parent.mkdir(parents=True)
    model.write_bytes(b"verified model fixture")
    runtime.reset_owned_environment(root, "se3")
    assert not (root / "se3").exists()
    assert model.read_bytes() == b"verified model fixture"
    with pytest.raises(ValueError, match="unrecognized"):
        runtime.reset_owned_environment(root, "../other")
    assert model.exists()


def test_provision_refuses_home_before_download(provisioning, monkeypatch):
    _root, wheel, commands, downloads = provisioning
    with pytest.raises(ValueError, match="dedicated directory"):
        runtime.provision(Path.home(), source=wheel, check_only=True)
    assert commands == downloads == []


@pytest.fixture
def scientific_checkout(tmp_path):
    git = shutil.which("git")
    if not git:
        pytest.skip("Git is required to exercise actual checkout integrity")
    target = tmp_path / "scientific"
    subprocess.run([git, "init", "--quiet", str(target)], check=True)
    (target / "model.py").write_text("VALUE = 1\n")
    (target / ".gitignore").write_text("ignored/\n")
    subprocess.run([git, "-C", str(target), "add", "."], check=True)
    subprocess.run(
        [
            git,
            "-C",
            str(target),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "--quiet",
            "-m",
            "Fixture source",
        ],
        check=True,
    )
    return git, target, dict(os.environ)


@pytest.mark.parametrize("injection", ["tracked", "untracked", "ignored"])
def test_scientific_checkout_refuses_code_edits(scientific_checkout, injection):
    git, target, environment = scientific_checkout
    runtime.verify_managed_checkout(git, target, environment)
    if injection == "tracked":
        source = target / "model.py"
    elif injection == "ignored":
        source = target / "ignored/injected.py"
        source.parent.mkdir()
    else:
        source = target / "injected.pth"
    source.write_text("UNREVIEWED SOURCE\n")
    with pytest.raises(RuntimeError, match=r"tracked edits|untracked importable"):
        runtime.verify_managed_checkout(git, target, environment)
    assert source.read_text() == "UNREVIEWED SOURCE\n"  # Preserve unexpected user data.


def test_scientific_checkout_cleans_only_generated_bytecode(scientific_checkout):
    git, target, environment = scientific_checkout
    cache = target / "__pycache__/model.cpython-311.pyc"
    cache.parent.mkdir()
    cache.write_bytes(b"generated bytecode fixture")
    model = target / "models/Base_ckpt.pt"
    model.parent.mkdir()
    model.write_bytes(b"model fixture")
    copied = target / "build/lib/model.py"
    copied.parent.mkdir(parents=True)
    shutil.copy2(target / "model.py", copied)
    runtime.verify_managed_checkout(git, target, environment)
    assert not cache.exists()
    assert model.read_bytes() == b"model fixture"
    assert copied.read_bytes() == (target / "model.py").read_bytes()
    copied.write_text("INJECTED BUILD COPY\n")
    with pytest.raises(RuntimeError, match="untracked importable"):
        runtime.verify_managed_checkout(git, target, environment)


def test_source_identity_matches_wheel_code_and_ignores_documentation(tmp_path):
    project = tmp_path / "project"
    package = project / "bindsight"
    (package / "runners").mkdir(parents=True)
    (project / "pyproject.toml").write_text("[project]\nname='bindsight'\n")
    (package / "__init__.py").write_text("__version__='fixture'\n")
    executor = package / "runners/job_exec.py"
    executor.write_text("ALGORITHM = 1\n")
    first = runtime.source_identity(project)
    (project / "README.md").write_text("Documentation changed\n")
    (project / "docs").mkdir()
    (project / "docs/guide.md").write_text("More documentation\n")
    assert runtime.source_identity(project) == first
    wheel = tmp_path / "bindsight-0.3.8-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        for path in package.rglob("*.py"):
            archive.writestr(path.relative_to(project).as_posix(), path.read_bytes())
    assert runtime.source_identity(wheel)["implementation_sha256"] == first["implementation_sha256"]
    executor.write_text("ALGORITHM = 2\n")
    second = runtime.source_identity(project)
    assert second["implementation_sha256"] != first["implementation_sha256"]
    assert second["sha256"] != first["sha256"]


@pytest.mark.parametrize("helper", ["boltz_runtime_wheel.py", "archive_bounds.py"])
def test_recipe_fingerprint_changes_with_metadata_helper(monkeypatch, helper):
    first = pins.recipe()
    assert {
        "archive_bounds.py",
        "boltz_runtime_wheel.py",
        "boltz_assets.py",
        "boltz_msa.py",
        "job_exec.py",
        "tools.py",
        "boltz_compat.py",
    }.issubset(first["implementation_helpers_sha256"])
    read = Path.read_bytes

    def changed(path):
        data = read(path)
        return data + b"\n# changed implementation" if path.name == helper else data

    monkeypatch.setattr(Path, "read_bytes", changed)
    second = pins.recipe()
    assert second["id"] != first["id"]

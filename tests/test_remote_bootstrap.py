# SPDX-License-Identifier: AGPL-3.0-or-later
"""Generated cloud wrappers preserve the same source and execution boundary."""

from __future__ import annotations

import ast
import json
from types import SimpleNamespace

import pytest

from bindsight import __version__
from bindsight.runners import modal_runner, notebook_content


def notebook_cells(spec, *, handle_id="safe_job"):
    notebook = notebook_content.build_design_notebook(
        handle_id=handle_id, designer="rfdiff_mpnn", gpu_type="T4", spec=spec
    )
    return ["".join(cell["source"]) for cell in notebook["cells"] if cell["cell_type"] == "code"]


def local_load_cell(cell, tmp_path):
    return cell.replace(
        "pathlib.Path(f'/content/{JOB_ID}_spec')",
        f"pathlib.Path({str(tmp_path / 'safe_job_spec')!r})",
    )


def test_generated_notebook_compiles_and_spec_is_data_not_executable_code(tmp_path):
    value = "'''\n\"\"\"\n__import__('os').system('unsafe')\n{{ dangerous }}\nλ"
    spec = {"target_uniprot": value, "extra_params": {"mode": "validate_only"}}
    cells = notebook_cells(spec)
    for cell in cells:
        ast.parse(cell)
    load = next(cell for cell in cells if "SPEC = json.loads" in cell)
    assert value not in load
    namespace = {}
    exec(compile(local_load_cell(load, tmp_path), "load-spec", "exec"), namespace)
    assert namespace["SPEC"] == spec
    assert json.loads((tmp_path / "safe_job_spec/spec.json").read_text()) == spec


def test_notebook_bootstrap_helpers_are_standalone_and_driver_is_private():
    namespace = {}
    exec(compile(notebook_content._bootstrap_source(), "embedded-helpers", "exec"), namespace)
    assert callable(namespace["download_verified_uv"])
    assert callable(namespace["download_release_wheel"])
    install = next(cell for cell in notebook_cells({}) if "RELEASE_VERSION =" in cell)
    assert f"RELEASE_VERSION = '{__version__}'" in install
    assert "bindsight.runners.gpu_runtime" in install
    assert "--source" in install
    assert 'uv_install_command(UV, DRIVER, [str(WHEEL), "psutil>=5.9,<8"])' in install
    assert "git+" not in install
    assert "SE3Transformer" not in install
    assert "sys.executable" not in install
    assert "pip install bindsight" not in install


@pytest.mark.parametrize(
    "name",
    [
        "../outside.pdb",
        "/outside.pdb",
        "nested/../../outside",
        "spec.json",
        "./spec.json",
        "..\\outside.pdb",
        "",
    ],
)
def test_notebook_target_cannot_escape_or_replace_its_spec(tmp_path, name):
    spec = {"extra_params": {"target_structure_name": name}, "target_structure_b64": "eA=="}
    load = next(cell for cell in notebook_cells(spec) if "SPEC = json.loads" in cell)
    with pytest.raises(ValueError, match="path escapes"):
        exec(compile(local_load_cell(load, tmp_path), "load-spec", "exec"), {})
    assert json.loads((tmp_path / "safe_job_spec/spec.json").read_text()) == spec


@pytest.mark.parametrize("handle", ["../escape", "job';raise RuntimeError();#", "", "a" * 129])
def test_notebook_rejects_unsafe_job_id(handle):
    with pytest.raises(ValueError, match="job ID"):
        notebook_cells({}, handle_id=handle)


def test_notebook_rejects_mode_code_injection():
    with pytest.raises(ValueError, match="mode"):
        notebook_cells({"extra_params": {"mode": "';raise RuntimeError();#"}})


def test_notebook_executes_managed_interpreter_and_merges_host_environment(tmp_path, monkeypatch):
    receipt = {"boltz_python": "/managed/bin/python", "execution_environment": {"MANAGED": "yes"}}
    (tmp_path / "provision-receipt.json").write_text(json.dumps(receipt))
    monkeypatch.setenv("HOST_SECRET", "never-serialize-this")
    monkeypatch.setenv("PYTHONPATH", "/untrusted")
    calls = []
    monkeypatch.setattr(
        "subprocess.run",
        lambda argv, **kwargs: calls.append((argv, kwargs)) or SimpleNamespace(returncode=0),
    )
    run = next(cell for cell in notebook_cells({}) if "job_env.update" in cell)
    exec(
        compile(run, "execute-job", "exec"),
        {"ROOT": tmp_path, "WHEEL": tmp_path / "source.whl", "SOURCE_KIND": "candidate-wheel"},
    )
    argv, options = calls[0]
    assert argv[:4] == ["/managed/bin/python", "-I", "-m", "bindsight.runners.hosted_job"]
    assert options["env"]["HOST_SECRET"] == "never-serialize-this"
    assert "PYTHONPATH" not in options["env"]
    assert options["env"]["MANAGED"] == "yes"
    assert options["check"] is False
    assert "HOST_SECRET" not in (tmp_path / "provision-receipt.json").read_text()


@pytest.fixture
def modal_stub(tmp_path, monkeypatch):
    calls = {"pip": [], "base": [], "commands": []}

    class Image:
        @classmethod
        def debian_slim(cls, **kwargs):
            calls["base"].append(kwargs)
            return cls()

        def apt_install(self, *args):
            return self

        def pip_install(self, *args):
            calls["pip"].extend(args)
            return self

        def run_commands(self, *args):
            calls["commands"].extend(args)
            return self

    class App:
        def __init__(self, name):
            pass

        def function(self, **kwargs):
            return lambda function: SimpleNamespace(remote=function)

    monkeypatch.setattr(
        modal_runner, "_require_modal", lambda: SimpleNamespace(Image=Image, App=App)
    )
    monkeypatch.setattr(modal_runner, "_ATEXIT_CLEANUP", lambda path: None)
    remote_dir = tmp_path / "remote"
    remote_dir.mkdir()
    monkeypatch.setattr("tempfile.mkdtemp", lambda **kwargs: str(remote_dir))
    _, remote = modal_runner.ModalRunner()._build_app()
    return remote.remote, calls, remote_dir


def test_modal_initial_driver_pins_callers_published_release(modal_stub):
    _, calls, _ = modal_stub
    assert calls["pip"] == ["certifi>=2026.10.19", "psutil>=5.9,<8"]
    assert "download_release_wheel" in calls["commands"][0]
    assert f"bindsight-{__version__}-py3-none-any.whl" in calls["commands"][1]
    assert calls["base"] == [{"python_version": "3.11"}]


@pytest.mark.parametrize(
    "name",
    [
        "../outside.pdb",
        "/outside.pdb",
        "nested/../../outside",
        "spec.json",
        "./spec.json",
        "..\\outside.pdb",
        "",
    ],
)
def test_modal_payload_cannot_escape_or_replace_spec(modal_stub, name):
    remote, _, directory = modal_stub
    with pytest.raises(ValueError, match="payload entry escapes"):
        remote("{}", {name: b"malicious"})
    assert (directory / "spec/spec.json").read_text() == "{}"
    assert not (directory / "outside.pdb").exists()


def test_modal_rejects_oversized_spec_before_starting_a_remote_container(tmp_path, monkeypatch):
    spec = tmp_path / "spec.json"
    spec.write_text("x" * (2 * 1024 * 1024 + 1))
    monkeypatch.setattr(
        modal_runner.ModalRunner, "_build_app", lambda _: pytest.fail("remote started")
    )
    with pytest.raises(ValueError, match="specification exceeds"):
        modal_runner.ModalRunner().submit(spec, results_dir=tmp_path / "results")


def test_modal_rejects_large_payload_before_provisioning(modal_stub, monkeypatch):
    remote, _, _ = modal_stub
    monkeypatch.setattr(modal_runner, "MAX_PAYLOAD_BYTES", 2)
    with pytest.raises(ValueError, match="payload exceeds"):
        remote("{}", {"target.pdb": b"123"})


def test_modal_rejects_unsupported_mode_before_downloading_release(modal_stub, monkeypatch):
    from bindsight.runners import release_bootstrap

    monkeypatch.setattr(
        release_bootstrap, "download_release_wheel", lambda *args: pytest.fail("download")
    )
    remote, _, _ = modal_stub
    with pytest.raises(ValueError, match="mode"):
        remote(json.dumps({"extra_params": {"mode": "unknown"}}), {})

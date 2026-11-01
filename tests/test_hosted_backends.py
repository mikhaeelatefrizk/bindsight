# SPDX-License-Identifier: AGPL-3.0-or-later
"""Candidate transport and returned evidence are verified without cloud compute."""

from __future__ import annotations

import ast
import base64
import hashlib
import io
import json
import tarfile
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from bindsight.runners import hosted_job, hosted_source, modal_runner, notebook_content


@pytest.fixture
def wheel(tmp_path):
    path = tmp_path / "bindsight-0.3.9-py3-none-any.whl"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("bindsight/__init__.py", "# inert test fixture\n")
        archive.writestr("bindsight-0.3.9.dist-info/METADATA", "Name: bindsight\nVersion: 0.3.9\n")
    return path


def test_candidate_roundtrip_binds_exact_bytes_and_metadata(wheel, tmp_path):
    identity = hosted_source.candidate_source(wheel)
    output = hosted_source.write_candidate(wheel.read_bytes(), identity, tmp_path / "transport")
    assert output.read_bytes() == wheel.read_bytes()
    assert json.loads(output.with_suffix(".source.json").read_text()) == identity
    assert identity["sha256"] == hashlib.sha256(output.read_bytes()).hexdigest()
    assert identity["version"] == "0.3.9"


@pytest.mark.parametrize("mutation", ["bytes", "digest", "version", "filename", "size"])
def test_candidate_tampering_fails_before_materialization(wheel, tmp_path, mutation):
    identity = hosted_source.candidate_source(wheel)
    data = wheel.read_bytes()
    if mutation == "bytes":
        data = b"X" + data[1:]
    elif mutation == "digest":
        identity["sha256"] = "0" * 64
    elif mutation == "version":
        identity["version"] = "0.3.10"
        identity["filename"] = "bindsight-0.3.10-py3-none-any.whl"
    elif mutation == "filename":
        identity["filename"] = "../escape.whl"
    else:
        identity["bytes"] += 1
    with pytest.raises(ValueError, match=r"[Cc]andidate"):
        hosted_source.write_candidate(data, identity, tmp_path / "transport")
    assert not list((tmp_path / "transport").glob("*.whl"))


@pytest.mark.parametrize("entry", ["other-1.0.dist-info/METADATA", "../escape.py", "/absolute.py"])
def test_candidate_rejects_ambiguous_or_unsafe_zip_entries(wheel, entry):
    with zipfile.ZipFile(wheel, "a") as archive:
        archive.writestr(entry, "Name: other\nVersion: 1.0\n")
    with pytest.raises(ValueError, match=r"[Cc]andidate"):
        hosted_source.candidate_source(wheel)


def test_candidate_rejects_duplicate_metadata(wheel):
    with zipfile.ZipFile(wheel, "a") as archive, pytest.warns(UserWarning, match="Duplicate"):
        archive.writestr("bindsight-0.3.9.dist-info/METADATA", "Name: bindsight\nVersion: 0.3.9")
    with pytest.raises(ValueError, match="members"):
        hosted_source.candidate_source(wheel)


def test_notebook_embeds_only_explicit_verified_candidate(wheel):
    notebook = notebook_content.build_design_notebook(
        handle_id="candidate", designer="rfdiff_mpnn", gpu_type="T4", spec={}, bindsight_wheel=wheel
    )
    cells = ["".join(cell["source"]) for cell in notebook["cells"] if cell["cell_type"] == "code"]
    for cell in cells:
        ast.parse(cell)
    install = next(cell for cell in cells if "RELEASE_VERSION =" in cell)
    namespace = {}
    exec(compile(notebook_content._bootstrap_source(), "bootstrap", "exec"), namespace)
    # Execute the actual generated selection stanza, without any installer or network call.
    selection = install[
        install.index("import base64\nCANDIDATE =") : install.index("ENV = package_environment")
    ]
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        namespace.update(ROOT=Path(directory), RELEASE_VERSION="0.3.9")
        exec(compile(selection, "candidate-selection", "exec"), namespace)
        assert namespace["WHEEL"].read_bytes() == wheel.read_bytes()
        assert namespace["SOURCE_KIND"] == "candidate-wheel"
    default = notebook_content.build_design_notebook(
        handle_id="release", designer="rfdiff_mpnn", gpu_type="T4", spec={}
    )
    assert base64.b64encode(wheel.read_bytes()).decode() not in json.dumps(default)


def test_modal_module_scope_and_no_source_automount(wheel, monkeypatch):
    calls = {}

    class Image:
        @classmethod
        def debian_slim(cls, **_kwargs):
            return cls()

        def apt_install(self, *_args):
            return self

        def pip_install(self, *_args):
            return self

        def add_local_file(self, local, remote, *, copy):
            calls.update(local=local, remote=remote, copy=copy)
            return self

        def run_commands(self, *commands):
            calls["commands"] = commands
            return self

    class App:
        def __init__(self, name):
            pass

        def function(self, **kwargs):
            calls["function_options"] = kwargs

            def decorate(function):
                assert "<locals>" not in function.__qualname__
                calls["function"] = function
                return object()

            return decorate

    monkeypatch.setattr(
        modal_runner, "_require_modal", lambda: SimpleNamespace(Image=Image, App=App)
    )
    runner = modal_runner.ModalRunner(bindsight_wheel=wheel, gpu_type="T4")
    runner._build_app()
    assert calls["function"] is modal_runner._run_remote
    assert calls["function_options"]["include_source"] is False
    assert "serialized" not in calls["function_options"]
    assert calls["copy"] is True
    assert Path(calls["local"]).read_bytes() == wheel.read_bytes()
    assert "verify_candidate" in calls["commands"][0]
    assert "pip install" in calls["commands"][1]
    # Constructor identity survives deferred image construction.
    wheel.write_bytes(b"replacement")
    with pytest.raises(ValueError, match=r"[Cc]andidate"):
        runner._build_app()


@pytest.mark.parametrize("candidate", [False, True])
def test_real_modal_sdk_constructs_without_starting_app(monkeypatch, wheel, candidate):
    modal = pytest.importorskip("modal")
    monkeypatch.setattr(modal.App, "run", lambda *_args, **_kwargs: pytest.fail("cloud run"))
    app, function = modal_runner.ModalRunner(
        gpu_type="T4", bindsight_wheel=wheel if candidate else None
    )._build_app()
    assert isinstance(app, modal.App)
    assert function is not None


def _tar(path, members):
    with tarfile.open(path, "w:gz") as archive:
        for name, content in members.items():
            entry = tarfile.TarInfo(name)
            entry.size = len(content)
            archive.addfile(entry, io.BytesIO(content))


@pytest.fixture
def hosted_run(tmp_path, wheel, monkeypatch):
    from bindsight.runners import gpu_runtime

    root = tmp_path / "runtime"
    root.mkdir()
    (root / "HUGE_WEIGHTS_NEVER_ARCHIVE.ckpt").write_bytes(b"private model cache")
    spec = tmp_path / "spec.json"
    spec.write_text('{"seed":42}')
    identity = hosted_source.candidate_source(wheel)
    receipt = {
        "source_identity": dict(identity, kind="wheel"),
        "mode": "design_and_validate",
        "boltz_python": "/managed/boltz/bin/python",
        "execution_environment": {"MANAGED": "yes"},
    }
    science = {
        "evidence/spec.json": spec.read_bytes(),
        "design/binder.fasta": b">binder\nACDE\n",
        "evidence/raw/backbone.trb": b"opaque pickle bytes: MUST NEVER EXECUTE",
        "validate/prediction.cif": b"original scientific bytes",
    }
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        if "bindsight.runners.job_exec" in argv:
            _tar(Path(argv[-1]), science)
            return SimpleNamespace(returncode=0)
        assert "freeze" in argv
        return SimpleNamespace(stdout="torch==2.14.1+cu126\n", returncode=0)

    monkeypatch.setattr(hosted_job.subprocess, "run", run)
    monkeypatch.setattr(hosted_job, "download_verified_uv", lambda _: root / "uv")
    monkeypatch.setattr(
        hosted_job,
        "_hardware_sample",
        lambda: {"utc": "2026-11-01T00:00:00Z", "gpus": [{"name": "T4", "memory.used": "100"}]},
    )
    monkeypatch.setattr(
        gpu_runtime,
        "collect_model_weights",
        lambda *_args: {
            "model_weights": [{"name": "known.ckpt", "sha256": "a" * 64, "used": True}]
        },
    )
    monkeypatch.setenv("HOST_SECRET", "do-not-serialize-this")
    monkeypatch.setenv("PYTHONPATH", "/untrusted")
    options = dict(
        backend="modal",
        root=root,
        receipt=receipt,
        source=wheel,
        source_kind="candidate-wheel",
        spec=spec,
        output=tmp_path / "result.tar.gz",
    )
    return options, science, calls


def test_hosted_archive_preserves_science_and_collects_selected_receipts(hosted_run):
    options, science, calls = hosted_run
    status = hosted_job.run_hosted_job(**options)
    assert status["outcome"] == "completed"
    assert status["returncode"] == 0
    assert hosted_job.archive_status(options["output"]) == status
    argv, kwargs = calls[0]
    assert argv[:4] == ["/managed/boltz/bin/python", "-I", "-m", "bindsight.runners.job_exec"]
    assert kwargs["env"]["MANAGED"] == "yes"
    assert "PYTHONPATH" not in kwargs["env"]
    assert kwargs["env"]["HOST_SECRET"] == "do-not-serialize-this"
    with tarfile.open(options["output"], "r:gz") as archive:
        data = {
            member.name: archive.extractfile(member).read() for member in archive if member.isfile()
        }
    for name, value in science.items():
        assert data[name] == value
    assert b"do-not-serialize-this" not in b"".join(data.values())
    assert not any("HUGE_WEIGHTS" in name or name.endswith(".ckpt") for name in data)
    assert "runtime/se3-final-freeze.txt" in data
    assert "runtime/boltz-final-freeze.txt" in data
    manifest = json.loads(data["runtime/manifest.json"])
    assert {item["path"] for item in manifest["files"]} == {
        name.removeprefix("runtime/")
        for name in data
        if name.startswith("runtime/") and name != "runtime/manifest.json"
    }
    for item in manifest["files"]:
        value = data["runtime/" + item["path"]]
        assert item["bytes"] == len(value)
        assert item["sha256"] == hashlib.sha256(value).hexdigest()


def test_hosted_refuses_runtime_with_different_wheel_before_execution(hosted_run):
    options, _, calls = hosted_run
    options["receipt"]["source_identity"]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="differs"):
        hosted_job.run_hosted_job(**options)
    assert not calls


def test_missing_final_freeze_makes_success_incomplete(hosted_run, monkeypatch):
    options, _, _ = hosted_run
    monkeypatch.setattr(
        hosted_job, "_freeze", lambda *_args: (_ for _ in ()).throw(ValueError("failure"))
    )
    status = hosted_job.run_hosted_job(**options)
    assert status["outcome"] == "incomplete"
    assert status["returncode"] == 0
    assert hosted_job.archive_status(options["output"])["evidence_errors"] == [
        {"stage": "final-freezes", "error": "ValueError"}
    ]


def test_failed_executor_returns_diagnostic_archive(hosted_run, monkeypatch):
    options, _, _ = hosted_run
    original = hosted_job.subprocess.run

    def fail(argv, **kwargs):
        if "bindsight.runners.job_exec" in argv:
            work = Path(argv[-1]).parent / "scientific_work/evidence/attempt-test"
            work.mkdir(parents=True)
            (work / "current-command.json").write_text('{"phase":"nonzero"}')
            return SimpleNamespace(returncode=7)
        return original(argv, **kwargs)

    monkeypatch.setattr(hosted_job.subprocess, "run", fail)
    status = hosted_job.run_hosted_job(**options)
    assert status["outcome"] == "failed"
    assert status["returncode"] == 7
    with tarfile.open(options["output"]) as archive:
        assert "partial-evidence/attempt-test/current-command.json" in archive.getnames()


@pytest.mark.parametrize("name", ["../outside", "/outside", "runtime/backend-status.json"])
def test_repack_rejects_unsafe_or_shadowing_scientific_members(tmp_path, name):
    original = tmp_path / "science.tar.gz"
    _tar(original, {name: b"unsafe"})
    receipts = tmp_path / "receipts"
    receipts.mkdir()
    output = tmp_path / "final.tar.gz"
    with pytest.raises(ValueError, match="Unsafe"):
        hosted_job._pack(original, receipts, output, tmp_path / "work")
    assert not output.exists()


def test_colab_run_cell_can_be_repeated_without_losing_previous_evidence(hosted_run):
    options, _, _ = hosted_run
    first = hosted_job.run_hosted_job(**options)
    second = hosted_job.run_hosted_job(**options)
    assert first["outcome"] == "completed"
    assert second["outcome"] == "completed"
    attempts = list(options["output"].parent.glob("result.tar.gz.runtime-*"))
    assert len(attempts) == 2
    assert all((path / "receipts/manifest.json").is_file() for path in attempts)


def test_corrupt_scientific_archive_retains_incomplete_diagnostic_archive(hosted_run, monkeypatch):
    options, _, _ = hosted_run
    original = hosted_job.subprocess.run

    def corrupt(argv, **kwargs):
        if "bindsight.runners.job_exec" in argv:
            Path(argv[-1]).write_bytes(b"truncated gzip")
            return SimpleNamespace(returncode=0)
        return original(argv, **kwargs)

    monkeypatch.setattr(hosted_job.subprocess, "run", corrupt)
    status = hosted_job.run_hosted_job(**options)
    assert status["outcome"] == "incomplete"
    assert status["evidence_errors"][-1]["stage"] == "scientific-archive"
    assert hosted_job.archive_status(options["output"])["outcome"] == "incomplete"

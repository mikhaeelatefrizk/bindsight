# SPDX-License-Identifier: AGPL-3.0-or-later
"""Private, version-pinned delivery when a wheel exceeds Kaggle's code limit."""

import ast
import hashlib
import json
import pathlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from bindsight.runners import kaggle, kaggle_kernel


def _fake_api(name, size, calls, *, reported_size=None):
    def create(folder, **options):
        directory = Path(folder)
        calls.append(
            ("create", options, json.loads((directory / "dataset-metadata.json").read_text()))
        )
        assert sorted(path.name for path in directory.iterdir()) == sorted(
            ["dataset-metadata.json", name]
        )
        assert (directory / name).stat().st_size == size
        return SimpleNamespace(error=None)

    def files(ref):
        calls.append(("files", ref))
        return SimpleNamespace(
            dataset_files=[
                SimpleNamespace(
                    name=name, total_bytes=size if reported_size is None else reported_size
                )
            ]
        )

    def push(folder, **options):
        directory = Path(folder)
        calls.append(
            (
                "push",
                options,
                json.loads((directory / "kernel-metadata.json").read_text()),
                (directory / "kernel.py").read_text(),
            )
        )

    return SimpleNamespace(
        config_values={"username": "testowner"},
        dataset_create_new=create,
        dataset_status=lambda ref: "ready",
        dataset_list_files=files,
        kernels_push=push,
    )


def _job(tmp_path, wheel_bytes=900321):
    spec = tmp_path / "spec/spec.json"
    spec.parent.mkdir()
    spec.write_text('{"extra_params":{"mode":"validate_only"}}')
    wheel = tmp_path / "bindsight-0.3.8-py3-none-any.whl"
    wheel.write_bytes(b"synthetic transport fixture".ljust(wheel_bytes, b"x"))
    return spec, wheel


def test_oversized_wheel_is_private_version_pinned_and_reused(tmp_path):
    spec, wheel = _job(tmp_path)
    calls = []
    runner = kaggle.KaggleRunner(
        username="testowner", bindsight_wheel=wheel, session_timeout_s=7200
    )
    runner._api_client = _fake_api(wheel.name, wheel.stat().st_size, calls)
    handle = runner.submit(spec, results_dir=tmp_path / "results")
    created = next(call for call in calls if call[0] == "create")
    assert created[1] == {
        "public": False,
        "quiet": True,
        "convert_to_csv": False,
        "dir_mode": "skip",
    }
    assert created[2]["licenses"] == [{"name": "AGPL-3.0"}]
    pushed = next(call for call in calls if call[0] == "push")
    assert pushed[1] == {"timeout": 7200}
    assert pushed[2]["dataset_sources"] == [created[2]["id"] + "/1"]
    assert pushed[2]["is_private"] is True
    assert len(pushed[3].encode()) < kaggle._MAX_KERNEL_BYTES
    assert "BINDSIGHT_WHEEL_B64 = ''" in pushed[3]
    assert hashlib.sha256(wheel.read_bytes()).hexdigest() in pushed[3]
    assert "/kaggle/input/datasets/testowner/" in pushed[3]
    work = tmp_path / "results" / ("kaggle_" + handle.handle_id)
    identity = json.loads((work / "wheel-dataset.json").read_text())
    runner._ensure_wheel_dataset(runner._api_client, work, identity, wheel.read_bytes())
    assert sum(call[0] == "create" for call in calls) == 1
    assert all(call[1].endswith("/1") for call in calls if call[0] == "files")


def test_small_wheel_stays_inline_without_dataset_upload(tmp_path):
    spec, wheel = _job(tmp_path, 100)
    calls = []
    runner = kaggle.KaggleRunner(username="testowner", bindsight_wheel=wheel)
    runner._api_client = _fake_api(wheel.name, wheel.stat().st_size, calls)
    runner.submit(spec, results_dir=tmp_path / "results")
    assert [call[0] for call in calls] == ["push"]
    assert calls[0][1] == {}
    assert calls[0][2]["dataset_sources"] == []


def test_remote_dataset_size_mismatch_prevents_gpu_submission(tmp_path):
    spec, wheel = _job(tmp_path)
    calls = []
    runner = kaggle.KaggleRunner(username="testowner", bindsight_wheel=wheel)
    runner._api_client = _fake_api(wheel.name, wheel.stat().st_size, calls, reported_size=1)
    with pytest.raises(RuntimeError, match="expected wheel"):
        runner.submit(spec, results_dir=tmp_path / "results")
    assert not any(call[0] == "push" for call in calls)


@pytest.mark.parametrize("value", [0, 59, 43201, True, 1.5])
def test_invalid_session_deadline_is_refused(value):
    with pytest.raises(ValueError, match="session_timeout_s"):
        kaggle.KaggleRunner(session_timeout_s=value)


def _reader():
    script = kaggle_kernel.build_kernel_script(handle_id="fixture", payload={})
    node = next(
        node
        for node in ast.parse(script).body
        if isinstance(node, ast.FunctionDef) and node.name == "read_attached_wheel"
    )
    namespace = {"pathlib": pathlib, "hashlib": hashlib}
    exec(compile(ast.Module(body=[node], type_ignores=[]), "mount-reader", "exec"), namespace)
    return namespace["read_attached_wheel"]


@pytest.mark.parametrize("layout", ["datasets/owner/slug", "owner/slug", "slug"])
def test_known_mount_layout_is_verified_before_install(tmp_path, layout):
    name, data = "bindsight-0.3.8-py3-none-any.whl", b"wheel fixture"
    target = tmp_path / layout / name
    target.parent.mkdir(parents=True)
    target.write_bytes(data)
    actual, actual_data = _reader()(
        "/kaggle/input/datasets/owner/slug/" + name,
        name,
        len(data),
        hashlib.sha256(data).hexdigest(),
        input_root=tmp_path,
    )
    assert actual == target.resolve()
    assert actual_data == data


def test_mount_integrity_and_ambiguity_fail_closed(tmp_path):
    name, data = "bindsight-0.3.8-py3-none-any.whl", b"wheel fixture"
    expected = "/kaggle/input/datasets/owner/slug/" + name
    arguments = (expected, name, len(data), hashlib.sha256(data).hexdigest())
    first = tmp_path / "slug" / name
    first.parent.mkdir()
    first.write_bytes(b"x" * len(data))
    with pytest.raises(RuntimeError, match="integrity"):
        _reader()(*arguments, input_root=tmp_path)
    first.write_bytes(data)
    second = tmp_path / "owner/slug" / name
    second.parent.mkdir(parents=True)
    second.write_bytes(data)
    with pytest.raises(RuntimeError, match="ambiguous"):
        _reader()(*arguments, input_root=tmp_path)


@pytest.mark.parametrize("status_code", [403, 404, 429, 500, 503])
def test_new_dataset_status_transient_http_failure_is_read_only_retry(
    tmp_path, monkeypatch, status_code
):
    from requests import HTTPError, Response

    spec, wheel = _job(tmp_path)
    calls, reads, sleeps = [], [], []
    runner = kaggle.KaggleRunner(username="testowner", bindsight_wheel=wheel)
    api = _fake_api(wheel.name, wheel.stat().st_size, calls)

    def status(ref):
        reads.append(ref)
        if len(reads) == 1:
            response = Response()
            response.status_code = status_code
            raise HTTPError("temporary dataset indexing", response=response)
        return "ready"

    api.dataset_status = status
    runner._api_client = api
    monkeypatch.setattr(kaggle.time, "sleep", sleeps.append)
    runner.submit(spec, results_dir=tmp_path / "results")
    assert len(reads) == 2
    assert sleeps == [2]
    assert sum(call[0] == "create" for call in calls) == 1
    assert sum(call[0] == "push" for call in calls) == 1


def test_new_dataset_status_permanent_failure_stops_after_fixed_deadline(tmp_path, monkeypatch):
    from requests import HTTPError, Response

    spec, wheel = _job(tmp_path)
    calls = []
    runner = kaggle.KaggleRunner(username="testowner", bindsight_wheel=wheel)
    api = _fake_api(wheel.name, wheel.stat().st_size, calls)

    def denied(ref):
        response = Response()
        response.status_code = 403
        raise HTTPError("still indexing", response=response)

    api.dataset_status = denied
    runner._api_client = api
    ticks = iter([0, 1, 301])
    monkeypatch.setattr(kaggle.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(kaggle.time, "sleep", lambda duration: None)
    with pytest.raises(TimeoutError, match="five minutes"):
        runner.submit(spec, results_dir=tmp_path / "results")
    assert sum(call[0] == "create" for call in calls) == 1
    assert not any(call[0] in {"files", "push"} for call in calls)


def test_new_dataset_status_does_not_retry_unrelated_http_errors(tmp_path, monkeypatch):
    from requests import HTTPError, Response

    spec, wheel = _job(tmp_path)
    calls = []
    runner = kaggle.KaggleRunner(username="testowner", bindsight_wheel=wheel)
    api = _fake_api(wheel.name, wheel.stat().st_size, calls)

    def unauthorized(ref):
        response = Response()
        response.status_code = 401
        raise HTTPError("unauthorized", response=response)

    api.dataset_status = unauthorized
    runner._api_client = api
    monkeypatch.setattr(kaggle.time, "sleep", lambda duration: pytest.fail("unexpected retry"))
    with pytest.raises(HTTPError):
        runner.submit(spec, results_dir=tmp_path / "results")
    assert sum(call[0] == "create" for call in calls) == 1

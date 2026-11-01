# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Behavioral checks for progress retained before a Kaggle process can finish."""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from bindsight.runners import kaggle_kernel


@pytest.fixture
def helpers(tmp_path: Path) -> dict:
    tree = ast.parse(kaggle_kernel._BODY)
    nodes = []
    for node in tree.body:
        if isinstance(node, ast.Import | ast.ImportFrom | ast.FunctionDef | ast.ClassDef) or (
            isinstance(node, ast.Assign)
            and all(
                isinstance(target, ast.Name)
                and target.id.startswith("_")
                and target.id != "_monitor"
                for target in node.targets
            )
        ):
            nodes.append(node)
    scratch = tmp_path / "scratch"
    evidence = tmp_path / "output"
    scratch.mkdir()
    evidence.mkdir()
    namespace = {
        "SCRATCH": scratch,
        "EVIDENCE": evidence,
        "HANDLE_ID": "fixture",
        "env": dict(os.environ),
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "<kaggle-helpers>", "exec"), namespace)
    return namespace


def test_split_output_never_exposes_partial_credentials(helpers: dict, monkeypatch) -> None:
    secret = "private-kaggle-credential-123456"
    monkeypatch.setenv("KAGGLE_KEY", secret)
    text = (
        "progress 🔬 " + secret + " https://user:password@host/file?token=secret\rnext\n"
    ).encode()
    for boundary in range(len(text) + 1):
        records = []
        lines = helpers["OutputLines"](
            lambda item, records=records: records.append(helpers["outer_redact"](item))
        )
        lines.feed(text[:boundary])
        lines.feed(text[boundary:])
        lines.close()
        joined = "".join(records)
        assert secret not in joined
        assert "user:password" not in joined
        assert "token=secret" not in joined
        assert "🔬" in joined
        assert "next\n" in joined


def test_oversized_unterminated_output_is_bounded_and_elided(helpers: dict) -> None:
    records = []
    lines = helpers["OutputLines"](records.append)
    for _ in range(100):
        lines.feed(b"x" * 4096)
        assert len(lines.pending) <= helpers["_LINE_LIMIT"]
    lines.feed(b"\nfinished")
    lines.close()
    assert records == ["<bindsight: oversized output line omitted>\n", "finished\n"]


@pytest.mark.parametrize("separator", ["\n", "\r\n", "\r"])
def test_chunked_multiline_credentials_are_redacted_per_line(
    helpers: dict, monkeypatch, separator: str
) -> None:
    parts = ["-----BEGIN PRIVATE KEY-----", "aGVsbG9wcml2YXRla2V5", "-----END PRIVATE KEY-----"]
    monkeypatch.setenv("TEST_PRIVATE_SECRET", separator.join(parts))
    payload = ("starting\n" + separator.join(parts) + "\nfinished\n").encode()
    for boundary in range(len(payload) + 1):
        records = []
        lines = helpers["OutputLines"](
            lambda item, records=records: records.append(helpers["outer_redact"](item))
        )
        lines.feed(payload[:boundary])
        lines.feed(payload[boundary:])
        lines.close()
        joined = "".join(records)
        assert all(part not in joined for part in parts)
        assert joined.count("<redacted>") == 3
        assert joined.startswith("starting\n")
        assert joined.endswith("finished\n")


@pytest.mark.parametrize("failure", ["broken-pipe", "unicode", "closed-console"])
def test_console_failure_preserves_log_and_does_not_fail_child(helpers: dict, failure: str) -> None:
    def unavailable_console(*args, **kwargs):
        assert (helpers["EVIDENCE"] / "commands.log").stat().st_size > 0
        if failure == "broken-pipe":
            raise BrokenPipeError("console disconnected")
        if failure == "unicode":
            raise UnicodeEncodeError("ascii", "🔬", 0, 1, "unsupported console character")
        raise ValueError("I/O operation on closed console")

    helpers["print"] = unavailable_console
    helpers["run"]([sys.executable, "-c", "print('scientific child finished')"])
    log = (helpers["EVIDENCE"] / "commands.log").read_text(encoding="utf-8")
    assert "scientific child finished\n" in log
    helpers["diagnostic"]("unicode 🔬 progress\n")
    assert "unicode 🔬 progress\n" in (helpers["EVIDENCE"] / "commands.log").read_text(
        encoding="utf-8"
    )


def test_log_is_flushed_redacted_and_bounded(helpers: dict, monkeypatch, capsys) -> None:
    monkeypatch.setenv("TEST_API_KEY", "never-print-this-secret")
    helpers["_LOG_LIMIT"] = 128
    helpers["diagnostic"]("never-print-this-secret\n")
    log = helpers["EVIDENCE"] / "commands.log"
    assert log.read_text() == "<redacted>\n"
    for index in range(30):
        helpers["diagnostic"](str(index) + "x" * 100)
    assert "never-print-this-secret" not in capsys.readouterr().out
    assert log.stat().st_size <= 128
    previous = log.with_name("commands.previous.log")
    assert previous.stat().st_size <= 128
    assert "29" in log.read_text()


def test_running_child_output_is_visible_before_exit(
    helpers: dict, tmp_path, monkeypatch, capsys
) -> None:
    secret = "streamed-private-token-123456"
    monkeypatch.setenv("TEST_TOKEN", secret)
    gate = tmp_path / "finish"
    child_env = {**os.environ, "TEST_TOKEN": secret}
    script = (
        "import os, pathlib, sys, time; "
        "print('live ' + os.environ['TEST_TOKEN'], flush=True); "
        "p=pathlib.Path(sys.argv[1]); "
        "exec('while not p.exists(): time.sleep(0.02)')"
    )
    errors = []

    def run() -> None:
        try:
            helpers["run"]([sys.executable, "-c", script, str(gate)], environment=child_env)
        except BaseException as error:
            errors.append(error)

    worker = threading.Thread(target=run)
    worker.start()
    try:
        deadline = time.monotonic() + 10
        log = helpers["EVIDENCE"] / "commands.log"
        while time.monotonic() < deadline:
            if log.exists() and "live <redacted>" in log.read_text():
                break
            time.sleep(0.02)
        assert worker.is_alive(), "The check must observe a still-running child"
        assert "live <redacted>" in log.read_text()
        assert secret not in log.read_text()
        assert "live <redacted>" in capsys.readouterr().out
    finally:
        gate.touch()
        worker.join(timeout=10)
    assert not worker.is_alive()
    assert not errors


def test_nonzero_and_timeout_keep_live_output(helpers: dict) -> None:
    with pytest.raises(subprocess.CalledProcessError):
        helpers["run"]([sys.executable, "-c", "print('before error'); raise SystemExit(3)"])
    assert "before error" in (helpers["EVIDENCE"] / "commands.log").read_text()
    helpers["_COMMAND_TIMEOUT"] = 0.2
    started = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        helpers["run"]([sys.executable, "-c", "import time; print('before wait'); time.sleep(20)"])
    assert time.monotonic() - started < 10
    assert "before wait" in (helpers["EVIDENCE"] / "commands.log").read_text()


def test_missing_gpu_probe_is_bounded_and_nonfatal(helpers: dict, monkeypatch) -> None:
    def missing(*args, **kwargs):
        assert kwargs["timeout"] == 5
        raise FileNotFoundError("nvidia-smi")

    monkeypatch.setattr(subprocess, "run", missing)
    assert helpers["gpu_reading"]() == {"error": "FileNotFoundError"}
    assert helpers["_vram_now"]() is None


def test_heartbeat_persists_inner_phase_gpu_and_process_measurements(helpers: dict) -> None:
    current = helpers["EVIDENCE"] / "job-evidence/attempt-1/current-command.json"
    current.parent.mkdir(parents=True)
    current.write_text(
        json.dumps({"phase": "running", "argv": ["python", "boltz"], "running": True})
    )
    saved = {}
    helpers["save_json"] = lambda path, value: saved.update({path.name: value})
    helpers["diagnostic"] = lambda text: None
    helpers["gpu_reading"] = lambda: {
        "devices": [{"utilization_percent": 91, "memory_used_mib": 1234}]
    }
    helpers["process_reading"] = lambda: {
        "processes": [{"pid": 12, "rss_bytes": 4321, "cpu_seconds": 6.1}]
    }
    helpers["_PHASE"][0] = "scientific executor"
    helpers["heartbeat"]()
    value = saved["heartbeat.json"]
    assert value["phase"] == "scientific executor"
    assert value["current_command"]["running"] is True
    assert value["gpu"]["devices"][0]["utilization_percent"] == 91
    assert value["processes"]["processes"][0]["rss_bytes"] == 4321
    assert "memory-progress.json" in saved


_POSIX = pytest.mark.skipif(
    os.name != "posix", reason="Kaggle uses POSIX no-follow directory handles"
)


@_POSIX
def test_snapshot_copies_only_changed_bounded_files_and_keeps_atomic_json(helpers: dict) -> None:
    source = helpers["SCRATCH"] / "fixture_work/evidence/attempt-1"
    source.mkdir(parents=True)
    current = source / "current-command.json"
    current.write_text('{"running":true}')
    (source / "model.ckpt").write_bytes(b"weights")
    (source / "too-big.log").write_bytes(b"x" * 200)
    helpers["_SNAPSHOT_FILE_LIMIT"] = 128
    helpers["retain_failed_evidence"]()
    output = helpers["EVIDENCE"] / "job-evidence/attempt-1/current-command.json"
    assert json.loads(output.read_text()) == {"running": True}
    before = output.stat()
    helpers["retain_failed_evidence"]()
    assert output.stat().st_ino == before.st_ino
    assert output.stat().st_mtime_ns == before.st_mtime_ns
    current.write_text('{"running":false}')
    helpers["retain_failed_evidence"]()
    assert json.loads(output.read_text()) == {"running": False}
    assert not (output.parent / "model.ckpt").exists()
    assert not (output.parent / "too-big.log").exists()
    assert not list(helpers["EVIDENCE"].rglob(".pending-*"))


@_POSIX
def test_snapshot_rejects_links_fifo_and_destination_escape(helpers: dict, tmp_path) -> None:
    source = helpers["SCRATCH"] / "fixture_work/evidence/attempt-1"
    source.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.log").write_text("secret must remain outside")
    (source / "linked.log").symlink_to(outside / "secret.log")
    (source / "linked-directory").symlink_to(outside, target_is_directory=True)
    os.mkfifo(source / "pipe.log")
    (source / "safe.json").write_text("{}")
    helpers["retain_failed_evidence"]()
    output = helpers["EVIDENCE"] / "job-evidence/attempt-1"
    assert (output / "safe.json").read_text() == "{}"
    assert not (output / "linked.log").exists()
    assert not (output / "pipe.log").exists()
    assert not (output / "linked-directory").exists()
    (output / "safe.json").unlink()
    output.rmdir()
    output.symlink_to(outside, target_is_directory=True)
    (source / "new.json").write_text("{}")
    helpers["retain_failed_evidence"]()
    assert not (outside / "new.json").exists()


@_POSIX
def test_snapshot_budget_is_for_retained_bytes_across_passes(helpers: dict) -> None:
    source = helpers["SCRATCH"] / "fixture_work/evidence/attempt-1"
    source.mkdir(parents=True)
    helpers["_SNAPSHOT_TOTAL_LIMIT"] = 16
    (source / "first.log").write_text("a" * 10)
    helpers["retain_failed_evidence"]()
    (source / "second.log").write_text("b" * 10)
    helpers["retain_failed_evidence"]()
    output = helpers["EVIDENCE"] / "job-evidence/attempt-1"
    assert (output / "first.log").exists()
    assert not (output / "second.log").exists()
    assert json.loads((helpers["EVIDENCE"] / "snapshot.json").read_text())["retained_bytes"] == 10


@_POSIX
def test_snapshot_rejects_a_file_swapped_for_symlink_before_open(
    helpers: dict, monkeypatch, tmp_path
) -> None:
    source = helpers["SCRATCH"] / "fixture_work/evidence/attempt-1"
    source.mkdir(parents=True)
    victim = source / "victim.log"
    victim.write_text("normal")
    secret = tmp_path / "secret"
    secret.write_text("must not be copied")
    original_open = os.open

    def swapping_open(path, flags, *args, **kwargs):
        if path == "victim.log":
            victim.unlink()
            victim.symlink_to(secret)
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", swapping_open)
    helpers["retain_failed_evidence"]()
    assert not (helpers["EVIDENCE"] / "job-evidence/attempt-1/victim.log").exists()


def test_generated_runtime_opts_into_diagnostics_without_changing_scientific_spec() -> None:
    script = kaggle_kernel.build_kernel_script(handle_id="test", payload={"spec.json": "unchanged"})
    assert 'job_env["BINDSIGHT_GPU_DIAGNOSTICS"] = "1"' in script
    assert "PAYLOAD = {'spec.json': 'unchanged'}" in script
    assert "threading.Thread(target=monitor_progress, daemon=True)" in script
    compile(script, "generated-kaggle", "exec")

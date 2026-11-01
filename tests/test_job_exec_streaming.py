# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Real CPU children prove live, bounded, redacted executor diagnostics."""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from contextlib import contextmanager

import pytest

from bindsight.runners import job_exec


@contextmanager
def evidence_at(root):
    root.mkdir(parents=True, exist_ok=True)
    evidence = job_exec._JobEvidence(root, root / "evidence")
    token = job_exec._EVIDENCE.set(evidence)
    try:
        yield evidence
    finally:
        job_exec._EVIDENCE.reset(token)


def no_reader_threads():
    assert not [
        t.name
        for t in threading.enumerate()
        if t.name.startswith(("bindsight-stdout-", "bindsight-stderr-"))
    ]


def test_live_output_and_running_receipt_exist_before_child_can_exit(tmp_path, capsys):
    gate = tmp_path / "finish"
    done = threading.Event()
    failure = []

    def run():
        try:
            with evidence_at(tmp_path):
                job_exec._run(
                    [
                        sys.executable,
                        "-c",
                        "import pathlib,time,sys; print('first live line',flush=True); "
                        "print('early stderr',file=sys.stderr,flush=True); "
                        f"gate=pathlib.Path({str(gate)!r}); "
                        "\nwhile not gate.exists(): time.sleep(0.02)",
                    ]
                )
        except Exception as error:
            failure.append(error)
        finally:
            done.set()

    thread = threading.Thread(target=run)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        live = tmp_path / "evidence/live/000001.stdout.log"
        while time.monotonic() < deadline and (
            not live.exists() or "first live line" not in live.read_text()
        ):
            assert not done.is_set(), failure
            time.sleep(0.02)
        assert "first live line" in live.read_text()
        current = json.loads((tmp_path / "evidence/current-command.json").read_text())
        assert current["phase"] == "running"
        assert current["running"] is True
        assert not done.is_set()
        assert "first live line" in capsys.readouterr().out
    finally:
        gate.touch()
        thread.join(15)
    assert not thread.is_alive()
    assert not failure
    assert json.loads((tmp_path / "evidence/current-command.json").read_text())["phase"] == "ok"
    no_reader_threads()


def test_split_secrets_and_utf8_are_redacted_only_in_logs(tmp_path, monkeypatch, capsys):
    secret = "fixture-secret-split-across-child-writes"
    monkeypatch.setenv("TEST_API_TOKEN", secret)
    code = (
        "import os,time; s=os.environ['TEST_API_TOKEN'].encode(); "
        "os.write(1,s[:13]); time.sleep(.1); os.write(1,s[13:]+b'\\n'); "
        "os.write(2,b'\\xe2'); time.sleep(.1); os.write(2,b'\\x82\\xac\\r'); "
        "time.sleep(.1); os.write(2,b'\\n')"
    )
    with evidence_at(tmp_path):
        result = job_exec._run([sys.executable, "-c", code])
    assert result.stdout == secret + "\n"
    assert result.stderr == "€\n"
    output = capsys.readouterr()
    assert secret not in output.out + output.err
    assert output.err == "€\n"
    for path in (tmp_path / "evidence").rglob("*"):
        if path.is_file():
            assert secret not in path.read_text()
    assert "<redacted>" in (tmp_path / "evidence/live/000001.stdout.log").read_text()
    no_reader_threads()


def test_both_large_pipes_are_drained_and_all_capture_is_bounded(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(job_exec, "_LOG_LIMIT", 4096)
    code = (
        "import os,threading; "
        "\ndef flood(fd,letter):\n"
        " os.write(fd,b'first\\n')\n"
        " for _ in range(3000): os.write(fd,letter*1000+b'\\n')\n"
        " os.write(fd,b'last\\n')\n"
        "a=threading.Thread(target=flood,args=(1,b'A')); a.start(); flood(2,b'B'); a.join()"
    )
    with evidence_at(tmp_path):
        result = job_exec._run([sys.executable, "-c", code])
    for text in (result.stdout, result.stderr):
        assert text.startswith("first\n")
        assert text.endswith("last\n")
        assert len(text.encode()) <= 4096
    record = json.loads((tmp_path / "evidence/commands/000001.json").read_text())
    assert record["stdout"]["truncated"] is True
    assert record["stderr"]["truncated"] is True
    assert all(p.stat().st_size <= 4096 for p in (tmp_path / "evidence/live").glob("*.log"))
    output = capsys.readouterr()
    assert len(output.out.encode()) <= 4096
    assert len(output.err.encode()) <= 4096
    no_reader_threads()


def test_oversized_unterminated_line_does_not_leak_partial_secret(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(job_exec, "_LINE_LIMIT", 100)
    monkeypatch.setenv("TEST_API_TOKEN", "start-" + "A" * 300 + "-finish")
    with evidence_at(tmp_path):
        job_exec._run(
            [sys.executable, "-c", "import os; print(os.environ['TEST_API_TOKEN']); print('after')"]
        )
    visible = capsys.readouterr().out
    assert "oversized output line suppressed" in visible
    assert "start-" not in visible
    assert "-finish" not in visible
    assert "after\n" in visible
    live = (tmp_path / "evidence/live/000001.stdout.log").read_text()
    assert "start-" not in live
    assert "-finish" not in live


def test_timeout_retains_partial_live_output_and_final_receipt(tmp_path, monkeypatch):
    monkeypatch.setattr(job_exec, "_TOOL_TIMEOUT_S", 0.5)
    with evidence_at(tmp_path), pytest.raises(RuntimeError, match="tool timeout"):
        job_exec._run(
            [
                sys.executable,
                "-c",
                "import time; print('before timeout',flush=True); time.sleep(30)",
            ]
        )
    record = json.loads((tmp_path / "evidence/commands/000001.json").read_text())
    assert record["outcome"] == "timeout"
    assert "before timeout" in record["stdout"]["text"]
    current = json.loads((tmp_path / "evidence/current-command.json").read_text())
    assert current["phase"] == "timeout"
    assert current["running"] is False
    no_reader_threads()


def test_nonzero_and_spawn_failure_have_terminal_receipts(tmp_path):
    for name, cmd, error in [
        (
            "nonzero",
            [
                sys.executable,
                "-c",
                "import sys; print('failure detail',file=sys.stderr); sys.exit(3)",
            ],
            RuntimeError,
        ),
        ("spawn_error", [str(tmp_path / "missing-executable")], OSError),
    ]:
        root = tmp_path / name
        with evidence_at(root), pytest.raises(error):
            job_exec._run(cmd)
        assert json.loads((root / "evidence/current-command.json").read_text())["phase"] == name
        assert json.loads((root / "evidence/commands/000001.json").read_text())["outcome"] == name
    no_reader_threads()


def test_small_output_matches_completedprocess_text_semantics(tmp_path):
    cmd = [
        sys.executable,
        "-c",
        "import sys; print('bindsight boltz version=2.0.3+bindsight.1'); print('stderr',file=sys.stderr)",
    ]
    expected = subprocess.run(cmd, capture_output=True, text=True, check=True)
    actual = job_exec._stream_command(cmd, cwd=None, timeout=10)
    assert actual.stdout == expected.stdout
    assert actual.stderr == expected.stderr
    assert actual.args == expected.args
    assert actual.returncode == expected.returncode


def test_running_snapshot_preserves_designs_before_validator(tmp_path, monkeypatch):
    def designer(spec, work, tools):
        attempt = next((work / "evidence").glob("attempt-*"))
        assert json.loads((attempt / "manifest.json").read_text())["status"] == "running"
        assert json.loads((attempt / "spec.json").read_text()) == spec
        for name in ("rfdiff_out/backbone.pdb", "mpnn_out/seqs/binder.fa"):
            path = work / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("scientific artifact")
        return [job_exec.Design("binder", "AAAA", work / "binder.pdb")]

    def validator(spec, designs, work):
        attempt = next((work / "evidence").glob("attempt-*"))
        assert json.loads((attempt / "manifest.json").read_text())["status"] == "running"
        assert (attempt / "raw/rfdiff_out/backbone.pdb").read_text() == "scientific artifact"
        assert (attempt / "raw/mpnn_out/seqs/binder.fa").read_text() == "scientific artifact"
        raise RuntimeError("validator fixture stop")

    monkeypatch.setitem(job_exec._DESIGNERS, "stream_fixture", designer)
    monkeypatch.setitem(job_exec._VALIDATORS, "stream_fixture", validator)
    spec = {"extra_params": {"designer": "stream_fixture", "validator": "stream_fixture"}}
    with pytest.raises(RuntimeError, match="validator fixture stop"):
        job_exec.run_job(spec, tmp_path / "job")
    attempt = next((tmp_path / "job/evidence").glob("attempt-*"))
    assert json.loads((attempt / "manifest.json").read_text())["status"] == "failed"
    assert (attempt / "raw/rfdiff_out/backbone.pdb").exists()


def test_pipe_inherited_by_grandchild_cannot_hold_reader_threads_open(tmp_path):
    pid_file = tmp_path / "grandchild.pid"
    code = (
        "import subprocess,sys,pathlib; "
        "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); "
        f"pathlib.Path({str(pid_file)!r}).write_text(str(p.pid)); print('parent done',flush=True)"
    )
    try:
        start = time.monotonic()
        result = job_exec._stream_command([sys.executable, "-c", code], cwd=None, timeout=10)
        assert time.monotonic() - start < 6
        assert "parent done" in result.stdout
        no_reader_threads()
    finally:
        if pid_file.exists():
            import psutil

            with __import__("contextlib").suppress(psutil.NoSuchProcess):
                child = psutil.Process(int(pid_file.read_text()))
                child.kill()
                child.wait(10)


def test_reader_start_failure_reaps_the_owned_process(monkeypatch):
    processes = []
    real_popen = job_exec.subprocess.Popen

    def spawn(*args, **kwargs):
        process = real_popen(*args, **kwargs)
        processes.append(process)
        return process

    def fail_start(thread):
        raise RuntimeError("reader resource fixture")

    monkeypatch.setattr(job_exec.subprocess, "Popen", spawn)
    monkeypatch.setattr(job_exec.threading.Thread, "start", fail_start)
    with pytest.raises(OSError, match="Cannot start command output reader"):
        job_exec._stream_command(
            [sys.executable, "-c", "import time; time.sleep(30)"], cwd=None, timeout=10
        )
    assert processes
    assert all(process.poll() is not None for process in processes)
    no_reader_threads()


def test_cp1252_console_replaces_unencodable_text_without_failing_work(tmp_path, monkeypatch):
    import io

    output = io.BytesIO()
    console = io.TextIOWrapper(output, encoding="cp1252", newline="\n")
    with monkeypatch.context() as changed:
        changed.setattr(job_exec.sys, "stdout", console)
        with evidence_at(tmp_path):
            result = job_exec._run(
                [sys.executable, "-c", "import os; os.write(1, b'\\xf0\\x9f\\xa7\\xac done\\n')"]
            )
        console.flush()
    assert result.stdout == "🧬 done\n"
    assert output.getvalue() == b"? done\n"
    assert "🧬" in (tmp_path / "evidence/live/000001.stdout.log").read_text(encoding="utf-8")


def test_broken_console_does_not_discard_durable_output(tmp_path, monkeypatch):
    class ClosedConsole:
        encoding = "utf-8"

        def write(self, text):
            raise BrokenPipeError("consumer closed")

        def flush(self):
            raise BrokenPipeError("consumer closed")

    with monkeypatch.context() as changed:
        changed.setattr(job_exec.sys, "stdout", ClosedConsole())
        with evidence_at(tmp_path):
            result = job_exec._run([sys.executable, "-c", "print('still completed')"])
    assert result.returncode == 0
    assert "still completed" in (tmp_path / "evidence/live/000001.stdout.log").read_text()
    assert json.loads((tmp_path / "evidence/current-command.json").read_text())["phase"] == "ok"


def test_live_files_are_not_rewritten_for_every_line(tmp_path, monkeypatch):
    from pathlib import Path

    replaces = []
    real_replace = Path.replace

    def replace(path, target):
        if path.parent.name == "live":
            replaces.append(path)
        return real_replace(path, target)

    monkeypatch.setattr(Path, "replace", replace)
    with evidence_at(tmp_path):
        job_exec._run([sys.executable, "-c", "for i in range(1000): print('line',i)"])
    assert len(replaces) < 20
    assert "line 999" in (tmp_path / "evidence/live/000001.stdout.log").read_text()


def test_sigterm_handler_is_restored_and_failure_evidence_cannot_mask_exit(tmp_path, monkeypatch):
    import signal

    original = signal.getsignal(signal.SIGTERM)

    def execute(*args, **kwargs):
        signal.raise_signal(signal.SIGTERM)

    def evidence(spec, status, error=None):
        if status == "failed":
            raise OSError("evidence fixture failed")

    monkeypatch.setattr(job_exec, "_execute_job", execute)
    monkeypatch.setattr(job_exec, "_finish_evidence", evidence)
    with pytest.raises(SystemExit) as caught:
        job_exec.run_job({}, tmp_path / "job")
    assert caught.value.code == 128 + signal.SIGTERM
    assert signal.getsignal(signal.SIGTERM) == original
    assert job_exec._EVIDENCE.get() is None


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX SIGTERM/process-group regression")
def test_sigterm_reaps_active_scientific_child_and_records_interruption(tmp_path):
    import contextlib
    import os
    import signal

    import psutil

    pid_file = tmp_path / "child.pid"
    child_code = (
        "import os,pathlib,time; "
        f"pathlib.Path({str(pid_file)!r}).write_text(str(os.getpid())); "
        "print('scientific child started',flush=True); time.sleep(60)"
    )
    driver_code = (
        "import sys; from pathlib import Path; from bindsight.runners import job_exec; "
        "\ndef designer(spec,work,tools):\n"
        f" job_exec._run([sys.executable,'-c',{child_code!r}])\n"
        " return []\n"
        "job_exec._DESIGNERS['signal_fixture']=designer\n"
        f"job_exec.run_job({{'extra_params': {{'designer': 'signal_fixture'}}}}, Path({str(tmp_path / 'job')!r}))\n"
    )
    driver = subprocess.Popen(
        [sys.executable, "-c", driver_code], stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    try:
        deadline = time.monotonic() + 15
        while not pid_file.exists() and time.monotonic() < deadline:
            assert driver.poll() is None
            time.sleep(0.05)
        child_pid = int(pid_file.read_text())
        os.kill(driver.pid, signal.SIGTERM)
        driver.communicate(timeout=15)
        assert driver.returncode == 128 + signal.SIGTERM
        assert not psutil.pid_exists(child_pid)
        attempt = next((tmp_path / "job/evidence").glob("attempt-*"))
        assert json.loads((attempt / "current-command.json").read_text())["phase"] == "interrupted"
        assert json.loads((attempt / "manifest.json").read_text())["status"] == "failed"
    finally:
        if driver.poll() is None:
            driver.kill()
            driver.communicate(timeout=10)
        if pid_file.exists():
            with contextlib.suppress(psutil.NoSuchProcess):
                child = psutil.Process(int(pid_file.read_text()))
                child.kill()
                child.wait(10)


def test_zero_exit_boltz_without_confidence_fails_and_preserves_design_evidence(
    tmp_path, monkeypatch, caplog
):
    secret = "fixture-private-boltz-warning-token"
    monkeypatch.setenv("TEST_API_TOKEN", secret)
    monkeypatch.setattr(job_exec, "_target_sequence_for_design", lambda *args: "AAAA")
    monkeypatch.setattr(
        job_exec.tools,
        "build_boltz_cmd",
        lambda **kwargs: [
            sys.executable,
            "-c",
            "import os,sys; print(os.environ['TEST_API_TOKEN']); "
            "print(os.environ['TEST_API_TOKEN'],file=sys.stderr)",
        ],
    )

    def designer(spec, work, tools):
        fasta = work / "design/P0_binder.fasta"
        for path in (fasta, work / "rfdiff_out/backbone.pdb", work / "mpnn_out/seqs/binder.fa"):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(">P0_binder\nAAAA\n")
        return [job_exec.Design("P0_binder", "AAAA", fasta)]

    monkeypatch.setitem(job_exec._DESIGNERS, "empty_boltz_fixture", designer)
    work = tmp_path / "job"
    spec = {
        "target_uniprot": "P0",
        "extra_params": {"designer": "empty_boltz_fixture", "validator": "boltz2"},
    }
    with pytest.raises(RuntimeError, match="refusing incomplete validation"):
        job_exec.run_job(spec, work)
    assert secret not in caplog.text
    assert "boltz2 produced no confidence" in caplog.text
    assert "<redacted>" in caplog.text
    assert (work / "design/P0_binder.fasta").exists()
    attempt = next((work / "evidence").glob("attempt-*"))
    assert (attempt / "raw/rfdiff_out/backbone.pdb").exists()
    assert (attempt / "raw/mpnn_out/seqs/binder.fa").exists()
    assert json.loads((attempt / "manifest.json").read_text())["status"] == "failed"
    assert json.loads((attempt / "commands/000001.json").read_text())["returncode"] == 0
    assert not work.with_suffix(".tar.gz").exists()
    assert not (work / "metrics.jsonl").exists()

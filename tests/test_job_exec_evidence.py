# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Exercise real subprocess capture and selective transported job evidence."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

from bindsight.runners import job_exec


def _write(root: Path, name: str, content: bytes = b"fixture") -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _install_fake_pipeline(monkeypatch, designer) -> dict:
    monkeypatch.setitem(job_exec._DESIGNERS, "evidence_test", designer)
    monkeypatch.setitem(job_exec._VALIDATORS, "evidence_test", lambda *args: [{"iptm": 0.4}])
    return {"seed": 42, "extra_params": {"designer": "evidence_test", "validator": "evidence_test"}}


def test_success_transports_commands_raw_inputs_and_weight_receipt_without_weight_bytes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("KAGGLE_API_TOKEN", "secret-from-environment-123")

    def designer(spec, work, tools):
        job_exec._run(
            [
                sys.executable,
                "-c",
                "import os,sys; print('precision=32 iptm=0.4'); print(os.environ['KAGGLE_API_TOKEN'],file=sys.stderr)",
            ]
        )
        for name in (
            "target.pdb",
            "rfdiff_out/binder_42.pdb",
            "rfdiff_out/binder_42.trb",
            "mpnn_out/binder_42/seqs/binder.fa",
            "boltz_out/binder.yaml",
            "boltz_out/binder/boltz_results_binder/processed/msa/0.npz",
            "boltz_out/binder/boltz_results_binder/msas/input.a3m",
        ):
            _write(work, name)
        _write(
            work,
            "boltz_out/binder/boltz_results_binder/processed/manifest.json",
            b'{"id":"binder"}',
        )
        weight = _write(work, "_tools/RFdiffusion/models/model.pt", b"weight bytes must stay local")
        job_exec._verify_checkpoint(weight, hashlib.sha256(weight.read_bytes()).hexdigest())
        _write(work, "boltz_out/binder/boltz_results_binder/processed/model.pt", b"another weight")
        _write(work, "boltz_out/binder/.env", b"TOKEN=secret-config")
        _write(work, "unrelated-cache/private.json", b'{"password":"private"}')
        fasta = _write(work, "design/binder.fasta", b">binder\nACDE\n")
        return [job_exec.Design("binder", "ACDE", fasta)]

    spec = _install_fake_pipeline(monkeypatch, designer)
    spec["extra_params"]["api_key"] = "not-an-environment-secret"
    archive = job_exec.run_job(spec, tmp_path / "job")
    with tarfile.open(archive) as result:
        names = result.getnames()
        for path in (
            "design/binder.fasta",
            "metrics.jsonl",
            "prescreen.txt",
            "evidence/spec.json",
            "evidence/raw/rfdiff_out/binder_42.pdb",
            "evidence/raw/rfdiff_out/binder_42.trb",
            "evidence/raw/mpnn_out/binder_42/seqs/binder.fa",
            "evidence/raw/boltz_out/binder.yaml",
            "evidence/raw/boltz_out/binder/boltz_results_binder/processed/msa/0.npz",
        ):
            assert path in names
        assert not any(
            name.endswith((".pt", ".env")) or "unrelated-cache" in name for name in names
        )
        command = json.load(result.extractfile("evidence/commands/000001.json"))
        assert command["outcome"] == "ok"
        assert "precision=32 iptm=0.4" in command["stdout"]["text"]
        assert command["stderr"]["text"] == "<redacted>\n"
        assert "secret-from-environment-123" not in json.dumps(command)
        assert (
            json.load(result.extractfile("evidence/spec.json"))["extra_params"]["api_key"]
            == "<redacted>"
        )
        weights = json.load(result.extractfile("evidence/weights.json"))
        assert weights[0]["sha256"] == hashlib.sha256(b"weight bytes must stay local").hexdigest()
        assert weights[0]["pin_match"] is True
        manifest = json.load(result.extractfile("evidence/manifest.json"))
        assert manifest["status"] == "completed"
        assert manifest["missing_categories"] == []
        for row in manifest["files"]:
            assert (
                hashlib.sha256(result.extractfile("evidence/raw/" + row["path"]).read()).hexdigest()
                == row["sha256"]
            )
    assert job_exec._EVIDENCE.get() is None


@pytest.mark.parametrize("mode", ["nonzero", "timeout", "spawn_error"])
def test_failure_retains_output_and_resets_recording(
    tmp_path: Path, monkeypatch, mode: str
) -> None:
    def spawn(*args, **kwargs):
        if mode == "timeout":
            raise subprocess.TimeoutExpired(
                args[0], 1, output=b"partial stdout", stderr=b"partial stderr"
            )
        if mode == "spawn_error":
            raise FileNotFoundError("missing scientific executable")
        return subprocess.CompletedProcess(args[0], 2, "before failure", "model failed")

    monkeypatch.setattr(job_exec, "_stream_command", spawn)

    def designer(*args):
        job_exec._run(["model", "--seed", "42"])

    spec = _install_fake_pipeline(monkeypatch, designer)
    work = tmp_path / "job"
    with pytest.raises((RuntimeError, FileNotFoundError)):
        job_exec.run_job(spec, work)
    receipt = next(work.glob("evidence/attempt-*/commands/*.json"))
    command = json.loads(receipt.read_text())
    assert command["outcome"] == mode
    if mode == "timeout":
        assert command["stdout"]["text"] == "partial stdout"
        assert command["stderr"]["text"] == "partial stderr"
    if mode == "nonzero":
        assert command["returncode"] == 2
        assert command["stdout"]["text"] == "before failure"
    assert json.loads((receipt.parent.parent / "manifest.json").read_text())["status"] == "failed"
    assert not work.with_suffix(".tar.gz").exists()
    assert job_exec._EVIDENCE.get() is None


def test_retry_archives_only_current_receipts_and_reports_truncation(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(job_exec, "_LOG_LIMIT", 64)
    output = "first attempt"

    def designer(*args):
        job_exec._run([sys.executable, "-c", f"print({output!r})"])
        return [job_exec.Design("binder", "ACDE", tmp_path / "unused.pdb")]

    spec = _install_fake_pipeline(monkeypatch, designer)
    work = tmp_path / "job"
    job_exec.run_job(spec, work)
    output = "start " + "A" * 1000 + " end"
    archive = job_exec.run_job(spec, work)
    assert len(list((work / "evidence").glob("attempt-*"))) == 2
    with tarfile.open(archive) as result:
        commands = [name for name in result.getnames() if name.startswith("evidence/commands/")]
        assert commands == ["evidence/commands/000001.json"]
        command = json.load(result.extractfile(commands[0]))
        assert command["stdout"]["truncated"] is True
        assert "start " in command["stdout"]["text"]
        assert " end" in command["stdout"]["text"]
        assert "first attempt" not in json.dumps(command)


def test_evidence_refuses_symlinks(tmp_path: Path, monkeypatch) -> None:
    external = _write(tmp_path, "private.txt", b"must never be transported")
    work = tmp_path / "job"
    link = work / "rfdiff_out" / "escaped.pdb"
    link.parent.mkdir(parents=True)
    try:
        link.symlink_to(external)
    except OSError:
        pytest.skip("This host does not permit creating symbolic links")

    def designer(*args):
        return [job_exec.Design("binder", "ACDE", tmp_path / "unused.pdb")]

    archive = job_exec.run_job(_install_fake_pipeline(monkeypatch, designer), work)
    with tarfile.open(archive) as result:
        manifest = json.load(result.extractfile("evidence/manifest.json"))
        assert {row["reason"] for row in manifest["skipped"]} == {"symbolic link"}
        assert not any("escaped.pdb" in name for name in result.getnames())


def test_evidence_records_oversized_artifacts(tmp_path: Path, monkeypatch) -> None:
    work = tmp_path / "job"
    monkeypatch.setattr(job_exec, "_ARTIFACT_LIMIT", 10)
    _write(work, "rfdiff_out/oversized.trb", b"X" * 11)

    def designer(*args):
        return [job_exec.Design("binder", "ACDE", tmp_path / "unused.pdb")]

    archive = job_exec.run_job(_install_fake_pipeline(monkeypatch, designer), work)
    with tarfile.open(archive) as result:
        manifest = json.load(result.extractfile("evidence/manifest.json"))
        assert manifest["skipped"] == [
            {"path": "rfdiff_out/oversized.trb", "reason": "evidence size limit", "bytes": 11}
        ]
        assert not any("oversized.trb" in name for name in result.getnames())


def test_redaction_keeps_sequences_scores_and_removes_url_credentials() -> None:
    raw = 'https://person:password@example.org/msa?token=abc#secret {"api_key": "not-a-known-prefix"} Bearer confidential-value iptm=0.42 ACDEFGHIKLMNPQRSTVWY'
    redacted = job_exec._redact(raw)
    assert "person:password" not in redacted
    assert "token=abc" not in redacted
    assert "not-a-known-prefix" not in redacted
    assert "confidential-value" not in redacted
    assert "iptm=0.42 ACDEFGHIKLMNPQRSTVWY" in redacted

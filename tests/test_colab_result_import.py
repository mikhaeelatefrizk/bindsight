# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Exercise the documented notebook/download/validate handoff without a GPU."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import tarfile
from pathlib import Path

import pandas as pd
import pytest
from click import ClickException
from click.testing import CliRunner

from bindsight import cli
from bindsight.runners.job_exec import _binder_id_prefix


def make_jobs(tmp_path: Path, *, sites: int = 1) -> tuple[Path, list[Path]]:
    run = tmp_path / "run"
    (run / "epitopes").mkdir(parents=True)
    target = run / "target.pdb"
    target.write_text("ATOM target fixture\n", encoding="utf-8")
    pd.DataFrame(
        [
            {
                "uniprot_id": "P04626",
                "structure_path": str(target),
                "chain": "A",
                "residues": [10 + i],
                "design_ranges": [[1, 50]],
            }
            for i in range(sites)
        ]
    ).to_parquet(run / "epitopes/epitopes.parquet")
    assert cli._write_design_notebooks(run, designer="rfdiff_mpnn", trajectories=1) == sites
    return run, sorted((run / "design").glob("*.spec.json"))


def result_files(spec_path: Path) -> tuple[dict[str, bytes], str]:
    spec = json.loads(spec_path.read_text())
    binder = _binder_id_prefix(spec) + "_binder_0_seq0"
    row = {
        "binder_id": binder,
        "target_uniprot": "P04626",
        "iptm": 0.8,
        "pae_interaction": 3.0,
        "validator_name": "boltz2",
        "validator_version": "2.0.3+bindsight.1",
    }
    return {
        "metrics.jsonl": (json.dumps(row) + "\n").encode(),
        "evidence/spec.json": json.dumps(spec).encode(),
        "evidence/manifest.json": b'{"status":"completed"}',
        "evidence/raw/target.pdb": base64.b64decode(spec["target_structure_b64"]),
        f"design/{binder}.fasta": f">{binder}\nAAAA\n".encode(),
        f"validate/{binder}/complex.pdb": b"ATOM predicted fixture\n",
        f"validate/{binder}/confidence.json": b'{"iptm":0.8}',
    }, binder


def write_archive(spec_path: Path, files: dict[str, bytes], *, extra=None) -> Path:
    archive = spec_path.with_name(spec_path.name.removesuffix(".spec.json") + ".tar.gz")
    with tarfile.open(archive, "w:gz") as tf:
        for name, data in files.items():
            member = tarfile.TarInfo(name)
            member.size = len(data)
            tf.addfile(member, io.BytesIO(data))
        if extra is not None:
            tf.addfile(extra)
    return archive


def assert_not_imported(run: Path) -> None:
    assert not (run / "design/metrics.jsonl").exists()
    assert not (run / "design/_targets").exists()
    assert not (run / "validate/validated.parquet").exists()


def test_documented_cli_handoff_and_idempotent_validation(tmp_path):
    run, specs = make_jobs(tmp_path, sites=2)
    binders = []
    for spec in specs:
        files, binder = result_files(spec)
        binders.append(binder)
        write_archive(spec, files)
    assert len(list((run / "design").glob("*.ipynb"))) == 2
    for _ in range(2):
        result = CliRunner().invoke(cli.main, ["validate", str(run)])
        assert result.exit_code == 0, result.output + str(result.exception)
        frame = pd.read_parquet(run / "validate/validated.parquet")
        assert set(frame.binder_id) == set(binders)
        assert set(frame.passes_thresholds) == {"pass"}
    assert len(list((run / "design/_targets").glob("*.tar.gz"))) == 2
    assert len(list((run / "design").glob("*.tar.gz"))) == 2
    for binder in binders:
        assert (
            run / "validate" / binder / "complex.pdb"
        ).read_bytes() == b"ATOM predicted fixture\n"


def hosted_files(*, backend: str = "colab", outcome: str = "completed") -> dict[str, bytes]:
    """Construct the selected receipt set, with the real wrapper manifest writer."""
    status = {
        "schema": "bindsight-hosted-run/1",
        "backend": backend,
        "outcome": outcome,
        "returncode": 0,
    }
    files = {
        "backend-status.json": json.dumps(status).encode(),
        "provision-receipt.json": b"{}",
        "hardware.json": b"{}",
        "model-weights.json": b"{}",
        "se3-final-freeze.txt": b"torch==2.14.1+cu126\n",
        "boltz-final-freeze.txt": b"torch==2.14.1+cu126\n",
    }
    manifest = {
        "schema": "bindsight-hosted-evidence/1",
        "files": [
            {"path": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
            for name, data in sorted(files.items())
        ],
    }
    return {"runtime/" + name: data for name, data in files.items()} | {
        "runtime/manifest.json": json.dumps(manifest).encode()
    }


@pytest.mark.parametrize("backend", ["colab", "modal"])
def test_real_hosted_packer_to_production_validate_preserves_science(tmp_path, backend):
    from bindsight.runners.hosted_job import _pack, _receipt_manifest

    run, specs = make_jobs(tmp_path)
    scientific_files, binder = result_files(specs[0])
    original = write_archive(specs[0], scientific_files)
    scientific = tmp_path / "science.tar.gz"
    original.replace(scientific)
    receipts = tmp_path / "runtime"
    receipts.mkdir()
    for name, data in hosted_files(backend=backend).items():
        if name != "runtime/manifest.json":
            (receipts / Path(name).name).write_bytes(data)
    _receipt_manifest(receipts)
    _pack(scientific, receipts, original, tmp_path / "unused-work")
    original_bytes = original.read_bytes()
    result = CliRunner().invoke(cli.main, ["validate", str(run)])
    assert result.exit_code == 0, result.output + str(result.exception)
    frame = pd.read_parquet(run / "validate/validated.parquet")
    assert frame.iloc[0].binder_id == binder
    assert frame.iloc[0].iptm == 0.8
    assert (run / f"validate/{binder}/complex.pdb").read_bytes() == scientific_files[
        f"validate/{binder}/complex.pdb"
    ]
    assert original.read_bytes() == original_bytes
    assert not (run / "runtime").exists()
    assert not (run / "validate/runtime").exists()
    retained = next((run / "design/_targets").glob("*.tar.gz"))
    assert retained.read_bytes() == original_bytes


@pytest.mark.parametrize("outcome", ["failed", "incomplete", "running"])
def test_hosted_noncompletion_refused_despite_valid_scientific_metrics(tmp_path, outcome):
    run, specs = make_jobs(tmp_path)
    files, _ = result_files(specs[0])
    files.update(hosted_files(outcome=outcome))
    write_archive(specs[0], files)
    with pytest.raises(ClickException, match="completed successful"):
        cli._finalize_validate(run)
    assert_not_imported(run)


@pytest.mark.parametrize(
    "problem",
    [
        "digest",
        "size",
        "missing",
        "unlisted",
        "duplicate",
        "unsafe_path",
        "status_returncode",
        "status_bool",
        "backend",
        "backend_type",
        "status_schema",
        "manifest_schema",
        "duplicate_json_key",
    ],
)
def test_hosted_manifest_and_completion_tampering_refused(tmp_path, problem):
    run, specs = make_jobs(tmp_path)
    files, _ = result_files(specs[0])
    runtime = hosted_files()
    manifest = json.loads(runtime["runtime/manifest.json"])
    if problem == "digest":
        runtime["runtime/hardware.json"] = b'{"tampered":true}'
    elif problem == "size":
        manifest["files"][0]["bytes"] += 1
    elif problem == "missing":
        runtime.pop("runtime/model-weights.json")
    elif problem == "unlisted":
        manifest["files"].pop()
    elif problem == "duplicate":
        manifest["files"].append(manifest["files"][0])
    elif problem == "unsafe_path":
        manifest["files"][0]["path"] = "../validate/replacement"
    elif problem == "manifest_schema":
        manifest["schema"] = "unknown"
    else:
        status = json.loads(runtime["runtime/backend-status.json"])
        if problem == "status_returncode":
            status["returncode"] = 1
        elif problem == "status_bool":
            status["returncode"] = False
        elif problem == "backend":
            status["backend"] = "unknown"
        elif problem == "backend_type":
            status["backend"] = []
        elif problem == "status_schema":
            status["schema"] = "unknown"
        data = json.dumps(status).encode()
        if problem == "duplicate_json_key":
            data = data[:-1] + b', "outcome":"completed"}'
        runtime["runtime/backend-status.json"] = data
        for entry in manifest["files"]:
            if entry["path"] == "backend-status.json":
                entry.update(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
    runtime["runtime/manifest.json"] = json.dumps(manifest).encode()
    files.update(runtime)
    write_archive(specs[0], files)
    with pytest.raises(ClickException, match=r"[Hh]osted|runtime"):
        cli._finalize_validate(run)
    assert_not_imported(run)


@pytest.mark.parametrize(
    "name",
    [
        "runtime/extra.json",
        "runtime/validate/binder/file",
        "runtime/../validate/file",
        "runtime/provision-receipt.json/nested",
        "runtime/HARDWARE.json",
    ],
)
def test_runtime_cannot_smuggle_unselected_or_scientific_outputs(tmp_path, name):
    run, specs = make_jobs(tmp_path)
    files, _ = result_files(specs[0])
    files.update(hosted_files())
    files[name] = b"unselected evidence"
    write_archive(specs[0], files)
    with pytest.raises(ClickException, match=r"Unsafe|runtime|duplicate"):
        cli._finalize_validate(run)
    assert_not_imported(run)


def test_runtime_member_above_individual_limit_refused(tmp_path):
    run, specs = make_jobs(tmp_path)
    files, _ = result_files(specs[0])
    files.update(hosted_files())
    files["runtime/hardware.json"] = b"x" * (16 * 1024**2 + 1)
    write_archive(specs[0], files)
    with pytest.raises(ClickException, match="oversized hosted"):
        cli._finalize_validate(run)
    assert_not_imported(run)


@pytest.mark.parametrize(
    "name",
    [
        "../escape",
        "/absolute",
        "validate/../../escape",
        "validate\\escape",
        "validate/C:/escape",
        "validate/con/file",
        "validate/x./file",
        "validate//x/file",
        "metrics.jsonl",
        "evidence/SPEC.json",
    ],
)
def test_unsafe_and_duplicate_members_leave_outputs_untouched(tmp_path, name):
    run, specs = make_jobs(tmp_path)
    files, _ = result_files(specs[0])
    write_archive(specs[0], files, extra=tarfile.TarInfo(name))
    with pytest.raises(ClickException, match=r"Unsafe|duplicate"):
        cli._finalize_validate(run)
    assert_not_imported(run)


@pytest.mark.parametrize(
    "kind", [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.CHRTYPE, tarfile.FIFOTYPE]
)
def test_link_and_special_members_refused(tmp_path, kind):
    run, specs = make_jobs(tmp_path)
    files, _ = result_files(specs[0])
    member = tarfile.TarInfo("evidence/redirect")
    member.type = kind
    member.linkname = "../../outside"
    write_archive(specs[0], files, extra=member)
    with pytest.raises(ClickException, match="Unsafe"):
        cli._finalize_validate(run)
    assert_not_imported(run)


@pytest.mark.parametrize(
    "problem",
    [
        "spec",
        "target_bytes",
        "target_metric",
        "binder",
        "duplicate",
        "empty",
        "incomplete",
        "missing_validation",
    ],
)
def test_inconsistent_results_refused(tmp_path, problem):
    run, specs = make_jobs(tmp_path)
    files, binder = result_files(specs[0])
    if problem == "spec":
        spec = json.loads(files["evidence/spec.json"])
        spec["seed"] += 1
        files["evidence/spec.json"] = json.dumps(spec).encode()
    elif problem == "target_bytes":
        files["evidence/raw/target.pdb"] = b"different target"
    elif problem in {"target_metric", "binder"}:
        row = json.loads(files["metrics.jsonl"])
        row["target_uniprot" if problem == "target_metric" else "binder_id"] = "OTHER"
        files["metrics.jsonl"] = json.dumps(row).encode()
    elif problem == "duplicate":
        files["metrics.jsonl"] *= 2
    elif problem == "empty":
        files["metrics.jsonl"] = b""
    elif problem == "incomplete":
        files["evidence/manifest.json"] = b'{"status":"failed"}'
    else:
        files = {
            name: data for name, data in files.items() if not name.startswith(f"validate/{binder}/")
        }
    write_archive(specs[0], files)
    with pytest.raises(ClickException):
        cli._finalize_validate(run)
    assert_not_imported(run)


def test_missing_one_job_does_not_partially_import_another(tmp_path):
    run, specs = make_jobs(tmp_path, sites=2)
    files, _ = result_files(specs[0])
    write_archive(specs[0], files)
    with pytest.raises(ClickException, match="Download all"):
        cli._finalize_validate(run)
    assert_not_imported(run)


def test_older_unrecorded_results_are_preserved_and_refused(tmp_path):
    run, specs = make_jobs(tmp_path)
    files, _ = result_files(specs[0])
    archive = write_archive(specs[0], files)
    original = archive.read_bytes()
    specs[0].unlink()
    with pytest.raises(ClickException, match="regenerate notebooks"):
        cli._finalize_validate(run)
    assert archive.read_bytes() == original
    assert_not_imported(run)


def test_existing_different_validation_output_is_never_overwritten(tmp_path):
    run, specs = make_jobs(tmp_path)
    files, binder = result_files(specs[0])
    write_archive(specs[0], files)
    conflict = run / "validate" / binder / "complex.pdb"
    conflict.parent.mkdir(parents=True)
    conflict.write_bytes(b"earlier scientific output")
    with pytest.raises(ClickException, match="refusing to overwrite"):
        cli._finalize_validate(run)
    assert conflict.read_bytes() == b"earlier scientific output"
    assert_not_imported(run)


def test_generation_refuses_changed_spec_without_replacing_notebook(tmp_path):
    run, specs = make_jobs(tmp_path)
    notebook = next((run / "design").glob("*.ipynb"))
    before = notebook.read_bytes(), specs[0].read_bytes()
    with pytest.raises(ClickException, match="different inputs"):
        cli._write_design_notebooks(run, designer="rfdiff_mpnn", trajectories=2)
    assert before == (notebook.read_bytes(), specs[0].read_bytes())


def test_unrecognized_download_is_not_guessed(tmp_path):
    run, specs = make_jobs(tmp_path)
    files, _ = result_files(specs[0])
    write_archive(specs[0], files).rename(run / "design/unknown.tar.gz")
    with pytest.raises(ClickException, match="Unrecognized"):
        cli._finalize_validate(run)
    assert_not_imported(run)


def test_later_revalidation_is_not_replaced_with_old_colab_scores(tmp_path):
    run, specs = make_jobs(tmp_path)
    files, binder = result_files(specs[0])
    write_archive(specs[0], files)
    cli._finalize_validate(run)
    metrics = run / "design/metrics.jsonl"
    row = json.loads(metrics.read_text())
    row.update(validator_name="chai1r", validator_version="new", iptm=0.6)
    metrics.write_text(json.dumps(row) + "\n")
    cli._finalize_validate(run)
    frame = pd.read_parquet(run / "validate/validated.parquet")
    assert frame.iloc[0].validator_name == "chai1r"
    assert frame.iloc[0].iptm == 0.6
    assert frame.iloc[0].binder_id == binder


def test_import_lock_prevents_concurrent_mutation(tmp_path):
    run, specs = make_jobs(tmp_path)
    files, _ = result_files(specs[0])
    write_archive(specs[0], files)
    lock = run / "design/.colab-import.lock"
    lock.write_text("owned by another import")
    with pytest.raises(ClickException, match="lock already exists"):
        cli._finalize_validate(run)
    assert lock.read_text() == "owned by another import"
    assert_not_imported(run)


def test_archive_changed_after_import_is_refused(tmp_path):
    run, specs = make_jobs(tmp_path)
    files, _ = result_files(specs[0])
    write_archive(specs[0], files)
    cli._finalize_validate(run)
    old_metrics = (run / "design/metrics.jsonl").read_bytes()
    files["evidence/extra.txt"] = b"changed"
    write_archive(specs[0], files)
    with pytest.raises(ClickException, match="Previously imported Colab inputs changed"):
        cli._finalize_validate(run)
    assert (run / "design/metrics.jsonl").read_bytes() == old_metrics


@pytest.mark.parametrize("extra", ["evidence/RAW/other.txt", "evidence/raw"])
def test_case_colliding_or_file_directory_paths_are_rejected(tmp_path, extra):
    run, specs = make_jobs(tmp_path)
    files, _ = result_files(specs[0])
    files[extra] = b"bad"
    write_archive(specs[0], files)
    with pytest.raises(ClickException, match=r"Case-colliding|replaced by a file"):
        cli._finalize_validate(run)
    assert_not_imported(run)


def test_oversized_member_is_refused_before_reading_its_content(tmp_path):
    import gzip

    run, specs = make_jobs(tmp_path)
    member = tarfile.TarInfo("evidence/huge.bin")
    member.size = 8 * 1024**3 + 1
    archive = specs[0].with_name(specs[0].name.removesuffix(".spec.json") + ".tar.gz")
    # Deliberately supply only a valid oversized header, never its 8 GiB body.
    # Python 3.13 correctly rejects addfile(nonempty_member) without a fileobj.
    with gzip.open(archive, "wb") as stream:
        stream.write(member.tobuf(format=tarfile.PAX_FORMAT) + b"\0" * 1024)
    assert archive.stat().st_size < 4096
    with tarfile.open(archive, "r:gz") as tf:
        assert tf.next().size == member.size
    with pytest.raises(ClickException, match="size or member limit"):
        cli._finalize_validate(run)
    assert_not_imported(run)


def test_truncated_download_is_actionable_and_does_not_import(tmp_path):
    run, specs = make_jobs(tmp_path)
    files, _ = result_files(specs[0])
    archive = write_archive(specs[0], files)
    archive.write_bytes(archive.read_bytes()[:60])
    with pytest.raises(ClickException, match="Cannot import Colab results"):
        cli._finalize_validate(run)
    assert_not_imported(run)


def test_existing_metrics_conflict_leaves_them_untouched(tmp_path):
    run, specs = make_jobs(tmp_path)
    files, _ = result_files(specs[0])
    write_archive(specs[0], files)
    row = json.loads(files["metrics.jsonl"])
    row["iptm"] = 0.1
    metrics = run / "design/metrics.jsonl"
    metrics.write_text(json.dumps(row) + "\n")
    before = metrics.read_bytes()
    with pytest.raises(ClickException, match="Conflicting metrics"):
        cli._finalize_validate(run)
    assert metrics.read_bytes() == before
    assert not (run / "design/_targets").exists()


def test_embedded_target_requires_matching_actual_target_evidence(tmp_path):
    run, specs = make_jobs(tmp_path)
    files, _ = result_files(specs[0])
    del files["evidence/raw/target.pdb"]
    write_archive(specs[0], files)
    with pytest.raises(ClickException, match="missing evidence/raw/target"):
        cli._finalize_validate(run)
    assert_not_imported(run)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("iptm", "0.8"),
        ("iptm", float("nan")),
        ("iptm", 1.2),
        ("pae_interaction", -1.0),
        ("pae_interaction", float("inf")),
        ("affinity_pred_value", float("nan")),
        ("iptm_n_samples", True),
    ],
)
def test_malformed_or_nonfinite_metric_values_are_rejected(tmp_path, field, value):
    run, specs = make_jobs(tmp_path)
    files, _ = result_files(specs[0])
    row = json.loads(files["metrics.jsonl"])
    row[field] = value
    files["metrics.jsonl"] = json.dumps(row).encode()
    write_archive(specs[0], files)
    with pytest.raises(ClickException):
        cli._finalize_validate(run)
    assert_not_imported(run)


def test_staged_archive_must_match_the_receipt_digest(tmp_path, monkeypatch):
    import shutil

    run, specs = make_jobs(tmp_path)
    files, _ = result_files(specs[0])
    write_archive(specs[0], files)
    copy = shutil.copyfile

    def corrupt_after_copy(source, destination, **kwargs):
        result = copy(source, destination, **kwargs)
        with Path(destination).open("ab") as stream:
            stream.write(b"changed after initial hashing")
        return result

    monkeypatch.setattr(shutil, "copyfile", corrupt_after_copy)
    with pytest.raises(ClickException, match="archive changed during import"):
        cli._finalize_validate(run)
    assert_not_imported(run)


def test_linked_validation_destination_cannot_escape_the_run(tmp_path):
    run, specs = make_jobs(tmp_path)
    files, _ = result_files(specs[0])
    write_archive(specs[0], files)
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (run / "validate").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("This Windows account cannot create directory symlinks")
    with pytest.raises(ClickException, match=r"outside|link"):
        cli._finalize_validate(run)
    assert not list(outside.iterdir())
    assert_not_imported(run)


def test_resolved_containment_works_without_python312_is_junction(tmp_path, monkeypatch):
    run = tmp_path / "selected-run"
    redirect = run / "design"
    redirect.mkdir(parents=True)
    real_resolve = Path.resolve

    def simulated_junction_resolve(path, *args, **kwargs):
        if path == redirect / "new-file.json":
            return tmp_path / "outside-run" / "new-file.json"
        return real_resolve(path, *args, **kwargs)

    monkeypatch.delattr(Path, "is_junction", raising=False)
    monkeypatch.setattr(Path, "resolve", simulated_junction_resolve)
    with pytest.raises(ClickException, match="resolves outside this run"):
        cli._check_import_destination(redirect / "new-file.json", run)


@pytest.mark.skipif(__import__("sys").platform != "win32", reason="Windows junction regression")
def test_actual_windows_junction_cannot_redirect_import(tmp_path, monkeypatch):
    import os
    import subprocess

    run, specs = make_jobs(tmp_path)
    files, _ = result_files(specs[0])
    write_archive(specs[0], files)
    outside = tmp_path / "outside"
    outside.mkdir()
    junction = run / "validate"
    environment = dict(
        os.environ, BINDSIGHT_TEST_LINK=str(junction), BINDSIGHT_TEST_TARGET=str(outside)
    )
    created = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "$ErrorActionPreference = 'Stop'; New-Item -ItemType Junction "
            "-Path $env:BINDSIGHT_TEST_LINK -Target $env:BINDSIGHT_TEST_TARGET | Out-Null",
        ],
        env=environment,
        capture_output=True,
        timeout=30,
    )
    if created.returncode:
        pytest.skip("Windows could not create an owned test junction")
    try:
        # Reproduce the Python 3.11 API surface even when CI runs a newer Python.
        monkeypatch.delattr(Path, "is_junction", raising=False)
        with pytest.raises(ClickException, match=r"outside|link"):
            cli._finalize_validate(run)
        assert not list(outside.iterdir())
        assert_not_imported(run)
    finally:
        # Remove only the junction entry, never recursively traverse its target.
        junction.rmdir()


def test_destination_is_relative_to_the_user_selected_run(tmp_path):
    selected = tmp_path / "custom-location" / "selected-run"
    selected.mkdir(parents=True)
    cli._check_import_destination(selected / "design" / "future-file", selected)
    with pytest.raises(ClickException, match="outside this run"):
        cli._check_import_destination(selected.parent / "other-run" / "file", selected)

# SPDX-License-Identifier: AGPL-3.0-or-later
"""Engineering regressions; artificial inputs here are never public research evidence."""

import gzip
import json
import os
import re
import subprocess
import sys
import threading
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from bindsight.deg.diagnostics import write_fit_diagnostics
from bindsight.deg.pydeseq2_runner import PyDESeq2Runner
from bindsight.report.coverage import annotation_coverage
from bindsight.report.web import resources
from bindsight.report.web.app import create_app
from bindsight.report.web.workspace import (
    Workspace,
    WorkspaceInUseError,
    inspect_inputs,
    write_json,
)


@pytest.fixture
def admitted_workstation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Lifecycle tests use fixed artificial admission; resource checks have dedicated tests."""
    monkeypatch.setattr(
        resources,
        "assess_execution",
        lambda *args, **kwargs: {
            "admitted": True,
            "n_cpus": 1,
            "policy": "artificial-lifecycle-test-only",
            "reasons": [],
        },
    )


def inputs(tmp_path: Path) -> tuple[Path, Path]:
    counts = tmp_path / "counts.tsv"
    design = tmp_path / "design.tsv"
    counts.write_text(
        "gene\t01\t02\t03\t04\t05\t06\n"
        + "".join(f"ENSG{i:011d}\t20\t30\t40\t50\t60\t70\n" for i in range(1, 12))
    )
    design.write_text(
        "sample\tcondition\tpatient\n01\t0\t001\n02\t1\t001\n03\t0\t002\n04\t1\t002\n05\t0\t003\n06\t1\t003\n"
    )
    return counts, design


def test_checks_last_row_instead_of_only_preview(tmp_path: Path) -> None:
    counts, design = inputs(tmp_path)
    with counts.open("a") as stream:
        stream.write("ENSG99999999999\t20\t30\t40\t50\t60\t0.2\n")
    with pytest.raises(ValueError, match="raw integer"):
        inspect_inputs(counts, design)


@pytest.mark.parametrize("raw", ["20.0000000000000001", "9007199254740993", "1_000", "١٢"])
def test_count_validation_never_rounds_invalid_input_into_an_integer(
    tmp_path: Path, raw: str
) -> None:
    counts, design = inputs(tmp_path)
    counts.write_text(counts.read_text().replace("\t20\t", f"\t{raw}\t", 1), encoding="utf-8")
    with pytest.raises(ValueError, match=r"raw integer|non-numeric"):
        inspect_inputs(counts, design)


def test_literal_numeric_patients_and_samples_remain_categorical(tmp_path: Path) -> None:
    _, design = inputs(tmp_path)
    parsed = PyDESeq2Runner.load_design(design, ["condition", "patient"])
    assert list(parsed.index) == ["01", "02", "03", "04", "05", "06"]
    assert isinstance(parsed.patient.dtype, pd.CategoricalDtype)
    assert list(parsed.patient.cat.categories) == ["001", "002", "003"]
    assert list(parsed.condition.cat.categories) == ["0", "1"]


def test_all_reference_failures_are_distinct_from_intentional_caps() -> None:
    taxonomy = pd.DataFrame(
        {
            "disposition": [
                "surfaced",
                "safety_unassessed",
                "normal_tissue_unassessed",
                "structure_confidence_unassessed",
                "uniprot_lookup_failed",
                "below_enrichment_cutoff",
                "structure_not_queried",
            ],
            "open_targets_status": ["ok"] * 7,
        }
    )
    result = annotation_coverage(taxonomy)
    assert result["unassessed_lookups"] == 4
    assert result["intentionally_beyond_enrichment_cap"] == 1
    assert result["structure_not_queried"] == 1


@pytest.mark.parametrize("recorded", [True, False])
def test_local_result_surfaces_verified_fit_diagnostics(tmp_path: Path, recorded: bool) -> None:
    root = tmp_path / "runs"
    identity = "a" * 32
    run = root / identity
    table = run / "deg/results.parquet"
    table.parent.mkdir(parents=True)
    table.write_bytes(b"artificial engineering fixture")
    if recorded:
        write_fit_diagnostics(table, {"residual_degrees_of_freedom": 2})
    state_dir = root / "_workbench" / identity
    state_dir.mkdir(parents=True)
    write_json(
        state_dir / "job.json",
        {"id": identity, "state": "completed", "run_dir": str(run)},
    )
    with TestClient(create_app(run_root=root)) as client:
        response = client.get(f"/api/workbench/jobs/{identity}")
        assert response.status_code == 200
        fit = response.json()["numerical_fit"]
        assert fit["available"] is recorded
        if recorded:
            assert "below 3" in fit["warnings"][0]
        else:
            assert "unavailable" in fit["details"][0]


def test_real_http_upload_inspection_and_host_token_guards(tmp_path: Path) -> None:
    counts, design = inputs(tmp_path)
    with TestClient(create_app(run_root=tmp_path / "runs")) as client:
        page = client.get("/workbench")
        token = re.search(r'data-session-token="([^"]+)"', page.text).group(1)
        headers = {"X-Bindsight-Token": token}
        assert client.post("/api/workbench/uploads").status_code == 403
        assert client.get("/runs", headers={"Host": "attacker.example"}).status_code == 403
        assert (
            client.post(
                "/api/workbench/uploads", headers={**headers, "Origin": "https://attacker.example"}
            ).status_code
            == 403
        )
        identity = client.post("/api/workbench/uploads", headers=headers).json()["id"]
        for kind, path in [("counts", counts), ("design", design)]:
            response = client.put(
                f"/api/workbench/uploads/{identity}/{kind}",
                headers={**headers, "X-Filename": path.name},
                content=path.read_bytes(),
            )
            assert response.status_code == 200
        result = client.post(f"/api/workbench/uploads/{identity}/inspect", headers=headers).json()
        assert result["samples"] == 6
        assert result["genes"] == 11
        assert "records" not in result
        assert client.post("/try/run", headers=headers).status_code == 410


def test_queued_paired_config_preserves_categories_and_disables_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, admitted_workstation: None
) -> None:
    counts, design = inputs(tmp_path)
    workspace = Workspace(tmp_path / "runs")
    monkeypatch.setattr(workspace.executor, "submit", lambda *args: None)
    identity = workspace.create_upload()
    (workspace.directory(identity) / "counts.tsv").write_bytes(counts.read_bytes())
    (workspace.directory(identity) / "design.tsv").write_bytes(design.read_bytes())
    workspace.launch(
        identity,
        {"factor": "condition", "numerator": "1", "denominator": "0", "paired_by": "patient"},
    )
    config = json.loads((workspace.directory(identity) / "config.json").read_text())
    assert config["params"]["deg"]["categorical_factors"] == ["condition", "patient"]
    assert config["params"]["deg"]["design_formula"] == "~ patient + condition"
    assert config["params"]["target_discovery"]["allow_bundled_mapping_fallback"] is False
    with pytest.raises(ValueError, match="already belong"):
        workspace.launch(identity, {})
    workspace.close()


def test_worker_startup_error_cannot_leave_a_job_queued(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = Workspace(tmp_path / "runs")
    identity = workspace.create_upload()
    state_path = workspace.directory(identity) / "job.json"
    state_path.write_text(json.dumps({"id": identity, "state": "queued"}))

    def fail_start(_identity: str) -> None:
        raise OSError("The worker could not start")

    monkeypatch.setattr(workspace, "_execute_job", fail_start)
    workspace._execute(identity)
    assert workspace.read(identity)["state"] == "failed"
    assert "could not start" in workspace.read(identity)["error"]
    workspace.close()


def test_second_instance_cannot_reclassify_an_active_job(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path / "runs")
    try:
        identity = workspace.create_upload()
        write_json(workspace.directory(identity) / "job.json", {"id": identity, "state": "running"})
        with pytest.raises(WorkspaceInUseError, match="already open"):
            Workspace(tmp_path / "runs")
        assert workspace.read(identity)["state"] == "running"
    finally:
        workspace.close()
    reopened = Workspace(tmp_path / "runs")
    assert reopened.read(identity)["state"] == "interrupted"
    reopened.close()


def test_surviving_worker_is_not_relabelled_after_owner_exits(tmp_path: Path) -> None:
    import psutil

    root = tmp_path / "runs"
    folder = root / "_workbench" / ("a" * 32)
    folder.mkdir(parents=True)
    state = {
        "state": "running",
        "worker_pid": os.getpid(),
        "worker_created_at": psutil.Process().create_time(),
    }
    write_json(folder / "job.json", state)
    with pytest.raises(WorkspaceInUseError, match="still running"):
        Workspace(root)
    assert json.loads((folder / "job.json").read_text())["state"] == "running"
    # A reused PID does not keep an abandoned job alive.
    state["worker_created_at"] -= 100
    write_json(folder / "job.json", state)
    reopened = Workspace(root)
    assert json.loads((folder / "job.json").read_text())["state"] == "interrupted"
    reopened.close()


def _upload_pair(
    client: TestClient,
    headers: dict[str, str],
    counts: bytes,
    design: bytes,
    filename: str = "counts.tsv",
) -> str:
    identity = client.post("/api/workbench/uploads", headers=headers).json()["id"]
    for kind, data, name in [("counts", counts, filename), ("design", design, "design.tsv")]:
        response = client.put(
            f"/api/workbench/uploads/{identity}/{kind}",
            headers={**headers, "X-Filename": name},
            content=data,
        )
        assert response.status_code == 200
    return str(identity)


@pytest.mark.parametrize(
    "payload",
    [
        b"\x1f\x8b\x08\x00",
        gzip.compress(b"a" * (1024 * 1024 + 1)),
        gzip.compress(b"a" * 140_000 + b"\n"),
    ],
)
def test_malformed_compressed_inputs_return_validation_errors(
    tmp_path: Path, payload: bytes
) -> None:
    _, design = inputs(tmp_path)
    with TestClient(
        create_app(run_root=tmp_path / "runs"), raise_server_exceptions=False
    ) as client:
        token = re.search(r'data-session-token="([^"]+)"', client.get("/workbench").text).group(1)
        headers = {"X-Bindsight-Token": token}
        identity = _upload_pair(client, headers, payload, design.read_bytes(), "counts.gz")
        response = client.post(f"/api/workbench/uploads/{identity}/inspect", headers=headers)
        assert response.status_code == 400
        assert response.json()["error"]


@pytest.mark.parametrize("threshold", [{}, [], None, True, "Infinity", "NaN", "-Infinity"])
def test_invalid_numeric_settings_never_enqueue_a_job(tmp_path: Path, threshold: object) -> None:
    counts, design = inputs(tmp_path)
    with TestClient(
        create_app(run_root=tmp_path / "runs"), raise_server_exceptions=False
    ) as client:
        token = re.search(r'data-session-token="([^"]+)"', client.get("/workbench").text).group(1)
        headers = {"X-Bindsight-Token": token}
        identity = _upload_pair(client, headers, counts.read_bytes(), design.read_bytes())
        response = client.post(
            f"/api/workbench/jobs/{identity}",
            headers=headers,
            json={"factor": "condition", "numerator": "1", "denominator": "0", "log2fc": threshold},
        )
        assert response.status_code == 400
        assert response.json()["error"]
        assert client.get("/api/workbench/jobs").json()["jobs"] == []


def test_chunked_settings_obey_the_actual_body_limit(tmp_path: Path) -> None:
    with TestClient(create_app(run_root=tmp_path / "runs")) as client:
        token = re.search(r'data-session-token="([^"]+)"', client.get("/workbench").text).group(1)
        response = client.post(
            "/api/workbench/jobs/" + "a" * 32,
            headers={"X-Bindsight-Token": token},
            content=iter([b" " * 10_000, b" " * 10_000]),
        )
        assert response.status_code == 400
        assert "too large" in response.json()["error"]


def test_server_shutdown_cancels_and_reaps_its_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, admitted_workstation: None
) -> None:
    counts, design = inputs(tmp_path)
    original_popen = subprocess.Popen
    started = threading.Event()
    children = []

    def harmless_worker(command, *args, **kwargs):
        if "bindsight.report.web.worker" in command:
            command = [sys.executable, "-c", "import time; time.sleep(60)"]
        child = original_popen(command, *args, **kwargs)
        children.append(child)
        started.set()
        return child

    monkeypatch.setattr(subprocess, "Popen", harmless_worker)
    try:
        with TestClient(create_app(run_root=tmp_path / "runs")) as client:
            token = re.search(r'data-session-token="([^"]+)"', client.get("/workbench").text).group(
                1
            )
            headers = {"X-Bindsight-Token": token}
            identity = _upload_pair(client, headers, counts.read_bytes(), design.read_bytes())
            response = client.post(
                f"/api/workbench/jobs/{identity}",
                headers=headers,
                json={"factor": "condition", "numerator": "1", "denominator": "0"},
            )
            assert response.status_code == 200
            assert started.wait(10)
        assert children[0].poll() is not None
        state = json.loads((tmp_path / "runs" / "_workbench" / identity / "job.json").read_text())
        assert state["state"] == "cancelled"
        reopened = Workspace(tmp_path / "runs")
        reopened.close()
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=5)

# SPDX-License-Identifier: AGPL-3.0-or-later
"""Engineering regressions; artificial inputs here are never public research evidence."""

import json
import re
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from bindsight.deg.pydeseq2_runner import PyDESeq2Runner
from bindsight.report.coverage import annotation_coverage
from bindsight.report.web.app import create_app
from bindsight.report.web.workspace import Workspace, inspect_inputs


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
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
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
    workspace.executor.shutdown()


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
    workspace.executor.shutdown()

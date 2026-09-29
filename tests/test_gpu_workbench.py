# SPDX-License-Identifier: AGPL-3.0-or-later
"""Artificial engineering fixtures; these tests do not constitute GPU validation."""

import ast
import json
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pandas as pd
import pytest
import yaml
from fastapi.testclient import TestClient

from bindsight.config import RunConfig
from bindsight.provenance import append as provenance
from bindsight.provenance.manifest import Manifest, new_manifest, sha256_file
from bindsight.report.web import gpu, gpu_setup, gpu_worker, worker
from bindsight.report.web.app import create_app
from bindsight.report.web.workspace import Workspace, write_json


@pytest.fixture
def workspace(tmp_path):
    current = Workspace(tmp_path / "runs")
    try:
        yield current
    finally:
        current.close()


@pytest.fixture
def discovery(workspace):
    identity = workspace.create_upload()
    source = workspace.root / "analysis-source"
    source.mkdir()
    for folder in ("deg", "targets", "epitopes", "structures"):
        (source / folder).mkdir()
    config = RunConfig.model_validate(
        {
            "name": "Artificial dispatch fixture",
            "out_dir": source,
            "inputs": {"counts": source / "counts.tsv", "design": source / "design.tsv"},
            "params": {
                "deg": {
                    "design_formula": "~ condition",
                    "contrast": ["condition", "drug", "vehicle"],
                }
            },
        }
    )
    (source / "config.yaml").write_text(
        yaml.safe_dump(config.model_dump(mode="json", by_alias=True))
    )
    pd.DataFrame(
        {"gene_id": ["ENSG00000000001"], "log2FoldChange": [2.0], "padj": [0.01]}
    ).to_parquet(source / "deg/results.parquet")
    pd.DataFrame({"gene_id": ["ENSG00000000001"], "uniprot_id": ["P12345"]}).to_parquet(
        source / "targets/candidates.parquet"
    )
    structure = source / "structures/artificial.pdb"
    structure.write_text("REMARK ARTIFICIAL UNIT TEST STRUCTURE; NOT SCIENTIFIC EVIDENCE\nEND\n")
    pd.DataFrame(
        {
            "uniprot_id": ["P12345"],
            "structure_path": ["structures/artificial.pdb"],
            "chain": ["A"],
            "residues": [[1, 2]],
            "design_ranges": [[[1, 3]]],
        }
    ).to_parquet(source / "epitopes/epitopes.parquet")
    new_manifest(name=config.name).write(source / "run_manifest.jsonld")
    provenance.record(
        source,
        name="deg",
        tool="artificial-test",
        outputs={"deg": source / "deg/results.parquet"},
        params={"contrast": ["condition", "drug", "vehicle"]},
    )
    provenance.record(
        source,
        name="discover",
        tool="artificial-test",
        outputs={"candidates": source / "targets/candidates.parquet"},
    )
    provenance.record(
        source,
        name="epitopes",
        tool="artificial-test",
        outputs={"epitopes": source / "epitopes/epitopes.parquet", "structure": structure},
    )
    write_json(
        workspace.directory(identity) / "job.json",
        {
            "id": identity,
            "kind": "discovery",
            "name": config.name,
            "state": "completed",
            "run_dir": str(source),
            "created_at": "2026-01-01",
            "genes": 1,
            "samples": 6,
            "contrast": ["condition", "drug", "vehicle"],
        },
    )
    return identity, source


def _request(workspace, discovery):
    identity, source = discovery
    selected = gpu.targets(workspace, identity)["targets"][0]
    return {
        "kind": "gpu_design",
        "source_run": str(source),
        "out_dir": str(workspace.root / "analysis-child"),
        "gpu_root": str(gpu.gpu_root(workspace)),
        "gpu_index": 0,
        "recipe_id": gpu.recipe()["id"],
        "source_manifest_sha256": sha256_file(source / "run_manifest.jsonld"),
        "source_config_sha256": sha256_file(source / "config.yaml"),
        "selected_targets": [selected],
        "options": gpu.options({"target_ids": [selected["id"]]}),
    }


def _device(free=15300, total=15360):
    return {
        "index": 0,
        "name": "Artificial T4 capability fixture",
        "memory_mib": total,
        "free_memory_mib": free,
        "compute_capability": [7, 5],
    }


def test_owner_low_memory_gpu_is_refused_before_install(workspace, monkeypatch):
    monkeypatch.setattr(gpu, "supported_platform", lambda: True)
    monkeypatch.setattr(gpu, "devices", lambda: [_device(total=2048, free=1900)])
    assert not gpu.readiness(workspace)["hardware_eligible"]
    with pytest.raises(ValueError, match="15,360 MiB"):
        gpu.start_setup(workspace, {"approved": True})
    assert workspace.list() == []


def test_ready_receipt_does_not_override_current_free_memory(workspace, monkeypatch):
    root = gpu.gpu_root(workspace)
    (root / "boltz/bin").mkdir(parents=True)
    (root / "boltz/bin/python").touch()
    (root / "se3-python").touch()
    write_json(root / "ready.json", {"recipe_id": gpu.recipe()["id"], "cuda_smoke_passed": True})
    monkeypatch.setattr(gpu, "supported_platform", lambda: True)
    monkeypatch.setattr(gpu, "devices", lambda: [_device(free=5000)])
    result = gpu.readiness(workspace)
    assert result["hardware_eligible"]
    assert not result["ready"]
    assert any("currently busy" in reason for reason in result["blockers"])


@pytest.mark.parametrize("body", [{}, {"approved": 1}, {"approved": True, "command": "anything"}])
def test_setup_requires_exact_explicit_approval(workspace, body):
    with pytest.raises(ValueError, match="Approve"):
        gpu.start_setup(workspace, body)


@pytest.mark.parametrize(
    "extra",
    [
        {"backend": "mock"},
        {"trajectories": True},
        {"trajectories": 11},
        {"seed": -1},
        {"binder_length_min": 151},
        {"binder_length_min": 101, "binder_length_max": 100},
    ],
)
def test_gpu_options_reject_unbounded_or_untrusted_requests(extra):
    with pytest.raises(ValueError, match=r"Unknown|integer|minimum"):
        gpu.options({"target_ids": ["a" * 20], **extra})


def test_targets_have_no_browser_controlled_paths(workspace, discovery):
    identity, _ = discovery
    target = gpu.targets(workspace, identity)["targets"][0]
    assert target["eligible"]
    assert target["design_ranges"] == [[1, 3]]
    assert re.fullmatch(r"[a-f0-9]{20}", target["id"])
    assert "structure_path" not in target


def test_original_structure_hash_required_and_recorded_by_discovery_worker(workspace, discovery):
    identity, source = discovery
    path = source / "run_manifest.jsonld"
    manifest = Manifest.read(path)
    for stage in manifest.stages:
        stage.outputs = [ref for ref in stage.outputs if not ref.path.endswith("artificial.pdb")]
    manifest.write(path)
    target = gpu.targets(workspace, identity)["targets"][0]
    assert not target["eligible"]
    assert "did not record" in " ".join(target["reasons"])
    worker.record_structure_inputs(source)
    assert gpu.targets(workspace, identity)["targets"][0]["eligible"]
    (source / "structures/artificial.pdb").write_text("ALTERED ARTIFICIAL STRUCTURE")
    target = gpu.targets(workspace, identity)["targets"][0]
    assert not target["eligible"]
    assert "no longer match" in " ".join(target["reasons"])


def test_absolute_pipeline_output_references_are_contained_and_portable(workspace, discovery):
    _, source = discovery
    path = source / "run_manifest.jsonld"
    # The discovery pipeline constructs OutputRefs from its absolute out_path;
    # unlike CLI record(), it does not always normalise them to relative paths.
    manifest = Manifest.read(path)
    for stage in manifest.stages:
        stage.outputs = [
            ref.model_copy(update={"path": str(source / ref.path)}) for ref in stage.outputs
        ]
    manifest.write(path)
    assert all(
        Path(ref.path).is_absolute() for s in Manifest.read(path).stages for ref in s.outputs
    )
    child = gpu_worker.prepare(_request(workspace, discovery))
    fitted = next(s for s in Manifest.read(child / "run_manifest.jsonld").stages if s.name == "deg")
    assert fitted.outputs[0].path == "deg/results.parquet"
    assert sha256_file(child / fitted.outputs[0].path) == fitted.outputs[0].sha256


def test_wsl_driver_fallback_is_used_without_path_entry(monkeypatch):
    monkeypatch.setattr(gpu.sys, "platform", "linux")
    monkeypatch.setattr(gpu.shutil, "which", lambda command: None)
    monkeypatch.setattr(
        gpu.Path,
        "is_file",
        lambda path: str(path).replace("\\", "/") == "/usr/lib/wsl/lib/nvidia-smi",
    )
    assert gpu.nvidia_smi().replace("\\", "/") == "/usr/lib/wsl/lib/nvidia-smi"


def test_start_queues_separate_child_without_changing_discovery(workspace, discovery, monkeypatch):
    identity, source = discovery
    digest = sha256_file(source / "run_manifest.jsonld")
    target = gpu.targets(workspace, identity)["targets"][0]
    monkeypatch.setattr(gpu, "readiness", lambda _: {"ready": True, "selected_gpu_index": 0})
    monkeypatch.setattr(workspace.executor, "submit", Mock(return_value=Mock()))
    job = gpu.start_design(workspace, identity, {"target_ids": [target["id"]]})
    assert job["kind"] == "gpu_design"
    assert Path(job["run_dir"]) != source
    saved = json.loads((workspace.directory(job["id"]) / "config.json").read_text())
    assert saved["source_run"] == str(source)
    assert saved["selected_targets"] == [target]
    assert sha256_file(source / "run_manifest.jsonld") == digest


def test_prepare_preserves_original_fit_attribution_and_selects_only_requested_target(
    workspace, discovery
):
    config = _request(workspace, discovery)
    original = sha256_file(discovery[1] / "run_manifest.jsonld")
    run = gpu_worker.prepare(config)
    fit = next(s for s in Manifest.read(run / "run_manifest.jsonld").stages if s.name == "deg")
    assert fit.status == "skipped_cache"
    assert fit.params["contrast"] == [
        "condition",
        "drug",
        "vehicle",
    ]
    assert "not recomputed" in fit.notes
    assert len(pd.read_parquet(run / "epitopes/epitopes.parquet")) == 1
    assert sha256_file(discovery[1] / "run_manifest.jsonld") == original
    assert gpu_worker.prepare(config) == run


@pytest.mark.parametrize(
    "relative", ["deg/results.parquet", "config.yaml", "epitopes/epitopes.parquet"]
)
def test_resume_refuses_modified_imported_inputs(workspace, discovery, relative):
    config = _request(workspace, discovery)
    run = gpu_worker.prepare(config)
    with (run / relative).open("ab") as stream:
        stream.write(b"CORRUPTED ARTIFICIAL TEST ARTIFACT")
    with pytest.raises(RuntimeError, match="imported discovery artifact changed"):
        gpu_worker.prepare(config)


def test_source_table_hash_is_verified_before_copy(workspace, discovery):
    config = _request(workspace, discovery)
    (discovery[1] / "deg/results.parquet").write_bytes(b"ARTIFICIAL CORRUPTION")
    with pytest.raises(RuntimeError, match="no longer matches"):
        gpu_worker.prepare(config)


@pytest.mark.parametrize("absolute_refs", [False, True])
@pytest.mark.parametrize(
    "changed_artifact", ["design/_targets/target.tar.gz", "validate/binder/complex.cif"]
)
def test_actual_command_sequence_and_verified_stage_resume(
    workspace, discovery, monkeypatch, absolute_refs, changed_artifact
):
    config = _request(workspace, discovery)
    job = workspace.storage / "worker-test"
    job.mkdir()
    monkeypatch.setattr(gpu_worker, "devices", lambda: [_device()])
    monkeypatch.setattr(gpu_setup, "smoke", lambda *a, **k: {"fixture": True})
    called = []

    class Command:
        def __init__(self, argv, env):
            assert argv[:3] == [gpu_worker.sys.executable, "-m", "bindsight.cli"]
            assert env["BINDSIGHT_LOCAL_NATIVE"] == "1"
            self.stage = argv[3]
            self.run = Path(argv[4])
            called.append(self.stage)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def wait(self, timeout):
            outputs = {}
            for name in gpu_worker.STAGES[self.stage]:
                path = self.run / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("ARTIFICIAL ENGINEERING TEST OUTPUT, NOT A GPU RESULT")
                outputs[name] = path
            extra = {
                "design": "design/_targets/target.tar.gz",
                "validate": "validate/binder/complex.cif",
            }.get(self.stage)
            if extra:
                path = self.run / extra
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("ARTIFICIAL LOOSE ENGINEERING TEST OUTPUT")
            provenance.record(
                self.run, name=self.stage, tool="artificial-command-fixture", outputs=outputs
            )
            if absolute_refs:
                manifest_path = self.run / "run_manifest.jsonld"
                manifest = Manifest.read(manifest_path)
                stage = next(s for s in manifest.stages if s.name == self.stage)
                stage.outputs = [
                    ref.model_copy(update={"path": str(self.run / ref.path)})
                    for ref in stage.outputs
                ]
                manifest.write(manifest_path)
            return 0

    monkeypatch.setattr(gpu_worker.subprocess, "Popen", Command)
    gpu_worker.run(config, job)
    assert called == ["design", "validate", "rank", "report"]
    called.clear()
    gpu_worker.run(config, job)
    assert called == []
    (Path(config["out_dir"]) / "validate/validated.parquet").write_text("CORRUPTED")
    gpu_worker.run(config, job)
    assert called == ["validate", "rank", "report"]
    called.clear()
    (Path(config["out_dir"]) / changed_artifact).write_text("ALTERED LOOSE OUTPUT")
    with pytest.raises(RuntimeError, match="loose outputs changed"):
        gpu_worker.run(config, job)
    assert called == []


def test_worker_rechecks_free_gpu_memory_before_any_scientific_work(
    workspace, discovery, monkeypatch
):
    config = _request(workspace, discovery)
    monkeypatch.setattr(gpu_worker, "devices", lambda: [_device(free=4000)])
    with pytest.raises(RuntimeError, match="busy"):
        gpu_worker.run(config, workspace.storage)
    assert not Path(config["out_dir"]).exists()


def test_routes_preserve_origin_token_guard_and_list_only_actual_artifacts(tmp_path, monkeypatch):
    root = tmp_path / "runs"
    with TestClient(create_app(run_root=root)) as client:
        page = client.get("/workbench").text
        token = re.search('data-session-token="([^"]+)"', page).group(1)
        assert client.post("/api/workbench/gpu/setup", json={"approved": True}).status_code == 403
        assert (
            client.post(
                "/api/workbench/gpu/setup",
                json={"approved": True},
                headers={"X-Bindsight-Token": token, "Origin": "https://evil.example"},
            ).status_code
            == 403
        )
        identity = "a" * 32
        folder = root / "_workbench" / identity
        folder.mkdir()
        run = root / "analysis-fixture"
        run.mkdir()
        (run / "gpu_setup_receipt.json").write_text('{"artificial":true}')
        write_json(
            folder / "job.json",
            {
                "id": identity,
                "kind": "gpu_setup",
                "state": "completed",
                "created_at": "2026-01-01",
                "run_dir": str(run),
            },
        )
        state = client.get(f"/api/workbench/jobs/{identity}").json()
        assert state["available_artifacts"] == ["gpu_setup_receipt"]
        assert "numerical_fit" not in state
        assert (
            client.get(f"/api/workbench/jobs/{identity}/artifact/gpu_setup_receipt").status_code
            == 200
        )
        assert client.get(f"/api/workbench/jobs/{identity}/artifact/report").status_code == 404


def test_cpu_recipe_check_never_writes_gpu_ready_receipt(tmp_path, monkeypatch):
    root = tmp_path / "environments"
    job = tmp_path / "job"
    job.mkdir()
    monkeypatch.setattr(gpu_setup.sys, "platform", "linux")
    commands = []

    def fake_command(argv, env):
        commands.append(argv)
        if "create" in argv:
            environment = Path(argv[argv.index("-p") + 1])
            (environment / "bin").mkdir(parents=True)
            (environment / "bin/python").touch()
        if "-m" in argv and "pip" in argv:
            assert env["PATH"].split(gpu_setup.os.pathsep)[0] == str(root / "boltz/bin")

    def fake_download(url, destination, expected, **kwargs):
        assert url == gpu.MICROMAMBA_URL  # No model downloads in this engineering mode.
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"ARTIFICIAL TEST EXECUTABLE")
        return "a" * 64

    monkeypatch.setattr(gpu_setup, "command", fake_command)
    monkeypatch.setattr(gpu_setup, "download", fake_download)
    monkeypatch.setattr(
        gpu_setup,
        "smoke",
        lambda root, env, require_cuda: (
            {"boltz": {"boltz": "2.0.3"}}
            if not require_cuda
            else pytest.fail("CPU test requested CUDA")
        ),
    )
    monkeypatch.setattr(
        gpu_setup.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout="artificial==1\n")
    )
    gpu_setup.install(
        {
            "recipe_id": gpu.recipe()["id"],
            "gpu_root": str(root),
            "gpu_index": 0,
            "out_dir": str(tmp_path / "output"),
        },
        job,
        check_recipe=True,
    )
    assert not (root / "ready.json").exists()
    result = json.loads((job / "recipe_check.json").read_text())
    assert result["cuda_tested"] is False
    assert result["models_downloaded"] is False
    assert any(
        "boltz==2.0.3" in command and "torch==2.2.2+cu118" in command for command in commands
    )


@pytest.mark.parametrize("require_cuda", [False, True])
def test_smoke_checks_actual_entrypoints_and_only_requested_cuda(
    tmp_path, monkeypatch, require_cuda
):
    """The generated probes are inspected here; real import execution is required by Linux CI."""
    commands = []

    def fake_probe(argv, **kwargs):
        assert argv[1] == "-c"
        assert kwargs["check"] is True
        assert kwargs["timeout"] == 120
        tree = ast.parse(argv[2])
        commands.append((argv, tree))
        return SimpleNamespace(stdout='{"artificial_probe":true}\n')

    monkeypatch.setattr(gpu_setup.subprocess, "run", fake_probe)
    gpu_setup.smoke(tmp_path, {}, require_cuda=require_cuda)
    assert len(commands) == 2
    se3, boltz = [command[0][2] for command in commands]
    assert "rfdiffusion.inference.model_runners" in se3
    assert "import protein_mpnn_utils" in se3
    assert repr(str(tmp_path / "tools/ProteinMPNN")) in se3
    assert "protein_mpnn_utils.__file__" in se3
    assert "import boltz.main" in boltz
    assert "'1.12.1+cu113'" in se3
    assert "'2.2.2+cu118'" in boltz
    assert "version('boltz') == '2.0.3'" in boltz
    assert ("device='cuda'" in se3) is require_cuda
    assert ("device='cuda'" in boltz) is require_cuda
    assert ("g.update_all" in se3) is require_cuda
    assert "g.update_all" not in boltz

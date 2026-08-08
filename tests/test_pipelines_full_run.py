# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the full-pipeline orchestrator."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pandas as pd
import pytest

from bindsight.config import RunConfig
from bindsight.pipelines import full_run as full_run_module
from bindsight.provenance import Manifest

REPO_ROOT = Path(__file__).parent.parent
EXAMPLES = REPO_ROOT / "examples" / "demo"

#: Every stage a full run accounts for, in execution order.
ALL_STAGES = ["deg", "discover", "design", "validate", "rank", "report", "export"]


def _fake_deg() -> pd.DataFrame:
    """The synthetic DESeq2 table the tests in this module run the pipeline on."""
    return pd.DataFrame(
        {
            "log2FoldChange": [3.5, 2.8, 0.1, 0.0, 0.05, -2.5, -2.8, 4.0, 3.0, 0.0],
            "lfcSE": [0.5] * 10,
            "stat": [7.0, 5.6, 0.25, 0.0, 0.1, -5.0, -5.6, 8.0, 6.0, 0.0],
            "pvalue": [1e-10, 1e-7, 0.8, 0.99, 0.95, 1e-8, 1e-9, 1e-11, 1e-9, 0.99],
            "padj": [1e-9, 1e-6, 0.95, 0.99, 0.95, 1e-7, 1e-8, 1e-10, 1e-8, 0.99],
            "baseMean": [800, 600, 500, 280, 240, 250, 260, 1000, 900, 250],
        },
        index=[
            "ENSG00000141736",
            "ENSG00000146648",
            "ENSG00000091831",
            "ENSG00000142208",
            "ENSG00000118260",
            "ENSG00000074706",
            "ENSG00000196712",
            "ENSG00000133703",
            "ENSG00000174775",
            "ENSG00000129965",
        ],
    )


@pytest.fixture
def demo_cfg(tmp_path: Path) -> RunConfig:
    from tests.conftest import write_mock_cohort

    cfg = RunConfig.from_yaml(EXAMPLES / "config.yaml")
    cfg.out_dir = tmp_path / "full_out"
    counts = tmp_path / "cache" / "counts.tsv.gz"
    design = tmp_path / "cache" / "design.tsv"
    write_mock_cohort(counts, design)
    cfg.inputs.counts = counts
    cfg.inputs.design = design
    cfg.inputs.download = None  # cohort already materialised above
    return cfg


def test_full_run_with_only_discover(
    offline_real_data, demo_cfg: RunConfig, tmp_path: Path
) -> None:
    """Full run with no GPU artifacts: discover OK, design/validate skipped, report+crate produced."""
    fake_deg = pd.DataFrame(
        {
            "log2FoldChange": [3.5, 2.8, 0.1, 0.0, 0.05, -2.5, -2.8, 4.0, 3.0, 0.0],
            "lfcSE": [0.5] * 10,
            "stat": [7.0, 5.6, 0.25, 0.0, 0.1, -5.0, -5.6, 8.0, 6.0, 0.0],
            "pvalue": [1e-10, 1e-7, 0.8, 0.99, 0.95, 1e-8, 1e-9, 1e-11, 1e-9, 0.99],
            "padj": [1e-9, 1e-6, 0.95, 0.99, 0.95, 1e-7, 1e-8, 1e-10, 1e-8, 0.99],
            "baseMean": [800, 600, 500, 280, 240, 250, 260, 1000, 900, 250],
        },
        index=[
            "ENSG00000141736",
            "ENSG00000146648",
            "ENSG00000091831",
            "ENSG00000142208",
            "ENSG00000118260",
            "ENSG00000074706",
            "ENSG00000196712",
            "ENSG00000133703",
            "ENSG00000174775",
            "ENSG00000129965",
        ],
    )

    out = tmp_path / "full_out"
    with patch(
        "bindsight.deg.pydeseq2_runner.PyDESeq2Runner._run_pydeseq2",
        return_value=fake_deg,
    ):
        result = full_run_module.run(demo_cfg, out_dir=out)

    assert result.discover_ok is True
    assert result.design_ok is False  # no Colab artifacts present
    assert result.validate_ok is False
    assert result.rank_ok is False  # no validation, so nothing to rank
    assert result.report_path is not None
    assert result.report_path.exists()
    assert result.crate_path is not None
    assert result.crate_path.exists()


def test_full_run_skips_export_when_requested(
    offline_real_data, demo_cfg: RunConfig, tmp_path: Path
) -> None:
    fake_deg = pd.DataFrame(
        {
            "log2FoldChange": [3.5, 2.8, 0.1, 0.0, 0.05, -2.5, -2.8, 4.0, 3.0, 0.0],
            "lfcSE": [0.5] * 10,
            "stat": [7.0, 5.6, 0.25, 0.0, 0.1, -5.0, -5.6, 8.0, 6.0, 0.0],
            "pvalue": [1e-10, 1e-7, 0.8, 0.99, 0.95, 1e-8, 1e-9, 1e-11, 1e-9, 0.99],
            "padj": [1e-9, 1e-6, 0.95, 0.99, 0.95, 1e-7, 1e-8, 1e-10, 1e-8, 0.99],
            "baseMean": [800, 600, 500, 280, 240, 250, 260, 1000, 900, 250],
        },
        index=[
            "ENSG00000141736",
            "ENSG00000146648",
            "ENSG00000091831",
            "ENSG00000142208",
            "ENSG00000118260",
            "ENSG00000074706",
            "ENSG00000196712",
            "ENSG00000133703",
            "ENSG00000174775",
            "ENSG00000129965",
        ],
    )

    out = tmp_path / "full_out2"
    with patch(
        "bindsight.deg.pydeseq2_runner.PyDESeq2Runner._run_pydeseq2",
        return_value=fake_deg,
    ):
        result = full_run_module.run(demo_cfg, out_dir=out, skip_report=True, skip_export=True)
    assert result.report_path is None
    assert result.crate_path is None


def test_full_run_picks_up_existing_validated_for_rank(
    offline_real_data, demo_cfg: RunConfig, tmp_path: Path
) -> None:
    """If user dropped validate/validated.parquet from Colab, rank stage runs."""
    fake_deg = pd.DataFrame(
        {
            "log2FoldChange": [3.5, 2.8, 0.1, 0.0, 0.05, -2.5, -2.8, 4.0, 3.0, 0.0],
            "lfcSE": [0.5] * 10,
            "stat": [7.0, 5.6, 0.25, 0.0, 0.1, -5.0, -5.6, 8.0, 6.0, 0.0],
            "pvalue": [1e-10, 1e-7, 0.8, 0.99, 0.95, 1e-8, 1e-9, 1e-11, 1e-9, 0.99],
            "padj": [1e-9, 1e-6, 0.95, 0.99, 0.95, 1e-7, 1e-8, 1e-10, 1e-8, 0.99],
            "baseMean": [800, 600, 500, 280, 240, 250, 260, 1000, 900, 250],
        },
        index=[
            "ENSG00000141736",
            "ENSG00000146648",
            "ENSG00000091831",
            "ENSG00000142208",
            "ENSG00000118260",
            "ENSG00000074706",
            "ENSG00000196712",
            "ENSG00000133703",
            "ENSG00000174775",
            "ENSG00000129965",
        ],
    )
    out = tmp_path / "full_out3"
    out.mkdir(parents=True, exist_ok=True)
    (out / "validate").mkdir()
    pd.DataFrame(
        [
            {
                "binder_id": "b1",
                "target_uniprot": "P04626",
                "iptm": 0.8,
                "affinity_pred_value": -7.5,
            },
        ]
    ).to_parquet(out / "validate" / "validated.parquet", index=False)

    with patch(
        "bindsight.deg.pydeseq2_runner.PyDESeq2Runner._run_pydeseq2",
        return_value=fake_deg,
    ):
        result = full_run_module.run(demo_cfg, out_dir=out)
    assert result.validate_ok is True
    assert result.rank_ok is True
    assert (out / "rank" / "ranking.parquet").exists()

    # The adopted file is pinned by digest, but this run did not make it, and
    # the manifest has to say so rather than imply a validation happened here.
    validate = next(s for s in result.manifest.stages if s.name == "validate")
    assert validate.status == "completed"
    assert "produced outside this run" in (validate.notes or "")
    assert [o.role for o in validate.outputs] == ["validated"]


# ---------------------------------------------------------------------------
# Manifest completeness (I7): all seven stages, in order, skips included
# ---------------------------------------------------------------------------
def test_full_run_records_all_seven_stages(
    offline_real_data, demo_cfg: RunConfig, tmp_path: Path
) -> None:
    """Only deg and discover used to appear; the five stages full_run drives were invisible."""
    out = tmp_path / "full_out_stages"
    with patch(
        "bindsight.deg.pydeseq2_runner.PyDESeq2Runner._run_pydeseq2",
        return_value=_fake_deg(),
    ):
        result = full_run_module.run(demo_cfg, out_dir=out)

    assert [s.name for s in result.manifest.stages] == ALL_STAGES
    on_disk = Manifest.read(out / "run_manifest.jsonld")
    assert [s.name for s in on_disk.stages] == ALL_STAGES

    by_name = {s.name: s for s in on_disk.stages}
    # The demo backend is `colab`, so the GPU half never ran here. A stage that
    # was not attempted is recorded as skipped WITH its reason — not omitted,
    # and not "skipped_cache", which would claim a cache hit that never happened.
    for name in ("design", "validate", "rank"):
        assert by_name[name].status == "skipped", name
        assert (by_name[name].notes or "").strip(), f"{name} skipped without saying why"
    assert "not headless" in (by_name["design"].notes or "")

    for name in ("report", "export"):
        assert by_name[name].status == "completed", name
        assert by_name[name].outputs, f"{name} completed without digesting an output"
    assert [o.role for o in by_name["export"].outputs] == ["ro_crate"]
    # Every recorded artifact carries a real content digest.
    for stage in on_disk.stages:
        for ref in (*stage.inputs, *stage.outputs):
            assert len(ref.sha256) == 64


def test_full_run_records_skipped_report_and_export(
    offline_real_data, demo_cfg: RunConfig, tmp_path: Path
) -> None:
    """Opting a stage out must record the opt-out, not erase the stage."""
    out = tmp_path / "full_out_skips"
    with patch(
        "bindsight.deg.pydeseq2_runner.PyDESeq2Runner._run_pydeseq2",
        return_value=_fake_deg(),
    ):
        result = full_run_module.run(demo_cfg, out_dir=out, skip_report=True, skip_export=True)

    assert result.report_path is None
    assert result.crate_path is None
    by_name = {s.name: s for s in Manifest.read(out / "run_manifest.jsonld").stages}
    assert set(by_name) == set(ALL_STAGES)
    for name in ("report", "export"):
        assert by_name[name].status == "skipped"
        assert "by request" in (by_name[name].notes or "")
        assert by_name[name].outputs == []


def test_full_run_manifest_is_prov_typed_on_disk(
    offline_real_data, demo_cfg: RunConfig, tmp_path: Path
) -> None:
    """The written file is PROV-O, not merely named .jsonld."""
    out = tmp_path / "full_out_prov"
    with patch(
        "bindsight.deg.pydeseq2_runner.PyDESeq2Runner._run_pydeseq2",
        return_value=_fake_deg(),
    ):
        result = full_run_module.run(demo_cfg, out_dir=out)

    body = json.loads((out / "run_manifest.jsonld").read_text())
    assert body["@type"] == "prov:Bundle"
    assert body["@id"] == f"urn:uuid:{result.manifest.run_id}"
    assert body["@context"]["inputs"] == "prov:used"
    assert body["@context"]["outputs"] == "prov:generated"
    assert "@vocab" not in body["@context"]
    assert {s["@type"] for s in body["stages"]} == {"prov:Activity"}

    # The report reads artifacts discover produced: the same file must be one
    # content-addressed entity on both sides of the hand-off.
    produced = {e["@id"] for s in body["stages"] if s["name"] == "discover" for e in s["outputs"]}
    consumed = {e["@id"] for s in body["stages"] if s["name"] == "report" for e in s["inputs"]}
    assert produced
    assert produced & consumed
    assert all(i.startswith("urn:sha256:") for i in produced | consumed)


# ---------------------------------------------------------------------------
# Container digest (I7): record a verified digest or record none
# ---------------------------------------------------------------------------
@pytest.fixture
def containerised(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force the local_docker runner out of native mode, into its container mode."""
    monkeypatch.setenv("BINDSIGHT_LOCAL_NATIVE", "0")


def _fake_docker(stdout: str) -> Callable[..., subprocess.CompletedProcess[str]]:
    """A `docker image inspect` that prints ``stdout`` and exits 0."""

    def _run(cmd: Any, **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr="")

    return _run


def test_container_ref_records_the_verified_digest(
    containerised, monkeypatch: pytest.MonkeyPatch
) -> None:
    digest = "sha256:" + "a" * 64
    monkeypatch.setattr(
        full_run_module.subprocess,
        "run",
        _fake_docker(f"ghcr.io/mikhaeelatefrizk/bindsight@{digest}\n"),
    )
    ref = full_run_module._container_ref("local_docker")
    assert ref is not None
    assert ref.image == "ghcr.io/mikhaeelatefrizk/bindsight"
    assert ref.digest == digest
    assert ref.runtime == "docker"


@pytest.mark.parametrize(
    "failure",
    [
        FileNotFoundError("docker not on PATH"),
        subprocess.TimeoutExpired(cmd="docker", timeout=20),
        subprocess.CalledProcessError(1, "docker"),
    ],
    ids=["no-docker", "timeout", "nonzero-exit"],
)
def test_container_ref_records_nothing_when_it_cannot_verify(
    containerised, monkeypatch: pytest.MonkeyPatch, failure: Exception
) -> None:
    def _boom(*_args: Any, **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise failure

    monkeypatch.setattr(full_run_module.subprocess, "run", _boom)
    assert full_run_module._container_ref("local_docker") is None


def test_container_ref_refuses_an_image_with_no_repository_digest(
    containerised, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A locally-built image carries no digest; a tag is not an identity."""
    monkeypatch.setattr(full_run_module.subprocess, "run", _fake_docker("ghcr.io/x/y:dev\n"))
    assert full_run_module._container_ref("local_docker") is None


@pytest.mark.parametrize("backend", ["modal", "kaggle", "colab", "mock"])
def test_container_ref_is_none_for_backends_it_cannot_inspect(
    monkeypatch: pytest.MonkeyPatch, backend: str
) -> None:
    def _unreachable(*_args: Any, **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise AssertionError("docker must not be invoked for " + backend)

    monkeypatch.setattr(full_run_module.subprocess, "run", _unreachable)
    assert full_run_module._container_ref(backend) is None

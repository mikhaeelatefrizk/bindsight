# SPDX-License-Identifier: AGPL-3.0-or-later
"""A cached table must retain the identity of the computation that produced it."""

import json
from pathlib import Path

import pytest

from bindsight.config import RunConfig
from bindsight.deg import cache
from bindsight.pipelines.discover import _stage_deg


@pytest.fixture
def fake_stage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    counts, design = tmp_path / "counts.tsv", tmp_path / "design.tsv"
    counts.write_text("artificial fixture counts\n")
    design.write_text("artificial fixture design\n")
    cfg = RunConfig.model_validate(
        {
            "name": "cache-integrity",
            "out_dir": tmp_path,
            "inputs": {"counts": counts, "design": design},
            "params": {
                "deg": {
                    "design_formula": "~ condition",
                    "contrast": ["condition", "case", "control"],
                }
            },
        }
    )
    output = tmp_path / "deg/results.parquet"
    calls = []

    def fake_fit(self, counts, design, out_path):
        calls.append(1)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"original artificial artifact")
        return {"n_samples": 6, "n_genes_tested": 10, "n_significant": 2}

    monkeypatch.setattr("bindsight.pipelines.discover.PyDESeq2Runner.run", fake_fit)
    return cfg, output, calls


def test_identical_execution_reuses_verified_output_and_records_its_identity(fake_stage) -> None:
    cfg, output, calls = fake_stage
    fresh = _stage_deg(cfg, output)
    cached = _stage_deg(cfg, output)
    assert fresh.status == cached.status == "completed"
    assert fresh.cache_status == "miss"
    assert cached.cache_status == "hit"
    assert len(calls) == 1
    assert fresh.params["execution_identity"] == cached.params["execution_identity"]
    assert "deg/inference.py" in fresh.params["execution_identity"]["source_sha256"]
    assert "scipy" in fresh.params["execution_identity"]["libraries"]
    assert "torch" not in fresh.params["execution_identity"]["libraries"]


@pytest.mark.parametrize("damage", ["same_size_edit", "truncated", "plain_key", "bad_metadata"])
def test_unverified_or_modified_tables_are_recomputed(fake_stage, damage: str) -> None:
    cfg, output, calls = fake_stage
    first = _stage_deg(cfg, output)
    metadata_path = output.with_suffix(".cache_key")
    if damage == "same_size_edit":
        output.write_bytes(b"X" * output.stat().st_size)
    elif damage == "truncated":
        output.write_bytes(b"truncated")
    elif damage == "plain_key":
        metadata_path.write_text(first.cache_key)
    else:
        metadata_path.write_text("[]")
    repaired = _stage_deg(cfg, output)
    assert repaired.status == "completed"
    assert repaired.cache_status == "miss"
    assert len(calls) == 2
    assert output.read_bytes() == b"original artificial artifact"
    assert json.loads(metadata_path.read_text())["schema_version"] == 2


def test_numerical_dependency_change_causes_real_cache_miss(
    fake_stage, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg, output, calls = fake_stage
    installed = {"scipy": "1.0"}
    monkeypatch.setattr(
        "bindsight.validate.protocol.installed_version", lambda name: installed.get(name, "0.5.4")
    )
    first = _stage_deg(cfg, output)
    installed["scipy"] = "2.0"
    second = _stage_deg(cfg, output)
    assert first.cache_key != second.cache_key
    assert second.cache_status == "miss"
    assert second.params["execution_identity"]["libraries"]["scipy"] == "2.0"
    assert len(calls) == 2


def test_repaired_adapter_at_same_package_version_causes_real_cache_miss(
    fake_stage, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg, output, calls = fake_stage
    package = tmp_path / "copied-package"
    for name in cache._DEG_SOURCES:
        path = package / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((cache._PACKAGE_ROOT / name).read_bytes())
    monkeypatch.setattr(cache, "_PACKAGE_ROOT", package)
    first = _stage_deg(cfg, output)
    adapter = package / "deg/inference.py"
    adapter.write_bytes(adapter.read_bytes() + b"\n# independently reviewed repair\n")
    second = _stage_deg(cfg, output)
    assert first.cache_key != second.cache_key
    assert first.tool.version == second.tool.version
    assert second.cache_status == "miss"
    assert len(calls) == 2


def test_code_identity_does_not_depend_on_installation_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = cache.execution_identity()
    package = tmp_path / "elsewhere"
    for name in cache._DEG_SOURCES:
        path = package / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((cache._PACKAGE_ROOT / name).read_bytes())
    monkeypatch.setattr(cache, "_PACKAGE_ROOT", package)
    assert cache.execution_identity() == original

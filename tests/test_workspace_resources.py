# SPDX-License-Identifier: AGPL-3.0-or-later
"""Scheduling/dependency checks; these fixtures are not biological validation."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from bindsight.report.web import resources as r


def machine(
    memory: int | None = 8 * r.GIB, disk: int | None = 20 * r.GIB, cpus: int = 8
) -> dict[str, Any]:
    return {"memory_available_bytes": memory, "disk_free_bytes": disk, "cpus": cpus}


def test_worker_budget_responds_to_available_memory_and_cpu_count() -> None:
    small = r.assess_resources(20_000, 16, 300_000, machine(memory=2 * r.GIB))
    large = r.assess_resources(20_000, 16, 300_000, machine(memory=16 * r.GIB))
    single_cpu = r.assess_resources(20_000, 16, 300_000, machine(cpus=1))
    assert small["admitted"]
    assert small["n_cpus"] == single_cpu["n_cpus"] == 1
    assert large["n_cpus"] == 4
    assert large["estimated_memory_bytes"] > small["estimated_memory_bytes"]
    assert large["estimated_memory_bytes"] + large["memory_reserve_bytes"] <= 16 * r.GIB


def test_tiny_compressed_upload_does_not_hide_large_dense_matrix() -> None:
    small = r.assess_resources(20_000, 6, 1_000, machine())
    large = r.assess_resources(150_000, 2_000, 1_000, machine())
    assert small["admitted"]
    assert not large["admitted"]
    assert large["one_worker_memory_bytes"] > 8 * r.GIB
    assert large["estimated_disk_bytes"] > small["estimated_disk_bytes"]
    assert any("RAM" in reason for reason in large["reasons"])


def test_disk_admission_boundary_is_inclusive_and_independent_of_ram() -> None:
    budget = r.assess_resources(20_000, 6, 300_000, machine())["estimated_disk_bytes"]
    assert r.assess_resources(20_000, 6, 300_000, machine(disk=budget))["admitted"]
    refused = r.assess_resources(20_000, 6, 300_000, machine(disk=budget - 1))
    assert not refused["admitted"]
    assert any("Free space" in reason for reason in refused["reasons"])


def test_unknown_capacity_is_explicit_and_uses_one_worker() -> None:
    report = r.assess_resources(20_000, 6, 300_000, machine(memory=None, disk=None))
    assert report["admitted"]
    assert report["n_cpus"] == 1
    assert report["memory_reserve_bytes"] is None
    assert len(report["warnings"]) == 2
    assert report["measurements"]["memory_available_bytes"] is None
    assert not r.assess_resources(20_000, 6, 300_000, machine(memory=0))["admitted"]


@pytest.mark.parametrize(
    ("genes", "samples", "input_bytes"),
    [(0, 6, 1), (20, -1, 1), (20, 6, -1), (True, 6, 1), (20, 6.5, 1)],
)
def test_invalid_dimensions_are_rejected(genes: Any, samples: Any, input_bytes: Any) -> None:
    with pytest.raises(ValueError, match="must be an integer"):
        r.assess_resources(genes, samples, input_bytes, machine())


def test_real_subprocess_distinguishes_import_failure_from_installation_presence() -> None:
    report = r._probe_dependencies(
        (("json", True), ("_bindsight_missing_dependency_for_test", True)), 10
    )
    assert not report["usable"]
    assert report["status"] == "import_failed"
    assert report["checks"][0]["usable"]
    assert "ModuleNotFoundError" in report["checks"][1]["error"]


def test_optional_import_failure_keeps_core_usable_but_remains_visible() -> None:
    report = r._probe_dependencies(
        (("json", True), ("_bindsight_optional_missing_for_test", False)), 10
    )
    assert report["usable"]
    assert report["status"] == "ok"
    assert not report["checks"][1]["usable"]
    assert "ModuleNotFoundError" in report["checks"][1]["error"]


def test_probe_timeout_preserves_completed_checks_and_marks_remaining_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    partial = r._PROBE_MARKER + json.dumps({"module": "json", "usable": True, "error": ""}) + "\n"

    def timeout(*args: Any, **kwargs: Any) -> None:
        assert kwargs["timeout"] == 0.25
        assert kwargs["env"]["OPENBLAS_NUM_THREADS"] == "1"
        raise subprocess.TimeoutExpired("isolated import check", 0.25, output=partial.encode())

    monkeypatch.setattr(r.subprocess, "run", timeout)
    report = r._probe_dependencies((("json", True), ("slow_import", True)), 0.25)
    assert report["status"] == "timeout"
    assert not report["usable"]
    assert report["checks"][0]["usable"]
    assert not report["checks"][1]["usable"]
    assert "Not checked" in report["checks"][1]["error"]


def test_import_error_reason_is_retained_without_host_paths_or_credentials() -> None:
    message = r.sanitize_error(
        "ImportError: DLL load failed: Windows Application Control blocked 'C:\\Users\\PrivateName\\library.dll'; token=secret-value https://host.test/?key=hidden\x00"
    )
    assert "DLL load failed" in message
    assert "Windows Application Control" in message
    assert "PrivateName" not in message
    assert "secret-value" not in message
    assert "host.test" not in message
    assert "\x00" not in message


def test_dependency_cache_refresh_expiry_and_mutation_isolation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []
    clock = [10.0]

    def probe(*args: Any) -> dict[str, Any]:
        calls.append(1)
        return {"usable": True, "checks": [{"module": "json", "usable": True}]}

    monkeypatch.setattr(r, "_dependency_cache", None)
    monkeypatch.setattr(r, "_probe_dependencies", probe)
    monkeypatch.setattr(r.time, "monotonic", lambda: clock[0])
    first = r.dependency_status()
    first["checks"][0]["usable"] = False
    assert r.dependency_status()["checks"][0]["usable"]
    assert len(calls) == 1
    r.dependency_status(refresh=True)
    assert len(calls) == 2
    clock[0] += r.PROBE_CACHE_SECONDS + 1
    r.dependency_status()
    assert len(calls) == 3


def test_missing_or_malformed_probe_output_cannot_claim_usable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        r.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess([], 0, r._PROBE_MARKER + "{}", ""),
    )
    report = r._probe_dependencies((("json", True),), 1)
    assert report["status"] == "invalid_output"
    assert not report["usable"]


def test_resource_refusal_avoids_heavy_imports(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(r, "measured_resources", lambda root: machine(memory=128 * r.MIB))

    def forbidden(**kwargs: Any) -> None:
        pytest.fail("A refused resource budget must not start heavy imports")

    monkeypatch.setattr(r, "dependency_status", forbidden)
    report = r.assess_execution(tmp_path, genes=20_000, samples=6, input_bytes=100)
    assert not report["admitted"]
    assert report["dependencies"]["usable"] is None


def test_unusable_required_library_blocks_admission(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(r, "measured_resources", lambda root: machine())
    monkeypatch.setattr(
        r,
        "dependency_status",
        lambda **kwargs: {"usable": False, "error": "DLL load failed", "checks": []},
    )
    report = r.assess_execution(tmp_path, genes=20_000, samples=6, input_bytes=100)
    assert not report["admitted"]
    assert any("DLL load failed" in reason for reason in report["reasons"])

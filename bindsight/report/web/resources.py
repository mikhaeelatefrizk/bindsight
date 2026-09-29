# SPDX-License-Identifier: AGPL-3.0-or-later
"""Conservative local CPU admission and isolated dependency usability checks.

These estimates are scheduling policies, not measured peak-memory predictions.
They never change the scientific model, thresholds, or numerical objective.
"""

from __future__ import annotations

import copy
import importlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

MIB = 2**20
GIB = 2**30
POLICY = "cpu-discovery-admission-v1"
PROBE_CACHE_SECONDS = 30.0
PROBES = (
    ("numpy", True),
    ("scipy.linalg", True),
    ("scipy.stats", True),
    ("pandas", True),
    ("pyarrow.parquet", True),
    ("pydeseq2.dds", True),
    ("pydeseq2.ds", True),
    ("formulaic", True),
    ("bindsight.deg.inference", True),
    ("bindsight.pipelines.discover", True),
    ("bindsight.report.html", True),
    ("matplotlib.backends.backend_agg", True),
    ("Bio.PDB.MMCIF2Dict", False),
    ("openpyxl", False),
)
_PROBE_MARKER = "BINDSIGHT_IMPORT_CHECK "
_PROBE_SCRIPT = r"""
import contextlib, importlib, json, os, sys
probes = json.loads(sys.argv[1])
with open(os.devnull, 'w') as quiet:
    for name, required in probes:
        result = {'module': name, 'required': required, 'usable': False, 'error': ''}
        try:
            with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
                loaded = importlib.import_module(name)
                if name == 'bindsight.deg.inference':
                    loaded.RegularizedInference(n_cpus=1)
            result['usable'] = True
        except Exception as error:
            result['error'] = type(error).__name__ + ': ' + str(error)[:1200]
        print('BINDSIGHT_IMPORT_CHECK ' + json.dumps(result), flush=True)
"""
_dependency_cache: tuple[float, dict[str, Any]] | None = None
_dependency_lock = threading.Lock()


def sanitize_error(value: object) -> str:
    """Retain the failure reason without exposing paths, credentials or control codes."""
    message = str(value)
    for location in (str(Path.home()), sys.prefix, str(Path.cwd())):
        message = message.replace(location, "<path>")
        message = message.replace(location.replace("\\", "/"), "<path>")
    message = re.sub(r"([\"'])(?:[A-Za-z]:[\\/]|/)[^\r\n]*?\1", "'<path>'", message)
    message = re.sub(r"https?://[^\s\"']+", "<url>", message)
    message = re.sub(
        r"\b[A-Za-z]:[\\/][^\s\"']+|(?<![\w:])/(?:[^\s/]+/)+[^\s\"']*", "<path>", message
    )
    message = re.sub(
        r"(?i)\b(token|password|secret|api[_-]?key)\s*[=:]\s*[^\s,;]+",
        r"\1=<redacted>",
        message,
    )
    return " ".join(re.sub(r"[\x00-\x1f\x7f]", " ", message).split())[:600]


def _text(value: str | bytes | None) -> str:
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value or ""


def _probe_dependencies(
    probes: tuple[tuple[str, bool], ...], timeout_seconds: float
) -> dict[str, Any]:
    stdout = ""
    failure = ""
    status = "ok"
    try:
        completed = subprocess.run(
            [sys.executable, "-I", "-B", "-X", "utf8", "-c", _PROBE_SCRIPT, json.dumps(probes)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
            creationflags=(
                int(getattr(subprocess, "CREATE_NO_WINDOW", 0)) if sys.platform == "win32" else 0
            ),
            env=dict(
                os.environ, OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1"
            ),
        )
        stdout = completed.stdout
        if completed.returncode:
            status = "process_failed"
            failure = f"Dependency check exited with code {completed.returncode}: {sanitize_error(completed.stderr[-1500:])}"
    except subprocess.TimeoutExpired as error:
        stdout = _text(error.stdout)
        status = "timeout"
        failure = f"Dependency imports did not finish within {timeout_seconds:g} seconds."
    except OSError as error:
        status = "unavailable"
        failure = f"Dependency check could not start: {sanitize_error(error)}"

    reported: dict[str, dict[str, Any]] = {}
    allowed = dict(probes)
    for line in stdout.splitlines():
        if not line.startswith(_PROBE_MARKER):
            continue
        try:
            record = json.loads(line.removeprefix(_PROBE_MARKER))
            name = record["module"]
            if name not in allowed or not isinstance(record["usable"], bool) or name in reported:
                raise ValueError("Invalid import-check record")
            reported[name] = {
                "module": name,
                "required": allowed[name],
                "usable": record["usable"],
                "error": sanitize_error(record.get("error", "")),
            }
        except (ValueError, KeyError, TypeError):
            status = "invalid_output"
            failure = "The dependency subprocess returned an invalid check record."
    if len(reported) != len(probes) and status == "ok":
        status = "invalid_output"
        failure = "The dependency subprocess did not return every required check."
    checks = [
        reported.get(
            name,
            {
                "module": name,
                "required": required,
                "usable": False,
                "error": "Not checked; " + failure,
            },
        )
        for name, required in probes
    ]
    required_failures = [check for check in checks if check["required"] and not check["usable"]]
    usable = status == "ok" and not required_failures
    if status == "ok" and required_failures:
        status = "import_failed"
        failure = "; ".join(f"{item['module']}: {item['error']}" for item in required_failures)[
            :1200
        ]
    return {
        "usable": usable,
        "status": status,
        "checks": checks,
        "error": failure,
        "checked_at": datetime.now(UTC).isoformat(),
        "cache_seconds": PROBE_CACHE_SECONDS,
        "limitation": "Actual imports and the pinned inference adapter are checked in a subprocess. This does not execute a model, test reference services, or verify optional GPU tools. Optional parser failures remain visible and can limit annotations.",
    }


def dependency_status(*, refresh: bool = False, timeout_seconds: float = 20) -> dict[str, Any]:
    """Check real imports with a bounded timeout, caching results for at most 30 seconds."""
    if not 0 < timeout_seconds <= 60:
        raise ValueError(
            "Dependency-check timeout must be greater than zero and at most 60 seconds"
        )
    global _dependency_cache
    with _dependency_lock:
        if (
            not refresh
            and _dependency_cache
            and time.monotonic() - _dependency_cache[0] < PROBE_CACHE_SECONDS
        ):
            return copy.deepcopy(_dependency_cache[1])
        result = _probe_dependencies(PROBES, timeout_seconds)
        _dependency_cache = (time.monotonic(), result)
        return copy.deepcopy(result)


def measured_resources(root: Path) -> dict[str, Any]:
    """Read currently available memory and free space at the actual output filesystem."""
    errors = []
    memory = None
    disk = None
    try:
        memory = int(importlib.import_module("psutil").virtual_memory().available)
    except (ImportError, OSError, AttributeError, ValueError) as error:
        errors.append(f"Available memory could not be measured: {sanitize_error(error)}")
    try:
        disk = shutil.disk_usage(root).free
    except OSError as error:
        errors.append(f"Free output storage could not be measured: {sanitize_error(error)}")
    return {
        "cpus": os.cpu_count() or 1,
        "memory_available_bytes": memory,
        "disk_free_bytes": disk,
        "measurement_errors": errors,
    }


def assess_resources(
    genes: int, samples: int, input_bytes: int, measurements: dict[str, Any]
) -> dict[str, Any]:
    """Choose at most four workers and refuse datasets exceeding measured headroom."""
    for name, value, minimum in (
        ("genes", genes, 1),
        ("samples", samples, 1),
        ("input_bytes", input_bytes, 0),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
            raise ValueError(f"{name} must be an integer at least {minimum}")
    # Budget dense 64-bit arrays, parsing/metadata, and a square design workspace.
    # Full validated dimensions matter even when a compressed upload is tiny.
    matrix = genes * samples * 8
    base_memory = 512 * MIB + matrix * 16 + genes * 1024 + samples * samples * 32
    extra_worker = 256 * MIB + matrix * 2 + genes * 256
    disk_estimate = 512 * MIB + 2 * input_bytes + matrix * 4 + genes * 1024
    warnings = list(measurements.get("measurement_errors", []))
    reasons = []
    memory = measurements.get("memory_available_bytes")
    disk = measurements.get("disk_free_bytes")
    cpus = measurements.get("cpus")
    cpus = cpus if isinstance(cpus, int) and not isinstance(cpus, bool) and cpus > 0 else 1
    memory = (
        memory if isinstance(memory, int) and not isinstance(memory, bool) and memory >= 0 else None
    )
    disk = disk if isinstance(disk, int) and not isinstance(disk, bool) and disk >= 0 else None
    reserve = min(GIB, max(256 * MIB, memory // 5)) if memory is not None else None
    workers = 1
    if memory is None:
        warnings.append(
            "Available RAM is unknown; using one worker without a memory-capacity assurance."
        )
    else:
        if memory < base_memory + int(reserve or 0):
            reasons.append(
                "Available RAM is below this dataset's conservative one-worker budget plus operating-system reserve. Close other applications or use a machine with more available RAM."
            )
        elif memory >= 4 * GIB:
            for candidate in range(2, min(4, max(1, cpus - 1)) + 1):
                if base_memory + (candidate - 1) * extra_worker + int(reserve or 0) <= memory:
                    workers = candidate
    if disk is None:
        warnings.append("Free output storage is unknown; storage capacity could not be checked.")
    elif disk < disk_estimate:
        reasons.append(
            "Free space on the output filesystem is below the estimated working/output budget. Free storage before starting this analysis."
        )
    return {
        "policy": POLICY,
        "admitted": not reasons,
        "n_cpus": workers,
        "genes": genes,
        "samples": samples,
        "input_bytes": input_bytes,
        "estimated_memory_bytes": base_memory + (workers - 1) * extra_worker,
        "one_worker_memory_bytes": base_memory,
        "memory_reserve_bytes": reserve,
        "estimated_disk_bytes": disk_estimate,
        "measurements": measurements,
        "reasons": reasons,
        "warnings": warnings,
        "limits": "Conservative admission heuristic, not a benchmarked peak or guarantee of completion. Available resources change over time. Design complexity, library/OS overhead, container limits and downloaded references can exceed this budget. Compressed file size does not replace full gene/sample dimensions. Worker count changes scheduling only; the model and thresholds are unchanged.",
    }


def assess_execution(
    root: Path, *, genes: int, samples: int, input_bytes: int, refresh_dependencies: bool = False
) -> dict[str, Any]:
    """Combine measured admission and actual dependency checks before queuing a CPU fit."""
    result = assess_resources(genes, samples, input_bytes, measured_resources(root))
    if not result["admitted"]:
        result["dependencies"] = {
            "usable": None,
            "status": "not_checked_resources",
            "checks": [],
            "error": "Imports were not started because the resource budget was refused.",
        }
        return result
    dependencies = dependency_status(refresh=refresh_dependencies)
    result["dependencies"] = dependencies
    if not dependencies["usable"]:
        result["admitted"] = False
        result["reasons"].append("Required CPU libraries are unusable: " + dependencies["error"])
    for check in dependencies["checks"]:
        if not check["required"] and not check["usable"]:
            result["warnings"].append(
                f"Optional annotation dependency {check['module']}: {check['error']}"
            )
    return result

# SPDX-License-Identifier: AGPL-3.0-or-later
"""Bounded local GPU workflow; browser requests never supply executable paths."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, Any

from bindsight.provenance.manifest import Manifest, sha256_file
from bindsight.runners import tools

if TYPE_CHECKING:
    from bindsight.report.web.workspace import Workspace

MIN_MEMORY_MIB = 15360  # A nominal 16 GB T4 reports 15,360 MiB.
MIN_FREE_MEMORY_MIB = 14900  # Exceeds the recorded 14,859 MiB workload peak.
SETUP_DISK_BYTES = 60 * 2**30
DEFAULTS = {"trajectories": 1, "seed": 42, "binder_length_min": 60, "binder_length_max": 100}
MICROMAMBA_URL = (
    "https://github.com/mamba-org/micromamba-releases/releases/download/2.3.2-0/micromamba-linux-64"
)
MICROMAMBA_SHA256 = "ffc3cb8d52d4d6b354bdbb979c407719c485392b74e462cbd50811aa88e58f85"


def recipe() -> dict[str, Any]:
    """Name the fixed installation recipe without claiming all transitives are pinned."""
    body: dict[str, Any] = {
        "version": 1,
        "designer": "rfdiff_mpnn",
        "validator": "boltz2",
        "rfdiffusion_commit": tools.RFDIFF_COMMIT,
        "proteinmpnn_commit": tools.PROTEINMPNN_COMMIT,
        "boltz": tools.BOLTZ_PIP,
        "se3": {"python": "3.9", "torch": "1.12.1+cu113", "dgl": "1.0.2+cu113", "numpy": "1.23.5"},
        "validation": {"python": "3.11", "torch": "2.2.2+cu118", "numpy": "1.26.4"},
        "micromamba_sha256": MICROMAMBA_SHA256,
        "checkpoint_expected_sha256": tools.RFDIFF_WEIGHT_SHA256,
        "minimum_memory_mib": MIN_MEMORY_MIB,
        "minimum_free_memory_mib": MIN_FREE_MEMORY_MIB,
        "minimum_setup_disk_bytes": SETUP_DISK_BYTES,
        "installer_sha256": hashlib.sha256(
            Path(__file__).with_name("gpu_setup.py").read_bytes()
        ).hexdigest(),
    }
    body["id"] = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
    return body


def gpu_root(workspace: Workspace) -> Path:
    """Keep the optional environments inside the owned workspace."""
    root = workspace.storage / "_gpu"
    if root.is_symlink() or not root.resolve().is_relative_to(workspace.storage.resolve()):
        raise ValueError("The GPU environment directory must remain inside this workspace.")
    return root


def nvidia_smi() -> str:
    """Use WSL's fixed driver location when its directory is absent from PATH."""
    located = shutil.which("nvidia-smi")
    fallback = Path("/usr/lib/wsl/lib/nvidia-smi")
    return located or (
        str(fallback) if sys.platform == "linux" and fallback.is_file() else "nvidia-smi"
    )


def devices() -> list[dict[str, Any]]:
    """Read actual NVIDIA memory/capability, never infer CUDA support from a model name."""
    try:
        result = subprocess.run(
            [
                nvidia_smi(),
                "--query-gpu=index,name,memory.total,memory.free,compute_cap",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
            if sys.platform == "win32"
            else 0,
        )
        if result.returncode:
            return []
        found = []
        for row in csv.reader(result.stdout.splitlines()):
            if len(row) != 5:
                continue
            index, name, total, free, capability = (x.strip() for x in row)
            major, minor = (int(x) for x in capability.split("."))
            found.append(
                {
                    "index": int(index),
                    "name": name,
                    "memory_mib": int(total),
                    "free_memory_mib": int(free),
                    "compute_capability": [major, minor],
                }
            )
        return found
    except (OSError, ValueError, subprocess.SubprocessError):
        return []


def readiness(workspace: Workspace) -> dict[str, Any]:
    """Separate host eligibility, environment setup and actual scientific verification."""
    root = gpu_root(workspace)
    supported = supported_platform()
    gpus = devices()
    eligible = [
        g
        for g in gpus
        if g["memory_mib"] >= MIN_MEMORY_MIB and tuple(g["compute_capability"]) >= (7, 5)
    ]
    blockers = []
    if not supported:
        blockers.append(
            "Automatic GPU setup requires Linux x86_64 or a Linux WSL2 workspace. "
            "Native Windows and macOS remain CPU workspaces."
        )
    if not eligible:
        blockers.append(
            "This workflow requires an NVIDIA GPU with at least 15,360 MiB "
            "(nominal 16 GB) and compute capability 7.5 or newer."
        )
    disk_free = shutil.disk_usage(workspace.storage).free
    receipt: dict[str, Any] = {}
    with suppress(OSError, ValueError):
        receipt = json.loads((root / "ready.json").read_text(encoding="utf-8"))
    if not isinstance(receipt, dict):
        receipt = {}
    installed = (
        receipt.get("recipe_id") == recipe()["id"]
        and (root / "se3-python").is_file()
        and (root / "boltz/bin/python").is_file()
        and receipt.get("cuda_smoke_passed") is True
    )
    if not installed and disk_free < SETUP_DISK_BYTES:
        blockers.append("GPU setup needs at least 60 GiB of free workspace storage.")
    active = next(
        (
            j
            for j in workspace.list()
            if j.get("kind") == "gpu_setup"
            and j.get("state") in {"queued", "running", "cancelling"}
        ),
        None,
    )
    available = [g for g in eligible if g["free_memory_mib"] >= MIN_FREE_MEMORY_MIB]
    if eligible and not available:
        blockers.append(
            "The compatible GPU is currently busy: at least 14,900 MiB free GPU "
            "memory is required before design can start. This is not a fit guarantee."
        )
    return {
        "supported_platform": supported,
        "hardware_eligible": supported and bool(eligible),
        "ready": supported and bool(available) and installed,
        "can_setup": not blockers and active is None,
        "blockers": blockers,
        "gpus": gpus,
        "selected_gpu_index": available[0]["index"]
        if available
        else eligible[0]["index"]
        if eligible
        else None,
        "disk_free_bytes": disk_free,
        "setup": {
            "state": active["state"] if active else "ready" if installed else "not_ready",
            "job_id": active["id"] if active else None,
        },
        "recipe": recipe(),
        "defaults": DEFAULTS,
        "limits": {"targets": 3, "trajectories": [1, 10], "binder_length": [40, 150]},
        "note": "Environment checks are not an end-to-end GPU scientific validation. "
        "Model weights need internet access; a particular target may still exceed memory. "
        "Predicted binding requires independent experimental validation.",
    }


def supported_platform() -> bool:
    """The reviewed environment recipe targets Linux x86_64, including WSL2."""
    return sys.platform == "linux" and platform.machine().lower() in {"x86_64", "amd64"}


def _source(workspace: Workspace, identity: str) -> tuple[dict[str, Any], Path]:
    state = workspace.read(identity)
    if state.get("kind", "discovery") != "discovery" or state["state"] not in {
        "completed",
        "incomplete_annotation",
    }:
        raise ValueError("Choose a completed discovery analysis before starting protein design.")
    run = Path(state["run_dir"]).resolve()
    if run.parent != workspace.root or not run.is_dir():
        raise ValueError("The discovery output is outside this workspace.")
    return state, run


def recorded_outputs(
    run: Path, manifest: Manifest | None = None, *, stage_name: str | None = None
) -> dict[str, str]:
    """Normalise both original absolute refs and portable refs without trusting outside paths."""
    result = {}
    manifest = manifest or Manifest.read(run / "run_manifest.jsonld")
    for stage in manifest.stages:
        if stage_name is not None and stage.name != stage_name:
            continue
        for ref in stage.outputs:
            path = Path(ref.path)
            resolved = path.resolve() if path.is_absolute() else (run / path).resolve()
            if resolved.is_relative_to(run.resolve()):
                result[resolved.relative_to(run.resolve()).as_posix()] = ref.sha256
    return result


def targets(workspace: Workspace, identity: str) -> dict[str, Any]:
    """Offer only recorded structured extracellular targets, with opaque selection IDs."""
    from bindsight.cli import _top_targets

    _, run = _source(workspace, identity)
    recorded = recorded_outputs(run)
    found = []
    for target in _top_targets(run):
        structure = Path(target["structure_path"])
        reasons = []
        if (
            structure.is_symlink()
            or not structure.resolve().is_relative_to(run)
            or not structure.is_file()
        ):
            reasons.append("The target structure is missing or outside this recorded run.")
        if not target["design_ranges"]:
            reasons.append("No recorded extracellular residue ranges are available.")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", target["uniprot"]):
            reasons.append("The target identifier is invalid.")
        if not reasons:
            expected = recorded.get(structure.resolve().relative_to(run).as_posix())
            if expected is None:
                reasons.append(
                    "This older discovery did not record the structure hash. Run discovery again before GPU design."
                )
            elif expected != sha256_file(structure):
                reasons.append("The structure bytes no longer match the discovery provenance.")
        descriptor = {k: v for k, v in target.items() if k != "structure_path"}
        descriptor["structure_sha256"] = sha256_file(structure) if not reasons else None
        key = hashlib.sha256(json.dumps(descriptor, sort_keys=True).encode()).hexdigest()[:20]
        found.append(
            {
                "id": key,
                "uniprot": target["uniprot"],
                "chain": target["chain"],
                "residues": target["residues"],
                "design_ranges": [list(pair) for pair in target["design_ranges"]],
                "structure_sha256": descriptor["structure_sha256"],
                "eligible": not reasons,
                "reasons": reasons,
                "size_note": "GPU memory depends on the retained target residues and binder length; passing hardware checks does not guarantee this target fits.",
            }
        )
    return {
        "source_job_id": identity,
        "targets": found,
        "note": "Eligibility reflects the recorded discovery filters and annotations, "
        "not proven safety, accessibility or binding.",
    }


def options(body: dict[str, Any]) -> dict[str, Any]:
    """Reject unsupported tools, paths, arbitrary commands and unbounded work."""
    if set(body) - {"target_ids", *DEFAULTS}:
        raise ValueError("Unknown protein-design setting.")
    selected = body.get("target_ids")
    if (
        not isinstance(selected, list)
        or not 1 <= len(selected) <= 3
        or any(not isinstance(v, str) or not re.fullmatch(r"[a-f0-9]{20}", v) for v in selected)
        or len(set(selected)) != len(selected)
    ):
        raise ValueError("Select one to three distinct eligible targets from this analysis.")
    result: dict[str, Any] = {"target_ids": selected}
    bounds = {
        "trajectories": (1, 10),
        "seed": (0, 2**31 - 1),
        "binder_length_min": (40, 150),
        "binder_length_max": (40, 150),
    }
    for name, (low, high) in bounds.items():
        value = body.get(name, DEFAULTS[name])
        if type(value) is not int or not low <= value <= high:
            raise ValueError(f"{name} must be an integer between {low} and {high}.")
        result[name] = value
    if result["binder_length_min"] > result["binder_length_max"]:
        raise ValueError("The minimum binder length must not exceed the maximum.")
    return result


def _enqueue(
    workspace: Workspace, kind: str, config: dict[str, Any], source: dict[str, Any] | None = None
) -> dict[str, Any]:
    from bindsight.report.web.workspace import now, write_json

    identity = workspace.create_upload()
    folder = workspace.directory(identity)
    run = workspace.root / f"analysis-{identity[:12]}"
    config.update(kind=kind, out_dir=str(run), gpu_root=str(gpu_root(workspace)))
    state = {
        "id": identity,
        "kind": kind,
        "name": "GPU environment setup"
        if kind == "gpu_setup"
        else "Protein design · " + str((source or {}).get("name", "discovery")),
        "state": "queued",
        "created_at": now(),
        "run_dir": str(run),
        "error": "",
        "genes": (source or {}).get("genes", 0),
        "samples": (source or {}).get("samples", 0),
        "contrast": (source or {}).get("contrast", ["condition", "target", "reference"]),
        "source_job_id": config.get("source_job_id"),
        "source_annotation_incomplete": (source or {}).get("state") == "incomplete_annotation",
    }
    with workspace.lock:
        if workspace._closed:
            raise ValueError("The workspace is closing. Reopen it before starting a job.")
        write_json(folder / "config.json", config)
        write_json(folder / "job.json", state)
        workspace.futures[identity] = workspace.executor.submit(workspace._execute, identity)
    return state


def start_setup(workspace: Workspace, body: dict[str, Any]) -> dict[str, Any]:
    """An explicit approved request installs only the fixed isolated recipe."""
    if set(body) != {"approved"} or body["approved"] is not True:
        raise ValueError(
            "Approve the GPU download and isolated installation before starting setup."
        )
    with workspace.lock:
        status = readiness(workspace)
        if not status["can_setup"]:
            raise ValueError(" ".join(status["blockers"]) or "GPU setup is already running.")
        return _enqueue(
            workspace,
            "gpu_setup",
            {"recipe_id": recipe()["id"], "gpu_index": status["selected_gpu_index"]},
        )


def start_design(workspace: Workspace, identity: str, body: dict[str, Any]) -> dict[str, Any]:
    """Queue a child run without overwriting discovery or accepting browser paths."""
    chosen = options(body)
    state, source = _source(workspace, identity)
    allowed = {t["id"]: t for t in targets(workspace, identity)["targets"] if t["eligible"]}
    if not set(chosen["target_ids"]).issubset(allowed):
        raise ValueError("A selected target is no longer eligible in this recorded analysis.")
    status = readiness(workspace)
    if not status["ready"]:
        raise ValueError(
            "Complete supported GPU environment setup before starting protein design. "
            + " ".join(status["blockers"])
        )
    return _enqueue(
        workspace,
        "gpu_design",
        {
            "source_job_id": identity,
            "source_run": str(source),
            "options": chosen,
            "selected_targets": [allowed[key] for key in chosen["target_ids"]],
            "source_manifest_sha256": sha256_file(source / "run_manifest.jsonld"),
            "source_config_sha256": sha256_file(source / "config.yaml"),
            "recipe_id": recipe()["id"],
            "gpu_index": status["selected_gpu_index"],
        },
        state,
    )


def resume(workspace: Workspace, identity: str) -> dict[str, Any]:
    """Resume only this application's fixed GPU work at verified stage boundaries."""
    from bindsight.report.web.workspace import now, write_json

    with workspace.lock:
        state = workspace.read(identity)
        if state.get("kind") not in {"gpu_setup", "gpu_design"} or state["state"] not in {
            "failed",
            "cancelled",
            "interrupted",
        }:
            raise ValueError("Only stopped GPU setup or design jobs can be resumed.")
        status = readiness(workspace)
        if not status["hardware_eligible"] or (
            state["kind"] == "gpu_design" and not status["ready"]
        ):
            raise ValueError(
                "The supported GPU environment is not ready. " + " ".join(status["blockers"])
            )
        if workspace._closed:
            raise ValueError("The workspace is closing.")
        state.update(state="queued", error="", resumed_at=now())
        state.pop("finished_at", None)
        write_json(workspace.directory(identity) / "job.json", state)
        workspace.futures[identity] = workspace.executor.submit(workspace._execute, identity)
    return state


def execution_environment(root: Path, gpu_index: int) -> dict[str, str]:
    """Use our prepared interpreters, ignoring unrelated custom executable overrides."""
    env = dict(os.environ)
    for key in ("BINDSIGHT_BOLTZ_BIN", "BINDSIGHT_LOCAL_IMAGE"):
        env.pop(key, None)
    env.update(
        BINDSIGHT_LOCAL_NATIVE="1",
        BINDSIGHT_DESIGN_PYTHON=str(root / "se3-python"),
        BINDSIGHT_BOLTZ_PYTHON=str(root / "boltz/bin/python"),
        BINDSIGHT_TOOLS_ROOT=str(root / "tools"),
        CUDA_VISIBLE_DEVICES=str(gpu_index),
        OMP_NUM_THREADS="1",
        OPENBLAS_NUM_THREADS="1",
        MKL_NUM_THREADS="1",
        PYTHONUNBUFFERED="1",
        PYTHONUTF8="1",
    )
    return env

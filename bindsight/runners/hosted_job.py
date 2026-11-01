# SPDX-License-Identifier: AGPL-3.0-or-later
"""Run the canonical executor and retain bounded hosted-runtime evidence.

The scientific command and its archive members are unchanged. Supplemental
receipts contain only selected source/runtime/model identities, final package
inventories and sampled hardware observations, never caches or model payloads.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tarfile
import tempfile
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from bindsight.archive_bounds import open_bounded_tar
from bindsight.runners.hosted_source import candidate_source
from bindsight.runners.installer_security import download_verified_uv, package_environment

MAX_ARCHIVE_BYTES = 8 * 1024**3
MAX_ARCHIVE_MEMBERS = 100000


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _json(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8", newline="\n")
    temporary.replace(path)


def _hardware_sample() -> dict[str, Any]:
    fields = ["index", "name", "driver_version", "memory.total", "memory.used", "utilization.gpu"]
    result = subprocess.run(
        ["nvidia-smi", "--query-gpu=" + ",".join(fields), "--format=csv,noheader,nounits"],
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    rows = []
    for line in result.stdout.splitlines()[:16]:
        parts = [part.strip() for part in line.split(",")]
        if len(parts) != len(fields):
            raise ValueError("Unexpected nvidia-smi field count")
        rows.append(dict(zip(fields, parts, strict=True)))
    return {"utc": _now(), "gpus": rows}


class _HardwareMonitor:
    def __init__(self, destination: Path):
        self.destination = destination
        self.stop = threading.Event()
        self.data: dict[str, Any] = {
            "schema": "bindsight-hosted-hardware/1",
            "memory_units": "MiB",
            "utilization_units": "percent",
            "sample_interval_seconds": 15,
            "samples": [],
            "sample_count": 0,
            "max_observed_memory_used_mib": 0,
            "errors": [],
        }
        self.thread = threading.Thread(target=self._loop, daemon=True)

    def sample(self) -> None:
        try:
            sample = _hardware_sample()
            self.data["sample_count"] += 1
            self.data["samples"].append(sample)
            if len(self.data["samples"]) > 2048:
                del self.data["samples"][1]
            for gpu in sample["gpus"]:
                used = int(gpu["memory.used"])
                self.data["max_observed_memory_used_mib"] = max(
                    self.data["max_observed_memory_used_mib"], used
                )
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            # Do not serialize subprocess output or environmental credentials.
            self.data["errors"] = (self.data["errors"] + [type(exc).__name__])[-16:]
        _json(self.destination, self.data)

    def _loop(self) -> None:
        while not self.stop.wait(15):
            self.sample()

    def __enter__(self) -> _HardwareMonitor:
        self.sample()
        self.thread.start()
        return self

    def __exit__(self, *_args: Any) -> None:
        self.stop.set()
        self.thread.join(timeout=12)
        if not self.thread.is_alive():
            self.sample()


def execution_environment(receipt: dict[str, Any]) -> dict[str, str]:
    """Apply the managed selection without inheriting Python/tool overrides."""
    environment = dict(os.environ)
    for key in (
        "PYTHONPATH",
        "PYTHONHOME",
        "PYTHONSTARTUP",
        "PYTHONUSERBASE",
        "BINDSIGHT_BOLTZ_BIN",
        "BINDSIGHT_LOCAL_IMAGE",
        "BINDSIGHT_DESIGN_PYTHON",
    ):
        environment.pop(key, None)
    environment.update(receipt["execution_environment"])
    environment["BINDSIGHT_GPU_DIAGNOSTICS"] = "1"
    return environment


def _freeze(root: Path, receipt: dict[str, Any], destination: Path) -> None:
    installer = download_verified_uv(root / "uv")
    environment = package_environment(execution_environment(receipt), root / "uv-cache")
    for name in ("se3", "boltz"):
        if name == "se3" and receipt["mode"] == "validate_only":
            continue
        result = subprocess.run(
            [
                str(installer),
                "--no-config",
                "pip",
                "freeze",
                "--python",
                str(root / name / "bin/python"),
            ],
            env=environment,
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        )
        if len(result.stdout.encode("utf-8")) > 2 * 1024**2:
            raise ValueError("Final runtime inventory exceeds its size limit")
        (destination / f"{name}-final-freeze.txt").write_text(
            result.stdout, encoding="utf-8", newline="\n"
        )


def _pack(
    scientific: Path, runtime: Path, output: Path, work: Path, *, include_scientific: bool = True
) -> None:
    """Copy safe scientific members verbatim and append only our selected receipts."""
    temporary = output.with_suffix(output.suffix + ".tmp")
    try:
        with tarfile.open(temporary, "w:gz", encoding="utf-8") as destination:
            if include_scientific and scientific.exists():
                with open_bounded_tar(
                    scientific, max_bytes=MAX_ARCHIVE_BYTES, max_members=MAX_ARCHIVE_MEMBERS
                ) as original:
                    seen = set()
                    total = 0
                    for member in original:
                        name = PurePosixPath(member.name)
                        if (
                            name.is_absolute()
                            or ".." in name.parts
                            or "\\" in member.name
                            or not name.parts
                            or name.parts[0] == "runtime"
                            or member.name in seen
                            or not (member.isfile() or member.isdir())
                        ):
                            raise ValueError("Unsafe scientific archive member")
                        seen.add(member.name)
                        total += member.size
                        if total > MAX_ARCHIVE_BYTES:
                            raise ValueError("Scientific archive exceeds its size limit")
                        source = original.extractfile(member) if member.isfile() else None
                        try:
                            destination.addfile(member, source)
                        finally:
                            if source is not None:
                                source.close()
            else:
                # Failed jobs may have no final archive. Preserve bounded raw
                # evidence only; never traverse runtime caches or model roots.
                evidence = work / "evidence"
                total = 0
                count = 0
                for path in sorted(evidence.rglob("*")):
                    if path.is_symlink() or not path.is_file():
                        continue
                    if not path.resolve().is_relative_to(evidence.resolve()):
                        raise ValueError("Partial evidence escapes its directory")
                    count += 1
                    total += path.stat().st_size
                    if total > 512 * 1024**2 or count > 20000:
                        break
                    destination.add(
                        path,
                        arcname="partial-evidence/" + path.relative_to(evidence).as_posix(),
                        recursive=False,
                    )
            for path in sorted(runtime.iterdir()):
                if path.is_symlink() or not path.is_file() or path.stat().st_size > 16 * 1024**2:
                    raise ValueError("Unsafe runtime evidence file")
                destination.add(path, arcname="runtime/" + path.name, recursive=False)
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)


def run_hosted_job(
    *,
    backend: str,
    root: Path,
    receipt: dict[str, Any],
    source: Path,
    spec: Path,
    output: Path,
    source_kind: str = "published-wheel",
) -> dict[str, Any]:
    """Run unchanged science, then return status after writing its evidence archive."""
    from bindsight.runners.gpu_runtime import collect_model_weights

    if backend not in {"colab", "modal"} or source_kind not in {
        "published-wheel",
        "candidate-wheel",
    }:
        raise ValueError("Unsupported hosted backend or source kind")
    identity = candidate_source(source)
    identity["kind"] = source_kind
    provisioned = receipt["source_identity"]
    if any(provisioned.get(key) != identity[key] for key in ("filename", "sha256", "bytes")):
        raise ValueError("Provisioned runtime source differs from the selected wheel")
    output.parent.mkdir(parents=True, exist_ok=True)
    runtime = Path(tempfile.mkdtemp(prefix=output.name + ".runtime-", dir=output.parent))
    scientific = runtime / "scientific.tar.gz"
    # Match job_exec.main's work directory derivation exactly.
    work = scientific.parent / "scientific_work"
    status: dict[str, Any] = {
        "schema": "bindsight-hosted-run/1",
        "backend": backend,
        "outcome": "incomplete",
        "returncode": None,
        "source": identity,
        "started_utc": _now(),
        "evidence_errors": [],
    }
    _json(runtime / "provision-receipt.json", receipt)
    _json(runtime / "backend-status.json", status)
    with _HardwareMonitor(runtime / "hardware.json"):
        try:
            result = subprocess.run(
                [
                    receipt["boltz_python"],
                    "-I",
                    "-m",
                    "bindsight.runners.job_exec",
                    str(spec),
                    str(scientific),
                ],
                env=execution_environment(receipt),
                check=False,
            )
            status["returncode"] = result.returncode
            status["outcome"] = (
                "completed" if result.returncode == 0 and scientific.is_file() else "failed"
            )
        except (OSError, subprocess.SubprocessError) as exc:
            status["evidence_errors"].append({"stage": "executor", "error": type(exc).__name__})
            status["outcome"] = "failed"
    collectors: tuple[tuple[str, Callable[[], None]], ...] = (
        (
            "model-weights",
            lambda: _json(
                runtime / "model-weights.json", collect_model_weights(root, work / "evidence")
            ),
        ),
        ("final-freezes", lambda: _freeze(root, receipt, runtime)),
    )
    for stage, collect in collectors:
        try:
            collect()
        except Exception as exc:
            status["evidence_errors"].append({"stage": stage, "error": type(exc).__name__})
            if status["outcome"] == "completed":
                status["outcome"] = "incomplete"
    status["finished_utc"] = _now()
    _json(runtime / "backend-status.json", status)
    # Keep the large executor output/work out of the receipt-only directory.
    receipts = runtime / "receipts"
    receipts.mkdir()
    for name in (
        "backend-status.json",
        "provision-receipt.json",
        "hardware.json",
        "model-weights.json",
        "se3-final-freeze.txt",
        "boltz-final-freeze.txt",
    ):
        path = runtime / name
        if path.exists():
            path.replace(receipts / name)
    _receipt_manifest(receipts)
    try:
        _pack(scientific, receipts, output, work)
    except (OSError, ValueError, tarfile.TarError, EOFError) as exc:
        status["outcome"] = "incomplete" if status["returncode"] == 0 else "failed"
        status["evidence_errors"].append(
            {"stage": "scientific-archive", "error": type(exc).__name__}
        )
        _json(receipts / "backend-status.json", status)
        _receipt_manifest(receipts)
        _pack(scientific, receipts, output, work, include_scientific=False)
    return status


def _receipt_manifest(receipts: Path) -> None:
    _json(
        receipts / "manifest.json",
        {
            "schema": "bindsight-hosted-evidence/1",
            "files": [
                {
                    "path": path.name,
                    "bytes": path.stat().st_size,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
                for path in sorted(receipts.iterdir())
                if path.name != "manifest.json"
            ],
        },
    )


def archive_status(path: Path) -> dict[str, Any]:
    """Read the explicit backend outcome without extracting or executing data."""
    with open_bounded_tar(
        path, max_bytes=MAX_ARCHIVE_BYTES, max_members=MAX_ARCHIVE_MEMBERS
    ) as archive:
        matches = [member for member in archive if member.name == "runtime/backend-status.json"]
        if len(matches) != 1 or not matches[0].isfile() or matches[0].size > 2 * 1024**2:
            raise ValueError("Missing or invalid hosted backend status")
        stream = archive.extractfile(matches[0])
        assert stream is not None
        with stream:
            value: dict[str, Any] = json.load(stream)
        if value.get("schema") != "bindsight-hosted-run/1":
            raise ValueError("Unknown hosted backend status schema")
        return value


def main() -> None:
    """Execute the generated notebook's evidence-preserving managed job."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=("colab", "modal"), required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument(
        "--source-kind", choices=("published-wheel", "candidate-wheel"), default="published-wheel"
    )
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    status = run_hosted_job(
        backend=args.backend,
        root=args.root,
        receipt=json.loads(args.receipt.read_text(encoding="utf-8")),
        source=args.source,
        source_kind=args.source_kind,
        spec=args.spec,
        output=args.output,
    )
    if status["outcome"] != "completed":
        raise SystemExit(f"Hosted job {status['outcome']}; evidence retained in {args.output}")


if __name__ == "__main__":
    main()

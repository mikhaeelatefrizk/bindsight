# SPDX-License-Identifier: AGPL-3.0-or-later
"""Local-only analysis workspaces, complete input checks, and real subprocess jobs."""

from __future__ import annotations

import csv
import gzip
import importlib.util
import json
import math
import os
import re
import secrets
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

IDENTIFIER = re.compile(r"^[a-f0-9]{32}$")
COLUMN = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
MAX_UPLOAD = 512 * 1024 * 1024


def now() -> str:
    """Return a real UTC timestamp for the work log."""
    return datetime.now(UTC).isoformat()


def write_json(path: Path, data: dict[str, Any]) -> None:
    """Persist job state atomically."""
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    for attempt in range(10):
        try:
            tmp.replace(path)
            break
        except PermissionError:
            if attempt == 9:
                raise
            time.sleep(0.02)


def hardware(root: Path) -> dict[str, Any]:
    """Report measured hardware, separating GPU presence from tool readiness."""
    gpus = []
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        if result.returncode == 0:
            for row in csv.reader(result.stdout.splitlines()):
                if len(row) == 2:
                    gpus.append({"name": row[0].strip(), "memory_mib": int(row[1].strip())})
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pass
    memory = None
    try:
        psutil = importlib.import_module("psutil")
        memory = psutil.virtual_memory().available
    except ImportError:
        pass
    scientific = all(
        importlib.util.find_spec(name) is not None
        for name in ("pydeseq2", "pandas", "pyarrow", "numpy", "scipy")
    )
    return {
        "platform": sys.platform,
        "python": sys.version.split()[0],
        "cpus": os.cpu_count() or 1,
        "memory_available_bytes": memory,
        "disk_free_bytes": shutil.disk_usage(root).free,
        "gpus": gpus,
        "discovery_installed": scientific,
        "gpu_design_note": "A detected GPU is not a verified design environment. Local design needs the pinned RFdiffusion, ProteinMPNN and Boltz environments; available memory must fit the target.",
    }


def _read_rows(path: Path) -> Iterator[list[str]]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8-sig", newline="") as stream:

        def bounded_lines() -> Iterator[str]:
            expanded = 0
            for line in stream:
                expanded += len(line.encode("utf-8"))
                if expanded > 1024 * 1024 * 1024:
                    raise ValueError(
                        "An expanded input must be at most 1 GB for this local workflow."
                    )
                yield line

        yield from csv.reader(bounded_lines(), delimiter="\t")


def inspect_inputs(counts: Path, design: Path) -> dict[str, Any]:
    """Validate every row and value; never truncate a preview into a certification."""
    design_rows = _read_rows(design)
    header = next(design_rows, None)
    if not header or len(header) < 2 or len(set(header)) != len(header):
        raise ValueError(
            "The design table needs a sample-ID column and uniquely named factor columns, separated by tabs."
        )
    columns = header[1:]
    records: dict[str, dict[str, str]] = {}
    for line, row in enumerate(design_rows, 2):
        if not row or all(not cell for cell in row):
            continue
        if len(row) != len(header) or not row[0] or any(not value.strip() for value in row[1:]):
            raise ValueError(
                f"Design row {line} has missing values or a different number of columns."
            )
        if row[0] in records:
            raise ValueError(f"Repeated sample ID in design table: {row[0]}")
        records[row[0]] = dict(zip(columns, row[1:], strict=True))
        if len(records) > 2_000:
            raise ValueError("The local workbench supports at most 2,000 samples per run.")
    if len(records) < 6:
        raise ValueError(
            "At least six biological samples are required, with at least three in each comparison group."
        )
    counts_rows = _read_rows(counts)
    count_header = next(counts_rows, None)
    if not count_header or len(count_header) < 7:
        raise ValueError(
            "The counts matrix must be tab-separated, with gene IDs first and at least six sample columns."
        )
    samples = count_header[1:]
    if any(not s for s in samples) or len(set(samples)) != len(samples):
        raise ValueError("Counts sample names must be nonempty and unique.")
    if set(samples) != set(records):
        raise ValueError(
            "Sample IDs must match exactly between the counts matrix and design table; no samples are silently dropped."
        )
    genes: set[str] = set()
    totals = [0] * len(samples)
    for line, row in enumerate(counts_rows, 2):
        if not row or all(not cell for cell in row):
            continue
        if len(row) != len(count_header) or not row[0] or row[0] in genes:
            raise ValueError(
                f"Counts row {line} has a repeated/missing gene ID or a different number of columns."
            )
        if not re.fullmatch(r"ENSG\d+", row[0]):
            raise ValueError(
                f"Gene {row[0]!r} must be an unversioned human Ensembl gene ID (ENSG followed by digits). Resolve version suffixes and any resulting duplicate IDs before analysis; the surfaceome uses exact identifiers."
            )
        genes.add(row[0])
        for index, raw in enumerate(row[1:]):
            try:
                value = float(raw)
            except ValueError as exc:
                raise ValueError(f"Counts row {line} contains a non-numeric value.") from exc
            if not math.isfinite(value) or value < 0 or value != math.trunc(value) or value > 2**53:
                raise ValueError(
                    f"Counts row {line} must contain finite, nonnegative raw integer counts, not TPM/FPKM or normalized values."
                )
            totals[index] += int(value)
        if len(genes) > 150_000:
            raise ValueError("This local workflow supports up to 150,000 gene rows per analysis.")
    if not genes or any(n == 0 for n in totals):
        raise ValueError("The counts matrix is empty or includes a sample with zero total counts.")
    factors = []
    for column in columns:
        values = sorted({row[column] for row in records.values()})
        if COLUMN.fullmatch(column) and len(values) == 2:
            factors.append(
                {
                    "name": column,
                    "levels": values,
                    "sizes": {v: sum(row[column] == v for row in records.values()) for v in values},
                }
            )
    if not factors:
        raise ValueError(
            "Provide a two-level comparison column named using letters, numbers, and underscores (for example condition)."
        )
    return {
        "genes": len(genes),
        "samples": len(samples),
        "factors": factors,
        "columns": [c for c in columns if COLUMN.fullmatch(c)],
        "records": records,
    }


class Workspace:
    """One local, persistent workspace with a single active CPU job."""

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.storage = self.root / "_workbench"
        self.storage.mkdir(parents=True, exist_ok=True)
        self.token = secrets.token_urlsafe(32)
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="bindsight-local")
        self.lock = threading.RLock()
        self.processes: dict[str, subprocess.Popen[bytes]] = {}
        self.futures: dict[str, Any] = {}
        for state in self.storage.glob("*/job.json"):
            try:
                data = json.loads(state.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                continue
            if data.get("state") in {"queued", "running", "cancelling"}:
                data.update(
                    state="interrupted",
                    error="The local application stopped before this run completed.",
                    finished_at=now(),
                )
                write_json(state, data)

    def directory(self, identity: str) -> Path:
        """Resolve an existing, strictly validated workspace identifier."""
        if not IDENTIFIER.fullmatch(identity):
            raise ValueError("Unknown analysis identifier.")
        path = self.storage / identity
        if not path.is_dir():
            raise ValueError("Unknown analysis identifier.")
        return path

    def create_upload(self) -> str:
        """Create a new input directory without starting any analysis."""
        identity = uuid.uuid4().hex
        (self.storage / identity).mkdir()
        return identity

    def inputs(self, identity: str) -> tuple[Path, Path]:
        """Find exactly one completed upload for each required input."""
        root = self.directory(identity)
        found = []
        for kind in ("counts", "design"):
            candidates = [p for p in (root / f"{kind}.tsv", root / f"{kind}.tsv.gz") if p.is_file()]
            if len(candidates) != 1:
                raise ValueError("Choose and upload both input files before checking them.")
            found.append(candidates[0])
        return found[0], found[1]

    def launch(self, identity: str, options: dict[str, Any]) -> dict[str, Any]:
        """Validate complete inputs and enqueue one genuine discovery process."""
        from bindsight.config import RunConfig

        root = self.directory(identity)
        if (root / "job.json").exists():
            raise ValueError(
                "These inputs already belong to an analysis. Create a new analysis to run them again."
            )
        counts, design = self.inputs(identity)
        checked = inspect_inputs(counts, design)
        factor, numerator, denominator = (
            str(options.get(k, "")) for k in ("factor", "numerator", "denominator")
        )
        valid = next((f for f in checked["factors"] if f["name"] == factor), None)
        if (
            not valid
            or numerator == denominator
            or set((numerator, denominator)) != set(valid["levels"])
        ):
            raise ValueError(
                "Choose the comparison and reference from the actual two-level design column."
            )
        if min(valid["sizes"].values()) < 3:
            raise ValueError("Both groups need at least three biological replicates.")
        pair = str(options.get("paired_by") or "")
        formula = f"~ {factor}"
        if pair:
            if pair not in checked["columns"] or pair == factor:
                raise ValueError("Choose a valid donor/patient column for pairing.")
            groups: dict[str, list[str]] = {}
            for row in checked["records"].values():
                groups.setdefault(row[pair], []).append(row[factor])
            if any(sorted(values) != sorted(valid["levels"]) for values in groups.values()):
                raise ValueError(
                    "Each donor/patient must have exactly one sample from each condition for this paired workflow."
                )
            formula = f"~ {pair} + {factor}"
        output = self.root / f"analysis-{identity[:12]}"
        cfg = RunConfig.model_validate(
            {
                "name": str(options.get("name") or "Local RNA-seq analysis")[:120],
                "out_dir": str(output),
                "backend": "local_docker",
                "inputs": {"counts": str(counts), "design": str(design)},
                "params": {
                    "deg": {
                        "design_formula": formula,
                        "contrast": [factor, numerator, denominator],
                        "categorical_factors": [factor, *([pair] if pair else [])],
                        "n_cpus": max(1, min(4, (os.cpu_count() or 2) - 1)),
                        "fdr_threshold": float(options.get("fdr", 0.05)),
                        "log2fc_threshold": float(options.get("log2fc", 1.0)),
                    },
                    "target_discovery": {
                        "use_extended_surfaceome": True,
                        "allow_bundled_mapping_fallback": False,
                        "open_targets_require_measured": True,
                        "use_gtex_safety": True,
                        "gtex_require_measured": True,
                        "use_uniprot_topology": True,
                        "require_extracellular_domain": True,
                    },
                },
            }
        )
        if not 0 < cfg.params.deg.fdr_threshold < 1:
            raise ValueError("The FDR threshold must be greater than zero and less than one.")
        state = {
            "id": identity,
            "name": cfg.name,
            "state": "queued",
            "created_at": now(),
            "run_dir": str(output),
            "samples": checked["samples"],
            "genes": checked["genes"],
            "contrast": [factor, numerator, denominator],
            "error": "",
        }
        with self.lock:
            if (root / "job.json").exists():
                raise ValueError("An analysis has already been started for these inputs.")
            write_json(root / "config.json", cfg.model_dump(mode="json", by_alias=True))
            write_json(root / "job.json", state)
            self.futures[identity] = self.executor.submit(self._execute, identity)
        return state

    def _execute(self, identity: str) -> None:
        try:
            self._execute_job(identity)
        except Exception as exc:
            with self.lock:
                state = self.read(identity)
                state.update(state="failed", error=str(exc), finished_at=now())
                write_json(self.directory(identity) / "job.json", state)

    def _execute_job(self, identity: str) -> None:
        root = self.directory(identity)
        with self.lock:
            state = self.read(identity)
            if state["state"] == "cancelled":
                return
            state.update(state="running", started_at=now())
            write_json(root / "job.json", state)
        try:
            with (root / "analysis.log").open("w", encoding="utf-8") as log:
                kwargs: dict[str, Any] = {"stdout": log, "stderr": subprocess.STDOUT}
                if os.name == "nt":
                    kwargs["creationflags"] = (
                        subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
                    )
                else:
                    kwargs["start_new_session"] = True
                env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONUTF8="1")
                with self.lock:
                    state = self.read(identity)
                    if state["state"] in {"cancelled", "cancelling"}:
                        return
                    process = subprocess.Popen(
                        [
                            sys.executable,
                            "-m",
                            "bindsight.report.web.worker",
                            str(root / "config.json"),
                        ],
                        env=env,
                        **kwargs,
                    )
                    self.processes[identity] = process
                exit_code = process.wait()
            with self.lock:
                state = self.read(identity)
                if state["state"] in {"cancelling", "cancelled"}:
                    state["state"] = "cancelled"
                elif exit_code != 0:
                    state.update(
                        state="failed",
                        error="The analysis did not complete. Read the actual error in the log; partial outputs are not a completed result.",
                    )
                else:
                    manifest = Path(state["run_dir"]) / "run_manifest.jsonld"
                    body = json.loads(manifest.read_text(encoding="utf-8"))
                    stages = body.get("stages") or []
                    complete = {
                        s.get("name")
                        for s in stages
                        if s.get("status") in {"completed", "skipped_cache"}
                    }
                    if not {"deg", "discover", "report"}.issubset(complete) or any(
                        s.get("status") in {"failed", "running"} for s in stages
                    ):
                        state.update(
                            state="failed",
                            error="The scientific manifest records a failed or missing analysis stage.",
                        )
                    else:
                        coverage_path = root / "coverage.json"
                        coverage = (
                            json.loads(coverage_path.read_text(encoding="utf-8"))
                            if coverage_path.is_file()
                            else {}
                        )
                        state["coverage"] = coverage
                        state["state"] = (
                            "incomplete_annotation"
                            if coverage.get("unassessed_lookups", 0)
                            else "completed"
                        )
                state["finished_at"] = now()
                write_json(root / "job.json", state)
        except Exception as exc:
            with self.lock:
                state = self.read(identity)
                state.update(state="failed", error=str(exc), finished_at=now())
                write_json(root / "job.json", state)
        finally:
            with self.lock:
                self.processes.pop(identity, None)

    def read(self, identity: str) -> dict[str, Any]:
        """Read the persisted status of an existing analysis."""
        path = self.directory(identity) / "job.json"
        if not path.is_file():
            raise ValueError("No analysis has been started for those inputs.")
        with self.lock:
            data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return data

    def list(self) -> list[dict[str, Any]]:
        """List readable job records in reverse creation order."""
        records = []
        for path in self.storage.glob("*/job.json"):
            try:
                records.append(json.loads(path.read_text(encoding="utf-8")))
            except (ValueError, OSError):
                continue
        return sorted(records, key=lambda row: row.get("created_at", ""), reverse=True)

    def cancel(self, identity: str) -> dict[str, Any]:
        """Cancel a queued job or stop its own active process tree."""
        with self.lock:
            state = self.read(identity)
            if state["state"] not in {"queued", "running"}:
                return state
            future = self.futures.get(identity)
            process = self.processes.get(identity)
            state["state"] = "cancelling" if process else "cancelled"
            state["finished_at"] = now()
            write_json(self.directory(identity) / "job.json", state)
            if future:
                future.cancel()
            if process and process.poll() is None:
                if sys.platform == "win32":
                    subprocess.run(
                        ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                        capture_output=True,
                        timeout=15,
                        creationflags=subprocess.CREATE_NO_WINDOW,
                    )
                else:
                    os.killpg(process.pid, signal.SIGTERM)
            return state

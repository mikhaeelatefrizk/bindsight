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
import signal
import subprocess
import sys
import threading
import time
import uuid
import zlib
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, BinaryIO

IDENTIFIER = re.compile(r"^[a-f0-9]{32}$")
COLUMN = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")
MAX_UPLOAD = 512 * 1024 * 1024
MAX_INPUT_LINE = 1024 * 1024


class WorkspaceInUseError(RuntimeError):
    """Another application or surviving analysis already owns this workspace."""


def now() -> str:
    """Return a real UTC timestamp for the work log."""
    return datetime.now(UTC).isoformat()


def write_json(path: Path, data: dict[str, Any]) -> None:
    """Persist job state atomically."""
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8", newline="\n")
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
    from bindsight.report.web.gpu import nvidia_smi
    from bindsight.report.web.resources import dependency_status, measured_resources

    gpus = []
    creationflags = 0
    if sys.platform == "win32":
        creationflags = subprocess.CREATE_NO_WINDOW
    try:
        result = subprocess.run(
            [nvidia_smi(), "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=creationflags,
        )
        if result.returncode == 0:
            for row in csv.reader(result.stdout.splitlines()):
                if len(row) == 2:
                    gpus.append({"name": row[0].strip(), "memory_mib": int(row[1].strip())})
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pass
    measured = measured_resources(root)
    dependencies = dependency_status()
    return {
        "platform": sys.platform,
        "python": sys.version.split()[0],
        **measured,
        "gpus": gpus,
        "discovery_installed": dependencies["usable"],
        "dependency_status": dependencies,
        "gpu_design_note": "A detected GPU is not a verified design environment. Local design needs the pinned RFdiffusion, ProteinMPNN and Boltz environments; available memory must fit the target.",
    }


def _read_rows(path: Path) -> Iterator[list[str]]:
    opener = gzip.open if path.suffix == ".gz" else open
    try:
        with opener(path, "rt", encoding="utf-8-sig", newline="") as stream:

            def bounded_lines() -> Iterator[str]:
                expanded = 0
                # Bound each read before allocating an entire decompressed line.
                # A gzip file with one enormous line otherwise bypasses the
                # expanded-size check until that line is already in memory.
                while line := stream.readline(MAX_INPUT_LINE + 1):
                    if len(line) > MAX_INPUT_LINE:
                        raise ValueError(
                            "An input line exceeds the 1 MB limit; check its TSV format."
                        )
                    expanded += len(line.encode("utf-8"))
                    if expanded > 1024 * 1024 * 1024:
                        raise ValueError(
                            "An expanded input must be at most 1 GB for this local workflow."
                        )
                    yield line

            yield from csv.reader(bounded_lines(), delimiter="\t", strict=True)
    except (csv.Error, EOFError, UnicodeError, zlib.error) as exc:
        raise ValueError(
            f"The input is not a complete, valid UTF-8 TSV or gzip file: {exc}"
        ) from exc


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
                if not NUMBER.fullmatch(raw.strip()):
                    raise ValueError("Invalid numeric representation")
                value = Decimal(raw.strip())
            except (ValueError, InvalidOperation) as exc:
                raise ValueError(f"Counts row {line} contains a non-numeric value.") from exc
            if (
                not value.is_finite()
                or value < 0
                or value > 2**53
                or value != value.to_integral_value()
            ):
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
    """One owned workspace with a single active analysis or GPU setup job."""

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.storage = self.root / "_workbench"
        self.storage.mkdir(parents=True, exist_ok=True)
        self._owner: BinaryIO | None = None
        self._closed = False
        self._acquire_ownership()
        self.token = secrets.token_urlsafe(32)
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="bindsight-local")
        self.lock = threading.RLock()
        self.processes: dict[str, subprocess.Popen[bytes]] = {}
        self.futures: dict[str, Any] = {}
        try:
            abandoned = []
            for state in self.storage.glob("*/job.json"):
                try:
                    data = json.loads(state.read_text(encoding="utf-8"))
                except (ValueError, OSError):
                    continue
                if not isinstance(data, dict):
                    continue
                if data.get("state") in {"queued", "running", "cancelling"}:
                    if self._worker_is_alive(data, state.parent / "config.json"):
                        raise WorkspaceInUseError(
                            "An analysis from the previous application is still running. "
                            "Wait for it to finish before reopening this workspace."
                        )
                    abandoned.append((state, data))
            # Check every worker before changing any persisted status.
            for state, data in abandoned:
                data.update(
                    state="interrupted",
                    error="The local application stopped before this run completed.",
                    finished_at=now(),
                )
                write_json(state, data)
        except Exception:
            self.executor.shutdown(wait=False, cancel_futures=True)
            self._release_ownership()
            raise

    def _acquire_ownership(self) -> None:
        owner = (self.storage / ".owner.lock").open("a+b")
        try:
            if sys.platform == "win32":
                import msvcrt

                if owner.seek(0, 2) == 0:
                    owner.write(b"\0")
                    owner.flush()
                owner.seek(0)
                msvcrt.locking(owner.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(owner.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            owner.close()
            raise WorkspaceInUseError(
                "This workspace is already open in another application. "
                "Use its existing browser tab, or close it before launching again."
            ) from exc
        self._owner = owner

    def _release_ownership(self) -> None:
        if self._owner is not None:
            self._owner.close()
            self._owner = None

    @staticmethod
    def _worker_is_alive(state: dict[str, Any], config: Path) -> bool:
        """Recognise surviving workers without mistaking a reused PID for this job."""
        if not state.get("worker_pid"):
            return False
        psutil = importlib.import_module("psutil")

        try:
            process = psutil.Process(int(state["worker_pid"]))
            if process.status() == psutil.STATUS_ZOMBIE:
                return False
            if state.get("worker_created_at") is not None:
                return bool(process.create_time() == state["worker_created_at"])
            arguments = process.cmdline()
            workers = {
                "bindsight.report.web.worker",
                "bindsight.report.web.gpu_worker",
                "bindsight.report.web.gpu_setup",
            }
            return bool(workers.intersection(arguments)) and str(config) in arguments
        except psutil.NoSuchProcess:
            return False
        except psutil.AccessDenied:
            # A process whose identity cannot be checked must not be relabelled
            # as dead or killed based solely on a possibly reused PID.
            return True

    def close(self) -> None:
        """Stop and reap this application's workers before releasing ownership."""
        with self.lock:
            if self._closed:
                return
            self._closed = True
            identities = list(self.futures)
        for identity in identities:
            try:
                self.cancel(identity)
            except ValueError:
                with self.lock:
                    self._closed = False
                raise
        self.executor.shutdown(wait=True, cancel_futures=True)
        self._release_ownership()

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
        from bindsight.report.web.resources import assess_execution

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
        try:
            if any(isinstance(options.get(k), bool) for k in ("fdr", "log2fc")):
                raise ValueError
            fdr = float(options.get("fdr", 0.05))
            log2fc = float(options.get("log2fc", 1.0))
        except (TypeError, ValueError) as exc:
            raise ValueError("The FDR and fold-change thresholds must be finite numbers.") from exc
        if not math.isfinite(fdr) or not 0 < fdr < 1:
            raise ValueError(
                "The FDR threshold must be finite, greater than zero and less than one."
            )
        if not math.isfinite(log2fc) or log2fc < 0:
            raise ValueError("The fold-change threshold must be a finite, nonnegative number.")
        admission = assess_execution(
            self.storage,
            genes=checked["genes"],
            samples=checked["samples"],
            input_bytes=counts.stat().st_size + design.stat().st_size,
            refresh_dependencies=True,
        )
        if not admission["admitted"]:
            raise ValueError(" ".join(admission["reasons"]))
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
                        "n_cpus": admission["n_cpus"],
                        "fdr_threshold": fdr,
                        "log2fc_threshold": log2fc,
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
            "resource_admission": admission,
        }
        with self.lock:
            if self._closed:
                raise ValueError("The local workspace is closing. Reopen it before starting a run.")
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
            if self._closed:
                state.update(state="cancelled", finished_at=now())
                write_json(root / "job.json", state)
                return
            state.update(state="running", started_at=now())
            write_json(root / "job.json", state)
        try:
            with (root / "analysis.log").open("a", encoding="utf-8") as log:
                log.write(f"\n--- Worker attempt started {now()} ---\n")
                log.flush()
                kwargs: dict[str, Any] = {"stdout": log, "stderr": subprocess.STDOUT}
                if sys.platform == "win32":
                    kwargs["creationflags"] = (
                        subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
                    )
                else:
                    kwargs["start_new_session"] = True
                env = dict(
                    os.environ,
                    PYTHONUNBUFFERED="1",
                    PYTHONUTF8="1",
                    OMP_NUM_THREADS="1",
                    OPENBLAS_NUM_THREADS="1",
                    MKL_NUM_THREADS="1",
                )
                worker = {
                    "gpu_setup": "bindsight.report.web.gpu_setup",
                    "gpu_design": "bindsight.report.web.gpu_worker",
                }.get(state.get("kind", "discovery"), "bindsight.report.web.worker")
                with self.lock:
                    state = self.read(identity)
                    if state["state"] in {"cancelled", "cancelling"}:
                        return
                    process = subprocess.Popen(
                        [
                            sys.executable,
                            "-m",
                            worker,
                            str(root / "config.json"),
                        ],
                        env=env,
                        **kwargs,
                    )
                    self.processes[identity] = process
                    state["worker_pid"] = process.pid
                    psutil = importlib.import_module("psutil")

                    try:
                        state["worker_created_at"] = psutil.Process(process.pid).create_time()
                    except psutil.Error:
                        state["worker_created_at"] = None
                    write_json(root / "job.json", state)
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
                elif state.get("kind") == "gpu_setup":
                    from bindsight.report.web.gpu import recipe

                    receipt = Path(state["run_dir"]) / "gpu_setup_receipt.json"
                    body = json.loads(receipt.read_text(encoding="utf-8"))
                    if body.get("recipe_id") != recipe()["id"] or not body.get("cuda_smoke_passed"):
                        state.update(
                            state="failed",
                            error="GPU setup did not produce a valid environment receipt.",
                        )
                    else:
                        state["state"] = "completed"
                else:
                    manifest = Path(state["run_dir"]) / "run_manifest.jsonld"
                    body = json.loads(manifest.read_text(encoding="utf-8"))
                    stages = body.get("stages") or []
                    complete = {
                        s.get("name")
                        for s in stages
                        if s.get("status") in {"completed", "skipped_cache"}
                    }
                    required = (
                        {"design", "validate", "rank", "report"}
                        if state.get("kind") == "gpu_design"
                        else {"deg", "discover", "report"}
                    )
                    if not required.issubset(complete) or any(
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
                            or state.get("source_annotation_incomplete")
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
                try:
                    self._stop_process_tree(process)
                except (OSError, subprocess.SubprocessError) as exc:
                    if process.poll() is None:
                        state.update(state="running", error=f"Could not stop the analysis: {exc}")
                        state.pop("finished_at", None)
                        write_json(self.directory(identity) / "job.json", state)
                        raise ValueError(state["error"]) from exc
            return state

    @staticmethod
    def _stop_process_tree(process: subprocess.Popen[bytes]) -> None:
        if sys.platform == "win32":
            result = subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                timeout=15,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            if result.returncode != 0 and process.poll() is None:
                # Restricted Windows environments can deny taskkill's tree
                # enumeration even for a process we started. psutil checks
                # process identity against PID reuse; Popen kills its own
                # retained process handle, never an unrelated numeric PID.
                psutil = importlib.import_module("psutil")
                try:
                    children = psutil.Process(process.pid).children(recursive=True)
                    for child in reversed(children):
                        with suppress(psutil.NoSuchProcess):
                            child.kill()
                    if process.poll() is None:
                        process.kill()
                    _, alive = psutil.wait_procs(children, timeout=5)
                    if alive:
                        raise OSError("Some analysis subprocesses could not be stopped.")
                except psutil.NoSuchProcess:
                    pass
                except psutil.Error as exc:
                    raise OSError("Windows could not terminate the analysis process tree.") from exc
            process.wait(timeout=5)
        else:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                return
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)

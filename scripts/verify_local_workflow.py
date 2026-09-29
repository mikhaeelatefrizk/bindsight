# SPDX-License-Identifier: AGPL-3.0-or-later
"""Exercise real local uploads, inspection, analysis, and all eight result downloads.

Supply real observations; this script creates no expression data and substitutes no
scientific implementation. The public JSON is a portable execution record, not
biological validation. Raw logs and artifacts remain only in the requested new
local output directory; the record contains hashes and selected summary fields.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import importlib.metadata
import json
import math
import os
import platform
import re
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bindsight.provenance.manifest import SCIENTIFIC_STACK  # noqa: E402
from bindsight.report.web.app import create_app  # noqa: E402

ARTIFACTS = (
    "report",
    "manifest",
    "candidates",
    "deg",
    "config",
    "taxonomy",
    "coverage",
    "fit_diagnostics",
)
_SOURCE_FILES = (
    "scripts/verify_local_workflow.py",
    "pyproject.toml",
    "bindsight/config.py",
    "bindsight/deg/cache.py",
    "bindsight/deg/pydeseq2_runner.py",
    "bindsight/deg/inference.py",
    "bindsight/deg/diagnostics.py",
    "bindsight/pipelines/discover.py",
    "bindsight/targets/open_targets.py",
    "bindsight/targets/gtex.py",
    "bindsight/structures/topology.py",
    "bindsight/structures/alphafolddb.py",
    "bindsight/report/coverage.py",
    "bindsight/report/fit_diagnostics.py",
    "bindsight/report/html.py",
    "bindsight/report/templates/report.html.j2",
    "bindsight/report/web/app.py",
    "bindsight/report/web/workbench_routes.py",
    "bindsight/report/web/workspace.py",
    "bindsight/report/web/resources.py",
    "bindsight/report/web/gpu.py",
    "bindsight/report/web/worker.py",
)


def digest(path: Path) -> str:
    """Hash the supplied bytes without including their host path."""
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def versions() -> dict[str, str | None]:
    """Record installed scientific and local-server distributions."""
    result: dict[str, str | None] = {}
    for name in sorted(set(SCIENTIFIC_STACK) | {"bindsight", "fastapi", "starlette", "httpx2"}):
        try:
            result[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            result[name] = None
    return result


def source_hashes() -> dict[str, str]:
    """Identify the actual reviewed source bytes, including uncommitted repairs."""
    return {name: digest(ROOT / name) for name in _SOURCE_FILES}


def _json(response: Any) -> dict[str, Any]:
    response.raise_for_status()
    body = response.json()
    if not isinstance(body, dict):
        raise ValueError("An API response was not a JSON object")
    return body


def exercise(args: argparse.Namespace, record: dict[str, Any]) -> None:
    """Use the real application lifespan and subprocess worker, with bounded polling."""
    started = time.monotonic()
    deadline = started + args.timeout_seconds
    identity: str | None = None
    launched = False
    succeeded = False
    with TestClient(create_app(run_root=args.out)) as client:
        response = client.get("/workbench")
        response.raise_for_status()
        match = re.search(r'data-session-token="([^"]+)"', response.text)
        if match is None:
            raise ValueError("The workbench did not provide its local session token")
        headers = {"X-Bindsight-Token": match.group(1)}
        try:
            identity = str(_json(client.post("/api/workbench/uploads", headers=headers))["id"])
            for kind, path in (("counts", args.counts), ("design", args.design)):
                suffix = ".tsv.gz" if path.suffix.lower() == ".gz" else ".tsv"
                response = client.put(
                    f"/api/workbench/uploads/{identity}/{kind}",
                    headers={
                        **headers,
                        "X-Filename": kind + suffix,
                        "Content-Type": "application/octet-stream",
                    },
                    content=path.read_bytes(),
                )
                response.raise_for_status()
            checked = _json(
                client.post(f"/api/workbench/uploads/{identity}/inspect", headers=headers)
            )
            record["input_check"] = {key: checked[key] for key in ("genes", "samples")}
            print("Complete input inspection passed.", flush=True)
            if time.monotonic() >= deadline:
                raise TimeoutError("Input inspection exceeded the verification deadline")
            launched = True
            _json(
                client.post(
                    f"/api/workbench/jobs/{identity}",
                    headers=headers,
                    json={
                        "name": "Real local workflow execution verification",
                        **record["comparison"],
                    },
                )
            )
            previous = None
            while True:
                if time.monotonic() >= deadline:
                    raise TimeoutError("The scientific job exceeded the verification deadline")
                state = _json(client.get(f"/api/workbench/jobs/{identity}"))
                status = state["state"]
                if status != previous:
                    record["states"].append(
                        {"state": status, "elapsed_seconds": round(time.monotonic() - started, 3)}
                    )
                    print("Analysis state: " + str(status), flush=True)
                    previous = status
                if status not in {"queued", "running", "cancelling"}:
                    break
                time.sleep(min(2.0, max(0.0, deadline - time.monotonic())))
            record["final_state"] = status
            if status not in {"completed", "incomplete_annotation"}:
                raise RuntimeError("The real scientific process did not complete")
            target_list = _json(client.get(f"/api/workbench/jobs/{identity}/targets"))
            eligible_targets = [target for target in target_list["targets"] if target["eligible"]]
            record["design_handoff"] = {
                "recorded_targets": len(target_list["targets"]),
                "eligible_targets": len(eligible_targets),
                "scope": "Read-only target selection and provenance check; GPU design was not run.",
            }
            record["resource_admission"] = state.get("resource_admission")

            payloads: dict[str, bytes] = {}
            for kind in ARTIFACTS:
                if time.monotonic() >= deadline:
                    raise TimeoutError("Artifact verification exceeded the deadline")
                artifact = client.get(f"/api/workbench/jobs/{identity}/artifact/{kind}")
                artifact.raise_for_status()
                if not artifact.content:
                    raise ValueError("A required downloadable artifact was empty")
                payloads[kind] = artifact.content
                record["artifacts"][kind] = {
                    "http_status": artifact.status_code,
                    "bytes": len(artifact.content),
                    "sha256": hashlib.sha256(artifact.content).hexdigest(),
                }
            manifest = json.loads(payloads["manifest"])
            record["stages"] = [
                {
                    "name": stage["name"],
                    "status": stage["status"],
                    "tool": stage["tool"]["name"],
                    "version": stage["tool"]["version"],
                }
                for stage in manifest["stages"]
            ]
            record["coverage"] = json.loads(payloads["coverage"])
            record["numerical_fit"] = state.get("numerical_fit")
            fit = json.loads(payloads["fit_diagnostics"])
            config = yaml.safe_load(payloads["config"])
            record["effective_deg_parameters"] = config["params"]["deg"]
            report = payloads["report"].decode("utf-8")
            numerical_fit = state.get("numerical_fit") or {}
            completed = {
                stage["name"]
                for stage in record["stages"]
                if stage["status"] in {"completed", "skipped_cache"}
            }
            output_hashes = {
                output["role"]: output["sha256"]
                for stage in manifest["stages"]
                for output in stage["outputs"]
            }
            recorded_roles = {
                "report": "report_html",
                "deg": "deg_table",
                "candidates": "candidates",
                "taxonomy": "failure_taxonomy",
                "coverage": "annotation_coverage",
                "fit_diagnostics": "deg_fit_diagnostics",
            }
            record["checks"] = {
                "required_stages_completed": {"deg", "discover", "report"}.issubset(completed),
                "no_failed_stages": all(
                    stage["status"] not in {"running", "failed"} for stage in record["stages"]
                ),
                "all_eight_downloads_nonempty": len(payloads) == len(ARTIFACTS),
                "download_hashes_match_manifest": all(
                    output_hashes.get(role) == record["artifacts"][kind]["sha256"]
                    for kind, role in recorded_roles.items()
                ),
                "fit_record_matches_deg_table": fit.get("deg_table_sha256")
                == record["artifacts"]["deg"]["sha256"],
                "fit_summary_available": numerical_fit.get("available") is True,
                "report_contains_recorded_fit_warnings": "Numerical fit diagnostics" in report
                and all(
                    html.escape(message) in report for message in numerical_fit.get("warnings", [])
                ),
                "annotation_state_matches_coverage": (status == "incomplete_annotation")
                == bool(record["coverage"].get("unassessed_lookups")),
                "source_unchanged_during_execution": source_hashes() == record["source_sha256"],
                "eligible_targets_have_recorded_hashes": all(
                    re.fullmatch(r"[a-f0-9]{64}", target["structure_sha256"] or "") is not None
                    for target in eligible_targets
                ),
            }
            if not all(record["checks"].values()):
                raise RuntimeError("One or more workflow verification checks failed")
            record["passed"] = True
            succeeded = True
            print("All eight artifact downloads and provenance checks passed.", flush=True)
        finally:
            if not succeeded and launched and identity:
                try:
                    cancelled = client.post(
                        f"/api/workbench/jobs/{identity}/cancel", headers=headers
                    )
                    record["owned_job_cancellation_requested"] = cancelled.is_success
                except Exception:
                    record["owned_job_cancellation_requested"] = False
            # TestClient's lifespan closes the exclusively owned Workspace and
            # reaps its own subprocess even if cancellation or a request fails.


def main() -> int:
    """Refuse existing destinations and write only a sanitized portable summary."""
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("counts", "design", "out", "record"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--paired-by", default="case_barcode")
    parser.add_argument("--factor", default="condition")
    parser.add_argument("--numerator", default="tumor")
    parser.add_argument("--denominator", default="normal")
    parser.add_argument("--timeout-seconds", type=float, default=1800)
    args = parser.parse_args()
    if not math.isfinite(args.timeout_seconds) or not 0 < args.timeout_seconds <= 7200:
        parser.error("--timeout-seconds must be finite, positive, and at most 7200")
    if not args.counts.is_file() or not args.design.is_file():
        parser.error("Both supplied input files must exist")
    if args.out.exists() or args.record.exists():
        parser.error("The output directory and record must both be new; refusing to overwrite")
    args.out = args.out.resolve()
    args.out.mkdir(parents=True, exist_ok=False)
    args.record.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    record: dict[str, Any] = {
        "schema": "bindsight-local-workflow-verification/1",
        "scope": "Real local API and CPU workflow execution; not biological or experimental validation.",
        "passed": False,
        "started_at": datetime.now(UTC).isoformat(),
        "inputs": {
            kind: {"bytes": path.stat().st_size, "sha256": digest(path)}
            for kind, path in (("counts", args.counts), ("design", args.design))
        },
        "comparison": {
            "factor": args.factor,
            "numerator": args.numerator,
            "denominator": args.denominator,
            "paired_by": args.paired_by,
            "fdr": 0.05,
            "log2fc": 1.0,
        },
        "python": platform.python_version(),
        "platform": {"system": platform.system(), "machine": platform.machine()},
        "libraries": versions(),
        "numeric_thread_environment": {
            name: os.environ.get(name)
            for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")
        },
        "git_revision": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, timeout=10
        ).strip(),
        "git_working_tree_dirty": subprocess.run(
            ["git", "diff", "--quiet", "HEAD"], cwd=ROOT, check=False, timeout=10
        ).returncode
        != 0,
        "source_sha256": source_hashes(),
        "states": [],
        "artifacts": {},
    }
    # Exclusive creation is checked again here to avoid an overwrite race.
    with args.record.open("x", encoding="utf-8", newline="\n") as stream:
        try:
            exercise(args, record)
        except Exception as exc:
            # Exception strings and worker logs can contain host paths. Keep
            # the portable record limited to the error's type and known checks.
            record["failure_type"] = type(exc).__name__
            print(
                "Verification failed: " + type(exc).__name__ + ". Inspect the local output logs.",
                flush=True,
            )
        finally:
            record["finished_at"] = datetime.now(UTC).isoformat()
            record["elapsed_seconds"] = round(time.monotonic() - started, 3)
            json.dump(record, stream, indent=2, allow_nan=False)
            stream.write("\n")
    print("PASS" if record["passed"] else "FAIL", flush=True)
    return 0 if record["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

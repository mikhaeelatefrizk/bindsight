# SPDX-License-Identifier: AGPL-3.0-or-later
"""HTTP routes for the local workbench; no public-site upload service."""

from __future__ import annotations

import hashlib
import json
import secrets
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from bindsight.report.fit_diagnostics import fit_summary
from bindsight.report.web.evidence import evidence_bundle
from bindsight.report.web.workspace import (
    MAX_UPLOAD,
    Workspace,
    WorkspaceInUseError,
    hardware,
    inspect_inputs,
)

ARTIFACTS = {
    "report": "report.html",
    "manifest": "run_manifest.jsonld",
    "candidates": "targets/candidates.parquet",
    "deg": "deg/results.parquet",
    "config": "config.yaml",
    "taxonomy": "taxonomy/failure_taxonomy.parquet",
    "coverage": "annotation_coverage.json",
    "fit_diagnostics": "deg/fit_diagnostics.json",
    "ranking": "rank/ranking.parquet",
    "validated": "validate/validated.parquet",
    "design_archive": "design/results.tar.gz",
    "gpu_environment": "gpu_environment.json",
    "gpu_setup_receipt": "gpu_setup_receipt.json",
    "source_manifest": "source_discovery_manifest.jsonld",
}


def register(app: FastAPI, templates: Jinja2Templates, root: Path) -> None:
    """Register token-protected state changes against a loopback-only workspace."""
    workspace: Workspace | None = None
    workspace_lock = threading.Lock()

    def get_workspace() -> Workspace:
        nonlocal workspace
        with workspace_lock:
            if workspace is None:
                workspace = Workspace(root)
        return workspace

    def job_run(state: dict[str, Any]) -> Path:
        run = Path(state["run_dir"]).resolve()
        if run.parent != get_workspace().root:
            raise ValueError("The recorded output directory is outside this workspace.")
        return run

    def available(state: dict[str, Any]) -> dict[str, Path]:
        run = job_run(state)
        return {
            kind: run / name
            for kind, name in ARTIFACTS.items()
            if (run / name).is_file()
            and not (run / name).is_symlink()
            and (run / name).resolve().is_relative_to(run)
        }

    async def settings(request: Request) -> dict[str, Any]:
        payload = bytearray()
        async for chunk in request.stream():
            payload.extend(chunk)
            if len(payload) > 16_384:
                raise ValueError("The analysis settings are too large.")
        body = json.loads(payload)
        if not isinstance(body, dict):
            raise ValueError("Analysis settings must be an object.")
        return body

    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        # Acquire ownership before accepting requests. A second launcher must
        # never serve a second executor against the same persisted job state.
        get_workspace()
        try:
            async with original_lifespan(application):
                yield
        finally:
            if workspace is not None:
                await run_in_threadpool(workspace.close)

    app.router.lifespan_context = lifespan

    @app.exception_handler(WorkspaceInUseError)
    async def workspace_in_use(request: Request, exc: WorkspaceInUseError) -> JSONResponse:
        return JSONResponse({"error": str(exc)}, status_code=409)

    @app.middleware("http")
    async def local_security(request: Request, call_next: Any) -> Any:
        if request.url.hostname not in {"127.0.0.1", "localhost", "::1", "testserver"}:
            return JSONResponse(
                {"error": "The workbench only accepts local hostnames."}, status_code=403
            )
        origin = request.headers.get("origin")
        if origin and origin.rstrip("/") != str(request.base_url).rstrip("/"):
            return JSONResponse(
                {"error": "Open the local application to access your analyses."}, status_code=403
            )
        if request.method not in {"GET", "HEAD", "OPTIONS"} and not secrets.compare_digest(
            request.headers.get("x-bindsight-token", ""), get_workspace().token
        ):
            return JSONResponse(
                {"error": "This session has expired. Reload the local application."},
                status_code=403,
            )
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        return response

    @app.get("/workbench", response_class=HTMLResponse)
    def workbench(request: Request) -> Any:
        return templates.TemplateResponse(
            request=request,
            name="workbench.html.j2",
            context={
                "assets": "/static/",
                "local": True,
                "session_token": get_workspace().token,
            },
        )

    @app.get("/api/workbench/evidence")
    def evidence() -> Any:
        return evidence_bundle()

    @app.get("/api/workbench/hardware")
    async def capabilities() -> Any:
        return await run_in_threadpool(hardware, get_workspace().storage)

    @app.get("/api/workbench/gpu/readiness")
    async def gpu_readiness() -> Any:
        from bindsight.report.web.gpu import readiness

        return await run_in_threadpool(readiness, get_workspace())

    @app.post("/api/workbench/gpu/setup")
    async def gpu_setup(request: Request) -> Any:
        from bindsight.report.web.gpu import start_setup

        try:
            return await run_in_threadpool(start_setup, get_workspace(), await settings(request))
        except (ValueError, OSError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    @app.get("/api/workbench/jobs/{identity}/targets")
    async def gpu_targets(identity: str) -> Any:
        from bindsight.report.web.gpu import targets

        try:
            return await run_in_threadpool(targets, get_workspace(), identity)
        except (ValueError, OSError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    @app.post("/api/workbench/jobs/{identity}/design")
    async def gpu_design(identity: str, request: Request) -> Any:
        from bindsight.report.web.gpu import start_design

        try:
            return await run_in_threadpool(
                start_design, get_workspace(), identity, await settings(request)
            )
        except (ValueError, OSError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    @app.post("/api/workbench/jobs/{identity}/resume")
    async def resume_gpu(identity: str) -> Any:
        from bindsight.report.web.gpu import resume

        try:
            return await run_in_threadpool(resume, get_workspace(), identity)
        except (ValueError, OSError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    @app.get("/api/workbench/sequence/{identity}")
    def sequence(identity: str) -> Any:
        from bindsight.report.showcase import load_designer_benchmark

        designer = load_designer_benchmark()
        if designer:
            for binder in designer.binders:
                if binder.binder_id == identity and binder.fasta and binder.fasta.is_file():
                    return FileResponse(
                        binder.fasta, filename=binder.fasta.name, media_type="text/plain"
                    )
        return JSONResponse({"error": "No recorded sequence for that design."}, status_code=404)

    @app.post("/api/workbench/uploads")
    def create_upload() -> Any:
        return {"id": get_workspace().create_upload()}

    @app.put("/api/workbench/uploads/{identity}/{kind}")
    async def upload(identity: str, kind: str, request: Request) -> Any:
        temporary = None
        owns_temporary = False
        try:
            folder = get_workspace().directory(identity)
            if kind not in {"counts", "design"} or (folder / "job.json").exists():
                raise ValueError("This upload is not available.")
            filename = request.headers.get("x-filename", "")
            compressed = filename.lower().endswith(".gz")
            suffix = ".tsv.gz" if compressed else ".tsv"
            target = folder / (kind + suffix)
            other = folder / (kind + (".tsv" if compressed else ".tsv.gz"))
            if target.exists() or other.exists():
                raise ValueError("That input is already saved. Start a new analysis to replace it.")
            total = 0
            temporary = folder / (kind + ".uploading")
            with temporary.open("xb") as stream:
                owns_temporary = True
                async for block in request.stream():
                    total += len(block)
                    if total > MAX_UPLOAD:
                        raise ValueError(
                            "Each input file is limited to 512 MB for this local workflow."
                        )
                    stream.write(block)
            if total == 0:
                raise ValueError("The selected file is empty.")
            temporary.replace(target)
            return {"saved": kind, "bytes": total}
        except (ValueError, OSError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        finally:
            if owns_temporary and temporary and temporary.is_file():
                temporary.unlink()

    @app.post("/api/workbench/uploads/{identity}/inspect")
    async def inspect(identity: str) -> Any:
        try:
            checked = await run_in_threadpool(inspect_inputs, *get_workspace().inputs(identity))
            checked.pop("records", None)
            return checked
        except (ValueError, OSError, UnicodeError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    @app.post("/api/workbench/jobs/{identity}")
    async def start(identity: str, request: Request) -> Any:
        try:
            if int(request.headers.get("content-length", "0")) > 16_384:
                raise ValueError("The analysis settings are too large.")
            payload = bytearray()
            async for chunk in request.stream():
                if len(payload) + len(chunk) > 16_384:
                    raise ValueError("The analysis settings are too large.")
                payload.extend(chunk)
            options = json.loads(payload)
            if not isinstance(options, dict):
                raise ValueError("Analysis settings must be an object.")
            return await run_in_threadpool(get_workspace().launch, identity, options)
        except (ValueError, OSError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    @app.get("/api/workbench/jobs")
    def jobs() -> Any:
        jobs = get_workspace().list()
        for state in jobs:
            try:
                state["available_artifacts"] = list(available(state))
            except (ValueError, OSError):
                state["available_artifacts"] = []
        return {"jobs": jobs}

    @app.get("/api/workbench/jobs/{identity}")
    def status(identity: str) -> Any:
        try:
            state = get_workspace().read(identity)
            state["available_artifacts"] = list(available(state))
            if (
                state.get("state") in {"completed", "incomplete_annotation"}
                and state.get("kind") != "gpu_setup"
            ):
                run = job_run(state)
                state["numerical_fit"] = fit_summary(run)
            progress = get_workspace().directory(identity) / "progress.json"
            if progress.is_file():
                state["progress"] = json.loads(progress.read_text(encoding="utf-8"))
            log = get_workspace().directory(identity) / "analysis.log"
            if log.is_file():
                with log.open("rb") as stream:
                    stream.seek(max(0, log.stat().st_size - 20_000))
                    state["log"] = stream.read().decode("utf-8", errors="replace")
            else:
                state["log"] = "Waiting for the local analysis worker."
            return state
        except (ValueError, OSError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)

    @app.post("/api/workbench/jobs/{identity}/cancel")
    def cancel(identity: str) -> Any:
        try:
            return get_workspace().cancel(identity)
        except (ValueError, OSError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    @app.get("/api/workbench/jobs/{identity}/artifact/{kind}")
    def artifact(identity: str, kind: str) -> Any:
        try:
            state = get_workspace().read(identity)
            path = available(state).get(kind)
            if path is None or not path.is_file():
                raise ValueError("This artifact is not available for this analysis.")
            if kind == "report":
                # Reports contain embedded, locally generated plots and structures.
                return FileResponse(
                    path,
                    media_type="text/html",
                    headers={
                        "Content-Security-Policy": "sandbox allow-scripts; default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; font-src data:; connect-src 'none'",
                    },
                )
            return FileResponse(path, filename=path.name)
        except (ValueError, OSError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)

    def structures_for(identity: str) -> dict[str, Path]:
        state = get_workspace().read(identity)
        if state.get("kind") != "gpu_design" or state["state"] not in {
            "completed",
            "incomplete_annotation",
        }:
            return {}
        run = job_run(state)
        result = {}
        for path in (run / "validate").rglob("*"):
            if (
                path.suffix.lower() in {".pdb", ".cif"}
                and path.is_file()
                and not path.is_symlink()
                and path.resolve().is_relative_to(run)
            ):
                key = hashlib.sha256(path.relative_to(run).as_posix().encode()).hexdigest()[:20]
                result[key] = path
        return result

    @app.get("/api/workbench/jobs/{identity}/structures")
    def job_structures(identity: str) -> Any:
        from bindsight.provenance.manifest import sha256_file

        try:
            return {
                "structures": [
                    {
                        "id": key,
                        "filename": path.name,
                        "format": path.suffix.lstrip(".").lower(),
                        "sha256": sha256_file(path),
                        "url": f"/api/workbench/jobs/{identity}/structures/{key}",
                    }
                    for key, path in structures_for(identity).items()
                ],
                "note": "Original computational prediction files; binding is not experimentally established.",
            }
        except (ValueError, OSError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)

    @app.get("/api/workbench/jobs/{identity}/structures/{key}")
    def job_structure(identity: str, key: str) -> Any:
        try:
            path = structures_for(identity).get(key)
            if path is None:
                raise ValueError("No recorded structure has that identifier.")
            return FileResponse(path, filename=path.name, media_type="text/plain")
        except (ValueError, OSError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)

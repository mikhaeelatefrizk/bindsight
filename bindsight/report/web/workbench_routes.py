# SPDX-License-Identifier: AGPL-3.0-or-later
"""HTTP routes for the local workbench; no public-site upload service."""

from __future__ import annotations

import secrets
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from bindsight.report.web.evidence import evidence_bundle
from bindsight.report.web.workspace import MAX_UPLOAD, Workspace, hardware, inspect_inputs


def register(app: FastAPI, templates: Jinja2Templates, root: Path) -> None:
    """Register token-protected state changes against a loopback-only workspace."""
    workspace: Workspace | None = None

    def get_workspace() -> Workspace:
        nonlocal workspace
        if workspace is None:
            workspace = Workspace(root)
        return workspace

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
    def capabilities() -> Any:
        return hardware(get_workspace().storage)

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
            options = await request.json()
            if not isinstance(options, dict):
                raise ValueError("Analysis settings must be an object.")
            return await run_in_threadpool(get_workspace().launch, identity, options)
        except (ValueError, OSError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    @app.get("/api/workbench/jobs")
    def jobs() -> Any:
        return {"jobs": get_workspace().list()}

    @app.get("/api/workbench/jobs/{identity}")
    def status(identity: str) -> Any:
        try:
            state = get_workspace().read(identity)
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
            run = Path(state["run_dir"]).resolve()
            if run.parent != get_workspace().root:
                raise ValueError("The recorded output directory is outside this workspace.")
            paths = {
                "report": run / "report.html",
                "manifest": run / "run_manifest.jsonld",
                "candidates": run / "targets/candidates.parquet",
                "deg": run / "deg/results.parquet",
                "config": run / "config.yaml",
                "taxonomy": run / "taxonomy/failure_taxonomy.parquet",
                "coverage": run / "annotation_coverage.json",
            }
            path = paths.get(kind)
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

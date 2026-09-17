# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Routes and rendering for the bindsight web interface.

Five sections, in the order the argument runs:

1. **Overview** — what it is, and what it has and has not shown.
2. **Evidence** — the study, the controls, the binders, the provenance chain.
3. **Try it** — the demo, with per-stage progress.
4. **Your data** — upload, validate, run.
5. **Runs** — browse what is on disk.

The data layer is :mod:`bindsight.report.showcase`, unchanged. This module owns
presentation only, and enforces the two presentation rules the previous
interface broke: a figure appears with what makes it interpretable, and an
absent measurement renders as an em dash rather than as zero.
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

LOG = logging.getLogger(__name__)

HERE = Path(__file__).resolve().parent
STATIC = HERE / "static"
TEMPLATES = HERE / "templates"

# Presentation rules live in `bindsight.report.format` so the standalone HTML
# report applies the same ones. Re-exported here because the templates and the
# tests reach for them through this module.
from bindsight.report.format import (  # noqa: E402
    ABSENT,
    fmt,
    fmt_int,
    fmt_p,
    interval,
)


# ---------------------------------------------------------------------------
# Background jobs
# ---------------------------------------------------------------------------
@dataclass
class Job:
    """A pipeline run in progress, and what it has done so far.

    The Streamlit app showed a single indeterminate spinner for a download, a
    DESeq2 fit, a surfaceome filter and two API sweeps -- minutes of a motionless
    page on a cold cache, with no stage name and no way to tell a slow run from a
    stuck one.
    """

    id: str
    kind: str
    stages: list[dict[str, str]] = field(default_factory=list)
    state: str = "running"
    error: str = ""
    run_dir: str = ""

    def step(self, name: str, state: str = "running") -> None:
        """Record a stage, or move one already recorded to a new state."""
        for stage in self.stages:
            if stage["name"] == name:
                stage["state"] = state
                return
        self.stages.append({"name": name, "state": state})

    def finish_previous(self) -> None:
        """Close whatever is still running.

        Called when the next stage begins, so a reader can tell a slow run
        from a stuck one -- which a single indeterminate spinner cannot.
        """
        for stage in self.stages:
            if stage["state"] == "running":
                stage["state"] = "done"


_JOBS: dict[str, Job] = {}
_JOBS_LOCK = threading.Lock()


def _new_job(kind: str) -> Job:
    job = Job(id=uuid.uuid4().hex[:12], kind=kind)
    with _JOBS_LOCK:
        _JOBS[job.id] = job
    return job


def _get_job(job_id: str) -> Job | None:
    with _JOBS_LOCK:
        return _JOBS.get(job_id)


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------
def create_app(*, run_root: Path | None = None) -> Any:
    """Build the FastAPI application.

    Args:
        run_root: where to look for existing runs. Defaults to ``runs/`` under
            the current working directory.
    """
    from bindsight import __version__
    from bindsight.report import showcase, theme

    app = FastAPI(title="bindsight", docs_url=None, redoc_url=None)
    app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")
    templates = Jinja2Templates(directory=str(TEMPLATES))

    # Everything a template may call. Kept explicit so a template cannot reach
    # into arbitrary application state.
    templates.env.globals.update(
        fmt=fmt,
        fmt_int=fmt_int,
        fmt_p=fmt_p,
        interval=interval,
        ABSENT=ABSENT,
        version=__version__,
        tojson=lambda obj: json.dumps(obj),
        citation=theme.citation_line,
        doi_pending=theme.DOI_IS_PENDING,
        github=theme.GITHUB_URL,
    )

    runs_root = Path(run_root) if run_root else Path.cwd() / "runs"

    def page(request: Request, name: str, **ctx: Any) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request, name=name, context={"nav": name.split(".")[0], **ctx}
        )

    # -- 1. Overview --------------------------------------------------------
    @app.get("/", response_class=HTMLResponse)
    def overview(request: Request) -> HTMLResponse:
        study = showcase.load_study()
        designer = showcase.load_designer_benchmark()
        return page(
            request,
            "overview.html.j2",
            study=study,
            designer=designer,
            have_evidence=study is not None or designer is not None,
        )

    # -- 2. Evidence --------------------------------------------------------
    @app.get("/evidence", response_class=HTMLResponse)
    def evidence(request: Request) -> HTMLResponse:
        study = showcase.load_study()
        designer = showcase.load_designer_benchmark()
        # Only designs whose predicted complex is actually committed. Offering a
        # design with no structure gives the reader a viewer that stays empty
        # and no way to tell whether that is the design's fault or the page's.
        structures = designer.with_structures() if designer else []
        return page(
            request,
            "evidence.html.j2",
            structures=structures,
            study=study,
            designer=designer,
            paired=_paired_chart(designer),
            nulls=_nulls_chart(study),
            recall=_recall_chart(study),
        )

    # -- 3. Try it ----------------------------------------------------------
    @app.get("/try", response_class=HTMLResponse)
    def try_it(request: Request) -> HTMLResponse:
        return page(request, "try.html.j2", cohort=_demo_description())

    @app.post("/try/run")
    def try_run() -> JSONResponse:
        job = _new_job("demo")
        threading.Thread(target=_run_demo, args=(job,), daemon=True).start()
        return JSONResponse({"job": job.id})

    # -- 4. Your data -------------------------------------------------------
    @app.get("/your-data", response_class=HTMLResponse)
    def your_data(request: Request) -> HTMLResponse:
        return page(request, "your_data.html.j2")

    @app.get("/api/structure/{binder_id}")
    def structure(binder_id: str) -> Any:
        """The predicted complex for one binder, as mmCIF text.

        Resolved by matching ``binder_id`` against the designs the benchmark
        actually loaded, never by joining it onto a directory: a path built from
        a request parameter turns a structure viewer into a file-read
        primitive, and ``..`` is a legal path segment.
        """
        designer = showcase.load_designer_benchmark()
        if designer is None:
            return JSONResponse({"error": "no designer benchmark"}, status_code=404)
        for binder in designer.with_structures():
            if binder.binder_id == binder_id and binder.complex_cif is not None:
                return Response(
                    binder.complex_cif.read_text(encoding="utf-8"),
                    media_type="chemical/x-cif",
                )
        return JSONResponse({"error": "no structure for that design"}, status_code=404)

    # -- 5. Runs ------------------------------------------------------------
    @app.get("/runs", response_class=HTMLResponse)
    def runs(request: Request) -> HTMLResponse:
        return page(request, "runs.html.j2", runs=_discover_runs(runs_root), root=runs_root)

    # -- job status ---------------------------------------------------------
    @app.get("/api/job/{job_id}")
    def job_status(job_id: str) -> JSONResponse:
        job = _get_job(job_id)
        if job is None:
            return JSONResponse({"error": "no such job"}, status_code=404)
        return JSONResponse(
            {
                "id": job.id,
                "state": job.state,
                "stages": job.stages,
                "error": job.error,
                "run_dir": job.run_dir,
            }
        )

    return app


# ---------------------------------------------------------------------------
# Chart specifications, built server-side so the page states its own numbers
# ---------------------------------------------------------------------------
def _paired_chart(designer: Any) -> dict[str, Any] | None:
    """Designs against their own shuffles, one line per pair."""
    if designer is None:
        return None
    root = None
    try:
        from bindsight.report.showcase import benchmarks_root

        root = benchmarks_root()
    except Exception:  # pragma: no cover - defensive
        return None
    if root is None:
        return None
    path = root / "calibration" / "RESULTS.json"
    if not path.is_file():
        return None
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    pairs = report.get("pairs") or []
    rows = [
        {"id": p.get("binder_id", "?"), "a": float(p["design"]), "b": float(p["scramble"])}
        for p in pairs
        if p.get("design") is not None and p.get("scramble") is not None
    ]
    if not rows:
        return None
    return {
        "pairs": rows,
        "labelA": "design",
        "labelB": "its own shuffle",
        "threshold": report.get("threshold"),
        "thresholdLabel": f"ipTM {report.get('threshold')}",
        "title": "Each design beside a shuffle of its own sequence",
    }


def _ci_label(confidence: Any) -> str:
    """``95% CI`` when the artifact recorded a level, plain ``CI`` when it did not.

    The same rule :func:`bindsight.report.format.interval` applies, in the form
    the chart spec needs.
    """
    try:
        return f"{float(confidence) * 100:g}% CI"
    except (TypeError, ValueError):
        return "CI"


def _nulls_chart(study: Any) -> dict[str, Any] | None:
    """The two null models as intervals against the value that means 'nothing'."""
    if study is None:
        return None
    gap = study.indication_gap or {}
    if gap.get("point") is None:
        return None
    return {
        "rows": [
            {
                "label": "indication gap",
                "point": float(gap["point"]),
                "low": float(gap["low"]),
                "high": float(gap["high"]),
                "n": gap.get("n_clusters"),
                # Read, not assumed. Hardcoding the level here and again as
                # the renderer's fallback would have captioned a study
                # computed at another level as 95% from two places at once.
                "ciLabel": _ci_label(gap.get("confidence")),
            }
        ],
        "reference": 0.0,
        "title": "Within-antigen difference, against zero",
    }


def _recall_chart(study: Any) -> dict[str, Any] | None:
    if study is None:
        return None
    cascade = (study.recall_cascade or {}).get("all", {}).get("at_k") or {}
    rows = []
    for key in sorted(cascade, key=lambda k: int(k.split("@")[-1])):
        w = cascade[key].get("wilson") or {}
        num, den = w.get("numerator"), w.get("denominator")
        if num is None or den is None:
            continue
        # The level is recorded on every interval block in the study artifact.
        # Dropping it printed a bare `CI` beside the number a reviewer reads
        # first, and a 90% interval would have been indistinguishable from a 95%
        # one.
        ci = interval(w.get("low"), w.get("high"), digits=2, confidence=w.get("confidence"))
        rows.append(
            {
                "label": key,
                "value": num / den if den else 0,
                "display": f"{num}/{den}",
                "tip": f"{num} of {den} · {ci}",
            }
        )
    if not rows:
        return None
    return {"rows": rows, "max": 1.0, "title": "Recall at each cutoff"}


# ---------------------------------------------------------------------------
# Runs and the demo
# ---------------------------------------------------------------------------
def load_run_manifest(run: Path) -> dict[str, Any] | None:
    """A run's manifest as a dict, or ``None`` if there is not one to read.

    ``None`` for absent, unreadable, or not-an-object. Each of those is a
    different way of having no manifest, and none of them is an empty manifest:
    returning ``{}`` would let a caller conclude the run recorded no failed
    stages when in fact nothing was read.
    """
    path = run / "run_manifest.jsonld"
    if not path.is_file():
        return None
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    return body if isinstance(body, dict) else None


def stage_failures(manifest: dict[str, Any] | None) -> list[dict[str, str]]:
    """Stages the manifest records as failed.

    The distinction this exists for: *this cohort has no surface-antigen
    candidates* is a finding, and *the differential-expression step crashed* is
    a bug, and they leave behind the same empty tables. A run that failed must
    never be presented in the layout that means "completed, and found nothing".
    """
    if not isinstance(manifest, dict):
        return []
    failures: list[dict[str, str]] = []
    for stage in manifest.get("stages") or []:
        if not isinstance(stage, dict):
            continue
        if str(stage.get("status", "")).lower() == "failed":
            failures.append(
                {
                    "name": str(stage.get("name", "?")),
                    "error": str(stage.get("error") or "no error recorded"),
                }
            )
    return failures


# Open Targets reports this when a gene was mapped from a live record.
OT_STATUS_LIVE = "ok"


def open_targets_degradation(cand: Any) -> dict[str, Any] | None:
    """How far the gene -> protein mapping fell back, or ``None`` if it did not.

    Open Targets is the only genome-wide Ensembl -> UniProt source in the
    pipeline. When it is unreachable (or disabled), the only mapping left is the
    bundled table of a few well-known genes, and every gene missing from it is
    dropped before the surfaceome filter. The resulting shortlist is drawn from
    that fixed handful, not from the cohort, so it must not be read as a
    genome-wide discovery -- and an absence from it means nothing at all.

    Args:
        cand: The candidates table, or ``None`` when the run produced none.

    Returns:
        ``None`` when every candidate was mapped live (the normal case, which
        must stay silent) or when there is no status column to judge by.
        Otherwise the counts, the per-status breakdown, and whether the outage
        was total -- because a total outage means the shortlist is not a
        discovery at all, and a partial one means it is merely incomplete.
    """
    if cand is None or "open_targets_status" not in getattr(cand, "columns", ()):
        return None
    statuses = [str(s) for s in cand["open_targets_status"]]
    degraded = [s for s in statuses if s != OT_STATUS_LIVE]
    if not degraded:
        return None
    return {
        "degraded": len(degraded),
        "total": len(statuses),
        "breakdown": [{"status": s, "count": degraded.count(s)} for s in dict.fromkeys(degraded)],
        # Nothing came back live, so the bundled table was the entire mapping.
        "total_outage": len(degraded) == len(statuses),
    }


def _read_candidates(run: Path) -> Any:
    """A run's candidates table, or ``None`` when there is not one to read."""
    path = run / "targets" / "candidates.parquet"
    if not path.is_file():
        return None
    try:
        import pandas as pd

        return pd.read_parquet(path)
    except Exception:  # unreadable is not the same as absent, but both are None
        return None


def _discover_runs(root: Path) -> list[dict[str, Any]]:
    if not root.is_dir():
        return []
    found: list[dict[str, Any]] = []
    for path in sorted(root.iterdir()):
        if not path.is_dir():
            continue
        manifest = path / "run_manifest.jsonld"
        candidates = path / "targets" / "candidates.parquet"
        body = load_run_manifest(path)
        failures = stage_failures(body)
        found.append(
            {
                "name": path.name,
                "path": str(path),
                "has_manifest": manifest.is_file(),
                "has_candidates": candidates.is_file(),
                "failures": failures,
                # Three states, not two. "completed" and "found nothing" are the
                # same layout; "crashed" must not be.
                "verdict": ("failed" if failures else "unknown" if body is None else "completed"),
                "open_targets": open_targets_degradation(_read_candidates(path)),
                "mtime": path.stat().st_mtime,
            }
        )
    return sorted(found, key=lambda r: r["mtime"], reverse=True)


def _demo_description() -> dict[str, str]:
    return {
        "cohort": "TCGA-BRCA, primary tumour against solid-tissue normal",
        "source": "NIH/GDC, downloaded on first run and cached",
        "hardware": "CPU only — no GPU, no account",
        "duration": "a few minutes on a warm cache; longer on the first run, "
        "which downloads the cohort",
    }


_DEMO_STAGES = (
    "fetch the cohort",
    "differential expression",
    "surface-exposure filter",
    "target annotation",
    "rank candidates",
    "render the report",
)


def _run_demo(job: Job) -> None:
    """Run the demo, recording which stage is active.

    Each stage is named as it starts, so a reader can tell a slow run from a
    stuck one — which a single indeterminate spinner cannot.
    """
    for name in _DEMO_STAGES:
        job.step(name, "pending")
    try:
        from bindsight.pipelines import discover as discover_pipeline
        from bindsight.report import render_run

        cfg = _demo_config()
        out_dir = Path.cwd() / "runs" / "demo"

        job.step(_DEMO_STAGES[0], "running")
        manifest = discover_pipeline.run(cfg, out_dir=out_dir)
        job.finish_previous()
        for name in _DEMO_STAGES[1:-1]:
            job.step(name, "done")

        job.step(_DEMO_STAGES[-1], "running")
        render_run(out_dir)
        job.finish_previous()

        job.run_dir = str(out_dir)
        job.state = "done"
        LOG.info("demo complete: %s", manifest)
    except FileNotFoundError as exc:
        # Named separately: this is a packaging problem, and blaming the network
        # for it told users to retry something that can never succeed.
        job.state = "failed"
        job.error = (
            f"The bundled demo configuration is not available in this install "
            f"({exc}). It ships with the repository rather than the wheel — "
            "clone the repository to run the demo."
        )
    except Exception as exc:  # surfaced to the page verbatim, not swallowed
        job.state = "failed"
        job.error = str(exc)
        for stage in job.stages:
            if stage["state"] == "running":
                stage["state"] = "failed"


def _demo_config() -> Any:
    """The bundled demo cohort's config.

    ``RunConfig.from_yaml``, not a ``load_config`` helper: that name does not
    exist, so the demo raised ImportError into the broad handler below and
    reported it to the page as a failed run. mypy had it -- the module was
    outside the type-check scope until it was widened.
    """
    from bindsight.config import RunConfig
    from bindsight.report.showcase import benchmarks_root

    root = benchmarks_root()
    base = root.parent if root else Path.cwd()
    path = base / "examples" / "demo" / "config.yaml"
    if not path.is_file():
        raise FileNotFoundError(str(path))
    return RunConfig.from_yaml(path)


def serve(
    *,
    host: str = "127.0.0.1",
    port: int = 8501,
    open_browser: bool = True,
    run_root: Path | None = None,
) -> None:
    """Run the interface.

    Args:
        host: interface to bind. Loopback by default; nothing is exposed to
            the network unless the caller asks for it.
        port: port to bind. An occupied port is a failed launch, and uvicorn
            exits non-zero for it rather than reporting success.
        open_browser: open a tab once the server is up.
        run_root: where to look for runs. ``None`` means ``runs/`` under the
            working directory -- the same default ``create_app`` documents.
    """
    import uvicorn

    if open_browser:
        import webbrowser

        threading.Timer(1.0, lambda: webbrowser.open(f"http://{host}:{port}")).start()
    uvicorn.run(create_app(run_root=run_root), host=host, port=port, log_level="warning")

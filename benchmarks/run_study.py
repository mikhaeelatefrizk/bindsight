#!/usr/bin/env python
# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Run the rediscovery study, one TCGA cohort at a time.

    python benchmarks/run_study.py --list
    python benchmarks/run_study.py --project TCGA-ESCA
    python benchmarks/run_study.py --all --cpus 2
    python benchmarks/run_study.py --score-only

Staged by design. Each project is downloaded, run and scored independently, and
a cohort already on disk is reused, so a sweep can be stopped and resumed and a
failure costs one cohort rather than the study. The worker count is capped so a
multi-hour sweep does not make the machine it runs on unusable.

Scoring is separate from running: ``--score-only`` re-derives every number from
the run directories already present, which is how the reported statistics can be
changed and re-argued without re-running any differential expression.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:  # running from a checkout without an install
    sys.path.insert(0, str(REPO_ROOT))

from bindsight.benchmark import panel as P  # noqa: E402
from bindsight.benchmark import study as ST  # noqa: E402

LOG = logging.getLogger("bindsight.study")

DEFAULT_OUT = REPO_ROOT / "runs" / "study"
ARTIFACT_DIR = REPO_ROOT / "benchmarks" / "study"


def _surfaceome(*, extended: bool = True) -> frozenset[str]:
    """The accessions the pipeline filters on.

    This must match what discovery actually used. Scoring against SURFY alone
    while the pipeline ran against the extended reference would report antigens
    as unreachable that the run could see perfectly well — which is exactly what
    happened the first time the extension landed.
    """
    from bindsight.surfaceome import load_surfaceome

    return load_surfaceome(extended=extended)


def _list_projects() -> None:
    """Print the panel, so what will run is visible before anything runs."""
    scored = [c for c in P.PANEL if c.usable == "scored"]
    by_project: dict[str, list[str]] = {}
    for c in scored:
        by_project.setdefault(c.project, []).append(c.symbol)
    print(f"{len(scored)} scored antigen-cohort pairs across {len(by_project)} projects\n")
    for project in sorted(by_project):
        normals = P.PROJECT_NORMALS.get(project, 0)
        pairs = P.PROJECT_MATCHED_PAIRS.get(project, 0)
        print(
            f"  {project:12} {pairs:>3} matched pairs ({normals:>3} normals)  "
            f"{', '.join(sorted(by_project[project]))}"
        )
    print("\nnull-calibration projects (no antigen attached):")
    for project in P.NULL_CALIBRATION_PROJECTS:
        print(f"  {project:12} {P.PROJECT_MATCHED_PAIRS.get(project, 0):>3} matched pairs")
    print("\npublished but excluded from every denominator:")
    for c in P.EXCLUDED:
        print(f"  {c.project:12} {c.symbol:9} {c.usable}")


def run_project(project: str, config: ST.StudyConfig) -> dict[str, Any]:
    """Prepare, run and score one project. Returns a timing and status record."""
    started = time.monotonic()
    record: dict[str, Any] = {"project": project, "status": "ok"}
    try:
        provenance = ST.prepare_cohort(project, config)
        record["n_tumor"] = provenance.get("n_tumor")
        record["n_normal"] = provenance.get("n_normal")
        record["fetch_seconds"] = round(time.monotonic() - started, 1)

        deg_started = time.monotonic()
        run_dir = ST.run_cohort(project, config)
        record["run_seconds"] = round(time.monotonic() - deg_started, 1)
        record["run_dir"] = str(run_dir)
    except Exception as exc:  # one cohort failing must not end the sweep
        record["status"] = "failed"
        record["error"] = f"{type(exc).__name__}: {exc}"
        LOG.exception("%s failed", project)
    record["total_seconds"] = round(time.monotonic() - started, 1)
    return record


def score_all(config: ST.StudyConfig) -> dict[str, Any]:
    """Score every cohort already on disk and write the study summary."""
    surfaceome = _surfaceome()
    results: list[ST.CohortResult] = []
    missing: list[str] = []
    for project in P.projects_in_panel():
        run_dir = Path(config.out_dir) / project.removeprefix("TCGA-").lower()
        try:
            results.append(ST.score_cohort(project, run_dir, surfaceome=surfaceome))
        except FileNotFoundError:
            missing.append(project)
    if missing:
        # A cohort that has not run is not a cohort that found nothing, so it is
        # named rather than silently scored as a miss.
        LOG.warning("not yet run, so excluded from the summary: %s", ", ".join(missing))

    summary = ST.summarise(results, config)
    summary["cohorts_not_yet_run"] = missing
    summary["surfaceome_size"] = len(surfaceome)
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    (ARTIFACT_DIR / "results.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    LOG.info("wrote %s", ARTIFACT_DIR / "results.json")

    # The written page and its figures come from the same summary object, so a
    # figure can never disagree with the table beside it.
    from bindsight.benchmark.study_figures import render_figures
    from bindsight.benchmark.study_report import render_markdown

    (ARTIFACT_DIR / "RESULTS.md").write_text(render_markdown(summary), encoding="utf-8")
    figures = render_figures(summary, ARTIFACT_DIR / "figures")
    LOG.info("wrote RESULTS.md and %d figure(s)", len(figures))
    return summary


def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="print the panel and exit")
    parser.add_argument("--project", help="run one TCGA project, e.g. TCGA-ESCA")
    parser.add_argument("--all", action="store_true", help="run every project in the panel")
    parser.add_argument(
        "--score-only", action="store_true", help="re-score the runs already on disk"
    )
    parser.add_argument(
        "--cpus",
        type=int,
        default=2,
        help="worker cap for differential expression (default 2, to leave headroom)",
    )
    parser.add_argument(
        "--max-pairs",
        type=int,
        default=None,
        help="cap matched pairs per cohort (default: use every pair)",
    )
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="run directory root")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.list:
        _list_projects()
        return 0

    config = ST.StudyConfig(out_dir=args.out, n_cpus=args.cpus, max_pairs=args.max_pairs)

    if args.project:
        record = run_project(args.project, config)
        print(json.dumps(record, indent=2))
        if record["status"] != "ok":
            return 1
    elif args.all:
        records = []
        for project in P.projects_in_panel():
            LOG.info("=== %s ===", project)
            records.append(run_project(project, config))
        ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        (ARTIFACT_DIR / "run_log.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
        failed = [r["project"] for r in records if r["status"] != "ok"]
        if failed:
            LOG.warning("failed cohorts: %s", ", ".join(failed))
    elif not args.score_only:
        parser.error("choose one of --list, --project, --all or --score-only")

    summary = score_all(config)
    cascade = summary.get("recall_cascade", {})
    for name, block in cascade.items():
        wilson = block.get("wilson")
        if wilson:
            print(
                f"{name:12} {wilson['numerator']}/{wilson['denominator']} = "
                f"{wilson['point']:.3f} (95% CI {wilson['low']:.3f}-{wilson['high']:.3f})"
            )
        else:
            print(f"{name:12} {block.get('note', 'no data')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

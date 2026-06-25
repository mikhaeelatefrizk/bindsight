# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Full-pipeline orchestrator for ``bindsight run``.

Drives the complete chain: discover → design → validate → rank → report → export.

Each stage is opt-out via flags (e.g. skip GPU stages with ``--no-design``).
The orchestrator emits one combined manifest; failures in any stage are
recorded but downstream stages still attempt to run on whatever upstream
artifacts are available, so partial successes still produce a useful report.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from bindsight.config import RunConfig
from bindsight.pipelines import discover as discover_pipeline
from bindsight.provenance import Manifest

LOG = logging.getLogger(__name__)

# Backends that execute the design+validation job headlessly (vs. `colab`, which
# only generates a notebook the user runs by hand).
_HEADLESS_BACKENDS = {"mock", "local_docker", "modal", "kaggle"}


@dataclass
class FullRunResult:
    """Summary of a full ``bindsight run`` invocation."""

    manifest: Manifest
    discover_ok: bool
    design_ok: bool
    validate_ok: bool
    rank_ok: bool
    report_path: Path | None
    crate_path: Path | None


def run(
    config: RunConfig,
    *,
    out_dir: Path | None = None,
    skip_design: bool = False,
    skip_validate: bool = False,
    skip_rank: bool = False,
    skip_report: bool = False,
    skip_export: bool = False,
) -> FullRunResult:
    """Run the full pipeline.

    CPU-only stages always execute; GPU stages run only if the corresponding
    artifacts are already present (i.e. the user has run the GPU half on
    Colab/Modal and pulled results back).

    Returns a :class:`FullRunResult` describing what completed.
    """
    out = Path(out_dir) if out_dir else Path(config.out_dir)

    # ---- 1. Discover (CPU) ----
    LOG.info("== full run: discover ==")
    manifest = discover_pipeline.run(config, out_dir=out)
    discover_ok = all(s.status == "completed" for s in manifest.stages)

    # ---- 2. Design (GPU). Headless backends (mock/local_docker/modal/kaggle)
    #         launch the executor now; `colab` just generates notebooks, so we
    #         fall back to checking for an already-produced tarball. ----
    design_tarball = out / "design" / "results.tar.gz"
    if not skip_design and discover_ok and config.backend in _HEADLESS_BACKENDS:
        try:
            from bindsight.cli import _launch_design

            _launch_design(
                out,
                backend=config.backend,
                designer=config.params.design.designer,
                validator=config.params.validate_.validator,
                trajectories=config.params.design.n_trajectories,
            )
        except Exception as e:
            LOG.warning("design stage failed: %s", e)
    design_ok = design_tarball.exists() if not skip_design else False

    # ---- 3. Validate (GPU): materialise validated.parquet from design output. ----
    validated_path = out / "validate" / "validated.parquet"
    if design_ok and not skip_validate:
        try:
            from bindsight.cli import _finalize_validate

            _finalize_validate(out)
        except Exception as e:
            LOG.warning("validate stage failed: %s", e)
    validate_ok = (
        validated_path.exists() and validated_path.stat().st_size > 0
        if not skip_validate
        else False
    )

    # ---- 4. Rank (CPU; runs only if validate produced output) ----
    rank_ok = False
    if validate_ok and not skip_rank:
        try:
            from bindsight.rank import rank_run

            rank_run(out, weights=config.params.rank.weights)
            rank_ok = True
        except Exception as e:
            LOG.warning("rank stage failed: %s", e)

    # ---- 5. Report (CPU; works on whatever artifacts are present) ----
    report_path: Path | None = None
    if not skip_report:
        try:
            from bindsight.report import render_run

            report_path = render_run(out)
        except Exception as e:
            LOG.warning("report stage failed: %s", e)

    # ---- 6. Export (CPU; bundles everything) ----
    crate_path: Path | None = None
    if not skip_export:
        try:
            from bindsight.export import export_ro_crate

            crate_path = export_ro_crate(out)
        except Exception as e:
            LOG.warning("export stage failed: %s", e)

    return FullRunResult(
        manifest=manifest,
        discover_ok=discover_ok,
        design_ok=design_ok,
        validate_ok=validate_ok,
        rank_ok=rank_ok,
        report_path=report_path,
        crate_path=crate_path,
    )

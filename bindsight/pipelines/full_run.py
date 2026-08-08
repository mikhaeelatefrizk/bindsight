# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Full-pipeline orchestrator for ``bindsight run``.

Drives the complete chain: discover → design → validate → rank → report → export.

Each stage is opt-out via flags (e.g. skip GPU stages with ``--no-design``).
The orchestrator emits one combined manifest; failures in any stage are
recorded but downstream stages still attempt to run on whatever upstream
artifacts are available, so partial successes still produce a useful report.

Every stage — including the ones it delegates to ``bindsight.cli`` — appends a
:class:`~bindsight.provenance.StageRecord`, so the manifest of a full run
accounts for all seven stages: what ran, what was skipped and why, and the
digest of everything each stage consumed and produced.
"""

from __future__ import annotations

import logging
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bindsight import __version__
from bindsight.config import RunConfig
from bindsight.pipelines import discover as discover_pipeline
from bindsight.provenance import (
    ContainerRef,
    InputRef,
    Manifest,
    OutputRef,
    StageRecord,
    ToolRef,
)
from bindsight.provenance.fragments import artifact_ref

LOG = logging.getLogger(__name__)

# Backends that execute the design+validation job headlessly (vs. `colab`, which
# only generates a notebook the user runs by hand).
_HEADLESS_BACKENDS = {"mock", "local_docker", "modal", "kaggle"}

# Backends whose GPU half runs in a container the orchestrator cannot inspect
# from here (the image lives on Modal / Kaggle, not on this machine), so no
# digest can be recorded for them.
_REMOTE_CONTAINER_BACKENDS = {"modal", "kaggle"}

_REPO_URL = "https://github.com/mikhaeelatefrizk/bindsight"

# How long to wait on `docker image inspect` before giving up on a digest.
_DOCKER_INSPECT_TIMEOUT_S = 20


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


def _stage_tool(name: str) -> ToolRef:
    """Tool reference for a stage bindsight itself performs."""
    return ToolRef(
        name=name,
        version=__version__,
        license="AGPL-3.0-or-later",
        repo_url=_REPO_URL,
    )


def _inputs(root: Path, refs: Iterable[tuple[Path, str]]) -> list[InputRef]:
    """Digest every artifact that exists; the absent ones are simply not claimed."""
    out: list[InputRef] = []
    for path, role in refs:
        ref: dict[str, Any] | None = artifact_ref(path, role=role, run_root=root)
        if ref is not None:
            out.append(InputRef(**ref))
    return out


def _outputs(root: Path, refs: Iterable[tuple[Path, str]]) -> list[OutputRef]:
    """Digest every produced artifact that exists (see :func:`_inputs`)."""
    out: list[OutputRef] = []
    for path, role in refs:
        ref: dict[str, Any] | None = artifact_ref(path, role=role, run_root=root)
        if ref is not None:
            out.append(OutputRef(**ref))
    return out


def _container_ref(backend: str) -> ContainerRef | None:
    """Resolve the image digest of the container a backend runs the GPU half in.

    Returns ``None`` — and says why in the log — whenever the digest cannot be
    read: a backend that is not containerised, a local runner in native mode,
    no Docker on PATH, or an image that was built locally and never pushed (so
    it carries no repository digest). A manifest must not claim an image
    identity it could not verify, and a tag is not one.
    """
    if backend in _REMOTE_CONTAINER_BACKENDS:
        LOG.info("backend %s runs its container remotely; no local digest to record", backend)
        return None
    if backend != "local_docker":
        return None

    from bindsight.runners.local_docker import LocalDockerRunner

    runner = LocalDockerRunner()
    if runner.native:
        return None
    image = runner.image
    try:
        # Fixed argv (no shell); the image name comes from our own runner.
        proc = subprocess.run(
            ["docker", "image", "inspect", "--format", "{{index .RepoDigests 0}}", image],
            capture_output=True,
            text=True,
            timeout=_DOCKER_INSPECT_TIMEOUT_S,
            check=True,
        )
    except (OSError, subprocess.SubprocessError) as e:
        LOG.warning("could not read the image digest for %s (%s); not recording one", image, e)
        return None

    repo_digest = proc.stdout.strip()
    name, _, digest = repo_digest.partition("@")
    if not digest.startswith("sha256:"):
        LOG.warning("image %s has no repository digest (never pushed?); not recording one", image)
        return None
    _, _, tag = image.partition(":")
    return ContainerRef(image=name, tag=tag or None, digest=digest, runtime="docker")


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
    manifest_path = out / "run_manifest.jsonld"

    # ---- 1. Discover (CPU) ----
    LOG.info("== full run: discover ==")
    manifest = discover_pipeline.run(config, out_dir=out)
    discover_ok = all(s.status == "completed" for s in manifest.stages)

    candidates_path = out / "targets" / "candidates.parquet"
    epitopes_path = out / "epitopes" / "epitopes.parquet"

    # ---- 2. Design (GPU). Headless backends (mock/local_docker/modal/kaggle)
    #         launch the executor now; `colab` just generates notebooks, so we
    #         fall back to checking for an already-produced tarball. ----
    design_tarball = out / "design" / "results.tar.gz"
    design_stage = StageRecord(
        name="design",
        tool=_stage_tool(f"bindsight.design.{config.params.design.designer}"),
        container=_container_ref(config.backend),
        inputs=_inputs(out, [(epitopes_path, "epitopes"), (candidates_path, "candidates")]),
        params=config.params.design.model_dump() | {"backend": config.backend},
    )
    if skip_design:
        design_stage.mark_skipped("design skipped by request")
    elif not discover_ok:
        design_stage.mark_skipped("discovery did not complete; nothing to design against")
    elif config.backend not in _HEADLESS_BACKENDS:
        design_stage.mark_skipped(
            f"backend {config.backend!r} is not headless; run the GPU half by hand"
        )
    else:
        try:
            from bindsight.cli import _launch_design

            _launch_design(
                out,
                backend=config.backend,
                designer=config.params.design.designer,
                validator=config.params.validate_.validator,
                trajectories=config.params.design.n_trajectories,
                prescreen_top_k=config.params.design.prescreen_top_k,
            )
        except Exception as e:
            LOG.warning("design stage failed: %s", e)
            design_stage.mark_failed(repr(e))
    if design_stage.status == "running":
        if design_tarball.exists():
            design_stage.mark_completed(
                outputs=_outputs(
                    out,
                    [
                        (design_tarball, "design_results"),
                        (out / "design" / "metrics.jsonl", "metrics"),
                    ],
                )
            )
        else:
            design_stage.mark_failed("design produced no design/results.tar.gz")
    manifest.append(design_stage)
    manifest.write(manifest_path)
    design_ok = design_stage.status == "completed"

    # ---- 3. Validate (GPU): materialise validated.parquet from design output. ----
    validated_path = out / "validate" / "validated.parquet"
    validate_stage = StageRecord(
        name="validate",
        tool=_stage_tool(f"bindsight.validate.{config.params.validate_.validator}"),
        inputs=_inputs(out, [(design_tarball, "design_results")]),
        params=config.params.validate_.model_dump(),
    )
    if skip_validate:
        validate_stage.mark_skipped("validation skipped by request")
    else:
        if design_ok:
            try:
                from bindsight.cli import _finalize_validate

                _finalize_validate(out)
            except Exception as e:
                LOG.warning("validate stage failed: %s", e)
                validate_stage.mark_failed(repr(e))
        if validate_stage.status == "running":
            if validated_path.exists() and validated_path.stat().st_size > 0:
                if not design_ok:
                    # The GPU half can run elsewhere (Colab/Modal) with the
                    # results dropped back into the run directory; the digest
                    # still pins what was ranked, but this run did not make it.
                    validate_stage.notes = (
                        "adopted validate/validated.parquet produced outside this run"
                    )
                validate_stage.mark_completed(
                    outputs=_outputs(out, [(validated_path, "validated")])
                )
            elif design_ok:
                validate_stage.mark_failed("validation produced no validate/validated.parquet")
            else:
                validate_stage.mark_skipped("no design output in this run and none supplied")
    manifest.append(validate_stage)
    manifest.write(manifest_path)
    validate_ok = validate_stage.status == "completed"

    # ---- 4. Rank (CPU; runs only if validate produced output) ----
    ranking_path = out / "rank" / "ranking.parquet"
    rank_stage = StageRecord(
        name="rank",
        tool=_stage_tool("bindsight.rank"),
        inputs=_inputs(out, [(validated_path, "validated"), (candidates_path, "candidates")]),
        params=config.params.rank.model_dump(),
    )
    if skip_rank:
        rank_stage.mark_skipped("ranking skipped by request")
    elif not validate_ok:
        rank_stage.mark_skipped("no validation output to rank")
    else:
        try:
            from bindsight.rank import rank_run

            rank_run(out, weights=config.params.rank.weights)
            rank_stage.mark_completed(outputs=_outputs(out, [(ranking_path, "ranking")]))
        except Exception as e:
            LOG.warning("rank stage failed: %s", e)
            rank_stage.mark_failed(repr(e))
    manifest.append(rank_stage)
    manifest.write(manifest_path)
    rank_ok = rank_stage.status == "completed"

    # ---- 5. Report (CPU; works on whatever artifacts are present) ----
    report_path: Path | None = None
    report_stage = StageRecord(
        name="report",
        tool=_stage_tool("bindsight.report"),
        inputs=_inputs(
            out,
            [
                (out / "deg" / "results.parquet", "deg_table"),
                (candidates_path, "candidates"),
                (epitopes_path, "epitopes"),
                (out / "taxonomy" / "failure_taxonomy.parquet", "failure_taxonomy"),
                (ranking_path, "ranking"),
            ],
        ),
    )
    if skip_report:
        report_stage.mark_skipped("report skipped by request")
    else:
        try:
            from bindsight.report import render_run

            report_path = render_run(out)
            report_stage.mark_completed(outputs=_outputs(out, [(report_path, "report")]))
        except Exception as e:
            LOG.warning("report stage failed: %s", e)
            report_stage.mark_failed(repr(e))
    manifest.append(report_stage)
    manifest.write(manifest_path)

    # ---- 6. Export (CPU; bundles everything) ----
    crate_path: Path | None = None
    # The crate bundles the whole run directory, this manifest included, so the
    # manifest is deliberately not listed as an input: its digest changes the
    # moment this stage is recorded, and a digest that never matched the file
    # is worse than none. The crate's own metadata carries one per packaged file.
    export_inputs: list[tuple[Path, str]] = []
    if report_path is not None:
        export_inputs.append((report_path, "report"))
    export_stage = StageRecord(
        name="export",
        tool=_stage_tool("bindsight.export"),
        inputs=_inputs(out, export_inputs),
    )
    # The crate packages the manifest, so the copy inside it necessarily
    # predates this stage's own completion: the in-flight record is written
    # first, so the crate carries every stage up to the export itself.
    manifest.append(export_stage)
    manifest.write(manifest_path)
    if skip_export:
        export_stage.mark_skipped("export skipped by request")
    else:
        try:
            from bindsight.export import export_ro_crate

            crate_path = export_ro_crate(out)
            export_stage.mark_completed(outputs=_outputs(out, [(crate_path, "ro_crate")]))
        except Exception as e:
            LOG.warning("export stage failed: %s", e)
            export_stage.mark_failed(repr(e))
    manifest.write(manifest_path)

    return FullRunResult(
        manifest=manifest,
        discover_ok=discover_ok,
        design_ok=design_ok,
        validate_ok=validate_ok,
        rank_ok=rank_ok,
        report_path=report_path,
        crate_path=crate_path,
    )

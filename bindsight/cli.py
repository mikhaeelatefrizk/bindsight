# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""bindsight command-line interface.

A Click app exposing the pipeline stages as subcommands: ``discover`` (CPU
genomics → target shortlist), ``design`` / ``validate`` (GPU binder design +
structure/affinity prediction, dispatched to a runner backend), ``rank``,
``report``, ``export``, ``benchmark`` (rediscovery scoring against the held-out
known-antigen set), plus ``run`` (full pipeline), ``demo``, ``ui``, ``doctor``
and ``verify-licenses``.

GPU stages require a CUDA backend (``--backend modal|local_docker|kaggle`` for
headless execution, or ``--backend colab`` to generate a notebook). The CPU
stages run anywhere; ``--backend mock`` exercises the full chain in CI.
"""

from __future__ import annotations

import json
import logging
import sys
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as pkg_version
from pathlib import Path
from typing import TYPE_CHECKING, Any

import click
from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel
from rich.table import Table

from bindsight import __version__

if TYPE_CHECKING:  # pragma: no cover - typing only; runtime imports stay lazy
    from bindsight.config import RunConfig
    from bindsight.runners.protocol import CostEstimate


def _force_utf8_io() -> None:
    """Reconfigure stdout/stderr to UTF-8.

    Rich uses Unicode box-drawing characters for panels (┃ ━ etc.) and the
    pipeline log messages contain ≥, ×, → and other non-cp1252 glyphs. The
    default Windows console is cp1252 and will raise UnicodeEncodeError when
    asked to write those. ``sys.stdout.reconfigure(encoding='utf-8')`` is the
    one-line fix that works on Python 3.7+ on all platforms.
    """
    import contextlib

    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is not None and hasattr(stream, "reconfigure"):
            # Tests sometimes wrap sys.stdout in a non-reconfigurable buffer;
            # tolerate that and fall back to silently dropping bad chars.
            with contextlib.suppress(Exception):
                stream.reconfigure(encoding="utf-8", errors="replace")


_force_utf8_io()

LOG_CLI = logging.getLogger(__name__)


def _default_known_antigens() -> Path:
    """The shipped known-antigen set, resolved from the source tree if present.

    The default was the bare relative path ``benchmarks/known.tsv``, which only
    exists when the command is run from a repository checkout — and Click checks
    ``exists=True`` against it, so from a pip install the option failed before
    the command ran, naming a path the user has no reason to expect.
    """
    candidate = Path(__file__).resolve().parent.parent / "benchmarks" / "known.tsv"
    return candidate if candidate.is_file() else Path("benchmarks/known.tsv")


from bindsight.benchmark.core import DEFAULT_KS  # noqa: E402
from bindsight.provenance import append as provenance  # noqa: E402

# Rich console; legacy-windows mode off so box-drawing chars work after the
# UTF-8 reconfigure above.
console = Console(force_terminal=True, legacy_windows=False, soft_wrap=False)


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(console=console, rich_tracebacks=True, show_path=False)],
    )


# ---------------------------------------------------------------------------
# Top-level group
# ---------------------------------------------------------------------------
@click.group(
    name="bindsight",
    context_settings={"help_option_names": ["-h", "--help"]},
)
@click.version_option(__version__, prog_name="bindsight")
def main() -> None:
    """Bridge from RNA-seq to de novo protein binder design.

    See https://github.com/mikhaeelatefrizk/bindsight for the manual.
    """


# ---------------------------------------------------------------------------
# discover — CPU only; produces targets.parquet + epitopes.parquet
# ---------------------------------------------------------------------------
@main.command()
@click.argument(
    "config",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option(
    "--out",
    "out_dir",
    type=click.Path(file_okay=False, path_type=Path),
    required=True,
    help="Output directory for this run (will be created).",
)
@click.option(
    "--top-n",
    # Ranged, because this value is assigned straight onto the pydantic model
    # (``cfg.params.target_discovery.top_n = top_n``) and assignment does not
    # re-validate. ``--top-n 0`` therefore reached the pipeline and produced an
    # empty shortlist that looked like a finding.
    type=click.IntRange(min=1),
    default=None,
    help="Override params.target_discovery.top_n in the config.",
)
@click.option(
    "-v",
    "--verbose",
    is_flag=True,
    help="Verbose (DEBUG) logging.",
)
def discover(config: Path, out_dir: Path, top_n: int | None, verbose: bool) -> None:
    """Discover surface antigen targets from RNA-seq counts.

    Runs the discovery half of the pipeline (CPU only):
    DEG → surfaceome filter → Open Targets enrichment → AlphaFoldDB pull.
    (SURFACE-Bind targetable-site lookup is wired in: it reads a vendored data
    tree — there is no public API — and focuses design on real sites when
    present, else targets the whole surface.)
    """
    _setup_logging(verbose)
    from bindsight.config import RunConfig
    from bindsight.pipelines import discover as discover_pipeline

    cfg = RunConfig.from_yaml(config)
    cfg.out_dir = out_dir
    if top_n is not None:
        cfg.params.target_discovery.top_n = top_n

    console.print(f"[dim]config:[/dim] {config}")
    console.print(f"[dim]out:[/dim] {out_dir}")
    console.print(f"[dim]top-n:[/dim] {cfg.params.target_discovery.top_n}")

    manifest = discover_pipeline.run(cfg, out_dir=out_dir)

    failed = [s for s in manifest.stages if s.status == "failed"]
    if failed:
        console.print(
            Panel(
                "\n".join(f"[red]{s.name}[/red]: {s.error}" for s in failed),
                title="Stage failures",
                border_style="red",
            )
        )
        sys.exit(1)

    console.print(
        Panel(
            f"[green]Discovery complete.[/green]\n"
            f"Manifest: {out_dir / 'run_manifest.jsonld'}\n"
            f"Targets:  {out_dir / 'targets' / 'candidates.parquet'}\n"
            f"Epitopes: {out_dir / 'epitopes' / 'epitopes.parquet'}",
            title="bindsight discover",
            border_style="green",
        )
    )


# ---------------------------------------------------------------------------
# design — GPU offload; produces designed binder PDBs
# ---------------------------------------------------------------------------
@main.command()
@click.argument(
    "run_dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
)
@click.option(
    "--backend",
    type=click.Choice(["colab", "modal", "kaggle", "local_docker", "mock"]),
    default="colab",
    show_default=True,
)
@click.option(
    "--designer",
    type=click.Choice(["rfdiff_mpnn", "bindcraft", "boltzgen"]),
    default="rfdiff_mpnn",
    show_default=True,
)
@click.option(
    "--validator",
    type=click.Choice(["boltz2", "chai1r", "af2_ig"]),
    default="boltz2",
    show_default=True,
    help="Validator run on each design (structure + affinity prediction).",
)
@click.option(
    "--trajectories",
    type=click.IntRange(min=1),
    default=50,
    show_default=True,
    help=(
        "Number of independent design trajectories per target. The default shown "
        "here only applies when the run's config.yaml does not set "
        "params.design.n_trajectories; when it does, that value wins unless you "
        "pass this flag explicitly."
    ),
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Estimate compute cost without launching jobs.",
)
def design(
    run_dir: Path,
    backend: str,
    designer: str,
    validator: str,
    trajectories: int,
    dry_run: bool,
) -> None:
    """Generate de novo binder backbones + sequences (offloaded to a GPU runner).

    With ``--dry-run``, prints a per-target cost estimate without launching.
    Otherwise: ``--backend colab`` writes a ready-to-run notebook per target;
    the headless backends (``modal``/``local_docker``/``kaggle``/``mock``)
    execute the design+validation job and pull results back into ``<run>/design``.
    """
    from bindsight.cost import estimate_full_run

    # A run directory carries the configuration it was produced under. Until now
    # this command ignored it, so `params.design.n_trajectories: 10` in a config
    # became the flag's default of 50 — five times the GPU cost the user asked
    # for, printed in the cost panel as though it were their choice. An
    # explicitly passed flag still wins.
    designer, validator, trajectories = _design_defaults_from_run(
        run_dir, designer=designer, validator=validator, trajectories=trajectories
    )

    _preflight_backend(backend, designer=designer, validator=validator)

    epitopes_parquet = run_dir / "epitopes" / "epitopes.parquet"
    n_targets = _count_top_targets(epitopes_parquet)

    console.print(f"[dim]run-dir:[/dim] {run_dir}")
    console.print(f"[dim]backend:[/dim] {backend}")
    console.print(f"[dim]designer:[/dim] {designer}")
    console.print(f"[dim]validator:[/dim] {validator}")
    console.print(f"[dim]trajectories:[/dim] {trajectories}")
    console.print(f"[dim]targets:[/dim] {n_targets if n_targets is not None else 'unknown'}")

    if n_targets is None:
        # No estimate rather than an estimate of nothing. Costing a guessed
        # target count produces a plausible dollar figure for work whose size is
        # not known, which is worse than saying so.
        console.print(
            "[yellow]No epitopes table, so the target count is unknown and the "
            "cost estimate is skipped.[/yellow] Run `bindsight discover` first."
        )
    else:
        # gpu_type included, as `run` already does. Without it this quoted A100
        # prices for a run configured for a T4 -- the estimate was for different
        # hardware than the one the job would ask for.
        d_cost, _v_cost, _c_cost = estimate_full_run(
            backend=backend,
            designer=designer,
            validator=validator,
            n_targets=n_targets,
            n_trajectories=trajectories,
            gpu_type=_gpu_type_from_run(run_dir),
        )
        _print_cost_panel(d_cost, label=f"design ({designer})")

    if dry_run:
        console.print(
            Panel(
                "[green]--dry-run:[/green] no jobs launched. Drop --dry-run to run.",
                title="Dry run",
                border_style="green",
            )
        )
        return

    if backend == "colab":
        n = _write_design_notebooks(run_dir, designer=designer, trajectories=trajectories)
        console.print(
            Panel(
                f"[green]Wrote {n} Colab notebook(s)[/green] to {run_dir / 'design'}.\n"
                "Open each in Colab (GPU runtime), Run all, download the results "
                "tarball into <run>/design/, then run [bold]bindsight validate[/bold].",
                title="design: notebooks ready",
                border_style="green",
            )
        )
        return

    _seed, _blo, _bhi = _design_spec_params_from_run(run_dir)
    _top_k, _samples, _parallel = _validator_params_from_run(run_dir)
    launched = _launch_design(
        run_dir,
        backend=backend,
        designer=designer,
        validator=validator,
        trajectories=trajectories,
        prescreen_top_k=_top_k,
        diffusion_samples=_samples,
        max_parallel_samples=_parallel,
    )
    if launched == 0:
        console.print(
            Panel(
                "[yellow]No targets with a structure to design against.[/yellow] "
                "Run [bold]bindsight discover[/bold] first (and ensure AlphaFold "
                "structures were fetched).",
                title="design: nothing to do",
                border_style="yellow",
            )
        )
        sys.exit(2)
    provenance.record(
        run_dir,
        name="design",
        tool=f"bindsight.design.{designer}",
        outputs={
            "design_metrics": run_dir / "design" / "metrics.jsonl",
            "design_results": run_dir / "design" / "results.tar.gz",
        },
        params={
            "designer": designer,
            "validator": validator,
            "backend": backend,
            "n_trajectories": trajectories,
            # ARCHITECTURE 5 promises a reviewer can reach "the trajectory seed
            # and the resolved design parameters" from the manifest. They were
            # not recorded here, so a run's own manifest could not answer the
            # one question that makes it reproducible. `bindsight run` recorded
            # them by dumping the whole config; this path did not.
            "seed": _seed,
            "binder_length_min": _blo,
            "binder_length_max": _bhi,
        },
        notes=f"{launched} target(s) designed on the {backend} backend",
    )
    console.print(
        Panel(
            f"[green]Design complete for {launched} target(s).[/green]\n"
            f"Results: {run_dir / 'design'}\n"
            f"Next: [bold]bindsight validate {run_dir}[/bold]",
            title="bindsight design",
            border_style="green",
        )
    )


# ---------------------------------------------------------------------------
# validate — GPU; affinity + structure prediction on designed binders
# ---------------------------------------------------------------------------
@main.command()
@click.argument(
    "run_dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
)
@click.option(
    "--backend",
    type=click.Choice(["colab", "modal", "kaggle", "local_docker", "mock"]),
    default="colab",
    show_default=True,
)
@click.option(
    "--validator",
    type=click.Choice(["boltz2", "chai1r", "af2_ig"]),
    default="boltz2",
    show_default=True,
)
@click.option(
    "--revalidate",
    is_flag=True,
    help=(
        "Actually run --validator against the existing designs on --backend, instead of "
        "materialising the metrics the design step already produced. Use this to score the "
        "same binders with a second validator without redesigning them."
    ),
)
def validate(run_dir: Path, backend: str, validator: str, revalidate: bool) -> None:
    """Validate designed binders by predicting structure and binding affinity.

    By default this materialises the metrics the design job already produced,
    because the headless backends run design and validation together. Pass
    ``--revalidate`` to dispatch ``--validator`` against the existing designs;
    that is the path that makes cross-validator agreement possible.
    """
    from bindsight.cost import estimate

    if validator == "af2_ig":
        console.print(
            Panel(
                "[bold red]AF2-IG uses AlphaFold2 weights with a non-commercial license.[/bold red]\n"
                "See LICENSING.md § 3 for details. Default to boltz2 for commercial work.",
                title="License banner",
                border_style="red",
            )
        )

    design_dir = run_dir / "design"
    n_designs = _count_designs(design_dir)
    if n_designs is None:
        # No designs on disk yet, so any per-design figure would be invented.
        console.print(
            f"[yellow]No designs found under {design_dir}[/yellow] — "
            "cost is unknown until the design step has produced binders."
        )
    else:
        cost = estimate(backend=backend, stage="validate", plugin=validator, n_units=n_designs)
        _print_cost_panel(cost, label=f"validate ({validator}, {n_designs} designs)")

    if revalidate:
        # Revalidation dispatches to the backend just as design does, so the same
        # refusal applies: --validator chai1r --backend kaggle cannot work.
        _preflight_backend(backend, validator=validator)
        if backend == "colab":
            console.print(
                Panel(
                    "[yellow]--revalidate needs a headless backend[/yellow] "
                    "(modal / local_docker / kaggle / mock).\n"
                    "The colab runner cannot be launched from the CLI, so there is nothing "
                    "to dispatch to.",
                    title="validate: backend not dispatchable",
                    border_style="yellow",
                )
            )
            sys.exit(2)
        done = _launch_revalidate(run_dir, backend=backend, validator=validator)
        if done == 0:
            console.print(
                Panel(
                    "[yellow]Nothing to revalidate.[/yellow] No per-target design tarballs "
                    f"under {run_dir / 'design' / '_targets'} — run "
                    "[bold]bindsight design[/bold] first.",
                    title="validate: nothing to do",
                    border_style="yellow",
                )
            )
            sys.exit(2)
        console.print(f"[green]Revalidated {done} target(s) with {validator}.[/green]")

    # The design step (headless backends) runs design + validation together via
    # the executor, writing per-design metrics into the design tarballs. Here we
    # materialise those into validate/validated.parquet (+ per-binder dirs).
    n = _finalize_validate(run_dir)
    validated = run_dir / "validate" / "validated.parquet"
    if n == 0:
        # Nothing was validated, so nothing is recorded. provenance.record marks
        # the stage completed unconditionally, so this command used to append a
        # completed validate stage to run_manifest.jsonld and then print, on the
        # same screen, that the GPU step still needed running. The manifest is
        # what a reviewer reads and what the RO-Crate exports; it must not
        # assert a stage the console is telling the user to go and perform.
        console.print(
            Panel(
                "No design results to validate yet. Run [bold]bindsight design[/bold] on a\n"
                "headless backend (modal/local_docker/kaggle), or for --backend colab open "
                "the\ngenerated notebook (GPU), download the results tarball into "
                "<run>/design/,\nthen re-run this command. See docs/colab-design-howto.md.",
                title="validate: GPU step pending",
                border_style="cyan",
            )
        )
        sys.exit(0)
    # Record the validator that produced these numbers, not the one the flag
    # asked for. Without --revalidate no validator runs here, so the flag is a
    # request the metrics may not answer to.
    produced_by = _validators_that_produced(validated)
    provenance.record(
        run_dir,
        name="validate",
        tool=f"bindsight.validate.{'+'.join(produced_by) if produced_by else validator}",
        outputs={"validated": validated},
        params={
            "validator_requested": validator,
            "validator_recorded": produced_by,
            "backend": backend,
            "revalidate": revalidate,
        },
        notes=f"{n} design(s) materialised into validated.parquet",
    )
    # n == 0 returned above, before the stage was recorded, so reaching here
    # means designs really were validated.
    console.print(
        Panel(
            f"[green]Validated {n} design(s).[/green]\n"
            f"Output: {validated}\nNext: [bold]bindsight rank {run_dir}[/bold]",
            title="validate: ready",
            border_style="green",
        )
    )


# ---------------------------------------------------------------------------
# rank — multi-objective scoring
# ---------------------------------------------------------------------------
@main.command()
@click.argument(
    "run_dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
)
def rank(run_dir: Path) -> None:
    """Rank validated binders by composite score (affinity, iPTM, expression Δ)."""
    from bindsight.rank import rank_run

    try:
        out = rank_run(run_dir)
    except FileNotFoundError as e:
        console.print(
            Panel(
                f"[yellow]{e}[/yellow]\n\n"
                "Run [bold]bindsight validate <run_dir>[/bold] first, then this.",
                title="rank: nothing to rank",
                border_style="yellow",
            )
        )
        sys.exit(2)
    # The weights are what turn four metrics into one ordering, and they are
    # configurable. Recording the ranking without them left the published order
    # underdetermined: nothing in the manifest says which weighting produced it.
    from bindsight.config import RankWeights

    weights = RankWeights()
    provenance.record(
        run_dir,
        name="rank",
        tool="bindsight.rank",
        inputs={"validated": run_dir / "validate" / "validated.parquet"},
        outputs={"ranking": out},
        params={"weights": weights.model_dump()},
    )
    console.print(
        Panel(
            f"[green]Ranking written.[/green]\n[bold]Output:[/bold] {out}",
            title="bindsight rank",
            border_style="green",
        )
    )


# ---------------------------------------------------------------------------
# report — self-contained HTML / served interface
# ---------------------------------------------------------------------------
@main.command()
@click.argument(
    "run_dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
)
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["html", "web"]),
    default="html",
    show_default=True,
)
@click.option(
    "--include-binders/--no-include-binders",
    default=False,
    help=(
        "Embed each ranked binder's designed sequence in the report. The ranked "
        "binder table itself is always included when the design and rank stages "
        "have run."
    ),
)
def report(run_dir: Path, fmt: str, include_binders: bool) -> None:
    """Render the run as a self-contained HTML report, or serve the interface.

    HTML output is one self-contained file (CSS + plot + tables embedded) you
    can email or attach to a paper. `--format web` serves the same run locally
    for interactive browsing; nothing is fetched from a network either way.
    """
    if fmt == "html":
        from bindsight.report import render_run

        out_path = render_run(run_dir, include_binders=include_binders)
        provenance.record(
            run_dir,
            name="report",
            tool="bindsight.report",
            outputs={"report_html": out_path},
            params={"format": fmt, "include_binders": include_binders},
        )
        console.print(
            Panel(
                f"[green]Report rendered.[/green]\n[bold]Open:[/bold] {out_path}",
                title="bindsight report",
                border_style="green",
            )
        )
        return

    if fmt == "web":
        try:
            from bindsight.report.web.app import serve
        except ImportError as exc:  # pragma: no cover - exercised via the extra
            console.print(
                Panel(
                    "[yellow]The web interface is not installed.[/yellow]\n"
                    f"[dim]{exc}[/dim]\n"
                    # Rich reads an unescaped bracket as a style tag, which made
                    # this print `pip install -e "."` -- the base package, which
                    # is what the reader already had.
                    '  [bold]pip install -e ".\\[report]"[/bold]',
                    title="Missing dependency",
                    border_style="yellow",
                )
            )
            sys.exit(2)

        console.print(
            Panel(
                f"[bold]http://127.0.0.1:8501[/bold]\n"
                f"[dim]Serving runs from {run_dir.parent}. Ctrl-C to stop.[/dim]",
                title="bindsight",
                border_style="blue",
            )
        )
        try:
            # The root it just announced, not whatever ./runs resolves to from
            # the shell's working directory.
            serve(port=8501, open_browser=True, run_root=run_dir.parent)
        except KeyboardInterrupt:  # pragma: no cover - interactive
            console.print("[dim]stopped[/dim]")
        return


# ---------------------------------------------------------------------------
# run — full pipeline
# ---------------------------------------------------------------------------
@main.command()
@click.argument(
    "config",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option(
    "--out",
    "out_dir",
    type=click.Path(file_okay=False, path_type=Path),
    required=True,
)
@click.option("--backend", type=click.Choice(["colab", "modal", "kaggle", "local_docker", "mock"]))
@click.option("--designer", type=click.Choice(["rfdiff_mpnn", "bindcraft", "boltzgen"]))
@click.option("--validator", type=click.Choice(["boltz2", "chai1r", "af2_ig"]))
@click.option("--cheap", is_flag=True, help="Use the --cheap profile (T4-friendly defaults).")
@click.option("--dry-run", is_flag=True, help="Print a cost estimate, don't execute.")
def run(
    config: Path,
    out_dir: Path,
    backend: str | None,
    designer: str | None,
    validator: str | None,
    cheap: bool,
    dry_run: bool,
) -> None:
    """Run the full discover → design → validate → rank → report → export pipeline.

    CPU stages (discover, rank, report, export) always execute. The GPU stages
    (design, validate) **launch real work** when the configured backend is
    headless (mock, modal, kaggle, local_docker) — this help used to say they
    only reuse outputs from a previous session, which is true for ``colab`` and
    false for every other backend, on a command that spends GPU quota — this command is the
    single-entry-point version of running each stage in turn. To produce those
    outputs, run ``bindsight design`` against a GPU backend first; ``--backend
    kaggle`` is the verified free path.
    """
    _setup_logging(verbose=False)
    from bindsight.config import RunConfig
    from bindsight.pipelines.full_run import run as run_full

    cfg = RunConfig.from_yaml(config)
    cfg.out_dir = out_dir
    if backend:
        cfg.backend = backend  # type: ignore[assignment]
    if designer:
        cfg.params.design.designer = designer  # type: ignore[assignment]
    if validator:
        cfg.params.validate_.validator = validator  # type: ignore[assignment]
    if cheap:
        _apply_cheap_profile(cfg)

    # The same refusal `design` performs. This command launches the GPU half on
    # a headless backend, so skipping the check meant `run` could spend quota
    # discovering a designer/backend combination `design` would have refused
    # locally and for free.
    _preflight_backend(
        cfg.backend,
        designer=cfg.params.design.designer,
        validator=cfg.params.validate_.validator,
    )

    if dry_run:
        from bindsight.cost import estimate_full_run

        n_targets = cfg.params.target_discovery.top_n
        n_traj = cfg.params.design.n_trajectories
        _d, _v, c = estimate_full_run(
            backend=cfg.backend,
            designer=cfg.params.design.designer,
            validator=cfg.params.validate_.validator,
            n_targets=n_targets,
            n_trajectories=n_traj,
            gpu_type=cfg.params.design.gpu_type,
        )
        _print_cost_panel(c, label="full run (combined design + validate)")
        return

    result = run_full(cfg, out_dir=out_dir)
    summary_lines = [
        f"discover : {'OK' if result.discover_ok else 'partial / failed'}",
        f"design   : {'OK (artifacts present)' if result.design_ok else 'pending — run: bindsight design <run> --backend kaggle'}",
        f"validate : {'OK (artifacts present)' if result.validate_ok else 'pending — needs design output'}",
        f"rank     : {'OK' if result.rank_ok else 'skipped (no validate output)'}",
        f"report   : {result.report_path}" if result.report_path else "report: not rendered",
        f"crate    : {result.crate_path}" if result.crate_path else "crate: not exported",
    ]
    console.print(
        Panel(
            "\n".join(summary_lines),
            title="bindsight run — summary",
            border_style="green" if result.discover_ok else "yellow",
        )
    )


# ---------------------------------------------------------------------------
# export — RO-Crate
# ---------------------------------------------------------------------------
@main.command()
@click.argument(
    "run_dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
)
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["ro-crate"]),
    default="ro-crate",
    show_default=True,
)
@click.option(
    "--out",
    "out_path",
    type=click.Path(dir_okay=False, path_type=Path),
    required=True,
)
def export(run_dir: Path, fmt: str, out_path: Path) -> None:
    """Export a finished run as an RO-Crate zip suitable for Zenodo deposit."""
    from bindsight.export import export_ro_crate

    out = export_ro_crate(run_dir, out_path)
    # The crate is NOT recorded as a digested output. A copy of this manifest is
    # sealed inside the crate, so any digest written here describes a file that
    # did not exist when that copy was taken: the crate's own manifest would
    # assert a hash that is not the crate's, and a reviewer checking the deposit
    # against it would find a mismatch and no way to tell which artifact was
    # wrong. The crate's digest belongs outside the crate -- see the SHA256SUMS
    # published beside the deposit.
    provenance.record(
        run_dir,
        name="export",
        tool="bindsight.export",
        outputs={},
        params={"format": fmt, "crate_path": out.name},
        notes=(
            "The crate is not listed as a digested output: it contains a copy of "
            "this manifest, so it cannot also contain its own sha256. Publish the "
            "crate's digest alongside the deposit (SHA256SUMS), not inside it."
        ),
    )
    console.print(
        Panel(
            f"[green]RO-Crate written.[/green]\n[bold]File:[/bold] {out}\n\n"
            "Upload to Zenodo (https://zenodo.org/uploads/new) for a citable DOI.",
            title="bindsight export",
            border_style="green",
        )
    )


# ---------------------------------------------------------------------------
# benchmark — score rediscovery of held-out known antigens across runs
# ---------------------------------------------------------------------------
@main.command()
@click.argument(
    "run_dirs",
    nargs=-1,
    required=True,
    type=click.Path(exists=True, file_okay=False, path_type=Path),
)
@click.option(
    "--known-antigens",
    "known_antigens",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=_default_known_antigens(),
    show_default=True,
    help=(
        "TSV of held-out known antigens (symbol, uniprot, tumor_type, ...). "
        "The default ships with the source tree, not with the wheel: from a pip "
        "install there is no benchmarks/ directory, so pass this explicitly."
    ),
)
@click.option(
    "--out",
    "out_path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=Path("benchmark_report.html"),
    show_default=True,
    help="Where to write the HTML benchmark report.",
)
@click.option(
    "--k",
    "ks",
    multiple=True,
    type=click.IntRange(min=1),
    help=(
        "Top-k cutoffs for recall@k (repeatable). Default: "
        + ", ".join(str(k) for k in DEFAULT_KS)
        + "."
    ),
)
def benchmark(
    run_dirs: tuple[Path, ...],
    known_antigens: Path,
    out_path: Path,
    ks: tuple[int, ...],
) -> None:
    """Benchmark how well runs rediscover the held-out known antigens.

    Scores each RUN_DIR (a finished ``bindsight discover``/``run`` output) by the
    rank of every known antigen in its candidate shortlist, computes recall@k,
    and renders a side-by-side HTML report. The known set ships in
    ``benchmarks/known.tsv`` (see ``benchmarks/PROVENANCE.md``).
    """
    from bindsight.benchmark import run_benchmark

    # One source for the cutoffs. They were written as a literal here, again in
    # the help text above, and a third time as DEFAULT_KS in the benchmark
    # module -- three places to change, and a help string that could describe a
    # default the command does not use.
    cutoffs = tuple(ks) if ks else DEFAULT_KS
    out, scores = run_benchmark(list(run_dirs), known_antigens, out_html=out_path, ks=cutoffs)

    table = Table(title="rediscovery benchmark", show_lines=False, title_style="bold")
    table.add_column("run", style="cyan", no_wrap=True)
    table.add_column("found")
    for k in cutoffs:
        table.add_column(f"recall@{k}")
    for s in scores:
        table.add_row(
            s.run_name,
            f"{s.n_found}/{s.n_known}",
            *[f"{s.recall_at[k]:.0%}" for k in cutoffs],
        )
    console.print(table)
    console.print(
        Panel(
            f"[green]Benchmark written.[/green]\n[bold]Report:[/bold] {out}\n"
            f"Known set: {known_antigens}",
            title="bindsight benchmark",
            border_style="green",
        )
    )


# ---------------------------------------------------------------------------
# ui — launch the local web interface
# ---------------------------------------------------------------------------
@main.command()
@click.option(
    "--port",
    type=click.IntRange(min=1, max=65535),
    default=8501,
    show_default=True,
    help="Port for the local web server.",
)
@click.option(
    "--no-browser",
    is_flag=True,
    help="Don't auto-open a browser tab; just print the URL.",
)
def ui(port: int, no_browser: bool) -> None:
    """Launch the bindsight web interface in your browser.

    Five sections: what the tool is and has shown, the evidence behind that, a
    demo, your own data, and the runs already on disk. Served locally; nothing
    leaves the machine and nothing is fetched from a network once installed --
    the stylesheet, the charts and the structure viewer all travel inside the
    package.
    """
    try:
        from bindsight.report.web.app import serve
    except ImportError as exc:  # pragma: no cover - exercised via the extra
        console.print(
            Panel(
                "[red]The web interface is not installed.[/red]\n"
                f"[dim]{exc}[/dim]\n\n"
                # Escaped: Rich would read `[report]` as a style tag and drop
                # it, printing a command that installs nothing new.
                'Install it with: [bold]pip install -e ".\\[report]"[/bold]',
                title="ui: missing dependency",
                border_style="red",
            )
        )
        sys.exit(2)

    url = f"http://127.0.0.1:{port}"
    console.print(
        Panel(
            f"[bold]{url}[/bold]\n[dim]Ctrl-C to stop. Runs are read from ./runs.[/dim]",
            title="bindsight",
            border_style="blue",
        )
    )
    # Served in-process. The subprocess this replaced ran with ``check=False``
    # and its status was discarded, so a server that never started still left
    # the command printing "Launching bindsight UI" and exiting 0. uvicorn exits
    # non-zero on a port it cannot bind, and that status is no longer swallowed.
    try:
        serve(port=port, open_browser=not no_browser)
    except KeyboardInterrupt:  # pragma: no cover - interactive
        console.print("[dim]stopped[/dim]")


# ---------------------------------------------------------------------------
# verify-licenses — pure-Python, works today
# ---------------------------------------------------------------------------
@main.command(name="verify-licenses")
@click.argument(
    "config",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    required=False,
)
def verify_licenses(config: Path | None) -> None:
    """Print the license summary for components used by bindsight.

    With a config path, audits the components selected by that config and
    flags any non-commercial choices.
    """
    # Single source of truth: (component, license, commercial?, role).
    # `commercial` is True when the component is usable in commercial work.
    components: list[tuple[str, str, bool, str]] = [
        ("bindsight", "AGPL-3.0-or-later", True, "this package"),
        ("pydeseq2", "MIT", True, "DEG analysis (default)"),
        ("Open Targets", "CC0 / Apache-2", True, "target evidence"),
        ("GTEx (v8 public)", "Open", True, "tissue baselines"),
        ("SURFY", "CC BY", True, "surfaceome filter"),
        ("SURFACE-Bind", "BSD-3", True, "targetable sites"),
        ("AlphaFoldDB", "CC BY 4.0", True, "structures"),
        ("RFdiffusion", "BSD-3", True, "default backbone designer"),
        ("ProteinMPNN", "MIT", True, "sequence design"),
        ("Boltz-2", "MIT (code+weights)", True, "default validator"),
        ("Chai-1r", "Apache-2", True, "alt validator"),
        ("BoltzGen", "MIT (code+weights)", True, "alt designer"),
        ("BindCraft", "MIT", True, "premium designer"),
        ("Snakemake", "MIT", True, "workflow"),
        ("AF2-IG (opt-in)", "AF2 weights NC", False, "alt validator (banner)"),
    ]
    by_name = {c[0]: c for c in components}

    def _commercial_cell(ok: bool) -> str:
        return "[green]yes[/green]" if ok else "[red]no[/red]"

    def _render(title: str, rows: list[tuple[str, str, bool, str]]) -> None:
        t = Table(title=title, show_lines=False, title_style="bold")
        t.add_column("Component", style="cyan", no_wrap=True)
        t.add_column("License")
        t.add_column("Commercial?", style="bold")
        t.add_column("Role")
        for name, lic, ok, role in rows:
            t.add_row(name, lic, _commercial_cell(ok), role)
        console.print(t)

    if config is None:
        _render("bindsight component licenses (default config)", components)
    else:
        from bindsight.config import RunConfig

        cfg = RunConfig.from_yaml(config)
        designer = cfg.params.design.designer
        validator = cfg.params.validate_.validator
        backend = cfg.backend

        # Map the config's plugin choices to the components they pull in.
        designer_components = {
            "rfdiff_mpnn": ["RFdiffusion", "ProteinMPNN"],
            "bindcraft": ["BindCraft"],
            "boltzgen": ["BoltzGen"],
        }[designer]
        validator_components = {
            "boltz2": ["Boltz-2"],
            "chai1r": ["Chai-1r"],
            "af2_ig": ["AF2-IG (opt-in)"],
        }[validator]

        # Core discovery components are always pulled in, regardless of config.
        core = [
            "bindsight",
            "pydeseq2",
            "Open Targets",
            "GTEx (v8 public)",
            "SURFY",
            "SURFACE-Bind",
            "AlphaFoldDB",
        ]
        selected = [by_name[n] for n in core + designer_components + validator_components]

        _render(
            f"Components selected by {Path(config).name} "
            f"(designer={designer}, validator={validator}, backend={backend})",
            selected,
        )

        nc = [r for r in selected if not r[2]]
        if nc:
            names = ", ".join(r[0] for r in nc)
            console.print(
                f"\n[red bold]⚠ Non-commercial component(s) selected:[/red bold] {names}.\n"
                "[yellow]This configuration is NOT cleared for commercial use. Switch the "
                "offending stage (e.g. validator -> boltz2 or chai1r) for a fully "
                "commercial-friendly run.[/yellow]"
            )
        else:
            console.print(
                "\n[green bold]✓ All components selected by this config are "
                "commercial-friendly.[/green bold]"
            )

    console.print(
        "\n[dim]See LICENSING.md for the full inventory and commercial-use guidance.[/dim]"
    )


# ---------------------------------------------------------------------------
# CLI helpers used by design + validate
# ---------------------------------------------------------------------------
def _count_top_targets(epitopes_parquet: Path) -> int | None:
    """Count top-N targets from a discover-stage epitopes Parquet; None when unknown.

    ``None``, not 5. This returned a hard-coded 5 for a table that was missing or
    unreadable, and that invented number was printed as ``targets: 5`` and then
    fed to the cost estimate — so a run with no epitopes table quoted a GPU cost
    for work it had no targets to do, with nothing on screen to say the figure
    was made up. Its sibling ``_count_designs`` already says exactly this.
    """
    if not epitopes_parquet.exists():
        LOG_CLI.warning("no epitopes table at %s; target count unknown", epitopes_parquet)
        return None
    try:
        import pandas as pd

        return len(pd.read_parquet(epitopes_parquet))
    except Exception as exc:
        LOG_CLI.warning("could not read %s (%s); target count unknown", epitopes_parquet, exc)
        return None


def _count_designs(design_dir: Path) -> int | None:
    """Count the designs actually present in ``<run>/design``; None when unknown.

    The executor ships designs inside per-target tarballs, so the loose ``*.pdb``
    files a plain glob sees are only the ones a user unpacked by hand — both are
    counted, tarball members by name. ``None`` means nothing countable is there
    yet (the GPU step hasn't run), which the caller must report as unknown rather
    than quote a made-up number.
    """
    import tarfile

    if not design_dir.exists():
        return None
    n = len({p for p in design_dir.rglob("*.pdb") if "validate" not in p.parts})
    for archive in sorted(design_dir.rglob("*.tar.gz")):
        try:
            with tarfile.open(archive, "r:gz", encoding="utf-8") as tf:
                # Only the archive's own design/ members; the per-target tarballs
                # nested inside results.tar.gz are counted from their own files.
                n += sum(
                    1
                    for name in tf.getnames()
                    if name.lower().endswith(".pdb") and Path(name).parts[:1] == ("design",)
                )
        except (tarfile.TarError, OSError) as e:
            LOG_CLI.warning("could not read %s: %s", archive, e)
    return n or None


#: The ``--cheap`` profile, as specified in ARCHITECTURE.md §10: "RFdiff+MPNN
#: on T4, 10 trajectories, ESM-2 pre-screen". The flag was parsed and then
#: silently ignored, so a user asking for the cheap profile got the expensive
#: one and a cost estimate quoting A100 prices.
CHEAP_DESIGNER = "rfdiff_mpnn"
CHEAP_TRAJECTORIES = 10
CHEAP_GPU_TYPE = "T4"
CHEAP_PRESCREEN_TOP_K = 5


def _apply_cheap_profile(cfg: RunConfig) -> None:
    """Apply the T4-friendly profile in place.

    Applied before the ``--dry-run`` branch so the printed estimate describes
    the run that would actually happen.

    Args:
        cfg: The run configuration to modify.
    """
    design = cfg.params.design
    design.designer = CHEAP_DESIGNER  # type: ignore[assignment]
    design.n_trajectories = CHEAP_TRAJECTORIES
    design.gpu_type = CHEAP_GPU_TYPE
    design.prescreen_top_k = min(CHEAP_PRESCREEN_TOP_K, CHEAP_TRAJECTORIES)
    console.print(
        Panel(
            f"designer={CHEAP_DESIGNER} · trajectories={CHEAP_TRAJECTORIES} · "
            f"GPU={CHEAP_GPU_TYPE} · ESM-2 pre-screen keeps "
            f"{design.prescreen_top_k} designs per target",
            title="--cheap profile",
            border_style="cyan",
        )
    )


def _preflight_backend(backend: str, **plugins: str) -> None:
    """Refuse a backend/plugin combination the backend cannot run.

    The CLI accepted any designer against any backend and found out remotely.
    ``--designer bindcraft --backend kaggle`` built the same two-environment
    kernel every Kaggle job builds, because the kernel takes no designer
    argument, and failed only after roughly six minutes of environment building
    had been charged to a weekly GPU quota that does not refund.

    A combination the backend has no environment for is refused here, in about a
    second, naming what it does provide. A combination the executor would *try*
    to bootstrap is allowed and announced, because untested is not the same
    statement as impossible and blocking it would remove a path that may work.

    Args:
        backend: the runner the job would go to.
        **plugins: role name -> plugin name, e.g. ``designer="bindcraft"``.

    Raises:
        SystemExit: with status 2 when any combination is unsupported.
    """
    from bindsight.plugins import UNSUPPORTED, UNTESTED, plugin_support

    refusals: list[str] = []
    for role, name in plugins.items():
        if not name:
            continue
        verdict, why = plugin_support(backend, name)
        if verdict == UNSUPPORTED:
            refusals.append(f"[bold]{role} {name}[/bold] — {why}")
        elif verdict == UNTESTED:
            console.print(
                f"[yellow]untested:[/yellow] {why}. Proceeding, but this path has "
                "not been demonstrated end to end."
            )
    if not refusals:
        return
    console.print(
        Panel(
            "\n\n".join(refusals)
            + "\n\n[dim]Refused locally so no GPU quota is spent discovering it "
            "remotely.[/dim]",
            title=f"{backend}: unsupported combination",
            border_style="red",
        )
    )
    sys.exit(2)


def _design_defaults_from_run(
    run_dir: Path, *, designer: str, validator: str, trajectories: int
) -> tuple[str, str, int]:
    """Fill unset design options from the configuration the run was produced under.

    ``bindsight design <run>`` takes a run directory, not a config, so it had no
    way to see what the user configured and used its own flag defaults instead.
    That silently overrode ``params.design.n_trajectories`` — a fivefold change
    in GPU cost, reported in the cost panel as if it had been requested.

    Click knows whether a value came from the command line or from a default, so
    an explicit flag still wins and only unset options are filled in.

    Args:
        run_dir: the run directory, which holds the effective ``config.yaml``.
        designer: the designer option as Click resolved it.
        validator: the validator option as Click resolved it.
        trajectories: the trajectory count as Click resolved it.

    Returns:
        The three values, with defaults replaced by the run's configuration
        where one is available.
    """
    import logging

    log = logging.getLogger(__name__)
    cfg_path = run_dir / "config.yaml"
    if not cfg_path.is_file():
        return designer, validator, trajectories

    try:
        import yaml

        params = (yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}).get("params") or {}
        design_params = params.get("design") or {}
        validate_params = params.get("validate") or {}
    except Exception as e:  # pragma: no cover - a malformed config is the user's
        log.warning("could not read %s (%s); using command-line defaults", cfg_path, e)
        return designer, validator, trajectories

    ctx = click.get_current_context(silent=True)

    def _from_default(name: str) -> bool:
        if ctx is None:
            return False
        return ctx.get_parameter_source(name) is click.core.ParameterSource.DEFAULT

    if _from_default("designer") and design_params.get("designer"):
        designer = str(design_params["designer"])
    if _from_default("validator") and validate_params.get("validator"):
        validator = str(validate_params["validator"])
    if _from_default("trajectories") and design_params.get("n_trajectories"):
        trajectories = int(design_params["n_trajectories"])
        log.info("using n_trajectories=%d from %s", trajectories, cfg_path)

    return designer, validator, trajectories


def _validator_params_from_run(run_dir: Path) -> tuple[int | None, int, int]:
    """Validator settings this command has no flag for, read from the run's config.

    ``_design_defaults_from_run`` fills in options that *are* flags, deferring to
    an explicit one. These three are not flags, so the configuration is their
    only source — and this command was not reading them, which made them inert
    on the one path that runs design without ``bindsight run``.

    ``prescreen_top_k`` is the expensive one to lose: ``--cheap`` sets it, and
    dropping it validates every design instead of the configured few, paying the
    GPU cost the profile exists to avoid. It is the same defect this command
    already carries a fix for — a configured value honoured by ``bindsight run``
    and silently ignored here — one field further along.

    Args:
        run_dir: the run directory holding the effective ``config.yaml``.

    Returns:
        ``(prescreen_top_k, diffusion_samples, max_parallel_samples)``, using the
        schema's own defaults when the file is absent or unreadable.
    """
    import logging

    log = logging.getLogger(__name__)
    cfg_path = run_dir / "config.yaml"
    if not cfg_path.is_file():
        return None, 1, 1
    try:
        import yaml

        params = (yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}).get("params") or {}
        design_params = params.get("design") or {}
        validate_params = params.get("validate") or {}
    except Exception as e:  # pragma: no cover - a malformed config is the user's
        log.warning("could not read %s (%s); using defaults", cfg_path, e)
        return None, 1, 1

    top_k = design_params.get("prescreen_top_k")
    samples = int(validate_params.get("diffusion_samples") or 1)
    parallel = int(validate_params.get("max_parallel_samples") or 1)
    if top_k:
        log.info("using prescreen_top_k=%s from %s", top_k, cfg_path)
    if samples != 1:
        log.info("using diffusion_samples=%d from %s", samples, cfg_path)
    return (int(top_k) if top_k else None), samples, parallel


def _gpu_type_from_run(run_dir: Path) -> str | None:
    """The GPU the run was configured for, or ``None`` when unrecorded.

    ``bindsight run`` already passes ``params.design.gpu_type`` to the cost
    estimate; ``design --dry-run`` did not, so it quoted A100 prices for a run
    configured for a T4 -- an estimate for different hardware than the job would
    ask for, printed with no indication that the two differ.
    """
    cfg_path = run_dir / "config.yaml"
    if not cfg_path.is_file():
        return None
    try:
        import yaml

        params = (yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}).get("params") or {}
        return (params.get("design") or {}).get("gpu_type")
    except Exception as e:  # pragma: no cover - a malformed config is the user's
        LOG_CLI.warning("could not read %s (%s); pricing without a gpu_type", cfg_path, e)
        return None


def _design_spec_params_from_run(run_dir: Path) -> tuple[int, int, int]:
    """Read the design parameters a run was configured with, for its spec.

    Unlike :func:`_design_defaults_from_run`, none of these are command-line
    options, so there is no flag to defer to — the configuration is the only
    source. They were nonetheless not read at all: every job was built with
    ``make_spec``'s own defaults, so a run whose ``config.yaml`` recorded
    ``seed: 42`` shipped a spec carrying seed 0 to the GPU. That was verified by
    decoding the payload of a kernel launched from exactly such a config.

    A silently ignored seed is worse than an inconvenient one. The seed is part
    of the cache key and part of the manifest, so the artifact claimed to
    describe a run that had not happened, and the run could never be reproduced
    from the configuration filed beside it.

    Args:
        run_dir: the run directory, which holds the effective ``config.yaml``.

    Returns:
        ``(seed, binder_length_min, binder_length_max)``, falling back to the
        DesignSpec defaults wherever the configuration is silent or unreadable.
    """
    import logging

    from bindsight.design.protocol import DesignSpec

    log = logging.getLogger(__name__)
    fields = DesignSpec.model_fields
    seed = int(fields["seed"].default)
    lo = int(fields["binder_length_min"].default)
    hi = int(fields["binder_length_max"].default)

    cfg_path = run_dir / "config.yaml"
    if not cfg_path.is_file():
        return seed, lo, hi
    try:
        import yaml

        params = (yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}).get("params") or {}
        design_params = params.get("design") or {}
    except Exception as e:  # pragma: no cover - a malformed config is the user's
        log.warning("could not read %s (%s); using DesignSpec defaults", cfg_path, e)
        return seed, lo, hi

    if design_params.get("seed") is not None:
        seed = int(design_params["seed"])
    if design_params.get("binder_length_min") is not None:
        lo = int(design_params["binder_length_min"])
    if design_params.get("binder_length_max") is not None:
        hi = int(design_params["binder_length_max"])
    log.info("design spec from %s: seed=%d binder_length=%d-%d", cfg_path, seed, lo, hi)
    return seed, lo, hi


def _working_tree_wheel(backend: str, run_dir: Path) -> Path | None:
    """Build a wheel of this checkout for a remote backend to install.

    Remote runners pip-install bindsight before doing anything, and with no
    wheel that means the repository's default branch — not the code you are
    running. A designer benchmark launched to validate a fix once spent an hour
    on a GPU executing the unfixed code for exactly this reason, and reported
    success.

    Failure is not fatal: the runner falls back to a git install and warns that
    local changes will not run, so someone who installed bindsight from PyPI can
    still submit a job.

    Args:
        backend: the runner name. Local backends install nothing, so they get None.
        run_dir: the run directory; the wheel is built into ``_wheel`` inside it.

    Returns:
        Path to the built wheel, or None when it is unnecessary or unavailable.
    """
    if backend in {"mock", "local_docker"}:
        return None
    from bindsight.runners.source_wheel import build_working_tree_wheel

    return build_working_tree_wheel(run_dir / "_wheel")


def _target_artifact_stem(target: dict[str, Any]) -> str:
    """Filename stem for one design job's artifacts, unique per epitope site.

    Keyed on the accession alone, a receptor with two qualifying sites had its
    second job's tarball written over the first's — same name, different
    binders, no warning — and the reader then found one archive where two jobs
    had run. Discovery emits one epitopes row per site and each row becomes its
    own job, so the accession is not the unit of work.

    Mirrors :func:`bindsight.runners.job_exec._binder_id_prefix` deliberately, so
    an archive's name and the binder ids inside it agree, and a whole-surface
    job keeps the bare accession it has always had.
    """
    from bindsight.runners.job_exec import _binder_id_prefix

    return _binder_id_prefix(
        {
            "target_uniprot": target.get("uniprot"),
            "epitope_residues": target.get("residues") or [],
            "epitope_chain": target.get("chain") or "A",
        }
    )


def _top_targets(run_dir: Path) -> list[dict[str, Any]]:
    """Return top-N targets (uniprot, structure_path, chain, residues, ranges) to design.

    Structure references are resolved to absolute paths here, which is the one
    place every design/validate consumer funnels through. New runs store them
    run-relative so the run stays portable; runs made before that change stored
    absolute cache paths. ``resolve_run_path`` accepts both.

    ``design_ranges`` (the extracellular ranges discovery annotated from UniProt
    topology) is carried through to the design job so binders are designed against
    the reachable part of the receptor. Targets without it are named on the console
    — designing against the full length, transmembrane helix and cytoplasmic tail
    included, is a real difference the user has to know about.
    """
    import pandas as pd

    from bindsight.io.paths import resolve_run_path

    epitopes_parquet = run_dir / "epitopes" / "epitopes.parquet"
    if not epitopes_parquet.exists():
        return []
    df = pd.read_parquet(epitopes_parquet)
    targets: list[dict[str, Any]] = []
    no_ranges: list[str] = []
    for _, row in df.iterrows():
        uni = row.get("uniprot_id")
        resolved = resolve_run_path(run_dir, row.get("structure_path"))
        if resolved is None or not uni:
            continue
        struct = str(resolved)
        residues = row.get("residues")
        residues = list(residues) if residues is not None and len(residues) else []
        ranges = _design_ranges(row.get("design_ranges") if "design_ranges" in df.columns else None)
        if not ranges:
            no_ranges.append(str(uni))
        targets.append(
            {
                "uniprot": str(uni),
                "structure_path": struct,
                "chain": str(row.get("chain") or "A"),
                "residues": [int(r) for r in residues],
                "design_ranges": ranges,
            }
        )
    if no_ranges:
        console.print(
            f"[yellow]No extracellular ranges for {', '.join(sorted(set(no_ranges)))}[/yellow] — "
            "designing against the full-length chain (transmembrane and cytoplasmic "
            "regions included). Enable params.target_discovery.use_uniprot_topology "
            "in discover to restrict design to the extracellular domain."
        )
    return targets


def _design_ranges(raw: Any) -> list[tuple[int, int]]:
    """Coerce an epitopes-table ``design_ranges`` cell to ``[(lo, hi), ...]``.

    The column holds a nested array (or NaN/None when topology wasn't annotated),
    which is exactly the "we never determined the extracellular domain" case.
    """
    if raw is None or not hasattr(raw, "__len__") or len(raw) == 0:
        return []
    ranges: list[tuple[int, int]] = []
    for r in raw:
        if r is None or len(r) != 2:
            continue
        ranges.append((int(r[0]), int(r[1])))
    return ranges


def _write_design_notebooks(run_dir: Path, *, designer: str, trajectories: int) -> int:
    """Write one Colab design+validate notebook per top target. Returns count."""
    from bindsight.plugins import get_designer
    from bindsight.runners.notebook_content import write_design_notebook

    design_dir = run_dir / "design"
    design_dir.mkdir(parents=True, exist_ok=True)
    plugin = get_designer(designer)
    # The configured seed and binder-length bounds, read the same way the
    # launch path reads them. Omitting them here left make_spec's own defaults
    # embedded in the notebook -- on `colab`, which is the DEFAULT backend --
    # so a run configured with seed 42 shipped a notebook carrying seed 0.
    seed, binder_length_min, binder_length_max = _design_spec_params_from_run(run_dir)
    n = 0
    for t in _top_targets(run_dir):
        spec = plugin.make_spec(
            target_uniprot=t["uniprot"],
            target_structure_path=Path(t["structure_path"]),
            epitope_residues=t["residues"],
            epitope_chain=t["chain"],
            design_ranges=t["design_ranges"],
            n_trajectories=trajectories,
            seed=seed,
            binder_length_min=binder_length_min,
            binder_length_max=binder_length_max,
        )
        spec_dict = spec.model_dump()
        # Embed the target structure (converted to PDB) so the Colab notebook is
        # self-contained — RFdiffusion needs PDB; AlphaFold ships mmCIF.
        b64 = _structure_pdb_b64(Path(t["structure_path"]))
        if b64:
            spec_dict["target_structure_b64"] = b64
            spec_dict.setdefault("extra_params", {})["target_structure_name"] = "target.pdb"
        handle_id = f"{designer}_{t['uniprot']}"
        write_design_notebook(
            design_dir / f"{handle_id}.ipynb",
            handle_id=handle_id,
            designer=designer,
            gpu_type="T4",
            spec=spec_dict,
        )
        n += 1
    return n


def _structure_pdb_b64(structure_path: Path) -> str | None:
    """Return base64 PDB bytes for a structure (converting mmCIF → PDB)."""
    import base64
    import tempfile

    if not structure_path.exists():
        return None
    if structure_path.suffix.lower() in {".cif", ".mmcif"}:
        from bindsight.runners.job_exec import _cif_to_pdb

        tmp = Path(tempfile.mkdtemp()) / "target.pdb"
        try:
            _cif_to_pdb(structure_path, tmp)
            data = tmp.read_bytes()
        except Exception as e:  # pragma: no cover - biopython parse edge cases
            LOG_CLI.warning("could not convert %s to PDB: %s", structure_path, e)
            return None
        return base64.b64encode(data).decode()
    return base64.b64encode(structure_path.read_bytes()).decode()


def _validators_that_produced(validated: Path) -> list[str]:
    """Return the validators named in a validated table, as recorded per row.

    ``bindsight validate`` takes a ``--validator`` flag, but by default it does
    not run one: it materialises metrics the design job already produced, using
    whichever validator *that* job was given. Recording the flag in the manifest
    therefore described a validator that may never have run — passing
    ``--validator chai1r`` to a Boltz-2 run filed Chai-1r's name against
    Boltz-2's numbers. The rows themselves carry the truth, so ask them.

    Args:
        validated: path to ``validated.parquet``.

    Returns:
        Sorted distinct validator names, or an empty list when the table is
        missing, empty, or carries no ``validator_name``.
    """
    if not validated.is_file():
        return []
    try:
        import pandas as pd

        df = pd.read_parquet(validated)
    except Exception as e:  # a corrupt table must not sink the manifest
        LOG_CLI.warning("could not read %s (%s) to name the validator", validated, e)
        return []
    if "validator_name" not in df.columns:
        return []
    names = {str(v) for v in df["validator_name"].dropna().tolist() if str(v).strip()}
    return sorted(names)


def _validate_params(run_dir: Path) -> Any:
    """Read the run's validation parameters, falling back to the defaults.

    Args:
        run_dir: the run directory, which holds the effective ``config.yaml``.

    Only the ``params.validate`` section is parsed, not the whole ``RunConfig``.
    Validating the entire document would make an unrelated schema change — a new
    required field, a renamed input — silently revert the thresholds to their
    defaults on every existing run, which is the same class of quiet fallback
    these helpers exist to remove. The values actually used are still validated,
    because the section is parsed into :class:`ValidateParams`.

    Returns:
        The :class:`~bindsight.config.ValidateParams` the run was configured
        with. A malformed config must not cost the caller its metrics, so an
        unreadable file is a warning and the defaults are used.
    """
    from bindsight.config import ValidateParams

    cfg_path = run_dir / "config.yaml"
    if not cfg_path.is_file():
        return ValidateParams()
    try:
        import yaml

        params = (yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}).get("params") or {}
        return ValidateParams(**(params.get("validate") or {}))
    except Exception as e:  # a malformed config must not lose the metrics
        LOG_CLI.warning("could not read %s (%s); using default thresholds", cfg_path, e)
        return ValidateParams()


def _split_on_thresholds(df: Any, run_dir: Path, validate_dir: Path) -> Any:
    """Honour ``apply_thresholds`` by setting failing designs aside, not deleting them.

    The flag was declared in the config, shipped in an example YAML, and read by
    no code, so a user who asked for the quality bars to be enforced got a table
    in which every design still appeared. Its own comment claimed it changed what
    ``bindsight validate`` records, while the annotation ran unconditionally —
    the flag had no behaviour to describe.

    It is honoured now, and nothing is destroyed to do it. Rows that fail move to
    ``excluded_by_thresholds.parquet`` beside the table they left, each carrying
    the reason it failed, and the count is printed. A design that vanishes with
    no recorded reason is precisely the invisible filter this pipeline exists not
    to have; a design moved to a named file with its reason attached is not one.

    Designs whose metrics were never measured are kept. A bar a design was not
    scored against cannot be a bar it failed.

    Args:
        df: the annotated validation table.
        run_dir: the run directory, for its configuration.
        validate_dir: where to write the excluded rows.

    Returns:
        The table to keep — unchanged unless ``apply_thresholds`` is set.
    """
    params = _validate_params(run_dir)
    if not getattr(params, "apply_thresholds", False) or df.empty:
        return df

    failing = df["passes_thresholds"] == "fail"
    if not bool(failing.any()):
        return df

    excluded = df[failing]
    excluded.to_parquet(validate_dir / "excluded_by_thresholds.parquet", index=False)
    console.print(
        f"[yellow]apply_thresholds:[/yellow] {len(excluded)} of {len(df)} designs "
        f"failed the configured bars and were written to "
        f"{validate_dir / 'excluded_by_thresholds.parquet'} with their reasons."
    )
    return df[~failing].reset_index(drop=True)


def _mark_thresholds(df: Any, run_dir: Path) -> Any:
    """Annotate each validated design against the configured quality bars.

    ``iptm_threshold`` and ``pae_interaction_threshold`` were declared in the
    config, shipped in the example YAMLs, and read by nothing — so a user who
    tightened either was silently ignored. They are now applied, but only as
    annotation: every design stays in the table and carries ``passes_thresholds``
    plus a human-readable ``threshold_reason``. Nothing is dropped, because a
    design vanishing without a recorded reason is exactly the kind of invisible
    filter that makes a pipeline untrustworthy. Filtering is the reader's call.

    A metric the validator did not produce cannot fail a bar it was never
    measured against: such a row is marked ``unassessed`` rather than passed.
    """
    import pandas as pd

    params = _validate_params(run_dir)

    if df.empty:
        df["passes_thresholds"] = pd.Series(dtype="object")
        df["threshold_reason"] = pd.Series(dtype="object")
        return df

    iptm = pd.to_numeric(df.get("iptm"), errors="coerce")
    pae = pd.to_numeric(df.get("pae_interaction"), errors="coerce")

    verdicts: list[str | None] = []
    reasons: list[str] = []
    for i, p_ in zip(iptm, pae, strict=False):
        failed: list[str] = []
        unmeasured: list[str] = []
        if pd.isna(i):
            unmeasured.append("iptm")
        elif i < params.iptm_threshold:
            failed.append(f"iptm {i:.3f} < {params.iptm_threshold:.2f}")
        if pd.isna(p_):
            unmeasured.append("pae_interaction")
        elif p_ > params.pae_interaction_threshold:
            failed.append(f"pae_interaction {p_:.1f} > {params.pae_interaction_threshold:.1f}")
        if failed:
            verdicts.append("fail")
            reasons.append("; ".join(failed))
        elif unmeasured:
            verdicts.append("unassessed")
            reasons.append("not measured: " + ", ".join(unmeasured))
        else:
            verdicts.append("pass")
            reasons.append(
                f"iptm >= {params.iptm_threshold:.2f} and "
                f"pae_interaction <= {params.pae_interaction_threshold:.1f}"
            )
    df["passes_thresholds"] = verdicts
    df["threshold_reason"] = reasons
    return df


def _archive_carries_designs(archive: Path) -> bool:
    """True when a results tarball still contains the designed sequences.

    ``_launch_revalidate`` replaces a target's tarball with whatever the run
    returns. That is right when the new archive carries the designs back
    alongside the fresh validator output, and destructive when it does not: the
    FASTA is the only record of what was designed, since the staged PDBs are
    byte-identical per backbone, and a second revalidation would then find
    nothing left to rescore.
    """
    import tarfile

    if not archive.is_file():
        return False
    try:
        with tarfile.open(archive, "r:gz", encoding="utf-8") as tf:
            return any(
                m.isfile() and m.name.startswith("design/") and m.name.endswith(".fasta")
                for m in tf.getmembers()
            )
    except (OSError, tarfile.TarError):
        return False


def _launch_revalidate(run_dir: Path, *, backend: str, validator: str) -> int:
    """Run ``validator`` against the binders a previous design step produced.

    The designs travel to the GPU alongside the spec and no designer runs, so
    choosing a different validator costs one validation pass rather than a full
    redesign. This is what makes cross-validator agreement (Boltz-2 against
    Chai-1r or AF2 initial-guess on the *same* binders) reachable at all.

    Returns the number of targets revalidated.
    """
    import shutil
    import tarfile
    import tempfile

    from bindsight.design._common import make_cache_key, submit_via_runner
    from bindsight.design.protocol import DesignSpec
    from bindsight.plugins import get_runner

    targets = _top_targets(run_dir)
    if not targets:
        return 0
    design_dir = run_dir / "design"
    targets_dir = design_dir / "_targets"
    runner = get_runner(
        backend,
        designer="rfdiff_mpnn",
        n_units_per_target=1,
        bindsight_wheel=_working_tree_wheel(backend, run_dir),
    )

    metrics_lines: list[str] = []
    done = 0
    for t in targets:
        # Written under the site-specific stem since the per-site collision was
        # fixed. Runs made before that carry the bare accession, and they are
        # still readable: a naming fix must not orphan the archives it renames.
        tar_path = targets_dir / f"{_target_artifact_stem(t)}.tar.gz"
        if not tar_path.exists():
            legacy = targets_dir / f"{t['uniprot']}.tar.gz"
            if legacy.exists():
                tar_path = legacy
            else:
                LOG_CLI.warning("no design tarball for %s; skipping", t["uniprot"])
                continue
        with tempfile.TemporaryDirectory() as tmp:
            staged = Path(tmp) / "design"
            staged.mkdir(parents=True, exist_ok=True)
            with tarfile.open(tar_path, "r:gz", encoding="utf-8") as tf:
                for m in tf.getmembers():
                    if m.isfile() and m.name.startswith("design/"):
                        src = tf.extractfile(m)
                        if src is not None:
                            (staged / Path(m.name).name).write_bytes(src.read())
            if not any(staged.glob("*.fasta")):
                LOG_CLI.warning("no designs inside %s; skipping", tar_path)
                continue
            spec = DesignSpec(
                target_uniprot=t["uniprot"],
                target_structure_path=str(t["structure_path"]),
                epitope_chain=t["chain"],
                epitope_residues=t["residues"],
                design_ranges=t["design_ranges"],
                n_trajectories=1,
                seed=0,
                extra_params={"mode": "validate_only", "validator": validator},
            )
            result = submit_via_runner(
                spec,
                runner,
                designer_name=f"revalidate:{validator}",
                designer_version="1",
                designer_commit_sha=None,
                cache_key=make_cache_key(spec, extra=("validate_only", validator)),
                payload_dir=staged,
            )
        # Never trade the designs for a validator's output. See
        # :func:`_archive_carries_designs`.
        if _archive_carries_designs(Path(result.results_archive_path)):
            shutil.copy2(result.results_archive_path, tar_path)
        else:
            LOG_CLI.error(
                "the revalidated archive for %s carries no designs, so copying it "
                "over %s would destroy the binders it was meant to rescore. Keeping "
                "the original; the new metrics are still recorded.",
                t["uniprot"],
                tar_path,
            )
        mpath = Path(result.metrics_jsonl_path)
        if mpath.exists():
            metrics_lines += [
                ln for ln in mpath.read_text(encoding="utf-8").splitlines() if ln.strip()
            ]
        done += 1

    if metrics_lines:
        (design_dir / "metrics.jsonl").write_text(
            "\n".join(metrics_lines) + "\n", encoding="utf-8", newline="\n"
        )
    return done


def _launch_design(
    run_dir: Path,
    *,
    backend: str,
    designer: str,
    validator: str,
    trajectories: int,
    prescreen_top_k: int | None = None,
    diffusion_samples: int = 1,
    max_parallel_samples: int = 1,
) -> int:
    """Run design+validation for each top target via a headless runner backend.

    ``prescreen_top_k`` is passed through to the executor, which applies the
    ESM-2 screen between design and validation — the only point at which
    dropping a design saves GPU time. ``None`` validates every design.
    """
    import shutil

    from bindsight.plugins import get_designer, get_runner

    targets = _top_targets(run_dir)
    if not targets:
        return 0
    seed, binder_length_min, binder_length_max = _design_spec_params_from_run(run_dir)
    plugin = get_designer(designer)
    runner = get_runner(
        backend,
        designer=designer,
        n_units_per_target=trajectories,
        bindsight_wheel=_working_tree_wheel(backend, run_dir),
    )
    design_dir = run_dir / "design"
    targets_dir = design_dir / "_targets"
    targets_dir.mkdir(parents=True, exist_ok=True)

    metrics_lines: list[str] = []
    launched = 0
    for t in targets:
        spec = plugin.make_spec(
            target_uniprot=t["uniprot"],
            target_structure_path=Path(t["structure_path"]),
            epitope_residues=t["residues"],
            epitope_chain=t["chain"],
            design_ranges=t["design_ranges"],
            n_trajectories=trajectories,
            seed=seed,
            binder_length_min=binder_length_min,
            binder_length_max=binder_length_max,
        )
        extra: dict[str, str | int | float | bool] = {
            **spec.extra_params,
            "validator": validator,
        }
        if prescreen_top_k:
            extra["prescreen_top_k"] = int(prescreen_top_k)
        # Only when asked for. Both default to 1, so a run that does not set
        # them produces the same spec — and the same cache key — as before.
        if diffusion_samples and int(diffusion_samples) != 1:
            extra["diffusion_samples"] = int(diffusion_samples)
        if max_parallel_samples and int(max_parallel_samples) != 1:
            extra["max_parallel_samples"] = int(max_parallel_samples)
        spec = spec.model_copy(update={"extra_params": extra})
        result = plugin.submit(spec, runner)
        shutil.copy2(
            result.results_archive_path, targets_dir / f"{_target_artifact_stem(t)}.tar.gz"
        )
        mpath = Path(result.metrics_jsonl_path)
        if mpath.exists():
            metrics_lines += [
                ln for ln in mpath.read_text(encoding="utf-8").splitlines() if ln.strip()
            ]
        launched += 1

    (design_dir / "metrics.jsonl").write_text(
        "\n".join(metrics_lines) + ("\n" if metrics_lines else ""), encoding="utf-8", newline="\n"
    )
    # A top-level results.tar.gz marks design completion for `bindsight run`.
    import tarfile

    with tarfile.open(design_dir / "results.tar.gz", "w:gz", encoding="utf-8") as tf:
        tf.add(design_dir / "metrics.jsonl", arcname="metrics.jsonl")
        tf.add(targets_dir, arcname="_targets")
    return launched


def _finalize_validate(run_dir: Path) -> int:
    """Build validate/validated.parquet from design metrics; unpack per-binder dirs."""
    import tarfile

    import pandas as pd

    design_dir = run_dir / "design"
    validate_dir = run_dir / "validate"
    validate_dir.mkdir(parents=True, exist_ok=True)

    # Unpack each per-target tarball's validate/<binder_id>/ into <run>/validate/.
    targets_dir = design_dir / "_targets"
    if targets_dir.exists():
        for tar_path in targets_dir.glob("*.tar.gz"):
            try:
                with tarfile.open(tar_path, "r:gz", encoding="utf-8") as tf:
                    for m in tf.getmembers():
                        if m.name.startswith("validate/"):
                            tf.extract(m, validate_dir.parent, filter="data")
            except (tarfile.TarError, OSError) as e:
                LOG_CLI.warning("could not unpack %s: %s", tar_path, e)

    metrics_path = design_dir / "metrics.jsonl"
    rows = (
        [
            json.loads(ln)
            for ln in metrics_path.read_text(encoding="utf-8").splitlines()
            if ln.strip()
        ]
        if metrics_path.exists()
        else []
    )
    # Always write validated.parquet (with the expected schema even when empty)
    # so downstream rank / the Snakemake `validate` output always exists.
    cols = [
        "binder_id",
        "target_uniprot",
        "iptm",
        "pae_interaction",
        "affinity_pred_value",
        "affinity_probability_binary",
        "validator_name",
        "validator_version",
    ]
    df = pd.DataFrame(rows) if rows else pd.DataFrame(columns=cols)
    df = _mark_thresholds(df, run_dir)
    df = _split_on_thresholds(df, run_dir, validate_dir)
    df.to_parquet(validate_dir / "validated.parquet", index=False)
    return len(df)


def _print_cost_panel(cost: CostEstimate, label: str) -> None:
    """Render a CostEstimate as a Rich panel with the user-relevant fields."""
    usd = cost.usd_estimate or 0.0
    dollars = "free" if usd == 0 else f"~${usd:.2f}"
    console.print(
        Panel(
            f"[bold]{label}[/bold]\n"
            f"backend     {cost.backend}\n"
            f"GPU         {cost.gpu_type}\n"
            f"GPU-hours   {cost.gpu_hours:.2f}\n"
            f"USD         {dollars}\n"
            f"queue ~{cost.queue_minutes_estimate or 0:.0f} min  ·  "
            f"{cost.notes or ''}",
            title="Cost estimate",
            border_style="cyan",
        )
    )


# ---------------------------------------------------------------------------
# demo — one-command end-to-end against the shipped tiny example
# ---------------------------------------------------------------------------
@main.command()
@click.option(
    "--out",
    "out_dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path("runs/demo"),
    show_default=True,
    help="Where to write the demo output.",
)
@click.option(
    "--no-report",
    is_flag=True,
    help="Skip rendering the HTML report at the end.",
)
def demo(out_dir: Path, no_report: bool) -> None:
    """Run the full discovery half on a real TCGA breast-cancer cohort.

    Auto-downloads an authentic TCGA-BRCA tumor-vs-adjacent-normal RNA-seq
    cohort (STAR - Counts, 20 tumour vs 20 normal) from NIH/GDC on first run and
    runs real DESeq2 over it. Needs network the first time (cohort + SURFY
    downloaded, then cached); takes a few minutes on real data. Produces an HTML
    report.

    Which antigens surface is the run's result, not a scripted one: a 20-vs-20
    subsample can land either side of the significance cutoffs. See
    benchmarks/study/RESULTS.md for what the full cohorts show.
    """
    # This help text once promised the demo rediscovered ERBB2 (HER2) and EGFR
    # as top antibody-tractable surface antigens. The project's own rediscovery
    # study measures ERBB2 in an unstratified breast cohort (matched pairs, no
    # biomarker selection) at log2 fold
    # change 0.92 -- below the 1.0 floor, so it does not clear the significance
    # rule -- and the demo config's own comment notes that EGFR is often lower in
    # bulk tumour than in normal breast epithelium. Naming an expected outcome in
    # --help turns whatever the run produces into either a confirmation or an
    # apparent malfunction, and one of those readings would be wrong.
    from bindsight.config import RunConfig
    from bindsight.pipelines import discover as discover_pipeline

    _setup_logging(verbose=False)

    # Resolve the bundled config relative to the package install root.
    repo_root = Path(__file__).parent.parent
    cfg_path = repo_root / "examples" / "demo" / "config.yaml"
    if not cfg_path.exists():
        # Installed wheels put it in shared-data under sys.prefix (pyproject's
        # [tool.hatch.build.targets.wheel.shared-data]). Without this candidate
        # `bindsight demo` could only ever run from a source checkout, which is
        # the one situation the one-button demo is not for.
        cfg_path = Path(sys.prefix) / "bindsight_demo" / "config.yaml"
    if not cfg_path.exists():
        # Editable installs: try CWD as a fallback.
        cfg_path = Path("examples/demo/config.yaml")
    if not cfg_path.exists():
        console.print(
            Panel(
                "[red]Could not find examples/demo/config.yaml.[/red] "
                "Re-install with `pip install -e .` from the repo root.",
                title="demo failed",
                border_style="red",
            )
        )
        sys.exit(2)

    console.print(
        Panel(
            "[bold]bindsight demo[/bold]\n\n"
            f"config: {cfg_path}\nout:    {out_dir}\n\n"
            "Real TCGA-BRCA tumor-vs-adjacent-normal cohort (NIH/GDC). The\n"
            "pipeline discovers antibody-tractable cell-surface antigens that are\n"
            "over-expressed in tumor (known targets such as ERBB2/HER2 appear when\n"
            "their signal is present), with full provenance. First run downloads\n"
            "the cohort + SURFY and enriches via Open Targets (cached afterwards)\n"
            "and runs real DESeq2 — a few minutes, not seconds.",
            title="Demo run",
            border_style="cyan",
        )
    )

    cfg = RunConfig.from_yaml(cfg_path)
    cfg.out_dir = out_dir
    # Cache the auto-downloaded cohort under the OS user-cache dir (like the
    # SURFY/AlphaFold/Open Targets caches) so the one-button demo works from any
    # working directory and is downloaded only once.
    from bindsight.io.paths import cache_dir

    cohort_dir = cache_dir("gdc") / "tcga_brca"
    cfg.inputs.counts = cohort_dir / "counts.tsv.gz"
    cfg.inputs.design = cohort_dir / "design.tsv"

    manifest = discover_pipeline.run(cfg, out_dir=out_dir)
    failed = [s for s in manifest.stages if s.status == "failed"]
    if failed:
        console.print(
            Panel(
                "\n".join(f"[red]{s.name}[/red]: {s.error}" for s in failed),
                title="Demo stage failures",
                border_style="red",
            )
        )
        sys.exit(1)

    # Render the report unless asked not to.
    report_path: Path | None = None
    if not no_report:
        from bindsight.report import render_run

        report_path = render_run(out_dir)

    console.print(
        Panel(
            f"[green]Demo complete![/green]\n\n"
            f"Manifest:    {out_dir / 'run_manifest.jsonld'}\n"
            f"Targets:     {out_dir / 'targets' / 'candidates.parquet'}\n"
            f"Epitopes:    {out_dir / 'epitopes' / 'epitopes.parquet'}"
            + (f"\nReport HTML: {report_path}" if report_path else "")
            + "\n\nNext steps:\n"
            "  1. Open the HTML report in a browser to see the results.\n"
            "  2. Inspect the Parquet outputs with pandas / DuckDB.\n"
            "  3. Read docs/how-to-use.md to swap in your own RNA-seq cohort.\n"
            "  4. See docs/what-is-bindsight.md for the full pitch.",
            title="bindsight demo",
            border_style="green",
        )
    )


# ---------------------------------------------------------------------------
# doctor — diagnose the local install (cache state, vendored data, env vars)
# ---------------------------------------------------------------------------
@main.command()
def doctor() -> None:
    """Diagnose the local install: Python, deps, cache state, vendored data."""
    import os
    import platform

    from bindsight.io.paths import cache_dir

    table = Table(title="bindsight doctor", show_lines=False, title_style="bold")
    table.add_column("Check", style="cyan", no_wrap=True)
    table.add_column("Status")
    table.add_column("Detail", overflow="fold")

    def _row(name: str, ok: bool, detail: str = "") -> None:
        status = "[green]ok[/green]" if ok else "[yellow]warn[/yellow]"
        table.add_row(name, status, detail)

    # Runtime
    _row("python", sys.version_info >= (3, 11), platform.python_version())
    _row("platform", True, platform.platform())
    _row("bindsight", True, __version__)

    # Optional deps that the discovery half needs
    for dep in ("pydeseq2", "pandas", "pyarrow", "requests", "tenacity"):
        try:
            v = pkg_version(dep)
            _row(f"dep: {dep}", True, v)
        except PackageNotFoundError:
            _row(
                f"dep: {dep}",
                False,
                'not installed; run: pip install -e ".\\[discover]"',
            )

    # Cache state
    base = cache_dir()
    _row("cache root", base.exists(), str(base))
    # Report the surfaceome list discovery will *actually* use, not just whether
    # a refreshed network cache exists. The full list is vendored with the
    # package (2,886 accessions) and needs no network, so a missing cache is
    # normal, not a degradation.
    from bindsight.surfaceome.surfy import load_vendored_surfy

    surfy_cache = base / "surfy" / "surfy_v1.uniprot.txt"
    vendored = load_vendored_surfy()
    if surfy_cache.exists():
        n_cached = sum(
            1
            for ln in surfy_cache.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.lstrip().startswith("#")
        )
        _row("SURFY surfaceome", n_cached > 0, f"{n_cached} accessions (refreshed cache)")
    elif vendored is not None:
        _row(
            "SURFY surfaceome",
            True,
            f"{len(vendored)} accessions (vendored list — no network needed)",
        )
    else:
        _row(
            "SURFY surfaceome",
            False,
            "vendored list missing — reinstall bindsight (only a 10-protein fallback remains)",
        )
    afdb_cache = base / "alphafolddb"
    n_afdb = len(list(afdb_cache.glob("*.cif"))) if afdb_cache.exists() else 0
    _row("AlphaFoldDB cache", afdb_cache.exists(), f"{n_afdb} mmCIF files cached")
    ot_cache = base / "opentargets"
    n_ot = len(list(ot_cache.glob("*.json"))) if ot_cache.exists() else 0
    _row("Open Targets cache", ot_cache.exists(), f"{n_ot} cached responses")

    # Vendored data (SURFACE-Bind)
    sb_env = os.environ.get("BINDSIGHT_SURFACE_BIND_DATA")
    sb_default = Path("data/surface_bind")
    if sb_env:
        sb_path = Path(sb_env)
        _row(
            "SURFACE-Bind data",
            sb_path.exists(),
            f"env BINDSIGHT_SURFACE_BIND_DATA={sb_path}",
        )
    else:
        _row(
            "SURFACE-Bind data",
            (sb_default / "sites").exists() if sb_default.exists() else False,
            "data/surface_bind/sites — see data/surface_bind/README.md",
        )

    console.print(table)


if __name__ == "__main__":  # pragma: no cover
    main()

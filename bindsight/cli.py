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

import logging
import sys
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as pkg_version
from pathlib import Path

import click
from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel
from rich.table import Table

from bindsight import __version__


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
# Helpers
# ---------------------------------------------------------------------------
def _not_implemented(stage: str) -> None:
    """Print a stage-not-yet-implemented banner and exit with code 2."""
    console.print(
        Panel(
            f"[bold yellow]{stage}[/bold yellow] is not implemented in this dev build "
            f"(bindsight {__version__}).\n\n"
            "Track progress at https://github.com/mikhaeelatefrizk/bindsight/blob/main/CHANGELOG.md",
            title="Not implemented yet",
            border_style="yellow",
        )
    )
    sys.exit(2)


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
    type=int,
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
    SURFACE-Bind site lookup is wired in v0.0.3.
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
    "--trajectories",
    type=int,
    default=50,
    show_default=True,
    help="Number of independent design trajectories per target.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Estimate compute cost and print the DAG without launching jobs.",
)
def design(
    run_dir: Path,
    backend: str,
    designer: str,
    trajectories: int,
    dry_run: bool,
) -> None:
    """Generate de novo binder backbones + sequences (offloaded to GPU).

    With --dry-run, prints a per-target cost estimate without launching anything.
    Without --dry-run, the actual launch lands in v0.1.0-rc2 alongside the
    runner integrations; v0.0.x prints the plan and exits.
    """
    from bindsight.cost import estimate_full_run

    # Try to read the per-run epitopes table to count targets accurately.
    epitopes_parquet = run_dir / "epitopes" / "epitopes.parquet"
    n_targets = _count_top_targets(epitopes_parquet)

    console.print(f"[dim]run-dir:[/dim] {run_dir}")
    console.print(f"[dim]backend:[/dim] {backend}")
    console.print(f"[dim]designer:[/dim] {designer}")
    console.print(f"[dim]trajectories:[/dim] {trajectories}")
    console.print(f"[dim]targets:[/dim] {n_targets}")

    # Cost estimate works today regardless of --dry-run.
    d_cost, _v_cost, _c_cost = estimate_full_run(
        backend=backend,
        designer=designer,
        validator="boltz2",
        n_targets=n_targets,
        n_trajectories=trajectories,
    )
    _print_cost_panel(d_cost, label=f"design ({designer})")

    if dry_run:
        console.print(
            Panel(
                "[green]--dry-run:[/green] no jobs launched. "
                "Drop --dry-run to launch (live submit lands in v0.1.0-rc2).",
                title="Dry run",
                border_style="green",
            )
        )
        return

    _not_implemented("design (live submit)")


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
def validate(run_dir: Path, backend: str, validator: str) -> None:
    """Validate designed binders by predicting structure and binding affinity."""
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

    # Best-effort: count designs to validate from a design results manifest;
    # fall back to an estimate.
    design_dir = run_dir / "design"
    n_designs = _count_designs(design_dir)
    cost = estimate(backend=backend, stage="validate", plugin=validator, n_units=n_designs)
    _print_cost_panel(cost, label=f"validate ({validator}, {n_designs} designs)")

    # The actual validation runs in the GPU notebook (Colab/Modal). Once the
    # user pulls the validated.parquet back into <run_dir>/validate/, the
    # `bindsight rank` and `bindsight report` commands consume it.
    validated = run_dir / "validate" / "validated.parquet"
    if validated.exists():
        console.print(
            Panel(
                f"[green]Validation output already present:[/green] {validated}\n"
                "Next: [bold]bindsight rank " + str(run_dir) + "[/bold]",
                title="validate: ready",
                border_style="green",
            )
        )
        return

    console.print(
        Panel(
            "Validation runs on a GPU. Two paths:\n\n"
            "  1. [bold]Colab[/bold] — open the notebook bindsight wrote during "
            "[bold]bindsight design[/bold] (`<run>/design/<id>.ipynb`); the "
            "validation cells are included.\n"
            "  2. [bold]docs/colab-design-howto.md[/bold] — manual recipe.\n\n"
            "Drop the resulting validated.parquet into <run>/validate/ when done, "
            "then re-run this command.",
            title="validate: GPU step pending",
            border_style="cyan",
        )
    )
    sys.exit(0)


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
    console.print(
        Panel(
            f"[green]Ranking written.[/green]\n[bold]Output:[/bold] {out}",
            title="bindsight rank",
            border_style="green",
        )
    )


# ---------------------------------------------------------------------------
# report — Quarto / Streamlit
# ---------------------------------------------------------------------------
@main.command()
@click.argument(
    "run_dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
)
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["html", "streamlit"]),
    default="html",
    show_default=True,
)
@click.option(
    "--include-binders/--no-include-binders",
    default=False,
    help="Embed designed binder structures (requires GPU stages to have run).",
)
def report(run_dir: Path, fmt: str, include_binders: bool) -> None:
    """Render the run as a self-contained HTML report or launch the Streamlit dashboard.

    HTML output is one self-contained file (CSS + plot + tables embedded) you
    can email or attach to a paper. Streamlit launches a local dev server for
    interactive browsing.
    """
    if fmt == "html":
        from bindsight.report import render_run

        out_path = render_run(run_dir)
        console.print(
            Panel(
                f"[green]Report rendered.[/green]\n[bold]Open:[/bold] {out_path}",
                title="bindsight report",
                border_style="green",
            )
        )
        return

    if fmt == "streamlit":
        import subprocess
        import sys as _sys

        from bindsight.report import streamlit_app

        app_path = Path(streamlit_app.__file__)
        console.print(f"[dim]launching Streamlit:[/dim] {app_path} {run_dir}")
        try:
            subprocess.run(
                [_sys.executable, "-m", "streamlit", "run", str(app_path), "--", str(run_dir)],
                check=True,
            )
        except FileNotFoundError:
            console.print(
                Panel(
                    "[yellow]Streamlit not installed.[/yellow] Install the report extras:\n"
                    '  [bold]pip install -e ".[report]"[/bold]',
                    title="Missing dependency",
                    border_style="yellow",
                )
            )
            sys.exit(2)
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
@click.option("--dry-run", is_flag=True, help="Print DAG and cost estimate, don't execute.")
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

    CPU stages (discover, rank, report, export) always execute. GPU stages
    (design, validate) run only if the corresponding outputs are already
    present from a previous Colab/Modal session — this command is the
    single-entry-point version of running each stage in turn.
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
        )
        _print_cost_panel(c, label="full run (combined design + validate)")
        return

    result = run_full(cfg, out_dir=out_dir)
    summary_lines = [
        f"discover : {'OK' if result.discover_ok else 'partial / failed'}",
        f"design   : {'OK (artifacts present)' if result.design_ok else 'pending — run on Colab/Modal'}",
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
    default=Path("benchmarks/known.tsv"),
    show_default=True,
    help="TSV of held-out known antigens (symbol, uniprot, tumor_type, ...).",
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
    type=int,
    help="Top-k cutoffs for recall@k (repeatable). Default: 5, 10, 20.",
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

    cutoffs = tuple(ks) if ks else (5, 10, 20)
    out, scores = run_benchmark(
        list(run_dirs), known_antigens, out_html=out_path, ks=cutoffs
    )

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
# ui — launch the local Streamlit web app
# ---------------------------------------------------------------------------
@main.command()
@click.option(
    "--port",
    type=int,
    default=8501,
    show_default=True,
    help="Port for the local Streamlit server.",
)
@click.option(
    "--no-browser",
    is_flag=True,
    help="Don't auto-open a browser tab; just print the URL.",
)
def ui(port: int, no_browser: bool) -> None:
    """Launch the bindsight web interface in your browser.

    Same app that's deployed on Streamlit Cloud — multi-page, with the demo,
    'run on my data', and 'browse a run' panels. Local-first; no telemetry.
    """
    import subprocess
    import sys as _sys

    repo_root = Path(__file__).parent.parent
    entry = repo_root / "streamlit_app.py"
    if not entry.exists():
        # Editable installs: try CWD as a fallback.
        entry = Path("streamlit_app.py").resolve()
    if not entry.exists():
        console.print(
            Panel(
                "[red]streamlit_app.py not found.[/red] Re-install from the repo root: "
                "[bold]pip install -e .[/bold]",
                title="ui: missing entrypoint",
                border_style="red",
            )
        )
        sys.exit(2)

    cmd = [
        _sys.executable,
        "-m",
        "streamlit",
        "run",
        str(entry),
        "--server.port",
        str(port),
    ]
    if no_browser:
        cmd += ["--server.headless", "true"]

    console.print(
        Panel(
            f"[green]Launching bindsight UI at http://localhost:{port}[/green]\n\n"
            "Stop with Ctrl-C.\n"
            "Auto-deploy a public version: https://share.streamlit.io",
            title="bindsight ui",
            border_style="green",
        )
    )
    try:
        subprocess.run(cmd, check=False)
    except FileNotFoundError:
        console.print(
            Panel(
                "[yellow]Streamlit not installed.[/yellow] Install the report extras:\n"
                '  [bold]pip install -e ".[report]"[/bold]',
                title="Missing dependency",
                border_style="yellow",
            )
        )
        sys.exit(2)


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
    table = Table(
        title="bindsight component licenses (default config)",
        show_lines=False,
        title_style="bold",
    )
    table.add_column("Component", style="cyan", no_wrap=True)
    table.add_column("License")
    table.add_column("Commercial?", style="bold")
    table.add_column("Role")

    rows = [
        ("bindsight", "MIT", "[green]yes[/green]", "this package"),
        ("pydeseq2", "MIT", "[green]yes[/green]", "DEG analysis (default)"),
        ("Open Targets", "CC0 / Apache-2", "[green]yes[/green]", "target evidence"),
        ("HPA", "CC BY-SA 3.0", "[green]yes[/green]", "tissue baselines"),
        ("GTEx (v8 public)", "Open", "[green]yes[/green]", "tissue baselines"),
        ("SURFY", "CC BY", "[green]yes[/green]", "surfaceome filter"),
        ("SURFACE-Bind", "BSD-3", "[green]yes[/green]", "targetable sites"),
        ("AlphaFoldDB", "CC BY 4.0", "[green]yes[/green]", "structures"),
        ("RCSB / PDBe", "CC0 / Open", "[green]yes[/green]", "structures"),
        ("RFdiffusion", "BSD-3", "[green]yes[/green]", "default backbone designer"),
        ("ProteinMPNN", "MIT", "[green]yes[/green]", "sequence design"),
        ("Boltz-2", "MIT (code+weights)", "[green]yes[/green]", "default validator"),
        ("Chai-1r", "Apache-2", "[green]yes[/green]", "alt validator"),
        ("BoltzGen", "MIT (code+weights)", "[green]yes[/green]", "alt designer (v0.2)"),
        ("BindCraft", "MIT", "[green]yes[/green]", "premium designer"),
        ("Snakemake", "MIT", "[green]yes[/green]", "workflow"),
        ("AF2-IG (opt-in)", "AF2 weights NC", "[red]no[/red]", "alt validator (banner)"),
    ]
    for r in rows:
        table.add_row(*r)
    console.print(table)

    if config is not None:
        console.print(f"\n[dim]config audit for {config}:[/dim]")
        # Real audit lands in v0.1; for now a stub.
        console.print("[yellow]Per-config audit not yet implemented.[/yellow]")

    console.print(
        "\n[dim]See LICENSING.md for the full inventory and commercial-use guidance.[/dim]"
    )


# ---------------------------------------------------------------------------
# CLI helpers used by design + validate
# ---------------------------------------------------------------------------
def _count_top_targets(epitopes_parquet: Path) -> int:
    """Count top-N targets from a discover-stage epitopes Parquet, default 5."""
    if not epitopes_parquet.exists():
        return 5
    try:
        import pandas as pd

        return len(pd.read_parquet(epitopes_parquet))
    except Exception:
        return 5


def _count_designs(design_dir: Path) -> int:
    """Count design tarballs / metrics for cost estimation; fall back to 250."""
    if not design_dir.exists():
        return 250
    pdbs = list(design_dir.rglob("*.pdb"))
    return max(1, len(pdbs)) if pdbs else 250


def _print_cost_panel(cost, label: str) -> None:
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
    """Run the full discovery half on the shipped 10-gene synthetic cohort.

    Takes ~30 seconds on a CPU laptop. Produces a real HTML report you can
    open in a browser. Internet not required (Open Targets enrichment is
    skipped; SURFY uses the bundled offline fallback).
    """
    from bindsight.config import RunConfig
    from bindsight.pipelines import discover as discover_pipeline

    _setup_logging(verbose=False)

    # Resolve the bundled config relative to the package install root.
    repo_root = Path(__file__).parent.parent
    cfg_path = repo_root / "examples" / "demo" / "config.yaml"
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
            "Synthetic 10-gene tumor-vs-normal cohort. The pipeline should\n"
            "rediscover ERBB2 (HER2) and EGFR as top antibody-tractable surface\n"
            "antigens. Takes ~30s on a CPU laptop.",
            title="Demo run",
            border_style="cyan",
        )
    )

    cfg = RunConfig.from_yaml(cfg_path)
    cfg.out_dir = out_dir
    # Override input paths to be absolute relative to where the config lives.
    cfg.inputs.counts = (cfg_path.parent / "counts.tsv").resolve()
    cfg.inputs.design = (cfg_path.parent / "design.tsv").resolve()

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
                'not installed; run: pip install -e ".[discover]"',
            )

    # Cache state
    base = cache_dir()
    _row("cache root", base.exists(), str(base))
    surfy_cache = base / "surfy" / "surfy_v1.uniprot.txt"
    _row(
        "SURFY cache",
        surfy_cache.exists(),
        str(surfy_cache)
        if surfy_cache.exists()
        else "missing — using bundled offline fallback (~10 proteins)",
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
            f"env bindsight_SURFACE_BIND_DATA={sb_path}",
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

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
from typing import Any

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

LOG_CLI = logging.getLogger(__name__)

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

    epitopes_parquet = run_dir / "epitopes" / "epitopes.parquet"
    n_targets = _count_top_targets(epitopes_parquet)

    console.print(f"[dim]run-dir:[/dim] {run_dir}")
    console.print(f"[dim]backend:[/dim] {backend}")
    console.print(f"[dim]designer:[/dim] {designer}")
    console.print(f"[dim]validator:[/dim] {validator}")
    console.print(f"[dim]trajectories:[/dim] {trajectories}")
    console.print(f"[dim]targets:[/dim] {n_targets}")

    d_cost, _v_cost, _c_cost = estimate_full_run(
        backend=backend,
        designer=designer,
        validator=validator,
        n_targets=n_targets,
        n_trajectories=trajectories,
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

    launched = _launch_design(
        run_dir, backend=backend, designer=designer, validator=validator, trajectories=trajectories
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

    design_dir = run_dir / "design"
    n_designs = _count_designs(design_dir)
    cost = estimate(backend=backend, stage="validate", plugin=validator, n_units=n_designs)
    _print_cost_panel(cost, label=f"validate ({validator}, {n_designs} designs)")

    # The design step (headless backends) runs design + validation together via
    # the executor, writing per-design metrics into the design tarballs. Here we
    # materialise those into validate/validated.parquet (+ per-binder dirs).
    n = _finalize_validate(run_dir)
    validated = run_dir / "validate" / "validated.parquet"
    if n > 0:
        console.print(
            Panel(
                f"[green]Validated {n} design(s).[/green]\n"
                f"Output: {validated}\nNext: [bold]bindsight rank {run_dir}[/bold]",
                title="validate: ready",
                border_style="green",
            )
        )
        return

    console.print(
        Panel(
            "No design results to validate yet. Run [bold]bindsight design[/bold] on a\n"
            "headless backend (modal/local_docker/kaggle), or for --backend colab open the\n"
            "generated notebook (GPU), download the results tarball into <run>/design/,\n"
            "then re-run this command. See docs/colab-design-howto.md.",
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
# report — self-contained HTML / Streamlit
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
    # Single source of truth: (component, license, commercial?, role).
    # `commercial` is True when the component is usable in commercial work.
    components: list[tuple[str, str, bool, str]] = [
        ("bindsight", "AGPL-3.0-or-later", True, "this package"),
        ("pydeseq2", "MIT", True, "DEG analysis (default)"),
        ("Open Targets", "CC0 / Apache-2", True, "target evidence"),
        ("HPA", "CC BY-SA 3.0", True, "tissue baselines"),
        ("GTEx (v8 public)", "Open", True, "tissue baselines"),
        ("SURFY", "CC BY", True, "surfaceome filter"),
        ("SURFACE-Bind", "BSD-3", True, "targetable sites"),
        ("AlphaFoldDB", "CC BY 4.0", True, "structures"),
        ("RCSB / PDBe", "CC0 / Open", True, "structures"),
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
            "HPA",
            "GTEx (v8 public)",
            "SURFY",
            "SURFACE-Bind",
            "AlphaFoldDB",
            "RCSB / PDBe",
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


def _top_targets(run_dir: Path) -> list[dict[str, Any]]:
    """Return top-N targets (uniprot, structure_path, chain, residues) to design."""
    import pandas as pd

    epitopes_parquet = run_dir / "epitopes" / "epitopes.parquet"
    if not epitopes_parquet.exists():
        return []
    df = pd.read_parquet(epitopes_parquet)
    targets: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        struct = str(row.get("structure_path") or "")
        uni = row.get("uniprot_id")
        if not struct or not uni:
            continue
        residues = row.get("residues")
        residues = list(residues) if residues is not None and len(residues) else []
        targets.append(
            {
                "uniprot": str(uni),
                "structure_path": struct,
                "chain": str(row.get("chain") or "A"),
                "residues": [int(r) for r in residues],
            }
        )
    return targets


def _write_design_notebooks(run_dir: Path, *, designer: str, trajectories: int) -> int:
    """Write one Colab design+validate notebook per top target. Returns count."""
    from bindsight.plugins import get_designer
    from bindsight.runners.notebook_content import write_design_notebook

    design_dir = run_dir / "design"
    design_dir.mkdir(parents=True, exist_ok=True)
    plugin = get_designer(designer)
    n = 0
    for t in _top_targets(run_dir):
        spec = plugin.make_spec(
            target_uniprot=t["uniprot"],
            target_structure_path=Path(t["structure_path"]),
            epitope_residues=t["residues"],
            epitope_chain=t["chain"],
            n_trajectories=trajectories,
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


def _launch_design(
    run_dir: Path, *, backend: str, designer: str, validator: str, trajectories: int
) -> int:
    """Run design+validation for each top target via a headless runner backend."""
    import shutil

    from bindsight.plugins import get_designer, get_runner

    targets = _top_targets(run_dir)
    if not targets:
        return 0
    plugin = get_designer(designer)
    runner = get_runner(backend, designer=designer, n_units_per_target=trajectories)
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
            n_trajectories=trajectories,
        )
        spec = spec.model_copy(
            update={"extra_params": {**spec.extra_params, "validator": validator}}
        )
        result = plugin.submit(spec, runner)
        shutil.copy2(result.results_archive_path, targets_dir / f"{t['uniprot']}.tar.gz")
        mpath = Path(result.metrics_jsonl_path)
        if mpath.exists():
            metrics_lines += [ln for ln in mpath.read_text().splitlines() if ln.strip()]
        launched += 1

    (design_dir / "metrics.jsonl").write_text(
        "\n".join(metrics_lines) + ("\n" if metrics_lines else "")
    )
    # A top-level results.tar.gz marks design completion for `bindsight run`.
    import tarfile

    with tarfile.open(design_dir / "results.tar.gz", "w:gz") as tf:
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
                with tarfile.open(tar_path, "r:gz") as tf:
                    for m in tf.getmembers():
                        if m.name.startswith("validate/"):
                            tf.extract(m, validate_dir.parent, filter="data")
            except (tarfile.TarError, OSError) as e:
                LOG_CLI.warning("could not unpack %s: %s", tar_path, e)

    metrics_path = design_dir / "metrics.jsonl"
    rows = (
        [json.loads(ln) for ln in metrics_path.read_text().splitlines() if ln.strip()]
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
    df.to_parquet(validate_dir / "validated.parquet", index=False)
    return len(df)


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
    """Run the full discovery half on a real TCGA breast-cancer cohort.

    Auto-downloads an authentic TCGA-BRCA tumor-vs-adjacent-normal RNA-seq
    cohort (STAR - Counts) from NIH/GDC on first run, runs real DESeq2, and
    rediscovers ERBB2 (HER2) and EGFR as top antibody-tractable surface
    antigens. Needs network the first time (cohort + SURFY downloaded, then
    cached); takes a few minutes on real data. Produces an HTML report.
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

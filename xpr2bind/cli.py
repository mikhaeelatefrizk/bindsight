"""xpr2bind command-line interface.

The CLI is a thin Click wrapper around the Snakemake DAG. Subcommands map to
``snakemake --until <rule>`` calls so users get nice ergonomics
(``xpr2bind discover ...``) while the actual orchestration stays in
``Snakefile``.

Most commands are stubs in v0.0.x — they print the planned action and exit
with code 2 (not implemented) so callers can detect that we haven't run a real
pipeline. The exceptions are :func:`version` and :func:`verify_licenses`,
which are pure-Python and work today.
"""

from __future__ import annotations

import sys
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from xpr2bind import __version__

console = Console()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _not_implemented(stage: str) -> None:
    """Print a stage-not-yet-implemented banner and exit with code 2."""
    console.print(
        Panel(
            f"[bold yellow]{stage}[/bold yellow] is not implemented in this dev build "
            f"(xpr2bind {__version__}).\n\n"
            "Track progress at https://github.com/mikhaeelatefrizk/xpr2bind/blob/main/CHANGELOG.md",
            title="Not implemented yet",
            border_style="yellow",
        )
    )
    sys.exit(2)


# ---------------------------------------------------------------------------
# Top-level group
# ---------------------------------------------------------------------------
@click.group(
    name="xpr2bind",
    context_settings={"help_option_names": ["-h", "--help"]},
)
@click.version_option(__version__, prog_name="xpr2bind")
def main() -> None:
    """Bridge from RNA-seq to de novo protein binder design.

    See https://github.com/mikhaeelatefrizk/xpr2bind for the manual.
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
    default=5,
    show_default=True,
    help="Number of top-ranked targets to carry forward.",
)
def discover(config: Path, out_dir: Path, top_n: int) -> None:
    """Discover surface antigen targets from RNA-seq counts.

    Runs the discovery half of the pipeline (CPU only):
    DEG → surfaceome filter → SURFACE-Bind site lookup → AlphaFoldDB pull.
    """
    console.print(f"[dim]config:[/dim] {config}")
    console.print(f"[dim]out:[/dim] {out_dir}")
    console.print(f"[dim]top-n:[/dim] {top_n}")
    _not_implemented("discover")


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
    """Generate de novo binder backbones + sequences (offloaded to GPU)."""
    console.print(f"[dim]run-dir:[/dim] {run_dir}")
    console.print(f"[dim]backend:[/dim] {backend}")
    console.print(f"[dim]designer:[/dim] {designer}")
    console.print(f"[dim]trajectories:[/dim] {trajectories}")
    console.print(f"[dim]dry-run:[/dim] {dry_run}")
    _not_implemented("design")


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
    if validator == "af2_ig":
        console.print(
            Panel(
                "[bold red]AF2-IG uses AlphaFold2 weights with a non-commercial license.[/bold red]\n"
                "See LICENSING.md § 3 for details. Default to boltz2 for commercial work.",
                title="License banner",
                border_style="red",
            )
        )
    _not_implemented("validate")


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
    _not_implemented("rank")


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
    """Render the run as a Quarto HTML report or launch the Streamlit dashboard."""
    _not_implemented(f"report ({fmt})")


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
    """Run the full discover → design → validate → rank → report pipeline."""
    _not_implemented("run (full pipeline)")


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
    _not_implemented(f"export ({fmt})")


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
    """Print the license summary for components used by xpr2bind.

    With a config path, audits the components selected by that config and
    flags any non-commercial choices.
    """
    table = Table(
        title="xpr2bind component licenses (default config)",
        show_lines=False,
        title_style="bold",
    )
    table.add_column("Component", style="cyan", no_wrap=True)
    table.add_column("License")
    table.add_column("Commercial?", style="bold")
    table.add_column("Role")

    rows = [
        ("xpr2bind", "MIT", "[green]yes[/green]", "this package"),
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


if __name__ == "__main__":  # pragma: no cover
    main()

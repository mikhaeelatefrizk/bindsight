"""CLI tests for `xpr2bind demo` and `xpr2bind report`."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from click.testing import CliRunner

from xpr2bind.cli import main


def _seed_min_run(run: Path) -> None:
    """Create a minimal valid run directory for `xpr2bind report`."""
    (run / "deg").mkdir(parents=True)
    (run / "targets").mkdir(parents=True)
    (run / "epitopes").mkdir(parents=True)

    pd.DataFrame(
        {
            "gene_id": ["ENSG00000141736"],
            "log2fc": [3.0],
            "padj": [1e-8],
            "significant": [True],
        }
    ).to_parquet(run / "deg" / "results.parquet", index=False)
    pd.DataFrame(
        {
            "rank": [1],
            "symbol": ["ERBB2"],
            "uniprot_id": ["P04626"],
            "log2fc": [3.0],
            "padj": [1e-8],
            "tractable_modalities": ["Antibody"],
            "n_safety_events": [1],
            "has_alphafold_structure": [False],
            "rank_in_top_n": [True],
        }
    ).to_parquet(run / "targets" / "candidates.parquet", index=False)
    pd.DataFrame(
        {
            "symbol": ["ERBB2"],
            "uniprot_id": ["P04626"],
            "structure_path": [""],
            "site_id": [None],
            "epitope_status": ["pending_surface_bind_lookup"],
        }
    ).to_parquet(run / "epitopes" / "epitopes.parquet", index=False)


def test_cli_report_html_renders(tmp_path: Path) -> None:
    run = tmp_path / "run"
    _seed_min_run(run)
    r = CliRunner().invoke(main, ["report", str(run), "--format", "html"])
    assert r.exit_code == 0, r.output
    assert (run / "report.html").exists()
    assert "Report rendered" in r.output


def test_cli_demo_command_runs_to_completion(tmp_path: Path) -> None:
    """Full xpr2bind demo, no skip, against tmp output dir."""
    out = tmp_path / "demo_out"
    r = CliRunner().invoke(main, ["demo", "--out", str(out)])
    assert r.exit_code == 0, r.output
    assert "Demo complete" in r.output
    assert (out / "run_manifest.jsonld").exists()
    assert (out / "report.html").exists()
    # Pipeline should rediscover HER2 + EGFR via the bundled fallback
    candidates = pd.read_parquet(out / "targets" / "candidates.parquet")
    assert "P04626" in set(candidates["uniprot_id"].dropna())
    assert "P00533" in set(candidates["uniprot_id"].dropna())


def test_cli_demo_no_report_skips_html(tmp_path: Path) -> None:
    out = tmp_path / "demo_out"
    r = CliRunner().invoke(main, ["demo", "--out", str(out), "--no-report"])
    assert r.exit_code == 0, r.output
    assert not (out / "report.html").exists()
    assert (out / "run_manifest.jsonld").exists()

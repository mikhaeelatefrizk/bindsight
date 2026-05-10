"""End-to-end test: `xpr2bind demo` runs to completion on the shipped example.

This is the most important integration test in the suite — if it fails,
new users will hit the failure too. Runs the actual discovery pipeline
against the bundled examples/demo data and asserts the expected outputs.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from xpr2bind.config import RunConfig
from xpr2bind.pipelines import discover as discover_pipeline

REPO_ROOT = Path(__file__).parent.parent
EXAMPLES = REPO_ROOT / "examples" / "demo"


@pytest.fixture
def demo_cfg(tmp_path: Path) -> RunConfig:
    """Load the shipped demo config and redirect outputs to tmp_path."""
    cfg = RunConfig.from_yaml(EXAMPLES / "config.yaml")
    cfg.out_dir = tmp_path / "demo_out"
    cfg.inputs.counts = (EXAMPLES / "counts.tsv").resolve()
    cfg.inputs.design = (EXAMPLES / "design.tsv").resolve()
    return cfg


def test_demo_config_validates() -> None:
    """The shipped demo config validates against RunConfig."""
    cfg = RunConfig.from_yaml(EXAMPLES / "config.yaml")
    assert cfg.name == "xpr2bind_demo"
    assert cfg.params.target_discovery.surfy_allow_offline_fallback is True
    assert cfg.params.target_discovery.use_open_targets is False


def test_demo_data_files_present() -> None:
    """counts.tsv and design.tsv ship with the repo."""
    assert (EXAMPLES / "counts.tsv").exists()
    assert (EXAMPLES / "design.tsv").exists()
    assert (EXAMPLES / "config.yaml").exists()


@pytest.mark.slow
def test_demo_runs_end_to_end(demo_cfg: RunConfig, tmp_path: Path) -> None:
    """Real run with real pydeseq2 against the demo cohort.

    Marked slow because pydeseq2's import is slow; the assertions are fast.
    Should take <10 seconds even on a weak laptop.
    """
    out = tmp_path / "demo_out"
    manifest = discover_pipeline.run(demo_cfg, out_dir=out)

    # Manifest sanity
    assert (out / "run_manifest.jsonld").exists()
    assert all(s.status == "completed" for s in manifest.stages), manifest.stages
    assert len(manifest.stages) == 2

    # DEG outputs
    deg = pd.read_parquet(out / "deg" / "results.parquet")
    assert len(deg) == 10
    n_sig = int(deg["significant"].sum())
    assert 4 <= n_sig <= 6, (
        f"expected 4-6 significant DEGs, got {n_sig}: {deg[deg['significant']]['gene_id'].tolist()}"
    )

    # Targets — HER2 and EGFR should be top hits via the bundled ENSG → UniProt fallback
    candidates = pd.read_parquet(out / "targets" / "candidates.parquet")
    survived_uniprots = set(candidates["uniprot_id"].dropna())
    assert "P04626" in survived_uniprots, "HER2 (P04626) should survive demo filters"
    assert "P00533" in survived_uniprots, "EGFR (P00533) should survive demo filters"

    # Top-N flagged
    top = candidates[candidates["rank_in_top_n"]]
    assert len(top) >= 2

    # Epitopes table populated for top-N
    epitopes = pd.read_parquet(out / "epitopes" / "epitopes.parquet")
    assert len(epitopes) >= 2


@pytest.mark.slow
def test_demo_report_renders(demo_cfg: RunConfig, tmp_path: Path) -> None:
    """HTML report renders to a non-empty self-contained file."""
    from xpr2bind.report import render_run

    out = tmp_path / "demo_out"
    discover_pipeline.run(demo_cfg, out_dir=out)
    report_path = render_run(out)

    assert report_path.exists()
    assert report_path.stat().st_size > 5000, "report.html is suspiciously small"
    text = report_path.read_text(encoding="utf-8")
    assert "<title>xpr2bind report" in text
    # Embedded CSS, not a stylesheet link
    assert ":root {" in text
    # PNG volcano embedded as base64
    assert "data:image/png;base64," in text
    # KPI section rendered
    assert "candidates" in text.lower()
    # Provenance table rendered
    assert "provenance" in text.lower()


def test_manifest_jsonld_is_valid_json(demo_cfg: RunConfig, tmp_path: Path, monkeypatch) -> None:
    """The manifest emitted by the pipeline parses as valid JSON-LD."""
    # Mock pydeseq2 so this test is fast and runs in the default ('not slow') gate.
    fake_deg = pd.DataFrame(
        {
            "log2FoldChange": [3.5, 0.1, -3.0, 4.0, 2.0, 0.0, -2.5, 0.05, 1.5, 0.0],
            "lfcSE": [0.5] * 10,
            "stat": [7.0, 0.2, -6.0, 8.0, 4.0, 0.0, -5.0, 0.1, 3.0, 0.0],
            "pvalue": [1e-10, 0.8, 1e-9, 1e-11, 1e-7, 0.99, 1e-8, 0.95, 1e-5, 0.99],
            "padj": [1e-9, 0.95, 1e-8, 1e-10, 1e-6, 0.99, 1e-7, 0.95, 1e-4, 0.99],
            "baseMean": [800, 500, 1500, 1000, 700, 280, 250, 240, 1300, 240],
        },
        index=[
            "ENSG00000141736",
            "ENSG00000146648",
            "ENSG00000091831",
            "ENSG00000142208",
            "ENSG00000118260",
            "ENSG00000074706",
            "ENSG00000196712",
            "ENSG00000133703",
            "ENSG00000174775",
            "ENSG00000129965",
        ],
    )
    from unittest.mock import patch

    with patch(
        "xpr2bind.deg.pydeseq2_runner.PyDESeq2Runner._run_pydeseq2",
        return_value=fake_deg,
    ):
        out = tmp_path / "demo_out"
        discover_pipeline.run(demo_cfg, out_dir=out)
        manifest = json.loads((out / "run_manifest.jsonld").read_text(encoding="utf-8"))

    assert "@context" in manifest
    assert "stages" in manifest
    assert manifest["stages"][0]["name"] == "deg"

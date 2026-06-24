"""End-to-end test: `bindsight demo` runs to completion on a real-data cohort.

The demo now runs on a real TCGA-BRCA cohort auto-downloaded from NIH/GDC. To
keep this integration test fast and offline, the network seams are mocked:
``gdc.fetch_cohort`` writes a small real-format cohort (HER2/EGFR up in tumor),
the AlphaFoldDB client is stubbed, and SURFY uses the bundled offline fallback.
The real-data *code path* (auto-download wiring + discover) is exercised exactly
as in production.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from bindsight.config import RunConfig
from bindsight.pipelines import discover as discover_pipeline

REPO_ROOT = Path(__file__).parent.parent
EXAMPLES = REPO_ROOT / "examples" / "demo"


@pytest.fixture
def demo_cfg(tmp_path: Path) -> RunConfig:
    """Load the shipped demo config; redirect outputs + cohort cache to tmp."""
    cfg = RunConfig.from_yaml(EXAMPLES / "config.yaml")
    cfg.out_dir = tmp_path / "demo_out"
    cfg.inputs.counts = tmp_path / "cache" / "counts.tsv.gz"
    cfg.inputs.design = tmp_path / "cache" / "design.tsv"
    return cfg


def test_demo_config_validates() -> None:
    """The shipped demo config validates and is wired for real TCGA-BRCA data."""
    cfg = RunConfig.from_yaml(EXAMPLES / "config.yaml")
    assert cfg.name == "bindsight_demo_tcga_brca"
    assert cfg.inputs.download is not None
    assert cfg.inputs.download.project == "TCGA-BRCA"
    assert cfg.inputs.download.n_tumor >= 2
    assert cfg.params.target_discovery.require_surfy is True


def test_demo_no_synthetic_data_files() -> None:
    """The fabricated synthetic counts/design must be gone (no residue)."""
    assert not (EXAMPLES / "counts.tsv").exists()
    assert not (EXAMPLES / "design.tsv").exists()
    assert (EXAMPLES / "config.yaml").exists()


def test_demo_runs_end_to_end(offline_real_data, demo_cfg: RunConfig, tmp_path: Path) -> None:
    """Real pydeseq2 run via the auto-download code path; HER2 + EGFR rediscovered."""
    out = tmp_path / "demo_out"
    manifest = discover_pipeline.run(demo_cfg, out_dir=out)

    assert (out / "run_manifest.jsonld").exists()
    assert all(s.status == "completed" for s in manifest.stages), manifest.stages
    assert len(manifest.stages) == 2

    deg = pd.read_parquet(out / "deg" / "results.parquet")
    assert int(deg["significant"].sum()) >= 2

    candidates = pd.read_parquet(out / "targets" / "candidates.parquet")
    survived = set(candidates["uniprot_id"].dropna())
    assert "P04626" in survived, "HER2 (P04626) should survive demo filters"
    assert "P00533" in survived, "EGFR (P00533) should survive demo filters"

    epitopes = pd.read_parquet(out / "epitopes" / "epitopes.parquet")
    assert len(epitopes) >= 2

    # The discover stage records the honest scientific caveats in its manifest notes.
    discover_stage = next(s for s in manifest.stages if s.name == "discover")
    assert "caveats:" in (discover_stage.notes or ""), discover_stage.notes


def test_demo_report_renders(offline_real_data, demo_cfg: RunConfig, tmp_path: Path) -> None:
    """HTML report renders to a non-empty self-contained file."""
    from bindsight.report import render_run

    out = tmp_path / "demo_out"
    discover_pipeline.run(demo_cfg, out_dir=out)
    report_path = render_run(out)

    assert report_path.exists()
    assert report_path.stat().st_size > 5000, "report.html is suspiciously small"
    text = report_path.read_text(encoding="utf-8")
    assert "<title>bindsight report" in text
    assert ":root {" in text
    assert "data:image/png;base64," in text
    assert "candidates" in text.lower()
    assert "provenance" in text.lower()
    # Honest limitations are surfaced to the user in every report.
    assert "Limitations" in text
    assert "cell-surface protein abundance" in text


def test_manifest_jsonld_is_valid_json(
    offline_real_data, demo_cfg: RunConfig, tmp_path: Path
) -> None:
    """The manifest emitted by the pipeline parses as valid JSON-LD."""
    out = tmp_path / "demo_out"
    discover_pipeline.run(demo_cfg, out_dir=out)
    manifest = json.loads((out / "run_manifest.jsonld").read_text(encoding="utf-8"))

    assert "@context" in manifest
    assert "stages" in manifest
    assert manifest["stages"][0]["name"] == "deg"

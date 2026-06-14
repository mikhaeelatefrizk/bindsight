"""End-to-end test of the Snakemake front-end.

Runs the real Snakemake DAG (discover → design → validate → rank → report →
manifest) on the tiny fixtures with the ``mock`` GPU backend, and asserts the
expected artifacts are produced. Marked ``slow`` (it shells out to Snakemake and
touches the network for AlphaFoldDB), so CI's ``-m "not gpu and not slow"`` gate
skips it; run locally with ``pytest -m slow``.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.slow

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"

_SMOKE_CONFIG = """\
name: snakemake_smoke
out_dir: {out}
inputs:
  counts: {counts}
  design: {design}
params:
  deg: {{design_formula: "~ condition", contrast: [condition, tumor, normal],
        fdr_threshold: 0.5, log2fc_threshold: 0.5, min_replicates: 2, min_count: 0}}
  target_discovery: {{require_surfy: true, surfy_allow_offline_fallback: true,
        use_open_targets: false, require_tractable_modality: [], max_safety_events: 100,
        require_surface_bind_site: false, top_n: 3}}
  design: {{designer: rfdiff_mpnn, n_trajectories: 2, binder_length_min: 50,
        binder_length_max: 100, seed: 42}}
  validate: {{validator: boltz2, iptm_threshold: 0.65, pae_interaction_threshold: 8.0}}
  rank: {{weights: {{log2fc_specificity: 0.25, iptm: 0.30, affinity: 0.30,
        sequence_recovery: 0.15}}}}
backend: mock
cheap_profile: false
"""


def test_snakemake_dag_end_to_end(tmp_path: Path) -> None:
    pytest.importorskip("snakemake")

    out = tmp_path / "run"
    cfg = tmp_path / "smoke.yaml"
    cfg.write_text(
        _SMOKE_CONFIG.format(
            out=out,
            counts=FIXTURES / "tiny_counts.tsv",
            design=FIXTURES / "tiny_design.tsv",
        )
    )
    proc = subprocess.run(
        [sys.executable, "-m", "snakemake", "--configfile", str(cfg), "--cores", "1"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr[-3000:]
    # The same artifacts the CLI produces.
    assert (out / "report.html").exists()
    assert (out / "run_manifest.jsonld").exists()
    assert (out / "rank" / "ranking.parquet").exists()
    assert (out / "validate" / "validated.parquet").exists()

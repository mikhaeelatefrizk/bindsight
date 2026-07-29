# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""End-to-end test of the Snakemake front-end.

Runs the real DAG (deg → discover → design → validate → rank → manifest →
report) on the tiny fixtures with the ``mock`` GPU backend.

This used to be ``slow``-marked and therefore skipped in CI, and that gap was
expensive: ``scripts/run_discover.py`` called ``_do_discover()`` with six of its
eight required keyword-only arguments for roughly five weeks, so the DAG raised
``TypeError`` before doing any work while ``ARCHITECTURE.md`` claimed
``bindsight run <cfg> ≡ snakemake``. Nothing noticed.

It now runs offline and in CI. Hermeticity comes from ``BINDSIGHT_CACHE_DIR``:
the DAG runs in a subprocess (and each rule in another one), so ``conftest``'s
``monkeypatch``-based offline fixture cannot reach it, and ``XDG_CACHE_HOME``
is ignored by platformdirs on macOS. Seeding a temporary cache with a SURFY
list and AlphaFold models is the one approach that works on every platform.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"

# The two accessions in tests/fixtures/tiny_counts.tsv that reach structure
# fetching: ERBB2 and EGFR.
SEEDED_ACCESSIONS = ("P04626", "P00533")

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

# A minimal but genuinely parseable mmCIF: three CA atoms with B-factors, which
# is what structures/plddt.mean_plddt reads. Downloading the real model would
# reintroduce the network dependency this test exists to remove.
_MINIMAL_CIF = """\
data_model
_entry.id model
loop_
_atom_site.group_PDB
_atom_site.id
_atom_site.type_symbol
_atom_site.label_atom_id
_atom_site.label_alt_id
_atom_site.label_comp_id
_atom_site.label_seq_id
_atom_site.auth_seq_id
_atom_site.pdbx_PDB_ins_code
_atom_site.label_asym_id
_atom_site.Cartn_x
_atom_site.Cartn_y
_atom_site.Cartn_z
_atom_site.occupancy
_atom_site.label_entity_id
_atom_site.auth_asym_id
_atom_site.auth_comp_id
_atom_site.B_iso_or_equiv
_atom_site.pdbx_PDB_model_num
ATOM 1 C CA . GLY 1 1 ? A 0.000 0.000 0.000 1.00 1 A GLY 92.50 1
ATOM 2 C CA . ALA 2 2 ? A 3.800 0.000 0.000 1.00 1 A ALA 91.00 1
ATOM 3 C CA . SER 3 3 ? A 7.600 0.000 0.000 1.00 1 A SER 90.25 1
#
"""


@pytest.fixture(scope="module")
def offline_cache(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Seed a cache so the DAG needs no network, and return its root."""
    cache = tmp_path_factory.mktemp("cache")

    surfy = cache / "surfy"
    surfy.mkdir(parents=True)
    (surfy / "surfy_v1.uniprot.txt").write_text(
        "# seeded for the offline DAG test\n" + "\n".join(SEEDED_ACCESSIONS) + "\n",
        encoding="utf-8",
    )

    afdb = cache / "alphafolddb"
    afdb.mkdir(parents=True)
    for acc in SEEDED_ACCESSIONS:
        (afdb / f"AF-{acc}-F1-model_v6.cif").write_text(_MINIMAL_CIF, encoding="utf-8")

    return cache


def _run_dag(cfg: Path, cache: Path) -> subprocess.CompletedProcess[str]:
    """Invoke the real Snakemake DAG in a subprocess."""
    env = {
        **os.environ,
        "BINDSIGHT_CACHE_DIR": str(cache),
        # Belt and braces: no rule should reach the network, and a stray proxy
        # would otherwise let a regression hide.
        "no_proxy": "*",
        "NO_PROXY": "*",
    }
    return subprocess.run(
        [sys.executable, "-m", "snakemake", "--configfile", str(cfg), "--cores", "1"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


@pytest.fixture(scope="module")
def dag_run(tmp_path_factory: pytest.TempPathFactory, offline_cache: Path) -> Path:
    """Run the DAG once for the whole module and return the run directory.

    Module-scoped deliberately: the DAG takes ~14 s, and re-running it per
    assertion would put a minute of pure duplication into every CI job.
    """
    pytest.importorskip("snakemake")
    if sys.platform.startswith("win"):
        pytest.skip("Snakemake's Windows support is unreliable; covered on Linux")

    tmp_path = tmp_path_factory.mktemp("dag")
    out = tmp_path / "run"
    cfg = tmp_path / "smoke.yaml"
    cfg.write_text(
        _SMOKE_CONFIG.format(
            out=out,
            counts=FIXTURES / "tiny_counts.tsv",
            design=FIXTURES / "tiny_design.tsv",
        ),
        encoding="utf-8",
    )
    proc = _run_dag(cfg, offline_cache)
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-4000:]
    return out


def test_dag_produces_the_same_artifacts_as_the_cli(dag_run: Path) -> None:
    """The Snakemake front-end yields what the CLI yields."""
    for rel in (
        "report.html",
        "run_manifest.jsonld",
        "rank/ranking.parquet",
        "validate/validated.parquet",
        "targets/candidates.parquet",
        "epitopes/epitopes.parquet",
        "taxonomy/failure_taxonomy.parquet",
    ):
        assert (dag_run / rel).exists(), f"missing {rel}"


def test_manifest_records_real_provenance(dag_run: Path) -> None:
    """Snakemake manifests carry digests, not just stage names.

    They used to have empty ``inputs``/``outputs`` and no sha256 anywhere, while
    the assembler's docstring claimed it emitted what the CLI does.
    """
    manifest = json.loads((dag_run / "run_manifest.jsonld").read_text(encoding="utf-8"))
    stages = {s["name"]: s for s in manifest["stages"]}

    assert {"deg", "discover", "rank"} <= set(stages)

    deg = stages["deg"]
    assert deg["tool"]["name"] == "pydeseq2"
    assert len(deg["inputs"]) == 2, "counts and design should both be recorded"
    assert deg["outputs"], "the DEG table should be recorded as an output"
    assert deg["params"], "stage params should be recorded"
    for ref in [*deg["inputs"], *deg["outputs"]]:
        assert len(ref["sha256"]) == 64
    assert deg["ended_at"], "stage timings should be real"

    discover = stages["discover"]
    roles = {o["role"] for o in discover["outputs"]}
    assert {"candidates", "epitopes", "failure_taxonomy"} <= roles


def test_report_has_a_populated_provenance_section(dag_run: Path) -> None:
    """The report renders after the manifest exists, so provenance is filled in.

    The manifest used to be assembled last, so every Snakemake report shipped
    with an empty provenance table.
    """
    html = (dag_run / "report.html").read_text(encoding="utf-8")
    assert "No manifest stages found" not in html
    assert "pydeseq2" in html


def test_report_stage_reaches_the_manifest(dag_run: Path) -> None:
    """The terminal stage still gets recorded despite rendering after assembly."""
    manifest = json.loads((dag_run / "run_manifest.jsonld").read_text(encoding="utf-8"))
    assert "report" in {s["name"] for s in manifest["stages"]}


def test_rank_weights_from_config_are_applied(dag_run: Path) -> None:
    """Custom rank weights are honoured, not silently dropped.

    ``scripts/run_rank.py`` never passed ``weights``, so the Snakefile's
    ``params.rank`` block was ignored while the CLI honoured it.
    """
    manifest = json.loads((dag_run / "run_manifest.jsonld").read_text(encoding="utf-8"))
    rank = next(s for s in manifest["stages"] if s["name"] == "rank")
    weights = rank["params"]["weights"]
    assert weights["log2fc_specificity"] == pytest.approx(0.25)
    assert weights["iptm"] == pytest.approx(0.30)

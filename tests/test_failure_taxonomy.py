"""Negative-result taxonomy: every DEG gene gets exactly one disposition.

The funnel is exhaustive — the per-disposition counts must sum to the total DEG
gene count, so no gene's fate is silently dropped.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pandas as pd

from bindsight.config import RunConfig
from bindsight.pipelines import discover as discover_pipeline
from bindsight.pipelines.discover import TAXONOMY_DISPOSITIONS
from bindsight.structures.topology import Topology
from bindsight.targets.open_targets import TargetEvidence


class _FakeOpenTargets:
    def __init__(self, mapping: dict[str, TargetEvidence]) -> None:
        self.mapping = mapping

    def get_target(self, ensembl_id: str) -> TargetEvidence | None:
        return self.mapping.get(ensembl_id)


class _FakeAlphaFoldDB:
    def __init__(self, mapping: dict[str, Path | None]) -> None:
        self.mapping = mapping

    def fetch(self, uniprot_id: str) -> Path | None:
        return self.mapping.get(uniprot_id)


class _FakeTopology:
    def __init__(self, mapping: dict[str, Topology | None]) -> None:
        self.mapping = mapping

    def fetch(self, uniprot_id: str) -> Topology | None:
        return self.mapping.get(uniprot_id)


def _evidence(gene_id: str, uniprot: str, symbol: str) -> TargetEvidence:
    return TargetEvidence(
        ensembl_id=gene_id,
        symbol=symbol,
        name=symbol,
        biotype="protein_coding",
        uniprot_ids=[uniprot],
        tractability_modalities=["Antibody"],
        safety_event_count=1,
    )


def _cfg(tmp_path: Path, fixtures_dir: Path) -> RunConfig:
    return RunConfig.model_validate(
        {
            "name": "tax",
            "out_dir": str(tmp_path / "out"),
            "inputs": {
                "counts": str(fixtures_dir / "tiny_counts.tsv"),
                "design": str(fixtures_dir / "tiny_design.tsv"),
            },
            "params": {
                "deg": {
                    "design_formula": "~ condition",
                    "contrast": ["condition", "tumor", "normal"],
                    "fdr_threshold": 0.5,
                    "log2fc_threshold": 0.5,
                    "min_replicates": 2,
                    "min_count": 0,
                },
                "target_discovery": {
                    "require_surfy": True,
                    "surfy_allow_offline_fallback": True,
                    "use_open_targets": True,
                    "require_tractable_modality": ["Antibody"],
                    "max_safety_events": 5,
                    "require_surface_bind_site": False,
                    "top_n": 3,
                },
            },
            "backend": "mock",
        }
    )


def test_failure_taxonomy_is_exhaustive(tmp_path: Path, fixtures_dir: Path) -> None:
    cfg = _cfg(tmp_path, fixtures_dir)
    out = tmp_path / "out"

    fake_deg = pd.DataFrame(
        {
            "log2FoldChange": [3.5, -3.0, 0.1, 4.0, -2.5],
            "lfcSE": [0.5] * 5,
            "stat": [7.0, -6.0, 0.2, 8.0, -5.0],
            "pvalue": [1e-10, 1e-9, 0.8, 1e-11, 1e-8],
            "padj": [1e-9, 1e-8, 0.95, 1e-10, 1e-7],
            "baseMean": [800, 1500, 300, 1000, 600],
        },
        index=[
            "ENSG00000141736",  # ERBB2 — surface + structure + top-N → surfaced
            "ENSG00000146648",  # EGFR — candidate but no AlphaFold structure here
            "ENSG00000142208",  # AKT1 — not significant
            "ENSG00000119535",  # CSF3R — no Open Targets record (dropped upstream)
            "ENSG00000147889",  # CDKN2A — significant but no UniProt mapping
        ],
    )
    ot = _FakeOpenTargets(
        {
            "ENSG00000141736": _evidence("ENSG00000141736", "P04626", "ERBB2"),
            "ENSG00000146648": _evidence("ENSG00000146648", "P00533", "EGFR"),
            "ENSG00000147889": TargetEvidence(
                ensembl_id="ENSG00000147889",
                symbol="CDKN2A",
                uniprot_ids=[],
                tractability_modalities=[],
            ),
        }
    )
    struct = tmp_path / "s.cif"
    struct.write_text("# cif\n")
    afdb = _FakeAlphaFoldDB({"P04626": struct, "P00533": None})

    with patch(
        "bindsight.deg.pydeseq2_runner.PyDESeq2Runner._run_pydeseq2",
        return_value=fake_deg,
    ):
        discover_pipeline.run(
            cfg,
            out_dir=out,
            open_targets_client=ot,
            alphafolddb_client=afdb,
            surfy=frozenset({"P04626", "P00533"}),
        )

    tax_path = out / "taxonomy" / "failure_taxonomy.parquet"
    assert tax_path.exists()
    tax = pd.read_parquet(tax_path)
    deg = pd.read_parquet(out / "deg" / "results.parquet")

    # Exhaustive: one disposition per DEG gene; counts sum to the total.
    assert len(tax) == len(deg) == 5
    assert int(tax["disposition"].value_counts().sum()) == len(tax)
    assert set(tax["disposition"]).issubset(set(TAXONOMY_DISPOSITIONS))

    disp = dict(zip(tax["gene_id"], tax["disposition"], strict=True))
    assert disp["ENSG00000141736"] == "surfaced"  # ERBB2
    assert disp["ENSG00000142208"] == "not_significant"  # AKT1
    assert disp["ENSG00000147889"] == "no_uniprot"  # CDKN2A (no UniProt)
    assert disp["ENSG00000146648"] == "no_alphafold_model"  # EGFR (no structure here)


def test_low_confidence_structure_disposition(tmp_path: Path, fixtures_dir: Path) -> None:
    """An AlphaFold model below the pLDDT gate → low_confidence_structure, not surfaced."""
    cfg = _cfg(tmp_path, fixtures_dir)
    # Gate at 70; the fixture model's mean pLDDT is 55 (mostly disordered).
    cfg.params.target_discovery.min_mean_plddt = 70.0
    out = tmp_path / "out"

    fake_deg = pd.DataFrame(
        {
            "log2FoldChange": [3.5],
            "lfcSE": [0.5],
            "stat": [7.0],
            "pvalue": [1e-10],
            "padj": [1e-9],
            "baseMean": [800],
        },
        index=["ENSG00000141736"],  # ERBB2
    )
    ot = _FakeOpenTargets({"ENSG00000141736": _evidence("ENSG00000141736", "P04626", "ERBB2")})
    disordered = Path(__file__).parent / "fixtures" / "plddt" / "AF-TEST1-F1-model_v6.cif"
    afdb = _FakeAlphaFoldDB({"P04626": disordered})

    with patch(
        "bindsight.deg.pydeseq2_runner.PyDESeq2Runner._run_pydeseq2",
        return_value=fake_deg,
    ):
        discover_pipeline.run(
            cfg,
            out_dir=out,
            open_targets_client=ot,
            alphafolddb_client=afdb,
            surfy=frozenset({"P04626"}),
        )

    tax = pd.read_parquet(out / "taxonomy" / "failure_taxonomy.parquet")
    disp = dict(zip(tax["gene_id"], tax["disposition"], strict=True))
    assert disp["ENSG00000141736"] == "low_confidence_structure"

    candidates = pd.read_parquet(out / "targets" / "candidates.parquet")
    erbb2 = candidates[candidates["uniprot_id"] == "P04626"].iloc[0]
    assert erbb2["mean_plddt"] == 55.0  # real value parsed from the fixture
    assert bool(erbb2["low_confidence_structure"]) is True
    assert bool(erbb2["has_alphafold_structure"]) is False  # gated out of design


def _single_erbb2_deg() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "log2FoldChange": [3.5],
            "lfcSE": [0.5],
            "stat": [7.0],
            "pvalue": [1e-10],
            "padj": [1e-9],
            "baseMean": [800],
        },
        index=["ENSG00000141736"],  # ERBB2
    )


def test_no_extracellular_domain_disposition(tmp_path: Path, fixtures_dir: Path) -> None:
    """With the topology gate on, a candidate lacking an extracellular domain is dropped."""
    cfg = _cfg(tmp_path, fixtures_dir)
    cfg.params.target_discovery.use_uniprot_topology = True
    cfg.params.target_discovery.require_extracellular_domain = True
    out = tmp_path / "out"

    ot = _FakeOpenTargets({"ENSG00000141736": _evidence("ENSG00000141736", "P04626", "ERBB2")})
    struct = tmp_path / "s.cif"
    struct.write_text("# cif\n")
    afdb = _FakeAlphaFoldDB({"P04626": struct})
    # Topology with NO extracellular domain (only a cytoplasmic stretch).
    topo = _FakeTopology({"P04626": Topology("P04626", (), ((10, 30),), None)})

    with patch(
        "bindsight.deg.pydeseq2_runner.PyDESeq2Runner._run_pydeseq2",
        return_value=_single_erbb2_deg(),
    ):
        discover_pipeline.run(
            cfg,
            out_dir=out,
            open_targets_client=ot,
            alphafolddb_client=afdb,
            topology_client=topo,
            surfy=frozenset({"P04626"}),
        )

    tax = pd.read_parquet(out / "taxonomy" / "failure_taxonomy.parquet")
    disp = dict(zip(tax["gene_id"], tax["disposition"], strict=True))
    assert disp["ENSG00000141736"] == "no_extracellular_domain"

    cands = pd.read_parquet(out / "targets" / "candidates.parquet")
    erbb2 = cands[cands["uniprot_id"] == "P04626"].iloc[0]
    assert bool(erbb2["has_extracellular_domain"]) is False


def test_topology_annotates_ecd_for_design(tmp_path: Path, fixtures_dir: Path) -> None:
    """With topology on (gate off), the ECD is annotated and used as the design region."""
    cfg = _cfg(tmp_path, fixtures_dir)
    cfg.params.target_discovery.use_uniprot_topology = True  # gate stays off
    out = tmp_path / "out"

    ot = _FakeOpenTargets({"ENSG00000141736": _evidence("ENSG00000141736", "P04626", "ERBB2")})
    struct = tmp_path / "s.cif"
    struct.write_text("# cif\n")
    afdb = _FakeAlphaFoldDB({"P04626": struct})
    topo = _FakeTopology({"P04626": Topology("P04626", ((23, 652),), ((653, 675),), (1, 22))})

    with patch(
        "bindsight.deg.pydeseq2_runner.PyDESeq2Runner._run_pydeseq2",
        return_value=_single_erbb2_deg(),
    ):
        discover_pipeline.run(
            cfg,
            out_dir=out,
            open_targets_client=ot,
            alphafolddb_client=afdb,
            topology_client=topo,
            surfy=frozenset({"P04626"}),
        )

    cands = pd.read_parquet(out / "targets" / "candidates.parquet")
    erbb2 = cands[cands["uniprot_id"] == "P04626"].iloc[0]
    assert bool(erbb2["has_extracellular_domain"]) is True
    assert list(erbb2["extracellular_ranges"][0]) == [23, 652]

    epitopes = pd.read_parquet(out / "epitopes" / "epitopes.parquet")
    erow = epitopes[epitopes["uniprot_id"] == "P04626"].iloc[0]
    # whole-surface fallback targets the ECD, not the whole chain
    assert list(erow["design_ranges"][0]) == [23, 652]

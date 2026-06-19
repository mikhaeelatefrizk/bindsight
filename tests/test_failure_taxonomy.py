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

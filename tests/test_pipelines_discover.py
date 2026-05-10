"""End-to-end test of the discovery pipeline against tiny fixtures + fakes."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pandas as pd

from bindsight.config import RunConfig
from bindsight.pipelines import discover as discover_pipeline
from bindsight.targets.open_targets import TargetEvidence


def _fake_evidence(gene_id: str, uniprot: str, symbol: str) -> TargetEvidence:
    return TargetEvidence(
        ensembl_id=gene_id,
        symbol=symbol,
        name=symbol,
        biotype="protein_coding",
        uniprot_ids=[uniprot],
        tractability_modalities=["Antibody"],
        safety_event_count=1,
        top_disease_associations=[
            {
                "score": 0.9,
                "disease_id": "EFO_0000305",
                "disease_name": "lung adenocarcinoma",
                "therapeutic_areas": ["neoplasm"],
            }
        ],
    )


class _FakeOpenTargets:
    """Minimal stand-in for OpenTargetsClient used in tests."""

    def __init__(self, mapping: dict[str, TargetEvidence]) -> None:
        self.mapping = mapping
        self.calls: list[str] = []

    def get_target(self, ensembl_id: str) -> TargetEvidence | None:
        self.calls.append(ensembl_id)
        return self.mapping.get(ensembl_id)


class _FakeAlphaFoldDB:
    """Returns canned local paths instead of hitting EBI."""

    def __init__(self, mapping: dict[str, Path | None]) -> None:
        self.mapping = mapping
        self.calls: list[str] = []

    def fetch(self, uniprot_id: str) -> Path | None:
        self.calls.append(uniprot_id)
        return self.mapping.get(uniprot_id)


def _build_cfg(tmp_path: Path, fixtures_dir: Path) -> RunConfig:
    out = tmp_path / "out"
    return RunConfig.model_validate(
        {
            "name": "tiny",
            "out_dir": str(out),
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


def test_discover_pipeline_end_to_end(tmp_path: Path, fixtures_dir: Path) -> None:
    """Run the discovery half end-to-end with mocked pydeseq2 + Open Targets + AFDB."""
    cfg = _build_cfg(tmp_path, fixtures_dir)
    out = tmp_path / "out"

    # Mock pydeseq2 so we don't pay its import cost or stochastic reproducibility headaches.
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
            "ENSG00000141736",  # ERBB2 (HER2)
            "ENSG00000146648",  # EGFR
            "ENSG00000142208",  # AKT1 — non-significant log2fc
            "ENSG00000119535",  # CSF3R — won't get an Open Targets record
            "ENSG00000147889",  # CDKN2A — significant but no UniProt mapping
        ],
    )

    fake_evidence = {
        "ENSG00000141736": _fake_evidence("ENSG00000141736", "P04626", "ERBB2"),
        "ENSG00000146648": _fake_evidence("ENSG00000146648", "P00533", "EGFR"),
        # ENSG00000119535: deliberately missing from Open Targets
        "ENSG00000147889": TargetEvidence(
            ensembl_id="ENSG00000147889",
            symbol="CDKN2A",
            uniprot_ids=[],  # no UniProt mapping
            tractability_modalities=[],
        ),
    }
    fake_ot = _FakeOpenTargets(fake_evidence)

    fake_struct = tmp_path / "fake_struct.cif"
    fake_struct.write_text("# fake mmCIF\n")
    fake_afdb = _FakeAlphaFoldDB({"P04626": fake_struct, "P00533": None})

    with patch(
        "bindsight.deg.pydeseq2_runner.PyDESeq2Runner._run_pydeseq2",
        return_value=fake_deg,
    ):
        manifest = discover_pipeline.run(
            cfg,
            out_dir=out,
            open_targets_client=fake_ot,
            alphafolddb_client=fake_afdb,
            surfy=frozenset({"P04626", "P00533"}),
        )

    # ---- manifest sanity ----
    assert (out / "run_manifest.jsonld").exists()
    assert len(manifest.stages) == 2
    assert all(s.status == "completed" for s in manifest.stages), manifest.stages

    # ---- DEG output ----
    deg_path = out / "deg" / "results.parquet"
    assert deg_path.exists()
    deg_df = pd.read_parquet(deg_path)
    assert deg_df["significant"].sum() == 4  # four of five rows pass the lenient thresholds

    # ---- targets ----
    candidates_path = out / "targets" / "candidates.parquet"
    assert candidates_path.exists()
    candidates_df = pd.read_parquet(candidates_path)
    # ERBB2 and EGFR survive the surfaceome + tractability + safety filters.
    assert set(candidates_df["uniprot_id"]) == {"P04626", "P00533"}
    assert candidates_df["has_alphafold_structure"].sum() == 1  # only P04626 has a "structure"

    # ---- epitopes ----
    epitopes_path = out / "epitopes" / "epitopes.parquet"
    assert epitopes_path.exists()
    epitopes_df = pd.read_parquet(epitopes_path)
    assert all(epitopes_df["epitope_status"] == "pending_surface_bind_lookup")
    assert len(epitopes_df) == 2  # both top-N candidates


def test_discover_records_failure_when_inputs_missing(tmp_path: Path) -> None:
    """If counts/design don't exist, the DEG stage marks failed and pipeline stops cleanly."""
    cfg = RunConfig.model_validate(
        {
            "name": "missing",
            "out_dir": str(tmp_path / "out"),
            "inputs": {
                "counts": str(tmp_path / "DOES_NOT_EXIST_counts.tsv"),
                "design": str(tmp_path / "DOES_NOT_EXIST_design.tsv"),
            },
            "params": {
                "deg": {
                    "design_formula": "~ condition",
                    "contrast": ["condition", "t", "n"],
                }
            },
        }
    )
    manifest = discover_pipeline.run(cfg, out_dir=tmp_path / "out")
    assert len(manifest.stages) == 1
    assert manifest.stages[0].status == "failed"
    assert manifest.stages[0].name == "deg"
    assert "missing input" in (manifest.stages[0].error or "").lower()

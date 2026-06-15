"""Tests for the rediscovery-validation harness (pure logic, no network)."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

import pandas as pd

from bindsight.benchmark import rediscovery as R


def _result(cohort: R.Cohort, rank: int | None, log2fc: float, padj: float, sig: bool) -> dict:
    ex = (
        None
        if rank is None
        else {
            "symbol": cohort.expected_symbol,
            "uniprot": cohort.expected_uniprot,
            "found": True,
            "rank": rank,
            "log2fc": log2fc,
            "padj": padj,
        }
    )
    deg_expected = {"tested": True, "log2fc": log2fc, "padj": padj, "significant": sig}
    return {
        "cohort": asdict(cohort),
        "n_tumor": cohort.n_tumor,
        "n_normal": cohort.n_normal,
        "n_candidates": 40,
        "deg": {"n_genes_tested": 18000, "n_significant": 3000},
        "deg_expected": deg_expected,
        "expected": ex,
        "category": R._categorise(deg_expected, cohort.n_normal),
        "gdc_provenance": {"n_tumor": cohort.n_tumor, "n_normal": cohort.n_normal},
        "run_dir": "/tmp/none",
    }


def test_default_cohorts_have_one_negative_control() -> None:
    pos = [c for c in R.VALIDATION_COHORTS if c.expectation == "positive"]
    neg = [c for c in R.VALIDATION_COHORTS if c.expectation == "negative_control"]
    assert len(pos) == 3
    assert [c.expected_symbol for c in neg] == ["EGFR"]


def test_categorise_rules() -> None:
    # Over-expressed: significant and log2fc >= threshold, enough normals.
    assert R._categorise({"tested": True, "log2fc": 4.0, "significant": True}, 40) == "over_expressed"
    # Not over-expressed: not significant (clinical fame ≠ over-expression).
    assert (
        R._categorise({"tested": True, "log2fc": 0.4, "significant": False}, 40)
        == "not_over_expressed"
    )
    # Underpowered: too few normals trumps everything.
    assert R._categorise({"tested": True, "log2fc": 2.3, "significant": False}, 4) == "underpowered"
    assert R._categorise({"tested": False}, 40) == "not_tested"


def test_aggregate_recall_over_overexpressed_only() -> None:
    C = {c.key: c for c in R.VALIDATION_COHORTS}
    results = [
        _result(C["brca_her2"], 4, 4.4, 1e-59, True),  # over-expressed, found top-5
        _result(C["blca"], None, 1.6, 4e-3, True),  # over-expressed, missed
        _result(C["coad"], None, -0.3, 0.2, False),  # not over-expressed -> excluded from recall
        _result(C["paad"], None, 2.3, 0.13, False),  # underpowered (4 normals) -> excluded
    ]
    rec = R._aggregate_recall(results)
    # Denominator = 2 over-expressed (ERBB2 found@4, NECTIN4 missed): @5=1/2, @20=1/2.
    assert rec["recall@5"] == 0.5
    assert rec["recall@20"] == 0.5
    spec = R._specificity(results)
    # 1 not-over-expressed antigen (CEACAM5), correctly absent -> 1/1.
    assert spec["n"] == 1
    assert spec["fraction"] == 1.0


def test_render_results_md_has_sections() -> None:
    C = {c.key: c for c in R.VALIDATION_COHORTS}
    results = [
        _result(C["brca_her2"], 4, 4.4, 1e-59, True),
        _result(C["coad"], None, -0.3, 0.2, False),
    ]
    summary = {
        "generated_utc": "now",
        "bindsight_version": "0.1.0",
        "cbioportal_study": R.CBIOPORTAL_STUDY,
        "known_set": "benchmarks/known.tsv",
        "ks": list(R.KS),
        "overexpression_rule": "FDR<0.05 and log2fc>=1.0",
        "recall_at_k": R._aggregate_recall(results),
        "specificity": R._specificity(results),
        "cohorts": results,
        "data_limited": R.DATA_LIMITED,
    }
    md = R._render_results_md(summary)
    assert "over-expressed" in md.lower()
    assert "Specificity" in md
    assert "ERBB2" in md
    assert "CEACAM5" in md
    # ERBB2 fold-change is shown.
    assert "4.40" in md


def test_expected_deg_lookup(tmp_path: Path) -> None:
    run = tmp_path / "run"
    (run / "deg").mkdir(parents=True)
    pd.DataFrame(
        {
            "gene_id": ["ENSG00000141736", "ENSG00000000001"],
            "log2fc": [7.5, 0.1],
            "padj": [1e-10, 0.9],
            "significant": [True, False],
        }
    ).to_parquet(run / "deg" / "results.parquet")
    got = R._expected_deg(run, "ENSG00000141736")
    assert got["tested"] is True
    assert got["log2fc"] == 7.5
    assert got["significant"] is True
    assert R._expected_deg(run, "ENSG_NOPE") == {"tested": False}


def test_build_config_is_valid() -> None:
    c = R.VALIDATION_COHORTS[0]
    cfg = R._build_config(c, Path("c.tsv.gz"), Path("d.tsv"), Path("runs/x"))
    assert cfg.params.design.designer == "rfdiff_mpnn"
    assert cfg.params.validate_.validator == "boltz2"
    assert cfg.params.target_discovery.top_n == 20
    assert cfg.params.target_discovery.require_tractable_modality == []

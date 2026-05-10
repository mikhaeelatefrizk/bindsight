"""Tests for the multi-objective rank module."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from bindsight.config import RankWeights
from bindsight.rank import rank_run, rank_validated


def _make_validated() -> pd.DataFrame:
    """Six binders across two targets, with realistic-ish metric values."""
    return pd.DataFrame(
        [
            {
                "binder_id": "her2_d1",
                "target_uniprot": "P04626",
                "iptm": 0.85,
                "pae_interaction": 4.0,
                "rmsd_to_designed": 1.0,
                "affinity_pred_value": -8.0,
                "affinity_probability_binary": 0.9,
                "sequence_recovery": 0.55,
                "validator_name": "boltz2",
                "validator_version": "2.0.1",
            },
            {
                "binder_id": "her2_d2",
                "target_uniprot": "P04626",
                "iptm": 0.55,
                "pae_interaction": 8.0,
                "rmsd_to_designed": 3.0,
                "affinity_pred_value": -5.0,
                "affinity_probability_binary": 0.5,
                "sequence_recovery": 0.40,
                "validator_name": "boltz2",
                "validator_version": "2.0.1",
            },
            {
                "binder_id": "egfr_d1",
                "target_uniprot": "P00533",
                "iptm": 0.78,
                "pae_interaction": 5.0,
                "rmsd_to_designed": 1.5,
                "affinity_pred_value": -7.0,
                "affinity_probability_binary": 0.85,
                "sequence_recovery": 0.50,
                "validator_name": "boltz2",
                "validator_version": "2.0.1",
            },
        ]
    )


def _make_candidates() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"uniprot_id": "P04626", "symbol": "ERBB2", "log2fc": 3.5, "n_safety_events": 2},
            {"uniprot_id": "P00533", "symbol": "EGFR", "log2fc": 2.8, "n_safety_events": 1},
        ]
    )


def test_rank_validated_orders_by_composite() -> None:
    ranked = rank_validated(_make_validated(), _make_candidates())
    assert list(ranked.columns) >= [
        "binder_id",
        "score",
        "score_evidence",
        "score_structure",
        "score_affinity",
        "score_sequence",
        "rank",
    ]
    assert ranked["rank"].iloc[0] == 1
    # The strongest binder (her2_d1) should rank above the weakest (her2_d2)
    her2_d1_rank = ranked.loc[ranked["binder_id"] == "her2_d1", "rank"].iloc[0]
    her2_d2_rank = ranked.loc[ranked["binder_id"] == "her2_d2", "rank"].iloc[0]
    assert her2_d1_rank < her2_d2_rank


def test_rank_validated_handles_missing_columns() -> None:
    """If only some metrics are present, ranking still produces a score."""
    bare = pd.DataFrame(
        [
            {"binder_id": "a", "target_uniprot": "X", "iptm": 0.9},
            {"binder_id": "b", "target_uniprot": "X", "iptm": 0.5},
        ]
    )
    ranked = rank_validated(bare)
    assert ranked["rank"].iloc[0] == 1
    assert ranked.loc[0, "binder_id"] == "a"


def test_rank_run_writes_parquet(tmp_path: Path) -> None:
    run = tmp_path / "run"
    (run / "validate").mkdir(parents=True)
    (run / "targets").mkdir(parents=True)
    _make_validated().to_parquet(run / "validate" / "validated.parquet", index=False)
    _make_candidates().to_parquet(run / "targets" / "candidates.parquet", index=False)
    out = rank_run(run)
    assert out.exists()
    ranked = pd.read_parquet(out)
    assert "score" in ranked.columns
    assert len(ranked) == 3


def test_rank_run_raises_when_no_validation_output(tmp_path: Path) -> None:
    run = tmp_path / "empty"
    run.mkdir()
    with pytest.raises(FileNotFoundError):
        rank_run(run)


def test_custom_weights_change_ordering() -> None:
    """Heavily weighting evidence should pull in the higher-log2fc target."""
    df = _make_validated()
    cand = _make_candidates()
    # Default weights
    default_ranked = rank_validated(df, cand)
    # Evidence-only
    extreme = RankWeights(log2fc_specificity=1.0, iptm=0.0, affinity=0.0, sequence_recovery=0.0)
    evidence_ranked = rank_validated(df, cand, weights=extreme)
    assert "score" in evidence_ranked.columns
    # All HER2 binders share log2fc=3.5; with evidence-only weights, no
    # variance within a target → composite is the same for all HER2 rows.
    her2_scores = evidence_ranked[evidence_ranked["target_uniprot"] == "P04626"]["score"]
    assert her2_scores.nunique() == 1
    # Sanity: the default ranking still has multiple distinct scores.
    assert default_ranked["score"].nunique() > 1

# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the multi-objective rank module."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from bindsight.config import RankWeights
from bindsight.rank import rank_run, rank_validated
from bindsight.rank.scoring import _one_row_per_accession


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


# ---------------------------------------------------------------------------
# One candidate row per accession
# ---------------------------------------------------------------------------
def _colliding_candidates() -> pd.DataFrame:
    """Two gene rows mapping to one accession, with disagreeing evidence."""
    return pd.DataFrame(
        [
            {
                "symbol": "WEAK",
                "uniprot_id": "P04626",
                "log2fc": 0.4,
                "padj": 0.30,
                "n_safety_events": 0,
            },
            {
                "symbol": "STRONG",
                "uniprot_id": "P04626",
                "log2fc": 3.5,
                "padj": 1e-9,
                "n_safety_events": 2,
            },
        ]
    )


class TestOneRowPerAccession:
    """Several gene IDs can map to one accession, and each carries its own
    log2fc and padj, which feed the evidence component of the score. The old
    ``drop_duplicates`` kept whichever arrived first, so the number a binder was
    scored with depended on the row order of an upstream table.
    """

    def test_the_same_row_wins_whatever_order_they_arrive_in(self) -> None:
        """The property that was broken: order-independence."""
        forward = _one_row_per_accession(_colliding_candidates())
        reversed_ = _one_row_per_accession(
            _colliding_candidates().iloc[::-1].reset_index(drop=True)
        )

        assert len(forward) == len(reversed_) == 1
        assert forward.iloc[0]["symbol"] == reversed_.iloc[0]["symbol"] == "STRONG"
        assert forward.iloc[0]["padj"] == reversed_.iloc[0]["padj"] == 1e-9

    def test_a_row_without_a_statistic_never_displaces_one_that_has_it(self) -> None:
        cand = _colliding_candidates()
        cand.loc[0, "padj"] = None
        cand.loc[0, "log2fc"] = None

        kept = _one_row_per_accession(cand)

        assert kept.iloc[0]["symbol"] == "STRONG"

    def test_a_collision_is_logged_with_the_accession_and_symbols(self, caplog) -> None:
        """Silently picking one of two disagreeing rows is the part that makes
        this hard to notice; the log line is what makes it noticeable."""
        import logging

        with caplog.at_level(logging.WARNING, logger="bindsight.rank.scoring"):
            _one_row_per_accession(_colliding_candidates())

        messages = [r.getMessage() for r in caplog.records]
        assert any("P04626" in m for m in messages), messages
        assert any("STRONG" in m and "WEAK" in m for m in messages), messages

    def test_nothing_is_logged_when_there_is_no_collision(self, caplog) -> None:
        import logging

        cand = _colliding_candidates()
        cand.loc[0, "uniprot_id"] = "P00533"

        with caplog.at_level(logging.WARNING, logger="bindsight.rank.scoring"):
            kept = _one_row_per_accession(cand)

        assert len(kept) == 2
        assert not caplog.records, [r.getMessage() for r in caplog.records]

    def test_the_columns_and_their_order_survive(self) -> None:
        """The result is merged by column name downstream; a reordered or
        widened frame would change the join."""
        cand = _colliding_candidates()

        kept = _one_row_per_accession(cand)

        assert list(kept.columns) == list(cand.columns)

    def test_the_committed_cohorts_contain_no_collisions(self) -> None:
        """Why this went unnoticed, recorded as a fact rather than an assumption.

        If a future mapping starts producing collisions this fails, and whoever
        sees it can decide whether the tie-break is the behaviour they want.
        """
        repo = Path(__file__).resolve().parents[1]
        tables = sorted(repo.glob("runs/**/targets/candidates.parquet"))
        if not tables:
            pytest.skip("no committed candidate tables")

        total = 0
        collisions: dict[str, int] = {}
        for table in tables:
            df = pd.read_parquet(table)
            if "uniprot_id" not in df.columns:
                continue
            known = df[df["uniprot_id"].notna()]
            total += len(known)
            n = int(known.duplicated("uniprot_id").sum())
            if n:
                collisions[str(table.relative_to(repo))] = n

        assert total, "the committed candidate tables carry no accessions"
        assert not collisions, (
            f"candidate tables now contain duplicate accessions: {collisions}. "
            "The tie-break in _one_row_per_accession is now load-bearing."
        )


class TestTiedScoresRankReproducibly:
    """The published ``rank`` came from ``sort_values`` with pandas' default
    kind, which is not stable. Two binders on the same composite score were
    ordered by numpy's introsort internals, so the rank among ties could differ
    between runs and between platforms for byte-identical inputs.
    """

    @staticmethod
    def _tied(order: list[str]) -> "pd.DataFrame":
        return pd.DataFrame(
            [
                {
                    "binder_id": b,
                    "target_uniprot": "P04626",
                    "iptm": 0.7,
                    "pae_interaction": 6.0,
                    "affinity_pred_value": -7.0,
                    "sequence_recovery": 0.5,
                    "validator_name": "boltz2",
                    "validator_version": "2.0.3",
                }
                for b in order
            ]
        )

    def test_tied_groups_keep_their_input_order(self) -> None:
        """Groups of ties among distinct scores, not one all-equal block.

        An all-equal frame does not expose this: numpy's introsort happens to
        leave identical elements alone, so the first version of this test passed
        against ``kind="quicksort"`` and proved nothing. Partitioning only moves
        tied elements when there is something to partition around.
        """
        import random

        rng = random.Random(0)
        ids = [f"b{i:04d}" for i in range(60)]
        frame = self._tied(ids)
        # Three score levels, so most rows are tied with several others.
        frame["iptm"] = [rng.choice([0.9, 0.5, 0.1]) for _ in ids]

        ranked = rank_validated(frame)

        for level in (0.9, 0.5, 0.1):
            expected = [b for b, v in zip(ids, frame["iptm"], strict=True) if v == level]
            actual = [b for b in ranked["binder_id"] if b in set(expected)]
            assert actual == expected, (
                f"binders tied at ipTM {level} were reordered; the published rank "
                "is not reproducible for identical inputs"
            )

    def test_the_same_frame_ranks_the_same_way_twice(self) -> None:
        frame = self._tied([f"b{i}" for i in range(20)])

        first = list(rank_validated(frame.copy())["binder_id"])
        second = list(rank_validated(frame.copy())["binder_id"])

        assert first == second

    def test_a_real_difference_still_wins_over_input_order(self) -> None:
        """Stability must not override the score itself."""
        frame = self._tied(["low", "high"])
        frame.loc[frame["binder_id"] == "high", "iptm"] = 0.95

        ranked = rank_validated(frame)

        assert ranked.iloc[0]["binder_id"] == "high"

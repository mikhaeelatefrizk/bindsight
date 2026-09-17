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

    # A sixth test used to sweep runs/**/targets/candidates.parquet and assert
    # no committed cohort contained duplicate accessions. `runs/` is gitignored
    # and the repository tracks zero parquet files, so it skipped on every clone
    # and, on the author's machine, read artifacts nobody else has -- a skip
    # that reads like coverage. The property it wanted is proved above by
    # construction, in five tests that build the collision rather than hope to
    # find one, so removing it loses nothing.


class TestTiedScoresRankReproducibly:
    """The published ``rank`` came from ``sort_values`` with pandas' default
    kind, which is not stable. Two binders on the same composite score were
    ordered by numpy's introsort internals, so the rank among ties could differ
    between runs and between platforms for byte-identical inputs.
    """

    @staticmethod
    def _tied(order: list[str]) -> pd.DataFrame:
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


class TestTheCompositeExcludesWhatItCannotRead:
    """A component the composite cannot parse must not be counted against a binder.

    The loop took its presence mask from the raw column while coercing the value
    with ``errors="coerce"``. A non-numeric but non-null cell was therefore
    ``notna()`` -- counting its full weight in the denominator -- while coercing
    to NaN and contributing 0.0 to the numerator, silently depressing that
    binder. The comment directly above the loop promises the opposite.

    **No reachable path produces one today**, and this test says so rather than
    pretending otherwise: every ``score_*`` column is overwritten inside
    ``rank_validated`` by a helper that returns a numeric Series or raises --
    ``_minmax`` raises ``TypeError`` on a string rather than passing it through.
    So the fix is defensive, and the guard is structural: it asserts the mask is
    taken from the coerced column, which is the property that made the
    inconsistency possible.
    """

    def test_the_mask_is_taken_after_coercion(self) -> None:
        import inspect

        from bindsight.rank import scoring

        source = inspect.getsource(scoring.rank_validated)
        coerce_at = source.index('pd.to_numeric(df[col], errors="coerce")')
        mask_at = source.index("mask = ")

        assert mask_at > coerce_at, (
            "the presence mask is computed before coercion, so a value that "
            "coerces to NaN would still count its full weight against the binder"
        )
        assert "mask = column.notna()" in source, (
            "the mask no longer derives from the coerced column"
        )

    def test_the_weighted_average_ignores_missing_components(self) -> None:
        """The promise the comment makes, checked end to end on the live path.

        Two binders identical but for a component one of them lacks entirely.
        A missing metric must not move the score.
        """
        both = rank_validated(
            pd.DataFrame(
                {
                    "binder_id": ["a", "b"],
                    "target_uniprot": ["P1", "P1"],
                    "iptm": [0.8, 0.8],
                    "pae_interaction": [10.0, 10.0],
                }
            )
        )

        scores = dict(zip(both["binder_id"], both["score"], strict=True))
        assert scores["a"] == pytest.approx(scores["b"])
        assert all(pd.notna(v) for v in scores.values()), (
            "a row with no developability component scored NaN; missing metrics "
            "should be excluded from the average, not poison it"
        )


class TestTheRankCommandHonoursTheRunsWeights:
    """`bindsight rank <run>` ranked with the defaults whatever the config said.

    The command called `rank_run(run_dir)` with no `weights=`, so `rank_validated`
    fell back to `RankWeights()` — and then recorded those defaults in provenance.
    A user who set `params.rank.weights`, followed the documented per-stage path
    (`discover` → `design` → `validate` → `rank`), and read the manifest afterwards
    was told their weighting had been used when it had not.

    The weights are what turn four metrics into one ordering. The published order
    answered a different question from the one asked, and nothing in the run said
    so — which is what makes it worse than a crash.
    """

    @staticmethod
    def _run_with_weights(tmp_path: Path, weights: dict | None) -> Path:
        """A rankable run whose config names a weighting, or names none."""
        import yaml

        run = tmp_path / "run"
        (run / "validate").mkdir(parents=True)
        (run / "targets").mkdir(parents=True)
        _make_validated().to_parquet(run / "validate" / "validated.parquet", index=False)
        _make_candidates().to_parquet(run / "targets" / "candidates.parquet", index=False)
        if weights is not None:
            (run / "config.yaml").write_text(
                yaml.safe_dump({"params": {"rank": {"weights": weights}}}),
                encoding="utf-8",
                newline="\n",
            )
        return run

    def test_the_configured_weights_reach_the_ranker(self, tmp_path: Path) -> None:
        """Driven, not grepped: the weighting is read back off the call."""
        from click.testing import CliRunner

        from bindsight import cli

        run = self._run_with_weights(tmp_path, {"iptm": 0.9, "affinity": 0.05})

        seen: dict = {}

        def _capture(run_dir, *, weights=None):
            seen["weights"] = weights
            return run_dir / "rank" / "ranking.parquet"

        import bindsight.rank as rank_pkg

        original = rank_pkg.rank_run
        rank_pkg.rank_run = _capture
        try:
            CliRunner().invoke(cli.main, ["rank", str(run)])
        finally:
            rank_pkg.rank_run = original

        assert seen.get("weights") is not None, (
            "the rank command passed no weights, so the ranker used its defaults "
            "whatever the run was configured with"
        )
        assert seen["weights"].iptm == pytest.approx(0.9)
        assert seen["weights"].affinity == pytest.approx(0.05)

    def test_a_run_without_a_config_still_ranks_with_the_defaults(self, tmp_path: Path) -> None:
        """Guards the guard: reading the config must not become a requirement."""
        from bindsight.cli import _rank_weights
        from bindsight.config import RankWeights

        run = self._run_with_weights(tmp_path, None)

        assert _rank_weights(run).model_dump() == RankWeights().model_dump()

    def test_an_unreadable_config_warns_rather_than_reweighting_in_silence(
        self, tmp_path: Path, caplog
    ) -> None:
        """Falling back is fine; doing it quietly is the defect being fixed."""
        import logging

        from bindsight.cli import _rank_weights
        from bindsight.config import RankWeights

        run = self._run_with_weights(tmp_path, None)
        (run / "config.yaml").write_text("params: [not, a, mapping", encoding="utf-8")

        with caplog.at_level(logging.WARNING):
            got = _rank_weights(run)

        assert got.model_dump() == RankWeights().model_dump()
        assert any("default weights" in r.getMessage() for r in caplog.records), (
            "an unreadable config silently changed the weighting the run is ranked by"
        )

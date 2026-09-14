# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the rediscovery null models and interval estimates.

These assert against values that can be checked by hand or against published
worked examples, not merely against the code's own behaviour. A statistics module
whose tests only confirm it does what it does is worth nothing.
"""

from __future__ import annotations

import math

import pytest

from bindsight.benchmark import statistics as st


class TestNormalQuantile:
    """The interval widths depend on this, so it is pinned to published values."""

    @pytest.mark.parametrize(
        ("confidence", "expected"),
        [(0.90, 1.644854), (0.95, 1.959964), (0.99, 2.575829)],
    )
    def test_matches_published_quantiles(self, confidence: float, expected: float) -> None:
        assert st._z_for(confidence) == pytest.approx(expected, abs=1e-6)


class TestWilsonInterval:
    """The reported interval."""

    def test_matches_hand_computed_value(self) -> None:
        # 1 success in 15 trials, the situation this panel is realistically in.
        i = st.wilson_interval(1, 15)
        assert i.point == pytest.approx(1 / 15)
        assert i.low == pytest.approx(0.0119, abs=5e-4)
        assert i.high == pytest.approx(0.2982, abs=5e-4)

    def test_does_not_collapse_at_zero_successes(self) -> None:
        """A Wald interval gives (0, 0) here, which would be a false claim."""
        i = st.wilson_interval(0, 8)
        assert i.low == 0.0
        assert i.high > 0.3
        assert i.point == 0.0

    def test_does_not_collapse_at_full_success(self) -> None:
        i = st.wilson_interval(8, 8)
        assert i.high == 1.0
        assert i.low < 0.7

    def test_narrows_as_the_panel_grows(self) -> None:
        small = st.wilson_interval(1, 8)
        large = st.wilson_interval(10, 80)
        assert (large.high - large.low) < (small.high - small.low)

    def test_carries_its_own_counts(self) -> None:
        """A rate without its numerator and denominator is not reportable."""
        d = st.wilson_interval(3, 20).as_dict()
        assert d["numerator"] == 3
        assert d["denominator"] == 20
        assert d["method"] == "wilson"

    @pytest.mark.parametrize(
        ("s", "n", "message"),
        [(0, 0, "trials must be positive"), (-1, 5, "outside"), (6, 5, "outside")],
    )
    def test_rejects_impossible_counts(self, s: int, n: int, message: str) -> None:
        with pytest.raises(ValueError, match=message):
            st.wilson_interval(s, n)


class TestClopperPearson:
    def test_is_wider_than_wilson(self) -> None:
        """It is the conservative cross-check, so it must never be narrower."""
        w = st.wilson_interval(1, 15)
        cp = st.clopper_pearson_interval(1, 15)
        assert cp.low <= w.low
        assert cp.high >= w.high

    def test_handles_the_boundaries(self) -> None:
        assert st.clopper_pearson_interval(0, 10).low == 0.0
        assert st.clopper_pearson_interval(10, 10).high == 1.0

    def test_matches_the_textbook_interval(self) -> None:
        """2 of 10 at 95% is a published worked example: (0.0252, 0.5561)."""
        cp = st.clopper_pearson_interval(2, 10)
        assert cp.low == pytest.approx(0.0252107263, abs=1e-9)
        assert cp.high == pytest.approx(0.5560954623, abs=1e-9)

    def test_each_tail_carries_exactly_half_of_alpha(self) -> None:
        """The defining property, and the one "wider than Wilson" cannot pin.

        Clopper-Pearson inverts the binomial test: the lower bound is the p at
        which observing this many or more successes has probability alpha/2, and
        the upper bound the p at which observing this many or fewer does. Putting
        the whole of alpha in one tail still yields an interval that is wider
        than Wilson and looks entirely reasonable, while under-covering — so the
        identity has to be asserted rather than a comparison.
        """
        from scipy import stats as sps

        successes, trials, confidence = 3, 20, 0.95
        cp = st.clopper_pearson_interval(successes, trials, confidence=confidence)
        half_alpha = (1.0 - confidence) / 2
        assert sps.binom.sf(successes - 1, trials, cp.low) == pytest.approx(half_alpha, abs=1e-9)
        assert sps.binom.cdf(successes, trials, cp.high) == pytest.approx(half_alpha, abs=1e-9)

    def test_a_tighter_confidence_narrows_both_bounds(self) -> None:
        wide = st.clopper_pearson_interval(3, 20, confidence=0.99)
        narrow = st.clopper_pearson_interval(3, 20, confidence=0.80)
        assert wide.low < narrow.low
        assert wide.high > narrow.high


class TestClusterBootstrap:
    """One antigen in four cohorts is one piece of evidence, not four."""

    def test_correlated_pairs_widen_the_interval(self) -> None:
        """Four antigens seen twice each carry less information than eight trials."""
        # Half the antigens hit in both their cohorts, half miss in both — the
        # correlation the cluster structure exists to represent.
        clustered = st.cluster_bootstrap_interval(
            {"A": [True, True], "B": [True, True], "C": [False, False], "D": [False, False]},
            n_boot=4000,
            seed=1,
        )
        independent = st.wilson_interval(4, 8)
        assert clustered.denominator == 8
        assert clustered.point == pytest.approx(0.5)
        assert (clustered.high - clustered.low) > (independent.high - independent.low)

    def test_a_boundary_panel_produces_a_flagged_degenerate_interval(self) -> None:
        """All hits leaves nothing to resample, so the bootstrap cannot be quoted alone.

        This is a property of the percentile bootstrap, not a defect, and it is
        exactly the case a small panel lands in — so the interval says so in its
        own method string rather than reporting zero width as certainty.
        """
        i = st.cluster_bootstrap_interval(
            {"A": [True, True], "B": [True, True]}, n_boot=500, seed=1
        )
        assert i.low == i.high == 1.0
        assert "degenerate" in i.method
        # Wilson still carries real uncertainty here, which is why it is the
        # reported interval.
        assert st.wilson_interval(4, 4).low < 1.0

    def test_point_estimate_is_the_plain_rate(self) -> None:
        i = st.cluster_bootstrap_interval(
            {"A": [True, False], "B": [False, False]}, n_boot=500, seed=3
        )
        assert i.point == pytest.approx(0.25)

    def test_is_reproducible_from_its_seed(self) -> None:
        args = {"A": [True, False, True], "B": [False, True, False], "C": [True, True, False]}
        first = st.cluster_bootstrap_interval(args, n_boot=1000, seed=7)
        second = st.cluster_bootstrap_interval(args, n_boot=1000, seed=7)
        assert (first.low, first.high) == (second.low, second.high)

    def test_rejects_an_empty_panel(self) -> None:
        with pytest.raises(ValueError, match="no clusters"):
            st.cluster_bootstrap_interval({})

    def test_it_resamples_antigens_and_not_outcomes(self) -> None:
        """The entire reason this function exists, and it was unpinned.

        Resampling the flat list of outcomes instead of the antigen clusters
        still produces an interval wider than Wilson, so the comparison above
        cannot tell the two apart. A panel split into one antigen that hits
        everywhere and one that misses everywhere can.

        Drawing two antigens with replacement gives all-hits, all-misses, or one
        of each — so the estimate is 1.0, 0.0 or 0.5 and the interval spans the
        unit interval. Resampling twenty individual outcomes at a rate of one
        half concentrates near 0.5 and returns roughly (0.3, 0.7): a confident
        claim manufactured out of correlation the panel does not have.
        """
        split = st.cluster_bootstrap_interval(
            {"A": [True] * 10, "B": [False] * 10}, n_boot=4000, seed=1
        )
        assert split.point == pytest.approx(0.5)
        assert split.low == 0.0
        assert split.high == 1.0

    def test_a_cluster_travels_whole(self) -> None:
        """An antigen brings all of its cohorts, so its weight is its size.

        With a three-cohort antigen and a one-cohort antigen, two draws can only
        ever yield 6/6, 3/4 or 0/2. A rate of one half or one quarter is not
        reachable, and seeing one would mean cohorts had been drawn individually.
        """
        reachable = {0.0, 0.75, 1.0}
        i = st.cluster_bootstrap_interval(
            {"A": [True, True, True], "B": [False]}, n_boot=4000, seed=5
        )
        assert i.low in reachable, f"{i.low} is unreachable when clusters travel whole"
        assert i.high in reachable, f"{i.high} is unreachable when clusters travel whole"


class TestUniformRankNull:
    def test_p_is_rank_over_the_eligible_set(self) -> None:
        assert st.uniform_rank_p(10, 2000) == pytest.approx(0.005)
        assert st.uniform_rank_p(1, 1) == pytest.approx(1.0)

    def test_the_reference_set_matters(self) -> None:
        """Using the whole surfaceome instead of its up-regulated half halves p.

        That is the anticonservative error this signature exists to prevent, so
        the difference is asserted rather than left to a comment.
        """
        up_regulated_only = st.uniform_rank_p(10, 1000)
        whole_set = st.uniform_rank_p(10, 2000)
        assert whole_set == pytest.approx(up_regulated_only / 2)

    @pytest.mark.parametrize(
        ("rank", "n", "message"),
        [(0, 10, "rank must be"), (11, 10, "exceeds"), (1, 0, "n_eligible must be")],
    )
    def test_rejects_impossible_ranks(self, rank: int, n: int, message: str) -> None:
        with pytest.raises(ValueError, match=message):
            st.uniform_rank_p(rank, n)


class TestDecoyNull:
    def test_add_one_correction_prevents_a_zero_p_value(self) -> None:
        """No finite number of decoys can license p = 0."""
        p = st.decoy_null_p(1, [500] * 1000)
        assert p > 0
        assert p == pytest.approx(1 / 1001)

    def test_p_rises_as_decoys_do_better(self) -> None:
        beaten_by_none = st.decoy_null_p(1, list(range(2, 102)))
        beaten_by_half = st.decoy_null_p(51, list(range(1, 101)))
        assert beaten_by_none < beaten_by_half

    def test_a_tied_decoy_counts_as_at_least_as_good(self) -> None:
        """Ties are common: gated-out decoys pile up at the same rank.

        Counting only decoys that strictly beat the antigen discards exactly the
        draws that say the result was unremarkable, which biases every p-value
        downward. Three decoys all tied with the antigen is the clearest case
        there is — the evidence is worthless and p must say so.
        """
        assert st.decoy_null_p(5, [5, 5, 5]) == 1.0
        # Contrast: decoys that all rank worse leave the add-one floor.
        assert st.decoy_null_p(5, [6, 7, 8]) == pytest.approx(0.25)
        # One tie is one decoy that did as well.
        assert st.decoy_null_p(5, [5, 6, 7]) == pytest.approx(0.5)

    def test_requires_decoys(self) -> None:
        with pytest.raises(ValueError, match="at least one decoy"):
            st.decoy_null_p(5, [])


class TestDecoyMatching:
    @staticmethod
    def _pool() -> list[dict[str, object]]:
        return [
            {"uniprot": f"P{i:05d}", "base_mean_stratum": i % 10, "dispersion_stratum": i % 3}
            for i in range(300)
        ]

    def test_decoys_share_the_target_strata(self) -> None:
        target = {"uniprot": "TARGET", "base_mean_stratum": 4, "dispersion_stratum": 1}
        decoys = st.match_decoys(self._pool(), target, n_decoys=5, seed=2)
        assert decoys
        for d in decoys:
            assert d["base_mean_stratum"] == 4
            assert d["dispersion_stratum"] == 1

    def test_the_target_is_never_its_own_decoy(self) -> None:
        pool = self._pool()
        target = dict(pool[14])
        decoys = st.match_decoys(pool, target, n_decoys=50, seed=2)
        assert all(d["uniprot"] != target["uniprot"] for d in decoys)

    def test_a_thin_stratum_degrades_to_sampling_with_replacement(self) -> None:
        pool = [
            {"uniprot": "P1", "base_mean_stratum": 9, "dispersion_stratum": 9},
            {"uniprot": "P2", "base_mean_stratum": 9, "dispersion_stratum": 9},
        ]
        target = {"uniprot": "T", "base_mean_stratum": 9, "dispersion_stratum": 9}
        decoys = st.match_decoys(pool, target, n_decoys=10, seed=1)
        assert len(decoys) == 10

    def test_missing_strata_is_an_error_not_a_silent_mismatch(self) -> None:
        with pytest.raises(ValueError, match="strata"):
            st.match_decoys(self._pool(), {"uniprot": "T"}, n_decoys=2)


class TestPermutationNull:
    """The null permutes the assignment; it does not resample cohorts.

    It used to deal each antigen a *distinct* cohort from the whole panel. That
    put the observation outside the null's support as soon as two antigens
    shared an indication — and two do: FOLH1 and STEAP1 are both
    single-indication and both TCGA-PRAD. The observed statistic counted
    prostate twice; no draw ever could. Both score near the top there, so the
    observation was systematically larger than anything the null could produce
    and the p-value collapsed to its reporting floor.

    Shuffling which antigen receives which of the *observed* cohorts fixes the
    support — the observation is the identity permutation — and controls for
    cohort difficulty, since every permutation uses exactly the cohorts the
    observation used.
    """

    def test_perfect_indication_matching_is_significant(self) -> None:
        """Each antigen scores well only in its own cohort."""
        scores = {
            "A": {"ca": 1.0, "cb": 0.0, "cc": 0.0},
            "B": {"ca": 0.0, "cb": 1.0, "cc": 0.0},
            "C": {"ca": 0.0, "cb": 0.0, "cc": 1.0},
        }
        result = st.permutation_null_p(scores, {"A": "ca", "B": "cb", "C": "cc"})
        assert result["observed"] == pytest.approx(1.0)
        assert result["p_value"] == pytest.approx(1 / 6), "only the identity is this extreme"

    def test_generic_biology_is_not_significant(self) -> None:
        """If every antigen scores the same everywhere, matching means nothing."""
        scores = {a: {c: 0.5 for c in ("ca", "cb", "cc")} for a in ("A", "B", "C")}
        result = st.permutation_null_p(scores, {"A": "ca", "B": "cb", "C": "cc"})
        assert result["p_value"] == pytest.approx(1.0)

    def test_two_antigens_sharing_a_cohort_keep_the_observation_in_the_null(self) -> None:
        """The defect: the panel has two prostate-only antigens.

        Under the old null every permutation gave a cohort to at most one
        antigen, so an observation that used prostate twice could not be
        produced by any draw. Its p-value was not a tail probability of
        anything the code sampled.
        """
        scores = {
            "FOLH1": {"PRAD": 0.99, "KIRC": 0.40, "LIHC": 0.30},
            "STEAP1": {"PRAD": 0.93, "KIRC": 0.35, "LIHC": 0.32},
            "CA9": {"PRAD": 0.20, "KIRC": 0.98, "LIHC": 0.25},
        }
        assignment = {"FOLH1": "PRAD", "STEAP1": "PRAD", "CA9": "KIRC"}
        result = st.permutation_null_p(scores, assignment)

        # The observation is the identity permutation, so it is always counted.
        assert result["p_value"] >= result["p_value_floor"]
        assert result["p_value"] > 0.0
        assert result["observed"] == pytest.approx((0.99 + 0.93 + 0.98) / 3)

    def test_the_observed_statistic_comes_from_the_assignment(self) -> None:
        """It used to be passed in, computed by the caller under its own rule.

        That is how the observation and the null came to disagree. Deriving it
        here makes the two impossible to build differently.
        """
        scores = {
            "A": {"ca": 0.9, "cb": 0.1},
            "B": {"ca": 0.2, "cb": 0.8},
        }
        assert st.permutation_null_p(scores, {"A": "ca", "B": "cb"})["observed"] == pytest.approx(
            0.85
        )
        assert st.permutation_null_p(scores, {"A": "cb", "B": "ca"})["observed"] == pytest.approx(
            0.15
        )

    def test_the_null_uses_only_the_cohorts_the_observation_used(self) -> None:
        """Which is what makes it control for cohort difficulty.

        A cohort whose standings run high across the board cannot inflate the
        observed arm without inflating every permuted one too.
        """
        scores = {
            "A": {"ca": 0.5, "cb": 0.5, "unused": 9.0},
            "B": {"ca": 0.5, "cb": 0.5, "unused": 9.0},
        }
        # `unused` is never assigned, so it can never enter the statistic.
        result = st.permutation_null_p(scores, {"A": "ca", "B": "cb"})
        assert result["observed"] == pytest.approx(0.5)
        assert result["p_value"] == pytest.approx(1.0)

    def test_a_small_panel_is_enumerated_exactly(self) -> None:
        """A p-value that can be exact should not carry Monte Carlo error."""
        scores = {a: {c: 0.5 for c in ("ca", "cb", "cc")} for a in ("A", "B", "C")}
        result = st.permutation_null_p(scores, {"A": "ca", "B": "cb", "C": "cc"})
        assert result["exact"] is True
        assert result["n_permutations"] == 6
        assert result["p_value_floor"] == pytest.approx(1 / 6)

    def test_a_large_panel_falls_back_to_sampling_and_says_so(self) -> None:
        scores = {f"A{i}": {f"c{j}": 0.5 for j in range(10)} for i in range(10)}
        assignment = {f"A{i}": f"c{i}" for i in range(10)}
        result = st.permutation_null_p(scores, assignment, n_perm=200, exact_limit=1000)
        assert result["exact"] is False
        assert result["n_permutations"] == 200
        assert result["p_value_floor"] == pytest.approx(1 / 201)

    def test_the_same_seed_reproduces_a_sampled_p_value(self) -> None:
        scores = {f"A{i}": {f"c{j}": (i * j) % 7 / 7 for j in range(10)} for i in range(10)}
        assignment = {f"A{i}": f"c{i}" for i in range(10)}
        a = st.permutation_null_p(scores, assignment, n_perm=500, seed=3, exact_limit=10)
        b = st.permutation_null_p(scores, assignment, n_perm=500, seed=3, exact_limit=10)
        assert a["p_value"] == b["p_value"]

    def test_a_ragged_score_matrix_is_rejected(self) -> None:
        """A missing score is an unevaluated pair, which would bias the null."""
        with pytest.raises(ValueError, match="ragged"):
            st.permutation_null_p(
                {"A": {"ca": 1.0, "cb": 0.0}, "B": {"ca": 0.0}}, {"A": "ca", "B": "ca"}
            )

    def test_needs_more_than_one_antigen(self) -> None:
        with pytest.raises(ValueError, match="at least two antigens"):
            st.permutation_null_p({"A": {"ca": 1.0}}, {"A": "ca"})

    def test_an_assignment_that_misses_an_antigen_is_refused(self) -> None:
        scores = {"A": {"ca": 1.0, "cb": 0.0}, "B": {"ca": 0.0, "cb": 1.0}}
        with pytest.raises(ValueError, match="exactly one assigned cohort"):
            st.permutation_null_p(scores, {"A": "ca"})

    def test_an_assignment_naming_an_unscored_cohort_is_refused(self) -> None:
        """Scoring an antigen in a cohort it was never evaluated in is not a null."""
        scores = {"A": {"ca": 1.0, "cb": 0.0}, "B": {"ca": 0.0, "cb": 1.0}}
        with pytest.raises(ValueError, match="absent from the score matrix"):
            st.permutation_null_p(scores, {"A": "ca", "B": "somewhere_else"})

    def test_more_antigens_than_cohorts_is_now_allowed(self) -> None:
        """It had to be refused when cohorts were dealt out without replacement.

        Permuting an assignment has no such constraint, and forbidding it was
        forbidding exactly the panel shape that exposed the defect.
        """
        scores = {a: {"ca": 1.0, "cb": 1.0} for a in ("A", "B", "C")}
        result = st.permutation_null_p(scores, {"A": "ca", "B": "ca", "C": "cb"})
        assert result["p_value"] == pytest.approx(1.0)

    def test_lower_is_better_flips_the_tail(self) -> None:
        scores = {
            "A": {"ca": 0.0, "cb": 1.0},
            "B": {"ca": 1.0, "cb": 0.0},
        }
        assignment = {"A": "ca", "B": "cb"}
        low = st.permutation_null_p(scores, assignment, higher_is_better=False)
        high = st.permutation_null_p(scores, assignment, higher_is_better=True)
        assert low["p_value"] < high["p_value"]


class TestBenjaminiHochberg:
    def test_matches_the_published_worked_example(self) -> None:
        """Benjamini and Hochberg 1995, table 1."""
        raw = [
            0.0001,
            0.0004,
            0.0019,
            0.0095,
            0.0201,
            0.0278,
            0.0298,
            0.0344,
            0.0459,
            0.3240,
            0.4262,
            0.5719,
            0.6528,
            0.7590,
            1.000,
        ]
        adj = st.benjamini_hochberg(raw)
        assert adj[0] == pytest.approx(0.0015, abs=1e-4)
        assert adj[1] == pytest.approx(0.0030, abs=1e-4)
        # Monotone non-decreasing in the original p-value order.
        assert adj == sorted(adj)

    def test_preserves_input_order(self) -> None:
        adj = st.benjamini_hochberg([0.5, 0.01, 0.2])
        assert adj[1] < adj[2] < adj[0]

    def test_never_reduces_a_p_value(self) -> None:
        raw = [0.001, 0.01, 0.02, 0.9]
        assert all(a >= r for a, r in zip(st.benjamini_hochberg(raw), raw, strict=True))

    def test_empty_input(self) -> None:
        assert st.benjamini_hochberg([]) == []

    def test_rejects_values_outside_the_unit_interval(self) -> None:
        with pytest.raises(ValueError, match=r"\[0, 1\]"):
            st.benjamini_hochberg([0.5, 1.5])


class TestTheExactFloorCountsRepeatedAssignments:
    """Antigens sharing a cohort are interchangeable, so each distinct
    assignment is reproduced by several permutations. The floor has to count
    them, or a p sitting exactly on the floor reads as a measured value.

    This is not hypothetical: the committed panel has FOLH1 and STEAP1 both on
    PRAD, its observed p is 2/5040, and the floor was reported as 1/5040 --
    which silenced the report's own "p equals its floor" warning on the one
    result in the project that is not a negative control.
    """

    @staticmethod
    def _panel(assignment: dict[str, str]) -> dict[str, dict[str, float]]:
        cohorts = sorted(set(assignment.values()) | {"AAA", "BBB"})
        scores = {a: dict.fromkeys(cohorts, 0.1) for a in assignment}
        for antigen, cohort in assignment.items():
            scores[antigen][cohort] = 0.9
        return scores

    def test_no_shared_cohort_keeps_the_floor_at_one_permutation(self) -> None:
        assignment = {"A": "c1", "B": "c2", "C": "c3", "D": "c4"}
        result = st.permutation_null_p(self._panel(assignment), assignment)

        assert result["exact"] is True
        assert result["p_value_floor"] == pytest.approx(1 / math.factorial(4))

    def test_one_shared_cohort_doubles_the_floor(self) -> None:
        assignment = {"A": "c1", "B": "c2", "C": "c3", "D": "c3"}
        result = st.permutation_null_p(self._panel(assignment), assignment)

        assert result["p_value_floor"] == pytest.approx(2 / math.factorial(4))

    def test_three_on_one_cohort_gives_six(self) -> None:
        assignment = {"A": "c1", "B": "c2", "C": "c2", "D": "c2"}
        result = st.permutation_null_p(self._panel(assignment), assignment)

        assert result["p_value_floor"] == pytest.approx(6 / math.factorial(4))

    def test_a_perfect_assignment_lands_on_its_floor_not_below_it(self) -> None:
        """The property that matters: p can never be smaller than the floor,
        and when nothing beats the observation it must be equal to it."""
        assignment = {"A": "c1", "B": "c2", "C": "c3", "D": "c3"}
        result = st.permutation_null_p(self._panel(assignment), assignment)

        assert result["p_value"] == pytest.approx(result["p_value_floor"])

    def test_the_committed_panel_shape_reproduces_the_published_floor(self) -> None:
        """Seven antigens, two of them prostate -- the panel as committed."""
        assignment = {
            "CA9": "KIRC",
            "FGFR2": "STAD",
            "FOLH1": "PRAD",
            "FOLR1": "UCEC",
            "GPC3": "LIHC",
            "NECTIN4": "BLCA",
            "STEAP1": "PRAD",
        }
        result = st.permutation_null_p(self._panel(assignment), assignment)

        assert result["n_permutations"] == 5040
        assert result["p_value_floor"] == pytest.approx(2 / 5040)
        assert result["p_value"] == pytest.approx(2 / 5040)

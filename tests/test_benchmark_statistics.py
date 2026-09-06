# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the rediscovery null models and interval estimates.

These assert against values that can be checked by hand or against published
worked examples, not merely against the code's own behaviour. A statistics module
whose tests only confirm it does what it does is worth nothing.
"""

from __future__ import annotations

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

    def test_requires_decoys(self) -> None:
        with pytest.raises(ValueError, match="at least one decoy"):
            st.decoy_null_p(5, [])


class TestDecoyMatching:
    @staticmethod
    def _pool() -> list[dict[str, object]]:
        return [
            {"uniprot": f"P{i:05d}", "base_mean_decile": i % 10, "dispersion_decile": i % 3}
            for i in range(300)
        ]

    def test_decoys_share_the_target_strata(self) -> None:
        target = {"uniprot": "TARGET", "base_mean_decile": 4, "dispersion_decile": 1}
        decoys = st.match_decoys(self._pool(), target, n_decoys=5, seed=2)
        assert decoys
        for d in decoys:
            assert d["base_mean_decile"] == 4
            assert d["dispersion_decile"] == 1

    def test_the_target_is_never_its_own_decoy(self) -> None:
        pool = self._pool()
        target = dict(pool[14])
        decoys = st.match_decoys(pool, target, n_decoys=50, seed=2)
        assert all(d["uniprot"] != target["uniprot"] for d in decoys)

    def test_a_thin_stratum_degrades_to_sampling_with_replacement(self) -> None:
        pool = [
            {"uniprot": "P1", "base_mean_decile": 9, "dispersion_decile": 9},
            {"uniprot": "P2", "base_mean_decile": 9, "dispersion_decile": 9},
        ]
        target = {"uniprot": "T", "base_mean_decile": 9, "dispersion_decile": 9}
        decoys = st.match_decoys(pool, target, n_decoys=10, seed=1)
        assert len(decoys) == 10

    def test_missing_strata_is_an_error_not_a_silent_mismatch(self) -> None:
        with pytest.raises(ValueError, match="strata"):
            st.match_decoys(self._pool(), {"uniprot": "T"}, n_decoys=2)


class TestPermutationNull:
    def test_perfect_indication_matching_is_significant(self) -> None:
        """Each antigen scores well only in its own cohort."""
        scores = {
            "A": {"ca": 1.0, "cb": 0.0, "cc": 0.0},
            "B": {"ca": 0.0, "cb": 1.0, "cc": 0.0},
            "C": {"ca": 0.0, "cb": 0.0, "cc": 1.0},
        }
        p = st.permutation_null_p(1.0, scores, n_perm=2000, seed=5)
        assert p < 0.2

    def test_generic_biology_is_not_significant(self) -> None:
        """If every antigen scores the same everywhere, matching means nothing."""
        scores = {a: {c: 0.5 for c in ("ca", "cb", "cc")} for a in ("A", "B", "C")}
        p = st.permutation_null_p(0.5, scores, n_perm=2000, seed=5)
        assert p == pytest.approx(1.0)

    def test_a_ragged_score_matrix_is_rejected(self) -> None:
        """A missing score is an unevaluated pair, which would bias the null."""
        with pytest.raises(ValueError, match="ragged"):
            st.permutation_null_p(0.5, {"A": {"ca": 1.0, "cb": 0.0}, "B": {"ca": 0.0}}, n_perm=10)

    def test_needs_more_than_one_antigen(self) -> None:
        with pytest.raises(ValueError, match="at least two antigens"):
            st.permutation_null_p(1.0, {"A": {"ca": 1.0}}, n_perm=10)


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

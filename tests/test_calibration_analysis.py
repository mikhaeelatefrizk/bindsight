# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the ipTM calibration analysis (CPU-only, no GPU run required).

This code turns ``DEFAULT_IPTM_SUCCESS = 0.65`` from a bare constant into a
measured false-positive rate, so its arithmetic ends up in a published claim.
The exact sign-flip test is checked against a brute-force enumeration written a
different way, against cases whose answer is known in closed form, and across
the chunk boundary its vectorised implementation introduces.
"""

from __future__ import annotations

import itertools
import json
import random
import sys
from pathlib import Path
from typing import ClassVar

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "benchmarks" / "calibration"))

import analyse as calib


def _brute_force_p(diffs: list[float]) -> float:
    """The same p-value by direct enumeration, written independently.

    Deliberately not vectorised and not chunked: a reference that shared the
    implementation's structure would agree with its mistakes.
    """
    observed = abs(sum(diffs))
    patterns = list(itertools.product((1, -1), repeat=len(diffs)))
    extreme = sum(
        1
        for signs in patterns
        if abs(sum(s * d for s, d in zip(signs, diffs, strict=True))) >= observed - 1e-12
    )
    return extreme / len(patterns)


class TestTheExactSignFlipTest:
    def test_it_matches_a_brute_force_enumeration(self) -> None:
        rng = random.Random(20260912)
        for _ in range(8):
            diffs = [rng.uniform(-0.4, 0.6) for _ in range(6)]
            p, n_perm = calib.exact_signflip_p(diffs)
            assert n_perm == 2**6
            assert p == pytest.approx(_brute_force_p(diffs), abs=1e-12)

    def test_a_uniform_shift_gives_the_smallest_attainable_p(self) -> None:
        """All differences one way: only the all-plus and all-minus patterns tie.

        Two of 2^n, not one — the test is two-sided, so the mirror of the
        observed assignment is always as extreme as the observation.
        """
        p, n_perm = calib.exact_signflip_p([0.2] * 10)
        assert p == pytest.approx(2 / 2**10)
        assert n_perm == 1024

    def test_one_pair_can_never_be_significant(self) -> None:
        """With n=1 both sign patterns are as extreme as the observation."""
        assert calib.exact_signflip_p([0.9])[0] == pytest.approx(1.0)

    def test_differences_that_cancel_are_not_evidence(self) -> None:
        p, _ = calib.exact_signflip_p([0.3, -0.3, 0.3, -0.3])
        assert p == pytest.approx(1.0)

    def test_the_chunk_boundary_does_not_change_the_answer(self, monkeypatch) -> None:
        """The enumeration is chunked to bound memory; that must be invisible.

        With n=17 the null has 131,072 members and the default chunk is 65,536,
        so the loop runs more than once. Forcing an awkward chunk size that
        divides neither evenly catches an off-by-one in the final partial chunk.
        """
        rng = random.Random(7)
        diffs = [rng.uniform(-0.3, 0.5) for _ in range(17)]
        baseline, n_perm = calib.exact_signflip_p(diffs)
        assert n_perm == 2**17

        monkeypatch.setattr(calib, "_CHUNK", 1000)
        awkward, _ = calib.exact_signflip_p(diffs)
        assert awkward == pytest.approx(baseline, abs=1e-12)

    def test_it_refuses_rather_than_hangs_on_too_many_pairs(self) -> None:
        with pytest.raises(ValueError, match="sign patterns"):
            calib.exact_signflip_p([0.1] * 23)

    def test_it_refuses_an_empty_comparison(self) -> None:
        with pytest.raises(ValueError, match="no pairs"):
            calib.exact_signflip_p([])

    def test_a_p_at_the_floor_is_reported_as_a_floor(self, tmp_path: Path) -> None:
        """An exact test's p is never zero, and its smallest value is a ceiling on evidence.

        With twenty pairs only the observed assignment and its mirror are as
        extreme as a perfect separation, so p bottoms out at 2/2**20. Reporting
        that as "vanishingly significant" would claim more than twenty pairs
        can carry, which is why the study's decoy null reports its own floor too.
        """
        rows: dict[str, float | None] = {}
        for i in range(20):
            rows[f"b{i}"] = 0.80 + i * 0.005
            rows[f"b{i}_scram"] = 0.20 + i * 0.005
        report = calib.analyse(_metrics(tmp_path / "m.jsonl", rows), committed=None)
        assert report["exact_signflip_p_floor"] == pytest.approx(2 / 2**20)
        assert report["exact_signflip_p"] == pytest.approx(report["exact_signflip_p_floor"])
        assert "floor for 20 pairs" in calib.render(report)

    def test_a_small_p_does_not_render_as_zero(self) -> None:
        """``{:.5f}`` turns the twenty-pair floor into ``0.00000``."""
        assert calib._fmt_p(2 / 2**20) == "1.91e-06"
        assert calib._fmt_p(0.032) == "0.03200"


def _metrics(path: Path, rows: dict[str, float | None]) -> Path:
    path.write_text(
        "\n".join(
            json.dumps({"binder_id": b, "target_uniprot": "P04626", "iptm": v})
            for b, v in rows.items()
        )
        + "\n",
        encoding="utf-8",
    )
    return path


class TestTheNullResultCarriesItsOwnPower:
    """ "No difference found" and "no difference larger than X" are different claims.

    Only the second is what twenty pairs can support, and a null reported
    without it reads as the first.
    """

    def test_it_reports_what_the_run_could_have_detected(self) -> None:
        rng = random.Random(11)
        diffs = [rng.gauss(0.03, 0.23) for _ in range(20)]
        ci = calib.paired_interval(diffs)
        assert ci["n_pairs"] == 20
        # The detectable effect scales with spread over root-n.
        assert ci["min_detectable_difference_80pct"] == pytest.approx(
            2.8016 * ci["sd"] / 20**0.5, rel=1e-3
        )

    def test_a_wider_spread_needs_a_bigger_effect(self) -> None:
        tight = calib.paired_interval([0.05, 0.04, 0.06, 0.05] * 5)
        loose = calib.paired_interval([0.5, -0.4, 0.6, -0.5] * 5)
        assert loose["min_detectable_difference_80pct"] > tight["min_detectable_difference_80pct"]

    def test_the_interval_brackets_the_mean(self) -> None:
        rng = random.Random(5)
        diffs = [rng.gauss(0.2, 0.1) for _ in range(20)]
        ci = calib.paired_interval(diffs)
        assert ci["low"] < ci["mean"] < ci["high"]

    def test_a_clear_effect_excludes_zero_and_a_null_does_not(self) -> None:
        clear = calib.paired_interval([0.3] * 10 + [0.25] * 10)
        assert clear["low"] > 0
        rng = random.Random(2)
        null = calib.paired_interval([rng.gauss(0.0, 0.25) for _ in range(20)])
        assert null["low"] < 0 < null["high"]

    def test_it_is_reproducible(self) -> None:
        """A published interval that moves between runs is not a published interval."""
        diffs = [0.1, -0.2, 0.3, 0.05, -0.15, 0.4, 0.0, -0.3, 0.2, 0.1]
        assert calib.paired_interval(diffs) == calib.paired_interval(diffs)

    def test_one_pair_reports_that_it_bounds_nothing(self) -> None:
        """A single pair has no spread to resample.

        It must say so rather than emit a degenerate zero-width interval, which
        would read as the most precise result in the file.
        """
        ci = calib.paired_interval([0.3])
        assert ci["estimable"] is False
        assert "low" not in ci
        assert "high" not in ci

    def test_no_pairs_at_all_is_refused(self) -> None:
        with pytest.raises(ValueError, match="no pairs"):
            calib.paired_interval([])

    def test_the_report_states_the_bound(self, tmp_path: Path) -> None:
        rows: dict[str, float | None] = {}
        rng = random.Random(9)
        for i in range(20):
            v = rng.uniform(0.2, 0.9)
            rows[f"b{i}"] = v
            rows[f"b{i}_scram"] = v + rng.uniform(-0.3, 0.3)
        text = calib.render(calib.analyse(_metrics(tmp_path / "m.jsonl", rows), committed=None))
        assert "bootstrap interval on the mean difference" in text
        assert "bounds any real advantage rather than showing there is none" in text


class TestTheComparisonIsPaired:
    def test_each_design_is_matched_to_its_own_scramble(self, tmp_path: Path) -> None:
        m = _metrics(
            tmp_path / "metrics.jsonl",
            {"b0": 0.80, "b0_scram": 0.30, "b1": 0.70, "b1_scram": 0.20},
        )
        report = calib.analyse(m, committed=None)
        assert report["n_pairs"] == 2
        assert report["n_designs_above_scramble"] == 2
        assert report["paired_difference"]["mean"] == pytest.approx(0.50)
        by_id = {p["binder_id"]: p for p in report["pairs"]}
        assert by_id["b0"]["scramble"] == pytest.approx(0.30)
        assert by_id["b1"]["scramble"] == pytest.approx(0.20)

    def test_a_design_without_its_scramble_is_dropped(self, tmp_path: Path) -> None:
        """An unpaired design would otherwise be compared against nothing."""
        m = _metrics(
            tmp_path / "metrics.jsonl",
            {"b0": 0.80, "b0_scram": 0.30, "lonely": 0.99},
        )
        report = calib.analyse(m, committed=None)
        assert report["n_pairs"] == 1
        assert [p["binder_id"] for p in report["pairs"]] == ["b0"]

    def test_a_run_with_no_pairs_is_refused(self, tmp_path: Path) -> None:
        """Scrambles alone were the first submission; they cannot be analysed.

        Comparing them against the committed designs would cross two jobs, and
        the whole point of folding both arms together is that it does not.
        """
        m = _metrics(tmp_path / "metrics.jsonl", {"b0_scram": 0.3, "b1_scram": 0.4})
        with pytest.raises(ValueError, match="no design/scramble pairs"):
            calib.analyse(m, committed=None)

    def test_rows_without_an_iptm_are_skipped(self, tmp_path: Path) -> None:
        m = _metrics(
            tmp_path / "metrics.jsonl",
            {"b0": 0.8, "b0_scram": 0.3, "b1": None, "b1_scram": 0.4},
        )
        assert calib.analyse(m, committed=None)["n_pairs"] == 1


class TestTheThresholdGetsAFalsePositiveRate:
    """The deliverable: 0.65 stops being a bare constant and gains a rate."""

    def test_the_scramble_pass_rate_is_reported_at_the_shipped_threshold(
        self, tmp_path: Path
    ) -> None:
        m = _metrics(
            tmp_path / "metrics.jsonl",
            # two designs clear 0.65, one scramble does
            {"b0": 0.90, "b0_scram": 0.70, "b1": 0.66, "b1_scram": 0.40},
        )
        report = calib.analyse(m, committed=None)
        assert report["threshold"] == calib.DEFAULT_IPTM_SUCCESS == 0.65
        assert report["design_pass_rate"] == pytest.approx(1.0)
        assert report["scramble_pass_rate"] == pytest.approx(0.5)

    def test_the_sweep_covers_the_shipped_threshold(self, tmp_path: Path) -> None:
        m = _metrics(tmp_path / "metrics.jsonl", {"b0": 0.9, "b0_scram": 0.1})
        report = calib.analyse(m, committed=None)
        assert calib.DEFAULT_IPTM_SUCCESS in [r["threshold"] for r in report["sweep"]]

    def test_scrambles_scoring_like_designs_are_not_evidence(self, tmp_path: Path) -> None:
        """The outcome that would invalidate the metric must read as such.

        If ipTM is reporting something about the target rather than the design,
        the scrambles match the designs and the analysis has to say so rather
        than finding a difference anyway.
        """
        rows: dict[str, float | None] = {}
        rng = random.Random(3)
        for i in range(10):
            v = rng.uniform(0.3, 0.8)
            rows[f"b{i}"] = v
            rows[f"b{i}_scram"] = v + rng.uniform(-0.05, 0.05)
        report = calib.analyse(_metrics(tmp_path / "m.jsonl", rows), committed=None)
        assert report["exact_signflip_p"] > 0.05
        assert report["scramble_pass_rate"] == pytest.approx(report["design_pass_rate"], abs=0.2)


class TestTheOperatingPointIsBoundedNotEyeballed:
    """A sweep is a table to read; an operating point is a decision with a bound.

    The bound used is the interval's upper limit, not the point estimate,
    because twenty controls resolve a rate to steps of 5% and zero-of-twenty is
    not a 0% false-positive rate.
    """

    _SEPARATED = ([0.80 + i * 0.005 for i in range(20)], [0.20 + i * 0.005 for i in range(20)])

    def test_it_picks_the_lowest_threshold_that_clears_the_bound(self) -> None:
        """Lowest, not highest: raising it further only discards real designs."""
        designs, scrambles = self._SEPARATED
        op = calib.operating_point(designs, scrambles, max_fpr=0.25)
        assert op["reachable"] is True
        assert op["design_pass_rate"]["point"] == pytest.approx(1.0)
        assert op["design_pass_rate"]["n"] == len(designs)
        below = round(op["threshold"] - 0.01, 2)
        assert calib._fpr(scrambles, below)["upper95"] > 0.25

    def test_it_judges_on_the_upper_bound_not_the_point_estimate(self) -> None:
        """Zero of twenty passing is not proof of a rate below 16.8%."""
        designs, scrambles = self._SEPARATED
        op = calib.operating_point(designs, scrambles, max_fpr=0.25)
        assert op["false_positive_rate"]["point"] == 0.0
        assert op["false_positive_rate"]["upper95"] == pytest.approx(0.168, abs=0.001)

    def test_an_unreachable_bound_blames_the_control_set_not_the_designs(self) -> None:
        """Twenty controls cannot certify 5% however cleanly the arms separate.

        The record has to say that, because "no 5% operating point" read as a
        statement about the designs is the wrong conclusion entirely.
        """
        designs, scrambles = self._SEPARATED
        op = calib.operating_point(designs, scrambles, max_fpr=0.05)
        assert op["reachable"] is False
        assert op["n_controls"] == 20
        assert op["n_controls_needed"] == 72
        assert "threshold" not in op

    def test_controls_needed_is_the_smallest_n_that_actually_works(self) -> None:
        """Checked against the interval it has to satisfy, not against itself."""
        from bindsight.benchmark.statistics import clopper_pearson_interval

        for max_fpr in (0.25, 0.10, 0.05, 0.02):
            n = calib.controls_needed_for(max_fpr)
            assert clopper_pearson_interval(0, n).high <= max_fpr
            assert clopper_pearson_interval(0, n - 1).high > max_fpr

    def test_a_meaningless_bound_is_refused(self) -> None:
        for bad in (0.0, 1.0, -0.1, 1.5):
            with pytest.raises(ValueError, match="max_fpr"):
                calib.controls_needed_for(bad)

    def test_reachable_is_not_the_same_as_useful(self) -> None:
        """Controls scoring above the designs still admit a threshold: 1.00.

        It excludes every control, and every design with them. That is a real
        answer — the metric does not separate — and it has to surface as a
        design pass rate of zero rather than as a missing operating point,
        because "no operating point" and "an operating point that keeps
        nothing" are different findings.
        """
        designs, _ = self._SEPARATED
        op = calib.operating_point(designs, [0.99] * 20, max_fpr=0.25)
        assert op["reachable"] is True
        assert op["design_pass_rate"]["point"] == 0.0
        assert op["design_pass_rate"]["n_passing"] == 0

    def test_the_report_carries_both_bounds(self, tmp_path: Path) -> None:
        rows: dict[str, float | None] = {}
        for i in range(20):
            rows[f"b{i}"] = 0.80 + i * 0.005
            rows[f"b{i}_scram"] = 0.20 + i * 0.005
        report = calib.analyse(_metrics(tmp_path / "m.jsonl", rows), committed=None)
        assert [op["max_fpr"] for op in report["operating_points"]] == [0.25, 0.05]
        # An unreachable bound is kept, not filtered out; dropping it would make
        # the report silently omit the limit the run actually hit.
        assert any(not op["reachable"] for op in report["operating_points"])


class TestTheReadmePowerTableIsTheRealOne:
    """The README states what twenty controls can and cannot establish.

    It decides the next experiment's size, so it is recomputed here rather than
    trusted. A table of numbers in prose drifts the moment anything under it
    moves — a changed confidence level would leave it quietly wrong.
    """

    _README = Path(__file__).resolve().parents[1] / "benchmarks" / "calibration" / "README.md"

    def test_every_row_matches_the_interval_it_claims(self) -> None:
        import re

        from bindsight.benchmark.statistics import clopper_pearson_interval

        text = self._README.read_text(encoding="utf-8")
        rows = re.findall(r"^\| (\d+) \| ([\d.]+)% \|$", text, re.M)
        assert len(rows) >= 4, "the power table is missing from the README"
        for n_str, claimed in rows:
            actual = clopper_pearson_interval(0, int(n_str)).high * 100
            assert actual == pytest.approx(float(claimed), abs=0.05), (
                f"README says {claimed}% for {n_str} controls; it is {actual:.2f}%"
            )

    def test_the_seventy_two_the_readme_plans_around_is_derived(self) -> None:
        """The stated next experiment is sized off this number."""
        assert calib.controls_needed_for(0.05) == 72
        assert "72" in self._README.read_text(encoding="utf-8")


class TestTheMetricsOwnNoiseIsMeasured:
    """With more than one draw per binder the noise stops being an inference.

    Before this, the only handle on ipTM's spread was refolding across runs,
    which mixed sampling noise with everything else that differed between them
    — in this project's case an unrecorded Boltz-2 version among them. Drawn
    repeatedly inside one job, on one input, under one installed version,
    nothing is confounded with anything.
    """

    @staticmethod
    def _rows(sd: float, k: int = 5, n: int = 20) -> list[dict[str, object]]:
        return [
            {"binder_id": f"b{i}", "iptm": 0.5, "iptm_sd": sd, "iptm_n_samples": k}
            for i in range(n)
        ]

    def test_single_draw_runs_have_no_spread_to_report(self) -> None:
        """The honest answer for every run before the sampling fix."""
        rows = [{"binder_id": "b0", "iptm": 0.5, "iptm_n_samples": 1}]
        assert calib.sampling_noise(rows) is None

    def test_rows_predating_the_field_are_not_guessed_at(self) -> None:
        assert calib.sampling_noise([{"binder_id": "b0", "iptm": 0.5}]) is None

    def test_the_pooled_spread_averages_variances_not_deviations(self) -> None:
        """Standard deviations do not average; their squares do.

        Pooling them as a plain mean understates the spread whenever the
        per-binder values differ, which is exactly when pooling matters.
        """
        rows = [
            {"binder_id": "a", "iptm": 0.5, "iptm_sd": 0.10, "iptm_n_samples": 5},
            {"binder_id": "b", "iptm": 0.5, "iptm_sd": 0.30, "iptm_n_samples": 5},
        ]
        noise = calib.sampling_noise(rows)
        rms = ((0.10**2 + 0.30**2) / 2) ** 0.5
        assert noise["pooled_per_draw_sd"] == pytest.approx(rms)
        assert noise["pooled_per_draw_sd"] > (0.10 + 0.30) / 2

    def test_the_standard_error_shrinks_with_the_draw_count(self) -> None:
        """Averaging k draws is worth sqrt(k), and the report must say so."""
        one = calib.sampling_noise(self._rows(0.16, k=1))
        five = calib.sampling_noise(self._rows(0.16, k=5))
        assert one["standard_error_of_reported_mean"] == pytest.approx(0.16)
        assert five["standard_error_of_reported_mean"] == pytest.approx(0.16 / 5**0.5)

    def test_mixed_draw_counts_are_reported_not_hidden(self) -> None:
        """A run that averaged different numbers of draws is not one measurement."""
        rows = self._rows(0.1, k=5, n=2) + self._rows(0.1, k=3, n=2)
        noise = calib.sampling_noise(rows)
        assert noise["draws_per_binder"] == [3, 5]

    def test_the_report_says_when_the_effect_is_under_the_noise_floor(self, tmp_path: Path) -> None:
        """The whole point: an effect smaller than one input's own spread.

        A difference between two designs smaller than the spread of a single
        design's repeated draws was not observed, and the report has to say that
        rather than leaving a reader to compare the two numbers themselves.
        """
        rows: list[dict[str, object]] = []
        for i in range(20):
            rows.append({"binder_id": f"b{i}", "iptm": 0.60, "iptm_sd": 0.16, "iptm_n_samples": 5})
            rows.append(
                {
                    "binder_id": f"b{i}_scram",
                    "iptm": 0.57,
                    "iptm_sd": 0.16,
                    "iptm_n_samples": 5,
                }
            )
        m = tmp_path / "m.jsonl"
        m.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
        text = calib.render(calib.analyse(m, committed=None))
        assert "underneath the metric's noise floor" in text

    def test_the_report_says_when_the_effect_clears_it(self, tmp_path: Path) -> None:
        rows: list[dict[str, object]] = []
        for i in range(20):
            rows.append({"binder_id": f"b{i}", "iptm": 0.90, "iptm_sd": 0.02, "iptm_n_samples": 5})
            rows.append(
                {
                    "binder_id": f"b{i}_scram",
                    "iptm": 0.20,
                    "iptm_sd": 0.02,
                    "iptm_n_samples": 5,
                }
            )
        m = tmp_path / "m.jsonl"
        m.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
        text = calib.render(calib.analyse(m, committed=None))
        assert "above the metric's noise floor" in text

    def test_a_single_draw_run_renders_without_the_section(self, tmp_path: Path) -> None:
        """The first calibration run has no such data and must still render."""
        rows = [
            {"binder_id": "b0", "iptm": 0.8, "iptm_n_samples": 1},
            {"binder_id": "b0_scram", "iptm": 0.3, "iptm_n_samples": 1},
            {"binder_id": "b1", "iptm": 0.7, "iptm_n_samples": 1},
            {"binder_id": "b1_scram", "iptm": 0.2, "iptm_n_samples": 1},
        ]
        m = tmp_path / "m.jsonl"
        m.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
        report = calib.analyse(m, committed=None)
        assert report["sampling_noise"] is None
        assert "The metric's own noise" not in calib.render(report)


class TestTheVarianceIsAttributed:
    """Which experiment to run next depends on where the spread lives.

    The five-draw run measured this: averaging five structures per binder left
    the paired spread at 0.230, against 0.231 with a single draw. Almost
    unchanged — so the spread is not the validator resampling, and buying more
    draws would have bought nothing. That is the opposite of the obvious
    conclusion from the first run, and only the split shows it.
    """

    @staticmethod
    def _noise(se: float) -> dict[str, object]:
        return {
            "standard_error_of_reported_mean": se,
            "pooled_per_draw_sd": se * 5**0.5,
            "draws_per_binder": [5],
            "n_binders_with_spread": 40,
        }

    def test_pure_sampling_noise_is_attributed_to_sampling(self) -> None:
        """Two arms each with standard error se give a paired sd of se*sqrt(2)."""
        se = 0.1
        split = calib.variance_decomposition(se * 2**0.5, self._noise(se))
        assert split["sampling_share"] == pytest.approx(1.0, abs=1e-9)
        assert split["between_pair_share"] == pytest.approx(0.0, abs=1e-9)

    def test_spread_far_beyond_the_noise_is_attributed_to_the_pairs(self) -> None:
        split = calib.variance_decomposition(0.5, self._noise(0.01))
        assert split["between_pair_share"] > 0.99

    def test_the_shares_sum_to_one(self) -> None:
        split = calib.variance_decomposition(0.23, self._noise(0.0623))
        assert split["sampling_share"] + split["between_pair_share"] == pytest.approx(1.0)

    def test_noise_larger_than_the_spread_does_not_go_negative(self) -> None:
        """Sampling estimated above the total is rounding, not anti-variance."""
        split = calib.variance_decomposition(0.05, self._noise(0.3))
        assert split["between_pair_variance"] == 0.0
        assert split["between_pair_share"] == 0.0

    def test_more_pairs_are_required_for_a_smaller_effect(self) -> None:
        split = calib.variance_decomposition(0.23, self._noise(0.0623))
        needed = {p["effect"]: p["n_pairs"] for p in split["pairs_needed"]}
        assert needed[0.05] > needed[0.10]
        # Quartering the effect quadruples the pairs, as n scales with 1/effect^2.
        assert needed[0.05] == pytest.approx(needed[0.10] * 4, rel=0.1)

    def test_a_single_draw_run_cannot_be_split(self) -> None:
        """Nothing measured the noise, so nothing can be subtracted from it."""
        assert calib.variance_decomposition(0.23, None) is None

    def test_the_report_names_the_experiment_that_would_help(self, tmp_path: Path) -> None:
        rows: list[dict[str, object]] = []
        for i in range(20):
            rows.append(
                {"binder_id": f"b{i}", "iptm": 0.5 + i * 0.02, "iptm_sd": 0.05, "iptm_n_samples": 5}
            )
            rows.append(
                {
                    "binder_id": f"b{i}_scram",
                    "iptm": 0.5 - i * 0.02,
                    "iptm_sd": 0.05,
                    "iptm_n_samples": 5,
                }
            )
        m = tmp_path / "m.jsonl"
        m.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
        text = calib.render(calib.analyse(m, committed=None))
        assert "Where the spread actually is" in text
        assert "pairs**, however many draws each gets" in text


class TestRefoldDriftIsLabelledForWhatItIs:
    def test_drift_is_reported_against_committed_values(self, tmp_path: Path) -> None:
        m = _metrics(tmp_path / "metrics.jsonl", {"b0": 0.80, "b0_scram": 0.30})
        committed = _metrics(tmp_path / "committed.jsonl", {"b0": 0.78})
        drift = calib.analyse(m, committed=committed)["refold_drift"]
        assert drift["n"] == 1
        assert drift["per_binder"][0]["delta"] == pytest.approx(0.02)
        assert drift["abs_delta"]["max"] == pytest.approx(0.02)

    def test_it_is_not_called_determinism(self, tmp_path: Path) -> None:
        """The committed run's Boltz-2 version was never recorded.

        So this number bounds run drift and version drift together. Calling it
        determinism would claim one source for a quantity with two.
        """
        m = _metrics(tmp_path / "metrics.jsonl", {"b0": 0.80, "b0_scram": 0.30})
        committed = _metrics(tmp_path / "committed.jsonl", {"b0": 0.78})
        note = calib.analyse(m, committed=committed)["refold_drift"]["note"]
        assert "not determinism" in note

    def test_no_drift_section_without_committed_values(self, tmp_path: Path) -> None:
        m = _metrics(tmp_path / "metrics.jsonl", {"b0": 0.80, "b0_scram": 0.30})
        assert "refold_drift" not in calib.analyse(m, committed=tmp_path / "absent.jsonl")


class TestTheReportRenders:
    def test_it_states_both_rates_and_the_p_value(self, tmp_path: Path) -> None:
        m = _metrics(
            tmp_path / "metrics.jsonl",
            {f"b{i}": 0.8 for i in range(6)} | {f"b{i}_scram": 0.3 for i in range(6)},
        )
        text = calib.render(calib.analyse(m, committed=None))
        assert "0.65" in text
        assert "false-positive rate" in text
        assert "sign-flip" in text
        # The table must carry both arms, not just the flattering one.
        assert "| designs |" in text
        assert "| scrambles |" in text


class TestTheSpecificityComparison:
    """Whether these designs distinguish the target they were designed for.

    The scramble control asks whether the binder's sequence carries the score.
    This asks whether the target does — and a design that scores as well against
    a receptor it was not designed for is not a binder for either one, which
    would leave the metric unable to support target selection at all.
    """

    @staticmethod
    def _write(path: Path, rows: list[dict[str, object]]) -> Path:
        path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
        return path

    def _arms(self, tmp_path: Path, native: float, decoy: float, n: int = 20) -> tuple[Path, Path]:
        a = [
            {"binder_id": f"b{i}", "iptm": native + i * 0.001, "iptm_n_samples": 5}
            for i in range(n)
        ] + [{"binder_id": f"b{i}_scram", "iptm": 0.4, "iptm_n_samples": 5} for i in range(n)]
        b = [
            {"binder_id": f"b{i}", "iptm": decoy + i * 0.001, "iptm_n_samples": 5} for i in range(n)
        ] + [{"binder_id": f"b{i}_scram", "iptm": 0.4, "iptm_n_samples": 5} for i in range(n)]
        return (
            self._write(tmp_path / "native.jsonl", a),
            self._write(tmp_path / "decoy.jsonl", b),
        )

    def test_a_design_is_compared_against_itself(self, tmp_path: Path) -> None:
        """Paired, so the comparison does not depend on the sets matching elsewhere."""
        native, decoy = self._arms(tmp_path, 0.70, 0.30)
        xt = calib.cross_target(native, decoy)
        assert xt["n_designs"] == 20
        assert xt["paired_difference"]["mean"] == pytest.approx(0.40)
        assert xt["n_higher_on_native"] == 20

    def test_scrambles_are_left_out_of_the_comparison(self, tmp_path: Path) -> None:
        """A shuffle's score against a decoy answers nothing its design does not.

        Pooling them would also hide which arm a row belongs to.
        """
        native, decoy = self._arms(tmp_path, 0.70, 0.30)
        xt = calib.cross_target(native, decoy)
        assert all(not d["binder_id"].endswith("_scram") for d in xt["per_design"])

    def test_no_difference_reads_as_no_difference(self, tmp_path: Path) -> None:
        """The outcome that would invalidate target selection must read as such."""
        native, decoy = self._arms(tmp_path, 0.55, 0.55)
        xt = calib.cross_target(native, decoy)
        assert xt["exact_signflip_p"] > 0.05
        assert xt["native_pass_rate"] == pytest.approx(xt["decoy_pass_rate"])

    def test_both_pass_rates_are_reported(self, tmp_path: Path) -> None:
        native, decoy = self._arms(tmp_path, 0.70, 0.30)
        xt = calib.cross_target(native, decoy)
        assert xt["native_pass_rate"] == pytest.approx(1.0)
        assert xt["decoy_pass_rate"] == pytest.approx(0.0)

    def test_runs_with_no_shared_binder_yield_nothing(self, tmp_path: Path) -> None:
        """Two unrelated runs are not a paired comparison."""
        a = self._write(
            tmp_path / "a.jsonl", [{"binder_id": "x", "iptm": 0.5, "iptm_n_samples": 5}]
        )
        b = self._write(
            tmp_path / "b.jsonl", [{"binder_id": "y", "iptm": 0.5, "iptm_n_samples": 5}]
        )
        assert calib.cross_target(a, b) == {}

    def test_the_section_is_absent_without_a_decoy_run(self, tmp_path: Path) -> None:
        native, _ = self._arms(tmp_path, 0.70, 0.30)
        report = calib.analyse(native, committed=None)
        assert report["cross_target"] is None
        assert "Does the target matter?" not in calib.render(report)

    def test_the_section_states_both_arms_and_the_pairing(self, tmp_path: Path) -> None:
        native, decoy = self._arms(tmp_path, 0.70, 0.30)
        text = calib.render(calib.analyse(native, committed=None, decoy_metrics=decoy))
        assert "Does the target matter?" in text
        assert "designed target" in text
        assert "unrelated target" in text
        assert "two jobs" in text, "the cross-run caveat must travel with the number"


class TestTheControlledSpecificityComparison:
    """Raw native-versus-decoy is confounded by the decoy's own baseline.

    The specificity run measured it: the unrelated receptor scored higher with
    *everything*, and its shuffles rose further than its designs did. A target
    that folds well with any partner moves both arms, so the raw comparison
    reports the target's propensity rather than whether these binders pick it
    out — and it did so with p = 0.011 pointing the wrong way.

    Subtracting each binder's own shuffle on each target cancels whatever the
    target contributes to every partner. What is left is the question
    specificity actually asks.
    """

    @staticmethod
    def _write(path: Path, rows: dict[str, float]) -> Path:
        path.write_text(
            "\n".join(
                json.dumps({"binder_id": b, "iptm": v, "iptm_n_samples": 5})
                for b, v in rows.items()
            )
            + "\n",
            encoding="utf-8",
        )
        return path

    def _arms(
        self, tmp_path: Path, *, nd: float, ns: float, dd: float, ds: float, n: int = 20
    ) -> tuple[Path, Path]:
        """Two runs with given design/shuffle means on each target."""
        native = {}
        decoy = {}
        for i in range(n):
            native[f"b{i}"] = nd + i * 0.001
            native[f"b{i}_scram"] = ns + i * 0.001
            decoy[f"b{i}"] = dd + i * 0.001
            decoy[f"b{i}_scram"] = ds + i * 0.001
        return (
            self._write(tmp_path / "native.jsonl", native),
            self._write(tmp_path / "decoy.jsonl", decoy),
        )

    def test_a_decoy_that_lifts_everything_is_not_read_as_specificity(self, tmp_path: Path) -> None:
        """The exact shape the real run produced.

        Designs score lower on their own target *and* shuffles score lower
        still, so the design-minus-shuffle advantage is the same on both. The
        raw comparison screams; the controlled one is silent, and the
        controlled one is right.
        """
        native, decoy = self._arms(tmp_path, nd=0.50, ns=0.45, dd=0.70, ds=0.65)
        xt = calib.cross_target(native, decoy)

        assert xt["paired_difference"]["mean"] < 0, "raw comparison favours the decoy"
        ctl = xt["controlled"]
        assert ctl["difference_in_differences"] == pytest.approx(0.0, abs=1e-9)
        assert ctl["exact_signflip_p"] == pytest.approx(1.0)

    def test_real_specificity_survives_the_control(self, tmp_path: Path) -> None:
        """A design that genuinely beats its shuffle only on its own target."""
        native, decoy = self._arms(tmp_path, nd=0.80, ns=0.40, dd=0.70, ds=0.70)
        ctl = calib.cross_target(native, decoy)["controlled"]
        assert ctl["difference_in_differences"] == pytest.approx(0.40, abs=1e-9)
        assert ctl["exact_signflip_p"] < 0.01
        assert ctl["n_favouring_own_target"] == 20

    def test_both_shuffle_means_are_recorded(self, tmp_path: Path) -> None:
        """The prose cites them, so they come from the artifact."""
        native, decoy = self._arms(tmp_path, nd=0.50, ns=0.45, dd=0.70, ds=0.65)
        ctl = calib.cross_target(native, decoy)["controlled"]
        assert ctl["native_scramble_mean"] == pytest.approx(0.45 + 0.0095, abs=1e-6)
        assert ctl["decoy_scramble_mean"] == pytest.approx(0.65 + 0.0095, abs=1e-6)

    def test_without_shuffles_there_is_no_controlled_comparison(self, tmp_path: Path) -> None:
        """It cannot be faked from designs alone, so it reports nothing."""
        native = self._write(tmp_path / "n.jsonl", {f"b{i}": 0.5 for i in range(5)})
        decoy = self._write(tmp_path / "d.jsonl", {f"b{i}": 0.7 for i in range(5)})
        assert calib.cross_target(native, decoy)["controlled"] is None

    def test_the_report_leads_with_the_confound(self, tmp_path: Path) -> None:
        native, decoy = self._arms(tmp_path, nd=0.50, ns=0.45, dd=0.70, ds=0.65)
        text = calib.render(calib.analyse(native, committed=None, decoy_metrics=decoy))
        assert "raw comparison is confounded" in text
        assert "beat its own shuffle by more on the receptor it was designed for" in text


# ---------------------------------------------------------------------------
# The prose and the artifact it is rendered from
# ---------------------------------------------------------------------------
CALIBRATION_DIR = Path(__file__).resolve().parents[1] / "benchmarks" / "calibration"


class TestTheCalibrationProseIsRenderedNotWritten:
    """``analyse.py`` writes RESULTS.json and CALIBRATION.md from one report in
    one call, so they cannot disagree at the moment they are written. They can
    disagree afterwards: editing the prose, or regenerating the JSON alone,
    leaves a page whose numbers no longer come from anything. Nothing checked.
    """

    @staticmethod
    def _committed() -> tuple[dict, str]:
        results = CALIBRATION_DIR / "RESULTS.json"
        page = CALIBRATION_DIR / "CALIBRATION.md"
        if not results.is_file() or not page.is_file():
            pytest.skip("calibration artifacts not present")
        return (
            json.loads(results.read_text(encoding="utf-8")),
            page.read_text(encoding="utf-8"),
        )

    def test_the_committed_page_is_exactly_what_the_artifact_renders_to(self) -> None:
        """Byte-for-byte: this is the same call ``analyse.py`` makes when it
        writes the file, over the committed report."""
        report, page = self._committed()

        assert calib.render(report) == page, (
            "benchmarks/calibration/CALIBRATION.md is not what RESULTS.json renders "
            "to. Re-run analyse.py rather than editing the page by hand."
        )

    def test_the_renderer_actually_depends_on_the_numbers(self) -> None:
        """Guards the guard: a renderer that ignored the report would make the
        comparison above pass against any artifact at all."""
        report, page = self._committed()
        altered = json.loads(json.dumps(report))

        scramble = altered.get("scramble") or altered
        changed = False
        for value in list(scramble.values()):
            if isinstance(value, dict):
                for inner, v in list(value.items()):
                    if isinstance(v, (int, float)) and not isinstance(v, bool):
                        value[inner] = float(v) + 0.123456
                        changed = True
                        break
            if changed:
                break
        assert changed, f"no numeric field found to perturb in {list(scramble)}"

        assert calib.render(altered) != page, (
            "the rendered page is unchanged after perturbing a number in the "
            "report, so it is not derived from it"
        )


class TestTheOperatingPointReportsTheDesignSideAsCarefully:
    """The control side has carried an exact interval since it was written. The
    design side beside it was a bare fraction at a threshold chosen by scanning
    101 candidates against those same controls -- an in-sample figure presented
    like a measurement.
    """

    DESIGNS: ClassVar[list[float]] = [0.9, 0.8, 0.7, 0.66, 0.5, 0.4, 0.3, 0.2]
    SCRAMBLES: ClassVar[list[float]] = [0.2, 0.25, 0.3, 0.35, 0.4, 0.45, 0.5, 0.55]

    def test_the_design_pass_rate_carries_its_count_and_interval(self) -> None:
        op = calib.operating_point(self.DESIGNS, self.SCRAMBLES, max_fpr=0.9)

        assert op["reachable"], op
        keeps = op["design_pass_rate"]
        assert isinstance(keeps, dict), f"still a bare number: {keeps!r}"
        assert keeps["n"] == len(self.DESIGNS)
        assert keeps["n_passing"] <= keeps["n"]
        assert keeps["lower95"] <= keeps["point"] <= keeps["upper95"]

    def test_the_record_says_the_threshold_was_selected_on_the_data(self) -> None:
        op = calib.operating_point(self.DESIGNS, self.SCRAMBLES, max_fpr=0.9)

        assert op["n_thresholds_available"] == 101
        assert 1 <= op["n_thresholds_searched"] <= op["n_thresholds_available"]
        assert "in-sample" in op["selection_note"]

    def test_the_interval_is_the_one_the_rest_of_the_project_reports(self) -> None:
        """Clopper-Pearson from bindsight.benchmark.statistics, not a second
        implementation that could drift from it."""
        from bindsight.benchmark.statistics import clopper_pearson_interval

        op = calib.operating_point(self.DESIGNS, self.SCRAMBLES, max_fpr=0.9)
        keeps = op["design_pass_rate"]
        expected = clopper_pearson_interval(keeps["n_passing"], keeps["n"])

        assert keeps["lower95"] == pytest.approx(expected.low)
        assert keeps["upper95"] == pytest.approx(expected.high)

    def test_an_unreachable_bound_still_blames_the_control_set(self) -> None:
        """Unchanged behaviour, asserted so the change above did not disturb it."""
        op = calib.operating_point(self.DESIGNS, self.SCRAMBLES, max_fpr=0.001)

        assert op["reachable"] is False
        assert op["n_controls"] == len(self.SCRAMBLES)
        assert op["n_controls_needed"] > len(self.SCRAMBLES)

    def test_the_committed_report_states_the_count_and_the_selection(self) -> None:
        page = (CALIBRATION_DIR / "CALIBRATION.md").read_text(encoding="utf-8")
        report = json.loads((CALIBRATION_DIR / "RESULTS.json").read_text(encoding="utf-8"))

        for op in report["operating_points"]:
            if not op["reachable"]:
                continue
            keeps = op["design_pass_rate"]
            assert f"{keeps['n_passing']}/{keeps['n']}" in page, (
                f"the page states no count for the {op['max_fpr']:.0%} operating point"
            )
            assert "in-sample" in page


class TestTheCalibrationReportNamesWhatItRead:
    """RESULTS.json recorded no inputs. Rebuilding it meant scanning every
    metrics.jsonl under runs/ for one whose design mean happened to match the
    committed figure -- a reconstruction, not a record.
    """

    @staticmethod
    def _report() -> dict:
        path = CALIBRATION_DIR / "RESULTS.json"
        if not path.is_file():
            pytest.skip("calibration artifact not present")
        return json.loads(path.read_text(encoding="utf-8"))

    def test_every_input_is_named_with_a_digest(self) -> None:
        inputs = self._report().get("inputs")
        assert inputs, "the calibration report records no inputs"
        assert inputs.get("metrics"), "the primary metrics file is unrecorded"
        for role, entry in inputs.items():
            if entry is None:
                continue
            assert entry.get("path"), role
            assert "\\" not in entry["path"], (
                f"{role} records a Windows-style path, which differs by OS: {entry['path']}"
            )
            assert len(entry.get("sha256", "")) == 64, role

    def test_the_recorded_files_still_hold_what_they_held(self) -> None:
        """A path without a digest check is a path that may have been rewritten."""
        import hashlib

        repo = Path(__file__).resolve().parents[1]
        checked = 0
        for role, entry in (self._report().get("inputs") or {}).items():
            if entry is None:
                continue
            path = repo / entry["path"]
            if not path.is_file():
                pytest.skip(f"{role} input not present in this checkout: {entry['path']}")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            assert digest == entry["sha256"], (
                f"{role} ({entry['path']}) no longer matches the digest the report "
                "was computed from; re-run analyse.py"
            )
            checked += 1
        assert checked, "no input files were checked"

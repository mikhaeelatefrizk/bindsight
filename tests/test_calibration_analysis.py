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
        assert op["design_pass_rate"] == pytest.approx(1.0)
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
        assert op["design_pass_rate"] == 0.0

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

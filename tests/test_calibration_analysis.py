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

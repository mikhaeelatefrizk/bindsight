# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The public results page must derive its claims, not assert them.

``docs/results.md`` is generated, which is what makes it trustworthy — it cannot
drift from the artifacts. That only holds for the parts actually computed from
them. Two sentences were literals: one asserting the numbers came from a real
GPU, and one presenting a difference of two means as confirmatory when the two
are not distinguishable at this sample size.
"""

from __future__ import annotations

import copy
import importlib.util
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _generator() -> Any:
    """Load the generator script as a module (it is a script, not a package)."""
    spec = importlib.util.spec_from_file_location(
        "build_docs_results", ROOT / "scripts" / "build_docs_results.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _showcase(is_mock: bool | None) -> Any:
    """The committed designer benchmark, with its mock flag set."""
    from bindsight.report.showcase import load_designer_benchmark

    d = load_designer_benchmark(ROOT / "benchmarks")
    if d is None:
        pytest.skip("the designer benchmark artifact is not present")
    clone = copy.copy(d)
    object.__setattr__(clone, "is_mock", is_mock)
    return clone


def _provenance_line(module: Any, showcase: Any) -> str:
    """The sentence describing where the numbers came from."""
    for line in module._designer_section(showcase):
        if "backend" in line.lower():
            return line
    raise AssertionError("the section states no provenance at all")


class TestTheRealGpuClaimFollowsTheArtifact:
    """ "A real GPU run, not a simulation" was a string literal.

    The mock backend installs nothing, runs no tool and labels every row
    synthetic — and regenerating this page from a mock run would have published
    those numbers under the words "not a simulation".
    """

    def test_a_real_run_still_says_so(self) -> None:
        line = _provenance_line(_generator(), _showcase(is_mock=False))
        assert "real GPU run" in line
        assert "not a simulation" in line

    def test_a_mock_run_is_labelled_synthetic(self) -> None:
        line = _provenance_line(_generator(), _showcase(is_mock=True))
        assert "real GPU run" not in line
        assert "Synthetic" in line
        assert "no GPU ran" in line

    def test_an_artifact_that_does_not_say_claims_neither(self) -> None:
        """Absence of the flag is not evidence that a GPU ran."""
        line = _provenance_line(_generator(), _showcase(is_mock=None))
        assert "real GPU run" not in line
        assert "Synthetic" not in line
        assert "does not record" in line

    def test_the_committed_page_says_what_the_committed_artifact_says(self) -> None:
        """The page on disk must agree with the flag in the artifact."""
        from bindsight.report.showcase import load_designer_benchmark

        d = load_designer_benchmark(ROOT / "benchmarks")
        if d is None:
            pytest.skip("no designer benchmark artifact")
        page = (ROOT / "docs" / "results.md").read_text(encoding="utf-8")
        if d.is_mock is False:
            assert "real GPU run" in page
        else:
            assert "real GPU run" not in page, (
                "the published page claims a real GPU run that the artifact does not"
            )


class TestTheMeanComparisonCarriesItsInterval:
    """ "The corrected mean is lower … which is what you would expect" had neither.

    Twenty designs at this spread give a mean of 0.51 with a 95% interval of
    roughly 0.40–0.62, and the superseded run's 0.59 sits inside it. Presenting
    that as confirmatory is reporting a preference as a measurement — and the
    protocol correction does not need it: the chain-identity check is the
    evidence.
    """

    def test_the_interval_is_computed_from_the_binders(self) -> None:
        module = _generator()
        result = module._mean_iptm_interval(_showcase(is_mock=False))
        assert result is not None
        mean, low, high = result
        assert low < mean < high

    def test_the_superseded_mean_is_inside_it(self) -> None:
        """The fact that makes the old sentence an overclaim."""
        module = _generator()
        _mean, low, high = module._mean_iptm_interval(_showcase(is_mock=False))
        assert low <= 0.59 <= high

    def test_the_page_says_the_two_are_not_distinguishable(self) -> None:
        page = (ROOT / "docs" / "results.md").read_text(encoding="utf-8")
        assert "not distinguishable at this size" in page
        assert "which is what you would expect" not in page

    def test_the_page_rests_the_correction_on_the_check_not_the_means(self) -> None:
        page = (ROOT / "docs" / "results.md").read_text(encoding="utf-8")
        assert "rests on the chain-identity check" in page

    def test_too_few_binders_yield_no_interval(self) -> None:
        """One design has no spread; the sentence must not invent one."""
        module = _generator()
        one = _showcase(is_mock=False)
        object.__setattr__(one, "binders", list(one.binders)[:1])
        assert module._mean_iptm_interval(one) is None

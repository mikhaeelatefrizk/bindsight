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


class TestTheOutcomeTableNamesItsDenominator:
    """``outcome_class_counts`` counts the pre-registered approved-tier
    denominator. The page rendered it as a single unlabelled column reading
    "Reached the shortlist | 2" directly above a table listing the five pairs
    that reached it, and the figure drew bars summing to 17 for a 22-pair study.
    """

    @staticmethod
    def _study():
        from bindsight.report.showcase import load_study

        study = load_study(ROOT / "benchmarks")
        if study is None:
            pytest.skip("study artifact not present")
        return study

    def test_the_every_tier_counts_account_for_every_scored_pair(self) -> None:
        """The second column's whole purpose is to sum to the pair table."""
        study = self._study()

        assert sum(study.outcome_counts_every_tier.values()) == study.n_scored

    def test_the_primary_counts_cover_fewer_pairs_than_the_panel(self) -> None:
        """If these ever coincide the two columns become redundant, and the
        labelling decision below should be revisited rather than left in place."""
        study = self._study()

        assert study.primary_tiers, "the study no longer records its denominator"
        assert sum(study.outcome_counts.values()) < study.n_scored

    def test_the_primary_counts_are_the_tier_filtered_pairs(self) -> None:
        study = self._study()
        in_tier = [p for p in study.pairs if p.get("tier") in study.primary_tiers]

        for outcome, n in study.outcome_counts.items():
            assert n == sum(1 for p in in_tier if p.get("outcome_class") == outcome), outcome

    def test_the_page_gives_both_columns_and_they_sum_correctly(self) -> None:
        """Read off the rendered page, because that is what a reader meets."""
        page = (ROOT / "docs" / "results.md").read_text(encoding="utf-8")
        study = self._study()

        assert "| Outcome | Approved agents | Every scored pair |" in page, (
            "the outcome table no longer names its two denominators"
        )
        rows = [
            line
            for line in page.splitlines()
            if line.startswith("| ") and line.count("|") == 4 and " | " in line
        ]
        totals = {"primary": 0, "every": 0}
        for line in rows:
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) != 3 or not cells[1].isdigit() or not cells[2].isdigit():
                continue
            totals["primary"] += int(cells[1])
            totals["every"] += int(cells[2])
        assert totals["every"] == study.n_scored, (
            f"the every-pair column sums to {totals['every']}, not the "
            f"{study.n_scored} pairs the study scored"
        )
        assert totals["primary"] == sum(study.outcome_counts.values()), totals

    def test_the_page_never_shows_the_primary_count_as_if_it_were_the_total(
        self,
    ) -> None:
        """The exact line that shipped."""
        page = (ROOT / "docs" / "results.md").read_text(encoding="utf-8")
        study = self._study()
        ranked_primary = study.outcome_counts.get("ranked", 0)
        ranked_every = study.outcome_counts_every_tier.get("ranked", 0)
        if ranked_primary == ranked_every:  # pragma: no cover - frames coincide
            pytest.skip("the two frames agree; the confusion cannot arise")

        # Whole lines: the corrected two-column row starts with the same text,
        # so a substring check passes on the page that shipped and fails on the
        # page that fixed it.
        lines = {line.strip() for line in page.splitlines()}
        assert f"| Reached the shortlist | {ranked_primary} |" not in lines, (
            "the outcome table shows the approved-tier count as a single "
            f"unlabelled column, above a table of {study.n_scored} pairs"
        )

    def test_the_outcome_figure_title_names_the_denominator(self, tmp_path) -> None:
        """Drawn, then read back off the rendered axes, so the title is the real
        one rather than the format string it came from."""
        import json

        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        from bindsight.benchmark import study_figures

        summary = json.loads(
            (ROOT / "benchmarks" / "study" / "results.json").read_text(encoding="utf-8")
        )
        titles: list[str] = []
        original = plt.subplots

        def _subplots(*a, **kw):
            fig, ax = original(*a, **kw)
            titles.append(ax)
            return fig, ax

        plt.subplots = _subplots
        try:
            study_figures.plot_outcome_classes(summary, tmp_path / "outcomes.png")
        finally:
            plt.subplots = original

        assert titles, "no figure was drawn"
        title = titles[0].get_title()
        for tier in summary["design"]["tiers_in_primary_denominator"]:
            assert str(tier).replace("_", " ") in title, (
                f"the figure title does not name the {tier} denominator: {title!r}"
            )


class TestAnEmptyCategoryIsDrawnAsZeroNotAsAbsent:
    """`if value:` suppressed the annotation on a bar of height zero.

    A category with no pairs was then drawn as a bar of no height carrying no
    number — visually identical to a category that was not plotted at all. "None
    of these" is a finding; "not shown" is not, and the reader could not tell
    which they were looking at.

    The figure is committed (`docs/assets/figures/outcome_classes.png`) and
    embedded in `docs/results.md`, so this is what a reader sees.
    """

    def test_every_bar_carries_its_count_including_zero(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pytest.importorskip("matplotlib")

        import matplotlib

        matplotlib.use("Agg")
        from matplotlib.axes import Axes

        from bindsight.benchmark import study_figures as F

        annotated: list[str] = []
        real_text = Axes.text

        def _record(self, x, y, sss, *a, **kw):
            annotated.append(str(sss))
            return real_text(self, x, y, sss, *a, **kw)

        monkeypatch.setattr(Axes, "text", _record)

        summary = {
            "outcome_class_counts": {"ranked": 3, "gated_out": 14, "not_reachable": 0},
            "design": {"tiers_in_primary_denominator": ["approved"]},
        }
        if F.plot_outcome_classes(summary, tmp_path / "figs") is None:
            pytest.skip("this artifact shape produces no outcome-class figure")

        assert "0" in annotated, (
            f"a category with zero pairs was drawn without its count; the bars annotated "
            f"were {annotated}. A bar of no height and no number cannot be told apart "
            "from one that was not plotted at all"
        )
        assert "3" in annotated, "a non-zero bar stopped being annotated"
        assert "14" in annotated, "a non-zero bar stopped being annotated"

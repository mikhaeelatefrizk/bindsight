# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Every published number must appear in the artifact it claims to come from.

The project's whole argument is that its claims are checkable. That only holds
if the prose and the artifact agree, and the failure this file exists to prevent
is not hypothetical: the previous headline said ERBB2 rank 4 and recall@5 of 33%
across the README, the docs site, the JOSS paper, the bioRxiv draft, the
validation manuscript and the social preview image. Correcting one surface at a
time is how a repository ends up asserting two different results at once.

So the rediscovery study's numbers are read out of ``benchmarks/study/results.json``
and every document that states them is checked against it. A re-run that moves a
figure fails here until the prose is updated, which is the point.

These are string checks against the rendered documents on purpose. A reader
meets the number as text, so text is what has to be right.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
STUDY = REPO / "benchmarks" / "study" / "results.json"


@pytest.fixture(scope="module")
def summary() -> dict:
    if not STUDY.is_file():
        pytest.skip("study artifact not present")
    return json.loads(STUDY.read_text(encoding="utf-8"))


def _doc(rel: str) -> str:
    p = REPO / rel
    if not p.is_file():
        pytest.skip(f"{rel} not present")
    return p.read_text(encoding="utf-8")


class TestTheStudyArtifactIsSelfConsistent:
    """Before checking the prose, check the artifact does not contradict itself."""

    def test_the_primary_cascade_counts_fewer_pairs_than_the_sensitivity(
        self, summary: dict
    ) -> None:
        """The cascade is tier-restricted; the sensitivity analysis is not.

        Its row was labelled `all` while counting 17 of 22 pairs, and the printed
        question said "every scored pair". The label now names the tier.
        """
        primary = summary["recall_cascade"]["all"]["wilson"]["denominator"]
        every_tier = summary["tier_sensitivity"]["headline"]["denominator"]
        assert primary <= every_tier
        assert summary["design"]["tiers_in_primary_denominator"]

    def test_the_cascade_is_nested(self, summary: dict) -> None:
        """Each step may only remove pairs, never add them."""
        d = [
            summary["recall_cascade"][k]["wilson"]["denominator"]
            for k in ("all", "reachable", "gate_passed")
        ]
        assert d == sorted(d, reverse=True), d

    def test_no_pair_failed_for_infrastructure_reasons(self, summary: dict) -> None:
        """A lookup that errored is not a negative result, and invalidates the rate."""
        assert summary["infrastructure_failures"]["n"] == 0
        assert summary["outcome_class_counts"]["infrastructure"] == 0

    def test_every_ranked_pair_carries_its_shortlist_size(self, summary: dict) -> None:
        """A rank without the size of the list it sits in is not interpretable."""
        ranked = [p for p in summary["pairs"] if p.get("outcome_class") == "ranked"]
        assert ranked
        for p in ranked:
            assert p.get("shortlist_size"), p.get("symbol")
            assert p["rank"] <= p["shortlist_size"]


class TestTheValidationManuscriptMatchesTheArtifact:
    def test_the_headline_recall_appears_as_written(self, summary: dict) -> None:
        w = summary["recall_cascade"]["all"]["at_k"]["recall@20"]["wilson"]
        text = _doc("paper/validation/manuscript.md")
        assert f"{w['numerator']} of {w['denominator']}" in text
        # The interval is quoted to two decimals in prose.
        assert f"{w['low']:.2f}–{w['high']:.2f}" in text

    def test_the_independent_antigen_interval_appears(self, summary: dict) -> None:
        w = summary["primary_interval"]["wilson"]
        text = _doc("paper/validation/manuscript.md")
        assert f"{w['numerator']}/{w['denominator']}" in text

    def test_the_tier_sensitivity_figure_appears(self, summary: dict) -> None:
        w = summary["tier_sensitivity"]["headline"]
        text = _doc("paper/validation/manuscript.md")
        assert f"{w['numerator']}/{w['denominator']}" in text

    def test_every_surfaced_antigen_is_reported_with_its_shortlist(self, summary: dict) -> None:
        """`rank 1` alone is the claim the old headline made. `1 of 291` is checkable."""
        text = _doc("paper/validation/manuscript.md")
        for p in summary["pairs"]:
            if p.get("outcome_class") != "ranked":
                continue
            rank, size = p["rank"], p["shortlist_size"]
            assert f"{rank} of {size}" in text or f"{rank} / {size}" in text, (
                f"{p['symbol']}: manuscript does not state rank {rank} of {size}"
            )


class TestTheWithdrawnHeadlineStaysWithdrawn:
    """ERBB2 at rank 4 and recall@5 of 33% are retracted everywhere.

    They were asserted on six surfaces at once. Any of them re-acquiring the
    figure means the repository is again publishing two results.
    """

    SURFACES = (
        "README.md",
        "docs/index.md",
        "docs/results.md",
        "paper/paper.md",
        "paper/validation/manuscript.md",
        "ARCHITECTURE.md",
    )

    @pytest.mark.parametrize("rel", SURFACES)
    def test_no_surface_asserts_the_old_recall(self, rel: str) -> None:
        text = _doc(rel)
        # Permitted only where the document is explicitly retracting it.
        # `recall@5` must not match `recall@50`, and `33` must not match `0.033`.
        pattern = re.compile(r"recall@5(?!\d)")
        thirty_three = re.compile(r"(?<![.\d])33\s*%")
        for line in text.splitlines():
            if not pattern.search(line) or not thirty_three.search(line):
                continue
            low = line.lower()
            assert any(
                w in low
                for w in ("withdraw", "retract", "supersed", "previous", "old", "no longer")
            ), f"{rel}: states recall@5 33% without retracting it:\n{line}"

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


BENCH = REPO / "benchmarks" / "designer_benchmark" / "results.json"


@pytest.fixture(scope="module")
def bench() -> dict:
    if not BENCH.is_file():
        pytest.skip("designer benchmark artifact not present")
    return json.loads(BENCH.read_text(encoding="utf-8"))


class TestTheDesignerBenchmarkMatchesTheArtifact:
    """The binder figures quoted in prose must come from the committed run.

    This one is load-bearing right now. The committed run used a ProteinMPNN
    protocol that has since been corrected, and a re-run under the fixed
    protocol will move every number here. When it lands, these tests fail until
    the prose is updated — which is the only reliable way to keep a superseded
    ipTM from surviving in one document after being replaced in five others.
    """

    #: Surfaces that quote the binder numbers.
    SURFACES = ("README.md", "docs/index.md", "docs/results.md")

    @staticmethod
    def _arm(bench: dict) -> dict:
        arms = [d for d in bench["designers"] if d.get("n_designs")]
        assert arms, "benchmark records no designer arm with any designs"
        return arms[0]

    def test_the_run_is_not_a_mock(self, bench: dict) -> None:
        """A mock arm published as a result is the failure the backend cache key guards."""
        assert bench["is_mock"] is False
        assert bench["backend"] != "mock"

    def test_the_design_count_is_stated_as_written(self, bench: dict) -> None:
        n = self._arm(bench)["n_designs"]
        for rel in self.SURFACES:
            assert str(n) in _doc(rel), f"{rel} does not state {n} designs"

    def test_the_best_iptm_matches(self, bench: dict) -> None:
        """Prose quotes the best ipTM to two decimals; it must be the artifact's."""
        metrics = REPO / "benchmarks" / "designer_benchmark" / "binders" / "metrics.jsonl"
        if not metrics.is_file():
            pytest.skip("per-design metrics not present")
        best = max(
            json.loads(ln)["iptm"]
            for ln in metrics.read_text(encoding="utf-8").splitlines()
            if ln.strip() and json.loads(ln).get("iptm") is not None
        )
        for rel in self.SURFACES:
            assert f"{best:.2f}" in _doc(rel), f"{rel} does not state best ipTM {best:.2f}"

    def test_the_success_rate_matches(self, bench: dict) -> None:
        rate = self._arm(bench)["success_rate"]
        pct = f"{rate * 100:g}"
        for rel in self.SURFACES:
            assert pct in _doc(rel), f"{rel} does not state success rate {pct}%"

    def test_the_gpu_is_named_consistently(self, bench: dict) -> None:
        """The card a result was produced on is part of the result."""
        gpu = bench["gpu"]
        assert gpu
        assert "mock" not in gpu.lower()
        # "Tesla T4-16GB (Kaggle free)" -> the docs say "T4"; "Tesla P100-..." -> "P100".
        model = gpu.split()[1].split("-")[0]
        text = _doc("docs/results.md")
        assert model in text, f"docs/results.md does not name the {model} the run used"

    def test_no_surface_still_promises_the_correction_in_the_future_tense(
        self, bench: dict
    ) -> None:
        """Once the corrected run is the committed artifact, a promise is stale.

        The retraction check elsewhere matches keywords, and "supersed" is
        satisfied by a promise as readily as by a retraction. So the README
        carried "these figures ... will be superseded by a corrected re-run"
        long after the corrected re-run had landed and been committed: a
        sentence that passes a grep and misleads a reader, sitting a few
        hundred lines below the corrected figures it contradicted.

        Tense is the whole difference between disclosing a correction and
        deferring one. This deactivates itself while the artifact is still the
        pre-fix run, when the promise would be true.
        """
        if bench.get("bindsight_version", "") in {"0.2.0"}:
            pytest.skip("the corrected run is not the committed artifact yet")
        promise = re.compile(
            r"will be (?:superseded|replaced|withdrawn|corrected)"
            r"|(?:pending|awaiting) (?:a|the) (?:corrected )?re-?run",
            re.IGNORECASE,
        )
        surfaces = (
            *self.SURFACES,
            "ARCHITECTURE.md",
            "paper/paper.md",
            "paper/validation/manuscript.md",
            "benchmarks/designer_benchmark/RESULTS.md",
            "benchmarks/designer_benchmark/DESIGNER_BENCHMARK.md",
        )
        for rel in surfaces:
            doc = REPO / rel
            if not doc.is_file():
                continue
            found = promise.search(doc.read_text(encoding="utf-8"))
            assert found is None, (
                f"{rel} still defers the correction to the future ({found.group(0)!r}), "
                "but the committed artifact is already the corrected run"
            )

    def test_a_superseded_protocol_is_disclosed_wherever_its_numbers_appear(
        self, bench: dict
    ) -> None:
        """Until the corrected re-run lands, every quoting surface must say so.

        Delete this test in the same commit that replaces the artifact — and
        only then, because the caveat and the numbers have to move together.
        """
        if bench.get("bindsight_version", "") not in {"0.2.0"}:
            pytest.skip("artifact is from the corrected protocol; caveat no longer required")
        for rel in self.SURFACES:
            low = _doc(rel).lower()
            assert "pdb_path_chains" in low or "provisional" in low, (
                f"{rel} quotes the pre-fix binder numbers without disclosing the protocol"
            )

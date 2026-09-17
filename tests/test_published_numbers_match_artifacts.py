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
import math
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

    #: Discovered, not listed. This was a six-path tuple and the module docstring
    #: above names the bioRxiv draft as one of the six surfaces that carried the
    #: withdrawn headline — and that draft was not in the tuple, so the one
    #: manuscript most likely to be read by a reviewer was checked by nothing.
    SURFACES = tuple(
        sorted(
            p.relative_to(REPO).as_posix()
            for p in [
                *REPO.glob("*.md"),
                *(REPO / "docs").rglob("*.md"),
                *(REPO / "paper").rglob("*.md"),
                *(REPO / "paper").rglob("*.tex"),
            ]
            if p.is_file() and "CHANGELOG" not in p.name
        )
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


def _shipped_surfaces() -> tuple[str, ...]:
    """Every shipped prose document, discovered.

    Two classes below carried hand-written tuples of three and five names. That
    is the defect class this repository keeps finding: the list cannot express
    "wherever this figure is quoted", which is the property that matters, and it
    silently stops covering a document the moment one is added or a claim moves.

    ``CHANGELOG.md`` is excluded: it records what figures *were*, by design.
    """
    root = REPO
    paths = [
        *root.glob("*.md"),
        *(root / "docs").rglob("*.md"),
        *(root / "paper").rglob("*.md"),
        *(root / "paper").rglob("*.tex"),
        *(root / "benchmarks").rglob("*.md"),
    ]
    tracked = _tracked()
    return tuple(
        sorted(
            rel
            for rel in (p.relative_to(root).as_posix() for p in paths if p.is_file())
            if "CHANGELOG" not in rel and (tracked is None or rel in tracked)
        )
    )


def _tracked() -> frozenset[str] | None:
    """Paths git carries, so a local build product is never treated as shipped."""
    import subprocess

    try:
        out = subprocess.run(
            ["git", "-C", str(REPO), "ls-files", "-z"],
            capture_output=True,
            check=True,
            timeout=60,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    return frozenset(part.decode("utf-8") for part in out.split(b"\0") if part)


class TestTheDesignerBenchmarkMatchesTheArtifact:
    """The binder figures quoted in prose must come from the committed run.

    This one is load-bearing right now. The committed run used a ProteinMPNN
    protocol that has since been corrected, and a re-run under the fixed
    protocol will move every number here. When it lands, these tests fail until
    the prose is updated — which is the only reliable way to keep a superseded
    ipTM from surviving in one document after being replaced in five others.
    """

    #: Surfaces that quote the binder numbers.
    SURFACES = _shipped_surfaces()

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
        """Wherever the run is described, its size must be the artifact's."""
        n = self._arm(bench)["n_designs"]
        stating = [rel for rel in self.SURFACES if "designer benchmark" in _doc(rel).lower()]

        assert stating, "no shipped document describes the designer benchmark"
        for rel in stating:
            assert str(n) in _doc(rel), f"{rel} describes the run without stating {n} designs"

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
        # Wherever a best ipTM is quoted it must be the artifact's. Requiring
        # every surface to quote one forced the figure onto the README, which
        # deliberately no longer reports design performance: the rate that
        # framed it is withdrawn, and a front page stating it is advertising a
        # retracted result however carefully it is caveated.
        pattern = re.compile(r"best\s+(?:ipTM|iPTM)\s*\*{0,2}\s*(\d\.\d{2})")
        seen = 0
        for rel in self.SURFACES:
            lines = _doc(rel).splitlines()
            for i, line in enumerate(lines):
                # Read the window a reader reads, not the line a regex matched.
                # ARCHITECTURE.md wraps "A superseded run on / a P100 reported
                # best ipTM 0.84" across two lines, putting the framing above
                # the figure, and a line-scoped check called that a live claim.
                window = " ".join(lines[max(0, i - 2) : i + 2]).lower()
                if any(w in window for w in ("superseded", "withdraw", "earlier run", "predates")):
                    continue  # the retracted 0.84 is allowed to say 0.84
                for match in pattern.finditer(line):
                    seen += 1
                    assert match.group(1) == f"{best:.2f}", (
                        f"{rel} states best ipTM {match.group(1)}; the artifact says {best:.2f}"
                    )
        assert seen, "no shipped document quotes the run's best ipTM"

    def test_the_success_rate_matches(self, bench: dict) -> None:
        """Wherever a success@0.65 rate is quoted, it must be the artifact's.

        Requiring every surface to state it made the rate mandatory on pages
        that deliberately do not report design performance at all -- and once
        the surface list became a discovery, that included CODE_OF_CONDUCT.md.
        The property is "no surface states a different rate", not "every surface
        states this one".
        """
        rate = self._arm(bench)["success_rate"]
        pct = f"{rate * 100:g}"
        pattern = re.compile(
            r"(\d{1,3})\s?%\s*success@0\.65"
            r"|success@0\.65[^\n]{0,20}?(\d{1,3})\s?%"
        )
        seen = 0
        for rel in self.SURFACES:
            for line in _doc(rel).splitlines():
                low = line.lower()
                if "superseded" in low or "withdraw" in low or "earlier" in low:
                    continue  # the retracted 50% is allowed to say 50%
                for match in pattern.finditer(line):
                    stated = match.group(1) or match.group(2)
                    seen += 1
                    assert stated == pct, (
                        f"{rel} states success@0.65 of {stated}%; the artifact says {pct}%"
                    )
        assert seen, "no shipped document quotes the run's success rate"

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

    def test_the_superseded_protocol_is_gone_rather_than_disclosed(self, bench: dict) -> None:
        """The caveat was conditional on the artifact still being the bad one.

        It read "until the corrected re-run lands, every quoting surface must say
        so", and skipped whenever the artifact was not 0.2.0. The corrected run
        landed: the committed artifact is 0.2.2. So the test has been skipping
        ever since — present in the file, absent from every run, and its own
        docstring said to delete it at exactly that moment.

        Asserting the condition is better than deleting it. A regression that put
        the superseded artifact back would silently restore the need for a caveat
        nothing now carries, and this is the line that would notice.
        """
        version = str(bench.get("bindsight_version", ""))

        assert version, "the committed artifact records no bindsight version"
        assert version != "0.2.0", (
            "the committed designer-benchmark artifact is back to the superseded "
            "0.2.0 protocol, whose binder numbers were produced before the "
            "pdb_path_chains fix. Either restore the corrected artifact or "
            "re-instate the disclosure on every surface that quotes it"
        )


class TestTheSuccessRateNeverAppearsBare:
    """A percentage from twenty designs must carry the interval around it.

    Two runs of the same target, differing only in the random seed, returned
    2/20 and 6/20 — 10% and 30% — which a Fisher exact test cannot separate
    (p = 0.24). The point estimate alone invites a comparison the sample cannot
    support, and the panel half of this project already holds itself to the
    rule that the interval is the finding.

    A retracted figure is exempt: the interval around a withdrawn number is not
    information anyone should be acting on.
    """

    #: "40% success@0.65", "50 % success@0.65", and so on.
    RATE = re.compile(r"(\d{1,3})\s?%\s*success@0\.65")
    #: Any of the ways an interval is written in these documents.
    INTERVAL = re.compile(r"CI|\u2013\s?\d{1,3}\s?%|\d{1,3}\s?%\u2013|\(\d{1,3}%\u2013")
    RETRACTED = ("withdraw", "supersed", "retract", "earlier run", "no longer")

    SURFACES = (
        "README.md",
        "ARCHITECTURE.md",
        "docs/positioning.md",
        "docs/index.md",
        "docs/results.md",
        "benchmarks/designer_benchmark/DESIGNER_BENCHMARK.md",
        "benchmarks/designer_benchmark/RESULTS.md",
    )

    @pytest.mark.parametrize("rel", SURFACES)
    def test_no_bare_success_percentage(self, rel: str) -> None:
        path = REPO / rel
        if not path.is_file():
            pytest.skip(f"{rel} not present")
        text = path.read_text(encoding="utf-8")
        for match in self.RATE.finditer(text):
            window = text[max(0, match.start() - 300) : match.end() + 300]
            low = window.lower()
            if any(word in low for word in self.RETRACTED):
                continue  # a withdrawn figure needs no interval
            assert self.INTERVAL.search(window), (
                f"{rel} states {match.group(0)!r} with no interval near it; "
                "twenty designs do not support a bare percentage"
            )

    def test_the_artifact_carries_the_interval_too(self, bench: dict) -> None:
        """Prose can only quote an interval the artifact actually records."""
        arm = self._arm(bench)
        assert arm.get("n_success") is not None, "results.json records no numerator"
        assert arm.get("success_ci_low") is not None
        assert arm.get("success_ci_high") is not None
        assert arm["success_ci_low"] < arm["success_rate"] < arm["success_ci_high"], (
            "the recorded interval does not contain its own point estimate"
        )

    @staticmethod
    def _arm(bench: dict) -> dict:
        arms = [d for d in bench["designers"] if d.get("n_designs")]
        assert arms
        return arms[0]


class TestTheDerivedFiguresMatchTheArtifact:
    """The headline four were pinned; everything derived from them was not.

    mean ipTM, mean PAE-interaction and the interval bounds are quoted across
    five surfaces as bare literals. A re-run that moves them leaves half of each
    sentence stale, which is worse than a wholly stale sentence because the
    correct half lends the wrong half its authority.
    """

    SURFACES = _shipped_surfaces()

    @staticmethod
    def _arm(bench: dict) -> dict:
        return next(d for d in bench["designers"] if d.get("n_designs"))

    def test_every_quoted_mean_iptm_is_the_artifact_value(self, bench: dict) -> None:
        """`mean 0.51` and `mean **ipTM 0.51**` must both track results.json."""
        expected = f"{self._arm(bench)['mean_iptm']:.2f}"
        pattern = re.compile(r"mean\s+(?:\*\*)?(?:ipTM\s+)?(?:\*\*)?(\d\.\d{2})")
        seen = 0
        for rel in self.SURFACES:
            path = REPO / rel
            if not path.is_file():
                continue
            for line in path.read_text(encoding="utf-8").splitlines():
                low = line.lower()
                if "superseded" in low or "withdraw" in low or "earlier" in low:
                    continue  # the retracted 0.59 is allowed to say 0.59
                for match in pattern.finditer(line):
                    seen += 1
                    assert match.group(1) == expected, (
                        f"{rel} states mean {match.group(1)}; the artifact says {expected}"
                    )
        assert seen, "no surface quotes a mean ipTM; this guard is checking nothing"

    def test_every_quoted_pae_is_the_artifact_value(self, bench: dict) -> None:
        expected = f"{self._arm(bench)['mean_pae_interaction']:.1f}"
        pattern = re.compile(r"mean PAE[- ]interaction\s+(\d+\.\d)")
        seen = 0
        for rel in self.SURFACES:
            path = REPO / rel
            if not path.is_file():
                continue
            for match in pattern.finditer(path.read_text(encoding="utf-8")):
                seen += 1
                assert match.group(1) == expected, (
                    f"{rel} states mean PAE-interaction {match.group(1)}; "
                    f"the artifact says {expected}"
                )
        if not seen:
            pytest.skip(
                "no shipped document quotes a mean PAE-interaction in prose; the "
                "designer benchmark reports it in a table column, which "
                "test_the_designer_table_matches_the_artifact covers"
            )

    def test_every_quoted_interval_is_the_artifact_interval(self, bench: dict) -> None:
        """The bounds were unpinned while the rate they qualify was pinned."""
        arm = self._arm(bench)
        expected = f"{arm['success_ci_low'] * 100:.0f}\u2013{arm['success_ci_high'] * 100:.0f}%"
        pattern = re.compile(r"95% CI (\d{1,3}\u2013\d{1,3}%)")
        seen = 0
        for rel in self.SURFACES:
            path = REPO / rel
            if not path.is_file():
                continue
            for match in pattern.finditer(path.read_text(encoding="utf-8")):
                if match.group(1).startswith("0"):
                    continue  # study intervals like "0.01-0.27" are a different figure
                seen += 1
                assert match.group(1) == expected, (
                    f"{rel} states 95% CI {match.group(1)}; the artifact says {expected}"
                )
        assert seen, "no surface quotes the designer interval"

    def test_the_interval_is_clustered_not_binomial(self, bench: dict) -> None:
        """A guard against silently reverting to the narrower estimator."""
        arm = self._arm(bench)
        assert arm["success_ci_method"].startswith("cluster-bootstrap")
        assert arm["success_ci_low"] < arm["success_ci_independent_low"]
        assert arm["success_ci_high"] > arm["success_ci_independent_high"]


def _legitimate_study_fractions(summary: dict) -> set[tuple[int, int]]:
    """Every (numerator, denominator) the study artifact actually supports.

    Recall at every cutoff and tier, the de-duplicated antigen interval, the
    tier sensitivity headline, and each ranked pair's rank within its shortlist.
    A fraction outside this set, stated in a study context, is a figure the
    artifact does not contain.
    """
    legit: set[tuple[int, int]] = set()
    for block in summary.get("recall_cascade", {}).values():
        for entry in (block.get("at_k") or {}).values():
            w = entry["wilson"]
            legit.add((w["numerator"], w["denominator"]))
    for key in ("primary_interval", "tier_sensitivity"):
        node = summary.get(key) or {}
        w = node.get("wilson") or node.get("headline")
        if w:
            legit.add((w["numerator"], w["denominator"]))
        # The tier sensitivity carries its own per-cutoff block, which the
        # documents quote alongside the headline.
        for entry in (node.get("at_k") or {}).values():
            legit.add((entry["numerator"], entry["denominator"]))
    for pair in summary.get("pairs", []):
        if pair.get("outcome_class") == "ranked" and pair.get("shortlist_size"):
            legit.add((pair["rank"], pair["shortlist_size"]))
        # The counterfactual rank — where the antigen sits among the eligible
        # surfaceome with every gate removed — is published beside the shortlist
        # rank, and separates "a gate killed it" from "the ranker buried it".
        if pair.get("counterfactual_rank") and pair.get("n_eligible"):
            legit.add((pair["counterfactual_rank"], pair["n_eligible"]))

    # Counts the null-model section derives from those same pairs: how many
    # used their whole stratum, how many are nominally significant, and how
    # many survive the panel correction. Each is a fraction of the scored pairs
    # and is recomputed here rather than trusted from the prose.
    scored = [p for p in summary.get("pairs", []) if p.get("p_decoy") is not None]
    if scored:
        total = len(scored)
        legit.add((sum(1 for p in scored if p.get("decoy_exact")), total))
        legit.add((sum(1 for p in scored if float(p["p_decoy"]) < 0.05), total))
        legit.add(
            (
                sum(
                    1
                    for p in scored
                    if isinstance(p.get("p_decoy_bh"), float) and p["p_decoy_bh"] < 0.05
                ),
                total,
            )
        )
    spec = summary.get("specificity_null") or {}
    if spec.get("n_antigens"):
        legit.add((spec["n_antigens"], spec["n_cohorts"]))
    return legit


class TestEverySurfaceStatesOnlyTheArtifactsStudyFigures:
    """The study numbers were pinned in one document and restated in five others.

    `TestTheValidationManuscriptMatchesTheArtifact` checks
    paper/validation/manuscript.md and nothing else, while README.md,
    ARCHITECTURE.md, paper/paper.md, docs/index.md and docs/what-is-bindsight.md
    all restate the same figures unchecked — the six-surface drift that class's
    own docstring says it exists to prevent.

    Requiring every surface to state every figure would be wrong: a README does
    not enumerate ranked pairs. The checkable property is the other direction —
    a surface may say less than the artifact, but nothing it does say may be a
    figure the artifact lacks.
    """

    SURFACES = (
        "README.md",
        "ARCHITECTURE.md",
        "paper/paper.md",
        "paper/validation/manuscript.md",
        "docs/index.md",
        "docs/what-is-bindsight.md",
        "benchmarks/study/RESULTS.md",
    )

    #: A fraction only counts as a study claim if the sentence is about one.
    _CONTEXT = re.compile(r"recall|antigen|approved|tier|shortlist|surfac|rank", re.I)
    #: A trial phase ("phase 2/3") is not a recall figure, and the drug-name
    #: column shares a row with the ranks.
    #: ``\d{1,4}`` stopped at the comma in "7 of 2,170" and read it as "7 of 2",
    #: so every eligible-surfaceome figure in the manuscript was being compared
    #: against the wrong denominator -- and matched nothing, silently, until a
    #: table row happened to fall inside the context filter.
    _FRACTION = re.compile(
        r"(?<!phase )\b(\d{1,3}(?:,\d{3})*)\s*(?:of|/)\s*(\d{1,3}(?:,\d{3})*|\d{1,4})\b",
        re.I,
    )
    _RETRACTED = ("withdraw", "supersed", "retract", "earlier", "no longer", "replaces")

    @pytest.mark.parametrize("rel", SURFACES)
    def test_no_surface_states_a_study_fraction_the_artifact_lacks(
        self, summary: dict, rel: str
    ) -> None:
        path = REPO / rel
        if not path.is_file():
            pytest.skip(f"{rel} not present")
        legit = _legitimate_study_fractions(summary)
        checked = 0
        for line in path.read_text(encoding="utf-8").splitlines():
            if not self._CONTEXT.search(line):
                continue
            for match in self._FRACTION.finditer(line):
                # Scoped to the fraction, not the line. A sentence that retracts
                # one figure while stating current ones is common, and skipping
                # the whole line on a word as ordinary as "earlier" left
                # ARCHITECTURE.md's live recall figures unchecked.
                near = line[max(0, match.start() - 90) : match.end() + 90].lower()
                if any(word in near for word in self._RETRACTED):
                    continue  # a retraction may quote the figure it retracts
                found = (
                    int(match.group(1).replace(",", "")),
                    int(match.group(2).replace(",", "")),
                )
                if found[1] < 2:  # "1 of 1" style prose, not a study figure
                    continue
                checked += 1
                assert found in legit, (
                    f"{rel} states {found[0]} of {found[1]} in a study context; "
                    f"benchmarks/study/results.json contains no such figure"
                )
        # Only docs/index.md legitimately states no study fraction. Exempting a
        # file that does state them would let it quietly stop, which is how a
        # scan-based guard decays into checking nothing.
        assert checked or rel == "docs/index.md", (
            f"{rel} states no study fraction; this guard is checking nothing there"
        )

    def test_the_guard_covers_more_than_the_manuscript(self) -> None:
        """The drift this replaces was exactly 'only one document was checked'."""
        assert len(self.SURFACES) >= 6
        assert "paper/validation/manuscript.md" in self.SURFACES
        assert "README.md" in self.SURFACES


# ---------------------------------------------------------------------------
# The approved-tier disposition counts, recomputed rather than quoted
# ---------------------------------------------------------------------------
#: Documents stating how many approved-tier pairs fail the significance rule.
#:
#: Six of them said "thirteen of the seventeen". Thirteen is the count across
#: all twenty-two pairs; across the seventeen approved-tier pairs it is eleven,
#: with a twelfth measured as down-regulated. The wrong figure survived in a
#: deposit-ready manuscript, a preprint, the architecture document and the
#: public landing page at once, because each copy was written from another copy
#: rather than from the artifact.
_APPROVED_TIER_DOCUMENTS: tuple[str, ...] = (
    "ARCHITECTURE.md",
    "docs/index.md",
    "paper/paper.md",
    "paper/biorxiv/manuscript.tex",
    "paper/validation/manuscript.md",
)


def _approved_tier_counts() -> dict[str, int]:
    """Disposition counts over the approved tier, straight from results.json."""
    import collections
    import json

    root = Path(__file__).resolve().parents[1]
    data = json.loads((root / "benchmarks" / "study" / "results.json").read_text(encoding="utf-8"))
    approved = [p for p in data["pairs"] if p.get("tier") == "approved"]
    counts = collections.Counter(p.get("disposition") for p in approved)
    return {"n": len(approved), **counts}


def test_the_approved_tier_split_is_what_the_artifact_says() -> None:
    """The anchor. If the study is re-run, these move and the prose must follow."""
    counts = _approved_tier_counts()
    assert counts["n"] == 17
    assert counts["not_significant"] == 11
    assert counts["down_regulated"] == 1


def test_no_document_claims_thirteen_approved_tier_failures() -> None:
    """Thirteen is the all-tier count; attributing it to the seventeen is wrong."""
    root = Path(__file__).resolve().parents[1]
    for rel in _APPROVED_TIER_DOCUMENTS:
        text = " ".join((root / rel).read_text(encoding="utf-8").split())
        for wrong in (
            "Thirteen of the seventeen",
            "Thirteen of seventeen",
            "13 of the 17",
            "13 of 17",
        ):
            assert wrong not in text, f"{rel} still claims {wrong!r}"


def test_every_document_states_a_number_the_artifact_supports() -> None:
    """Eleven fail the rule; twelve are not over-expressed. Nothing else is right."""
    counts = _approved_tier_counts()
    fails_rule = counts["not_significant"]
    not_over = counts["not_significant"] + counts["down_regulated"]

    words = {11: ("Eleven", "eleven"), 12: ("Twelve", "twelve")}
    root = Path(__file__).resolve().parents[1]
    for rel in _APPROVED_TIER_DOCUMENTS:
        text = " ".join((root / rel).read_text(encoding="utf-8").split())
        if "approved-tier" not in text and "seventeen" not in text:
            continue
        assert any(w in text for w in words[fails_rule] + words[not_over]), (
            f"{rel} discusses the approved tier but states neither {fails_rule} nor {not_over}"
        )


# ---------------------------------------------------------------------------
# The gated-out breakdown, and the denominator it is stated against
# ---------------------------------------------------------------------------
#: Each gate a pair can fail, and the phrase the artifact's ``reason`` uses.
#: Derived from the reason text rather than a separate field so the buckets
#: cannot drift from what the pairs actually say.
_GATES = {
    "significance": "significance rule",
    "enrichment": "enrichment cut",
    "down_regulated": "down-regulated",
}


def _gated_out_breakdown(pairs: list[dict]) -> dict[str, int]:
    """How many gated-out pairs failed at each gate."""
    counts = dict.fromkeys(_GATES, 0)
    for pair in pairs:
        if pair.get("outcome_class") != "gated_out":
            continue
        reason = str(pair.get("reason", ""))
        matched = [name for name, phrase in _GATES.items() if phrase in reason]
        assert len(matched) == 1, f"{pair.get('symbol')}: {len(matched)} gates match {reason!r}"
        counts[matched[0]] += 1
    return counts


class TestTheGatedOutBreakdownAddsUp:
    """Section 3.3 stated a total of 15 -- the pre-registered approved-tier
    denominator -- with a breakdown of 13 + 3 + 1 taken from the all-tier frame.
    The numbers were each correct about a different set of pairs, so the sentence
    was wrong about both. These tests tie every stated figure to one frame.
    """

    def test_the_breakdown_sums_to_the_number_of_gated_out_pairs(self, summary: dict) -> None:
        """The artifact first: a breakdown that does not sum is a bug in the study,
        not in the prose quoting it."""
        for label, pairs in (
            ("all tiers", summary["pairs"]),
            (
                "approved tier",
                [
                    p
                    for p in summary["pairs"]
                    if p.get("tier") in summary["design"]["tiers_in_primary_denominator"]
                ],
            ),
        ):
            gated = [p for p in pairs if p.get("outcome_class") == "gated_out"]
            breakdown = _gated_out_breakdown(pairs)
            assert sum(breakdown.values()) == len(gated), (
                f"{label}: breakdown {breakdown} does not sum to {len(gated)} gated-out pairs"
            )

    def test_the_recorded_class_counts_are_the_primary_denominator(self, summary: dict) -> None:
        """``outcome_class_counts`` counts the pre-registered tiers, not every
        pair. It reads like a total, and section 3.3 used it as one."""
        tiers = summary["design"]["tiers_in_primary_denominator"]
        in_tiers = [p for p in summary["pairs"] if p.get("tier") in tiers]
        recorded = summary["outcome_class_counts"]
        for outcome in ("gated_out", "ranked"):
            assert recorded[outcome] == sum(
                1 for p in in_tiers if p.get("outcome_class") == outcome
            ), f"{outcome}: {recorded[outcome]} recorded, {len(in_tiers)} pairs in tier"
        assert sum(recorded.values()) < len(summary["pairs"]), (
            "the recorded counts now cover every pair; section 3.3's framing "
            "sentence needs revisiting"
        )

    def test_the_manuscript_states_the_approved_tier_breakdown(self, summary: dict) -> None:
        """The stated numbers, in the frame the rest of the manuscript uses."""
        tiers = summary["design"]["tiers_in_primary_denominator"]
        in_tiers = [p for p in summary["pairs"] if p.get("tier") in tiers]
        gated = sum(1 for p in in_tiers if p.get("outcome_class") == "gated_out")
        breakdown = _gated_out_breakdown(in_tiers)

        text = " ".join(_doc("paper/validation/manuscript.md").split())
        sentence = (
            f"Of the {gated} gated-out approved-tier pairs: "
            f"{_word(breakdown['significance'])} failed the significance rule, "
            f"{breakdown['enrichment']} fell outside the enrichment cut, and "
            f"{_word(breakdown['down_regulated'])} was measured as down-regulated."
        )
        assert sentence in text, f"manuscript does not state:\n  {sentence}"

    def test_the_manuscript_states_the_all_tier_breakdown_as_the_other_frame(
        self, summary: dict
    ) -> None:
        every = _gated_out_breakdown(summary["pairs"])
        gated = sum(1 for p in summary["pairs"] if p.get("outcome_class") == "gated_out")
        text = " ".join(_doc("paper/validation/manuscript.md").split())
        assert (
            f"Across all three tiers the {gated} gated-out pairs break down as "
            f"{every['significance']}, {every['enrichment']} and {every['down_regulated']}."
        ) in text, f"the all-tier frame is not stated as {gated}: {every}"

    def test_every_ranked_antigen_in_the_table_carries_its_tier(self, summary: dict) -> None:
        """The table spans three tiers while the text around it counts one. A
        reader who assumes the table is the denominator reads 5 of 17."""
        text = _doc("paper/validation/manuscript.md")
        ranked = [p for p in summary["pairs"] if p.get("outcome_class") == "ranked"]
        assert ranked
        for pair in ranked:
            tier = str(pair["tier"]).replace("_", " ").capitalize()
            row = [
                line
                for line in text.splitlines()
                if line.startswith("| ") and f"| {pair['symbol']} |" in line
            ]
            assert row, f"{pair['symbol']} has no row in the ranked table"
            assert tier in row[0], (
                f"{pair['symbol']}'s row does not name its tier ({tier}): {row[0]}"
            )


def _word(n: int) -> str:
    """The manuscript spells small counts; the artifact holds integers."""
    return {
        1: "one",
        2: "two",
        3: "three",
        4: "four",
        5: "five",
        6: "six",
        7: "seven",
        8: "eight",
        9: "nine",
        10: "ten",
        11: "11",
        12: "12",
        13: "13",
    }.get(n, str(n))


# ---------------------------------------------------------------------------
# Licensing claims must agree with LICENSING.md
# ---------------------------------------------------------------------------
def test_no_document_calls_one_validator_the_only_commercially_usable_one() -> None:
    """ARCHITECTURE.md called Chai-1r "the only commercially usable validator"
    eight lines after calling Boltz-2 commercial-friendly, and LICENSING.md --
    the authority -- marks Boltz-2, Chai-1r and BoltzGen all usable. A reader
    choosing a validator for commercial work was told the wrong thing.
    """
    licensing = _doc("LICENSING.md")
    usable = [
        line
        for line in licensing.splitlines()
        if line.startswith("|") and "✅" in line and ("Boltz" in line or "Chai" in line)
    ]
    assert len(usable) >= 2, (
        f"LICENSING.md no longer lists two commercially usable validators: {usable}"
    )

    for rel in ("ARCHITECTURE.md", "README.md", "LICENSING.md", "docs/index.md"):
        text = " ".join(_doc(rel).split())
        assert "only commercially usable" not in text, (
            f"{rel} claims a single commercially usable tool; LICENSING.md lists {len(usable)}"
        )


class TestTheCalibrationContrastCarriesItsUncertainty:
    """The report contrasted two mean standings -- 0.418 against 0.738 -- with no
    n and no interval. Two bare means are not a comparison, and this study's own
    argument is that a number without its uncertainty should not be quoted.
    """

    def test_both_means_carry_an_interval_and_a_cluster_count(self, summary: dict) -> None:
        calib = summary.get("null_calibration")
        if not calib:
            pytest.skip("no null calibration in the artifact")
        for key in ("off_indication_interval", "own_indication_interval"):
            block = calib.get(key)
            assert block, f"{key} missing; the contrast has no uncertainty behind it"
            assert block["low"] <= block["point"] <= block["high"], block
            assert block["n_clusters"] >= 1, block
            assert block["n_observations"] >= block["n_clusters"], block

    def test_the_contrast_is_paired_within_antigen(self, summary: dict) -> None:
        """The two groups are the same antigens measured in different cohorts, so
        the difference of the two means is not a difference of independent
        samples. The paired statistic is the one to quote."""
        calib = summary.get("null_calibration")
        if not calib:
            pytest.skip("no null calibration in the artifact")
        # Asserted, not skipped: this artifact carries the paired statistic, so
        # an artifact that stops carrying it is a regression rather than an
        # older file, and a skip here would let that regression through.
        paired = calib.get("paired_difference")
        assert paired, "the calibration contrast lost its paired statistic"
        assert paired["low"] <= paired["point"] <= paired["high"], paired
        assert "antigens" in paired["description"]

    def test_the_report_states_every_interval_the_artifact_holds(self, summary: dict) -> None:
        """Each bound, from the artifact.

        An earlier version of this test asserted only that "95% CI" appeared
        somewhere in the sentence, and passed with one of the three intervals
        deleted -- the other two kept the phrase alive. Checking the numbers is
        what makes it a check.
        """
        calib = summary.get("null_calibration")
        if not calib:
            pytest.skip("no null calibration in the artifact")
        text = " ".join(_doc("benchmarks/study/RESULTS.md").split())
        assert "**Calibration.**" in text
        head = text[text.index("**Calibration.**") :][:1200]

        for key in ("off_indication_interval", "own_indication_interval", "paired_difference"):
            block = calib.get(key)
            assert block, f"{key} missing from the artifact"
            bounds = f"95% CI {block['low']:.3f}–{block['high']:.3f}"
            assert bounds in head, (
                f"the calibration sentence does not state {key} as '{bounds}': {head[:400]}"
            )
        assert "within-antigen difference" in head, head[:400]

    def test_the_bootstrap_treats_the_antigen_as_the_unit(self) -> None:
        """An antigen measured in ten cohorts must not outweigh one measured in
        two; that is the whole reason for clustering."""
        from bindsight.benchmark.statistics import cluster_bootstrap_mean

        lopsided = cluster_bootstrap_mean({"A": [1.0] * 10, "B": [0.0]}, seed=0)
        balanced = cluster_bootstrap_mean({"A": [1.0], "B": [0.0]}, seed=0)

        assert lopsided.point == balanced.point == 0.5
        assert lopsided.n_observations == 11
        assert lopsided.n_clusters == balanced.n_clusters == 2

    def test_a_single_cluster_says_it_cannot_resample(self) -> None:
        from bindsight.benchmark.statistics import cluster_bootstrap_mean

        lone = cluster_bootstrap_mean({"A": [0.5, 0.7]}, seed=0)

        assert "degenerate" in lone.method
        assert lone.low == lone.high == lone.point


class TestAPointEstimateAndItsIntervalAreTheSameEstimator:
    """The calibration sentence printed the flat mean over every standing (0.738)
    with the bounds of the cluster bootstrap (computed around 0.765). Both
    numbers were correct; pairing them was not. The flat mean counts an antigen
    once per cohort and the bootstrap counts it once, so they are estimates of
    different things and their uncertainty is not interchangeable.
    """

    def test_the_artifact_marks_its_unclustered_means_as_such(self, summary: dict) -> None:
        calib = summary.get("null_calibration")
        if not calib:
            pytest.skip("no null calibration in the artifact")
        for key in ("mean_standing_off_indication", "mean_standing_in_own_indication"):
            if key not in calib:
                continue
            assert calib.get(f"{key}_is_unclustered") is True, (
                f"{key} is a flat mean and the artifact does not say so; a reader "
                "pairing it with the clustered interval repeats the original error"
            )

    def test_the_flat_and_clustered_means_really_do_differ(self, summary: dict) -> None:
        """If they ever coincided this guard would be vacuous, and the distinction
        it protects would look like pedantry rather than arithmetic."""
        calib = summary.get("null_calibration") or {}
        flat = calib.get("mean_standing_in_own_indication")
        clustered = (calib.get("own_indication_interval") or {}).get("point")
        if flat is None or clustered is None:
            pytest.skip("artifact does not carry both means")

        assert flat != clustered, (
            "the flat and clustered means coincide in this artifact, so this "
            "guard proves nothing about the current data"
        )

    def test_the_report_states_the_interval_own_point_not_the_flat_mean(
        self, summary: dict
    ) -> None:
        """Read off the rendered page, because the pairing is a rendering choice."""
        calib = summary.get("null_calibration")
        if not calib:
            pytest.skip("no null calibration in the artifact")
        text = " ".join(_doc("benchmarks/study/RESULTS.md").split())
        head = text[text.index("**Calibration.**") :][:1200]

        for interval_key, flat_key in (
            ("off_indication_interval", "mean_standing_off_indication"),
            ("own_indication_interval", "mean_standing_in_own_indication"),
        ):
            block = calib.get(interval_key)
            if not block:
                continue
            stated = f"**{block['point']:.3f}**"
            assert stated in head, (
                f"the calibration sentence does not state {interval_key}'s own point "
                f"{stated}; it must not pair an interval with another estimator"
            )
            flat = calib.get(flat_key)
            if flat is not None and f"{flat:.3f}" != f"{block['point']:.3f}":
                assert f"**{flat:.3f}**" not in head, (
                    f"the sentence states the unclustered mean {flat:.3f} beside "
                    f"{interval_key}, whose bounds are around {block['point']:.3f}"
                )


class TestStrataAreNamedForWhatTheyAre:
    """The decoy-matching strata were published as ``base_mean_decile`` and
    ``dispersion_decile`` while the binning uses five bins, so the labels 0-4 are
    quintiles. The name told a reader the matching was ten times finer than it is.
    """

    def test_no_published_field_claims_a_decile(self, summary: dict) -> None:
        offenders = sorted(
            {key for pair in summary["pairs"] for key in pair if key.endswith("_decile")}
        )

        assert not offenders, f"fields named for deciles: {offenders}"

    def test_the_code_does_not_emit_a_decile_field(self) -> None:
        """The artifact check above only sees the committed run; a rename in the
        code would not reach it until the study is re-scored, so the source is
        checked too."""
        source = (REPO / "bindsight" / "benchmark" / "study.py").read_text(encoding="utf-8")
        emitted = re.findall(r'"([a-z]+(?:_[a-z]+)*_decile)"', source)

        assert not emitted, f"study.py emits {emitted} while binning into _DECOY_STRATA_BINS strata"

    def test_the_strata_labels_fit_the_declared_bin_count(self, summary: dict) -> None:
        from bindsight.benchmark.study import _DECOY_STRATA_BINS

        seen = {
            value
            for pair in summary["pairs"]
            for key, value in pair.items()
            if key.endswith("_stratum") and isinstance(value, int)
        }
        assert seen, "no stratum labels in the artifact"
        assert max(seen) < _DECOY_STRATA_BINS, (
            f"stratum label {max(seen)} exceeds the {_DECOY_STRATA_BINS} declared bins"
        )


class TestBothNullsReachAReader:
    """The study's two null models must appear on the page readers are sent to.

    Before this, both lived only in ``benchmarks/study/RESULTS.md``: the decoy
    null -- the study's own primary null, and a negative -- and the
    indication-specificity null -- the strongest claim the study supports.
    Neither was in any README, docs page or manuscript, because
    ``StudyShowcase`` had no field for either and every generated surface was
    therefore structurally incapable of rendering them.

    A project whose credibility rests on publishing its own disconfirming
    evidence cannot publish it in one file and omit it everywhere a reader
    actually looks.
    """

    @staticmethod
    def _page() -> str:
        return (REPO / "docs" / "results.md").read_text(encoding="utf-8")

    @staticmethod
    def _study() -> dict:
        import json

        return json.loads(
            (REPO / "benchmarks" / "study" / "results.json").read_text(encoding="utf-8")
        )

    def test_the_negative_null_is_on_the_page(self) -> None:
        page = self._page()

        assert "Benjamini" in page, (
            "the results page does not mention the decoy null's correction; its "
            "headline is a negative and omitting it makes the page selective"
        )
        assert "decoy" in page.lower()

    def test_the_positive_null_is_on_the_page_with_its_interval(self) -> None:
        page = self._page()
        study = self._study()
        gap = (study.get("null_calibration") or {}).get("paired_difference") or {}

        assert "permut" in page.lower(), "the specificity null is not on the page"
        if gap.get("point") is not None:
            assert f"{gap['point']:.3f}" in page, (
                "the within-antigen difference is stated without its own value"
            )
            note = (
                "the within-antigen difference appears without its interval; at this "
                "panel size the interval is the finding"
            )
            assert f"{gap['low']:.3f}" in page, note
            assert f"{gap['high']:.3f}" in page, note

    def test_a_permutation_p_on_its_floor_says_so(self) -> None:
        """A floor reported as a measurement implies precision the design lacks."""
        page = self._page()
        spec = self._study().get("specificity_null") or {}
        p_value, floor = spec.get("p_value"), spec.get("p_value_floor")
        if p_value is None or floor is None:
            pytest.skip("no specificity null in the artifact")

        if p_value <= floor * 1.000001:
            assert "floor" in page, (
                "the published permutation p sits on the smallest value its design "
                "can express, and the page does not say so"
            )

    def test_the_page_does_not_combine_correlated_pairs(self) -> None:
        """Guards against a tempting overclaim.

        Combining the 22 decoy p-values with Fisher's method returns 0.006, which
        is a much better-looking number than "none survives correction". It is
        also wrong: ERBB2 appears in four cohorts and EGFR in four, so the pairs
        are 13 antigens rather than 22 independent tests, and Fisher over
        correlated tests is anti-conservative. The study's own machinery
        clusters over antigens for exactly this reason.
        """
        page = self._page().lower()

        assert "fisher" not in page, (
            "the results page reports a Fisher combination over pairs that repeat "
            "antigens; use a clustered estimator or report the pairs as they are"
        )


class TestThePanelNotesAgreeWithTheArtifact:
    """A panel note may state any number; nothing checked it against the data.

    `bindsight/benchmark/panel.py` says of itself that it is "data, deliberately
    separated from the code that runs the study so the panel can be read, cited
    and criticised on its own". Its notes are therefore a published surface —
    and one of them said EGFR measured **log2fc 0.42** in TCGA-LUAD. The
    artifact says 0.061. 0.414 is *ERBB2* in that same cohort: the note quoted
    the wrong gene's number, seven-fold out, and nothing noticed because no test
    compared a note to the data it describes.
    """

    @staticmethod
    def _artifact() -> dict:
        import json

        path = REPO / "benchmarks" / "study" / "results.json"
        if not path.is_file():
            pytest.skip("the study artifact ships with the repository, not the wheel")
        return json.loads(path.read_text(encoding="utf-8"))

    def test_every_log2fc_quoted_in_a_note_matches_the_artifact(self) -> None:
        import re

        from bindsight.benchmark import panel

        art = self._artifact()
        measured = {
            (p.get("project"), p.get("symbol")): p.get("log2fc")
            for p in art.get("pairs", [])
            if p.get("log2fc") is not None
        }
        assert measured, "the artifact records no log2fc values to check against"

        quoted = re.compile(r"log2fc\s+(-?\d+(?:\.\d+)?)", re.I)
        checked = 0
        wrong: list[str] = []
        for entry in panel.PANEL:
            note = getattr(entry, "note", "") or ""
            for found in quoted.finditer(note):
                # A note that explains a past correction may name the old value.
                if "quoted" in note[: found.start()].lower():
                    continue
                claimed = float(found.group(1))
                actual = measured.get((entry.project, entry.symbol))
                if actual is None:
                    continue
                checked += 1
                # The notes round; allow the rounding but not a different number.
                if abs(claimed - actual) > 0.5 * 10 ** -len(found.group(1).split(".")[-1]):
                    wrong.append(
                        f"{entry.project} {entry.symbol}: note says log2fc {claimed}, "
                        f"the artifact says {actual:.4f}"
                    )

        assert checked, "no note quotes a log2fc the artifact also records; the sweep found nothing"
        assert not wrong, "panel notes disagree with the artifact they describe:\n  " + "\n  ".join(
            wrong
        )

    def test_no_note_promises_an_analysis_the_study_does_not_run(self) -> None:
        """A note said "the unpaired secondary carries this cohort".

        `study.py` has no secondary analysis and deliberately refuses to fall
        back to an unpaired design — it raises rather than substitute a
        different contrast. A note that promises one describes a study that was
        never run.
        """
        from bindsight.benchmark import panel

        study_src = (REPO / "bindsight" / "benchmark" / "study.py").read_text(encoding="utf-8")
        runs_unpaired_secondary = "secondary" in study_src.lower()

        promising = [
            f"{e.project} {e.symbol}"
            for e in panel.PANEL
            if "unpaired secondary" in (getattr(e, "note", "") or "").lower()
            and "no unpaired secondary" not in (getattr(e, "note", "") or "").lower()
        ]

        if not runs_unpaired_secondary:
            assert not promising, (
                "these panel notes promise an unpaired secondary analysis, and "
                f"study.py runs none: {promising}"
            )


class TestTheStudyReportIsWhatItsArtifactRenders:
    """`study_report.py:21` claims the page "cannot drift from the artifacts".

    Nothing enforced it. The page is generated from `results.json`, so the two
    can only agree if someone regenerates after every change to the renderer —
    and a renderer change that nobody regenerates leaves the committed page
    stating one thing while the code that claims to produce it says another.

    This is the check the docstring was asserting. It renders the committed
    artifact and compares, so a renderer edit without a regeneration fails here
    rather than shipping a page the code no longer produces.
    """

    def test_regenerating_the_page_from_its_artifact_changes_nothing(self) -> None:
        import json

        from bindsight.benchmark.study_report import render_markdown

        artifact = REPO / "benchmarks" / "study" / "results.json"
        page = REPO / "benchmarks" / "study" / "RESULTS.md"
        if not artifact.is_file() or not page.is_file():
            pytest.skip("the study artifacts ship with the repository, not the wheel")

        rendered = render_markdown(json.loads(artifact.read_text(encoding="utf-8")))
        committed = page.read_text(encoding="utf-8")

        if rendered == committed:
            return

        import difflib

        diff = list(
            difflib.unified_diff(
                committed.splitlines(),
                rendered.splitlines(),
                fromfile="committed RESULTS.md",
                tofile="rendered from results.json",
                lineterm="",
                n=1,
            )
        )
        raise AssertionError(
            "benchmarks/study/RESULTS.md is not what results.json renders to. "
            "Re-run the generator and commit the result:\n  " + "\n  ".join(diff[:24])
        )


# ---------------------------------------------------------------------------
# The two indication-specificity analyses are not one analysis
# ---------------------------------------------------------------------------
class TestThePermutationPBelongsToItsOwnDenominator:
    """Two results, two denominators, and one of them has no p-value at all.

    `null_calibration.paired_difference` is a cluster bootstrap over the
    **13** antigens that appear in the calibration cohorts: 0.348, 95% CI
    0.188-0.513. It reports an interval and no p.

    `specificity_null` is an exact permutation test over the **7** antigens
    carrying a single indication -- 5,040 orderings is 7!, and an antigen used in
    two cancers has no one cohort to permute. It reports observed 0.858 and
    p = 3.97e-04.

    README, docs/what-is-bindsight.md and the Evidence page each stated the
    13-antigen effect size and then attached the 7-antigen test's p-value to it,
    naming neither denominator. A reader would take 3.97e-04 as the significance
    of 0.348.

    `benchmarks/study/RESULTS.md` always reported them separately and correctly,
    which is where the wording now used on the other surfaces came from.
    """

    #: Surfaces that state both results. RESULTS.md is generated and already
    #: correct; the rest are hand-written and were not.
    SURFACES = (
        "README.md",
        "docs/what-is-bindsight.md",
    )

    @staticmethod
    def _flat(text: str) -> str:
        """Tags stripped and whitespace collapsed, so a line break cannot hide a phrase."""
        return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text))

    @staticmethod
    def _study() -> dict:
        return json.loads(
            (REPO / "benchmarks" / "study" / "results.json").read_text(encoding="utf-8")
        )

    def test_the_two_analyses_really_do_have_different_denominators(self) -> None:
        """Guards the guard: if they ever coincide, the checks below prove nothing."""
        study = self._study()

        permutation_n = study["specificity_null"]["n_antigens"]
        bootstrap_n = study["null_calibration"]["paired_difference"]["n_clusters"]

        assert permutation_n != bootstrap_n, (
            f"both analyses now cover {permutation_n} antigens; this test can no "
            "longer distinguish a correct page from a fused one"
        )

    def test_the_permutation_count_is_the_factorial_of_its_own_denominator(self) -> None:
        """The arithmetic that makes the mismatch visible: 5,040 is 7!, not 13!."""
        study = self._study()
        spec = study["specificity_null"]

        assert math.factorial(spec["n_antigens"]) == spec["n_permutations"], (
            f"{spec['n_permutations']} orderings is not "
            f"{spec['n_antigens']}! -- the permutation test's denominator and its "
            "enumeration disagree"
        )

    @pytest.mark.parametrize("rel", SURFACES)
    def test_a_surface_stating_the_p_value_states_its_denominator(self, rel: str) -> None:
        study = self._study()
        spec = study["specificity_null"]
        text = self._flat(_doc(rel))

        if f"{spec['p_value']:.2e}" not in text:
            pytest.skip(f"{rel} does not state the permutation p-value")

        assert f"{spec['n_antigens']} antigens" in text, (
            f"{rel} states the permutation p-value without naming the "
            f"{spec['n_antigens']} antigens it was computed over, so a reader "
            "attaches it to the 13-antigen difference stated beside it"
        )

    @pytest.mark.parametrize("rel", SURFACES)
    def test_a_surface_stating_the_difference_states_its_denominator(self, rel: str) -> None:
        study = self._study()
        diff = study["null_calibration"]["paired_difference"]
        text = self._flat(_doc(rel))

        if f"{diff['point']:.3f}" not in text:
            pytest.skip(f"{rel} does not state the within-antigen difference")

        assert f"{diff['n_clusters']} antigens" in text, (
            f"{rel} states the {diff['point']:.3f} difference without naming the "
            f"{diff['n_clusters']} antigens it was bootstrapped over"
        )

    def test_the_evidence_page_keeps_them_apart(self) -> None:
        """The page renders both; it must say the p is not the difference's."""
        fastapi = pytest.importorskip("fastapi", reason="the web interface needs the report extra")
        assert fastapi is not None
        from fastapi.testclient import TestClient

        from bindsight.report.web.app import create_app

        study = self._study()
        text = self._flat(TestClient(create_app()).get("/evidence").text)

        assert f"{study['specificity_null']['n_antigens']} antigens" in text, (
            "the Evidence page states the permutation p without its denominator"
        )
        assert f"{study['null_calibration']['paired_difference']['n_clusters']} antigens" in text, (
            "the Evidence page states the within-antigen difference without its denominator"
        )
        assert "not the significance of the" in text, (
            "the Evidence page prints the permutation p under the within-antigen "
            "difference without saying it is not that difference's significance"
        )

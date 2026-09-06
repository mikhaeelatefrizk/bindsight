# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the rediscovery evaluation panel.

The panel is data, and wrong data here would silently corrupt every number the
study reports. These tests pin the identifiers against the vendored references
the pipeline itself uses, and pin the design rules that make the study
non-circular.
"""

from __future__ import annotations

import pytest

from bindsight.benchmark import panel as P


@pytest.fixture(scope="module")
def surfaceome() -> frozenset[str]:
    """The surfaceome accessions bindsight actually filters on.

    Loaded through the package's own loader rather than by splitting the file on
    whitespace: the vendored list carries a comment header, and a naive split
    turns its prose into fake accessions.
    """
    from bindsight.surfaceome.surfy import load_surfy

    return load_surfy(allow_offline_fallback=False)


class TestPanelComposition:
    def test_panel_size_matches_what_is_reported(self) -> None:
        scored = [c for c in P.PANEL if c.usable == "scored"]
        assert len(scored) == 22
        assert len({c.project for c in scored}) == 13
        assert len({c.uniprot for c in scored}) == 13

    def test_no_cohort_is_stratified(self) -> None:
        """Every cohort is a whole TCGA project.

        The previous study selected TCGA-BRCA by PAM50 HER2-enriched subtype and
        then reported discovering ERBB2, which is one of the fifty PAM50 genes.
        The panel has no stratification field at all, so that class of circularity
        cannot be reintroduced by editing data.
        """
        assert not hasattr(P.AntigenCohort, "subtype")
        for cohort in P.PANEL:
            assert cohort.project.startswith("TCGA-")

    def test_admissibility_rule_separates_the_two_properties(self) -> None:
        """Non-circular and not-enriched-for-the-answer are different tests."""
        rule = P.ADMISSIBLE_STRATIFIER_RULE
        assert "counts matrix" in rule
        assert "antigen under test" in rule
        # The IHC case is the one that passes the first and fails the second.
        assert "IHC" in rule
        assert "never" in rule

    def test_every_pair_has_an_agent_and_a_tier(self) -> None:
        for c in P.PANEL + P.EXCLUDED:
            assert c.agent, f"{c.key} has no targeting agent"
            assert c.tier in ("approved", "late_clinical", "clinical_stage")
            assert len(c.note) > 40, f"{c.key} needs an interpretable note"

    def test_keys_are_unique(self) -> None:
        keys = [c.key for c in P.PANEL]
        assert len(keys) == len(set(keys))


class TestIdentifiers:
    """Wrong identifiers would silently corrupt every number in the study."""

    @pytest.mark.parametrize(
        ("uniprot", "ensembl", "symbol"),
        [
            ("P04626", "ENSG00000141736", "ERBB2"),
            ("P09758", "ENSG00000184292", "TACSTD2"),
            ("Q16790", "ENSG00000107159", "CA9"),
            ("P08581", "ENSG00000105976", "MET"),
            ("P00533", "ENSG00000146648", "EGFR"),
            ("Q04609", "ENSG00000086205", "FOLH1"),
            ("Q9UHE8", "ENSG00000164647", "STEAP1"),
            ("P56856", "ENSG00000066405", "CLDN18"),
            ("P21802", "ENSG00000066468", "FGFR2"),
            ("P06731", "ENSG00000105388", "CEACAM5"),
            ("Q96NY8", "ENSG00000143217", "NECTIN4"),
            ("P51654", "ENSG00000147257", "GPC3"),
            ("P15328", "ENSG00000110195", "FOLR1"),
        ],
    )
    def test_accession_and_gene_id_agree_with_uniprot(
        self, uniprot: str, ensembl: str, symbol: str
    ) -> None:
        """Each triple was resolved from the UniProt cross-reference for that accession."""
        matches = [c for c in P.PANEL if c.uniprot == uniprot]
        assert matches, f"{symbol} missing from the panel"
        for c in matches:
            assert c.ensembl == ensembl
            assert c.symbol == symbol

    def test_accessions_are_well_formed(self) -> None:
        for c in P.PANEL + P.EXCLUDED:
            assert c.uniprot.isalnum()
            assert c.ensembl.startswith("ENSG")
            assert len(c.ensembl) == 15


class TestReachability:
    """An antigen the instrument cannot see is not a ranking failure."""

    def test_the_two_unreachable_antigens_are_identified(self, surfaceome: frozenset[str]) -> None:
        unreachable = sorted(
            c.symbol for c in P.PANEL if not P.reachability(c.uniprot, surfaceome)["in_surfaceome"]
        )
        assert unreachable == ["CA9", "STEAP1"]

    def test_the_documentation_names_them(self) -> None:
        assert "CA9" in P.UNREACHABLE_NOTE
        assert "STEAP1" in P.UNREACHABLE_NOTE
        # It must also name the fix, not only the symptom.
        assert "extend the surfaceome" in P.UNREACHABLE_NOTE

    def test_every_other_panel_antigen_is_reachable(self, surfaceome: frozenset[str]) -> None:
        for c in P.PANEL:
            if c.symbol in ("CA9", "STEAP1"):
                continue
            r = P.reachability(c.uniprot, surfaceome)
            assert r["in_surfaceome"], f"{c.symbol} unexpectedly absent from the surfaceome"
            assert r["uniprot_resolved"]

    def test_an_empty_accession_is_never_reachable(self) -> None:
        r = P.reachability("", surfaceome=frozenset())
        assert not r["uniprot_resolved"]
        assert not r["in_surfaceome"]


class TestDenominators:
    """A rate is meaningless without the set it was computed over."""

    def test_primary_denominator_is_approved_agents_only(self) -> None:
        primary = P.scored_panel()
        assert primary
        assert {c.tier for c in primary} == {"approved"}

    def test_widening_the_tier_widens_the_denominator(self) -> None:
        primary = P.scored_panel()
        wide = P.scored_panel(tiers=("approved", "late_clinical", "clinical_stage"))
        assert len(wide) > len(primary)

    def test_underpowered_cohorts_never_enter_a_denominator(self) -> None:
        for c in P.scored_panel(tiers=("approved", "late_clinical", "clinical_stage")):
            assert c.n_normals >= P.MIN_NORMALS_FOR_POWER

    def test_deduplication_gives_one_cohort_per_antigen(self) -> None:
        """ERBB2 in four cohorts is one piece of evidence, not four."""
        dedup = P.deduplicated_panel()
        accessions = [c.uniprot for c in dedup]
        assert len(accessions) == len(set(accessions))

    def test_deduplication_keeps_the_best_powered_cohort(self) -> None:
        """The retained cohort is chosen by sample count, never by outcome."""
        by_acc = {c.uniprot: c for c in P.deduplicated_panel()}
        erbb2 = by_acc["P04626"]
        all_erbb2 = [c for c in P.scored_panel() if c.uniprot == "P04626"]
        assert erbb2.n_normals == max(c.n_normals for c in all_erbb2)

    def test_erbb2_and_egfr_appear_in_several_indications(self) -> None:
        """Within-antigen comparison across cancers is the point of the panel."""
        scored = [c for c in P.PANEL if c.usable == "scored"]
        assert len([c for c in scored if c.symbol == "ERBB2"]) >= 3
        assert len([c for c in scored if c.symbol == "EGFR"]) >= 3


class TestExclusions:
    def test_excluded_pairs_carry_a_reason(self) -> None:
        for c in P.EXCLUDED:
            assert c.usable in ("underpowered", "no_normals")
            assert len(c.note) > 40

    def test_no_normal_projects_really_have_none(self) -> None:
        for c in P.EXCLUDED:
            if c.usable == "no_normals":
                assert P.PROJECT_NORMALS.get(c.project, 0) == 0

    def test_underpowered_projects_are_below_the_floor(self) -> None:
        for c in P.EXCLUDED:
            if c.usable == "underpowered":
                assert 0 < c.n_normals < P.MIN_NORMALS_FOR_POWER

    def test_excluded_pairs_are_not_in_any_denominator(self) -> None:
        scored_keys = {
            c.key for c in P.scored_panel(tiers=("approved", "late_clinical", "clinical_stage"))
        }
        assert not scored_keys & {c.key for c in P.EXCLUDED}


class TestSampleCounts:
    def test_matched_pairs_never_exceed_available_normals(self) -> None:
        for project, pairs in P.PROJECT_MATCHED_PAIRS.items():
            assert pairs <= P.PROJECT_NORMALS[project], project

    def test_every_scored_project_has_verified_counts(self) -> None:
        for c in P.PANEL:
            if c.usable == "scored":
                assert c.project in P.PROJECT_NORMALS
                assert c.project in P.PROJECT_MATCHED_PAIRS

    def test_null_calibration_projects_have_ample_normals(self) -> None:
        """They exist to calibrate the nulls, so they must be well powered."""
        for project in P.NULL_CALIBRATION_PROJECTS:
            assert P.PROJECT_NORMALS[project] >= 20

    def test_null_calibration_projects_carry_no_antigen(self) -> None:
        """Attaching an antigen to them would be inventing an expectation."""
        scored_projects = {c.project for c in P.PANEL if c.usable == "scored"}
        assert not scored_projects & set(P.NULL_CALIBRATION_PROJECTS)

    def test_projects_in_panel_covers_both_sets(self) -> None:
        projects = P.projects_in_panel()
        assert "TCGA-BRCA" in projects
        assert "TCGA-THCA" in projects

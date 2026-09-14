# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for outcome classification and the counterfactual rank.

The point of this module is that four different failures must not be reported as
one number. These tests pin exactly that separation, especially the case the
disposition cascade gets wrong on its own.
"""

from __future__ import annotations

import pandas as pd
import pytest

from bindsight.benchmark import outcomes as O

REACHABLE = {"uniprot_resolved": True, "in_surfaceome": True}
UNREACHABLE = {"uniprot_resolved": True, "in_surfaceome": False}
NO_ACCESSION = {"uniprot_resolved": False, "in_surfaceome": False}


class TestClassification:
    def test_a_ranked_antigen_reports_rank_and_shortlist_size(self) -> None:
        o = O.classify(reachability=REACHABLE, disposition="surfaced", rank=4, shortlist_size=27)
        assert o.outcome_class == O.RANKED
        assert o.rank == 4
        assert o.shortlist_size == 27
        assert o.as_dict()["normalised_rank"] == pytest.approx(4 / 27)
        assert o.counts_in_denominator

    def test_a_rank_without_its_shortlist_is_refused(self) -> None:
        """A rank alone is not interpretable, so it cannot be recorded."""
        with pytest.raises(ValueError, match="shortlist size"):
            O.classify(reachability=REACHABLE, disposition="surfaced", rank=4, shortlist_size=None)

    def test_a_gated_antigen_names_the_gate(self) -> None:
        o = O.classify(
            reachability=REACHABLE,
            disposition="below_enrichment_cutoff",
            rank=None,
            shortlist_size=27,
        )
        assert o.outcome_class == O.GATED_OUT
        assert "top-K enrichment cut" in o.reason
        # It must be legible as a gate rather than a ranking outcome.
        assert "not a ranking outcome" in o.reason
        assert o.counts_in_denominator

    def test_an_unreachable_antigen_is_not_a_ranking_miss(self) -> None:
        """CA9 and STEAP1 are in this position, and it is not the ranker's fault."""
        o = O.classify(
            reachability=UNREACHABLE,
            disposition="below_enrichment_cutoff",
            rank=None,
            shortlist_size=27,
        )
        assert o.outcome_class == O.NOT_REACHABLE
        assert not o.counts_in_denominator
        assert "extend the reference" in o.reason

    def test_reachability_beats_the_disposition_cascade(self) -> None:
        """The cascade cannot express this case, which is why it does not decide it.

        `not_surfaceome` is only reachable in the cascade for genes that already
        passed the enrichment cut, so a surfaceome-absent antigen that also missed
        the cut is recorded as `below_enrichment_cutoff`. Classifying from the
        disposition would file an instrument failure as a gate failure.
        """
        o = O.classify(
            reachability=UNREACHABLE,
            disposition="below_enrichment_cutoff",
            rank=None,
            shortlist_size=100,
        )
        assert o.outcome_class == O.NOT_REACHABLE
        # The disposition is kept as corroboration, and it is allowed to disagree.
        assert o.disposition == "below_enrichment_cutoff"

    def test_a_missing_accession_is_also_unreachable(self) -> None:
        o = O.classify(
            reachability=NO_ACCESSION, disposition="no_uniprot", rank=None, shortlist_size=10
        )
        assert o.outcome_class == O.NOT_REACHABLE
        assert not o.counts_in_denominator

    @pytest.mark.parametrize("disposition", ["uniprot_lookup_failed", "structure_not_queried"])
    def test_a_lookup_failure_is_never_a_negative_result(self, disposition: str) -> None:
        o = O.classify(
            reachability=REACHABLE, disposition=disposition, rank=None, shortlist_size=10
        )
        assert o.outcome_class == O.INFRASTRUCTURE
        assert not o.counts_in_denominator
        assert "re-run" in o.reason

    def test_an_unrecorded_disposition_still_classifies(self) -> None:
        o = O.classify(reachability=REACHABLE, disposition=None, rank=None, shortlist_size=5)
        assert o.outcome_class == O.GATED_OUT
        assert "unrecorded" in o.reason

    def test_only_ranked_and_gated_pairs_enter_a_denominator(self) -> None:
        """Reachability and infrastructure failures say nothing about the ranker."""
        counted = {
            O.classify(
                reachability=REACHABLE, disposition="surfaced", rank=1, shortlist_size=9
            ).counts_in_denominator,
            O.classify(
                reachability=REACHABLE,
                disposition="not_significant",
                rank=None,
                shortlist_size=9,
            ).counts_in_denominator,
        }
        uncounted = {
            O.classify(
                reachability=UNREACHABLE, disposition=None, rank=None, shortlist_size=9
            ).counts_in_denominator,
            O.classify(
                reachability=REACHABLE,
                disposition="uniprot_lookup_failed",
                rank=None,
                shortlist_size=9,
            ).counts_in_denominator,
        }
        assert counted == {True}
        assert uncounted == {False}


def _deg() -> pd.DataFrame:
    """Six genes; G3 is strongly up, G6 strongly down."""
    return pd.DataFrame(
        [
            {"gene_id": "G1", "log2fc": 0.5, "padj": 0.20},
            {"gene_id": "G2", "log2fc": 1.0, "padj": 0.01},
            {"gene_id": "G3", "log2fc": 4.0, "padj": 1e-40},
            {"gene_id": "G4", "log2fc": 2.0, "padj": 0.001},
            {"gene_id": "G5", "log2fc": -0.3, "padj": 0.30},
            {"gene_id": "G6", "log2fc": -3.0, "padj": 1e-20},
        ]
    )


ELIGIBLE = {"G1", "G2", "G3", "G4", "G5", "G6"}


class TestCounterfactualRank:
    def test_the_strongest_gene_ranks_first(self) -> None:
        cf = O.counterfactual_rank(_deg(), target_gene_id="G3", eligible_gene_ids=ELIGIBLE)
        assert cf is not None
        assert cf.rank == 1
        assert cf.n_eligible == 6
        assert cf.direction == "up"

    def test_a_down_regulated_antigen_is_ranked_not_dropped(self) -> None:
        """Restricting to up-regulated genes would leave CEACAM5 undefined.

        CEACAM5 measured a negative fold change in the published run, and it is
        exactly the lineage-antigen case the counterfactual rank exists to
        adjudicate. Silently excluding it would defeat the purpose.
        """
        cf = O.counterfactual_rank(_deg(), target_gene_id="G6", eligible_gene_ids=ELIGIBLE)
        assert cf is not None
        assert cf.rank == 6
        assert cf.direction == "down"
        assert cf.log2fc == pytest.approx(-3.0)

    def test_up_regulated_count_is_the_null_reference_set(self) -> None:
        """The uniform-rank null divides by this, not by the whole eligible set."""
        cf = O.counterfactual_rank(_deg(), target_gene_id="G3", eligible_gene_ids=ELIGIBLE)
        assert cf is not None
        assert cf.n_up_regulated == 4
        assert cf.n_eligible == 6
        assert cf.as_dict()["n_up_regulated"] == 4

    def test_only_eligible_genes_are_ranked_within(self) -> None:
        """A gene outside the surfaceome could never have been a candidate."""
        cf = O.counterfactual_rank(_deg(), target_gene_id="G4", eligible_gene_ids={"G3", "G4"})
        assert cf is not None
        assert cf.n_eligible == 2
        assert cf.rank == 2

    def test_an_untested_gene_returns_none_not_last_place(self) -> None:
        """Never tested and ranked last are different statements."""
        assert (
            O.counterfactual_rank(_deg(), target_gene_id="ABSENT", eligible_gene_ids=ELIGIBLE)
            is None
        )

    def test_no_eligible_genes_returns_none(self) -> None:
        assert O.counterfactual_rank(_deg(), target_gene_id="G1", eligible_gene_ids=set()) is None

    def test_ranking_is_deterministic_on_ties(self) -> None:
        """Two runs must produce the same published rank."""
        tied = pd.DataFrame(
            [
                {"gene_id": "B", "log2fc": 2.0, "padj": 0.01},
                {"gene_id": "A", "log2fc": 2.0, "padj": 0.01},
            ]
        )
        first = O.counterfactual_rank(tied, target_gene_id="A", eligible_gene_ids={"A", "B"})
        second = O.counterfactual_rank(tied, target_gene_id="A", eligible_gene_ids={"A", "B"})
        assert first is not None
        assert second is not None
        assert first.rank == second.rank == 1  # gene_id breaks the tie, ascending

    def test_a_precomputed_score_column_is_used(self) -> None:
        df = _deg()
        df["pi_score"] = [0, 0, 0, 99, 0, 0]  # G4 forced to the top
        cf = O.counterfactual_rank(df, target_gene_id="G4", eligible_gene_ids=ELIGIBLE)
        assert cf is not None
        assert cf.rank == 1

    def test_a_table_without_the_needed_columns_is_an_error(self) -> None:
        with pytest.raises(ValueError, match="log2fc"):
            O.counterfactual_rank(
                pd.DataFrame([{"gene_id": "G1"}]),
                target_gene_id="G1",
                eligible_gene_ids={"G1"},
            )

    def test_missing_padj_is_an_error_when_the_score_must_be_computed(self) -> None:
        with pytest.raises(ValueError, match="padj"):
            O.counterfactual_rank(
                pd.DataFrame([{"gene_id": "G1", "log2fc": 1.0}]),
                target_gene_id="G1",
                eligible_gene_ids={"G1"},
            )


def test_gate_explanations_cover_every_pipeline_disposition() -> None:
    """A results table must never print a bare enum at a reader."""
    from bindsight.pipelines.discover import TAXONOMY_DISPOSITIONS

    missing = [d for d in TAXONOMY_DISPOSITIONS if d not in O.GATE_EXPLANATIONS]
    assert not missing, f"dispositions with no plain-language explanation: {missing}"


class TestAnUntestedGeneIsNotRanked:
    """pydeseq2 writes ``padj = NaN`` for genes independent filtering removed.

    That is *not tested*, which this module's opening paragraph names as a
    different class from *tested and found null*. ``eligible_ranking`` used to
    merge them: ``fillna(1.0)`` gives ``-log10(1.0) == 0``, so an untested gene
    scored exactly 0 and landed mid-pack in the counterfactual ordering,
    displacing the antigen it exists to be a reference for.

    No committed cohort is affected -- 0 of 259,297 genes across all fifteen
    carry a NaN padj -- so no published number moves. A latent defect in the
    ranking that decides a null model is still worth closing before it fires.
    """

    @staticmethod
    def _frame() -> pd.DataFrame:
        return pd.DataFrame(
            {
                "gene_id": ["strong", "weak", "untested", "down"],
                "log2fc": [5.0, 0.5, 9.0, -3.0],
                "padj": [1e-20, 0.4, float("nan"), 1e-10],
            }
        )

    def _ranked(self) -> pd.DataFrame:
        return O.eligible_ranking(
            self._frame(), eligible_gene_ids={"strong", "weak", "untested", "down"}
        )

    def test_the_untested_gene_leaves_the_ordering(self) -> None:
        assert "untested" not in set(self._ranked()["gene_id"]), (
            "a gene that was never tested is ranked among genes that were"
        )

    def test_the_count_is_reported_not_discarded(self) -> None:
        """Dropping them silently would shrink the pool without saying so."""
        assert self._ranked().attrs.get("n_untested") == 1

    def test_a_tested_but_unimpressive_gene_still_ranks(self) -> None:
        """Guards the guard: only *untested* leaves, not merely weak."""
        ordered = self._ranked()

        assert "weak" in set(ordered["gene_id"])
        assert next(iter(ordered["gene_id"])) == "strong"

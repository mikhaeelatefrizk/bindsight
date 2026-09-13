# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Why an antigen did not appear: four classes that must never be merged.

The earlier study reported one number, recall at k, and it conflated four
entirely different things. An antigen bindsight's surfaceome reference has never
heard of, an antigen a documented filter deliberately excluded, an antigen the
ranker buried, and an antigen whose lookup hit a network error are four separate
statements about four different parts of the system. Reporting them as one rate
tells a reader nothing about which part to fix.

The four classes:

- :data:`NOT_REACHABLE` — decidable **before the run**, from static references
  alone: the gene is absent from the annotation, or its accession is absent from
  the surfaceome list. This is an instrument-coverage failure. It names its own
  fix, which is to extend the reference, and it must never be reported as a
  ranking miss.
- :data:`GATED_OUT` — measured, then excluded by a stated filter. Every gate
  gets named, including the enrichment cut, which decides which genes become
  candidates at all and was previously invisible.
- :data:`RANKED` — entered the candidate table. Report the rank *and the size of
  the shortlist it sits in*, because one without the other is not interpretable.
- :data:`INFRASTRUCTURE` — a lookup errored or never ran. A network outage is
  not a scientific negative. Any pair landing here invalidates that pair, and the
  count must be zero in anything published.

**Why the class is not read off the disposition.** ``failure_taxonomy.parquet``
records an ordered cascade, and in that cascade ``not_surfaceome`` is only
reachable for genes that already passed significance, up-regulation and the
enrichment cut. A surfaceome-absent antigen that also missed the enrichment cut
is recorded as ``below_enrichment_cutoff``, so classifying from the disposition
alone would file an instrument-coverage failure as a gate failure. Reachability
is therefore computed independently and wins; the disposition is corroboration.

**The counterfactual rank.** For every pair that did not reach the shortlist,
:func:`counterfactual_rank` reports where it *would* have ranked with no gates at
all. A counterfactual rank of 3 means a gate killed it; a rank of 900 means the
ranker buried it. That single number is what separates the two failure modes,
and it costs nothing beyond the differential-expression table that already
exists.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

__all__ = [
    "GATED_OUT",
    "INFRASTRUCTURE",
    "NOT_REACHABLE",
    "RANKED",
    "CounterfactualRank",
    "Outcome",
    "OutcomeClass",
    "classify",
    "counterfactual_rank",
    "eligible_ranking",
]

OutcomeClass = Literal["not_reachable", "gated_out", "ranked", "infrastructure"]

NOT_REACHABLE: OutcomeClass = "not_reachable"
GATED_OUT: OutcomeClass = "gated_out"
RANKED: OutcomeClass = "ranked"
INFRASTRUCTURE: OutcomeClass = "infrastructure"

#: Dispositions meaning a lookup errored or was never attempted. These are not
#: findings about biology and must never be published as negative results.
_INFRASTRUCTURE_DISPOSITIONS = frozenset({"uniprot_lookup_failed", "structure_not_queried"})

#: Dispositions meaning the gene was measured and then excluded by a named gate,
#: before ever entering the candidate table.
_GATE_DISPOSITIONS = frozenset(
    {
        "not_significant",
        "down_regulated",
        "below_enrichment_cutoff",
        "fails_tractability",
        "fails_safety",
    }
)

#: Human-readable explanation of each gate, so a results table can say what
#: actually happened rather than emitting a bare enum.
GATE_EXPLANATIONS: dict[str, str] = {
    "not_significant": (
        "did not clear the significance rule, which requires BOTH an adjusted "
        "p-value below the FDR threshold AND an absolute log2 fold change at or "
        "above the floor — naming only the FDR would misattribute an antigen that "
        "is statistically solid but modestly changed, such as ERBB2 in the "
        "unstratified breast cohort at log2fc 0.92"
    ),
    "down_regulated": "measured as down-regulated in tumour",
    "below_enrichment_cutoff": (
        "outside the top-K enrichment cut, so it never became a candidate at all "
        "(this is a gate, not a ranking outcome)"
    ),
    "fails_tractability": "no required antibody-tractability modality in Open Targets",
    "fails_safety": "too many vital-tissue safety events",
    "not_surfaceome": "absent from the surfaceome reference",
    "no_uniprot": "no UniProt accession resolved for the gene",
    "uniprot_lookup_failed": "the Open Targets lookup errored; nothing was measured",
    "structure_not_queried": "past the structure-fetch cap; no lookup was attempted",
    "high_normal_tissue_expression": "over the vital-tissue expression ceiling",
    "normal_tissue_unassessed": "no normal-tissue measurement, so the safety gate could not clear it",
    "safety_unassessed": (
        "no Open Targets record, so its safety-event count is unknown rather "
        "than zero and the gate could not clear it"
    ),
    "no_extracellular_domain": "no annotated extracellular domain to bind",
    "low_confidence_structure": "predicted structure too disordered",
    "no_alphafold_model": "no AlphaFold model available",
    "not_top_n": "ranked below the design carry-forward cutoff",
    "no_surface_bind_site": "no targetable site in the SURFACE-Bind data",
    "surface_bind_lookup_failed": (
        "the SURFACE-Bind lookup errored, so nothing was learned about this "
        "protein — not the same as learning it has no targetable site"
    ),
    "surfaced": "carried through to design",
}


@dataclass(frozen=True)
class Outcome:
    """What happened to one antigen in one cohort, and why.

    Attributes:
        outcome_class: Which of the four classes this pair belongs to.
        disposition: The pipeline's own per-gene disposition, kept as
            corroboration. It may disagree with ``outcome_class`` for a
            reachability failure, which is expected and is why both are reported.
        rank: Position in the candidate shortlist, when the pair reached it.
        shortlist_size: Size of that shortlist. A rank without it is not
            interpretable, so the two always travel together.
        reason: Plain-language explanation suitable for a results table.
        counts_in_denominator: Whether this pair may enter a recall rate. False
            for reachability and infrastructure failures, which say nothing about
            the ranker.
    """

    outcome_class: OutcomeClass
    disposition: str | None
    rank: int | None
    shortlist_size: int | None
    reason: str
    counts_in_denominator: bool

    def as_dict(self) -> dict[str, Any]:
        """Serialisable form for the results table."""
        return {
            "outcome_class": self.outcome_class,
            "disposition": self.disposition,
            "rank": self.rank,
            "shortlist_size": self.shortlist_size,
            "normalised_rank": (
                self.rank / self.shortlist_size
                if self.rank is not None and self.shortlist_size
                else None
            ),
            "reason": self.reason,
            "counts_in_denominator": self.counts_in_denominator,
        }


def classify(
    *,
    reachability: dict[str, bool],
    disposition: str | None,
    rank: int | None,
    shortlist_size: int | None,
) -> Outcome:
    """Assign an antigen-cohort pair to exactly one outcome class.

    Reachability is evaluated first and wins, because it is decidable from static
    references before the run and the disposition cascade cannot express it
    reliably. See the module docstring.

    Args:
        reachability: from :func:`bindsight.benchmark.panel.reachability`.
        disposition: the pipeline's per-gene disposition, if the gene was tested.
        rank: position in the candidate shortlist, if it reached one.
        shortlist_size: size of that shortlist.

    Returns:
        The classified outcome.

    Raises:
        ValueError: If a rank is given without the shortlist size it sits in.
            A rank alone is not interpretable and must not be recorded.
    """
    if rank is not None and not shortlist_size:
        raise ValueError(
            "a rank requires the shortlist size it was taken within; "
            "reporting one without the other is not interpretable"
        )

    if not reachability.get("uniprot_resolved", False):
        return Outcome(
            outcome_class=NOT_REACHABLE,
            disposition=disposition,
            rank=None,
            shortlist_size=shortlist_size,
            reason="no UniProt accession, so the antigen can never enter the candidate table",
            counts_in_denominator=False,
        )
    if not reachability.get("in_surfaceome", False):
        return Outcome(
            outcome_class=NOT_REACHABLE,
            disposition=disposition,
            rank=None,
            shortlist_size=shortlist_size,
            reason=(
                "absent from the surfaceome reference, so unreachable at any expression "
                "level. This is an instrument-coverage failure, not a ranking miss; the "
                "fix is to extend the reference"
            ),
            counts_in_denominator=False,
        )

    # A pair that reached the shortlist was assessed by the ranking, which is what
    # this study measures, so its rank stands whatever a later stage reports.
    # `structure_not_queried` in particular is the normal outcome for anything
    # past the structure-fetch cap: treating it as an infrastructure failure
    # would discard a genuine rank and shrink the denominator for no reason.
    if rank is None and disposition in _INFRASTRUCTURE_DISPOSITIONS:
        return Outcome(
            outcome_class=INFRASTRUCTURE,
            disposition=disposition,
            rank=None,
            shortlist_size=shortlist_size,
            reason=(
                f"{GATE_EXPLANATIONS.get(disposition, disposition)} — this pair is "
                "invalid and must be re-run, not reported"
            ),
            counts_in_denominator=False,
        )

    if rank is not None:
        return Outcome(
            outcome_class=RANKED,
            disposition=disposition,
            rank=rank,
            shortlist_size=shortlist_size,
            reason=(
                f"reached the candidate shortlist at rank {rank} of {shortlist_size}"
                + (
                    f" ({GATE_EXPLANATIONS[disposition]})"
                    if disposition and disposition in GATE_EXPLANATIONS
                    else ""
                )
            ),
            counts_in_denominator=True,
        )

    if disposition in _GATE_DISPOSITIONS:
        return Outcome(
            outcome_class=GATED_OUT,
            disposition=disposition,
            rank=None,
            shortlist_size=shortlist_size,
            reason=GATE_EXPLANATIONS.get(disposition, str(disposition)),
            counts_in_denominator=True,
        )

    return Outcome(
        outcome_class=GATED_OUT,
        disposition=disposition,
        rank=None,
        shortlist_size=shortlist_size,
        reason=(
            GATE_EXPLANATIONS.get(disposition or "")
            or f"excluded before the shortlist (disposition: {disposition or 'unrecorded'})"
        ),
        counts_in_denominator=True,
    )


@dataclass(frozen=True)
class CounterfactualRank:
    """Where an antigen would have ranked with every gate removed.

    Attributes:
        rank: 1-based position among the eligible surfaceome by combined score.
        n_eligible: size of that eligible set, without which the rank means nothing.
        n_up_regulated: how many of the eligible set were up-regulated. This is
            the reference set for the uniform-rank null; using ``n_eligible``
            there would roughly halve the p-value.
        log2fc: the antigen's fold change, reported separately from the rank so a
            down-regulated antigen is legible rather than silently excluded.
        score: the combined score itself.
    """

    rank: int
    n_eligible: int
    n_up_regulated: int
    log2fc: float | None
    score: float | None

    @property
    def direction(self) -> str:
        """Whether the antigen was up- or down-regulated, or neither."""
        if self.log2fc is None:
            return "unmeasured"
        if self.log2fc > 0:
            return "up"
        return "down" if self.log2fc < 0 else "flat"

    def as_dict(self) -> dict[str, Any]:
        """Serialisable form for the results table."""
        return {
            "counterfactual_rank": self.rank,
            "n_eligible": self.n_eligible,
            "n_up_regulated": self.n_up_regulated,
            "normalised_counterfactual_rank": self.rank / self.n_eligible
            if self.n_eligible
            else None,
            "log2fc": self.log2fc,
            "direction": self.direction,
            "combined_score": self.score,
        }


def eligible_ranking(
    deg: Any,
    *,
    eligible_gene_ids: set[str],
    score_column: str = "pi_score",
) -> Any:
    """Order the eligible surfaceome by combined score, best first.

    Factored out of :func:`counterfactual_rank` because the decoy null needs
    every eligible gene's rank, not one. Calling that function per gene re-sorted
    the whole frame each time — on a real cohort that is roughly 4,800 sorts of a
    4,800-row table, to produce an ordering that never changes.

    Ranking is over **all** eligible genes with no sign restriction, for the
    reason :func:`counterfactual_rank` gives: restricting to up-regulated genes
    leaves the value undefined for exactly the lineage-antigen cases it exists to
    adjudicate.

    Args:
        deg: the differential-expression table, carrying ``gene_id``, ``log2fc``
            and the score column. The score is computed from ``padj`` if absent.
        eligible_gene_ids: gene ids whose accession is in the surfaceome. These,
            and only these, could ever have been candidates.
        score_column: the combined ranking score.

    Returns:
        A frame ordered best-first with a 1-based ``counterfactual_rank``
        column, or an empty frame when nothing is eligible.

    Raises:
        ValueError: If the table lacks the columns needed to rank at all.
    """
    import numpy as np
    import pandas as pd

    if not isinstance(deg, pd.DataFrame):  # pragma: no cover - defensive
        raise ValueError("deg must be a pandas DataFrame")
    for required in ("gene_id", "log2fc"):
        if required not in deg.columns:
            raise ValueError(f"differential-expression table is missing {required!r}")

    eligible = deg[deg["gene_id"].astype(str).isin(eligible_gene_ids)].copy()
    if eligible.empty:
        return eligible

    if score_column not in eligible.columns:
        if "padj" not in eligible.columns:
            raise ValueError(f"cannot compute {score_column!r}: the table has no 'padj' column")
        padj = eligible["padj"].astype(float).fillna(1.0).clip(lower=1e-300)
        eligible[score_column] = eligible["log2fc"].astype(float) * -np.log10(padj)

    ordered = eligible.sort_values(
        by=[score_column, "gene_id"], ascending=[False, True]
    ).reset_index(drop=True)
    ordered["counterfactual_rank"] = ordered.index + 1
    return ordered


def counterfactual_rank(
    deg: Any,
    *,
    target_gene_id: str,
    eligible_gene_ids: set[str],
    score_column: str = "pi_score",
) -> CounterfactualRank | None:
    """Rank an antigen among the eligible surfaceome with every gate removed.

    Ranking is over **all** eligible genes with no sign restriction. Restricting
    to up-regulated genes would leave the value undefined for exactly the
    lineage-antigen cases it exists to adjudicate — CEACAM5 measured a negative
    fold change, and CLDN18 and EGFR are expected near zero — so the direction is
    reported alongside the rank instead of silently filtering.

    Args:
        deg: the differential-expression table, carrying ``gene_id``, ``log2fc``
            and the score column.
        target_gene_id: the antigen's Ensembl gene id.
        eligible_gene_ids: gene ids whose accession is in the surfaceome. These,
            and only these, could ever have been candidates.
        score_column: the combined ranking score. Computed if absent.

    Returns:
        The counterfactual rank, or ``None`` if the antigen was never tested,
        which is a different statement from ranking last.

    Raises:
        ValueError: If the table lacks the columns needed to rank at all.
    """
    import pandas as pd

    ordered = eligible_ranking(deg, eligible_gene_ids=eligible_gene_ids, score_column=score_column)
    if ordered.empty:
        return None
    match = ordered.index[ordered["gene_id"].astype(str) == str(target_gene_id)]
    if len(match) == 0:
        return None

    position = int(match[0]) + 1
    row = ordered.iloc[position - 1]
    log2fc = float(row["log2fc"]) if pd.notna(row["log2fc"]) else None
    return CounterfactualRank(
        rank=position,
        n_eligible=len(ordered),
        n_up_regulated=int((ordered["log2fc"].astype(float) > 0).sum()),
        log2fc=log2fc,
        score=float(row[score_column]) if pd.notna(row[score_column]) else None,
    )

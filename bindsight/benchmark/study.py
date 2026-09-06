# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The rediscovery study: run one cohort at a time, then score the panel.

Deliberately split into two halves that do not depend on each other.

:func:`prepare_cohort` and :func:`run_cohort` touch the network and the CPU.
They are staged on purpose — one TCGA project per call — so a sweep across
thirteen projects never becomes a single unattended multi-hour job that makes
the machine unusable, and so a failure costs one cohort rather than the study.
The worker count is capped rather than left at "every core".

:func:`score_cohort` and :func:`summarise` are pure functions over tables that
already exist on disk. They can be re-run, tested and argued with at no cost,
which matters because the scoring rules are where the previous study went wrong.

**The paired design.** Cohorts are built from patients who contributed both a
tumour and a solid-tissue normal, and the contrast blocks on the patient. In
most TCGA projects nearly every normal has a matching tumour, so pairing costs
almost no data and removes between-patient variance — the largest free power
gain available here. The blocking factor is ``case_barcode``, which is the
column the design table actually carries.

**What is reported.** Never a bare rate. Every cohort publishes the sizes of the
sets its numbers were computed over, every pair publishes its outcome class and
its counterfactual rank, and every rate publishes a numerator, a denominator and
an interval. A reader who disagrees with the denominator can recompute from what
is printed.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from bindsight.benchmark import outcomes as O
from bindsight.benchmark import panel as P
from bindsight.benchmark import statistics as S

LOG = logging.getLogger(__name__)

__all__ = [
    "CohortResult",
    "StudyConfig",
    "prepare_cohort",
    "run_cohort",
    "score_cohort",
    "summarise",
]


@dataclass(frozen=True)
class StudyConfig:
    """How the study runs, and what it is scored against.

    Attributes:
        out_dir: root for cohort run directories and artifacts.
        n_cpus: worker cap for differential expression. Two leaves headroom on a
            four-core laptop, which is what this is expected to run on.
        max_pairs: cap on matched pairs per cohort. ``None`` uses every pair,
            which is the point of the paired design.
        tiers: regulatory tiers entering the primary denominator.
        fdr_threshold: FDR for calling a gene differentially expressed.
        log2fc_threshold: fold-change floor applied after FDR.
        seed: fixed so every interval and null in the report is reproducible.
        n_decoys: decoys per antigen for the primary null.
        n_permutations: permutations for the panel-level specificity null.
    """

    out_dir: Path
    n_cpus: int | None = 2
    max_pairs: int | None = None
    tiers: tuple[P.Tier, ...] = ("approved",)
    fdr_threshold: float = 0.05
    log2fc_threshold: float = 1.0
    seed: int = 0
    n_decoys: int = 1000
    n_permutations: int = 10_000
    # Cutoffs at which recall is reported. A single cutoff is not interpretable
    # across cohorts whose shortlists differ in size, and the shortlist here is
    # roughly 285 rather than the ~40 it was before the surfaceome pre-filter —
    # so "within the top 20" silently became a far harder question. Reporting a
    # range, alongside each antigen's normalised rank, is what lets a reader see
    # that rather than infer it.
    recall_at_k: tuple[int, ...] = (5, 10, 20, 50, 100)


@dataclass
class CohortResult:
    """Everything one cohort contributes to the study.

    ``set_sizes`` is not optional decoration. A rank without the size of the
    shortlist it sits in is uninterpretable, and the previous study's results
    table omitted it.
    """

    project: str
    set_sizes: dict[str, int]
    pairs: list[dict[str, Any]] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)
    stage_status: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        """Serialisable form."""
        return {
            "project": self.project,
            "set_sizes": self.set_sizes,
            "pairs": self.pairs,
            "provenance": self.provenance,
            "stage_status": self.stage_status,
        }


def prepare_cohort(
    project: str, config: StudyConfig, *, max_pairs: int | None = None
) -> dict[str, Any]:
    """Download one project's matched tumour-normal cohort.

    Only patients contributing both arms are used, so the contrast can block on
    the patient. Nothing is downloaded twice: an existing counts file with its
    provenance is reused, which is what makes a staged sweep resumable.

    Args:
        project: GDC project id.
        config: study configuration.
        max_pairs: override the configured cap for this cohort.

    Returns:
        The GDC provenance dict.

    Raises:
        ValueError: If the project has no matched pairs, so no paired contrast
            exists. That is a property of the data and must not be worked around
            by silently falling back to an unpaired design.
    """
    from bindsight.io.gdc import fetch_cohort, matched_pair_cases

    run_dir = Path(config.out_dir) / project.removeprefix("TCGA-").lower()
    counts = run_dir / "counts.tsv.gz"
    design = run_dir / "design.tsv"
    provenance_path = run_dir / "provenance.json"

    if counts.exists() and design.exists() and provenance_path.exists():
        LOG.info("%s: reusing the cohort already on disk (%s)", project, counts)
        return dict(json.loads(provenance_path.read_text()))

    cases = matched_pair_cases(project)
    if not cases:
        raise ValueError(
            f"{project} has no patients with both a primary tumour and a solid-tissue "
            "normal, so no paired contrast is possible. Exclude the cohort rather than "
            "substituting an unpaired or cross-study normal."
        )
    cap = max_pairs if max_pairs is not None else config.max_pairs
    if cap is not None:
        cases = cases[:cap]

    LOG.info("%s: fetching %d matched pair(s)", project, len(cases))
    provenance = fetch_cohort(
        project=project,
        n_tumor=len(cases),
        n_normal=len(cases),
        counts_out=counts,
        design_out=design,
        tumor_cases=cases,
        normal_cases=cases,
    )
    return dict(provenance)


def build_run_config(project: str, config: StudyConfig) -> Any:
    """Discovery configuration for one cohort, with the paired design.

    The blocking factor is ``case_barcode`` because that is the column the
    design table carries; ``patient`` does not exist and would fail inside
    pydeseq2 with an unhelpful message about an unknown factor.
    """
    from bindsight.config import (
        DEGParams,
        DesignParams,
        InputsConfig,
        RankParams,
        RunConfig,
        StageParams,
        TargetDiscoveryParams,
        ValidateParams,
    )

    run_dir = Path(config.out_dir) / project.removeprefix("TCGA-").lower()
    return RunConfig(
        name=f"study_{project.removeprefix('TCGA-').lower()}",
        out_dir=run_dir,
        inputs=InputsConfig(
            counts=run_dir / "counts.tsv.gz", design=run_dir / "design.tsv", download=None
        ),
        params=StageParams(
            deg=DEGParams(
                # Blocking on the patient is what the matched-pair cohort exists
                # for. case_barcode is the column the design table carries;
                # "patient" does not exist and would fail inside pydeseq2 with an
                # unhelpful message about an unknown factor.
                design_formula="~ case_barcode + condition",
                contrast=["condition", "tumor", "normal"],
                fdr_threshold=config.fdr_threshold,
                log2fc_threshold=config.log2fc_threshold,
                min_replicates=3,
                n_cpus=config.n_cpus,
            ),
            target_discovery=TargetDiscoveryParams(
                require_surfy=True,
                surfy_allow_offline_fallback=False,
                use_open_targets=True,
                # The surfaceome filter already enforces cell-surface localisation,
                # which is the biological prerequisite. Gating additionally on Open
                # Targets' antibody-tractability bucket would drop bona-fide surface
                # antigens on an incomplete curated call and confound a test that is
                # meant to be about expression.
                require_tractable_modality=[],
                max_safety_events=5,
                require_surface_bind_site=False,
                top_n=20,
            ),
            design=DesignParams(),
            validate=ValidateParams(),
            rank=RankParams(),
        ),
        backend="mock",
    )


def run_cohort(project: str, config: StudyConfig) -> Path:
    """Run discovery for one prepared cohort. Returns its run directory.

    This is the expensive call: differential expression across every gene with a
    blocking factor per patient. It is one project per invocation by design.
    """
    from bindsight.pipelines.discover import run as run_discover

    run_dir = Path(config.out_dir) / project.removeprefix("TCGA-").lower()
    run_config = build_run_config(project, config)
    LOG.info("%s: running discovery (n_cpus=%s)", project, config.n_cpus)
    run_discover(run_config, out_dir=run_dir)
    return run_dir


def score_cohort(
    project: str,
    run_dir: Path,
    *,
    surfaceome: frozenset[str],
    entries: list[P.AntigenCohort] | None = None,
) -> CohortResult:
    """Score every panel antigen for one cohort. Pure: reads tables, writes nothing.

    Args:
        project: the project scored.
        run_dir: a completed discovery run directory.
        surfaceome: the accessions the pipeline filters on, used to decide
            reachability *before* consulting any pipeline output.
        entries: panel entries for this project; defaults to all of them.

    Returns:
        The cohort's contribution to the study.

    Raises:
        FileNotFoundError: If the run has no differential-expression table, which
            means the cohort never ran and must not be scored as a miss.
    """
    import pandas as pd

    deg_path = run_dir / "deg" / "results.parquet"
    if not deg_path.exists():
        raise FileNotFoundError(
            f"{project}: no differential-expression table at {deg_path}. A cohort that "
            "did not run is not a cohort that found nothing."
        )
    deg = pd.read_parquet(deg_path)

    candidates_path = run_dir / "targets" / "candidates.parquet"
    candidates = (
        pd.read_parquet(candidates_path)
        if candidates_path.exists() and candidates_path.stat().st_size > 0
        else pd.DataFrame()
    )
    taxonomy_path = run_dir / "taxonomy" / "failure_taxonomy.parquet"
    taxonomy = (
        pd.read_parquet(taxonomy_path)
        if taxonomy_path.exists() and taxonomy_path.stat().st_size > 0
        else pd.DataFrame()
    )

    # The eligible surfaceome: every TESTED gene whose accession is in the
    # reference. This is the set a counterfactual rank is taken within, and its
    # size is what makes that rank mean anything.
    #
    # It must come from the vendored gene map, not from the run's own candidates
    # table. The candidates table holds only the genes that survived the
    # enrichment cut, so ranking within it would be ranking within the pipeline's
    # own output — and the counterfactual rank exists precisely to say where an
    # antigen would have landed had that cut not been applied.
    from bindsight.surfaceome.surfy import load_surfy_gene_map

    gene_to_uniprot = {
        gene: accession
        for gene, accession in load_surfy_gene_map().items()
        if accession in surfaceome
    }
    entries = entries if entries is not None else [c for c in P.PANEL if c.project == project]
    # Panel antigens must be resolvable even if the vendored map missed them.
    for entry in entries:
        if entry.uniprot in surfaceome:
            gene_to_uniprot.setdefault(entry.ensembl, entry.uniprot)
    tested_genes = set(deg["gene_id"].astype(str))
    eligible_gene_ids = tested_genes & set(gene_to_uniprot)

    shortlist_size = len(candidates) if not candidates.empty else 0
    rank_by_gene: dict[str, int] = {}
    if not candidates.empty and {"gene_id", "rank"} <= set(candidates.columns):
        rank_by_gene = {
            str(g): int(r) for g, r in zip(candidates["gene_id"], candidates["rank"], strict=False)
        }
    disposition_by_gene: dict[str, str] = {}
    if not taxonomy.empty and {"gene_id", "disposition"} <= set(taxonomy.columns):
        disposition_by_gene = {
            str(g): str(d)
            for g, d in zip(taxonomy["gene_id"], taxonomy["disposition"], strict=False)
        }

    pairs: list[dict[str, Any]] = []
    for entry in entries:
        reach = P.reachability(entry.uniprot, surfaceome)
        rank = rank_by_gene.get(entry.ensembl)
        outcome = O.classify(
            reachability=reach,
            disposition=disposition_by_gene.get(entry.ensembl),
            rank=rank,
            shortlist_size=shortlist_size or None,
        )
        counterfactual = O.counterfactual_rank(
            deg, target_gene_id=entry.ensembl, eligible_gene_ids=eligible_gene_ids
        )
        row: dict[str, Any] = {
            "project": entry.project,
            "symbol": entry.symbol,
            "uniprot": entry.uniprot,
            "ensembl": entry.ensembl,
            "agent": entry.agent,
            "tier": entry.tier,
            "usable": entry.usable,
            "note": entry.note,
            "reachability": reach,
            **outcome.as_dict(),
        }
        row.update(counterfactual.as_dict() if counterfactual else {"counterfactual_rank": None})
        row.update(_deg_row(deg, entry.ensembl))
        pairs.append(row)

    return CohortResult(
        project=project,
        set_sizes={
            "n_genes_tested": len(deg),
            "n_eligible_surfaceome": len(eligible_gene_ids),
            "n_candidates": shortlist_size,
            "n_significant": int(deg["significant"].sum()) if "significant" in deg.columns else 0,
        },
        pairs=pairs,
        stage_status={"deg": "completed", "discover": "completed"},
    )


def _deg_row(deg: Any, ensembl: str) -> dict[str, Any]:
    """The antigen's own differential-expression statistics, or explicit nulls."""
    import pandas as pd

    match = deg[deg["gene_id"].astype(str) == ensembl]
    if match.empty:
        # Not tested is a different statement from not significant, and the
        # results table has to be able to say which.
        return {"tested": False, "log2fc": None, "padj": None, "significant": None}
    row = match.iloc[0]

    def _num(column: str) -> float | None:
        if column not in match.columns or pd.isna(row[column]):
            return None
        return float(row[column])

    return {
        "tested": True,
        "log2fc": _num("log2fc"),
        "padj": _num("padj"),
        "base_mean": _num("baseMean"),
        "lfc_se": _num("lfc_se"),
        "significant": bool(row["significant"]) if "significant" in match.columns else None,
    }


def summarise(results: list[CohortResult], config: StudyConfig) -> dict[str, Any]:
    """Aggregate scored cohorts into the reportable study summary.

    Three denominators are published as a nested cascade, each with its own
    numerator and count, so a reader can reconstruct the conservative headline
    from the permissive one:

    - **all** — every scored pair. The headline, and the most conservative.
    - **reachable** — pairs the instrument could have surfaced at all.
    - **gate_passed** — pairs that entered the shortlist. This, and only this, is
      a measure of the ranker.

    The previous study chose its denominator after seeing the data, restricting
    to antigens measured as over-expressed, which mechanically inflated the rate.
    These are fixed in advance and never merged.
    """
    pairs = [p for r in results for p in r.pairs if p.get("usable") == "scored"]
    in_tiers = [p for p in pairs if p.get("tier") in config.tiers]
    infrastructure = [p for p in in_tiers if p["outcome_class"] == O.INFRASTRUCTURE]

    cascade: dict[str, Any] = {}
    for name, subset in (
        ("all", in_tiers),
        ("reachable", [p for p in in_tiers if p["outcome_class"] != O.NOT_REACHABLE]),
        ("gate_passed", [p for p in in_tiers if p["outcome_class"] == O.RANKED]),
    ):
        eligible = [p for p in subset if p["outcome_class"] != O.INFRASTRUCTURE]
        if not eligible:
            cascade[name] = {"numerator": 0, "denominator": 0, "note": "no eligible pairs"}
            continue
        at_k: dict[str, Any] = {}
        for k in config.recall_at_k:
            hits = sum(1 for p in eligible if _is_hit(p, k=k))
            at_k[f"recall@{k}"] = {
                "wilson": S.wilson_interval(hits, len(eligible)).as_dict(),
                "clopper_pearson": S.clopper_pearson_interval(hits, len(eligible)).as_dict(),
            }
        # The headline cutoff, kept so a single number can still be quoted — but
        # only ever beside the shortlist sizes it was computed against.
        headline_k = 20 if 20 in config.recall_at_k else config.recall_at_k[-1]
        headline = at_k[f"recall@{headline_k}"]
        cascade[name] = {
            "at_k": at_k,
            "headline_k": headline_k,
            "wilson": headline["wilson"],
            "clopper_pearson": headline["clopper_pearson"],
            "removed_from_previous_step": len(subset) - len(eligible),
            "median_shortlist_size": _median(
                [p["shortlist_size"] for p in eligible if p.get("shortlist_size")]
            ),
        }

    # The de-duplicated panel is what the interval is honestly computed over,
    # because one antigen in four cohorts is one piece of evidence.
    dedup_keys = {c.key for c in P.deduplicated_panel(tiers=config.tiers)}
    dedup = [p for p in in_tiers if _pair_key(p) in dedup_keys]
    dedup_eligible = [p for p in dedup if p["outcome_class"] != O.INFRASTRUCTURE]

    clusters: dict[str, Sequence[bool]] = {}
    headline_k = 20 if 20 in config.recall_at_k else config.recall_at_k[-1]
    for p in in_tiers:
        if p["outcome_class"] != O.INFRASTRUCTURE:
            cast("list[bool]", clusters.setdefault(p["uniprot"], [])).append(
                _is_hit(p, k=headline_k)
            )

    summary: dict[str, Any] = {
        "schema": "bindsight-rediscovery/3",
        "design": {
            "cohorts": "whole unstratified TCGA project, all primary tumour vs all normal",
            "contrast": "~ case_barcode + condition (paired on patient)",
            "admissible_stratifier_rule": P.ADMISSIBLE_STRATIFIER_RULE,
            "unreachable_note": P.UNREACHABLE_NOTE,
            "tiers_in_primary_denominator": list(config.tiers),
            "seed": config.seed,
        },
        "set_sizes_by_cohort": {r.project: r.set_sizes for r in results},
        "recall_cascade": cascade,
        "infrastructure_failures": {
            "n": len(infrastructure),
            "pairs": [f"{p['project']}:{p['symbol']}" for p in infrastructure],
            "note": (
                "A lookup that errored or never ran is not a negative result. This "
                "count must be zero in anything published; any pair here invalidates "
                "itself and must be re-run."
            ),
        },
        "outcome_class_counts": _class_counts(in_tiers),
        "pairs": pairs,
    }

    if dedup_eligible:
        headline_k = 20 if 20 in config.recall_at_k else config.recall_at_k[-1]
        hits = sum(1 for p in dedup_eligible if _is_hit(p, k=headline_k))
        summary["primary_interval"] = {
            "description": (
                "One cohort per antigen, so the trials are independent. This is the "
                "interval to quote; the cascade above is computed over correlated pairs."
            ),
            "wilson": S.wilson_interval(hits, len(dedup_eligible)).as_dict(),
            "clopper_pearson": S.clopper_pearson_interval(hits, len(dedup_eligible)).as_dict(),
            "n_distinct_antigens": len(dedup_eligible),
        }
    if len(clusters) >= 2:
        summary["cluster_bootstrap"] = S.cluster_bootstrap_interval(
            clusters, seed=config.seed
        ).as_dict()

    for p in summary["pairs"]:
        cf, n_up = p.get("counterfactual_rank"), p.get("n_up_regulated")
        if isinstance(cf, int) and isinstance(n_up, int) and n_up > 0 and cf <= n_up:
            p["p_uniform_rank"] = S.uniform_rank_p(cf, n_up)
        else:
            p["p_uniform_rank"] = None
    return summary


def _pair_key(pair: dict[str, Any]) -> str:
    project = str(pair["project"]).removeprefix("TCGA-").lower()
    return f"{project}_{str(pair['symbol']).lower()}"


def _is_hit(pair: dict[str, Any], *, k: int = 20) -> bool:
    """Whether the antigen reached the shortlist inside the given cutoff.

    ``k`` is an absolute rank, so it is only comparable across cohorts whose
    shortlists are of similar size. The shortlist sizes are published alongside
    every rate for exactly that reason, and each pair also carries its
    normalised rank.
    """
    rank = pair.get("rank")
    return isinstance(rank, int) and rank <= k


def _median(values: list[int]) -> int | None:
    """Median as an integer, or None for an empty list."""
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) // 2


def _class_counts(pairs: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = dict.fromkeys(
        (O.NOT_REACHABLE, O.GATED_OUT, O.RANKED, O.INFRASTRUCTURE), 0
    )
    for p in pairs:
        counts[p["outcome_class"]] = counts.get(p["outcome_class"], 0) + 1
    return counts

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
    # Every panel antigen's standing in THIS cohort, whether or not the cohort is
    # its indication. Symbol -> 1.0 at counterfactual rank 1, falling to 0 at the
    # bottom of the eligible set. The panel-level specificity null needs each
    # antigen scored in every cohort, and this is where that matrix comes from.
    antigen_scores: dict[str, float] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        """Serialisable form."""
        return {
            "project": self.project,
            "set_sizes": self.set_sizes,
            "pairs": self.pairs,
            "provenance": self.provenance,
            "stage_status": self.stage_status,
            "antigen_scores": self.antigen_scores,
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


#: Number of strata per axis for decoy matching, on each of abundance and
#: dispersion.
#:
#: Quintiles, not deciles, and the reason is resolution. An exact within-stratum
#: tail can be no smaller than ``1 / (1 + pool)``, so the stratum size *is* the
#: smallest p-value the null can ever report. Measured on the real KIRC cohort,
#: whose eligible surfaceome is 2,209 genes:
#:
#:     deciles   97 cells   median  22 per cell   floor p = 0.046
#:     quintiles 25 cells   median  76 per cell   floor p = 0.013
#:
#: Deciles match more tightly and cannot resolve significance at all — CA9's own
#: cell held nine other genes, so 0.1 was the best p obtainable for the
#: strongest signal in the panel. Quintiles keep each cell a fifth of each axis,
#: which is still a meaningful match, and buy an order of magnitude of
#: resolution. Every pair reports its own floor so the trade is visible per
#: antigen rather than assumed.
_DECOY_STRATA_BINS = 5


def _decoy_strata(ordered: Any) -> Any:
    """Label each eligible gene with its abundance and dispersion stratum.

    A decoy is only a decoy if it could plausibly have been the antigen. The
    confound the decoy null exists to remove is that abundant, high-dispersion
    genes reach significance more easily, so a matched decoy must share both.

    ``baseMean`` is DESeq2's abundance. ``lfc_se`` stands in for dispersion: the
    standard error of the log fold change is a function of dispersion, count
    depth and sample size, and since abundance is already conditioned on, what
    remains tracks dispersion. The true fitted dispersion is not written to
    ``deg/results.parquet``, and re-running DESeq2 across fifteen cohorts to
    recover it would cost far more than the refinement is worth. This is a proxy
    and is reported as one.

    Ranks are binned rather than raw values, so a heavily skewed distribution
    still yields even strata.

    Args:
        ordered: the eligible ranking, carrying ``baseMean`` and ``lfc_se``.

    Returns:
        The frame with ``base_mean_decile`` and ``dispersion_decile`` columns.
        Either is ``-1`` where the underlying column is missing or unusable, which
        collapses those genes into one stratum rather than dropping them.
    """
    import pandas as pd

    out = ordered.copy()
    for column, label in (("baseMean", "base_mean_decile"), ("lfc_se", "dispersion_decile")):
        if column not in out.columns:
            out[label] = -1
            continue
        values = pd.to_numeric(out[column], errors="coerce")
        if values.notna().sum() < _DECOY_STRATA_BINS:
            out[label] = -1
            continue
        binned = pd.qcut(
            values.rank(method="first"), _DECOY_STRATA_BINS, labels=False, duplicates="drop"
        )
        out[label] = binned.fillna(-1).astype(int)
    return out


def _decoy_null_by_gene(
    ordered: Any,
    *,
    gene_ids: set[str],
    n_decoys: int,
    seed: int,
) -> dict[str, dict[str, Any]]:
    """Decoy-null p-value for each named gene, against its own stratum.

    **This is the null the module calls primary, and until now it had never
    run.** ``decoy_null_p`` and ``match_decoys`` had no non-test call site, and
    ``StudyConfig.n_decoys`` was documented as configuring them and read by
    nothing.

    Scoped to the **counterfactual rank**, not the shortlist rank. That matters:
    a decoy null over the shortlist would require every decoy to face the same
    gates as the antigen, and Open Targets is only queried for the top few
    hundred genes per cohort, so gate parity would need a bulk warm-up over the
    whole surfaceome. The counterfactual rank is a pure function of the
    differential-expression table and the surfaceome reference — there are no
    gates to match — so the comparison is exact and costs nothing.

    Exact, too, in the literal sense. The counterfactual rank is deterministic,
    so the honest p-value is the true within-stratum tail: of the genes matched
    to this one on abundance and dispersion, what fraction ranked at least as
    well. Drawing a thousand samples from a stratum of fifty would only add Monte
    Carlo noise to a quantity that can be computed. ``n_decoys`` is therefore a
    cap: a stratum at or below it is used whole and the p-value is exact, and
    only a larger one is subsampled.

    Args:
        ordered: the eligible ranking from :func:`outcomes.eligible_ranking`.
        gene_ids: the genes to compute a p-value for.
        n_decoys: cap on decoys drawn from one stratum.
        seed: fixed so a published p-value is reproducible.

    Returns:
        gene id -> the p-value, the stratum it was taken in, how many decoys
        were available and used, and whether the tail was exact.
    """
    out: dict[str, dict[str, Any]] = {}
    if ordered.empty or not gene_ids:
        return out

    labelled = _decoy_strata(ordered)
    wanted = labelled[labelled["gene_id"].astype(str).isin(gene_ids)]
    if wanted.empty:
        return out

    grouped = {
        key: frame for key, frame in labelled.groupby(["base_mean_decile", "dispersion_decile"])
    }
    for row in wanted.itertuples(index=False):
        gene = str(row.gene_id)
        stratum = grouped.get((row.base_mean_decile, row.dispersion_decile))
        if stratum is None:
            continue
        pool = stratum[stratum["gene_id"].astype(str) != gene]
        available = len(pool)
        if available == 0:
            # A stratum of one says nothing: there was nothing to compare against.
            out[gene] = {
                "p_decoy": None,
                "p_decoy_floor": None,
                "decoy_pool_size": 0,
                "decoy_n_used": 0,
                "decoy_exact": False,
                "base_mean_decile": int(row.base_mean_decile),
                "dispersion_decile": int(row.dispersion_decile),
            }
            continue

        exact = available <= n_decoys
        if exact:
            ranks = [int(r) for r in pool["counterfactual_rank"]]
        else:
            # Too many to enumerate: fall back to the matched sampler, which
            # draws without replacement while the stratum can supply it.
            records = [
                {
                    "uniprot": str(g),
                    "base_mean_decile": int(row.base_mean_decile),
                    "dispersion_decile": int(row.dispersion_decile),
                    "counterfactual_rank": int(r),
                }
                for g, r in zip(pool["gene_id"], pool["counterfactual_rank"], strict=True)
            ]
            target = {
                "uniprot": gene,
                "base_mean_decile": int(row.base_mean_decile),
                "dispersion_decile": int(row.dispersion_decile),
            }
            drawn = S.match_decoys(records, target, n_decoys=n_decoys, seed=seed)
            ranks = [int(d["counterfactual_rank"]) for d in drawn]

        out[gene] = {
            "p_decoy": S.decoy_null_p(int(row.counterfactual_rank), ranks),
            # The smallest p this stratum could ever have produced. Without it a
            # reader cannot tell a genuine null result from a stratum too thin to
            # resolve one.
            "p_decoy_floor": 1 / (1 + len(ranks)),
            "decoy_pool_size": available,
            "decoy_n_used": len(ranks),
            "decoy_exact": exact,
            "base_mean_decile": int(row.base_mean_decile),
            "dispersion_decile": int(row.dispersion_decile),
        }
    return out


#: What a stage status says when the run cannot be asked.
#:
#: Deliberately not "completed". A cohort scored from a run whose manifest is
#: missing has an unknown provenance, and the one thing that must not be written
#: is the reassuring answer.
UNRECORDED_STAGE = "unrecorded"


def stage_status_from_manifest(run_dir: Path) -> dict[str, str]:
    """The stages a run actually recorded, read rather than assumed.

    ``CohortResult.stage_status`` was the literal
    ``{"deg": "completed", "discover": "completed"}``. A cohort whose discover
    stage crashed still has its DEG table, so it was scored — with an empty
    shortlist, every panel antigen counted as gated out, and both stages
    asserted complete. That turns an infrastructure failure into a biological
    negative and folds it into the study's headline recall.

    The principle is already stated one function down, for the DEG table: *a
    cohort that did not run is not a cohort that found nothing*. It simply was
    not applied to the stage that builds the shortlist.

    Args:
        run_dir: the cohort's run directory.

    Returns:
        ``{stage name: status}`` from ``run_manifest.jsonld``. A stage the
        manifest does not mention, and every stage when the manifest is absent
        or unreadable, maps to :data:`UNRECORDED_STAGE`.
    """
    import json

    wanted = ("deg", "discover")
    manifest = Path(run_dir) / "run_manifest.jsonld"
    status = dict.fromkeys(wanted, UNRECORDED_STAGE)
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return status
    for record in data.get("stages") or []:
        name = record.get("name")
        if name in status and record.get("status"):
            # Last write wins: a stage re-run supersedes its earlier attempt.
            status[name] = str(record["status"])
    return status


def score_cohort(
    project: str,
    run_dir: Path,
    *,
    surfaceome: frozenset[str],
    entries: list[P.AntigenCohort] | None = None,
    n_decoys: int = StudyConfig.n_decoys,
    seed: int = StudyConfig.seed,
) -> CohortResult:
    """Score every panel antigen for one cohort. Pure: reads tables, writes nothing.

    Args:
        project: the project scored.
        run_dir: a completed discovery run directory.
        surfaceome: the accessions the pipeline filters on, used to decide
            reachability *before* consulting any pipeline output.
        entries: panel entries for this project; defaults to all of them.
        n_decoys: cap on decoys drawn from one abundance/dispersion stratum.
            A stratum at or below it is used whole, making the tail exact.
        seed: fixed so a published decoy p-value is reproducible.

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

    # Read, not assumed. A discover stage that crashed leaves the DEG table
    # intact, so the guard above passes and the cohort is scored with an empty
    # shortlist — every panel antigen gated out, counted in the denominator,
    # and folded into the study's recall as though discovery had legitimately
    # found nothing.
    stage_status = stage_status_from_manifest(run_dir)
    if stage_status.get("discover") == "failed":
        raise RuntimeError(
            f"{project}: the discover stage failed, so this cohort has no shortlist "
            "to score. A cohort whose discovery crashed is not a cohort that found "
            "nothing; scoring it would count every panel antigen as a miss."
        )

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

    # One ranking for the whole cohort, shared by every antigen and by the decoy
    # null. Building it per gene would re-sort a 4,800-row frame 4,800 times to
    # produce an ordering that never changes.
    ordered = O.eligible_ranking(deg, eligible_gene_ids=eligible_gene_ids)
    decoy_by_gene = _decoy_null_by_gene(
        ordered,
        gene_ids={str(entry.ensembl) for entry in entries},
        n_decoys=n_decoys,
        seed=seed,
    )

    # Every panel antigen's standing here, not only this cohort's own. The
    # ranking already exists, so this is a lookup, and it is what lets the
    # panel-level null ask whether antigens land in the *right* cancers.
    rank_of_gene = (
        {
            str(g): int(r)
            for g, r in zip(ordered["gene_id"], ordered["counterfactual_rank"], strict=True)
        }
        if not ordered.empty
        else {}
    )
    n_ranked = len(rank_of_gene)
    antigen_scores = {
        antigen.symbol: 1.0 - (rank_of_gene[str(antigen.ensembl)] - 1) / n_ranked
        for antigen in P.PANEL
        if n_ranked and str(antigen.ensembl) in rank_of_gene
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
        row.update(decoy_by_gene.get(str(entry.ensembl), {"p_decoy": None}))
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
        stage_status=stage_status,
        antigen_scores=antigen_scores,
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

    - **all** — every scored pair *in the primary regulatory tier*
      (``config.tiers``), not every scored pair in the panel. The headline, and
      the most conservative of the three. The unrestricted figure is published
      separately as the tier sensitivity analysis, and is a different number:
      1/17 here against 3/22 across every tier.
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

    # Sensitivity to the regulatory tier. The primary denominator is
    # pre-registered on approved agents alone, but restricting to them excludes
    # antigens whose evidence is strong and whose agent is merely not yet
    # licensed — CA9 among them, which ranks first in its cohort. Reporting the
    # wider panel separately shows what the pre-registration costs, without
    # letting a post-hoc denominator inflate the headline.
    all_tiers: tuple[P.Tier, ...] = ("approved", "late_clinical", "clinical_stage")
    wider = [p for p in pairs if p.get("tier") in all_tiers]
    wider_eligible = [p for p in wider if p["outcome_class"] != O.INFRASTRUCTURE]
    if wider_eligible:
        headline_k = 20 if 20 in config.recall_at_k else config.recall_at_k[-1]
        summary["tier_sensitivity"] = {
            "description": (
                "Every scored pair regardless of regulatory tier, reported as a "
                "sensitivity analysis. The primary denominator remains "
                f"{list(config.tiers)}."
            ),
            "at_k": {
                f"recall@{k}": S.wilson_interval(
                    sum(1 for p in wider_eligible if _is_hit(p, k=k)), len(wider_eligible)
                ).as_dict()
                for k in config.recall_at_k
            },
            "headline": S.wilson_interval(
                sum(1 for p in wider_eligible if _is_hit(p, k=headline_k)),
                len(wider_eligible),
            ).as_dict(),
        }

    for p in summary["pairs"]:
        cf, n_up = p.get("counterfactual_rank"), p.get("n_up_regulated")
        if isinstance(cf, int) and isinstance(n_up, int) and n_up > 0 and cf <= n_up:
            p["p_uniform_rank"] = S.uniform_rank_p(cf, n_up)
        else:
            p["p_uniform_rank"] = None

    _adjust_decoy_p(summary["pairs"])
    specificity = _specificity_null(results, config)
    if specificity is not None:
        summary["specificity_null"] = specificity
    calibration = _null_calibration(results)
    if calibration is not None:
        summary["null_calibration"] = calibration
    return summary


def _cognate_projects() -> dict[str, set[str]]:
    """Antigen symbol -> the projects the panel names as its indication."""
    cognate: dict[str, set[str]] = {}
    for entry in P.PANEL:
        cognate.setdefault(entry.symbol, set()).add(entry.project)
    return cognate


def _null_calibration(results: list[CohortResult]) -> dict[str, Any] | None:
    """What the pipeline surfaces where no panel antigen is expected.

    ``NULL_CALIBRATION_PROJECTS`` has been declared since the panel was written —
    "run with no antigen attached, purely to calibrate the null models and audit
    shortlist composition" — and both cohorts were downloaded, run and scored
    without contributing to a single reported number.

    They contribute two things now. As cohorts they enter the permutation null
    as assignments an antigen could receive but should not fit, which is what
    makes that test a test. And they answer directly the question the recall
    number cannot: where does a panel antigen land in a cancer it has nothing to
    do with? If the standing in an antigen's own indication is not clearly
    better than its standing here, the pipeline is ranking generic biology.

    Args:
        results: every scored cohort.

    Returns:
        The comparison and the cohorts it was computed over, or None when
        neither calibration cohort has been run.
    """
    calibration = [r for r in results if r.project in P.NULL_CALIBRATION_PROJECTS]
    if not calibration:
        return None

    cognate = _cognate_projects()
    off_indication = [score for r in calibration for score in r.antigen_scores.values()]
    own_indication = [
        score
        for r in results
        for symbol, score in r.antigen_scores.items()
        if r.project in cognate.get(symbol, set())
    ]
    if not off_indication:
        return None

    block: dict[str, Any] = {
        "description": (
            "Cohorts carrying no panel antigen, run to calibrate the nulls and to "
            "show where panel antigens land in a cancer that is not theirs. A "
            "standing near the off-indication mean is what 'no signal' looks "
            "like on this scale."
        ),
        "projects": [r.project for r in calibration],
        "shortlist_sizes": {r.project: r.set_sizes.get("n_candidates") for r in calibration},
        # Must be zero. A scored pair here would mean an expectation was invented
        # for a cohort chosen precisely because it carries none.
        "n_scored_pairs": sum(len(r.pairs) for r in calibration),
        "n_antigen_standings": len(off_indication),
        "mean_standing_off_indication": sum(off_indication) / len(off_indication),
    }
    if own_indication:
        block["mean_standing_in_own_indication"] = sum(own_indication) / len(own_indication)
        block["n_own_indication"] = len(own_indication)
    return block


def _adjust_decoy_p(pairs: list[dict[str, Any]]) -> None:
    """Benjamini-Hochberg across the panel's decoy p-values, in place.

    The panel puts roughly twenty hypotheses forward at once, and one nominally
    significant result among twenty is not news. Every pair carries both its raw
    p and the panel-adjusted one, so a reader can see the cost of the correction
    rather than being handed only its output.

    Pairs with no decoy p — a stratum of one, or an antigen never tested — get
    ``None`` rather than being dropped, so the column is present on every row.
    """
    for pair in pairs:
        pair.setdefault("p_decoy_bh", None)
    scored = [
        (index, pair["p_decoy"])
        for index, pair in enumerate(pairs)
        if isinstance(pair.get("p_decoy"), float)
    ]
    if not scored:
        return
    adjusted = S.benjamini_hochberg([value for _, value in scored])
    for (index, _), q in zip(scored, adjusted, strict=True):
        pairs[index]["p_decoy_bh"] = q


def _specificity_null(results: list[CohortResult], config: StudyConfig) -> dict[str, Any] | None:
    """Does bindsight put antigens in the *right* cancers?

    The decoy null asks whether an antigen beats matched background inside its
    own cohort. This asks the panel-level question instead: are antigens ranked
    better in their own indication than in someone else's, or is the pipeline
    surfacing generic epithelial biology that happens to contain them? The
    antigen-to-cohort assignment is permuted and the panel statistic recomputed.
    No differential expression is re-run, so it is nearly free.

    **Restricted to antigens with exactly one indication in the panel.** The test
    assigns one cohort per antigen, and ERBB2, EGFR, TACSTD2, MET and CLDN18 each
    appear in several; giving such an antigen a single "own" cohort would mean
    choosing one arbitrarily, and averaging its cognate cohorts would compare an
    average against a single draw. The count of usable antigens is reported so
    the restriction is visible rather than implied.

    Args:
        results: every scored cohort, each carrying its antigen scores.
        config: supplies the permutation count and the seed.

    Returns:
        The panel statistic, its p-value and what it was computed over, or None
        when fewer than two antigens qualify.
    """
    by_project = {r.project: r.antigen_scores for r in results if r.antigen_scores}
    if len(by_project) < 2:
        return None

    # An antigen must be scored in every cohort, or the permutation would compare
    # a statistic built from one set of cohorts against one built from another.
    scored_everywhere = set.intersection(*(set(v) for v in by_project.values()))

    cognate = _cognate_projects()

    usable = sorted(
        symbol
        for symbol in scored_everywhere
        if len(cognate.get(symbol, ())) == 1 and next(iter(cognate[symbol])) in by_project
    )
    if len(usable) < 2:
        return None

    scores = {
        symbol: {project: by_project[project][symbol] for project in by_project}
        for symbol in usable
    }
    observed = sum(scores[s][next(iter(cognate[s]))] for s in usable) / len(usable)
    p = S.permutation_null_p(
        observed, scores, n_perm=config.n_permutations, seed=config.seed, higher_is_better=True
    )
    return {
        "description": (
            "Antigens ranked in their own indication versus a permuted "
            "assignment. The statistic is the mean standing of each antigen in "
            "its cohort, where 1.0 is the top of the eligible surfaceome and 0.0 "
            "the bottom. Restricted to antigens with a single indication in the "
            "panel, because the test assigns one cohort per antigen."
        ),
        "observed": observed,
        "p_value": p,
        "n_antigens": len(usable),
        "n_cohorts": len(by_project),
        "n_permutations": config.n_permutations,
        "antigens": usable,
        "excluded_multi_indication": sorted(
            s for s in scored_everywhere if len(cognate.get(s, ())) > 1
        ),
        # An antigen missing from any cohort's eligible surfaceome cannot enter a
        # complete matrix. Named rather than silently dropped, because the list
        # includes CA9 — the strongest signal in the panel — and a reader should
        # know the specificity result was reached without it.
        "excluded_not_scored_everywhere": sorted(
            {symbol for scores_ in by_project.values() for symbol in scores_} - scored_everywhere
        ),
    }


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

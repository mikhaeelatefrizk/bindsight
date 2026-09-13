# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Multi-objective ranking of validated binders.

Combines four orthogonal signals into a composite ``score``:

1. **Upstream evidence** — DE log2FC × specificity penalty (vital-tissue baseline).
2. **Structure quality** — iPTM, pTM, binder pLDDT, pAE_interaction, RMSD-to-designed.
3. **Affinity** — ``affinity_pred_value`` and ``affinity_probability_binary``.
4. **Sequence quality** — ProteinMPNN sequence recovery vs. backbone (when available).

``affinity_pred_value`` is a log(IC50)-like quantity where **lower is stronger**,
so it is inverted before normalisation. Only a validator that genuinely predicts
affinity may populate it; structure-confidence metrics belong to component 2. Boltz-2
affinity prediction is ligand-only, so for protein binders this component is usually
absent and the composite is renormalised over the components that are present.

Each signal is min-max normalised to [0, 1] across the run, then combined with
user-configurable weights from :class:`bindsight.config.RankWeights`. The output
Parquet has BOTH the composite ``score`` and every component, so users can
re-rank by any single metric in the report.

The rank module deliberately does NOT pick one Right Answer; it produces a
defensible default and surfaces the components so the user can override.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from bindsight.config import RankWeights
from bindsight.design.developability import developability

LOG = logging.getLogger(__name__)


def _minmax(s: pd.Series, *, invert: bool = False) -> pd.Series:
    """Min-max normalise to [0, 1]. NaN stays NaN. Constant series → 0.5.

    With ``invert=True``, lower values → 1.0 (used for "lower is better"
    metrics like pAE_interaction or RMSD).
    """
    if s.isna().all():
        return s
    lo, hi = s.min(skipna=True), s.max(skipna=True)
    if pd.isna(lo) or pd.isna(hi) or lo == hi:
        return s.where(s.isna(), 0.5)
    norm = (s - lo) / (hi - lo)
    return 1.0 - norm if invert else norm


def rank_validated(
    validated: pd.DataFrame,
    candidates: pd.DataFrame | None = None,
    *,
    weights: RankWeights | None = None,
) -> pd.DataFrame:
    """Rank validated binders by a composite score; return a new DataFrame.

    Args:
        validated: rows produced by ``bindsight validate``. Must include at
            least ``binder_id``, ``target_uniprot``, and any of the metric
            columns (``iptm``, ``pae_interaction``, ``affinity_pred_value``,
            ``affinity_probability_binary``, ``rmsd_to_designed``,
            ``sequence_recovery``).
        candidates: optional rows from ``bindsight discover`` (provides
            ``log2fc``, ``symbol``, ``n_safety_events``). Joined on
            ``target_uniprot`` if provided.
        weights: composite-score weights. Defaults to the RankWeights defaults.

    Returns:
        DataFrame sorted by descending ``score``, with ``rank`` column added.
        Columns include the composite ``score``, every component score
        (``score_evidence``, ``score_structure``, ``score_affinity``,
        ``score_sequence``), and the original metrics for transparency.
    """
    weights = weights or RankWeights()
    df = validated.copy()

    # Join in upstream evidence if available.
    if candidates is not None and not candidates.empty:
        keep_cols = [
            c
            for c in ("symbol", "uniprot_id", "log2fc", "padj", "n_safety_events")
            if c in candidates.columns
        ]
        if "uniprot_id" in keep_cols:
            cand = _one_row_per_accession(candidates[keep_cols])
            df = df.merge(
                cand,
                left_on="target_uniprot",
                right_on="uniprot_id",
                how="left",
                suffixes=("", "_cand"),
            )
            if "uniprot_id" in df.columns and "target_uniprot" in df.columns:
                df = df.drop(columns=["uniprot_id"], errors="ignore")

    # Component scores (each in [0, 1]; NaN if metric missing for the row).
    df["score_evidence"] = _evidence_score(df)
    df["score_structure"] = _structure_score(df)
    df["score_affinity"] = _affinity_score(df)
    df["score_sequence"] = (
        _minmax(df["sequence_recovery"])
        if "sequence_recovery" in df.columns
        else pd.Series([float("nan")] * len(df))
    )
    # Developability (sequence biophysics) — only when the binder sequence is
    # carried on the row. developability_score is already an absolute [0, 1].
    if "sequence" in df.columns:
        df["developability_score"] = df["sequence"].map(_developability_score)
        df["score_developability"] = df["developability_score"]
    else:
        df["score_developability"] = pd.Series([float("nan")] * len(df))

    # Composite. Weights apply to non-NaN components only; missing metrics
    # don't penalise — they're just excluded from the weighted average.
    component_cols = [
        ("score_evidence", weights.log2fc_specificity),
        ("score_structure", weights.iptm),
        ("score_affinity", weights.affinity),
        ("score_sequence", weights.sequence_recovery),
        ("score_developability", weights.developability),
    ]
    composite = pd.Series([0.0] * len(df), index=df.index)
    weight_sum = pd.Series([0.0] * len(df), index=df.index)
    for col, w in component_cols:
        if col in df.columns:
            mask = df[col].notna()
            column = pd.to_numeric(df[col], errors="coerce").astype(float)
            composite = composite.add(column.fillna(0.0) * w, fill_value=0.0)
            weight_sum = weight_sum + (mask.astype(float) * w)
    df["score"] = composite / weight_sum.replace(0.0, pd.NA)

    # Sort + add rank
    df = df.sort_values("score", ascending=False, na_position="last").reset_index(drop=True)
    df["rank"] = range(1, len(df) + 1)

    return df


def _developability_score(sequence: object) -> float:
    """Absolute developability score in [0, 1] for a binder sequence; NaN if unavailable."""
    if not isinstance(sequence, str) or not sequence:
        return float("nan")
    d = developability(sequence)
    return d.developability_score if d is not None else float("nan")


def _fold_change_score(log2fc: pd.Series) -> pd.Series:
    """Scale log2 fold change to [0, 1] against an absolute floor of zero.

    Min-max normalisation is scale-free: it maps the smallest value in the table
    to 0 and the largest to 1 regardless of how far apart they actually are. For
    a per-binder metric across forty rows that is harmless. For log2 fold change
    it is not, because the value is per *target*, so a two-target run has two
    distinct values and min-max maps them onto exactly {0.0, 1.0}.

    That is what happened on the first real two-target run. CA9 was
    over-expressed 764-fold and CD70 304-fold; both are enormous, and min-max
    scored the second one zero. The full 0.25 evidence weight swung on a log2fc
    difference of 1.33, which pushed CD70 binders with an ipTM of 0.95 and a
    3.3 A interface below CA9 binders at 0.83 and 11.7 A. The ranking was being
    driven by an artefact of normalisation rather than by evidence.

    Anchoring the floor at zero fixes it without inventing a scale. A log2 fold
    change of zero *is* an absolute zero point: no differential expression, no
    evidence. The top of the range stays relative to the run, which is what
    makes this a ranking rather than an absolute score, but nothing that is
    genuinely over-expressed can be scored as though it were not.

    Down-regulated targets score zero rather than negative: this component asks
    how strong the tumour-selective evidence is, and a gene expressed less in
    tumour has none.

    Args:
        log2fc: per-row log2 fold change, possibly with missing values.

    Returns:
        A [0, 1] series, NaN preserved.
    """
    values = pd.to_numeric(log2fc, errors="coerce")
    if values.isna().all():
        return values
    top = values.max(skipna=True)
    if pd.isna(top) or top <= 0:
        # Nothing in the table is over-expressed, so nothing carries evidence.
        return values.where(values.isna(), 0.0)
    return (values.clip(lower=0.0) / top).where(values.notna())


def _one_row_per_accession(cand: pd.DataFrame) -> pd.DataFrame:
    """Reduce the candidate evidence to one row per UniProt accession.

    Several gene IDs can map to one accession -- read-through loci, paralogous
    symbols sharing a product -- and each carries its own ``log2fc`` and
    ``padj``, which feed the evidence component of the composite score. The
    previous ``drop_duplicates("uniprot_id")`` kept whichever row happened to
    come first, so the evidence joined to a binder depended on the row order of
    an upstream table: a different answer from the same data.

    The strongest evidence for the protein wins instead: smallest ``padj``, then
    largest ``|log2fc|``, then the symbol, so the result is the same whatever
    order the rows arrive in. A collision is logged, because an accession with
    two disagreeing rows is something the reader should be able to see.

    No committed cohort has ever contained one (4,665 candidate rows across the
    eleven real runs, zero duplicated accessions), which is why the arbitrary
    tie-break went unnoticed; that is a reason to make it deterministic, not a
    reason to leave it.
    """
    accessions = cand["uniprot_id"]
    duplicated = accessions.notna() & accessions.duplicated(keep=False)
    if not duplicated.any():
        return cand.drop_duplicates("uniprot_id")

    for accession, group in cand[duplicated].groupby("uniprot_id", sort=True):
        LOG.warning(
            "%d candidate rows share accession %s (%s); keeping the most "
            "significant one for ranking evidence",
            len(group),
            accession,
            ", ".join(sorted(str(v) for v in group.get("symbol", []))) or "no symbols",
        )

    order = cand.copy()
    order["_padj"] = order["padj"].astype(float) if "padj" in order.columns else 1.0
    order["_absfc"] = -order["log2fc"].abs().astype(float) if "log2fc" in order.columns else 0.0
    order["_symbol"] = order["symbol"].astype(str) if "symbol" in order.columns else ""
    # NaN padj sorts last under na_position, so a row with no statistic never
    # displaces one that has it.
    order = order.sort_values(["_padj", "_absfc", "_symbol"], na_position="last", kind="mergesort")
    return (
        order.drop_duplicates("uniprot_id")
        .drop(columns=["_padj", "_absfc", "_symbol"])
        .loc[:, cand.columns]
    )


def _evidence_score(df: pd.DataFrame) -> pd.Series:
    """log2FC on an absolute scale, cut by a vital-tissue specificity penalty.

    ``n_safety_events`` counts the normal tissues where the target is expressed
    above the configured safety ceiling (see ``bindsight.targets.gtex``). Each
    event divides the evidence score down, so a strongly over-expressed target
    that is also present in vital tissue cannot outrank a comparably
    over-expressed one that is tumour-restricted. A target with no recorded
    events is unpenalised.

    Returns NaN where ``log2fc`` is absent, matching the other components: a
    missing metric is excluded from the composite rather than scored as zero.
    """
    if "log2fc" not in df.columns:
        return pd.Series([float("nan")] * len(df), index=df.index)
    score = _fold_change_score(df["log2fc"])
    if "n_safety_events" in df.columns:
        events = pd.to_numeric(df["n_safety_events"], errors="coerce").fillna(0.0).clip(lower=0.0)
        score = score * (1.0 / (1.0 + events))
    return score


def _structure_score(df: pd.DataFrame) -> pd.Series:
    """Mean of the available structure-confidence signals, all oriented so higher is better.

    Carries iPTM, pTM and binder pLDDT (confidence, higher better) alongside
    inverted pAE-interaction and RMSD (error, lower better). pTM and pLDDT live
    here rather than in the affinity component because they measure how confident
    the predictor is in the fold, not how tightly the binder binds.
    """
    parts: list[pd.Series] = []
    if "iptm" in df.columns:
        parts.append(_minmax(df["iptm"]))
    if "ptm" in df.columns:
        parts.append(_minmax(df["ptm"]))
    if "plddt_binder" in df.columns:
        parts.append(_minmax(df["plddt_binder"]))
    if "pae_interaction" in df.columns:
        parts.append(_minmax(df["pae_interaction"], invert=True))
    if "rmsd_to_designed" in df.columns:
        parts.append(_minmax(df["rmsd_to_designed"], invert=True))
    if not parts:
        return pd.Series([float("nan")] * len(df), index=df.index)
    stacked = pd.concat(parts, axis=1)
    return stacked.mean(axis=1, skipna=True)


def _affinity_score(df: pd.DataFrame) -> pd.Series:
    """Combined predicted affinity + binary binder probability, higher = better.

    ``affinity_pred_value`` is a log(IC50)-like quantity: **lower is a stronger
    binder** (-8.0 beats -6.0), so it is inverted on the way in. Getting this
    backwards silently promotes the weakest designs, which is why it is asserted
    numerically in ``tests/test_rank.py`` rather than only by ordering.
    """
    parts: list[pd.Series] = []
    if "affinity_pred_value" in df.columns:
        parts.append(_minmax(df["affinity_pred_value"], invert=True))
    if "affinity_probability_binary" in df.columns:
        # Already in [0, 1]
        parts.append(df["affinity_probability_binary"].astype(float))
    if not parts:
        return pd.Series([float("nan")] * len(df), index=df.index)
    stacked = pd.concat(parts, axis=1)
    return stacked.mean(axis=1, skipna=True)


def rank_run(
    run_dir: Path | str,
    *,
    weights: RankWeights | None = None,
) -> Path:
    """Read a finished run, rank validated binders, write ``rank/ranking.parquet``.

    Returns the output path. Raises FileNotFoundError if validation hasn't
    been run.
    """
    run = Path(run_dir)
    validated_path = run / "validate" / "validated.parquet"
    candidates_path = run / "targets" / "candidates.parquet"
    if not validated_path.exists() or validated_path.stat().st_size == 0:
        raise FileNotFoundError(
            f"no validation output at {validated_path}; run `bindsight validate <run_dir>` first."
        )

    validated = pd.read_parquet(validated_path)
    candidates = (
        pd.read_parquet(candidates_path)
        if candidates_path.exists() and candidates_path.stat().st_size > 0
        else None
    )

    ranked = rank_validated(validated, candidates, weights=weights)
    out = run / "rank" / "ranking.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    ranked.to_parquet(out, index=False)
    LOG.info("wrote %s (%d rows)", out, len(ranked))
    return out

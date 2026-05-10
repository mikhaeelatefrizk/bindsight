"""Multi-objective ranking of validated binders.

Combines four orthogonal signals into a composite ``score``:

1. **Upstream evidence** — DE log2FC × specificity penalty (vital-tissue baseline).
2. **Structure quality** — iPTM, pAE_interaction, RMSD-to-designed.
3. **Affinity** — Boltz-2 ``affinity_pred_value`` and ``affinity_probability_binary``.
4. **Sequence quality** — ProteinMPNN sequence recovery vs. backbone (when available).

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
            cand = candidates[keep_cols].drop_duplicates("uniprot_id")
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
    df["score_evidence"] = (
        _minmax(df["log2fc"]) if "log2fc" in df.columns else pd.Series([float("nan")] * len(df))
    )
    df["score_structure"] = _structure_score(df)
    df["score_affinity"] = _affinity_score(df)
    df["score_sequence"] = (
        _minmax(df["sequence_recovery"])
        if "sequence_recovery" in df.columns
        else pd.Series([float("nan")] * len(df))
    )

    # Composite. Weights apply to non-NaN components only; missing metrics
    # don't penalise — they're just excluded from the weighted average.
    component_cols = [
        ("score_evidence", weights.log2fc_specificity),
        ("score_structure", weights.iptm),
        ("score_affinity", weights.affinity),
        ("score_sequence", weights.sequence_recovery),
    ]
    composite = pd.Series([0.0] * len(df), index=df.index)
    weight_sum = pd.Series([0.0] * len(df), index=df.index)
    for col, w in component_cols:
        if col in df.columns:
            mask = df[col].notna()
            composite = composite.add(df[col].fillna(0.0) * w, fill_value=0.0)
            weight_sum = weight_sum + (mask.astype(float) * w)
    df["score"] = composite / weight_sum.replace(0.0, pd.NA)

    # Sort + add rank
    df = df.sort_values("score", ascending=False, na_position="last").reset_index(drop=True)
    df["rank"] = range(1, len(df) + 1)

    return df


def _structure_score(df: pd.DataFrame) -> pd.Series:
    """Combined iPTM + (1 - normalised pAE) + (1 - normalised RMSD)."""
    parts: list[pd.Series] = []
    if "iptm" in df.columns:
        parts.append(_minmax(df["iptm"]))
    if "pae_interaction" in df.columns:
        parts.append(_minmax(df["pae_interaction"], invert=True))
    if "rmsd_to_designed" in df.columns:
        parts.append(_minmax(df["rmsd_to_designed"], invert=True))
    if not parts:
        return pd.Series([float("nan")] * len(df), index=df.index)
    stacked = pd.concat(parts, axis=1)
    return stacked.mean(axis=1, skipna=True)


def _affinity_score(df: pd.DataFrame) -> pd.Series:
    """Combined affinity_pred_value (higher = better) + binary binder probability."""
    parts: list[pd.Series] = []
    if "affinity_pred_value" in df.columns:
        parts.append(_minmax(df["affinity_pred_value"]))
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

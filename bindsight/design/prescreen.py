# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""ESM-2 pre-screen: cut the validation set before it reaches the GPU.

Structure-and-affinity validation is the expensive half of a design run —
Boltz-2 costs roughly 20 GPU-seconds per design against RFdiffusion+ProteinMPNN's
~45 for producing one. Validating fifty near-identical backbones is mostly
wasted compute.

This screen embeds each designed sequence with ESM-2 and keeps a
*representative* subset: designs closest to the embedding centroid, which are
the ones the model considers most typical of what the designer produced.
Outliers are dropped first, on the reasoning that a design far from the rest of
the batch in sequence space is more often a degenerate backbone than a
breakthrough.

Deliberate properties:

- **Opt-in.** ``top_k=None`` returns everything untouched, so default runs are
  bit-identical to before this module existed.
- **Degrading, never fatal.** ``torch``/``transformers`` live in the optional
  ``embed`` extra. Without them the screen logs and returns everything: a
  missing optional dependency must not lose a GPU run that already succeeded.
- **Deterministic.** Ties break on the input order, so the same batch always
  yields the same selection.
- **Auditable.** :func:`prescreen_report` describes exactly what was dropped,
  and that goes into provenance — silently discarding candidates would violate
  the project's own contract that failures are recorded, not swallowed.

Reuses :func:`bindsight.design.embeddings.esm2_embed`; this module adds only
the selection, not a second embedding implementation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class PrescreenResult:
    """Outcome of a pre-screen pass."""

    kept: list[int]
    dropped: list[int]
    applied: bool
    reason: str

    @property
    def n_kept(self) -> int:
        """Number of designs carried forward to validation."""
        return len(self.kept)

    @property
    def n_dropped(self) -> int:
        """Number of designs screened out before validation."""
        return len(self.dropped)


def _fallback(n: int, reason: str) -> PrescreenResult:
    """Keep everything, recording why the screen did not run."""
    if reason:
        LOG.warning("ESM-2 pre-screen skipped: %s; validating all %d designs", reason, n)
    return PrescreenResult(kept=list(range(n)), dropped=[], applied=False, reason=reason)


def select_representative(sequences: list[str], top_k: int | None) -> PrescreenResult:
    """Choose which designs to carry into validation.

    Args:
        sequences: Designed binder sequences, in design order.
        top_k: How many to keep. ``None`` or a value at least as large as the
            input keeps everything and skips the embedding entirely.

    Returns:
        A :class:`PrescreenResult` whose ``kept`` indices are in ascending
        design order, so downstream output ordering is unchanged.
    """
    n = len(sequences)
    if top_k is None:
        return _fallback(n, "")
    if top_k <= 0:
        return _fallback(n, f"top_k={top_k} is not positive")
    if n <= top_k:
        return _fallback(n, "")
    if any(not s for s in sequences):
        return _fallback(n, "one or more designs have an empty sequence")

    try:
        import numpy as np

        from bindsight.design.embeddings import esm2_embed
    except ImportError as e:  # pragma: no cover - exercised via the extra
        return _fallback(n, f"the 'embed' extra is not installed ({e})")

    try:
        emb = esm2_embed(sequences)
    except Exception as e:  # a screen must never lose an already-successful GPU run
        return _fallback(n, f"embedding failed ({e})")

    matrix = np.asarray(emb, dtype=float)
    if matrix.ndim != 2 or matrix.shape[0] != n:
        return _fallback(n, f"unexpected embedding shape {matrix.shape} for {n} designs")

    centroid = matrix.mean(axis=0)
    distances = np.linalg.norm(matrix - centroid, axis=1)
    # argsort is stable, so equal distances keep their original design order.
    order = np.argsort(distances, kind="stable")
    kept = sorted(int(i) for i in order[:top_k])
    dropped = sorted(int(i) for i in order[top_k:])

    LOG.info(
        "ESM-2 pre-screen: keeping %d of %d designs (dropped %d least-representative)",
        len(kept),
        n,
        len(dropped),
    )
    return PrescreenResult(
        kept=kept,
        dropped=dropped,
        applied=True,
        reason=f"kept the {top_k} designs closest to the ESM-2 embedding centroid",
    )


def prescreen_report(result: PrescreenResult, binder_ids: list[str]) -> str:
    """Render a one-line, provenance-ready summary of the screen.

    Args:
        result: The screen outcome.
        binder_ids: Binder identifiers in design order.

    Returns:
        A human-readable summary naming the dropped designs.
    """
    if not result.applied:
        return (
            f"ESM-2 pre-screen not applied ({result.reason or 'no top_k set'}); "
            f"all {len(binder_ids)} designs validated"
        )
    dropped = [binder_ids[i] for i in result.dropped if i < len(binder_ids)]
    shown = ", ".join(dropped[:10]) + (" …" if len(dropped) > 10 else "")
    return (
        f"ESM-2 pre-screen: validated {result.n_kept} of {len(binder_ids)} designs; "
        f"{result.reason}. Screened out: {shown or 'none'}"
    )

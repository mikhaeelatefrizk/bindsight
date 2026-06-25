"""Binder developability — sequence-level manufacturability / liability flags.

A high-ipTM design is useless if it won't express, aggregates, or is hard to
manufacture. This module scores a designed binder's *sequence* on well-established,
deterministic biophysical descriptors (no network, no GPU), so poor-developability
designs can be down-ranked before any wet-lab or GPU spend:

- **Instability index** (Guruprasad 1990) — > 40 predicts an unstable protein.
- **GRAVY** (Kyte-Doolittle grand average hydropathy) — higher ⇒ more hydrophobic
  ⇒ harder to express / more aggregation-prone.
- **Isoelectric point** & **aromaticity** — formulation / handling liabilities.
- **Aggregation-prone fraction** — fraction of the chain inside a hydrophobic
  (Kyte-Doolittle window) aggregation-prone region (APR), a standard first-order
  aggregation signal.
- **Free cysteines** — odd cysteine counts flag disulfide / oxidation liabilities.

All descriptors come from Biopython's ``ProtParam`` (the reference implementation) —
deterministic, offline, and exact. (T-cell–epitope / immunogenicity scoring, which
needs a licensed or heavy MHC predictor, is intentionally left for a follow-up so
this module ships only signals it can compute exactly here.)
"""

from __future__ import annotations

import logging
import math
from dataclasses import asdict, dataclass

LOG = logging.getLogger(__name__)

_STANDARD_AA = set("ACDEFGHIKLMNPQRSTVWY")


@dataclass(frozen=True)
class Developability:
    """Deterministic sequence-level developability descriptors for one binder."""

    length: int
    molecular_weight: float
    gravy: float
    instability_index: float
    isoelectric_point: float
    aromaticity: float
    n_cys: int
    aggregation_prone_fraction: float
    developability_score: float  # composite in [0, 1], higher = more developable

    @property
    def is_stable(self) -> bool:
        """ProtParam instability index < 40 ⇒ predicted stable."""
        return self.instability_index < 40.0

    def as_dict(self) -> dict:
        """Return the descriptors as a plain dict (for TSV/JSON export)."""
        return asdict(self)


def _aggregation_prone_fraction(seq: str, window: int = 7, threshold: float = 1.0) -> float:
    """Fraction of residues inside a hydrophobic (Kyte-Doolittle) APR window.

    Slides a ``window``-residue window; a window whose mean Kyte-Doolittle
    hydropathy exceeds ``threshold`` is aggregation-prone, and all its residues
    are marked. Returns marked / length (0.0 for sequences shorter than a window).
    """
    from Bio.SeqUtils.ProtParamData import kd  # Kyte-Doolittle scale

    n = len(seq)
    if n < window:
        return 0.0
    prone = [False] * n
    for i in range(n - window + 1):
        w = seq[i : i + window]
        if sum(kd.get(a, 0.0) for a in w) / window > threshold:
            for j in range(i, i + window):
                prone[j] = True
    return sum(prone) / n


def _composite(instability: float, gravy: float, aggregation_prone_fraction: float) -> float:
    """Combine stability, solubility and aggregation into a [0, 1] developability score."""
    # Stable below the 40 instability threshold, decaying above it.
    stability = 1.0 if instability < 40.0 else max(0.0, 1.0 - (instability - 40.0) / 40.0)
    # Solubility: sigmoid of -GRAVY (GRAVY 0 → 0.5, negative/hydrophilic → higher).
    solubility = 1.0 / (1.0 + math.exp(gravy))
    non_aggregating = 1.0 - aggregation_prone_fraction
    return (stability + solubility + non_aggregating) / 3.0


def developability(sequence: str) -> Developability | None:
    """Compute developability descriptors for a binder amino-acid sequence.

    Returns ``None`` for an empty sequence or one containing non-standard
    residues (ProtParam is only defined on the 20 standard amino acids).
    """
    if not sequence:
        return None
    seq = sequence.strip().upper()
    if not seq or any(a not in _STANDARD_AA for a in seq):
        return None
    try:
        from Bio.SeqUtils.ProtParam import ProteinAnalysis

        pa = ProteinAnalysis(seq)
        instability = float(pa.instability_index())
        gravy = float(pa.gravy())
        apr = _aggregation_prone_fraction(seq)
        return Developability(
            length=len(seq),
            molecular_weight=round(float(pa.molecular_weight()), 2),
            gravy=round(gravy, 4),
            instability_index=round(instability, 2),
            isoelectric_point=round(float(pa.isoelectric_point()), 2),
            aromaticity=round(float(pa.aromaticity()), 4),
            n_cys=seq.count("C"),
            aggregation_prone_fraction=round(apr, 4),
            developability_score=round(_composite(instability, gravy, apr), 4),
        )
    except Exception as e:  # malformed sequence ProtParam can't handle
        LOG.warning("developability failed for a %d-aa sequence: %s", len(seq), e)
        return None

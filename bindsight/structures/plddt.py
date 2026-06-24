"""Per-residue confidence (pLDDT) from AlphaFold models.

AlphaFold stores its per-residue confidence estimate (pLDDT, 0–100) in the
B-factor column of every atom. pLDDT doubles as a practical disorder signal:
regions below ~50 are very likely intrinsically disordered, and 50–70 is low
confidence. Designing a binder against a disordered or low-confidence region
wastes GPU time, so bindsight reads pLDDT straight from the cached AlphaFoldDB
mmCIF and uses it to flag/avoid those regions.

Pure parsing on top of Biopython's ``MMCIF2Dict`` — no network, no heavy
structure objects. All functions degrade gracefully (return ``None``/empty) on a
missing or unparseable file so discovery never crashes on a bad model.
"""

from __future__ import annotations

import logging
from pathlib import Path

LOG = logging.getLogger(__name__)


def _as_list(value: object) -> list[str]:
    """``MMCIF2Dict`` returns a scalar for single-row loops and a list otherwise."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    return [str(value)]


def per_residue_plddt(cif_path: Path | str | None) -> dict[int, float]:
    """Map residue number → pLDDT for an AlphaFold mmCIF.

    Uses the representative (Cα) atom's B-factor per residue. Returns an empty
    dict if the file is missing or cannot be parsed.
    """
    if not cif_path:
        return {}
    p = Path(cif_path)
    if not p.exists():
        return {}
    try:
        from Bio.PDB.MMCIF2Dict import MMCIF2Dict

        d = MMCIF2Dict(str(p))
    except Exception as e:  # malformed file, missing biopython, etc.
        LOG.warning("pLDDT parse failed for %s: %s", p, e)
        return {}

    atom_ids = _as_list(d.get("_atom_site.label_atom_id"))
    seq_ids = _as_list(d.get("_atom_site.label_seq_id"))
    bfactors = _as_list(d.get("_atom_site.B_iso_or_equiv"))
    if not (atom_ids and seq_ids and bfactors):
        return {}

    out: dict[int, float] = {}
    for atom, seq, bfac in zip(atom_ids, seq_ids, bfactors, strict=False):
        if atom != "CA":
            continue
        try:
            out[int(seq)] = float(bfac)
        except (ValueError, TypeError):
            continue
    return out


def mean_plddt(cif_path: Path | str | None) -> float | None:
    """Mean per-residue pLDDT over the whole model, or ``None`` if unavailable."""
    vals = per_residue_plddt(cif_path)
    if not vals:
        return None
    return sum(vals.values()) / len(vals)


def region_plddt(cif_path: Path | str | None, residues: list[int]) -> float | None:
    """Mean pLDDT over a specific set of residue numbers (e.g. an epitope).

    Falls back to the whole-model mean when ``residues`` is empty (the
    whole-surface design case). Returns ``None`` if no pLDDT is available.
    """
    vals = per_residue_plddt(cif_path)
    if not vals:
        return None
    if not residues:
        return sum(vals.values()) / len(vals)
    picked = [vals[r] for r in residues if r in vals]
    if not picked:
        return None
    return sum(picked) / len(picked)

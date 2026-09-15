#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Prepare the decoy receptor for the specificity control.

**Why this exists.** The scramble control asked whether the binder's *sequence*
matters, and answered no. It could not ask whether the *target* matters. A
design that scores as well against an unrelated receptor is not a binder for
either one, and nothing in this project had tested that.

**The decoy.** NECTIN4 (UniProt Q96NY8), Ig-like V-type domain, residues 32-144.
Chosen on four grounds, all checkable:

- **Unrelated.** An Ig V-set fold. ERBB2 domain IV is a cysteine-rich furin-like
  domain. They share no family, no fold and no ligand.
- **Size-matched.** 113 residues against domain IV's 142, so the complex a
  binder forms is comparable in size and the fold cost and VRAM ceiling do not
  change between the two arms.
- **Real and antibody-accessible.** The membrane-distal domain of a receptor
  that enfortumab vedotin targets clinically, not an invented sequence. A decoy
  that cannot be bound by anything would prove nothing.
- **In this project's own panel**, so the control doubles as a check on whether
  binders designed for one panel antigen spuriously score against another.

Boundaries come from UniProt's own annotation for Q96NY8, verified against the
REST API: signal 1-31, Ig-like V-type 32-144, Ig-like C2-type 148-237 and
248-331, transmembrane 350-370, extracellular 32-349.

Usage::

    python benchmarks/calibration/prepare_decoy_target.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

#: NECTIN4's Ig-like V-type domain, from UniProt's annotation.
UNIPROT = "Q96NY8"
SYMBOL = "NECTIN4"
IG_V_DOMAIN = (32, 144)


def main(argv: list[str] | None = None) -> int:
    """Fetch the decoy's AlphaFold model and write the domain slice. Returns an exit code."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lo", type=int, default=IG_V_DOMAIN[0])
    parser.add_argument("--hi", type=int, default=IG_V_DOMAIN[1])
    parser.add_argument(
        "--out",
        type=Path,
        default=REPO / "benchmarks" / "calibration" / "target" / f"{UNIPROT}_ig_v.pdb",
    )
    args = parser.parse_args(argv)

    from Bio.PDB import PDBIO, MMCIFParser, Select

    from bindsight.structures.alphafolddb import AlphaFoldDBClient

    cif = AlphaFoldDBClient().fetch(UNIPROT)
    if cif is None:
        print(f"could not fetch the AlphaFold model for {UNIPROT}", file=sys.stderr)
        return 1

    structure = MMCIFParser(QUIET=True).get_structure(UNIPROT, str(cif))

    # Biopython ships no type information, so ``Select`` is ``Any`` and mypy
    # cannot check the subclass. The ignore is narrow and the method below is
    # annotated, so the part that is ours stays checked.
    class Domain(Select):  # type: ignore[misc]
        def accept_residue(self, residue: Any) -> bool:
            return bool(args.lo <= residue.id[1] <= args.hi)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    io = PDBIO()
    io.set_structure(structure)
    io.save(str(args.out), Domain())

    kept = [r.id[1] for r in structure[0]["A"].get_residues() if args.lo <= r.id[1] <= args.hi]
    if not kept:
        print(f"no residues in {args.lo}-{args.hi} of {UNIPROT}", file=sys.stderr)
        return 1
    print(
        f"wrote {args.out} — {SYMBOL} Ig-like V-type domain residues "
        f"{min(kept)}-{max(kept)} ({len(kept)} residues) from AlphaFold {cif}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

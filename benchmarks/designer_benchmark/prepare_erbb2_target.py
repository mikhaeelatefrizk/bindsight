#!/usr/bin/env python3
"""Prepare the ERBB2 design target: extracellular domain IV (trastuzumab epitope).

The full ERBB2 (UniProt **P04626**) is 1255 residues. RFdiffusion holds the entire
target in the diffusion, so designing against the whole protein would not fit a free
16 GB GPU. We therefore design against **extracellular subdomain IV** (~residues
511–652) — the clinically validated epitope bound by trastuzumab (Herceptin) — which
is both the most therapeutically relevant ERBB2 surface and small enough to run on a
free Tesla P100.

This fetches the current AlphaFold model for P04626, slices chain A to the domain-IV
window, and writes ``data/target_structures/P04626.pdb`` (the file the designer
benchmark ships to the GPU). Re-runnable; the AlphaFold CIF is cached under
``data/alphafolddb_cache/`` via bindsight's own client.

    python benchmarks/designer_benchmark/prepare_erbb2_target.py
"""

from __future__ import annotations

import argparse
from pathlib import Path

# Domain IV (CR2/S2) of the ERBB2 extracellular region — the trastuzumab epitope.
DOMAIN_IV = (511, 652)
UNIPROT = "P04626"


def main() -> None:
    """Fetch ERBB2's AlphaFold model and write the domain-IV slice as the target."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lo", type=int, default=DOMAIN_IV[0])
    parser.add_argument("--hi", type=int, default=DOMAIN_IV[1])
    parser.add_argument(
        "--out", type=Path, default=Path("data/target_structures") / f"{UNIPROT}.pdb"
    )
    args = parser.parse_args()

    from Bio.PDB import PDBIO, MMCIFParser, Select

    from bindsight.structures.alphafolddb import AlphaFoldDBClient

    cif = AlphaFoldDBClient().fetch(UNIPROT)
    if cif is None:
        raise SystemExit(f"could not fetch AlphaFold model for {UNIPROT}")

    structure = MMCIFParser(QUIET=True).get_structure(UNIPROT, str(cif))

    class DomainIV(Select):
        def accept_residue(self, residue):
            return args.lo <= residue.id[1] <= args.hi

    args.out.parent.mkdir(parents=True, exist_ok=True)
    io = PDBIO()
    io.set_structure(structure)
    io.save(str(args.out), DomainIV())

    # Report what we wrote.
    kept = [r.id[1] for r in structure[0]["A"].get_residues() if args.lo <= r.id[1] <= args.hi]
    print(
        f"wrote {args.out} — ERBB2 domain IV residues {min(kept)}–{max(kept)} "
        f"({len(kept)} residues; trastuzumab epitope) from AlphaFold {cif}"
    )


if __name__ == "__main__":
    main()

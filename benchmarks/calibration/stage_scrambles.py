# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Build the scrambled-sequence control set for the ipTM calibration.

**Why this exists.** Every binder number this project publishes comes from
Boltz-2, and nothing establishes what those numbers mean. ``success@0.65`` is a
bare constant with no citation carrying the whole headline, and an ipTM of 0.88
has no scale attached: high relative to what?

The first control to run is the cheapest and the most on-distribution. Take the
twenty committed ERBB2 designs, shuffle each one's own sequence, and refold the
shuffles against the same target through the same validator on the same card. A
shuffle preserves length and amino-acid composition exactly and destroys only
the order — which is the entire content of the design. So:

- if the scrambles score like the designs, ipTM is reporting something about the
  target, or about folding a peptide of that composition, and not about the
  design at all;
- if they score clearly lower, the bar has a floor underneath it and the
  designs are saying something.

Either outcome is worth more than another design run. This is deliberately not
a comparison against a different target or a different job size: same target,
same trajectory count, same precision patch, same T4, so nothing but the residue
order differs.

The staged ``.pdb`` beside each FASTA is the parent design's **backbone** —
extracted from the committed Boltz-2 complex, backbone atoms only — carrying the
scramble's residue identities. Boltz-2 folds from the sequence and never reads
it; it is there because ``load_existing_designs`` requires a structure beside
every sequence. Side-chain atoms are dropped rather than kept, because keeping
them would leave a file whose side chains belong to a different sequence than
its backbone claims.

Usage::

    python benchmarks/calibration/stage_scrambles.py --out runs/calibration
"""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from bindsight.runners import tools  # noqa: E402

BENCH = REPO / "benchmarks" / "designer_benchmark"
BINDERS = BENCH / "binders"
NATIVE_TARGET = BENCH / "target" / "P04626_domain_IV.pdb"

#: Backbone atoms only. The scramble has a different sequence from the structure
#: it borrows coordinates from, so any side chain would describe the wrong
#: residue.
_BACKBONE_ATOMS = ("N", "CA", "C", "O")

#: Fixed so a published control is reproducible.
SEED = 20260912


def _binder_backbone_pdb(cif: Path, native: str) -> tuple[str, str]:
    """The binder chain of a committed complex, as a backbone-only PDB.

    Args:
        cif: a committed ``*_complex.cif``.
        native: the native target sequence, used to tell the chains apart by
            content rather than by letter.

    Returns:
        ``(pdb_text, binder_sequence)``.

    Raises:
        ValueError: If the complex does not hold exactly one non-target chain.
    """
    from Bio.PDB.MMCIF2Dict import MMCIF2Dict

    data = MMCIF2Dict(str(cif))
    chains = tools.chain_sequences_from_cif(cif)
    binder = [name for name, seq in chains.items() if seq != native]
    if len(binder) != 1:
        raise ValueError(f"{cif.name}: expected one binder chain, found {binder}")
    chain = binder[0]

    lines: list[str] = []
    serial = 0
    for asym, atom, comp, seq_id, x, y, z in zip(
        data["_atom_site.label_asym_id"],
        data["_atom_site.label_atom_id"],
        data["_atom_site.label_comp_id"],
        data["_atom_site.label_seq_id"],
        data["_atom_site.Cartn_x"],
        data["_atom_site.Cartn_y"],
        data["_atom_site.Cartn_z"],
        strict=True,
    ):
        if str(asym) != chain or str(atom) not in _BACKBONE_ATOMS:
            continue
        serial += 1
        lines.append(
            f"ATOM  {serial:>5d}  {atom!s:<3s}{comp!s:>4s} A{int(seq_id):>4d}    "
            f"{float(x):8.3f}{float(y):8.3f}{float(z):8.3f}  1.00  0.00           "
            f"{str(atom)[0]}"
        )
    if not lines:
        raise ValueError(f"{cif.name}: no backbone atoms for chain {chain}")
    return "\n".join(lines) + "\n", chains[chain]


def _scramble(sequence: str, rng: random.Random) -> str:
    """A composition-preserving shuffle that is not the original.

    Retried rather than accepted, because a shuffle that returns the input is
    not a control — it is the design under another name.
    """
    residues = list(sequence)
    for _ in range(64):
        rng.shuffle(residues)
        shuffled = "".join(residues)
        if shuffled != sequence:
            return shuffled
    raise ValueError("could not shuffle into a different sequence")


def main(argv: list[str] | None = None) -> int:
    """Stage the scrambled control set. Returns a process exit code."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=REPO / "runs" / "calibration")
    args = parser.parse_args(argv)

    if not NATIVE_TARGET.is_file():
        print(f"missing the native target: {NATIVE_TARGET}", file=sys.stderr)
        return 1
    native = tools.chain_sequence_from_pdb(NATIVE_TARGET, "A")

    staged = Path(args.out) / "design"
    staged.mkdir(parents=True, exist_ok=True)
    rng = random.Random(SEED)

    complexes = sorted(BINDERS.glob("*_complex.cif"))
    if not complexes:
        print(f"no committed complexes under {BINDERS}", file=sys.stderr)
        return 1

    written = 0
    for cif in complexes:
        parent = cif.name.replace("_complex.cif", "")
        backbone_text, designed = _binder_backbone_pdb(cif, native)

        scratch = staged / f"{parent}_backbone.tmp.pdb"
        scratch.write_text(backbone_text, encoding="utf-8")

        scrambled = _scramble(designed, rng)
        binder_id = f"{parent}_scram"
        tools.write_designed_backbone(
            scratch, staged / f"{binder_id}.pdb", chain="A", sequence=scrambled
        )
        scratch.unlink()
        (staged / f"{binder_id}.fasta").write_text(f">{binder_id}\n{scrambled}\n", encoding="utf-8")
        written += 1

    print(f"staged {written} scrambled control(s) in {staged}")
    print(f"target: {NATIVE_TARGET.name} ({len(native)} residues)")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

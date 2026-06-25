#!/usr/bin/env python3
"""Annotate the designed binders with sequence-level developability (real, offline).

Reads every ``binders/*.fasta`` and writes ``binders/developability.tsv`` with
Biopython ProtParam descriptors (instability index, GRAVY, pI, aromaticity, free
cysteines), an aggregation-prone fraction, and a composite developability score.
Fully deterministic — no GPU, no network — so it can be re-run on any design set.

    python benchmarks/designer_benchmark/score_developability.py \
        --binders benchmarks/designer_benchmark/binders
"""

from __future__ import annotations

import argparse
from pathlib import Path

from bindsight.design.developability import developability

_COLS = [
    "binder_id",
    "length",
    "molecular_weight",
    "gravy",
    "instability_index",
    "isoelectric_point",
    "aromaticity",
    "n_cys",
    "aggregation_prone_fraction",
    "developability_score",
]


def _read_fasta_seq(path: Path) -> str:
    return "".join(
        ln.strip() for ln in path.read_text(encoding="utf-8").splitlines() if not ln.startswith(">")
    )


def main() -> None:
    """Write binders/developability.tsv with real ProtParam descriptors per binder."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--binders", type=Path, default=Path("benchmarks/designer_benchmark/binders"))
    args = ap.parse_args()

    rows: list[list[str]] = []
    for fa in sorted(args.binders.glob("*.fasta")):
        d = developability(_read_fasta_seq(fa))
        if d is None:
            continue
        dd = d.as_dict()
        rows.append([fa.stem] + [str(dd[c]) for c in _COLS[1:]])

    out = args.binders / "developability.tsv"
    out.write_text("\t".join(_COLS) + "\n" + "\n".join("\t".join(r) for r in rows) + "\n")

    scores = [float(r[_COLS.index("developability_score")]) for r in rows]
    stable = sum(1 for r in rows if float(r[_COLS.index("instability_index")]) < 40.0)
    print(f"wrote {out} ({len(rows)} binders)")
    if scores:
        print(
            f"mean developability_score={sum(scores) / len(scores):.3f} | "
            f"stable (instability<40): {stable}/{len(rows)}"
        )


if __name__ == "__main__":
    main()

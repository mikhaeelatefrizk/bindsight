#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pre-GPU sequence-space visualizer: ESM-2 embed the designed binders, PCA to 2-D.

Produces a ProtSpace-style view of the binder set *before* any GPU spend:
``binders/embedding_coords.tsv`` (per-binder PC1/PC2) and
``binders/embedding_space.png``. Real ESM-2 inference — needs ``bindsight[embed]``.

    pip install 'bindsight[embed]'
    python benchmarks/designer_benchmark/embed_binders.py
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

from bindsight.design.embeddings import esm2_embed, pca_2d, render_embedding_png


def _read_fasta_seq(path: Path) -> str:
    return "".join(
        ln.strip() for ln in path.read_text(encoding="utf-8").splitlines() if not ln.startswith(">")
    )


def main() -> None:
    """Embed binders/*.fasta with ESM-2, project to 2-D, write coords TSV + PNG."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--binders", type=Path, default=Path("benchmarks/designer_benchmark/binders"))
    ap.add_argument(
        "--save-embeddings", type=Path, default=None, help="optional .npy of raw embeddings"
    )
    args = ap.parse_args()

    fastas = sorted(args.binders.glob("*.fasta"))
    labels = [f.stem for f in fastas]
    seqs = [_read_fasta_seq(f) for f in fastas]

    emb = esm2_embed(seqs)
    coords = pca_2d(emb)

    out = args.binders / "embedding_coords.tsv"
    with out.open("w", encoding="utf-8") as f:
        f.write("binder_id\tpc1\tpc2\n")
        for lab, (x, y) in zip(labels, coords, strict=True):
            f.write(f"{lab}\t{x:.4f}\t{y:.4f}\n")
    render_embedding_png(coords, labels, args.binders / "embedding_space.png")
    if args.save_embeddings is not None:
        args.save_embeddings.parent.mkdir(parents=True, exist_ok=True)
        np.save(args.save_embeddings, emb)

    print(f"embedded {len(seqs)} binders (ESM-2 dim {emb.shape[1]}) -> {out}")


if __name__ == "__main__":
    main()

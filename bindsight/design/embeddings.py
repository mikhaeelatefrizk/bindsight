# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Protein-language-model embeddings + a pre-GPU sequence-space visualizer.

Before spending GPU on structure prediction / validation, it's useful to *see*
the sequence space of your designed binders (or candidate targets): which designs
cluster, which are outliers, how diverse the set is. This is the ProtSpace idea —
project protein-language-model (pLM) embeddings to 2-D.

**pLM choice — ESM-2 (`facebook/esm2_t6_8M_UR50D`, 8 M params).** ESM-2 is the
de-facto open protein LM; the 8 M (t6) checkpoint runs on a CPU in seconds, needs
no GPU, and its mean-pooled residue embedding is a strong, standard per-protein
representation. Larger ESM-2 checkpoints (35 M…3 B) or ProtT5 can be dropped in via
``model_name`` when accuracy matters more than speed.

Embedding (ESM-2) needs the optional ``embed`` extra (torch + transformers):
``pip install 'bindsight[embed]'``. The 2-D projection (PCA) is pure NumPy and
always available, so the visualizer works on any precomputed embedding matrix.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

LOG = logging.getLogger(__name__)

DEFAULT_PLM = "facebook/esm2_t6_8M_UR50D"

_INSTALL_HINT = (
    "ESM-2 embeddings need the optional 'embed' extra: pip install 'bindsight[embed]' "
    "(installs torch + transformers)."
)


def esm2_embed(
    sequences: list[str],
    *,
    model_name: str = DEFAULT_PLM,
    batch_size: int = 8,
) -> np.ndarray:
    """Mean-pooled ESM-2 embeddings for ``sequences`` → array of shape (N, D).

    Real protein-LM inference (no placeholder). Pools over residue token states,
    excluding the special BOS/EOS and padding tokens. Raises ``ImportError`` (with
    an install hint) if the ``embed`` extra isn't installed.
    """
    if not sequences:
        return np.zeros((0, 0), dtype=np.float32)
    try:
        import torch
        from transformers import AutoModel, AutoTokenizer
    except ImportError as e:  # optional extra not installed
        raise ImportError(_INSTALL_HINT) from e

    tok = AutoTokenizer.from_pretrained(model_name)
    model = AutoModel.from_pretrained(model_name)
    model.eval()

    vecs: list[np.ndarray] = []
    with torch.no_grad():
        for i in range(0, len(sequences), batch_size):
            batch = sequences[i : i + batch_size]
            enc = tok(
                batch,
                return_tensors="pt",
                padding=True,
                return_special_tokens_mask=True,
            )
            special = enc.pop("special_tokens_mask")
            hidden = model(**enc).last_hidden_state  # (B, L, D)
            # Real residues only: attended to, and not a special token.
            keep = (enc["attention_mask"] * (1 - special)).cpu().numpy()
            vecs.append(mean_pool_residues(hidden.cpu().numpy(), keep))
    return np.vstack(vecs)


def mean_pool_residues(hidden: np.ndarray, keep: np.ndarray) -> np.ndarray:
    """Mean of ``hidden`` over the positions ``keep`` marks, per sequence.

    Split out of :func:`esm2_embed` so it can be tested. It is arithmetic --
    no model, no tokenizer, no ``torch`` -- and it is the step that decides the
    numbers: a padding token or a BOS/EOS marker left in the average shifts
    every embedding, and the prescreen built on those embeddings decides which
    designs reach validation. Inside ``esm2_embed`` it was reachable only with
    the ``embed`` extra installed, which no CI job does, so the one test that
    exercised it skipped on every platform.

    Args:
        hidden: ``(B, L, D)`` final hidden states.
        keep: ``(B, L)`` of 1 for a real residue and 0 for padding or a special
            token.

    Returns:
        ``(B, D)`` float32. A sequence with no kept position averages over a
        count of 1 rather than dividing by zero, giving a zero vector.
    """
    weights = keep[..., None].astype(hidden.dtype)
    summed = (hidden * weights).sum(axis=1)
    counts = weights.sum(axis=1).clip(min=1.0)
    pooled: np.ndarray = (summed / counts).astype(np.float32)
    return pooled


def pca_2d(embeddings: np.ndarray) -> np.ndarray:
    """Project an (N, D) embedding matrix to (N, 2) principal coordinates.

    Pure NumPy (centred SVD) so it needs no scikit-learn/UMAP and runs anywhere.
    Returns zeros for fewer than 2 rows. An embedding with a single feature has
    only one principal axis; the second coordinate is then zero, and the shape
    is still (N, 2) because every caller relies on it.
    """
    x = np.asarray(embeddings, dtype=float)
    if x.ndim != 2 or x.shape[0] < 2:
        return np.zeros((x.shape[0] if x.ndim == 2 else 0, 2), dtype=float)
    xc = x - x.mean(axis=0, keepdims=True)
    _u, _s, vt = np.linalg.svd(xc, full_matrices=False)
    coords = np.asarray(xc @ vt[:2].T, dtype=float)  # principal coordinates
    if coords.shape[1] < 2:
        # A one-dimensional embedding has one principal axis, so `vt[:2]` is a
        # single row and this returned (N, 1) while promising (N, 2) -- which
        # `render_embedding_png` then unpacks as x and y. The second axis is not
        # missing, it is zero: there is no variance left to put on it. Say that
        # rather than hand back a shape the signature rules out.
        coords = np.concatenate(
            [coords, np.zeros((coords.shape[0], 2 - coords.shape[1]), dtype=float)], axis=1
        )
    return coords


def render_embedding_png(
    coords: np.ndarray,
    labels: list[str],
    out_path: str | Path,
    *,
    title: str = "Binder sequence space (ESM-2 → PCA)",
) -> bool:
    """Render a 2-D scatter of ``coords`` labelled by ``labels`` to a PNG.

    Returns False (no-op) if matplotlib isn't installed. Used to produce the
    committed ProtSpace-style visualization of the designed binders.
    """
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return False

    fig, ax = plt.subplots(figsize=(7, 6), dpi=120)
    ax.scatter(coords[:, 0], coords[:, 1], s=40, alpha=0.8, c="#1f77b4")
    for (x, y), lab in zip(coords, labels, strict=False):
        ax.annotate(
            str(lab), (x, y), fontsize=7, alpha=0.75, xytext=(3, 3), textcoords="offset points"
        )
    ax.set_xlabel("PC1")
    ax.set_ylabel("PC2")
    ax.set_title(title)
    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)
    return True

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
            # Pool over real residues only (attention=1 and not a special token).
            keep = (enc["attention_mask"] * (1 - special)).unsqueeze(-1).to(hidden.dtype)
            summed = (hidden * keep).sum(dim=1)
            counts = keep.sum(dim=1).clamp(min=1.0)
            vecs.append((summed / counts).cpu().numpy().astype(np.float32))
    return np.vstack(vecs)


def pca_2d(embeddings: np.ndarray) -> np.ndarray:
    """Project an (N, D) embedding matrix to (N, 2) principal coordinates.

    Pure NumPy (centred SVD) so it needs no scikit-learn/UMAP and runs anywhere.
    Returns zeros for fewer than 2 rows.
    """
    x = np.asarray(embeddings, dtype=float)
    if x.ndim != 2 or x.shape[0] < 2:
        return np.zeros((x.shape[0] if x.ndim == 2 else 0, 2), dtype=float)
    xc = x - x.mean(axis=0, keepdims=True)
    _u, _s, vt = np.linalg.svd(xc, full_matrices=False)
    coords = xc @ vt[:2].T  # principal coordinates (N, 2)
    return np.asarray(coords, dtype=float)


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

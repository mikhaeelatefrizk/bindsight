"""Tests for pLM embeddings + the PCA sequence-space visualizer.

The PCA projection and PNG rendering run in CI on a *real* committed ESM-2
embedding matrix (no torch needed). The actual ESM-2 inference test runs only
where the optional ``embed`` extra is installed (skipped otherwise).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from bindsight.design.embeddings import pca_2d, render_embedding_png

# Real ESM-2 (esm2_t6_8M) embeddings of the 20 committed ERBB2 binders.
_EMB_FIX = Path(__file__).parent / "fixtures" / "embeddings" / "binders_esm2_t6.npy"


def test_real_embedding_fixture_shape() -> None:
    emb = np.load(_EMB_FIX)
    assert emb.shape == (20, 320)  # 20 binders × ESM-2 t6 hidden dim


def test_pca_2d_on_real_embeddings() -> None:
    coords = pca_2d(np.load(_EMB_FIX))
    assert coords.shape == (20, 2)
    # PC1 captures at least as much spread as PC2.
    assert coords[:, 0].var() >= coords[:, 1].var()


def test_pca_2d_separates_two_clusters() -> None:
    rng = np.random.default_rng(0)
    c1 = rng.normal(0.0, 0.1, (8, 16))
    c2 = rng.normal(5.0, 0.1, (8, 16))
    coords = pca_2d(np.vstack([c1, c2]))
    # The two well-separated clusters split along PC1.
    assert abs(coords[:8, 0].mean() - coords[8:, 0].mean()) > 1.0


def test_pca_2d_handles_degenerate_input() -> None:
    assert pca_2d(np.zeros((1, 5))).shape == (1, 2)
    assert pca_2d(np.zeros((0, 5))).shape == (0, 2)


def test_render_embedding_png(tmp_path: Path) -> None:
    coords = pca_2d(np.load(_EMB_FIX))
    out = tmp_path / "space.png"
    assert render_embedding_png(coords, [f"b{i}" for i in range(20)], out) is True
    assert out.exists()
    assert out.stat().st_size > 1000


def test_esm2_embed_real_inference() -> None:
    """Real ESM-2 inference — runs only where the 'embed' extra is installed."""
    pytest.importorskip("torch")
    pytest.importorskip("transformers")
    from bindsight.design.embeddings import esm2_embed

    emb = esm2_embed(["MKTAYIAKQRQISFVK", "GGGGGGGGGGGG"])
    assert emb.shape == (2, 320)
    assert np.isfinite(emb).all()

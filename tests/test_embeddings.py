# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
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


class TestTheResiduePoolingIsArithmeticAnyoneCanCheck:
    """`esm2_embed` decides which designs reach validation, and nothing tested it.

    Its only test needs `torch` and `transformers` — the `embed` extra, which no
    CI job installs — so it skipped on every platform, and a model download on
    top of that. What actually decides the numbers is one step: the mean over
    real residues, excluding padding and the special BOS/EOS markers. A padding
    token left in that average shifts every embedding, and the prescreen built
    on those embeddings chooses what gets folded.

    That step is now `mean_pool_residues`, which needs no model, and these run
    everywhere.
    """

    @staticmethod
    def _pool(hidden, keep):
        from bindsight.design.embeddings import mean_pool_residues

        return mean_pool_residues(np.asarray(hidden, dtype=np.float32), np.asarray(keep))

    def test_a_padding_position_does_not_enter_the_average(self) -> None:
        """The defect this exists to catch, stated as a number.

        Two real residues at 1.0 and 3.0 average to 2.0. Include a padded 100.0
        and it becomes 34.67 — and nothing downstream would look wrong.
        """
        hidden = [[[1.0], [3.0], [100.0]]]
        assert self._pool(hidden, [[1, 1, 0]])[0][0] == pytest.approx(2.0)

    def test_a_special_token_does_not_enter_the_average(self) -> None:
        """BOS/EOS carry no residue; averaging them in is the same error."""
        hidden = [[[50.0], [2.0], [4.0], [50.0]]]
        assert self._pool(hidden, [[0, 1, 1, 0]])[0][0] == pytest.approx(3.0)

    def test_every_position_kept_is_a_plain_mean(self) -> None:
        """Guards the guard: the masking must not distort the ordinary case."""
        assert self._pool([[[2.0], [4.0], [6.0]]], [[1, 1, 1]])[0][0] == pytest.approx(4.0)

    def test_sequences_in_a_batch_do_not_bleed_into_each_other(self) -> None:
        """Padding makes batch rows different lengths; each keeps its own mean."""
        hidden = [[[1.0], [3.0], [0.0]], [[10.0], [0.0], [0.0]]]
        out = self._pool(hidden, [[1, 1, 0], [1, 0, 0]])

        assert out[0][0] == pytest.approx(2.0)
        assert out[1][0] == pytest.approx(10.0)

    def test_a_sequence_with_nothing_kept_is_zero_not_a_division_error(self) -> None:
        """An all-special row must not raise, and must not invent a value."""
        out = self._pool([[[7.0], [9.0]]], [[0, 0]])

        assert out.shape == (1, 1)
        assert out[0][0] == pytest.approx(0.0)

    def test_the_shape_and_dtype_are_what_the_caller_stacks(self) -> None:
        """`esm2_embed` vstacks these; a wrong rank or dtype breaks the join."""
        out = self._pool([[[1.0, 2.0], [3.0, 4.0]]], [[1, 1]])

        assert out.shape == (1, 2)
        assert out.dtype == np.float32
        assert out[0] == pytest.approx([2.0, 3.0])

    def test_each_dimension_is_pooled_independently(self) -> None:
        """A bug that pooled across D instead of L would pass every test above
        that uses a single dimension."""
        hidden = [[[1.0, 10.0], [3.0, 30.0], [99.0, 99.0]]]
        out = self._pool(hidden, [[1, 1, 0]])

        assert out[0] == pytest.approx([2.0, 20.0])

# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the Boltz-2 output retention fix in the job executor.

job_exec imports no GPU libraries at module load, so these run anywhere — they
exercise structure/PAE retention with a synthetic Boltz-2 output layout.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from bindsight.runners.job_exec import _boltz_pae_interaction, _stage_validate_outputs


def _make_boltz_out(out_dir: Path) -> None:
    """Synthetic Boltz-2 output: predicted complex + confidence + PAE."""
    pred = out_dir / "boltz_results_b0" / "predictions" / "b0"
    pred.mkdir(parents=True)
    (pred / "b0_model_0.cif").write_text("data_b0\n# predicted complex\n")
    (pred / "confidence_b0_model_0.json").write_text('{"iptm": 0.7}')
    # 4-residue PAE (target_len=2, binder_len=2): intra blocks 0, inter blocks 5.
    pae = np.zeros((4, 4), dtype=float)
    pae[:2, 2:] = 5.0
    pae[2:, :2] = 5.0
    np.savez(pred / "pae_b0_model_0.npz", pae=pae)


def test_stage_validate_outputs_retains_structure_and_pae(tmp_path: Path) -> None:
    src = tmp_path / "boltz_out" / "b0"
    src.mkdir(parents=True)
    _make_boltz_out(src)
    dst = tmp_path / "validate" / "b0"
    _stage_validate_outputs(src, dst)

    staged = {p.name for p in dst.iterdir()}
    assert "b0_model_0.cif" in staged  # the real predicted complex is retained
    assert "confidence_b0_model_0.json" in staged
    assert "pae_b0_model_0.npz" in staged


def test_boltz_pae_interaction_is_mean_interchain(tmp_path: Path) -> None:
    out = tmp_path / "b0"
    out.mkdir()
    _make_boltz_out(out)
    pae_i = _boltz_pae_interaction(out, target_len=2, binder_len=2)
    assert pae_i == 5.0  # mean of the off-diagonal (inter-chain) blocks


def test_boltz_pae_interaction_none_when_shape_mismatch(tmp_path: Path) -> None:
    out = tmp_path / "b0"
    out.mkdir()
    _make_boltz_out(out)
    # Wrong chain lengths (matrix is 4x4, not 3+3) -> None, not a wrong number.
    assert _boltz_pae_interaction(out, target_len=3, binder_len=3) is None


def test_boltz_pae_interaction_none_when_absent(tmp_path: Path) -> None:
    assert _boltz_pae_interaction(tmp_path, target_len=2, binder_len=2) is None

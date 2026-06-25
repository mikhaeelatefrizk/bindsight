# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for binder developability scoring (ProtParam, deterministic)."""

from __future__ import annotations

import pandas as pd
import pytest

from bindsight.design.developability import developability
from bindsight.rank.scoring import rank_validated

# A real ProteinMPNN design from the committed ERBB2 benchmark (binder_0_seq0).
_REAL_BINDER = (
    "MTKATLTVKSREAVVKMVELIKEKYPDFKVEVTTSSGKVIGGDVEKIKASKDKNFTVTVTAEGMSVEELLLAILEIREEIKGETSSIVAETIE"
)


def test_developability_on_real_binder_is_exact() -> None:
    d = developability(_REAL_BINDER)
    assert d is not None
    assert d.length == 93
    assert d.molecular_weight == pytest.approx(10189.72, rel=1e-4)
    assert d.instability_index == pytest.approx(26.48, abs=0.01)
    assert d.gravy == pytest.approx(-0.0538, abs=1e-3)
    assert d.n_cys == 0
    assert d.is_stable is True  # instability < 40
    assert 0.0 <= d.developability_score <= 1.0


def test_hydrophobic_sequence_scores_worse_than_hydrophilic() -> None:
    hydrophobic = developability("FFFFFWWWWWLLLLLIIIIIVVVVV")
    hydrophilic = developability("EKEKEKEKEKDKDKDKDKDKSTSTST")
    assert hydrophobic is not None
    assert hydrophilic is not None
    # The hydrophobic chain is more aggregation-prone and less soluble.
    assert hydrophobic.aggregation_prone_fraction > hydrophilic.aggregation_prone_fraction
    assert hydrophobic.developability_score < hydrophilic.developability_score


def test_invalid_sequences_return_none() -> None:
    assert developability("") is None
    assert developability("MKTB1Z") is None  # non-standard residues / digits


def test_rank_uses_developability_when_sequence_present() -> None:
    validated = pd.DataFrame(
        {
            "binder_id": ["a", "b"],
            "target_uniprot": ["P04626", "P04626"],
            "iptm": [0.8, 0.4],
            "sequence": [_REAL_BINDER, "FFFFFWWWWWLLLLLIIIIIVVVVV"],
        }
    )
    ranked = rank_validated(validated)
    assert "developability_score" in ranked.columns
    assert "score_developability" in ranked.columns
    assert ranked["score_developability"].notna().all()
    # The well-behaved real binder out-scores the hydrophobic one on developability.
    by_id = dict(zip(ranked["binder_id"], ranked["score_developability"], strict=True))
    assert by_id["a"] > by_id["b"]


def test_rank_without_sequence_is_graceful() -> None:
    validated = pd.DataFrame({"binder_id": ["a"], "target_uniprot": ["P04626"], "iptm": [0.8]})
    ranked = rank_validated(validated)
    assert "score_developability" in ranked.columns
    assert ranked["score_developability"].isna().all()  # no sequence -> excluded from composite
    assert ranked["score"].notna().all()  # composite still computed from present components

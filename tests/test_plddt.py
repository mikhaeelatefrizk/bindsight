# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for AlphaFold pLDDT parsing (disorder signal)."""

from __future__ import annotations

from pathlib import Path

import pytest

from bindsight.structures.plddt import mean_plddt, per_residue_plddt, region_plddt

FIX = Path(__file__).parent / "fixtures" / "plddt" / "AF-TEST1-F1-model_v6.cif"


def test_per_residue_plddt_reads_ca_bfactors() -> None:
    # CA atoms only, keyed by residue number; B-factor column = pLDDT.
    assert per_residue_plddt(FIX) == {1: 90.0, 2: 80.0, 3: 30.0, 4: 20.0}


def test_mean_plddt() -> None:
    assert mean_plddt(FIX) == pytest.approx((90 + 80 + 30 + 20) / 4)  # 55.0


def test_region_plddt_subset() -> None:
    assert region_plddt(FIX, [1, 2]) == pytest.approx(85.0)  # well-folded region
    assert region_plddt(FIX, [3, 4]) == pytest.approx(25.0)  # disordered region


def test_region_plddt_empty_falls_back_to_whole_model() -> None:
    assert region_plddt(FIX, []) == pytest.approx(mean_plddt(FIX))


def test_region_plddt_unknown_residues_is_none() -> None:
    assert region_plddt(FIX, [999]) is None


def test_graceful_on_missing_or_none() -> None:
    assert per_residue_plddt(None) == {}
    assert per_residue_plddt(Path("/no/such/file.cif")) == {}
    assert mean_plddt(None) is None
    assert region_plddt(None, [1]) is None

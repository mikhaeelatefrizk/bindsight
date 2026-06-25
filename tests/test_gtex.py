# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for GTEx normal-tissue expression (on-target/off-tumor safety).

Uses a small fixture GCT whose values are the real GTEx v8 medians for a handful
of genes (ERBB2, ALB, TNNT2, ACTB, MAGEA4, CTAG1B) across six tissues.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from bindsight.targets.gtex import GTExTissueExpression, normalize_tissue

FIX = Path(__file__).parent / "fixtures" / "gtex" / "gtex_median_subset.gct"
VITAL = ["heart_left_ventricle", "brain_cortex", "liver", "lung"]


def _client() -> GTExTissueExpression:
    return GTExTissueExpression(gct_path=FIX)


def test_normalize_tissue() -> None:
    assert normalize_tissue("Heart - Left Ventricle") == "heart_left_ventricle"
    assert normalize_tissue("Brain - Cortex") == "brain_cortex"
    assert normalize_tissue("Liver") == "liver"


def test_max_expression_real_values() -> None:
    c = _client()
    # ALB is liver-specific (~25201 TPM) — far above any vital-tissue threshold.
    assert c.max_expression("ENSG00000163631", VITAL) == pytest.approx(25201.3, rel=1e-3)
    # ERBB2 is expressed in normal lung/heart (~47.8) — the trastuzumab tox concern.
    assert c.max_expression("ENSG00000141736", VITAL) == pytest.approx(47.7796, rel=1e-3)


def test_cancer_testis_antigens_are_safe_in_vital_tissues() -> None:
    c = _client()
    # MAGEA4 / NY-ESO-1 are 0 in vital tissues (ideal tumour-selective targets).
    assert c.max_expression("ENSG00000147381", VITAL) == pytest.approx(0.0)
    assert c.max_expression("ENSG00000184033", VITAL) == pytest.approx(0.0)


def test_version_suffix_is_stripped() -> None:
    c = _client()
    assert c.max_expression("ENSG00000163631.16", VITAL) == c.max_expression(
        "ENSG00000163631", VITAL
    )


def test_unknown_gene_or_tissue_is_none() -> None:
    c = _client()
    assert c.max_expression("ENSG99999999999", VITAL) is None  # not in GTEx
    assert c.max_expression("ENSG00000163631", ["nonexistent_tissue"]) is None
    assert c.max_expression("", VITAL) is None

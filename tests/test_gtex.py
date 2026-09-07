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


# ---------------------------------------------------------------------------
# The gate itself. `assess` decides whether a candidate cleared normal-tissue
# safety, and until now only `max_expression` was tested — so the three-way
# verdict this gate exists to make had nothing holding it in place. Reporting an
# unmeasured gene as "safe" passed the entire suite.
# ---------------------------------------------------------------------------
_UNMEASURED = "ENSG99999999999"
_ALB = "ENSG00000163631"  # liver-specific, ~25201 TPM
_MAGEA4 = "ENSG00000147381"  # cancer-testis, 0 in vital tissues


class TestTheGateFailsClosed:
    """An answer we do not have is not an answer of "safe"."""

    def test_a_gene_absent_from_gtex_is_unassessed_never_safe(self) -> None:
        """The whole point of the gate: silence must not read as clearance."""
        v = _client().assess(_UNMEASURED, VITAL, max_tpm=5.0)
        assert v.status == "unassessed"
        assert v.status != "safe", "an unmeasured gene must never clear the gate"
        assert v.max_tpm is None
        assert "no GTEx median-TPM entry" in v.reason

    def test_an_empty_gene_id_is_unassessed(self) -> None:
        v = _client().assess("", VITAL, max_tpm=5.0)
        assert v.status == "unassessed"
        assert v.max_tpm is None

    def test_tissues_that_are_not_in_the_reference_are_unassessed(self) -> None:
        """A gene measured elsewhere is still unmeasured *here*."""
        v = _client().assess(_ALB, ["nonexistent_tissue"], max_tpm=5.0)
        assert v.status == "unassessed"

    def test_a_gene_over_the_ceiling_is_unsafe_and_says_by_how_much(self) -> None:
        v = _client().assess(_ALB, VITAL, max_tpm=5.0)
        assert v.status == "unsafe"
        assert v.max_tpm == pytest.approx(25201.3, rel=1e-3)
        assert "exceeds" in v.reason

    def test_only_a_measured_value_may_be_reported_safe(self) -> None:
        v = _client().assess(_MAGEA4, VITAL, max_tpm=5.0)
        assert v.status == "safe"
        assert v.max_tpm is not None, "a safe verdict must carry the measurement it rests on"
        assert v.max_tpm <= 5.0

    def test_the_ceiling_is_inclusive_at_its_boundary(self) -> None:
        """A gene exactly at the ceiling is at or below it, per the stated reason."""
        c = _client()
        exact = c.max_expression(_MAGEA4, VITAL)
        assert exact is not None
        assert c.assess(_MAGEA4, VITAL, max_tpm=exact).status == "safe"

    def test_every_status_is_one_of_the_three_declared_verdicts(self) -> None:
        """A fourth state would slip past every consumer's branch."""
        c = _client()
        seen = {
            c.assess(_UNMEASURED, VITAL, 5.0).status,
            c.assess(_ALB, VITAL, 5.0).status,
            c.assess(_MAGEA4, VITAL, 5.0).status,
        }
        assert seen == {"unassessed", "unsafe", "safe"}

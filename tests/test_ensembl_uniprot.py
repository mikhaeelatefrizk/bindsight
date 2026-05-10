"""Tests for the bundled Ensembl gene ID → UniProt fallback map."""

from __future__ import annotations

from bindsight.targets.ensembl_uniprot import is_known, lookup


def test_known_oncoprotein_lookups() -> None:
    """The bundled map covers the well-known surface antigens used by the demo."""
    assert lookup("ENSG00000141736") == ("ERBB2", "P04626")  # HER2
    assert lookup("ENSG00000146648") == ("EGFR", "P00533")
    assert is_known("ENSG00000141736")
    assert is_known("ENSG00000146648")


def test_unknown_gene_returns_none_pair() -> None:
    assert lookup("ENSG_DOES_NOT_EXIST") == (None, None)
    assert not is_known("ENSG_DOES_NOT_EXIST")


def test_returns_tuple_of_strings() -> None:
    sym, uni = lookup("ENSG00000091831")
    assert isinstance(sym, str)
    assert isinstance(uni, str)
    assert uni.startswith("P") or uni.startswith("Q") or uni.startswith("O")

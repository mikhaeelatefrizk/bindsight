"""Bundled Ensembl gene ID → UniProt accession map for offline / demo runs.

Used as a fallback when ``use_open_targets`` is disabled (e.g. the demo) or
when Open Targets is unreachable. The full pipeline always prefers Open
Targets' authoritative mapping; this is a small curated set of well-known
human surface antigens + driver oncoproteins kept in sync with the bundled
``examples/demo`` and the SURFY offline fallback.

Source: UniProt Swiss-Prot canonical IDs as of 2026-05.
"""

from __future__ import annotations

# (gene_id, symbol, uniprot_id)
_BUNDLED: dict[str, tuple[str, str]] = {
    # ---- Surface antigens (also in the SURFY offline fallback) ----
    "ENSG00000141736": ("ERBB2", "P04626"),  # HER2
    "ENSG00000146648": ("EGFR", "P00533"),
    "ENSG00000111799": ("CLDN6", "Q14953"),  # mismatched in older annotations; use canonical
    "ENSG00000133110": ("MSLN", "Q13421"),
    "ENSG00000178562": ("CD28", "P10747"),
    "ENSG00000163599": ("CTLA4", "P16410"),
    "ENSG00000120217": ("CD274", "Q9NZQ7"),  # PD-L1
    "ENSG00000091831": ("ESR1", "P03372"),
    # ---- Driver oncoproteins (not surface; used in demo for the "stable / down" rows) ----
    "ENSG00000142208": ("AKT1", "P31749"),
    "ENSG00000118260": ("CREB1", "P16220"),
    "ENSG00000074706": ("PTEN", "P60484"),
    "ENSG00000196712": ("NF1", "P21359"),
    "ENSG00000133703": ("KRAS", "P01116"),
    "ENSG00000174775": ("HRAS", "P01112"),
    "ENSG00000129965": ("INS-IGF2", "P01308"),
}


def lookup(gene_id: str) -> tuple[str | None, str | None]:
    """Return ``(symbol, uniprot_id)`` for a gene_id, or ``(None, None)`` if unknown."""
    if gene_id in _BUNDLED:
        return _BUNDLED[gene_id]
    return (None, None)


def is_known(gene_id: str) -> bool:
    """Return True if the bundled map has an entry for ``gene_id``."""
    return gene_id in _BUNDLED


__all__ = ["is_known", "lookup"]

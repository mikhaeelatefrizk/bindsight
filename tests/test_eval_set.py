"""Integrity tests for the committed held-out evaluation set (benchmarks/).

These run offline against the committed files (no network); they guard against
regressions / fabrication: real accessions, every binder cited, FASTA sequences
valid and consistent with the structural binders.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd
import pytest

BENCH = Path(__file__).resolve().parent.parent / "benchmarks"

# Official UniProtKB accession syntax (the O/P/Q-prefix form covers P20138 etc.).
UNIPROT_RE = re.compile(
    r"^(?:[OPQ][0-9][A-Z0-9]{3}[0-9]|[A-NR-Z][0-9](?:[A-Z][A-Z0-9]{2}[0-9]){1,2})$"
)
ENSG_RE = re.compile(r"^ENSG\d{11}$")
AA = set("ACDEFGHIKLMNPQRSTVWY")


@pytest.fixture
def known() -> pd.DataFrame:
    return pd.read_csv(BENCH / "known.tsv", sep="\t", dtype=str).fillna("")


@pytest.fixture
def binders() -> pd.DataFrame:
    return pd.read_csv(BENCH / "binders.tsv", sep="\t", dtype=str).fillna("")


def test_known_antigens_present_and_valid(known: pd.DataFrame) -> None:
    syms = set(known["symbol"])
    # The held-out targets the user specified, plus the solid-tumor extension.
    assert {"CD33", "IL3RA", "ERBB2", "EGFR", "MSLN", "CLDN6"} <= syms
    for _, r in known.iterrows():
        assert UNIPROT_RE.match(r["uniprot"]), f"bad UniProt {r['uniprot']} for {r['symbol']}"
        assert ENSG_RE.match(r["ensembl_gene"]), f"bad Ensembl {r['ensembl_gene']}"


def test_cldn6_uses_correct_accession(known: pd.DataFrame) -> None:
    """CLDN6 must be P56747 — NOT Q14953 (which is KIR2DS5)."""
    cldn6 = known[known["symbol"] == "CLDN6"].iloc[0]
    assert cldn6["uniprot"] == "P56747"
    assert "Q14953" not in set(known["uniprot"])


def test_aml_targets_have_binders(binders: pd.DataFrame) -> None:
    """CD33 and CD123/IL3RA each have multiple literature-validated binders."""
    cd33 = binders[binders["target_uniprot"] == "P20138"]
    cd123 = binders[binders["target_uniprot"] == "P26951"]
    assert len(cd33) >= 3
    assert len(cd123) >= 3
    # The named flagship agents are present.
    names = " ".join(binders["binder_id"])
    for expected in ("gemtuzumab", "lintuzumab", "tagraxofusp", "flotetuzumab", "talacotuzumab"):
        assert expected in names


def test_every_binder_has_a_citation(binders: pd.DataFrame) -> None:
    for _, r in binders.iterrows():
        cites = [r["chembl_id"], r["nct_id"], r["pmid"], r["doi"], r["pdb_id"]]
        assert any(c.strip() for c in cites), f"binder {r['binder_id']} has no citation"


def test_structural_binders_have_real_sequences(binders: pd.DataFrame) -> None:
    fasta = (BENCH / "binders.fasta").read_text()
    ids = {line[1:].strip() for line in fasta.splitlines() if line.startswith(">")}
    struct = binders[binders["sequence_source"].str.startswith("PDB:")]
    assert len(struct) >= 5  # 10C8, 7G3, trastuzumab, pertuzumab, cetuximab
    for _, r in struct.iterrows():
        for sid in r["sequence_ids"].split(";"):
            assert sid in ids, f"missing FASTA entry {sid}"


def test_fasta_sequences_are_valid_amino_acids() -> None:
    seqs = _read_fasta(BENCH / "binders.fasta")
    assert len(seqs) >= 10  # H+L for 5 structural binders
    for header, seq in seqs.items():
        assert len(seq) > 80, f"{header} suspiciously short"
        assert set(seq) <= AA, f"{header} has non-standard residues: {set(seq) - AA}"


def test_trastuzumab_vh_matches_known_cdr() -> None:
    """Sanity check the deposited trastuzumab VH (CDR-H1 'DTYIH')."""
    seqs = _read_fasta(BENCH / "binders.fasta")
    vh = next(s for h, s in seqs.items() if h.startswith("trastuzumab|H"))
    assert "DTYIH" in vh  # trastuzumab heavy-chain CDR-H1 motif


def test_sources_json_provenance() -> None:
    src = json.loads((BENCH / "sources.json").read_text())
    assert src["counts"]["known_antigens"] >= 6
    assert src["counts"]["binders_with_structure_sequences"] >= 5
    # Every recorded output's SHA-256 matches the committed file.
    import hashlib

    for name, meta in src["outputs"].items():
        digest = hashlib.sha256((BENCH / name).read_bytes()).hexdigest()
        assert digest == meta["sha256"], f"{name} drifted from sources.json"


def _read_fasta(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    header, chunks = None, []
    for line in path.read_text().splitlines():
        if line.startswith(">"):
            if header:
                out[header] = "".join(chunks)
            header, chunks = line[1:].strip(), []
        elif header:
            chunks.append(line.strip())
    if header:
        out[header] = "".join(chunks)
    return out

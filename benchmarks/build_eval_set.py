#!/usr/bin/env python3
"""Reproducibly build the bindsight held-out evaluation set from public sources.

This script is the *single source of truth* for ``benchmarks/known.tsv``,
``benchmarks/binders.tsv``, ``benchmarks/binders.fasta`` and
``benchmarks/sources.json``. Every record below is curated from canonical,
globally-authoritative public databases and carries a verifiable identifier
(UniProt accession, Ensembl gene ID, RCSB PDB ID, ChEMBL ID, ClinicalTrials.gov
NCT number, and/or PubMed PMID). No value is fabricated.

Binder amino-acid sequences are **not** typed by hand: they are downloaded at
build time from the RCSB PDB FASTA service for the exact co-crystal structure
cited, so the ground-truth sequences are byte-for-byte the deposited ones.

Run ``python benchmarks/build_eval_set.py`` to regenerate (needs network).
The generated files are committed so the eval set is usable offline; rerun to
refresh provenance (retrieval timestamp + SHA-256 of each output).

Sources
-------
- UniProt            https://www.uniprot.org/        (CC BY 4.0)
- Ensembl            https://www.ensembl.org/        (open)
- RCSB PDB           https://www.rcsb.org/           (CC0)
- ChEMBL (EMBL-EBI)  https://www.ebi.ac.uk/chembl/   (CC BY-SA 3.0)
- ClinicalTrials.gov https://clinicaltrials.gov/     (public domain, NIH/NLM)
- PubMed (NCBI)      https://pubmed.ncbi.nlm.nih.gov/(public domain)
"""

from __future__ import annotations

import csv
import datetime as _dt
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
RCSB_FASTA = "https://www.rcsb.org/fasta/entry/{pdb}/display"


# ---------------------------------------------------------------------------
# Known antigens — the held-out targets a rediscovery run must surface.
# Each is a real, clinically-pursued cell-surface antigen with a validated
# UniProt accession and Ensembl gene ID (both verified against UniProt).
# ---------------------------------------------------------------------------
KNOWN_ANTIGENS: list[dict[str, str]] = [
    {
        "symbol": "CD33",
        "aka": "SIGLEC3",
        "uniprot": "P20138",
        "ensembl_gene": "ENSG00000105383",
        "disease": "Acute myeloid leukemia",
        "tumor_type": "AML",
        "expected_direction": "up",
        "note": "Canonical AML myeloid surface antigen; target of gemtuzumab ozogamicin.",
    },
    {
        "symbol": "IL3RA",
        "aka": "CD123",
        "uniprot": "P26951",
        "ensembl_gene": "ENSG00000185291",
        "disease": "Acute myeloid leukemia",
        "tumor_type": "AML",
        "expected_direction": "up",
        "note": "AML leukemic stem-cell marker; target of tagraxofusp/flotetuzumab.",
    },
    {
        "symbol": "ERBB2",
        "aka": "HER2",
        "uniprot": "P04626",
        "ensembl_gene": "ENSG00000141736",
        "disease": "Breast carcinoma",
        "tumor_type": "BRCA",
        "expected_direction": "up",
        "note": "HER2-amplified breast cancer; target of trastuzumab/pertuzumab.",
    },
    {
        "symbol": "EGFR",
        "aka": "HER1",
        "uniprot": "P00533",
        "ensembl_gene": "ENSG00000146648",
        "disease": "Lung adenocarcinoma",
        "tumor_type": "LUAD",
        "expected_direction": "up",
        "note": "EGFR-driven carcinoma; target of cetuximab/panitumumab.",
    },
    {
        "symbol": "MSLN",
        "aka": "mesothelin",
        "uniprot": "Q13421",
        "ensembl_gene": "ENSG00000102854",
        "disease": "Pancreatic adenocarcinoma",
        "tumor_type": "PAAD",
        "expected_direction": "up",
        "note": "Mesothelin; target of amatuximab/anetumab ravtansine.",
    },
    {
        "symbol": "CLDN6",
        "aka": "claudin-6",
        "uniprot": "P56747",
        "ensembl_gene": "ENSG00000184697",
        "disease": "Ovarian carcinoma",
        "tumor_type": "OV",
        "expected_direction": "up",
        "note": "Oncofetal claudin-6; target of BNT211 CLDN6 CAR-T. (NB: the "
        "canonical accession is P56747 — NOT Q14953, which is KIR2DS5.)",
    },
    {
        "symbol": "FOLH1",
        "aka": "PSMA",
        "uniprot": "Q04609",
        "ensembl_gene": "ENSG00000086205",
        "disease": "Prostate adenocarcinoma",
        "tumor_type": "PRAD",
        "expected_direction": "up",
        "note": "Prostate-specific membrane antigen; target of J591 and of "
        "[177Lu]Lu-PSMA-617 (Pluvicto, FDA-approved).",
    },
]


# ---------------------------------------------------------------------------
# Literature-validated binders (held-out ground truth).
# `pdb` + `pdb_chains` populate real VH/VL sequences from the co-crystal.
# Binders without a public structure carry their clinical/database citations
# and are marked sequence_source="not_public" rather than inventing a sequence.
# ---------------------------------------------------------------------------
BINDERS: list[dict[str, object]] = [
    # ---- CD33 / AML ----
    {
        "binder_id": "gemtuzumab_ozogamicin",
        "name": "Gemtuzumab ozogamicin (Mylotarg)",
        "target_symbol": "CD33",
        "target_uniprot": "P20138",
        "disease": "AML",
        "modality": "antibody-drug conjugate",
        "status": "approved",
        "max_phase": "4",
        "chembl": "CHEMBL1201506",
        "nct": "NCT03531918",
        "pmid": "22482940",  # Castaigne et al., Lancet 2012 (ALFA-0701)
        "doi": "10.1016/S0140-6736(12)60485-1",
        "pdb": "",
        "pdb_chains": {},
    },
    {
        "binder_id": "lintuzumab",
        "name": "Lintuzumab (HuM195 / SGN-33)",
        "target_symbol": "CD33",
        "target_uniprot": "P20138",
        "disease": "AML",
        "modality": "monoclonal antibody",
        "status": "phase 3",
        "max_phase": "3",
        "chembl": "CHEMBL2109150",
        "nct": "NCT00006045",
        "pmid": "15961759",  # Feldman et al., J Clin Oncol 2005 (phase III)
        "doi": "10.1200/JCO.2005.09.133",
        "pdb": "",
        "pdb_chains": {},
    },
    {
        "binder_id": "vadastuximab_talirine",
        "name": "Vadastuximab talirine (SGN-CD33A)",
        "target_symbol": "CD33",
        "target_uniprot": "P20138",
        "disease": "AML",
        "modality": "antibody-drug conjugate",
        "status": "phase 2",
        "max_phase": "2",
        "chembl": "CHEMBL3990021",
        "nct": "NCT02326584",
        "pmid": "29534618",
        "doi": "10.1080/13543784.2018.1452911",
        "pdb": "",
        "pdb_chains": {},
    },
    {
        "binder_id": "fab_10C8_anti_CD33",
        "name": "Fab-10C8 (anti-CD33, structurally resolved)",
        "target_symbol": "CD33",
        "target_uniprot": "P20138",
        "disease": "AML",
        "modality": "Fab",
        "status": "research",
        "max_phase": "",
        "chembl": "",
        "nct": "",
        "pmid": "",  # Crystal structure of the CD33/Fab-10C8 complex, J Biomed Sci 2026
        "doi": "",
        "pdb": "9VL2",
        "pdb_chains": {"H": "heavy", "L": "light"},
    },
    # ---- CD123 / AML ----
    {
        "binder_id": "tagraxofusp",
        "name": "Tagraxofusp (SL-401 / Elzonris)",
        "target_symbol": "IL3RA",
        "target_uniprot": "P26951",
        "disease": "AML",
        "modality": "cytokine-toxin fusion (IL-3/diphtheria toxin)",
        "status": "approved",
        "max_phase": "4",
        "chembl": "CHEMBL4297573",
        "nct": "NCT04342962",
        "pmid": "31018069",  # Pemmaraju et al., N Engl J Med 2019 (BPDCN)
        "doi": "10.1056/NEJMoa1815105",
        "pdb": "",
        "pdb_chains": {},
    },
    {
        "binder_id": "talacotuzumab",
        "name": "Talacotuzumab (CSL362 / JNJ-56022473)",
        "target_symbol": "IL3RA",
        "target_uniprot": "P26951",
        "disease": "AML",
        "modality": "monoclonal antibody (Fc-engineered, humanized 7G3)",
        "status": "phase 2/3",
        "max_phase": "2",
        "chembl": "CHEMBL4297837",
        "nct": "NCT02472145",
        "pmid": "26130514",  # Efficacy of CSL362, Haematologica 2015
        "doi": "10.3324/haematol.2014.113092",
        "pdb": "",  # structurally represented by its murine parent 7G3 (below)
        "pdb_chains": {},
    },
    {
        "binder_id": "fab_7G3_anti_CD123",
        "name": "Fab 7G3 (murine parent of CSL362/talacotuzumab)",
        "target_symbol": "IL3RA",
        "target_uniprot": "P26951",
        "disease": "AML",
        "modality": "Fab",
        "status": "research",
        "max_phase": "",
        "chembl": "",
        "nct": "",
        "pmid": "25043189",  # Broughton et al., Cell Rep 2014
        "doi": "10.1016/j.celrep.2014.06.038",
        "pdb": "4JZJ",
        "pdb_chains": {"H": "heavy", "L": "light"},
    },
    {
        "binder_id": "flotetuzumab",
        "name": "Flotetuzumab (MGD006 / S80880)",
        "target_symbol": "IL3RA",
        "target_uniprot": "P26951",
        "disease": "AML",
        "modality": "bispecific DART (CD123 x CD3)",
        "status": "phase 2",
        "max_phase": "2",
        "chembl": "CHEMBL3990038",
        "nct": "NCT03739606",
        "pmid": "32929488",  # Uy et al., Blood 2021
        "doi": "10.1182/blood.2020007732",
        "pdb": "",
        "pdb_chains": {},
    },
    # ---- HER2 / breast ----
    {
        "binder_id": "trastuzumab",
        "name": "Trastuzumab (Herceptin)",
        "target_symbol": "ERBB2",
        "target_uniprot": "P04626",
        "disease": "BRCA",
        "modality": "monoclonal antibody",
        "status": "approved",
        "max_phase": "4",
        "chembl": "CHEMBL1201585",
        "nct": "",
        "pmid": "12610629",  # Cho et al., Nature 2003 (HER2/Herceptin structure)
        "doi": "10.1038/nature01392",
        "pdb": "1N8Z",
        "pdb_chains": {"H": "heavy", "L": "light"},
    },
    {
        "binder_id": "pertuzumab",
        "name": "Pertuzumab (Perjeta)",
        "target_symbol": "ERBB2",
        "target_uniprot": "P04626",
        "disease": "BRCA",
        "modality": "monoclonal antibody",
        "status": "approved",
        "max_phase": "4",
        "chembl": "CHEMBL1201827",
        "nct": "",
        "pmid": "15093539",  # Franklin et al., Cancer Cell 2004 (ErbB2/pertuzumab)
        "doi": "10.1016/j.ccr.2004.03.020",
        "pdb": "1S78",
        "pdb_chains": {"H": "heavy", "L": "light"},
    },
    # ---- EGFR / lung ----
    {
        "binder_id": "cetuximab",
        "name": "Cetuximab (Erbitux)",
        "target_symbol": "EGFR",
        "target_uniprot": "P00533",
        "disease": "LUAD",
        "modality": "monoclonal antibody",
        "status": "approved",
        "max_phase": "4",
        "chembl": "CHEMBL1201577",
        "nct": "",
        "pmid": "15837620",  # Li et al., Cancer Cell 2005 (EGFR/cetuximab)
        "doi": "10.1016/j.ccr.2005.03.003",
        "pdb": "1YY9",
        "pdb_chains": {"H": "heavy", "L": "light"},
    },
    # ---- MSLN / pancreatic ----
    {
        "binder_id": "amatuximab",
        "name": "Amatuximab (MORAb-009)",
        "target_symbol": "MSLN",
        "target_uniprot": "Q13421",
        "disease": "PAAD",
        "modality": "monoclonal antibody",
        "status": "phase 2",
        "max_phase": "2",
        "chembl": "",
        "nct": "",
        "pmid": "29184420",
        "doi": "",
        "pdb": "",
        "pdb_chains": {},
    },
    {
        "binder_id": "anetumab_ravtansine",
        "name": "Anetumab ravtansine (BAY 94-9343)",
        "target_symbol": "MSLN",
        "target_uniprot": "Q13421",
        "disease": "PAAD",
        "modality": "antibody-drug conjugate",
        "status": "phase 2",
        "max_phase": "2",
        "chembl": "",
        "nct": "",
        "pmid": "39197359",
        "doi": "",
        "pdb": "",
        "pdb_chains": {},
    },
    # ---- CLDN6 / ovarian ----
    {
        "binder_id": "bnt211_cldn6",
        "name": "BNT211 (CLDN6 CAR-T)",
        "target_symbol": "CLDN6",
        "target_uniprot": "P56747",
        "disease": "OV",
        "modality": "CAR-T cell therapy",
        "status": "phase 1/2",
        "max_phase": "1",
        "chembl": "",
        "nct": "",
        "pmid": "37872225",
        "doi": "",
        "pdb": "",
        "pdb_chains": {},
    },
]


def _fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "bindsight-eval-builder"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8")


def _parse_fasta(text: str) -> list[tuple[str, str]]:
    """Parse FASTA text into a list of (header, sequence)."""
    out: list[tuple[str, str]] = []
    header, chunks = None, []
    for line in text.splitlines():
        if line.startswith(">"):
            if header is not None:
                out.append((header, "".join(chunks)))
            header, chunks = line[1:], []
        elif header is not None:
            chunks.append(line.strip())
    if header is not None:
        out.append((header, "".join(chunks)))
    return out


def fetch_binder_sequences(pdb: str, chains: dict[str, str]) -> dict[str, str]:
    """Return {role: sequence} by matching antibody chain descriptions.

    ``chains`` maps a role (``"H"``/``"L"``) to a keyword (``"heavy"``/``"light"``)
    expected in the PDB entity description; the matching entity's deposited
    sequence is returned. This keeps ground-truth sequences byte-identical to
    the PDB without hand-transcription.
    """
    entities = _parse_fasta(_fetch(RCSB_FASTA.format(pdb=pdb)))
    seqs: dict[str, str] = {}
    for role, keyword in chains.items():
        for header, seq in entities:
            if keyword.lower() in header.lower():
                seqs[role] = seq
                break
        else:
            raise RuntimeError(f"{pdb}: no entity matching '{keyword}' for role {role}")
    return seqs


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    """Generate the eval-set files and print a summary."""
    retrieved = _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds")

    # ---- known.tsv ----
    known_path = HERE / "known.tsv"
    known_cols = [
        "symbol",
        "aka",
        "uniprot",
        "ensembl_gene",
        "disease",
        "tumor_type",
        "expected_direction",
        "note",
    ]
    with known_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=known_cols, delimiter="\t", lineterminator="\n")
        w.writeheader()
        w.writerows(KNOWN_ANTIGENS)

    # ---- binders.tsv + binders.fasta (sequences pulled live) ----
    fasta_lines: list[str] = []
    binder_rows: list[dict[str, str]] = []
    for b in BINDERS:
        pdb = str(b["pdb"])
        chains = b["pdb_chains"]  # type: ignore[assignment]
        seq_source = "not_public"
        seq_ids: list[str] = []
        if pdb and chains:
            seqs = fetch_binder_sequences(pdb, chains)  # type: ignore[arg-type]
            seq_source = f"PDB:{pdb}"
            for role, seq in seqs.items():
                sid = f"{b['binder_id']}|{role}|PDB_{pdb}"
                seq_ids.append(sid)
                fasta_lines.append(f">{sid}")
                fasta_lines += [seq[i : i + 60] for i in range(0, len(seq), 60)]
        # Every row must carry at least one resolvable citation.
        if not any(b[k] for k in ("pdb", "pmid", "nct", "chembl")):
            raise RuntimeError(f"binder {b['binder_id']} has no citation")
        binder_rows.append(
            {
                "binder_id": str(b["binder_id"]),
                "name": str(b["name"]),
                "target_symbol": str(b["target_symbol"]),
                "target_uniprot": str(b["target_uniprot"]),
                "disease": str(b["disease"]),
                "modality": str(b["modality"]),
                "status": str(b["status"]),
                "max_phase": str(b["max_phase"]),
                "chembl_id": str(b["chembl"]),
                "nct_id": str(b["nct"]),
                "pmid": str(b["pmid"]),
                "doi": str(b["doi"]),
                "pdb_id": pdb,
                "sequence_source": seq_source,
                "sequence_ids": ";".join(seq_ids),
            }
        )

    binders_path = HERE / "binders.tsv"
    binder_cols = list(binder_rows[0].keys())
    with binders_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=binder_cols, delimiter="\t", lineterminator="\n")
        w.writeheader()
        w.writerows(binder_rows)

    fasta_path = HERE / "binders.fasta"
    fasta_path.write_text("\n".join(fasta_lines) + "\n")

    # ---- sources.json (provenance: SHA-256 + retrieval metadata) ----
    n_struct = sum(1 for r in binder_rows if r["sequence_source"].startswith("PDB:"))
    sources = {
        "schema": "bindsight-eval-set/1",
        "generated_by": "benchmarks/build_eval_set.py",
        "retrieved_utc": retrieved,
        "databases": {
            "UniProt": "https://www.uniprot.org/ (CC BY 4.0)",
            "Ensembl": "https://www.ensembl.org/ (open)",
            "RCSB PDB": "https://www.rcsb.org/ (CC0)",
            "ChEMBL": "https://www.ebi.ac.uk/chembl/ (CC BY-SA 3.0)",
            "ClinicalTrials.gov": "https://clinicaltrials.gov/ (NIH/NLM, public domain)",
            "PubMed": "https://pubmed.ncbi.nlm.nih.gov/ (public domain)",
        },
        "counts": {
            "known_antigens": len(KNOWN_ANTIGENS),
            "binders": len(binder_rows),
            "binders_with_structure_sequences": n_struct,
        },
        "outputs": {
            p.name: {"sha256": _sha256(p), "bytes": p.stat().st_size}
            for p in (known_path, binders_path, fasta_path)
        },
    }
    (HERE / "sources.json").write_text(json.dumps(sources, indent=2) + "\n")

    print(f"known antigens : {len(KNOWN_ANTIGENS)} -> {known_path.name}")
    print(f"binders        : {len(binder_rows)} -> {binders_path.name}")
    print(f"  with real VH/VL sequences from PDB: {n_struct} -> {fasta_path.name}")
    print(f"provenance     : sources.json ({retrieved})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

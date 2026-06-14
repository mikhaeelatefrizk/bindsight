"""NIH/GDC RNA-seq cohort fetcher.

Downloads **real** TCGA gene-expression (STAR - Counts) for a project such as
``TCGA-BRCA``, assembles a gene × sample integer-count matrix plus a sample
design table, and writes full provenance (GDC file UUIDs, case barcodes,
sample types, workflow, retrieval timestamp, SHA-256 of the outputs).

This is what makes ``bindsight demo`` / a ``bindsight discover`` config run on
authentic patient data rather than illustrative numbers. The GDC open-access
gene-level expression API needs no token. Outputs are written where the run
config's ``inputs.counts`` / ``inputs.design`` point (typically a cache dir),
so the first run downloads and subsequent runs are offline.

Source: GDC Data Portal, https://portal.gdc.cancer.gov/ (NIH/NCI, open access).
TCGA data usage: https://gdc.cancer.gov/about-data/publication-guidelines
"""

from __future__ import annotations

import datetime as _dt
import gzip
import hashlib
import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import requests
from tenacity import retry, stop_after_attempt, wait_exponential

LOG = logging.getLogger(__name__)

GDC_FILES_ENDPOINT = "https://api.gdc.cancer.gov/files"
GDC_DATA_ENDPOINT = "https://api.gdc.cancer.gov/data/{file_id}"

# STAR-Counts column layout (GENCODE v36); column 3 (0-based) is the raw count.
_UNSTRANDED_COL = 3
_SKIP_ROW_PREFIXES = ("N_unmapped", "N_multimapping", "N_noFeature", "N_ambiguous")

_SAMPLE_TYPES = {"tumor": "Primary Tumor", "normal": "Solid Tissue Normal"}


@dataclass(frozen=True)
class CohortSample:
    """One downloaded sample's provenance."""

    sample: str  # short bindsight sample id, e.g. "T01"
    condition: str  # "tumor" | "normal"
    sample_type: str  # GDC sample_type, e.g. "Primary Tumor"
    case_barcode: str  # TCGA case submitter id
    sample_barcode: str  # TCGA sample submitter id
    gdc_file_id: str


@retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=2, min=2, max=16))
def _post_files_query(
    filters: dict[str, Any], fields: list[str], size: int
) -> list[dict[str, Any]]:
    """Query the GDC files endpoint; return the hits list (retried on failure)."""
    resp = requests.post(
        GDC_FILES_ENDPOINT,
        json={
            "filters": filters,
            "fields": ",".join(fields),
            "format": "JSON",
            "size": str(size),
            "sort": "file_id:asc",  # deterministic selection
        },
        timeout=60,
    )
    resp.raise_for_status()
    hits: list[dict[str, Any]] = resp.json()["data"]["hits"]
    return hits


def _list_cohort_files(project: str, condition: str, n: int) -> list[dict[str, Any]]:
    """List the first ``n`` STAR-Counts files for a project + tumor/normal class."""
    filters = {
        "op": "and",
        "content": [
            {"op": "in", "content": {"field": "cases.project.project_id", "value": [project]}},
            {
                "op": "in",
                "content": {"field": "data_type", "value": ["Gene Expression Quantification"]},
            },
            {
                "op": "in",
                "content": {"field": "analysis.workflow_type", "value": ["STAR - Counts"]},
            },
            {
                "op": "in",
                "content": {
                    "field": "cases.samples.sample_type",
                    "value": [_SAMPLE_TYPES[condition]],
                },
            },
        ],
    }
    fields = [
        "file_id",
        "cases.submitter_id",
        "cases.samples.submitter_id",
        "cases.samples.sample_type",
    ]
    hits = _post_files_query(filters, fields, size=n)
    if len(hits) < n:
        LOG.warning(
            "%s %s: requested %d files but only %d available", project, condition, n, len(hits)
        )
    return hits[:n]


@retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=2, min=2, max=16))
def _download_counts(file_id: str, gene_types: tuple[str, ...]) -> dict[str, int]:
    """Download one STAR-Counts file; return {ensembl_gene_id: unstranded_count}.

    Strips the Ensembl version suffix, skips the STAR summary rows and the
    pseudoautosomal ``_PAR_Y`` duplicates, and optionally restricts to the
    given gene biotypes.
    """
    resp = requests.get(GDC_DATA_ENDPOINT.format(file_id=file_id), timeout=120)
    resp.raise_for_status()
    counts: dict[str, int] = {}
    for line in resp.text.splitlines():
        if not line or line.startswith("#") or line.startswith("gene_id\t"):
            continue
        if line.startswith(_SKIP_ROW_PREFIXES):
            continue
        parts = line.split("\t")
        if len(parts) <= _UNSTRANDED_COL:
            continue
        gene_id = parts[0]
        if "_PAR_Y" in gene_id:
            continue
        gene_type = parts[2]
        if gene_types and gene_type not in gene_types:
            continue
        base = gene_id.split(".")[0]
        try:
            counts[base] = int(parts[_UNSTRANDED_COL])
        except ValueError:
            continue
    return counts


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fetch_cohort(
    *,
    project: str,
    n_tumor: int,
    n_normal: int,
    counts_out: Path,
    design_out: Path,
    gene_types: tuple[str, ...] = ("protein_coding",),
) -> dict[str, object]:
    """Download a real TCGA cohort and write counts + design + provenance.

    Args:
        project: GDC project id, e.g. ``"TCGA-BRCA"``.
        n_tumor: number of Primary Tumor samples to download.
        n_normal: number of Solid Tissue Normal samples to download.
        counts_out: where to write the gzipped gene × sample counts TSV.
        design_out: where to write the sample design TSV.
        gene_types: biotypes to keep (``()`` keeps all). Defaults to
            protein-coding, which covers the surface-antigen targets and keeps
            DESeq2 tractable.

    Returns:
        The provenance dict (also written next to ``counts_out`` as
        ``provenance.json``).
    """
    counts_out = Path(counts_out)
    design_out = Path(design_out)
    counts_out.parent.mkdir(parents=True, exist_ok=True)
    design_out.parent.mkdir(parents=True, exist_ok=True)

    LOG.info("GDC: listing %s files (%d tumor + %d normal)…", project, n_tumor, n_normal)
    tumor_hits = _list_cohort_files(project, "tumor", n_tumor)
    normal_hits = _list_cohort_files(project, "normal", n_normal)

    samples: list[CohortSample] = []
    per_sample_counts: dict[str, dict[str, int]] = {}
    for condition, hits in (("tumor", tumor_hits), ("normal", normal_hits)):
        prefix = "T" if condition == "tumor" else "N"
        for i, hit in enumerate(hits, start=1):
            sample_id = f"{prefix}{i:02d}"
            case = hit.get("cases", [{}])[0]
            sample0 = (case.get("samples") or [{}])[0]
            LOG.info("GDC: downloading %s (%s) %s…", sample_id, condition, hit["file_id"][:8])
            per_sample_counts[sample_id] = _download_counts(hit["file_id"], gene_types)
            samples.append(
                CohortSample(
                    sample=sample_id,
                    condition=condition,
                    sample_type=sample0.get("sample_type", _SAMPLE_TYPES[condition]),
                    case_barcode=case.get("submitter_id", ""),
                    sample_barcode=sample0.get("submitter_id", ""),
                    gdc_file_id=hit["file_id"],
                )
            )

    if not per_sample_counts:
        raise RuntimeError(f"GDC returned no files for {project}")

    # Assemble the gene × sample matrix on the intersection of genes (all STAR
    # files share the GENCODE v36 gene set, so this is the full set in practice).
    counts_df = pd.DataFrame(per_sample_counts).dropna().astype(int)
    counts_df.index.name = "gene_id"
    counts_df = counts_df.sort_index()

    with gzip.open(counts_out, "wt", newline="") as fh:
        counts_df.to_csv(fh, sep="\t")

    design_df = pd.DataFrame([asdict(s) for s in samples]).set_index("sample")
    design_df.to_csv(design_out, sep="\t", lineterminator="\n")

    provenance = {
        "schema": "bindsight-gdc-cohort/1",
        "source": "NIH/GDC (https://portal.gdc.cancer.gov/)",
        "project": project,
        "workflow": "STAR - Counts (GENCODE v36)",
        "data_column": "unstranded",
        "gene_types": list(gene_types),
        "retrieved_utc": _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds"),
        "n_tumor": sum(1 for s in samples if s.condition == "tumor"),
        "n_normal": sum(1 for s in samples if s.condition == "normal"),
        "n_genes": int(counts_df.shape[0]),
        "samples": [asdict(s) for s in samples],
        "outputs": {
            counts_out.name: {"sha256": _sha256(counts_out), "bytes": counts_out.stat().st_size},
            design_out.name: {"sha256": _sha256(design_out), "bytes": design_out.stat().st_size},
        },
    }
    prov_path = counts_out.parent / "provenance.json"
    prov_path.write_text(json.dumps(provenance, indent=2) + "\n")
    LOG.info(
        "GDC: wrote %s (%d genes × %d samples) + %s",
        counts_out,
        counts_df.shape[0],
        counts_df.shape[1],
        design_out.name,
    )
    return provenance

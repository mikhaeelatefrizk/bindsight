# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for the GDC cohort fetcher (HTTP mocked — no network)."""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import pandas as pd
import pytest

from bindsight.config import GDCSource, RunConfig
from bindsight.io import gdc

# A minimal STAR-Counts file body: comment + header + 4 summary rows + genes,
# including a _PAR_Y duplicate and a non-coding gene to exercise the filters.
_STAR_BODY = (
    "# gene-model: GENCODE v36\n"
    "gene_id\tgene_name\tgene_type\tunstranded\tstranded_first\tstranded_second\t"
    "tpm_unstranded\tfpkm_unstranded\tfpkm_uq_unstranded\n"
    "N_unmapped\t\t\t1000\t1000\t1000\t\t\t\n"
    "N_multimapping\t\t\t500\t500\t500\t\t\t\n"
    "N_noFeature\t\t\t200\t200\t200\t\t\t\n"
    "N_ambiguous\t\t\t100\t100\t100\t\t\t\n"
    "ENSG00000141736.14\tERBB2\tprotein_coding\t{erbb2}\t1\t1\t1\t1\t1\n"
    "ENSG00000146648.18\tEGFR\tprotein_coding\t{egfr}\t1\t1\t1\t1\t1\n"
    "ENSG00000000005.6\tTNMD\tprotein_coding\t{tnmd}\t1\t1\t1\t1\t1\n"
    "ENSG00000270726.5\tMIRLET7\tlncRNA\t999\t1\t1\t1\t1\t1\n"  # filtered (biotype)
    "ENSG00000002586.20_PAR_Y\tCD99\tprotein_coding\t7\t1\t1\t1\t1\t1\n"  # filtered (_PAR_Y)
)


class _FakeResp:
    def __init__(self, *, text: str = "", payload: dict | None = None) -> None:
        self.text = text
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        assert self._payload is not None
        return self._payload


@pytest.fixture
def mock_gdc(monkeypatch: pytest.MonkeyPatch):
    """Mock the GDC files query + data download."""

    def _fake_post(url, json, timeout):
        sample_type = json["filters"]["content"][3]["content"]["value"][0]
        tag = "T" if sample_type == "Primary Tumor" else "N"
        hit = {
            "file_id": f"file-{tag}-0001",
            "cases": [
                {
                    "submitter_id": f"TCGA-XX-{tag}001",
                    "samples": [
                        {"submitter_id": f"TCGA-XX-{tag}001-01", "sample_type": sample_type}
                    ],
                }
            ],
        }
        return _FakeResp(payload={"data": {"hits": [hit]}})

    def _fake_get(url, timeout):
        # Tumor files over-express ERBB2/EGFR; normal files don't.
        if "file-T" in url:
            body = _STAR_BODY.format(erbb2=2000, egfr=1800, tnmd=50)
        else:
            body = _STAR_BODY.format(erbb2=150, egfr=170, tnmd=55)
        return _FakeResp(text=body)

    monkeypatch.setattr(gdc.requests, "post", _fake_post)
    monkeypatch.setattr(gdc.requests, "get", _fake_get)


def test_download_counts_parses_and_filters(mock_gdc) -> None:
    counts = gdc._download_counts("file-T-0001", ("protein_coding",))
    # Version stripped; summary rows, _PAR_Y, and non-coding biotype dropped.
    assert counts["ENSG00000141736"] == 2000
    assert counts["ENSG00000146648"] == 1800
    assert "ENSG00000270726" not in counts  # lncRNA filtered out
    assert "ENSG00000002586" not in counts  # _PAR_Y filtered out
    assert all(not k.startswith("N_") for k in counts)


def test_fetch_cohort_writes_counts_design_provenance(mock_gdc, tmp_path: Path) -> None:
    counts_out = tmp_path / "cache" / "counts.tsv.gz"
    design_out = tmp_path / "cache" / "design.tsv"
    prov = gdc.fetch_cohort(
        project="TCGA-BRCA",
        n_tumor=1,
        n_normal=1,
        counts_out=counts_out,
        design_out=design_out,
    )

    assert counts_out.exists()
    assert design_out.exists()

    with gzip.open(counts_out, "rt") as fh:
        counts = pd.read_csv(fh, sep="\t", index_col=0)
    assert list(counts.columns) == ["T01", "N01"]
    assert counts.loc["ENSG00000141736", "T01"] == 2000
    assert counts.loc["ENSG00000141736", "N01"] == 150

    design = pd.read_csv(design_out, sep="\t", index_col=0)
    assert set(design.index) == {"T01", "N01"}
    assert design.loc["T01", "condition"] == "tumor"
    assert design.loc["N01", "condition"] == "normal"
    assert design.loc["T01", "gdc_file_id"] == "file-T-0001"

    # Provenance written with SHA-256 of the outputs.
    assert prov["project"] == "TCGA-BRCA"
    assert prov["n_tumor"] == 1
    prov_file = json.loads((counts_out.parent / "provenance.json").read_text())
    assert prov_file["outputs"]["counts.tsv.gz"]["sha256"]
    assert len(prov_file["samples"]) == 2


def test_gdc_source_config_roundtrips() -> None:
    cfg = RunConfig.model_validate(
        {
            "name": "t",
            "out_dir": "out",
            "inputs": {
                "counts": "c.tsv.gz",
                "design": "d.tsv",
                "download": {"project": "TCGA-BRCA", "n_tumor": 5, "n_normal": 5},
            },
            "params": {
                "deg": {"design_formula": "~ condition", "contrast": ["condition", "t", "n"]}
            },
        }
    )
    assert isinstance(cfg.inputs.download, GDCSource)
    assert cfg.inputs.download.project == "TCGA-BRCA"
    assert cfg.inputs.download.gene_types == ["protein_coding"]

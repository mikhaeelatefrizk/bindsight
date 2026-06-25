# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""cBioPortal molecular-subtype fetcher.

Pulls canonical PAM50 intrinsic-subtype calls for a TCGA study from the public
cBioPortal REST API (https://www.cbioportal.org/api). Subtype labels are keyed
by patient barcode (``TCGA-XX-XXXX``), which is identical to the GDC
``cases.submitter_id`` — so the labels map straight onto the STAR-Counts files
fetched by :mod:`bindsight.io.gdc`.

This is what lets the rediscovery validation run *subtype-stratified* cohorts
(e.g. HER2-enriched breast tumors vs. adjacent normal), which is the scientific
prerequisite for recovering a subtype-specific antigen like ERBB2 — bulk
tumor-vs-normal over the whole BRCA cohort averages the HER2 signal away.

Source: cBioPortal (https://www.cbioportal.org/), Cerami et al. 2012
(doi:10.1158/2159-8290.CD-12-0095), Gao et al. 2013 (doi:10.1126/scisignal.2004088).
PAM50 subtypes: Parker et al. 2009 (doi:10.1200/JCO.2008.18.1370).
"""

from __future__ import annotations

import collections
import datetime as _dt
import hashlib
import json
import logging
from pathlib import Path
from typing import Any

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

LOG = logging.getLogger(__name__)

CBIOPORTAL_API = "https://www.cbioportal.org/api"
DEFAULT_STUDY = "brca_tcga_pan_can_atlas_2018"


@retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=2, min=2, max=16))
def _get_subtype_clinical_data(study_id: str) -> list[dict[str, Any]]:
    """GET the per-patient SUBTYPE clinical attribute for a study (retried)."""
    resp = requests.get(
        f"{CBIOPORTAL_API}/studies/{study_id}/clinical-data",
        params={
            "clinicalDataType": "PATIENT",
            "attributeId": "SUBTYPE",
            "projection": "SUMMARY",
        },
        headers={"Accept": "application/json"},
        timeout=60,
    )
    resp.raise_for_status()
    data: list[dict[str, Any]] = resp.json()
    return data


def fetch_pam50_subtypes(
    study_id: str = DEFAULT_STUDY,
    *,
    cache_dir: Path | None = None,
) -> dict[str, str]:
    """Return ``{patient_barcode: subtype_label}`` for a cBioPortal study.

    For ``brca_tcga_pan_can_atlas_2018`` the labels are the PAM50 calls
    ``BRCA_Basal``, ``BRCA_Her2``, ``BRCA_LumA``, ``BRCA_LumB``, ``BRCA_Normal``.

    Args:
        study_id: cBioPortal study id.
        cache_dir: if given, write the raw labels + provenance JSON here and
            reuse them on subsequent calls (offline after the first run).

    Returns:
        Mapping from TCGA patient barcode to subtype label.
    """
    cache_path = None
    if cache_dir is not None:
        cache_dir = Path(cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path = cache_dir / f"{study_id}_SUBTYPE.json"
        if cache_path.exists():
            cached = json.loads(cache_path.read_text())
            LOG.info("cBioPortal: using cached subtypes (%d patients)", len(cached["labels"]))
            return dict(cached["labels"])

    LOG.info("cBioPortal: fetching SUBTYPE for %s", study_id)
    rows = _get_subtype_clinical_data(study_id)
    labels = {r["patientId"]: r["value"] for r in rows if r.get("value")}
    if not labels:
        raise RuntimeError(f"cBioPortal returned no SUBTYPE labels for {study_id}")

    counts = collections.Counter(labels.values())
    LOG.info("cBioPortal: %d patients with SUBTYPE (%s)", len(labels), dict(counts))

    if cache_path is not None:
        payload = {
            "schema": "bindsight-cbioportal-subtypes/1",
            "source": "cBioPortal (https://www.cbioportal.org/)",
            "study_id": study_id,
            "attribute": "SUBTYPE",
            "retrieved_utc": _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds"),
            "n_patients": len(labels),
            "counts": dict(sorted(counts.items())),
            "labels": labels,
        }
        text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
        cache_path.write_text(text, encoding="utf-8")
        payload_sha = hashlib.sha256(text.encode()).hexdigest()
        (cache_path.parent / f"{study_id}_SUBTYPE.sha256").write_text(
            payload_sha + "\n", encoding="utf-8"
        )

    return labels


def patients_with_subtype(labels: dict[str, str], subtype: str) -> list[str]:
    """Return the sorted patient barcodes whose label equals ``subtype``."""
    return sorted(bc for bc, st in labels.items() if st == subtype)

# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Open Targets client tests with a mocked transport (no network calls)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import requests

from bindsight.targets.open_targets import _TARGET_QUERY, OpenTargetsClient


def _fake_data(ensembl_id: str) -> dict:
    return {
        "target": {
            "id": ensembl_id,
            "approvedSymbol": "ERBB2",
            "approvedName": "Erb-B2 receptor tyrosine kinase 2",
            "biotype": "protein_coding",
            "proteinIds": [
                {"id": "P04626", "source": "uniprot_swissprot"},
                {"id": "ENSP00000269571", "source": "ensembl_PRO"},
            ],
            "tractability": [
                {"modality": "Antibody", "label": "approved drug", "value": True},
                {"modality": "SmallMolecule", "label": "advanced clinical", "value": False},
            ],
            "safetyLiabilities": [{"event": "cardiotoxicity", "datasource": "literature"}],
            "associatedDiseases": {
                "count": 1,
                "rows": [
                    {
                        "score": 0.92,
                        "disease": {
                            "id": "EFO_0000305",
                            "name": "breast cancer",
                            "therapeuticAreas": [{"id": "MONDO_0045024", "name": "neoplasm"}],
                        },
                    }
                ],
            },
        }
    }


def _make_client_with_canned_response(tmp_path: Path) -> OpenTargetsClient:
    session = MagicMock(spec=requests.Session)
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"data": _fake_data("ENSG00000141736")}
    session.post.return_value = response
    session.headers = {}

    client = OpenTargetsClient(session=session, cache_subdir="opentargets_test")
    # Redirect the cache to a clean tmp_path so previous test runs don't bleed in.
    client.cache = tmp_path
    return client


def test_get_target_extracts_uniprot_and_modalities(tmp_path: Path) -> None:
    client = _make_client_with_canned_response(tmp_path)
    ev = client.get_target("ENSG00000141736")
    assert ev is not None
    assert ev.symbol == "ERBB2"
    assert ev.uniprot_ids == ["P04626"]
    assert ev.tractability_modalities == ["Antibody"]
    assert ev.safety_event_count == 1
    assert ev.top_disease_associations[0]["disease_name"] == "breast cancer"


def test_query_writes_cache(tmp_path: Path) -> None:
    client = _make_client_with_canned_response(tmp_path)
    client.query(_TARGET_QUERY, {"ensemblId": "ENSG00000141736"})
    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1
    parsed = json.loads(files[0].read_text())
    assert parsed["target"]["approvedSymbol"] == "ERBB2"


def test_query_uses_cache_on_second_call(tmp_path: Path) -> None:
    client = _make_client_with_canned_response(tmp_path)
    client.query(_TARGET_QUERY, {"ensemblId": "ENSG00000141736"})
    client.query(_TARGET_QUERY, {"ensemblId": "ENSG00000141736"})
    # First call posts; second call uses cache. (Plus the first call's caching write.)
    assert client.session.post.call_count == 1


def test_get_target_returns_none_on_missing(tmp_path: Path) -> None:
    session = MagicMock(spec=requests.Session)
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"data": {"target": None}}
    session.post.return_value = response
    session.headers = {}

    client = OpenTargetsClient(session=session, cache_subdir="opentargets_test_none")
    client.cache = tmp_path
    assert client.get_target("ENSG_DOES_NOT_EXIST") is None

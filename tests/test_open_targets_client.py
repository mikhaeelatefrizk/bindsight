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
    parsed = json.loads(files[0].read_text(encoding="utf-8"))

    assert parsed["data"]["target"]["approvedSymbol"] == "ERBB2"
    # The envelope, not decoration: an entry that does not say when and where it
    # came from cannot be told apart from one fetched against a different Open
    # Targets release, whose association scores move the ranking.
    assert parsed["endpoint"] == client.endpoint
    assert isinstance(parsed["fetched_at"], (int, float))


def test_a_stale_cache_entry_is_refetched(tmp_path: Path) -> None:
    """A warm cache from an old release used to be served forever.

    The entry had no age and the endpoint was not in its key, so a response
    fetched months ago -- possibly from a different Open Targets release, with
    different association scores -- was returned to a run whose provenance
    stamped today. Two machines, the same command, different candidate
    rankings, and nothing in either manifest saying which.
    """
    import time

    from bindsight.targets.open_targets import CACHE_MAX_AGE_DAYS

    client = _make_client_with_canned_response(tmp_path)
    client.query(_TARGET_QUERY, {"ensemblId": "ENSG00000141736"})
    assert client.session.post.call_count == 1

    cached = next(iter(tmp_path.glob("*.json")))
    envelope = json.loads(cached.read_text(encoding="utf-8"))
    envelope["fetched_at"] = time.time() - (CACHE_MAX_AGE_DAYS + 1) * 86400
    cached.write_text(json.dumps(envelope), encoding="utf-8", newline="\n")

    client.query(_TARGET_QUERY, {"ensemblId": "ENSG00000141736"})

    assert client.session.post.call_count == 2, (
        "a cache entry older than the maximum age was served instead of refetched"
    )


def test_an_entry_from_before_age_recording_is_refetched(tmp_path: Path) -> None:
    """Guards the guard: the old format must not be trusted either.

    Entries written before the cache recorded its age carry no release
    information at all, so they cannot be shown to describe the run that reads
    them.
    """
    client = _make_client_with_canned_response(tmp_path)
    client.query(_TARGET_QUERY, {"ensemblId": "ENSG00000141736"})

    cached = next(iter(tmp_path.glob("*.json")))
    legacy = json.loads(cached.read_text(encoding="utf-8"))["data"]
    cached.write_text(json.dumps(legacy), encoding="utf-8", newline="\n")

    client.query(_TARGET_QUERY, {"ensemblId": "ENSG00000141736"})

    assert client.session.post.call_count == 2


def test_the_endpoint_is_part_of_the_cache_key(tmp_path: Path) -> None:
    """Two endpoints must not share an entry."""
    client = _make_client_with_canned_response(tmp_path)
    first = client._cache_key(_TARGET_QUERY, {"ensemblId": "ENSG00000141736"})

    client.endpoint = "https://example.invalid/graphql"
    second = client._cache_key(_TARGET_QUERY, {"ensemblId": "ENSG00000141736"})

    assert first != second


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

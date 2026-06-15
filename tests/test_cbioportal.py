"""Tests for the cBioPortal PAM50 subtype fetcher (mocked HTTP, no network)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from bindsight.io import cbioportal


class _FakeResp:
    def __init__(self, payload: list[dict[str, Any]]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> list[dict[str, Any]]:
        return self._payload


_ROWS = [
    {"patientId": "TCGA-AA-0001", "value": "BRCA_Her2"},
    {"patientId": "TCGA-AA-0002", "value": "BRCA_Basal"},
    {"patientId": "TCGA-AA-0003", "value": "BRCA_Her2"},
    {"patientId": "TCGA-AA-0004", "value": ""},  # dropped (no value)
]


def test_fetch_pam50_subtypes_parses_and_caches(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls = {"n": 0}

    def fake_get(url: str, **kwargs: Any) -> _FakeResp:
        calls["n"] += 1
        return _FakeResp(_ROWS)

    monkeypatch.setattr(cbioportal.requests, "get", fake_get)

    labels = cbioportal.fetch_pam50_subtypes("study_x", cache_dir=tmp_path)
    assert labels == {
        "TCGA-AA-0001": "BRCA_Her2",
        "TCGA-AA-0002": "BRCA_Basal",
        "TCGA-AA-0003": "BRCA_Her2",
    }
    assert calls["n"] == 1

    # The cache file is written with provenance and reused (no second HTTP call).
    cache = tmp_path / "study_x_SUBTYPE.json"
    assert cache.exists()
    payload = json.loads(cache.read_text())
    assert payload["n_patients"] == 3
    assert payload["counts"]["BRCA_Her2"] == 2

    labels2 = cbioportal.fetch_pam50_subtypes("study_x", cache_dir=tmp_path)
    assert labels2 == labels
    assert calls["n"] == 1  # served from cache


def test_patients_with_subtype() -> None:
    labels = {"A": "BRCA_Her2", "B": "BRCA_Basal", "C": "BRCA_Her2"}
    assert cbioportal.patients_with_subtype(labels, "BRCA_Her2") == ["A", "C"]
    assert cbioportal.patients_with_subtype(labels, "BRCA_LumA") == []


def test_fetch_raises_when_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cbioportal.requests, "get", lambda url, **kw: _FakeResp([]))
    with pytest.raises(RuntimeError):
        cbioportal.fetch_pam50_subtypes("empty_study")

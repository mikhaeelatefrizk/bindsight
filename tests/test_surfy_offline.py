"""Tests for the SURFY offline-fallback path."""

from __future__ import annotations

import pytest

from bindsight.surfaceome import is_surface_protein, load_surfy


@pytest.fixture(autouse=True)
def _clear_surfy_cache(monkeypatch, tmp_path):
    """Force the cache miss so we always hit the offline fallback."""
    cache_path = tmp_path / "surfy_v1.uniprot.txt"
    monkeypatch.setattr("bindsight.surfaceome.surfy._surfy_cache_path", lambda: cache_path)


def test_offline_fallback_loads() -> None:
    surfy = load_surfy(allow_offline_fallback=True)
    assert isinstance(surfy, frozenset)
    assert len(surfy) > 0


def test_known_surface_antigens_present() -> None:
    surfy = load_surfy(allow_offline_fallback=True)
    # ERBB2/HER2, EGFR, MSLN
    for uid in ["P04626", "P00533", "Q13421"]:
        assert uid in surfy, f"{uid} missing from offline SURFY fallback"


def test_is_surface_protein() -> None:
    assert is_surface_protein("P04626") is True
    assert is_surface_protein("DEFINITELY_NOT_REAL") is False


def test_no_fallback_raises_when_disabled(tmp_path, monkeypatch) -> None:
    cache_path = tmp_path / "missing.txt"
    monkeypatch.setattr("bindsight.surfaceome.surfy._surfy_cache_path", lambda: cache_path)
    with pytest.raises(FileNotFoundError):
        load_surfy(allow_offline_fallback=False)

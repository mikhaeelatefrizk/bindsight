# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the SURFY offline-fallback path."""

from __future__ import annotations

import pytest

from bindsight.surfaceome import is_surface_protein, load_surfy


@pytest.fixture(autouse=True)
def _clear_surfy_cache(monkeypatch, tmp_path):
    """Force the cache miss so we exercise the packaged lists."""
    cache_path = tmp_path / "surfy_v1.uniprot.txt"
    monkeypatch.setattr("bindsight.surfaceome.surfy._surfy_cache_path", lambda: cache_path)


@pytest.fixture
def _no_vendored_list(monkeypatch):
    """Simulate an install missing the vendored full list."""
    monkeypatch.setattr("bindsight.surfaceome.surfy.load_vendored_surfy", lambda: None)


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


@pytest.mark.usefixtures("_no_vendored_list")
def test_no_fallback_raises_when_no_full_list_available() -> None:
    """With no cache and no vendored list, refusing the tiny fallback still errors.

    The vendored full list now satisfies ``allow_offline_fallback=False`` on its
    own — that flag exists to stop a run silently using ten proteins, and the
    vendored list is the real 2,886-entry SURFY set. The guarantee being tested
    here is the remaining one: if *no* full list can be found, a caller who
    refused the degraded fallback gets an error rather than bad results.
    """
    with pytest.raises(FileNotFoundError, match="No full SURFY list available"):
        load_surfy(allow_offline_fallback=False)


@pytest.mark.usefixtures("_no_vendored_list")
def test_tiny_fallback_used_only_when_permitted() -> None:
    """Without the vendored list, the ten-protein set is the explicit opt-in."""
    surfy = load_surfy(allow_offline_fallback=True)
    assert 0 < len(surfy) <= 20
    assert "P04626" in surfy

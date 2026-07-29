# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The vendored SURFY surfaceome list is the discovery half's foundation.

Before it was vendored, the surfaceome could not be populated at all: the
upstream spreadsheet host began serving an HTML landing page (so
``pandas.read_excel`` raised ``BadZipFile``) and the mirror serves a Git-LFS
pointer. A fresh install either hard-failed or silently degraded to ten
proteins and surfaced almost nothing.

These tests guard the replacement: that the list ships, is complete, is
license-attributed, and that resolving it touches no network.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from bindsight.surfaceome.surfy import (
    SURFY_PROTEIN_COUNT,
    _download_xlsx,
    load_surfy,
    load_vendored_surfy,
)

# Antigens the benchmarks and the e2e test depend on being classified surface.
BENCHMARK_ANTIGENS = {
    "P04626": "ERBB2 / HER2",
    "P00533": "EGFR",
    "Q13421": "MSLN",
    "P56747": "CLDN6",
    "Q96NY8": "NECTIN4",
    "Q04609": "FOLH1 / PSMA",
    "P06731": "CEACAM5",
}


def test_vendored_list_ships_and_is_complete() -> None:
    """The full canonical list is present, at the published size."""
    surfy = load_vendored_surfy()
    assert surfy is not None, "vendored SURFY list missing from the install"
    assert len(surfy) == SURFY_PROTEIN_COUNT


def test_vendored_list_covers_the_benchmark_antigens() -> None:
    """Every antigen the published benchmarks score must be in the list."""
    surfy = load_vendored_surfy()
    assert surfy is not None
    missing = {a: n for a, n in BENCHMARK_ANTIGENS.items() if a not in surfy}
    assert not missing, f"benchmark antigens missing from vendored SURFY: {missing}"


def test_accessions_look_like_uniprot() -> None:
    """Entries are accessions (P04626), not entry names (ERBB2_HUMAN).

    The upstream file that seeds the generator lists entry names; shipping those
    unresolved would silently match nothing, since the pipeline joins on
    accessions.
    """
    surfy = load_vendored_surfy()
    assert surfy is not None
    for acc in surfy:
        assert "_" not in acc, f"{acc} looks like an entry name, not an accession"
        assert 6 <= len(acc) <= 10, f"{acc} is not a plausible UniProt accession"
        assert acc[0].isalpha()
        assert acc.isalnum()


def test_vendored_list_carries_its_licence_attribution() -> None:
    """SURFY is CC-BY; redistribution requires attribution in the file."""
    from importlib import resources

    text = (
        resources.files("bindsight.surfaceome")
        .joinpath("data", "surfy_v1.uniprot.txt")
        .read_text("utf-8")
    )
    header = "\n".join(ln for ln in text.splitlines() if ln.startswith("#"))
    assert "CC BY" in header
    assert "Bausch-Fluck" in header
    assert "10.1073/pnas.1808790115" in header
    assert "build_surfy_list.py" in header


def test_load_surfy_prefers_the_full_list_over_the_tiny_fallback() -> None:
    """The default path yields the real surfaceome, not ten proteins."""
    assert len(load_surfy()) == SURFY_PROTEIN_COUNT


def test_user_cache_still_wins(tmp_path, monkeypatch) -> None:
    """A refreshed cache overrides the vendored list, so users can update."""
    cache = tmp_path / "surfy_v1.uniprot.txt"
    cache.write_text("# refreshed\nP04626\nP00533\n", encoding="utf-8")
    monkeypatch.setattr("bindsight.surfaceome.surfy._surfy_cache_path", lambda: cache)
    assert load_surfy() == frozenset({"P04626", "P00533"})


def test_resolving_the_surfaceome_touches_no_network() -> None:
    """Discovery must not depend on a reachable SURFY host.

    Runs in a clean subprocess with sockets disabled, which is the only honest
    way to assert "no network" — an in-process monkeypatch would not catch a
    call made through a different code path.
    """
    code = (
        # Block name resolution and connection setup rather than gutting
        # socket.socket, which would break ssl's class hierarchy at import time
        # and fail for reasons that have nothing to do with bindsight.
        "import socket\n"
        "def _blocked(*a, **k):\n"
        "    raise AssertionError('network access attempted')\n"
        "socket.getaddrinfo = _blocked\n"
        "socket.create_connection = _blocked\n"
        "socket.socket.connect = _blocked\n"
        "from bindsight.surfaceome.surfy import load_surfy\n"
        "print(len(load_surfy(allow_offline_fallback=False)))\n"
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == str(SURFY_PROTEIN_COUNT)


class _FakeResponse:
    """Minimal stand-in for a requests response."""

    def __init__(self, content: bytes, content_type: str = "application/octet-stream") -> None:
        self.content = content
        self.headers = {"content-type": content_type}

    def raise_for_status(self) -> None:
        """No-op; these fixtures all model HTTP 200."""


@pytest.mark.parametrize(
    ("payload", "content_type", "expected"),
    [
        (b"<!DOCTYPE html><html><body>SURFY</body></html>", "text/html", "an HTML page"),
        (b"version https://git-lfs.github.com/spec/v1\noid sha256:ab\n", "", "Git-LFS pointer"),
        (b"\x00\x01\x02", "application/octet-stream", "not a zip/xlsx container"),
    ],
)
def test_refresh_rejects_non_spreadsheets_with_a_clear_error(
    monkeypatch, payload: bytes, content_type: str, expected: str
) -> None:
    """A 200 carrying the wrong bytes must say so, not raise BadZipFile.

    Both known hosts answer 200 with something that is not a spreadsheet. The
    old code passed those bytes straight to openpyxl, and the user saw
    ``BadZipFile: File is not a zip file``.
    """
    monkeypatch.setattr(
        "bindsight.surfaceome.surfy.requests.get",
        lambda *a, **k: _FakeResponse(payload, content_type),
    )
    with pytest.raises(RuntimeError, match=expected):
        _download_xlsx("https://example.invalid/table.xlsx")


def test_refresh_accepts_a_real_zip_container(monkeypatch) -> None:
    """A genuine .xlsx (a zip) passes the guard untouched."""
    monkeypatch.setattr(
        "bindsight.surfaceome.surfy.requests.get",
        lambda *a, **k: _FakeResponse(b"PK\x03\x04rest-of-the-xlsx"),
    )
    assert _download_xlsx("https://example.invalid/table.xlsx").startswith(b"PK")

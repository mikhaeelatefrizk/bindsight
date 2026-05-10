"""AlphaFoldDB client tests with mocked transport."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import requests

from bindsight.structures.alphafolddb import AlphaFoldDBClient


def _make_client(
    tmp_path: Path, *, payload: bytes | None = None, status: int = 200
) -> AlphaFoldDBClient:
    session = MagicMock(spec=requests.Session)
    response = MagicMock()
    if status != 200:
        http_error = requests.HTTPError(response=MagicMock(status_code=status))
        response.raise_for_status.side_effect = http_error
    else:
        response.raise_for_status.return_value = None
        response.content = payload or b"# fake mmCIF\ndata_AF\n"
    session.get.return_value = response
    session.headers = {}

    client = AlphaFoldDBClient(session=session, cache_subdir="afdb_test")
    client.cache = tmp_path
    return client


def test_fetch_writes_cache(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    p = client.fetch("P04626")
    assert p is not None
    assert p.exists()
    assert p.read_bytes().startswith(b"# fake mmCIF")


def test_fetch_uses_cache_on_second_call(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    client.fetch("P04626")
    client.fetch("P04626")
    assert client.session.get.call_count == 1


def test_fetch_returns_none_on_404(tmp_path: Path) -> None:
    client = _make_client(tmp_path, status=404)
    assert client.fetch("DOES_NOT_EXIST") is None

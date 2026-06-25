# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""AlphaFoldDB structure fetcher.

Pulls predicted structures by UniProt ID from EBI's AlphaFold Database.
All AlphaFoldDB models are CC BY 4.0; we cache them locally to avoid
hammering the public API.

Endpoint pattern (mmCIF):
    https://alphafold.ebi.ac.uk/files/AF-{uniprot_id}-F1-model_v6.cif

API docs: https://alphafold.ebi.ac.uk/api-docs
"""

from __future__ import annotations

import logging
from pathlib import Path

import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from bindsight.io.paths import cache_dir

LOG = logging.getLogger(__name__)

ALPHAFOLDDB_BASE = "https://alphafold.ebi.ac.uk/files"
# AlphaFoldDB bumps the model version periodically (v4 → v6 as of 2026); the old
# URLs 404. Track the current release.
DEFAULT_MODEL_VERSION = "v6"


class AlphaFoldDBClient:
    """Cached AlphaFoldDB mmCIF downloader."""

    def __init__(
        self,
        cache_subdir: str = "alphafolddb",
        timeout: float = 60.0,
        session: requests.Session | None = None,
        model_version: str = DEFAULT_MODEL_VERSION,
    ) -> None:
        self.cache = cache_dir(cache_subdir)
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers.setdefault(
            "User-Agent", "bindsight/0.0.1 (+https://github.com/mikhaeelatefrizk/bindsight)"
        )
        self.model_version = model_version

    def _url(self, uniprot_id: str) -> str:
        return f"{ALPHAFOLDDB_BASE}/AF-{uniprot_id}-F1-model_{self.model_version}.cif"

    def _cache_path(self, uniprot_id: str) -> Path:
        return self.cache / f"AF-{uniprot_id}-F1-model_{self.model_version}.cif"

    @retry(
        retry=retry_if_exception_type(requests.RequestException),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        stop=stop_after_attempt(5),
        reraise=True,
    )
    def _download(self, url: str) -> bytes:
        resp = self.session.get(url, timeout=self.timeout)
        resp.raise_for_status()
        return resp.content

    def fetch(self, uniprot_id: str, *, force: bool = False) -> Path | None:
        """Download the AlphaFoldDB mmCIF for a UniProt ID.

        Returns the path to the cached mmCIF file, or ``None`` if AlphaFoldDB
        has no model for the given UniProt accession (HTTP 404).
        """
        cached = self._cache_path(uniprot_id)
        if cached.exists() and not force:
            return cached

        url = self._url(uniprot_id)
        try:
            payload = self._download(url)
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 404:
                LOG.warning("AlphaFoldDB has no model for %s", uniprot_id)
                return None
            raise

        cached.write_bytes(payload)
        return cached

    def fetch_many(
        self,
        uniprot_ids: list[str],
        *,
        force: bool = False,
    ) -> dict[str, Path | None]:
        """Bulk-fetch; returns ``{uniprot_id: path-or-None}``."""
        results: dict[str, Path | None] = {}
        for uid in uniprot_ids:
            results[uid] = self.fetch(uid, force=force)
        return results

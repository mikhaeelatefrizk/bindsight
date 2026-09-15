# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Open Targets Platform GraphQL client.

Open Targets aggregates target-disease association evidence from ~20 sources
(literature, genetic associations, somatic mutations, drug evidence, etc.).
We use it to enrich differentially-expressed candidates with druggability,
known disease links, safety liabilities, and tractability scores.

API docs: https://platform-docs.opentargets.org/data-access/graphql-api
Endpoint: https://api.platform.opentargets.org/api/v4/graphql

Rate limits are generous but not unlimited. We back off with tenacity.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time as _time
from pathlib import Path
from typing import Any

import requests
from pydantic import BaseModel, ConfigDict, Field
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from bindsight.io.paths import cache_dir

LOG = logging.getLogger(__name__)

OPEN_TARGETS_URL = "https://api.platform.opentargets.org/api/v4/graphql"

# A focused query: per Ensembl gene ID, fetch the bits we actually use for
# target prioritization downstream. Kept small to stay friendly to the API.
_TARGET_QUERY = """
query Target($ensemblId: String!) {
  target(ensemblId: $ensemblId) {
    id
    approvedSymbol
    approvedName
    biotype
    proteinIds {
      id
      source
    }
    tractability {
      modality
      label
      value
    }
    safetyLiabilities {
      event
      datasource
    }
    associatedDiseases(page: { index: 0, size: 20 }) {
      count
      rows {
        score
        disease {
          id
          name
          therapeuticAreas {
            id
            name
          }
        }
      }
    }
  }
}
"""


class TargetEvidence(BaseModel):
    """Slim record of Open Targets evidence for a single gene."""

    model_config = ConfigDict(extra="ignore")

    ensembl_id: str
    symbol: str | None = None
    name: str | None = None
    biotype: str | None = None
    uniprot_ids: list[str] = Field(default_factory=list)
    tractability_modalities: list[str] = Field(
        default_factory=list,
        description="e.g. ['Antibody', 'SmallMolecule', 'PROTAC']. Sourced from "
        "tractability.value=true rows.",
    )
    safety_event_count: int = 0
    top_disease_associations: list[dict[str, Any]] = Field(default_factory=list)


#: How long an Open Targets response may be reused. Their releases are roughly
#: quarterly and move association scores, which move the ranking; an entry older
#: than this describes a different release from the one a run claims to have
#: used. Refetching costs one request against a cache that is otherwise warm.
CACHE_MAX_AGE_DAYS = 30


class OpenTargetsClient:
    """Cached, retrying GraphQL client for Open Targets."""

    def __init__(
        self,
        endpoint: str = OPEN_TARGETS_URL,
        cache_subdir: str = "opentargets",
        timeout: float = 30.0,
        session: requests.Session | None = None,
    ) -> None:
        self.endpoint = endpoint
        self.cache = cache_dir(cache_subdir)
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers.setdefault(
            "User-Agent", "bindsight/0.0.1 (+https://github.com/mikhaeelatefrizk/bindsight)"
        )

    def _cache_key(self, query: str, variables: dict[str, Any]) -> Path:
        """Where a response is cached.

        The endpoint is part of the key, and the file records when it was
        fetched. Neither was true before: the key was a hash of the query text
        and variables alone, and a hit was returned unconditionally however old
        it was and whichever endpoint produced it. So a warm cache from an
        earlier Open Targets release supplied that release's association scores
        to today's run while the provenance recorded today's date -- two
        machines, the same command, different candidate rankings, and nothing in
        either manifest saying which.

        The repository already accepted exactly this reasoning for the
        surfaceome (``tests/test_silent_success.py`` -- "two runs on two machines
        could use different surfaceome lists ... and nothing in either manifest
        would say which"). Open Targets is a larger input to the ranking than
        the surfaceome is.
        """
        payload = json.dumps(
            {"endpoint": self.endpoint, "query": query, "variables": variables},
            sort_keys=True,
        )
        sig = hashlib.sha256(payload.encode()).hexdigest()
        return self.cache / f"{sig}.json"

    @retry(
        retry=retry_if_exception_type(requests.RequestException),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        stop=stop_after_attempt(5),
        reraise=True,
    )
    def _post(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        resp = self.session.post(
            self.endpoint,
            json={"query": query, "variables": variables},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        body = resp.json()
        if "errors" in body:
            raise RuntimeError(f"Open Targets GraphQL errors: {body['errors']}")
        data: dict[str, Any] = body["data"]
        return data

    def query(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        """Execute a raw GraphQL query, with on-disk caching.

        A cached entry older than :data:`CACHE_MAX_AGE_DAYS` is refetched. The
        cache used to have no expiry at all, so a response fetched months ago
        was served to a run whose provenance stamped today -- the run was
        reproducible against that machine's disk and against nothing else.
        """
        key = self._cache_key(query, variables)
        if key.exists():
            try:
                envelope = json.loads(key.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                envelope = None
            if isinstance(envelope, dict) and "fetched_at" in envelope:
                age = _time.time() - float(envelope.get("fetched_at") or 0)
                if age <= CACHE_MAX_AGE_DAYS * 86400:
                    cached: dict[str, Any] = envelope.get("data") or {}
                    return cached
                LOG.info(
                    "Open Targets cache entry is %.0f days old; refetching",
                    age / 86400,
                )
            else:
                # An entry from before the cache recorded its age. Its release
                # is unknown, so it cannot be trusted to describe today's run.
                LOG.info("Open Targets cache entry predates age recording; refetching")

        data = self._post(query, variables)
        key.write_text(
            json.dumps({"fetched_at": _time.time(), "endpoint": self.endpoint, "data": data}),
            encoding="utf-8",
            newline="\n",
        )
        return data

    def get_target(self, ensembl_id: str) -> TargetEvidence | None:
        """Fetch the target evidence record for an Ensembl gene ID.

        Returns ``None`` if Open Targets has no record for the gene.
        """
        data = self.query(_TARGET_QUERY, {"ensemblId": ensembl_id})
        t = data.get("target")
        if t is None:
            return None

        uniprot_ids = [
            p["id"] for p in (t.get("proteinIds") or []) if p.get("source") == "uniprot_swissprot"
        ]
        modalities = sorted(
            {row["modality"] for row in (t.get("tractability") or []) if row.get("value") is True}
        )
        diseases = [
            {
                "score": row["score"],
                "disease_id": row["disease"]["id"],
                "disease_name": row["disease"]["name"],
                "therapeutic_areas": [ta["name"] for ta in row["disease"]["therapeuticAreas"]],
            }
            for row in (t.get("associatedDiseases", {}) or {}).get("rows", [])
        ]
        return TargetEvidence(
            ensembl_id=t["id"],
            symbol=t.get("approvedSymbol"),
            name=t.get("approvedName"),
            biotype=t.get("biotype"),
            uniprot_ids=uniprot_ids,
            tractability_modalities=modalities,
            safety_event_count=len(t.get("safetyLiabilities") or []),
            top_disease_associations=diseases,
        )

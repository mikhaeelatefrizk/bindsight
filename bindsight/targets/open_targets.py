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
        sig = hashlib.sha256((query + json.dumps(variables, sort_keys=True)).encode()).hexdigest()
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
        return body["data"]

    def query(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        """Execute a raw GraphQL query, with on-disk caching by query hash."""
        key = self._cache_key(query, variables)
        if key.exists():
            return json.loads(key.read_text())
        data = self._post(query, variables)
        key.write_text(json.dumps(data))
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

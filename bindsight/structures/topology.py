# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Membrane topology from UniProt (extracellular-domain awareness).

An antibody or a de novo mini-binder can only reach the **extracellular** part of
a cell-surface protein. Designing against the whole chain — which usually includes
a transmembrane helix and a cytoplasmic tail — wastes effort on regions a binder
can never touch. UniProt curates per-residue membrane topology; this module pulls
it and exposes the extracellular ranges so discovery can target the ECD.

Endpoint (JSON):
    https://rest.uniprot.org/uniprotkb/{acc}.json?fields=ft_transmem,ft_topo_dom,ft_signal

Cached on disk like the AlphaFoldDB client. Degrades gracefully: a network/parse
failure or an un-annotated entry returns ``None`` so discovery falls back to
whole-surface design rather than crashing.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from bindsight.io.paths import cache_dir

LOG = logging.getLogger(__name__)

UNIPROT_BASE = "https://rest.uniprot.org/uniprotkb"
_FIELDS = "ft_transmem,ft_topo_dom,ft_signal"


@dataclass(frozen=True)
class Topology:
    """Parsed membrane topology for one UniProt accession (1-based residue ranges)."""

    uniprot_id: str
    extracellular_ranges: tuple[tuple[int, int], ...]
    transmembrane_ranges: tuple[tuple[int, int], ...]
    signal_peptide: tuple[int, int] | None
    #: Omega-site residue of a GPI anchor, when UniProt annotates one.
    #:
    #: A GPI-anchored protein is tethered to the outer leaflet by a lipid rather
    #: than by a transmembrane helix, so it has no transmembrane segment — and
    #: UniProt annotates topological domains *relative to* transmembrane
    #: segments, so it has none of those either. Reading extracellular extent
    #: from topological domains alone therefore classified an entire class of
    #: cell-surface protein as having nothing a binder can reach. MSLN
    #: (Q13421) is the clearest case: no Transmembrane feature, no Topological
    #: domain, one Lipidation reading "GPI-anchor amidated serine" — and it is
    #: the target of multiple clinical antibody-drug conjugates and CAR-T
    #: programmes. CEACAM5, FOLR1 and CD59 have the same shape.
    gpi_anchor: int | None = None

    @property
    def is_gpi_anchored(self) -> bool:
        """True if UniProt annotates a GPI anchor and no transmembrane segment."""
        return self.gpi_anchor is not None and not self.transmembrane_ranges

    @property
    def has_extracellular(self) -> bool:
        """True if any part of the chain is annotated as reachable from outside.

        A GPI-anchored protein counts: its whole mature chain sits outside the
        membrane. This returned ``False`` for every one of them, and with
        ``require_extracellular_domain`` enabled that dropped them from design
        carry-forward as "not antibody-accessible" — the opposite of the truth
        for some of the best-validated antibody targets there are.
        """
        return bool(self.extracellular_ranges)

    def extracellular_residues(self) -> set[int]:
        """All residue numbers inside extracellular topological domains."""
        out: set[int] = set()
        for s, e in self.extracellular_ranges:
            out.update(range(s, e + 1))
        return out

    def fraction_extracellular(self, residues: list[int]) -> float | None:
        """Fraction of ``residues`` that fall in an extracellular domain.

        ``None`` if ``residues`` is empty; ``0.0`` if the protein has no annotated
        extracellular domain (nothing a binder can reach).
        """
        if not residues:
            return None
        ecd = self.extracellular_residues()
        if not ecd:
            return 0.0
        return sum(1 for r in residues if r in ecd) / len(residues)


def parse_topology(uniprot_id: str, data: dict[str, Any]) -> Topology:
    """Parse a UniProt entry JSON into a :class:`Topology` (pure; no I/O)."""
    extracellular: list[tuple[int, int]] = []
    transmembrane: list[tuple[int, int]] = []
    signal: tuple[int, int] | None = None
    gpi: int | None = None
    propeptide: tuple[int, int] | None = None
    for feat in data.get("features", []):
        loc = feat.get("location", {})
        start = loc.get("start", {}).get("value")
        end = loc.get("end", {}).get("value")
        if start is None or end is None:
            continue  # uncertain/fuzzy location — skip
        rng = (int(start), int(end))
        ftype = feat.get("type")
        desc = (feat.get("description") or "").strip().lower()
        if ftype == "Topological domain" and desc.startswith("extracellular"):
            extracellular.append(rng)
        elif ftype == "Transmembrane":
            transmembrane.append(rng)
        elif ftype == "Signal" and signal is None:
            signal = rng
        elif ftype == "Lipidation" and "gpi-anchor" in desc and gpi is None:
            # The omega site: the residue the glycolipid is amidated onto.
            gpi = rng[0]
        elif ftype == "Propeptide" and propeptide is None:
            propeptide = rng

    if gpi is not None and not transmembrane and not extracellular:
        # A GPI-anchored protein has no transmembrane helix, so UniProt gives it
        # no topological domains either — the annotation is defined relative to
        # a membrane-spanning segment. Its mature chain nonetheless sits wholly
        # outside the cell, which is why MSLN and CEACAM5 are antibody targets.
        #
        # The reachable region is the mature chain: everything after the signal
        # peptide, up to and including the omega site. Residues beyond it are
        # the propeptide UniProt marks "Removed in mature form" — they are gone
        # before the protein reaches the surface, so designing against them
        # would target a sequence that does not exist on a cell. For MSLN that
        # is 37-598 of 622: signal 1-36, omega site 598, propeptide 599-622.
        start = (signal[1] + 1) if signal else 1
        end = gpi
        if propeptide is not None and propeptide[0] <= gpi:
            # An omega site inside the cleaved region would make the mature
            # chain end before it begins; trust the propeptide boundary.
            end = propeptide[0] - 1
        if end >= start:
            extracellular.append((start, end))

    return Topology(
        uniprot_id=uniprot_id,
        extracellular_ranges=tuple(extracellular),
        transmembrane_ranges=tuple(transmembrane),
        signal_peptide=signal,
        gpi_anchor=gpi,
    )


class UniProtTopologyClient:
    """Cached UniProt membrane-topology fetcher."""

    def __init__(
        self,
        cache_subdir: str = "uniprot_topology",
        timeout: float = 60.0,
        session: requests.Session | None = None,
    ) -> None:
        self.cache = cache_dir(cache_subdir)
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers.setdefault(
            "User-Agent", "bindsight/0.0.1 (+https://github.com/mikhaeelatefrizk/bindsight)"
        )

    def _url(self, acc: str) -> str:
        return f"{UNIPROT_BASE}/{acc}.json?fields={_FIELDS}"

    def _cache_path(self, acc: str) -> Path:
        return self.cache / f"{acc}.topology.json"

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

    def fetch(self, uniprot_id: str, *, force: bool = False) -> Topology | None:
        """Fetch + parse topology for a UniProt accession.

        Returns ``None`` on a 404, a network failure, or unparseable JSON, so the
        caller falls back to whole-surface design.
        """
        if not uniprot_id:
            return None
        cached = self._cache_path(uniprot_id)
        if cached.exists() and not force:
            try:
                return parse_topology(uniprot_id, json.loads(cached.read_text(encoding="utf-8")))
            except Exception as e:
                LOG.warning("cached topology unreadable for %s (%s); refetching", uniprot_id, e)

        try:
            payload = self._download(self._url(uniprot_id))
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 404:
                LOG.warning("UniProt has no entry for %s", uniprot_id)
                return None
            LOG.warning("UniProt topology fetch failed for %s: %s", uniprot_id, e)
            return None
        except requests.RequestException as e:
            LOG.warning("UniProt topology fetch failed for %s: %s", uniprot_id, e)
            return None

        try:
            data = json.loads(payload)
        except json.JSONDecodeError as e:
            LOG.warning("UniProt returned non-JSON for %s: %s", uniprot_id, e)
            return None
        cached.write_bytes(payload)
        return parse_topology(uniprot_id, data)

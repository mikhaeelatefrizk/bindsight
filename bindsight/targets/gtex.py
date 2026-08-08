# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Normal-tissue expression from GTEx (on-target / off-tumor safety).

A good antibody / ADC target is over-expressed in tumour but **low in vital normal
tissues** — otherwise the binder attacks healthy heart, brain, liver or lung
(on-target/off-tumor toxicity). bindsight ranks candidates from tumour RNA-seq;
this module adds the missing other half: median expression across normal tissues,
straight from GTEx v8 (the reference normal-tissue RNA atlas), so a candidate's
vital-tissue expression can gate it.

Data (real, cached): GTEx v8 gene-level median TPM per tissue (GCT), ~7 MB:
    https://storage.googleapis.com/adult-gtex/bulk-gex/v8/rna-seq/
        GTEx_Analysis_2017-06-05_v8_RNASeQCv1.1.9_gene_median_tpm.gct.gz

Fails closed. The gate exists to keep unsafe targets out, so "we could not check"
must never read as "checked and safe": an unavailable reference raises
:class:`GTExUnavailableError`, and a gene the reference does not cover is reported
as ``unassessed`` (:meth:`GTExTissueExpression.assess`) rather than silently
passing the gate.
"""

from __future__ import annotations

import contextlib
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import pandas as pd
import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from bindsight.io.paths import cache_dir

LOG = logging.getLogger(__name__)

GTEX_MEDIAN_TPM_URL = (
    "https://storage.googleapis.com/adult-gtex/bulk-gex/v8/rna-seq/"
    "GTEx_Analysis_2017-06-05_v8_RNASeQCv1.1.9_gene_median_tpm.gct.gz"
)


class GTExUnavailableError(RuntimeError):
    """The GTEx reference could not be obtained or parsed.

    Raised instead of returning "no expression found", which a caller would read
    as a clean safety verdict on a target whose normal-tissue expression was in
    fact never checked.
    """


@dataclass(frozen=True)
class TissueSafety:
    """One gene's normal-tissue verdict against a vital-tissue TPM ceiling."""

    status: Literal["safe", "unsafe", "unassessed"]
    max_tpm: float | None
    reason: str


def normalize_tissue(name: str) -> str:
    """Normalise a GTEx tissue label to a config-friendly key.

    'Heart - Left Ventricle' -> 'heart_left_ventricle'; 'Brain - Cortex' ->
    'brain_cortex'; 'Liver' -> 'liver'.
    """
    return name.strip().lower().replace(" - ", "_").replace(" ", "_").replace("-", "_")


class GTExTissueExpression:
    """Cached GTEx median-TPM-by-tissue lookup, keyed by Ensembl gene id."""

    def __init__(
        self,
        cache_subdir: str = "gtex",
        url: str = GTEX_MEDIAN_TPM_URL,
        gct_path: Path | str | None = None,
        timeout: float = 180.0,
        session: requests.Session | None = None,
    ) -> None:
        self.cache = cache_dir(cache_subdir)
        self.url = url
        # When provided (tests / vendored data) the GCT is read directly, no network.
        self.gct_path = Path(gct_path) if gct_path else None
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers.setdefault(
            "User-Agent", "bindsight/0.0.1 (+https://github.com/mikhaeelatefrizk/bindsight)"
        )
        self._df: pd.DataFrame | None = None

    def _parquet_cache_path(self) -> Path:
        return self.cache / "gene_median_tpm.parquet"

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

    def _ensure_gct(self) -> Path:
        cached = self.cache / "gene_median_tpm.gct.gz"
        if cached.exists():
            return cached
        try:
            payload = self._download(self.url)
        except requests.RequestException as e:
            raise GTExUnavailableError(f"GTEx download failed: {e}") from e
        cached.write_bytes(payload)
        return cached

    def _load(self) -> pd.DataFrame:
        """Return a DataFrame indexed by unversioned Ensembl id, columns = tissues.

        Raises:
            GTExUnavailableError: The reference is missing or unparseable, so no
                normal-tissue claim can be made about any gene.
        """
        if self._df is not None:
            return self._df
        # Fast path: parsed parquet cache (only for the live/downloaded source).
        parq = self._parquet_cache_path()
        if self.gct_path is None and parq.exists():
            try:
                self._df = pd.read_parquet(parq)
                return self._df
            except Exception as e:  # corrupt cache — rebuild
                LOG.warning("GTEx parquet cache unreadable (%s); rebuilding", e)

        gct = self.gct_path or self._ensure_gct()
        if not Path(gct).exists():
            raise GTExUnavailableError(f"GTEx reference not found at {gct}")
        try:
            df = pd.read_csv(gct, sep="\t", skiprows=2)
            df["__gene"] = df["Name"].str.split(".").str[0]
            df = df.drop(columns=["Name", "Description"]).set_index("__gene")
            df.columns = [normalize_tissue(c) for c in df.columns]
            df = df[~df.index.duplicated(keep="first")]
        except Exception as e:
            raise GTExUnavailableError(f"GTEx GCT parse failed for {gct}: {e}") from e
        self._df = df
        if self.gct_path is None:
            # parquet cache is an optimisation, not required
            with contextlib.suppress(Exception):
                df.to_parquet(parq)
        return df

    def max_expression(self, ensembl_id: str, tissues: list[str]) -> float | None:
        """Max median TPM of ``ensembl_id`` across ``tissues``.

        ``None`` means *not measured here* — no gene id, the gene isn't in GTEx,
        or none of the requested tissues exist. It never means "low expression";
        use :meth:`assess` to get that distinction as a verdict.

        Raises:
            GTExUnavailableError: The reference itself is unavailable.
        """
        if not ensembl_id:
            return None
        df = self._load()
        gene = ensembl_id.split(".")[0]
        if gene not in df.index:
            return None
        cols = [normalize_tissue(t) for t in tissues]
        cols = [c for c in cols if c in df.columns]
        if not cols:
            return None
        return float(df.loc[gene, cols].max())

    def assess(self, ensembl_id: str, tissues: list[str], max_tpm: float) -> TissueSafety:
        """Verdict for one gene against the vital-tissue ceiling ``max_tpm``.

        Args:
            ensembl_id: Ensembl gene id (a version suffix is stripped).
            tissues: Vital tissues to check, in config spelling.
            max_tpm: Median-TPM ceiling above which the target is unsafe.

        Returns:
            A :class:`TissueSafety` whose ``status`` separates a measured pass
            (``safe``) from an absent measurement (``unassessed``). Only ``safe``
            may be presented as having cleared the normal-tissue gate.

        Raises:
            GTExUnavailableError: The reference is unavailable, so the gate cannot
                be applied to any candidate at all.
        """
        value = self.max_expression(ensembl_id, tissues)
        if value is None:
            return TissueSafety(
                status="unassessed",
                max_tpm=None,
                reason=f"{ensembl_id or '<no gene id>'} has no GTEx median-TPM entry for "
                f"{', '.join(tissues) or '<no tissues>'}",
            )
        if value > max_tpm:
            return TissueSafety(
                status="unsafe",
                max_tpm=value,
                reason=f"median TPM {value:.1f} exceeds the {max_tpm:.1f} vital-tissue ceiling",
            )
        return TissueSafety(
            status="safe",
            max_tpm=value,
            reason=f"median TPM {value:.1f} is at or below the {max_tpm:.1f} vital-tissue ceiling",
        )

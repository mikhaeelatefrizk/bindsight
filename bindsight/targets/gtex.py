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

Degrades gracefully: a network failure or an unmapped gene returns ``None`` so
discovery keeps going (the candidate simply isn't tissue-gated).
"""

from __future__ import annotations

import contextlib
import logging
from pathlib import Path

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

    def _ensure_gct(self) -> Path | None:
        cached = self.cache / "gene_median_tpm.gct.gz"
        if cached.exists():
            return cached
        try:
            payload = self._download(self.url)
        except requests.RequestException as e:
            LOG.warning("GTEx download failed (%s); skipping normal-tissue safety", e)
            return None
        cached.write_bytes(payload)
        return cached

    def _load(self) -> pd.DataFrame | None:
        """Return a DataFrame indexed by unversioned Ensembl id, columns = tissues."""
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
        if gct is None or not Path(gct).exists():
            return None
        try:
            df = pd.read_csv(gct, sep="\t", skiprows=2)
            df["__gene"] = df["Name"].str.split(".").str[0]
            df = df.drop(columns=["Name", "Description"]).set_index("__gene")
            df.columns = [normalize_tissue(c) for c in df.columns]
            df = df[~df.index.duplicated(keep="first")]
        except Exception as e:
            LOG.warning("GTEx GCT parse failed (%s); skipping normal-tissue safety", e)
            return None
        self._df = df
        if self.gct_path is None:
            # parquet cache is an optimisation, not required
            with contextlib.suppress(Exception):
                df.to_parquet(parq)
        return df

    def max_expression(self, ensembl_id: str, tissues: list[str]) -> float | None:
        """Max median TPM of ``ensembl_id`` across ``tissues``.

        ``None`` if GTEx is unavailable, the gene isn't in GTEx, or none of the
        requested tissues exist — so the caller treats it as "unknown", not "safe".
        """
        if not ensembl_id:
            return None
        df = self._load()
        if df is None:
            return None
        gene = ensembl_id.split(".")[0]
        if gene not in df.index:
            return None
        cols = [normalize_tissue(t) for t in tissues]
        cols = [c for c in cols if c in df.columns]
        if not cols:
            return None
        return float(df.loc[gene, cols].max())

"""SURFY surfaceome filter.

SURFY is a curated list of ~2,886 human surface proteins published by
Bausch-Fluck et al. (PNAS 2018). It's a high-confidence subset of the
predicted human surfaceome based on a machine-learned classifier trained on
mass-spec evidence.

Distribution: the SURFY web tool at https://wlab.ethz.ch/surfaceome serves
the list as a download. The CC-BY-licensed list itself is small enough to
vendor — but to keep the wheel light and to allow the user to update the
list independently, we lazy-fetch it on first use and cache it.

The on-disk cache layout (under user cache root):

    surfy/
        surfy_v1.tsv           # raw download, columns include UniProt accession
        surfy_v1.uniprot.txt   # one accession per line, used at query time

A small bundled fallback list (the names of widely-cited surface antigens)
ships with the package so the discovery half can run offline for tests.
"""

from __future__ import annotations

import logging
from importlib import resources
from pathlib import Path

from bindsight.io.paths import cache_dir

LOG = logging.getLogger(__name__)

# Number of proteins in the canonical SURFY list (Bausch-Fluck et al. 2018).
# Used as a sanity check after parsing.
SURFY_PROTEIN_COUNT = 2886

# Canonical SURFY surfaceome table (CC-BY), Bausch-Fluck et al. PNAS 2018.
SURFY_XLSX_URL = "https://wlab.ethz.ch/surfaceome/table_S3_surfaceome.xlsx"

# Bundled fallback for offline tests — a small set of well-characterized
# surface antigens. NOT a substitute for the full SURFY list in production.
_OFFLINE_FALLBACK_UNIPROT = frozenset(
    {
        "P04626",  # ERBB2 / HER2
        "P00533",  # EGFR
        "P56747",  # CLDN6
        "Q13421",  # MSLN (mesothelin)
        "P10747",  # CD28
        "P16410",  # CTLA-4
        "Q9NZQ7",  # PD-L1 / CD274
        "P09038",  # FGF2
        "P10275",  # AR
        "P19838",  # NF-kB1
    }
)


def _bundled_uniprot_set() -> frozenset[str]:
    """Return the small offline-test surface-protein set bundled with bindsight."""
    try:
        # Optional bundled list — fall back to the hardcoded set if missing.
        text = (
            resources.files("bindsight.surfaceome")
            .joinpath("data", "surfy_offline.txt")
            .read_text()
        )
        return frozenset(
            line.strip() for line in text.splitlines() if line.strip() and not line.startswith("#")
        )
    except (FileNotFoundError, ModuleNotFoundError):
        return _OFFLINE_FALLBACK_UNIPROT


def load_surfy(*, allow_offline_fallback: bool = True) -> frozenset[str]:
    """Return the set of UniProt accessions classified as surface by SURFY.

    Resolution order:

    1. ``<user_cache>/bindsight/surfy/surfy_v1.uniprot.txt`` (full canonical list,
       parsed once and persisted).
    2. The bundled offline fallback (small, sufficient for unit tests but NOT
       for real discovery runs).

    If the cache is empty and ``allow_offline_fallback`` is ``False``, raises
    :class:`FileNotFoundError`.

    See ``bindsight/surfaceome/data/surfy_offline.txt`` for the fallback list.
    For production, populate the cache by downloading the full SURFY table
    from https://wlab.ethz.ch/surfaceome (CC-BY) — see the v0.1 docs for the
    exact recipe.
    """
    cache_path = _surfy_cache_path()
    if cache_path.exists():
        return frozenset(
            line.strip()
            for line in cache_path.read_text().splitlines()
            if line.strip() and not line.startswith("#")
        )

    if not allow_offline_fallback:
        raise FileNotFoundError(
            f"SURFY list not found at {cache_path}. Populate the cache or set "
            "allow_offline_fallback=True to use the small bundled set."
        )

    LOG.warning(
        "Using small bundled offline SURFY fallback (%d proteins). "
        "Populate %s with the full SURFY list before doing real discovery runs.",
        len(_bundled_uniprot_set()),
        cache_path,
    )
    return _bundled_uniprot_set()


def populate_surfy_cache(*, url: str = SURFY_XLSX_URL, force: bool = False) -> Path:
    """Download the full canonical SURFY surfaceome table into the cache.

    Parses the ~2,886 ``surface``-labelled UniProt accessions from the SURFY
    master table (Bausch-Fluck et al., PNAS 2018; CC-BY) and writes them to the
    on-disk cache so ``require_surfy`` runs against the real surfaceome instead
    of the tiny bundled offline fallback. Idempotent: returns the existing
    cache unless ``force=True``.

    Requires the ``discover`` extra (``openpyxl``).
    """
    cache_path = _surfy_cache_path()
    if cache_path.exists() and not force:
        return cache_path

    import requests

    try:
        import pandas as pd
    except ImportError as e:  # pragma: no cover - import guard
        raise RuntimeError(
            "populate_surfy_cache needs the 'discover' extra (pandas + openpyxl). "
            'Install with: pip install -e ".[discover]"'
        ) from e

    LOG.info("downloading SURFY surfaceome table from %s …", url)
    resp = requests.get(url, timeout=120)
    resp.raise_for_status()

    import io

    try:
        df = pd.read_excel(
            io.BytesIO(resp.content),
            sheet_name="SurfaceomeMasterTable",
            header=1,
            engine="openpyxl",
        )
    except ImportError as e:  # pragma: no cover - import guard
        raise RuntimeError(
            "reading the SURFY .xlsx needs openpyxl (in the 'discover' extra). "
            'Install with: pip install -e ".[discover]"'
        ) from e

    label = df["Surfaceome Label"].astype(str).str.strip().str.lower()
    accessions = df.loc[label == "surface", "UniProt accession"].dropna().astype(str).str.strip()
    accs = sorted({a for a in accessions if a})
    if not accs:
        raise RuntimeError("parsed 0 surface proteins from SURFY table; format changed?")
    if len(accs) != SURFY_PROTEIN_COUNT:
        LOG.warning(
            "SURFY surface count %d != expected %d (upstream table may have been revised)",
            len(accs),
            SURFY_PROTEIN_COUNT,
        )

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        "# SURFY surfaceome (Bausch-Fluck et al., PNAS 2018; CC-BY).\n"
        f"# {len(accs)} UniProt accessions labelled 'surface'. Source: {url}\n"
        + "\n".join(accs)
        + "\n"
    )
    LOG.info("wrote %d surface accessions to %s", len(accs), cache_path)
    return cache_path


def is_surface_protein(uniprot_id: str, *, surfy: frozenset[str] | None = None) -> bool:
    """Return True if the UniProt accession is in the loaded SURFY set."""
    if surfy is None:
        surfy = load_surfy()
    return uniprot_id in surfy


def _surfy_cache_path() -> Path:
    return cache_dir("surfy") / "surfy_v1.uniprot.txt"

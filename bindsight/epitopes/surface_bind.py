"""SURFACE-Bind targetable-site lookup.

SURFACE-Bind (Khakzad et al., PNAS 2025; https://github.com/hamedkhakzad/SURFACE-Bind,
BSD-3) ships pre-computed targetable interfaces for ~2,800 human surface
proteins, with binder seeds for each. bindsight treats it as the canonical
keystone for v0.1: given a UniProt ID, look up sites + seeds and skip the
expensive epitope-prediction step.

Distribution: SURFACE-Bind has no public REST API. The repo provides
pre-computed result archives that we pin at a specific commit SHA and either
(a) clone-and-vendor at install time or (b) require the user to download once
and point at via env var. See ``data/surface_bind/README.md`` for the recipe.

This module is a stub in v0.0.x — landing the lookup is the v0.0.2 milestone.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

LOG = logging.getLogger(__name__)

# Default vendored location, configurable via env var for CI / paid runners.
SURFACE_BIND_DATA_ENV = "BINDSIGHT_SURFACE_BIND_DATA"


class TargetableSite(BaseModel):
    """One targetable interface on a surface protein."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    uniprot_id: str
    site_id: str = Field(..., description="SURFACE-Bind site ID, e.g. 'P04626_site_3'.")
    chain: str = Field("A", description="Chain ID in the structure (default 'A').")
    residues: list[int] = Field(..., min_length=1, description="Residue indices in the epitope.")
    score: float | None = Field(None, description="SURFACE-Bind composite druggability score.")
    seed_pdb_path: str | None = Field(
        None,
        description="Relative path to the docked binder seed (PDB), if available.",
    )


class SurfaceBindClient:
    """Lookup client over a vendored SURFACE-Bind data tree."""

    def __init__(self, data_root: Path | str | None = None) -> None:
        env = os.environ.get(SURFACE_BIND_DATA_ENV)
        chosen = data_root or env
        if chosen is None:
            raise RuntimeError(
                f"SURFACE-Bind data root not configured. Set the environment variable "
                f"{SURFACE_BIND_DATA_ENV} or pass data_root=. See "
                "data/surface_bind/README.md for the install recipe."
            )
        self.data_root = Path(chosen)
        if not self.data_root.exists():
            raise FileNotFoundError(f"SURFACE-Bind data root does not exist: {self.data_root}")

    def has(self, uniprot_id: str) -> bool:
        """Return True if SURFACE-Bind has any site for the given UniProt ID."""
        raise NotImplementedError("SurfaceBindClient.has lands in v0.0.2.")

    def sites(self, uniprot_id: str) -> list[TargetableSite]:
        """Return all targetable sites for a UniProt ID; empty list if none."""
        raise NotImplementedError("SurfaceBindClient.sites lands in v0.0.2.")

    def metadata(self) -> dict[str, Any]:
        """Return the pinned SURFACE-Bind release metadata (commit SHA, version)."""
        raise NotImplementedError("SurfaceBindClient.metadata lands in v0.0.2.")

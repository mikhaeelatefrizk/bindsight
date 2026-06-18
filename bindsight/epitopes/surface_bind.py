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

The lookup is implemented over a *vendored* data tree (the SURFACE-Bind data
itself is user-supplied — there is no public API; see
``data/surface_bind/README.md`` for the recipe). When no data is vendored,
discovery falls back to whole-surface design and says so in the run manifest.
"""

from __future__ import annotations

import json
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

    @property
    def _sites_dir(self) -> Path:
        """Directory holding one subdirectory per UniProt.

        Accepts a ``data_root`` that either *contains* a ``sites/`` subtree (the
        vendored ``data/surface_bind/`` layout) or *is* the sites tree itself
        (the ``BINDSIGHT_SURFACE_BIND_DATA=.../sites`` env form).
        """
        nested = self.data_root / "sites"
        return nested if nested.is_dir() else self.data_root

    def has(self, uniprot_id: str) -> bool:
        """Return True if SURFACE-Bind has any site for the given UniProt ID."""
        return (self._sites_dir / uniprot_id / "sites.json").is_file()

    def sites(self, uniprot_id: str) -> list[TargetableSite]:
        """Return all targetable sites for a UniProt ID; empty list if none.

        Reads ``<sites>/<uniprot_id>/sites.json`` — a JSON array of records
        ``{site_id, chain, residues, score, seed_pdb}`` (bindsight's vendoring
        contract; see ``data/surface_bind/README.md``). Records with no residues
        are skipped (a site needs at least one). Seed paths are resolved relative
        to the UniProt directory. Sites are returned best-score-first.
        """
        path = self._sites_dir / uniprot_id / "sites.json"
        if not path.is_file():
            return []
        records = json.loads(path.read_text(encoding="utf-8"))
        out: list[TargetableSite] = []
        for i, rec in enumerate(records):
            residues = [int(r) for r in rec.get("residues", [])]
            if not residues:
                continue
            seed = rec.get("seed_pdb") or rec.get("seed_pdb_path")
            seed_path = str(self._sites_dir / uniprot_id / seed) if seed else None
            score = rec.get("score")
            out.append(
                TargetableSite(
                    uniprot_id=uniprot_id,
                    site_id=str(rec.get("site_id") or f"{uniprot_id}_site_{i + 1}"),
                    chain=str(rec.get("chain", "A")),
                    residues=residues,
                    score=float(score) if score is not None else None,
                    seed_pdb_path=seed_path,
                )
            )
        # Best-scored sites first; sites without a score sort last.
        out.sort(key=lambda s: (s.score is not None, s.score or 0.0), reverse=True)
        return out

    def metadata(self) -> dict[str, Any]:
        """Return the pinned SURFACE-Bind release metadata (commit SHA, root)."""
        commit_file = self.data_root / ".commit_sha"
        if not commit_file.is_file():
            # data_root may be the sites/ dir; the SHA sits beside it.
            alt = self._sites_dir.parent / ".commit_sha"
            commit_file = alt if alt.is_file() else commit_file
        commit = commit_file.read_text(encoding="utf-8").strip() if commit_file.is_file() else None
        return {
            "source": "SURFACE-Bind (Khakzad et al., PNAS 2025)",
            "url": "https://github.com/hamedkhakzad/SURFACE-Bind",
            "license": "BSD-3-Clause",
            "commit_sha": commit,
            "data_root": str(self.data_root),
        }

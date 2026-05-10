"""Cache and run directory helpers.

Cache layout (resolved via :mod:`platformdirs`):

    <user_cache>/bindsight/
        surface_bind/<commit_sha>/...
        alphafolddb/<uniprot_id>.cif.gz
        opentargets/<query_sha>.json

Run layout (per-run, user-chosen via ``--out``):

    <run_dir>/
        config.yaml
        run_manifest.jsonld
        deg/results.parquet
        targets/candidates.parquet
        epitopes/epitopes.parquet
        structures/<uniprot_id>.cif
        design/<uniprot_id>/...
        validate/<uniprot_id>/...
        rank/ranking.parquet
        report.html
"""

from __future__ import annotations

from pathlib import Path

from platformdirs import user_cache_path


def cache_dir(subdir: str | None = None) -> Path:
    """Return ``<user_cache>/bindsight[/subdir]``, creating it if missing."""
    base = user_cache_path("bindsight", appauthor=False, ensure_exists=True)
    if subdir is None:
        return base
    p = base / subdir
    p.mkdir(parents=True, exist_ok=True)
    return p


def ensure_dir(path: Path | str) -> Path:
    """``mkdir -p``-style; returns the resolved Path."""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def run_dir(out: Path | str) -> Path:
    """Initialize a run directory, creating the standard subdirectories."""
    root = Path(out)
    for sub in ("deg", "targets", "epitopes", "structures", "design", "validate", "rank"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    return root

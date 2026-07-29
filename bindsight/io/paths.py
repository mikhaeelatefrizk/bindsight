# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
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

import os
import shutil
from pathlib import Path

from platformdirs import user_cache_path

#: Overrides the cache root. The only cross-platform seam for redirecting the
#: cache: ``XDG_CACHE_HOME`` is ignored by platformdirs on macOS, and a
#: ``monkeypatch`` cannot reach a subprocess — which is what the Snakemake
#: front-end and its test are. Same convention as ``BINDSIGHT_SURFACE_BIND_DATA``.
ENV_CACHE_DIR = "BINDSIGHT_CACHE_DIR"

#: Subdirectory of a run holding structures copied in from the cache.
STRUCTURES_SUBDIR = "structures"


def cache_root() -> Path:
    """Return the bindsight cache root, honouring ``BINDSIGHT_CACHE_DIR``."""
    override = os.environ.get(ENV_CACHE_DIR)
    if override:
        base = Path(override).expanduser()
        base.mkdir(parents=True, exist_ok=True)
        return base
    return user_cache_path("bindsight", appauthor=False, ensure_exists=True)


def cache_dir(subdir: str | None = None) -> Path:
    """Return ``<cache_root>/[subdir]``, creating it if missing."""
    base = cache_root()
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
    for sub in ("deg", "targets", "epitopes", STRUCTURES_SUBDIR, "design", "validate", "rank"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    return root


def adopt_structure(run_root: Path | str, source: Path | str) -> str:
    """Copy a structure into the run's ``structures/`` directory.

    ``structures/`` has always been created by :func:`run_dir` and never written
    to, while the structure itself stayed in the machine-local cache. Runs were
    therefore not portable: a candidate table, and any RO-Crate built from it,
    pointed at absolute paths that exist on exactly one machine.

    Copying is deliberate — the cache is shared across runs and may be pruned,
    so a hard link or symlink would let an unrelated cleanup silently gut a
    finished, exported run.

    Args:
        run_root: The run directory.
        source: Path to the cached structure file.

    Returns:
        The path relative to ``run_root``, in POSIX form, suitable for storing
        in a Parquet column and reading back on another machine.
    """
    root = Path(run_root)
    src = Path(source)
    dest_dir = root / STRUCTURES_SUBDIR
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name
    if not dest.exists() or dest.stat().st_size != src.stat().st_size:
        shutil.copy2(src, dest)
    return dest.relative_to(root).as_posix()


def resolve_run_path(run_root: Path | str, stored: str | Path | None) -> Path | None:
    """Resolve a path stored in a run artifact back to a real file.

    Accepts both forms deliberately. New runs store run-relative paths so they
    stay portable; runs produced before that change stored absolute cache
    paths, and must keep working.

    Args:
        run_root: The run directory the artifact belongs to.
        stored: The stored path, possibly empty or ``None``.

    Returns:
        An existing absolute path, or ``None`` if the reference is empty or
        cannot be resolved.
    """
    if not stored:
        return None
    p = Path(stored)
    if p.is_absolute():
        return p if p.exists() else None
    candidate = Path(run_root) / p
    return candidate if candidate.exists() else None

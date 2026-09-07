# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Build a wheel from the working tree, so a GPU run executes the code you have.

Remote backends install bindsight with pip. Until now that meant
``pip install git+<repo>`` with no ref, so every Kaggle run installed the
default branch — whatever the operator had checked out, whatever was fixed
locally, whatever was on an unmerged branch. A run launched to validate a fix
ran the unfixed code and reported success.

Pinning a ref narrows that but does not close it: a branch name still resolves
on the GPU, at pip time, to whatever it points at then, and an unpushed commit
cannot be named at all. A wheel built from the tree that launched the run is the
only thing that answers "which code produced this result" exactly.

The wheel is small because bindsight is pure Python, so it can travel inside the
kernel script itself rather than needing a dataset upload.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

LOG = logging.getLogger(__name__)


def find_repo_root(start: Path | None = None) -> Path | None:
    """Walk up from ``start`` looking for the directory holding ``pyproject.toml``.

    Args:
        start: where to begin; defaults to this module's location.

    Returns:
        The source-checkout root, or None when running from an installed
        package with no source tree beside it.
    """
    here = (start or Path(__file__).resolve()).resolve()
    for candidate in (here, *here.parents):
        if (candidate / "pyproject.toml").is_file() and (candidate / "bindsight").is_dir():
            return candidate
    return None


def build_working_tree_wheel(dest_dir: Path, *, repo_root: Path | None = None) -> Path | None:
    """Build a wheel from the source checkout and return its path.

    Uses ``pip wheel --no-deps``, which honours the project's own build backend,
    so the wheel contains exactly what an install of this tree would.

    Args:
        dest_dir: directory to write the wheel into.
        repo_root: the checkout to build; discovered when omitted.

    Returns:
        Path to the built wheel, or None when there is no source tree to build
        or the build failed. Returning None rather than raising is deliberate:
        the caller falls back to a git ref and warns, so a user who installed
        bindsight from PyPI can still submit a job.
    """
    root = repo_root or find_repo_root()
    if root is None:
        LOG.warning(
            "no source checkout found, so no wheel can be built; the remote job will "
            "install bindsight from git and may therefore run different code"
        )
        return None

    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        "-m",
        "pip",
        "wheel",
        str(root),
        "--no-deps",
        "--no-build-isolation",
        "--wheel-dir",
        str(dest_dir),
        "--quiet",
    ]
    LOG.info("building a wheel from %s so the GPU runs this tree", root)
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=900)
    except subprocess.CalledProcessError as e:
        LOG.warning("wheel build failed (%s); falling back to a git install:\n%s", e, e.stderr)
        return None
    except (subprocess.TimeoutExpired, OSError) as e:
        LOG.warning("wheel build could not run (%s); falling back to a git install", e)
        return None

    wheels = sorted(dest_dir.glob("bindsight-*.whl"), key=lambda p: p.stat().st_mtime)
    if not wheels:
        LOG.warning("wheel build produced nothing in %s; falling back to a git install", dest_dir)
        return None
    wheel = wheels[-1]
    LOG.info("built %s (%d bytes)", wheel.name, wheel.stat().st_size)
    return wheel


__all__ = ["build_working_tree_wheel", "find_repo_root"]

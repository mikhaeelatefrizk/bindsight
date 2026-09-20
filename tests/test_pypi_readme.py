# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The README PyPI shows must link somewhere; the README GitHub shows must stay relative.

0.3.5's project page on PyPI carried the README with every one of its relative
links dead, because PyPI renders a long description with no base URL and
GitHub renders the same file with one. The fix is a rewrite at build time,
which means two things can silently stop being true: the rewrite can miss a
link shape (a badge wrapped in a link nests brackets the obvious regex cannot
see), and the release workflow can stop running it before ``python -m build``.
Both are held here, along with the opposite guard -- that nobody "fixes" the
PyPI page by making the tree's README absolute, which would break GitHub's own
rendering of it on every fork and branch.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from pypi_readme import RAW_URL, REPO_URL, relative_targets, rewrite  # noqa: E402

README = (REPO / "README.md").read_text(encoding="utf-8")
REF = "v0.0.0-test"


def test_the_tree_readme_keeps_its_relative_links() -> None:
    """GitHub, forks and branches render relative links; the tree stays that way."""
    assert len(relative_targets(README)) >= 40, (
        "README.md has fewer than forty relative links; if they were made absolute "
        "to fix the PyPI page, undo that -- the rewrite happens at build time"
    )


def test_no_relative_link_survives_the_rewrite() -> None:
    assert relative_targets(rewrite(README, REF)) == []


def test_every_rewritten_target_exists_in_the_tree() -> None:
    """A link rewritten to ``blob/<ref>/x`` is only better than a dead one if ``x`` exists."""
    out = rewrite(README, REF)
    blobs = re.findall(re.escape(f"{REPO_URL}/blob/{REF}/") + r"([^)#\s]+)", out)
    trees = re.findall(re.escape(f"{REPO_URL}/tree/{REF}/") + r"([^)#\s]+)", out)
    raws = re.findall(re.escape(f"{RAW_URL}/{REF}/") + r"([^)#\s]+)", out)
    assert blobs, "the rewrite produced no file links at all"
    for path in blobs + raws:
        assert (REPO / path).is_file(), f"{path} is linked as a file and is not one"
    for path in trees:
        assert (REPO / path).is_dir(), f"{path} is linked as a directory and is not one"


def test_absolute_links_and_anchors_are_left_alone() -> None:
    absolute = re.findall(r"\]\((https?://[^)\s]+|#[^)\s]+|mailto:[^)\s]+)\)", README)
    out = rewrite(README, REF)
    for target in absolute:
        assert f"]({target})" in out, f"{target} was altered by the rewrite"


def test_the_badge_wrapped_in_a_link_is_reached() -> None:
    """``[![License](https://img.shields.io/...)](LICENSE)`` nests brackets; the
    licence badge is the first thing on the page and was the first thing dead."""
    out = rewrite(README, REF)
    assert f"]({REPO_URL}/blob/{REF}/LICENSE)" in out


def test_the_rewrite_is_idempotent() -> None:
    once = rewrite(README, REF)
    assert rewrite(once, REF) == once


def _release_build_steps() -> list[dict[str, Any]]:
    workflow = yaml.safe_load(
        (REPO / ".github" / "workflows" / "release-artifacts.yml").read_text(encoding="utf-8")
    )
    return workflow["jobs"]["build"]["steps"]


def test_the_release_workflow_rewrites_before_it_builds() -> None:
    """The step order is the whole point: rewritten first, then ``python -m build``."""
    runs = [str(step.get("run", "")) for step in _release_build_steps()]
    rewrite_at = next(
        (i for i, r in enumerate(runs) if "scripts/pypi_readme.py --write" in r), None
    )
    build_at = next((i for i, r in enumerate(runs) if r.strip() == "python -m build"), None)
    assert rewrite_at is not None, "release-artifacts.yml no longer rewrites the README for PyPI"
    assert build_at is not None, "release-artifacts.yml no longer runs `python -m build`"
    assert rewrite_at < build_at, "the README is rewritten after the wheel was built"

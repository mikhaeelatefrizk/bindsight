# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""LICENSING.md says when it was last re-checked; that date is now checked too.

The header carried "Last reviewed: 2026-06-15" for three months and three
releases, through two tool-pin bumps in `bindsight/runners/tools.py`, and one
of its rows described a Python client this project has never depended on. A
review date nothing reads is a claim, not a record. Two things are held here:
the date is a real date that has already happened, and it is not older than
the last change to the registry of upstream tools -- a new pin without a
licence re-check fails, which is the moment the check is cheapest.
"""

from __future__ import annotations

import datetime as dt
import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
LICENSING = REPO / "LICENSING.md"
TOOL_REGISTRY = "bindsight/runners/tools.py"

_REVIEWED = re.compile(r"Last reviewed: (\d{4}-\d{2}-\d{2})")


def _review_date() -> dt.date:
    text = LICENSING.read_text(encoding="utf-8")
    match = _REVIEWED.search(text)
    assert match, "LICENSING.md no longer states when it was last reviewed"
    return dt.date.fromisoformat(match.group(1))


def _git(*args: str) -> str | None:
    try:
        return subprocess.run(
            ["git", *args], cwd=REPO, capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def test_the_review_date_is_one_date_that_has_happened() -> None:
    assert _review_date() <= dt.date.today(), "LICENSING.md was reviewed in the future"


def test_the_review_is_not_older_than_the_tool_registry() -> None:
    """A pin bump in tools.py means an upstream tree changed under a licence
    row. CI checks out one commit deep, so the file's history is only readable
    from a full clone; the test skips there rather than trusting a boundary
    commit's date."""
    if _git("rev-parse", "--is-shallow-repository") != "false":
        pytest.skip("needs a full clone to read the tool registry's history")
    last_change = _git("log", "-1", "--format=%cs", "--", TOOL_REGISTRY)
    if not last_change:
        pytest.skip("git history for the tool registry is unavailable")
    assert _review_date() >= dt.date.fromisoformat(last_change), (
        f"{TOOL_REGISTRY} changed on {last_change}, after LICENSING.md was last "
        f"reviewed on {_review_date()}; re-check the rows it pins and move the date"
    )


def test_the_inventory_names_no_client_this_project_does_not_ship() -> None:
    """The row deleted in 0.3.5: an Apache-licensed Open Targets Python client
    that nothing here imports. `bindsight/targets/open_targets.py` talks to the
    Platform's API with `requests`."""
    text = LICENSING.read_text(encoding="utf-8")
    rows = [line for line in text.splitlines() if line.startswith("|")]
    assert not [row for row in rows if "Open Targets Python client" in row], (
        "LICENSING.md again lists a Python client for Open Targets as a component"
    )
    assert "opentargets" not in (REPO / "pyproject.toml").read_text(encoding="utf-8").lower()

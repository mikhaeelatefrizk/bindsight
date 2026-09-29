# SPDX-License-Identifier: AGPL-3.0-or-later
"""A launch-only URI; it cannot choose paths, commands, downloads or arguments."""

from __future__ import annotations

import json
import re
import urllib.request
from pathlib import Path

from companion.core import SetupError

OPEN_URI = "bindsight://open"


def validate_open_uri(uri: str, arguments: list[str]) -> None:
    """Allow one exact URI with no additional CLI options or decoded payloads."""
    if uri != OPEN_URI or arguments != [OPEN_URI]:
        raise SetupError("Only the exact bindsight://open launch link is supported.")


def existing_workspace(root: Path, revision: str) -> str | None:
    """Recover a responding same-release loopback workspace, never an external URL."""
    try:
        record = json.loads((root / "running.json").read_text(encoding="utf-8"))
        url = record.get("url")
        if record.get("revision") != revision or not isinstance(url, str):
            return None
        match = re.fullmatch(r"http://127\.0\.0\.1:([0-9]{1,5})/workbench", url)
        if not match or not 1 <= int(match[1]) <= 65535:
            return None
        with urllib.request.urlopen(url, timeout=1) as response:
            if response.status == 200 and b"bindsight" in response.read(128 * 1024).lower():
                return url
    except (OSError, ValueError, AttributeError):
        return None
    return None

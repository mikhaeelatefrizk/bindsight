# SPDX-License-Identifier: AGPL-3.0-or-later
"""Packaged-process smoke against an already installed isolated CPU fixture."""

from __future__ import annotations

import hashlib
import json
import threading
import urllib.request
from pathlib import Path
from typing import Any

from companion.core import (
    Cancelled,
    Installer,
    SetupError,
    app_directory,
    application_lock,
    embedded_revision,
)


def smoke_existing(root: Path) -> dict[str, Any]:
    """Start only an existing test install; never download or register anything."""
    root = root.resolve()
    if root == app_directory().resolve():
        raise SetupError("Use an isolated test installation, not the normal app directory.")
    record = json.loads((root / "current.json").read_text(encoding="utf-8"))
    cancel = threading.Event()
    observed: dict[str, Any] = {}
    with (root / "packaged-smoke.log").open("a", encoding="utf-8") as log:

        def report(message: str) -> None:
            log.write(message + "\n")
            log.flush()

        installer = Installer(root, record["revision"], report, cancel)
        if installer.current() is None:
            raise SetupError("The test workspace is not already installed.")

        def opened(url: str) -> None:
            with urllib.request.urlopen(url, timeout=5) as response:
                content = response.read(2 * 1024 * 1024)
                if response.status != 200 or b"bindsight" not in content.lower():
                    raise SetupError("The installed server did not return the real workbench.")
                observed.update(
                    http_status=response.status,
                    html_sha256=hashlib.sha256(content).hexdigest(),
                    bytes=len(content),
                )
            cancel.set()

        with application_lock(root):
            try:
                installer.launch(record, opened)
            except Cancelled:
                if not observed:
                    raise
    return {
        "ok": bool(observed),
        "companion_revision": embedded_revision(),
        "installed_source_revision": record["revision"],
        "workspace": observed,
        "downloads": 0,
        "registered_launchers": False,
    }

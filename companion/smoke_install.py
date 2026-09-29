# SPDX-License-Identifier: AGPL-3.0-or-later
"""Developer-only real installation smoke in an explicitly chosen empty workspace.

This does not register protocols, install shortcuts, open a browser or touch the
normal per-user application directory. It performs real approved CPU downloads.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import threading
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from companion.core import (  # noqa: E402
    Cancelled,
    Installer,
    app_directory,
    application_lock,
)


def main() -> None:
    """Install a specified published revision and prove loopback startup."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--approve-downloads", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    if not args.approve_downloads:
        parser.error("Explicit --approve-downloads is required")
    if root == app_directory().resolve():
        parser.error("Use a separate test workspace, not the normal application directory")
    root.mkdir(parents=True, exist_ok=True)
    cancellation = threading.Event()
    ready: dict[str, object] = {}
    with (root / "smoke.log").open("a", encoding="utf-8") as log:

        def report(message: str) -> None:
            print(message, flush=True)
            log.write(message + "\n")
            log.flush()

        with application_lock(root):
            installer = Installer(root, args.revision, report, cancellation)
            record = installer.current() or installer.install(approved=True)

            def opened(url: str) -> None:
                with urllib.request.urlopen(url, timeout=5) as response:
                    body = response.read(2 * 1024 * 1024)
                    if response.status != 200 or b"bindsight" not in body.lower():
                        raise RuntimeError("The loopback response is not the Bindsight workspace")
                    ready.update(
                        url=url,
                        http_status=response.status,
                        html_sha256=hashlib.sha256(body).hexdigest(),
                        bytes=len(body),
                    )
                cancellation.set()

            try:
                installer.launch(record, opened)
            except Cancelled:
                if not ready:
                    raise
    receipt = {
        "schema": "bindsight-companion-install-smoke/1",
        "passed": bool(ready),
        "installation": record,
        "workspace": ready,
        "shortcuts_registered": False,
        "protocol_registered": False,
        "system_python_changed": False,
        "global_path_changed": False,
    }
    (root / "smoke-receipt.json").write_text(
        json.dumps(receipt, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    if not ready:
        raise SystemExit("The real workspace never became ready")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()

# SPDX-License-Identifier: AGPL-3.0-or-later
"""Install the pinned CPU workspace once, then open it on loopback only."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import urllib.request
import venv
import webbrowser

ROOT = Path(__file__).resolve().parent


def main() -> int:
    """Keep installation local to this folder and show genuine setup failures."""
    if not (3, 11) <= sys.version_info[:2] <= (3, 13):
        print("Please install Python 3.11, 3.12, or 3.13 from https://www.python.org/downloads/.")
        print("Then launch again using that Python version. No analysis has run.")
        return 1
    os.chdir(ROOT)
    environment = ROOT / ".venv-bindsight"
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    marker = environment / ".bindsight-ready"
    fingerprint = hashlib.sha256(
        (ROOT / "pyproject.toml").read_bytes() + (ROOT / "envs/constraints.txt").read_bytes()
    ).hexdigest()
    if not python.is_file():
        print("Creating Bindsight's private Python environment in this folder…", flush=True)
        venv.EnvBuilder(with_pip=True).create(environment)
    if not marker.is_file() or marker.read_text() != fingerprint:
        print(
            "Installing the CPU analysis packages. This first setup needs internet access.",
            flush=True,
        )
        subprocess.run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "-c",
                str(ROOT / "envs/constraints.txt"),
                "-e",
                ".[discover,report]",
            ],
            check=True,
        )
        marker.write_text(fingerprint, encoding="utf-8", newline="\n")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    url = f"http://127.0.0.1:{port}/workbench"
    print(f"\nOpen Bindsight: {url}\nKeep this window open. Press Ctrl+C to stop.\n", flush=True)

    def open_when_ready():
        import time

        for _ in range(60):
            try:
                with urllib.request.urlopen(url, timeout=1) as response:
                    if response.status == 200:
                        webbrowser.open(url)
                        return
            except OSError:
                time.sleep(0.5)

    threading.Thread(target=open_when_ready, daemon=True).start()
    return subprocess.call(
        [str(python), "-m", "bindsight.cli", "ui", "--no-browser", "--port", str(port)]
    )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, subprocess.CalledProcessError) as error:
        print(f"Setup could not finish: {error}\nYour input files have not been changed.")
        raise SystemExit(1) from None

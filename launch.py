# SPDX-License-Identifier: AGPL-3.0-or-later
"""Install the pinned CPU workspace once, then open it on loopback only."""

from __future__ import annotations

import hashlib
import os
import socket
import subprocess
import sys
import threading
import urllib.request
import venv
import webbrowser
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent


@contextmanager
def launcher_lock(environment: Path) -> Iterator[None]:
    """Prevent overlapping first installs and duplicate launches from this folder."""
    environment.mkdir(parents=True, exist_ok=True)
    with (environment / ".launcher.lock").open("a+b") as lock:
        try:
            if sys.platform == "win32":
                import msvcrt

                if lock.seek(0, 2) == 0:
                    lock.write(b"\0")
                    lock.flush()
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise OSError(
                "Bindsight is already starting or running from this folder. "
                "Use its existing window, or wait for that setup to finish."
            ) from exc
        yield


def main() -> int:
    """Keep installation local to this folder and show genuine setup failures."""
    if not (3, 11) <= sys.version_info[:2] <= (3, 13):
        print("Please install Python 3.11, 3.12, or 3.13 from https://www.python.org/downloads/.")
        print("Then launch again using that Python version. No analysis has run.")
        return 1
    os.chdir(ROOT)
    environment = ROOT / ".venv-bindsight"
    with launcher_lock(environment):
        return launch(environment)


def launch(environment: Path) -> int:
    """Install if needed, then keep the launcher lock until the server stops."""
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

    def open_when_ready() -> None:
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

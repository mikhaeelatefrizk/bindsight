# SPDX-License-Identifier: AGPL-3.0-or-later
"""Explicit Windows OS setup and a revision-checked, isolated WSL handoff.

No import performs setup. Readiness starts only read-only commands in existing
supported distributions. OS installation requires its own explicit approval;
the Linux companion installs only into its separate per-user app directory.
"""

from __future__ import annotations

import csv
import ctypes
import hashlib
import io
import json
import re
import stat
import subprocess
import sys
import threading
import time
import urllib.parse
import uuid
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from companion.core import (
    PINS,
    Cancelled,
    SetupError,
    approved_url,
    download,
    external_environment,
    external_libraries,
    inside,
)

GUIDANCE_URL = "https://learn.microsoft.com/en-us/windows/wsl/basic-commands"
DISTROS = ("Ubuntu-24.04", "Ubuntu-22.04", "Ubuntu")
MIN_GPU_MIB = 15_360
MAX_ARCHIVE_BYTES = 256 * 1024**2
MAX_EXECUTABLE_BYTES = 512 * 1024**2
INSTALL_ARGUMENTS = "--install --distribution Ubuntu-24.04 --no-launch"


def _wsl_executable() -> Path:
    if sys.platform != "win32":
        raise SetupError("This handoff is available only on native Windows.")
    # GetWindowsDirectoryW avoids resolving an executable through PATH or a
    # caller-provided SYSTEMROOT environment variable.
    buffer = ctypes.create_unicode_buffer(32768)
    length = ctypes.windll.kernel32.GetWindowsDirectoryW(buffer, len(buffer))
    if not length or length >= len(buffer):
        raise SetupError("Windows could not locate its system directory.")
    executable = Path(buffer.value) / "System32" / "wsl.exe"
    if not executable.is_file():
        raise SetupError("Windows Linux support is unavailable on this Windows installation.")
    return executable


def _decode(data: bytes) -> str:
    # Windows WSL management commands commonly emit UTF-16LE even to a pipe;
    # Linux commands emit UTF-8. Decode both without relying on the locale.
    encoding = (
        "utf-16"
        if data.startswith((b"\xff\xfe", b"\xfe\xff"))
        else ("utf-16-le" if b"\0" in data[:100] else "utf-8")
    )
    return data.decode(encoding, errors="replace").lstrip("\ufeff")


def _message(value: str) -> str:
    value = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", value)
    value = value.replace(str(Path.home()), "<user>")
    return value.strip()[:1200]


def _run(args: list[str], *, timeout: float = 8) -> str:
    try:
        with external_libraries():
            result = subprocess.run(
                [str(_wsl_executable()), *args],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=timeout,
                check=False,
                shell=False,
                env=external_environment(),
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
    except subprocess.TimeoutExpired as exc:
        raise SetupError(
            "Windows Linux support did not respond before the readiness timeout."
        ) from exc
    except OSError as exc:
        raise SetupError(f"Windows could not start Linux support: {_message(str(exc))}") from exc
    output = _decode(result.stdout)
    if result.returncode:
        raise SetupError(f"WSL exited with code {result.returncode}: {_message(output)}")
    return output


def _distributions(output: str) -> dict[str, int]:
    found: dict[str, int] = {}
    for line in output.splitlines():
        match = re.fullmatch(r"\s*\*?\s*(Ubuntu(?:-22\.04|-24\.04)?)\s+.+?\s+([12])\s*", line)
        if match:
            found[match[1]] = int(match[2])
    return found


def readiness() -> dict[str, Any]:
    """Measure WSL2, Ubuntu user initialization, architecture and real GPU memory.

    This is prerequisite admission, not a CUDA/model test. Every subprocess is
    bounded and no distro configuration, package, default or kernel is changed.
    """
    result: dict[str, Any] = {
        "ready": False,
        "blockers": [],
        "distro": None,
        "gpus": [],
        "guidance_url": GUIDANCE_URL,
        "os_install_available": False,
        "limitations": "GPU visibility and memory admission do not verify CUDA, model installation or a scientific run.",
    }
    deadline = time.monotonic() + 30

    def probe(arguments: list[str]) -> str:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise SetupError("WSL readiness reached its 30-second time budget.")
        return _run(arguments, timeout=min(8, remaining))

    try:
        _wsl_executable()
        result["os_install_available"] = True
        distros = _distributions(probe(["--list", "--verbose"]))
        supported = [name for name in DISTROS if distros.get(name) == 2]
        if not supported:
            raise SetupError(
                "An initialized Ubuntu 22.04 or 24.04 on WSL2 is required. "
                "Use the separately approved Windows Linux setup if missing; "
                "restart Windows if requested, finish Ubuntu's username/password setup, and reopen Bindsight. "
                "Existing WSL1 distributions are not converted automatically."
            )
        failures = []
        for distro in supported:
            try:
                prefix = ["--distribution", distro, "--exec"]
                release = probe([*prefix, "/bin/cat", "/etc/os-release"])
                fields = dict(
                    re.findall(r'^([A-Z_]+)=["\']?([^"\'\r\n]+)["\']?$', release, re.MULTILINE)
                )
                if fields.get("ID") != "ubuntu" or fields.get("VERSION_ID") not in {
                    "22.04",
                    "24.04",
                }:
                    raise SetupError("The distribution is not Ubuntu 22.04 or 24.04.")
                uid = probe([*prefix, "/usr/bin/id", "-u"]).strip()
                if not uid.isdecimal() or int(uid) == 0:
                    raise SetupError(
                        "Finish Ubuntu's first-launch username/password setup and use a non-root default user."
                    )
                if probe([*prefix, "/usr/bin/uname", "-m"]).strip() != "x86_64":
                    raise SetupError("The published Linux companion requires x86_64 WSL.")
                gpu_output = probe(
                    [
                        *prefix,
                        "/usr/lib/wsl/lib/nvidia-smi",
                        "--query-gpu=name,memory.total,driver_version",
                        "--format=csv,noheader,nounits",
                    ]
                )
                gpus: list[dict[str, Any]] = []
                for row in csv.reader(io.StringIO(gpu_output)):
                    if len(row) == 3:
                        try:
                            memory = int(row[1].strip())
                        except ValueError:
                            continue
                        gpus.append(
                            {
                                "name": _message(row[0]),
                                "memory_total_mib": memory,
                                "driver": _message(row[2]),
                            }
                        )
                result["gpus"] = gpus
                if not any(gpu["memory_total_mib"] >= MIN_GPU_MIB for gpu in gpus):
                    raise SetupError(
                        "WSL needs a visible NVIDIA GPU with at least 15,360 MiB memory for this design workflow. A 2 GB GPU cannot run it."
                    )
                result.update(ready=True, distro=distro)
                return result
            except SetupError as exc:
                failures.append(f"{distro}: {exc}")
        result["blockers"] = failures
    except SetupError as exc:
        result["blockers"].append(str(exc))
    return result


def _elevated_install(executable: Path) -> int:
    # A native, OS-owned interactive window is intentional: this action requires
    # the user's separate confirmation and Windows administrator approval.
    if sys.platform != "win32":
        raise SetupError("Windows Linux installation requires Windows.")
    function = ctypes.windll.shell32.ShellExecuteW
    function.argtypes = [
        ctypes.c_void_p,
        ctypes.c_wchar_p,
        ctypes.c_wchar_p,
        ctypes.c_wchar_p,
        ctypes.c_wchar_p,
        ctypes.c_int,
    ]
    function.restype = ctypes.c_void_p
    with external_libraries():
        return int(function(None, "runas", str(executable), INSTALL_ARGUMENTS, None, 1) or 0)


def install_prerequisites(*, approved: bool = False) -> dict[str, Any]:
    """Request the fixed Microsoft setup only after separate explicit OS approval.

    This launches Windows' own installer; it does not await or certify successful
    installation. It never restarts Windows or replaces/converts a distribution.
    Microsoft documents the flags at ``GUIDANCE_URL``.
    """
    if not approved:
        raise SetupError(
            "Approve the separate Windows Linux installation and restart notice first."
        )
    executable = _wsl_executable()
    try:
        existing = _distributions(_run(["--list", "--verbose"]))
    except SetupError:
        # Missing/disabled WSL can fail enumeration; the OS installer diagnoses it.
        existing = {}
    if "Ubuntu-24.04" in existing:
        return {
            "started": False,
            "ready": False,
            "guidance_url": GUIDANCE_URL,
            "message": "Ubuntu 24.04 is already registered. Open Ubuntu from Windows Start to finish initialization, then reopen Bindsight. Existing distributions are not reinstalled or converted.",
        }
    code = _elevated_install(executable)
    if code <= 32:
        raise SetupError(
            f"Windows did not start Linux setup (Windows code {code}). Administrator approval may have been cancelled or blocked by policy."
        )
    return {
        "started": True,
        "ready": False,
        "guidance_url": GUIDANCE_URL,
        "message": "Windows Linux setup opened. Complete its administrator-approved installation. Restart Windows if it asks; Bindsight will not restart it. Then open Ubuntu 24.04 from Windows Start, complete its username/password setup, and reopen Bindsight to check readiness.",
    }


def _artifact(manifest: Any, revision: str) -> tuple[str, int]:
    if not isinstance(manifest, dict) or manifest.get("revision") != revision:
        raise SetupError(
            "The Linux companion belongs to a different release. Download the current Windows companion and retry."
        )
    platforms = manifest.get("platforms")
    item = platforms.get("linux-x64") if isinstance(platforms, dict) else None
    if not isinstance(item, dict) or item.get("filename") != "Bindsight-Companion-linux-x64.zip":
        raise SetupError("The release has no supported Linux companion download.")
    sha, size = item.get("sha256"), item.get("size_bytes")
    if (
        not isinstance(sha, str)
        or not re.fullmatch(r"[0-9a-f]{64}", sha)
        or type(size) is not int
        or not 0 < size <= MAX_ARCHIVE_BYTES
    ):
        raise SetupError("The Linux companion checksum or download size is invalid.")
    return sha, size


def _extract(
    archive: Path, destination: Path, sha: str, size: int, cancel: threading.Event
) -> Path:
    with archive.open("rb") as stream:
        if (
            archive.stat().st_size != size
            or hashlib.file_digest(stream, "sha256").hexdigest() != sha
        ):
            raise SetupError("The Linux companion archive failed checksum or size verification.")
    destination.mkdir(parents=True, exist_ok=True)
    target = inside(destination, destination / "BindsightCompanion")
    partial = inside(destination, destination / "BindsightCompanion.partial")
    try:
        with zipfile.ZipFile(archive) as bundle:
            entries = bundle.infolist()
            if len(entries) not in {1, 2} or len({item.filename for item in entries}) != len(
                entries
            ):
                raise SetupError("Unexpected Linux companion archive layout.")
            for item in entries:
                mode = item.external_attr >> 16
                if (
                    item.filename not in {"BindsightCompanion", "README.txt"}
                    or stat.S_IFMT(mode) not in {0, stat.S_IFREG}
                    or item.flag_bits & 1
                    or item.file_size > MAX_EXECUTABLE_BYTES
                ):
                    raise SetupError("The Linux companion archive contains an unsafe member.")
            entry = bundle.getinfo("BindsightCompanion")
            with bundle.open(entry) as source, partial.open("wb") as sink:
                total = 0
                while chunk := source.read(1024 * 1024):
                    if cancel.is_set():
                        raise Cancelled("WSL setup cancelled during extraction.")
                    total += len(chunk)
                    if total > MAX_EXECUTABLE_BYTES:
                        raise SetupError("The Linux companion executable is too large.")
                    sink.write(chunk)
            if total == 0:
                raise SetupError("The Linux companion executable is empty.")
        partial.replace(target)
    except (zipfile.BadZipFile, KeyError) as exc:
        raise SetupError("The Linux companion archive is incomplete or corrupt.") from exc
    finally:
        partial.unlink(missing_ok=True)
    return target


def _linux_path(distro: str, path: Path) -> str:
    result = _run(
        ["--distribution", distro, "--exec", "/usr/bin/wslpath", "-a", "-u", str(path.resolve())]
    ).strip()
    if not result.startswith("/") or any(ord(character) < 32 for character in result):
        raise SetupError("WSL could not map the companion's shared application path.")
    return result


def _browser_url(value: Any) -> str | None:
    if not isinstance(value, str) or len(value) > 200:
        return None
    try:
        parsed = urllib.parse.urlsplit(value)
        if (
            parsed.scheme == "http"
            and parsed.hostname == "127.0.0.1"
            and parsed.port
            and parsed.username is None
            and parsed.password is None
            and parsed.path == "/workbench"
            and not parsed.query
            and not parsed.fragment
            and value == f"http://127.0.0.1:{parsed.port}/workbench"
        ):
            return value
    except ValueError:
        pass
    return None


def _event(line: str, report: Callable[[str], None], open_browser: Callable[[str], None]) -> None:
    try:
        event = json.loads(line)
    except (ValueError, TypeError):
        report(_message(line))
        return
    if not isinstance(event, dict):
        return
    if event.get("event") == "log" and isinstance(event.get("message"), str):
        report(_message(event["message"]))
    elif event.get("event") == "browser":
        url = _browser_url(event.get("url"))
        if url is None:
            report("Ignored an invalid Linux workspace browser address.")
        else:
            open_browser(url)


def _bridge(
    args: list[str],
    marker: Path,
    cancel: threading.Event,
    report: Callable[[str], None],
    open_browser: Callable[[str], None],
) -> None:
    with external_libraries():
        process = subprocess.Popen(
            args,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            shell=False,
            env=external_environment(),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

    def read() -> None:
        if process.stdout is None:
            return
        with process.stdout:
            while line := process.stdout.readline(16385):
                if len(line) > 16384:
                    # Do not interpret a truncated JSON event or retain unbounded output.
                    while line and not line.endswith(b"\n"):
                        line = process.stdout.readline(16385)
                    report("A Linux log record exceeded the display limit.")
                    continue
                _event(line.decode("utf-8", errors="replace"), report, open_browser)

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    try:
        while process.poll() is None:
            if cancel.wait(0.15):
                marker.write_text("cancel\n", encoding="utf-8")
                report(
                    "Stopping the Linux companion and its owned work; saved runs remain in Linux."
                )
                try:
                    process.wait(timeout=40)
                except subprocess.TimeoutExpired:
                    # Do not terminate/shutdown a distro or unrelated Linux work.
                    process.terminate()
                    report(
                        "The WSL connection did not acknowledge shutdown. The cancellation marker remains for the Linux companion; check its workspace before starting another run."
                    )
                raise Cancelled("The WSL workspace stop was requested.")
        reader.join(timeout=2)
        if process.returncode:
            raise SetupError(
                f"The Linux companion exited with code {process.returncode}. See its log above."
            )
    finally:
        if process.poll() is None:
            marker.write_text("cancel\n", encoding="utf-8")
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.terminate()


def launch(
    root: Path,
    revision: str,
    report: Callable[[str], None],
    cancel: threading.Event,
    open_browser: Callable[[str], None],
) -> None:
    """After user-space setup approval, launch only the matching verified release."""
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise SetupError("A fixed 40-character source revision is required.")
    if cancel.is_set():
        raise Cancelled("WSL setup cancelled.")
    state = readiness()
    if not state["ready"]:
        raise SetupError(" ".join(state["blockers"]))
    distro = state["distro"]
    if distro not in DISTROS:
        raise SetupError("An unsupported Linux distribution was selected.")
    root = root.resolve()
    directory = inside(root, root / "wsl")
    directory.mkdir(parents=True, exist_ok=True)
    base = PINS["release_base"] + "downloads/"
    if not approved_url(base + "companion.json"):
        raise SetupError("The companion manifest location is not approved.")
    manifest_path = inside(root, directory / "companion.json")
    download(base + "companion.json", manifest_path, 64 * 1024, cancel, report)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise SetupError("The companion manifest could not be read.") from exc
    sha, size = _artifact(manifest, revision)
    archive = inside(root, directory / f"linux-{sha}.zip")
    download(
        base + "Bindsight-Companion-linux-x64.zip", archive, size, cancel, report, expected_sha=sha
    )
    executable = _extract(archive, inside(root, directory / f"{revision}-{sha}"), sha, size, cancel)
    marker = inside(root, directory / f"cancel-{uuid.uuid4().hex}")
    linux_executable, linux_marker = _linux_path(distro, executable), _linux_path(distro, marker)
    _run(["--distribution", distro, "--exec", "/bin/chmod", "u+x", linux_executable])
    if cancel.is_set():
        raise Cancelled("WSL setup cancelled before launch.")
    report(
        "Opening the verified Linux companion. Linux runs and packages use their own user directory; Windows runs are not moved."
    )
    _bridge(
        [
            str(_wsl_executable()),
            "--distribution",
            distro,
            "--exec",
            linux_executable,
            "--headless",
            "--setup-approved",
            "--cancel-file",
            linux_marker,
        ],
        marker,
        cancel,
        report,
        open_browser,
    )

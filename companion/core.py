# SPDX-License-Identifier: AGPL-3.0-or-later
"""Standard-library installation core; imports perform no network or installation."""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import platform
import re
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tarfile
import threading
import time
import urllib.parse
import urllib.request
import uuid
import zipfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Any

MAX_SOURCE_BYTES = 64 * 1024 * 1024
MAX_EXPANDED_BYTES = 512 * 1024 * 1024
MAX_MEMBERS = 20_000
RESOURCE_ROOT = Path(__file__).resolve().parent
PINS = json.loads((RESOURCE_ROOT / "pins.json").read_text(encoding="utf-8"))
_DLL_LOCK = threading.Lock()


class SetupError(RuntimeError):
    """A setup failure suitable for the visible setup log."""


class Cancelled(SetupError):
    """Explicit cancellation; partial installs are never marked ready."""


def platform_key(system: str | None = None, machine: str | None = None) -> str:
    """Return only the platforms with reviewed bootstrap pins."""
    system = system or platform.system()
    machine = (machine or platform.machine()).lower()
    arch = (
        "x64"
        if machine in {"amd64", "x86_64"}
        else "arm64"
        if machine in {"arm64", "aarch64"}
        else machine
    )
    key = f"{ {'Windows': 'windows', 'Darwin': 'macos', 'Linux': 'linux'}.get(system, system.lower()) }-{arch}"
    if key not in PINS["artifacts"]:
        raise SetupError(f"This companion does not support {system} {machine}.")
    return key


def app_directory() -> Path:
    """Use a persistent per-user location without system configuration changes."""
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local")))
    elif sys.platform == "darwin":
        base = Path.home() / "Library/Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share")))
    return base / "Bindsight"


def embedded_revision() -> str:
    """Require the build-time revision; development runs cannot install unpinned code."""
    file = RESOURCE_ROOT / "build-info.json"
    if not file.is_file():
        raise SetupError("This is a development checkout. Build a revision-pinned companion first.")
    revision = json.loads(file.read_text(encoding="utf-8"))["revision"]
    if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise SetupError("The companion build revision is invalid.")
    return revision


def inside(root: Path, path: Path) -> Path:
    """Resolve a managed path and reject symlink or path traversal escapes."""
    resolved = path.resolve()
    if not resolved.is_relative_to(root.resolve()) or resolved == root.resolve():
        raise SetupError("A managed path escapes the application directory.")
    return resolved


@contextmanager
def application_lock(root: Path) -> Iterator[None]:
    """Hold an OS advisory lock through setup and the running local server."""
    root.mkdir(parents=True, exist_ok=True)
    with inside(root, root / "companion.lock").open("a+b") as handle:
        try:
            if sys.platform == "win32":
                import msvcrt

                if handle.seek(0, 2) == 0:
                    handle.write(b"\0")
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise SetupError(
                "Bindsight is already starting or running. Use its existing window."
            ) from exc
        yield


def approved_url(url: str, *, uv: bool = False) -> bool:
    """Allow HTTPS only, including uv's official GitHub binary redirect host."""
    parsed = urllib.parse.urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.username
        or parsed.password
        or parsed.port not in {None, 443}
    ):
        return False
    if uv:
        return (
            parsed.hostname == "github.com"
            and parsed.path.startswith(f"/astral-sh/uv/releases/download/{PINS['uv_version']}/")
        ) or parsed.hostname == "release-assets.githubusercontent.com"
    base = urllib.parse.urlsplit(PINS["release_base"])
    return (
        parsed.hostname == base.hostname and parsed.path.startswith(base.path) and not parsed.query
    )


class CheckedRedirect(urllib.request.HTTPRedirectHandler):
    """Check every redirect before making its next network request."""

    def __init__(self, uv: bool = False):
        self.uv = uv

    def redirect_request(
        self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> Any:
        """Validate the destination before following a server redirect."""
        if not approved_url(newurl, uv=self.uv):
            raise SetupError("The download redirected outside the approved release hosts.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download(
    url: str,
    target: Path,
    limit: int,
    cancel: threading.Event,
    report: Callable[[str], None],
    *,
    expected_sha: str | None = None,
    uv: bool = False,
) -> None:
    """Stream bounded bytes, verify SHA256, then atomically publish the file."""
    if not approved_url(url, uv=uv):
        raise SetupError("The download URL is not an approved release location.")
    if (
        expected_sha
        and target.is_file()
        and target.stat().st_size <= limit
        and hashlib.sha256(target.read_bytes()).hexdigest() == expected_sha
    ):
        report(f"Using verified cached {target.name}.")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".partial")
    request = urllib.request.Request(url, headers={"User-Agent": "Bindsight-Companion/1"})
    opener = urllib.request.build_opener(CheckedRedirect(uv))
    try:
        with opener.open(request, timeout=20) as response, partial.open("wb") as stream:
            if int(response.headers.get("Content-Length", "0")) > limit:
                raise SetupError("The download exceeds the permitted size.")
            total = 0
            digest = hashlib.sha256()
            last_report = 0.0
            while chunk := response.read(256 * 1024):
                if cancel.is_set():
                    raise Cancelled("Setup cancelled. No incomplete installation was activated.")
                total += len(chunk)
                if total > limit:
                    raise SetupError("The download exceeds the permitted size.")
                digest.update(chunk)
                stream.write(chunk)
                if time.monotonic() - last_report > 1:
                    report(f"Downloading {target.name}: {total // (1024 * 1024)} MB received")
                    last_report = time.monotonic()
        if expected_sha and digest.hexdigest() != expected_sha:
            raise SetupError(f"Checksum mismatch for {target.name}; the file was not used.")
        if cancel.is_set():
            raise Cancelled("Setup cancelled.")
        partial.replace(target)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise


def source_checksum(text: str) -> str:
    """Find exactly one checksum for the expected archive filename."""
    matches = re.findall(r"^([0-9a-fA-F]{64})\s+\*?bindsight-local\.zip\s*$", text, re.MULTILINE)
    if len(matches) != 1:
        raise SetupError("The release must provide exactly one source archive checksum.")
    return str(matches[0]).lower()


def validate_release(release: dict[str, Any], revision: str) -> None:
    """Refuse mixed publication generations instead of silently upgrading code."""
    if release.get("revision") != revision or release.get("repository") != PINS["repository"]:
        raise SetupError(
            "This download belongs to a different release. Download the latest companion from the Bindsight website and retry."
        )


def safe_member(name: str) -> PurePosixPath:
    """Reject ZIP/TAR paths that can escape or alias a different Windows file."""
    path = PurePosixPath(name)
    if (
        not name
        or "\\" in name
        or path.is_absolute()
        or any(
            part in {"", ".", ".."} or ":" in part or part.rstrip(" .") != part
            for part in name.rstrip("/").split("/")
        )
    ):
        raise SetupError(f"Unsafe archive path: {name!r}")
    reserved = {
        "con",
        "prn",
        "aux",
        "nul",
        *(f"com{i}" for i in range(1, 10)),
        *(f"lpt{i}" for i in range(1, 10)),
    }
    if any(part.split(".")[0].lower() in reserved for part in path.parts):
        raise SetupError("Archive contains a reserved device filename.")
    return path


def verify_source(archive: Path, sha: str, revision: str) -> list[zipfile.ZipInfo]:
    """Validate the entire archive before any member is extracted."""
    if (
        archive.stat().st_size > MAX_SOURCE_BYTES
        or hashlib.sha256(archive.read_bytes()).hexdigest() != sha
    ):
        raise SetupError("The source archive checksum or size is invalid.")
    with zipfile.ZipFile(archive) as bundle:
        members = bundle.infolist()
        seen: set[str] = set()
        total = 0
        for item in members:
            # ZipInfo normalizes backslashes on Windows; inspect original bytes'
            # decoded name so the same unsafe archive is rejected on every OS.
            path = safe_member(item.orig_filename)
            if path.parts[0] != "bindsight" or len(path.parts) < 2:
                raise SetupError("Unexpected archive layout.")
            key = item.filename.casefold().rstrip("/")
            mode = item.external_attr >> 16
            if (
                key in seen
                or stat.S_ISLNK(mode)
                or (stat.S_IFMT(mode) not in {0, stat.S_IFREG, stat.S_IFDIR})
            ):
                raise SetupError("Archive contains duplicate paths, links or special files.")
            seen.add(key)
            total += item.file_size
            if (
                len(members) > MAX_MEMBERS
                or total > MAX_EXPANDED_BYTES
                or item.file_size > MAX_SOURCE_BYTES
            ):
                raise SetupError("The expanded archive exceeds the permitted size.")
        required = {
            "bindsight/pyproject.toml",
            "bindsight/envs/constraints.txt",
            "bindsight/SOURCE_REVISION.json",
        }
        if not required.issubset({item.filename for item in members}):
            raise SetupError("The source archive is incomplete.")
        validate_release(json.loads(bundle.read("bindsight/SOURCE_REVISION.json")), revision)
        return members


def extract_source(
    archive: Path, destination: Path, sha: str, revision: str, cancel: threading.Event
) -> Path:
    """Extract regular files only, with resolved destination confinement."""
    members = verify_source(archive, sha, revision)
    destination.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(archive) as bundle:
        for item in members:
            if cancel.is_set():
                raise Cancelled("Setup cancelled during extraction.")
            target = inside(destination, destination / item.filename)
            if item.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(item) as source, target.open("xb") as sink:
                    shutil.copyfileobj(source, sink, 256 * 1024)
    return destination / "bindsight"


def extract_uv(archive: Path, destination: Path, key: str) -> Path:
    """Extract only the pinned uv executable; never trust archive link entries."""
    pin = PINS["artifacts"][key]
    if (
        archive.stat().st_size != pin["bytes"]
        or hashlib.sha256(archive.read_bytes()).hexdigest() != pin["sha256"]
    ):
        raise SetupError("The uv bootstrap archive failed verification.")
    destination.mkdir(parents=True, exist_ok=True)
    executable = destination / ("uv.exe" if key.startswith("windows") else "uv")
    if archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as bundle:
            candidates = [
                i for i in bundle.infolist() if PurePosixPath(i.filename).name == "uv.exe"
            ]
            if (
                len(candidates) != 1
                or stat.S_ISLNK(candidates[0].external_attr >> 16)
                or candidates[0].file_size > 150 * 1024 * 1024
            ):
                raise SetupError("Unexpected uv archive layout.")
            data = bundle.read(candidates[0])
    else:
        with tarfile.open(archive, "r:gz") as bundle:
            tar_candidates = [
                i for i in bundle.getmembers() if PurePosixPath(i.name).name == "uv" and i.isfile()
            ]
            if len(tar_candidates) != 1 or tar_candidates[0].size > 150 * 1024 * 1024:
                raise SetupError("Unexpected uv archive layout.")
            stream = bundle.extractfile(tar_candidates[0])
            if stream is None:
                raise SetupError("Missing uv executable.")
            with stream:
                data = stream.read()
    executable.write_bytes(data)
    executable.chmod(0o700)
    return executable


def private_environment(root: Path) -> dict[str, str]:
    """Ignore inherited package/Python configuration and keep all uv writes local."""
    env = {
        key: value
        for key, value in external_environment().items()
        if not key.startswith(("UV_", "PIP_", "PYTHON"))
    }
    env.pop("VIRTUAL_ENV", None)
    env.update(
        {
            "UV_CACHE_DIR": str(root / "cache"),
            "UV_PYTHON_INSTALL_DIR": str(root / "python"),
            "UV_PYTHON_INSTALL_BIN": "0",
            "UV_NO_CONFIG": "1",
            "UV_NO_PROGRESS": "1",
            "PYTHONNOUSERSITE": "1",
            "PYTHONUNBUFFERED": "1",
            "OMP_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
            "TMPDIR": str(root / "tmp"),
            "TEMP": str(root / "tmp"),
            "TMP": str(root / "tmp"),
            "MPLCONFIGDIR": str(root / "cache/matplotlib"),
            "XDG_CACHE_HOME": str(root / "cache"),
            "BINDSIGHT_CACHE_DIR": str(root / "cache/references"),
        }
    )
    return env


def external_environment() -> dict[str, str]:
    """Undo the frozen loader's search paths for external programs only.

    See PyInstaller's official common-issues documentation, section
    'Launching External Programs from the Frozen Application'.
    """
    env = dict(os.environ)
    if not getattr(sys, "frozen", False):
        return env
    if sys.platform.startswith("linux"):
        if "LD_LIBRARY_PATH_ORIG" in env:
            env["LD_LIBRARY_PATH"] = env["LD_LIBRARY_PATH_ORIG"]
        else:
            env.pop("LD_LIBRARY_PATH", None)
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        base = Path(bundle).resolve()
        for key in ("PATH", "DYLD_LIBRARY_PATH"):
            if key in env:
                env[key] = os.pathsep.join(
                    part
                    for part in env[key].split(os.pathsep)
                    if part and not Path(part).resolve().is_relative_to(base)
                )
    return env


@contextmanager
def external_libraries() -> Iterator[None]:
    """Let Windows children inherit system DLL search, then restore our loader."""
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        yield
        return
    with _DLL_LOCK:
        kernel = ctypes.windll.kernel32
        buffer = ctypes.create_unicode_buffer(32768)
        length = kernel.GetDllDirectoryW(len(buffer), buffer)
        if length >= len(buffer):
            raise SetupError("The process DLL directory is unexpectedly long.")
        if not kernel.SetDllDirectoryW(None):
            raise SetupError("Windows could not prepare the external program library paths.")
        try:
            yield
        finally:
            kernel.SetDllDirectoryW(buffer.value if length else None)


def stop_process(process: subprocess.Popen[str]) -> None:
    """Stop only this owned process tree; do not leave installation children running."""
    if process.poll() is not None:
        return
    if sys.platform == "win32":
        tool = Path(os.environ["SYSTEMROOT"]) / "System32/taskkill.exe"
        subprocess.run(
            [str(tool), "/PID", str(process.pid), "/T", "/F"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    else:
        os.killpg(process.pid, signal.SIGTERM)
    try:
        # The web workspace gracefully cancels its separately grouped jobs.
        # Give that cleanup time before force-killing the parent server.
        process.wait(timeout=5 if sys.platform == "win32" else 30)
    except subprocess.TimeoutExpired:
        if sys.platform == "win32":
            process.kill()
        else:
            os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=5)


class Installer:
    """Explicitly approved, resumable downloads with atomic readiness activation."""

    def __init__(
        self, root: Path, revision: str, report: Callable[[str], None], cancel: threading.Event
    ):
        if not re.fullmatch(r"[0-9a-f]{40}", revision):
            raise SetupError("A fixed 40-character source revision is required.")
        self.root, self.revision, self.report, self.cancel = (
            root.resolve(),
            revision,
            report,
            cancel,
        )
        self.process: subprocess.Popen[str] | None = None

    def command(
        self, args: list[str], cwd: Path, *, ready: Callable[[], None] | None = None
    ) -> None:
        """Stream actual command output; cancellation also covers quiet subprocesses."""
        if self.cancel.is_set():
            raise Cancelled("Setup cancelled.")
        inside(self.root, self.root / "tmp").mkdir(parents=True, exist_ok=True)
        options: dict[str, Any]
        if sys.platform == "win32":
            options = {
                "creationflags": subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
            }
        else:
            options = {"start_new_session": True}
        with external_libraries():
            self.process = subprocess.Popen(
                args,
                cwd=cwd,
                env=private_environment(self.root),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                shell=False,
                **options,
            )
        process = self.process

        def read() -> None:
            assert process.stdout is not None
            for line in process.stdout:
                self.report(line.rstrip())

        reader = threading.Thread(target=read, daemon=True)
        reader.start()
        try:
            while process.poll() is None:
                if self.cancel.wait(0.15):
                    stop_process(process)
                    raise Cancelled("Stopped. Partial setup files were retained for diagnosis.")
                if ready:
                    ready()
            reader.join(timeout=2)
            if process.returncode:
                raise SetupError(
                    f"A setup/application step exited with code {process.returncode}. See the log above."
                )
        finally:
            if process.poll() is None:
                stop_process(process)
            self.process = None

    def current(self) -> dict[str, Any] | None:
        """Read only a completed installation owned by this pinned companion."""
        marker = self.root / "current.json"
        if not marker.is_file():
            return None
        try:
            record: dict[str, Any] = json.loads(marker.read_text(encoding="utf-8"))
            if not isinstance(record, dict):
                raise ValueError("Expected an installation record")
        except (ValueError, UnicodeError):
            self.report(
                "The saved installation record is unreadable; approved setup can repair it."
            )
            return None
        if record.get("revision") != self.revision:
            return None
        for key in ["source", "python"]:
            if not isinstance(record.get(key), str):
                return None
            path = inside(self.root, self.root / record[key])
            if not path.exists():
                return None
        return record

    def install(self, *, approved: bool = False) -> dict[str, Any]:
        """Download and install only after an explicit UI approval action."""
        if not approved:
            raise SetupError("Select Set up Bindsight to approve the downloads and installation.")
        self.root.mkdir(parents=True, exist_ok=True)
        if shutil.disk_usage(self.root).free < 4 * 1024**3:
            raise SetupError("At least 4 GB of free storage is needed for CPU setup.")
        key = platform_key()
        downloads = inside(self.root, self.root / "downloads")
        downloads.mkdir(exist_ok=True)
        base = PINS["release_base"]
        self.report("Checking the published source revision and checksum…")
        release, sums = downloads / "release.json", downloads / "SHA256SUMS"
        download(base + "release.json", release, 64 * 1024, self.cancel, self.report)
        validate_release(json.loads(release.read_text()), self.revision)
        download(base + "downloads/SHA256SUMS", sums, 64 * 1024, self.cancel, self.report)
        sha = source_checksum(sums.read_text())
        archive = downloads / f"source-{sha}.zip"
        download(
            base + "downloads/bindsight-local.zip",
            archive,
            MAX_SOURCE_BYTES,
            self.cancel,
            self.report,
            expected_sha=sha,
        )
        verify_source(archive, sha, self.revision)
        pin = PINS["artifacts"][key]
        uv_archive = downloads / pin["name"]
        uv_url = (
            f"https://github.com/astral-sh/uv/releases/download/{PINS['uv_version']}/{pin['name']}"
        )
        self.report("Verifying the pinned Python setup tool…")
        download(
            uv_url,
            uv_archive,
            pin["bytes"],
            self.cancel,
            self.report,
            expected_sha=pin["sha256"],
            uv=True,
        )
        uv = extract_uv(
            uv_archive, inside(self.root, self.root / "tools" / PINS["uv_version"]), key
        )
        attempt = inside(
            self.root, self.root / "releases" / f"{self.revision}-{uuid.uuid4().hex[:8]}"
        )
        attempt.mkdir(parents=True)
        source = extract_source(archive, attempt / "source", sha, self.revision, self.cancel)
        self.report("Installing private Python 3.12; system Python and PATH are unchanged…")
        python_install_args = [
            str(uv),
            "python",
            "install",
            PINS["python_version"],
            "--no-bin",
            "--no-config",
        ]
        if sys.platform == "win32":
            python_install_args.append("--no-registry")
        self.command(python_install_args, attempt)
        environment = attempt / "environment"
        self.command(
            [
                str(uv),
                "venv",
                str(environment),
                "--python",
                PINS["python_version"],
                "--managed-python",
                "--no-python-downloads",
                "--no-config",
                "--no-project",
            ],
            attempt,
        )
        python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        self.report("Installing the constrained CPU analysis and browser workspace packages…")
        self.command(
            [
                str(uv),
                "pip",
                "install",
                "--python",
                str(python),
                "--index-url",
                "https://pypi.org/simple",
                "--constraint",
                str(source / "envs/constraints.txt"),
                "--no-config",
                "--editable",
                str(source) + "[discover,report]",
            ],
            source,
        )
        self.report("Checking that the installed workspace imports successfully…")
        self.command(
            [
                str(python),
                "-c",
                "import bindsight, pydeseq2, fastapi, uvicorn; from bindsight.report.web.app import create_app; print('CPU workspace imports verified')",
            ],
            source,
        )
        record = {
            "schema": "bindsight-companion-install/1",
            "revision": self.revision,
            "source_sha256": sha,
            "uv_version": PINS["uv_version"],
            "python_version": PINS["python_version"],
            "platform": key,
            "source": str(source.relative_to(self.root)),
            "python": str(python.relative_to(self.root)),
        }
        temporary = self.root / "current.json.partial"
        if self.cancel.is_set():
            raise Cancelled("Setup cancelled before activation.")
        temporary.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8", newline="\n")
        temporary.replace(self.root / "current.json")
        self.report("CPU setup completed. GPU models and CUDA were not installed.")
        return record

    def launch(self, record: dict[str, Any], open_browser: Callable[[str], None]) -> None:
        """Keep the server and lock alive; open a browser only after loopback responds."""
        source = inside(self.root, self.root / record["source"])
        python = inside(self.root, self.root / record["python"])
        runs = inside(self.root, self.root / "runs")
        runs.mkdir(exist_ok=True)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        url = f"http://127.0.0.1:{port}/workbench"
        opened = False
        deadline = time.monotonic() + 90
        owner = uuid.uuid4().hex
        running = self.root / "running.json"

        def ready() -> None:
            nonlocal opened
            if opened:
                return
            if time.monotonic() > deadline:
                raise SetupError(
                    "The local workspace did not become ready within 90 seconds. See its startup log."
                )
            try:
                with urllib.request.urlopen(url, timeout=0.2) as response:
                    if response.status == 200:
                        opened = True
                        running.write_text(
                            json.dumps({"revision": self.revision, "url": url, "owner": owner})
                            + "\n",
                            encoding="utf-8",
                            newline="\n",
                        )
                        self.report(f"Workspace ready: {url}")
                        open_browser(url)
            except OSError:
                return

        launcher = "from pathlib import Path; import sys; from bindsight.report.web.app import serve; serve(port=int(sys.argv[1]), open_browser=False, run_root=Path(sys.argv[2]))"
        try:
            self.command([str(python), "-c", launcher, str(port), str(runs)], source, ready=ready)
        finally:
            if running.is_file() and json.loads(running.read_text()).get("owner") == owner:
                running.unlink()

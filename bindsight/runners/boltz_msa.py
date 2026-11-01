# SPDX-License-Identifier: AGPL-3.0-or-later
"""Bound the verified Boltz MSA client's extraction and network wait.

Only that module's archive and HTTP helpers are wrapped. Its original function,
request payloads, retry order, random draws and successful MSA bytes are retained.
The alarm covers compute_msa, including paired and unpaired requests together.
"""

from __future__ import annotations

import functools
import hashlib
import importlib
import math
import os
import signal
import stat
import sys
import tarfile
import tempfile
import threading
import time
from contextlib import AbstractContextManager, suppress
from pathlib import Path, PurePosixPath
from typing import IO, Any
from urllib.parse import urlsplit

from bindsight.archive_bounds import open_bounded_tar

UPSTREAM_MSA_SHA256 = "64ceeda8287778c3ad643ebe11a70df9f7eeaa0f6d89c318b7ef8acadd1d3d29"
MAX_ARCHIVE_ENTRIES = 10_000
MAX_EXTRACTED_BYTES = 2 * 2**30
MAX_ARCHIVE_BYTES = 128 * 2**20
MAX_JSON_BYTES = 4 * 2**20
DEFAULT_TIMEOUT_SECONDS = 1800.0


class MSABoundaryError(BaseException):
    """Escape upstream retry/skip handlers; the outer CLI must report failure."""


class MSADeadlineExceeded(MSABoundaryError):
    """The complete MSA phase exceeded its configured wall-clock allowance."""


def _timeout() -> float:
    value = os.environ.get("BINDSIGHT_MSA_TIMEOUT", str(DEFAULT_TIMEOUT_SECONDS))
    try:
        seconds = float(value)
    except ValueError as error:
        raise ValueError(
            "BINDSIGHT_MSA_TIMEOUT must be positive and at most 21600 seconds"
        ) from error
    if not math.isfinite(seconds) or not 0 < seconds <= 21600:
        raise ValueError("BINDSIGHT_MSA_TIMEOUT must be positive and at most 21600 seconds")
    return seconds


def _check_path(path: Path, *, directory: bool = False) -> None:
    """Reject existing links and special files without resolving away links."""
    for candidate in reversed((path, *path.parents)):
        try:
            mode = candidate.lstat().st_mode
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(mode):
            raise ValueError("MSA extraction path contains a symbolic link")
        if candidate != path or directory:
            if not stat.S_ISDIR(mode):
                raise ValueError("MSA extraction parent is not a directory")
        elif not stat.S_ISREG(mode):
            raise ValueError("MSA extraction destination is not a regular file")


def _member_name(member: tarfile.TarInfo) -> str:
    raw = member.name
    if not (member.isdir() or member.isfile()) or member.sparse is not None or member.size < 0:
        raise ValueError("Unsafe MSA archive member")
    if raw.startswith("/") or "\\" in raw or ":" in raw or "\x00" in raw:
        raise ValueError("Unsafe MSA archive path")
    while raw.startswith("./"):
        raw = raw[2:]
    raw = raw.rstrip("/") if member.isdir() else raw
    if member.isdir() and raw in {"", "."}:
        return "."
    if not raw or any(part in {"", ".", ".."} for part in raw.split("/")):
        raise ValueError("Unsafe MSA archive member")
    return raw


def _hash_stream(source: IO[bytes], maximum: int, output: IO[bytes] | None = None) -> str:
    digest, size = hashlib.sha256(), 0
    while block := source.read(min(1024 * 1024, maximum - size + 1)):
        size += len(block)
        if size > maximum:
            raise ValueError("MSA archive member exceeds declared size")
        digest.update(block)
        if output is not None:
            output.write(block)
    if size != maximum:
        raise ValueError("MSA archive member is truncated")
    return digest.hexdigest()


def _safe_extract(archive: tarfile.TarFile, destination: Path) -> None:
    destination = destination.absolute()
    _check_path(destination, directory=True)
    members: dict[str, tarfile.TarInfo] = {}
    total = 0
    for member in archive:
        name = _member_name(member)
        if name in members:
            raise ValueError("Duplicate MSA archive member")
        members[name] = member
        total += member.size
        if len(members) > MAX_ARCHIVE_ENTRIES or total > MAX_EXTRACTED_BYTES:
            raise ValueError("MSA archive exceeds extraction limits")
    if not members:
        raise ValueError("MSA archive is empty")
    files = {name for name, member in members.items() if member.isfile()}
    if not files:
        raise ValueError("MSA archive contains no regular files")
    hashes: dict[str, str] = {}
    # Complete metadata, existing-destination and payload validation precedes
    # every filesystem write, including creation of staging directories.
    for name, member in members.items():
        if any(parent.as_posix() in files for parent in PurePosixPath(name).parents):
            raise ValueError("Conflicting MSA archive file and directory paths")
        target = destination / name
        _check_path(target, directory=member.isdir())
        if member.isfile():
            stream = archive.extractfile(member)
            if stream is None:
                raise ValueError("Missing MSA archive payload")
            with stream:
                hashes[name] = _hash_stream(stream, member.size)
            if target.exists():
                if target.stat().st_size != member.size:
                    raise ValueError("Existing MSA file differs from archive")
                with target.open("rb") as existing:
                    if _hash_stream(existing, member.size) != hashes[name]:
                        raise ValueError("Existing MSA file differs from archive")

    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".bindsight-msa-", dir=destination.parent) as temporary:
        staging = Path(temporary)
        for name in sorted(files):
            member = members[name]
            staged = staging / name
            staged.parent.mkdir(parents=True, exist_ok=True)
            stream = archive.extractfile(member)
            if stream is None:
                raise ValueError("Missing MSA archive payload")
            with stream, staged.open("xb") as output:
                if _hash_stream(stream, member.size, output) != hashes[name]:
                    raise ValueError("MSA archive changed during extraction")
        _check_path(destination, directory=True)
        destination.mkdir(parents=True, exist_ok=True)
        for name, member in members.items():
            target = destination / name
            _check_path(target, directory=member.isdir())
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                # Exclusive creation also rejects a link appearing at the final
                # filename and works on filesystems without hard-link support.
                with target.open("xb") as output, (staging / name).open("rb") as staged_stream:
                    _hash_stream(staged_stream, member.size, output)
            except FileExistsError:
                _check_path(target)
                if target.stat().st_size != member.size:
                    raise ValueError("Existing MSA file differs from archive") from None
                with target.open("rb") as existing:
                    if _hash_stream(existing, member.size) != hashes[name]:
                        raise ValueError("Existing MSA file differs from archive") from None


class _SafeTarFile:
    def __init__(
        self, archive: tarfile.TarFile, context: AbstractContextManager[tarfile.TarFile]
    ) -> None:
        self._archive = archive
        self._context = context

    def __enter__(self) -> _SafeTarFile:
        return self

    def __exit__(self, *arguments: Any) -> Any:
        return self._context.__exit__(*arguments)

    def close(self) -> None:
        self._context.__exit__(None, None, None)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._archive, name)

    def extractall(self, path: Any = ".", members: Any = None, **kwargs: Any) -> None:
        if members is not None or kwargs:
            raise MSABoundaryError("Unsupported MSA archive extraction options")
        try:
            _safe_extract(self._archive, Path(path))
        except (ValueError, OSError, tarfile.TarError) as error:
            raise MSABoundaryError(f"Unsafe Boltz MSA archive: {error}") from error


class _TarfileProxy:
    def open(self, *args: Any, **kwargs: Any) -> _SafeTarFile:
        # Upstream passes one cached archive pathname. Tests may pass a seekable
        # BytesIO instead. Neither case trusts a network Content-Length header.
        filename = args[0] if args else kwargs.get("name")
        stream = kwargs.get("fileobj")
        try:
            if filename is not None:
                _check_path(Path(filename).absolute())
                size = Path(filename).stat().st_size
            elif stream is not None:
                position = stream.tell()
                stream.seek(0, os.SEEK_END)
                size = stream.tell()
                stream.seek(position)
            else:
                raise ValueError("MSA archive must have a bounded source")
            if not 0 < size <= MAX_ARCHIVE_BYTES:
                raise ValueError("MSA compressed archive exceeds size limits or is empty")
            mode = args[1] if len(args) > 1 else kwargs.get("mode", "r")
            if len(args) > 2 or mode not in {"r", "r:*", "r:gz", "r:"}:
                raise ValueError("Unsupported MSA archive open options")
            if set(kwargs) - {"name", "mode", "fileobj", "encoding"}:
                raise ValueError("Unsupported MSA archive open options")
            bounded_source: Any = filename if filename is not None else stream
            context = open_bounded_tar(
                bounded_source,
                max_bytes=MAX_EXTRACTED_BYTES,
                max_members=MAX_ARCHIVE_ENTRIES,
                encoding=kwargs.get("encoding", "utf-8"),
            )
            return _SafeTarFile(context.__enter__(), context)
        except (ValueError, OSError, EOFError, tarfile.TarError) as error:
            raise MSABoundaryError(f"Unsafe Boltz MSA archive: {error}") from error

    def __getattr__(self, name: str) -> Any:
        return getattr(tarfile, name)


class _RequestsProxy:
    def __init__(self, requests_module: Any):
        self._requests = requests_module

    def _request(self, method: str, url: str, *args: Any, **kwargs: Any) -> Any:
        limit = (
            MAX_ARCHIVE_BYTES
            if method == "get" and "/result/download/" in urlsplit(url).path
            else MAX_JSON_BYTES
        )
        kwargs["stream"] = True
        response = getattr(self._requests, method)(url, *args, **kwargs)
        try:
            blocks, size = [], 0
            for block in response.iter_content(chunk_size=64 * 1024):
                size += len(block)
                if size > limit:
                    raise MSABoundaryError("Boltz MSA server response exceeds the size limit")
                blocks.append(block)
            # This is the same decoded bytes requests ordinarily caches for
            # stream=False. Keep its Response.json/text behavior unchanged.
            response._content = b"".join(blocks)
            response._content_consumed = True
        except BaseException:
            # Cleanup must not replace the one-shot deadline with an ordinary
            # exception that upstream's infinite retry handler would catch.
            # A new deadline arriving during cleanup must also escape; suppress
            # ordinary cleanup errors only, never fatal boundary exceptions.
            with suppress(Exception):
                response.close()
            raise
        else:
            response.close()
            return response

    def get(self, url: str, *args: Any, **kwargs: Any) -> Any:
        return self._request("get", url, *args, **kwargs)

    def post(self, url: str, *args: Any, **kwargs: Any) -> Any:
        return self._request("post", url, *args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._requests, name)


def configure_msa(boltz_main: Any) -> None:
    """Install a verified-source hook without changing upstream files or global modules."""
    module: Any = importlib.import_module("boltz.data.msa.mmseqs2")
    source = getattr(module, "__file__", None)
    if (
        not source
        or Path(source).is_symlink()
        or hashlib.sha256(Path(source).read_bytes()).hexdigest() != UPSTREAM_MSA_SHA256
    ):
        raise RuntimeError("Boltz MSA source differs from the reviewed upstream 2.0.3 module")
    seconds = _timeout()
    original = boltz_main.compute_msa
    if getattr(original, "_bindsight_msa_boundary", False):
        return

    @functools.wraps(original)
    def compute_msa(*args: Any, **kwargs: Any) -> Any:
        if (
            not sys.platform.startswith("linux")
            or threading.current_thread() is not threading.main_thread()
        ):
            raise RuntimeError("Bounded Boltz MSA execution requires the Linux main thread")
        previous_timer = signal.getitimer(signal.ITIMER_REAL)
        if previous_timer != (0.0, 0.0):
            raise RuntimeError("Cannot bound Boltz MSA while another real-time alarm is active")
        previous_handler = signal.getsignal(signal.SIGALRM)
        started = time.monotonic()
        outcome = "failed"

        def deadline(_signum: int, _frame: Any) -> None:
            raise MSADeadlineExceeded(f"Boltz MSA phase exceeded {seconds:g} seconds")

        print(f"bindsight: MSA phase begin timeout={seconds:g}s", flush=True)
        signal.signal(signal.SIGALRM, deadline)
        try:
            signal.setitimer(signal.ITIMER_REAL, seconds)
            result = original(*args, **kwargs)
            outcome = "complete"
            return result
        except MSADeadlineExceeded:
            outcome = "deadline-exceeded"
            raise
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous_handler)
            print(
                f"bindsight: MSA phase {outcome} elapsed={time.monotonic() - started:.3f}s",
                flush=True,
            )

    compute_msa._bindsight_msa_boundary = True  # type: ignore[attr-defined]
    module.tarfile = _TarfileProxy()
    module.requests = _RequestsProxy(module.requests)
    boltz_main.compute_msa = compute_msa

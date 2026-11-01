# SPDX-License-Identifier: AGPL-3.0-or-later
"""Explicit, bounded candidate-wheel transport for hosted GPU wrappers.

These stdlib-only helpers are embedded in Colab and Modal image bootstrap code.
An explicit caller-supplied wheel is trusted code, but its transport is checked
before installation. No working tree is selected implicitly.
"""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
import zipfile
from email.parser import BytesParser
from pathlib import Path, PurePosixPath
from typing import Any

MAX_CANDIDATE_BYTES = 64 * 1024 * 1024


def verify_candidate(path: Path, source: dict[str, Any]) -> None:
    """Check exact bytes and wheel identity before any installer executes them."""
    filename = source.get("filename", "")
    version = source.get("version", "")
    size = source.get("bytes")
    digest = source.get("sha256", "")
    if (
        not isinstance(version, str)
        or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+[a-zA-Z0-9.+]*", version)
        or filename != f"bindsight-{version}-py3-none-any.whl"
        or type(size) is not int
        or not 0 < size <= MAX_CANDIDATE_BYTES
        or not isinstance(digest, str)
        or not re.fullmatch(r"[0-9a-f]{64}", digest)
    ):
        raise ValueError("Invalid candidate wheel identity.")
    if path.is_symlink() or not path.is_file() or path.stat().st_size != size:
        raise ValueError("Candidate wheel size or file type mismatch.")
    with path.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != digest:
            raise ValueError("Candidate wheel SHA256 mismatch.")
    with zipfile.ZipFile(path) as wheel:
        entries = wheel.infolist()
        names = [entry.filename for entry in entries]
        if (
            len(entries) > 10000
            or len(set(names)) != len(names)
            or sum(entry.file_size for entry in entries) > 256 * 1024 * 1024
            or any(
                "\\" in name or name.startswith("/") or ".." in PurePosixPath(name).parts
                for name in names
            )
        ):
            raise ValueError("Candidate wheel has unsafe or excessive members.")
        expected = f"bindsight-{version}.dist-info/METADATA"
        metadata = [entry for entry in entries if entry.filename.endswith(".dist-info/METADATA")]
        if (
            len(metadata) != 1
            or metadata[0].filename != expected
            or not 0 < metadata[0].file_size <= 2 * 1024 * 1024
        ):
            raise ValueError("Candidate wheel has invalid package metadata.")
        message = BytesParser().parsebytes(wheel.read(metadata[0]))
        if message.get_all("Name") != ["bindsight"] or message.get_all("Version") != [version]:
            raise ValueError("Candidate wheel metadata does not match its identity.")


def candidate_source(path: Path) -> dict[str, Any]:
    """Describe and validate a deliberately selected universal Bindsight wheel."""
    path = Path(path)
    match = re.fullmatch(r"bindsight-(.+)-py3-none-any\.whl", path.name)
    if not match or path.is_symlink() or not path.is_file():
        raise ValueError("Select a regular Bindsight universal candidate wheel.")
    size = path.stat().st_size
    if not 0 < size <= MAX_CANDIDATE_BYTES:
        raise ValueError("Candidate wheel exceeds its size limit.")
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    source = {
        "kind": "candidate-wheel",
        "filename": path.name,
        "version": match[1],
        "bytes": size,
        "sha256": digest,
    }
    verify_candidate(path, source)
    return source


def write_candidate(data: bytes, source: dict[str, Any], directory: Path) -> Path:
    """Atomically materialize a transported wheel only after full validation."""
    if not 0 < len(data) <= MAX_CANDIDATE_BYTES or len(data) != source.get("bytes"):
        raise ValueError("Transported candidate wheel size mismatch.")
    directory = Path(directory)
    if directory.is_symlink():
        raise ValueError("Candidate directory must not be a symlink.")
    directory.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=directory, prefix=".candidate-", delete=False) as out:
            temporary = Path(out.name)
            out.write(data)
        verify_candidate(temporary, source)
        destination = directory / str(source["filename"])
        if destination.is_symlink():
            raise ValueError("Candidate destination must not be a symlink.")
        temporary.replace(destination)
        destination.with_suffix(".source.json").write_text(
            json.dumps(source, indent=2) + "\n", encoding="utf-8", newline="\n"
        )
        return destination
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)

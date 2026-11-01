# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fetch one exact published Bindsight wheel without running downloaded code.

The functions use only the standard library so the same reviewed source can
bootstrap a private driver in a notebook that has no Bindsight installation.
"""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
import urllib.parse
import urllib.request
import zipfile
from email.parser import BytesParser
from pathlib import Path
from typing import Any

MAX_WHEEL_BYTES = 64 * 1024 * 1024
MAX_METADATA_BYTES = 2 * 1024 * 1024


def published_version(value: str) -> str:
    """Only public release versions can identify the remote source snapshot."""
    if not isinstance(value, str) or not re.fullmatch(
        r"[0-9]+\.[0-9]+\.[0-9]+(?:(?:a|b|rc)[0-9]+)?(?:\.post[0-9]+)?", value
    ):
        raise ValueError("Remote setup requires an exact published Bindsight release version.")
    return value


def _approved_url(url: str, *, host: str, filename: str) -> bool:
    try:
        if not isinstance(url, str) or any(ord(character) <= 32 for character in url):
            return False
        parsed = urllib.parse.urlsplit(url)
        return (
            parsed.scheme == "https"
            and parsed.hostname == host
            and parsed.netloc == host
            and not parsed.query
            and not parsed.fragment
            and "%" not in parsed.path
            and "\\" not in parsed.path
            and ".." not in parsed.path.split("/")
            and (
                parsed.path == filename
                if host == "pypi.org"
                else parsed.path.startswith("/packages/")
                and parsed.path.rsplit("/", 1)[-1] == filename
            )
        )
    except (TypeError, ValueError):
        return False


class _ReleaseRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, host: str, filename: str):
        self.host = host
        self.filename = filename

    def redirect_request(
        self, req: urllib.request.Request, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> urllib.request.Request | None:
        if not _approved_url(newurl, host=self.host, filename=self.filename):
            raise ValueError("Release download redirected outside its approved HTTPS source.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _read_https(url: str, *, host: str, filename: str, maximum: int) -> bytes:
    if not _approved_url(url, host=host, filename=filename):
        raise ValueError("Release download URL is outside its approved HTTPS source.")
    opener = urllib.request.build_opener(_ReleaseRedirect(host, filename))
    request = urllib.request.Request(
        url, headers={"User-Agent": "Bindsight-release-bootstrap", "Accept-Encoding": "identity"}
    )
    with opener.open(request, timeout=45) as response:
        if not _approved_url(response.geturl(), host=host, filename=filename):
            raise ValueError("Release response came from an unapproved source.")
        data: bytes = response.read(maximum + 1)
    if not data or len(data) > maximum:
        raise ValueError("Release download is empty or exceeds its size limit.")
    return data


def _check_wheel(path: Path, *, version: str, size: int, digest: str) -> None:
    if path.is_symlink() or not path.is_file() or path.stat().st_size != size:
        raise ValueError("The Bindsight wheel does not match its published size.")
    with path.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != digest:
            raise ValueError("The Bindsight wheel does not match its published SHA256.")
    metadata_name = f"bindsight-{version}.dist-info/METADATA"
    with zipfile.ZipFile(path) as wheel:
        entries = [info for info in wheel.infolist() if info.filename == metadata_name]
        if len(entries) != 1 or not 0 < entries[0].file_size <= MAX_METADATA_BYTES:
            raise ValueError("The Bindsight wheel has invalid package metadata.")
        metadata = BytesParser().parsebytes(wheel.read(entries[0]))
    if metadata.get_all("Name") != ["bindsight"] or metadata.get_all("Version") != [version]:
        raise ValueError("The Bindsight wheel metadata does not identify the requested release.")


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Release metadata contains duplicate JSON keys.")
        result[key] = value
    return result


def download_release_wheel(version: str, directory: Path) -> Path:
    """Verify PyPI release identity, official URL, exact length and digest before use."""
    version = published_version(version)
    metadata_path = f"/pypi/bindsight/{version}/json"
    metadata_url = "https://pypi.org" + metadata_path
    metadata = json.loads(
        _read_https(
            metadata_url, host="pypi.org", filename=metadata_path, maximum=MAX_METADATA_BYTES
        ),
        object_pairs_hook=_unique_json_object,
    )
    if (
        not isinstance(metadata, dict)
        or not isinstance(metadata.get("info"), dict)
        or metadata["info"].get("version") != version
        or not isinstance(metadata.get("urls"), list)
        or not all(isinstance(item, dict) for item in metadata["urls"])
    ):
        raise ValueError("PyPI metadata does not identify the requested Bindsight version.")
    filename = f"bindsight-{version}-py3-none-any.whl"
    candidates = [
        item
        for item in metadata.get("urls", [])
        if item.get("filename") == filename and item.get("packagetype") == "bdist_wheel"
    ]
    if len(candidates) != 1 or candidates[0].get("yanked"):
        raise ValueError("The requested release has no unique, non-yanked universal wheel.")
    artifact = candidates[0]
    size = artifact.get("size")
    digests = artifact.get("digests")
    digest = digests.get("sha256", "") if isinstance(digests, dict) else ""
    url = artifact.get("url", "")
    if (
        type(size) is not int
        or not 0 < size <= MAX_WHEEL_BYTES
        or not isinstance(digest, str)
        or not re.fullmatch(r"[0-9a-f]{64}", digest)
        or not _approved_url(url, host="files.pythonhosted.org", filename=filename)
    ):
        raise ValueError("The published wheel has invalid size, digest or download metadata.")
    directory = Path(directory)
    if directory.is_symlink():
        raise ValueError("The release cache must not be a symlink.")
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / filename
    if destination.exists() or destination.is_symlink():
        _check_wheel(destination, version=version, size=size, digest=digest)
    else:
        data = _read_https(url, host="files.pythonhosted.org", filename=filename, maximum=size)
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=directory, prefix=".release-", delete=False
            ) as out:
                temporary = Path(out.name)
                out.write(data)
            _check_wheel(temporary, version=version, size=size, digest=digest)
            temporary.replace(destination)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    destination.with_suffix(".source.json").write_text(
        json.dumps(
            {
                "version": version,
                "filename": filename,
                "metadata_url": metadata_url,
                "local_checkout_used": False,
                "url": url,
                "sha256": digest,
                "size_bytes": size,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return destination

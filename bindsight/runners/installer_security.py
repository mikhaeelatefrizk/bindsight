# SPDX-License-Identifier: AGPL-3.0-or-later
"""Verified independent package installer shared by managed GPU backends.

Bootstrap functions can be embedded before Bindsight is installed. Keep their
dependencies in the standard library and retain identical artifact verification
for every official download source.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

UV_VERSION = "0.13.6"
UV_ARCHIVE_URL = (
    "https://releases.astral.sh/github/uv/releases/download/0.13.6/"
    "uv-x86_64-unknown-linux-gnu.tar.gz"
)
UV_ARCHIVE_URLS = (
    UV_ARCHIVE_URL,
    "https://github.com/astral-sh/uv/releases/download/0.13.6/uv-x86_64-unknown-linux-gnu.tar.gz",
)
UV_ARCHIVE_BYTES = 16799024
UV_ARCHIVE_SHA256 = "f29c3e94ffabd7e6f3ba521dba169a9b7ec12100bf3257087f0f24f6123f3645"
CERTIFI_REQUIREMENT = "certifi>=2026.10.19"
MICROMAMBA_URL = (
    "https://github.com/mamba-org/micromamba-releases/releases/download/2.3.2-0/micromamba-linux-64"
)
MICROMAMBA_SHA256 = "ffc3cb8d52d4d6b354bdbb979c407719c485392b74e462cbd50811aa88e58f85"


def write_verified_micromamba(executable: bytes, destination: Path) -> Path:
    """Write the pinned environment manager only after checking its full digest."""
    import hashlib

    if (
        not 0 < len(executable) <= 100 * 2**20
        or hashlib.sha256(executable).hexdigest() != MICROMAMBA_SHA256
    ):
        raise RuntimeError("The micromamba executable does not match its pinned SHA256.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".partial")
    temporary.write_bytes(executable)
    temporary.chmod(0o755)
    temporary.replace(destination)
    return destination


def extract_verified_uv(archive: bytes, destination: Path) -> Path:
    """Verify the full official archive before writing its sole requested executable."""
    import hashlib
    import io
    import tarfile

    if len(archive) != UV_ARCHIVE_BYTES or hashlib.sha256(archive).hexdigest() != UV_ARCHIVE_SHA256:
        raise RuntimeError("The uv archive does not match its official size and SHA256.")
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as bundle:
        matches = [m for m in bundle.getmembers() if m.name == "uv-x86_64-unknown-linux-gnu/uv"]
        if len(matches) != 1 or not matches[0].isfile() or not 0 < matches[0].size < 100 * 2**20:
            raise RuntimeError("The verified uv archive has an unexpected executable entry.")
        stream = bundle.extractfile(matches[0])
        if stream is None:
            raise RuntimeError("The verified uv executable could not be read.")
        with stream:
            executable = stream.read()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".partial")
    temporary.write_bytes(executable)
    temporary.chmod(0o755)
    temporary.replace(destination)
    return destination


def download_verified_uv(destination: Path, *, report: Callable[[str], None] | None = None) -> Path:
    """Fetch from official sources only; transport fallback never relaxes integrity."""
    import json
    import urllib.error
    import urllib.request

    archive = destination.with_suffix(".tar.gz")
    provenance = destination.with_suffix(".download.json")
    attempts: list[dict[str, str]] = []
    if archive.is_file():
        if report:
            report("Verifying the cached independent package installer")
        if archive.stat().st_size != UV_ARCHIVE_BYTES:
            raise RuntimeError("The cached uv archive does not match its official size.")
        return extract_verified_uv(archive.read_bytes(), destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    for url in UV_ARCHIVE_URLS:
        try:
            with urllib.request.urlopen(url, timeout=45) as response:
                data = response.read(UV_ARCHIVE_BYTES + 1)
        except (urllib.error.URLError, TimeoutError) as error:
            attempts.append({"url": url, "error": str(error)})
            if report:
                report(f"Installer download unavailable from {url}: {error}")
            if url == UV_ARCHIVE_URLS[-1]:
                provenance.write_text(
                    json.dumps({"attempts": attempts}, indent=2) + "\n",
                    encoding="utf-8",
                    newline="\n",
                )
                raise
            continue
        # Hash or archive-layout errors are fatal; do not fall back after one.
        extract_verified_uv(data, destination)
        temporary = archive.with_name(archive.name + ".partial")
        temporary.write_bytes(data)
        temporary.replace(archive)
        attempts.append({"url": url, "sha256": UV_ARCHIVE_SHA256})
        provenance.write_text(
            json.dumps({"source": url, "attempts": attempts, "sha256": UV_ARCHIVE_SHA256}, indent=2)
            + "\n",
            encoding="utf-8",
            newline="\n",
        )
        if report:
            report(f"Verified independent package installer from {url}")
        return destination
    raise RuntimeError("No approved package installer source is configured.")


def package_environment(environment: dict[str, str], cache: Path) -> dict[str, str]:
    """Keep inherited installer configuration from changing indexes or TLS validation."""
    blocked = {
        "VIRTUAL_ENV",
        "CONDA_PREFIX",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "CURL_CA_BUNDLE",
        "PYTHONPATH",
        "PYTHONHOME",
        "PYTHONSTARTUP",
        "PYTHONUSERBASE",
    }
    clean = {
        key: value
        for key, value in environment.items()
        if not key.startswith(("UV_", "PIP_")) and key not in blocked
    }
    clean.update(UV_CACHE_DIR=str(cache), UV_NO_PROGRESS="1", UV_NO_PYTHON_DOWNLOADS="1")
    return clean


def uv_install_command(executable: Path, python: Path, arguments: list[str]) -> list[str]:
    """Target the exact owned interpreter while preserving pip's multi-index resolution."""
    return [
        str(executable),
        "--no-config",
        "pip",
        "install",
        "--python",
        str(python),
        "--index-url",
        "https://pypi.org/simple",
        # Existing recipes resolve the best matching wheel across PyPI and the
        # fixed official PyTorch index. Keep those semantics and scientific pins.
        "--index-strategy",
        "unsafe-best-match",
        *arguments,
        CERTIFI_REQUIREMENT,
    ]

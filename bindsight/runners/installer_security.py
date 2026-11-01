# SPDX-License-Identifier: AGPL-3.0-or-later
"""Verified external installer for legacy scientific Python environments.

Python 3.9 cannot run the patched pip 26.2.2. Package downloads therefore run
through this independent uv executable; this does not make Python 3.9 supported.
The same functions are embedded in the standalone Kaggle script before Bindsight
is installed there. Keep them self-contained and free of package imports.
"""

from __future__ import annotations

from pathlib import Path

UV_VERSION = "0.13.6"
UV_ARCHIVE_URL = (
    "https://releases.astral.sh/github/uv/releases/download/0.13.6/"
    "uv-x86_64-unknown-linux-gnu.tar.gz"
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


def package_environment(environment: dict[str, str], cache: Path) -> dict[str, str]:
    """Keep inherited installer configuration from changing indexes or TLS validation."""
    blocked = {"VIRTUAL_ENV", "CONDA_PREFIX", "SSL_CERT_FILE", "SSL_CERT_DIR", "CURL_CA_BUNDLE"}
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

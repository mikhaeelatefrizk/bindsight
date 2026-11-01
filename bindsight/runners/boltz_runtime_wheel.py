# SPDX-License-Identifier: AGPL-3.0-or-later
"""An auditable dependency-only patch of the unchanged Boltz 2.0.3 implementation.

The upstream wheel pins vulnerable orchestration/HTTP/parser dependencies. This
downstream local version changes package metadata, never scientific source,
model architecture, weights, or numerical parameters. Runtime GPU acceptance
is separate from the byte-preservation proof recorded here.
"""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

UPSTREAM_VERSION = "2.0.3"
RUNTIME_VERSION = "2.0.3+bindsight.1"
UPSTREAM_URL = (
    "https://files.pythonhosted.org/packages/10/ce/"
    "60902bf1cde0444b690e965b25efb32c82b6029acaec3cb8ad944bfcb4df/"
    "boltz-2.0.3-py3-none-any.whl"
)
UPSTREAM_BYTES = 263964
UPSTREAM_SHA256 = "5851dd10c7819d4c011534a4e5c9cc495d95e42e0e1336617a1e9e78d6c4cf12"
UPSTREAM_MAIN_SHA256 = "655e5b93a89cb31686778dcf98e6e19f2763e074319d589398b03156a8ccfc65"
DEPENDENCY_PATCHES = {
    "hydra-core": ("1.3.2", "1.3.8"),
    "pytorch-lightning": ("2.5.0", "2.6.6"),
    "requests": ("2.32.3", "2.34.2"),
    "biopython": ("1.84", "1.88"),
}


def _patch_bytes(original: bytes) -> tuple[bytes, dict[str, Any]]:
    """Refuse unknown input and deterministically rebuild valid wheel metadata."""
    if len(original) != UPSTREAM_BYTES or hashlib.sha256(original).hexdigest() != UPSTREAM_SHA256:
        raise ValueError("Boltz upstream wheel does not match its reviewed size and SHA256")
    old_info = f"boltz-{UPSTREAM_VERSION}.dist-info/"
    new_info = f"boltz-{RUNTIME_VERSION}.dist-info/"
    with zipfile.ZipFile(io.BytesIO(original)) as source:
        names = source.namelist()
        if (
            len(names) != len(set(names))
            or sum(x.file_size for x in source.infolist()) > 16 * 2**20
        ):
            raise ValueError("Boltz wheel has duplicate or oversized members")
        if any(not n.startswith(("boltz/", old_info)) or ".." in n.split("/") for n in names):
            raise ValueError("Boltz wheel has an unexpected member")
        contents = {name: source.read(name) for name in names}
    metadata = contents[old_info + "METADATA"]
    replacements = {
        f"Version: {UPSTREAM_VERSION}": f"Version: {RUNTIME_VERSION}",
        **{
            f"Requires-Dist: {name} =={old}": f"Requires-Dist: {name} =={new}"
            for name, (old, new) in DEPENDENCY_PATCHES.items()
        },
    }
    header, separator, description = metadata.partition(b"\n\n")
    if not separator:
        raise ValueError("Boltz metadata has no header boundary")
    lines = header.split(b"\n")
    for old, new in replacements.items():
        if lines.count(old.encode()) != 1:
            raise ValueError(f"Boltz metadata differs from the reviewed requirement: {old}")
        lines[lines.index(old.encode())] = new.encode()
    contents[old_info + "METADATA"] = b"\n".join(lines) + separator + description
    del contents[old_info + "RECORD"]
    contents = {name.replace(old_info, new_info, 1): data for name, data in contents.items()}
    payload_hashes = {
        name: hashlib.sha256(data).hexdigest()
        for name, data in sorted(contents.items())
        if name.startswith("boltz/")
    }
    record = io.StringIO(newline="")
    writer = csv.writer(record, lineterminator="\n")
    for name, data in sorted(contents.items()):
        digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
        writer.writerow([name, "sha256=" + digest, len(data)])
    writer.writerow([new_info + "RECORD", "", ""])
    contents[new_info + "RECORD"] = record.getvalue().encode()
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as wheel:
        for name, data in sorted(contents.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            wheel.writestr(info, data)
    patched = output.getvalue()
    # Compare the final archive, not just the pre-serialization dictionary.
    with (
        zipfile.ZipFile(io.BytesIO(original)) as source,
        zipfile.ZipFile(io.BytesIO(patched)) as final,
    ):
        for name in source.namelist():
            if name in {old_info + "METADATA", old_info + "RECORD"}:
                continue
            if source.read(name) != final.read(name.replace(old_info, new_info, 1)):
                raise RuntimeError("Dependency patch changed a Boltz implementation/resource file")
    receipt = {
        "schema": "bindsight-boltz-dependency-patch/1",
        "upstream_version": UPSTREAM_VERSION,
        "installed_version": RUNTIME_VERSION,
        "upstream_url": UPSTREAM_URL,
        "upstream_sha256": UPSTREAM_SHA256,
        "patched_sha256": hashlib.sha256(patched).hexdigest(),
        "dependency_changes": {
            name: {"from": old, "to": new} for name, (old, new) in DEPENDENCY_PATCHES.items()
        },
        "unchanged_implementation": True,
        "unchanged_package_files": payload_hashes,
        "scope": "Version/dependency metadata, dist-info directory name and regenerated RECORD only; license and all implementation/resource bytes retained",
    }
    return patched, receipt


def prepare_boltz_runtime_wheel(directory: Path) -> tuple[Path, dict[str, Any]]:
    """Fetch a fixed public wheel, verify it, and retain its explicit downstream identity."""
    if directory.is_symlink():
        raise ValueError("Boltz wheel cache must not be a symbolic link")
    directory.mkdir(parents=True, exist_ok=True)
    source = directory / f"boltz-{UPSTREAM_VERSION}-py3-none-any.whl"
    if source.is_symlink():
        raise ValueError("Boltz upstream cache must not be a symbolic link")
    if source.exists():
        original = source.read_bytes()
    else:
        with urllib.request.urlopen(UPSTREAM_URL, timeout=45) as response:
            original = response.read(UPSTREAM_BYTES + 1)
    patched, receipt = _patch_bytes(original)
    if not source.exists():
        source.write_bytes(original)
    destination = directory / f"boltz-{RUNTIME_VERSION}-py3-none-any.whl"
    if destination.is_symlink() or (destination.exists() and destination.read_bytes() != patched):
        raise ValueError("Boltz downstream cache differs from the reviewed dependency patch")
    destination.write_bytes(patched)
    evidence = directory / "boltz-dependency-patch.json"
    if evidence.is_symlink():
        raise ValueError("Boltz patch receipt must not be a symbolic link")
    evidence.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8", newline="\n")
    return destination, receipt

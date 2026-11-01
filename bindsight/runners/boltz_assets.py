# SPDX-License-Identifier: AGPL-3.0-or-later
"""Authenticate publisher-pinned Boltz assets before upstream cache-only use."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import tarfile
import tempfile
from pathlib import Path
from typing import IO, Any, TypedDict


class AssetPin(TypedDict):
    """Publisher-declared identity of one immutable model asset."""

    bytes: int
    sha256: str


PUBLISHER_REVISION = "6fdef46d763fee7fbb83ca5501ccceff43b85607"
ASSETS: dict[str, AssetPin] = {
    "boltz2_conf.ckpt": {
        "bytes": 2286561469,
        "sha256": "090e82ac8c92f5e943fa1b39e7410a44027bea7243c0bbb3caa67a77fc1428e1",
    },
    "boltz2_aff.ckpt": {
        "bytes": 2062139170,
        "sha256": "dcc5cd3722b1c9eaa34267e4ae32f55cbbf1963f4c19319381ccfa30fdd2ca9e",
    },
    "mols.tar": {
        "bytes": 1855662080,
        "sha256": "39e076d96dbec6b4e86982bbda16f3a53a2a60c9bdc17828d88f6f9a0c7d1fd7",
    },
}
MAX_EXTRACTED_BYTES = 8 * 2**30
MAX_ARCHIVE_ENTRIES = 100000
CANONICAL_MOLECULES = {
    name + ".pkl"
    for name in [
        "ALA",
        "ARG",
        "ASN",
        "ASP",
        "CYS",
        "GLN",
        "GLU",
        "GLY",
        "HIS",
        "ILE",
        "LEU",
        "LYS",
        "MET",
        "PHE",
        "PRO",
        "SER",
        "THR",
        "TRP",
        "TYR",
        "VAL",
        "UNK",
    ]
}


def _no_symlink(path: Path) -> None:
    for parent in (path, *path.parents):
        try:
            info = parent.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError(f"Boltz cache path must not contain links or reparse points: {path}")


def _stream_hash(source: IO[bytes], destination: IO[bytes] | None = None) -> tuple[str, int]:
    digest, size = hashlib.sha256(), 0
    while block := source.read(1024 * 1024):
        digest.update(block)
        size += len(block)
        if destination is not None:
            destination.write(block)
    return digest.hexdigest(), size


def _member_path(member: tarfile.TarInfo) -> Path:
    name = member.name
    while name.startswith("./"):
        name = name[2:]
    if member.isdir():
        name = name.rstrip("/")
    parts = name.split("/")
    if (
        not parts
        or parts[0] != "mols"
        or any(part in {"", ".", ".."} for part in parts)
        or "\\" in name
        or ":" in name
        or "\x00" in name
        or not (member.isdir() or member.isfile())
        or member.sparse is not None
        or (len(parts) == 1 and not member.isdir())
    ):
        raise ValueError(f"Unsafe Boltz molecule archive member: {member.name}")
    return Path(*parts)


def _existing_tree(directory: Path) -> tuple[set[str], set[str]]:
    """Enumerate without following links, including empty/extra directories."""
    files, directories = set(), {"mols"}
    count = 0
    for root, dirs, names in os.walk(directory, followlinks=False):
        for name in dirs + names:
            path = Path(root) / name
            count += 1
            if count > MAX_ARCHIVE_ENTRIES:
                raise ValueError("Boltz extracted cache exceeds the entry limit")
            info = path.lstat()
            mode = info.st_mode
            relative = path.relative_to(directory.parent).as_posix()
            if getattr(info, "st_file_attributes", 0) & 0x400:
                raise ValueError(f"Unsafe reparse point in Boltz molecule cache: {path}")
            if stat.S_ISDIR(mode):
                directories.add(relative)
            elif stat.S_ISREG(mode):
                files.add(relative)
            else:
                raise ValueError(f"Unsafe entry in Boltz molecule cache: {path}")
    return files, directories


def _molecules(archive: Path, cache: Path) -> dict[str, Any]:
    mols = cache / "mols"
    _no_symlink(mols)
    existing = mols.exists()
    if existing and not mols.is_dir():
        raise ValueError("Boltz molecule cache must be a directory")
    actual_files, actual_dirs = _existing_tree(mols) if existing else (set(), set())
    inventory: dict[str, dict[str, Any]] = {}
    directories = {"mols"}
    members: set[str] = set()
    total = 0
    # All writes use a new, owned directory. No extraction API follows tar links.
    with tempfile.TemporaryDirectory(prefix=".boltz-mols-", dir=cache) as temporary:
        staging = Path(temporary)
        staging.resolve().relative_to(cache.resolve())
        (staging / "mols").mkdir()
        with tarfile.open(archive, mode="r:") as bundle:
            for member in bundle:
                relative = _member_path(member)
                key = relative.as_posix()
                if key in members:
                    raise ValueError(f"Duplicate Boltz molecule archive path: {key}")
                members.add(key)
                if len(members) > MAX_ARCHIVE_ENTRIES:
                    raise ValueError("Boltz molecule archive exceeds the entry limit")
                directories.update(
                    parent.as_posix() for parent in relative.parents if parent != Path(".")
                )
                if member.isdir():
                    directories.add(key)
                    if not existing:
                        (staging / relative).mkdir(parents=True, exist_ok=True)
                    continue
                if member.size < 0 or total + member.size > MAX_EXTRACTED_BYTES:
                    raise ValueError("Boltz molecule archive exceeds the extracted size limit")
                total += member.size
                source = bundle.extractfile(member)
                if source is None:
                    raise ValueError(f"Unreadable Boltz molecule archive member: {key}")
                with source:
                    if existing:
                        digest, size = _stream_hash(source)
                        target = cache / relative
                        if key not in actual_files or target.stat().st_size != member.size:
                            raise ValueError(
                                f"Boltz molecule cache differs from publisher archive: {key}"
                            )
                        with target.open("rb") as stored:
                            if _stream_hash(stored) != (digest, size):
                                raise ValueError(f"Boltz molecule cache SHA256 mismatch: {key}")
                    else:
                        target = staging / relative
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with target.open("xb") as destination:
                            digest, size = _stream_hash(source, destination)
                if size != member.size:
                    raise ValueError(f"Truncated Boltz molecule archive member: {key}")
                inventory[key] = {"sha256": digest, "bytes": size}
        if not inventory:
            raise ValueError("Boltz molecule archive has no regular files")
        if existing:
            if actual_files != set(inventory) or actual_dirs != directories:
                raise ValueError("Boltz molecule cache has missing or unexpected entries")
        else:
            (staging / "mols").rename(mols)
    manifest = json.dumps(inventory, sort_keys=True, separators=(",", ":")).encode()
    return {
        "files": len(inventory),
        "bytes": total,
        "inventory_sha256": hashlib.sha256(manifest).hexdigest(),
        "verified_against_authenticated_archive": True,
        "canonical_files": {
            Path(name).name: row
            for name, row in inventory.items()
            if Path(name).parent == Path("mols") and Path(name).name in CANONICAL_MOLECULES
        },
    }


def prepare_boltz_assets(cache: Path) -> dict[str, Any]:
    """Verify every cached asset and extracted byte against the pinned publisher."""
    # Runtime imports this module; delay this shared helper import to avoid a cycle.
    from bindsight.runners.gpu_runtime import download

    _no_symlink(cache)
    cache.mkdir(parents=True, exist_ok=True)
    assets = {}
    for name, pin in ASSETS.items():
        target = cache / name
        _no_symlink(target)
        if target.exists() and not target.is_file():
            raise ValueError(f"Boltz asset cache is not a regular file: {name}")
        size, expected = int(pin["bytes"]), str(pin["sha256"])
        url = f"https://huggingface.co/boltz-community/boltz-2/resolve/{PUBLISHER_REVISION}/{name}"
        if target.exists():
            digest = download(url, target, expected, minimum=size, maximum=size)
        else:
            # Isolate the download helper's .partial file from untrusted cache entries.
            with tempfile.TemporaryDirectory(prefix=".boltz-download-", dir=cache) as temporary:
                staging = Path(temporary)
                staging.resolve().relative_to(cache.resolve())
                partial_target = staging / name
                digest = download(url, partial_target, expected, minimum=size, maximum=size)
                partial_target.replace(target)
        assets[name] = {"url": url, "bytes": size, "sha256": digest, "pin_match": True}
    molecules = _molecules(cache / "mols.tar", cache)
    return {
        "schema": "bindsight-boltz-assets/1",
        "publisher_revision": PUBLISHER_REVISION,
        "assets": assets,
        "molecules": molecules,
    }

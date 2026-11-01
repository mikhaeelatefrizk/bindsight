"""Bounded, data-only extraction of one actual GPU result for independent inspection."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath, PureWindowsPath
import tarfile

from bindsight.archive_bounds import open_bounded_tar


def extract(archive: Path, destination: Path) -> dict:
    archive = archive.resolve(strict=True)
    destination = destination.resolve()
    if destination.exists():
        raise ValueError("A new extraction directory is required")
    allowed_roots = {"design", "validate", "evidence", "metrics.jsonl", "prescreen.txt"}
    seen = set()
    records = []
    total = 0
    with open_bounded_tar(archive, max_bytes=2 * 1024**3, max_members=100000) as bundle:
        members = bundle.getmembers()
        for member in members:
            path = PurePosixPath(member.name)
            if (
                not member.name
                or "\\" in member.name
                or ":" in member.name
                or path.is_absolute()
                or any(p in {"", ".", ".."} for p in member.name.split("/"))
                or path.parts[0] not in allowed_roots
                or any(PureWindowsPath(p).is_reserved() or p.endswith((".", " ")) for p in path.parts)
                or not (member.isfile() or member.isdir())
                or member.issparse()
                or member.size < 0
                or member.size > 256 * 1024**2
            ):
                raise ValueError(f"Unsupported member: {member.name!r}")
            key = member.name.casefold()
            if key in seen:
                raise ValueError(f"Duplicate path: {member.name!r}")
            seen.add(key)
            tarfile.data_filter(member, str(destination))
            total += member.size
            if total > 2 * 1024**3:
                raise ValueError("Result payload budget exceeded")
        # No writes occur before every header/path has been checked.
        destination.mkdir(parents=True, exist_ok=False)
        for member in members:
            target = destination.joinpath(*PurePosixPath(member.name).parts)
            if not target.resolve().is_relative_to(destination):
                raise ValueError("Destination escape")
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            stream = bundle.extractfile(member)
            if stream is None:
                raise ValueError("Missing regular-file stream")
            remaining = member.size
            digest = hashlib.sha256()
            with stream, target.open("xb") as out:
                while remaining:
                    chunk = stream.read(min(1024**2, remaining))
                    if not chunk:
                        raise ValueError("Truncated member")
                    out.write(chunk)
                    digest.update(chunk)
                    remaining -= len(chunk)
            records.append({"path": member.name, "bytes": member.size, "sha256": digest.hexdigest()})
    with archive.open("rb") as stream:
        archive_sha = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"archive_sha256": archive_sha, "archive_bytes": archive.stat().st_size,
            "payload_bytes": total, "files": records, "executed_archive_content": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    record = extract(args.archive, args.destination)
    args.receipt.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"files": len(record["files"]), "payload_bytes": record["payload_bytes"],
                      "archive_sha256": record["archive_sha256"]}))

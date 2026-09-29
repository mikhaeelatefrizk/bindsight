# SPDX-License-Identifier: AGPL-3.0-or-later
"""Bind platform installers to the exact tested source published by Pages."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any

PLATFORMS = {"windows-x64", "macos-arm64", "macos-x64", "linux-x64"}


def publish(artifacts: Path, workspace: Path) -> None:
    """Validate every input before copying any installer into the publication."""
    artifacts = artifacts.resolve()
    release = json.loads((workspace / "release.json").read_text(encoding="utf-8"))
    revision = release["revision"]
    if not re.fullmatch(r"[a-f0-9]{40}", revision):
        raise ValueError("The website has no verified source revision")
    manifest: dict[str, Any] = {"revision": revision, "platforms": {}}
    checked = []
    for platform in sorted(PLATFORMS):
        directory = artifacts / ("companion-" + platform)
        record_path = directory / "build.json"
        if record_path.is_symlink() or not record_path.resolve().is_relative_to(artifacts):
            raise ValueError("Companion build metadata must stay inside the downloaded artifacts")
        record = json.loads(record_path.read_text(encoding="utf-8"))
        if record.get("revision") != revision or record.get("platform") != platform:
            raise ValueError("A companion was built from a different source revision or platform")
        proof = record.get("self_test", {})
        if (
            record.get("development_dirty_build") is not False
            or proof.get("ok") is not True
            or proof.get("revision") != revision
            or proof.get("platform") != platform
        ):
            raise ValueError("A companion has no matching successful packaged self-test")
        filename = record.get("filename", "")
        expected_filename = (
            "Bindsight-Companion-" + platform + (".exe" if platform == "windows-x64" else ".zip")
        )
        if filename != expected_filename:
            raise ValueError("Unexpected companion filename")
        path = directory / filename
        if path.is_symlink() or not path.resolve().is_relative_to(directory.resolve()):
            raise ValueError("A companion download must be a contained regular file")
        if directory.is_symlink() or not directory.resolve().is_relative_to(artifacts):
            raise ValueError("The companion directory escaped the downloaded artifacts")
        size = path.stat().st_size
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if size <= 0 or size != record.get("size_bytes") or digest != record.get("sha256"):
            raise ValueError("Companion checksum or length differs from its build record")
        if (workspace / "downloads" / filename).exists():
            raise ValueError("Refusing to overwrite an existing companion publication")
        manifest["platforms"][platform] = {
            "filename": filename,
            "sha256": digest,
            "size_bytes": size,
        }
        checked.append((path, filename))
    for path, filename in checked:
        shutil.copyfile(path, workspace / "downloads" / filename)
    (workspace / "downloads/companion.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifacts", required=True, type=Path)
    parser.add_argument("--workspace", required=True, type=Path)
    args = parser.parse_args()
    publish(args.artifacts, args.workspace)

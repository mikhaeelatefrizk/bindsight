# SPDX-License-Identifier: AGPL-3.0-or-later
"""A download must correspond to the tested source, not another workflow run."""

import hashlib
import json
from pathlib import Path

import pytest

from scripts.publish_companions import PLATFORMS, publish


def fixtures(tmp_path: Path) -> tuple[Path, Path]:
    artifacts = tmp_path / "artifacts"
    workspace = tmp_path / "workspace"
    (workspace / "downloads").mkdir(parents=True)
    (workspace / "release.json").write_text(json.dumps({"revision": "a" * 40}))
    for platform in PLATFORMS:
        directory = artifacts / ("companion-" + platform)
        directory.mkdir(parents=True)
        filename = (
            "Bindsight-Companion-" + platform + (".exe" if platform == "windows-x64" else ".zip")
        )
        data = b"ARTIFICIAL PACKAGING TEST, NOT AN INSTALLER"
        (directory / filename).write_bytes(data)
        (directory / "build.json").write_text(
            json.dumps(
                {
                    "revision": "a" * 40,
                    "platform": platform,
                    "filename": filename,
                    "size_bytes": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "development_dirty_build": False,
                    "self_test": {"ok": True, "revision": "a" * 40, "platform": platform},
                }
            )
        )
    return artifacts, workspace


def test_exact_platform_builds_are_published_with_hashes(tmp_path: Path) -> None:
    artifacts, workspace = fixtures(tmp_path)
    publish(artifacts, workspace)
    manifest = json.loads((workspace / "downloads/companion.json").read_text())
    assert set(manifest["platforms"]) == PLATFORMS
    for record in manifest["platforms"].values():
        data = (workspace / "downloads" / record["filename"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == record["sha256"]


@pytest.mark.parametrize("problem", ["revision", "bytes", "path", "dirty", "self-test"])
def test_incomplete_or_mixed_builds_publish_nothing(tmp_path: Path, problem: str) -> None:
    artifacts, workspace = fixtures(tmp_path)
    directory = artifacts / "companion-windows-x64"
    record = json.loads((directory / "build.json").read_text())
    if problem == "revision":
        record["revision"] = "b" * 40
    elif problem == "path":
        record["filename"] = "../../private"
    elif problem == "dirty":
        record["development_dirty_build"] = True
    elif problem == "self-test":
        record["self_test"]["revision"] = "b" * 40
    else:
        (directory / record["filename"]).write_bytes(b"ALTERED TEST DATA")
    (directory / "build.json").write_text(json.dumps(record))
    with pytest.raises(ValueError, match=r"companion|Companion"):
        publish(artifacts, workspace)
    assert not list((workspace / "downloads").iterdir())

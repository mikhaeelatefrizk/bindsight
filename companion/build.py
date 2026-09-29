# SPDX-License-Identifier: AGPL-3.0-or-later
"""Build on each target OS; self-test before emitting a publishable artifact."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from importlib.metadata import version
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from companion.core import platform_key  # noqa: E402


def main() -> None:
    """Write only the distributable artifact and build.json to the output folder."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--revision", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="Development smoke only; never publish this artifact",
    )
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.revision):
        parser.error("--revision must be a full lowercase Git SHA")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    if args.revision != head:
        parser.error("The requested revision differs from the checked-out source")
    dirty = bool(
        subprocess.check_output(
            ["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT, text=True
        ).strip()
    )
    if dirty and not args.allow_dirty:
        parser.error("Commit reviewed source before building a release")
    if version("pyinstaller") != "6.16.0":
        parser.error("Build with the pinned PyInstaller 6.16.0")
    output = args.output.resolve()
    if output.exists() and any(output.iterdir()):
        parser.error("--output must be a new or empty directory")
    key = platform_key()
    scratch = ROOT / "companion/.build"
    scratch.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="package-", dir=scratch) as temporary:
        work = Path(temporary)
        info = work / "build-info.json"
        info.write_text(
            json.dumps(
                {"revision": args.revision, "platform": key, "development_dirty_build": dirty}
            )
            + "\n",
            encoding="utf-8",
        )
        env = dict(
            os.environ,
            BINDSIGHT_BUILD_INFO=str(info),
            PYINSTALLER_CONFIG_DIR=str(work / "pyinstaller-cache"),
        )
        subprocess.run(
            [
                sys.executable,
                "-m",
                "PyInstaller",
                "--noconfirm",
                "--clean",
                "--distpath",
                str(work / "dist"),
                "--workpath",
                str(work / "work"),
                str(ROOT / "companion/companion.spec"),
            ],
            cwd=ROOT,
            env=env,
            check=True,
        )
        if key.startswith("macos"):
            bundle = work / "dist/Bindsight Companion.app"
            executable = bundle / "Contents/MacOS/BindsightCompanion"
        else:
            executable = work / (
                "dist/BindsightCompanion.exe" if key == "windows-x64" else "dist/BindsightCompanion"
            )
        smoke = work / "self-test.json"
        subprocess.run(
            [str(executable), "--self-test", "--self-test-output", str(smoke)],
            check=True,
            timeout=60,
        )
        proof = json.loads(smoke.read_text(encoding="utf-8"))
        if not proof["ok"] or proof["revision"] != args.revision or proof["platform"] != key:
            raise RuntimeError("The packaged executable failed its revision/platform self-test")
        output.mkdir(parents=True, exist_ok=True)
        filename = f"Bindsight-Companion-{key}" + (".exe" if key == "windows-x64" else ".zip")
        target = output / filename
        if key == "windows-x64":
            shutil.copyfile(executable, target)
        elif key.startswith("macos"):
            # ditto preserves app-bundle metadata and executable permissions.
            subprocess.run(
                [
                    "/usr/bin/ditto",
                    "-c",
                    "-k",
                    "--sequesterRsrc",
                    "--keepParent",
                    str(bundle),
                    str(target),
                ],
                check=True,
            )
        else:
            with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
                entry = zipfile.ZipInfo("BindsightCompanion", date_time=(2026, 9, 29, 0, 0, 0))
                entry.external_attr = 0o100755 << 16
                entry.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(entry, executable.read_bytes())
                archive.writestr(
                    "README.txt",
                    "Extract this archive and open BindsightCompanion. Your desktop may ask you to approve opening a downloaded application. No system Python is needed. The first Setup button downloads CPU packages; GPU setup is separate.\n",
                )
        metadata = {
            "revision": args.revision,
            "platform": key,
            "filename": filename,
            "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            "size_bytes": target.stat().st_size,
            "development_dirty_build": dirty,
            "self_test": proof,
        }
        (output / "build.json").write_text(
            json.dumps(metadata, indent=2) + "\n", encoding="utf-8", newline="\n"
        )
        print(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    main()

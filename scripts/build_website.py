# SPDX-License-Identifier: AGPL-3.0-or-later
"""Build the hosted evidence workspace from original, committed artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from jinja2 import Environment, FileSystemLoader  # noqa: E402

from bindsight.report.web.evidence import evidence_bundle  # noqa: E402


def build(destination: Path) -> None:
    """Copy scientific assets byte-for-byte and render the shared interface."""
    web = ROOT / "bindsight/report/web"
    destination.mkdir(parents=True, exist_ok=True)
    env = Environment(loader=FileSystemLoader(str(web / "templates")), autoescape=True)
    html = env.get_template("workbench.html.j2").render(assets="assets/", local=False)
    (destination / "index.html").write_text(html, encoding="utf-8", newline="\n")
    bundle = evidence_bundle(public=True)
    if len(bundle["binders"]) != 20 or bundle["study"] is None:
        raise RuntimeError(
            "Committed evidence is missing; refusing to publish an incomplete showcase"
        )
    (destination / "evidence.json").write_text(
        json.dumps(bundle, ensure_ascii=False, allow_nan=False), encoding="utf-8", newline="\n"
    )
    static = destination / "assets"
    static.mkdir(exist_ok=True)
    for name in ("workbench.css", "workbench.js", "workbench-pages.js"):
        shutil.copyfile(web / "static" / name, static / name)
    shutil.copytree(web / "static/vendor", static / "vendor", dirs_exist_ok=True)
    shutil.copytree(web / "static/fonts", static / "fonts", dirs_exist_ok=True)
    for subdir, suffix in (("structures", "_complex.cif"), ("sequences", ".fasta")):
        (destination / subdir).mkdir(exist_ok=True)
        for binder in bundle["binders"]:
            name = binder["id"] + suffix
            shutil.copyfile(
                ROOT / "benchmarks/designer_benchmark/binders" / name, destination / subdir / name
            )
    downloads = destination / "downloads"
    downloads.mkdir(exist_ok=True)
    archive = downloads / "bindsight-local.zip"
    # Git's allowlist includes authored source and excludes local analyses, caches,
    # environments and credentials. The website never packages arbitrary folders.
    listed = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=ROOT
    )
    paths = sorted(set(listed.decode("utf-8").split("\0")) - {""})
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as bundle_zip:
        for name in paths:
            path = ROOT / name
            if not path.is_file() or name.startswith(("website/", ".github/")):
                continue
            info = zipfile.ZipInfo("bindsight/" + name, date_time=(2026, 9, 29, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o755 if name.endswith(".command") else 0o644) << 16
            bundle_zip.writestr(info, path.read_bytes())
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (downloads / "SHA256SUMS").write_text(
        f"{digest}  bindsight-local.zip\n", encoding="ascii", newline="\n"
    )
    if archive.stat().st_size > 24 * 1024 * 1024:
        raise RuntimeError("The local download exceeds the hosting asset limit")
    print(f"Built real evidence workspace: {destination}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=ROOT / "website/dist")
    build(parser.parse_args().out.resolve())

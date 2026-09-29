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

from jinja2 import DictLoader, Environment  # noqa: E402

from bindsight.report.web.evidence import evidence_bundle  # noqa: E402


def archive_sources(root: Path) -> list[tuple[str, Path]]:
    """Allow only tracked regular files; local untracked data is never a release input."""
    root = root.resolve()
    listed = subprocess.check_output(["git", "ls-files", "--cached", "-z"], cwd=root)
    paths = sorted(set(listed.decode("utf-8").split("\0")) - {""})
    sources = []
    for name in paths:
        path = root / name
        if name.startswith(("website/", ".github/")):
            continue
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError(
                f"A release source must be a regular file inside the repository: {name}"
            )
        if path.is_file():
            sources.append((name, path))
    return sources


def build(destination: Path) -> None:
    """Copy scientific assets byte-for-byte and render the shared interface."""
    if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
        raise ValueError("The public build destination must be new or empty")
    if subprocess.run(["git", "diff", "--quiet", "HEAD"], cwd=ROOT, check=False).returncode:
        raise RuntimeError("Commit the reviewed source before building a public release")
    sources = dict(archive_sources(ROOT))
    template_prefix = "bindsight/report/web/templates/"
    templates = {
        name.removeprefix(template_prefix): path.read_text(encoding="utf-8")
        for name, path in sources.items()
        if name.startswith(template_prefix)
    }
    env = Environment(loader=DictLoader(templates), autoescape=True)
    html = env.get_template("workbench.html.j2").render(assets="assets/", local=False)
    bundle = evidence_bundle(public=True)
    if len(bundle["binders"]) != 20 or bundle["study"] is None:
        raise RuntimeError(
            "Committed evidence is missing; refusing to publish an incomplete showcase"
        )
    if not bundle["revision"]:
        raise RuntimeError(
            "Commit the reviewed evidence before publishing; its source revision is unverified"
        )
    public_sources: dict[str, Path] = {}
    static_prefix = "bindsight/report/web/static/"
    for name, path in sources.items():
        if name.startswith((static_prefix + "vendor/", static_prefix + "fonts/")):
            public_sources["assets/" + name.removeprefix(static_prefix)] = path
    required = {
        "assets/" + name: static_prefix + name
        for name in ("workbench.css", "workbench.js", "workbench-pages.js")
    }
    for subdir, suffix in (("structures", "_complex.cif"), ("sequences", ".fasta")):
        for binder in bundle["binders"]:
            name = binder["id"] + suffix
            required[subdir + "/" + name] = "benchmarks/designer_benchmark/binders/" + name
    for public_name, source_name in required.items():
        if source_name not in sources:
            raise ValueError(
                f"A required public asset is not a tracked regular file: {source_name}"
            )
        public_sources[public_name] = sources[source_name]

    # Resolve every input before creating output. Directory walks and copytree
    # would expose untracked files (or follow an untracked directory link).
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "index.html").write_text(html, encoding="utf-8", newline="\n")
    release = {"revision": bundle["revision"], "repository": bundle["repository"]}
    (destination / "release.json").write_text(
        json.dumps(release, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    (destination / "evidence.json").write_text(
        json.dumps(bundle, ensure_ascii=False, allow_nan=False), encoding="utf-8", newline="\n"
    )
    for public_name, path in public_sources.items():
        target = destination / public_name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    downloads = destination / "downloads"
    downloads.mkdir(exist_ok=True)
    archive = downloads / "bindsight-local.zip"
    # Untracked files can contain patient data or notes even when .gitignore does
    # not name them. Only explicitly tracked regular source files enter a release.
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as bundle_zip:
        for name, path in sources.items():
            info = zipfile.ZipInfo("bindsight/" + name, date_time=(2026, 9, 29, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o755 if name.endswith(".command") else 0o644) << 16
            bundle_zip.writestr(info, path.read_bytes())
        revision_info = zipfile.ZipInfo(
            "bindsight/SOURCE_REVISION.json", date_time=(2026, 9, 29, 0, 0, 0)
        )
        revision_info.compress_type = zipfile.ZIP_DEFLATED
        revision_info.external_attr = 0o644 << 16
        bundle_zip.writestr(revision_info, json.dumps(release, indent=2) + "\n")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (downloads / "SHA256SUMS").write_text(
        f"{digest}  bindsight-local.zip\n", encoding="ascii", newline="\n"
    )
    # GitHub Pages now serves the download through a streaming relay; it is not
    # bundled as a Sites static asset. Keep a project size budget for portability.
    if archive.stat().st_size > 64 * 1024 * 1024:
        raise RuntimeError("The local download exceeds the project's 64 MiB size budget")
    print(f"Built real evidence workspace: {destination}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=ROOT / "website/dist")
    build(parser.parse_args().out.resolve())

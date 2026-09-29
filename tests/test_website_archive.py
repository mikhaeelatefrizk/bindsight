# SPDX-License-Identifier: AGPL-3.0-or-later
"""Local private files must never become inputs to the public download."""

import subprocess
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from launch import launcher_lock
from scripts import build_docs_results, build_website
from scripts.build_website import archive_sources


@pytest.fixture
def public_sources(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A tiny, explicitly artificial release; no biological claims are tested here."""
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    files = {
        "bindsight/report/web/templates/workbench.html.j2": "<html>artificial test</html>",
        "bindsight/report/web/static/workbench.css": "/* artificial test */",
        "bindsight/report/web/static/workbench.js": "// artificial test",
        "bindsight/report/web/static/workbench-pages.js": "// artificial test",
        "bindsight/report/web/static/vendor/reviewed.js": "// reviewed test asset",
        "bindsight/report/web/static/fonts/reviewed.woff2": "artificial font bytes",
    }
    binders = [{"id": f"artificial_{number}"} for number in range(20)]
    for binder in binders:
        for suffix in ("_complex.cif", ".fasta"):
            files["benchmarks/designer_benchmark/binders/" + binder["id"] + suffix] = (
                "ARTIFICIAL UNIT TEST DATA, NOT SCIENTIFIC EVIDENCE"
            )
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "artificial release fixture",
        ],
        cwd=root,
        check=True,
    )
    monkeypatch.setattr(build_website, "ROOT", root)
    monkeypatch.setattr(
        build_website,
        "evidence_bundle",
        lambda **_: {
            "binders": binders,
            "study": {"artificial": True},
            "revision": "a" * 40,
            "repository": "https://example.invalid/artificial",
        },
    )
    return root


def _directory_link(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target, target_is_directory=True)
        return
    except OSError:
        if sys.platform == "win32":
            # Junctions exercise the same escaping-directory case without
            # requiring Windows' administrator-only symbolic-link privilege.
            result = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(link), str(target)],
                capture_output=True,
                check=False,
            )
            if result.returncode == 0:
                return
    pytest.skip("This platform does not permit creating a directory link")


def test_public_assets_and_archive_exclude_untracked_canaries(
    public_sources: Path,
    tmp_path: Path,
) -> None:
    canary = b"ARTIFICIAL PRIVACY CANARY MUST NEVER BE PUBLISHED"
    static = public_sources / "bindsight/report/web/static"
    for folder in ("fonts", "vendor"):
        (static / folder / "private-note.txt").write_bytes(canary)
    (public_sources / "benchmarks/designer_benchmark/binders/private.cif").write_bytes(canary)
    destination = tmp_path / "site"
    build_website.build(destination)
    assert (destination / "assets/fonts/reviewed.woff2").is_file()
    assert (destination / "assets/vendor/reviewed.js").is_file()
    assert len(list((destination / "structures").iterdir())) == 20
    assert len(list((destination / "sequences").iterdir())) == 20
    for path in destination.rglob("*"):
        if path.is_file() and path.suffix != ".zip":
            assert canary not in path.read_bytes()
    with zipfile.ZipFile(destination / "downloads/bindsight-local.zip") as archive:
        assert not any("private" in name for name in archive.namelist())
        assert all(canary not in archive.read(name) for name in archive.namelist())


def test_public_assets_do_not_follow_untracked_escaping_directory(
    public_sources: Path,
    tmp_path: Path,
) -> None:
    external = tmp_path / "external"
    external.mkdir()
    (external / "private-note.txt").write_text("ARTIFICIAL PRIVACY CANARY", encoding="utf-8")
    link = public_sources / "bindsight/report/web/static/fonts/private-folder"
    _directory_link(link, external)
    destination = tmp_path / "site"
    build_website.build(destination)
    assert not (destination / "assets/fonts/private-folder").exists()
    with zipfile.ZipFile(destination / "downloads/bindsight-local.zip") as archive:
        assert not any("private-folder" in name for name in archive.namelist())


def test_release_rejects_tracked_file_through_escaping_directory(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    folder = root / "assets"
    folder.mkdir()
    (folder / "reviewed.txt").write_text("artificial reviewed file", encoding="utf-8")
    subprocess.run(["git", "add", "assets/reviewed.txt"], cwd=root, check=True)
    (folder / "reviewed.txt").unlink()
    folder.rmdir()
    external = tmp_path / "external"
    external.mkdir()
    (external / "reviewed.txt").write_text("ARTIFICIAL PRIVACY CANARY", encoding="utf-8")
    _directory_link(folder, external)
    with pytest.raises(ValueError, match="regular file inside"):
        archive_sources(root)


def test_docs_vendor_copy_excludes_untracked_canary_and_escaping_directory(
    public_sources: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    static = public_sources / "bindsight/report/web/static"
    canary = b"ARTIFICIAL PRIVACY CANARY MUST NEVER BE PUBLISHED"
    (static / "vendor/private-note.txt").write_bytes(canary)
    external = tmp_path / "external-docs"
    external.mkdir()
    (external / "private-note.txt").write_bytes(canary)
    _directory_link(static / "vendor/private-folder", external)
    for name in ("binder_viewer.js", "your_data_check.js"):
        (static / name).write_text("// artificial script", encoding="utf-8")
    destination = tmp_path / "docs"
    monkeypatch.setattr(build_docs_results, "ROOT", public_sources)
    monkeypatch.setattr(build_docs_results, "WEB_STATIC", static)
    monkeypatch.setattr(build_docs_results, "VENDOR_DIR", destination / "vendor")
    monkeypatch.setattr(build_docs_results, "STRUCT_DIR", destination / "structures")
    monkeypatch.setattr(build_docs_results, "JS_DIR", destination / "js")
    designer = SimpleNamespace(
        with_structures=lambda: [
            SimpleNamespace(
                complex_cif=public_sources
                / "benchmarks/designer_benchmark/binders/artificial_0_complex.cif"
            )
        ]
    )
    counts = build_docs_results._copy_assets(None, designer)
    assert counts["vendor"] == 1
    assert list((destination / "vendor").iterdir()) == [destination / "vendor/reviewed.js"]
    assert all(canary not in path.read_bytes() for path in destination.rglob("*") if path.is_file())


def test_docs_vendor_copy_rejects_tracked_file_through_escaping_directory(
    public_sources: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    static = public_sources / "bindsight/report/web/static"
    vendor = static / "vendor"
    (vendor / "reviewed.js").unlink()
    vendor.rmdir()
    external = tmp_path / "external-docs"
    external.mkdir()
    (external / "reviewed.js").write_text("ARTIFICIAL PRIVACY CANARY", encoding="utf-8")
    _directory_link(vendor, external)
    monkeypatch.setattr(build_docs_results, "ROOT", public_sources)
    monkeypatch.setattr(build_docs_results, "WEB_STATIC", static)
    with pytest.raises(ValueError, match="regular file inside the repository"):
        build_docs_results._tracked_vendor_sources()


@pytest.mark.parametrize("suffix", ["_complex.cif", ".fasta"])
def test_required_scientific_assets_must_be_tracked(
    public_sources: Path,
    tmp_path: Path,
    suffix: str,
) -> None:
    name = "benchmarks/designer_benchmark/binders/artificial_0" + suffix
    subprocess.run(["git", "rm", "--cached", name], cwd=public_sources, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "exclude required test artifact",
        ],
        cwd=public_sources,
        check=True,
    )
    destination = tmp_path / "site"
    with pytest.raises(ValueError, match="required public asset is not a tracked regular file"):
        build_website.build(destination)
    assert not destination.exists()


def test_nonempty_public_destination_is_rejected_before_writing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "site"
    destination.mkdir()
    canary = destination / "stale-private-file.txt"
    canary.write_bytes(b"ARTIFICIAL PRIVACY CANARY")
    # An invalid source root proves the destination guard runs before Git or writes.
    monkeypatch.setattr(build_website, "ROOT", tmp_path / "missing-repository")
    with pytest.raises(ValueError, match="destination must be new or empty"):
        build_website.build(destination)
    assert list(destination.iterdir()) == [canary]
    assert canary.read_bytes() == b"ARTIFICIAL PRIVACY CANARY"


def test_launcher_serializes_setup_and_releases_ownership(tmp_path: Path) -> None:
    environment = tmp_path / "environment"
    with (
        launcher_lock(environment),
        pytest.raises(OSError, match="already starting or running"),
        launcher_lock(environment),
    ):
        pytest.fail("Two launchers acquired the same installation directory")
    with launcher_lock(environment):
        assert environment.is_dir()


def test_release_archive_excludes_untracked_files_even_when_not_ignored(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "launch.py").write_text("# tracked release source\n")
    subprocess.run(["git", "add", "launch.py"], cwd=tmp_path, check=True)
    (tmp_path / "patient-counts.tsv").write_text("artificial privacy-test canary\n")
    (tmp_path / "private-notes.txt").write_text("artificial privacy-test canary\n")
    assert [name for name, _ in archive_sources(tmp_path)] == ["launch.py"]


def test_release_archive_rejects_tracked_links_to_external_files(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    external = tmp_path / "external.txt"
    external.write_text("artificial privacy-test canary\n")
    link = root / "external.txt"
    try:
        link.symlink_to(external)
    except OSError:
        pytest.skip("This platform does not permit creating an unprivileged symlink")
    subprocess.run(["git", "add", "external.txt"], cwd=root, check=True)
    with pytest.raises(ValueError, match="regular file inside"):
        archive_sources(root)


def test_dirty_tracked_code_cannot_be_labelled_with_a_clean_commit(
    tmp_path: Path, monkeypatch
) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "launch.py").write_text("# reviewed source\n")
    subprocess.run(["git", "add", "launch.py"], cwd=tmp_path, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "reviewed",
        ],
        cwd=tmp_path,
        check=True,
    )
    (tmp_path / "launch.py").write_text("# unreviewed modification\n")
    monkeypatch.setattr(build_website, "ROOT", tmp_path)
    with pytest.raises(RuntimeError, match="Commit the reviewed source"):
        build_website.build(tmp_path / "site")

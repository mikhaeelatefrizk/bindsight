"""Bootstrap security boundaries and failure activation, without network downloads."""

from __future__ import annotations

import hashlib
import io
import json
import stat
import sys
import threading
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from companion import core

REVISION = "a" * 40


def source_zip(tmp_path, additions=(), *, revision=REVISION):
    archive = tmp_path / "source.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("bindsight/pyproject.toml", "[project]\nname='bindsight'\n")
        bundle.writestr("bindsight/envs/constraints.txt", "numpy==2.2.6\n")
        bundle.writestr(
            "bindsight/SOURCE_REVISION.json",
            json.dumps({"repository": core.PINS["repository"], "revision": revision}),
        )
        for name, value in additions:
            if isinstance(name, str):
                entry = zipfile.ZipInfo()
                # Preserve malicious raw spelling rather than ZipInfo's host
                # separator normalization while constructing the test archive.
                entry.filename = name
                bundle.writestr(entry, value)
            else:
                bundle.writestr(name, value)
    return archive, hashlib.sha256(archive.read_bytes()).hexdigest()


@pytest.mark.parametrize(
    ("system", "machine", "expected"),
    [
        ("Windows", "AMD64", "windows-x64"),
        ("Darwin", "aarch64", "macos-arm64"),
        ("Darwin", "x86_64", "macos-x64"),
        ("Linux", "x86_64", "linux-x64"),
    ],
)
def test_platform_has_verified_pin(system, machine, expected):
    assert core.platform_key(system, machine) == expected
    pin = core.PINS["artifacts"][expected]
    assert len(pin["sha256"]) == 64
    assert pin["bytes"] > 0


def test_unreviewed_platform_is_rejected():
    with pytest.raises(core.SetupError, match="does not support"):
        core.platform_key("Windows", "ARM64")


def test_install_requires_explicit_approval_before_any_effect(tmp_path, monkeypatch):
    network = Mock(side_effect=AssertionError("No network before consent"))
    monkeypatch.setattr(core, "download", network)
    root = tmp_path / "not-created"
    installer = core.Installer(root, REVISION, lambda _: None, threading.Event())
    with pytest.raises(core.SetupError, match="approve"):
        installer.install()
    network.assert_not_called()
    assert not root.exists()


def test_valid_source_exact_manifest_case_and_extraction(tmp_path):
    archive, sha = source_zip(tmp_path, [("bindsight/data/input.tsv", "gene\tsample\ng1\t20\n")])
    destination = tmp_path / "extracted"
    source = core.extract_source(archive, destination, sha, REVISION, threading.Event())
    assert (source / "SOURCE_REVISION.json").is_file()
    assert (source / "data/input.tsv").read_text() == "gene\tsample\ng1\t20\n"


@pytest.mark.parametrize(
    "path",
    [
        "../outside",
        "/bindsight/file",
        "bindsight/../outside",
        "bindsight/./file",
        "bindsight//file",
        "bindsight\\file",
        "bindsight/NUL.txt",
        "bindsight/x:stream",
        "bindsight/trailing.",
        "bindsight/trailing ",
    ],
)
def test_unsafe_member_rejected_before_extraction(tmp_path, path):
    archive, sha = source_zip(tmp_path, [(path, "bad")])
    destination = tmp_path / "extracted"
    with pytest.raises(core.SetupError):
        core.extract_source(archive, destination, sha, REVISION, threading.Event())
    assert not destination.exists()


def test_duplicate_case_path_is_rejected(tmp_path):
    archive, sha = source_zip(tmp_path, [("bindsight/PYPROJECT.toml", "aliased")])
    with pytest.raises(core.SetupError, match="duplicate"):
        core.verify_source(archive, sha, REVISION)


def test_source_links_are_rejected(tmp_path):
    entry = zipfile.ZipInfo("bindsight/link")
    entry.external_attr = (stat.S_IFLNK | 0o777) << 16
    archive, sha = source_zip(tmp_path, [(entry, "../../outside")])
    with pytest.raises(core.SetupError, match="links"):
        core.verify_source(archive, sha, REVISION)


def test_source_revision_and_checksum_independently_required(tmp_path):
    archive, sha = source_zip(tmp_path)
    with pytest.raises(core.SetupError, match="checksum"):
        core.verify_source(archive, "0" * 64, REVISION)
    with pytest.raises(core.SetupError, match="different release"):
        core.verify_source(archive, sha, "b" * 40)


def test_expansion_bound_checked_before_writing(tmp_path, monkeypatch):
    archive, sha = source_zip(tmp_path)
    monkeypatch.setattr(core, "MAX_EXPANDED_BYTES", 5)
    with pytest.raises(core.SetupError, match="expanded"):
        core.extract_source(archive, tmp_path / "out", sha, REVISION, threading.Event())
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize(
    "url",
    [
        "http://mikhaeelatefrizk.github.io/bindsight/workspace/release.json",
        "https://evil.example/release.json",
        "https://mikhaeelatefrizk.github.io.evil.example/bindsight/workspace/release.json",
        "https://user@mikhaeelatefrizk.github.io/bindsight/workspace/release.json",
        "https://mikhaeelatefrizk.github.io/other/release.json",
    ],
)
def test_external_or_insecure_release_urls_rejected(url):
    assert not core.approved_url(url)
    with pytest.raises(core.SetupError, match="redirected"):
        core.CheckedRedirect().redirect_request(None, None, 302, "Found", {}, url)


@pytest.mark.parametrize(
    "bad", ["", "a" * 64 + "  other.zip", ("a" * 64 + "  bindsight-local.zip\n") * 2]
)
def test_source_checksum_requires_exactly_one_entry(bad):
    with pytest.raises(core.SetupError, match="exactly one"):
        core.source_checksum(bad)


@pytest.mark.parametrize(
    ("limit", "sha", "cancelled"), [(3, None, False), (100, "0" * 64, False), (100, None, True)]
)
def test_failed_download_never_replaces_existing_file(tmp_path, monkeypatch, limit, sha, cancelled):
    class Response(io.BytesIO):
        @property
        def headers(self):
            return {}

    opener = SimpleNamespace(open=lambda *args, **kwargs: Response(b"downloaded-content"))
    monkeypatch.setattr(core.urllib.request, "build_opener", lambda *args: opener)
    target = tmp_path / "download.zip"
    target.write_bytes(b"old-content")
    cancel = threading.Event()
    if cancelled:
        cancel.set()
    with pytest.raises(core.SetupError):
        core.download(
            core.PINS["release_base"] + "downloads/bindsight-local.zip",
            target,
            limit,
            cancel,
            lambda _: None,
            expected_sha=sha,
        )
    assert target.read_bytes() == b"old-content"
    assert not target.with_suffix(".zip.partial").exists()


def test_private_environment_removes_inherited_configuration(tmp_path, monkeypatch):
    monkeypatch.setenv("PIP_INDEX_URL", "https://untrusted.example")
    monkeypatch.setenv("UV_INDEX_URL", "https://untrusted.example")
    monkeypatch.setenv("PYTHONPATH", "untrusted")
    monkeypatch.setenv("VIRTUAL_ENV", "untrusted")
    env = core.private_environment(tmp_path)
    assert "PIP_INDEX_URL" not in env
    assert "UV_INDEX_URL" not in env
    assert "PYTHONPATH" not in env
    assert "VIRTUAL_ENV" not in env
    for key in ["UV_CACHE_DIR", "UV_PYTHON_INSTALL_DIR", "TEMP", "MPLCONFIGDIR"]:
        assert Path(env[key]).is_relative_to(tmp_path)


@pytest.mark.parametrize("original", [None, "/original/lib"])
def test_frozen_external_linux_library_paths_restored(tmp_path, monkeypatch, original):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setenv("LD_LIBRARY_PATH", str(tmp_path))
    if original:
        monkeypatch.setenv("LD_LIBRARY_PATH_ORIG", original)
    else:
        monkeypatch.delenv("LD_LIBRARY_PATH_ORIG", raising=False)
    result = core.external_environment()
    assert result.get("LD_LIBRARY_PATH") == original
    assert core.os.environ["LD_LIBRARY_PATH"] == str(tmp_path)


def test_nested_application_lock_rejected_and_then_released(tmp_path):
    with core.application_lock(tmp_path), pytest.raises(core.SetupError, match="already"):  # noqa: SIM117
        with core.application_lock(tmp_path):
            pytest.fail("second owner admitted")
    with core.application_lock(tmp_path):
        pass


def test_malformed_current_record_can_be_repaired(tmp_path):
    (tmp_path / "current.json").write_text("broken-json")
    installer = core.Installer(tmp_path, REVISION, lambda _: None, threading.Event())
    assert installer.current() is None


def test_current_record_cannot_escape_application_directory(tmp_path):
    (tmp_path / "current.json").write_text(
        json.dumps({"revision": REVISION, "source": "../outside", "python": "python"})
    )
    installer = core.Installer(tmp_path, REVISION, lambda _: None, threading.Event())
    with pytest.raises(core.SetupError, match="escapes"):
        installer.current()


def test_quiet_owned_subprocess_is_cancelled(tmp_path):
    cancel = threading.Event()
    installer = core.Installer(tmp_path, REVISION, lambda _: None, cancel)
    timer = threading.Timer(0.5, cancel.set)
    timer.start()
    try:
        with pytest.raises(core.Cancelled):
            installer.command([sys.executable, "-c", "import time; time.sleep(30)"], tmp_path)
        assert installer.process is None
    finally:
        timer.cancel()


def test_frozen_windows_library_search_is_restored_after_failure(monkeypatch):
    calls = []

    def get_directory(length, buffer):
        buffer.value = "C:\\bundled"
        return len(buffer.value)

    kernel = SimpleNamespace(
        GetDllDirectoryW=get_directory, SetDllDirectoryW=lambda path: calls.append(path) or 1
    )
    monkeypatch.setattr(core.ctypes, "windll", SimpleNamespace(kernel32=kernel), raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "platform", "win32")

    def failing_child():
        with core.external_libraries():
            assert calls == [None]
            raise RuntimeError("child failed")

    with pytest.raises(RuntimeError, match="child failed"):
        failing_child()
    assert calls == [None, "C:\\bundled"]


@pytest.mark.parametrize("failing", [True, False])
def test_install_record_only_activated_after_dependency_and_import_checks(
    tmp_path, monkeypatch, failing
):
    archive, sha = source_zip(tmp_path)
    root = tmp_path / "app"
    events = []

    def fake_download(url, target, *args, **kwargs):
        if target.name == "release.json":
            target.write_text(
                json.dumps({"revision": REVISION, "repository": core.PINS["repository"]})
            )
        elif target.name == "SHA256SUMS":
            target.write_text(sha + "  bindsight-local.zip\n")
        elif target.suffix == ".zip" and target.name.startswith("source-"):
            target.write_bytes(archive.read_bytes())
        else:
            target.write_bytes(b"test-bootstrap")

    monkeypatch.setattr(core, "download", fake_download)
    monkeypatch.setattr(core, "extract_uv", lambda *args: tmp_path / "uv")
    monkeypatch.setattr(core.shutil, "disk_usage", lambda _: SimpleNamespace(free=10 * 1024**3))
    installer = core.Installer(root, REVISION, lambda _: None, threading.Event())

    def command(args, cwd, **kwargs):
        assert not (root / "current.json").exists()
        events.append(args)
        if len(events) == 4 and failing:
            raise core.SetupError("import verification failed")

    monkeypatch.setattr(installer, "command", command)
    if failing:
        with pytest.raises(core.SetupError, match="import verification"):
            installer.install(approved=True)
        assert not (root / "current.json").exists()
    else:
        record = installer.install(approved=True)
        assert json.loads((root / "current.json").read_text()) == record
    assert len(events) == 4
    assert "create_app" in events[-1][-1]

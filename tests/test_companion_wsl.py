# SPDX-License-Identifier: AGPL-3.0-or-later
"""Offline orchestration tests; artificial binaries never run or become evidence."""

from __future__ import annotations

import hashlib
import io
import json
import stat
import threading
import zipfile
from pathlib import Path
from typing import Any

import pytest

from companion import wsl
from companion.core import Cancelled, SetupError


def _ready_commands(
    monkeypatch: pytest.MonkeyPatch, *, memory: int = 24_576, uid: str = "1000", version: int = 2
) -> list[list[str]]:
    calls = []
    monkeypatch.setattr(wsl, "_wsl_executable", lambda: Path("C:/Windows/System32/wsl.exe"))

    def run(args: list[str], **kwargs: Any) -> str:
        calls.append(args)
        if args == ["--list", "--verbose"]:
            return f"  NAME STATE VERSION\n* Ubuntu-24.04 Stopped {version}\n"
        if args[-1] == "/etc/os-release":
            return 'ID=ubuntu\nVERSION_ID="24.04"\n'
        if args[-1] == "-u":
            return uid + "\n"
        if args[-1] == "-m":
            return "x86_64\n"
        if "nvidia-smi" in args[-3]:
            return f"Test GPU, {memory}, 570.00\n"
        pytest.fail(f"Unexpected command {args}")

    monkeypatch.setattr(wsl, "_run", run)
    return calls


def _archive(tmp_path: Path, *, unsafe: str | None = None) -> tuple[Path, str, int]:
    path = tmp_path / "test.zip"
    with zipfile.ZipFile(path, "w") as archive:
        item = zipfile.ZipInfo(unsafe or "BindsightCompanion")
        item.external_attr = (stat.S_IFREG | 0o755) << 16
        archive.writestr(item, b"ARTIFICIAL UNIT TEST EXECUTABLE - NEVER RUN")
        archive.writestr("README.txt", b"ARTIFICIAL TEST FIXTURE")
    data = path.read_bytes()
    return path, hashlib.sha256(data).hexdigest(), len(data)


def test_readiness_probes_real_requirements_without_installing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _ready_commands(monkeypatch)
    result = wsl.readiness()
    assert result["ready"] is True
    assert result["distro"] == "Ubuntu-24.04"
    assert result["gpus"][0]["memory_total_mib"] == 24576
    assert not result["blockers"]
    assert all("--install" not in call and "--set-default" not in call for call in calls)


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [({"memory": 2048}, "15,360"), ({"uid": "0"}, "non-root"), ({"version": 1}, "WSL2")],
)
def test_readiness_refuses_insufficient_or_uninitialized_environment(
    monkeypatch: pytest.MonkeyPatch, kwargs: dict[str, Any], reason: str
) -> None:
    _ready_commands(monkeypatch, **kwargs)
    result = wsl.readiness()
    assert result["ready"] is False
    assert reason in " ".join(result["blockers"])


def test_wsl_utf16_and_localized_state_names() -> None:
    text = "  NAME STATE VERSION\r\n* Ubuntu-24.04 Arrêté 2\r\n Ubuntu-22.04 Stopped 1\r\nEvilUbuntu Stopped 2\r\n"
    assert wsl._decode(text.encode("utf-16")) == text
    assert wsl._distributions(text) == {"Ubuntu-24.04": 2, "Ubuntu-22.04": 1}


def test_os_install_requires_distinct_approval(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wsl, "_wsl_executable", lambda: pytest.fail("No OS access before approval"))
    with pytest.raises(SetupError, match="separate"):
        wsl.install_prerequisites()


def test_fixed_os_install_launch_never_reports_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    executable = Path("C:/Windows/System32/wsl.exe")
    monkeypatch.setattr(wsl, "_wsl_executable", lambda: executable)
    monkeypatch.setattr(wsl, "_run", lambda *a, **k: "")
    calls = []
    monkeypatch.setattr(wsl, "_elevated_install", lambda path: calls.append(path) or 42)
    result = wsl.install_prerequisites(approved=True)
    assert calls == [executable]
    assert result["started"] is True
    assert result["ready"] is False
    assert "Restart Windows if it asks" in result["message"]
    assert wsl.INSTALL_ARGUMENTS == "--install --distribution Ubuntu-24.04 --no-launch"


def test_os_install_preserves_existing_distribution(monkeypatch: pytest.MonkeyPatch) -> None:
    _ready_commands(monkeypatch)
    monkeypatch.setattr(wsl, "_elevated_install", lambda *a: pytest.fail("Must not reinstall"))
    assert wsl.install_prerequisites(approved=True)["started"] is False


def test_os_admin_denial_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wsl, "_wsl_executable", lambda: Path("wsl.exe"))
    monkeypatch.setattr(wsl, "_run", lambda *a, **k: "")
    monkeypatch.setattr(wsl, "_elevated_install", lambda path: 5)
    with pytest.raises(SetupError, match="cancelled or blocked"):
        wsl.install_prerequisites(approved=True)


@pytest.mark.parametrize("change", ["revision", "filename", "sha256", "size_bytes"])
def test_manifest_refuses_mixed_revision_paths_and_unbounded_files(change: str) -> None:
    manifest = {
        "revision": "a" * 40,
        "platforms": {
            "linux-x64": {
                "filename": "Bindsight-Companion-linux-x64.zip",
                "sha256": "b" * 64,
                "size_bytes": 30,
            }
        },
    }
    if change == "revision":
        manifest["revision"] = "c" * 40
    else:
        manifest["platforms"]["linux-x64"][change] = {
            "filename": "../other.zip",
            "sha256": "bad",
            "size_bytes": wsl.MAX_ARCHIVE_BYTES + 1,
        }[change]
    with pytest.raises(SetupError):
        wsl._artifact(manifest, "a" * 40)


def test_verified_archive_extracts_only_executable_and_replaces_tampered_cache(
    tmp_path: Path,
) -> None:
    archive, sha, size = _archive(tmp_path)
    folder = tmp_path / "app"
    target = wsl._extract(archive, folder, sha, size, threading.Event())
    expected = target.read_bytes()
    target.write_bytes(b"TAMPERED")
    wsl._extract(archive, folder, sha, size, threading.Event())
    assert target.read_bytes() == expected
    assert not (folder / "README.txt").exists()
    with pytest.raises(SetupError, match="checksum"):
        wsl._extract(archive, folder, "0" * 64, size, threading.Event())


@pytest.mark.parametrize(
    "unsafe", ["../BindsightCompanion", "/BindsightCompanion", "sub/BindsightCompanion"]
)
def test_unsafe_zip_never_extracts(tmp_path: Path, unsafe: str) -> None:
    archive, sha, size = _archive(tmp_path, unsafe=unsafe)
    with pytest.raises(SetupError, match="unsafe"):
        wsl._extract(archive, tmp_path / "app", sha, size, threading.Event())
    assert not list((tmp_path / "app").iterdir())


def test_cancelled_extraction_leaves_no_executable(tmp_path: Path) -> None:
    archive, sha, size = _archive(tmp_path)
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(Cancelled):
        wsl._extract(archive, tmp_path / "app", sha, size, cancel)
    assert not list((tmp_path / "app").iterdir())


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.test/workbench",
        "http://127.0.0.1:88@evil.test/workbench",
        "http://localhost:88/workbench",
        "http://127.0.0.1:88/workbench?next=evil",
        "http://127.0.0.1:99999/workbench",
        "http://127.0.0.1:88/workbench\n",
        "file:///private",
    ],
)
def test_browser_event_cannot_open_arbitrary_address(url: str) -> None:
    opened = []
    wsl._event(json.dumps({"event": "browser", "url": url}), lambda value: None, opened.append)
    assert opened == []


def test_valid_browser_and_log_events() -> None:
    opened, messages = [], []
    wsl._event(
        '{"event":"browser","url":"http://127.0.0.1:8181/workbench"}',
        messages.append,
        opened.append,
    )
    wsl._event('{"event":"log","message":"Actual setup output"}', messages.append, opened.append)
    assert opened == ["http://127.0.0.1:8181/workbench"]
    assert messages == ["Actual setup output"]


def test_handoff_refuses_unready_gpu_before_download(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(wsl, "readiness", lambda: {"ready": False, "blockers": ["Only 2 GB GPU"]})
    monkeypatch.setattr(wsl, "download", lambda *a, **k: pytest.fail("No download"))
    with pytest.raises(SetupError, match="2 GB"):
        wsl.launch(tmp_path, "a" * 40, lambda value: None, threading.Event(), lambda value: None)


def test_handoff_downloads_matching_release_and_passes_only_fixed_flags(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    archive, sha, size = _archive(tmp_path)
    monkeypatch.setattr(wsl, "readiness", lambda: {"ready": True, "distro": "Ubuntu-24.04"})
    monkeypatch.setattr(wsl, "_wsl_executable", lambda: Path("C:/Windows/System32/wsl.exe"))
    monkeypatch.setattr(wsl, "_linux_path", lambda distro, path: "/mnt/c/owned/" + path.name)
    monkeypatch.setattr(wsl, "_run", lambda *a, **k: "")
    urls = []

    def download(url: str, target: Path, limit: int, *args: Any, **kwargs: Any) -> None:
        urls.append(url)
        if url.endswith("companion.json"):
            target.write_text(
                json.dumps(
                    {
                        "revision": "a" * 40,
                        "platforms": {
                            "linux-x64": {
                                "filename": "Bindsight-Companion-linux-x64.zip",
                                "sha256": sha,
                                "size_bytes": size,
                            }
                        },
                    }
                )
            )
        else:
            assert kwargs["expected_sha"] == sha
            assert limit == size
            target.write_bytes(archive.read_bytes())

    monkeypatch.setattr(wsl, "download", download)
    commands = []
    monkeypatch.setattr(wsl, "_bridge", lambda args, *rest: commands.append(args))
    wsl.launch(
        tmp_path / "owned", "a" * 40, lambda value: None, threading.Event(), lambda value: None
    )
    assert all(url.startswith(wsl.PINS["release_base"] + "downloads/") for url in urls)
    assert commands[0][1:4] == ["--distribution", "Ubuntu-24.04", "--exec"]
    assert commands[0][5:8] == ["--headless", "--setup-approved", "--cancel-file"]


def test_cancel_marker_precedes_wait_and_never_terminates_distro(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    marker = tmp_path / "cancel"
    cancel = threading.Event()
    cancel.set()
    events = []

    class Process:
        stdout = io.BytesIO(b'{"event":"log","message":"started"}\n')
        returncode = None

        def poll(self) -> int | None:
            return self.returncode

        def wait(self, timeout: float) -> int:
            assert marker.read_text() == "cancel\n"
            events.append("graceful_wait")
            self.returncode = 0
            return 0

        def terminate(self) -> None:
            pytest.fail("Graceful cancellation must not kill the client")

    monkeypatch.setattr(wsl.subprocess, "Popen", lambda *a, **k: Process())
    with pytest.raises(Cancelled):
        wsl._bridge(
            ["wsl.exe", "--exec", "owned"], marker, cancel, lambda value: None, lambda value: None
        )
    assert events == ["graceful_wait"]

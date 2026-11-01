# SPDX-License-Identifier: AGPL-3.0-or-later
"""The packager must use the version CI and documented local setup install."""

from __future__ import annotations

import re
import sys
from importlib.metadata import PackageNotFoundError
from pathlib import Path
from unittest.mock import Mock

import pytest
import yaml

from companion import build


def requirements_file(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "requirements-build.txt"
    path.write_text(text, encoding="utf-8")
    return path


@pytest.mark.parametrize("pin", ["6.22.3", "9.9.9"])
def test_build_accepts_the_installed_version_from_the_file(tmp_path, monkeypatch, pin):
    path = requirements_file(tmp_path, f"\ufeff# Packaging tool\npyinstaller == {pin} # reviewed\n")
    monkeypatch.setattr(build, "version", lambda _package: pin)
    assert build.check_pyinstaller(path) == pin


@pytest.mark.parametrize(
    "text",
    [
        "",
        "# PyInstaller==6.22.3\n",
        "PyInstaller>=6.22.3\n",
        "PyInstaller==6.*\n",
        "PyInstaller==6.22.3; sys_platform == 'win32'\n",
        "PyInstaller==6.22.3\nPyInstaller==6.22.3\n",
        "PyInstaller==6.22.3\nPyInstaller==6.16.0\n",
    ],
)
def test_ambiguous_or_inexact_packaging_pin_is_rejected(tmp_path, text):
    with pytest.raises(ValueError, match="exactly one PyInstaller"):
        build.pinned_pyinstaller(requirements_file(tmp_path, text))


def test_missing_installed_packager_names_the_required_version(tmp_path, monkeypatch):
    path = requirements_file(tmp_path, "PyInstaller==6.22.3\n")
    monkeypatch.setattr(build, "version", Mock(side_effect=PackageNotFoundError("pyinstaller")))
    with pytest.raises(ValueError, match=r"not installed.*6\.22\.3"):
        build.check_pyinstaller(path)


@pytest.mark.parametrize("problem", ["mismatch", "missing-file"])
def test_bad_build_environment_stops_before_creating_artifacts(
    tmp_path, monkeypatch, capsys, problem
):
    companion = tmp_path / "companion"
    companion.mkdir()
    if problem != "missing-file":
        requirements_file(companion, "PyInstaller==6.22.3\n")
    monkeypatch.setattr(build, "ROOT", tmp_path)
    monkeypatch.setattr(build, "version", lambda _package: "6.16.0")
    monkeypatch.setattr(build.subprocess, "check_output", Mock(side_effect=["a" * 40, ""]))
    package = Mock(side_effect=AssertionError("Packaging must not start"))
    monkeypatch.setattr(build.subprocess, "run", package)
    output = tmp_path / "output"
    monkeypatch.setattr(sys, "argv", ["build.py", "--revision", "a" * 40, "--output", str(output)])

    with pytest.raises(SystemExit) as error:
        build.main()

    assert error.value.code == 2
    message = capsys.readouterr().err
    assert "requirements-build.txt" in message
    if problem == "mismatch":
        assert "6.16.0" in message
        assert "6.22.3" in message
    package.assert_not_called()
    assert not output.exists()
    assert not (companion / ".build").exists()


def test_ci_installs_the_canonical_packager_file():
    root = Path(__file__).resolve().parents[1]
    workflow = yaml.safe_load((root / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    commands = [step["run"] for step in workflow["jobs"]["companion"]["steps"] if "run" in step]
    canonical_install = re.compile(
        r"(?m)^\s*python\s+-m\s+pip\s+install\b[^#\n]*\s-r\s+companion/requirements-build\.txt\b"
    )
    assert any(canonical_install.search(cmd) for cmd in commands)
    assert not any(re.search(r"pyinstaller\s*==", cmd, re.I) for cmd in commands)
    assert build.pinned_pyinstaller(root / "companion/requirements-build.txt")

# SPDX-License-Identifier: AGPL-3.0-or-later
"""Installer integrity and dispatch checks; no GPU or scientific validation."""

import ast
import hashlib
import io
import json
import os
import pathlib
import shlex
import tarfile
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import pytest

from bindsight.runners import installer_security as secure
from bindsight.runners import kaggle_kernel


def _archive(kind=tarfile.REGTYPE):
    content = io.BytesIO()
    with tarfile.open(fileobj=content, mode="w:gz") as archive:
        member = tarfile.TarInfo("uv-x86_64-unknown-linux-gnu/uv")
        member.type = kind
        member.linkname = "../../outside"
        data = b"ARTIFICIAL EXECUTABLE FIXTURE"
        member.size = len(data) if kind == tarfile.REGTYPE else 0
        archive.addfile(member, io.BytesIO(data) if member.size else None)
    return content.getvalue()


def _fixture_pin(monkeypatch, archive):
    monkeypatch.setattr(secure, "UV_ARCHIVE_BYTES", len(archive))
    monkeypatch.setattr(secure, "UV_ARCHIVE_SHA256", hashlib.sha256(archive).hexdigest())


def test_uv_archive_checked_before_existing_executable_is_replaced(tmp_path, monkeypatch):
    archive = _archive()
    _fixture_pin(monkeypatch, archive)
    target = tmp_path / "uv"
    target.write_bytes(b"EXISTING EXECUTABLE")
    with pytest.raises(RuntimeError, match="SHA256"):
        secure.extract_verified_uv(archive[:-1] + bytes([archive[-1] ^ 1]), target)
    assert target.read_bytes() == b"EXISTING EXECUTABLE"
    secure.extract_verified_uv(archive, target)
    assert target.read_bytes() == b"ARTIFICIAL EXECUTABLE FIXTURE"


@pytest.mark.parametrize("kind", [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.DIRTYPE])
def test_uv_extractor_never_extracts_links_or_directories(tmp_path, monkeypatch, kind):
    archive = _archive(kind)
    _fixture_pin(monkeypatch, archive)
    with pytest.raises(RuntimeError, match="entry"):
        secure.extract_verified_uv(archive, tmp_path / "uv")
    assert list(tmp_path.iterdir()) == []


def test_secure_installer_pin_matches_the_independently_verified_companion_pin():
    pins = json.loads((Path(__file__).parents[1] / "companion/pins.json").read_text())
    linux = pins["artifacts"]["linux-x64"]
    assert pins["uv_version"] == secure.UV_VERSION
    assert linux["bytes"] == secure.UV_ARCHIVE_BYTES
    assert linux["sha256"] == secure.UV_ARCHIVE_SHA256


def test_uv_transport_failure_uses_verified_official_fallback(tmp_path, monkeypatch):
    archive = _archive()
    _fixture_pin(monkeypatch, archive)
    calls = []

    def response(url, **kwargs):
        calls.append(url)
        if len(calls) == 1:
            raise urllib.error.HTTPError(url, 403, "host unavailable", {}, None)
        return io.BytesIO(archive)

    monkeypatch.setattr(urllib.request, "urlopen", response)
    target = tmp_path / "uv"
    assert secure.download_verified_uv(target) == target
    assert calls == list(secure.UV_ARCHIVE_URLS)
    assert target.read_bytes() == b"ARTIFICIAL EXECUTABLE FIXTURE"
    provenance = json.loads(target.with_suffix(".download.json").read_text())
    assert provenance["source"] == secure.UV_ARCHIVE_URLS[-1]
    assert provenance["sha256"] == secure.UV_ARCHIVE_SHA256
    assert "403" in provenance["attempts"][0]["error"]
    # Re-use still authenticates the archive and repairs a changed executable.
    target.write_bytes(b"MODIFIED EXECUTABLE")
    secure.download_verified_uv(target)
    assert len(calls) == 2
    assert target.read_bytes() == b"ARTIFICIAL EXECUTABLE FIXTURE"


def test_uv_integrity_failure_never_tries_another_source(tmp_path, monkeypatch):
    archive = _archive()
    _fixture_pin(monkeypatch, archive)
    calls = []

    def response(url, **kwargs):
        calls.append(url)
        return io.BytesIO(b"CORRUPTED ARCHIVE")

    monkeypatch.setattr(urllib.request, "urlopen", response)
    with pytest.raises(RuntimeError, match="SHA256"):
        secure.download_verified_uv(tmp_path / "uv")
    assert calls == [secure.UV_ARCHIVE_URLS[0]]
    assert not (tmp_path / "uv").exists()


def test_environment_cannot_select_insecure_tls_or_a_different_package_index(tmp_path):
    original = {
        "UV_INSECURE_HOST": "pypi.org",
        "UV_INDEX_URL": "https://untrusted.example/simple",
        "PIP_TRUSTED_HOST": "pypi.org",
        "SSL_CERT_FILE": "/untrusted/certificates",
        "CONDA_PREFIX": "/unrelated/environment",
        "PATH": "/managed/bin",
    }
    result = secure.package_environment(original, tmp_path / "cache")
    assert result["PATH"] == original["PATH"]
    assert set(result) == {"PATH", "UV_CACHE_DIR", "UV_NO_PROGRESS", "UV_NO_PYTHON_DOWNLOADS"}
    assert "UV_INSECURE_HOST" in original  # Parent process settings were not mutated.


def test_micromamba_download_verified_before_it_can_replace_an_executable(tmp_path, monkeypatch):
    data = b"ARTIFICIAL ENVIRONMENT MANAGER"
    monkeypatch.setattr(secure, "MICROMAMBA_SHA256", hashlib.sha256(data).hexdigest())
    target = tmp_path / "micromamba"
    target.write_bytes(b"EXISTING")
    with pytest.raises(RuntimeError, match="SHA256"):
        secure.write_verified_micromamba(data + b"corruption", target)
    assert target.read_bytes() == b"EXISTING"
    secure.write_verified_micromamba(data, target)
    assert target.read_bytes() == data


def test_generated_kernel_uses_the_same_installer_and_exact_python_target(tmp_path):
    script = kaggle_kernel.build_kernel_script(handle_id="test", payload={})
    tree = ast.parse(script)
    definitions = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "uv_install_command"
    ]
    calls = []
    namespace = {
        "Path": Path,
        "UV": tmp_path / "uv",
        "CERTIFI_REQUIREMENT": secure.CERTIFI_REQUIREMENT,
        "pathlib": pathlib,
        "os": os,
        "shlex": shlex,
        "subprocess": SimpleNamespace(run=lambda argv, **kwargs: calls.append((argv, kwargs))),
    }
    exec(
        compile(ast.Module(body=definitions, type_ignores=[]), "kernel-installer", "exec"),
        namespace,
    )
    for environment in ("se3", "boltz"):
        target = tmp_path / environment
        argv = namespace["uv_install_command"](
            tmp_path / "uv", target / "bin/python", ["torch==2.14.1+cu126"]
        )
        assert argv == secure.uv_install_command(
            tmp_path / "uv", target / "bin/python", ["torch==2.14.1+cu126"]
        )
    assert "pip install" not in script  # The target interpreter's pip never makes a download.
    assert "micro.mamba.pm" not in script
    assert secure.UV_ARCHIVE_SHA256 in script
    assert "download_verified_uv(UV, report=print)" in script
    assert "bindsight.runners.gpu_runtime" in script

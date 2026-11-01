# SPDX-License-Identifier: AGPL-3.0-or-later
"""The release source boundary must be checked before any wheel is installed."""

from __future__ import annotations

import hashlib
import io
import json
import urllib.request
import zipfile

import pytest

from bindsight.runners import release_bootstrap as bootstrap

VERSION = "0.3.8"
FILENAME = f"bindsight-{VERSION}-py3-none-any.whl"
URL = "https://files.pythonhosted.org/packages/ab/cd/" + FILENAME


def wheel_bytes(*, package_version=VERSION):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as wheel:
        wheel.writestr(
            f"bindsight-{VERSION}.dist-info/METADATA",
            f"Metadata-Version: 2.1\nName: bindsight\nVersion: {package_version}\n",
        )
        wheel.writestr("bindsight/__init__.py", "raise AssertionError('never execute a download')")
    return output.getvalue()


@pytest.fixture
def server(monkeypatch):
    data = wheel_bytes()
    item = {
        "filename": FILENAME,
        "packagetype": "bdist_wheel",
        "yanked": False,
        "url": URL,
        "size": len(data),
        "digests": {"sha256": hashlib.sha256(data).hexdigest()},
    }
    metadata = {"info": {"version": VERSION}, "urls": [item]}
    state = {"metadata": metadata, "wheel": data, "requests": [], "item": item}

    class Response(io.BytesIO):
        def __init__(self, content, url):
            super().__init__(content)
            self.url = url

        def geturl(self):
            return self.url

    class Opener:
        def open(self, request, *, timeout):
            assert timeout == 45
            state["requests"].append(request.full_url)
            content = (
                json.dumps(metadata).encode()
                if request.full_url.startswith("https://pypi.org/")
                else state["wheel"]
            )
            return Response(content, request.full_url)

    monkeypatch.setattr(bootstrap.urllib.request, "build_opener", lambda *handlers: Opener())
    return state


def test_exact_release_wheel_is_verified_and_provenance_recorded(server, tmp_path):
    path = bootstrap.download_release_wheel(VERSION, tmp_path)
    assert path.read_bytes() == server["wheel"]
    receipt = json.loads(path.with_suffix(".source.json").read_text())
    assert receipt["version"] == VERSION
    assert receipt["sha256"] == server["item"]["digests"]["sha256"]
    assert server["requests"] == [f"https://pypi.org/pypi/bindsight/{VERSION}/json", URL]


@pytest.mark.parametrize(
    "version", ["main", "latest", "0.0.0+unknown", "0.3.8.dev1", "../0.3.8", "0.3.8?token=x"]
)
def test_unpublished_or_unsafe_version_never_reaches_network(server, tmp_path, version):
    with pytest.raises(ValueError, match="exact published"):
        bootstrap.download_release_wheel(version, tmp_path)
    assert not server["requests"]


@pytest.mark.parametrize(
    "url",
    [
        "http://files.pythonhosted.org/packages/" + FILENAME,
        "https://files.pythonhosted.org.evil.test/packages/" + FILENAME,
        "https://files.pythonhosted.org@evil.test/packages/" + FILENAME,
        "https://files.pythonhosted.org:443/packages/" + FILENAME,
        "https://files.pythonhosted.org/packages/" + FILENAME + "?secret=x",
        "https://files.pythonhosted.org/packages/" + FILENAME + "#fragment",
        "https://files.pythonhosted.org/packages/../" + FILENAME,
        "https://files.pythonhosted.org/packages/%2e%2e/" + FILENAME,
        "https://files.pythonhosted.org/other/" + FILENAME,
        "https://files.pythonhosted.org/packages/other.whl",
    ],
)
def test_unapproved_wheel_url_is_rejected_before_fetch(server, tmp_path, url):
    server["item"]["url"] = url
    with pytest.raises(ValueError, match="download metadata"):
        bootstrap.download_release_wheel(VERSION, tmp_path)
    assert len(server["requests"]) == 1
    assert not list(tmp_path.iterdir())


def test_redirect_cannot_escape_official_wheel_boundary():
    handler = bootstrap._ReleaseRedirect("files.pythonhosted.org", FILENAME)
    with pytest.raises(ValueError, match="redirected outside"):
        handler.redirect_request(
            urllib.request.Request(URL), None, 302, "Found", {}, "https://evil.test/payload.whl"
        )


@pytest.mark.parametrize(
    "fault", ["digest", "size", "oversized", "boolean-size", "yanked", "duplicate", "wrong-version"]
)
def test_invalid_artifact_never_becomes_an_installable_wheel(server, tmp_path, fault):
    if fault == "digest":
        server["item"]["digests"]["sha256"] = "0" * 64
    elif fault == "size":
        server["item"]["size"] += 1
    elif fault == "oversized":
        server["item"]["size"] = bootstrap.MAX_WHEEL_BYTES + 1
    elif fault == "boolean-size":
        server["item"]["size"] = True
    elif fault == "yanked":
        server["item"]["yanked"] = True
    elif fault == "duplicate":
        server["metadata"]["urls"].append(dict(server["item"]))
    else:
        server["metadata"]["info"]["version"] = "0.3.7"
    with pytest.raises(ValueError, match=r"(SHA256|size|non-yanked|version)"):
        bootstrap.download_release_wheel(VERSION, tmp_path)
    assert not (tmp_path / FILENAME).exists()
    assert not list(tmp_path.glob(".release-*"))


def test_wheel_internal_version_must_match_verified_release_metadata(server, tmp_path):
    data = wheel_bytes(package_version="0.3.7")
    server["wheel"] = data
    server["item"]["size"] = len(data)
    server["item"]["digests"]["sha256"] = hashlib.sha256(data).hexdigest()
    with pytest.raises(ValueError, match="wheel metadata"):
        bootstrap.download_release_wheel(VERSION, tmp_path)


def test_cached_wheel_is_rehashed_and_tampering_is_not_silently_repaired(server, tmp_path):
    path = bootstrap.download_release_wheel(VERSION, tmp_path)
    data = bytearray(path.read_bytes())
    data[-1] ^= 1
    path.write_bytes(data)
    with pytest.raises(ValueError, match="SHA256"):
        bootstrap.download_release_wheel(VERSION, tmp_path)
    assert len(server["requests"]) == 3  # fresh metadata, no replacement download


def test_bounded_reader_rejects_overlong_response(server):
    with pytest.raises(ValueError, match="size limit"):
        bootstrap._read_https(URL, host="files.pythonhosted.org", filename=FILENAME, maximum=1)


def test_duplicate_json_keys_fail_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(
        bootstrap, "_read_https", lambda *args, **kwargs: b'{"info": {}, "info": {}}'
    )
    with pytest.raises(ValueError, match="duplicate JSON keys"):
        bootstrap.download_release_wheel(VERSION, tmp_path)


@pytest.mark.parametrize(
    "metadata", [[], {"info": None}, {"info": {"version": VERSION}, "urls": [None]}]
)
def test_malformed_metadata_fails_closed(tmp_path, monkeypatch, metadata):
    monkeypatch.setattr(
        bootstrap, "_read_https", lambda *args, **kwargs: json.dumps(metadata).encode()
    )
    with pytest.raises(ValueError, match="metadata does not identify"):
        bootstrap.download_release_wheel(VERSION, tmp_path)

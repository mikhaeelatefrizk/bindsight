"""Launch links only open the fixed local workspace action."""

import json
from unittest.mock import Mock

import pytest

from companion import protocol
from companion.core import SetupError


@pytest.mark.parametrize(
    "uri",
    [
        "bindsight://open?install=1",
        "bindsight://open/path",
        "bindsight://open#fragment",
        "bindsight://open/",
        "bindsight://open --setup-approved",
        "https://evil.example",
        "bindsight://%6fpen",
    ],
)
def test_launch_uri_rejects_extra_actions(uri):
    with pytest.raises(SetupError):
        protocol.validate_open_uri(uri, [uri])


def test_exact_launch_uri_cannot_smuggle_cli_arguments():
    protocol.validate_open_uri("bindsight://open", ["bindsight://open"])
    with pytest.raises(SetupError):
        protocol.validate_open_uri("bindsight://open", ["bindsight://open", "--setup-approved"])


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example/workbench",
        "http://127.0.0.1:0/workbench",
        "http://127.0.0.1:65536/workbench",
        "http://localhost:8080/workbench",
        "http://127.0.0.1:8080/workbench?command=evil",
    ],
)
def test_existing_workspace_never_requests_external_or_invalid_url(tmp_path, monkeypatch, url):
    network = Mock(side_effect=AssertionError("Invalid URL must not be requested"))
    monkeypatch.setattr(protocol.urllib.request, "urlopen", network)
    (tmp_path / "running.json").write_text(json.dumps({"revision": "a" * 40, "url": url}))
    assert protocol.existing_workspace(tmp_path, "a" * 40) is None
    network.assert_not_called()


def test_old_revision_running_marker_is_not_reused(tmp_path, monkeypatch):
    network = Mock()
    monkeypatch.setattr(protocol.urllib.request, "urlopen", network)
    (tmp_path / "running.json").write_text(
        json.dumps({"revision": "b" * 40, "url": "http://127.0.0.1:8080/workbench"})
    )
    assert protocol.existing_workspace(tmp_path, "a" * 40) is None
    network.assert_not_called()

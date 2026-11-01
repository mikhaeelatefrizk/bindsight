# SPDX-License-Identifier: AGPL-3.0-or-later
"""Exercise the exact reviewed upstream client without scientific packages or HTTP."""

import hashlib
import io
import random
import signal
import sys
import tarfile
import threading
import time
import types
from unittest.mock import Mock

import pytest
import requests

from bindsight.runners import boltz_msa as msa

# A small readable client exercises hook integration offline. The exact upstream
# module was compared separately in the release acceptance record; CI does not
# read scratch files, install Boltz, or access a server.
UPSTREAM_SOURCE = b"""import logging, os, tarfile, requests
logger = logging.getLogger(__name__)
def run_mmseqs2(sequences, prefix="tmp", use_env=False, use_pairing=False):
    sequences = [sequences] if isinstance(sequences, str) else sequences
    mode = "pairgreedy" if use_pairing else "all"
    path = f"{prefix}_{mode}"
    os.makedirs(path, exist_ok=True)
    archive = os.path.join(path, "out.tar.gz")
    filename = "pair.a3m" if use_pairing else "uniref.a3m"
    if not os.path.isfile(archive):
        while True:
            try:
                submitted = requests.post("https://example.invalid/ticket/msa", timeout=6.02)
            except requests.exceptions.Timeout:
                logger.warning("Retrying")
                continue
            except Exception:
                continue
            break
        identity = submitted.json()["id"]
        result = requests.get(f"https://example.invalid/result/download/{identity}", timeout=6.02)
        with open(archive, "wb") as stream:
            stream.write(result.content)
    if not os.path.isfile(os.path.join(path, filename)):
        with tarfile.open(archive) as result:
            result.extractall(path)
    with open(os.path.join(path, filename), "rb") as stream:
        data = stream.read().decode()
    return data.split(chr(0))
"""


class Progress:
    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def set_description(self, *args):
        pass

    def update(self, **kwargs):
        pass


@pytest.fixture
def upstream(tmp_path, monkeypatch):
    monkeypatch.setattr(msa, "UPSTREAM_MSA_SHA256", hashlib.sha256(UPSTREAM_SOURCE).hexdigest())
    source = tmp_path / "mmseqs2.py"
    source.write_bytes(UPSTREAM_SOURCE)
    module = types.ModuleType("boltz.data.msa.mmseqs2")
    module.__file__ = str(source)
    # Progress rendering is independent of client logic; tqdm is not a core
    # Bindsight dependency and no scientific runtime is needed for this test.
    progress_module = types.ModuleType("tqdm")
    progress_module.tqdm = Progress
    monkeypatch.setitem(sys.modules, "tqdm", progress_module)
    exec(compile(UPSTREAM_SOURCE, str(source), "exec"), module.__dict__)
    monkeypatch.setitem(sys.modules, module.__name__, module)
    monkeypatch.setattr(requests, "post", lambda *a, **k: pytest.fail("Unexpected HTTP POST"))
    monkeypatch.setattr(requests, "get", lambda *a, **k: pytest.fail("Unexpected HTTP GET"))
    return module


def make_tar(members):
    result = io.BytesIO()
    with tarfile.open(fileobj=result, mode="w:gz") as archive:
        for name, kind, payload in members:
            item = tarfile.TarInfo(name)
            item.type = kind
            item.mode = 0o755 if kind == tarfile.DIRTYPE else 0o644
            item.linkname = "../../outside"
            item.size = len(payload) if kind == tarfile.REGTYPE else 0
            archive.addfile(item, io.BytesIO(payload) if item.size else None)
    return result.getvalue()


def extract(payload, destination):
    with msa._TarfileProxy().open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
        archive.extractall(destination)


def response(payload):
    result = requests.Response()
    result.status_code = 200
    result.raw = io.BytesIO(payload)
    result.close = Mock(wraps=result.close)
    return result


@pytest.mark.parametrize("paired", [False, True])
@pytest.mark.parametrize("cached", [False, True])
def test_client_success_preserves_msa_and_random_state(
    upstream, tmp_path, monkeypatch, paired, cached
):
    filename = "pair.a3m" if paired else "uniref.a3m"
    mode = "pairgreedy" if paired else "all"
    data = b">101\nAAAA\n>match\nAA-A\n\x00>102\nRRRR\n>match2\nR-RR\n"
    payload = make_tar([("./", tarfile.DIRTYPE, b""), (filename, tarfile.REGTYPE, data)])
    before = random.getstate()
    results = []
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return response(b'{"status":"COMPLETE","id":"fixture"}')

    def get(url, **kwargs):
        calls.append((url, kwargs))
        return response(payload)

    monkeypatch.setattr(requests, "post", post)
    monkeypatch.setattr(requests, "get", get)
    for label in ("original", "bounded"):
        prefix = tmp_path / label
        directory = tmp_path / f"{label}_{mode}"
        directory.mkdir()
        if cached:
            (directory / "out.tar.gz").write_bytes(payload)
        if label == "bounded":
            original_open = tarfile.open
            main = types.SimpleNamespace(compute_msa=lambda: None)
            msa.configure_msa(main)
            assert tarfile.open is original_open
            assert upstream.tarfile is not tarfile
        results.append(
            upstream.run_mmseqs2(
                ["AAAA", "RRRR"], prefix=str(prefix), use_env=False, use_pairing=paired
            )
        )
        assert (directory / filename).read_bytes() == data
    assert results == [[">101\nAAAA\n>match\nAA-A\n", ">102\nRRRR\n>match2\nR-RR\n"]] * 2
    assert random.getstate() == before
    if not cached:
        assert len(calls) == 4
        assert all(call[1].get("stream") is None for call in calls[:2])
        assert all(call[1]["stream"] is True for call in calls[2:])


@pytest.mark.parametrize(
    ("name", "kind"),
    [
        ("../outside", tarfile.REGTYPE),
        ("/outside", tarfile.REGTYPE),
        ("a/../../outside", tarfile.REGTYPE),
        ("a\\outside", tarfile.REGTYPE),
        ("C:outside", tarfile.REGTYPE),
        ("a//outside", tarfile.REGTYPE),
        ("a/./outside", tarfile.REGTYPE),
        (".", tarfile.REGTYPE),
        ("./", tarfile.REGTYPE),
        ("link", tarfile.SYMTYPE),
        ("link", tarfile.LNKTYPE),
        ("device", tarfile.CHRTYPE),
        ("device", tarfile.BLKTYPE),
        ("fifo", tarfile.FIFOTYPE),
        ("sparse", tarfile.GNUTYPE_SPARSE),
    ],
)
def test_hostile_member_rejected_before_any_write(tmp_path, name, kind):
    payload = make_tar([("safe", tarfile.REGTYPE, b"valid"), (name, kind, b"malicious")])
    with pytest.raises(msa.MSABoundaryError):
        extract(payload, tmp_path / "destination")
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "members",
    [
        [("same", tarfile.REGTYPE, b"one"), ("./same", tarfile.REGTYPE, b"one")],
        [("parent", tarfile.REGTYPE, b"one"), ("parent/child", tarfile.REGTYPE, b"two")],
    ],
)
def test_duplicate_and_conflicting_paths_write_nothing(tmp_path, members):
    with pytest.raises(msa.MSABoundaryError):
        extract(make_tar(members), tmp_path / "destination")
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    ("limit", "value"), [("MAX_ARCHIVE_ENTRIES", 1), ("MAX_EXTRACTED_BYTES", 2)]
)
def test_archive_limits_precede_writes(tmp_path, monkeypatch, limit, value):
    monkeypatch.setattr(msa, limit, value)
    with pytest.raises(msa.MSABoundaryError, match="limit"):
        extract(
            make_tar([("first", tarfile.REGTYPE, b"ab"), ("second", tarfile.REGTYPE, b"cd")]),
            tmp_path / "destination",
        )
    assert list(tmp_path.iterdir()) == []


def test_empty_archive_rejected_before_writes(tmp_path):
    with pytest.raises(msa.MSABoundaryError, match="empty"):
        extract(make_tar([]), tmp_path / "destination")
    assert list(tmp_path.iterdir()) == []


def test_directory_only_archive_rejected_before_writes(tmp_path):
    with pytest.raises(msa.MSABoundaryError, match="no regular files"):
        extract(make_tar([("./", tarfile.DIRTYPE, b"")]), tmp_path / "destination")
    assert list(tmp_path.iterdir()) == []


def test_cached_compressed_archive_limit_precedes_tar_open(tmp_path, monkeypatch):
    payload = make_tar([("file", tarfile.REGTYPE, b"content")])
    archive = tmp_path / "cached.tar.gz"
    archive.write_bytes(payload)
    monkeypatch.setattr(msa, "MAX_ARCHIVE_BYTES", len(payload) - 1)
    with pytest.raises(msa.MSABoundaryError, match="compressed archive"):
        msa._TarfileProxy().open(archive)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["cached.tar.gz"]


def test_real_requests_response_bytes_json_and_text_preserved(monkeypatch):
    data = b'{"message":"unicode \\u00e9", "status":"COMPLETE"}'
    original = response(data)
    bounded = response(data)
    captured = {}

    def post(url, **kwargs):
        captured.update(kwargs)
        return bounded

    proxy = msa._RequestsProxy(types.SimpleNamespace(post=post))
    result = proxy.post("https://example.invalid/ticket/msa", timeout=6.02)
    assert result is bounded
    assert result.content == original.content == data
    assert result.json() == original.json()
    assert result.text == original.text
    assert captured == {"timeout": 6.02, "stream": True}
    bounded.close.assert_called_once()


@pytest.mark.parametrize("download", [False, True])
def test_response_limit_escapes_retry_and_closes_response(
    upstream, monkeypatch, tmp_path, download
):
    monkeypatch.setattr(msa, "MAX_ARCHIVE_BYTES" if download else "MAX_JSON_BYTES", 3)
    oversized = response(b"1234")
    if download:
        monkeypatch.setattr(
            requests, "post", lambda *a, **k: response(b'{"status":"COMPLETE","id":"fixture"}')
        )
        monkeypatch.setattr(requests, "get", lambda *a, **k: oversized)
    else:
        monkeypatch.setattr(requests, "post", lambda *a, **k: oversized)
    msa.configure_msa(types.SimpleNamespace(compute_msa=lambda: None))
    with pytest.raises(msa.MSABoundaryError, match="response exceeds"):
        upstream.run_mmseqs2("AAAA", prefix=str(tmp_path / "remote"), use_env=False)
    oversized.close.assert_called_once()
    assert not (tmp_path / "remote_all/out.tar.gz").exists()


def test_response_cleanup_cannot_mask_deadline():
    error = msa.MSADeadlineExceeded("fixture deadline")

    class Response:
        def iter_content(self, **kwargs):
            raise error

        def close(self):
            raise OSError("fixture cleanup failure")

    proxy = msa._RequestsProxy(types.SimpleNamespace(get=lambda *a, **k: Response()))
    with pytest.raises(msa.MSADeadlineExceeded) as caught:
        proxy.get("https://example.invalid/result/download/fixture")
    assert caught.value is error


def test_new_deadline_during_response_cleanup_is_not_suppressed():
    error = msa.MSADeadlineExceeded("fixture deadline during cleanup")

    class Response:
        def iter_content(self, **kwargs):
            raise OSError("fixture read failure")

        def close(self):
            raise error

    proxy = msa._RequestsProxy(types.SimpleNamespace(get=lambda *a, **k: Response()))
    with pytest.raises(msa.MSADeadlineExceeded) as caught:
        proxy.get("https://example.invalid/result/download/fixture")
    assert caught.value is error


def test_existing_identical_file_not_overwritten_and_different_file_rejected(tmp_path):
    existing = tmp_path / "same"
    existing.write_bytes(b"same bytes")
    timestamp = existing.stat().st_mtime_ns
    extract(make_tar([("same", tarfile.REGTYPE, b"same bytes")]), tmp_path)
    assert existing.stat().st_mtime_ns == timestamp
    with pytest.raises(msa.MSABoundaryError, match="differs"):
        extract(
            make_tar([("new", tarfile.REGTYPE, b"new"), ("same", tarfile.REGTYPE, b"different")]),
            tmp_path,
        )
    assert existing.read_bytes() == b"same bytes"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["same"]


@pytest.mark.parametrize("target_is_directory", [False, True])
def test_existing_link_destination_rejected(tmp_path, target_is_directory):
    outside = tmp_path / "outside"
    if target_is_directory:
        outside.mkdir()
    else:
        outside.write_bytes(b"preserve")
    destination = tmp_path / "destination"
    destination.mkdir()
    try:
        (destination / "link").symlink_to(outside, target_is_directory=target_is_directory)
    except OSError:
        pytest.skip("Host cannot create symlinks")
    filename = "link/child" if target_is_directory else "link"
    with pytest.raises(msa.MSABoundaryError, match="symbolic link"):
        extract(make_tar([(filename, tarfile.REGTYPE, b"changed")]), destination)
    assert (
        list(outside.iterdir()) == []
        if target_is_directory
        else outside.read_bytes() == b"preserve"
    )


@pytest.mark.parametrize("value", ["", "0", "-1", "nan", "inf", "21601", "one"])
def test_invalid_timeout_rejected_before_hooking(upstream, monkeypatch, value):
    monkeypatch.setenv("BINDSIGHT_MSA_TIMEOUT", value)
    main = types.SimpleNamespace(compute_msa=lambda: None)
    original = main.compute_msa
    with pytest.raises(ValueError, match="BINDSIGHT_MSA_TIMEOUT"):
        msa.configure_msa(main)
    assert main.compute_msa is original
    assert upstream.tarfile is tarfile


def test_unknown_source_rejected_before_hooking(upstream):
    from pathlib import Path

    Path(upstream.__file__).write_bytes(UPSTREAM_SOURCE + b"\n")
    main = types.SimpleNamespace(compute_msa=lambda: None)
    original = main.compute_msa
    with pytest.raises(RuntimeError, match="source differs"):
        msa.configure_msa(main)
    assert main.compute_msa is original
    assert upstream.tarfile is tarfile


def test_repeated_configuration_does_not_double_wrap(upstream):
    main = types.SimpleNamespace(compute_msa=lambda: None)
    msa.configure_msa(main)
    wrapper, proxy = main.compute_msa, upstream.tarfile
    msa.configure_msa(main)
    assert main.compute_msa is wrapper
    assert upstream.tarfile is proxy


def test_unsupported_platform_fails_before_original(upstream, monkeypatch):
    main = types.SimpleNamespace(compute_msa=lambda: pytest.fail("Must not start"))
    msa.configure_msa(main)
    monkeypatch.setattr(msa.sys, "platform", "win32")
    with pytest.raises(RuntimeError, match="Linux main thread"):
        main.compute_msa()


LINUX_ONLY = pytest.mark.skipif(
    not sys.platform.startswith("linux"), reason="Linux SIGALRM boundary"
)


@LINUX_ONLY
@pytest.mark.parametrize("fails", [False, True])
def test_alarm_restored_after_success_or_failure(upstream, monkeypatch, capsys, fails):
    monkeypatch.setenv("BINDSIGHT_MSA_TIMEOUT", "1")

    def original():
        if fails:
            raise ValueError("fixture failure")
        return b"unchanged result"

    main = types.SimpleNamespace(compute_msa=original)
    msa.configure_msa(main)
    before = signal.getsignal(signal.SIGALRM)
    assert signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0)
    if fails:
        with pytest.raises(ValueError, match="fixture failure"):
            main.compute_msa()
    else:
        assert main.compute_msa() == b"unchanged result"
    assert signal.getsignal(signal.SIGALRM) is before
    assert signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0)
    output = capsys.readouterr().out
    assert "MSA phase begin timeout=1s" in output
    assert f"MSA phase {'failed' if fails else 'complete'} elapsed=" in output


@LINUX_ONLY
def test_deadline_escapes_client_retry_loop_and_restores_alarm(upstream, monkeypatch, tmp_path):
    monkeypatch.setenv("BINDSIGHT_MSA_TIMEOUT", "0.03")
    attempts = []

    def timeout(*args, **kwargs):
        attempts.append(1)
        raise requests.exceptions.Timeout("synthetic remote wait")

    monkeypatch.setattr(requests, "post", timeout)
    monkeypatch.setattr(upstream.logger, "warning", lambda *args, **kwargs: None)

    def original():
        try:
            return upstream.run_mmseqs2("AAAA", prefix=str(tmp_path / "remote"), use_env=False)
        except Exception:
            pytest.fail("Deadline must escape the upstream process_input exception handler")

    main = types.SimpleNamespace(compute_msa=original)
    msa.configure_msa(main)
    before = signal.getsignal(signal.SIGALRM)
    started = time.monotonic()
    with pytest.raises(msa.MSADeadlineExceeded, match="exceeded"):
        main.compute_msa()
    assert attempts
    assert time.monotonic() - started < 2
    assert signal.getsignal(signal.SIGALRM) is before
    assert signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0)


@LINUX_ONLY
def test_existing_alarm_refused_without_mutation(upstream):
    main = types.SimpleNamespace(compute_msa=lambda: pytest.fail("Must not start"))
    msa.configure_msa(main)
    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_timer = signal.getitimer(signal.ITIMER_REAL)
    try:
        signal.setitimer(signal.ITIMER_REAL, 5)
        with pytest.raises(RuntimeError, match="another real-time alarm"):
            main.compute_msa()
        assert 0 < signal.getitimer(signal.ITIMER_REAL)[0] <= 5
        assert signal.getsignal(signal.SIGALRM) is previous_handler
    finally:
        signal.setitimer(signal.ITIMER_REAL, *previous_timer)
        signal.signal(signal.SIGALRM, previous_handler)


@LINUX_ONLY
def test_worker_thread_refused_before_original(upstream):
    main = types.SimpleNamespace(compute_msa=lambda: pytest.fail("Must not start"))
    msa.configure_msa(main)
    failures = []

    def invoke():
        try:
            main.compute_msa()
        except RuntimeError as error:
            failures.append(str(error))

    thread = threading.Thread(target=invoke)
    thread.start()
    thread.join(timeout=2)
    assert not thread.is_alive()
    assert failures == ["Bounded Boltz MSA execution requires the Linux main thread"]

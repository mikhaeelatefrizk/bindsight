# SPDX-License-Identifier: AGPL-3.0-or-later
"""Check a metadata-only wheel rebuild; these tests do not validate GPU results."""

import base64
import csv
import hashlib
import io
import json
import zipfile

import pytest

from bindsight.runners import boltz_runtime_wheel as runtime

OLD_INFO = "boltz-2.0.3.dist-info/"
NEW_INFO = "boltz-2.0.3+bindsight.1.dist-info/"
METADATA = (
    b"Metadata-Version: 2.1\nName: boltz\nVersion: 2.0.3\n"
    b"Summary: metadata-only test\n  Version: 2.0.3\n"
    b"Requires-Dist: hydra-core ==1.3.2\n"
    b"Requires-Dist: pytorch-lightning ==2.5.0\n"
    b"Requires-Dist: requests ==2.32.3\n"
    b"Requires-Dist: biopython ==1.84\n"
    b"Requires-Dist: requests-toolbelt ==2.32.3\n"
    b'Requires-Dist: pytest ==8.0; extra == "dev"\n'
    b"Requires-Dist: numpy ==1.26.3\n\n"
    b"Version: 2.0.3\nRequires-Dist: hydra-core ==1.3.2\n"
    b"Requires-Dist: biopython ==1.84\n"
)


def make_upstream(metadata=METADATA, extra=()):
    entries = [
        ("boltz/model/core.py", b"# Scientific source fixture\nANSWER = 42\n"),
        (OLD_INFO + "LICENSE", b"LICENSE fixture\r\nCopyright retained\n"),
        ("boltz/data/ccd.bin", bytes(range(256)) + b"PK\x03\x04\r\n"),
        (OLD_INFO + "METADATA", metadata),
        ("boltz/__init__.py", b""),
        (OLD_INFO + "WHEEL", b"Wheel-Version: 1.0\nTag: py3-none-any\n"),
        (OLD_INFO + "entry_points.txt", b"[console_scripts]\nboltz=boltz.main:cli\n"),
        *extra,
    ]
    record = io.StringIO(newline="")
    writer = csv.writer(record, lineterminator="\n")
    for name, data in entries:
        digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
        writer.writerow((name, "sha256=" + digest, len(data)))
    writer.writerow((OLD_INFO + "RECORD", "", ""))
    entries.append((OLD_INFO + "RECORD", record.getvalue().encode()))
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as wheel:
        for name, data in entries:
            wheel.writestr(zipfile.ZipInfo(name, (2024, 1, 2, 3, 4, 6)), data)
    return output.getvalue()


def pin_fixture(monkeypatch, original):
    monkeypatch.setattr(runtime, "UPSTREAM_BYTES", len(original))
    monkeypatch.setattr(runtime, "UPSTREAM_SHA256", hashlib.sha256(original).hexdigest())


@pytest.fixture
def upstream(monkeypatch):
    original = make_upstream()
    pin_fixture(monkeypatch, original)
    calls = []

    def download(url, **kwargs):
        calls.append((url, kwargs))
        return io.BytesIO(original)

    monkeypatch.setattr(runtime.urllib.request, "urlopen", download)
    return original, calls


def test_only_five_metadata_headers_change_and_all_other_bytes_survive(tmp_path, upstream):
    original, calls = upstream
    path, receipt = runtime.prepare_boltz_runtime_wheel(tmp_path)
    assert path.name == "boltz-2.0.3+bindsight.1-py3-none-any.whl"
    assert len(calls) == 1
    with zipfile.ZipFile(io.BytesIO(original)) as source, zipfile.ZipFile(path) as patched:

        def renamed(name):
            return NEW_INFO + name[len(OLD_INFO) :] if name.startswith(OLD_INFO) else name

        assert set(patched.namelist()) == {renamed(name) for name in source.namelist()}
        for name in source.namelist():
            if name not in (OLD_INFO + "METADATA", OLD_INFO + "RECORD"):
                assert patched.read(renamed(name)) == source.read(name)
        actual = patched.read(NEW_INFO + "METADATA")
        old_lines, new_lines = METADATA.splitlines(keepends=True), actual.splitlines(keepends=True)
        assert len(old_lines) == len(new_lines)
        differences = [(a, b) for a, b in zip(old_lines, new_lines, strict=True) if a != b]
        assert differences == [
            (b"Version: 2.0.3\n", b"Version: 2.0.3+bindsight.1\n"),
            (b"Requires-Dist: hydra-core ==1.3.2\n", b"Requires-Dist: hydra-core ==1.3.8\n"),
            (
                b"Requires-Dist: pytorch-lightning ==2.5.0\n",
                b"Requires-Dist: pytorch-lightning ==2.6.6\n",
            ),
            (b"Requires-Dist: requests ==2.32.3\n", b"Requires-Dist: requests ==2.34.2\n"),
            (b"Requires-Dist: biopython ==1.84\n", b"Requires-Dist: biopython ==1.88\n"),
        ]
        assert actual.partition(b"\n\n")[2] == METADATA.partition(b"\n\n")[2]
        assert receipt["unchanged_package_files"] == {
            name: hashlib.sha256(source.read(name)).hexdigest()
            for name in source.namelist()
            if name.startswith("boltz/")
        }
    assert receipt["unchanged_implementation"] is True
    assert receipt["upstream_sha256"] == hashlib.sha256(original).hexdigest()
    assert receipt["patched_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert receipt["installed_version"] == "2.0.3+bindsight.1"
    assert json.loads((tmp_path / "boltz-dependency-patch.json").read_text()) == receipt


def test_rebuilt_record_exactly_covers_all_members_with_valid_hashes(tmp_path, upstream):
    path, _ = runtime.prepare_boltz_runtime_wheel(tmp_path)
    with zipfile.ZipFile(path) as wheel:
        record_name = NEW_INFO + "RECORD"
        rows = list(csv.reader(io.StringIO(wheel.read(record_name).decode())))
        assert len(rows) == len({row[0] for row in rows}) == len(wheel.namelist())
        assert {row[0] for row in rows} == set(wheel.namelist())
        for name, digest, size in rows:
            if name == record_name:
                assert (digest, size) == ("", "")
            else:
                payload = wheel.read(name)
                encoded = (
                    base64.urlsafe_b64encode(hashlib.sha256(payload).digest()).rstrip(b"=").decode()
                )
                assert digest == "sha256=" + encoded
                assert size == str(len(payload))


def test_output_is_deterministic_across_directories_and_cached_reuse(
    tmp_path, upstream, monkeypatch
):
    _, calls = upstream
    a, receipt_a = runtime.prepare_boltz_runtime_wheel(tmp_path / "a")
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "2147483647")
    b, receipt_b = runtime.prepare_boltz_runtime_wheel(tmp_path / "b")
    assert a.read_bytes() == b.read_bytes()
    assert receipt_a == receipt_b
    again, receipt_again = runtime.prepare_boltz_runtime_wheel(tmp_path / "a")
    assert again == a
    assert receipt_again == receipt_a
    assert len(calls) == 2  # The authenticated cached upstream avoids a third download.


@pytest.mark.parametrize("corruption", ["same_size", "truncated", "oversized"])
def test_download_integrity_failure_creates_no_wheel(tmp_path, upstream, monkeypatch, corruption):
    original, _ = upstream
    bad = {
        "same_size": original[:-1] + bytes([original[-1] ^ 1]),
        "truncated": original[:-1],
        "oversized": original + b"x",
    }[corruption]
    monkeypatch.setattr(runtime.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(bad))
    with pytest.raises(ValueError, match="size and SHA256"):
        runtime.prepare_boltz_runtime_wheel(tmp_path)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("cached", ["upstream", "downstream"])
def test_changed_cached_wheel_is_rejected_not_silently_reused(tmp_path, upstream, cached):
    _, calls = upstream
    destination, _ = runtime.prepare_boltz_runtime_wheel(tmp_path)
    target = tmp_path / "boltz-2.0.3-py3-none-any.whl" if cached == "upstream" else destination
    data = target.read_bytes()
    target.write_bytes(data[:-1] + bytes([data[-1] ^ 1]))
    with pytest.raises(ValueError, match=r"SHA256|downstream cache"):
        runtime.prepare_boltz_runtime_wheel(tmp_path)
    assert len(calls) == 1


@pytest.mark.parametrize(
    "metadata",
    [
        METADATA.replace(b"Requires-Dist: hydra-core ==1.3.2\n", b"", 1),
        METADATA.replace(
            b"Requires-Dist: hydra-core ==1.3.2\n", b"Requires-Dist: hydra-core >=1.3.2\n", 1
        ),
        METADATA.replace(
            b"Requires-Dist: requests ==2.32.3\n", b"Requires-Dist: requests ==2.32.3\n" * 2, 1
        ),
        METADATA.replace(b"Version: 2.0.3\n", b"Version: 2.0.4\n", 1),
        METADATA.replace(b"Version: 2.0.3\n", b"Version: 2.0.3\n" * 2, 1),
        METADATA.replace(b"\n\n", b"\n", 1),
    ],
)
def test_unreviewed_metadata_shape_is_rejected(monkeypatch, metadata):
    original = make_upstream(metadata)
    pin_fixture(monkeypatch, original)
    with pytest.raises(ValueError, match="metadata"):
        runtime._patch_bytes(original)


@pytest.mark.parametrize("name", ["outside.py", "../outside.py", "boltz/../outside.py"])
def test_unexpected_archive_members_are_rejected(monkeypatch, name):
    original = make_upstream(extra=[(name, b"unexpected")])
    pin_fixture(monkeypatch, original)
    with pytest.raises(ValueError, match="unexpected member"):
        runtime._patch_bytes(original)


def test_duplicate_archive_members_are_rejected(monkeypatch):
    with pytest.warns(UserWarning, match="Duplicate name"):
        original = make_upstream(extra=[("boltz/__init__.py", b"ambiguous")])
    pin_fixture(monkeypatch, original)
    with pytest.raises(ValueError, match="duplicate"):
        runtime._patch_bytes(original)

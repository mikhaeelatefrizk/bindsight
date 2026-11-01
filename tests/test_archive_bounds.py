# SPDX-License-Identifier: AGPL-3.0-or-later
"""Parser allocation guards, including valid PAX logical-size semantics."""

import gzip
import io
import tarfile

import pytest

from bindsight import archive_bounds as bounds


def record(
    name, data=b"", *, kind=tarfile.REGTYPE, size=None, pax=None, format=tarfile.USTAR_FORMAT
):
    info = tarfile.TarInfo(name)
    info.type = kind
    info.size = len(data) if size is None else size
    info.pax_headers = pax or {}
    return info.tobuf(format=format) + data + b"\0" * (-len(data) % 512)


def pax_record(value):
    value = b" comment=" + value + b"\n"
    length = len(value) + 1
    while len(str(length)) + len(value) != length:
        length = len(str(length)) + len(value)
    return str(length).encode() + value


def open_bytes(data, *, max_bytes=2**20, max_members=10):
    return bounds.open_bounded_tar(io.BytesIO(data), max_bytes=max_bytes, max_members=max_members)


@pytest.mark.parametrize(
    "kind", [tarfile.XHDTYPE, tarfile.XGLTYPE, tarfile.GNUTYPE_LONGNAME, tarfile.GNUTYPE_LONGLINK]
)
def test_oversized_extension_rejected_before_dangerous_parser(monkeypatch, kind):
    source = record("metadata", kind=kind, size=bounds.MAX_EXTENSION_BYTES + 1) + b"\0" * 1024

    def forbidden(*args):
        pytest.fail("Oversized metadata reached the allocating stdlib parser")

    monkeypatch.setattr(tarfile.TarInfo, "_proc_pax", forbidden)
    monkeypatch.setattr(tarfile.TarInfo, "_proc_gnulong", forbidden)
    with (
        pytest.raises(bounds.ArchiveLimitError, match="size or member limit"),
        open_bytes(gzip.compress(source), max_bytes=2**30) as archive,
    ):
        archive.getmembers()


def test_original_compressed_pax_reproducer_rejected_before_parser(monkeypatch):
    payload = pax_record(b"A" * 1048576)
    source = record("paxmeta", payload, kind=tarfile.XHDTYPE)
    source += record("file.a3m", b"A") + b"\0" * 1024
    compressed = gzip.compress(source)
    assert len(compressed) < 2048
    monkeypatch.setattr(
        tarfile, "open", lambda *a, **k: pytest.fail("Parser entered before decode bound")
    )
    with pytest.raises(bounds.ArchiveLimitError), open_bytes(compressed, max_bytes=32):
        pytest.fail("Archive must not be opened")


def test_decoded_spool_limit_rejects_gzip_bomb_before_parser(monkeypatch):
    compressed = gzip.compress(b"\0" * 2**20)
    monkeypatch.setattr(
        tarfile, "open", lambda *a, **k: pytest.fail("Parser entered before decode bound")
    )
    with (
        pytest.raises(bounds.ArchiveLimitError),
        open_bytes(compressed, max_bytes=32, max_members=1),
    ):
        pytest.fail("Archive must not be opened")


def test_aggregate_metadata_is_bounded(monkeypatch):
    payload = pax_record(b"A" * 100)
    monkeypatch.setattr(bounds, "MAX_TOTAL_METADATA_BYTES", len(payload) * 2)
    source = (
        b"".join(
            record("pax", payload, kind=tarfile.XHDTYPE) + record(f"file-{index}", b"x")
            for index in range(3)
        )
        + b"\0" * 1024
    )
    with pytest.raises(bounds.ArchiveLimitError), open_bytes(gzip.compress(source)) as archive:
        archive.getmembers()


def test_physical_extension_headers_count_towards_member_limit():
    source = record("pax", pax_record(b"ok"), kind=tarfile.XHDTYPE)
    source += record("file", b"x") + b"\0" * 1024
    with pytest.raises(bounds.ArchiveLimitError), open_bytes(source, max_members=1):
        pytest.fail("PAX plus following file is two physical headers")


@pytest.mark.parametrize("compressed", [False, True])
def test_valid_pax_logical_size_and_longname_offsets_preserved(compressed):
    name = "nested/" + "long-name-" * 30 + ".a3m"
    source = record(
        "short", b"ABC", size=0, pax={"size": "3", "path": name}, format=tarfile.PAX_FORMAT
    )
    source += record("second.a3m", b"Z") + b"\0" * 1024
    with open_bytes(gzip.compress(source) if compressed else source) as archive:
        members = archive.getmembers()
        assert [(item.name, item.size) for item in members] == [(name, 3), ("second.a3m", 1)]
        assert archive.extractfile(members[0]).read() == b"ABC"
        assert archive.extractfile(members[1]).read() == b"Z"


def test_valid_gnu_longname_preserved():
    name = "long-name-" * 30 + ".a3m"
    source = record(name, b"ABC", format=tarfile.GNU_FORMAT) + b"\0" * 1024
    with open_bytes(gzip.compress(source)) as archive:
        member = archive.getmembers()[0]
        assert member.name == name
        assert archive.extractfile(member).read() == b"ABC"


def test_pax_logical_oversize_fails_with_limit_message():
    source = record("file", pax={"size": str(2**33 + 1)}, format=tarfile.PAX_FORMAT) + b"\0" * 1024
    with (
        pytest.raises(bounds.ArchiveLimitError, match="size or member limit"),
        open_bytes(gzip.compress(source), max_bytes=2**33),
    ):
        pytest.fail("Logical size must not escape the bound")


def test_caller_stream_remains_open_and_position_is_restored():
    stream = io.BytesIO(b"prefix" + gzip.compress(record("file", b"A") + b"\0" * 1024))
    stream.seek(len(b"prefix"))
    with bounds.open_bounded_tar(stream, max_bytes=1024, max_members=10) as archive:
        assert archive.extractfile("file").read() == b"A"
        spool = archive.fileobj
    assert spool.closed
    assert not stream.closed
    assert stream.tell() == len(b"prefix")

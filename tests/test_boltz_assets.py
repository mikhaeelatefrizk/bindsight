# SPDX-License-Identifier: AGPL-3.0-or-later
"""Publisher integrity and safe extraction without downloading real model weights."""

import hashlib
import io
import tarfile
from pathlib import Path

import pytest

from bindsight.runners import boltz_assets as assets
from bindsight.runners import gpu_runtime


def make_tar(members):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as archive:
        for name, kind, content in members:
            member = tarfile.TarInfo(name)
            member.type = kind
            member.mode = 0o777
            member.linkname = "../../outside"
            member.size = len(content) if kind == tarfile.REGTYPE else 0
            archive.addfile(member, io.BytesIO(content) if member.size else None)
    return stream.getvalue()


def fixture_assets(monkeypatch, members=None):
    if members is None:
        members = [
            ("./mols/", tarfile.DIRTYPE, b""),
            ("./mols/ALA.pkl", tarfile.REGTYPE, b"raw publisher bytes\x00\xff"),
            ("mols/nested/UNK.pkl", tarfile.REGTYPE, b"another raw member"),
        ]
    data = {
        "boltz2_conf.ckpt": b"synthetic confidence checkpoint",
        "boltz2_aff.ckpt": b"synthetic affinity checkpoint",
        "mols.tar": make_tar(members),
    }
    monkeypatch.setattr(
        assets,
        "ASSETS",
        {
            name: {"bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}
            for name, content in data.items()
        },
    )
    calls = []

    class Response:
        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def raise_for_status(self):
            pass

        def iter_content(self, size):
            for position in range(0, len(self.payload), 127):
                yield self.payload[position : position + 127]

    def get(url, **kwargs):
        calls.append(url)
        assert f"/resolve/{assets.PUBLISHER_REVISION}/" in url
        return Response(data[url.rsplit("/", 1)[-1]])

    monkeypatch.setattr(gpu_runtime.requests, "get", get)
    return data, calls


def test_publisher_bytes_preserved_and_cached_assets_fully_reverified(tmp_path, monkeypatch):
    original, calls = fixture_assets(monkeypatch)
    cache = tmp_path / "cache"
    receipt = assets.prepare_boltz_assets(cache)
    assert len(calls) == 3  # Includes unused affinity, preventing upstream's unverified fetch.
    for name, content in original.items():
        assert (cache / name).read_bytes() == content
        assert receipt["assets"][name]["sha256"] == hashlib.sha256(content).hexdigest()
        assert receipt["assets"][name]["bytes"] == len(content)
        assert receipt["assets"][name]["pin_match"] is True
    assert (cache / "mols/ALA.pkl").read_bytes() == b"raw publisher bytes\x00\xff"
    assert (cache / "mols/nested/UNK.pkl").read_bytes() == b"another raw member"
    assert receipt["molecules"]["files"] == 2
    assert receipt["molecules"]["verified_against_authenticated_archive"] is True
    assert receipt["molecules"]["canonical_files"] == {
        "ALA.pkl": {
            "bytes": len(b"raw publisher bytes\x00\xff"),
            "sha256": hashlib.sha256(b"raw publisher bytes\x00\xff").hexdigest(),
        }
    }
    before = {p: p.stat().st_mtime_ns for p in cache.rglob("*") if p.is_file()}
    assert assets.prepare_boltz_assets(cache) == receipt
    assert len(calls) == 3
    assert {p: p.stat().st_mtime_ns for p in before} == before
    assert not list(cache.glob(".boltz-*-*"))


@pytest.mark.parametrize("name", ["boltz2_conf.ckpt", "boltz2_aff.ckpt", "mols.tar"])
def test_same_size_cached_asset_tampering_is_rejected(tmp_path, monkeypatch, name):
    _, calls = fixture_assets(monkeypatch)
    cache = tmp_path / "cache"
    assets.prepare_boltz_assets(cache)
    path = cache / name
    data = path.read_bytes()
    changed = bytes([data[0] ^ 1]) + data[1:]
    path.write_bytes(changed)
    with pytest.raises(RuntimeError, match="SHA256"):
        assets.prepare_boltz_assets(cache)
    assert path.read_bytes() == changed
    assert len(calls) == 3


@pytest.mark.parametrize("corruption", ["short", "long", "same_size"])
def test_download_integrity_failure_never_publishes_asset_or_molecules(
    tmp_path, monkeypatch, corruption
):
    data, _ = fixture_assets(monkeypatch)
    original = data["mols.tar"]
    data["mols.tar"] = {
        "short": original[:-1],
        "long": original + b"x",
        "same_size": bytes([original[0] ^ 1]) + original[1:],
    }[corruption]
    cache = tmp_path / "cache"
    with pytest.raises(RuntimeError, match=r"SHA256|size limit"):
        assets.prepare_boltz_assets(cache)
    assert not (cache / "mols.tar").exists()
    assert not (cache / "mols").exists()
    assert not list(cache.glob(".boltz-*-*"))


@pytest.mark.parametrize(
    "kind", [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.CHRTYPE, tarfile.BLKTYPE, tarfile.FIFOTYPE]
)
def test_links_and_special_archive_members_are_rejected(tmp_path, monkeypatch, kind):
    fixture_assets(monkeypatch, [("mols/unsafe", kind, b"")])
    with pytest.raises(ValueError, match="Unsafe"):
        assets.prepare_boltz_assets(tmp_path)
    assert not (tmp_path / "mols").exists()


@pytest.mark.parametrize(
    "name",
    [
        "../escape",
        "/absolute",
        "mols/../escape",
        "other/file",
        "mols\\escape",
        "C:/escape",
        "mols/./file",
        "mols//file",
        "mols/ads:stream",
    ],
)
def test_unsafe_path_rejected_even_after_a_valid_member(tmp_path, monkeypatch, name):
    fixture_assets(
        monkeypatch,
        [
            ("mols/valid.pkl", tarfile.REGTYPE, b"valid"),
            (name, tarfile.REGTYPE, b"unsafe"),
        ],
    )
    with pytest.raises(ValueError, match="Unsafe"):
        assets.prepare_boltz_assets(tmp_path)
    assert not (tmp_path / "mols").exists()
    assert not list(tmp_path.glob(".boltz-*-*"))
    assert not (tmp_path.parent / "escape").exists()


def test_normalized_duplicate_paths_are_rejected(tmp_path, monkeypatch):
    fixture_assets(
        monkeypatch,
        [
            ("./mols/A.pkl", tarfile.REGTYPE, b"one"),
            ("mols/A.pkl", tarfile.REGTYPE, b"two"),
        ],
    )
    with pytest.raises(ValueError, match="Duplicate"):
        assets.prepare_boltz_assets(tmp_path)
    assert not (tmp_path / "mols").exists()


@pytest.mark.parametrize("limit", ["bytes", "entries"])
def test_extraction_limits_prevent_publishing_partial_tree(tmp_path, monkeypatch, limit):
    fixture_assets(monkeypatch)
    monkeypatch.setattr(
        assets, "MAX_EXTRACTED_BYTES" if limit == "bytes" else "MAX_ARCHIVE_ENTRIES", 1
    )
    with pytest.raises(ValueError, match="limit"):
        assets.prepare_boltz_assets(tmp_path)
    assert not (tmp_path / "mols").exists()
    assert not list(tmp_path.glob(".boltz-*-*"))


@pytest.mark.parametrize("change", ["modify", "missing", "extra_file", "extra_directory"])
def test_extracted_cache_compared_to_authenticated_archive_not_local_receipt(
    tmp_path, monkeypatch, change
):
    _, calls = fixture_assets(monkeypatch)
    assets.prepare_boltz_assets(tmp_path)
    path = tmp_path / "mols/ALA.pkl"
    if change == "modify":
        value = path.read_bytes()
        path.write_bytes(bytes([value[0] ^ 1]) + value[1:])
    elif change == "missing":
        path.unlink()
    elif change == "extra_file":
        (tmp_path / "mols/extra.pkl").write_bytes(b"extra")
    else:
        (tmp_path / "mols/extra_directory").mkdir()
    # A locally supplied approval/manifest cannot authorize changed molecule bytes.
    (tmp_path / "boltz-assets.json").write_text('{"verified":true}')
    before = {p.relative_to(tmp_path) for p in tmp_path.rglob("*")}
    with pytest.raises(ValueError, match=r"cache.*(?:differs|mismatch|missing|unexpected)"):
        assets.prepare_boltz_assets(tmp_path)
    assert before == {p.relative_to(tmp_path) for p in tmp_path.rglob("*")}
    assert len(calls) == 3


def _link_or_skip(link: Path, destination: Path, *, directory=False):
    try:
        link.symlink_to(destination, target_is_directory=directory)
    except OSError:
        pytest.skip("This host does not permit creating symbolic links")


@pytest.mark.parametrize("location", ["root", "checkpoint", "molecule"])
def test_symlinked_cache_paths_are_rejected(tmp_path, monkeypatch, location):
    fixture_assets(monkeypatch)
    cache = tmp_path / "cache"
    outside = tmp_path / "outside"
    outside.mkdir()
    if location == "root":
        _link_or_skip(cache, outside, directory=True)
    elif location == "checkpoint":
        cache.mkdir()
        target = outside / "checkpoint"
        target.write_bytes(b"outside bytes")
        _link_or_skip(cache / "boltz2_conf.ckpt", target)
    else:
        assets.prepare_boltz_assets(cache)
        target = outside / "molecule"
        target.write_bytes((cache / "mols/ALA.pkl").read_bytes())
        (cache / "mols/ALA.pkl").unlink()
        _link_or_skip(cache / "mols/ALA.pkl", target)
    with pytest.raises(ValueError, match=r"links|Unsafe"):
        assets.prepare_boltz_assets(cache)

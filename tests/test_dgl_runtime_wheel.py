# SPDX-License-Identifier: AGPL-3.0-or-later
"""Wheel transformation and fail-closed installed identity checks, without DGL."""

from __future__ import annotations

import base64
import csv
import hashlib
import importlib.util
import io
import json
import py_compile
import sys
import zipfile
from types import ModuleType, SimpleNamespace

import pytest

from bindsight.runners import dgl_runtime_wheel as runtime


@pytest.fixture
def upstream(tmp_path, monkeypatch):
    source = tmp_path / f"dgl-{runtime.UPSTREAM_VERSION}-{runtime.WHEEL_TAG}.whl"
    old_info = f"dgl-{runtime.UPSTREAM_VERSION}.dist-info/"
    files = {name: b"# upstream distributed implementation\n" for name in runtime.DISTRIBUTED_PATHS}
    files.update(
        {
            "dgl/_ffi/libinfo.py": b"# original\n" + runtime.VERSION_LINE + b"\n",
            "dgl/local_graph.py": b"def add(x, y): return x + y\n",
            "dgl/libdgl.so": b"binary native compute and RPC bytes\x00\xff",
            old_info
            + "METADATA": f"Metadata-Version: 2.1\nName: dgl\nVersion: {runtime.UPSTREAM_VERSION}\n\nOriginal description\n".encode(),
            old_info + "WHEEL": b"Wheel-Version: 1.0\nRoot-Is-Purelib: false\n",
            old_info + "LICENSE": b"Original Apache-2.0 license fixture\n",
            old_info + "RECORD": b"replaced\n",
        }
    )
    with zipfile.ZipFile(source, "w", compression=zipfile.ZIP_DEFLATED) as wheel:
        for name, data in files.items():
            wheel.writestr(name, data)
    monkeypatch.setattr(runtime, "UPSTREAM_BYTES", source.stat().st_size)
    monkeypatch.setattr(runtime, "UPSTREAM_SHA256", hashlib.sha256(source.read_bytes()).hexdigest())
    return source, files


def test_exact_transformation_license_native_payload_record_and_determinism(upstream, tmp_path):
    source, files = upstream
    first, second = tmp_path / "a.whl", tmp_path / "b.whl"
    receipt = runtime._build_verified_wheel(source, first)
    assert runtime._build_verified_wheel(source, second) == receipt
    assert first.read_bytes() == second.read_bytes()
    old_info = f"dgl-{runtime.UPSTREAM_VERSION}.dist-info/"
    new_info = f"dgl-{runtime.RUNTIME_VERSION}.dist-info/"
    removed = set(runtime.DISTRIBUTED_PATHS) - {"dgl/distributed/__init__.py"}
    assert set(receipt["removed_paths"]) == removed
    with zipfile.ZipFile(first) as wheel:
        assert set(wheel.namelist()) == {
            n.replace(old_info, new_info, 1) for n in files if n not in removed
        }
        for original_name, original in files.items():
            if original_name in removed:
                continue
            name = original_name.replace(old_info, new_info, 1)
            if original_name not in {
                old_info + "METADATA",
                old_info + "RECORD",
                "dgl/_ffi/libinfo.py",
                "dgl/distributed/__init__.py",
            }:
                assert wheel.read(name) == original
            assert wheel.getinfo(name).create_system == 3
            assert wheel.getinfo(name).compress_type == zipfile.ZIP_STORED
        assert wheel.read("dgl/distributed/__init__.py") == runtime.SHIM
        assert runtime.PATCHED_VERSION_LINE in wheel.read("dgl/_ffi/libinfo.py")
        rows = list(csv.reader(io.StringIO(wheel.read(new_info + "RECORD").decode())))
        assert {r[0] for r in rows} == set(wheel.namelist())
        for name, digest, size in rows:
            if name == new_info + "RECORD":
                assert digest == size == ""
            else:
                data = wheel.read(name)
                expected = (
                    base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
                )
                assert digest == "sha256=" + expected
                assert int(size) == len(data)
    assert receipt["unchanged_native_files"] == {
        "dgl/libdgl.so": hashlib.sha256(files["dgl/libdgl.so"]).hexdigest()
    }


def test_unknown_upstream_refused_before_output(upstream, tmp_path):
    source, _ = upstream
    source.write_bytes(source.read_bytes() + b"tamper")
    destination = tmp_path / "unknown.whl"
    with pytest.raises(ValueError, match="reviewed size and SHA256"):
        runtime._build_verified_wheel(source, destination)
    assert not destination.exists()


def test_cached_patched_wheel_tamper_refused(upstream, tmp_path, monkeypatch):
    source, _ = upstream
    reference = tmp_path / "reference.whl"
    expected = runtime._build_verified_wheel(source, reference)
    monkeypatch.setattr(runtime, "PATCHED_SHA256", expected["patched_sha256"])
    monkeypatch.setattr(
        runtime.urllib.request,
        "urlopen",
        lambda *a, **k: pytest.fail("cached upstream must not download"),
    )
    destination, receipt = runtime.prepare_dgl_runtime_wheel(tmp_path)
    assert receipt == expected
    assert json.loads((tmp_path / "dgl-rpc-removal.json").read_bytes()) == expected
    destination.write_bytes(b"wrong local wheel")
    with pytest.raises(ValueError, match="Cached DGL downstream"):
        runtime.prepare_dgl_runtime_wheel(tmp_path)
    assert not (tmp_path / "dgl-rpc-removal.build.whl").exists()


@pytest.fixture
def installed(tmp_path, monkeypatch):
    root = tmp_path / "dgl"
    (root / "distributed").mkdir(parents=True)
    (root / "_ffi").mkdir()
    (root / "distributed/__init__.py").write_bytes(runtime.SHIM)
    (root / "_ffi/libinfo.py").write_bytes(runtime.PATCHED_VERSION_LINE + b"\n")
    (root / "libdgl.so").write_bytes(b"native original")
    info = tmp_path / f"dgl-{runtime.RUNTIME_VERSION}.dist-info"
    info.mkdir()
    (info / "METADATA").write_text(
        f"Name: dgl\nVersion: {runtime.RUNTIME_VERSION}\n", encoding="utf-8"
    )
    monkeypatch.setattr(
        runtime,
        "LIBINFO_SHA256",
        hashlib.sha256((root / "_ffi/libinfo.py").read_bytes()).hexdigest(),
    )
    monkeypatch.setattr(
        runtime, "METADATA_SHA256", hashlib.sha256((info / "METADATA").read_bytes()).hexdigest()
    )
    monkeypatch.setattr(
        runtime, "NATIVE_SHA256", {"dgl/libdgl.so": hashlib.sha256(b"native original").hexdigest()}
    )
    monkeypatch.setattr(
        runtime.importlib.metadata,
        "distribution",
        lambda name: SimpleNamespace(
            version=runtime.RUNTIME_VERSION, locate_file=lambda path: tmp_path / path
        ),
    )
    return root


def test_installed_identity_accepts_only_source_derived_cache(installed):
    source = installed / "distributed/__init__.py"
    py_compile.compile(str(source), doraise=True)
    proof = runtime.verify_installed_dgl()
    assert proof["source_derived_bytecode_files"] == 1
    cache = next((source.parent / "__pycache__").glob("*.pyc"))
    cache.write_bytes(cache.read_bytes()[:-1] + b"!")
    with pytest.raises(RuntimeError, match="bytecode differs"):
        runtime.verify_installed_dgl()


@pytest.mark.parametrize(
    "name",
    [
        "rpc.py",
        "rpc.pyc",
        "rpc_server.py",
        "nn/__init__.py",
        "__pycache__/rpc.cpython-311.pyc",
        "__pycache__/__init__.foreign.pyc",
    ],
)
def test_stale_distributed_files_rejected_before_import(installed, name):
    stale = installed / "distributed" / name
    stale.parent.mkdir(exist_ok=True)
    stale.write_bytes(b"must never import this stale implementation")
    with pytest.raises(RuntimeError, match=r"Stale|extraneous"):
        runtime.verify_installed_dgl()


@pytest.mark.parametrize("name", ["distributed/__init__.py", "_ffi/libinfo.py", "libdgl.so"])
def test_installed_payload_tamper_rejected(installed, name):
    target = installed / name
    target.write_bytes(target.read_bytes() + b"tamper")
    with pytest.raises(RuntimeError, match="differs"):
        runtime.verify_installed_dgl()


def test_import_negative_controls_distinguish_actual_removal(monkeypatch, tmp_path):
    root = tmp_path / "dgl"
    folder = root / "distributed"
    folder.mkdir(parents=True)
    (folder / "__init__.py").write_bytes(runtime.SHIM)
    (folder / "rpc.py").write_text("KNOWN_PRESENT = True\n", encoding="utf-8")
    parent = ModuleType("dgl")
    parent.__path__ = [str(root)]
    monkeypatch.setitem(sys.modules, "dgl", parent)
    # A known-present control proves Python can discover this harmless fixture.
    legacy = ModuleType("dgl.distributed")
    legacy.__path__ = [str(folder)]
    monkeypatch.setitem(sys.modules, "dgl.distributed", legacy)
    observed = importlib.import_module("dgl.distributed.rpc")
    assert observed.KNOWN_PRESENT is True
    monkeypatch.delitem(sys.modules, "dgl.distributed.rpc")
    spec = importlib.util.spec_from_file_location("dgl.distributed", folder / "__init__.py")
    assert spec is not None
    assert spec.loader is not None
    shim = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "dgl.distributed", shim)
    spec.loader.exec_module(shim)

    class DistNodeDataLoader(shim.DistDataLoader):
        def __init__(self):
            pytest.fail("disabled subclass constructor reached scientific code")

    class DistEdgeDataLoader(shim.DistDataLoader):
        pass

    parent.distributed = shim
    parent.__version__ = runtime.RUNTIME_VERSION
    parent.dataloading = SimpleNamespace(
        DistNodeDataLoader=DistNodeDataLoader, DistEdgeDataLoader=DistEdgeDataLoader
    )
    parent.list_global_func_names = lambda: ["distributed.rpc._CAPI_DGLRPCRecvRPCMessage"]
    result = runtime.verify_disabled_distributed(parent)
    assert len(result["blocked_module_imports"]) == 28
    assert result["rejected_constructors"] == [
        "DistGraph",
        "DistDataLoader",
        "DistNodeDataLoader",
        "DistEdgeDataLoader",
    ]
    assert result["native_rpc_registry_present"] is True
    parent.list_global_func_names = lambda: []
    with pytest.raises(RuntimeError, match="native inventory"):
        runtime.verify_disabled_distributed(parent)

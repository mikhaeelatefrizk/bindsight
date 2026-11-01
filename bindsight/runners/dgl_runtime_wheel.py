# SPDX-License-Identifier: AGPL-3.0-or-later
"""Remove unused distributed Python RPC from one authenticated DGL wheel.

This downstream distribution preserves local graph code and native libraries.
Native RPC symbols and unrelated local-file deserializers remain; this is a
specific remediation of GHSA-3x5x-fw77-g54c, not a general security guarantee.
"""

from __future__ import annotations

import base64
import csv
import hashlib
import importlib
import importlib.metadata
import importlib.util
import io
import json
import marshal
import os
import stat
import sys
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

UPSTREAM_VERSION = "1.0.2+cu118"
RUNTIME_VERSION = "1.0.2+cu118.bindsight.rpcoff1"
UPSTREAM_URL = (
    "https://data.dgl.ai/wheels/cu118/dgl-1.0.2%2Bcu118-cp311-cp311-manylinux1_x86_64.whl"
)
UPSTREAM_BYTES = 265620048
UPSTREAM_SHA256 = "84c6c705a01692a7c36038581a54c1b04a6cd3ce86d20f1607695aa61d9edd3b"
WHEEL_TAG = "cp311-cp311-manylinux1_x86_64"
ADVISORY = "GHSA-3x5x-fw77-g54c"
# Set from the independently inspected deterministic build, never from a cache.
PATCHED_SHA256 = "e3698014ff1d33cfc5ba8b4e23ea9b4d16b45d2f998edb7ecb714071bc00f01e"
LIBINFO_SHA256 = "1f2789c82fa7cdb409bd34112c798399384ea6877e423f9b666790e879b83587"
METADATA_SHA256 = "111da64dee498f95f69e0108dd85575d5c0a197cdaf80155e6cce9cd4dd1432b"
NATIVE_SHA256 = {
    "dgl/_ffi/_cy3/core.cpython-311-x86_64-linux-gnu.so": "73f6dbc2e92cc1d679696fd41e1f86770bad57a804d13a7a37d50ff0890d203a",
    "dgl/dgl_sparse/libdgl_sparse_pytorch_1.12.0.so": "f0668ad0fcb43b842ad6bb227e3e710ca96644d6be6b338fbb4e46924edf7eac",
    "dgl/dgl_sparse/libdgl_sparse_pytorch_1.12.1.so": "ad45e336112c1afae6a29ff2b660c36aed9b044243e94c9cdbcc1f8ec12238a3",
    "dgl/dgl_sparse/libdgl_sparse_pytorch_1.13.0.so": "c34d1ac8b1093cd5915d6415b3532586a87a7a706b74287071f8ca138293302e",
    "dgl/dgl_sparse/libdgl_sparse_pytorch_1.13.1.so": "ea26205aefee9e04c75f3fce9548f22afd7d3c7c4e4a5eaf5af89d063e22a006",
    "dgl/dgl_sparse/libdgl_sparse_pytorch_2.0.0.so": "81343618960c8c19106ef80298fd7a1a207152d82e5807e70a9ef42bada84e98",
    "dgl/libdgl.so": "4a5c6b896b3f1c370d261341f1953261edaac0f8110a697f675e0bb296713147",
    "dgl/tensoradapter/pytorch/libtensoradapter_pytorch_1.12.0.so": "036cb4188c526c4948472cdc5882487b429e3407ffae111f52d48aa3cc45c80c",
    "dgl/tensoradapter/pytorch/libtensoradapter_pytorch_1.12.1.so": "d6eb52333dd8eeb332c63fee5b0394023bd1ab772ddee8615105426a40c9890b",
    "dgl/tensoradapter/pytorch/libtensoradapter_pytorch_1.13.0.so": "20adff497b27f53b1a7ed1ea83167970637ff5d92faf14399da827cae8528a7e",
    "dgl/tensoradapter/pytorch/libtensoradapter_pytorch_1.13.1.so": "4b7c2c66dd7f25837ba09e7097d092fb6a22e3c3e6cbe640867ad9535ba0bc7d",
    "dgl/tensoradapter/pytorch/libtensoradapter_pytorch_2.0.0.so": "c52c72851f16c045611ed25e458f9b7694bbb40c2a622bac0230917ef3ea446d",
}
DISTRIBUTED_PATHS = tuple(
    "dgl/distributed/" + name
    for name in (
        "__init__.py",
        "constants.py",
        "dist_context.py",
        "dist_dataloader.py",
        "dist_graph.py",
        "dist_tensor.py",
        "graph_partition_book.py",
        "graph_services.py",
        "id_map.py",
        "kvstore.py",
        "partition.py",
        "role.py",
        "rpc.py",
        "rpc_client.py",
        "rpc_server.py",
        "server_state.py",
        "shared_mem_utils.py",
        "standalone_kvstore.py",
        "nn/__init__.py",
        "nn/mxnet/__init__.py",
        "nn/pytorch/__init__.py",
        "nn/pytorch/sparse_emb.py",
        "nn/tensorflow/__init__.py",
        "optim/__init__.py",
        "optim/mxnet/__init__.py",
        "optim/pytorch/__init__.py",
        "optim/pytorch/sparse_optim.py",
        "optim/pytorch/utils.py",
        "optim/tensorflow/__init__.py",
    )
)
SHIM = b'''# SPDX-License-Identifier: Apache-2.0
"""Bindsight modification: distributed DGL is removed (GHSA-3x5x-fw77-g54c).

Only import-compatibility classes for unchanged local dataloading remain.
The original DGL Apache-2.0 license accompanies this downstream distribution.
"""

__all__ = ["DistGraph", "DistDataLoader"]
__path__ = ()


class DistributedDisabledError(RuntimeError):
    """The downstream local-only DGL distribution excludes this operation."""


class _DisabledDistributed:
    def __new__(cls, *args, **kwargs):
        raise DistributedDisabledError(
            "Distributed DGL was removed from this Bindsight build "
            "(GHSA-3x5x-fw77-g54c); use local graph operations."
        )


class DistGraph(_DisabledDistributed):
    pass


class DistDataLoader(_DisabledDistributed):
    pass
'''
SHIM_SHA256 = hashlib.sha256(SHIM).hexdigest()
VERSION_LINE = f'__version__ = "{UPSTREAM_VERSION}"'.encode()
PATCHED_VERSION_LINE = (
    "# Bindsight downstream modification: version label for distributed RPC removal.\n"
    f'__version__ = "{RUNTIME_VERSION}"'
).encode()


def _regular(path: Path) -> os.stat_result:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
        raise ValueError("DGL artifact must be a regular file, never a link")
    return info


def _digest(path: Path) -> str:
    _regular(path)
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _directory(path: Path) -> None:
    if path.is_symlink() or (path.exists() and not path.is_dir()):
        raise ValueError("DGL cache must be a real directory")
    path.mkdir(parents=True, exist_ok=True)


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    info.compress_type = zipfile.ZIP_STORED
    return info


def _build_verified_wheel(source_path: Path, destination: Path) -> dict[str, Any]:
    """Stream a fixed input into deterministic packaging; preserve retained bytes."""
    if _regular(source_path).st_size != UPSTREAM_BYTES or _digest(source_path) != UPSTREAM_SHA256:
        raise ValueError("DGL upstream wheel differs from its reviewed size and SHA256")
    if destination.exists() or destination.is_symlink():
        raise ValueError("DGL build destination must be new")
    old_info = f"dgl-{UPSTREAM_VERSION}.dist-info/"
    new_info = f"dgl-{RUNTIME_VERSION}.dist-info/"
    removed = sorted(set(DISTRIBUTED_PATHS) - {"dgl/distributed/__init__.py"})
    originals: dict[str, str] = {}
    final: dict[str, dict[str, Any]] = {}
    changed: dict[str, dict[str, str]] = {}
    try:
        with zipfile.ZipFile(source_path) as source, zipfile.ZipFile(destination, "w") as output:
            names = source.namelist()
            if (
                len(names) != len(set(names))
                or set(n for n in names if n.startswith("dgl/distributed/"))
                != set(DISTRIBUTED_PATHS)
                or any(
                    not n.startswith(("dgl/", old_info))
                    or ".." in n.split("/")
                    or "\\" in n
                    or n.endswith(".pyc")
                    for n in names
                )
                or sum(i.file_size for i in source.infolist()) > 2 * 2**30
            ):
                raise ValueError("DGL upstream wheel member inventory differs from review")
            for name in sorted(names):
                if name in removed or name == old_info + "RECORD":
                    continue
                target = name.replace(old_info, new_info, 1)
                replacement = None
                if name in {
                    "dgl/distributed/__init__.py",
                    "dgl/_ffi/libinfo.py",
                    old_info + "METADATA",
                }:
                    original = source.read(name)
                    originals[name] = hashlib.sha256(original).hexdigest()
                    if name == "dgl/distributed/__init__.py":
                        replacement = SHIM
                    elif name == "dgl/_ffi/libinfo.py":
                        if original.count(VERSION_LINE) != 1:
                            raise ValueError("DGL version source differs from review")
                        replacement = original.replace(VERSION_LINE, PATCHED_VERSION_LINE)
                    else:
                        old = f"Version: {UPSTREAM_VERSION}\n".encode()
                        if original.count(old) != 1:
                            raise ValueError("DGL package version metadata differs from review")
                        replacement = original.replace(
                            old, f"Version: {RUNTIME_VERSION}\n".encode()
                        )
                digest = hashlib.sha256()
                size = 0
                with output.open(_zip_info(target), "w", force_zip64=True) as writer:
                    if replacement is not None:
                        writer.write(replacement)
                        digest.update(replacement)
                        size = len(replacement)
                    else:
                        with source.open(name) as reader:
                            while chunk := reader.read(2**20):
                                writer.write(chunk)
                                digest.update(chunk)
                                size += len(chunk)
                        originals[name] = digest.hexdigest()
                final[target] = {"sha256": digest.hexdigest(), "bytes": size}
                if replacement is not None:
                    changed[name] = {
                        "original_sha256": originals[name],
                        "patched_sha256": digest.hexdigest(),
                    }
            rows = io.StringIO(newline="")
            record_writer = csv.writer(rows, lineterminator="\n")
            for name, item in sorted(final.items()):
                encoded = (
                    base64.urlsafe_b64encode(bytes.fromhex(item["sha256"])).rstrip(b"=").decode()
                )
                record_writer.writerow([name, "sha256=" + encoded, item["bytes"]])
            record_writer.writerow([new_info + "RECORD", "", ""])
            output.writestr(_zip_info(new_info + "RECORD"), rows.getvalue().encode())
        # Inspect the serialized product; do not trust the input-to-output loop alone.
        with zipfile.ZipFile(destination) as product:
            if set(product.namelist()) != set(final) | {new_info + "RECORD"}:
                raise RuntimeError("DGL downstream member inventory differs")
            for name, expected in final.items():
                with product.open(name) as stream:
                    digest = hashlib.sha256()
                    while chunk := stream.read(2**20):
                        digest.update(chunk)
                    actual = digest.hexdigest()
                if (
                    actual != expected["sha256"]
                    or product.getinfo(name).file_size != expected["bytes"]
                ):
                    raise RuntimeError("DGL downstream serialization changed payload bytes")
        unchanged = {
            name: item["sha256"]
            for name, item in final.items()
            if name.startswith("dgl/") and name not in changed
        }
        return {
            "schema": "bindsight-dgl-rpc-removal/1",
            "advisory": ADVISORY,
            "upstream_version": UPSTREAM_VERSION,
            "installed_version": RUNTIME_VERSION,
            "upstream_url": UPSTREAM_URL,
            "upstream_bytes": UPSTREAM_BYTES,
            "upstream_sha256": UPSTREAM_SHA256,
            "patched_sha256": _digest(destination),
            "patched_bytes": destination.stat().st_size,
            "removed_paths": removed,
            "modified_files": changed,
            "unchanged_package_files": unchanged,
            "unchanged_native_files": {n: h for n, h in unchanged.items() if n.endswith(".so")},
            "python_rpc_implementation": "removed",
            "native_rpc_code": "present",
            "scope": "Distributed Python implementation removed; compatibility shim, version metadata and RECORD changed. Retained local graph and native payload bytes unchanged; native RPC and unrelated local-file deserializers remain.",
        }
    except BaseException:
        destination.unlink(missing_ok=True)
        raise


def prepare_dgl_runtime_wheel(directory: Path) -> tuple[Path, dict[str, Any]]:
    """Authenticate upstream bytes and install only the reviewed local artifact."""
    _directory(directory)
    source = directory / f"dgl-{UPSTREAM_VERSION}-{WHEEL_TAG}.whl"
    if source.is_symlink():
        raise ValueError("DGL upstream cache must not be a link")
    if not source.exists():
        temporary = source.with_suffix(".download")
        if temporary.exists() or temporary.is_symlink():
            raise ValueError("Unexpected DGL download staging file")
        try:
            with (
                urllib.request.urlopen(UPSTREAM_URL, timeout=45) as response,
                temporary.open("xb") as output,
            ):
                total = 0
                while chunk := response.read(min(2**20, UPSTREAM_BYTES + 1 - total)):
                    total += len(chunk)
                    if total > UPSTREAM_BYTES:
                        raise ValueError("DGL download exceeds reviewed size")
                    output.write(chunk)
            if total != UPSTREAM_BYTES or _digest(temporary) != UPSTREAM_SHA256:
                raise ValueError("DGL download failed integrity verification")
            temporary.replace(source)
        finally:
            temporary.unlink(missing_ok=True)
    destination = directory / f"dgl-{RUNTIME_VERSION}-{WHEEL_TAG}.whl"
    temporary = directory / "dgl-rpc-removal.build.whl"
    if temporary.exists() or temporary.is_symlink():
        raise ValueError("Unexpected DGL build staging file")
    receipt = _build_verified_wheel(source, temporary)
    try:
        if receipt["patched_sha256"] != PATCHED_SHA256:
            raise ValueError("DGL downstream artifact differs from its reviewed SHA256")
        if destination.exists():
            if (
                _regular(destination).st_size != receipt["patched_bytes"]
                or _digest(destination) != PATCHED_SHA256
            ):
                raise ValueError("Cached DGL downstream wheel failed integrity verification")
        elif destination.is_symlink():
            raise ValueError("DGL downstream destination must not be a link")
        else:
            temporary.replace(destination)
        evidence = directory / "dgl-rpc-removal.json"
        if evidence.is_symlink():
            raise ValueError("DGL receipt must not be a link")
        evidence.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8", newline="\n")
        return destination, receipt
    finally:
        temporary.unlink(missing_ok=True)


def verify_installed_dgl() -> dict[str, Any]:
    """Check installed identity before importing DGL, including stale code files."""
    distribution = importlib.metadata.distribution("dgl")
    if distribution.version != RUNTIME_VERSION:
        raise RuntimeError("DGL is not the reviewed downstream RPC-removal build")
    root = Path(str(distribution.locate_file("dgl")))
    distributed = root / "distributed"
    if root.is_symlink() or distributed.is_symlink() or not distributed.is_dir():
        raise RuntimeError("DGL distributed package path is not an owned real directory")
    shim = distributed / "__init__.py"
    if _digest(shim) != SHIM_SHA256:
        raise RuntimeError("DGL distributed compatibility shim differs from review")
    caches = 0
    for path in distributed.rglob("*"):
        relative = path.relative_to(distributed).as_posix()
        if path.is_symlink():
            raise RuntimeError("DGL distributed package contains an unexpected link")
        if path.is_dir():
            if relative != "__pycache__":
                raise RuntimeError("Stale distributed DGL directory remains installed")
            continue
        if relative == "__init__.py":
            continue
        allowed = {
            f"__pycache__/__init__.{sys.implementation.cache_tag}"
            + (f".opt-{level}" if level else "")
            + ".pyc": level
            for level in (0, 1, 2)
        }
        if relative not in allowed or _regular(path).st_size > 2**20:
            raise RuntimeError("Stale or extraneous distributed DGL file remains installed")
        code = compile(SHIM, str(shim), "exec", dont_inherit=True, optimize=allowed[relative])
        expected = marshal.dumps(code)
        # Compare bytes; never unmarshal or execute an untrusted cache payload.
        cached = path.read_bytes()
        if (
            cached[:4] != importlib.util.MAGIC_NUMBER
            or int.from_bytes(cached[4:8], "little") not in {0, 1, 3}
            or cached[16:] != expected
        ):
            raise RuntimeError("DGL distributed bytecode differs from reviewed shim source")
        caches += 1
    if _digest(root / "_ffi/libinfo.py") != LIBINFO_SHA256:
        raise RuntimeError("DGL version source differs from the reviewed distribution")
    metadata = Path(str(distribution.locate_file(f"dgl-{RUNTIME_VERSION}.dist-info/METADATA")))
    if _digest(metadata) != METADATA_SHA256:
        raise RuntimeError("DGL metadata differs from the reviewed distribution")
    natives = {}
    if not NATIVE_SHA256:
        raise RuntimeError("DGL native payload expectations are missing")
    for name, expected_hash in NATIVE_SHA256.items():
        actual_hash = _digest(root.parent / name)
        if actual_hash != expected_hash:
            raise RuntimeError("DGL native payload differs from authenticated upstream")
        natives[name] = actual_hash
    return {
        "installed_version": RUNTIME_VERSION,
        "shim_sha256": SHIM_SHA256,
        "source_derived_bytecode_files": caches,
        "native_sha256": natives,
        "python_rpc_implementation": "removed",
        "native_rpc_code": "present",
    }


def verify_disabled_distributed(dgl: Any) -> dict[str, Any]:
    """Exercise expected unavailable APIs; unexpected errors are not suppressed."""
    module = dgl.distributed
    expected_names = {
        "DistGraph",
        "DistDataLoader",
        "DistributedDisabledError",
        "_DisabledDistributed",
    }
    if {n for n in vars(module) if not n.startswith("__")} != expected_names:
        raise RuntimeError("Unexpected DGL distributed compatibility namespace")
    if module.__path__ != () or dgl.__version__ != RUNTIME_VERSION:
        raise RuntimeError("DGL distributed search path or version differs")
    blocked = []
    for name in DISTRIBUTED_PATHS:
        if name == "dgl/distributed/__init__.py":
            continue
        module_name = name.removesuffix(".py").replace("/", ".").removesuffix(".__init__")
        try:
            importlib.import_module(module_name)
        except ModuleNotFoundError as error:
            if error.name not in {
                module_name,
                module_name.rsplit(".", 1)[0],
                "dgl.distributed.nn",
                "dgl.distributed.optim",
            }:
                raise RuntimeError(
                    "Unexpected dependency failure during DGL removal check"
                ) from error
            blocked.append(module_name)
        else:
            raise RuntimeError("Removed DGL distributed implementation is importable")
    rejected = []
    for cls in (
        module.DistGraph,
        module.DistDataLoader,
        dgl.dataloading.DistNodeDataLoader,
        dgl.dataloading.DistEdgeDataLoader,
    ):
        try:
            cls()
        except module.DistributedDisabledError as error:
            if ADVISORY not in str(error):
                raise RuntimeError(
                    "DGL compatibility stub lacks explicit remediation identity"
                ) from error
            rejected.append(cls.__name__)
        else:
            raise RuntimeError("Distributed DGL constructor unexpectedly succeeded")
    if any(n.startswith("dgl.distributed.") for n in sys.modules):
        raise RuntimeError("A removed DGL distributed module was loaded")
    native_present = "distributed.rpc._CAPI_DGLRPCRecvRPCMessage" in dgl.list_global_func_names()
    if not native_present:
        raise RuntimeError("DGL native inventory differs from the reviewed retained library")
    return {
        "blocked_module_imports": sorted(set(blocked)),
        "rejected_constructors": rejected,
        "unexpected_distributed_modules": [],
        "native_rpc_registry_present": native_present,
    }


if __name__ == "__main__":
    # The managed se3-python wrapper runs this before every Python invocation,
    # including reuse of an existing environment. No DGL/native import occurs.
    verify_installed_dgl()

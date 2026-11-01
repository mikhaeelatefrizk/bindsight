# SPDX-License-Identifier: AGPL-3.0-or-later
"""Restricted loading of the two authenticated upstream Boltz checkpoints.

The publisher checkpoints contain OmegaConf metadata. Allow only their measured
types, while keeping PyTorch's restricted unpickler enabled. This adapter belongs
to the short-lived, single prediction driver; PyTorch's allowlist is process-global
and is not a boundary for unrelated concurrent checkpoint loads.
"""

from __future__ import annotations

import hashlib
import inspect
import os
import stat
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from importlib import import_module
from importlib.metadata import version
from pathlib import Path
from typing import Any

from bindsight.runners.boltz_assets import ASSETS, AssetPin, _no_symlink
from bindsight.runners.boltz_runtime_wheel import UPSTREAM_MAIN_SHA256

_SOURCE_HASHES = {
    "boltz.model.models.boltz2": "c14592dc0bce81fb7e62872605c4cfe70ccfecc9a8d592fe610a51808c879bc2",
    "pytorch_lightning.core.module": "ba5461af71728704315b9fd5beef370e8cf9335ce70f78b6215e93a3ddaca9ff",
    "pytorch_lightning.core.saving": "2ccf5ae904f3ee8b04e7e2d716f066a7d7da4f10b8e6db94055543c757f74619",
    "lightning_fabric.utilities.cloud_io": "718f7f303262b7e9587f6ba1dd081620d7366774488a5622d0bbec56442654b8",
    "pytorch_lightning.utilities.migration.utils": "3bbd9f2297bc4c9e7364705072d81e14ca742f4029a5db66bad9d4686516093b",
    "pytorch_lightning.utilities.model_helpers": "aa2f389e8f1f753e416d7996f68dd1525308e827acb2b3f3eb8549ad5a64edb1",
}
_COMMON_GLOBALS = frozenset(
    {
        "builtins.dict",
        "collections.defaultdict",
        "omegaconf.base.ContainerMetadata",
        "omegaconf.base.Metadata",
        "omegaconf.dictconfig.DictConfig",
        "omegaconf.nodes.AnyNode",
        "typing.Any",
    }
)
CHECKPOINT_GLOBALS = {
    "boltz2_conf.ckpt": _COMMON_GLOBALS
    | {"builtins.int", "builtins.list", "omegaconf.listconfig.ListConfig"},
    "boltz2_aff.ckpt": _COMMON_GLOBALS,
}
_MISSING = object()
_LOAD_LOCK = threading.Lock()


def _verify_source(module: Any, expected: str) -> None:
    source = getattr(module, "__file__", None)
    if not source or hashlib.sha256(Path(source).read_bytes()).hexdigest() != expected:
        raise RuntimeError("Checkpoint compatibility requires the inspected upstream source")


def _verify_runtime(boltz_main: Any, torch: Any) -> tuple[Any, Any]:
    """Guard both the original Boltz calls and Lightning's IO/restricted-load path."""
    _verify_source(boltz_main, UPSTREAM_MAIN_SHA256)
    for name, digest in _SOURCE_HASHES.items():
        _verify_source(import_module(name), digest)
    if (
        version("pytorch-lightning") != "2.6.6"
        or version("omegaconf") != "2.3.1"
        or str(torch.__version__).split("+", 1)[0] != "2.14.1"
    ):
        raise RuntimeError("Checkpoint compatibility requires the inspected runtime versions")
    model = boltz_main.Boltz2
    if model is not import_module("boltz.model.models.boltz2").Boltz2:
        raise RuntimeError("Unexpected Boltz checkpoint model class")
    lightning = import_module("pytorch_lightning.core.module").LightningModule
    descriptor = vars(lightning).get("load_from_checkpoint")
    loader = model.load_from_checkpoint
    if (
        "load_from_checkpoint" in vars(model)
        or type(descriptor).__name__ != "_restricted_classmethod_impl"
        or getattr(loader, "__func__", None) is not getattr(descriptor, "method", None)
        or getattr(loader, "__module__", None) != "pytorch_lightning.core.module"
        or getattr(loader, "__qualname__", None) != "LightningModule.load_from_checkpoint"
        or "weights_only" not in inspect.signature(loader).parameters
    ):
        raise RuntimeError("Unexpected Lightning checkpoint loader")
    return model, loader


def _fixed_globals() -> dict[str, Any]:
    # These explicit imports are never selected by names inside a checkpoint.
    import collections
    import typing

    omega = import_module("omegaconf")
    base = import_module("omegaconf.base")
    nodes = import_module("omegaconf.nodes")

    return {
        "builtins.dict": dict,
        "builtins.int": int,
        "builtins.list": list,
        "collections.defaultdict": collections.defaultdict,
        "omegaconf.base.ContainerMetadata": base.ContainerMetadata,
        "omegaconf.base.Metadata": base.Metadata,
        "omegaconf.dictconfig.DictConfig": omega.DictConfig,
        "omegaconf.listconfig.ListConfig": omega.ListConfig,
        "omegaconf.nodes.AnyNode": nodes.AnyNode,
        "typing.Any": typing.Any,
    }


def _authenticate(stream: Any, pin: AssetPin) -> os.stat_result:
    info = os.fstat(stream.fileno())
    if not stat.S_ISREG(info.st_mode) or info.st_size != pin["bytes"]:
        raise ValueError("Checkpoint does not match the publisher's pinned byte count")
    stream.seek(0)
    digest, remaining = hashlib.sha256(), pin["bytes"]
    while remaining:
        block = stream.read(min(1024 * 1024, remaining))
        if not block:
            raise ValueError("Publisher checkpoint is truncated")
        digest.update(block)
        remaining -= len(block)
    if stream.read(1) or digest.hexdigest() != pin["sha256"]:
        raise ValueError("Checkpoint does not match the publisher's pinned SHA256")
    after = os.fstat(stream.fileno())
    if _file_identity(after) != _file_identity(info):
        raise ValueError("Checkpoint changed during authentication")
    stream.seek(0)
    return after


def _file_identity(info: os.stat_result) -> tuple[int, int, int, int, int]:
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _load_checkpoint(loader: Any, torch: Any, checkpoint: Any, kwargs: dict[str, Any]) -> Any:
    if not isinstance(checkpoint, (str, Path)):
        raise ValueError("Only local publisher-pinned Boltz checkpoints are supported")
    path = Path(checkpoint)
    if path.name not in CHECKPOINT_GLOBALS:
        raise ValueError("Custom checkpoints cannot use the publisher metadata allowlist")
    if "weights_only" in kwargs and kwargs["weights_only"] is not True:
        raise ValueError("Boltz checkpoint loading requires weights_only=True")
    if kwargs.get("hparams_file") is not None:
        raise ValueError("External checkpoint hyperparameters are not supported")
    if kwargs.get("strict") is not True or kwargs.get("map_location") != "cpu":
        raise ValueError("Unexpected upstream Boltz checkpoint loading arguments")
    _no_symlink(path)
    pin = ASSETS[path.name]
    with path.open("rb", buffering=0) as stream:
        identity = _authenticate(stream, pin)
        serialization = torch.serialization
        before = list(serialization.get_safe_globals())
        try:
            # Prevent an ambient allowlist from hiding an unexpected pickle name.
            # Restore those exact objects below, including on BaseException exits.
            serialization.clear_safe_globals()
            found = set(serialization.get_unsafe_globals_in_checkpoint(stream))
            if found != CHECKPOINT_GLOBALS[path.name]:
                raise ValueError("Publisher checkpoint has unexpected serialized metadata types")
            stream.seek(0)
            allowed = _fixed_globals()
            selected = [allowed[name] for name in sorted(found)]
            print(f"bindsight: restricted checkpoint load begin ({path.name})", flush=True)
            with serialization.safe_globals(selected):
                result = loader(stream, **{**kwargs, "weights_only": True})
            after = _authenticate(stream, pin)
            if _file_identity(after) != _file_identity(identity):
                raise ValueError("Checkpoint changed during loading")
            print(f"bindsight: restricted checkpoint load complete ({path.name})", flush=True)
            return result
        finally:
            serialization.clear_safe_globals()
            serialization.add_safe_globals(before)


@contextmanager
def verified_checkpoint_loading(boltz_main: Any, torch: Any) -> Iterator[None]:
    """Temporarily adapt only Boltz2's loader; the model files stay untouched."""
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError("Restricted Boltz checkpoint loading requires the driver main thread")
    model, original = _verify_runtime(boltz_main, torch)
    descriptor = vars(model).get("load_from_checkpoint", _MISSING)

    def load(cls: Any, checkpoint_path: Any, *args: Any, **kwargs: Any) -> Any:
        if cls is not model or args or threading.current_thread() is not threading.main_thread():
            raise ValueError("Unexpected Boltz checkpoint call shape")
        if not _LOAD_LOCK.acquire(blocking=False):
            raise RuntimeError("Recursive or concurrent checkpoint loading is unsupported")
        try:
            return _load_checkpoint(original, torch, checkpoint_path, kwargs)
        finally:
            _LOAD_LOCK.release()

    model.load_from_checkpoint = classmethod(load)
    try:
        yield
    finally:
        if descriptor is _MISSING:
            delattr(model, "load_from_checkpoint")
        else:
            model.load_from_checkpoint = descriptor

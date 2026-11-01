"""Publisher identity and restricted-loader boundaries without model downloads."""

from __future__ import annotations

import functools
import hashlib
import inspect
import io
import os
import random
import threading
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from bindsight.runners import boltz_checkpoint as checkpoint


class FakeSerialization:
    def __init__(self, found: set[str], baseline: list[Any]) -> None:
        self.found = found
        self.globals = set(baseline)
        self.inspected: list[Any] = []

    def get_safe_globals(self) -> list[Any]:
        return list(self.globals)

    def clear_safe_globals(self) -> None:
        self.globals.clear()

    def add_safe_globals(self, values: list[Any]) -> None:
        self.globals.update(values)

    def get_unsafe_globals_in_checkpoint(self, stream: Any) -> set[str]:
        assert not self.globals  # Ambient entries cannot hide a pickle global.
        assert stream.tell() == 0
        stream.read(3)
        self.inspected.append(stream)
        return self.found

    @contextmanager
    def safe_globals(self, values: list[Any]) -> Any:
        self.globals.update(values)
        try:
            yield
        finally:
            self.globals.difference_update(values)


@pytest.fixture
def setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    body = b"small authenticated fixture, never deserialized"
    paths = {}
    pins = {}
    for name in checkpoint.CHECKPOINT_GLOBALS:
        path = tmp_path / name
        path.write_bytes(body)
        paths[name] = path
        pins[name] = {"bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}
    allowed = {name: object() for name in checkpoint.CHECKPOINT_GLOBALS["boltz2_conf.ckpt"]}
    alias = (object(), "prior.alias")
    baseline = [allowed["builtins.dict"], object(), alias]
    serial = FakeSerialization(set(checkpoint.CHECKPOINT_GLOBALS["boltz2_conf.ckpt"]), baseline)
    torch = SimpleNamespace(serialization=serial)
    calls = []
    result = object()

    class Base:
        @classmethod
        def load_from_checkpoint(cls: Any, stream: Any, **kwargs: Any) -> Any:
            assert cls is Model
            assert stream is serial.inspected[-1]
            assert stream.tell() == 0
            assert stream.read() == body
            assert serial.globals == {allowed[name] for name in serial.found}
            calls.append((stream, kwargs))
            return result

    class Model(Base):
        pass

    module = SimpleNamespace(Boltz2=Model)
    original = Model.load_from_checkpoint
    monkeypatch.setattr(checkpoint, "ASSETS", pins)
    monkeypatch.setattr(checkpoint, "_fixed_globals", lambda: allowed)
    monkeypatch.setattr(checkpoint, "_verify_runtime", lambda *args: (Model, original))
    return SimpleNamespace(
        module=module,
        model=Model,
        original=original,
        torch=torch,
        serial=serial,
        paths=paths,
        body=body,
        baseline=set(baseline),
        calls=calls,
        result=result,
    )


def _load(setup: Any, **kwargs: Any) -> Any:
    return setup.model.load_from_checkpoint(
        setup.paths["boltz2_conf.ckpt"], **{"strict": True, "map_location": "cpu", **kwargs}
    )


@pytest.mark.parametrize("name", list(checkpoint.CHECKPOINT_GLOBALS))
def test_authenticated_load_uses_same_handle_exact_globals_and_restricted_mode(
    setup: Any, name: str
) -> None:
    setup.serial.found = set(checkpoint.CHECKPOINT_GLOBALS[name])
    before_rng = random.getstate()
    kwargs = {
        "strict": True,
        "map_location": "cpu",
        "predict_args": {"sampling_steps": 200},
        "ema": False,
    }
    with checkpoint.verified_checkpoint_loading(setup.module, setup.torch):
        assert setup.model.load_from_checkpoint(setup.paths[name], **kwargs) is setup.result
        assert setup.calls[0][1] == {**kwargs, "weights_only": True}
        assert setup.serial.globals == setup.baseline
    assert random.getstate() == before_rng
    assert "load_from_checkpoint" not in vars(setup.model)
    assert setup.model.load_from_checkpoint.__func__ is setup.original.__func__
    assert setup.calls[0][0].closed


@pytest.mark.parametrize("error", [ValueError("load failed"), KeyboardInterrupt()])
def test_failure_restores_descriptor_and_exact_prior_global_objects(
    setup: Any, monkeypatch: pytest.MonkeyPatch, error: BaseException
) -> None:
    def fail(*args: Any, **kwargs: Any) -> None:
        raise error

    monkeypatch.setattr(checkpoint, "_verify_runtime", lambda *args: (setup.model, fail))
    with (
        pytest.raises(type(error)),
        checkpoint.verified_checkpoint_loading(setup.module, setup.torch),
    ):
        _load(setup)
    assert setup.serial.globals == setup.baseline
    assert "load_from_checkpoint" not in vars(setup.model)
    assert setup.serial.inspected[0].closed
    assert not checkpoint._LOAD_LOCK.locked()


@pytest.mark.parametrize("change", ["unexpected", "missing"])
def test_global_inventory_must_match_exact_asset_set(setup: Any, change: str) -> None:
    if change == "unexpected":
        setup.serial.found.add("untrusted.ArbitraryClass")
    else:
        setup.serial.found.remove("builtins.dict")
    with (
        checkpoint.verified_checkpoint_loading(setup.module, setup.torch),
        pytest.raises(ValueError, match="metadata types"),
    ):
        _load(setup)
    assert not setup.calls
    assert setup.serial.globals == setup.baseline


@pytest.mark.parametrize("change", ["truncate", "tamper", "grow"])
def test_modified_publisher_file_fails_before_global_inventory(setup: Any, change: str) -> None:
    path = setup.paths["boltz2_conf.ckpt"]
    data = (
        setup.body[:-1]
        if change == "truncate"
        else setup.body + b"!"
        if change == "grow"
        else b"X" + setup.body[1:]
    )
    path.write_bytes(data)
    with (
        checkpoint.verified_checkpoint_loading(setup.module, setup.torch),
        pytest.raises(ValueError, match="pinned"),
    ):
        _load(setup)
    assert not setup.calls
    assert not setup.serial.inspected
    assert setup.serial.globals == setup.baseline


@pytest.mark.parametrize(
    "kwargs",
    [
        {"weights_only": False},
        {"weights_only": None},
        {"hparams_file": "custom.yaml"},
        {"strict": False},
        {"map_location": "cuda"},
    ],
)
def test_unsafe_loading_arguments_are_rejected(setup: Any, kwargs: dict[str, Any]) -> None:
    with (
        checkpoint.verified_checkpoint_loading(setup.module, setup.torch),
        pytest.raises(ValueError, match=r"requires|not supported|Unexpected"),
    ):
        _load(setup, **kwargs)
    assert not setup.serial.inspected


@pytest.mark.parametrize(
    "path", [io.BytesIO(b"custom"), "custom.ckpt", "https://example.invalid/boltz2_conf.ckpt"]
)
def test_custom_checkpoint_input_cannot_borrow_allowlist(setup: Any, path: Any) -> None:
    with (
        checkpoint.verified_checkpoint_loading(setup.module, setup.torch),
        pytest.raises((ValueError, OSError)),
    ):
        setup.model.load_from_checkpoint(path, strict=True, map_location="cpu")
    assert not setup.serial.inspected


def test_changes_during_loading_are_detected_even_if_size_and_mtime_are_restored(
    setup: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = setup.paths["boltz2_conf.ckpt"]
    before = path.stat()

    def mutate(*args: Any, **kwargs: Any) -> object:
        path.write_bytes(b"X" + setup.body[1:])
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
        return object()

    monkeypatch.setattr(checkpoint, "_verify_runtime", lambda *args: (setup.model, mutate))
    with (
        checkpoint.verified_checkpoint_loading(setup.module, setup.torch),
        pytest.raises(ValueError, match="SHA256"),
    ):
        _load(setup)
    assert setup.serial.globals == setup.baseline


def test_reentrant_loading_fails_instead_of_deadlocking(
    setup: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        checkpoint, "_verify_runtime", lambda *args: (setup.model, lambda *a, **k: _load(setup))
    )
    with (
        checkpoint.verified_checkpoint_loading(setup.module, setup.torch),
        pytest.raises(RuntimeError, match="Recursive"),
    ):
        _load(setup)
    assert setup.serial.globals == setup.baseline
    assert not checkpoint._LOAD_LOCK.locked()


def test_background_thread_cannot_install_or_use_wrapper(setup: Any) -> None:
    errors = []

    def install() -> None:
        try:
            with checkpoint.verified_checkpoint_loading(setup.module, setup.torch):
                pass
        except RuntimeError as error:
            errors.append(str(error))

    thread = threading.Thread(target=install)
    thread.start()
    thread.join()
    assert errors
    assert "main thread" in errors[0]
    assert "load_from_checkpoint" not in vars(setup.model)


def test_linked_checkpoint_is_rejected(setup: Any, tmp_path: Path) -> None:
    directory = tmp_path / "linked"
    directory.mkdir()
    link = directory / "boltz2_conf.ckpt"
    try:
        link.symlink_to(setup.paths["boltz2_conf.ckpt"])
    except OSError:
        pytest.skip("Host does not permit creating test symlinks")
    with (
        checkpoint.verified_checkpoint_loading(setup.module, setup.torch),
        pytest.raises(ValueError, match="links"),
    ):
        setup.model.load_from_checkpoint(link, strict=True, map_location="cpu")
    assert not setup.serial.inspected


def test_source_guard_rejects_modified_or_missing_file(tmp_path: Path) -> None:
    source = tmp_path / "source.py"
    source.write_text("original", encoding="utf-8")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    checkpoint._verify_source(SimpleNamespace(__file__=str(source)), digest)
    source.write_text("changed", encoding="utf-8")
    for module in [SimpleNamespace(__file__=str(source)), SimpleNamespace()]:
        with pytest.raises(RuntimeError, match="inspected upstream source"):
            checkpoint._verify_source(module, digest)


@pytest.fixture
def guarded_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    # Preserve the important descriptor behavior from Lightning2.6.6
    # model_helpers.py118-133: class access returns a functools wrapper carrying
    # __func__ = descriptor.method, rather than a normal Python bound method.
    class _restricted_classmethod_impl(classmethod):
        def __init__(self, method: Any) -> None:
            super().__init__(method)
            self.method = method

        def __get__(self, instance: Any, cls: Any = None) -> Any:
            @functools.wraps(self.method)
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                return self.method(cls, *args, **kwargs)

            wrapper.__func__ = self.method
            return wrapper

    def load(cls: Any, path: Any, *, weights_only: bool | None = None, **kwargs: Any) -> None:
        pass

    load.__module__ = "pytorch_lightning.core.module"
    load.__qualname__ = "LightningModule.load_from_checkpoint"

    class LightningModule:
        load_from_checkpoint = _restricted_classmethod_impl(load)

    class Model(LightningModule):
        pass

    modules = {}
    hashes = {}
    for name in ["boltz.main", *checkpoint._SOURCE_HASHES]:
        source = tmp_path / (name + ".py")
        source.write_text(name, encoding="utf-8")
        modules[name] = SimpleNamespace(__file__=str(source))
        hashes[name] = hashlib.sha256(source.read_bytes()).hexdigest()
    modules["boltz.main"].Boltz2 = Model
    modules["boltz.model.models.boltz2"].Boltz2 = Model
    modules["pytorch_lightning.core.module"].LightningModule = LightningModule
    versions = {"pytorch-lightning": "2.6.6", "omegaconf": "2.3.1"}
    monkeypatch.setattr(checkpoint, "version", versions.__getitem__)
    monkeypatch.setattr(checkpoint, "import_module", modules.__getitem__)
    monkeypatch.setattr(checkpoint, "UPSTREAM_MAIN_SHA256", hashes.pop("boltz.main"))
    monkeypatch.setattr(checkpoint, "_SOURCE_HASHES", hashes)
    return SimpleNamespace(
        module=modules["boltz.main"],
        torch=SimpleNamespace(__version__="2.14.1+cu126"),
        modules=modules,
        model=Model,
        loader=load,
        versions=versions,
    )


def test_source_guard_accepts_inspected_descriptor_with_bundled_fabric(
    guarded_runtime: Any,
) -> None:
    model, loader = checkpoint._verify_runtime(guarded_runtime.module, guarded_runtime.torch)
    assert model is guarded_runtime.model
    assert loader.__func__ is guarded_runtime.loader
    assert not inspect.ismethod(loader)  # Actual Lightning descriptor shape.


@pytest.mark.parametrize("change", ["source", "version", "class", "descriptor", "signature"])
def test_runtime_guard_refuses_unknown_implementations(guarded_runtime: Any, change: str) -> None:
    runtime = guarded_runtime
    if change == "source":
        Path(runtime.modules["lightning_fabric.utilities.cloud_io"].__file__).write_text("changed")
    elif change == "version":
        runtime.versions["omegaconf"] = "uninspected"
    elif change == "class":
        runtime.module.Boltz2 = type("Other", (), {})
    elif change == "descriptor":
        runtime.model.load_from_checkpoint = classmethod(runtime.loader)
    else:
        runtime.loader.__signature__ = inspect.Signature([])
    with pytest.raises(RuntimeError, match=r"requires|Unexpected"):
        checkpoint._verify_runtime(runtime.module, runtime.torch)

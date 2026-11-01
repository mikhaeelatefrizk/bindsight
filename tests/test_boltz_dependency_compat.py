"""The dependency-only local distribution must retain the audited model CLI."""

import hashlib
import sys
from contextlib import contextmanager, nullcontext
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from bindsight.runners import boltz_compat
from bindsight.runners.boltz_runtime_wheel import RUNTIME_VERSION


def _predict(model="boltz2"):
    return dict(precision=32 if model == "boltz1" else "bf16-mixed")


def _module(path):
    return SimpleNamespace(
        __file__=str(path), predict=SimpleNamespace(callback=_predict), Trainer=Mock(), cli=Mock()
    )


def _torch():
    return SimpleNamespace(
        cuda=SimpleNamespace(
            is_available=lambda: True,
            device_count=lambda: 1,
            get_device_capability=lambda _: (7, 5),
        )
    )


def test_dependency_variant_uses_only_unchanged_verified_cli(tmp_path, monkeypatch):
    source = tmp_path / "main.py"
    source.write_bytes(b"reviewed implementation")
    monkeypatch.setattr(
        boltz_compat, "UPSTREAM_MAIN_SHA256", hashlib.sha256(source.read_bytes()).hexdigest()
    )
    module = _module(source)
    assert boltz_compat.configure_precision(module, _torch(), boltz_version=RUNTIME_VERSION) == "32"
    source.write_bytes(b"changed implementation")
    with pytest.raises(RuntimeError, match="differs"):
        boltz_compat.configure_precision(_module(source), _torch(), boltz_version=RUNTIME_VERSION)


def test_unknown_local_variant_is_not_accepted(tmp_path):
    with pytest.raises(RuntimeError, match="requires boltz"):
        boltz_compat.configure_precision(
            _module(tmp_path / "main.py"), _torch(), boltz_version="2.0.3+unknown.1"
        )


def test_precision_receipt_names_actual_distribution(monkeypatch, capsys, tmp_path):
    module = _module(tmp_path / "main.py")
    configure_msa = Mock()
    monkeypatch.setitem(sys.modules, "torch", _torch())
    monkeypatch.setattr(boltz_compat, "import_module", lambda _: module)
    monkeypatch.setattr(boltz_compat, "version", lambda _: RUNTIME_VERSION)
    monkeypatch.setattr(boltz_compat, "configure_precision", lambda *a, **kw: "32")
    monkeypatch.setattr(boltz_compat, "configure_msa", configure_msa)
    checkpoint_context = Mock(return_value=nullcontext())
    monkeypatch.setattr(boltz_compat, "verified_checkpoint_loading", checkpoint_context)
    assert boltz_compat.main(["predict", "input.yaml"]) == 0
    configure_msa.assert_called_once_with(module)
    assert f"Boltz {RUNTIME_VERSION} precision=32" in capsys.readouterr().out
    module.cli.assert_called_once_with(args=["predict", "input.yaml"])
    checkpoint_context.assert_called_once_with(module, sys.modules["torch"])


def test_actual_cli_download_hook_refuses_changed_cache_before_prediction(monkeypatch, tmp_path):
    module = _module(tmp_path / "main.py")
    configure_msa = Mock()
    original_download = Mock()
    module.download_boltz2 = original_download
    prediction = Mock()
    cache = tmp_path / "cache"

    def cli(**kwargs):
        module.download_boltz2(cache)
        prediction()

    verified_download = Mock(side_effect=ValueError("Boltz cache SHA256 mismatch"))
    module.cli = cli
    monkeypatch.setitem(sys.modules, "torch", _torch())
    monkeypatch.setattr(boltz_compat, "import_module", lambda _: module)
    monkeypatch.setattr(boltz_compat, "version", lambda _: RUNTIME_VERSION)
    monkeypatch.setattr(boltz_compat, "configure_precision", lambda *a, **kw: "32")
    monkeypatch.setattr(boltz_compat, "configure_msa", configure_msa)
    monkeypatch.setattr(boltz_compat, "verified_checkpoint_loading", lambda *args: nullcontext())
    monkeypatch.setattr(boltz_compat, "prepare_boltz_assets", verified_download)
    with pytest.raises(ValueError, match="SHA256 mismatch"):
        boltz_compat.main(["predict", "input.yaml"])
    configure_msa.assert_called_once_with(module)
    verified_download.assert_called_once_with(cache)
    original_download.assert_not_called()
    prediction.assert_not_called()


def test_checkpoint_guard_encloses_cli_and_cleans_up_on_failure(monkeypatch, tmp_path):
    module = _module(tmp_path / "main.py")
    events = []

    @contextmanager
    def guard(received_module, received_torch):
        assert received_module is module
        assert received_torch is sys.modules["torch"]
        events.append("enter")
        try:
            yield
        finally:
            events.append("exit")

    def cli(**kwargs):
        assert events == ["enter"]
        events.append("cli")
        raise RuntimeError("prediction failed")

    module.cli = cli
    monkeypatch.setitem(sys.modules, "torch", _torch())
    monkeypatch.setattr(boltz_compat, "import_module", lambda _: module)
    monkeypatch.setattr(boltz_compat, "version", lambda _: RUNTIME_VERSION)
    monkeypatch.setattr(boltz_compat, "configure_precision", lambda *a, **kw: "32")
    monkeypatch.setattr(boltz_compat, "configure_msa", lambda *a: None)
    monkeypatch.setattr(boltz_compat, "verified_checkpoint_loading", guard)
    with pytest.raises(RuntimeError, match="prediction failed"):
        boltz_compat.main(["predict", "input.yaml"])
    assert events == ["enter", "cli", "exit"]

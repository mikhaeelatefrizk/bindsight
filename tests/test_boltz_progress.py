# SPDX-License-Identifier: AGPL-3.0-or-later
"""Check additive PAE output and observational long-running diagnostics."""

import faulthandler
from pathlib import Path

import pytest

from bindsight.runners import boltz_compat, tools
from bindsight.runners.boltz_msa import MSABoundaryError, MSADeadlineExceeded


def test_prediction_explicitly_retains_pae_without_changing_sampling():
    command = tools.build_boltz_cmd(yaml_path=Path("input.yaml"), out_dir=Path("out"), seed=42)
    assert command.count("--write_full_pae") == 1
    assert "--use_msa_server" in command
    assert command[command.index("--seed") + 1] == "42"
    assert "--sampling_steps" not in command
    assert "--recycling_steps" not in command
    assert "--diffusion_samples" not in command


@pytest.mark.parametrize("fails", [False, True])
@pytest.mark.parametrize("enabled", [False, True])
def test_diagnostics_are_opt_in_and_cancel_on_success_or_failure(monkeypatch, fails, enabled):
    calls = []
    monkeypatch.setenv("BINDSIGHT_GPU_DIAGNOSTICS", "1" if enabled else "0")
    monkeypatch.setattr(faulthandler, "dump_traceback_later", lambda *a, **k: calls.append((a, k)))
    monkeypatch.setattr(faulthandler, "cancel_dump_traceback_later", lambda: calls.append("cancel"))
    arguments = ["predict", "input.yaml", "--seed", "42"]

    def predict(argv):
        assert argv is arguments
        if fails:
            raise RuntimeError("model failed")
        return 0

    monkeypatch.setattr(boltz_compat, "_predict", predict)
    if fails:
        with pytest.raises(RuntimeError, match="model failed"):
            boltz_compat.main(arguments)
    else:
        assert boltz_compat.main(arguments) == 0
    assert calls == ([((600,), {"repeat": True, "exit": False}), "cancel"] if enabled else [])


@pytest.mark.parametrize("error_class", [MSABoundaryError, MSADeadlineExceeded])
def test_msa_deadline_becomes_failure_only_outside_upstream_callback(monkeypatch, error_class):
    monkeypatch.delenv("BINDSIGHT_GPU_DIAGNOSTICS", raising=False)
    swallowed = []

    def upstream(argv):
        try:
            raise error_class("alignment boundary reached")
        except Exception:
            swallowed.append(True)  # Upstream normally catches invalid inputs.
        return 0

    monkeypatch.setattr(boltz_compat, "_predict", upstream)
    with pytest.raises(RuntimeError, match="alignment boundary reached"):
        boltz_compat.main(["predict", "input.yaml"])
    assert swallowed == []

"""Tests for the Kaggle split-env kernel builder + status mapping (CPU-only).

The GPU run itself can't be exercised without Kaggle, but the kernel *script* is
pure string assembly — assert it is valid Python, embeds the spec payload, sources
the pinned revisions from :mod:`bindsight.runners.tools`, and wires the two
micromamba envs the way :mod:`bindsight.runners.job_exec` expects. Also covers the
`KaggleRunner` status-enum mapping that an earlier version got wrong.
"""

from __future__ import annotations

import ast
import base64
from types import SimpleNamespace

from bindsight.runners import kaggle, kaggle_kernel, tools


def _payload() -> dict[str, str]:
    spec = b'{"target_uniprot": "P04626", "extra_params": {"designer": "rfdiff_mpnn"}}'
    pdb = b"ATOM      1  CA  MET A   1       0.0   0.0   0.0  1.0  0.0           C\n"
    return {
        "spec.json": base64.b64encode(spec).decode(),
        "target.pdb": base64.b64encode(pdb).decode(),
    }


def test_kernel_script_is_valid_python_and_embeds_payload() -> None:
    payload = _payload()
    src = kaggle_kernel.build_kernel_script(handle_id="abc123", payload=payload)
    ast.parse(src)  # must be syntactically valid Python
    # Payload is embedded verbatim (base64), to be decoded on the GPU.
    assert payload["spec.json"] in src
    assert payload["target.pdb"] in src
    assert "'abc123'" in src


def test_kernel_header_constants_are_valid_python_literals() -> None:
    """Execute the generated header — guards against JSON literals (null/true) that
    parse syntactically but raise NameError at runtime (an early bug)."""
    src = kaggle_kernel.build_kernel_script(handle_id="abc123", payload=_payload())
    header = src.split("\n\n", 1)[0]
    ns: dict[str, object] = {}
    exec(header, ns)  # must bind without NameError
    assert ns["HANDLE_ID"] == "abc123"
    assert ns["N_TRAJ_NOTE"] is None
    assert ns["RFDIFF_COMMIT"] == tools.RFDIFF_COMMIT
    assert isinstance(ns["PAYLOAD"], dict)


def test_kernel_script_sources_pins_from_tools() -> None:
    src = kaggle_kernel.build_kernel_script(handle_id="h", payload=_payload())
    # Single source of truth: the pins come from bindsight.runners.tools.
    assert tools.RFDIFF_COMMIT in src
    assert tools.PROTEINMPNN_COMMIT in src
    assert tools.BOLTZ_PIP in src
    for url in tools.RFDIFF_WEIGHTS.values():
        assert url in src
    # Split-env wiring the executor relies on.
    assert "BINDSIGHT_TOOLS_ROOT" in src
    assert "BINDSIGHT_DESIGN_PYTHON" in src
    assert "bindsight.runners.job_exec" in src
    assert "micromamba" in src
    # Both envs are built and the result is staged to the output volume.
    assert "envs/se3" in src
    assert "envs/boltz" in src
    assert "/kaggle/working/" in src


def test_kernel_metadata_is_gpu_internet_script_no_dataset() -> None:
    md = kaggle_kernel.build_kernel_metadata(username="someuser", slug="bindsight-x")
    assert md["id"] == "someuser/bindsight-x"
    assert md["enable_gpu"] is True
    assert md["enable_internet"] is True
    assert md["kernel_type"] == "script"
    assert md["dataset_sources"] == []  # payload is embedded, not a dataset


def test_status_name_and_state_mapping() -> None:
    # Real API shape: response.status is a KernelWorkerStatus enum.
    enum_complete = SimpleNamespace(name="COMPLETE")
    resp = SimpleNamespace(status=enum_complete, failureMessage=None)
    assert kaggle._status_name(resp) == "COMPLETE"
    assert kaggle._STATE_MAP["COMPLETE"] == "succeeded"
    assert kaggle._STATE_MAP["ERROR"] == "failed"
    assert kaggle._STATE_MAP["RUNNING"] == "running"
    # Dict fallback (older clients).
    assert kaggle._status_name({"status": "running"}) == "RUNNING"

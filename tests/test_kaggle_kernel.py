# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
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


def test_metadata_pins_the_t4_accelerator() -> None:
    """`enable_gpu` alone gets Kaggle's default P100, which cannot run the stack.

    Kaggle's own CLI docs warn the P100 is unusable with the default image because
    current PyTorch ships no Pascal kernels. Pinning `machine_shape` puts the
    hardware a published result was produced on under version control.
    """
    meta = kaggle_kernel.build_kernel_metadata(username="u", slug="run-1")
    assert meta["machine_shape"] == "NvidiaTeslaT4"
    assert meta["enable_gpu"] is True
    assert meta["enable_internet"] is True


def test_metadata_accelerator_is_overridable() -> None:
    meta = kaggle_kernel.build_kernel_metadata(
        username="u", slug="run-1", accelerator="NvidiaTeslaT4x2"
    )
    assert meta["machine_shape"] == "NvidiaTeslaT4x2"


def test_kernel_refuses_an_insufficient_gpu() -> None:
    """The kernel must fail fast rather than die hours in on the first CUDA op."""
    src = kaggle_kernel.build_kernel_script(handle_id="h", payload={"spec.json": "e30="})
    assert "compute_cap" in src
    assert "MIN_CC" in src
    # The failure has to name the fix, not just the symptom.
    assert "machine_shape" in src
    assert "NvidiaTeslaT4" in src


def test_kernel_reports_disk_and_gpu_at_every_stage() -> None:
    """Kaggle does not publish the scratch volume size, so it gets measured."""
    src = kaggle_kernel.build_kernel_script(handle_id="h", payload={"spec.json": "e30="})
    assert "def disk_report(" in src
    assert "def gpu_report(" in src
    # step() drives both, so every stage records what was available.
    body = src.split("def step(msg):", 1)[1].split("step(", 1)[0]
    assert "disk_report(msg)" in body
    assert "gpu_report(msg)" in body
    for volume in ("/kaggle/working", "/kaggle/temp", "/tmp"):
        assert volume in src


def test_kernel_still_forces_fp32_for_boltz() -> None:
    """bfloat16 needs sm_80+; the pinned T4 is sm_75, so the patch stays required."""
    src = kaggle_kernel.build_kernel_script(handle_id="h", payload={"spec.json": "e30="})
    assert "precision=32" in src
    assert "bf16-mixed" in src


# ---------------------------------------------------------------------------
# VRAM instrumentation: it promised a measurement and delivered a constant
# ---------------------------------------------------------------------------
def _extract(src: str, names: set[str]) -> dict[str, object]:
    """Exec just the named top-level defs/assignments from the kernel script.

    The kernel is a generated program, so its helpers cannot be imported. Pulling
    the relevant nodes out and running them is what lets the behaviour be tested
    rather than the text grepped.
    """
    import subprocess as real_subprocess

    tree = ast.parse(src)
    keep: list[ast.stmt] = []
    for node in tree.body:
        wanted_def = isinstance(node, ast.FunctionDef) and node.name in names
        wanted_assign = isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id in names for t in node.targets
        )
        if wanted_def or wanted_assign:
            keep.append(node)
    ns: dict[str, object] = {"subprocess": real_subprocess, "time": __import__("time")}
    exec(compile(ast.Module(body=keep, type_ignores=[]), "<kernel>", "exec"), ns)
    return ns


def test_the_kernel_samples_vram_in_the_background() -> None:
    """Between-stage sampling measured nothing, because the work had already exited.

    RFdiffusion and Boltz-2 run in subprocesses under separate micromamba
    environments. By the time a stage boundary is reached they have exited and
    released their memory, so a 3h49m design run reported 0 MiB at every single
    stage while plainly using the GPU. The docstring promised "every memory
    claim is a measurement"; the number was a constant.
    """
    src = kaggle_kernel.build_kernel_script(handle_id="t", payload=_payload())
    assert "threading.Thread(target=_vram_sampler" in src, "nothing samples during the work"
    assert "daemon=True" in src, "the sampler must not keep the kernel alive"
    assert "peak so far" in src, "gpu_report must report the high-water mark"
    # The sampler has to be running before the first stage boundary, or the
    # early stages report a peak that was never observed.
    assert src.index("threading.Thread(target=_vram_sampler") < src.index("def step(")


def test_the_vram_reader_parses_nvidia_smi_and_survives_its_absence(
    monkeypatch: object,
) -> None:
    ns = _extract(
        kaggle_kernel.build_kernel_script(handle_id="t", payload=_payload()),
        {"_vram_now", "_VRAM_PEAK"},
    )
    vram_now = ns["_vram_now"]

    class _Result:
        def __init__(self, returncode: int, stdout: str) -> None:
            self.returncode = returncode
            self.stdout = stdout

    calls: list[object] = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return _Result(0, "4321\n")

    ns["subprocess"] = SimpleNamespace(run=fake_run)
    assert vram_now() == 4321
    assert "--query-gpu=memory.used" in " ".join(calls[0])

    # A GPU-less machine, or a driver that answers with prose, must not crash
    # the run: the measurement is instrumentation, not the result.
    ns["subprocess"] = SimpleNamespace(run=lambda cmd, **kw: _Result(9, ""))
    assert vram_now() is None
    ns["subprocess"] = SimpleNamespace(run=lambda cmd, **kw: _Result(0, "[N/A]\n"))
    assert vram_now() is None


def test_the_peak_starts_at_zero_and_is_a_mutable_cell() -> None:
    """The sampler thread and gpu_report must see the same counter."""
    ns = _extract(
        kaggle_kernel.build_kernel_script(handle_id="t", payload=_payload()),
        {"_VRAM_PEAK"},
    )
    peak = ns["_VRAM_PEAK"]
    assert peak == [0]

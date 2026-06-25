# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the Colab runner: notebook construction + lifecycle."""

from __future__ import annotations

import json
import tarfile
from pathlib import Path

import pytest

from bindsight.runners.colab import ColabRunner


@pytest.fixture
def runner(tmp_path: Path) -> ColabRunner:
    return ColabRunner(notebooks_dir=tmp_path / "nb", designer="rfdiff_mpnn", gpu_type="T4")


def test_estimate_cost_t4_free(runner: ColabRunner) -> None:
    cost = runner.estimate_cost(spec_size=50)
    assert cost.usd_estimate == pytest.approx(0.0)
    assert cost.backend == "colab"
    assert cost.gpu_type == "T4"


def test_submit_writes_valid_notebook_json(runner: ColabRunner, tmp_path: Path) -> None:
    spec = tmp_path / "spec.json"
    spec.write_text('{"target_uniprot": "P04626", "epitope_residues": [10, 11, 12]}')
    results = tmp_path / "results"

    handle = runner.submit(spec, results_dir=results)
    nb_path = Path(handle.model_extra["notebook_path"])
    assert nb_path.exists()

    nb = json.loads(nb_path.read_text())
    assert nb["nbformat"] == 4
    assert nb["metadata"]["accelerator"] == "GPU"
    assert nb["metadata"]["colab"]["gpuType"] == "T4"
    # New design notebook: ~16 cells (markdown + code interleaved for the full
    # RFdiff + MPNN + Boltz-2 pipeline). Check the rough shape rather than exact
    # count so minor template tweaks don't break the test.
    assert len(nb["cells"]) >= 8
    code_cells = [c for c in nb["cells"] if c["cell_type"] == "code"]
    md_cells = [c for c in nb["cells"] if c["cell_type"] == "markdown"]
    assert len(code_cells) >= 4
    assert len(md_cells) >= 4
    # Real install commands + executor invocation are in there (not stubs).
    src = "\n".join("".join(c["source"]) for c in code_cells)
    assert "RFdiffusion" in src
    assert "ProteinMPNN" in src
    assert "boltz" in src.lower()
    assert "bindsight.runners.job_exec" in src


def test_submit_handles_missing_spec_file_gracefully(runner: ColabRunner, tmp_path: Path) -> None:
    """Submit should not fail if the spec file doesn't exist; embed an empty spec."""
    handle = runner.submit(tmp_path / "no_spec.json", results_dir=tmp_path / "results")
    nb_path = Path(handle.model_extra["notebook_path"])
    nb = json.loads(nb_path.read_text())
    # Notebook is still well-formed; the spec-load cell handles an empty dict.
    src = "\n".join("".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "code")
    assert "SPEC" in src


def test_poll_returns_running_when_no_results_yet(runner: ColabRunner, tmp_path: Path) -> None:
    handle = runner.submit(tmp_path / "spec.json", results_dir=tmp_path / "r")
    status = runner.poll(handle)
    assert status.state == "running"


def test_fetch_raises_until_user_drops_tarball(runner: ColabRunner, tmp_path: Path) -> None:
    handle = runner.submit(tmp_path / "spec.json", results_dir=tmp_path / "r")
    with pytest.raises(FileNotFoundError):
        runner.fetch(handle)


def test_fetch_returns_path_when_tarball_arrives(runner: ColabRunner, tmp_path: Path) -> None:
    results = tmp_path / "r"
    handle = runner.submit(tmp_path / "spec.json", results_dir=results)
    archive = results / f"{handle.id}.tar.gz"
    # Build a real (empty) tarball where the user would drop it.
    with tarfile.open(archive, "w:gz") as tf:
        placeholder = results / "PLACEHOLDER"
        placeholder.write_text("hello\n")
        tf.add(placeholder, arcname="PLACEHOLDER")
    assert runner.poll(handle).state == "succeeded"
    assert runner.fetch(handle) == archive

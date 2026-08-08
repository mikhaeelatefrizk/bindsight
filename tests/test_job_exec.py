# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Executor dispatch tests — real assembly logic, subprocess mocked (no GPU).

Monkeypatches the single subprocess seam (`job_exec._run`) to drop canned
RFdiffusion / ProteinMPNN / Boltz-2 outputs, then asserts the executor produces
the downstream-correct tarball layout (metrics.jsonl + validate/<binder>/...).
"""

from __future__ import annotations

import json
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from bindsight.runners import job_exec

_TINY_PDB = (
    "ATOM      1  CA  MET A   1      0.0  0.0  0.0  1.0  0.0           C\n"
    "ATOM      2  CA  ALA A   2      0.0  0.0  0.0  1.0  0.0           C\n"
    "ATOM      3  CA  GLY A   3      0.0  0.0  0.0  1.0  0.0           C\n"
)
_MPNN_FASTA = ">native, score=2.0\nMAG\n>T=0.1, sample=1, score=0.8\nGSHMSLEQKKGADII\n"

#: Chain letters RFdiffusion gives the output complex. The target moves to B and
#: the diffused binder takes A — deliberately *not* the input target's letter, so
#: a chain choice made by letter rather than by content would pick the antigen.
_TARGET_CHAIN = "B"
_BINDER_CHAIN = "A"


def _atom_line(serial: int, resname: str, chain: str, resi: int) -> str:
    """One CA ATOM record in fixed PDB columns."""
    return (
        f"ATOM  {serial:>5d}  CA  {resname} {chain}{resi:>4d}"
        "      0.0  0.0  0.0  1.0  0.0           C"
    )


def _backbone_pdb() -> str:
    """An RFdiffusion binder-design backbone: target chain + diffused binder chain.

    The target block carries the native residues copied off ``target.pdb``; the
    binder is the poly-glycine RFdiffusion emits before ProteinMPNN gives it a
    sequence. Two chains is what the real tool produces — a single-chain output
    is not a binder-design complex at all.
    """
    lines = [
        _atom_line(i, res, _TARGET_CHAIN, i) for i, res in enumerate(("MET", "ALA", "GLY"), start=1)
    ]
    lines += [_atom_line(3 + i, "GLY", _BINDER_CHAIN, i) for i in range(1, 61)]
    return "\n".join(lines) + "\n"


def _fake_run(cmd, *, cwd=None):
    """Mimic the design tools by writing their expected output files."""
    s = " ".join(cmd)
    if "run_inference.py" in s:
        prefix = next(a.split("=", 1)[1] for a in cmd if a.startswith("inference.output_prefix="))
        outdir = Path(prefix).parent
        outdir.mkdir(parents=True, exist_ok=True)
        for i in range(2):
            (outdir / f"binder_{i}.pdb").write_text(_backbone_pdb())
    elif "protein_mpnn_run.py" in s:
        out_folder = Path(cmd[cmd.index("--out_folder") + 1])
        seqs = out_folder / "seqs"
        seqs.mkdir(parents=True, exist_ok=True)
        (seqs / "bb.fa").write_text(_MPNN_FASTA)
    elif cmd[0] == "boltz":
        out_dir = Path(cmd[cmd.index("--out_dir") + 1])
        pred = out_dir / "predictions" / "run"
        pred.mkdir(parents=True, exist_ok=True)
        (pred / "confidence_run_model_0.json").write_text(
            json.dumps({"iptm": 0.77, "pae_interaction": 5.0})
        )
        (pred / "affinity_run.json").write_text(
            json.dumps({"affinity_pred_value": -7.0, "affinity_probability_binary": 0.9})
        )
    # git clone / checkout / wget: no-ops
    return SimpleNamespace(returncode=0, stdout="", stderr="")


@pytest.fixture
def mock_run(monkeypatch):
    """Patch the subprocess seam; yields the argv lists the executor ran."""
    calls: list[list[str]] = []

    def _record(cmd, *, cwd=None):
        calls.append(list(cmd))
        return _fake_run(cmd, cwd=cwd)

    monkeypatch.setattr(job_exec, "_run", _record)
    return calls


def _spec() -> dict:
    return {
        "target_uniprot": "P04626",
        "target_structure_path": "target.pdb",
        "epitope_chain": "A",
        "epitope_residues": [1, 2],
        "binder_length_min": 50,
        "binder_length_max": 100,
        "n_trajectories": 2,
        "seed": 0,
        "extra_params": {"designer": "rfdiff_mpnn", "validator": "boltz2"},
    }


def test_run_job_rfdiff_boltz_produces_correct_layout(mock_run, tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    (work / "target.pdb").write_text(_TINY_PDB)

    tar = job_exec.run_job(_spec(), work, tarball=tmp_path / "results.tar.gz")
    assert tar.exists()

    # metrics.jsonl has one ValidationResult-shaped row per design, parsed real.
    metrics = [
        json.loads(ln) for ln in (work / "metrics.jsonl").read_text().splitlines() if ln.strip()
    ]
    assert len(metrics) == 2  # 2 backbones × 1 design each
    assert metrics[0]["iptm"] == 0.77
    assert metrics[0]["affinity_pred_value"] == -7.0
    assert metrics[0]["validator_name"] == "boltz2"

    # validate/<binder_id>/ holds the per-binder Boltz JSONs for downstream use.
    binder_dirs = list((work / "validate").iterdir())
    assert binder_dirs
    assert any(p.name.startswith("confidence_") for p in binder_dirs[0].iterdir())

    # The tarball carries the downstream-correct members.
    with tarfile.open(tar) as tf:
        names = tf.getnames()
    assert "metrics.jsonl" in names
    assert any(n.startswith("validate/") for n in names)
    assert any(n.startswith("design/") for n in names)

    # ProteinMPNN was told to design the binder chain only — the antigen is held
    # fixed. Without --pdb_path_chains it designs every chain, i.e. rewrites the
    # target and optimises the binder against a surface it partly invented.
    mpnn_cmds = [c for c in mock_run if any("protein_mpnn_run.py" in a for a in c)]
    assert len(mpnn_cmds) == 2  # one per backbone
    for cmd in mpnn_cmds:
        assert "--pdb_path_chains" in cmd
        chains = cmd[cmd.index("--pdb_path_chains") + 1].split()
        assert chains == [_BINDER_CHAIN]
        assert _TARGET_CHAIN not in chains


def test_run_job_rejects_unknown_designer(tmp_path: Path) -> None:
    spec = _spec()
    spec["extra_params"]["designer"] = "nope"
    with pytest.raises(ValueError, match="unknown designer"):
        job_exec.run_job(spec, tmp_path / "w")


def test_run_job_rejects_unknown_validator(mock_run, tmp_path: Path) -> None:
    spec = _spec()
    spec["extra_params"]["validator"] = "nope"
    (tmp_path / "w").mkdir()
    (tmp_path / "w" / "target.pdb").write_text(_TINY_PDB)
    with pytest.raises(ValueError, match="unknown validator"):
        job_exec.run_job(spec, tmp_path / "w")


def test_materialise_target_copies_pdb(tmp_path: Path) -> None:
    spec_dir = tmp_path / "spec"
    spec_dir.mkdir()
    (spec_dir / "target.pdb").write_text(_TINY_PDB)
    spec = {"extra_params": {"target_structure_name": "target.pdb"}}
    work = tmp_path / "work"
    job_exec.materialise_target(spec, spec_dir, work)
    assert (work / "target.pdb").read_text() == _TINY_PDB

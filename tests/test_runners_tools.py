"""Unit tests for the design-tool command builders + output parsers.

These cover the highest-risk, CPU-verifiable pieces of the design half: exact
RFdiffusion contig/hotspot strings, argv construction for every tool, and the
parsers (ProteinMPNN FASTA, PDB sequence, Chai, AF2-IG).
"""

from __future__ import annotations

import json
from pathlib import Path

from bindsight.runners import tools


# ---------------------------------------------------------------------------
# String builders (highest risk)
# ---------------------------------------------------------------------------
def test_build_hotspot_str() -> None:
    assert tools.build_hotspot_str("A", [30, 31, 45]) == "[A30,A31,A45]"
    assert tools.build_hotspot_str("B", []) == "[]"


def test_build_contig_str_uses_real_span() -> None:
    # keep target chain A residues 5..620, then a 50-100 binder after a break
    assert tools.build_contig_str("A", 5, 620, 50, 100) == "[A5-620/0 50-100]"


def test_build_rfdiff_cmd() -> None:
    cmd = tools.build_rfdiff_cmd(
        rfdiff_dir=Path("/opt/RFdiffusion"),
        input_pdb=Path("/w/target.pdb"),
        output_prefix=Path("/w/out/binder"),
        num_designs=8,
        hotspot="[A30,A31]",
        contig="[A1-200/0 50-100]",
    )
    assert cmd[0] == "python"
    assert cmd[1].replace("\\", "/").endswith("scripts/run_inference.py")  # OS-agnostic
    assert "inference.num_designs=8" in cmd
    assert "ppi.hotspot_res=[A30,A31]" in cmd
    assert "contigmap.contigs=[A1-200/0 50-100]" in cmd


def test_build_mpnn_cmd() -> None:
    cmd = tools.build_mpnn_cmd(
        mpnn_dir=Path("/opt/ProteinMPNN"),
        pdb_path=Path("/w/b.pdb"),
        out_folder=Path("/w/mpnn"),
        seed=7,
    )
    assert cmd[1].endswith("protein_mpnn_run.py")
    assert "--pdb_path" in cmd
    assert "--seed" in cmd
    assert "7" in cmd


def test_build_boltz_cmd_msa_flag() -> None:
    cmd = tools.build_boltz_cmd(yaml_path=Path("/w/x.yaml"), out_dir=Path("/w/o"))
    assert cmd[:2] == ["boltz", "predict"]
    assert "--use_msa_server" in cmd
    no_msa = tools.build_boltz_cmd(
        yaml_path=Path("/w/x.yaml"), out_dir=Path("/w/o"), use_msa_server=False
    )
    assert "--use_msa_server" not in no_msa


def test_interpreter_overrides_for_split_env_hosts(monkeypatch) -> None:
    """BINDSIGHT_DESIGN_PYTHON / BINDSIGHT_BOLTZ_BIN swap argv[0] (Kaggle split env).

    Defaults stay ``python`` / ``boltz`` so every other backend is unaffected.
    """
    monkeypatch.setenv("BINDSIGHT_DESIGN_PYTHON", "/opt/se3_python.sh")
    monkeypatch.setenv("BINDSIGHT_BOLTZ_BIN", "/opt/mamba/envs/boltz/bin/boltz")
    rf = tools.build_rfdiff_cmd(
        rfdiff_dir=Path("/opt/RFdiffusion"),
        input_pdb=Path("/w/t.pdb"),
        output_prefix=Path("/w/o/b"),
        num_designs=2,
        hotspot="[A30]",
        contig="[A1-100/0 50-100]",
    )
    assert rf[0] == "/opt/se3_python.sh"
    mpnn = tools.build_mpnn_cmd(
        mpnn_dir=Path("/opt/ProteinMPNN"), pdb_path=Path("/w/b.pdb"), out_folder=Path("/w/m")
    )
    assert mpnn[0] == "/opt/se3_python.sh"
    boltz = tools.build_boltz_cmd(yaml_path=Path("/w/x.yaml"), out_dir=Path("/w/o"))
    assert boltz[0] == "/opt/mamba/envs/boltz/bin/boltz"


def test_build_chai_boltzgen_bindcraft_af2ig_cmds() -> None:
    assert tools.build_chai_cmd(fasta_path=Path("/w/x.fa"), out_dir=Path("/w/o"))[:2] == [
        "chai-lab",
        "fold",
    ]
    bg = tools.build_boltzgen_cmd(
        target_pdb=Path("/w/t.pdb"), out_dir=Path("/w/o"), num_designs=4, hotspot="[A1]"
    )
    assert bg[:2] == ["boltzgen", "design"]
    assert "--num_designs" in bg
    bc = tools.build_bindcraft_cmd(
        bindcraft_dir=Path("/opt/BindCraft"),
        settings_json=Path("/w/s.json"),
        filters_json=Path("/w/f.json"),
        advanced_json=Path("/w/a.json"),
    )
    assert bc[1].endswith("bindcraft.py")
    af2 = tools.build_af2ig_cmd(
        dl_binder_design_dir=Path("/opt/dl"), silent_or_pdb=Path("/w/b.pdb"), out_dir=Path("/w/o")
    )
    assert af2[1].replace("\\", "/").endswith("af2_initial_guess/predict.py")  # OS-agnostic


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------
_MPNN_FASTA = """\
>backbone_0, score=2.1, global_score=2.0, seq_recovery=0.0
MKTAYIAKQRQISFVKSHFSRQLEERLGLIEVQ
>T=0.1, sample=1, score=0.85, global_score=0.9, seq_recovery=0.42
GSHMSLEQKKGADIISKILQIQNSIGKTTSPST
"""


def test_parse_mpnn_fasta_and_designs(tmp_path: Path) -> None:
    fa = tmp_path / "seqs.fa"
    fa.write_text(_MPNN_FASTA)
    records = tools.parse_mpnn_fasta(fa)
    assert len(records) == 2
    # mpnn_design_sequences skips the native (first) record.
    designs = tools.mpnn_design_sequences(fa)
    assert designs == ["GSHMSLEQKKGADIISKILQIQNSIGKTTSPST"]


def test_parse_mpnn_design_picks_last_chain_segment(tmp_path: Path) -> None:
    fa = tmp_path / "multi.fa"
    fa.write_text(">native, score=1\nAAAA/BBBB\n>T=0.1, sample=1, score=1\nTARGETSEQ/BINDERSEQ\n")
    assert tools.mpnn_design_sequences(fa) == ["BINDERSEQ"]


def test_chain_sequence_from_pdb(tmp_path: Path) -> None:
    pdb = tmp_path / "t.pdb"
    pdb.write_text(
        "ATOM      1  CA  MET A   1      0.0  0.0  0.0  1.0  0.0           C\n"
        "ATOM      2  CA  ALA A   2      0.0  0.0  0.0  1.0  0.0           C\n"
        "ATOM      3  CA  GLY B   1      0.0  0.0  0.0  1.0  0.0           C\n"
    )
    assert tools.chain_sequence_from_pdb(pdb, "A") == "MA"
    assert tools.chain_sequence_from_pdb(pdb, "B") == "G"


def test_parse_af2ig_output(tmp_path: Path) -> None:
    sc = tmp_path / "af2_scores.sc"
    sc.write_text("description pae_interaction plddt_binder\nb0 6.3 0.88\n")
    res = tools.parse_af2ig_output(sc, binder_id="b0", target_uniprot="P04626")
    assert res.pae_interaction == 6.3
    assert res.validator_name == "af2_ig"


def test_parse_chai_output(tmp_path: Path) -> None:
    import numpy as np

    out = tmp_path / "b0"
    out.mkdir()
    np.savez(out / "scores.model_idx_0.npz", iptm=np.array(0.72), ptm=np.array(0.81))
    res = tools.parse_chai_output(out, binder_id="b0", target_uniprot="P04626")
    assert res.iptm == 0.72
    assert res.validator_name == "chai1r"


def test_boltz_yaml_reexport_and_metrics_writer(tmp_path: Path) -> None:
    spec = tools.build_boltz_yaml(
        target_id="T", target_sequence="MKT", binder_id="b0", binder_sequence="GSH"
    )
    assert spec["sequences"][0]["protein"]["sequence"] == "MKT"
    p = tools.write_metrics_jsonl([{"binder_id": "b0", "iptm": 0.7}], tmp_path / "m.jsonl")
    assert json.loads(p.read_text().splitlines()[0])["binder_id"] == "b0"

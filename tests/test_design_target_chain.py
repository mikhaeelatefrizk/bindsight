# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The target must survive the design step untouched, and only its ECD is designed against.

Two scientific contracts are pinned here, both at the builder level and through
the real executor dispatch (subprocess seam mocked, no GPU):

P3 — ProteinMPNN is invoked with ``--pdb_path_chains`` naming ONLY the diffused
binder chain. Its default is to design *every* chain, so on an RFdiffusion
binder–target complex it rewrote the antigen too and the binder was optimised
against a surface the model partly invented, then folded and scored against the
native one. The binder chain is identified from the backbone's own content, not
from a chain letter.

I6 — the extracellular ``design_ranges`` discovery annotates from UniProt
topology reach the design job, so binders are designed against the reachable
part of the receptor rather than the full-length chain (transmembrane helix and
cytoplasmic tail included). When they are absent that is stated loudly, never
silently treated as "the whole receptor was intended".
"""

from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from bindsight import cli
from bindsight.design._common import make_cache_key
from bindsight.design.rfdiff_mpnn import RFdiffMPNNDesigner
from bindsight.runners import job_exec, tools

# ---------------------------------------------------------------------------
# Fixture structures: a realistic two-chain RFdiffusion binder-design backbone
# ---------------------------------------------------------------------------
#: ERBB2 extracellular-domain fragment (the target the designer is given).
_TARGET_SEQ = (
    "TQVCTGTDMKLRLPASPETHLDMLRHLYQGCQVVQGNLELTYLPTNASLSFLQDIQEVQGYVLIAHNQ"
    "VRQVPLQRLRIVRGTQLFEDNYALAVLDNGDPLNNTTPVTGASPGGLREL"
)
#: UniProt numbering of the first modelled residue (P04626's ECD starts at 23).
_TARGET_START = 23
_TARGET_END = _TARGET_START + len(_TARGET_SEQ) - 1

#: RFdiffusion assigns output chain letters from the contig: the target lands on
#: B and the diffused binder takes A — the input target's own letter. Choosing a
#: chain by letter would therefore hand ProteinMPNN the antigen to redesign.
_TARGET_CHAIN_OUT = "B"
_BINDER_CHAIN_OUT = "A"

_MPNN_FASTA = ">native, score=2.0\nGGG\n>T=0.1, sample=1, score=0.8\nGSHMSLEQKKGADII\n"

_THREE = {
    "A": "ALA",
    "C": "CYS",
    "D": "ASP",
    "E": "GLU",
    "F": "PHE",
    "G": "GLY",
    "H": "HIS",
    "I": "ILE",
    "K": "LYS",
    "L": "LEU",
    "M": "MET",
    "N": "ASN",
    "P": "PRO",
    "Q": "GLN",
    "R": "ARG",
    "S": "SER",
    "T": "THR",
    "V": "VAL",
    "W": "TRP",
    "Y": "TYR",
}


def _atom_line(serial: int, resname: str, chain: str, resi: int) -> str:
    """One CA ATOM record in fixed PDB columns."""
    return (
        f"ATOM  {serial:>5d}  CA  {resname} {chain}{resi:>4d}"
        "      0.0  0.0  0.0  1.0  0.0           C"
    )


def _chain_pdb(seq: str, chain: str, *, start_resi: int = 1, first_serial: int = 1) -> str:
    """CA-only PDB text for one chain."""
    lines = [
        _atom_line(first_serial + i, _THREE[aa], chain, start_resi + i) for i, aa in enumerate(seq)
    ]
    return "\n".join(lines) + "\n"


def _target_pdb() -> str:
    """The AlphaFold target structure handed to the designer (chain A, UniProt numbering)."""
    return _chain_pdb(_TARGET_SEQ, "A", start_resi=_TARGET_START)


def _backbone_pdb(target_part: str) -> str:
    """An RFdiffusion output complex: kept target block + poly-glycine binder."""
    target = _chain_pdb(target_part, _TARGET_CHAIN_OUT, start_resi=1)
    binder = _chain_pdb(
        "G" * 60, _BINDER_CHAIN_OUT, start_resi=1, first_serial=len(target_part) + 1
    )
    return target + binder


def _kept_target_seq(contig: str) -> str:
    """The target residues a contig keeps, as RFdiffusion would copy them out."""
    segments = contig.strip("[]").split("/0 ")[0]
    seq = ""
    for seg in segments.split("/"):
        lo, hi = (int(x) for x in seg[1:].split("-"))
        seq += _TARGET_SEQ[lo - _TARGET_START : hi - _TARGET_START + 1]
    return seq


def _spec(**overrides: object) -> dict:
    spec: dict = {
        "target_uniprot": "P04626",
        "epitope_chain": "A",
        "epitope_residues": [_TARGET_START + 5, _TARGET_START + 9],
        "binder_length_min": 50,
        "binder_length_max": 100,
        "n_trajectories": 1,
        "seed": 0,
        "extra_params": {"designer": "rfdiff_mpnn", "validator": "boltz2"},
    }
    spec.update(overrides)
    return spec


@pytest.fixture
def recorded_run(monkeypatch):
    """Patch the subprocess seam with design-tool stubs; yields the argv lists run."""
    calls: list[list[str]] = []

    def _fake(cmd, *, cwd=None):
        calls.append(list(cmd))
        s = " ".join(cmd)
        if "run_inference.py" in s:
            prefix = next(
                a.split("=", 1)[1] for a in cmd if a.startswith("inference.output_prefix=")
            )
            contig = next(a.split("=", 1)[1] for a in cmd if a.startswith("contigmap.contigs="))
            outdir = Path(prefix).parent
            outdir.mkdir(parents=True, exist_ok=True)
            (outdir / "binder_0.pdb").write_text(_backbone_pdb(_kept_target_seq(contig)))
        elif "protein_mpnn_run.py" in s:
            seqs = Path(cmd[cmd.index("--out_folder") + 1]) / "seqs"
            seqs.mkdir(parents=True, exist_ok=True)
            (seqs / "bb.fa").write_text(_MPNN_FASTA)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(job_exec, "_run", _fake)
    return calls


def _mpnn_designed_chains(calls: list[list[str]]) -> list[list[str]]:
    """The ``--pdb_path_chains`` value of every ProteinMPNN invocation, split."""
    return [
        cmd[cmd.index("--pdb_path_chains") + 1].split()
        for cmd in calls
        if any("protein_mpnn_run.py" in a for a in cmd)
    ]


# ---------------------------------------------------------------------------
# P3 — argv: ProteinMPNN is constrained to the binder chain
# ---------------------------------------------------------------------------
def test_build_mpnn_cmd_names_only_the_designed_chain() -> None:
    cmd = tools.build_mpnn_cmd(
        mpnn_dir=Path("/opt/ProteinMPNN"),
        pdb_path=Path("/w/binder_0.pdb"),
        out_folder=Path("/w/mpnn"),
        designed_chains=["A"],
    )
    assert "--pdb_path_chains" in cmd
    # Adjacent pair: the flag and its value, nothing between them.
    assert cmd[cmd.index("--pdb_path_chains") + 1] == "A"
    # The target chain is never handed over as designable.
    assert "B" not in cmd[cmd.index("--pdb_path_chains") + 1]


def test_build_mpnn_cmd_joins_multiple_designed_chains() -> None:
    cmd = tools.build_mpnn_cmd(
        mpnn_dir=Path("/opt/ProteinMPNN"),
        pdb_path=Path("/w/binder_0.pdb"),
        out_folder=Path("/w/mpnn"),
        designed_chains=["B", "C"],
    )
    assert cmd[cmd.index("--pdb_path_chains") + 1] == "B C"


def test_build_mpnn_cmd_rejects_empty_designed_chains() -> None:
    """No chain list means ProteinMPNN's design-everything default — refuse it."""
    with pytest.raises(ValueError, match="at least one chain"):
        tools.build_mpnn_cmd(
            mpnn_dir=Path("/opt/ProteinMPNN"),
            pdb_path=Path("/w/binder_0.pdb"),
            out_folder=Path("/w/mpnn"),
            designed_chains=[],
        )


# ---------------------------------------------------------------------------
# P3 — the binder chain is identified from the backbone's content
# ---------------------------------------------------------------------------
def test_binder_chain_from_backbone_picks_the_diffused_chain(tmp_path: Path) -> None:
    """Target on B, binder on A: the answer is A even though A is the input's letter."""
    bb = tmp_path / "binder_0.pdb"
    bb.write_text(_backbone_pdb(_TARGET_SEQ))
    assert tools.binder_chain_from_backbone(bb, target_sequence=_TARGET_SEQ) == _BINDER_CHAIN_OUT


def test_binder_chain_from_backbone_is_letter_agnostic(tmp_path: Path) -> None:
    """Swap the letters over and the identification follows the sequences."""
    bb = tmp_path / "swapped.pdb"
    bb.write_text(
        _chain_pdb(_TARGET_SEQ, "A", start_resi=1)
        + _chain_pdb("G" * 60, "B", start_resi=1, first_serial=len(_TARGET_SEQ) + 1)
    )
    assert tools.binder_chain_from_backbone(bb, target_sequence=_TARGET_SEQ) == "B"


def test_binder_chain_from_backbone_rejects_single_chain_backbone(tmp_path: Path) -> None:
    """A backbone that is only the target is not a binder-design complex."""
    bb = tmp_path / "target_only.pdb"
    bb.write_text(_chain_pdb(_TARGET_SEQ, "A", start_resi=1))
    with pytest.raises(ValueError, match="cannot identify the binder chain"):
        tools.binder_chain_from_backbone(bb, target_sequence=_TARGET_SEQ)


def test_binder_chain_from_backbone_rejects_indistinguishable_chains(tmp_path: Path) -> None:
    """Two target-like chains: guessing would silently redesign the antigen."""
    bb = tmp_path / "two_targets.pdb"
    bb.write_text(
        _chain_pdb(_TARGET_SEQ, "A", start_resi=1)
        + _chain_pdb(_TARGET_SEQ, "B", start_resi=1, first_serial=len(_TARGET_SEQ) + 1)
    )
    with pytest.raises(ValueError, match="cannot identify the binder chain"):
        tools.binder_chain_from_backbone(bb, target_sequence=_TARGET_SEQ)


# ---------------------------------------------------------------------------
# P3 — end to end through the executor
# ---------------------------------------------------------------------------
def test_executor_designs_the_binder_chain_and_holds_the_target_fixed(
    recorded_run, tmp_path: Path
) -> None:
    work = tmp_path / "work"
    work.mkdir()
    (work / "target.pdb").write_text(_target_pdb())

    designs = job_exec._design_rfdiff_mpnn(_spec(), work, tmp_path / "tools")
    assert designs

    designed = _mpnn_designed_chains(recorded_run)
    assert designed == [[_BINDER_CHAIN_OUT]]
    assert _TARGET_CHAIN_OUT not in designed[0]


def test_executor_refuses_a_backbone_whose_binder_chain_is_ambiguous(
    monkeypatch, tmp_path: Path
) -> None:
    """A target-only 'backbone' must fail, not fall back to designing everything."""

    def _fake(cmd, *, cwd=None):
        if any("run_inference.py" in a for a in cmd):
            prefix = next(
                a.split("=", 1)[1] for a in cmd if a.startswith("inference.output_prefix=")
            )
            outdir = Path(prefix).parent
            outdir.mkdir(parents=True, exist_ok=True)
            (outdir / "binder_0.pdb").write_text(_chain_pdb(_TARGET_SEQ, "A", start_resi=1))
        assert not any("protein_mpnn_run.py" in a for a in cmd), "MPNN must not be reached"
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(job_exec, "_run", _fake)
    work = tmp_path / "work"
    work.mkdir()
    (work / "target.pdb").write_text(_target_pdb())
    with pytest.raises(ValueError, match="cannot identify the binder chain"):
        job_exec._design_rfdiff_mpnn(_spec(), work, tmp_path / "tools")


# ---------------------------------------------------------------------------
# I6 — the extracellular ranges reach the design job
# ---------------------------------------------------------------------------
def test_build_ranges_contig_keeps_only_the_named_segments() -> None:
    assert tools.build_ranges_contig_str("A", [(23, 652), (700, 720)], 50, 100) == (
        "[A23-652/A700-720/0 50-100]"
    )
    # The single-range form is the same builder, so the two cannot drift.
    assert tools.build_contig_str("A", 5, 620, 50, 100) == "[A5-620/0 50-100]"


def test_build_ranges_contig_rejects_no_ranges() -> None:
    with pytest.raises(ValueError, match="at least one target range"):
        tools.build_ranges_contig_str("A", [], 50, 100)


def test_target_ranges_clip_the_spec_ranges_to_the_modelled_chain(tmp_path: Path) -> None:
    pdb = tmp_path / "target.pdb"
    pdb.write_text(_target_pdb())
    ranges = job_exec._target_ranges(
        {"design_ranges": [[_TARGET_START, 60], [100, 9999]]}, pdb, "A"
    )
    assert ranges == [(_TARGET_START, 60), (100, _TARGET_END)]


def test_target_ranges_without_design_ranges_warns_and_takes_the_whole_chain(
    tmp_path: Path, caplog
) -> None:
    """Designing against the full-length receptor is a real choice; say so."""
    pdb = tmp_path / "target.pdb"
    pdb.write_text(_target_pdb())
    with caplog.at_level(logging.WARNING, logger="bindsight.runners.job_exec"):
        ranges = job_exec._target_ranges({}, pdb, "A")
    assert ranges == [(_TARGET_START, _TARGET_END)]
    assert "no design_ranges" in caplog.text
    assert "transmembrane" in caplog.text


def test_target_ranges_reject_ranges_off_the_modelled_chain(tmp_path: Path) -> None:
    pdb = tmp_path / "target.pdb"
    pdb.write_text(_target_pdb())
    with pytest.raises(ValueError, match="do not overlap"):
        job_exec._target_ranges({"design_ranges": [[900, 950]]}, pdb, "A")


def test_target_structure_for_design_is_trimmed_to_the_ranges(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    (work / "target.pdb").write_text(_target_pdb())
    trimmed = job_exec._target_structure_for_design(
        {"design_ranges": [[_TARGET_START, _TARGET_START + 5]]}, work, "A"
    )
    assert trimmed.name == "target_design_region.pdb"
    assert tools.chain_residues_from_pdb(trimmed, "A") == [
        (_TARGET_START + i, aa) for i, aa in enumerate(_TARGET_SEQ[:6])
    ]
    # Whole-chain ranges need no trimming, so the original structure is used.
    whole = job_exec._target_structure_for_design(
        {"design_ranges": [[_TARGET_START, _TARGET_END]]}, work, "A"
    )
    assert whole.name == "target.pdb"


def test_executor_presents_only_the_design_ranges_to_rfdiffusion(
    recorded_run, tmp_path: Path
) -> None:
    """The contig keeps the ECD segments and drops everything between them."""
    work = tmp_path / "work"
    work.mkdir()
    (work / "target.pdb").write_text(_target_pdb())

    job_exec._design_rfdiff_mpnn(
        _spec(design_ranges=[[_TARGET_START, 60], [100, 140]]), work, tmp_path / "tools"
    )

    contigs = [
        a.split("=", 1)[1]
        for cmd in recorded_run
        for a in cmd
        if a.startswith("contigmap.contigs=")
    ]
    assert contigs == ["[A23-60/A100-140/0 50-100]"]
    # The non-extracellular stretch 61-99 is not presented to the designer.
    assert f"A{_TARGET_START}-{_TARGET_END}" not in contigs[0]
    # And the binder chain is still the only one ProteinMPNN designs.
    assert _mpnn_designed_chains(recorded_run) == [[_BINDER_CHAIN_OUT]]


# ---------------------------------------------------------------------------
# I6 — the CLI hand-off from the epitopes table to the DesignSpec
# ---------------------------------------------------------------------------
def _seed_epitopes(run: Path, *, design_ranges: list[list[int]] | None) -> None:
    """Write a one-row epitopes table (+ its structure) into ``run``."""
    (run / "epitopes").mkdir(parents=True, exist_ok=True)
    (run / "structures").mkdir(parents=True, exist_ok=True)
    (run / "structures" / "P04626.pdb").write_text(_target_pdb())
    row: dict = {
        "symbol": ["ERBB2"],
        "uniprot_id": ["P04626"],
        "structure_path": ["structures/P04626.pdb"],
        "chain": ["A"],
        "residues": [[_TARGET_START + 5, _TARGET_START + 9]],
        "epitope_status": ["surface_bind_not_configured"],
    }
    if design_ranges is not None:
        row["design_ranges"] = [design_ranges]
        row["design_range_source"] = ["uniprot_topology"]
    pd.DataFrame(row).to_parquet(run / "epitopes" / "epitopes.parquet", index=False)


def test_top_targets_carries_design_ranges_into_the_design_spec(tmp_path: Path) -> None:
    run = tmp_path / "run"
    run.mkdir()
    _seed_epitopes(run, design_ranges=[[23, 652], [700, 720]])

    targets = cli._top_targets(run)
    assert len(targets) == 1
    assert targets[0]["design_ranges"] == [(23, 652), (700, 720)]

    spec = RFdiffMPNNDesigner().make_spec(
        target_uniprot=targets[0]["uniprot"],
        target_structure_path=Path(targets[0]["structure_path"]),
        epitope_residues=targets[0]["residues"],
        epitope_chain=targets[0]["chain"],
        design_ranges=targets[0]["design_ranges"],
    )
    assert spec.design_ranges == [(23, 652), (700, 720)]


def test_design_ranges_change_the_design_cache_key() -> None:
    """Two jobs differing only in the designed region are different jobs."""
    designer = RFdiffMPNNDesigner()
    ecd = designer.make_spec(
        target_uniprot="P04626",
        target_structure_path=Path("P04626.pdb"),
        epitope_residues=[28, 32],
        design_ranges=[(23, 652)],
    )
    full = ecd.model_copy(update={"design_ranges": [(1, 1255)]})
    assert make_cache_key(ecd) != make_cache_key(full)


def test_top_targets_names_the_targets_without_extracellular_ranges(tmp_path: Path, capsys) -> None:
    """No topology must be stated, not silently read as 'design the whole receptor'."""
    run = tmp_path / "run"
    run.mkdir()
    _seed_epitopes(run, design_ranges=None)

    targets = cli._top_targets(run)
    assert targets[0]["design_ranges"] == []
    out = capsys.readouterr().out
    assert "No extracellular ranges for P04626" in out
    assert "use_uniprot_topology" in out


def test_top_targets_is_quiet_when_every_target_has_ranges(tmp_path: Path, capsys) -> None:
    run = tmp_path / "run"
    run.mkdir()
    _seed_epitopes(run, design_ranges=[[23, 652]])
    cli._top_targets(run)
    assert "No extracellular ranges" not in capsys.readouterr().out

# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the scramble control set's construction (CPU-only).

This script builds the control that the ipTM calibration's conclusion rests on,
and the conclusion was strong enough to withdraw a published headline. If a
"scramble" were not actually a composition-preserving shuffle, or if a staged
structure described a different sequence from the FASTA beside it, the control
would be measuring something other than what it claims and nothing downstream
would notice: every file would still be well-formed.
"""

from __future__ import annotations

import collections
import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "benchmarks" / "calibration"))

import stage_scrambles as stage

REPO = Path(__file__).resolve().parents[1]
COMMITTED_BINDERS = REPO / "benchmarks" / "designer_benchmark" / "binders"
COMMITTED_TARGET = REPO / "benchmarks" / "designer_benchmark" / "target" / "P04626_domain_IV.pdb"


class TestTheShuffleIsAControl:
    def test_composition_is_preserved_exactly(self) -> None:
        """Length and residue counts must be identical, or it is not matched."""
        rng = random.Random(1)
        seq = "MKVLATTWQCGHIPSDEFNRYMKVLATTWQ"
        shuffled = stage._scramble(seq, rng)
        assert collections.Counter(shuffled) == collections.Counter(seq)
        assert len(shuffled) == len(seq)

    def test_the_shuffle_is_never_the_original(self) -> None:
        """A shuffle that returns its input is the design under another name."""
        rng = random.Random(2)
        for _ in range(200):
            seq = "".join(rng.choice("ACDEFGHIKLMNPQRSTVWY") for _ in range(12))
            assert stage._scramble(seq, rng) != seq

    def test_a_sequence_that_cannot_differ_is_refused(self) -> None:
        """A homopolymer has one arrangement, so it cannot be a control.

        Returning it unchanged would put a "scramble" in the set that is
        byte-identical to its design, which reads as a zero difference the
        analysis would average in as evidence.
        """
        rng = random.Random(3)
        with pytest.raises(ValueError, match="shuffle"):
            stage._scramble("AAAAAAAA", rng)

    def test_the_seed_makes_the_control_reproducible(self) -> None:
        """A published control that differs on rerun is not a published control."""
        seq = "MKVLATTWQCGHIPSDEFNRY"
        a = stage._scramble(seq, random.Random(stage.SEED))
        b = stage._scramble(seq, random.Random(stage.SEED))
        assert a == b


def _stage(tmp_path: Path, *extra: str) -> Path:
    rc = stage.main(
        [
            "--out",
            str(tmp_path),
            "--binders",
            str(COMMITTED_BINDERS),
            "--target",
            str(COMMITTED_TARGET),
            *extra,
        ]
    )
    assert rc == 0
    return tmp_path / "design"


def _fasta_seq(path: Path) -> str:
    return "".join(
        ln.strip() for ln in path.read_text(encoding="utf-8").splitlines() if not ln.startswith(">")
    )


class TestTheStagedSetDescribesItself:
    """Every staged structure must describe the sequence staged beside it.

    The executor reads the sequence from the FASTA and requires a PDB alongside.
    A mismatch would be invisible: both files parse, the job runs, and the
    metrics row is well-formed and about a different molecule.
    """

    def test_each_pdb_carries_the_sequence_of_its_fasta(self, tmp_path: Path) -> None:
        from bindsight.runners import tools

        staged = _stage(tmp_path, "--with-originals")
        fastas = sorted(staged.glob("*.fasta"))
        assert fastas, "nothing staged"
        for fasta in fastas:
            pdb = staged / f"{fasta.stem}.pdb"
            assert pdb.is_file(), f"{fasta.name} has no structure beside it"
            assert tools.chain_sequence_from_pdb(pdb, "A") == _fasta_seq(fasta)

    def test_every_scramble_is_a_permutation_of_its_own_design(self, tmp_path: Path) -> None:
        """Not of some other design — the pairing is what the test relies on."""
        staged = _stage(tmp_path, "--with-originals")
        for scram in sorted(staged.glob("*_scram.fasta")):
            parent = staged / f"{scram.stem.removesuffix('_scram')}.fasta"
            assert parent.is_file()
            assert collections.Counter(_fasta_seq(scram)) == collections.Counter(_fasta_seq(parent))
            assert _fasta_seq(scram) != _fasta_seq(parent)

    def test_originals_match_the_committed_complexes_byte_for_byte(self, tmp_path: Path) -> None:
        """The staged "design" must be the design, or the pairing is a fiction."""
        from bindsight.runners import tools

        native = tools.chain_sequence_from_pdb(COMMITTED_TARGET, "A")
        staged = _stage(tmp_path, "--with-originals")
        checked = 0
        for fasta in sorted(staged.glob("*.fasta")):
            if fasta.stem.endswith("_scram"):
                continue
            cif = COMMITTED_BINDERS / f"{fasta.stem}_complex.cif"
            assert cif.is_file()
            binder = [s for s in tools.chain_sequences_from_cif(cif).values() if s != native]
            assert len(binder) == 1
            assert binder[0] == _fasta_seq(fasta)
            checked += 1
        assert checked == 20

    def test_without_originals_only_scrambles_are_staged(self, tmp_path: Path) -> None:
        staged = _stage(tmp_path)
        names = [f.stem for f in staged.glob("*.fasta")]
        assert names
        assert all(n.endswith("_scram") for n in names)

    def test_no_temporary_scratch_file_survives(self, tmp_path: Path) -> None:
        """The staged directory is shipped verbatim; strays become payload."""
        staged = _stage(tmp_path, "--with-originals")
        assert not list(staged.glob("*.tmp.pdb"))
        for f in staged.iterdir():
            assert f.suffix in {".pdb", ".fasta"}, f"unexpected file staged: {f.name}"


class TestItRefusesRatherThanStagesNonsense:
    def test_an_empty_binder_directory_is_refused(self, tmp_path: Path) -> None:
        """Staging nothing would submit a job that validates nothing."""
        empty = tmp_path / "none"
        empty.mkdir()
        rc = stage.main(
            [
                "--out",
                str(tmp_path / "o"),
                "--binders",
                str(empty),
                "--target",
                str(COMMITTED_TARGET),
            ]
        )
        assert rc == 1

    def test_a_missing_target_is_refused(self, tmp_path: Path) -> None:
        rc = stage.main(
            [
                "--out",
                str(tmp_path / "o"),
                "--binders",
                str(COMMITTED_BINDERS),
                "--target",
                str(tmp_path / "absent.pdb"),
            ]
        )
        assert rc == 1

    def test_a_target_chain_with_no_sequence_is_refused(self, tmp_path: Path) -> None:
        """The binder chain is found by differing from the target's.

        An empty target sequence makes every chain in every complex look like a
        binder, so the set would be staged from the wrong chains rather than
        failing.
        """
        rc = stage.main(
            [
                "--out",
                str(tmp_path / "o"),
                "--binders",
                str(COMMITTED_BINDERS),
                "--target",
                str(COMMITTED_TARGET),
                "--target-chain",
                "Z",
            ]
        )
        assert rc == 1


class TestItIsNotTiedToOneBenchmark:
    """A scramble control is meaningful for any design run, not just this one."""

    def test_the_binder_directory_is_a_flag_not_a_constant(self, tmp_path: Path) -> None:
        subset = tmp_path / "subset"
        subset.mkdir()
        chosen = sorted(COMMITTED_BINDERS.glob("*_complex.cif"))[:3]
        for cif in chosen:
            (subset / cif.name).write_bytes(cif.read_bytes())

        rc = stage.main(
            [
                "--out",
                str(tmp_path / "o"),
                "--binders",
                str(subset),
                "--target",
                str(COMMITTED_TARGET),
                "--with-originals",
            ]
        )
        assert rc == 0
        staged = tmp_path / "o" / "design"
        assert len(list(staged.glob("*.fasta"))) == len(chosen) * 2

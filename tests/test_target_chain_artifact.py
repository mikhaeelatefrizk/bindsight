# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The committed complexes must actually carry the native target.

"The target was held fixed, and that is checked rather than asserted" appears
in six documents. It is the entire difference between the current designer
benchmark and the withdrawn one: the superseded run invoked ProteinMPNN without
``--pdb_path_chains``, so it redesigned the ERBB2 target chain along with the
binder and scored designs against a surface they had helped invent.

Until now the check was over *code*: `tests/test_design_target_chain.py` proves
the argv carries the flag, on synthetic fixtures with the subprocess seam
mocked. The 20 committed ``*_complex.cif`` files were never opened, and the
"142 residues" in the prose existed nowhere but the prose.

These tests read the artifacts. Same shape as the three blind spots found the
day they were written: a green test guaranteeing a property of a test double
rather than of the thing shipped.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from bindsight.runners import tools

REPO = Path(__file__).resolve().parents[1]
BENCH = REPO / "benchmarks" / "designer_benchmark"
NATIVE = BENCH / "target" / "P04626_domain_IV.pdb"
BINDERS = BENCH / "binders"

#: UniProt P04626 residues 511-652, per `prepare_erbb2_target.py`.
DOMAIN_IV_LENGTH = 142


@pytest.fixture(scope="module")
def native() -> str:
    if not NATIVE.is_file():
        pytest.skip("the native target artifact is not committed")
    return tools.chain_sequence_from_pdb(NATIVE, "A")


@pytest.fixture(scope="module")
def complexes() -> list[Path]:
    found = sorted(BINDERS.glob("*_complex.cif"))
    if not found:
        pytest.skip("no committed complexes")
    return found


def test_the_native_target_is_the_domain_the_prose_names(native: str) -> None:
    """`142` must come from the artifact, not from a sentence."""
    assert len(native) == DOMAIN_IV_LENGTH
    assert set(native) <= set("ACDEFGHIKLMNPQRSTVWY"), "the target carries unresolved residues"


def test_every_committed_design_has_a_complex(complexes: list[Path]) -> None:
    """A missing structure must fail rather than shrink the check silently."""
    fastas = sorted(BINDERS.glob("*.fasta"))
    assert len(complexes) == 20, f"expected 20 complexes, found {len(complexes)}"
    assert len(fastas) == len(complexes), "a design is missing its structure or its sequence"


def test_each_complex_carries_the_native_target_unchanged(
    native: str, complexes: list[Path]
) -> None:
    """The claim, checked: exactly one chain per complex *is* the native target.

    Phrased as "exactly one" rather than "chain T" so it cannot pass by the
    validator happening to relabel chains, and cannot pass by the binder having
    been designed into a copy of the target.
    """
    for path in complexes:
        chains = tools.chain_sequences_from_cif(path)
        assert chains, f"{path.name} carries no atom records"
        matching = [c for c, seq in chains.items() if seq == native]
        assert len(matching) == 1, (
            f"{path.name}: {len(matching)} chains equal the native target "
            f"(chain lengths {{{', '.join(f'{c}:{len(s)}' for c, s in chains.items())}}}). "
            "The target was not held fixed."
        )


def test_each_complex_also_carries_a_binder(native: str, complexes: list[Path]) -> None:
    """A complex of the target with itself would satisfy the check above alone."""
    for path in complexes:
        chains = tools.chain_sequences_from_cif(path)
        others = [seq for seq in chains.values() if seq != native]
        assert len(others) == 1, f"{path.name} has no single binder chain beside the target"
        assert 20 <= len(others[0]) <= 200, (
            f"{path.name}: binder is {len(others[0])} residues, outside the designed range"
        )


def test_the_designs_are_not_all_the_same_binder(native: str, complexes: list[Path]) -> None:
    """Twenty copies of one sequence would pass every test above."""
    binders = set()
    for path in complexes:
        chains = tools.chain_sequences_from_cif(path)
        binders.update(seq for seq in chains.values() if seq != native)
    assert len(binders) > 1, "every complex carries an identical binder"


def test_the_binder_sequences_match_their_fastas(native: str, complexes: list[Path]) -> None:
    """The structure and the sequence file must describe the same molecule.

    Staged design PDBs are byte-identical per backbone, so the FASTA is the only
    place a design's own sequence lives. If the two disagree, one of them is
    describing something that was never folded.
    """
    for path in complexes:
        fasta = path.with_name(path.name.replace("_complex.cif", ".fasta"))
        if not fasta.is_file():
            pytest.fail(f"{path.name} has no sibling FASTA")
        expected = "".join(
            line.strip()
            for line in fasta.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith(">")
        )
        chains = tools.chain_sequences_from_cif(path)
        binder = next(seq for seq in chains.values() if seq != native)
        assert binder == expected, f"{path.name}: folded sequence differs from its FASTA"

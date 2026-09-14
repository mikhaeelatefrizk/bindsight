# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The committed provenance run must actually support the walk it claims.

`git ls-files` returned zero manifests and zero crates until this run. The
provenance graph is the stated moat and had never been exhibited, so nothing
could check it. These tests hold the committed artifacts to the claim.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
JOIN = REPO / "benchmarks" / "provenance_join"
MANIFEST = JOIN / "run_manifest.jsonld"
CRATE_META = JOIN / "ro-crate-metadata.json"


@pytest.fixture(scope="module")
def manifest() -> dict:
    if not MANIFEST.is_file():
        pytest.skip("provenance run manifest not committed")
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def graph() -> list[dict]:
    if not CRATE_META.is_file():
        pytest.skip("crate metadata not committed")
    return json.loads(CRATE_META.read_text(encoding="utf-8"))["@graph"]


def test_every_stage_of_the_chain_completed(manifest: dict) -> None:
    """A chain that stops early demonstrates nothing."""
    stages = {s["name"]: s["status"] for s in manifest["stages"]}
    for name in ("deg", "discover", "design", "validate", "rank", "report", "export"):
        assert stages.get(name) == "completed", f"stage {name} is {stages.get(name)}"


def test_the_cohort_inputs_are_recorded_with_digests(manifest: dict) -> None:
    """The patient end of the walk, and the integrity check on it."""
    inputs = [
        ref
        for stage in manifest["stages"]
        for ref in (stage.get("inputs") or [])
        if ref.get("role") in {"counts", "design"}
    ]
    roles = {ref["role"] for ref in inputs}
    assert roles == {"counts", "design"}, f"cohort inputs not recorded: {roles}"
    for ref in inputs:
        assert ref.get("sha256"), f"{ref['role']} recorded without a digest"
        assert len(ref["sha256"]) == 64


def test_the_crate_carries_the_cohort(graph: list[dict]) -> None:
    """An earlier crate of this same run shipped 31 files and no cohort at all."""
    ids = {entry.get("@id", "") for entry in graph}
    for required in ("inputs/counts.tsv.gz", "inputs/design.tsv", "inputs/provenance.json"):
        assert required in ids, f"the crate metadata does not list {required}"


def test_the_carried_in_cohort_keeps_its_digest(graph: list[dict]) -> None:
    counts = next(e for e in graph if e.get("@id") == "inputs/counts.tsv.gz")
    assert counts.get("sha256"), "the cohort travelled without its recorded digest"
    assert counts["contentSize"] > 1_000_000


def test_the_crate_carries_each_step_of_the_walk(graph: list[dict]) -> None:
    """Ranked binder -> target -> structure -> expression -> cohort."""
    ids = {entry.get("@id", "") for entry in graph}
    for step in (
        "rank/ranking.parquet",
        "epitopes/epitopes.parquet",
        "deg/results.parquet",
        "run_manifest.jsonld",
    ):
        assert step in ids, f"the walk cannot reach {step}"
    assert any(i.startswith("structures/") and i.endswith(".cif") for i in ids), (
        "no structure in the crate, so a target's model cannot be inspected"
    )


def test_the_readme_states_the_seed_gap_rather_than_hiding_it(manifest: dict) -> None:
    """This manifest predates the seed-recording fix; the note must say so.

    Delete this test in the same commit that replaces the artifact with one
    whose design stage records the seed — and only then.
    """
    design = next(s for s in manifest["stages"] if s["name"] == "design")
    readme = (JOIN / "README.md").read_text(encoding="utf-8").lower()
    if "seed" in (design.get("params") or {}):
        pytest.skip("the committed manifest records the seed; the note is obsolete")
    assert "not the seed" in readme or "does not carry" in readme, (
        "the manifest omits the seed and the note beside it does not say so"
    )
    assert "42" in readme, "the note does not say which seed was actually used"


class TestTheWalkMatchesWhatTheCloneCarries:
    """The README exhibits a seven-step walk from binder to patient samples.

    It used to open by saying a reviewer could do that "reading committed
    artifacts and running nothing". Only the first three steps are in the
    committed manifest: the gene identifier, the cohort and the patient
    barcodes live in the 74 MB crate, which is not committed, and ``runs/`` is
    gitignored in full. The walk was genuinely performed -- the transcript is
    real -- but a reader with only the clone can confirm half of it.

    These tests hold both halves of that statement true: the steps claimed as
    checkable must actually be checkable, and the claim must not creep back.
    """

    @staticmethod
    def _committed_text() -> str:
        import json

        root = Path(__file__).resolve().parents[1] / "benchmarks" / "provenance_join"
        parts = []
        for name in ("run_manifest.jsonld", "ro-crate-metadata.json"):
            parts.append(json.dumps(json.loads((root / name).read_text(encoding="utf-8"))))
        return "".join(parts)

    @staticmethod
    def _readme() -> str:
        root = Path(__file__).resolve().parents[1] / "benchmarks" / "provenance_join"
        return (root / "README.md").read_text(encoding="utf-8")

    def test_the_first_three_steps_resolve_from_the_committed_manifest(self) -> None:
        """The part the README says a clone can check, it must be able to check."""
        text = self._committed_text()

        for step, needle in (
            ("1 — the ranked binder", "P32970_binder_6_seq0"),
            ("2 — its target", "P32970"),
            ("3 — the structure it was built against", "AF-P32970"),
        ):
            assert needle in text, (
                f"step {step} is claimed to be verifiable from this directory, but "
                f"{needle!r} is in neither committed file"
            )

    def test_the_readme_does_not_claim_the_whole_walk_from_a_clone(self) -> None:
        """The later steps are genuinely absent; the text must keep saying so."""
        text = self._committed_text()
        readme = self._readme()

        absent = [n for n in ("ENSG00000125726", "TCGA-A3-", "TCGA-KIRC") if n in text]
        if absent:
            pytest.skip(f"the committed files now carry {absent}; widen the claim")

        assert "are not" in readme or "cannot" in readme, (
            "the manifest carries only the first three steps, and the README no "
            "longer tells the reader which half of the walk they can check"
        )
        assert "74 MB" in readme
        assert "not committed" in readme

    def test_the_barcodes_quoted_are_open_access_identifiers(self) -> None:
        """The README names TCGA cases, so it must say what they are.

        They are pseudonymous study identifiers from the GDC open-access tier,
        not patient identifiers -- a distinction a reader in a clinical setting
        will want made explicitly rather than assumed.
        """
        readme = self._readme()
        if "TCGA-A3-" not in readme:
            pytest.skip("no barcode is quoted")

        lowered = readme.lower()
        assert "open-access" in lowered or "open access" in lowered, (
            "patient barcodes are quoted without stating their access tier"
        )
        assert "pseudonymous" in lowered or "not patient identifiers" in lowered

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

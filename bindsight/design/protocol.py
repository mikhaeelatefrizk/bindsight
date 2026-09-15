# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Designer plugin protocol.

A Designer turns a ``DesignSpec`` (target structure + epitope + params) into
``DesignResult`` (a tarball of binder PDBs + per-design metrics). All real
work is offloaded to a :class:`bindsight.runners.GPURunner`; the Designer
itself only owns the spec shape and result schema.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

# A real import, not a TYPE_CHECKING one. ``submit`` annotates this type, and
# the annotation was previously silenced with ``# type: ignore[name-defined]``
# plus a ``noqa: F821`` directive -- which quieted two checkers rather than
# telling either
# what the name is, so ``typing.get_type_hints`` on this Protocol raised and
# nothing could introspect the contract. ``bindsight.runners.protocol`` imports
# nothing from this package, so there is no cycle to avoid.
from bindsight.runners.protocol import GPURunner


class DesignSpec(BaseModel):
    """Inputs to a single design job (one target × N trajectories)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    target_uniprot: str
    target_structure_path: str = Field(..., description="Local path to mmCIF/PDB.")
    epitope_chain: str = "A"
    # Hotspot residues to focus the binder on. Empty = whole-target design
    # (valid before SURFACE-Bind epitope prediction is wired); RFdiffusion then
    # runs without ``ppi.hotspot_res``.
    epitope_residues: list[int] = Field(default_factory=list)
    # Inclusive residue ranges of the target the binder may be designed against —
    # the extracellular domain(s) annotated by discovery. Empty means no topology
    # was available, so the whole chain (transmembrane helix and cytoplasmic tail
    # included) is the design surface; the executor says so rather than implying
    # the full-length receptor was intended.
    design_ranges: list[tuple[int, int]] = Field(default_factory=list)
    binder_length_min: int = 50
    binder_length_max: int = 100
    n_trajectories: int = 50
    seed: int = 0
    extra_params: dict[str, str | int | float | bool] = Field(default_factory=dict)


class DesignResult(BaseModel):
    """Result of a design job."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    spec: DesignSpec
    results_archive_path: str = Field(..., description="Local path to the .tar.gz of PDBs.")
    metrics_jsonl_path: str = Field(
        ..., description="Local path to per-design metrics JSONL (one row per design)."
    )
    designer_name: str
    designer_version: str
    designer_commit_sha: str | None = None
    weights_sha256: str | None = None
    cache_key: str = Field(..., description="Used to deduplicate identical jobs across runs.")
    cache_status: Literal["hit", "miss"] = Field(
        "miss",
        description=(
            "Whether this result was reused from a previous run with the same cache_key "
            "('hit') or newly computed ('miss'). Recorded so a manifest shows which units "
            "actually consumed GPU time."
        ),
    )


@runtime_checkable
class Designer(Protocol):
    """Protocol every designer plugin must implement."""

    name: str
    version: str

    def make_spec(
        self,
        *,
        target_uniprot: str,
        target_structure_path: Path,
        epitope_residues: list[int],
        epitope_chain: str = "A",
        design_ranges: list[tuple[int, int]] | None = None,
        n_trajectories: int = 50,
        seed: int = 0,
        binder_length_min: int = 50,
        binder_length_max: int = 100,
    ) -> DesignSpec:
        """Build a designer-specific DesignSpec from generic inputs."""
        ...

    def submit(self, spec: DesignSpec, runner: GPURunner) -> DesignResult:
        """Execute the design job (synchronous from the caller's POV)."""
        ...

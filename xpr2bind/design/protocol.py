"""Designer plugin protocol.

A Designer turns a ``DesignSpec`` (target structure + epitope + params) into
``DesignResult`` (a tarball of binder PDBs + per-design metrics). All real
work is offloaded to a :class:`xpr2bind.runners.GPURunner`; the Designer
itself only owns the spec shape and result schema.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field


class DesignSpec(BaseModel):
    """Inputs to a single design job (one target × N trajectories)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    target_uniprot: str
    target_structure_path: str = Field(..., description="Local path to mmCIF/PDB.")
    epitope_chain: str = "A"
    epitope_residues: list[int] = Field(..., min_length=1)
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
        n_trajectories: int = 50,
        seed: int = 0,
    ) -> DesignSpec:
        """Build a designer-specific DesignSpec from generic inputs."""
        ...

    def submit(self, spec: DesignSpec, runner: GPURunner) -> DesignResult:  # type: ignore[name-defined]  # noqa: F821
        """Execute the design job (synchronous from the caller's POV)."""
        ...

# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""GPU runner protocol.

Runners abstract WHERE GPU work executes. The pipeline calls the same
``submit/poll/fetch`` API regardless of whether the backend is free Colab,
paid Modal, Kaggle Notebooks, local NVIDIA Docker, or a mock for CI.

The ``estimate_cost`` method gates ``--dry-run``: it must return a usable
estimate without launching anything.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

JobState = Literal["queued", "running", "succeeded", "failed", "cancelled"]


class JobHandle(BaseModel):
    """Opaque handle returned by :meth:`GPURunner.submit`."""

    model_config = ConfigDict(extra="allow", frozen=True)

    backend: str
    id: str
    submitted_at: str


class JobStatus(BaseModel):
    """Status snapshot returned by :meth:`GPURunner.poll`."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    handle: JobHandle
    state: JobState
    progress: float | None = Field(None, ge=0.0, le=1.0)
    log_tail: str | None = None


class CostEstimate(BaseModel):
    """Pre-flight cost estimate for a job."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    backend: str
    gpu_type: str = Field(..., description="e.g. 'T4', 'A100-40GB', 'A100-80GB'.")
    gpu_hours: float = Field(..., ge=0.0)
    usd_estimate: float | None = Field(
        None,
        ge=0.0,
        description="Best-effort USD estimate. None for free tiers (Colab/Kaggle/HF Spaces).",
    )
    queue_minutes_estimate: float | None = Field(None, ge=0.0)
    notes: str | None = None


@runtime_checkable
class GPURunner(Protocol):
    """Protocol every runner backend must implement."""

    name: str

    def estimate_cost(self, spec_size: int) -> CostEstimate:
        """Estimate cost for a job of the given spec_size (e.g. trajectory count)."""
        ...

    def submit(self, spec_path: Path, *, results_dir: Path) -> JobHandle:
        """Launch the job; return immediately with a handle."""
        ...

    def poll(self, handle: JobHandle) -> JobStatus:
        """Return current job status; cheap, may be called frequently."""
        ...

    def fetch(self, handle: JobHandle) -> Path:
        """Block until job completes, then return the local results.tar.gz path."""
        ...

"""Local-Docker GPU runner.

For users with a local NVIDIA GPU, this runner shells out to ``docker run``
against the pinned xpr2bind image, mounting the spec + results dirs. v0.0.x
exposes the cost estimator (always $0 — your hardware) and a stub submit
that documents the docker command users would run.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path

from xpr2bind.cost import estimate
from xpr2bind.runners.protocol import CostEstimate, JobHandle, JobStatus

LOG = logging.getLogger(__name__)


class LocalDockerRunner:
    """Stub: live docker invocation lands in v0.1.0-rc2."""

    name = "local_docker"

    def __init__(
        self,
        *,
        designer: str = "rfdiff_mpnn",
        n_units_per_target: int = 50,
        gpu_type: str = "A100-40GB",
        image: str = "ghcr.io/mikhaeelatefrizk/xpr2bind:dev",
    ) -> None:
        self.designer = designer
        self.n_units_per_target = n_units_per_target
        self.gpu_type = gpu_type
        self.image = image

    def estimate_cost(self, spec_size: int) -> CostEstimate:
        return estimate(
            backend=self.name,
            stage="design",
            plugin=self.designer,
            n_units=spec_size,
            gpu_type=self.gpu_type,
        )

    def submit(self, spec_path: Path, *, results_dir: Path) -> JobHandle:
        results_dir.mkdir(parents=True, exist_ok=True)
        handle_id = str(uuid.uuid4())
        LOG.info(
            "Local Docker live submit lands in v0.1.0-rc2. "
            "Reference command:\n"
            "  docker run --rm --gpus all "
            "-v %s:/spec -v %s:/results "
            "%s xpr2bind-design /spec/spec.json /results/%s",
            spec_path.parent,
            results_dir,
            self.image,
            handle_id,
        )
        return JobHandle(
            backend=self.name,
            id=handle_id,
            submitted_at=datetime.now(UTC).isoformat(timespec="seconds"),
            results_dir=str(results_dir),
        )

    def poll(self, handle: JobHandle) -> JobStatus:
        return JobStatus(
            handle=handle,
            state="failed",
            log_tail="local_docker live submit not wired in v0.0.x",
        )

    def fetch(self, handle: JobHandle) -> Path:
        raise NotImplementedError("local_docker fetch lands in v0.1.0-rc2.")


class KaggleRunner:
    """Kaggle Notebooks runner — same shape as Colab, lands in v0.1.0-rc2."""

    name = "kaggle"

    def __init__(self, *, designer: str = "rfdiff_mpnn", gpu_type: str = "T4") -> None:
        self.designer = designer
        self.gpu_type = gpu_type

    def estimate_cost(self, spec_size: int) -> CostEstimate:
        return estimate(
            backend=self.name,
            stage="design",
            plugin=self.designer,
            n_units=spec_size,
            gpu_type=self.gpu_type,
        )

    def submit(self, spec_path: Path, *, results_dir: Path) -> JobHandle:
        raise NotImplementedError("Kaggle runner lands in v0.1.0-rc2.")

    def poll(self, handle: JobHandle) -> JobStatus:
        return JobStatus(handle=handle, state="failed", log_tail="not wired")

    def fetch(self, handle: JobHandle) -> Path:
        raise NotImplementedError("Kaggle runner lands in v0.1.0-rc2.")

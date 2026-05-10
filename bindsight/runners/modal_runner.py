"""Modal GPU runner.

`Modal <https://modal.com/>`_ is a serverless GPU platform with a Python-native
API: you decorate a function with ``@app.function(gpu="A100")`` and Modal
provisions, runs, and tears down. Per-second billing, no queue waits beyond
cold starts, A100 ≈ $3/hr.

This module provides the runner skeleton. The actual ``modal.Function`` call
is split into :meth:`_submit_modal` so a future v0.1.0-rc2 can wire it
without rewriting the surrounding orchestration. v0.0.x raises
``NotImplementedError`` from the actual launch path so users get a clean
error if they pick this backend without the next milestone.

To enable for real, install the optional ``runners`` extra:

    pip install -e ".[runners]"
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path

from bindsight.cost import estimate
from bindsight.runners.protocol import CostEstimate, JobHandle, JobStatus

LOG = logging.getLogger(__name__)


class ModalRunner:
    """Serverless-GPU runner. Cost estimate works today; live submit is v0.1.0-rc2."""

    name = "modal"

    def __init__(
        self,
        *,
        designer: str = "rfdiff_mpnn",
        n_units_per_target: int = 50,
        gpu_type: str = "A100-40GB",
        app_name: str = "bindsight",
    ) -> None:
        self.designer = designer
        self.n_units_per_target = n_units_per_target
        self.gpu_type = gpu_type
        self.app_name = app_name

    def estimate_cost(self, spec_size: int) -> CostEstimate:
        """Estimate cost for ``spec_size`` design trajectories on Modal."""
        return estimate(
            backend=self.name,
            stage="design",
            plugin=self.designer,
            n_units=spec_size,
            gpu_type=self.gpu_type,
        )

    def submit(self, spec_path: Path, *, results_dir: Path) -> JobHandle:
        """Submit a job to Modal.

        v0.0.x raises ``NotImplementedError`` — the live Modal client wiring
        lands in v0.1.0-rc2. The cost estimator above already works.
        """
        # Generate a handle so callers can correlate logs even on the failure path.
        handle = JobHandle(
            backend=self.name,
            id=str(uuid.uuid4()),
            submitted_at=datetime.now(UTC).isoformat(timespec="seconds"),
            results_dir=str(results_dir),
        )
        try:
            self._submit_modal(spec_path=spec_path, results_dir=results_dir, handle=handle)
        except NotImplementedError:
            LOG.warning(
                "Modal live submit is not wired in v0.0.x; "
                "use --backend colab or --backend mock for now."
            )
            raise
        return handle

    def _submit_modal(
        self,
        *,
        spec_path: Path,
        results_dir: Path,
        handle: JobHandle,
    ) -> None:
        """Hook for the live Modal submission. Raises until v0.1.0-rc2."""
        raise NotImplementedError(
            "Modal live submit lands in v0.1.0-rc2. The cost estimator is functional today."
        )

    def poll(self, handle: JobHandle) -> JobStatus:
        """Stub: returns ``failed`` since submit doesn't actually start anything yet."""
        return JobStatus(
            handle=handle,
            state="failed",
            progress=None,
            log_tail="Modal live submit not wired in v0.0.x",
        )

    def fetch(self, handle: JobHandle) -> Path:
        """Stub: raises since no job ever started."""
        raise NotImplementedError("Modal fetch lands in v0.1.0-rc2 alongside live submit.")

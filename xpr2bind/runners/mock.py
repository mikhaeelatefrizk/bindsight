"""Mock GPU runner for CI.

Returns canned results immediately so CI can exercise the orchestration code
end-to-end without a real GPU.
"""

from __future__ import annotations

import shutil
import tarfile
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path

from xpr2bind.runners.protocol import CostEstimate, JobHandle, JobStatus


class MockRunner:
    """Returns a canned tarball of fake results."""

    name = "mock"

    def __init__(self, canned_archive: Path | None = None) -> None:
        self.canned = canned_archive

    def estimate_cost(self, spec_size: int) -> CostEstimate:
        """Return a zero-cost estimate; the mock runner never spends money."""
        return CostEstimate(
            backend=self.name,
            gpu_type="mock",
            gpu_hours=0.0,
            usd_estimate=0.0,
            queue_minutes_estimate=0.0,
            notes="Mock runner — no real compute.",
        )

    def submit(self, spec_path: Path, *, results_dir: Path) -> JobHandle:
        """Pretend to submit a job; returns a unique handle immediately."""
        results_dir.mkdir(parents=True, exist_ok=True)
        return JobHandle(
            backend=self.name,
            id=str(uuid.uuid4()),
            submitted_at=datetime.now(UTC).isoformat(timespec="seconds"),
        )

    def poll(self, handle: JobHandle) -> JobStatus:
        """Always report 'succeeded' immediately."""
        return JobStatus(handle=handle, state="succeeded", progress=1.0, log_tail=None)

    def fetch(self, handle: JobHandle) -> Path:
        """Return either the canned archive provided at construction, or a placeholder."""
        if self.canned is not None:
            return self.canned
        # Build an empty placeholder tarball so callers get a real file path.
        tmp = Path(tempfile.mkdtemp(prefix="xpr2bind_mock_")) / "results.tar.gz"
        with tarfile.open(tmp, "w:gz") as tf:
            placeholder = tmp.parent / "PLACEHOLDER.txt"
            placeholder.write_text("mock runner — no real designs\n")
            tf.add(placeholder, arcname="PLACEHOLDER.txt")
        return tmp

    @staticmethod
    def cleanup(path: Path) -> None:
        """Remove a temp directory created by :meth:`fetch`."""
        if path.parent.name.startswith("xpr2bind_mock_"):
            shutil.rmtree(path.parent, ignore_errors=True)

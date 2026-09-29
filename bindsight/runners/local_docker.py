# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Local-GPU runner.

For users with a local NVIDIA GPU. Two modes, selected by the ``native`` flag
(or the ``BINDSIGHT_LOCAL_NATIVE`` env var):

- **native** — runs :mod:`bindsight.runners.job_exec` in the current Python env
  (a CUDA box with bindsight + the design tools installed). Simplest for an
  already-provisioned workstation; also the mode CPU tests exercise (with
  ``job_exec`` monkeypatched).
- **docker** — ``docker run --gpus all <image> python -m bindsight.runners.job_exec``
  against an explicitly configured custom GPU image, mounting spec + results.
  The published default image is CPU-only and is refused for GPU jobs.

Both call the same executor, so the design+validation pipeline is identical to
the Modal/Kaggle paths.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

from bindsight.cost import estimate
from bindsight.runners.protocol import CostEstimate, JobHandle, JobStatus

LOG = logging.getLogger(__name__)
DEFAULT_CPU_IMAGE = "ghcr.io/mikhaeelatefrizk/bindsight:latest"

# Track launched processes by handle id (JobHandle is frozen, so we can't stash
# the Popen on it). Maps handle id -> (Popen, tarball Path).
_PROCS: dict[str, tuple[subprocess.Popen[bytes], Path]] = {}


class LocalDockerRunner:
    """Run design+validation on a local GPU, natively or via Docker."""

    name = "local_docker"

    def __init__(
        self,
        *,
        designer: str = "rfdiff_mpnn",
        n_units_per_target: int = 50,
        gpu_type: str = "A100-40GB",
        # `:latest` because it is the only tag `docker.yml` always publishes:
        # the others are the commit SHA and, on a tag push, the release. There
        # has never been a `:dev`. A moving tag is safe here in a way it is not
        # for a CI action -- the image carries its own bindsight and runs it, and
        # `pipelines.full_run._container_ref` records the resolved *digest* in the
        # manifest, never the tag, for exactly this reason.
        image: str = "ghcr.io/mikhaeelatefrizk/bindsight:latest",
        native: bool | None = None,
    ) -> None:
        self.designer = designer
        self.n_units_per_target = n_units_per_target
        self.gpu_type = gpu_type
        self.image = (
            os.environ.get("BINDSIGHT_LOCAL_IMAGE", image) if image == DEFAULT_CPU_IMAGE else image
        )
        self.native = (
            native
            if native is not None
            else os.environ.get("BINDSIGHT_LOCAL_NATIVE", "").lower() in {"1", "true", "yes"}
        )

    def estimate_cost(self, spec_size: int) -> CostEstimate:
        """Estimate cost (always $0 — your hardware)."""
        return estimate(
            backend=self.name,
            stage="design",
            plugin=self.designer,
            n_units=spec_size,
            gpu_type=self.gpu_type,
        )

    def submit(self, spec_path: Path, *, results_dir: Path) -> JobHandle:
        """Launch the executor (native subprocess or docker run); return a handle."""
        if issue := self.configuration_issue():
            raise RuntimeError(issue)
        results_dir.mkdir(parents=True, exist_ok=True)
        handle_id = str(uuid.uuid4())
        tarball = results_dir / f"{handle_id}.tar.gz"

        if self.native:
            cmd = [
                sys.executable,
                "-m",
                "bindsight.runners.job_exec",
                str(spec_path),
                str(tarball),
            ]
        else:
            spec_dir = spec_path.parent.resolve()
            cmd = [
                "docker",
                "run",
                "--rm",
                "--gpus",
                "all",
                "--entrypoint",
                "python",
                "-v",
                f"{spec_dir}:/spec",
                "-v",
                f"{results_dir.resolve()}:/results",
                self.image,
                "-m",
                "bindsight.runners.job_exec",
                f"/spec/{spec_path.name}",
                f"/results/{handle_id}.tar.gz",
            ]

        LOG.info(
            "local_docker submit (%s): %s", "native" if self.native else "docker", " ".join(cmd)
        )
        try:
            proc = subprocess.Popen(cmd)
        except FileNotFoundError as e:
            raise RuntimeError(
                "docker not found — install Docker, or use native mode "
                "(BINDSIGHT_LOCAL_NATIVE=1) on a machine with bindsight + the design tools."
                if not self.native
                else f"failed to launch executor: {e}"
            ) from e
        _PROCS[handle_id] = (proc, tarball)
        return JobHandle(
            backend=self.name,
            id=handle_id,
            submitted_at=datetime.now(UTC).isoformat(timespec="seconds"),
            results_dir=str(results_dir),
            tarball=str(tarball),
        )

    def configuration_issue(self) -> str | None:
        """Reject the known CPU image without pretending to inspect a custom one."""
        if not self.native and self.image == DEFAULT_CPU_IMAGE:
            return (
                "The default bindsight Docker image is CPU-only and cannot run GPU design "
                "or Boltz-2. Use an already provisioned CUDA environment with "
                "BINDSIGHT_LOCAL_NATIVE=1, or set BINDSIGHT_LOCAL_IMAGE to your own "
                "GPU image containing the pinned design and validation environments. "
                "A custom environment still needs validation on the actual GPU."
            )
        return None

    def poll(self, handle: JobHandle) -> JobStatus:
        """Report queued/running/succeeded/failed from the tracked process."""
        entry = _PROCS.get(handle.id)
        tarball = Path(entry[1]) if entry else Path(getattr(handle, "tarball", ""))
        if entry is None:
            state = "succeeded" if tarball.exists() else "failed"
            return JobStatus(handle=handle, state=state, log_tail=None)
        proc, _ = entry
        rc = proc.poll()
        if rc is None:
            return JobStatus(handle=handle, state="running", progress=None)
        state = "succeeded" if rc == 0 and tarball.exists() else "failed"
        return JobStatus(handle=handle, state=state, log_tail=f"exit code {rc}")

    def fetch(self, handle: JobHandle) -> Path:
        """Block until the job finishes; return the results tarball path."""
        entry = _PROCS.get(handle.id)
        tarball = Path(entry[1]) if entry else Path(getattr(handle, "tarball", ""))
        if entry is not None:
            proc, _ = entry
            rc = proc.wait()
            if rc != 0:
                raise RuntimeError(f"local_docker job {handle.id} failed (exit {rc})")
        if not tarball.exists():
            raise RuntimeError(f"local_docker job {handle.id} produced no results at {tarball}")
        return tarball

# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Kaggle Notebooks GPU runner.

Drives Kaggle's free GPU tier (T4×2, ~30 GPU-hr/week) headlessly via the Kaggle
public API: push a generated kernel that runs :mod:`bindsight.runners.job_exec`,
poll its status, then pull the results tarball from the kernel output. Requires
the ``runners`` extra (``kaggle``) and Kaggle API credentials
(``~/.kaggle/kaggle.json`` or ``KAGGLE_USERNAME``/``KAGGLE_KEY``).

The ``kaggle`` client is imported lazily so ``import bindsight`` works without
the extra installed.
"""

from __future__ import annotations

import base64
import json
import logging
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bindsight.cost import estimate
from bindsight.runners import kaggle_kernel
from bindsight.runners.protocol import CostEstimate, JobHandle, JobStatus

LOG = logging.getLogger(__name__)


def _require_kaggle() -> Any:
    """Import + authenticate the Kaggle API, with a clear error if missing."""
    try:
        from kaggle.api.kaggle_api_extended import KaggleApi
    except ImportError as e:
        raise RuntimeError(
            'Kaggle runner needs the "runners" extra: pip install -e ".[runners]" '
            "and Kaggle credentials (~/.kaggle/access_token or ~/.kaggle/kaggle.json)."
        ) from e
    api = KaggleApi()
    api.authenticate()
    return api


# Kaggle's status enum (KernelWorkerStatus.*) → our JobStatus.state. The API
# returns an object whose ``.status`` is the enum (not a lowercase dict), so we
# read ``.name`` and map it here.
_STATE_MAP = {
    "QUEUED": "queued",
    "RUNNING": "running",
    "COMPLETE": "succeeded",
    "ERROR": "failed",
    "CANCEL_REQUESTED": "running",
    "CANCEL_ACKNOWLEDGED": "cancelled",
    "CANCELACKNOWLEDGED": "cancelled",
}


def _status_name(status: Any) -> str:
    """Extract the upper-case status name from a kernels_status response."""
    s = getattr(status, "status", status)
    name = getattr(s, "name", None)
    if name:
        return str(name).upper()
    if isinstance(status, dict):
        return str(status.get("status", "")).upper()
    return str(s).upper()


class KaggleRunner:
    """Headless Kaggle Notebooks runner (push kernel, poll, pull tarball)."""

    name = "kaggle"

    def __init__(
        self,
        *,
        designer: str = "rfdiff_mpnn",
        gpu_type: str = "P100",
        username: str | None = None,
        poll_interval_s: int = 30,
        bindsight_ref: str | None = None,
    ) -> None:
        self.designer = designer
        self.gpu_type = gpu_type
        self.username = username
        self.poll_interval_s = poll_interval_s
        # Git ref the kernel installs bindsight from (default branch if None).
        self.bindsight_ref = bindsight_ref

    def estimate_cost(self, spec_size: int) -> CostEstimate:
        """Estimate cost (free tier — $0, but queue/quota limited)."""
        return estimate(
            backend=self.name,
            stage="design",
            plugin=self.designer,
            n_units=spec_size,
            gpu_type=self.gpu_type,
        )

    def submit(self, spec_path: Path, *, results_dir: Path) -> JobHandle:
        """Push a self-contained Kaggle kernel that runs the executor on the spec.

        The spec dir (``spec.json`` + the target structure it references) is
        embedded in the kernel as base64 — no Kaggle dataset needed — and the
        kernel builds RFdiffusion's legacy env + the Boltz-2 env on the GPU before
        running :mod:`bindsight.runners.job_exec` across them.
        """
        api = _require_kaggle()
        results_dir.mkdir(parents=True, exist_ok=True)
        handle_id = uuid.uuid4().hex[:12]
        user = self.username or api.config_values.get("username", "user")
        slug = f"bindsight-{handle_id}"

        # Embed every file in the spec dir (spec.json + target structure).
        payload = {
            f.name: base64.b64encode(f.read_bytes()).decode("ascii")
            for f in sorted(spec_path.parent.iterdir())
            if f.is_file()
        }
        work = results_dir / f"kaggle_{handle_id}"
        work.mkdir(parents=True, exist_ok=True)
        (work / "kernel.py").write_text(
            kaggle_kernel.build_kernel_script(
                handle_id=handle_id, payload=payload, bindsight_ref=self.bindsight_ref
            ),
            encoding="utf-8",
        )
        (work / "kernel-metadata.json").write_text(
            json.dumps(kaggle_kernel.build_kernel_metadata(username=user, slug=slug)),
            encoding="utf-8",
        )
        api.kernels_push(str(work))
        LOG.info("kaggle: pushed kernel %s/%s", user, slug)
        return JobHandle(
            backend=self.name,
            id=f"{user}/{slug}",
            submitted_at=datetime.now(UTC).isoformat(timespec="seconds"),
            results_dir=str(results_dir),
            handle_id=handle_id,
        )

    def poll(self, handle: JobHandle) -> JobStatus:
        """Query the kernel's run status."""
        api = _require_kaggle()
        status = api.kernels_status(handle.id)
        name = _status_name(status)
        return JobStatus(handle=handle, state=_STATE_MAP.get(name, "running"), log_tail=name)

    def fetch(self, handle: JobHandle) -> Path:
        """Block until the kernel completes; download the results tarball."""
        api = _require_kaggle()
        results_dir = Path(getattr(handle, "results_dir", "."))
        handle_id = getattr(handle, "handle_id", "")
        while True:
            st = self.poll(handle)
            if st.state in {"succeeded", "failed", "cancelled"}:
                break
            time.sleep(self.poll_interval_s)
        if st.state != "succeeded":
            raise RuntimeError(f"kaggle kernel {handle.id} finished in state {st.state}")
        api.kernels_output(handle.id, str(results_dir))
        tarball = results_dir / f"{handle_id}.tar.gz"
        if not tarball.exists():
            raise RuntimeError(f"kaggle kernel {handle.id} produced no tarball at {tarball}")
        return tarball


__all__ = ["KaggleRunner"]

# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Modal serverless-GPU runner.

`Modal <https://modal.com/>`_ provisions a GPU, runs
:mod:`bindsight.runners.job_exec` (the same executor as the local/Kaggle
paths), and tears down — per-second billing, A100 ≈ $3/hr. Requires the
``runners`` extra (``modal``) and a Modal token (``modal token new``).

``import modal`` happens lazily inside the methods via :func:`_require_modal`,
so ``import bindsight`` works without the extra installed. Execution is
synchronous from the caller's point of view (``submit`` runs the job and caches
the tarball; ``fetch`` returns it), matching the Designer ``submit→fetch``
contract.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bindsight.cost import estimate
from bindsight.runners import tools
from bindsight.runners.protocol import CostEstimate, JobHandle, JobStatus

LOG = logging.getLogger(__name__)

# Map bindsight GPU names to Modal gpu= strings.
_MODAL_GPU = {
    "A100-40GB": "A100",
    "A100-80GB": "A100-80GB",
    "T4": "T4",
    "L4": "L4",
    "A10G": "A10G",
    "H100": "H100",
}

# handle id -> local tarball path (submit runs synchronously and caches here).
_RESULTS: dict[str, Path] = {}


def _require_modal() -> Any:
    """Import Modal with a clear, actionable error if the extra isn't installed."""
    try:
        import modal
    except ImportError as e:
        raise RuntimeError(
            'Modal runner needs the "runners" extra: pip install -e ".[runners]" '
            "and a Modal token (run: modal token new)."
        ) from e
    return modal


class ModalRunner:
    """Serverless-GPU runner that executes the design+validation job on Modal."""

    name = "modal"

    def __init__(
        self,
        *,
        designer: str = "rfdiff_mpnn",
        n_units_per_target: int = 50,
        gpu_type: str = "A100-40GB",
        app_name: str = "bindsight",
        timeout_s: int = 3600,
    ) -> None:
        self.designer = designer
        self.n_units_per_target = n_units_per_target
        self.gpu_type = gpu_type
        self.app_name = app_name
        self.timeout_s = timeout_s

    def estimate_cost(self, spec_size: int) -> CostEstimate:
        """Estimate cost for ``spec_size`` design trajectories on Modal."""
        return estimate(
            backend=self.name,
            stage="design",
            plugin=self.designer,
            n_units=spec_size,
            gpu_type=self.gpu_type,
        )

    def _build_app(self) -> tuple[Any, Any]:
        """Define the Modal app + GPU function lazily."""
        modal = _require_modal()
        image = (
            modal.Image.debian_slim()
            .apt_install("git", "wget")
            .pip_install("bindsight", tools.BOLTZ_PIP, "pandas", "pyarrow")
        )
        app = modal.App(self.app_name)
        gpu = _MODAL_GPU.get(self.gpu_type, "A100")

        @app.function(gpu=gpu, image=image, timeout=self.timeout_s)  # type: ignore[untyped-decorator]
        def _run_remote(spec_json: str, files: dict[str, bytes]) -> bytes:
            import json as _json
            import tempfile
            from pathlib import Path as _P

            from bindsight.runners import job_exec

            work = _P(tempfile.mkdtemp(prefix="bindsight_modal_"))
            spec_dir = work / "spec"
            spec_dir.mkdir(parents=True, exist_ok=True)
            (spec_dir / "spec.json").write_text(spec_json)
            for name, data in files.items():
                (spec_dir / name).write_bytes(data)
            spec = _json.loads(spec_json)
            job_exec.materialise_target(spec, spec_dir, work / "run")
            tarball = job_exec.run_job(spec, work / "run", tarball=work / "results.tar.gz")
            return tarball.read_bytes()

        return app, _run_remote

    def submit(self, spec_path: Path, *, results_dir: Path) -> JobHandle:
        """Run the job on Modal (synchronously) and cache the tarball locally."""
        results_dir.mkdir(parents=True, exist_ok=True)
        handle_id = str(uuid.uuid4())
        tarball = results_dir / f"{handle_id}.tar.gz"

        spec_json = spec_path.read_text()
        files = {
            f.name: f.read_bytes()
            for f in spec_path.parent.iterdir()
            if f.is_file() and f.name != spec_path.name
        }
        app, run_remote = self._build_app()
        LOG.info("modal submit: running job on %s (gpu=%s)", self.app_name, self.gpu_type)
        with app.run():
            data: bytes = run_remote.remote(spec_json, files)
        tarball.write_bytes(data)
        _RESULTS[handle_id] = tarball
        return JobHandle(
            backend=self.name,
            id=handle_id,
            submitted_at=datetime.now(UTC).isoformat(timespec="seconds"),
            results_dir=str(results_dir),
            tarball=str(tarball),
        )

    def poll(self, handle: JobHandle) -> JobStatus:
        """Report status (submit is synchronous, so a known handle is done)."""
        tarball = _RESULTS.get(handle.id) or Path(getattr(handle, "tarball", ""))
        state = "succeeded" if Path(tarball).exists() else "failed"
        return JobStatus(handle=handle, state=state, progress=1.0 if state == "succeeded" else None)

    def fetch(self, handle: JobHandle) -> Path:
        """Return the locally-cached results tarball written by :meth:`submit`."""
        tarball = _RESULTS.get(handle.id) or Path(getattr(handle, "tarball", ""))
        if not Path(tarball).exists():
            raise RuntimeError(f"modal job {handle.id} produced no results at {tarball}")
        return Path(tarball)

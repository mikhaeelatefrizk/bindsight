# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Modal serverless-GPU runner.

`Modal <https://modal.com/>`_ provisions a GPU, runs
:mod:`bindsight.runners.job_exec` (the same executor as the local/Kaggle
paths), and tears down — subject to Modal's usage billing. Requires the
``runners`` extra (``modal``) and a Modal token (``modal token new``).

``import modal`` happens lazily inside the methods via :func:`_require_modal`,
so ``import bindsight`` works without the extra installed. Execution is
synchronous from the caller's point of view (``submit`` runs the job and caches
the tarball; ``fetch`` returns it), matching the Designer ``submit→fetch``
contract.

The initial image installs the caller's exact published Bindsight version from
PyPI using pip. Its remote function independently verifies that release wheel,
uses the same managed GPU provisioner as the other backends, then executes the
job with the provisioned interpreter. Unpublished local changes are not sent.
No end-to-end Modal GPU run is established by the CPU tests.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bindsight.cost import estimate
from bindsight.runners.protocol import CostEstimate, JobHandle, JobStatus
from bindsight.runners.release_bootstrap import published_version


def _ATEXIT_CLEANUP(path: Path) -> None:
    """Remove a scratch directory when the process ends.

    These were created with ``mkdtemp`` and never removed. On a long-lived
    process -- the hosted app is the obvious one -- that is one directory per
    invocation, retained for the container's lifetime.
    """
    import atexit
    import shutil

    atexit.register(shutil.rmtree, path, True)


LOG = logging.getLogger(__name__)

MAX_PAYLOAD_BYTES = 128 * 1024 * 1024

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
        if gpu_type not in _MODAL_GPU:
            raise ValueError(
                f"Unsupported Modal GPU {gpu_type!r}; choose one of {sorted(_MODAL_GPU)}"
            )
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
        from bindsight import __version__

        release_version = published_version(__version__)
        modal = _require_modal()
        image = (
            # Modal supplies the GPU driver; the canonical provisioner owns
            # the matching scientific Python, CUDA libraries and tool pins.
            modal.Image.debian_slim(python_version="3.11")
            .apt_install("git", "build-essential", "ca-certificates")
            .pip_install("certifi>=2026.10.19", "psutil>=5.9,<8", f"bindsight=={release_version}")
        )
        app = modal.App(self.app_name)
        gpu = _MODAL_GPU[self.gpu_type]

        @app.function(gpu=gpu, image=image, timeout=self.timeout_s)  # type: ignore[untyped-decorator]
        def _run_remote(spec_json: str, files: dict[str, bytes]) -> bytes:
            import json as _json
            import os
            import subprocess
            import tempfile
            from pathlib import Path as _P
            from pathlib import PurePosixPath

            from bindsight.runners.gpu_runtime import provision
            from bindsight.runners.release_bootstrap import download_release_wheel

            work = _P(tempfile.mkdtemp(prefix="bindsight_modal_"))
            _ATEXIT_CLEANUP(work)
            if len(spec_json.encode("utf-8")) > 2 * 1024 * 1024:
                raise ValueError("The job specification exceeds its size limit.")
            if len(files) > 1024 or sum(len(data) for data in files.values()) > MAX_PAYLOAD_BYTES:
                raise ValueError("The job payload exceeds its size limit.")
            spec_dir = work / "spec"
            spec_dir.mkdir(parents=True, exist_ok=True)
            (spec_dir / "spec.json").write_text(spec_json, encoding="utf-8", newline="\n")
            for name, data in files.items():
                destination = spec_dir / name
                if (
                    not name
                    or "\\" in name
                    or ".." in PurePosixPath(name).parts
                    or not destination.resolve().is_relative_to(spec_dir.resolve())
                    or destination.resolve()
                    in {spec_dir.resolve(), (spec_dir / "spec.json").resolve()}
                ):
                    raise ValueError(f"payload entry escapes the spec directory: {name}")
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(data)
            spec = _json.loads(spec_json)
            mode = spec.get("extra_params", {}).get("mode", "design_and_validate")
            if mode not in {"design_and_validate", "validate_only"}:
                raise ValueError("Unsupported GPU job mode.")
            wheel = download_release_wheel(release_version, work / "release")
            receipt = provision(work / "runtime", source=wheel, mode=mode, gpu_index=0)
            environment = dict(os.environ)
            for key in (
                "PYTHONPATH",
                "PYTHONHOME",
                "PYTHONSTARTUP",
                "PYTHONUSERBASE",
                "BINDSIGHT_BOLTZ_BIN",
                "BINDSIGHT_LOCAL_IMAGE",
                "BINDSIGHT_DESIGN_PYTHON",
            ):
                environment.pop(key, None)
            environment.update(receipt["execution_environment"])
            tarball = work / "results.tar.gz"
            subprocess.run(
                [
                    receipt["boltz_python"],
                    "-I",
                    "-m",
                    "bindsight.runners.job_exec",
                    str(spec_dir / "spec.json"),
                    str(tarball),
                ],
                env=environment,
                check=True,
            )
            return tarball.read_bytes()

        return app, _run_remote

    def submit(self, spec_path: Path, *, results_dir: Path) -> JobHandle:
        """Run the job on Modal (synchronously) and cache the tarball locally."""
        results_dir.mkdir(parents=True, exist_ok=True)
        handle_id = str(uuid.uuid4())
        tarball = results_dir / f"{handle_id}.tar.gz"

        spec_json = spec_path.read_text(encoding="utf-8")
        if len(spec_json.encode("utf-8")) > 2 * 1024 * 1024:
            raise ValueError("The job specification exceeds its size limit.")
        files: dict[str, bytes] = {}
        total = 0
        for path in spec_path.parent.rglob("*"):
            if path.is_symlink():
                raise ValueError("A Modal payload must not contain symlinks.")
            if path.is_file() and path != spec_path:
                total += path.stat().st_size
                if total > MAX_PAYLOAD_BYTES or len(files) >= 1024:
                    raise ValueError("The job payload exceeds its size limit.")
                files[path.relative_to(spec_path.parent).as_posix()] = path.read_bytes()
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

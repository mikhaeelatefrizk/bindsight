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
PyPI after verifying its digest, size and metadata. Its remote function rechecks that wheel,
uses the same managed GPU provisioner as the other backends, then executes the
job with the provisioned interpreter. An explicit ``bindsight_wheel`` transports a hash-checked candidate instead.
Automatic Modal source mounting is disabled so it cannot replace installed code.
No end-to-end Modal GPU run is established by the CPU tests.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bindsight.cost import estimate
from bindsight.runners.hosted_source import candidate_source
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
    "A10G": "A10",
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


def _run_remote(
    spec_json: str, files: dict[str, bytes], source: dict[str, Any] | None = None
) -> bytes:
    """Module-level Modal entry point loaded from the selected installed wheel."""
    import json as _json
    import tempfile
    from pathlib import Path as _P
    from pathlib import PurePosixPath

    from bindsight import __version__
    from bindsight.runners.gpu_runtime import provision
    from bindsight.runners.hosted_job import run_hosted_job
    from bindsight.runners.hosted_source import verify_candidate
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
            or destination.resolve() in {spec_dir.resolve(), (spec_dir / "spec.json").resolve()}
        ):
            raise ValueError(f"payload entry escapes the spec directory: {name}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
    spec = _json.loads(spec_json)
    mode = spec.get("extra_params", {}).get("mode", "design_and_validate")
    if mode not in {"design_and_validate", "validate_only"}:
        raise ValueError("Unsupported GPU job mode.")
    if source is not None:
        wheel = _P("/opt/bindsight-candidate") / source["filename"]
        verify_candidate(wheel, source)
    else:
        wheel = download_release_wheel(published_version(__version__), _P("/opt/bindsight-release"))
    receipt = provision(work / "runtime", source=wheel, mode=mode, gpu_index=0)
    tarball = work / "results.tar.gz"
    run_hosted_job(
        backend="modal",
        root=work / "runtime",
        receipt=receipt,
        source=wheel,
        source_kind="candidate-wheel" if source is not None else "published-wheel",
        spec=spec_dir / "spec.json",
        output=tarball,
    )
    return tarball.read_bytes()


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
        bindsight_wheel: Path | None = None,
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
        self.bindsight_wheel = Path(bindsight_wheel) if bindsight_wheel is not None else None
        self._source = candidate_source(self.bindsight_wheel) if self.bindsight_wheel else None

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
        import inspect
        import shlex

        from bindsight import __version__

        modal = _require_modal()
        image = (
            modal.Image.debian_slim(python_version="3.11")
            .apt_install("git", "build-essential", "ca-certificates")
            .pip_install("certifi>=2026.10.19", "psutil>=5.9,<8")
        )
        if self.bindsight_wheel is None:
            from bindsight.runners import release_bootstrap

            version = published_version(__version__)
            remote_path = f"/opt/bindsight-release/bindsight-{version}-py3-none-any.whl"
            bootstrap = inspect.getsource(release_bootstrap) + (
                "\ndownload_release_wheel(" + repr(version) + ", Path('/opt/bindsight-release'))\n"
            )
            image = image.run_commands(
                "python -c " + shlex.quote(bootstrap),
                "python -m pip install --no-input " + shlex.quote(remote_path),
            )
        else:
            import tempfile

            from bindsight.runners import hosted_source

            assert self._source is not None
            # Snapshot exact validated bytes before Modal's deferred image upload.
            directory = Path(tempfile.mkdtemp(prefix="bindsight_modal_source_"))
            _ATEXIT_CLEANUP(directory)
            wheel = hosted_source.write_candidate(
                self.bindsight_wheel.read_bytes(), self._source, directory
            )
            remote_path = "/opt/bindsight-candidate/" + wheel.name
            bootstrap = inspect.getsource(hosted_source) + (
                "\nverify_candidate(Path(" + repr(remote_path) + "), " + repr(self._source) + ")\n"
            )
            image = image.add_local_file(str(wheel), remote_path, copy=True).run_commands(
                "python -c " + shlex.quote(bootstrap),
                "python -m pip install --no-input " + shlex.quote(remote_path),
            )
        # No local package automount: imported code comes from the installed
        # published release or verified candidate, including this entry point.
        app = modal.App(self.app_name)
        gpu = _MODAL_GPU[self.gpu_type]

        run_remote = app.function(
            gpu=gpu,
            image=image,
            timeout=self.timeout_s,
            include_source=False,
            cpu=4,
            memory=16384,
        )(_run_remote)

        return app, run_remote

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
            data: bytes = run_remote.remote(spec_json, files, self._source)
        tarball.write_bytes(data)
        from bindsight.runners.hosted_job import archive_status

        status = archive_status(tarball)
        if status.get("outcome") != "completed" or status.get("returncode") != 0:
            raise RuntimeError(f"Modal job did not complete; evidence retained at {tarball}")
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

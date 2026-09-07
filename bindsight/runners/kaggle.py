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
import builtins
import contextlib
import gzip
import json
import logging
import time
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bindsight.cost import estimate
from bindsight.runners import kaggle_kernel
from bindsight.runners.protocol import CostEstimate, JobHandle, JobStatus

LOG = logging.getLogger(__name__)

#: Ceiling on the generated kernel script, in bytes.
#:
#: Kaggle rejects an oversized kernel at push time, which is cheap, but the
#: error is opaque. Checking here names the two things that actually grow the
#: script: the embedded target structure and the embedded wheel.
_MAX_KERNEL_BYTES = 900_000


#: Consecutive failed polls tolerated before a wait is abandoned.
#:
#: At the default 30-second interval this rides out roughly ten minutes of
#: network trouble. The cost of being wrong in each direction is asymmetric: a
#: needless retry costs one HTTPS request, while giving up too early abandons a
#: kernel that keeps consuming a fixed weekly GPU quota with nothing waiting on
#: its result.
_POLL_FAILURE_LIMIT = 20


class KaggleUnavailable(RuntimeError):
    """The Kaggle client is not installed — a condition no retry can heal."""


def _require_kaggle() -> Any:
    """Import + authenticate the Kaggle API, with a clear error if missing."""
    try:
        from kaggle.api.kaggle_api_extended import KaggleApi
    except ImportError as e:
        raise KaggleUnavailable(
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


@contextlib.contextmanager
def _default_text_encoding(encoding: str) -> Iterator[None]:
    """Make encoding-less text ``open()`` calls use ``encoding`` inside this block.

    The Kaggle client writes the kernel log with a plain ``open(path, "w")``, so
    it inherits the interpreter's locale encoding. Kernel output carries
    micromamba's progress glyphs (U+29D6, U+2714), which cp1252 cannot represent,
    so on a default Windows install the write raises — discarding a completed GPU
    run over a log file.

    Running the whole interpreter with ``PYTHONUTF8=1`` fixes it, but that is a
    startup setting and cannot be applied to a library call. Narrowing the
    default for the duration of one download can.

    Only calls that pass no ``encoding`` and no ``mode`` containing ``b`` are
    affected; binary reads and writes, including the results tarball, go through
    untouched.

    Args:
        encoding: the encoding to use when a caller specifies none.

    Yields:
        None, for the duration of the override.
    """
    real_open = builtins.open

    def _open(file: Any, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        if "b" not in mode and "encoding" not in kwargs:
            kwargs["encoding"] = encoding
            kwargs.setdefault("errors", "replace")
        return real_open(file, mode, *args, **kwargs)

    builtins.open = _open
    try:
        yield
    finally:
        builtins.open = real_open


class KaggleRunner:
    """Headless Kaggle Notebooks runner (push kernel, poll, pull tarball)."""

    name = "kaggle"

    def __init__(
        self,
        *,
        designer: str = "rfdiff_mpnn",
        gpu_type: str = kaggle_kernel.KAGGLE_COST_GPU,
        username: str | None = None,
        poll_interval_s: int = 30,
        bindsight_ref: str | None = None,
        bindsight_wheel: Path | str | None = None,
    ) -> None:
        self.designer = designer
        self.gpu_type = gpu_type
        self.username = username
        self.poll_interval_s = poll_interval_s
        # Git ref the kernel installs bindsight from (default branch if None).
        self.bindsight_ref = bindsight_ref
        # A wheel built from the working tree. When set it wins over the ref,
        # because it is the code that launched the run rather than whatever the
        # branch resolves to when pip runs on the GPU.
        self.bindsight_wheel = Path(bindsight_wheel) if bindsight_wheel else None
        # Authenticated client, created on first use. See :meth:`_api`.
        self._api_client: Any = None

    def _api(self) -> Any:
        """Return the authenticated Kaggle client, authenticating once.

        ``authenticate()`` is not local: it introspects the access token over
        HTTPS. Calling it on every poll made a job's whole lifetime a chain of
        network round trips, any one of which could end the job — a single
        dropped TLS handshake mid-poll raised ``SSLError`` out of :meth:`fetch`
        and abandoned a kernel that went on to finish on Kaggle with nobody
        waiting for its output. Authenticating once removes both the repeated
        cost and that failure mode.
        """
        if self._api_client is None:
            self._api_client = _require_kaggle()
        return self._api_client

    def _reset_api(self) -> None:
        """Drop the cached client so the next call re-authenticates.

        Used after a failed poll: if the failure was a stale or revoked session
        rather than a transient blip, reauthenticating is what recovers it.
        """
        self._api_client = None

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
        api = self._api()
        results_dir.mkdir(parents=True, exist_ok=True)
        handle_id = uuid.uuid4().hex[:12]
        user = self.username or api.config_values.get("username", "user")
        slug = f"bindsight-{handle_id}"

        # Embed every file in the spec dir (spec.json + target structure),
        # gzipped. Structures are mmCIF or PDB text and compress to roughly a
        # fifth: a full-length receptor is about 550 KB of base64 raw and 120 KB
        # compressed. Without this, that structure plus the working-tree wheel
        # pushes the kernel script past its size ceiling, and the run cannot be
        # submitted at all.
        payload = {
            f.name: base64.b64encode(gzip.compress(f.read_bytes(), 9)).decode("ascii")
            for f in sorted(spec_path.parent.iterdir())
            if f.is_file()
        }
        wheel_b64: str | None = None
        if self.bindsight_wheel is not None:
            if not self.bindsight_wheel.is_file():
                raise FileNotFoundError(f"bindsight wheel not found: {self.bindsight_wheel}")
            wheel_b64 = base64.b64encode(self.bindsight_wheel.read_bytes()).decode("ascii")
            LOG.info(
                "kaggle: embedding %s (%d bytes) — the kernel installs this, not a git ref",
                self.bindsight_wheel.name,
                self.bindsight_wheel.stat().st_size,
            )
        else:
            LOG.warning(
                "kaggle: no wheel given, so the kernel will pip-install bindsight from "
                "%s. Local changes that are not on that ref will NOT run on the GPU. "
                "Pass bindsight_wheel= to run the working tree.",
                self.bindsight_ref or "the default branch",
            )

        script = kaggle_kernel.build_kernel_script(
            handle_id=handle_id,
            payload=payload,
            bindsight_ref=self.bindsight_ref,
            bindsight_wheel_b64=wheel_b64,
            bindsight_wheel_name=(
                self.bindsight_wheel.name
                if self.bindsight_wheel is not None
                else "bindsight-0.0.0-py3-none-any.whl"
            ),
        )
        if len(script.encode("utf-8")) > _MAX_KERNEL_BYTES:
            raise ValueError(
                f"kernel script is {len(script.encode('utf-8')):,} bytes, over the "
                f"{_MAX_KERNEL_BYTES:,}-byte ceiling. The embedded wheel and target "
                "structure are what grow it. Push the branch and pass bindsight_ref "
                "instead of a wheel, or reduce the payload."
            )
        # Only now, once the script is known to be submittable: a refused
        # submit should leave no half-built kernel directory behind.
        work = results_dir / f"kaggle_{handle_id}"
        work.mkdir(parents=True, exist_ok=True)
        (work / "kernel.py").write_text(script, encoding="utf-8")
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
        api = self._api()
        status = api.kernels_status(handle.id)
        name = _status_name(status)
        return JobStatus(handle=handle, state=_STATE_MAP.get(name, "running"), log_tail=name)

    def _await_terminal(self, handle: JobHandle) -> JobStatus:
        """Poll until the kernel reaches a terminal state, surviving network blips.

        A poll is a network call, and networks fail transiently. Treating one
        such failure as fatal is wrong twice over: the kernel keeps running on
        Kaggle with nothing waiting for it, and the GPU hours it burns come out
        of a fixed weekly quota that cannot be refunded. This is not
        hypothetical — a dropped TLS handshake during a routine poll ended the
        client for a design job that was two and a half hours into a T4.

        So a failed poll means "unknown, ask again". Only a sustained outage of
        ``_POLL_FAILURE_LIMIT`` consecutive failures ends the wait, and the last
        error is chained so the cause survives. A missing Kaggle client is
        re-raised at once, because no amount of retrying installs a package.

        Args:
            handle: the job to wait on.

        Returns:
            The terminal :class:`JobStatus` (succeeded, failed or cancelled).

        Raises:
            KaggleUnavailable: the Kaggle client is not installed.
            RuntimeError: polling failed ``_POLL_FAILURE_LIMIT`` times running.
        """
        failures = 0
        while True:
            try:
                st = self.poll(handle)
            except KaggleUnavailable:
                raise
            except Exception as e:
                failures += 1
                if failures >= _POLL_FAILURE_LIMIT:
                    raise RuntimeError(
                        f"kaggle kernel {handle.id}: {failures} consecutive poll "
                        "failures. The kernel may still be running on Kaggle; "
                        "rerun to reattach to it rather than resubmitting."
                    ) from e
                LOG.warning(
                    "kaggle: poll %d/%d for %s failed (%s); retrying in %ds",
                    failures,
                    _POLL_FAILURE_LIMIT,
                    handle.id,
                    e,
                    self.poll_interval_s,
                )
                self._reset_api()
                time.sleep(self.poll_interval_s)
                continue
            failures = 0
            if st.state in {"succeeded", "failed", "cancelled"}:
                return st
            time.sleep(self.poll_interval_s)

    def fetch(self, handle: JobHandle) -> Path:
        """Block until the kernel completes; download the results tarball."""
        api = self._api()
        results_dir = Path(getattr(handle, "results_dir", "."))
        handle_id = getattr(handle, "handle_id", "")
        st = self._await_terminal(handle)
        if st.state != "succeeded":
            raise RuntimeError(f"kaggle kernel {handle.id} finished in state {st.state}")
        self._download_output(api, handle.id, results_dir)
        tarball = results_dir / f"{handle_id}.tar.gz"
        if not tarball.exists():
            raise RuntimeError(f"kaggle kernel {handle.id} produced no tarball at {tarball}")
        return tarball

    @staticmethod
    def _download_output(api: Any, kernel_id: str, results_dir: Path) -> None:
        """Download a finished kernel's output, surviving an unwritable log.

        The Kaggle client writes the kernel log with the interpreter's default
        text encoding. Kernel output contains micromamba's progress glyphs
        (U+29D6, U+2714), so on a cp1252 Windows install the write raises
        ``UnicodeEncodeError`` — and it raises *after* the GPU work is finished,
        which turns a completed hour of a weekly 30-hour quota into a run with
        no results. That is exactly what happened to the first corrected
        designer benchmark: the T4 ran to completion, the tarball was produced,
        and the harness recorded zero designs and an encoding error.

        The log is a convenience; the tarball is the result. So a log failure is
        downgraded to a warning and the download is retried once. The retry
        succeeds because the client skips files that already exist, and the
        truncated log file does, so the second pass reaches the tarball.

        Args:
            api: the authenticated Kaggle API client.
            kernel_id: ``owner/slug`` of the finished kernel.
            results_dir: directory to download into.
        """
        with _default_text_encoding("utf-8"):
            try:
                api.kernels_output(kernel_id, str(results_dir))
                return
            except UnicodeEncodeError as e:
                LOG.warning(
                    "kaggle: could not write the kernel log on this platform (%s). "
                    "The log is not the result; retrying for the tarball.",
                    e,
                )
            # Second pass. Anything already written is skipped, so this picks up
            # where the encoding error interrupted.
            try:
                api.kernels_output(kernel_id, str(results_dir))
            except UnicodeEncodeError as e:
                LOG.warning("kaggle: log still unwritable (%s); checking for the tarball anyway", e)


__all__ = ["KaggleRunner"]

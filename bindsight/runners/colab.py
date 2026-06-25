# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Colab GPU runner.

Colab is a free-or-cheap GPU on-ramp. bindsight doesn't have a way to *launch*
a Colab notebook from the CLI (Google's API doesn't permit it for free-tier
users), so the workflow is:

1. ``submit()`` writes a self-contained ``.ipynb`` to disk and prints the
   command for the user to open it in Colab.
2. The notebook installs deps, runs the GPU step, tarballs results, writes
   them to a known location (Google Drive folder, or anywhere the user can
   download from).
3. ``poll()`` checks whether ``results.tar.gz`` has appeared in the local
   results directory (the user downloads it from Drive after the notebook
   finishes).
4. ``fetch()`` returns the local path once it's there.

This is intentionally simple. v0.2 may add Drive API auto-fetch via OAuth;
v0.0.x explicitly favors "user clicks two buttons in Colab" over "wire
OAuth and fight rate limits".
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path

from bindsight.cost import estimate
from bindsight.runners.protocol import CostEstimate, JobHandle, JobStatus

LOG = logging.getLogger(__name__)


class ColabRunner:
    """Local-disk Colab job orchestrator.

    Args:
        notebooks_dir: where templated ``.ipynb`` files are written. Default
            is ``./runs/<run_id>/colab_notebooks/``.
        designer: passed through to the cost estimator.
        n_units_per_target: trajectories per design (used for cost estimate).
        gpu_type: GPU to request from Colab (``T4`` for free, ``A100`` for Pro+).
    """

    name = "colab"

    def __init__(
        self,
        notebooks_dir: Path | None = None,
        *,
        designer: str = "rfdiff_mpnn",
        n_units_per_target: int = 50,
        gpu_type: str = "T4",
    ) -> None:
        self.notebooks_dir = Path(notebooks_dir) if notebooks_dir else None
        self.designer = designer
        self.n_units_per_target = n_units_per_target
        self.gpu_type = gpu_type

    def estimate_cost(self, spec_size: int) -> CostEstimate:
        """Estimate cost for ``spec_size`` design trajectories."""
        return estimate(
            backend=self.name,
            stage="design",
            plugin=self.designer,
            n_units=spec_size,
            gpu_type=self.gpu_type,
        )

    def submit(self, spec_path: Path, *, results_dir: Path) -> JobHandle:
        """Write a Colab notebook + spec to disk, return a JobHandle.

        The user is responsible for opening the notebook in Colab. The
        ``handle.id`` is used as the cache key for results.
        """
        results_dir.mkdir(parents=True, exist_ok=True)
        handle_id = str(uuid.uuid4())
        notebook_dest = results_dir / f"{handle_id}.ipynb"

        notebook = self._build_notebook(spec_path=spec_path, handle_id=handle_id)
        notebook_dest.write_text(notebook)

        LOG.info(
            "Colab notebook written to %s. Open it in Colab, run all cells, "
            "and place the resulting %s.tar.gz in %s.",
            notebook_dest,
            handle_id,
            results_dir,
        )

        return JobHandle(
            backend=self.name,
            id=handle_id,
            submitted_at=datetime.now(UTC).isoformat(timespec="seconds"),
            notebook_path=str(notebook_dest),
            results_dir=str(results_dir),
        )

    def poll(self, handle: JobHandle) -> JobStatus:
        """Check whether the user has placed the results tarball in the dir."""
        results_dir = Path(handle.model_extra.get("results_dir") or ".")
        archive = results_dir / f"{handle.id}.tar.gz"
        if archive.exists():
            return JobStatus(handle=handle, state="succeeded", progress=1.0)
        return JobStatus(
            handle=handle,
            state="running",
            progress=None,
            log_tail="awaiting results.tar.gz from Colab user",
        )

    def fetch(self, handle: JobHandle) -> Path:
        """Return the local path to the results tarball.

        Raises ``FileNotFoundError`` if the user hasn't dropped the tarball
        in the configured results_dir yet — call :meth:`poll` first.
        """
        results_dir = Path(handle.model_extra.get("results_dir") or ".")
        archive = results_dir / f"{handle.id}.tar.gz"
        if not archive.exists():
            raise FileNotFoundError(
                f"results tarball not yet available: {archive}. "
                "Run the Colab notebook and place the output here."
            )
        return archive

    # ---------------------------------------------------------------- #
    # Notebook construction                                            #
    # ---------------------------------------------------------------- #
    def _build_notebook(self, *, spec_path: Path, handle_id: str) -> str:
        """Build the design + validation notebook with REAL RFdiff+MPNN+Boltz cells.

        Delegates to :mod:`bindsight.runners.notebook_content` which holds the
        canonical install + inference cell templates patterned on ColabDesign,
        dl_binder_design, and the upstream Boltz-2 README.
        """
        import json as _json  # local alias keeps it out of module init time

        from bindsight.runners.notebook_content import build_design_notebook

        spec: dict = {}
        if Path(spec_path).exists():
            try:
                spec = _json.loads(Path(spec_path).read_text())
            except _json.JSONDecodeError:
                spec = {}

        notebook = build_design_notebook(
            handle_id=handle_id,
            designer=self.designer,
            gpu_type=self.gpu_type,
            spec=spec,
        )
        return _json.dumps(notebook, indent=1)

# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Generate a portable Colab notebook and collect its downloaded result archive.

``submit()`` writes a self-contained notebook with the job specification and,
when explicitly selected, an integrity-checked candidate wheel. Open it in
Colab, select a compatible GPU, and run its cells. Download the original
``<handle>.tar.gz`` to the local results directory; ``poll()`` and ``fetch()``
look for that exact file. The CLI's generated design notebooks additionally
retain matching ``.spec.json`` files for safe import by ``bindsight validate``.

This runner uses a manual notebook handoff. The separate official Colab CLI
supports Linux/macOS; this module does not depend on it or launch cloud jobs.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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
        bindsight_wheel: Path | None = None,
    ) -> None:
        self.notebooks_dir = Path(notebooks_dir) if notebooks_dir else None
        self.designer = designer
        self.n_units_per_target = n_units_per_target
        self.gpu_type = gpu_type
        self.bindsight_wheel = Path(bindsight_wheel) if bindsight_wheel is not None else None

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
        notebook_dest.write_text(notebook, encoding="utf-8", newline="\n")

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
        results_dir = Path((handle.model_extra or {}).get("results_dir") or ".")
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
        results_dir = Path((handle.model_extra or {}).get("results_dir") or ".")
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

        spec: dict[str, Any] = {}
        if Path(spec_path).exists():
            try:
                spec = _json.loads(Path(spec_path).read_text(encoding="utf-8"))
            except _json.JSONDecodeError:
                spec = {}

        notebook = build_design_notebook(
            handle_id=handle_id,
            designer=self.designer,
            gpu_type=self.gpu_type,
            spec=spec,
            bindsight_wheel=self.bindsight_wheel,
        )
        return _json.dumps(notebook, indent=1)

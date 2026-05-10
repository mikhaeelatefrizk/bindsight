"""Colab GPU runner.

Colab is a free-or-cheap GPU on-ramp. xpr2bind doesn't have a way to *launch*
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

from xpr2bind.cost import estimate
from xpr2bind.runners.protocol import CostEstimate, JobHandle, JobStatus

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
        from xpr2bind.runners.notebook import (
            build_notebook,
            code_cell_from_template,
            markdown_cell,
        )

        spec_text = Path(spec_path).read_text() if Path(spec_path).exists() else ""
        intro = markdown_cell(
            f"# xpr2bind Colab job — `{handle_id}`\n\n"
            f"**Designer:** `{self.designer}`  \n"
            f"**GPU:** `{self.gpu_type}`  \n"
            f"**Job ID:** `{handle_id}`\n\n"
            "Run all cells (`Runtime → Run all`). The final cell zips the "
            f"results into `{handle_id}.tar.gz` — download it from the file "
            "browser into your local `results_dir`.\n"
        )
        # Each cell is an independent template render so the bundled notebook
        # is fully self-contained and easy to read on Colab.
        install_cell = code_cell_from_template(
            "!pip install -q boltz==2.* &> /dev/null\n"
            "import os, json, tarfile, pathlib, datetime\n"
            "JOB_ID = '{{ handle_id }}'\n"
            "OUT = pathlib.Path(f'/content/{JOB_ID}_out')\n"
            "OUT.mkdir(parents=True, exist_ok=True)\n",
            {"handle_id": handle_id},
        )
        spec_cell = code_cell_from_template(
            "SPEC = json.loads('''{{ spec_text | replace('\\\\', '\\\\\\\\') }}''') "
            "if '{{ spec_text }}' else {}\n"
            "print('Loaded spec keys:', list(SPEC.keys()))\n",
            {"spec_text": spec_text or "{}"},
        )
        designer_cell = code_cell_from_template(
            "# Designer: {{ designer }}\n"
            "# v0.0.x: this is a self-test stub that writes one fake binder PDB.\n"
            "# v0.1 will git-clone RFdiffusion + ProteinMPNN here and run the real pipeline.\n"
            "(OUT / 'design_0.pdb').write_text('REMARK xpr2bind {{ designer }} stub\\n')\n"
            "(OUT / 'metrics.jsonl').write_text("
            "json.dumps({'binder_id': 'design_0', 'designer': '{{ designer }}', "
            "'note': 'stub output'}) + '\\n')\n",
            {"designer": self.designer},
        )
        package_cell = code_cell_from_template(
            "tarball = pathlib.Path(f'/content/{JOB_ID}.tar.gz')\n"
            "with tarfile.open(tarball, 'w:gz') as tf:\n"
            "    tf.add(OUT, arcname=JOB_ID)\n"
            "print('Wrote', tarball, '— download via the file browser on the left.')\n",
            {},
        )

        notebook = build_notebook(
            cells=[intro, install_cell, spec_cell, designer_cell, package_cell],
            gpu=self.gpu_type,  # type: ignore[arg-type]
            title=f"xpr2bind {self.designer} {handle_id[:8]}",
        )
        # Return as JSON string for write_text — write_notebook serializes too,
        # but we want callers to control the destination.
        import json as _json  # local alias keeps it out of module init time

        return _json.dumps(notebook, indent=1)

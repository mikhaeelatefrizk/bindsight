# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""BindCraft designer plugin (premium GPU path).

BindCraft (`Pacesa et al., Nature 2025 <https://www.nature.com/articles/s41586-025-09429-6>`_,
MIT) is a one-shot AF2-based binder design pipeline with reported ~10-100%
experimental success rates. Trade-off vs. RFdiff+MPNN: needs ≥32 GB VRAM, so
free Colab T4 (16 GB) doesn't fit; you need Colab Pro+ A100 or paid Modal.

The GPU work runs in :mod:`bindsight.runners.job_exec`; this module owns the
plugin entry point and the spec it builds.
"""

from __future__ import annotations

import logging
from pathlib import Path

from bindsight.design._common import make_cache_key, submit_via_runner
from bindsight.design.protocol import DesignResult, DesignSpec
from bindsight.runners.protocol import GPURunner
from bindsight.runners.tools import BINDCRAFT_COMMIT

LOG = logging.getLogger(__name__)


class BindCraftDesigner:
    """Plugin: BindCraft one-shot binder design (≥32 GB VRAM)."""

    name = "bindcraft"
    version = "0.1.0"
    license_notice = "BindCraft: MIT. Commercial-OK. Requires ≥32 GB VRAM."

    def make_spec(
        self,
        *,
        target_uniprot: str,
        target_structure_path: Path,
        epitope_residues: list[int],
        epitope_chain: str = "A",
        n_trajectories: int = 10,
        seed: int = 0,
    ) -> DesignSpec:
        """Build a DesignSpec carrying the BindCraft parameters."""
        return DesignSpec(
            target_uniprot=target_uniprot,
            target_structure_path=str(target_structure_path),
            epitope_chain=epitope_chain,
            epitope_residues=epitope_residues,
            n_trajectories=n_trajectories,
            seed=seed,
            extra_params={
                "designer": self.name,
                "designer_version": self.version,
                "bindcraft_commit": BINDCRAFT_COMMIT,
            },
        )

    def submit(self, spec: DesignSpec, runner: GPURunner) -> DesignResult:
        """Ship the spec+structure to the runner and stage the results."""
        cache_key = make_cache_key(spec, extra=(BINDCRAFT_COMMIT,))
        return submit_via_runner(
            spec,
            runner,
            designer_name=self.name,
            designer_version=self.version,
            designer_commit_sha=BINDCRAFT_COMMIT,
            cache_key=cache_key,
        )

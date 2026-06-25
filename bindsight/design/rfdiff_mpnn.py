# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""RFdiffusion + ProteinMPNN designer plugin.

The default designer. Generates backbones with `RFdiffusion
<https://github.com/RosettaCommons/RFdiffusion>`_ (BSD-3, weights open) and
fills in sequences with `ProteinMPNN <https://github.com/dauparas/ProteinMPNN>`_
(MIT). Both fit in 16 GB VRAM, so this designer works on free Colab T4 — that
is why it's the default over BindCraft (which needs ≥32 GB).

The actual GPU work runs in :mod:`bindsight.runners.job_exec` (via whichever
runner backend the user picks). This module owns the plugin entry point and the
spec it builds; the submit body is shared via :mod:`bindsight.design._common`.
"""

from __future__ import annotations

import logging
from pathlib import Path

from bindsight.design._common import make_cache_key, submit_via_runner
from bindsight.design.protocol import DesignResult, DesignSpec
from bindsight.runners.protocol import GPURunner
from bindsight.runners.tools import PROTEINMPNN_COMMIT, RFDIFF_COMMIT

LOG = logging.getLogger(__name__)

# Pinned real upstream revisions (resolved via git ls-remote; see runners.tools).
DEFAULT_RFDIFF_COMMIT = RFDIFF_COMMIT
DEFAULT_PROTEINMPNN_COMMIT = PROTEINMPNN_COMMIT


class RFdiffMPNNDesigner:
    """Plugin: RFdiffusion backbone + ProteinMPNN sequence."""

    name = "rfdiff_mpnn"
    version = "0.1.0"
    license_notice = "RFdiffusion: BSD-3. ProteinMPNN: MIT. Both commercial-OK."

    def make_spec(
        self,
        *,
        target_uniprot: str,
        target_structure_path: Path,
        epitope_residues: list[int],
        epitope_chain: str = "A",
        n_trajectories: int = 50,
        seed: int = 0,
    ) -> DesignSpec:
        """Build a DesignSpec carrying the RFdiff+MPNN parameters."""
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
                "rfdiff_commit": DEFAULT_RFDIFF_COMMIT,
                "proteinmpnn_commit": DEFAULT_PROTEINMPNN_COMMIT,
                "binder_length_min": 50,
                "binder_length_max": 100,
            },
        )

    def submit(self, spec: DesignSpec, runner: GPURunner) -> DesignResult:
        """Ship the spec+structure to the runner and stage the results."""
        cache_key = make_cache_key(
            spec,
            extra=(
                str(spec.extra_params.get("rfdiff_commit", "")),
                str(spec.extra_params.get("proteinmpnn_commit", "")),
            ),
        )
        return submit_via_runner(
            spec,
            runner,
            designer_name=self.name,
            designer_version=self.version,
            designer_commit_sha=DEFAULT_RFDIFF_COMMIT,
            cache_key=cache_key,
        )

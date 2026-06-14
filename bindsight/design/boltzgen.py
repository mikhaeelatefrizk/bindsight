"""BoltzGen designer plugin (newest, watch-list for v0.2 default).

`BoltzGen <https://github.com/HannesStark/boltzgen>`_ (Nov 2025, MIT for both
code and weights) is a "universal binder design" framework from the same
author as Boltz-2. Permissive license + same family as our default validator
makes it the strongest v0.2 candidate to replace RFdiff+MPNN as the default
designer once benchmarked.

The GPU work runs in :mod:`bindsight.runners.job_exec`; this module owns the
plugin entry point and the spec it builds.
"""

from __future__ import annotations

import logging
from pathlib import Path

from bindsight.design._common import make_cache_key, submit_via_runner
from bindsight.design.protocol import DesignResult, DesignSpec
from bindsight.runners.protocol import GPURunner
from bindsight.runners.tools import BOLTZGEN_COMMIT

LOG = logging.getLogger(__name__)


class BoltzGenDesigner:
    """Plugin: BoltzGen universal binder design."""

    name = "boltzgen"
    version = "0.1.0"
    license_notice = "BoltzGen: MIT (code + weights). Commercial-OK."

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
        """Build a DesignSpec carrying the BoltzGen parameters."""
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
                "boltzgen_commit": BOLTZGEN_COMMIT,
            },
        )

    def submit(self, spec: DesignSpec, runner: GPURunner) -> DesignResult:
        """Ship the spec+structure to the runner and stage the results."""
        cache_key = make_cache_key(spec, extra=(BOLTZGEN_COMMIT,))
        return submit_via_runner(
            spec,
            runner,
            designer_name=self.name,
            designer_version=self.version,
            designer_commit_sha=BOLTZGEN_COMMIT,
            cache_key=cache_key,
        )

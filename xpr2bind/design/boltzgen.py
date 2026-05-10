"""BoltzGen designer plugin (newest, watch-list for v0.2 default).

`BoltzGen <https://github.com/HannesStark/boltzgen>`_ (Nov 2025, MIT for both
code and weights) is a "universal binder design" framework from the same
author as Boltz-2. Permissive license + same family as our default validator
makes it the strongest v0.2 candidate to replace RFdiff+MPNN as the default
designer once benchmarked.

v0.0.x ships the plugin shell only.
"""

from __future__ import annotations

import logging

from xpr2bind.design.protocol import DesignResult, DesignSpec
from xpr2bind.runners.protocol import GPURunner

LOG = logging.getLogger(__name__)


class BoltzGenDesigner:
    """Plugin: BoltzGen universal binder design."""

    name = "boltzgen"
    version = "0.0.1"
    license_notice = "BoltzGen: MIT (code + weights). Commercial-OK."

    def make_spec(self, **kwargs) -> DesignSpec:  # type: ignore[override]
        return DesignSpec(
            target_uniprot=kwargs["target_uniprot"],
            target_structure_path=str(kwargs["target_structure_path"]),
            epitope_chain=kwargs.get("epitope_chain", "A"),
            epitope_residues=kwargs["epitope_residues"],
            n_trajectories=kwargs.get("n_trajectories", 50),
            seed=kwargs.get("seed", 0),
            extra_params={
                "designer": self.name,
                "designer_version": self.version,
            },
        )

    def submit(self, spec: DesignSpec, runner: GPURunner) -> DesignResult:
        raise NotImplementedError(
            "BoltzGen live submit lands in v0.1.0-rc2. "
            "Use --designer rfdiff_mpnn for the v0.0.x default path."
        )

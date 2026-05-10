"""BindCraft designer plugin (premium GPU path).

BindCraft (`Pacesa et al., Nature 2025 <https://www.nature.com/articles/s41586-025-09429-6>`_,
MIT) is a one-shot AF2-based binder design pipeline with reported ~10-100%
experimental success rates. Trade-off vs. RFdiff+MPNN: needs ≥32 GB VRAM, so
free Colab T4 (16 GB) doesn't fit; you need Colab Pro+ A100 or paid Modal.

v0.0.x ships the plugin shell; the live BindCraft invocation lands in
v0.1.0-rc2 alongside RFdiff+MPNN and BoltzGen.
"""

from __future__ import annotations

import logging

from xpr2bind.design.protocol import DesignResult, DesignSpec
from xpr2bind.runners.protocol import GPURunner

LOG = logging.getLogger(__name__)


class BindCraftDesigner:
    """Plugin: BindCraft one-shot binder design (≥32 GB VRAM)."""

    name = "bindcraft"
    version = "0.0.1"
    license_notice = "BindCraft: MIT. Commercial-OK. Requires ≥32 GB VRAM."

    def make_spec(self, **kwargs) -> DesignSpec:  # type: ignore[override]
        spec = DesignSpec(
            target_uniprot=kwargs["target_uniprot"],
            target_structure_path=str(kwargs["target_structure_path"]),
            epitope_chain=kwargs.get("epitope_chain", "A"),
            epitope_residues=kwargs["epitope_residues"],
            n_trajectories=kwargs.get("n_trajectories", 10),
            seed=kwargs.get("seed", 0),
            extra_params={
                "designer": self.name,
                "designer_version": self.version,
            },
        )
        return spec

    def submit(self, spec: DesignSpec, runner: GPURunner) -> DesignResult:
        raise NotImplementedError(
            "BindCraft live submit lands in v0.1.0-rc2. "
            "Use --designer rfdiff_mpnn for the v0.0.x default path."
        )

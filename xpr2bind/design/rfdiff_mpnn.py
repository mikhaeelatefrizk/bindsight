"""RFdiffusion + ProteinMPNN designer plugin.

The default designer for v0.1. Generates backbones with `RFdiffusion
<https://github.com/RosettaCommons/RFdiffusion>`_ (BSD-3, weights open) and
fills in sequences with `ProteinMPNN <https://github.com/dauparas/ProteinMPNN>`_
(MIT). Both fit in 16 GB VRAM, so this designer works on free Colab T4 — that
is why it's the default over BindCraft (which needs ≥32 GB).

The actual GPU work happens in a templated Colab/Modal notebook. This module
owns:

- :class:`RFdiffMPNNDesigner` — the plugin entry point (Designer Protocol).
- The Jinja2 notebook template for the GPU job.
- The cache-key construction so reruns are idempotent.

Real "git clone RFdiffusion + invoke" lands in v0.1.0-rc2; v0.0.x ships the
plugin shell and a self-test stub notebook that produces one fake binder PDB
so the orchestration can be wired and tested end-to-end with the mock runner.
"""

from __future__ import annotations

import hashlib
import logging
import shutil
from pathlib import Path

from xpr2bind.design.protocol import DesignResult, DesignSpec
from xpr2bind.runners.protocol import GPURunner

LOG = logging.getLogger(__name__)

# Pin: when we wire the real RFdiffusion call in v0.1.0-rc2, this becomes the
# default revision. Users can override via DesignSpec.extra_params['rfdiff_sha'].
DEFAULT_RFDIFF_COMMIT = "a3a23bbb6c1c9b56b16ef3c9d18ac38e6d83c95b"  # placeholder
DEFAULT_PROTEINMPNN_COMMIT = "8907e6671bfbfc92303b5f79c4b5e6ce47cdef57"  # placeholder


class RFdiffMPNNDesigner:
    """Plugin: RFdiffusion backbone + ProteinMPNN sequence."""

    name = "rfdiff_mpnn"
    version = "0.0.1"
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
        """Submit the design job and return a DesignResult.

        Wraps the runner contract: write the spec as JSON, ask the runner for
        a JobHandle, then return a synchronous DesignResult by blocking on
        :meth:`GPURunner.fetch`.
        """
        cache_key = self._cache_key(spec)
        # Spec serializes to a stable JSON the runner notebook will consume.
        spec_json = spec.model_dump_json(indent=2)
        spec_path = Path(f"_xpr2bind_spec_{cache_key[:8]}.json")
        spec_path.write_text(spec_json)

        try:
            handle = runner.submit(spec_path, results_dir=Path("./runs/_design"))
            archive_path = runner.fetch(handle)
        finally:
            if spec_path.exists():
                spec_path.unlink()

        # Stage the archive into the per-job design directory.
        results_dir = Path("./runs/_design") / cache_key
        results_dir.mkdir(parents=True, exist_ok=True)
        staged_archive = results_dir / "results.tar.gz"
        if archive_path.resolve() != staged_archive.resolve():
            shutil.copy2(archive_path, staged_archive)

        return DesignResult(
            spec=spec,
            results_archive_path=str(staged_archive),
            metrics_jsonl_path=str(results_dir / "metrics.jsonl"),
            designer_name=self.name,
            designer_version=self.version,
            designer_commit_sha=DEFAULT_RFDIFF_COMMIT,
            weights_sha256=None,  # filled in v0.1.0-rc2 once weights are pinned
            cache_key=cache_key,
        )

    @staticmethod
    def _cache_key(spec: DesignSpec) -> str:
        """SHA-256 over the deterministic inputs to a design job."""
        bits = "|".join(
            [
                spec.target_uniprot,
                spec.epitope_chain,
                ",".join(str(r) for r in sorted(spec.epitope_residues)),
                str(spec.binder_length_min),
                str(spec.binder_length_max),
                str(spec.n_trajectories),
                str(spec.seed),
                spec.extra_params.get("rfdiff_commit", ""),
                spec.extra_params.get("proteinmpnn_commit", ""),
            ]
        )
        return hashlib.sha256(bits.encode()).hexdigest()

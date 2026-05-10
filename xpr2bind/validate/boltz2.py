"""Boltz-2 validator plugin.

`Boltz-2 <https://github.com/jwohlwend/boltz>`_ (MIT for both code and
weights) is the default validator. Predicts complex structure + binding
affinity from sequences, ~seconds-minutes per complex on A100. We use:

- ``affinity_pred_value`` for ranking (higher = stronger predicted binder)
- ``affinity_probability_binary`` as an early discovery filter (binder vs decoy)
- ``ipTM`` and ``pae_interaction`` from the structure prediction for QC

v0.0.x ships the plugin shell + the Boltz-2 Colab notebook template. The
live Python integration lands in v0.1.0-rc2, alongside the runner integrations.
"""

from __future__ import annotations

import logging

from xpr2bind.validate.protocol import ValidationResult

LOG = logging.getLogger(__name__)

DEFAULT_BOLTZ2_MODEL = "boltz2_v0.5"  # placeholder; pin the real release in v0.1.0-rc2


class Boltz2Validator:
    """Plugin: Boltz-2 structure + affinity prediction."""

    name = "boltz2"
    version = "0.0.1"
    license_notice = "Boltz-2: MIT (code + weights). Commercial-OK."

    def __init__(self, model_version: str = DEFAULT_BOLTZ2_MODEL) -> None:
        self.model_version = model_version

    def validate(
        self,
        target_uniprot: str,
        binder_id: str,
        binder_sequence: str,
        target_structure_path: str,
    ) -> ValidationResult:
        """Run Boltz-2 (live in v0.1.0-rc2). v0.0.x returns a stub result."""
        # The real call: import boltz, build a YAML config, invoke `boltz predict`,
        # parse the resulting structure + affinity JSON. v0.0.x stub returns NaN
        # so downstream rank stage exercises the merging logic.
        return ValidationResult(
            binder_id=binder_id,
            target_uniprot=target_uniprot,
            iptm=None,
            pae_interaction=None,
            rmsd_to_designed=None,
            affinity_pred_value=None,
            affinity_probability_binary=None,
            validator_name=self.name,
            validator_version=self.version,
            notes="stub validation result — live Boltz-2 invocation lands in v0.1.0-rc2",
        )

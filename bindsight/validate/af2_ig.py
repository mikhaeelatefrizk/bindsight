"""AF2-IG validator plugin (opt-in, non-commercial weights).

AF2 with initial guess (`Bennet/Baker dl_binder_design
<https://github.com/nrbennet/dl_binder_design>`_) is the gold-standard binder
filter — but inherits AF2's weights restriction (non-commercial). The CLI
prints a license banner before invoking this plugin.

v0.0.x ships the plugin shell only.
"""

from __future__ import annotations

from bindsight.validate.protocol import ValidationResult


class AF2IGValidator:
    """Plugin: AlphaFold2 with initial guess (NON-COMMERCIAL weights)."""

    name = "af2_ig"
    version = "0.0.1"
    license_notice = (
        "AF2-IG uses AlphaFold2 weights — DeepMind license restricts commercial use. "
        "See LICENSING.md § 3."
    )

    def validate(
        self,
        target_uniprot: str,
        binder_id: str,
        binder_sequence: str,
        target_structure_path: str,
    ) -> ValidationResult:
        """Stub: returns a placeholder ValidationResult; live AF2-IG in v0.1.0-rc2."""
        return ValidationResult(
            binder_id=binder_id,
            target_uniprot=target_uniprot,
            validator_name=self.name,
            validator_version=self.version,
            notes="stub — live AF2-IG invocation lands in v0.1.0-rc2 behind a license banner",
        )

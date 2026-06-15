"""AF2-IG validator plugin (opt-in, non-commercial weights).

AF2 with initial guess (`Bennett/Baker dl_binder_design
<https://github.com/nrbennet/dl_binder_design>`_) is the gold-standard binder
filter — but inherits AF2's weights restriction (non-commercial). The CLI prints
a license banner before invoking this plugin. The GPU inference runs in
:mod:`bindsight.runners.job_exec`; this plugin's :meth:`validate` parses the
AF2 initial-guess score file the runner produced.
"""

from __future__ import annotations

from pathlib import Path

from bindsight.validate.boltz2 import MissingValidationError
from bindsight.validate.protocol import ValidationResult


class AF2IGValidator:
    """Plugin: AlphaFold2 with initial guess (NON-COMMERCIAL weights)."""

    name = "af2_ig"
    version = "1.0"
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
        """Parse AF2 initial-guess output for this binder from ``validate/<binder_id>/``."""
        from bindsight.runners.tools import parse_af2ig_output

        cwd = Path("validate") / binder_id
        score_file = cwd / "af2_scores.sc"
        if not score_file.exists():
            raise MissingValidationError(
                f"no AF2-IG output found at {score_file}; run the GPU validation step first "
                "(bindsight validate --validator af2_ig)"
            )
        return parse_af2ig_output(score_file, binder_id=binder_id, target_uniprot=target_uniprot)

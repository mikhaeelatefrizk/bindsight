# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Chai-1 validator plugin.

`Chai-1 <https://github.com/chaidiscovery/chai-lab>`_ (Apache-2) is an
alternative to Boltz-2 for cross-model agreement. The GPU inference runs in
:mod:`bindsight.runners.job_exec`; this plugin's :meth:`validate` parses the
Chai output the runner produced into a :class:`ValidationResult`.
"""

from __future__ import annotations

from pathlib import Path

from bindsight.validate.boltz2 import MissingValidationError
from bindsight.validate.protocol import ValidationResult


class Chai1rValidator:
    """Plugin: Chai-1 structure + confidence prediction (parser side)."""

    name = "chai1r"
    version = "0.6"
    license_notice = "Chai-1: Apache-2.0. Commercial-OK."

    def validate(
        self,
        target_uniprot: str,
        binder_id: str,
        binder_sequence: str,
        target_structure_path: str,
    ) -> ValidationResult:
        """Parse Chai-1 output for this binder from ``validate/<binder_id>/``."""
        from bindsight.runners.tools import parse_chai_output

        cwd = Path("validate") / binder_id
        if not cwd.exists():
            raise MissingValidationError(
                f"no Chai-1 output found at {cwd}; run the GPU validation step first "
                "(bindsight validate --validator chai1r)"
            )
        return parse_chai_output(cwd, binder_id=binder_id, target_uniprot=target_uniprot)

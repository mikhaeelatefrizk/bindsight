# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Designer plugin interface.

Designers consume ``(structure, epitope)`` and produce designed binders.
Implementations are loaded via the ``bindsight.designers`` entry point group
(see pyproject.toml). Note that the CLI currently validates ``--designer``
against a fixed ``click.Choice`` of the built-in names, and
``runners.job_exec`` dispatches on the same fixed set, so a third-party
designer is not yet usable without also editing those two places. Lifting
that restriction is a roadmap item.

Built-in designers:

- ``rfdiff_mpnn`` (default) — RFdiffusion backbone + ProteinMPNN sequence,
  T4-friendly, BSD-3 / MIT.
- ``bindcraft`` — BindCraft one-shot AF2-based, A100 (≥32 GB), MIT.
- ``boltzgen`` — BoltzGen universal binder design, MIT.
"""

from bindsight.design.protocol import Designer, DesignResult, DesignSpec

__all__ = ["DesignResult", "DesignSpec", "Designer"]

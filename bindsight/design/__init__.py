# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Designer plugin interface.

Designers consume ``(structure, epitope)`` and produce designed binders.
Implementations are loaded via the ``bindsight.designers`` entry point group
(see pyproject.toml), so third parties can ship their own designers without
forking bindsight.

Built-in designers (v0.1):

- ``rfdiff_mpnn`` (default) — RFdiffusion backbone + ProteinMPNN sequence,
  T4-friendly, BSD-3 / MIT.
- ``bindcraft`` — BindCraft one-shot AF2-based, A100 (≥32 GB), MIT.
- ``boltzgen`` — BoltzGen universal binder design (v0.2 plug-in), MIT.
"""

from bindsight.design.protocol import Designer, DesignResult, DesignSpec

__all__ = ["DesignResult", "DesignSpec", "Designer"]

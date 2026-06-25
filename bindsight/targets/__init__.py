# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Target evidence: Open Targets enrichment + a bundled ENSG→UniProt fallback."""

from bindsight.targets.open_targets import OpenTargetsClient, TargetEvidence

__all__ = ["OpenTargetsClient", "TargetEvidence"]

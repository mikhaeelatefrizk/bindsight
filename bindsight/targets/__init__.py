"""Target evidence: Open Targets enrichment + a bundled ENSG→UniProt fallback."""

from bindsight.targets.open_targets import OpenTargetsClient, TargetEvidence

__all__ = ["OpenTargetsClient", "TargetEvidence"]

# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Validator protocol.

Validators take a designed binder (sequence + maybe a structural model) plus
the target, and predict the complex structure + binding affinity. We treat
``Boltz-2`` as the default; users can opt into ``Chai-1r`` for cross-model
agreement or ``AF2-IG`` for the gold-standard Bennet/Baker filtering pipeline
(non-commercial weights — banner shown at CLI time).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field


class ValidationResult(BaseModel):
    """Per-design validation metrics."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    binder_id: str
    target_uniprot: str
    iptm: float | None = Field(None, ge=0.0, le=1.0)
    pae_interaction: float | None = Field(None, ge=0.0)
    rmsd_to_designed: float | None = Field(None, ge=0.0)
    affinity_pred_value: float | None = Field(
        None, description="Predicted affinity (e.g. -log10(KD/M)) for ranking."
    )
    affinity_probability_binary: float | None = Field(
        None,
        ge=0.0,
        le=1.0,
        description="Probability the design is a binder vs. a decoy (early-discovery filter).",
    )
    validator_name: str
    validator_version: str
    notes: str | None = None


@runtime_checkable
class Validator(Protocol):
    """Protocol every validator plugin must implement."""

    name: str
    version: str
    license_notice: str  # Shown by the CLI before each run.

    def validate(
        self,
        target_uniprot: str,
        binder_id: str,
        binder_sequence: str,
        target_structure_path: str,
    ) -> ValidationResult:
        """Run the validator and return metrics."""
        ...

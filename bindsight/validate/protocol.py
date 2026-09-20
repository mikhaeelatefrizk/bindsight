# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Validator protocol.

Validators take a designed binder (sequence + maybe a structural model) plus
the target, and predict the complex structure + binding affinity. We treat
``Boltz-2`` as the default; users can opt into ``Chai-1r`` for cross-model
agreement or ``AF2-IG`` for the gold-standard Bennet/Baker filtering pipeline
(PyRosetta is free only for non-commercial use — banner shown at CLI time).
"""

from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

#: What a validator reports when its tool's version cannot be established.
#:
#: Deliberately not a version-shaped string. Every parser here used to write a
#: literal into :attr:`ValidationResult.validator_version` — ``"2.0.1"``,
#: ``"0.6"``, ``"1.0"`` — regardless of what was installed, which made the one
#: field that looks like provenance answer from a constant. A reader checking
#: which model produced a result got a confident wrong answer instead of an
#: obviously missing one, and no substitute that *looks* like a version fixes
#: that.
UNRECORDED_VERSION = "unrecorded"


def installed_version(distribution: str) -> str | None:
    """The installed version of ``distribution``, or ``None`` if it is absent.

    Validators parse output on whatever machine holds the files, which is not
    always the machine that produced them; ``None`` is the honest answer there,
    and callers turn it into :data:`UNRECORDED_VERSION`.

    Args:
        distribution: the installed distribution name, e.g. ``"boltz"``.

    Returns:
        The version string, or ``None`` when the distribution is not installed.
    """
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version(distribution)
    except PackageNotFoundError:
        return None


class ValidationResult(BaseModel):
    """Per-design validation metrics."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    binder_id: str
    target_uniprot: str
    iptm: float | None = Field(None, ge=0.0, le=1.0)
    ptm: float | None = Field(
        None,
        ge=0.0,
        le=1.0,
        description=(
            "Predicted TM-score for the complex — a structure-confidence metric, NOT an "
            "affinity. Kept in its own field so it can never be mistaken for one."
        ),
    )
    plddt_binder: float | None = Field(
        None,
        ge=0.0,
        le=100.0,
        description=(
            "Mean pLDDT over the binder chain (0-100 scale) — a structure-confidence "
            "metric, NOT an affinity."
        ),
    )
    pae_interaction: float | None = Field(None, ge=0.0)
    rmsd_to_designed: float | None = Field(None, ge=0.0)
    affinity_pred_value: float | None = Field(
        None,
        description=(
            "Predicted binding affinity from a validator that actually predicts one. "
            "LOWER IS STRONGER: Boltz-2 reports a log(IC50)-like value, so -8.0 is a "
            "tighter binder than -6.0, and the ranker inverts it accordingly. Validators "
            "that do not predict affinity MUST leave this None rather than substituting a "
            "confidence metric — see ptm and plddt_binder."
        ),
    )
    affinity_probability_binary: float | None = Field(
        None,
        ge=0.0,
        le=1.0,
        description="Probability the design is a binder vs. a decoy (early-discovery filter).",
    )
    iptm_n_samples: int | None = Field(
        None,
        ge=1,
        description=(
            "How many independent draws ``iptm`` averages. Boltz-2 builds "
            "structures by diffusion, so one draw is a sample, not a "
            "measurement — a reader cannot otherwise tell a single draw from an "
            "average of five. ``None`` means the run predates this field and "
            "the count is unknown."
        ),
    )
    iptm_sd: float | None = Field(
        None,
        ge=0.0,
        description=(
            "Spread of ``iptm`` across those draws, or ``None`` when there was "
            "only one. This is the metric's own noise, measured on the same "
            "input in the same job, and it is what any difference between two "
            "designs has to be larger than to mean anything."
        ),
    )
    validator_name: str
    validator_version: str
    notes: str | None = None

    @property
    def measured(self) -> bool:
        """True when the validator produced at least one metric.

        A result whose every metric is ``None`` is still a valid row: it reaches
        metrics.jsonl, the ranker and the report looking exactly like a design
        that was scored and scored badly. It is not the same thing, and the
        difference is invisible unless something says so.
        """
        return any(
            value is not None
            for value in (
                self.iptm,
                self.ptm,
                self.plddt_binder,
                self.pae_interaction,
                self.affinity_pred_value,
            )
        )


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


#: The phrase a validator's ``notes`` carries when it parsed no metric at all.
#: Checked across every parser by the test suite, so the guarantee is uniform
#: rather than whichever parser someone remembered to handle.
NO_METRICS_NOTE = "no metrics parsed"


def note_unmeasured(
    result: ValidationResult, *, reason: str, log: logging.Logger
) -> ValidationResult:
    """Warn and annotate when ``result`` carries no metric; pass it through otherwise.

    The AF2 initial-guess parser returned an all-``None`` result for a score file
    that was missing, truncated to its header, or written with different column
    names -- three real failure modes, none of which produced a warning or left
    any trace in the row. This is the single place that decides what such a
    result says about itself.
    """
    if result.measured:
        return result
    log.warning(
        "%s parsed no metrics for %s: %s",
        result.validator_name,
        result.binder_id,
        reason,
    )
    existing = (result.notes or "").strip()
    note = f"{NO_METRICS_NOTE}: {reason}"
    return result.model_copy(update={"notes": f"{existing}; {note}" if existing else note})

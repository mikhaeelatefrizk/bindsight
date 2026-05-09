"""User-facing pipeline configuration.

The YAML configs under ``examples/`` (and any user-authored config) are
parsed and validated through these Pydantic v2 models. Validation runs at
load time so misconfigured runs fail loudly *before* any compute is spent.

Add new options here, not by inventing keys in the YAML. Schema additions are
backwards-compatible if every new field has a default; otherwise bump the
schema version (we don't track one yet — first add when we ship a breaking
change).
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------
class InputsConfig(BaseModel):
    """Input file paths."""

    model_config = ConfigDict(extra="forbid")

    counts: Path = Field(
        ...,
        description="Path to the gene × sample counts matrix (TSV or TSV.gz). "
        "Rows are gene IDs, columns are sample IDs, values are integer counts.",
    )
    design: Path = Field(
        ...,
        description="Path to the sample design TSV. Rows are samples, columns include "
        "at least the factors named in ``params.deg.design_formula``.",
    )


# ---------------------------------------------------------------------------
# Per-stage parameters
# ---------------------------------------------------------------------------
class DEGParams(BaseModel):
    """Differential expression parameters."""

    model_config = ConfigDict(extra="forbid")

    design_formula: str = Field(..., description="Patsy formula, e.g. '~ condition'.")
    contrast: list[str] = Field(
        ...,
        min_length=3,
        max_length=3,
        description="Three-element list ``[factor, numerator_level, denominator_level]``.",
    )
    fdr_threshold: float = Field(0.05, ge=0.0, le=1.0)
    log2fc_threshold: float = Field(1.0, ge=0.0)
    min_replicates: int = Field(3, ge=2)
    # When True, only genes with at least this many counts in at least
    # ``min_replicates`` samples are retained (low-count filter).
    min_count: int = Field(10, ge=0)


class TargetDiscoveryParams(BaseModel):
    """Target discovery / surfaceome / specificity parameters."""

    model_config = ConfigDict(extra="forbid")

    # Surfaceome filter
    require_surfy: bool = True
    surfy_allow_offline_fallback: bool = Field(
        False,
        description="If True, fall back to the small bundled SURFY list when the "
        "user cache is empty. Production runs should set this False so the "
        "pipeline fails fast if the cache isn't populated.",
    )

    # Tissue-specificity filter (low expression in vital tissues)
    vital_tissues: list[str] = Field(
        default_factory=lambda: [
            "heart_left_ventricle",
            "brain_cortex",
            "liver",
            "lung",
        ]
    )
    vital_tissue_max_tpm: float = Field(5.0, ge=0.0)

    # Open Targets enrichment
    use_open_targets: bool = True
    require_tractable_modality: list[str] = Field(default_factory=lambda: ["Antibody"])
    max_safety_events: int = Field(5, ge=0)

    # SURFACE-Bind site lookup
    require_surface_bind_site: bool = True
    min_surface_bind_score: float = Field(0.5, ge=0.0, le=1.0)

    # Pipeline cap
    top_n: int = Field(5, ge=1)


class DesignParams(BaseModel):
    """De novo binder design parameters (consumed by the GPU half)."""

    model_config = ConfigDict(extra="forbid")

    designer: Literal["rfdiff_mpnn", "bindcraft", "boltzgen"] = "rfdiff_mpnn"
    n_trajectories: int = Field(50, ge=1)
    binder_length_min: int = Field(50, ge=20)
    binder_length_max: int = Field(100, ge=20)
    seed: int = 42

    @field_validator("binder_length_max")
    @classmethod
    def _check_length_range(cls, v: int, info) -> int:
        lo = info.data.get("binder_length_min")
        if lo is not None and v < lo:
            raise ValueError("binder_length_max must be ≥ binder_length_min")
        return v


class ValidateParams(BaseModel):
    """Validator parameters."""

    model_config = ConfigDict(extra="forbid")

    validator: Literal["boltz2", "chai1r", "af2_ig"] = "boltz2"
    iptm_threshold: float = Field(0.65, ge=0.0, le=1.0)
    pae_interaction_threshold: float = Field(8.0, ge=0.0)


class RankWeights(BaseModel):
    """Composite-score weights. Should sum to 1.0 for interpretability."""

    model_config = ConfigDict(extra="forbid")

    log2fc_specificity: float = Field(0.25, ge=0.0, le=1.0)
    iptm: float = Field(0.30, ge=0.0, le=1.0)
    affinity: float = Field(0.30, ge=0.0, le=1.0)
    sequence_recovery: float = Field(0.15, ge=0.0, le=1.0)


class RankParams(BaseModel):
    """Ranking parameters."""

    model_config = ConfigDict(extra="forbid")

    weights: RankWeights = Field(default_factory=RankWeights)


# ---------------------------------------------------------------------------
# Top-level
# ---------------------------------------------------------------------------
class StageParams(BaseModel):
    """Container for per-stage parameter blocks."""

    model_config = ConfigDict(extra="forbid")

    deg: DEGParams
    target_discovery: TargetDiscoveryParams = Field(default_factory=TargetDiscoveryParams)
    design: DesignParams = Field(default_factory=DesignParams)
    validate_: ValidateParams = Field(default_factory=ValidateParams, alias="validate")
    rank: RankParams = Field(default_factory=RankParams)


class RunConfig(BaseModel):
    """Top-level pipeline configuration parsed from a YAML file."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., description="Human-readable run label, used in the manifest.")
    out_dir: Path = Field(..., description="Output directory. Will be created.")
    inputs: InputsConfig
    params: StageParams
    backend: Literal["colab", "modal", "kaggle", "local_docker", "mock"] = "colab"
    cheap_profile: bool = False

    @classmethod
    def from_yaml(cls, path: Path | str) -> RunConfig:
        """Load and validate a config from a YAML file."""
        text = Path(path).read_text()
        return cls.model_validate(yaml.safe_load(text))

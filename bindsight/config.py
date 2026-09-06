# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
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
from pydantic_core.core_schema import ValidationInfo


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------
class GDCSource(BaseModel):
    """Auto-download spec for a real TCGA cohort from NIH/GDC.

    When set on :class:`InputsConfig` and the ``counts``/``design`` files are
    absent, ``bindsight discover`` fetches the cohort (STAR - Counts) from the
    GDC open-access API and writes the files before running DESeq2.
    """

    model_config = ConfigDict(extra="forbid")

    project: str = Field(..., description="GDC project id, e.g. 'TCGA-BRCA'.")
    n_tumor: int = Field(20, ge=2, description="Number of Primary Tumor samples to fetch.")
    n_normal: int = Field(20, ge=2, description="Number of Solid Tissue Normal samples to fetch.")
    gene_types: list[str] = Field(
        default_factory=lambda: ["protein_coding"],
        description="Gene biotypes to keep ([] keeps all). Protein-coding covers the "
        "surface-antigen targets and keeps DESeq2 tractable.",
    )


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
    download: GDCSource | None = Field(
        None,
        description="Optional: auto-download a real TCGA cohort from GDC when the "
        "counts/design files are missing.",
    )


# Open Targets' tractability vocabulary. The API reports modalities by these
# two-letter codes only, so any other spelling ("Antibody") intersects nothing and
# silently drops every candidate — the filter must reject it at load time instead.
TRACTABLE_MODALITIES: dict[str, str] = {
    "AB": "antibody",
    "OC": "other clinical modality",
    "PR": "PROTAC",
    "SM": "small molecule",
}


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
    # Worker processes pydeseq2 may use. None means "every core", which is the
    # right default on a server and the wrong one on the laptop this pipeline is
    # meant to run on: a multi-hour job that pegs every core makes the machine
    # unusable. Set this to leave headroom.
    n_cpus: int | None = Field(None, ge=1)


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
    # A safety gate that cannot measure a gene has not cleared it. When GTEx has
    # no median-TPM entry for a candidate, treat that as unassessed and withhold
    # it from design carry-forward rather than passing it silently. This matches
    # the contract documented on ``GTExTissueExpression.assess``: only a measured
    # ``safe`` verdict may be presented as having cleared the gate. Set False to
    # accept unmeasured candidates, which is a deliberate loosening.
    gtex_require_measured: bool = True

    # Structure-confidence (disorder) filter — AlphaFold pLDDT (0-100). pLDDT is
    # always computed and surfaced (mean_plddt column); this only gates carry-
    # forward. 0 disables the gate (default). A typical disorder threshold is
    # ~50 (very low confidence / likely disordered) to ~70 (confident).
    min_mean_plddt: float = Field(0.0, ge=0.0, le=100.0)

    # Membrane-topology (extracellular-domain) awareness — UniProt. A binder can
    # only reach the extracellular part of a surface protein. When enabled,
    # discovery annotates each candidate's extracellular ranges and targets the
    # ECD for whole-surface design. Off by default (requires UniProt network).
    use_uniprot_topology: bool = False
    # Gate: drop candidates with no annotated extracellular domain (only meaningful
    # when use_uniprot_topology is True). Off by default.
    require_extracellular_domain: bool = False

    # Cap on how many significant DEGs are carried into target enrichment,
    # ranked by the combined score pi = log2fc x -log10(padj). This is the most
    # consequential filter in discovery: a gene outside the cut never becomes a
    # candidate at all, no matter how surface-exposed or tractable it is. It is
    # a declared parameter rather than a module constant precisely so it lands
    # in the run manifest and can be reported as a gate, not disappear into the
    # ranking.
    enrich_top_k: int = Field(300, ge=1)
    # Whether the surfaceome filter runs BEFORE the enrichment cut.
    #
    # It used to run after, which meant surface antigens competed against every
    # gene in the genome for the enrichment slots. In a real cohort roughly four
    # thousand genes are significant and only a few dozen of the top three
    # hundred are surface proteins, so most of the surfaceome was discarded
    # before it was ever looked at. Measured effect: NECTIN4 in bladder cancer,
    # the target of an approved drug for that exact indication, ranks 259th of
    # 2,104 surface proteins and was still excluded.
    #
    # The old ordering was forced rather than careless: the filter needs UniProt
    # accessions, and those only existed after Open Targets enrichment. The
    # vendored Ensembl-to-accession map removes that dependency, so the cut can
    # now be spent on genes that could actually be targets. The number of Open
    # Targets calls is unchanged.
    surfaceome_prefilter: bool = True

    # Open Targets enrichment
    use_open_targets: bool = True
    require_tractable_modality: list[str] = Field(
        default_factory=lambda: ["AB"],
        description="Open Targets tractability modality codes a candidate must have "
        "(see TRACTABLE_MODALITIES). [] disables the filter.",
    )
    max_safety_events: int = Field(5, ge=0)

    @field_validator("require_tractable_modality")
    @classmethod
    def _check_modalities(cls, v: list[str]) -> list[str]:
        unknown = [m for m in v if m not in TRACTABLE_MODALITIES]
        if unknown:
            valid = ", ".join(f"{code} ({name})" for code, name in TRACTABLE_MODALITIES.items())
            raise ValueError(
                f"unknown tractability modality {unknown}: Open Targets reports "
                f"modalities as {valid}. An unrecognised value matches nothing and "
                "would drop every candidate."
            )
        return v

    # Normal-tissue safety (GTEx) — on-target/off-tumor toxicity. When enabled,
    # candidates whose median expression in any vital tissue exceeds
    # ``vital_tissue_max_tpm`` are flagged ``high_normal_tissue_expression`` and
    # dropped from design. Off by default (requires the GTEx download). Wires the
    # ``vital_tissues`` / ``vital_tissue_max_tpm`` knobs above.
    use_gtex_safety: bool = False

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

    # GPU the run is costed against. None resolves to the backend's default in
    # bindsight.cost, which is how every run behaved before this field existed;
    # the --cheap profile sets it to "T4" so the estimate reflects the hardware
    # the profile actually targets instead of quoting A100 prices.
    gpu_type: str | None = None

    # ESM-2 pre-screen: keep only this many designs for validation. None (the
    # default) validates every design, so behaviour is unchanged unless asked
    # for. See bindsight.design.prescreen.
    prescreen_top_k: int | None = Field(None, ge=1)

    @field_validator("binder_length_max")
    @classmethod
    def _check_length_range(cls, v: int, info: ValidationInfo) -> int:
        lo = info.data.get("binder_length_min")
        if lo is not None and v < lo:
            raise ValueError("binder_length_max must be ≥ binder_length_min")
        return v


class ValidateParams(BaseModel):
    """Validator parameters."""

    model_config = ConfigDict(extra="forbid")

    validator: Literal["boltz2", "chai1r", "af2_ig"] = "boltz2"
    # Quality bars applied to validated binders. ``apply_thresholds`` is False by
    # default so existing runs keep every row and the columns stay descriptive;
    # set it True to have ``bindsight validate`` mark rows that fail. Either way
    # the pass/fail is recorded per row rather than silently dropping designs.
    iptm_threshold: float = Field(0.65, ge=0.0, le=1.0)
    pae_interaction_threshold: float = Field(8.0, ge=0.0)
    apply_thresholds: bool = False


class RankWeights(BaseModel):
    """Composite-score weights.

    The composite is a weighted average over the components *present* for a row
    (missing metrics are excluded, not penalised), so the weights need not sum to
    1.0 — they are renormalised per row. ``developability`` only contributes when
    a binder sequence is available, so it is inert on sequence-less runs.
    """

    model_config = ConfigDict(extra="forbid")

    log2fc_specificity: float = Field(0.25, ge=0.0, le=1.0)
    iptm: float = Field(0.30, ge=0.0, le=1.0)
    affinity: float = Field(0.30, ge=0.0, le=1.0)
    sequence_recovery: float = Field(0.15, ge=0.0, le=1.0)
    developability: float = Field(0.15, ge=0.0, le=1.0)


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

# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the Pydantic RunConfig and per-stage param models."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from bindsight.config import (
    DEGParams,
    DesignParams,
    RankWeights,
    RunConfig,
    StageParams,
    TargetDiscoveryParams,
    ValidateParams,
)


# ---------------------------------------------------------------------------
# DEGParams
# ---------------------------------------------------------------------------
def test_deg_params_minimum() -> None:
    p = DEGParams(design_formula="~ condition", contrast=["condition", "t", "n"])
    assert p.fdr_threshold == pytest.approx(0.05)
    assert p.log2fc_threshold == pytest.approx(1.0)


def test_deg_params_rejects_short_contrast() -> None:
    with pytest.raises(ValidationError):
        DEGParams(design_formula="~ condition", contrast=["condition", "t"])


def test_deg_params_rejects_extra() -> None:
    with pytest.raises(ValidationError):
        DEGParams(
            design_formula="~ condition",
            contrast=["condition", "t", "n"],
            extra_thing=True,
        )


# ---------------------------------------------------------------------------
# DesignParams
# ---------------------------------------------------------------------------
def test_design_params_length_validation() -> None:
    with pytest.raises(ValidationError):
        DesignParams(binder_length_min=100, binder_length_max=50)


def test_design_params_designer_choice() -> None:
    with pytest.raises(ValidationError):
        DesignParams(designer="not_a_designer")


# ---------------------------------------------------------------------------
# Validators / Rank
# ---------------------------------------------------------------------------
def test_validate_params_validator_choice() -> None:
    p = ValidateParams(validator="boltz2")
    assert p.iptm_threshold == pytest.approx(0.65)


def test_rank_weights_default_sums_close_to_one() -> None:
    w = RankWeights()
    total = w.log2fc_specificity + w.iptm + w.affinity + w.sequence_recovery
    assert abs(total - 1.0) < 1e-9


# ---------------------------------------------------------------------------
# StageParams + RunConfig
# ---------------------------------------------------------------------------
def test_stage_params_validate_alias() -> None:
    sp = StageParams.model_validate(
        {
            "deg": {"design_formula": "~ condition", "contrast": ["condition", "t", "n"]},
            "target_discovery": {},
            "design": {},
            "validate": {},  # alias
            "rank": {},
        }
    )
    assert sp.validate_.validator == "boltz2"


def test_run_config_minimal(tmp_path: Path) -> None:
    counts = tmp_path / "c.tsv"
    counts.write_text("g\ts\n1\t2\n")
    design = tmp_path / "d.tsv"
    design.write_text("sample\tcondition\ns\tt\n")
    cfg = RunConfig.model_validate(
        {
            "name": "x",
            "out_dir": str(tmp_path / "out"),
            "inputs": {"counts": str(counts), "design": str(design)},
            "params": {
                "deg": {
                    "design_formula": "~ condition",
                    "contrast": ["condition", "t", "n"],
                }
            },
        }
    )
    assert cfg.name == "x"
    assert cfg.params.deg.fdr_threshold == pytest.approx(0.05)
    assert cfg.params.target_discovery.top_n == 5
    assert cfg.backend == "colab"


def test_run_config_from_yaml_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "name": "round",
                "out_dir": str(tmp_path / "out"),
                "inputs": {"counts": str(tmp_path / "c"), "design": str(tmp_path / "d")},
                "params": {
                    "deg": {
                        "design_formula": "~ condition",
                        "contrast": ["condition", "t", "n"],
                    }
                },
            }
        )
    )
    cfg = RunConfig.from_yaml(path)
    assert cfg.name == "round"


def test_run_config_rejects_extra_top_level(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        RunConfig.model_validate(
            {
                "name": "x",
                "out_dir": str(tmp_path),
                "inputs": {"counts": "c", "design": "d"},
                "params": {
                    "deg": {
                        "design_formula": "~ condition",
                        "contrast": ["condition", "t", "n"],
                    }
                },
                "rogue_top_level": True,
            }
        )


# ---------------------------------------------------------------------------
# Validates the bundled examples/tcga_luad.yaml against the schema.
# Catches accidental drift between docs and code.
# ---------------------------------------------------------------------------
def test_examples_tcga_luad_yaml_validates() -> None:
    repo_root = Path(__file__).parent.parent
    cfg = RunConfig.from_yaml(repo_root / "examples" / "tcga_luad.yaml")
    assert cfg.name == "tcga_luad_v01"
    assert cfg.params.deg.contrast == ["condition", "tumor", "normal"]
    assert cfg.params.target_discovery.top_n == 5
    assert "Antibody" in cfg.params.target_discovery.require_tractable_modality


# ---------------------------------------------------------------------------
# Sanity: TargetDiscoveryParams defaults
# ---------------------------------------------------------------------------
def test_target_discovery_defaults() -> None:
    p = TargetDiscoveryParams()
    assert "heart_left_ventricle" in p.vital_tissues
    assert p.require_surface_bind_site is True

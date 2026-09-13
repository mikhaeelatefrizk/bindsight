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


def test_every_declared_rank_weight_is_accounted_for() -> None:
    """The previous version of this test added four of the five weights by name
    and asserted they summed to 1.0. They do -- because ``developability`` was
    left out. It asserted a property the model's own docstring disclaims ("the
    weights need not sum to 1.0 -- they are renormalised per row"), and it did so
    over a hand-written subset, so adding a weight could not fail it.
    """
    w = RankWeights()
    fields = list(type(w).model_fields)

    assert len(fields) >= 5, fields
    assert sum(getattr(w, f) for f in fields) > 1.0, (
        "the declared weights sum to 1.0; if that is now intended, say so here "
        "and in the RankWeights docstring, which currently says they need not"
    )
    assert all(getattr(w, f) > 0.0 for f in fields), (
        "a default weight of zero silently removes a component from the composite"
    )


def test_scaling_every_weight_does_not_change_the_ranking() -> None:
    """The property the docstring actually claims: weights are renormalised per
    row, so only their ratios matter. This is what "need not sum to 1.0" means,
    and it is checkable."""
    import pandas as pd

    from bindsight.rank import rank_validated

    validated = pd.DataFrame(
        [
            {"binder_id": "a", "target_uniprot": "P1", "iptm": 0.9, "affinity_pred_value": -9.0},
            {"binder_id": "b", "target_uniprot": "P1", "iptm": 0.4, "affinity_pred_value": -5.0},
            {"binder_id": "c", "target_uniprot": "P2", "iptm": 0.7, "affinity_pred_value": -7.0},
        ]
    )
    base = RankWeights()
    scaled = RankWeights(**{f: getattr(base, f) * 3.0 for f in type(base).model_fields})

    first = rank_validated(validated, weights=base)
    second = rank_validated(validated, weights=scaled)

    assert list(first["binder_id"]) == list(second["binder_id"])


def test_an_all_zero_weighting_is_refused() -> None:
    """Every weight may be zero on its own -- turning a component off is a real
    choice -- but all of them at zero made every composite NaN and published the
    input order as a ranking."""
    fields = list(RankWeights.model_fields)

    with pytest.raises(ValidationError, match="every rank weight is zero"):
        RankWeights(**{f: 0.0 for f in fields})


def test_one_positive_weight_is_enough() -> None:
    """The guard must not forbid switching components off."""
    fields = list(RankWeights.model_fields)
    weights = dict.fromkeys(fields, 0.0)
    weights[fields[0]] = 1.0

    assert RankWeights(**weights)


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
def _shipped_example_configs() -> list[Path]:
    """Every example config the repository ships, found rather than listed."""
    repo_root = Path(__file__).parent.parent
    return sorted(p for p in (repo_root / "examples").rglob("*.yaml") if p.is_file())


def test_the_example_sweep_finds_more_than_one_config() -> None:
    """Guards the guard: this test existed for one file while two others shipped
    unvalidated by anything."""
    found = _shipped_example_configs()

    assert len(found) >= 3, f"only {len(found)} example config(s) discovered: {found}"


@pytest.mark.parametrize("path", _shipped_example_configs(), ids=lambda p: p.name)
def test_every_shipped_example_validates(path: Path) -> None:
    """A shipped example that the schema rejects is a broken instruction."""
    assert RunConfig.from_yaml(path)


def test_examples_tcga_luad_yaml_validates() -> None:
    repo_root = Path(__file__).parent.parent
    cfg = RunConfig.from_yaml(repo_root / "examples" / "tcga_luad.yaml")
    assert cfg.name == "tcga_luad_v01"
    assert cfg.params.deg.contrast == ["condition", "tumor", "normal"]
    assert cfg.params.target_discovery.top_n == 5
    # Open Targets reports tractability as short codes; "Antibody" is a string the
    # API never emits, so the shipped config would have filtered out every candidate.
    assert cfg.params.target_discovery.require_tractable_modality == ["AB"]


# ---------------------------------------------------------------------------
# Sanity: TargetDiscoveryParams defaults
# ---------------------------------------------------------------------------
def test_target_discovery_defaults() -> None:
    p = TargetDiscoveryParams()
    assert "heart_left_ventricle" in p.vital_tissues
    assert p.require_surface_bind_site is True
    assert p.require_tractable_modality == ["AB"]


# ---------------------------------------------------------------------------
# Tractability modality vocabulary — an unmatchable code silently emptied the
# candidate table at run time, so it must now fail at load time instead.
# ---------------------------------------------------------------------------
def test_tractable_modality_accepts_open_targets_codes() -> None:
    p = TargetDiscoveryParams(require_tractable_modality=["AB", "SM"])
    assert p.require_tractable_modality == ["AB", "SM"]


def test_tractable_modality_empty_list_disables_the_filter() -> None:
    p = TargetDiscoveryParams(require_tractable_modality=[])
    assert p.require_tractable_modality == []


@pytest.mark.parametrize("bad", [["Antibody"], ["ab"], ["SmallMolecule"], ["AB", "PROTAC"]])
def test_tractable_modality_rejects_values_open_targets_never_emits(bad: list[str]) -> None:
    with pytest.raises(ValidationError) as exc:
        TargetDiscoveryParams(require_tractable_modality=bad)
    message = str(exc.value)
    # The error has to teach the vocabulary, not merely refuse the value.
    for code in ("AB", "OC", "PR", "SM"):
        assert code in message


def test_run_config_rejects_unknown_modality_before_any_compute(tmp_path: Path) -> None:
    """A config carrying the old "Antibody" string must not load at all."""
    with pytest.raises(ValidationError, match="unknown tractability modality"):
        RunConfig.model_validate(
            {
                "name": "x",
                "out_dir": str(tmp_path / "out"),
                "inputs": {"counts": "c", "design": "d"},
                "params": {
                    "deg": {
                        "design_formula": "~ condition",
                        "contrast": ["condition", "t", "n"],
                    },
                    "target_discovery": {"require_tractable_modality": ["Antibody"]},
                },
            }
        )

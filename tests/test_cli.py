# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""CLI smoke tests."""

from __future__ import annotations

from click.testing import CliRunner

from bindsight import __version__
from bindsight.cli import main


def test_cli_help() -> None:
    r = CliRunner().invoke(main, ["--help"])
    assert r.exit_code == 0
    assert "Bridge from RNA-seq" in r.output


def test_cli_version() -> None:
    r = CliRunner().invoke(main, ["--version"])
    assert r.exit_code == 0
    assert __version__ in r.output


def test_cli_verify_licenses() -> None:
    r = CliRunner().invoke(main, ["verify-licenses"])
    assert r.exit_code == 0
    assert "bindsight" in r.output
    assert "Boltz-2" in r.output


def test_cli_discover_rejects_invalid_config(tmp_path) -> None:
    """An ill-shaped YAML must raise a Pydantic ValidationError, not silently run."""
    from pydantic import ValidationError

    cfg = tmp_path / "config.yaml"
    cfg.write_text("name: x\n")
    r = CliRunner().invoke(main, ["discover", str(cfg), "--out", str(tmp_path / "run")])
    assert r.exit_code != 0
    assert isinstance(r.exception, ValidationError)


def test_cli_design_dry_run_prints_cost_and_exits_zero(tmp_path) -> None:
    """``design --dry-run`` prints a cost estimate and exits cleanly without launching."""
    run = tmp_path / "run"
    run.mkdir()
    r = CliRunner().invoke(main, ["design", str(run), "--backend", "modal", "--dry-run"])
    assert r.exit_code == 0
    assert "Cost estimate" in r.output
    assert "modal" in r.output


def test_cli_design_without_targets_exits_2(tmp_path) -> None:
    """Without --dry-run on a run with no designable targets, design exits 2."""
    run = tmp_path / "run"
    run.mkdir()
    r = CliRunner().invoke(main, ["design", str(run), "--backend", "modal"])
    assert r.exit_code == 2
    assert "Cost estimate" in r.output
    assert "nothing to do" in r.output.lower()


def test_cli_validate_prints_cost_panel(tmp_path) -> None:
    run = tmp_path / "run"
    run.mkdir()
    r = CliRunner().invoke(
        main, ["validate", str(run), "--backend", "modal", "--validator", "boltz2"]
    )
    # validate prints the cost estimate, then a 'pending' panel pointing the
    # user at the GPU step. Exit code is 0 (work to do but not an error).
    assert r.exit_code == 0
    assert "Cost estimate" in r.output


def test_cli_validate_af2_ig_shows_license_banner(tmp_path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    r = CliRunner().invoke(main, ["validate", str(run_dir), "--validator", "af2_ig"])
    assert "non-commercial" in r.output

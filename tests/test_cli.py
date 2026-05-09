"""CLI smoke tests."""

from __future__ import annotations

from click.testing import CliRunner

from xpr2bind import __version__
from xpr2bind.cli import main


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
    assert "xpr2bind" in r.output
    assert "Boltz-2" in r.output


def test_cli_discover_rejects_invalid_config(tmp_path) -> None:
    """An ill-shaped YAML must raise a Pydantic ValidationError, not silently run."""
    from pydantic import ValidationError

    cfg = tmp_path / "config.yaml"
    cfg.write_text("name: x\n")
    r = CliRunner().invoke(main, ["discover", str(cfg), "--out", str(tmp_path / "run")])
    assert r.exit_code != 0
    assert isinstance(r.exception, ValidationError)


def test_cli_design_not_implemented(tmp_path) -> None:
    """``design`` is still a stub in v0.0.x — kept for the CLI surface."""
    run = tmp_path / "run"
    run.mkdir()
    r = CliRunner().invoke(main, ["design", str(run)])
    assert r.exit_code == 2
    assert "Not implemented" in r.output


def test_cli_validate_af2_ig_shows_license_banner(tmp_path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    r = CliRunner().invoke(main, ["validate", str(run_dir), "--validator", "af2_ig"])
    assert "non-commercial" in r.output

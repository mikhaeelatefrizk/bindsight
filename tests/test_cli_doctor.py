"""Tests for ``xpr2bind doctor``."""

from __future__ import annotations

from click.testing import CliRunner

from xpr2bind.cli import main


def test_doctor_runs_clean() -> None:
    r = CliRunner().invoke(main, ["doctor"])
    assert r.exit_code == 0
    assert "xpr2bind doctor" in r.output
    assert "python" in r.output
    assert "AlphaFoldDB cache" in r.output

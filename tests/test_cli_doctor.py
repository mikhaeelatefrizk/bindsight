# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for ``bindsight doctor``."""

from __future__ import annotations

from click.testing import CliRunner

from bindsight.cli import main


def test_doctor_runs_clean() -> None:
    r = CliRunner().invoke(main, ["doctor"])
    assert r.exit_code == 0
    assert "bindsight doctor" in r.output
    assert "python" in r.output
    assert "AlphaFoldDB cache" in r.output

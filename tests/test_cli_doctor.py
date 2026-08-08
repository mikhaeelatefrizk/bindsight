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


def test_doctor_reports_real_surfaceome_size() -> None:
    """The surfaceome row must reflect the vendored full list, not the old
    "~10 proteins" fallback message that predated vendoring the real list.

    Rich renders the table into fixed-width columns and may wrap the accession
    count across lines, so assert on the digits of the vendored size rather than
    a contiguous substring.
    """
    from bindsight.surfaceome.surfy import load_vendored_surfy

    vendored = load_vendored_surfy()
    assert vendored is not None
    assert len(vendored) > 1000

    r = CliRunner().invoke(main, ["doctor"])
    assert r.exit_code == 0
    assert "surfaceome" in r.output.lower()
    # The stale, incorrect message must be gone.
    assert "10 proteins" not in r.output

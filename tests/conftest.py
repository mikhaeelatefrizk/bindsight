"""Shared pytest fixtures for bindsight tests."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def fixtures_dir() -> Path:
    """Path to the bundled tests/fixtures directory."""
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def tmp_run_dir(tmp_path: pytest.TempPathFactory) -> Path:
    """A fresh, empty pytest tmp_path with the standard run subdirs."""
    from bindsight.io.paths import run_dir

    return run_dir(tmp_path)

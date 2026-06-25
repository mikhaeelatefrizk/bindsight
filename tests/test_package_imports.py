# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Smoke test: every public module imports cleanly."""

from __future__ import annotations

import importlib

import pytest

PUBLIC_MODULES = [
    "bindsight",
    "bindsight.cli",
    "bindsight.config",
    "bindsight.cost",
    "bindsight.io",
    "bindsight.io.paths",
    "bindsight.pipelines",
    "bindsight.pipelines.discover",
    "bindsight.provenance",
    "bindsight.provenance.manifest",
    "bindsight.targets",
    "bindsight.targets.open_targets",
    "bindsight.targets.ensembl_uniprot",
    "bindsight.surfaceome",
    "bindsight.surfaceome.surfy",
    "bindsight.structures",
    "bindsight.structures.alphafolddb",
    "bindsight.deg",
    "bindsight.deg.pydeseq2_runner",
    "bindsight.epitopes",
    "bindsight.epitopes.surface_bind",
    "bindsight.design",
    "bindsight.design.protocol",
    "bindsight.design.rfdiff_mpnn",
    "bindsight.design.bindcraft",
    "bindsight.design.boltzgen",
    "bindsight.runners",
    "bindsight.runners.protocol",
    "bindsight.runners.mock",
    "bindsight.runners.colab",
    "bindsight.runners.modal_runner",
    "bindsight.runners.kaggle",
    "bindsight.runners.local_docker",
    "bindsight.runners.notebook",
    "bindsight.validate",
    "bindsight.validate.protocol",
    "bindsight.validate.boltz2",
    "bindsight.validate.chai1r",
    "bindsight.validate.af2_ig",
    "bindsight.rank",
    "bindsight.rank.scoring",
    "bindsight.report",
    "bindsight.report.html",
    "bindsight.report.streamlit_app",
    "bindsight.report.webapp",
    "bindsight.export",
    "bindsight.export.ro_crate",
    "bindsight.pipelines.full_run",
    "bindsight.runners.notebook_content",
]


@pytest.mark.parametrize("module_name", PUBLIC_MODULES)
def test_module_imports(module_name: str) -> None:
    """Every public module imports without error."""
    importlib.import_module(module_name)


def test_version_is_set() -> None:
    """``bindsight.__version__`` is a non-empty string."""
    import bindsight

    assert isinstance(bindsight.__version__, str)
    assert bindsight.__version__

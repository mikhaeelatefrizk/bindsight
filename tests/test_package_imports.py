"""Smoke test: every public module imports cleanly."""

from __future__ import annotations

import importlib

import pytest

PUBLIC_MODULES = [
    "xpr2bind",
    "xpr2bind.cli",
    "xpr2bind.config",
    "xpr2bind.cost",
    "xpr2bind.io",
    "xpr2bind.io.paths",
    "xpr2bind.pipelines",
    "xpr2bind.pipelines.discover",
    "xpr2bind.provenance",
    "xpr2bind.provenance.manifest",
    "xpr2bind.targets",
    "xpr2bind.targets.open_targets",
    "xpr2bind.targets.ensembl_uniprot",
    "xpr2bind.surfaceome",
    "xpr2bind.surfaceome.surfy",
    "xpr2bind.structures",
    "xpr2bind.structures.alphafolddb",
    "xpr2bind.deg",
    "xpr2bind.deg.pydeseq2_runner",
    "xpr2bind.epitopes",
    "xpr2bind.epitopes.surface_bind",
    "xpr2bind.design",
    "xpr2bind.design.protocol",
    "xpr2bind.design.rfdiff_mpnn",
    "xpr2bind.design.bindcraft",
    "xpr2bind.design.boltzgen",
    "xpr2bind.runners",
    "xpr2bind.runners.protocol",
    "xpr2bind.runners.mock",
    "xpr2bind.runners.colab",
    "xpr2bind.runners.modal_runner",
    "xpr2bind.runners.kaggle",
    "xpr2bind.runners.local_docker",
    "xpr2bind.runners.notebook",
    "xpr2bind.validate",
    "xpr2bind.validate.protocol",
    "xpr2bind.validate.boltz2",
    "xpr2bind.validate.chai1r",
    "xpr2bind.validate.af2_ig",
    "xpr2bind.rank",
    "xpr2bind.report",
    "xpr2bind.report.html",
    "xpr2bind.report.streamlit_app",
]


@pytest.mark.parametrize("module_name", PUBLIC_MODULES)
def test_module_imports(module_name: str) -> None:
    """Every public module imports without error."""
    importlib.import_module(module_name)


def test_version_is_set() -> None:
    """``xpr2bind.__version__`` is a non-empty string."""
    import xpr2bind

    assert isinstance(xpr2bind.__version__, str)
    assert xpr2bind.__version__

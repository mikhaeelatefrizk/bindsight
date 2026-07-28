# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The hosted demo must not write into the install tree.

``bindsight demo`` caches its TCGA-BRCA cohort under the OS user-cache
directory. The web app used to point at ``examples/demo/counts.tsv`` and
``design.tsv`` instead — files that do not exist and that
``tests/test_demo_e2e.py`` asserts must stay absent. Because the demo config
carries a ``download:`` block, the pipeline would therefore fetch the cohort
and write it *inside the installed package*, which is read-only in the Docker
image behind the Hugging Face Space.

Nothing covered this path. These tests do, without running the pipeline.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("streamlit")

from bindsight.io.paths import cache_dir
from bindsight.report import webapp


@pytest.fixture
def cfg(tmp_path: Path):
    """The demo configuration, built for a temporary output directory."""
    return webapp._demo_config(tmp_path / "run")


def test_demo_reads_from_the_user_cache(cfg, tmp_path: Path) -> None:
    """Inputs resolve into the shared GDC cache, not the package directory."""
    expected = cache_dir("gdc") / "tcga_brca"
    assert cfg.inputs.counts.parent == expected
    assert cfg.inputs.design.parent == expected


def test_demo_does_not_write_into_the_install_tree(cfg) -> None:
    """No input path lands inside the installed bindsight package."""
    package_root = Path(webapp.__file__).resolve().parents[1]
    for path in (cfg.inputs.counts, cfg.inputs.design):
        assert package_root not in path.resolve().parents


def test_demo_counts_filename_declares_its_compression(cfg) -> None:
    """The GDC fetcher writes counts.tsv.gz and pandas infers from the suffix.

    Naming it ``.tsv`` would make ``compression="infer"`` read a gzip stream as
    text, so the extension is load-bearing.
    """
    assert cfg.inputs.counts.name == "counts.tsv.gz"
    assert cfg.inputs.design.name == "design.tsv"


def test_demo_matches_the_cli_demo_paths(cfg) -> None:
    """The web demo and `bindsight demo` share one cached cohort.

    Whichever runs first warms the other; they must not diverge.
    """
    cohort_dir = cache_dir("gdc") / "tcga_brca"
    assert cfg.inputs.counts == cohort_dir / "counts.tsv.gz"
    assert cfg.inputs.design == cohort_dir / "design.tsv"


def test_demo_keeps_the_bundled_config_settings(cfg, tmp_path: Path) -> None:
    """Only the paths are overridden; the shipped demo config is otherwise intact."""
    assert cfg.name == "bindsight_demo_tcga_brca"
    assert cfg.inputs.download is not None
    assert cfg.inputs.download.project == "TCGA-BRCA"
    assert cfg.out_dir == tmp_path / "run"

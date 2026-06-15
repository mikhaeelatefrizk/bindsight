"""Shared pytest fixtures for bindsight tests."""

from __future__ import annotations

import gzip
from pathlib import Path

import pandas as pd
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


# A small real-format STAR-like cohort: ERBB2 (HER2) + EGFR strongly up in tumor,
# a few surface/driver genes for contrast. Keyed by Ensembl gene id (versionless).
_MOCK_COHORT = {
    "ENSG00000141736": [1850, 2120, 1980, 2210, 150, 170, 120, 160],  # ERBB2 / HER2
    "ENSG00000146648": [1450, 1620, 1530, 1710, 180, 160, 200, 170],  # EGFR
    "ENSG00000091831": [820, 950, 890, 1020, 320, 290, 310, 300],  # ESR1 (not surface)
    "ENSG00000142208": [500, 520, 480, 510, 480, 500, 490, 520],  # AKT1 (flat)
    "ENSG00000118260": [300, 290, 310, 320, 290, 300, 305, 295],  # CREB1 (flat)
    "ENSG00000074706": [120, 140, 130, 150, 480, 520, 500, 490],  # PTEN (down)
    "ENSG00000196712": [240, 260, 220, 280, 680, 720, 700, 710],  # NF1 (down)
    "ENSG00000133703": [1320, 1480, 1410, 1550, 220, 240, 230, 250],  # KRAS (driver)
    "ENSG00000174775": [980, 1100, 1050, 1180, 320, 280, 310, 340],  # HRAS (driver)
    "ENSG00000129965": [250, 260, 240, 270, 250, 240, 260, 255],  # INS-IGF2 (flat)
}
_MOCK_SAMPLES = [f"T{i:02d}" for i in range(1, 5)] + [f"N{i:02d}" for i in range(1, 5)]
_MOCK_CONDITIONS = ["tumor"] * 4 + ["normal"] * 4


def write_mock_cohort(counts_out: Path, design_out: Path) -> None:
    """Write a small real-format TCGA-like cohort (counts.tsv.gz + design.tsv)."""
    counts_out.parent.mkdir(parents=True, exist_ok=True)
    design_out.parent.mkdir(parents=True, exist_ok=True)
    counts = pd.DataFrame(_MOCK_COHORT, index=_MOCK_SAMPLES).T
    counts.index.name = "gene_id"
    with gzip.open(counts_out, "wt", newline="") as fh:
        counts.to_csv(fh, sep="\t")
    pd.DataFrame(
        {"condition": _MOCK_CONDITIONS, "sample_type": _MOCK_CONDITIONS},
        index=pd.Index(_MOCK_SAMPLES, name="sample"),
    ).to_csv(design_out, sep="\t")


@pytest.fixture
def offline_real_data(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Mock the network seams so the real-data demo runs offline + hermetic.

    - ``gdc.fetch_cohort`` writes the small mock cohort to the requested paths.
    - the OS user-cache dir is redirected to tmp (cohort cache isolation).
    - SURFY falls back to the bundled offline list (no network populate).
    - AlphaFoldDB is stubbed.
    """

    def _fake_fetch(*, counts_out, design_out, **_kwargs):
        write_mock_cohort(Path(counts_out), Path(design_out))
        return {"source": "mock", "n_tumor": 4, "n_normal": 4}

    monkeypatch.setattr("bindsight.io.gdc.fetch_cohort", _fake_fetch)
    monkeypatch.setattr(
        "bindsight.io.paths.user_cache_path",
        lambda *a, **k: tmp_path / "cache",
    )
    # Open Targets returns nothing offline -> discover uses the bundled ENSG map.
    monkeypatch.setattr(
        "bindsight.targets.open_targets.OpenTargetsClient.get_target",
        lambda self, gid: None,
    )
    monkeypatch.setattr(
        "bindsight.surfaceome.surfy.populate_surfy_cache",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("offline")),
    )
    monkeypatch.setattr(
        "bindsight.surfaceome.surfy._surfy_cache_path",
        lambda: tmp_path / "no_surfy_cache.txt",
    )
    monkeypatch.setattr(
        "bindsight.structures.alphafolddb.AlphaFoldDBClient.fetch",
        lambda self, uid: None,
    )

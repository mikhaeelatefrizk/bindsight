# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the SURFACE-Bind targetable-site client and its discovery wiring.

The fixture under ``tests/fixtures/surface_bind/`` holds **synthetic** site
records (arbitrary residue indices) purely to exercise the parsing/lookup and
pipeline-wiring code. They are NOT real SURFACE-Bind predictions and are never
surfaced as results.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from bindsight.config import TargetDiscoveryParams
from bindsight.epitopes.surface_bind import SurfaceBindClient, TargetableSite
from bindsight.pipelines.discover import _build_epitopes, _resolve_surface_bind_client

FIX = Path(__file__).parent / "fixtures" / "surface_bind"


# --------------------------------------------------------------------------- #
# Client
# --------------------------------------------------------------------------- #
def test_has() -> None:
    c = SurfaceBindClient(data_root=FIX)
    assert c.has("P04626") is True
    assert c.has("Q99999") is False


def test_sites_parses_scores_and_sorts() -> None:
    c = SurfaceBindClient(data_root=FIX)
    sites = c.sites("P04626")
    # best score first
    assert [s.site_id for s in sites] == ["P04626_site_1", "P04626_site_2"]
    s1 = sites[0]
    assert isinstance(s1, TargetableSite)
    assert s1.residues == [10, 11, 12, 15, 18]
    assert s1.score == 0.82
    assert s1.seed_pdb_path is not None
    assert s1.seed_pdb_path.replace("\\", "/").endswith("seeds/site_1.pdb")  # OS-agnostic
    assert sites[1].seed_pdb_path is None  # no seed in the second record


def test_sites_missing_returns_empty() -> None:
    assert SurfaceBindClient(data_root=FIX).sites("Q99999") == []


def test_metadata_reads_commit_sha() -> None:
    md = SurfaceBindClient(data_root=FIX).metadata()
    assert md["commit_sha"] == "fixture-not-a-real-sha"
    assert "SURFACE-Bind" in md["source"]


def test_missing_data_root_raises() -> None:
    with pytest.raises(FileNotFoundError):
        SurfaceBindClient(data_root=FIX / "nope")


def test_unconfigured_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BINDSIGHT_SURFACE_BIND_DATA", raising=False)
    with pytest.raises(RuntimeError):
        SurfaceBindClient()


# --------------------------------------------------------------------------- #
# Discovery wiring (_build_epitopes / _resolve_surface_bind_client)
# --------------------------------------------------------------------------- #
def _top() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "gene_id": "ENSG00000141736",
                "symbol": "ERBB2",
                "uniprot_id": "P04626",
                "alphafold_structure_path": "/x/P04626.cif",
            },
            {
                "gene_id": "ENSG00000000000",
                "symbol": "NOPE",
                "uniprot_id": "Q99999",
                "alphafold_structure_path": "/x/Q99999.cif",
            },
        ]
    )


def test_build_epitopes_with_sites() -> None:
    c = SurfaceBindClient(data_root=FIX)
    p = TargetDiscoveryParams(require_surface_bind_site=False, min_surface_bind_score=0.5)
    ep = _build_epitopes(_top(), c, p)
    erbb2 = ep[ep["uniprot_id"] == "P04626"]
    # site_2 (0.41) is filtered by min_surface_bind_score=0.5 → exactly one row
    assert len(erbb2) == 1
    assert list(erbb2.iloc[0]["residues"]) == [10, 11, 12, 15, 18]
    assert erbb2.iloc[0]["epitope_status"] == "surface_bind_site"
    nope = ep[ep["uniprot_id"] == "Q99999"]
    assert len(nope) == 1
    assert list(nope.iloc[0]["residues"]) == []
    assert nope.iloc[0]["epitope_status"] == "no_surface_bind_site"


def test_build_epitopes_require_true_drops_siteless() -> None:
    c = SurfaceBindClient(data_root=FIX)
    p = TargetDiscoveryParams(require_surface_bind_site=True, min_surface_bind_score=0.5)
    ep = _build_epitopes(_top(), c, p)
    assert set(ep["uniprot_id"]) == {"P04626"}  # Q99999 (no qualifying site) dropped


def test_build_epitopes_no_client_is_whole_surface() -> None:
    ep = _build_epitopes(_top(), None, TargetDiscoveryParams())  # default require=True
    assert len(ep) == 2  # no data to require → every candidate designable
    assert set(ep["epitope_status"]) == {"surface_bind_not_configured"}
    assert all(len(r) == 0 for r in ep["residues"])


def test_resolve_returns_injected() -> None:
    c = SurfaceBindClient(data_root=FIX)
    assert _resolve_surface_bind_client(c) is c


def test_resolve_none_when_no_data(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("BINDSIGHT_SURFACE_BIND_DATA", raising=False)
    monkeypatch.chdir(tmp_path)  # no data/surface_bind/sites/ here
    assert _resolve_surface_bind_client(None) is None

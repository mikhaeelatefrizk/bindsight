"""Tests for designer + validator plugins (load via entry points; spec construction)."""

from __future__ import annotations

from importlib.metadata import entry_points
from pathlib import Path

import pytest

from xpr2bind.design import DesignSpec
from xpr2bind.design.bindcraft import BindCraftDesigner
from xpr2bind.design.boltzgen import BoltzGenDesigner
from xpr2bind.design.rfdiff_mpnn import RFdiffMPNNDesigner
from xpr2bind.runners.mock import MockRunner
from xpr2bind.validate.af2_ig import AF2IGValidator
from xpr2bind.validate.boltz2 import Boltz2Validator
from xpr2bind.validate.chai1r import Chai1rValidator


# ---------------------------------------------------------------------------
# Designers
# ---------------------------------------------------------------------------
class TestRFdiffMPNNDesigner:
    def test_spec_construction(self, tmp_path: Path) -> None:
        struct = tmp_path / "P04626.cif"
        struct.write_text("# fake mmCIF\n")
        d = RFdiffMPNNDesigner()
        spec = d.make_spec(
            target_uniprot="P04626",
            target_structure_path=struct,
            epitope_residues=[101, 102, 103, 104],
            n_trajectories=10,
            seed=42,
        )
        assert isinstance(spec, DesignSpec)
        assert spec.target_uniprot == "P04626"
        assert spec.n_trajectories == 10
        assert spec.extra_params["designer"] == "rfdiff_mpnn"
        assert "rfdiff_commit" in spec.extra_params

    def test_cache_key_is_deterministic(self, tmp_path: Path) -> None:
        struct = tmp_path / "P04626.cif"
        struct.write_text("# fake\n")
        d = RFdiffMPNNDesigner()
        spec_a = d.make_spec(
            target_uniprot="P04626",
            target_structure_path=struct,
            epitope_residues=[101, 102, 103],
            n_trajectories=10,
            seed=42,
        )
        spec_b = d.make_spec(
            target_uniprot="P04626",
            target_structure_path=struct,
            epitope_residues=[103, 102, 101],  # different order, same set
            n_trajectories=10,
            seed=42,
        )
        # Same epitope residues (order-independent) => same cache key.
        assert RFdiffMPNNDesigner._cache_key(spec_a) == RFdiffMPNNDesigner._cache_key(spec_b)

    def test_cache_key_changes_with_seed(self, tmp_path: Path) -> None:
        struct = tmp_path / "P04626.cif"
        struct.write_text("# fake\n")
        d = RFdiffMPNNDesigner()
        a = d.make_spec(
            target_uniprot="P04626",
            target_structure_path=struct,
            epitope_residues=[1],
            n_trajectories=1,
            seed=42,
        )
        b = d.make_spec(
            target_uniprot="P04626",
            target_structure_path=struct,
            epitope_residues=[1],
            n_trajectories=1,
            seed=43,
        )
        assert RFdiffMPNNDesigner._cache_key(a) != RFdiffMPNNDesigner._cache_key(b)

    def test_submit_with_mock_runner_round_trip(self, tmp_path: Path, monkeypatch) -> None:
        """End-to-end: spec → mock runner → DesignResult, cache key intact."""
        monkeypatch.chdir(tmp_path)
        struct = tmp_path / "P04626.cif"
        struct.write_text("# fake\n")
        designer = RFdiffMPNNDesigner()
        spec = designer.make_spec(
            target_uniprot="P04626",
            target_structure_path=struct,
            epitope_residues=[1, 2, 3],
            n_trajectories=1,
            seed=0,
        )
        runner = MockRunner()
        result = designer.submit(spec, runner)
        assert result.designer_name == "rfdiff_mpnn"
        assert result.cache_key
        assert Path(result.results_archive_path).exists()


class TestStubDesigners:
    def test_bindcraft_submit_raises(self, tmp_path: Path) -> None:
        struct = tmp_path / "P04626.cif"
        struct.write_text("# fake\n")
        d = BindCraftDesigner()
        spec = d.make_spec(
            target_uniprot="P04626",
            target_structure_path=struct,
            epitope_residues=[1],
        )
        with pytest.raises(NotImplementedError, match=r"v0\.1\.0-rc2"):
            d.submit(spec, MockRunner())

    def test_boltzgen_submit_raises(self, tmp_path: Path) -> None:
        struct = tmp_path / "P04626.cif"
        struct.write_text("# fake\n")
        d = BoltzGenDesigner()
        spec = d.make_spec(
            target_uniprot="P04626",
            target_structure_path=struct,
            epitope_residues=[1],
        )
        with pytest.raises(NotImplementedError, match=r"v0\.1\.0-rc2"):
            d.submit(spec, MockRunner())


# ---------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------
class TestValidators:
    def test_boltz2_returns_stub_result(self) -> None:
        v = Boltz2Validator()
        result = v.validate(
            target_uniprot="P04626",
            binder_id="design_0",
            binder_sequence="ACDEFGHIKLMN",
            target_structure_path="/tmp/fake.cif",
        )
        assert result.binder_id == "design_0"
        assert result.validator_name == "boltz2"
        assert "stub" in (result.notes or "").lower()

    def test_chai1r_returns_stub_result(self) -> None:
        v = Chai1rValidator()
        result = v.validate(
            target_uniprot="P04626",
            binder_id="design_0",
            binder_sequence="ACDEFGHIKLMN",
            target_structure_path="/tmp/fake.cif",
        )
        assert result.validator_name == "chai1r"

    def test_af2_ig_license_notice_warns(self) -> None:
        v = AF2IGValidator()
        notice = v.license_notice.lower()
        assert "alphafold2" in notice
        assert "commercial" in notice  # the notice says "restricts commercial use"


# ---------------------------------------------------------------------------
# Entry-point loading (catches pyproject.toml drift)
# ---------------------------------------------------------------------------
class TestPluginEntryPoints:
    def test_designer_entry_points_resolve(self) -> None:
        eps = entry_points(group="xpr2bind.designers")
        names = {ep.name for ep in eps}
        assert {"rfdiff_mpnn", "bindcraft", "boltzgen"} <= names
        # The default designer must actually load.
        klass = next(ep for ep in eps if ep.name == "rfdiff_mpnn").load()
        assert klass is RFdiffMPNNDesigner

    def test_validator_entry_points_resolve(self) -> None:
        eps = entry_points(group="xpr2bind.validators")
        names = {ep.name for ep in eps}
        assert {"boltz2", "chai1r", "af2_ig"} <= names
        klass = next(ep for ep in eps if ep.name == "boltz2").load()
        assert klass is Boltz2Validator

    def test_runner_entry_points_resolve(self) -> None:
        eps = entry_points(group="xpr2bind.runners")
        names = {ep.name for ep in eps}
        assert {"colab", "modal", "kaggle", "local_docker", "mock"} <= names

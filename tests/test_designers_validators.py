# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for designer + validator plugins (load via entry points; spec construction)."""

from __future__ import annotations

import json
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any

import pytest

from bindsight.design import DesignSpec
from bindsight.design.bindcraft import BindCraftDesigner
from bindsight.design.boltzgen import BoltzGenDesigner
from bindsight.design.rfdiff_mpnn import RFdiffMPNNDesigner
from bindsight.runners.mock import MockRunner
from bindsight.validate.af2_ig import AF2IGValidator
from bindsight.validate.boltz2 import Boltz2Validator
from bindsight.validate.chai1r import Chai1rValidator


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
        from bindsight.design._common import make_cache_key

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
        assert make_cache_key(spec_a) == make_cache_key(spec_b)

    def test_cache_key_changes_with_seed(self, tmp_path: Path) -> None:
        from bindsight.design._common import make_cache_key

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
        assert make_cache_key(a) != make_cache_key(b)

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


class TestAltDesigners:
    """BindCraft + BoltzGen are real designers (submit via a runner, no stubs)."""

    @pytest.mark.parametrize(
        ("cls", "name"),
        [(BindCraftDesigner, "bindcraft"), (BoltzGenDesigner, "boltzgen")],
    )
    def test_submit_round_trip(self, cls, name, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        struct = tmp_path / "P04626.cif"
        struct.write_text("# fake\n")
        d = cls()
        spec = d.make_spec(
            target_uniprot="P04626",
            target_structure_path=struct,
            epitope_residues=[1, 2, 3],
            n_trajectories=1,
        )
        assert spec.extra_params["designer"] == name
        result = d.submit(spec, MockRunner())
        assert result.designer_name == name
        assert result.cache_key
        assert Path(result.results_archive_path).exists()


# ---------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------
class TestValidators:
    def test_boltz2_raises_when_no_output_dir(self, tmp_path, monkeypatch) -> None:
        """Boltz2Validator looks for pre-computed Boltz output; raises if missing."""
        from bindsight.validate.boltz2 import MissingValidationError

        monkeypatch.chdir(tmp_path)
        v = Boltz2Validator()
        with pytest.raises(MissingValidationError):
            v.validate(
                target_uniprot="P04626",
                binder_id="design_0",
                binder_sequence="ACDEFGHIKLMN",
                target_structure_path="/tmp/fake.cif",
            )

    def test_boltz2_parses_real_output_jsons(self, tmp_path, monkeypatch) -> None:
        """Drop fake but well-formed Boltz JSONs and verify parsing."""
        import json

        from bindsight.validate.boltz2 import parse_boltz_output

        outdir = tmp_path / "validate" / "design_0"
        outdir.mkdir(parents=True)
        (outdir / "confidence_design_0_model_0.json").write_text(
            json.dumps({"iptm": 0.78, "pae_interaction": 5.4, "ptm": 0.85})
        )
        (outdir / "affinity_design_0.json").write_text(
            json.dumps({"affinity_pred_value": -7.3, "affinity_probability_binary": 0.91})
        )
        result = parse_boltz_output(
            output_dir=outdir, binder_id="design_0", target_uniprot="P04626"
        )
        assert result.iptm == pytest.approx(0.78)
        assert result.pae_interaction == pytest.approx(5.4)
        assert result.affinity_pred_value == pytest.approx(-7.3)
        assert result.affinity_probability_binary == pytest.approx(0.91)
        assert result.validator_name == "boltz2"

    def test_chai1r_raises_when_no_output_dir(self, tmp_path, monkeypatch) -> None:
        """Chai-1r parses pre-computed output; raises if missing (no stub result)."""
        from bindsight.validate.boltz2 import MissingValidationError

        monkeypatch.chdir(tmp_path)
        v = Chai1rValidator()
        with pytest.raises(MissingValidationError):
            v.validate(
                target_uniprot="P04626",
                binder_id="design_0",
                binder_sequence="ACDEFGHIKLMN",
                target_structure_path="/tmp/fake.cif",
            )

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
        eps = entry_points(group="bindsight.designers")
        names = {ep.name for ep in eps}
        assert {"rfdiff_mpnn", "bindcraft", "boltzgen"} <= names
        # The default designer must actually load.
        klass = next(ep for ep in eps if ep.name == "rfdiff_mpnn").load()
        assert klass is RFdiffMPNNDesigner

    def test_validator_entry_points_resolve(self) -> None:
        eps = entry_points(group="bindsight.validators")
        names = {ep.name for ep in eps}
        assert {"boltz2", "chai1r", "af2_ig"} <= names
        klass = next(ep for ep in eps if ep.name == "boltz2").load()
        assert klass is Boltz2Validator

    def test_runner_entry_points_resolve(self) -> None:
        eps = entry_points(group="bindsight.runners")
        names = {ep.name for ep in eps}
        assert {"colab", "modal", "kaggle", "local_docker", "mock"} <= names


class TestTheRecordedValidatorVersionIsMeasured:
    """``validator_version`` reported a hardcoded ``"2.0.1"`` on every row.

    It sat beside genuine measurements in the same metrics line, so it read as
    one. It was not: the pin was a range, any 2.x could have produced the
    number, and the field said 2.0.1 regardless. A provenance field answering
    from a constant is worse than no field, because a reader checking which
    model produced a result gets a confident wrong answer instead of an
    obviously missing one.
    """

    @staticmethod
    def _row(tmp_path: Path) -> Any:
        from bindsight.validate.boltz2 import parse_boltz_output

        out = tmp_path / "predictions" / "run"
        out.mkdir(parents=True)
        (out / "confidence_run_model_0.json").write_text(
            json.dumps({"iptm": 0.7, "pae_interaction": 5.0})
        )
        return parse_boltz_output(output_dir=tmp_path, binder_id="b0", target_uniprot="P04626")

    def test_the_version_comes_from_the_environment(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from bindsight.validate import boltz2

        monkeypatch.setattr(boltz2, "installed_boltz_version", lambda: "9.9.9")
        assert self._row(tmp_path).validator_version == "9.9.9"

    def test_an_absent_boltz_is_reported_as_unrecorded(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The fallback must not be a plausible version number.

        Substituting the pin when Boltz is not installed would rebuild the
        original defect: a row that names a version nothing here ever ran.
        """
        from bindsight.validate import boltz2

        monkeypatch.setattr(boltz2, "installed_boltz_version", lambda: None)
        recorded = self._row(tmp_path).validator_version
        assert recorded == "unrecorded"
        assert recorded != boltz2.PINNED_BOLTZ2_VERSION

    def test_the_reader_returns_none_rather_than_guessing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from importlib.metadata import PackageNotFoundError

        from bindsight.validate import boltz2

        def _absent(_name: str) -> str:
            raise PackageNotFoundError("boltz")

        monkeypatch.setattr("importlib.metadata.version", _absent)
        assert boltz2.installed_boltz_version() is None

    def test_the_pin_is_the_single_source_of_truth(self) -> None:
        """Two places to edit a version is one place to forget."""
        from bindsight.runners import tools
        from bindsight.validate import boltz2

        assert f"boltz=={boltz2.PINNED_BOLTZ2_VERSION}" == tools.BOLTZ_PIP
        assert Boltz2Validator.version == boltz2.PINNED_BOLTZ2_VERSION

    def test_no_parser_writes_a_version_literal(self) -> None:
        """Boltz-2 was not the only one; it was the only one anyone had run.

        Chai-1r wrote ``"0.6"`` and AF2-IG wrote ``"1.0"`` into every row the
        same way. Neither has produced a published number — no shipped backend
        can execute them — so the defect was latent rather than realised, which
        is not a reason to leave a provenance field answering from a literal.
        """
        import ast
        import inspect

        from bindsight.runners import tools
        from bindsight.validate import boltz2

        offenders: list[str] = []
        for module in (tools, boltz2):
            tree = ast.parse(inspect.getsource(module))
            for node in ast.walk(tree):
                if not isinstance(node, ast.keyword) or node.arg != "validator_version":
                    continue
                if isinstance(node.value, ast.Constant):
                    offenders.append(f"{module.__name__}:{node.lineno} = {node.value.value!r}")
        assert not offenders, "validator_version is assigned a literal at " + "; ".join(offenders)


class TestEveryDiffusionDrawIsCounted:
    """Boltz ranks its samples best-first, so reading one reported the maximum.

    With ``--diffusion_samples k`` Boltz writes ``model_0..model_{k-1}`` sorted
    by confidence descending. Taking whichever file ``rglob`` yielded first
    therefore reported a max over k — an estimate that improves as more samples
    are bought, with no change to the design being scored. Averaging estimates
    the distribution's centre; the best draw estimates nothing.
    """

    @staticmethod
    def _out(tmp_path: Path, iptms: list[float], paes: list[float] | None = None) -> Path:
        out = tmp_path / "predictions" / "run"
        out.mkdir(parents=True)
        paes = paes if paes is not None else [5.0] * len(iptms)
        for i, (iptm, pae) in enumerate(zip(iptms, paes, strict=True)):
            (out / f"confidence_run_model_{i}.json").write_text(
                json.dumps({"iptm": iptm, "pae_interaction": pae})
            )
        return tmp_path

    def test_iptm_is_the_mean_not_the_best_draw(self, tmp_path: Path) -> None:
        from bindsight.validate.boltz2 import parse_boltz_output

        # Best-first, as Boltz writes them.
        root = self._out(tmp_path, [0.90, 0.60, 0.50, 0.40, 0.30])
        row = parse_boltz_output(output_dir=root, binder_id="b0", target_uniprot="P04626")
        assert row.iptm == pytest.approx(0.54)
        assert row.iptm != pytest.approx(0.90), "reported the best draw, not an estimate"

    def test_the_number_of_draws_is_recorded(self, tmp_path: Path) -> None:
        """A single draw and an average of five must not look alike."""
        from bindsight.validate.boltz2 import parse_boltz_output

        root = self._out(tmp_path, [0.9, 0.6, 0.5])
        row = parse_boltz_output(output_dir=root, binder_id="b0", target_uniprot="P04626")
        assert row.iptm_n_samples == 3
        # The note now reports files parsed of files found, because counting the
        # files present reported the same number whether or not they were
        # readable. Three of three is what this fixture wrote.
        assert "parsed confidence=3 of 3 file(s)" in (row.notes or ""), row.notes

    def test_the_spread_across_draws_is_recorded(self, tmp_path: Path) -> None:
        """The metric's own noise, measured on one input in one job."""
        import statistics

        from bindsight.validate.boltz2 import parse_boltz_output

        values = [0.90, 0.60, 0.50, 0.40, 0.30]
        root = self._out(tmp_path, values)
        row = parse_boltz_output(output_dir=root, binder_id="b0", target_uniprot="P04626")
        assert row.iptm_sd == pytest.approx(statistics.stdev(values))

    def test_one_draw_has_no_spread(self, tmp_path: Path) -> None:
        from bindsight.validate.boltz2 import parse_boltz_output

        root = self._out(tmp_path, [0.77])
        row = parse_boltz_output(output_dir=root, binder_id="b0", target_uniprot="P04626")
        assert row.iptm == pytest.approx(0.77)
        assert row.iptm_n_samples == 1
        assert row.iptm_sd is None, "a single draw cannot have a spread"

    def test_pae_is_averaged_across_draws_too(self, tmp_path: Path) -> None:
        from bindsight.validate.boltz2 import parse_boltz_output

        root = self._out(tmp_path, [0.9, 0.5], paes=[4.0, 8.0])
        row = parse_boltz_output(output_dir=root, binder_id="b0", target_uniprot="P04626")
        assert row.pae_interaction == pytest.approx(6.0)

    def test_a_corrupt_draw_does_not_discard_the_others(self, tmp_path: Path) -> None:
        """One unreadable file must cost one sample, not the whole binder."""
        from bindsight.validate.boltz2 import parse_boltz_output

        root = self._out(tmp_path, [0.8, 0.6])
        (root / "predictions" / "run" / "confidence_run_model_2.json").write_text("{not json")
        row = parse_boltz_output(output_dir=root, binder_id="b0", target_uniprot="P04626")
        assert row.iptm == pytest.approx(0.7)
        assert row.iptm_n_samples == 2

    def test_no_output_still_yields_a_row_with_nulls(self, tmp_path: Path) -> None:
        from bindsight.validate.boltz2 import parse_boltz_output

        row = parse_boltz_output(output_dir=tmp_path, binder_id="b0", target_uniprot="P04626")
        assert row.iptm is None
        assert row.iptm_n_samples is None


class TestEveryValidatorRecordsWhatItRan:
    """Each parser reports its own tool's provenance, by its own mechanism."""

    def test_chai_reads_the_installed_distribution(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """chai_lab is pip-installed, and CHAI_PIP is still a range."""
        from bindsight.runners import tools

        monkeypatch.setattr(tools, "installed_version", lambda dist: "0.6.1" if dist else None)
        row = tools.parse_chai_output(tmp_path, binder_id="b0", target_uniprot="P04626")
        assert row.validator_version == "0.6.1"

    def test_chai_says_unrecorded_when_absent(self, tmp_path: Path) -> None:
        from bindsight.runners import tools
        from bindsight.validate.protocol import UNRECORDED_VERSION

        row = tools.parse_chai_output(tmp_path, binder_id="b0", target_uniprot="P04626")
        assert row.validator_version == UNRECORDED_VERSION

    def test_af2ig_records_the_pinned_commit(self, tmp_path: Path) -> None:
        """Cloned from git at a SHA, so there is no distribution to query.

        A SHA is the stronger record regardless: it is content-addressed, so a
        clone yields exactly that tree or fails.
        """
        from bindsight.runners import tools

        row = tools.parse_af2ig_output(
            tmp_path / "none.sc", binder_id="b0", target_uniprot="P04626"
        )
        assert row.validator_version == f"dl_binder_design@{tools.DL_BINDER_DESIGN_COMMIT}"
        assert len(tools.DL_BINDER_DESIGN_COMMIT) == 40

    def test_the_unrecorded_sentinel_is_not_version_shaped(self) -> None:
        """It has to be obviously absent, not quietly plausible."""
        from bindsight.validate.protocol import UNRECORDED_VERSION

        assert not any(ch.isdigit() for ch in UNRECORDED_VERSION)

    def test_the_shared_reader_returns_a_real_version(self) -> None:
        """Something certainly installed, so the happy path is exercised."""
        from bindsight.validate.protocol import installed_version

        assert installed_version("pydantic") is not None
        assert installed_version("a-distribution-that-is-not-installed") is None


class TestTheChaiValidatorMatchesTheBoltzDiscipline:
    """Chai-1 carried the same two defects Boltz-2 did, unfixed because unused.

    `plugin_support` marks chai1r unsupported on every bundled backend — it
    needs bfloat16 and the free tiers pin pre-Ampere cards — so no published
    number comes from it. That is exactly why the defects survived: a plugin
    that has not run is the one place a defect sits unnoticed until it is
    producing results.

    Both verified against the pinned commit c544fb1: `run_inference` takes
    `seed: int | None = None` and `num_diffn_samples: int = 5`.
    """

    @staticmethod
    def _scores(tmp_path: Path, values: list[float]) -> Path:
        import numpy as np

        for i, v in enumerate(values):
            np.savez(tmp_path / f"scores.model_idx_{i}.npz", iptm=np.array(v), ptm=np.array(v))
        return tmp_path

    def test_the_reported_iptm_is_the_mean_not_the_best_draw(self, tmp_path: Path) -> None:
        """chai-lab writes one npz per draw and ranks them best-first."""
        from bindsight.runners import tools

        root = self._scores(tmp_path, [0.81, 0.62, 0.58, 0.55, 0.51])
        row = tools.parse_chai_output(root, binder_id="b0", target_uniprot="P04626")
        assert row.iptm == pytest.approx(0.614)
        assert row.iptm != pytest.approx(0.81), "reported the best draw, not an estimate"

    def test_the_draw_count_and_spread_are_recorded(self, tmp_path: Path) -> None:
        from bindsight.runners import tools

        root = self._scores(tmp_path, [0.8, 0.6, 0.4])
        row = tools.parse_chai_output(root, binder_id="b0", target_uniprot="P04626")
        assert row.iptm_n_samples == 3
        assert row.iptm_sd is not None
        assert row.iptm_sd > 0

    def test_a_single_draw_has_no_spread(self, tmp_path: Path) -> None:
        from bindsight.runners import tools

        root = self._scores(tmp_path, [0.77])
        row = tools.parse_chai_output(root, binder_id="b0", target_uniprot="P04626")
        assert row.iptm_n_samples == 1
        assert row.iptm_sd is None

    def test_no_output_yields_nulls_rather_than_a_guess(self, tmp_path: Path) -> None:
        from bindsight.runners import tools

        row = tools.parse_chai_output(tmp_path, binder_id="b0", target_uniprot="P04626")
        assert row.iptm is None
        assert row.iptm_n_samples is None

    def test_the_command_can_carry_a_seed(self) -> None:
        from bindsight.runners import tools

        cmd = tools.build_chai_cmd(fasta_path=Path("x.fa"), out_dir=Path("o"), seed=7)
        assert cmd[cmd.index("--seed") + 1] == "7"

    def test_the_unseeded_form_is_unchanged(self) -> None:
        from bindsight.runners import tools

        assert tools.build_chai_cmd(fasta_path=Path("x.fa"), out_dir=Path("o")) == [
            "chai-lab",
            "fold",
            "x.fa",
            "o",
        ]

    def test_a_negative_seed_is_refused(self) -> None:
        from bindsight.runners import tools

        with pytest.raises(ValueError, match="negative"):
            tools.build_chai_cmd(fasta_path=Path("x.fa"), out_dir=Path("o"), seed=-1)


# ---------------------------------------------------------------------------
# A Protocol's signature is a contract, defaults included
# ---------------------------------------------------------------------------
class TestEveryDesignerMatchesItsProtocol:
    """BindCraft's ``make_spec`` declared ``n_trajectories: int = 10`` where the
    Designer protocol declares 50. Nothing depended on it — every call site
    passes the value — so it was a latent contradiction rather than a live bug,
    and latent is exactly how it survived.
    """

    @staticmethod
    def _defaults(func: object) -> dict[str, object]:
        import inspect

        return {
            name: param.default
            for name, param in inspect.signature(func).parameters.items()
            if param.default is not inspect.Parameter.empty
        }

    @staticmethod
    def _shipped_designers() -> dict[str, type]:
        import tomllib

        from bindsight.plugins import get_designer

        root = Path(__file__).resolve().parents[1]
        data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
        names = data["project"]["entry-points"]["bindsight.designers"]
        return {name: type(get_designer(name)) for name in sorted(names)}

    def test_the_registry_is_not_empty(self) -> None:
        """Guards the guard: an empty registry would check nothing."""
        assert len(self._shipped_designers()) >= 3, self._shipped_designers()

    def test_every_designer_declares_the_protocol_defaults(self) -> None:
        from bindsight.design.protocol import Designer

        expected = self._defaults(Designer.make_spec)
        assert expected, "the Designer protocol declares no defaults to compare against"

        for name, cls in self._shipped_designers().items():
            actual = self._defaults(cls.make_spec)
            for param, value in expected.items():
                assert actual.get(param) == value, (
                    f"{name}.make_spec declares {param}={actual.get(param)!r} where the "
                    f"Designer protocol declares {value!r}; a caller relying on the "
                    "protocol's contract would get different work from different plugins"
                )

    def test_every_designer_accepts_every_protocol_parameter(self) -> None:
        """A missing parameter is the same contract break, one step earlier."""
        import inspect

        from bindsight.design.protocol import Designer

        expected = set(inspect.signature(Designer.make_spec).parameters)
        for name, cls in self._shipped_designers().items():
            actual = set(inspect.signature(cls.make_spec).parameters)
            missing = expected - actual
            assert not missing, f"{name}.make_spec does not accept {sorted(missing)}"

    def test_the_protocol_annotations_are_resolvable(self) -> None:
        """``submit`` annotated ``GPURunner`` with the name never imported, and
        silenced both checkers rather than telling either what it is — so
        ``get_type_hints`` raised and nothing could introspect the contract."""
        import typing

        from bindsight.design.protocol import Designer

        hints = typing.get_type_hints(Designer.submit)

        assert "runner" in hints

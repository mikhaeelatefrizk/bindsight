# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A designer registered through an entry point must be selectable.

`bindsight/plugins.py` resolves designers, validators and runners through the
`bindsight.designers` / `.validators` / `.runners` entry-point groups, and its
docstring says this exists "so third parties can register their own without
forking". `docs/use-cases.md` walks a method developer through registering one
and then shows the command to run it.

That command could not work. The loader was correct and nothing could reach it:

* `DesignParams.designer` was `Literal["rfdiff_mpnn", "bindcraft", "boltzgen"]`,
  so a config naming the plugin failed validation before anything loaded.
* Ten `click.Choice` literals in `cli.py` rejected the name before the command
  body ran.
* `ALL_DESIGNERS` and `ALL_VALIDATORS` were built from the bundled fallback
  dict alone, so the registry's own "everything we know about" constants did
  not include entry points either.
* `verify-licenses` indexed a bare dict by designer name.

Every one of those was a separate hand-maintained copy of a list the registry
already owned -- the same defect class as the cache key's missing parameters,
in a place where the consequence is a documented feature that does not exist.

These tests register a plugin the way a third party would, through the
`importlib.metadata` machinery the loader reads, and drive the paths a user
would take.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]


class _AcmeDesigner:
    """A third-party designer, as minimal as the Protocol allows."""

    name = "acme"
    version = "9.9.9"
    license_notice = "Acme Proprietary. Not commercial-OK."


@pytest.fixture
def registered_acme(monkeypatch: pytest.MonkeyPatch) -> None:
    """Register `acme` in the designer entry-point group for one test.

    Patches `bindsight.plugins.entry_points`, which is the single function the
    loader and the registry both go through, so this exercises the real
    resolution path rather than a stand-in for it.
    """
    from importlib.metadata import EntryPoint

    import bindsight.plugins as plugins

    real = plugins.entry_points
    acme = EntryPoint(
        name="acme",
        value="tests.test_third_party_plugins:_AcmeDesigner",
        group="bindsight.designers",
    )

    def fake(*args: Any, **kwargs: Any) -> Any:
        found = list(real(*args, **kwargs))
        if kwargs.get("group") == "bindsight.designers":
            return [*found, acme]
        return found

    monkeypatch.setattr(plugins, "entry_points", fake)


class TestTheRegistrySeesWhatIsRegistered:
    def test_a_registered_designer_is_listed(self, registered_acme: None) -> None:
        from bindsight.plugins import all_designers

        assert "acme" in all_designers()

    def test_the_bundled_designers_are_still_listed(self, registered_acme: None) -> None:
        """A registered plugin adds to the set; it does not replace it."""
        from bindsight.plugins import all_designers

        assert {"rfdiff_mpnn", "bindcraft", "boltzgen"} <= all_designers()

    def test_nothing_is_listed_that_was_not_registered(self) -> None:
        from bindsight.plugins import all_designers

        assert "acme" not in all_designers(), "the fixture leaked out of its test"

    def test_the_bundled_names_are_available_without_metadata(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An editable install whose metadata will not resolve still works."""
        import bindsight.plugins as plugins

        def broken(*_args: Any, **_kwargs: Any) -> Any:
            raise RuntimeError("no metadata here")

        monkeypatch.setattr(plugins, "entry_points", broken)

        assert plugins.all_designers() == plugins.BUNDLED_DESIGNERS


class TestAConfigCanNameARegisteredDesigner:
    def test_it_validates(self, registered_acme: None) -> None:
        from bindsight.config import DesignParams

        assert DesignParams(designer="acme").designer == "acme"

    def test_a_name_nothing_registered_is_still_rejected(self) -> None:
        """Dropping the Literal must not drop the validation with it."""
        from pydantic import ValidationError

        from bindsight.config import DesignParams

        with pytest.raises(ValidationError, match="unknown designer"):
            DesignParams(designer="rfdif_mpnn")  # a plausible typo

    def test_the_message_names_what_is_available(self) -> None:
        from pydantic import ValidationError

        from bindsight.config import DesignParams

        with pytest.raises(ValidationError) as excinfo:
            DesignParams(designer="nope")

        message = str(excinfo.value)
        assert "rfdiff_mpnn" in message
        assert "entry-point group" in message, (
            "the error does not tell a third party how to register one"
        )

    def test_the_validator_field_is_checked_the_same_way(self) -> None:
        from pydantic import ValidationError

        from bindsight.config import ValidateParams

        with pytest.raises(ValidationError, match="unknown validator"):
            ValidateParams(validator="boltz3")

    def test_the_backend_field_is_checked_the_same_way(self) -> None:
        from pydantic import ValidationError

        from bindsight.config import RunConfig

        with pytest.raises(ValidationError, match="unknown backend"):
            RunConfig.model_validate(
                {
                    "name": "x",
                    "out_dir": "out",
                    "backend": "aws",
                    "inputs": {"counts": "c", "design": "d"},
                    "params": {
                        "deg": {
                            "design_formula": "~ condition",
                            "contrast": ["condition", "t", "n"],
                        }
                    },
                }
            )


class TestTheCommandLineOffersWhatIsRegistered:
    def test_the_designer_choice_includes_a_registered_plugin(self, registered_acme: None) -> None:
        from bindsight.cli import _designer_choice

        assert "acme" in _designer_choice().choices

    def test_every_bundled_designer_is_still_offered(self) -> None:
        from bindsight.cli import _designer_choice

        assert set(_designer_choice().choices) >= {"rfdiff_mpnn", "bindcraft", "boltzgen"}

    def test_the_validator_and_backend_choices_come_from_the_registry(self) -> None:
        from bindsight.cli import _backend_choice, _validator_choice
        from bindsight.plugins import all_runners, all_validators

        assert set(_validator_choice().choices) == all_validators()
        assert set(_backend_choice().choices) == all_runners()

    def test_no_choice_literal_is_left_hardcoded(self) -> None:
        """The enumerations are gone, not merely shadowed by the helpers.

        Each was a separate copy of a list the registry owns, and a copy that
        nothing checks is how this defect arrived.
        """
        source = (REPO / "bindsight" / "cli.py").read_text(encoding="utf-8")

        for literal in (
            '"rfdiff_mpnn", "bindcraft", "boltzgen"',
            '"boltz2", "chai1r", "af2_ig"',
            '"colab", "modal", "kaggle", "local_docker", "mock"',
        ):
            assert f"click.Choice([{literal}])" not in source, (
                f"cli.py still hardcodes click.Choice([{literal}]), which rejects a "
                "registered plugin before the command body runs"
            )


class TestTheLoaderReachesTheRegisteredClass:
    def test_it_loads(self, registered_acme: None) -> None:
        from bindsight.plugins import get_designer

        assert get_designer("acme").name == "acme"

    def test_the_mock_backend_will_run_it(self, registered_acme: None) -> None:
        """Where anyone would first try a plugin: the backend that runs no tool."""
        from bindsight.plugins import SUPPORTED, plugin_support

        status, _ = plugin_support("mock", "acme")

        assert status == SUPPORTED

    def test_the_mock_backend_still_supports_the_bundled_ones(self) -> None:
        from bindsight.plugins import SUPPORTED, plugin_support

        for plugin in ("rfdiff_mpnn", "boltz2", "bindcraft", "chai1r"):
            assert plugin_support("mock", plugin)[0] == SUPPORTED, plugin

    def test_a_real_backend_still_refuses_what_it_cannot_build(self) -> None:
        """Widening the registry must not widen the capability table."""
        from bindsight.plugins import UNSUPPORTED, plugin_support

        assert plugin_support("kaggle", "bindcraft")[0] == UNSUPPORTED


class TestALicenceVerdictIsNotGivenForAPluginNobodyAssessed:
    """`verify-licenses` mapped the designer name through a bare dict lookup.

    With a third-party plugin selectable, that is a `KeyError`. Replacing it
    with `.get(name, [])` alone would be worse: the plugin's components would
    silently vanish from the table and the command would print a green
    "all commercial-friendly" clearance covering software whose licence it had
    never seen. A legal statement about code nobody looked at.
    """

    def test_the_command_says_it_did_not_assess_the_plugin(
        self, registered_acme: None, tmp_path: Path
    ) -> None:
        from click.testing import CliRunner

        from bindsight.cli import main

        config = tmp_path / "acme.yaml"
        config.write_text(
            "name: acme-run\n"
            f"out_dir: {(tmp_path / 'out').as_posix()}\n"
            "backend: mock\n"
            "inputs:\n"
            "  counts: counts.csv\n"
            "  design: design.csv\n"
            "params:\n"
            "  deg:\n"
            "    design_formula: '~ condition'\n"
            "    contrast: [condition, tumor, normal]\n"
            "  design:\n"
            "    designer: acme\n",
            encoding="utf-8",
        )

        result = CliRunner().invoke(main, ["verify-licenses", str(config)])

        assert result.exit_code == 0, result.output
        assert "Not assessed" in result.output, result.output
        assert "acme" in result.output
        assert "✓ All components selected by this config are" not in result.output, (
            "a commercial-use clearance was printed covering a plugin whose "
            "licence was never examined"
        )

    def test_a_fully_bundled_config_still_gets_its_clearance(self, tmp_path: Path) -> None:
        """The warning must fire only when something really was not assessed."""
        from click.testing import CliRunner

        from bindsight.cli import main

        config = tmp_path / "bundled.yaml"
        config.write_text(
            "name: bundled-run\n"
            f"out_dir: {(tmp_path / 'out').as_posix()}\n"
            "backend: mock\n"
            "inputs:\n"
            "  counts: counts.csv\n"
            "  design: design.csv\n"
            "params:\n"
            "  deg:\n"
            "    design_formula: '~ condition'\n"
            "    contrast: [condition, tumor, normal]\n"
            "  design:\n"
            "    designer: rfdiff_mpnn\n"
            "  validate:\n"
            "    validator: boltz2\n",
            encoding="utf-8",
        )

        result = CliRunner().invoke(main, ["verify-licenses", str(config)])

        assert result.exit_code == 0, result.output
        assert "Not assessed" not in result.output, result.output


class TestTheDocumentedExampleIsTheOneThatWorks:
    """`docs/use-cases.md` is what a method developer follows."""

    def test_the_documented_entry_point_group_is_the_one_the_loader_reads(self) -> None:
        doc = (REPO / "docs" / "use-cases.md").read_text(encoding="utf-8")

        assert '[project.entry-points."bindsight.designers"]' in doc
        from bindsight.plugins import _FALLBACK

        assert "bindsight.designers" in _FALLBACK, (
            "the group the docs tell developers to register under is not one the loader knows about"
        )

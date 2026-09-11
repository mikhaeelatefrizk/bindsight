# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A backend must refuse what it cannot run, locally and immediately.

`build_kernel_script` takes no designer or validator argument, so
`--designer bindcraft --backend kaggle` built the same two-environment kernel
every Kaggle job builds and failed only after roughly six minutes of environment
building had been charged to a weekly GPU quota that does not refund. The CLI
accepted the combination and found out remotely.

The distinction these tests protect is between *unsupported* and *untested*.
The executor bootstraps RFdiffusion at run time — clone, fetch weights, verify,
pip-install — so a general-purpose CUDA image may well succeed without the
backend having prepared anything. Refusing that would remove a path that may
work; claiming it is demonstrated would be a different lie.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from bindsight import cli
from bindsight.plugins import (
    BACKEND_CAPABILITIES,
    SUPPORTED,
    UNSUPPORTED,
    UNTESTED,
    plugin_support,
)


class TestTheCapabilityTableSaysWhatTheCodeBuilds:
    def test_kaggle_provides_exactly_what_its_kernel_builds(self) -> None:
        """se3 for RFdiffusion and ProteinMPNN, boltz for Boltz-2. Nothing else."""
        assert BACKEND_CAPABILITIES["kaggle"].provides == frozenset({"rfdiff_mpnn", "boltz2"})
        assert plugin_support("kaggle", "rfdiff_mpnn")[0] == SUPPORTED
        assert plugin_support("kaggle", "boltz2")[0] == SUPPORTED

    @pytest.mark.parametrize("plugin", ["bindcraft", "boltzgen", "af2_ig"])
    def test_kaggle_refuses_the_plugins_it_has_no_environment_for(self, plugin: str) -> None:
        verdict, why = plugin_support("kaggle", plugin)
        assert verdict == UNSUPPORTED
        assert "two environments" in why
        assert "provides" in why, "a refusal must name what the backend can do instead"

    def test_a_bfloat16_plugin_is_refused_on_a_turing_card(self) -> None:
        """Chai-1r's assumption is spread through its modules; the Boltz-2
        one-line precision patch does not transfer to it."""
        verdict, why = plugin_support("kaggle", "chai1r")
        assert verdict == UNSUPPORTED
        assert "bfloat16" in why
        assert "sm_80" in why

    def test_a_bootstrappable_plugin_is_untested_not_refused(self) -> None:
        """The executor would try; nothing has run it. Both halves matter."""
        verdict, why = plugin_support("modal", "rfdiff_mpnn")
        assert verdict == UNTESTED
        assert "not been run" in why

    def test_the_mock_backend_accepts_everything(self) -> None:
        """It synthesises results, which is what makes it useless as evidence."""
        for plugin in ("bindcraft", "boltzgen", "chai1r", "af2_ig", "rfdiff_mpnn"):
            assert plugin_support("mock", plugin)[0] == SUPPORTED

    def test_an_unknown_backend_is_not_blocked_by_a_table_it_is_absent_from(self) -> None:
        """A third-party runner registered through the entry points must still run."""
        verdict, why = plugin_support("someone_elses_runner", "rfdiff_mpnn")
        assert verdict == UNTESTED
        assert "unknown" in why


def _run_dir(tmp_path: Path) -> Path:
    """The minimum a design invocation needs before the pre-flight fires."""
    run = tmp_path / "run"
    (run / "epitopes").mkdir(parents=True)
    return run


class TestTheCliRefusesLocally:
    def test_an_unsupported_designer_exits_two_and_names_the_alternatives(
        self, tmp_path: Path
    ) -> None:
        result = CliRunner().invoke(
            cli.main,
            ["design", str(_run_dir(tmp_path)), "--designer", "bindcraft", "--backend", "kaggle"],
        )
        assert result.exit_code == 2, result.output
        assert "unsupported combination" in result.output
        assert "rfdiff_mpnn" in result.output, "the refusal must say what to use instead"

    def test_an_unsupported_validator_is_refused_too(self, tmp_path: Path) -> None:
        result = CliRunner().invoke(
            cli.main,
            ["design", str(_run_dir(tmp_path)), "--validator", "chai1r", "--backend", "kaggle"],
        )
        assert result.exit_code == 2, result.output
        assert "bfloat16" in result.output

    def test_the_refusal_happens_before_any_remote_work(self, tmp_path: Path) -> None:
        """No cost panel, no kernel, no quota. That is the entire point."""
        result = CliRunner().invoke(
            cli.main,
            ["design", str(_run_dir(tmp_path)), "--designer", "boltzgen", "--backend", "kaggle"],
        )
        assert result.exit_code == 2
        assert "Cost estimate" not in result.output, (
            "the refusal must precede the cost panel, which is the last thing "
            "printed before a job is launched"
        )

    def test_a_supported_combination_is_not_refused(self, tmp_path: Path) -> None:
        """The guard must not block the path the benchmark actually uses."""
        result = CliRunner().invoke(
            cli.main,
            [
                "design",
                str(_run_dir(tmp_path)),
                "--designer",
                "rfdiff_mpnn",
                "--backend",
                "kaggle",
                "--dry-run",
            ],
        )
        assert "unsupported combination" not in result.output
        assert result.exit_code == 0, result.output

    def test_revalidation_is_refused_on_the_same_grounds(self, tmp_path: Path) -> None:
        """`validate --revalidate` dispatches to a backend exactly as design does."""
        result = CliRunner().invoke(
            cli.main,
            [
                "validate",
                str(_run_dir(tmp_path)),
                "--validator",
                "chai1r",
                "--revalidate",
                "--backend",
                "kaggle",
            ],
        )
        assert result.exit_code == 2, result.output
        assert "bfloat16" in result.output

# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The gate that checks the environment had no test of its own.

``scripts/check_pinned_environment.py`` is a CI step — ``.github/workflows/ci.yml``
runs it as *"The installed versions are the recorded ones"* — and nothing
exercised it. That matters more than for an ordinary script, because its failure
mode was to report success:

    try:
        from packaging.requirements import Requirement
        from packaging.version import Version
    except ImportError:
        return []

An empty list means *no problems found*. The truth, in that branch, was *nothing
was checked* — and the step exits 0 either way. A gate that cannot run and says
so is a build failure; a gate that cannot run and stays quiet is worse than no
gate at all, because the green tick is now evidence of nothing.

The tests below drive the real functions against constructed environments rather
than asserting on source text, so deleting the fix would fail them.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "check_pinned_environment.py"


def _load() -> Any:
    """Import the script as a module, the way a test can call into it."""
    spec = importlib.util.spec_from_file_location("_check_pinned_environment", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def script() -> Any:
    return _load()


class TestAGateThatCannotRunMustNotReportSuccess:
    """The defect this module exists for."""

    def test_a_missing_packaging_raises_rather_than_returning_no_problems(
        self, script: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Driven, not grepped.

        A source check for the absence of ``except ImportError`` passes against
        a handler that swallows something else. What matters is that the
        environment where the dependency is gone produces a *failure*, not an
        empty list that reads as a clean bill of health.
        """
        real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __import__

        def no_packaging(name: str, *args: Any, **kwargs: Any) -> Any:
            if name.startswith("packaging"):
                raise ImportError("No module named 'packaging'")
            return real_import(name, *args, **kwargs)

        monkeypatch.setitem(sys.modules, "packaging", None)
        monkeypatch.setattr("builtins.__import__", no_packaging)

        with pytest.raises(ImportError):
            script.check_ranges()

    def test_packaging_is_declared_so_that_branch_cannot_be_reached(self) -> None:
        """Static, so it holds in every environment.

        Making the failure loud is only half the fix: the dependency also has to
        be declared, or the loud failure is what every clean install gets.
        """
        import tomllib

        data = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
        project = data["project"]
        groups = [project.get("dependencies", [])]
        groups += list(project.get("optional-dependencies", {}).values())
        declared = {
            req.split(";")[0]
            .split("[")[0]
            .split("=")[0]
            .split("<")[0]
            .split(">")[0]
            .strip()
            .lower()
            for group in groups
            for req in group
        }

        assert "packaging" in declared, (
            "scripts/check_pinned_environment.py imports packaging at the top of "
            "check_ranges(), and CI runs that script as a gate; nothing declares it"
        )


class TestItReportsRealDrift:
    """And the check must still catch what it exists to catch."""

    def test_a_version_outside_its_declared_range_is_reported(
        self, script: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(script, "_declared_ranges", lambda: {"pandas": ">=2.2,<3"})
        monkeypatch.setattr(script, "_installed", lambda name: "3.5.0")

        problems = script.check_ranges()

        assert problems, "a version above the declared ceiling was not reported"
        assert any("pandas" in line for line in problems)

    def test_a_version_inside_its_range_is_not_reported(
        self, script: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Guards the guard: a check that always fails is not a check."""
        monkeypatch.setattr(script, "_declared_ranges", lambda: {"pandas": ">=2.2,<3"})
        monkeypatch.setattr(script, "_installed", lambda name: "2.3.1")

        assert script.check_ranges() == []

    def test_an_uninstalled_package_is_not_reported_as_out_of_range(
        self, script: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Absent is not the same as wrong; an optional extra is legitimately absent."""
        monkeypatch.setattr(script, "_declared_ranges", lambda: {"snakemake": ">=8.0"})
        monkeypatch.setattr(script, "_installed", lambda name: None)

        assert script.check_ranges() == []

    def test_main_exits_non_zero_when_something_is_out_of_range(
        self, script: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The exit status is what CI reads; everything else is decoration."""
        monkeypatch.setattr(script, "check_pins", lambda: [])
        monkeypatch.setattr(script, "check_ranges", lambda: ["pandas 3.5.0 not in >=2.2,<3"])

        assert script.main([]) == 1

    def test_main_exits_zero_on_a_clean_environment(
        self, script: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(script, "check_pins", lambda: [])
        monkeypatch.setattr(script, "check_ranges", lambda: [])

        assert script.main([]) == 0

    def test_ranges_only_skips_the_exact_pin_check(
        self, script: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The flag exists so the unpinned matrix can still check its ranges."""
        called: list[str] = []
        monkeypatch.setattr(script, "check_pins", lambda: called.append("pins") or [])
        monkeypatch.setattr(script, "check_ranges", lambda: [])

        assert script.main(["--ranges-only"]) == 0
        assert called == [], "--ranges-only still ran the exact-pin check"

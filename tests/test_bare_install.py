# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""``pip install bindsight`` must produce a command that starts.

pandas is declared under the ``discover`` extra, not in ``dependencies``. A bare
install is a supported install: ``bindsight --version``, ``--help``, and every
subcommand's help have to work before anyone decides which extras they need.

They did not. ``cli.py`` imported ``DEFAULT_KS`` from
:mod:`bindsight.benchmark.core`, which imports pandas at module scope, and the
value is read at *import* time -- it is interpolated into the ``--k`` help
string, which Click evaluates when the command is defined. So the import
happened on every invocation, and a bare install raised ``ModuleNotFoundError``
before Click could print its version. Moving the constant to
:mod:`bindsight.benchmark.defaults` was not enough on its own, because
``bindsight/benchmark/__init__.py`` eagerly imported ``core``, so reaching any
submodule pulled pandas in anyway; the package now resolves its scoring API
lazily, exactly as :mod:`bindsight.report` does.

No CI job could have caught this. Every one of them installs
``.[dev,discover,report]``, so pandas is always present and the import always
succeeds. These tests install nothing -- they run a clean interpreter with a
meta-path hook that makes ``import pandas`` fail, which is what the bare
install's environment looks like from the inside.

The hook is the whole experiment, so it is tested too. If it silently stopped
blocking, every assertion below would pass while proving nothing at all --
which is the failure mode this repository keeps finding in its own tests.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap

import pytest

#: Installed ahead of the code under test: makes pandas unimportable in-process
#: without touching the environment on disk. ``find_spec`` raising (rather than
#: returning None) is what a missing distribution looks like to every importer.
_BLOCK_PANDAS = textwrap.dedent(
    """
    import sys

    class _NoPandas:
        def find_spec(self, name, path=None, target=None):
            if name == "pandas" or name.startswith("pandas."):
                raise ImportError("No module named 'pandas'")
            return None

    sys.meta_path.insert(0, _NoPandas())
    """
)


def _without_pandas(code: str) -> subprocess.CompletedProcess[str]:
    """Run *code* in a fresh interpreter where pandas cannot be imported.

    A subprocess, not a fixture: pandas is already resident in the pytest
    process, and unloading it in-process leaves partially-initialised modules
    behind. The clean interpreter is the only honest way to ask this question.
    """
    return subprocess.run(
        [sys.executable, "-c", _BLOCK_PANDAS + textwrap.dedent(code)],
        capture_output=True,
        text=True,
        check=False,
    )


class TestTheBlockerBlocks:
    """Controls. Without these, every test below could pass on a no-op hook."""

    def test_pandas_itself_is_unreachable(self) -> None:
        """The premise: inside this interpreter, pandas is not installed."""
        proc = _without_pandas("import pandas")

        assert proc.returncode != 0, "the hook let pandas through; nothing below is a test"
        assert "No module named 'pandas'" in proc.stderr

    def test_a_module_that_needs_pandas_still_fails(self) -> None:
        """And the block reaches through our own imports, not just the top level.

        ``benchmark.core`` genuinely needs pandas. If this passed, the hook
        would be failing to see imports made from inside the package -- and
        ``test_the_cli_imports`` would be green for the wrong reason.
        """
        proc = _without_pandas("import bindsight.benchmark.core")

        assert proc.returncode != 0, (
            "benchmark.core imported without pandas, so either it no longer needs "
            "pandas (retire this control) or the hook is not reaching package imports"
        )
        assert "No module named 'pandas'" in proc.stderr

    def test_the_interpreter_is_otherwise_usable(self) -> None:
        """The hook blocks pandas and nothing else."""
        proc = _without_pandas("import json, click, bindsight; print('ok')")

        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.strip() == "ok"


class TestTheCommandStartsWithoutTheExtras:
    """What a reader gets from ``pip install bindsight`` and nothing more."""

    def test_the_cli_module_imports(self) -> None:
        proc = _without_pandas(
            """
            import sys
            import bindsight.cli
            print("pandas" in sys.modules)
            """
        )

        assert proc.returncode == 0, f"bindsight.cli cannot be imported bare:\n{proc.stderr}"
        assert proc.stdout.strip() == "False", "cli imported pandas by some other route"

    @pytest.mark.parametrize("argv", [["--version"], ["--help"]])
    def test_the_entry_point_runs(self, argv: list[str]) -> None:
        """Not just importable -- the command a reader types has to answer."""
        proc = _without_pandas(
            f"""
            from click.testing import CliRunner
            from bindsight.cli import main
            result = CliRunner().invoke(main, {argv!r})
            print(result.exit_code)
            print(result.output, end="")
            if result.exception is not None:
                raise SystemExit(repr(result.exception))
            """
        )

        assert proc.returncode == 0, f"bindsight {' '.join(argv)} failed bare:\n{proc.stderr}"
        code, _, output = proc.stdout.partition("\n")
        assert code.strip() == "0", output

    def test_every_subcommands_help_renders(self) -> None:
        """Including ``benchmark --help``, whose text is built from DEFAULT_KS.

        The ``--k`` help string is the reason the constant was read at import
        time in the first place, so it is the one that has to keep working --
        and it has to still say what the default is, not silently lose it.
        """
        proc = _without_pandas(
            """
            from click.testing import CliRunner
            from bindsight.cli import main
            runner = CliRunner()
            failures = []
            for name in sorted(main.commands):
                result = runner.invoke(main, [name, "--help"])
                if result.exit_code != 0:
                    failures.append((name, repr(result.exception)))
            print(failures)
            k_help = runner.invoke(main, ["benchmark", "--help"]).output
            # Click re-wraps the help text, so the rendered cutoffs may be split
            # across lines. Compare on collapsed whitespace, not on the literal.
            print(" ".join(k_help.split()))
            """
        )

        assert proc.returncode == 0, proc.stderr
        failures, _, k_help = proc.stdout.partition("\n")
        assert failures.strip() == "[]", f"subcommand help failed bare: {failures}"
        assert "Default: 5, 10, 20." in k_help, k_help


class TestTheBenchmarkPackageResolvesLazily:
    """The package import must not be the thing that drags pandas back in."""

    def test_importing_the_package_leaves_pandas_unloaded(self) -> None:
        proc = _without_pandas(
            """
            import sys
            import bindsight.benchmark as pkg
            print(pkg.DEFAULT_KS, "pandas" in sys.modules)
            """
        )

        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.strip() == "(5, 10, 20) False"

    def test_the_two_definitions_are_one_object(self) -> None:
        """``core`` re-exports the constant; it does not keep a second copy.

        Two tuples with equal contents would pass an ``==`` test forever while
        drifting apart in value, which is precisely the duplication the
        constant exists to prevent.
        """
        from bindsight.benchmark import core, defaults

        assert core.DEFAULT_KS is defaults.DEFAULT_KS

    def test_the_scoring_api_still_resolves(self) -> None:
        """The lazy hook returns the real functions, not a stand-in."""
        import bindsight.benchmark as pkg
        from bindsight.benchmark import core

        for name in ("run_benchmark", "score_run", "load_known_antigens"):
            assert getattr(pkg, name) is getattr(core, name), name

    def test_submodule_imports_still_work(self) -> None:
        """``__getattr__`` runs before the submodule machinery.

        Raising ``ImportError`` there instead of ``AttributeError`` would break
        every one of these -- the trap :mod:`bindsight.report` documents.
        """
        from bindsight.benchmark import core, defaults

        assert core.__name__ == "bindsight.benchmark.core"
        assert defaults.__name__ == "bindsight.benchmark.defaults"

    def test_unknown_attribute_raises_attribute_error(self) -> None:
        import bindsight.benchmark as pkg

        with pytest.raises(AttributeError, match="no attribute 'nope'"):
            _ = pkg.nope

    def test_dir_advertises_the_lazy_exports(self) -> None:
        import bindsight.benchmark as pkg

        listed = dir(pkg)
        assert "DEFAULT_KS" in listed
        assert "run_benchmark" in listed

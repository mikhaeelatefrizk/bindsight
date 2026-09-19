# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Streamlit is gone, and the ways it could come back.

The application was deleted when the interface became server-rendered. Three
constants outlived it in `bindsight/report/theme.py` -- `PAGE_TITLE`,
`PAGE_ICON` and `PAGE_LAYOUT`, which are the three arguments of
`st.set_page_config`. Nothing read them, and `PAGE_LAYOUT` was annotated
`Literal["centered", "wide"]` with a comment explaining that this was the type
`st.set_page_config` requires: a type chosen to satisfy a function that no
longer existed.

A `grep` for "streamlit" never found them, because the comment says
`st.set_page_config`. They survived the migration for the same reason this file
does not search for the word: an API surface does not have to name its vendor.

What is deliberately NOT asserted here is the absence of the word. Several
mentions must survive -- the CHANGELOG records the migration, and
`pyproject.toml` explains that the `httpx2` pin exists because the removed
package was supplying httpx transitively. Deleting those would delete the
reasons, and a reason deleted is a change waiting to be reverted. (A third
lived in the workflow that probed the retired hosted deployment, and was
deleted with it; the CHANGELOG entry recording that retirement carries why
its probe did not ask for a health endpoint that release removed.) What must
not come back is the
dependency, the import, and the API surface.
"""

from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

#: Names that only ever existed as arguments to `st.set_page_config`.
PAGE_CONFIG_NAMES = ("PAGE_TITLE", "PAGE_ICON", "PAGE_LAYOUT")

#: Streamlit API names unambiguous enough to look for in a template, where
#: there is no syntax tree to consult. `write` is excluded on purpose: every
#: file-like object has one.
TEMPLATE_API_NAMES = (
    "set_page_config",
    "session_state",
    "cache_data",
    "cache_resource",
    "file_uploader",
    "plotly_chart",
    "experimental_rerun",
    "sidebar",
)


def _tracked(*paths: str) -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", *paths], cwd=REPO, capture_output=True, text=True
    ).stdout.split()
    return [REPO / f for f in out]


def _scope_bindings(scope: ast.AST) -> set[str]:
    """Names bound directly in ``scope``, not in any nested scope.

    Parameters count for a function; assignments, imports and nested
    definitions count for any scope. Bindings inside a nested function belong
    to that function, which is the whole point of resolving this per scope.
    """
    bound: set[str] = set()

    if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
        args = scope.args
        for arg in [*args.posonlyargs, *args.args, *args.kwonlyargs]:
            bound.add(arg.arg)
        for arg in (args.vararg, args.kwarg):
            if arg is not None:
                bound.add(arg.arg)

    stack: list[ast.AST] = (
        [scope.body] if isinstance(scope, ast.Lambda) else list(getattr(scope, "body", []))
    )
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(node.name)  # the name is bound here; the body is not this scope
            continue
        if isinstance(node, ast.Lambda):
            continue
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            bound.add(node.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                bound.add(alias.asname or alias.name.split(".")[0])
        stack.extend(ast.iter_child_nodes(node))

    return bound


def unbound_st_calls(source: str) -> list[str]:
    """``st.foo()`` where ``st`` is not bound in any enclosing scope.

    A text scan fails in both directions. It matched ``manifest.write(...)`` and
    ``dest.write_bytes(...)``, which end in the same two letters; and it flagged
    ``scripts/build_docs_results.py``, where ``st`` is a parameter annotated
    ``showcase.StudyShowcase`` -- a local with an unlucky name and nothing to do
    with the removed app.

    Resolving it per FILE was the next mistake, and the mutation test caught it:
    because that file binds ``st`` in two of its functions, a Streamlit call
    added to any other function in it was invisible.

    So binding is resolved the way Python resolves it, innermost scope outward.
    """
    found: list[tuple[int, str]] = []

    def visit(scope: ast.AST, enclosing: set[str]) -> None:
        visible = enclosing | _scope_bindings(scope)

        stack: list[ast.AST] = (
            [scope.body] if isinstance(scope, ast.Lambda) else list(getattr(scope, "body", []))
        )
        while stack:
            node = stack.pop()
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                visit(node, visible)  # its own scope, then stop descending here
                continue
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "st"
                and "st" not in visible
            ):
                found.append((node.lineno, node.func.attr))
            stack.extend(ast.iter_child_nodes(node))

    visit(ast.parse(source), set())
    return [f"line {n}: st.{attr}(...)" for n, attr in sorted(set(found))]


class TestTheDependencyIsGone:
    def test_nothing_declares_streamlit(self) -> None:
        import tomllib

        pyproject = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
        declared = list(pyproject["project"]["dependencies"])
        for group in pyproject["project"].get("optional-dependencies", {}).values():
            declared += list(group)

        offenders = [d for d in declared if d.lower().startswith("streamlit")]

        assert not offenders, f"streamlit is declared as a dependency: {offenders}"

    def test_no_requirements_file_pins_it(self) -> None:
        checked = 0
        for path in _tracked("requirements*.txt", "envs/*.txt"):
            if not path.is_file():
                continue
            checked += 1
            for line in path.read_text(encoding="utf-8", errors="ignore").split("\n"):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                assert not re.match(r"^streamlit\b", stripped, re.I), (
                    f"{path.relative_to(REPO)} pins streamlit: {stripped!r}"
                )

        assert checked, "no requirements file was found, so this checked nothing"


class TestTheImportIsGone:
    def test_nothing_imports_streamlit(self) -> None:
        offenders = []
        for path in _tracked("bindsight", "tests", "scripts", "benchmarks"):
            if path.suffix != ".py" or not path.is_file():
                continue
            for number, line in enumerate(path.read_text(encoding="utf-8").split("\n"), 1):
                if re.match(r"\s*(import streamlit|from streamlit\b)", line):
                    offenders.append(f"{path.relative_to(REPO)}:{number}")

        assert not offenders, f"streamlit is imported at: {offenders}"

    def test_the_package_never_loads_it_at_import_time(self) -> None:
        """Streamlit may still be installed on a developer's machine.

        That is what hid the `httpx` ghost dependency: an accidental import
        succeeds silently where the package is present and fails only on a
        clean machine. Watching `sys.modules` is the check that works either
        way.
        """
        import importlib
        import pkgutil
        import sys

        import bindsight

        for module in pkgutil.walk_packages(bindsight.__path__, prefix="bindsight."):
            try:
                importlib.import_module(module.name)
            except Exception:  # an absent optional extra is not this test's business
                continue

        assert "streamlit" not in sys.modules, (
            "importing bindsight pulled streamlit in; on a machine without it "
            "installed this would be an ImportError instead"
        )


class TestTheApiSurfaceIsGone:
    """The traces that do not carry the vendor's name."""

    def test_no_module_calls_the_streamlit_api(self) -> None:
        offenders = []
        for path in _tracked("bindsight", "scripts", "benchmarks"):
            if path.suffix != ".py" or not path.is_file():
                continue
            for hit in unbound_st_calls(path.read_text(encoding="utf-8")):
                offenders.append(f"{path.relative_to(REPO)}:{hit}")

        assert not offenders, "streamlit API calls:\n  " + "\n  ".join(offenders)

    def test_no_template_calls_the_streamlit_api(self) -> None:
        """Templates have no syntax tree, so they get the name list instead."""
        offenders = []
        for path in _tracked("bindsight"):
            if path.suffix != ".j2" or not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            offenders += [
                f"{path.relative_to(REPO)}: st.{name}"
                for name in TEMPLATE_API_NAMES
                if f"st.{name}" in text
            ]

        assert not offenders, f"streamlit API in templates: {offenders}"

    @pytest.mark.parametrize("name", PAGE_CONFIG_NAMES)
    def test_the_page_config_constants_are_gone(self, name: str) -> None:
        """Each is an argument of `st.set_page_config` and nothing else."""
        theme = (REPO / "bindsight" / "report" / "theme.py").read_text(encoding="utf-8")

        assert name not in theme, (
            f"{name} is back in theme.py. It exists only to be passed to "
            "st.set_page_config, which this project no longer calls."
        )

    def test_no_streamlit_config_directory(self) -> None:
        """`.streamlit/config.toml` was read from the working directory.

        It sat at this repository's root and the Space never received it, so
        its theme and telemetry settings applied to local clones only while the
        file's own comment claimed the Space was covered.
        """
        assert not (REPO / ".streamlit").exists(), "a .streamlit/ directory is back"

    def test_the_entrypoint_modules_are_gone(self) -> None:
        for name in ("streamlit_app.py", "webapp.py"):
            found = list((REPO / "bindsight").rglob(name))
            assert not found, f"{name} is back at {found}"


class TestTheScanWouldCatchWhatItLooksFor:
    """Each check proved against a sample, so none can go quietly blind."""

    def test_it_catches_a_real_streamlit_call(self) -> None:
        source = 'import streamlit as st\nst.set_page_config(page_title="x")\n'
        # The import binds `st`, so this file is judged by the import test
        # instead -- which is the division of labour, not a gap.
        assert unbound_st_calls(source) == []

    def test_it_catches_a_call_with_no_import_in_sight(self) -> None:
        """A snippet pasted in without its import is the case this covers."""
        assert unbound_st_calls("st.set_page_config(layout='wide')\n")
        assert unbound_st_calls("def f():\n    st.write(1)\n")

    def test_it_ignores_a_local_named_st(self) -> None:
        """`build_docs_results.py` really does have one, annotated StudyShowcase."""
        assert unbound_st_calls("def g(st):\n    return st.rows()\n") == []
        assert unbound_st_calls("st = make()\nst.rows()\n") == []

    def test_a_local_in_one_function_does_not_excuse_another(self) -> None:
        """The hole the mutation test found.

        Resolving `st` per file meant that a single function taking it as a
        parameter blinded the whole module -- which is the exact shape of
        `build_docs_results.py`.
        """
        source = (
            "def uses_a_local(st):\n"
            "    return st.rows()\n"
            "\n"
            "def leftover():\n"
            "    st.set_page_config(layout='wide')\n"
        )

        hits = unbound_st_calls(source)

        assert len(hits) == 1, hits
        assert "set_page_config" in hits[0]

    def test_a_module_level_binding_still_covers_its_functions(self) -> None:
        """Enclosing scopes count, or every helper would be flagged."""
        assert unbound_st_calls("st = make()\n\ndef f():\n    return st.rows()\n") == []

    def test_it_ignores_identifiers_that_merely_end_in_st(self) -> None:
        for sample in (
            "manifest.write(root / 'run_manifest.jsonld')\n",
            "dest.write_bytes(src.read_bytes())\n",
        ):
            assert unbound_st_calls(sample) == [], sample

    def test_the_repository_listing_is_not_empty(self) -> None:
        """Every check above iterates `git ls-files`; an empty list passes all of them."""
        assert len(_tracked("bindsight")) > 50, (
            "git ls-files returned almost nothing, so the scans above checked almost nothing"
        )

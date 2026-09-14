# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Smoke test: every public module imports cleanly."""

from __future__ import annotations

import importlib

import pytest

#: Modules whose import genuinely cannot be attempted here, each with a reason.
#: Anything not listed is expected to import; the list below is the exception,
#: not the scope.
_UNIMPORTABLE: frozenset[str] = frozenset()


def _public_modules() -> list[str]:
    """Every module in the package, discovered.

    This was a hand-written list of 53 names against a package of 78 modules, so
    25 were unchecked — including ``bindsight.plugins``, the entry-point loader
    every backend goes through. A smoke test whose scope is typed out by hand
    stops covering the code the moment someone adds a file.
    """
    import pkgutil

    import bindsight

    found = ["bindsight"]
    for info in pkgutil.walk_packages(bindsight.__path__, "bindsight."):
        if info.name.rsplit(".", 1)[-1].startswith("_"):
            continue
        found.append(info.name)
    return sorted(set(found) - _UNIMPORTABLE)


PUBLIC_MODULES = _public_modules()


@pytest.mark.parametrize("module_name", PUBLIC_MODULES)
def test_module_imports(module_name: str) -> None:
    """Every public module imports without error."""
    importlib.import_module(module_name)


def test_version_is_set() -> None:
    """``bindsight.__version__`` is a non-empty string."""
    import bindsight

    assert isinstance(bindsight.__version__, str)
    assert bindsight.__version__


def test_the_scan_covers_the_whole_package() -> None:
    """Guards the guard: a discovery that finds a handful would pass trivially."""
    from pathlib import Path as _Path

    import bindsight

    on_disk = {
        p.stem if p.name != "__init__.py" else p.parent.name
        for p in _Path(bindsight.__file__).parent.rglob("*.py")
        if "__pycache__" not in p.parts and not p.stem.startswith("_")
    }

    assert len(PUBLIC_MODULES) >= len(on_disk) * 0.8, (
        f"discovered {len(PUBLIC_MODULES)} modules against roughly {len(on_disk)} "
        "files on disk; the walk is missing most of the package"
    )
    assert "bindsight.plugins" in PUBLIC_MODULES

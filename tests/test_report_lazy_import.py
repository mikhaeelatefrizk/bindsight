# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""``bindsight.report`` must not drag heavy dependencies in on import.

:mod:`bindsight.report.theme` and :mod:`bindsight.report.showcase` are written
to be stdlib-only at module scope so they work in minimal environments — the
documentation build installs neither pandas nor jinja2 by choice. That intent
was defeated by the package ``__init__``, which eagerly imported
``report/html.py`` and therefore pandas, for *any* access to the package.

These tests run the import in a subprocess with a clean interpreter, because
pandas is already resident in the pytest process and an in-process check would
prove nothing.
"""

from __future__ import annotations

import subprocess
import sys

import pytest


def _in_clean_interpreter(code: str) -> subprocess.CompletedProcess[str]:
    """Run ``code`` in a fresh interpreter and return the completed process."""
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize("module", ["bindsight.report", "bindsight.report.theme"])
def test_import_does_not_pull_in_pandas(module: str) -> None:
    """Importing the package (or the theme) leaves pandas unloaded."""
    proc = _in_clean_interpreter(
        f"import sys, {module}; print('pandas' in sys.modules or 'jinja2' in sys.modules)"
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "False", f"{module} pulled in a heavy dependency"


def test_showcase_import_does_not_pull_in_pandas() -> None:
    """The benchmark loaders stay stdlib-only through the package import."""
    proc = _in_clean_interpreter(
        "import sys; from bindsight.report import showcase; "
        "print('pandas' in sys.modules or 'jinja2' in sys.modules)"
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "False"


def test_render_run_still_importable() -> None:
    """The one public export still resolves, via the lazy hook."""
    from bindsight.report import render_run

    assert callable(render_run)

    from bindsight.report.html import render_run as direct

    assert render_run is direct


def test_submodule_imports_still_work() -> None:
    """``from bindsight.report import <submodule>`` must keep working.

    ``__getattr__`` runs before the submodule import machinery, so returning
    anything other than ``AttributeError`` for an unknown name would break these.
    """
    from bindsight.report import html, showcase, streamlit_app, theme, webapp

    for mod in (html, showcase, streamlit_app, theme, webapp):
        assert mod.__name__.startswith("bindsight.report.")


def test_unknown_attribute_raises_attribute_error() -> None:
    """Unknown names raise AttributeError, not ImportError."""
    import bindsight.report as report_pkg

    with pytest.raises(AttributeError, match="no attribute 'nope'"):
        _ = report_pkg.nope


def test_dir_advertises_the_lazy_export() -> None:
    """``dir()`` still lists the lazily-resolved name."""
    import bindsight.report as report_pkg

    assert "render_run" in dir(report_pkg)

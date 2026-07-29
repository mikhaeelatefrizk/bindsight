# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Reporting: paper-style HTML + Streamlit dashboard, both backed by the same data.

``render_run`` is resolved lazily. Importing it eagerly pulled in
:mod:`bindsight.report.html`, and therefore pandas and jinja2, for anyone who
touched *anything* under this package — including :mod:`bindsight.report.theme`
and :mod:`bindsight.report.showcase`, both of which are deliberately
stdlib-only at module scope so they stay usable in minimal environments. The
documentation build is exactly such an environment.

The lazy hook must raise ``AttributeError`` (never ``ImportError``) for unknown
names: ``from bindsight.report import showcase`` consults ``__getattr__`` before
falling back to the submodule import machinery, so swallowing the error here
would break every ``from bindsight.report import <submodule>`` in the codebase.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    from bindsight.report.html import render_run

__all__ = ["render_run"]


def __getattr__(name: str) -> Any:
    """Resolve ``render_run`` on first access (PEP 562)."""
    if name == "render_run":
        from bindsight.report.html import render_run as _render_run

        return _render_run
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    """Keep ``dir()`` honest about the lazily-exported name."""
    return sorted({*globals(), *__all__})

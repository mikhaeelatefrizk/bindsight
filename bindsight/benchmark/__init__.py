# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Rediscovery benchmarking against the held-out known-antigen set.

Scores one or more finished ``bindsight`` run directories by how well they
resurface the literature-validated known antigens in ``benchmarks/known.tsv``
(rank of each known antigen, recall@k, enrichment), and renders a side-by-side
HTML report. This is the implementation behind the ``bindsight benchmark``
command referenced in ``docs/use-cases.md``.

Every public name here is resolved lazily. Importing them eagerly pulled
:mod:`bindsight.benchmark.core`, and therefore pandas, into anything that
touched this package by any route -- including ``from
bindsight.benchmark.defaults import DEFAULT_KS``, which needs nothing but a
tuple. :mod:`bindsight.cli` reads that tuple at import time, so a plain ``pip
install bindsight`` (pandas lives in the ``discover`` extra) shipped a command
that raised ``ModuleNotFoundError`` before ``--version`` could print.

The lazy hook must raise ``AttributeError`` (never ``ImportError``) for unknown
names, for the reason :mod:`bindsight.report` gives: ``from bindsight.benchmark
import core`` consults ``__getattr__`` before the submodule import machinery,
so swallowing the error here would break every such import in the codebase.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from bindsight.benchmark.defaults import DEFAULT_KS

if TYPE_CHECKING:  # pragma: no cover - typing only
    from bindsight.benchmark.core import (
        KnownAntigen,
        RunScore,
        load_known_antigens,
        render_benchmark_html,
        run_benchmark,
        score_run,
    )

# Spelled out as a literal, because mypy reads ``__all__`` statically and a list
# built with a splat tells it nothing -- it then reports every re-export as not
# explicitly exported. ``_LAZY`` is derived from it rather than written twice.
__all__ = [
    "DEFAULT_KS",
    "KnownAntigen",
    "RunScore",
    "load_known_antigens",
    "render_benchmark_html",
    "run_benchmark",
    "score_run",
]

#: Everything in ``__all__`` except the one name that costs nothing to import.
_LAZY = frozenset(__all__) - {"DEFAULT_KS"}


def __getattr__(name: str) -> Any:
    """Resolve the scoring API on first access (PEP 562)."""
    if name in _LAZY:
        import bindsight.benchmark.core as _core

        return getattr(_core, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    """Keep ``dir()`` honest about the lazily-exported names."""
    return sorted({*globals(), *__all__})

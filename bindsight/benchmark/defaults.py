# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Benchmark constants that cost nothing to import.

``DEFAULT_KS`` lived in :mod:`bindsight.benchmark.core`, which imports pandas at
module scope. :mod:`bindsight.cli` needs the value at import time -- it is
interpolated into a ``--k`` help string, which Click evaluates when the command
is defined -- so every invocation of ``bindsight``, including ``--version`` and
``--help``, pulled pandas in. pandas is declared under the ``discover`` extra
and not in the base dependencies, so a plain ``pip install bindsight`` produced
a command that could not start.

CI never saw it: every job installs ``.[dev,discover,report]``.

This module is stdlib-only at module scope and must stay that way.
"""

from __future__ import annotations

#: Rank cutoffs reported by ``bindsight benchmark`` when none are given.
#:
#: Named once, here. The CLI shows them in its help text and falls back to them
#: when ``--k`` is absent, and the scoring functions take them as a default
#: argument -- three readers of one value, which is three chances for it to be
#: written out by hand and drift.
DEFAULT_KS: tuple[int, ...] = (5, 10, 20)

__all__ = ["DEFAULT_KS"]

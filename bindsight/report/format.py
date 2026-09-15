# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""How bindsight writes a number down.

Shared by both surfaces on purpose. These lived inside the web app, and the
standalone report kept its own ``f"{v:.3g}"`` -- so the same ``padj`` from the
same run printed as ``<1e-300`` in the browser and as ``0`` in the file a
collaborator opened from an email. A design system that shares a stylesheet and
not its rules only makes the disagreement harder to spot.

Three of these are claims rather than cosmetics:

* **Absence is an em dash, never a zero.** A crisp ``0`` in metric chrome reads
  as a measurement, and a crashed run then looks like one that found nothing.
* **A p-value never prints as zero.** CA9's ``padj`` is literally ``0.0`` in the
  artifact -- below floating-point resolution, not measured as zero.
* **A confidence level is read, never assumed.** An interval labelled with a
  level nothing computed states two things from two different places.
"""

from __future__ import annotations

from typing import Any

#: How a number with nothing behind it is written. Never ``0``: four zeros in
#: metric chrome read as a measurement, and a broken run then looks like a run
#: that found nothing.
ABSENT = "—"


# ---------------------------------------------------------------------------
# Presentation helpers
# ---------------------------------------------------------------------------
def fmt(value: Any, digits: int = 2) -> str:
    """A number, or :data:`ABSENT` if there is not one."""
    if value is None:
        return ABSENT
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ABSENT
    if number != number:  # NaN
        return ABSENT
    return f"{number:.{digits}f}"


def fmt_int(value: Any) -> str:
    """An integer for the screen, or the em dash when there is not one.

    Absence renders as ``—``. It never renders as ``0``: a crisp zero in
    metric chrome reads as a measurement, which is how a run that crashed
    comes to look like a run that found nothing.
    """
    if value is None:
        return ABSENT
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return ABSENT


def fmt_p(value: Any) -> str:
    """A p-value that never prints as zero.

    ``%.2e`` rendered CA9's ``padj`` -- literally 0.0 in the artifact, below
    floating-point resolution -- as ``0.00e+00``. A p of zero is not a p.
    """
    if value is None:
        return ABSENT
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ABSENT
    if number != number:
        return ABSENT
    if number <= 0:
        return "<1e-300"
    # Scientific below 1e-3, not 1e-4: the study's own permutation p is
    # 3.97e-04, and fixed notation rendered that as "0.0004" -- losing the two
    # significant figures that distinguish it from the floor it sits on.
    if number < 1e-3:
        return f"{number:.2e}"
    return f"{number:.4f}"


def interval(low: Any, high: Any, *, digits: int = 3, confidence: Any = None) -> str:
    """``95% CI 0.188–0.513``, or :data:`ABSENT`.

    The confidence level is read, never assumed. An interval labelled with a
    level nothing computed states two things from two different places.
    """
    if low is None or high is None:
        return ABSENT
    label = ""
    if confidence is not None:
        try:
            label = f"{float(confidence) * 100:g}% "
        except (TypeError, ValueError):
            label = ""
    return f"{label}CI {fmt(low, digits)}–{fmt(high, digits)}"

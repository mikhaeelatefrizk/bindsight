# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shared, conservative wording for recorded numerical fitting diagnostics."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from bindsight.deg.diagnostics import read_fit_diagnostics

_CONVERGENCE_LABELS = {
    "_genewise_converged": "Gene-wise dispersion",
    "_MAP_converged": "MAP dispersion",
    "_LFC_converged": "Log fold-change",
}
_SCOPE = (
    "These diagnostics describe numerical fitting. They do not establish biological validity "
    "or experimental validation."
)


def _count(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def fit_summary(run_dir: Path) -> dict[str, Any]:
    """Describe recorded warnings without treating missing diagnostics as a healthy fit."""
    diagnostics = read_fit_diagnostics(run_dir / "deg" / "results.parquet")
    summary: dict[str, Any] = {
        "available": diagnostics is not None,
        "warnings": [],
        "details": [],
        "scope": _SCOPE,
    }
    if diagnostics is None:
        summary["details"].append(
            "Numerical fit diagnostics are unavailable for this run. "
            "They were not recorded, could not be read, or did not match the DEG table."
        )
        return summary

    residual = _count(diagnostics.get("residual_degrees_of_freedom"))
    if residual is None:
        summary["details"].append("Residual degrees of freedom were not recorded.")
    elif residual < 3:
        summary["warnings"].append(
            f"Residual degrees of freedom: {residual} (below 3). "
            "The design leaves little information for estimating residual variation; "
            "interpret the resulting uncertainty cautiously."
        )
    else:
        summary["details"].append(f"Residual degrees of freedom: {residual}.")

    convergence = diagnostics.get("convergence")
    convergence = convergence if isinstance(convergence, dict) else {}
    for name, label in _CONVERGENCE_LABELS.items():
        record = convergence.get(name)
        record = record if isinstance(record, dict) else {}
        failed = _count(record.get("not_converged"))
        unknown = _count(record.get("unreported"))
        if failed is None:
            summary["details"].append(f"{label}: optimizer convergence counts were not recorded.")
        elif failed:
            summary["warnings"].append(
                f"{label}: {failed} genes had a nonconverged optimizer flag. "
                "A returned estimate does not establish optimizer convergence."
            )
        else:
            summary["details"].append(f"{label}: 0 recorded nonconverged optimizer flags.")
        if unknown:
            summary["warnings"].append(f"{label}: convergence was unreported for {unknown} genes.")
        elif unknown is None:
            summary["details"].append(f"{label}: the number of unreported flags is unknown.")

    repairs = diagnostics.get("dispersion_fallback_repairs")
    counts = (
        [_count(record.get("n_failed")) if isinstance(record, dict) else None for record in repairs]
        if isinstance(repairs, list)
        else None
    )
    if counts is None or any(value is None for value in counts):
        summary["details"].append("Dispersion fallback use was not fully recorded.")
    else:
        total = sum(value for value in counts if value is not None)
        if total:
            summary["warnings"].append(
                f"The regularization-preserving dispersion grid fallback was used for {total} "
                f"fits across {len(counts)} inference calls. Counts can include the same gene "
                "more than once; fallback estimates retain their nonconverged optimizer flags."
            )
        else:
            summary["details"].append(
                "The recorded inference calls required 0 dispersion fallbacks."
            )
    return summary

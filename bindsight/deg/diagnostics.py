# SPDX-License-Identifier: AGPL-3.0-or-later
"""Persist numerical fit diagnostics against the exact differential-expression table."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from bindsight.provenance import sha256_file


def diagnostics_path(deg_table: Path) -> Path:
    """Return the diagnostics sidecar beside the DEG table."""
    return deg_table.with_name("fit_diagnostics.json")


def write_fit_diagnostics(deg_table: Path, diagnostics: dict[str, Any]) -> None:
    """Bind a completed fit's numerical record to its actual output bytes."""
    path = diagnostics_path(deg_table)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "deg_table_sha256": sha256_file(deg_table),
                "fit_diagnostics": diagnostics,
            },
            indent=2,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(path)


def read_fit_diagnostics(deg_table: Path) -> dict[str, Any] | None:
    """Read matching diagnostics; historical, damaged, or stale records stay unknown."""
    try:
        body = json.loads(diagnostics_path(deg_table).read_text(encoding="utf-8"))
        if not isinstance(body, dict) or body.get("schema_version") != 1:
            return None
        diagnostics = body.get("fit_diagnostics")
        if not isinstance(diagnostics, dict) or not diagnostics:
            return None
        if body.get("deg_table_sha256") != sha256_file(deg_table):
            return None
        return diagnostics
    except (OSError, ValueError):
        return None

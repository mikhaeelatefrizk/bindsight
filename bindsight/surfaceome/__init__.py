# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Surfaceome filtering — SURFY (gene list) and SURFACE-Bind (targetable sites)."""

from bindsight.surfaceome.surfy import (
    SURFY_PROTEIN_COUNT,
    is_surface_protein,
    load_surfy,
    populate_surfy_cache,
)

__all__ = [
    "SURFY_PROTEIN_COUNT",
    "is_surface_protein",
    "load_surfy",
    "populate_surfy_cache",
]

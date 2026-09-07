# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Surfaceome membership — is this protein on the cell surface?

Two sources, unioned: the SURFY machine-learning surfaceome (2,886
accessions) and a UniProt cell-membrane extension built from the curated
SL-0039 annotation (1,915 further accessions, 4,801 in total). The extension
exists because SURFY omits CA9 and STEAP1, both established antigens, which
made them unreachable at any expression level.

Targetable-site lookup is a different question and lives in
``bindsight.epitopes``; this package answers membership only.
"""

from bindsight.surfaceome.surfy import (
    SURFY_PROTEIN_COUNT,
    is_surface_protein,
    load_surfaceome,
    load_surfaceome_extension,
    load_surfaceome_gene_map,
    load_surfy,
    load_surfy_gene_map,
    populate_surfy_cache,
)

__all__ = [
    "SURFY_PROTEIN_COUNT",
    "is_surface_protein",
    "load_surfaceome",
    "load_surfaceome_extension",
    "load_surfaceome_gene_map",
    "load_surfy",
    "load_surfy_gene_map",
    "populate_surfy_cache",
]

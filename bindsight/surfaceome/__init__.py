# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Surfaceome membership — is this protein on the cell surface?

Two sources, unioned: the SURFY machine-learning surfaceome (2,886
accessions) and a UniProt cell-membrane extension built from the curated
SL-0039 annotation (1,915 further accessions, 4,801 in total). The extension
exists because SURFY omits CA9 and STEAP1, both established antigens, which
made them unreachable at any expression level.

Those three figures are checked against the lists themselves by
``tests/test_docs_claims.py``; they appear in several documents, and a number
restated in five places with nothing comparing it to the data is a number that
drifts.

Targetable-site lookup is a different question and lives in
``bindsight.epitopes``; this package answers membership only.
"""

from bindsight.surfaceome.surfy import (
    surfaceome_source,
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
    "surfaceome_source",
    "is_surface_protein",
    "load_surfaceome",
    "load_surfaceome_extension",
    "load_surfaceome_gene_map",
    "load_surfy",
    "load_surfy_gene_map",
    "populate_surfy_cache",
]

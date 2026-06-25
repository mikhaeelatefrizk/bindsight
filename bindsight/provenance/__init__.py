# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Provenance subsystem.

The :mod:`bindsight.provenance` package owns the inter-module contract: every
stage in the pipeline emits a :class:`StageRecord` into a single
``run_manifest.jsonld`` file (PROV-O JSON-LD), and the final stage packages
everything as an `RO-Crate <https://www.researchobject.org/ro-crate/>`_.

This is the audit trail that lets a reviewer, clinician, or future user walk
from a designed binder PDB back to the patient cohort it came from.
"""

from bindsight.provenance.manifest import (
    ContainerRef,
    InputRef,
    Manifest,
    OutputRef,
    StageRecord,
    ToolRef,
    new_manifest,
    sha256_file,
)

__all__ = [
    "ContainerRef",
    "InputRef",
    "Manifest",
    "OutputRef",
    "StageRecord",
    "ToolRef",
    "new_manifest",
    "sha256_file",
]

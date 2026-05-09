"""Provenance subsystem.

The :mod:`xpr2bind.provenance` package owns the inter-module contract: every
stage in the pipeline emits a :class:`StageRecord` into a single
``run_manifest.jsonld`` file (PROV-O JSON-LD), and the final stage packages
everything as an `RO-Crate <https://www.researchobject.org/ro-crate/>`_.

This is the audit trail that lets a reviewer, clinician, or future user walk
from a designed binder PDB back to the patient cohort it came from.
"""

from xpr2bind.provenance.manifest import (
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

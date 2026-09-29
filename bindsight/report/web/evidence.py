# SPDX-License-Identifier: AGPL-3.0-or-later
"""A portable, read-only snapshot of the committed scientific artifacts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from bindsight.report.showcase import benchmarks_root, load_designer_benchmark, load_study

EVIDENCE_COMMIT = "b23f1a29fa855089087e854ac2235be9bce12d4b"
REPOSITORY = "https://github.com/mikhaeelatefrizk/bindsight"


def evidence_bundle(*, public: bool = False) -> dict[str, Any]:
    """Expose real measurements only; missing evidence remains missing."""
    root = benchmarks_root()
    if root:
        expected = json.loads(
            Path(__file__).with_name("evidence-snapshot.json").read_text(encoding="utf-8")
        )
        for name, digest in expected.items():
            artifact = root / name
            if (
                not artifact.is_file()
                or hashlib.sha256(artifact.read_bytes()).hexdigest() != digest
            ):
                raise ValueError(
                    "The evidence files do not match the declared source snapshot. Restore the original benchmark files before showing them as committed evidence."
                )
    study = load_study(root) if root else None
    designer = load_designer_benchmark(root) if root else None
    binders = []
    if designer is not None and designer.is_mock is False:
        for binder in designer.with_structures():
            cif = binder.complex_cif
            if cif is None:
                continue
            binders.append(
                {
                    "id": binder.binder_id,
                    "iptm": binder.iptm,
                    "pae": binder.pae_interaction,
                    "target": binder.target_uniprot,
                    "sequence": "".join(
                        line.strip()
                        for line in binder.fasta.read_text().splitlines()
                        if not line.startswith(">")
                    )
                    if binder.fasta
                    else None,
                    "length": binder.developability.get("length"),
                    "structure": f"structures/{cif.name}"
                    if public
                    else f"/api/structure/{binder.binder_id}",
                    "sha256": hashlib.sha256(cif.read_bytes()).hexdigest(),
                    "fasta": (
                        f"sequences/{binder.fasta.name}"
                        if public
                        else f"/api/workbench/sequence/{binder.binder_id}"
                    )
                    if binder.fasta
                    else None,
                }
            )
    calibration: dict[str, Any] | None = None
    if root and (root / "calibration/RESULTS.json").is_file():
        calibration = json.loads((root / "calibration/RESULTS.json").read_text(encoding="utf-8"))
    return {
        "revision": EVIDENCE_COMMIT,
        "repository": REPOSITORY,
        "source": f"{REPOSITORY}/tree/{EVIDENCE_COMMIT}/benchmarks",
        "study": None
        if study is None
        else {
            "projects": study.n_projects,
            "pairs": study.pairs,
            "recall": study.recall_cascade,
            "primary_interval": study.primary_interval,
            "specificity": study.specificity_null,
            "gap": study.indication_gap,
            "decoy_nominal": study.decoy_nominal,
            "decoy_adjusted": study.decoy_surviving_correction,
            "surfaceome_size": study.surfaceome_size,
        },
        "binders": sorted(
            binders, key=lambda b: b["iptm"] if b["iptm"] is not None else -1, reverse=True
        ),
        "calibration": calibration,
    }

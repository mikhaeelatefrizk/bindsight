# SPDX-License-Identifier: AGPL-3.0-or-later
"""A portable, read-only snapshot of the committed scientific artifacts."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

from bindsight.report.showcase import benchmarks_root, load_designer_benchmark, load_study

REPOSITORY = "https://github.com/mikhaeelatefrizk/bindsight"


def source_revision(root: Path | None) -> str | None:
    """Identify committed evidence, or mark an unversioned local copy honestly."""
    if root is None:
        return None
    checkout = root.parent
    if (checkout / ".git").exists():
        try:
            changes = subprocess.check_output(
                ["git", "diff", "HEAD", "--", "benchmarks"], cwd=checkout, timeout=10
            )
            if changes:
                return None
            revision = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=checkout, text=True, timeout=10
            ).strip()
        except (OSError, subprocess.SubprocessError):
            return None
    else:
        try:
            revision = json.loads((checkout / "SOURCE_REVISION.json").read_text(encoding="utf-8"))[
                "revision"
            ]
        except (OSError, ValueError, KeyError, TypeError):
            return None
    return (
        revision if isinstance(revision, str) and re.fullmatch(r"[0-9a-f]{40}", revision) else None
    )


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
    revision = source_revision(root)
    numerical = []
    if root:
        for cohort, label, stage in [
            ("canonical_three", "3 matched patients · current input ordering", "current"),
            ("canonical_eight", "8 matched patients · current input ordering", "current"),
            ("mean_floor_three", "3 matched patients · earlier label-based ordering", "historical"),
            ("mean_floor_eight", "8 matched patients · earlier label-based ordering", "historical"),
        ]:
            relative = f"numerical_validation/results/{cohort}/validation.json"
            path = root / relative
            if not path.is_file():
                continue
            audit = json.loads(path.read_text(encoding="utf-8"))
            decision_changes = audit["checks"]["relabel_samples"]["significance_decisions"].get(
                "changed"
            )
            detail = path.with_name("sample_identifier_sensitivity.json")
            if decision_changes is None and detail.is_file():
                sensitivity = json.loads(detail.read_text(encoding="utf-8"))
                for fit in ["forward", "relabel_samples"]:
                    if (
                        sensitivity["input_sha256"][fit + ".parquet"]
                        != audit["fits"][fit]["sha256"]
                    ):
                        raise ValueError(
                            "The sample-identifier detail does not match its recorded fit"
                        )
                decision_changes = sensitivity["comparison"]["significance_decisions"]["changed"]
            numerical.append(
                {
                    "label": label,
                    "stage": stage,
                    "samples": audit["n_samples"],
                    "genes_tested": audit["fits"]["forward"]["n_genes_tested"],
                    "passed": audit["passed"],
                    "classification_changes": decision_changes,
                    "failed_checks": [
                        f"{group}: {name}"
                        for group, checks in audit["checks"].items()
                        for name, check in checks.items()
                        if not check["passed"]
                    ],
                    "source": "benchmarks/" + relative,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
            )
    return {
        "revision": revision,
        "repository": REPOSITORY,
        "source": f"{REPOSITORY}/tree/{revision or 'main'}/benchmarks",
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
        "numerical_validation": numerical,
    }

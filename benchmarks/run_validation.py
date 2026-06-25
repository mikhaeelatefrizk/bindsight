#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Run the bindsight rediscovery validation end-to-end and write artifacts.

Fetches real, subtype-stratified TCGA cohorts (PAM50 labels from cBioPortal,
STAR-Counts from NIH/GDC), runs the discovery half on each, scores whether the
expected clinical antigen is resurfaced, and writes everything reviewers need
under ``benchmarks/validation/``:

    RESULTS.md      headline recall@k + per-cohort table (single source of truth)
    results.json    machine-readable scores
    report.html     side-by-side per-antigen scoring over the full known set
    provenance.json GDC UUIDs / cBioPortal study / checksums
    figures/*.png   recall@k, per-cohort antigen rank, per-cohort volcanoes

Reproduce:

    pip install -e ".[discover,report]"
    python benchmarks/run_validation.py

First run downloads ~1-1.5 GB of STAR-Counts (cached under data/gdc_cache/) and
runs real DESeq2 + Open Targets enrichment per cohort; re-runs are offline for
the cohorts already cached. Nothing in the output is hand-set.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from bindsight.benchmark.rediscovery import VALIDATION_COHORTS, run_validation

REPO_ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    """Parse args and run the validation."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cohorts",
        nargs="*",
        choices=[c.key for c in VALIDATION_COHORTS],
        help="Subset of cohort keys to run (default: all).",
    )
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "benchmarks" / "validation")
    parser.add_argument(
        "--data-root", type=Path, default=REPO_ROOT / "data" / "gdc_cache" / "validation"
    )
    parser.add_argument("--runs-root", type=Path, default=REPO_ROOT / "runs" / "validation")
    parser.add_argument("--known", type=Path, default=REPO_ROOT / "benchmarks" / "known.tsv")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    cohorts = (
        [c for c in VALIDATION_COHORTS if c.key in set(args.cohorts)] if args.cohorts else None
    )

    summary = run_validation(
        out_dir=args.out,
        data_root=args.data_root,
        runs_root=args.runs_root,
        known_path=args.known,
        cohorts=cohorts,
    )

    print("\n=== rediscovery recall@k ===")
    for k, v in summary["recall_at_k"].items():
        print(f"  {k}: {v:.0%}")
    print("\n=== per-cohort ===")
    for r in summary["cohorts"]:
        ex = r.get("expected") or {}
        rank = ex.get("rank")
        print(
            f"  {r['cohort']['label']:<20} {r['cohort']['expected_symbol']:<6} "
            f"rank={rank if rank is not None else '—'}  "
            f"(tumor={r['n_tumor']} normal={r['n_normal']} candidates={r['n_candidates']})"
        )
    print(f"\nWrote {args.out}/RESULTS.md, results.json, report.html, provenance.json, figures/")


if __name__ == "__main__":
    main()

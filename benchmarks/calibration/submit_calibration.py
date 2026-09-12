# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Send a staged calibration set to a GPU backend for validation only.

No designer runs: the sequences already exist, and the job is to score them with
the same validator, against the same target, on the same card as the designs
they are a control for. Anything else and the comparison is between two
experiments rather than between designs and their own scrambles.

The spec carries ``mode=validate_only``, which the Kaggle kernel reads to skip
the RFdiffusion clone, its checkpoint download and the whole se3 environment —
several gigabytes and roughly six minutes that a re-scoring job has no use for.

Usage::

    python benchmarks/calibration/submit_calibration.py --staged runs/calibration
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from bindsight.design._common import make_cache_key, submit_via_runner  # noqa: E402
from bindsight.design.protocol import DesignSpec  # noqa: E402
from bindsight.plugins import get_runner  # noqa: E402
from bindsight.runners.source_wheel import build_working_tree_wheel  # noqa: E402

LOG = logging.getLogger("calibration")

NATIVE_TARGET = REPO / "benchmarks" / "designer_benchmark" / "target" / "P04626_domain_IV.pdb"
TARGET_UNIPROT = "P04626"


def main(argv: list[str] | None = None) -> int:
    """Submit the staged set and report where the metrics landed."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staged", type=Path, default=REPO / "runs" / "calibration")
    parser.add_argument(
        "--target",
        type=Path,
        default=NATIVE_TARGET,
        help=(
            "the receptor to fold against. Defaults to the one these binders "
            "were designed for. Pointing it at a different receptor is the "
            "specificity control: a design that scores as well against an "
            "unrelated target is not a binder for either. A spec carries one "
            "target, so that comparison necessarily spans two jobs — read it "
            "against the refold drift the analysis reports."
        ),
    )
    parser.add_argument(
        "--target-uniprot",
        default=TARGET_UNIPROT,
        help="accession recorded for the target; change it with --target.",
    )
    parser.add_argument("--backend", default="kaggle")
    parser.add_argument("--validator", default="boltz2")
    parser.add_argument(
        "--diffusion-samples",
        type=int,
        default=1,
        help=(
            "how many diffusion draws to average per binder. Boltz-2 samples "
            "structures, so one draw is a sample rather than a measurement: the "
            "first calibration run measured a median move of 0.129 ipTM between "
            "two folds of the same sequence, which is four times the effect it "
            "was trying to detect. Costs GPU time close to linearly."
        ),
    )
    args = parser.parse_args(argv)
    if args.diffusion_samples < 1:
        print("--diffusion-samples must be at least 1", file=sys.stderr)
        return 1

    staged = Path(args.staged) / "design"
    fastas = sorted(staged.glob("*.fasta"))
    if not fastas:
        print(f"nothing staged under {staged}", file=sys.stderr)
        return 1
    target = Path(args.target)
    if not target.is_file():
        print(f"missing the target structure: {target}", file=sys.stderr)
        return 1

    spec = DesignSpec(
        target_uniprot=str(args.target_uniprot),
        target_structure_path=str(target),
        epitope_chain="A",
        # No hotspots and no ranges: the committed target file *is* domain IV, so
        # the whole chain is the surface these binders were designed against.
        # Slicing it again here would score them against something narrower than
        # the designs were.
        epitope_residues=[],
        design_ranges=[],
        n_trajectories=1,
        seed=0,
        extra_params={
            "mode": "validate_only",
            "validator": str(args.validator),
            "diffusion_samples": int(args.diffusion_samples),
        },
    )

    runner = get_runner(
        args.backend,
        designer="rfdiff_mpnn",
        n_units_per_target=1,
        bindsight_wheel=build_working_tree_wheel(Path(args.staged) / "_wheel"),
    )
    LOG.info(
        "submitting %d sequence(s) for %s validation on %s, %d diffusion sample(s) each",
        len(fastas),
        args.validator,
        args.backend,
        args.diffusion_samples,
    )

    result = submit_via_runner(
        spec,
        runner,
        designer_name=f"calibration:{args.validator}",
        designer_version="1",
        designer_commit_sha=None,
        cache_key=make_cache_key(spec, extra=("calibration", str(args.validator), target.name)),
        payload_dir=staged,
    )
    print(f"metrics: {result.metrics_jsonl_path}")
    print(f"archive: {result.results_archive_path}")
    print(f"cache:   {result.cache_status}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

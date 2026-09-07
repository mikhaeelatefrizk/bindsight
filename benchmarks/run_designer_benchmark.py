#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
r"""Run the three-way designer benchmark (RFdiff+MPNN vs BindCraft vs BoltzGen).

Designs binders for the same target set with each designer and the same
validator (Boltz-2), then tabulates ipTM / PAE-interaction / predicted affinity /
success rate per designer.

The real comparison needs a GPU. CPU-test the harness with the mock backend:

    python benchmarks/run_designer_benchmark.py --backend mock --out /tmp/dbench

Produce real numbers on a GPU backend (writes benchmarks/designer_benchmark/):

    python benchmarks/run_designer_benchmark.py --backend modal \\
        --structures-dir data/target_structures \\
        --out benchmarks/designer_benchmark

See benchmarks/designer_benchmark/DESIGNER_BENCHMARK.md for the full protocol
(hardware, cost, runtime). Mock results are clearly labelled synthetic and must
not be committed as if they were real GPU results.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from bindsight.benchmark.designer_bench import (
    DEFAULT_DESIGNERS,
    DEFAULT_TARGETS,
    run_designer_benchmark,
)

REPO_ROOT = Path(__file__).resolve().parent.parent

LOG = logging.getLogger("bindsight.benchmark.run")


def main() -> None:
    """Parse args and run the designer benchmark."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--backend",
        default="mock",
        choices=["mock", "modal", "local_docker", "kaggle", "colab"],
        help="GPU backend (default: mock, for CPU testing).",
    )
    parser.add_argument("--designers", nargs="*", default=list(DEFAULT_DESIGNERS))
    parser.add_argument("--validator", default="boltz2")
    parser.add_argument("--trajectories", type=int, default=50)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--structures-dir",
        type=Path,
        default=REPO_ROOT / "data" / "target_structures",
        help=(
            "directory of prepared target structures (default: data/target_structures, "
            "where prepare_erbb2_target.py writes). On a real backend a missing "
            "structure is an error, never a placeholder."
        ),
    )
    parser.add_argument(
        "--targets",
        nargs="*",
        default=None,
        help="restrict to these target gene symbols (e.g. --targets ERBB2). "
        "Default: all DEFAULT_TARGETS. Only those needing a real GPU + structure fit a "
        "free 16 GB T4 when sliced (e.g. ERBB2 domain IV).",
    )
    parser.add_argument(
        "--out", type=Path, default=REPO_ROOT / "benchmarks" / "designer_benchmark" / "run"
    )
    parser.add_argument(
        "--bindsight-wheel",
        type=Path,
        default=None,
        help=(
            "a prebuilt wheel to install on the remote GPU. By default one is built "
            "from this checkout, so the run executes the code you have."
        ),
    )
    parser.add_argument(
        "--install-from-git",
        action="store_true",
        help=(
            "skip the wheel and let the remote job pip-install bindsight from the "
            "repository default branch. This is what every run used to do, and it "
            "means local or unpushed changes do NOT run on the GPU."
        ),
    )
    args = parser.parse_args()

    targets = None
    if args.targets:
        wanted = {t.upper() for t in args.targets}
        targets = [t for t in DEFAULT_TARGETS if t.symbol.upper() in wanted]
        if not targets:
            parser.error(
                f"no DEFAULT_TARGETS match {args.targets}; "
                f"available: {[t.symbol for t in DEFAULT_TARGETS]}"
            )

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    # Build a wheel from this checkout unless told not to. Remote backends
    # pip-install bindsight, and with no wheel that means the repository's
    # default branch — so a benchmark launched to validate a local fix would run
    # the unfixed code and report success. The mock backend installs nothing.
    wheel: Path | None = args.bindsight_wheel
    if args.backend != "mock" and wheel is None and not args.install_from_git:
        from bindsight.runners.source_wheel import build_working_tree_wheel

        wheel = build_working_tree_wheel(args.out / "_wheel", repo_root=REPO_ROOT)
        if wheel is None:
            parser.error(
                "could not build a wheel from this checkout, so the GPU would run "
                "the default branch instead of your code. Fix the build, pass "
                "--bindsight-wheel, or pass --install-from-git to accept that."
            )
    if wheel is not None:
        LOG.info("the remote job will install %s", wheel.name)

    summary = run_designer_benchmark(
        bindsight_wheel=wheel,
        out_dir=args.out,
        backend=args.backend,
        designers=tuple(args.designers),
        validator=args.validator,
        n_trajectories=args.trajectories,
        seed=args.seed,
        structures_dir=args.structures_dir,
        targets=targets,
    )

    tag = " (MOCK — synthetic)" if summary["is_mock"] else ""
    print(f"\n=== designer benchmark{tag} ===")
    for d in summary["designers"]:
        if d["error"]:
            print(f"  {d['designer']:<14} ERROR: {d['error']}")
            continue
        print(
            f"  {d['designer']:<14} designs={d['n_designs']:<4} "
            f"mean_ipTM={d['mean_iptm']} success@0.65={d['success_rate']} "
            f"est_cost=${d['cost_usd']}"
        )
    print(f"\nWrote {args.out}/RESULTS.md, results.json")


if __name__ == "__main__":
    main()

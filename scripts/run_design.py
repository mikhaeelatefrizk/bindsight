# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Snakemake script: design half — launches the real executor via a runner.

Invoked by the ``design`` rule. Delegates to the same code path as
``bindsight design`` (``bindsight.cli._launch_design``), so the Snakemake and
CLI front-ends produce identical artifacts. Needs a headless backend
(``mock`` / ``modal`` / ``local_docker`` / ``kaggle``); ``colab`` is interactive
and can't run unattended in a DAG.
"""

import logging
import sys
from pathlib import Path

snakemake = snakemake  # type: ignore[name-defined]  # noqa: F821

logging.basicConfig(
    filename=str(snakemake.log[0]),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
LOG = logging.getLogger("bindsight.design")


def main() -> int:
    from bindsight.cli import _launch_design
    from bindsight.provenance.fragments import artifact_ref, write_fragment
    from bindsight.provenance.manifest import _now_iso

    out_results = Path(snakemake.output.results)
    run_dir = out_results.parent.parent
    backend = str(snakemake.params.backend)
    design = dict(snakemake.params.design)
    validator = str(dict(snakemake.config["params"].get("validate", {})).get("validator", "boltz2"))

    if backend == "colab":
        raise SystemExit(
            "Snakemake automation needs a headless backend "
            "(backend: mock | modal | local_docker | kaggle). For Colab use the CLI: "
            "bindsight design <run> --backend colab."
        )

    started = _now_iso()
    prescreen = design.get("prescreen_top_k")
    launched = _launch_design(
        run_dir,
        backend=backend,
        designer=str(design.get("designer", "rfdiff_mpnn")),
        validator=validator,
        trajectories=int(design.get("n_trajectories", 50)),
        prescreen_top_k=int(prescreen) if prescreen else None,
    )
    LOG.info("design launched for %d target(s) via %s", launched, backend)

    write_fragment(
        Path(snakemake.output.manifest_fragment),
        stage="design",
        started_at=started,
        inputs=[artifact_ref(snakemake.input.epitopes, role="epitopes", run_root=run_dir)],
        outputs=[
            artifact_ref(out_results, role="design_results", run_root=run_dir),
            artifact_ref(
                run_dir / "design" / "metrics.jsonl", role="design_metrics", run_root=run_dir
            ),
        ],
        params=design,
        notes=f"design launched for {launched} target(s) via {backend}",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

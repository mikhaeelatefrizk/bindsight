"""Snakemake script: design half — launches the real executor via a runner.

Invoked by the ``design`` rule. Delegates to the same code path as
``bindsight design`` (``bindsight.cli._launch_design``), so the Snakemake and
CLI front-ends produce identical artifacts. Needs a headless backend
(``mock`` / ``modal`` / ``local_docker`` / ``kaggle``); ``colab`` is interactive
and can't run unattended in a DAG.
"""

import json
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

    launched = _launch_design(
        run_dir,
        backend=backend,
        designer=str(design.get("designer", "rfdiff_mpnn")),
        validator=validator,
        trajectories=int(design.get("n_trajectories", 50)),
    )
    LOG.info("design launched for %d target(s) via %s", launched, backend)

    out_manifest = Path(snakemake.output.manifest_fragment)
    out_manifest.parent.mkdir(parents=True, exist_ok=True)
    out_manifest.write_text(
        json.dumps(
            {"stage": "design", "status": "completed", "metrics": {"n_targets": launched}},
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

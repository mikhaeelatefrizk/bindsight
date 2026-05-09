"""Snakemake script: differential expression analysis (pydeseq2).

Invoked by the ``deg`` rule in the Snakefile. Snakemake injects the
``snakemake`` global with ``input``, ``output``, ``params``, ``log``, and
``config`` attributes.

This is now a real call into :class:`xpr2bind.deg.pydeseq2_runner.PyDESeq2Runner`.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

snakemake = snakemake  # type: ignore[name-defined]  # noqa: F821

logging.basicConfig(
    filename=str(snakemake.log[0]),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
)
LOG = logging.getLogger("xpr2bind.deg")


def main() -> int:
    from xpr2bind.config import DEGParams
    from xpr2bind.deg.pydeseq2_runner import PyDESeq2Runner

    counts = Path(snakemake.input.counts)
    design = Path(snakemake.input.design)
    out_table = Path(snakemake.output.deg_table)
    out_manifest = Path(snakemake.output.manifest_fragment)
    params = DEGParams.model_validate(dict(snakemake.params.deg))

    LOG.info("counts=%s design=%s out=%s params=%s", counts, design, out_table, params)
    runner = PyDESeq2Runner(params)
    metrics = runner.run(counts, design, out_table)

    out_manifest.parent.mkdir(parents=True, exist_ok=True)
    out_manifest.write_text(
        json.dumps({"stage": "deg", "status": "completed", "metrics": metrics}, indent=2)
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

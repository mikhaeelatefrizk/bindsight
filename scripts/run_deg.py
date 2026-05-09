"""Snakemake script: differential expression analysis (pydeseq2).

Invoked by the ``deg`` rule in the Snakefile. Snakemake injects the
``snakemake`` global with ``input``, ``output``, ``params``, ``log``, and
``config`` attributes.

v0.0.x: stub — emits a placeholder Parquet so downstream rules can be wired
up. The real pydeseq2 invocation lands in v0.0.2.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

# Snakemake injects this global at runtime.
snakemake = snakemake  # type: ignore[name-defined]  # noqa: F821

logging.basicConfig(
    filename=str(snakemake.log[0]),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
LOG = logging.getLogger("xpr2bind.deg")


def main() -> int:
    counts = Path(snakemake.input.counts)
    design = Path(snakemake.input.design)
    out_table = Path(snakemake.output.deg_table)
    out_manifest = Path(snakemake.output.manifest_fragment)
    params = dict(snakemake.params.deg)

    LOG.info("counts=%s design=%s out=%s params=%s", counts, design, out_table, params)

    # TODO(v0.0.2): replace with PyDESeq2Runner(params).run(counts, design, out_table)
    out_table.parent.mkdir(parents=True, exist_ok=True)
    out_table.write_bytes(b"")  # placeholder — empty file so downstream rules can detect
    out_manifest.parent.mkdir(parents=True, exist_ok=True)
    out_manifest.write_text('{"stage": "deg", "status": "stub"}\n')

    LOG.warning("DEG stub — no real analysis performed in v0.0.x.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

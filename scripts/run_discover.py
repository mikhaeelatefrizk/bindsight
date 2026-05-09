"""Snakemake script: target discovery + epitope lookup.

v0.0.x: stub. Real implementation will:

1. Read DEG Parquet, filter by FDR + log2FC.
2. Map gene IDs → UniProt via Open Targets ``proteinIds`` field.
3. Filter to surfaceome via SURFY.
4. Apply specificity filter (GTEx vital-tissue baseline).
5. For each surviving UniProt, look up SURFACE-Bind sites.
6. Pull AlphaFoldDB structures.
7. Emit ``targets/candidates.parquet`` and ``epitopes/epitopes.parquet``.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

snakemake = snakemake  # type: ignore[name-defined]  # noqa: F821

logging.basicConfig(
    filename=str(snakemake.log[0]),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
LOG = logging.getLogger("xpr2bind.discover")


def main() -> int:
    deg_table = Path(snakemake.input.deg_table)
    out_targets = Path(snakemake.output.targets)
    out_epitopes = Path(snakemake.output.epitopes)
    out_manifest = Path(snakemake.output.manifest_fragment)
    params = dict(snakemake.params.target)

    LOG.info(
        "deg_table=%s targets=%s epitopes=%s params=%s",
        deg_table,
        out_targets,
        out_epitopes,
        params,
    )

    # TODO(v0.0.2): wire up the real Open Targets + SURFY + SURFACE-Bind pipeline.
    for p in (out_targets, out_epitopes):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"")
    out_manifest.parent.mkdir(parents=True, exist_ok=True)
    out_manifest.write_text('{"stage": "discover", "status": "stub"}\n')

    LOG.warning("Discover stub — no real analysis performed in v0.0.x.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Snakemake script: GPU design half (offloaded). Stub in v0.0.x."""

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
LOG = logging.getLogger("bindsight.design")


def main() -> int:
    LOG.warning("Design stub — implement in v0.1 (Phase 2).")
    out_results = Path(snakemake.output.results)
    out_manifest = Path(snakemake.output.manifest_fragment)
    out_results.parent.mkdir(parents=True, exist_ok=True)
    out_results.write_bytes(b"")
    out_manifest.parent.mkdir(parents=True, exist_ok=True)
    out_manifest.write_text('{"stage": "design", "status": "stub"}\n')
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Snakemake script: multi-objective ranking. Stub in v0.0.x."""

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
LOG = logging.getLogger("xpr2bind.rank")


def main() -> int:
    LOG.warning("Rank stub — implement in v0.1 (Phase 2).")
    out_r = Path(snakemake.output.ranking)
    out_m = Path(snakemake.output.manifest_fragment)
    out_r.parent.mkdir(parents=True, exist_ok=True)
    out_r.write_bytes(b"")
    out_m.parent.mkdir(parents=True, exist_ok=True)
    out_m.write_text('{"stage": "rank", "status": "stub"}\n')
    return 0


if __name__ == "__main__":
    sys.exit(main())

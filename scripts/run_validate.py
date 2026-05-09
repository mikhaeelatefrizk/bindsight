"""Snakemake script: validate designed binders. Stub in v0.0.x."""

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
LOG = logging.getLogger("xpr2bind.validate")


def main() -> int:
    LOG.warning("Validate stub — implement in v0.1 (Phase 2).")
    out_v = Path(snakemake.output.validated)
    out_m = Path(snakemake.output.manifest_fragment)
    out_v.parent.mkdir(parents=True, exist_ok=True)
    out_v.write_bytes(b"")
    out_m.parent.mkdir(parents=True, exist_ok=True)
    out_m.write_text('{"stage": "validate", "status": "stub"}\n')
    return 0


if __name__ == "__main__":
    sys.exit(main())

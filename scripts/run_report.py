"""Snakemake script: render Quarto HTML report. Stub in v0.0.x."""

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
LOG = logging.getLogger("bindsight.report")


def main() -> int:
    LOG.warning("Report stub — implement in v0.1 (Phase 3).")
    out_html = Path(snakemake.output.html)
    out_m = Path(snakemake.output.manifest_fragment)
    out_html.parent.mkdir(parents=True, exist_ok=True)
    out_html.write_text(
        "<!doctype html><title>bindsight report (stub)</title>"
        "<h1>bindsight report (stub)</h1>"
        "<p>This is a placeholder. Real Quarto report ships in v0.1.</p>\n"
    )
    out_m.parent.mkdir(parents=True, exist_ok=True)
    out_m.write_text('{"stage": "report", "status": "stub"}\n')
    return 0


if __name__ == "__main__":
    sys.exit(main())

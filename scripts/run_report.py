# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Snakemake script: render the self-contained HTML report.

Invoked by the ``report`` rule. Delegates to :func:`bindsight.report.render_run`
(the same renderer the CLI uses) to write ``report.html`` for the run.
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
LOG = logging.getLogger("bindsight.report")


def main() -> int:
    from bindsight.report import render_run

    out_html = Path(snakemake.output.html)
    run_dir = out_html.parent
    rendered = render_run(run_dir, out_html)
    LOG.info("rendered report -> %s", rendered)

    out_m = Path(snakemake.output.manifest_fragment)
    out_m.parent.mkdir(parents=True, exist_ok=True)
    out_m.write_text('{"stage": "report", "status": "completed"}\n')
    return 0


if __name__ == "__main__":
    sys.exit(main())

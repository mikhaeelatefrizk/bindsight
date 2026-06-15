"""Snakemake script: validate designed binders.

Invoked by the ``validate`` rule. Materialises ``validate/validated.parquet``
from the design step's per-binder metrics — the same code path as
``bindsight validate`` (``bindsight.cli._finalize_validate``).
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
LOG = logging.getLogger("bindsight.validate")


def main() -> int:
    from bindsight.cli import _finalize_validate

    out_v = Path(snakemake.output.validated)
    run_dir = out_v.parent.parent
    n = _finalize_validate(run_dir)
    LOG.info("validated %d design(s) -> %s", n, out_v)

    out_m = Path(snakemake.output.manifest_fragment)
    out_m.parent.mkdir(parents=True, exist_ok=True)
    out_m.write_text(
        json.dumps(
            {"stage": "validate", "status": "completed", "metrics": {"n_validated": n}},
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Snakemake script: validate designed binders.

Invoked by the ``validate`` rule. Materialises ``validate/validated.parquet``
from the design step's per-binder metrics — the same code path as
``bindsight validate`` (``bindsight.cli._finalize_validate``).
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
LOG = logging.getLogger("bindsight.validate")


def main() -> int:
    from bindsight.cli import _finalize_validate
    from bindsight.provenance.fragments import artifact_ref, write_fragment
    from bindsight.provenance.manifest import _now_iso

    out_v = Path(snakemake.output.validated)
    run_dir = out_v.parent.parent
    started = _now_iso()
    n = _finalize_validate(run_dir)
    LOG.info("validated %d design(s) -> %s", n, out_v)

    write_fragment(
        Path(snakemake.output.manifest_fragment),
        stage="validate",
        started_at=started,
        outputs=[artifact_ref(out_v, role="validated", run_root=run_dir)],
        notes=f"validated {n} design(s)",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Snakemake script: multi-objective ranking.

Invoked by the ``rank`` rule. Delegates to :func:`bindsight.rank.rank_run`,
the same real ranking the CLI uses, writing ``rank/ranking.parquet``.
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
LOG = logging.getLogger("bindsight.rank")


def main() -> int:
    import pandas as pd

    from bindsight.config import RankWeights
    from bindsight.provenance.fragments import artifact_ref, write_fragment
    from bindsight.provenance.manifest import _now_iso
    from bindsight.rank import rank_run

    out_r = Path(snakemake.output.ranking)
    run_dir = out_r.parent.parent
    started = _now_iso()
    # The Snakefile declares params.rank and this wrapper never read it, so
    # custom rank weights were silently discarded on the Snakemake path while
    # the CLI honoured them (pipelines/full_run.py).
    raw = dict(getattr(snakemake.params, "rank", {}) or {})
    weights = RankWeights.model_validate(raw.get("weights", {})) if raw else RankWeights()
    out = rank_run(run_dir, weights=weights)
    n = len(pd.read_parquet(out))
    LOG.info("ranked %d binder(s) -> %s", n, out)

    write_fragment(
        Path(snakemake.output.manifest_fragment),
        stage="rank",
        started_at=started,
        outputs=[artifact_ref(out, role="ranking", run_root=run_dir)],
        params={"weights": weights.model_dump()},
        notes=f"ranked {n} binder(s)",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

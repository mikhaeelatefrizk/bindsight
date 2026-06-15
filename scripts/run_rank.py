"""Snakemake script: multi-objective ranking.

Invoked by the ``rank`` rule. Delegates to :func:`bindsight.rank.rank_run`,
the same real ranking the CLI uses, writing ``rank/ranking.parquet``.
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
LOG = logging.getLogger("bindsight.rank")


def main() -> int:
    import pandas as pd

    from bindsight.rank import rank_run

    out_r = Path(snakemake.output.ranking)
    run_dir = out_r.parent.parent
    out = rank_run(run_dir)
    n = len(pd.read_parquet(out))
    LOG.info("ranked %d binder(s) -> %s", n, out)

    out_m = Path(snakemake.output.manifest_fragment)
    out_m.parent.mkdir(parents=True, exist_ok=True)
    out_m.write_text(
        json.dumps({"stage": "rank", "status": "completed", "metrics": {"n_ranked": n}}, indent=2)
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

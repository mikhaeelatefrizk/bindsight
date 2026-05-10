"""Snakemake script: target discovery + epitope lookup.

Wraps :func:`bindsight.pipelines.discover._do_discover` so the work survives
either as a Snakemake rule or as a direct Python call from the CLI.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

snakemake = snakemake  # type: ignore[name-defined]  # noqa: F821

logging.basicConfig(
    filename=str(snakemake.log[0]),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
)
LOG = logging.getLogger("bindsight.discover")


def main() -> int:
    # Lazy imports keep the script importable even when the discover extras
    # are missing in a different env.
    from bindsight.config import RunConfig, TargetDiscoveryParams
    from bindsight.pipelines.discover import _do_discover

    deg_table = Path(snakemake.input.deg_table)
    out_targets = Path(snakemake.output.targets)
    out_epitopes = Path(snakemake.output.epitopes)
    out_manifest = Path(snakemake.output.manifest_fragment)
    target_params = TargetDiscoveryParams.model_validate(dict(snakemake.params.target))

    # Reconstruct a minimal RunConfig — only target_discovery is consulted.
    cfg = RunConfig.model_validate(
        {
            "name": "snakemake-run",
            "out_dir": str(out_targets.parent.parent),
            "inputs": {
                "counts": "PLACEHOLDER",
                "design": "PLACEHOLDER",
            },
            "params": {
                "deg": {
                    "design_formula": "~ condition",
                    "contrast": ["condition", "tumor", "normal"],
                },
                "target_discovery": target_params.model_dump(),
            },
        }
    )

    candidates_df, epitopes_df = _do_discover(
        config=cfg,
        deg_table_path=deg_table,
        open_targets_client=None,
        alphafolddb_client=None,
        surfy=None,
    )
    out_targets.parent.mkdir(parents=True, exist_ok=True)
    out_epitopes.parent.mkdir(parents=True, exist_ok=True)
    candidates_df.to_parquet(out_targets, index=False)
    epitopes_df.to_parquet(out_epitopes, index=False)

    out_manifest.parent.mkdir(parents=True, exist_ok=True)
    out_manifest.write_text(
        json.dumps(
            {
                "stage": "discover",
                "status": "completed",
                "metrics": {
                    "n_candidates": len(candidates_df),
                    "n_epitopes": len(epitopes_df),
                },
            },
            indent=2,
        )
    )
    LOG.info(
        "wrote %s (%d rows) and %s (%d rows)",
        out_targets,
        len(candidates_df),
        out_epitopes,
        len(epitopes_df),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

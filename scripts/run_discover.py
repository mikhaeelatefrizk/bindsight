# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Snakemake script: target discovery + epitope lookup.

Wraps :func:`bindsight.pipelines.discover._do_discover` so the work survives
either as a Snakemake rule or as a direct Python call from the CLI.
"""

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
    from bindsight.pipelines.caveats import caveat_summary
    from bindsight.pipelines.discover import _do_discover, _resolve_surface_bind_client
    from bindsight.provenance.fragments import artifact_ref, write_fragment
    from bindsight.provenance.manifest import _now_iso

    deg_table = Path(snakemake.input.deg_table)
    out_targets = Path(snakemake.output.targets)
    out_epitopes = Path(snakemake.output.epitopes)
    out_taxonomy = Path(snakemake.output.taxonomy)
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

    started = _now_iso()
    # Every keyword is passed explicitly. _do_discover's signature is
    # keyword-only with no defaults, so omitting the topology/GTEx clients --
    # as this wrapper did after they were added in June -- raised TypeError
    # before any work happened, and the slow-marked DAG test never caught it.
    candidates_df, epitopes_df, taxonomy_df = _do_discover(
        config=cfg,
        deg_table_path=deg_table,
        open_targets_client=None,
        alphafolddb_client=None,
        surface_bind_client=_resolve_surface_bind_client(None),
        topology_client=None,
        gtex_client=None,
        surfy=None,
    )
    out_targets.parent.mkdir(parents=True, exist_ok=True)
    out_epitopes.parent.mkdir(parents=True, exist_ok=True)
    out_taxonomy.parent.mkdir(parents=True, exist_ok=True)
    candidates_df.to_parquet(out_targets, index=False)
    epitopes_df.to_parquet(out_epitopes, index=False)
    taxonomy_df.to_parquet(out_taxonomy, index=False)

    run_root = out_targets.parent.parent
    write_fragment(
        out_manifest,
        stage="discover",
        started_at=started,
        inputs=[artifact_ref(deg_table, role="deg_table", run_root=run_root)],
        outputs=[
            artifact_ref(out_targets, role="candidates", run_root=run_root),
            artifact_ref(out_epitopes, role="epitopes", run_root=run_root),
            artifact_ref(out_taxonomy, role="failure_taxonomy", run_root=run_root),
        ],
        params=target_params.model_dump(),
        notes=(
            f"{len(candidates_df)} candidates, {len(epitopes_df)} epitopes, "
            f"{len(taxonomy_df)} taxonomy rows. {caveat_summary()}"
        ),
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

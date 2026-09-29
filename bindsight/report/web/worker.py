# SPDX-License-Identifier: AGPL-3.0-or-later
"""Execute a genuine local discovery analysis in an isolated process."""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path


def main(config_path: Path) -> int:
    """Use the scientific pipeline unchanged and propagate failed manifests."""
    from bindsight.config import RunConfig
    from bindsight.pipelines.discover import run
    from bindsight.provenance import append as provenance
    from bindsight.report import render_run
    from bindsight.report.coverage import annotation_coverage

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s")
    config = RunConfig.model_validate(json.loads(config_path.read_text(encoding="utf-8")))
    logging.info(
        "Starting real human bulk RNA-seq discovery; comparison %s", config.params.deg.contrast
    )
    manifest = run(config, out_dir=config.out_dir)
    failures = [stage for stage in manifest.stages if stage.status == "failed"]
    if failures:
        for stage in failures:
            logging.error("Scientific stage failed: %s", stage)
        return 1
    import pandas as pd

    taxonomy_path = config.out_dir / "taxonomy/failure_taxonomy.parquet"
    if not taxonomy_path.is_file():
        raise RuntimeError("The scientific run did not produce its annotation coverage table")
    coverage = annotation_coverage(pd.read_parquet(taxonomy_path))
    (config_path.parent / "coverage.json").write_text(
        json.dumps(coverage), encoding="utf-8", newline="\n"
    )
    coverage_path = config.out_dir / "annotation_coverage.json"
    coverage_path.write_text(json.dumps(coverage, indent=2), encoding="utf-8", newline="\n")
    provenance.record(
        config.out_dir,
        name="annotation_coverage",
        tool="bindsight.report",
        inputs={"taxonomy": taxonomy_path},
        outputs={"annotation_coverage": coverage_path},
        params=coverage,
    )
    if coverage["unassessed_lookups"]:
        logging.warning(
            "%d gene annotations were unassessed; this is incomplete annotation, not a complete biological negative",
            coverage["unassessed_lookups"],
        )
    logging.info("Rendering the report from actual run artifacts")
    report = render_run(config.out_dir)
    provenance.record(
        config.out_dir,
        name="report",
        tool="bindsight.report",
        inputs={
            "taxonomy": taxonomy_path,
            "annotation_coverage": coverage_path,
            "candidates": config.out_dir / "targets/candidates.parquet",
            "deg": config.out_dir / "deg/results.parquet",
        },
        outputs={"report_html": report},
        params={"format": "html"},
    )
    logging.info("Analysis completed; read the report's reference-data coverage and limitations")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(Path(sys.argv[1])))
    except Exception:
        logging.exception("Analysis failed")
        raise SystemExit(1) from None

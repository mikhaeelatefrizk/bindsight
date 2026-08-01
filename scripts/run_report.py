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
    from bindsight.provenance.fragments import artifact_ref, write_fragment
    from bindsight.provenance.manifest import _now_iso
    from bindsight.report import render_run

    started = _now_iso()
    out_html = Path(snakemake.output.html)
    run_dir = out_html.parent
    rendered = render_run(run_dir, out_html)
    LOG.info("rendered report -> %s", rendered)

    frag_path = write_fragment(
        Path(snakemake.output.manifest_fragment),
        stage="report",
        started_at=started,
        outputs=[artifact_ref(rendered, role="report", run_root=run_dir)],
        notes=f"rendered {rendered.name}",
    )

    # The manifest is assembled before this rule so the report can render its
    # provenance table (it used to be built afterwards, leaving that section
    # empty in every Snakemake report). Report is the terminal stage, so its own
    # record is appended here rather than by a later assembly pass.
    _append_report_stage(run_dir / "run_manifest.jsonld", frag_path)
    return 0


def _append_report_stage(manifest_path: Path, fragment_path: Path) -> None:
    """Append the report stage to an already-written manifest."""
    import json

    from bindsight.provenance import Manifest
    from bindsight.provenance.fragments import stage_record_from_fragment

    if not manifest_path.exists():
        LOG.warning("no manifest at %s; skipping report stage record", manifest_path)
        return
    try:
        manifest = Manifest.read(manifest_path)
        record = stage_record_from_fragment(json.loads(fragment_path.read_text(encoding="utf-8")))
    except (OSError, ValueError) as e:
        LOG.warning("could not append the report stage to the manifest: %s", e)
        return
    if any(s.name == "report" for s in manifest.stages):
        return
    manifest.append(record)
    manifest.write(manifest_path)
    LOG.info("appended report stage to %s", manifest_path)


if __name__ == "__main__":
    sys.exit(main())

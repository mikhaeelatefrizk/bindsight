# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Snakemake script: differential expression analysis (pydeseq2).

Invoked by the ``deg`` rule in the Snakefile. Snakemake injects the
``snakemake`` global with ``input``, ``output``, ``params``, ``log``, and
``config`` attributes.

This is now a real call into :class:`bindsight.deg.pydeseq2_runner.PyDESeq2Runner`.
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
LOG = logging.getLogger("bindsight.deg")


def _pydeseq2_tool() -> dict:
    """ToolRef for pydeseq2, matching what the CLI records for this stage."""
    from bindsight.provenance.fragments import default_tool

    try:
        from importlib.metadata import version

        v = version("pydeseq2")
    except Exception:
        v = "uninstalled"
    return default_tool(
        name="pydeseq2",
        version=v,
        license="MIT",
        repo_url="https://github.com/owkin/PyDESeq2",
        citation="10.1093/bioinformatics/btad547",
    )


def main() -> int:
    from bindsight.config import DEGParams
    from bindsight.deg.pydeseq2_runner import PyDESeq2Runner
    from bindsight.provenance.fragments import artifact_ref, write_fragment
    from bindsight.provenance.manifest import _now_iso

    counts = Path(snakemake.input.counts)
    design = Path(snakemake.input.design)
    out_table = Path(snakemake.output.deg_table)
    out_manifest = Path(snakemake.output.manifest_fragment)
    params = DEGParams.model_validate(dict(snakemake.params.deg))

    LOG.info("counts=%s design=%s out=%s params=%s", counts, design, out_table, params)
    started = _now_iso()
    runner = PyDESeq2Runner(params)
    metrics = runner.run(counts, design, out_table)

    run_root = out_table.parent.parent
    write_fragment(
        out_manifest,
        stage="deg",
        started_at=started,
        tool=_pydeseq2_tool(),
        inputs=[
            artifact_ref(counts, role="counts", run_root=run_root),
            artifact_ref(design, role="design", run_root=run_root),
        ],
        outputs=[artifact_ref(out_table, role="deg_table", run_root=run_root)],
        params=params.model_dump(),
        notes=", ".join(f"{k}={v}" for k, v in metrics.items()),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Streamlit dashboard for browsing an bindsight run.

Launch via the CLI:

    bindsight report runs/demo --format streamlit

or directly:

    streamlit run -m bindsight.report.streamlit_app -- runs/demo

Three-panel layout: KPIs at the top, the DEG / candidate / epitope tables in
the middle (``st.dataframe``, so columns sort by clicking their header), and
the per-stage provenance at the bottom.

This is the single-run viewer reached through ``bindsight report``. For the
full multi-page interface — including the real-results explorer and the 3-D
complex viewer — see :mod:`bindsight.report.webapp`, which is what
``bindsight ui`` and both hosted deployments serve.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def _read_run(run_dir: Path) -> Any:
    import pandas as pd

    deg = candidates = epitopes = None
    deg_path = run_dir / "deg" / "results.parquet"
    cand_path = run_dir / "targets" / "candidates.parquet"
    epi_path = run_dir / "epitopes" / "epitopes.parquet"
    manifest_path = run_dir / "run_manifest.jsonld"

    if deg_path.exists() and deg_path.stat().st_size > 0:
        deg = pd.read_parquet(deg_path)
    if cand_path.exists() and cand_path.stat().st_size > 0:
        candidates = pd.read_parquet(cand_path)
    if epi_path.exists() and epi_path.stat().st_size > 0:
        epitopes = pd.read_parquet(epi_path)
    manifest = None
    if manifest_path.exists():
        body = json.loads(manifest_path.read_text(encoding="utf-8"))
        body.pop("@context", None)
        manifest = body
    return deg, candidates, epitopes, manifest


def _failed_stages(manifest: Any) -> list[dict[str, Any]]:
    """Return the manifest stages that recorded a failure.

    A run whose stage crashed leaves behind the same empty tables as a run that
    genuinely surfaced nothing, so the two must never render alike: one is a
    finding, the other is no result at all.

    Args:
        manifest: Parsed ``run_manifest.jsonld`` body, or ``None``.

    Returns:
        The failed stage records, in manifest order.
    """
    stages = (manifest or {}).get("stages") or []
    return [s for s in stages if isinstance(s, dict) and s.get("status") == "failed"]


def main() -> None:
    """Streamlit entry point."""
    import streamlit as st

    st.set_page_config(page_title="bindsight", layout="wide", page_icon="🧬")

    if len(sys.argv) < 2:
        st.error("Usage: streamlit run bindsight/report/streamlit_app.py -- <run_dir>")
        return
    run_dir = Path(sys.argv[1])
    if not run_dir.exists():
        st.error(f"Run directory not found: {run_dir}")
        return

    deg, candidates, epitopes, manifest = _read_run(run_dir)

    # ---- header ----
    name = manifest.get("name") if manifest else run_dir.name
    st.title("bindsight report")
    st.caption(f"run: **{name}**  ·  dir: `{run_dir}`")

    # A failed stage means there is no result to summarise. Rendering the KPI row
    # and the empty-state advice below it would present a crash as a measured
    # negative, so the summary is replaced by the failure and the provenance that
    # explains it.
    failed = _failed_stages(manifest)
    if failed:
        names = ", ".join(str(s.get("name") or "?") for s in failed)
        st.error(
            f"**These results are incomplete — the {names} stage failed.** The run never "
            "finished, so this is not a real negative result and no filter should be "
            "loosened on the strength of it. The failing stage is detailed under "
            "Provenance below.",
            icon="🛑",
        )
    else:
        # ---- KPIs ----
        cols = st.columns(4)
        cols[0].metric("Genes tested", len(deg) if deg is not None else 0)
        cols[1].metric(
            "Significant DEGs",
            (
                int(deg["significant"].sum())
                if deg is not None and "significant" in deg.columns
                else 0
            ),
        )
        cols[2].metric("Candidates", len(candidates) if candidates is not None else 0)
        cols[3].metric("Top-N epitopes", len(epitopes) if epitopes is not None else 0)

        # ---- DEG ----
        st.header("Differential expression")
        if deg is not None and len(deg):
            st.dataframe(deg, hide_index=True, width="stretch")
        else:
            st.info("No DEG output found.")

        # ---- candidates ----
        st.header("Candidate targets")
        if candidates is not None and len(candidates):
            st.dataframe(candidates, hide_index=True, width="stretch")
        else:
            st.info("No candidates produced. Loosen filters in the config and re-run.")

        # ---- epitopes ----
        st.header("Top-N epitopes")
        if epitopes is not None and len(epitopes):
            st.dataframe(epitopes, hide_index=True, width="stretch")
        else:
            st.info("No top-N epitopes produced.")

    # ---- provenance ----
    st.header("Provenance")
    if manifest:
        st.write(f"Run ID: `{manifest.get('run_id')}`")
        st.write(f"Created: `{manifest.get('created_at')}`")
        for stage in manifest.get("stages", []):
            # A failed stage opens by default: its error is the whole story.
            with st.expander(
                f"stage: {stage['name']} — {stage['status']}",
                expanded=stage.get("status") == "failed",
            ):
                st.json(stage)
    else:
        st.warning("No manifest found.")


if __name__ == "__main__":
    main()

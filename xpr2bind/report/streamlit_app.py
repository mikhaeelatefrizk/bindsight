"""Streamlit dashboard for browsing an xpr2bind run.

Launch via the CLI:

    xpr2bind report runs/demo --format streamlit

or directly:

    streamlit run -m xpr2bind.report.streamlit_app -- runs/demo

Three-panel layout: KPIs at the top, candidates table in the middle (sortable
+ filterable via Streamlit's data_editor), provenance at the bottom.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def _read_run(run_dir: Path):
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


def main() -> None:
    """Streamlit entry point."""
    import streamlit as st

    st.set_page_config(page_title="xpr2bind", layout="wide", page_icon="🧬")

    if len(sys.argv) < 2:
        st.error("Usage: streamlit run xpr2bind/report/streamlit_app.py -- <run_dir>")
        return
    run_dir = Path(sys.argv[1])
    if not run_dir.exists():
        st.error(f"Run directory not found: {run_dir}")
        return

    deg, candidates, epitopes, manifest = _read_run(run_dir)

    # ---- header ----
    name = manifest.get("name") if manifest else run_dir.name
    st.title("xpr2bind report")
    st.caption(f"run: **{name}**  ·  dir: `{run_dir}`")

    # ---- KPIs ----
    cols = st.columns(4)
    cols[0].metric("Genes tested", len(deg) if deg is not None else 0)
    cols[1].metric(
        "Significant DEGs",
        int(deg["significant"].sum()) if deg is not None and "significant" in deg.columns else 0,
    )
    cols[2].metric("Candidates", len(candidates) if candidates is not None else 0)
    cols[3].metric("Top-N epitopes", len(epitopes) if epitopes is not None else 0)

    # ---- DEG ----
    st.header("Differential expression")
    if deg is not None and len(deg):
        st.dataframe(deg, hide_index=True, use_container_width=True)
    else:
        st.info("No DEG output found.")

    # ---- candidates ----
    st.header("Candidate targets")
    if candidates is not None and len(candidates):
        st.dataframe(candidates, hide_index=True, use_container_width=True)
    else:
        st.info("No candidates produced. Loosen filters in the config and re-run.")

    # ---- epitopes ----
    st.header("Top-N epitopes")
    if epitopes is not None and len(epitopes):
        st.dataframe(epitopes, hide_index=True, use_container_width=True)
    else:
        st.info("No top-N epitopes produced.")

    # ---- provenance ----
    st.header("Provenance")
    if manifest:
        st.write(f"Run ID: `{manifest.get('run_id')}`")
        st.write(f"Created: `{manifest.get('created_at')}`")
        for stage in manifest.get("stages", []):
            with st.expander(f"stage: {stage['name']} — {stage['status']}", expanded=False):
                st.json(stage)
    else:
        st.warning("No manifest found.")


if __name__ == "__main__":
    main()

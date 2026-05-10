"""bindsight web app — multi-page Streamlit interface.

Anyone can run this locally (``bindsight ui``) or hit the Streamlit Cloud
deployment to use the tool entirely in a browser.

Pages:

- **Home** — what this is, why it matters, "Try the demo" CTA
- **Demo** — one-click run of the bundled 10-gene cohort with live progress
- **Run with my data** — upload counts.tsv + design.tsv, run the pipeline
- **Browse a run** — open a run directory, inspect tables, view the report
- **About** — links to docs, source, citation

The app is intentionally one file so Streamlit Cloud can deploy from a
single import path, and the layout is conservative so it works on phones.
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

# Streamlit must be importable as the entry point. The rest is lazy-loaded
# below so command-line flags + module probing work without it.
try:
    import streamlit as st
except ImportError:  # pragma: no cover
    st = None  # type: ignore[assignment]


def _inject_css() -> None:
    st.markdown(
        """
        <style>
            .block-container { max-width: 980px; padding-top: 2rem; }
            h1 { color: #0b5394; letter-spacing: -0.02em; }
            h2 { color: #0b5394; border-bottom: 1px solid #e3e6ea; padding-bottom: .3rem; }
            .stButton button[kind="primary"] {
                background-color: #0b5394; color: white; font-weight: 600;
            }
            .small-muted { color: #6c757d; font-size: 0.85rem; }
            .pill {
                display: inline-block; padding: .15rem .55rem;
                background: #e8f0fb; color: #0b5394; border-radius: 999px;
                font-size: .75rem; font-weight: 600; margin-right: .3rem;
            }
            .ok-pill   { background: #e8f5e9; color: #2e7d32; }
            .warn-pill { background: #fff8e1; color: #b08400; }
            .err-pill  { background: #ffebee; color: #c62828; }
        </style>
        """,
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------
def _page_home() -> None:
    st.title("bindsight")
    st.markdown(
        "**RNA-seq counts → ranked de novo protein binder candidates, "
        "with full provenance back to the patient cohort.**"
    )
    st.markdown(
        '<div style="margin-bottom:1rem">'
        '<span class="pill ok-pill">v0.1.0 ready</span>'
        '<span class="pill">MIT license</span>'
        '<span class="pill">CPU-friendly</span>'
        '<span class="pill">PROV-O provenance</span>'
        "</div>",
        unsafe_allow_html=True,
    )

    col_left, col_right = st.columns([3, 2])
    with col_left:
        st.markdown(
            "### What this is\n"
            "Two ecosystems in computational biology have run in parallel for years: "
            "**genomics** (which stops at *here are the interesting genes*) and "
            "**protein design** (which starts at *given a target structure*). "
            "**bindsight is the first open-source tool that connects them.**\n\n"
            'Going from "this gene is up in disease" to "here is a designed '
            'binder candidate" used to take a competent grad student 4–6 weeks of '
            "glue scripting. bindsight does it in a single command on a CPU laptop, "
            "with reproducibility that survives peer review."
        )
        st.info(
            "👉 Click **Demo** in the left sidebar for a 60-second guided run on a "
            "tiny shipped cohort. The pipeline rediscovers HER2 and EGFR as the top "
            "antibody-tractable surface antigens — the textbook cancer immunotherapy targets.",
            icon="✨",
        )

    with col_right:
        st.markdown("### What works today")
        st.markdown(
            '<div style="line-height:1.9">'
            '<span class="pill ok-pill">✓</span> Differential expression (pydeseq2)<br>'
            '<span class="pill ok-pill">✓</span> Surfaceome filter (SURFY)<br>'
            '<span class="pill ok-pill">✓</span> Open Targets enrichment<br>'
            '<span class="pill ok-pill">✓</span> AlphaFoldDB structure pull<br>'
            '<span class="pill ok-pill">✓</span> SURFACE-Bind site lookup<br>'
            '<span class="pill ok-pill">✓</span> Multi-objective ranking<br>'
            '<span class="pill ok-pill">✓</span> Paper-style HTML report<br>'
            '<span class="pill ok-pill">✓</span> RO-Crate export (Zenodo-ready)<br>'
            '<span class="pill ok-pill">✓</span> GPU cost estimator<br>'
            '<span class="pill warn-pill">≈</span> RFdiffusion + ProteinMPNN + Boltz-2 '
            "(Colab notebook)<br>"
            "</div>",
            unsafe_allow_html=True,
        )

    st.markdown("### Three commands cover the whole pipeline")
    st.code(
        "bindsight demo                                # 60-second guided demo\n"
        "bindsight run my_config.yaml --out runs/x     # your cohort end-to-end\n"
        "bindsight ui                                  # this web interface, locally",
        language="bash",
    )

    st.markdown(
        "### Who this is for\n\n"
        "- **Translational researchers** with a TCGA cohort and limited compute\n"
        "- **Clinical biologists** who need a defensible audit trail (PROV-O / RO-Crate)\n"
        "- **Method developers** benchmarking new designers/validators against a fixed upstream\n"
        "- **Pharma early-discovery teams** wanting an open, reproducible comparator"
    )


def _page_demo() -> None:
    st.title("Demo: 60-second guided run")
    st.markdown(
        "This runs the full discovery half against a shipped 10-gene tumor-vs-normal "
        "cohort. Real pydeseq2 differential expression, real SURFY surfaceome filter, "
        "real ranked output. Internet not required, GPU not required.\n\n"
        "**Expected:** ERBB2 (HER2) and EGFR — the textbook cancer immunotherapy "
        "targets — should be the top two antibody-tractable surface antigens."
    )

    if st.button("▶  Run demo now", type="primary", use_container_width=True):
        out_dir = Path(tempfile.mkdtemp(prefix="bindsight_demo_")) / "demo_run"
        with st.spinner("Loading config and shipped data…"):
            from bindsight.config import RunConfig

            repo_root = _find_repo_root()
            cfg_path = repo_root / "examples" / "demo" / "config.yaml"
            cfg = RunConfig.from_yaml(cfg_path)
            cfg.out_dir = out_dir
            cfg.inputs.counts = (cfg_path.parent / "counts.tsv").resolve()
            cfg.inputs.design = (cfg_path.parent / "design.tsv").resolve()

        progress = st.progress(0.0, text="DEG analysis (pydeseq2)…")
        time.sleep(0.05)

        with st.spinner("Running pipeline…"):
            from bindsight.pipelines import discover as discover_pipeline

            t0 = time.time()
            manifest = discover_pipeline.run(cfg, out_dir=out_dir)
            elapsed = time.time() - t0

        progress.progress(1.0, text=f"Done in {elapsed:.1f} s")

        # Render the report inline
        with st.spinner("Rendering report…"):
            from bindsight.report import render_run

            report_path = render_run(out_dir)

        st.success(f"Demo complete in {elapsed:.1f} seconds.")
        _show_run_summary(out_dir, manifest, report_path)


def _page_run() -> None:
    st.title("Run on your own data")
    st.markdown(
        "Upload your **counts** matrix (gene × sample, integer counts) and "
        "**sample design** TSV. The pipeline runs the discovery half end-to-end "
        "and produces a paper-style HTML report you can download."
    )

    counts_file = st.file_uploader(
        "Counts matrix (TSV, gene_id × samples)",
        type=["tsv", "tsv.gz", "txt"],
        help="First column is gene_id (Ensembl ENSG…), other columns are sample IDs.",
    )
    design_file = st.file_uploader(
        "Sample design (TSV, sample × factors)",
        type=["tsv", "txt"],
        help="First column is sample (must match counts column names), then a 'condition' column.",
    )

    contrast_factor = st.text_input("Contrast factor", "condition")
    contrast_num = st.text_input("Contrast: numerator level (e.g. 'tumor')", "tumor")
    contrast_den = st.text_input("Contrast: denominator level (e.g. 'normal')", "normal")
    fdr = st.number_input("FDR threshold", 0.001, 1.0, 0.05, step=0.01)
    log2fc = st.number_input("|log2FC| threshold", 0.0, 10.0, 1.0, step=0.1)
    top_n = st.number_input("Top-N targets", 1, 20, 5)

    if st.button("▶  Run pipeline", type="primary", use_container_width=True):
        if not (counts_file and design_file):
            st.error("Please upload both files.")
            return

        out_dir = Path(tempfile.mkdtemp(prefix="bindsight_user_")) / "run"
        out_dir.mkdir(parents=True, exist_ok=True)

        # Persist uploads to disk so the pipeline can read them with pandas.
        counts_path = out_dir / "counts.tsv"
        design_path = out_dir / "design.tsv"
        counts_path.write_bytes(counts_file.getvalue())
        design_path.write_bytes(design_file.getvalue())

        from bindsight.config import (
            DEGParams,
            InputsConfig,
            RunConfig,
            StageParams,
            TargetDiscoveryParams,
        )

        cfg = RunConfig(
            name="user_run",
            out_dir=out_dir,
            inputs=InputsConfig(counts=counts_path, design=design_path),
            params=StageParams(
                deg=DEGParams(
                    design_formula=f"~ {contrast_factor}",
                    contrast=[contrast_factor, contrast_num, contrast_den],
                    fdr_threshold=float(fdr),
                    log2fc_threshold=float(log2fc),
                    min_replicates=2,
                    min_count=0,
                ),
                target_discovery=TargetDiscoveryParams(
                    surfy_allow_offline_fallback=True,
                    use_open_targets=False,
                    require_tractable_modality=[],
                    max_safety_events=1000,
                    require_surface_bind_site=False,
                    top_n=int(top_n),
                ),
            ),
        )

        with st.spinner("Running pipeline (typically 30 s – 2 min)…"):
            try:
                from bindsight.pipelines import discover as discover_pipeline

                t0 = time.time()
                manifest = discover_pipeline.run(cfg, out_dir=out_dir)
                elapsed = time.time() - t0
            except Exception as e:
                st.error(f"Pipeline failed: {e}")
                st.exception(e)
                return

        from bindsight.report import render_run

        report_path = render_run(out_dir)
        st.success(f"Pipeline complete in {elapsed:.1f} seconds.")
        _show_run_summary(out_dir, manifest, report_path)


def _page_browse() -> None:
    st.title("Browse a run")
    st.markdown(
        "Point the picker at a directory produced by `bindsight discover` or "
        "`bindsight demo` to inspect its outputs."
    )
    run_dir_str = st.text_input("Run directory path", "")
    if not run_dir_str:
        st.info("Enter a path above and press Enter.")
        return
    run_dir = Path(run_dir_str)
    if not run_dir.exists():
        st.error(f"Not a directory: {run_dir}")
        return
    _show_run_summary(run_dir, manifest=None, report_path=run_dir / "report.html")


def _page_about() -> None:
    st.title("About bindsight")
    st.markdown(
        """
        bindsight is an open-source pipeline that takes RNA-seq counts and
        outputs ranked de novo protein binder candidates against
        differentially-expressed surface antigens. Every output is one click
        from its evidence chain — the patient cohort, the differential
        expression, the structure, the designer commit, the validator metrics.

        **License:** MIT.
        **Source:** https://github.com/mikhaeelatefrizk/bindsight
        **Docs:** [What is bindsight?](https://github.com/mikhaeelatefrizk/bindsight/blob/main/docs/what-is-bindsight.md) ·
        [How to use](https://github.com/mikhaeelatefrizk/bindsight/blob/main/docs/how-to-use.md) ·
        [Use cases](https://github.com/mikhaeelatefrizk/bindsight/blob/main/docs/use-cases.md) ·
        [Colab design recipe](https://github.com/mikhaeelatefrizk/bindsight/blob/main/docs/colab-design-howto.md)

        **Built on the shoulders of:** RFdiffusion (BSD-3), ProteinMPNN (MIT),
        BindCraft (MIT), BoltzGen (MIT), Boltz-2 (MIT), Chai-1r (Apache-2),
        SURFACE-Bind (BSD-3), Open Targets (CC0), AlphaFoldDB (CC BY 4.0),
        Snakemake (MIT). See `LICENSING.md` for the full per-component
        commercial-use audit.
        """
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _find_repo_root() -> Path:
    """Walk up from this file to find the repo root (where examples/ lives)."""
    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        if (parent / "examples" / "demo" / "config.yaml").exists():
            return parent
    # Fall back to CWD if we can't locate the repo.
    return Path.cwd()


def _show_run_summary(run_dir: Path, manifest, report_path: Path | None) -> None:
    """Render KPIs, tables, and inline-report-iframe for a finished run."""
    import pandas as pd

    candidates_p = run_dir / "targets" / "candidates.parquet"
    epitopes_p = run_dir / "epitopes" / "epitopes.parquet"
    deg_p = run_dir / "deg" / "results.parquet"

    cand = pd.read_parquet(candidates_p) if candidates_p.exists() else None
    epi = pd.read_parquet(epitopes_p) if epitopes_p.exists() else None
    deg = pd.read_parquet(deg_p) if deg_p.exists() else None

    cols = st.columns(4)
    cols[0].metric("Genes tested", len(deg) if deg is not None else 0)
    cols[1].metric(
        "Significant DEGs",
        int(deg["significant"].sum()) if deg is not None and "significant" in deg.columns else 0,
    )
    cols[2].metric("Candidates", len(cand) if cand is not None else 0)
    cols[3].metric("Top-N epitopes", len(epi) if epi is not None else 0)

    if cand is not None and not cand.empty:
        st.markdown("### Ranked target candidates")
        cols_to_show = [
            c
            for c in (
                "rank",
                "symbol",
                "uniprot_id",
                "log2fc",
                "padj",
                "tractable_modalities",
                "n_safety_events",
                "has_alphafold_structure",
                "rank_in_top_n",
            )
            if c in cand.columns
        ]
        st.dataframe(cand[cols_to_show], hide_index=True, use_container_width=True)

        # Download buttons
        st.download_button(
            "⬇  Download candidates.parquet",
            data=candidates_p.read_bytes(),
            file_name="candidates.parquet",
            mime="application/x-parquet",
        )

    if report_path and report_path.exists():
        st.markdown("### Report")
        st.download_button(
            "⬇  Download report.html",
            data=report_path.read_bytes(),
            file_name="report.html",
            mime="text/html",
        )
        # Embed inline so the user sees it without leaving the app.
        with st.expander("Open the rendered report inline", expanded=True):
            st.components.v1.html(
                report_path.read_text(encoding="utf-8"),
                height=900,
                scrolling=True,
            )

    manifest_p = run_dir / "run_manifest.jsonld"
    if manifest_p.exists():
        with st.expander("Provenance manifest (PROV-O JSON-LD)"):
            data = json.loads(manifest_p.read_text(encoding="utf-8"))
            data.pop("@context", None)
            st.json(data)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> None:
    """Streamlit page-router entry point."""
    if st is None:  # pragma: no cover
        print('Streamlit not installed. Run: pip install -e ".[report]"', file=sys.stderr)
        sys.exit(1)

    st.set_page_config(page_title="bindsight", layout="wide", page_icon="🧬")
    _inject_css()

    page = st.sidebar.radio(
        "Navigation",
        options=("🏠 Home", "✨ Demo", "📤 Run on my data", "🔎 Browse a run", "ℹ️ About"),
        label_visibility="collapsed",
    )
    st.sidebar.markdown("---")
    st.sidebar.markdown(
        '<span class="small-muted">bindsight · MIT · '
        '<a href="https://github.com/mikhaeelatefrizk/bindsight">GitHub</a></span>',
        unsafe_allow_html=True,
    )

    if page.startswith("🏠"):
        _page_home()
    elif page.startswith("✨"):
        _page_demo()
    elif page.startswith("📤"):
        _page_run()
    elif page.startswith("🔎"):
        _page_browse()
    else:
        _page_about()


if __name__ == "__main__":
    main()

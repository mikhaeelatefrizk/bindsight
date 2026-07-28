# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""bindsight web app — multi-page Streamlit interface.

Anyone can run this locally (``bindsight ui``) or hit the Streamlit Cloud
deployment to use the tool entirely in a browser.

Pages:

- **Home** — what this is, why it matters, the headline results, CTAs
- **Real results** — the committed benchmarks: rediscovery over six TCGA
  cohorts, and the 20 real ERBB2 binders with their predicted complexes
- **Demo** — one-click run on a real TCGA-BRCA cohort
- **Run with my data** — upload counts.tsv + design.tsv, run the pipeline
- **Browse a run** — open a run directory, inspect tables, view the report
- **About** — links to docs, source, citation

The app is intentionally one file so Streamlit Cloud can deploy from a single
import path. Styling and brand constants come from
:mod:`bindsight.report.theme`; the published numbers come from
:mod:`bindsight.report.showcase`, so nothing on screen is hand-typed.
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

from bindsight.report import showcase, theme

# Streamlit must be importable as the entry point. The rest is lazy-loaded
# below so command-line flags + module probing work without it.
try:
    import streamlit as st
except ImportError:  # pragma: no cover
    st = None  # type: ignore[assignment]


def _inject_css() -> None:
    """Apply the shared stylesheet from :mod:`bindsight.report.theme`."""
    st.markdown(theme.app_css(), unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------
def _page_home() -> None:
    from bindsight import __version__

    st.title("bindsight")
    st.markdown(
        "**RNA-seq counts → ranked de novo protein binder candidates, "
        "with full provenance back to the patient cohort.**"
    )
    st.markdown(
        '<div style="margin-bottom:1rem">'
        f'<span class="pill ok-pill">v{__version__} ready</span>'
        '<span class="pill">AGPL-3.0 license</span>'
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


def _run_demo_cached() -> tuple[Path, object, float, Path]:
    """Run the demo pipeline once per server process and cache the full result.

    The demo always uses the same real TCGA-BRCA cohort (deterministic by GDC
    file id), so the output is safe to share across visitors. Caching the run
    means only the first visitor on a fresh container pays the
    download + pydeseq2 + Open Targets + AlphaFoldDB cost; every subsequent
    visitor sees the same result instantly, and the per-visitor RAM spike → ~0.
    This is the difference between "the app crashes after the first demo" and
    "the app stays up indefinitely under heavy load".
    """
    from bindsight.config import RunConfig
    from bindsight.pipelines import discover as discover_pipeline
    from bindsight.report import render_run

    out_dir = Path(tempfile.mkdtemp(prefix="bindsight_demo_")) / "demo_run"
    repo_root = _find_repo_root()
    cfg_path = repo_root / "examples" / "demo" / "config.yaml"
    cfg = RunConfig.from_yaml(cfg_path)
    cfg.out_dir = out_dir
    cfg.inputs.counts = (cfg_path.parent / "counts.tsv").resolve()
    cfg.inputs.design = (cfg_path.parent / "design.tsv").resolve()

    t0 = time.time()
    manifest = discover_pipeline.run(cfg, out_dir=out_dir)
    elapsed = time.time() - t0
    report_path = render_run(out_dir)
    return out_dir, manifest, elapsed, report_path


def _load_parquet_cached(path_str: str):
    """Cached parquet read so revisiting a run page doesn't re-read from disk."""
    import pandas as pd

    p = Path(path_str)
    if not p.exists():
        return None
    return pd.read_parquet(p)


# Apply Streamlit caching decorators only if streamlit is available.  The
# module must remain importable in test environments where streamlit isn't
# installed (see tests/test_package_imports.py), so we wrap rather than
# decorate at the def site.
if st is not None:
    _run_demo_cached = st.cache_resource(show_spinner=False)(_run_demo_cached)
    _load_parquet_cached = st.cache_data(show_spinner=False)(_load_parquet_cached)


def _page_demo() -> None:
    st.title("Demo: real TCGA-BRCA discovery")
    st.markdown(
        "This runs the full discovery half against a **real TCGA breast-cancer "
        "cohort** (NIH/GDC, tumor vs. adjacent normal). Real pydeseq2 differential "
        "expression, the full SURFY surfaceome filter, Open Targets enrichment, and "
        "ranked output — with full provenance. GPU not required.\n\n"
        "**Result:** antibody-tractable cell-surface antigens over-expressed in "
        "tumor; well-known targets such as ERBB2 (HER2) appear among the candidates "
        "when their signal is present in the cohort."
    )

    if st.button("▶  Run demo now", type="primary", use_container_width=True):
        # The pipeline result is cached per server process via
        # @st.cache_resource, so only the first visitor pays the cold-run cost.
        with st.spinner("Running demo pipeline (cached after first run)…"):
            out_dir, manifest, elapsed, report_path = _run_demo_cached()

        st.progress(1.0, text=f"Done in {elapsed:.1f} s")
        st.success(f"Demo complete in {elapsed:.1f} seconds.")
        _show_run_summary(out_dir, manifest, report_path)


def _render_complex(cif_path: Path, height: int = 420) -> bool:
    """Render a predicted binder-target complex with py3Dmol.

    ``py3Dmol`` has been a declared dependency of the ``report`` extra since the
    beginning and was never imported anywhere; ``report/html.py`` even documents
    a structure viewer that did not exist. This is that viewer.

    Chain ``B`` is the designed binder, chain ``T`` the target antigen, so the
    colouring shows the actual designed interface rather than a generic ribbon.

    Args:
        cif_path: Path to a validator-produced complex mmCIF.
        height: Viewer height in pixels.

    Returns:
        ``True`` if the viewer was rendered, ``False`` if py3Dmol is unavailable.
    """
    try:
        import py3Dmol
    except ImportError:  # pragma: no cover - report extra always ships py3Dmol
        st.info("Install the `report` extra to view structures: `pip install -e '.[report]'`")
        return False

    import streamlit.components.v1 as components

    view = py3Dmol.view(width="100%", height=height)
    view.addModel(cif_path.read_text(encoding="utf-8"), "cif")
    view.setStyle({"chain": "T"}, {"cartoon": {"color": theme.NAVY, "opacity": 0.85}})
    view.setStyle({"chain": "B"}, {"cartoon": {"color": theme.ACCENT}})
    view.zoomTo()
    components.html(view._make_html(), height=height + 10)
    return True


def _page_results() -> None:
    """Show the real, committed benchmark results."""
    import pandas as pd

    st.title("Real results")
    st.markdown(
        "Everything on this page is read straight from `benchmarks/` in the "
        "repository — the same files the paper and the README cite. Nothing here "
        "is illustrative, recomputed on the fly, or hand-typed."
    )

    validation = showcase.load_validation()
    designer = showcase.load_designer_benchmark()

    if validation is None and designer is None:
        st.warning(
            "The `benchmarks/` tree isn't available in this install — it ships with "
            "the repository, not the wheel."
        )
        st.markdown(
            f"Browse the committed results on [GitHub]({theme.GITHUB_URL}/tree/main/benchmarks)."
        )
        return

    # -- Rediscovery ------------------------------------------------------
    if validation is not None:
        st.markdown("## Does it rediscover antigens we already trust?")
        st.markdown(
            "Six real TCGA cohorts were run through the discovery half as "
            "tumor-vs-adjacent-normal contrasts, then scored by where each "
            "clinically-validated antigen landed in the shortlist. **Antigens are "
            "grouped by their *measured* differential expression, not by clinical "
            "fame** — an expression-based method can only surface what is actually "
            "over-expressed, and the benchmark reports that precondition openly."
        )

        top = validation.headline
        cols = st.columns(4)
        if top is not None:
            exp = top["expected"]
            cols[0].metric(f"{exp['symbol']} rank", exp["rank"], help=top["cohort"]["label"])
            cols[1].metric("log2 fold-change", f"{exp['log2fc']:.2f}")
        for i, k in enumerate(("recall@5", "recall@20")):
            if k in validation.recall_at_k:
                cols[2 + i].metric(k, f"{validation.recall_at_k[k] * 100:.0f}%")

        spec = validation.specificity or {}
        if spec.get("n"):
            st.success(
                f"**Specificity: {spec.get('correctly_excluded')}/{spec['n']}.** Antigens that "
                f"are *not* over-expressed at the bulk level are correctly kept out of the "
                f"top {spec.get('k', 20)} — the pipeline keys on genuine over-expression, "
                "not on clinical fame.",
                icon="✅",
            )

        rows = []
        for c in validation.cohorts:
            exp = c.get("expected") or {}
            rows.append(
                {
                    "antigen": exp.get("symbol", "—"),
                    "cohort": c.get("cohort", {}).get("label", ""),
                    "project": c.get("cohort", {}).get("project", ""),
                    "over-expressed": c.get("category") == "over_expressed",
                    "log2fc": exp.get("log2fc"),
                    "padj": exp.get("padj"),
                    "rank": exp.get("rank"),
                }
            )
        st.dataframe(
            pd.DataFrame(rows),
            hide_index=True,
            use_container_width=True,
            column_config={
                "over-expressed": st.column_config.CheckboxColumn(disabled=True),
                "log2fc": st.column_config.NumberColumn(format="%.2f"),
                "padj": st.column_config.NumberColumn(format="%.2e"),
                "rank": st.column_config.NumberColumn(
                    help="Position in the shortlist; blank = not surfaced"
                ),
            },
        )

        if validation.data_limited:
            with st.expander("Antigens excluded for data reasons (reported for transparency)"):
                for d in validation.data_limited:
                    st.markdown(f"- **{d.get('symbol')}** ({d.get('project')}) — {d.get('reason')}")

        fig_cols = st.columns(2)
        for i, key in enumerate(("antigen_rank", "recall_at_k")):
            if key in validation.figures:
                fig_cols[i].image(str(validation.figures[key]), use_container_width=True)

        volcanoes = {k: v for k, v in validation.figures.items() if k.startswith("volcano_")}
        if volcanoes:
            label = st.selectbox(
                "Differential expression by cohort",
                options=sorted(volcanoes),
                format_func=lambda k: k.replace("volcano_", "").replace("_", " ").upper(),
            )
            st.image(str(volcanoes[label]), use_container_width=True)

    # -- Designer benchmark ----------------------------------------------
    if designer is not None:
        st.markdown("## The binders it actually designed")
        provenance = (
            f"**Real GPU run**, not a simulation — backend `{designer.backend}`, "
            f"GPU `{designer.gpu}`, validator `{designer.validator}`, "
            f"bindsight `{designer.bindsight_version}`, {designer.generated_utc[:10]}."
        )
        st.markdown(provenance)
        if designer.targets:
            st.caption(f"Target: {designer.targets[0]}")

        best = designer.best
        cols = st.columns(4)
        cols[0].metric("Designs", designer.n_designs)
        if best is not None and best.iptm is not None:
            cols[1].metric("Best ipTM", f"{best.iptm:.2f}")
        if designer.success_rate is not None:
            cols[2].metric("Success @ ipTM 0.65", f"{designer.success_rate * 100:.0f}%")
        paes = [b.pae_interaction for b in designer.binders if b.pae_interaction is not None]
        if paes:
            cols[3].metric("Mean PAE-int", f"{sum(paes) / len(paes):.1f} Å")

        # -- 3D viewer ----------------------------------------------------
        with_struct = designer.with_structures()
        if with_struct:
            st.markdown("### The predicted complexes")
            st.markdown(
                f"<span class='pill' style='background:{theme.ACCENT}22;color:{theme.ACCENT}'>"
                "designed binder</span> docked against "
                f"<span class='pill'>target antigen</span> — the real Boltz-2 predicted "
                "structure behind each ipTM below.",
                unsafe_allow_html=True,
            )
            choice = st.selectbox(
                "Design",
                options=[b.binder_id for b in with_struct],
                format_func=lambda bid: (
                    f"{bid} — ipTM {next(b.iptm for b in with_struct if b.binder_id == bid):.3f}"
                ),
            )
            binder = next(b for b in with_struct if b.binder_id == choice)

            view_col, meta_col = st.columns([3, 1])
            with view_col:
                if binder.complex_cif is not None:
                    _render_complex(binder.complex_cif)
            with meta_col:
                if binder.iptm is not None:
                    st.metric("ipTM", f"{binder.iptm:.3f}")
                if binder.pae_interaction is not None:
                    st.metric("PAE-int", f"{binder.pae_interaction:.1f} Å")
                dev = binder.developability.get("developability_score")
                if dev is not None:
                    st.metric("Developability", f"{dev:.2f}")
                if binder.target_uniprot:
                    st.caption(f"Target {binder.target_uniprot}")
            seq = binder.sequence
            if seq:
                st.code(seq, language=None)
                st.caption(f"{len(seq)} aa · ProteinMPNN sequence · chain B in the structure above")

        # -- Per-design table ---------------------------------------------
        st.markdown("### Every design, scored")
        table = pd.DataFrame(
            [
                {
                    "binder_id": b.binder_id,
                    "ipTM": b.iptm,
                    "PAE-int (Å)": b.pae_interaction,
                    "developability": b.developability.get("developability_score"),
                    "length": b.developability.get("length"),
                    "instability": b.developability.get("instability_index"),
                    "GRAVY": b.developability.get("gravy"),
                    "free Cys": b.developability.get("n_cys"),
                }
                for b in designer.scored
            ]
        )
        st.dataframe(
            table,
            hide_index=True,
            use_container_width=True,
            column_config={
                "ipTM": st.column_config.ProgressColumn(
                    min_value=0.0,
                    max_value=1.0,
                    format="%.3f",
                    help="Boltz-2 interface confidence; ≥0.65 counts as success",
                ),
                "developability": st.column_config.ProgressColumn(
                    min_value=0.0,
                    max_value=1.0,
                    format="%.2f",
                    help="Composite of ProtParam sequence-biophysics descriptors",
                ),
                "PAE-int (Å)": st.column_config.NumberColumn(format="%.1f"),
                "instability": st.column_config.NumberColumn(
                    format="%.1f", help="ProtParam instability index; <40 predicts stable"
                ),
                "GRAVY": st.column_config.NumberColumn(format="%.3f"),
            },
        )

        # -- Sequence space ------------------------------------------------
        coords = [b for b in designer.binders if b.pc1 is not None and b.pc2 is not None]
        if coords:
            st.markdown("### Sequence space (ESM-2 → PCA)")
            st.markdown(
                "Each design's mean-pooled ESM-2 embedding projected to two dimensions — "
                "a *pre-GPU* triage that shows which designs cluster and which are outliers "
                "before spending compute on validation."
            )
            st.scatter_chart(
                pd.DataFrame(
                    {
                        "PC1": [b.pc1 for b in coords],
                        "PC2": [b.pc2 for b in coords],
                        "ipTM": [b.iptm for b in coords],
                    }
                ),
                x="PC1",
                y="PC2",
                color="ipTM",
                use_container_width=True,
            )

    st.markdown("---")
    st.markdown(
        f"Reproduce these numbers yourself: "
        f"[validation]({theme.GITHUB_URL}/blob/main/benchmarks/validation/RESULTS.md) · "
        f"[designer benchmark]({theme.GITHUB_URL}/blob/main/benchmarks/designer_benchmark/RESULTS.md)"
    )


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
    st.markdown(
        f"""
        # About bindsight

        bindsight is an open-source pipeline that takes RNA-seq counts and
        outputs ranked de novo protein binder candidates against
        differentially-expressed surface antigens. Every output is one click
        from its evidence chain — the patient cohort, the differential
        expression, the structure, the designer commit, the validator metrics.

        **License:** {theme.LICENSE_NAME} ·
        **Source:** [GitHub]({theme.GITHUB_URL}) ·
        **Cite:** [Zenodo DOI]({theme.ZENODO_DOI_URL})

        **Docs:** [What is bindsight?]({theme.docs_url("what-is-bindsight")}) ·
        [How to use]({theme.docs_url("how-to-use")}) ·
        [Use cases]({theme.docs_url("use-cases")}) ·
        [Designing on Colab]({theme.docs_url("colab-design-howto")})

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
    candidates_p = run_dir / "targets" / "candidates.parquet"
    epitopes_p = run_dir / "epitopes" / "epitopes.parquet"
    deg_p = run_dir / "deg" / "results.parquet"

    # Cached parquet reads (see @st.cache_data on _load_parquet_cached) keep
    # repeat visits to the same run free of disk I/O and pandas re-allocation.
    cand = _load_parquet_cached(str(candidates_p))
    epi = _load_parquet_cached(str(epitopes_p))
    deg = _load_parquet_cached(str(deg_p))

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

    st.set_page_config(
        page_title=theme.PAGE_TITLE,
        layout=theme.LAYOUT,
        page_icon=theme.PAGE_ICON,
        # All navigation lives in the sidebar, and Streamlit collapses it on
        # phones by default -- which left mobile visitors on Home with no
        # visible way to reach any other page.
        initial_sidebar_state="expanded",
    )
    _inject_css()

    page = st.sidebar.radio(
        "Navigation",
        options=(
            "🏠 Home",
            "🔬 Real results",
            "✨ Demo",
            "📤 Run on my data",
            "🔎 Browse a run",
            "ℹ️ About",
        ),
        label_visibility="collapsed",
    )
    st.sidebar.markdown("---")
    st.sidebar.markdown(
        f'<span class="small-muted">bindsight · {theme.LICENSE_NAME} · '
        f'<a href="{theme.GITHUB_URL}">GitHub</a> · '
        f'<a href="{theme.DOCS_URL}">Docs</a></span>',
        unsafe_allow_html=True,
    )

    if page.startswith("🏠"):
        _page_home()
    elif page.startswith("🔬"):
        _page_results()
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

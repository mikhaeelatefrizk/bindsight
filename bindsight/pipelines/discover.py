"""Discovery-half orchestrator.

Joins the upstream genomics evidence into a ranked target shortlist:

    DEGs  ──►  Open Targets enrichment  ──►  Surfaceome filter
                                                    │
                                                    ▼
                                              Top-N targets
                                                    │
                                                    ▼
                                          AlphaFoldDB structures
                                                    │
                                                    ▼
                                       SURFACE-Bind site lookup
                                                    │
                                                    ▼
                                       targets/candidates.parquet
                                       epitopes/epitopes.parquet

All steps are CPU-only and run on the user's laptop. Each stage appends a
:class:`bindsight.provenance.StageRecord` to a single per-run manifest.

Failures are recorded, not swallowed: if Open Targets has no record for a
gene, we tag the row ``no_open_targets`` and keep going. The downstream
``rank`` stage uses these tags to build a failure taxonomy for the report.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from bindsight import __version__
from bindsight.config import RunConfig, TargetDiscoveryParams
from bindsight.deg.pydeseq2_runner import PyDESeq2Runner
from bindsight.epitopes.surface_bind import SURFACE_BIND_DATA_ENV, SurfaceBindClient
from bindsight.io.paths import run_dir
from bindsight.provenance import (
    InputRef,
    Manifest,
    OutputRef,
    StageRecord,
    ToolRef,
    new_manifest,
    sha256_file,
)
from bindsight.structures.alphafolddb import AlphaFoldDBClient
from bindsight.surfaceome import is_surface_protein, load_surfy
from bindsight.targets.open_targets import OpenTargetsClient

LOG = logging.getLogger(__name__)

# Cap on how many top candidates (by |log2fc|) get an AlphaFoldDB structure
# fetch. Only the top-N proceed to design, so fetching for every surface DE gene
# on a real cohort (hundreds) is wasted work; this keeps discovery fast.
_STRUCTURE_FETCH_CAP = 25

# Cap on how many up-regulated significant DEGs are carried into target
# enrichment (Open Targets / UniProt mapping). A real cohort yields thousands of
# significant genes; antibody targets need tumor over-expression, so we enrich
# the most up-regulated and bound the (per-gene) Open Targets calls.
_ENRICH_TOP_K = 300


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def run(
    config: RunConfig,
    *,
    out_dir: Path | None = None,
    open_targets_client: OpenTargetsClient | None = None,
    alphafolddb_client: AlphaFoldDBClient | None = None,
    surface_bind_client: SurfaceBindClient | None = None,
    surfy: frozenset[str] | None = None,
) -> Manifest:
    """Run the discovery half end-to-end and write artifacts to ``out_dir``.

    The optional client/data arguments exist so tests can inject mocks. In
    normal use, they default to live clients hitting the public APIs.
    """
    root = run_dir(out_dir or config.out_dir)
    LOG.info("bindsight discover: out=%s name=%s", root, config.name)

    # Stage 0: ensure real reference data is present (auto-download TCGA cohort
    # from GDC if configured + missing; populate the full SURFY surfaceome cache
    # for production runs). No-ops when data is already present or injected.
    _ensure_reference_data(config, surfy=surfy)
    surface_bind_client = _resolve_surface_bind_client(surface_bind_client)

    manifest = new_manifest(name=config.name, config_path=str(config.inputs.counts.parent))

    # ---- 1. DEG ----
    deg_table_path = root / "deg" / "results.parquet"
    deg_stage = _stage_deg(config, deg_table_path)
    manifest.append(deg_stage)
    if deg_stage.status != "completed":
        manifest.write(root / "run_manifest.jsonld")
        return manifest

    # ---- 2. Discover ----
    candidates_path = root / "targets" / "candidates.parquet"
    epitopes_path = root / "epitopes" / "epitopes.parquet"
    discover_stage = _stage_discover(
        config,
        deg_table_path=deg_table_path,
        candidates_path=candidates_path,
        epitopes_path=epitopes_path,
        open_targets_client=open_targets_client,
        alphafolddb_client=alphafolddb_client,
        surface_bind_client=surface_bind_client,
        surfy=surfy,
    )
    manifest.append(discover_stage)

    manifest.write(root / "run_manifest.jsonld")
    LOG.info("bindsight discover complete; manifest=%s", root / "run_manifest.jsonld")
    return manifest


# ---------------------------------------------------------------------------
# Stage 0: ensure real reference data (GDC cohort + SURFY surfaceome)
# ---------------------------------------------------------------------------
def _ensure_reference_data(config: RunConfig, *, surfy: frozenset[str] | None) -> None:
    """Auto-download the real input cohort from NIH/GDC when configured + missing.

    Only fires when ``inputs.download`` is set and the counts/design files don't
    exist yet. (The SURFY surfaceome cache is populated later, inside the
    discover stage, so a missing-inputs run fails fast on DEG without any
    network calls.)
    """
    counts_p = Path(config.inputs.counts)
    design_p = Path(config.inputs.design)
    dl = config.inputs.download
    if dl is not None and (not counts_p.exists() or not design_p.exists()):
        from bindsight.io.gdc import fetch_cohort

        LOG.info("inputs missing; auto-downloading %s cohort from GDC", dl.project)
        fetch_cohort(
            project=dl.project,
            n_tumor=dl.n_tumor,
            n_normal=dl.n_normal,
            counts_out=counts_p,
            design_out=design_p,
            gene_types=tuple(dl.gene_types),
        )


def _resolve_surfy(p: object, surfy: frozenset[str] | None) -> frozenset[str]:
    """Return the SURFY surface set, populating the full cache on first use.

    If an explicit set was injected (tests), use it. Otherwise populate the full
    canonical SURFY cache when empty, falling back to the bundled offline list
    only if allowed.
    """
    from bindsight.config import TargetDiscoveryParams

    assert isinstance(p, TargetDiscoveryParams)
    if surfy is not None:
        return surfy
    if p.require_surfy:
        from bindsight.surfaceome.surfy import _surfy_cache_path, populate_surfy_cache

        if not _surfy_cache_path().exists():
            LOG.info("SURFY cache empty; populating the full surfaceome list")
            try:
                populate_surfy_cache()
            except Exception as e:  # network/parse failure
                if not p.surfy_allow_offline_fallback:
                    raise
                LOG.warning("SURFY populate failed (%s); using bundled offline fallback", e)
    return load_surfy(allow_offline_fallback=p.surfy_allow_offline_fallback)


# ---------------------------------------------------------------------------
# Stage: DEG
# ---------------------------------------------------------------------------
def _stage_deg(config: RunConfig, out_path: Path) -> StageRecord:
    counts_p = Path(config.inputs.counts)
    design_p = Path(config.inputs.design)

    inputs: list[InputRef] = []
    for role, p in (("counts", counts_p), ("design", design_p)):
        if p.exists():
            inputs.append(
                InputRef(
                    role=role,
                    path=str(p),
                    sha256=sha256_file(p),
                    bytes=p.stat().st_size,
                    media_type="text/tab-separated-values",
                )
            )

    try:
        from pydeseq2 import __version__ as pydeseq2_version
    except ImportError:
        pydeseq2_version = "uninstalled"

    stage = StageRecord(
        name="deg",
        tool=ToolRef(
            name="pydeseq2",
            version=pydeseq2_version,
            license="MIT",
            repo_url="https://github.com/owkin/PyDESeq2",
            citation="10.1093/bioinformatics/btad547",
        ),
        inputs=inputs,
        params=config.params.deg.model_dump(),
    )

    if not counts_p.exists() or not design_p.exists():
        stage.mark_failed(
            f"missing input(s): counts_exists={counts_p.exists()} design_exists={design_p.exists()}"
        )
        return stage

    try:
        runner = PyDESeq2Runner(config.params.deg)
        metrics = runner.run(counts_p, design_p, out_path)
        stage.notes = (
            f"n_samples={metrics['n_samples']}, "
            f"n_genes_tested={metrics['n_genes_tested']}, "
            f"n_significant={metrics['n_significant']}"
        )
        stage.mark_completed(
            outputs=[
                OutputRef(
                    role="deg_table",
                    path=str(out_path),
                    sha256=sha256_file(out_path),
                    bytes=out_path.stat().st_size,
                    media_type="application/x-parquet",
                )
            ]
        )
    except Exception as e:
        LOG.exception("DEG stage failed")
        stage.mark_failed(repr(e))
    return stage


# ---------------------------------------------------------------------------
# Stage: discover (joins DEGs → Open Targets → SURFY → SURFACE-Bind → AFDB)
# ---------------------------------------------------------------------------
def _stage_discover(
    config: RunConfig,
    *,
    deg_table_path: Path,
    candidates_path: Path,
    epitopes_path: Path,
    open_targets_client: OpenTargetsClient | None,
    alphafolddb_client: AlphaFoldDBClient | None,
    surface_bind_client: SurfaceBindClient | None,
    surfy: frozenset[str] | None,
) -> StageRecord:
    stage = StageRecord(
        name="discover",
        tool=ToolRef(
            name=f"bindsight/{__version__}",
            version=__version__,
            license="MIT",
            repo_url="https://github.com/mikhaeelatefrizk/bindsight",
        ),
        inputs=[
            InputRef(
                role="deg_table",
                path=str(deg_table_path),
                sha256=sha256_file(deg_table_path),
                bytes=deg_table_path.stat().st_size,
                media_type="application/x-parquet",
            )
        ],
        params=config.params.target_discovery.model_dump(),
    )

    try:
        candidates_df, epitopes_df, taxonomy_df = _do_discover(
            config=config,
            deg_table_path=deg_table_path,
            open_targets_client=open_targets_client,
            alphafolddb_client=alphafolddb_client,
            surface_bind_client=surface_bind_client,
            surfy=surfy,
        )
        candidates_path.parent.mkdir(parents=True, exist_ok=True)
        epitopes_path.parent.mkdir(parents=True, exist_ok=True)
        taxonomy_path = candidates_path.parent.parent / "taxonomy" / "failure_taxonomy.parquet"
        taxonomy_path.parent.mkdir(parents=True, exist_ok=True)
        candidates_df.to_parquet(candidates_path, index=False)
        epitopes_df.to_parquet(epitopes_path, index=False)
        taxonomy_df.to_parquet(taxonomy_path, index=False)

        disp_counts = taxonomy_df["disposition"].value_counts().to_dict()
        stage.notes = (
            f"n_candidates={len(candidates_df)}, "
            f"n_with_structure={int(candidates_df['has_alphafold_structure'].sum())}, "
            f"n_top={int((candidates_df['rank_in_top_n']).sum())}; "
            f"taxonomy({len(taxonomy_df)} genes)="
            + ",".join(f"{k}:{v}" for k, v in sorted(disp_counts.items()))
        )
        stage.mark_completed(
            outputs=[
                OutputRef(
                    role="candidates",
                    path=str(candidates_path),
                    sha256=sha256_file(candidates_path),
                    bytes=candidates_path.stat().st_size,
                    media_type="application/x-parquet",
                ),
                OutputRef(
                    role="epitopes",
                    path=str(epitopes_path),
                    sha256=sha256_file(epitopes_path),
                    bytes=epitopes_path.stat().st_size,
                    media_type="application/x-parquet",
                ),
                OutputRef(
                    role="failure_taxonomy",
                    path=str(taxonomy_path),
                    sha256=sha256_file(taxonomy_path),
                    bytes=taxonomy_path.stat().st_size,
                    media_type="application/x-parquet",
                ),
            ]
        )
    except Exception as e:
        LOG.exception("discover stage failed")
        stage.mark_failed(repr(e))
    return stage


def _do_discover(
    *,
    config: RunConfig,
    deg_table_path: Path,
    open_targets_client: OpenTargetsClient | None,
    alphafolddb_client: AlphaFoldDBClient | None,
    surface_bind_client: SurfaceBindClient | None,
    surfy: frozenset[str] | None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Pure-data discovery logic; returns (candidates_df, epitopes_df, taxonomy_df)."""
    p = config.params.target_discovery

    # 1. Load DEGs and keep significant ones. Antibody targets need tumor
    #    over-expression, so carry the most up-regulated significant genes into
    #    enrichment (bounded — a real cohort has thousands of significant DEGs).
    deg = pd.read_parquet(deg_table_path)
    sig = deg[deg["significant"]].copy()
    n_sig = len(sig)
    # Carry the most *confidently* over-expressed genes into enrichment, ranked
    # by the combined DE score π = log2fc × −log10(padj) rather than raw
    # fold-change — so a highly-significant, abundant antigen with a moderate
    # ratio (e.g. PSMA) is not crowded out by noisy high-fold-change genes.
    sig["pi_score"] = _pi_score(sig)
    sig = sig.sort_values("pi_score", ascending=False).head(_ENRICH_TOP_K)
    enriched_gene_ids = {str(g) for g in sig["gene_id"]}
    LOG.info(
        "DEGs: %d total, %d significant; enriching top %d by combined score (π)",
        len(deg),
        n_sig,
        len(sig),
    )

    # Default clients
    ot = open_targets_client or OpenTargetsClient()
    afdb = alphafolddb_client or AlphaFoldDBClient()
    surfy_set = _resolve_surfy(p, surfy)

    # 2. For each significant gene, enrich via Open Targets (or fall back to
    #    the bundled offline map for well-known genes — used by the demo and
    #    when Open Targets is unreachable).
    from bindsight.targets import ensembl_uniprot

    enriched_rows: list[dict[str, object]] = []
    for _, row in sig.iterrows():
        gene_id = str(row["gene_id"])
        ev = None
        ot_status = "skipped"
        if p.use_open_targets:
            try:
                ev = ot.get_target(gene_id)
                ot_status = "ok" if ev is not None else "no_record"
            except Exception as e:
                LOG.warning("Open Targets failed for %s: %s", gene_id, e)
                ot_status = f"error:{type(e).__name__}"

        uniprot_ids = ev.uniprot_ids if ev else []
        modalities = ev.tractability_modalities if ev else []
        symbol = ev.symbol if ev else None

        # Offline / fallback path: consult the bundled ENSG → UniProt map for
        # well-known genes so the demo (and other offline runs) still produce
        # candidates.
        if not uniprot_ids:
            fb_symbol, fb_uniprot = ensembl_uniprot.lookup(gene_id)
            if fb_uniprot:
                uniprot_ids = [fb_uniprot]
                if symbol is None:
                    symbol = fb_symbol
                if ot_status == "skipped":
                    ot_status = "bundled_fallback"

        for uniprot_id in uniprot_ids or [None]:
            enriched_rows.append(
                {
                    "gene_id": gene_id,
                    "symbol": symbol,
                    "uniprot_id": uniprot_id,
                    "log2fc": float(row["log2fc"]),
                    "padj": float(row["padj"]) if pd.notna(row["padj"]) else None,
                    "tractable_modalities": ";".join(modalities),
                    "open_targets_status": ot_status,
                    "n_safety_events": ev.safety_event_count if ev else 0,
                }
            )

    candidates = pd.DataFrame(enriched_rows)
    enriched_all = candidates.copy()
    if candidates.empty:
        LOG.warning("no candidates after Open Targets enrichment")
        taxonomy = _build_taxonomy(
            deg,
            enriched_gene_ids,
            enriched_all,
            _empty_candidates_frame(),
            _empty_epitopes_frame(),
            surfy_set,
            p,
            surface_bind_active=surface_bind_client is not None,
        )
        return _empty_candidates_frame(), _empty_epitopes_frame(), taxonomy

    # 3. Surfaceome filter.
    if p.require_surfy:
        before = len(candidates)
        candidates["is_surface"] = candidates["uniprot_id"].apply(
            lambda u: bool(u) and is_surface_protein(u, surfy=surfy_set)
        )
        candidates = candidates[candidates["is_surface"]].copy()
        LOG.info("surfaceome filter: %d → %d", before, len(candidates))
    else:
        candidates["is_surface"] = True

    # 4. Tractability filter (optional).
    if p.require_tractable_modality and not candidates.empty:
        before = len(candidates)
        wanted = set(p.require_tractable_modality)

        def _has_wanted_modality(s: str) -> bool:
            modalities = {m.strip() for m in s.split(";") if m.strip()}
            return bool(wanted & modalities)

        candidates = candidates[
            candidates["tractable_modalities"].fillna("").apply(_has_wanted_modality)
        ].copy()
        LOG.info("tractability filter (%s): %d → %d", sorted(wanted), before, len(candidates))

    # 5. Safety filter (optional).
    if not candidates.empty:
        before = len(candidates)
        candidates = candidates[candidates["n_safety_events"] <= p.max_safety_events].copy()
        LOG.info(
            "safety filter (≤%d events): %d → %d", p.max_safety_events, before, len(candidates)
        )

    # 6. Pull AlphaFoldDB structures + tag. Only the strongest candidates carry
    #    forward to design, so we fetch structures for the top ones by |log2fc|
    #    (capped) rather than every surface DE gene — on a real cohort that can
    #    be hundreds, and the rest are never used downstream.
    if not candidates.empty:
        candidates["pi_score"] = _pi_score(candidates)
        candidates = candidates.sort_values(by="pi_score", ascending=False).reset_index(drop=True)
        n_fetch = max(p.top_n, _STRUCTURE_FETCH_CAP)
        fetch_uniprots = sorted(
            {u for u in candidates.head(n_fetch)["uniprot_id"].dropna().unique() if u}
        )
        struct_paths: dict[str, Path | None] = {}
        for uid in fetch_uniprots:
            try:
                struct_paths[uid] = afdb.fetch(uid)
            except Exception as e:
                LOG.warning("AlphaFoldDB fetch failed for %s: %s", uid, e)
                struct_paths[uid] = None
        candidates["alphafold_structure_path"] = candidates["uniprot_id"].map(
            lambda u: str(struct_paths.get(u, "")) if u and struct_paths.get(u) else ""
        )
        candidates["has_alphafold_structure"] = candidates["alphafold_structure_path"] != ""
    else:
        candidates["alphafold_structure_path"] = ""
        candidates["has_alphafold_structure"] = False

    # 7. Rank by the combined DE score π = log2fc × −log10(padj) (Xiao et al.
    #    2014), structures first (only structure-bearing candidates can proceed
    #    to design). Higher π = more confidently over-expressed.
    if "pi_score" not in candidates.columns:
        candidates["pi_score"] = _pi_score(candidates)
    candidates = candidates.sort_values(
        by=["has_alphafold_structure", "pi_score"],
        ascending=[False, False],
    ).reset_index(drop=True)
    candidates["rank"] = range(1, len(candidates) + 1)
    candidates["rank_in_top_n"] = candidates["rank"] <= p.top_n

    # 8. Build the epitopes table from SURFACE-Bind targetable sites when the
    # data is vendored; otherwise design against the whole surface, recorded
    # honestly in ``epitope_status``.
    epitopes = _build_epitopes(candidates[candidates["rank_in_top_n"]], surface_bind_client, p)

    # 9. Negative-result taxonomy: one disposition per DEG gene, explaining why it
    # is / isn't a surfaced candidate. Every gene is accounted for (the counts sum
    # to the DEG total) — the failure modes are a first-class, auditable output.
    taxonomy = _build_taxonomy(
        deg,
        enriched_gene_ids,
        enriched_all,
        candidates,
        epitopes,
        surfy_set,
        p,
        surface_bind_active=surface_bind_client is not None,
    )
    return candidates, epitopes, taxonomy


# Negative-result taxonomy: the ordered dispositions a DEG gene can land in, from
# "never in contention" to "surfaced". The funnel is exhaustive, so the per-
# disposition counts always sum to the total DEG gene count.
TAXONOMY_DISPOSITIONS: tuple[str, ...] = (
    "not_significant",
    "down_regulated",
    "below_enrichment_cutoff",
    "no_uniprot",
    "not_surfaceome",
    "fails_tractability",
    "fails_safety",
    "no_alphafold_model",
    "not_top_n",
    "no_surface_bind_site",
    "surfaced",
)


def _build_taxonomy(
    deg: pd.DataFrame,
    enriched_gene_ids: set[str],
    enriched_all: pd.DataFrame,
    candidates: pd.DataFrame,
    epitopes: pd.DataFrame,
    surfy_set: frozenset[str],
    p: TargetDiscoveryParams,
    *,
    surface_bind_active: bool,
) -> pd.DataFrame:
    """One disposition per DEG gene explaining why it is / isn't a surfaced candidate.

    Re-derives each gene's fate from the same signals the pipeline used — without
    perturbing the candidate/epitope outputs — so the failure modes (the "negative
    results") become an auditable, first-class artifact. The funnel is exhaustive:
    the per-disposition counts always sum to the total DEG gene count.
    """
    wanted = {m for m in (p.require_tractable_modality or [])}

    # Per-gene "furthest stage reached", collapsed over a gene's UniProt rows.
    reach: dict[str, dict[str, bool]] = {}
    sym_map: dict[str, object] = {}
    for r in enriched_all.itertuples(index=False):
        gid = str(r.gene_id)
        sym_map.setdefault(gid, getattr(r, "symbol", None))
        uniprot = getattr(r, "uniprot_id", None)
        has_u = bool(uniprot) and pd.notna(uniprot)
        surf = has_u and (not p.require_surfy or is_surface_protein(str(uniprot), surfy=surfy_set))
        mods = {
            m.strip()
            for m in str(getattr(r, "tractable_modalities", "") or "").split(";")
            if m.strip()
        }
        tract = surf and (not wanted or bool(wanted & mods))
        safe = tract and (int(getattr(r, "n_safety_events", 0) or 0) <= p.max_safety_events)
        d = reach.setdefault(gid, {"u": False, "surf": False, "tract": False, "safe": False})
        d["u"] |= has_u
        d["surf"] |= surf
        d["tract"] |= tract
        d["safe"] |= safe

    cand_gids: set[str] = set()
    struct_gids: set[str] = set()
    topn_gids: set[str] = set()
    if not candidates.empty:
        cand_gids = {str(g) for g in candidates["gene_id"]}
        struct_gids = {
            str(g) for g in candidates.loc[candidates["has_alphafold_structure"], "gene_id"]
        }
        topn_gids = {str(g) for g in candidates.loc[candidates["rank_in_top_n"], "gene_id"]}
    site_gids: set[str] = set()
    if surface_bind_active and not epitopes.empty and "epitope_status" in epitopes.columns:
        site_gids = {
            str(g)
            for g in epitopes.loc[epitopes["epitope_status"] == "surface_bind_site", "gene_id"]
        }

    rows: list[dict[str, object]] = []
    for r in deg.itertuples(index=False):
        gid = str(r.gene_id)
        significant = bool(getattr(r, "significant", False))
        log2fc = float(r.log2fc) if pd.notna(getattr(r, "log2fc", None)) else None
        padj = float(r.padj) if pd.notna(getattr(r, "padj", None)) else None
        # Terminal outcome wins: a gene's *actual* fate (the pipeline ranks rather
        # than hard-filters on fold-change/structure, so a down-regulated or
        # structure-less gene can still appear in candidates). Only genes that
        # never reached candidates get the upstream "why dropped" reasons.
        if gid in struct_gids and gid in topn_gids:
            disp = (
                "no_surface_bind_site"
                if surface_bind_active and gid not in site_gids
                else "surfaced"
            )
        elif gid in cand_gids:
            # passed the filters but can't proceed to design: no structure, or out of top-N
            disp = "no_alphafold_model" if gid not in struct_gids else "not_top_n"
        elif gid in enriched_gene_ids:
            d = reach.get(gid, {"u": False, "surf": False, "tract": False, "safe": False})
            if not d["u"]:
                disp = "no_uniprot"
            elif p.require_surfy and not d["surf"]:
                disp = "not_surfaceome"
            elif wanted and not d["tract"]:
                disp = "fails_tractability"
            else:
                disp = "fails_safety"
        elif not significant:
            disp = "not_significant"
        elif (log2fc or 0.0) <= 0.0:
            disp = "down_regulated"
        else:
            disp = "below_enrichment_cutoff"
        rows.append(
            {
                "gene_id": gid,
                "symbol": sym_map.get(gid),
                "log2fc": log2fc,
                "padj": padj,
                "disposition": disp,
            }
        )
    return pd.DataFrame(rows, columns=["gene_id", "symbol", "log2fc", "padj", "disposition"])


def _pi_score(df: pd.DataFrame) -> pd.Series:
    """Combined DE ranking score π = log2fc × −log10(padj) (Xiao et al. 2014).

    Rewards genes that are both strongly and *confidently* up-regulated. Genes
    with a large fold-change but weak significance, or down-regulated genes
    (negative log2fc → negative score), are naturally de-prioritised. A missing
    padj maps to π = 0.
    """
    padj = df["padj"].astype(float).fillna(1.0).clip(lower=1e-300)
    return df["log2fc"].astype(float) * -np.log10(padj)


def _empty_candidates_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "gene_id",
            "symbol",
            "uniprot_id",
            "log2fc",
            "padj",
            "tractable_modalities",
            "open_targets_status",
            "n_safety_events",
            "is_surface",
            "alphafold_structure_path",
            "has_alphafold_structure",
            "rank",
            "rank_in_top_n",
        ]
    )


def _resolve_surface_bind_client(injected: SurfaceBindClient | None) -> SurfaceBindClient | None:
    """Return the injected client, or auto-construct one from vendored data.

    Auto-construction happens *only* if SURFACE-Bind data is actually vendored
    (the ``BINDSIGHT_SURFACE_BIND_DATA`` env var is set, or
    ``data/surface_bind/sites/`` exists). A bare or absent data tree yields None
    — discovery then designs against the whole surface and says so.
    """
    if injected is not None:
        return injected
    import os

    env = os.environ.get(SURFACE_BIND_DATA_ENV)
    local = Path("data/surface_bind")
    root: str | Path | None = env or (local if (local / "sites").is_dir() else None)
    if root is None:
        return None
    try:
        return SurfaceBindClient(data_root=root)
    except (RuntimeError, FileNotFoundError) as e:
        LOG.warning("SURFACE-Bind data not usable (%s); designing against the whole surface", e)
        return None


def _build_epitopes(
    top: pd.DataFrame, client: SurfaceBindClient | None, p: TargetDiscoveryParams
) -> pd.DataFrame:
    """Build the epitopes table for the top-N candidates.

    With a SURFACE-Bind client whose data is vendored, each candidate gets one
    row per qualifying targetable site (real residues → focused RFdiffusion
    design). The ``epitope_status`` is honest about what happened:

    - ``surface_bind_site``           — a real vendored site (focused design);
    - ``no_surface_bind_site``        — data present, none for this protein;
    - ``surface_bind_not_configured`` — no SURFACE-Bind data vendored.

    ``require_surface_bind_site`` only bites when data is actually vendored: with
    a client, ``True`` carries *only* candidates that have ≥1 qualifying site,
    while ``False`` carries every top-N candidate (whole-surface where no site
    exists). Without vendored data there is nothing to require, so every
    candidate falls back to whole-surface design.
    """
    rows: list[dict[str, Any]] = []
    for _, row in top.iterrows():
        uni = row["uniprot_id"]
        base = {
            "gene_id": row["gene_id"],
            "symbol": row["symbol"],
            "uniprot_id": uni,
            "structure_path": row["alphafold_structure_path"],
        }
        sites: list[Any] = []
        if client is not None and isinstance(uni, str) and uni:
            try:
                sites = [
                    s
                    for s in client.sites(uni)
                    if s.score is None or s.score >= p.min_surface_bind_score
                ]
            except Exception as e:  # malformed vendored data must not abort discovery
                LOG.warning("SURFACE-Bind lookup failed for %s: %s", uni, e)
        if sites:
            for s in sites:
                rows.append(
                    {
                        **base,
                        "site_id": s.site_id,
                        "chain": s.chain,
                        "residues": list(s.residues),
                        "score": s.score,
                        "seed_pdb_path": s.seed_pdb_path,
                        "epitope_status": "surface_bind_site",
                    }
                )
        elif client is None or not p.require_surface_bind_site:
            # whole-surface fallback (honest status); omitted only when data is
            # vendored AND a site is required but none exists for this protein.
            status = "no_surface_bind_site" if client is not None else "surface_bind_not_configured"
            rows.append(
                {
                    **base,
                    "site_id": None,
                    "chain": "A",
                    "residues": [],
                    "score": None,
                    "seed_pdb_path": None,
                    "epitope_status": status,
                }
            )
    return pd.DataFrame(rows) if rows else _empty_epitopes_frame()


def _empty_epitopes_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "gene_id",
            "symbol",
            "uniprot_id",
            "structure_path",
            "site_id",
            "chain",
            "residues",
            "score",
            "seed_pdb_path",
            "epitope_status",
        ]
    )

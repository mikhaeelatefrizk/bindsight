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
:class:`xpr2bind.provenance.StageRecord` to a single per-run manifest.

Failures are recorded, not swallowed: if Open Targets has no record for a
gene, we tag the row ``no_open_targets`` and keep going. The downstream
``rank`` stage uses these tags to build a failure taxonomy for the report.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from xpr2bind import __version__
from xpr2bind.config import RunConfig
from xpr2bind.deg.pydeseq2_runner import PyDESeq2Runner
from xpr2bind.io.paths import run_dir
from xpr2bind.provenance import (
    InputRef,
    Manifest,
    OutputRef,
    StageRecord,
    ToolRef,
    new_manifest,
    sha256_file,
)
from xpr2bind.structures.alphafolddb import AlphaFoldDBClient
from xpr2bind.surfaceome import is_surface_protein, load_surfy
from xpr2bind.targets.open_targets import OpenTargetsClient

LOG = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def run(
    config: RunConfig,
    *,
    out_dir: Path | None = None,
    open_targets_client: OpenTargetsClient | None = None,
    alphafolddb_client: AlphaFoldDBClient | None = None,
    surfy: frozenset[str] | None = None,
) -> Manifest:
    """Run the discovery half end-to-end and write artifacts to ``out_dir``.

    The optional client/data arguments exist so tests can inject mocks. In
    normal use, they default to live clients hitting the public APIs.
    """
    root = run_dir(out_dir or config.out_dir)
    LOG.info("xpr2bind discover: out=%s name=%s", root, config.name)

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
        surfy=surfy,
    )
    manifest.append(discover_stage)

    manifest.write(root / "run_manifest.jsonld")
    LOG.info("xpr2bind discover complete; manifest=%s", root / "run_manifest.jsonld")
    return manifest


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
    surfy: frozenset[str] | None,
) -> StageRecord:
    stage = StageRecord(
        name="discover",
        tool=ToolRef(
            name=f"xpr2bind/{__version__}",
            version=__version__,
            license="MIT",
            repo_url="https://github.com/mikhaeelatefrizk/xpr2bind",
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
        candidates_df, epitopes_df = _do_discover(
            config=config,
            deg_table_path=deg_table_path,
            open_targets_client=open_targets_client,
            alphafolddb_client=alphafolddb_client,
            surfy=surfy,
        )
        candidates_path.parent.mkdir(parents=True, exist_ok=True)
        epitopes_path.parent.mkdir(parents=True, exist_ok=True)
        candidates_df.to_parquet(candidates_path, index=False)
        epitopes_df.to_parquet(epitopes_path, index=False)

        stage.notes = (
            f"n_candidates={len(candidates_df)}, "
            f"n_with_structure={int(candidates_df['has_alphafold_structure'].sum())}, "
            f"n_top={int((candidates_df['rank_in_top_n']).sum())}"
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
    surfy: frozenset[str] | None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Pure-data discovery logic; returns (candidates_df, epitopes_df)."""
    p = config.params.target_discovery

    # 1. Load DEGs and keep significant ones.
    deg = pd.read_parquet(deg_table_path)
    sig = deg[deg["significant"]].copy()
    LOG.info("DEGs: %d total, %d significant", len(deg), len(sig))

    # Default clients
    ot = open_targets_client or OpenTargetsClient()
    afdb = alphafolddb_client or AlphaFoldDBClient()
    surfy_set = surfy or load_surfy(allow_offline_fallback=p.surfy_allow_offline_fallback)

    # 2. For each significant gene, enrich via Open Targets (or fall back to
    #    the bundled offline map for well-known genes — used by the demo and
    #    when Open Targets is unreachable).
    from xpr2bind.targets import ensembl_uniprot

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
    if candidates.empty:
        LOG.warning("no candidates after Open Targets enrichment")
        return _empty_candidates_frame(), _empty_epitopes_frame()

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

    # 6. Pull AlphaFoldDB structures + tag.
    if not candidates.empty:
        unique_uniprots = sorted({u for u in candidates["uniprot_id"].dropna().unique() if u})
        struct_paths: dict[str, Path | None] = {}
        for uid in unique_uniprots:
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

    # 7. Rank: composite score over (log2fc, -log10(padj)). Higher is better.
    candidates = candidates.sort_values(
        by=["has_alphafold_structure", "log2fc"],
        ascending=[False, False],
    ).reset_index(drop=True)
    candidates["rank"] = range(1, len(candidates) + 1)
    candidates["rank_in_top_n"] = candidates["rank"] <= p.top_n

    # 8. Build the (currently empty) epitopes table — populated when SURFACE-Bind
    # vendoring lands in v0.0.3. For now, every top-N candidate gets a row with
    # ``epitope_status = 'pending_surface_bind_lookup'``.
    epitopes_rows = []
    for _, row in candidates[candidates["rank_in_top_n"]].iterrows():
        epitopes_rows.append(
            {
                "gene_id": row["gene_id"],
                "symbol": row["symbol"],
                "uniprot_id": row["uniprot_id"],
                "structure_path": row["alphafold_structure_path"],
                "site_id": None,
                "chain": "A",
                "residues": [],
                "score": None,
                "seed_pdb_path": None,
                "epitope_status": "pending_surface_bind_lookup",
            }
        )
    epitopes = pd.DataFrame(epitopes_rows) if epitopes_rows else _empty_epitopes_frame()

    return candidates, epitopes


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

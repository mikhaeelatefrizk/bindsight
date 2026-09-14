# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
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

import json
import logging
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from bindsight import __version__
from bindsight.config import RunConfig, TargetDiscoveryParams
from bindsight.deg.pydeseq2_runner import PyDESeq2Runner
from bindsight.epitopes.surface_bind import SURFACE_BIND_DATA_ENV, SurfaceBindClient
from bindsight.io.paths import adopt_structure, resolve_run_path, run_dir
from bindsight.pipelines.caveats import DISCOVERY_LIMITATIONS, caveat_summary
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
from bindsight.structures.plddt import mean_plddt, region_plddt
from bindsight.structures.topology import Topology, UniProtTopologyClient
from bindsight.surfaceome import (
    is_surface_protein,
    load_surfaceome,
    load_surfaceome_gene_map,
    load_surfy,
    surfaceome_source,
)
from bindsight.targets.gtex import GTExTissueExpression
from bindsight.targets.open_targets import OpenTargetsClient

LOG = logging.getLogger(__name__)

# Cap on how many top candidates (by |log2fc|) get an AlphaFoldDB structure
# fetch. Only the top-N proceed to design, so fetching for every surface DE gene
# on a real cohort (hundreds) is wasted work; this keeps discovery fast.
_STRUCTURE_FETCH_CAP = 25

# The enrichment cap lives in TargetDiscoveryParams.enrich_top_k so it is
# recorded in the run manifest and can be reported as an explicit gate. The
# module-level constant that used to shadow it is gone: it was retained "for
# older callers" that do not exist, and it silently duplicated the field's
# default, so the two could disagree with nothing to notice.

#: Sentinel for a gene with no UniProt mapping (see _do_discover).
_NO_UNIPROT: str | None = None


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
    topology_client: UniProtTopologyClient | None = None,
    gtex_client: GTExTissueExpression | None = None,
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
    _ensure_reference_data(config)
    surface_bind_client = _resolve_surface_bind_client(surface_bind_client)

    # Persist the effective configuration inside the run. Nothing used to write
    # it, so a finished run — or an exported crate — could not say what produced
    # it, and any CLI override (--backend, --cheap …) was lost entirely.
    config_path = _write_run_config(config, root)

    manifest = new_manifest(name=config.name, config_path=str(config_path))

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
        topology_client=topology_client,
        gtex_client=gtex_client,
        surfy=surfy,
    )
    manifest.append(discover_stage)

    manifest.write(root / "run_manifest.jsonld")
    LOG.info("bindsight discover complete; manifest=%s", root / "run_manifest.jsonld")
    return manifest


# ---------------------------------------------------------------------------
# Stage 0: ensure real reference data (GDC cohort + SURFY surfaceome)
# ---------------------------------------------------------------------------
def _ensure_reference_data(config: RunConfig) -> None:
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


def _write_run_config(config: RunConfig, root: Path) -> Path:
    """Write the effective run configuration to ``<run>/config.yaml``.

    ``io/paths.py`` has always documented this file as part of the run layout,
    and nothing ever produced it. Writing the *effective* config — after CLI
    overrides are applied — is what makes a run self-describing and an exported
    crate reproducible.

    Args:
        config: The resolved run configuration.
        root: The run directory.

    Returns:
        Path to the written config file.
    """
    import yaml

    out = root / "config.yaml"
    payload = config.model_dump(mode="json", by_alias=True)
    out.write_text(
        "# Effective bindsight run configuration, written by the pipeline.\n"
        "# Includes any command-line overrides applied to the source config.\n"
        + yaml.safe_dump(payload, sort_keys=False),
        encoding="utf-8",
    )
    return out


def _resolve_surfy(p: object, surfy: frozenset[str] | None) -> frozenset[str]:
    """Return the SURFY surface set.

    No network access. The full canonical list is vendored with the package, so
    discovery resolves the surfaceome from disk every time.

    This used to try ``populate_surfy_cache()`` on a cache miss. That download
    can no longer succeed — upstream serves an HTML page on one host and a
    Git-LFS pointer on the other — so every fresh install either hard-failed or
    silently degraded to a ten-protein list and surfaced almost nothing. Keeping
    the attempt would only add five retries of latency before the same outcome.

    An explicitly injected set (tests) still wins.
    """
    from bindsight.config import TargetDiscoveryParams

    assert isinstance(p, TargetDiscoveryParams)
    if surfy is not None:
        return surfy
    if p.use_extended_surfaceome:
        # SURFY plus UniProt's curated cell-membrane annotations. SURFY alone
        # cannot see CA9 or STEAP1, and CA9 carries the largest effect measured
        # anywhere in the rediscovery panel.
        resolved = load_surfaceome(extended=True)
        LOG.info("surfaceome: %d accessions (SURFY + UniProt cell membrane)", len(resolved))
        return resolved
    return load_surfy(allow_offline_fallback=p.surfy_allow_offline_fallback)


# ---------------------------------------------------------------------------
# Stage: DEG
# ---------------------------------------------------------------------------
def _deg_cache_key(inputs: list[InputRef], params: dict[str, Any]) -> str:
    """Identify a differential-expression computation by its inputs and parameters.

    Covers the *content* of the counts and design tables, not their paths, so a
    moved or re-downloaded but identical cohort still hits. Any parameter change
    misses, including the worker count, because a run recorded under one
    configuration should not be reported under another.
    """
    import hashlib

    # The tool that produced the table is part of the work, not context around
    # it. Without it an upgraded pydeseq2 hits the old cache and the manifest
    # records the reused bytes under the NEW version -- a completed stage
    # attributing one tool's output to another. The design cache already folds
    # its code identity in for exactly this reason; this one did not.
    from bindsight.validate.protocol import UNRECORDED_VERSION, installed_version

    tool_identity = f"pydeseq2:{installed_version('pydeseq2') or UNRECORDED_VERSION}"
    material = "|".join(
        [
            *(f"{i.role}:{i.sha256}" for i in sorted(inputs, key=lambda x: x.role)),
            json.dumps(params, sort_keys=True, default=str),
            tool_identity,
        ]
    )
    return hashlib.sha256(material.encode()).hexdigest()


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

    # Differential expression is by far the most expensive stage — minutes to hours
    # on a real cohort — and it depends only on the counts, the design and the DEG
    # parameters. Re-running it because something downstream changed wastes that
    # time for an identical answer. The key covers the content of both inputs and
    # every parameter, so a cache hit is only ever the same computation.
    cache_key = _deg_cache_key(inputs, config.params.deg.model_dump())
    key_path = out_path.with_suffix(".cache_key")
    if (
        out_path.exists()
        and out_path.stat().st_size > 0
        and key_path.exists()
        and key_path.read_text(encoding="utf-8").strip() == cache_key
    ):
        LOG.info("DEG cache hit (%s); reusing %s", cache_key[:8], out_path)
        stage.cache_key = cache_key
        stage.cache_status = "hit"
        stage.notes = "reused an existing DEG table with identical inputs and parameters"
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
        return stage

    stage.cache_key = cache_key
    stage.cache_status = "miss"
    try:
        runner = PyDESeq2Runner(config.params.deg)
        metrics = runner.run(counts_p, design_p, out_path)
        key_path.write_text(cache_key, encoding="utf-8")
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
    topology_client: UniProtTopologyClient | None,
    gtex_client: GTExTissueExpression | None,
    surfy: frozenset[str] | None,
) -> StageRecord:
    stage = StageRecord(
        name="discover",
        tool=ToolRef(
            name=f"bindsight/{__version__}",
            version=__version__,
            license="AGPL-3.0-or-later",
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
        params=config.params.target_discovery.model_dump()
        | {
            # Which surfaceome list this run actually resolved. The choice
            # between a user-refreshed cache and the vendored list is made
            # inside load_surfy and was recorded nowhere, so two runs could use
            # different lists -- different eligible denominators, different
            # counterfactual ranks -- with nothing in either manifest saying so.
            "surfaceome_source": surfaceome_source(),
        },
    )

    for _title, _body in DISCOVERY_LIMITATIONS:
        LOG.warning("discovery limitation — %s: %s", _title, _body)

    try:
        candidates_df, epitopes_df, taxonomy_df = _do_discover(
            config=config,
            deg_table_path=deg_table_path,
            open_targets_client=open_targets_client,
            alphafolddb_client=alphafolddb_client,
            surface_bind_client=surface_bind_client,
            topology_client=topology_client,
            gtex_client=gtex_client,
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
            + "; "
            + caveat_summary()
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
    topology_client: UniProtTopologyClient | None,
    gtex_client: GTExTissueExpression | None,
    surfy: frozenset[str] | None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Pure-data discovery logic; returns (candidates_df, epitopes_df, taxonomy_df)."""
    p = config.params.target_discovery
    # The run root, derived the same way the taxonomy path is: the DEG table
    # lives at <run>/deg/results.parquet. Structures are adopted into <run>/
    # structures/ so the run stays portable.
    run_root = deg_table_path.parent.parent

    # 1. Load DEGs and keep significant ones. Antibody targets need tumor
    #    over-expression, so carry the most up-regulated significant genes into
    #    enrichment (bounded — a real cohort has thousands of significant DEGs).
    deg = pd.read_parquet(deg_table_path)
    sig = deg[deg["significant"]].copy()
    n_sig = len(sig)

    # The surfaceome must be resolved before the enrichment cut, because the cut
    # is now spent on surface proteins rather than on the whole genome.
    surfy_set = _resolve_surfy(p, surfy)

    # 1a. Surfaceome pre-filter. Enrichment slots are a scarce resource, and
    # spending them on genes that could never be antibody targets discards most
    # of the surfaceome before it is ever examined. Filtering first is free: the
    # number of Open Targets calls is unchanged, only which genes get them.
    surfaceome_gene_ids: frozenset[str] = frozenset()
    n_before_prefilter = len(sig)
    if p.surfaceome_prefilter and p.require_surfy:
        surfaceome_gene_ids = frozenset(
            gene
            for gene, accession in load_surfaceome_gene_map(
                extended=p.use_extended_surfaceome
            ).items()
            if accession in surfy_set
        )
        if surfaceome_gene_ids:
            sig = sig[sig["gene_id"].astype(str).isin(surfaceome_gene_ids)].copy()
            LOG.info(
                "surfaceome pre-filter: %d significant gene(s) → %d on the surfaceome",
                n_before_prefilter,
                len(sig),
            )
        else:
            # Without the map the pre-filter cannot run, and silently skipping it
            # would change the science without saying so.
            LOG.warning(
                "surfaceome gene map is unavailable; falling back to filtering AFTER "
                "enrichment, which spends the cut on the whole genome"
            )

    # Carry the most *confidently* over-expressed genes into enrichment, ranked
    # by the combined DE score π = log2fc × −log10(padj) rather than raw
    # fold-change — so a highly-significant, abundant antigen with a moderate
    # ratio (e.g. PSMA) is not crowded out by noisy high-fold-change genes.
    sig["pi_score"] = _pi_score(sig)
    sig = sig.sort_values("pi_score", ascending=False).head(p.enrich_top_k)
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

        # [None] is the deliberate sentinel for 'gene mapped to no UniProt
        # accession'; the row is still emitted so the failure taxonomy can
        # record it as no_uniprot rather than dropping it silently.
        candidates_for_gene: list[str | None] = list(uniprot_ids) or [_NO_UNIPROT]
        for uniprot_id in candidates_for_gene:
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
                    # Whether that count is a measurement or a default. Without
                    # this, a gene whose Open Targets lookup errored carries 0
                    # and sails through a filter meant to exclude genes with
                    # known safety events. Silence is not zero.
                    "safety_events_measured": ev is not None,
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
            structure_queried=frozenset(),
            surfaceome_gene_ids=surfaceome_gene_ids,
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
    #
    # An unreachable Open Targets is not a clean bill of health. The count
    # defaults to zero when the lookup returns nothing, so before this a rate
    # limit or a network blip promoted every affected gene to "no known safety
    # events" — the same fail-open the GTEx gate beside it was fixed not to do.
    # When the gate is switched off entirely the count claims nothing either
    # way, so nothing is withheld on its account.
    if not candidates.empty:
        before = len(candidates)
        within = candidates["n_safety_events"] <= p.max_safety_events
        gate_claims = p.use_open_targets and p.open_targets_require_measured
        if gate_claims and "safety_events_measured" in candidates.columns:
            measured = candidates["safety_events_measured"].fillna(False).astype(bool)
            withheld = int((~measured).sum())
            if withheld:
                LOG.warning(
                    "safety gate: %d candidate(s) withheld because Open Targets "
                    "returned no record, so their safety-event count is unknown "
                    "rather than zero",
                    withheld,
                )
            candidates = candidates[within & measured].copy()
        else:
            candidates = candidates[within].copy()
        LOG.info(
            "safety filter (≤%d events): %d → %d", p.max_safety_events, before, len(candidates)
        )

    # 6. Pull AlphaFoldDB structures + tag. Only the strongest candidates carry
    #    forward to design, so we fetch structures for the top ones by |log2fc|
    #    (capped) rather than every surface DE gene — on a real cohort that can
    #    be hundreds, and the rest are never used downstream.
    #
    #    ``structure_queried`` records the accessions whose AlphaFoldDB lookup
    #    actually completed. Everything else — below the cap, or a lookup that
    #    errored — was never assessed, which the taxonomy must not report as
    #    "no model exists".
    structure_queried: set[str] = set()
    if not candidates.empty:
        candidates["pi_score"] = _pi_score(candidates)
        candidates = candidates.sort_values(by="pi_score", ascending=False).reset_index(drop=True)
        n_fetch = max(p.top_n, _STRUCTURE_FETCH_CAP)
        fetch_uniprots = sorted(
            {u for u in candidates.head(n_fetch)["uniprot_id"].dropna().unique() if u}
        )
        # Structures are fetched into the shared cache, then adopted into the
        # run's own structures/ directory and referenced run-relatively. Storing
        # the absolute cache path made every run — and every RO-Crate built from
        # one — valid on exactly one machine.
        struct_paths: dict[str, str] = {}
        for uid in fetch_uniprots:
            try:
                cached = afdb.fetch(uid)
            except Exception as e:
                # A failed lookup is not evidence that no model exists; leaving the
                # accession out of ``structure_queried`` keeps the taxonomy honest.
                LOG.warning("AlphaFoldDB fetch failed for %s: %s", uid, e)
                continue
            structure_queried.add(uid)
            if cached is None:
                continue
            try:
                struct_paths[uid] = adopt_structure(run_root, cached)
            except OSError as e:
                # A copy failure must not lose the structure; fall back to the
                # cache path, which older runs used exclusively anyway.
                LOG.warning("could not adopt structure for %s into the run (%s)", uid, e)
                struct_paths[uid] = str(cached)
        candidates["alphafold_structure_path"] = candidates["uniprot_id"].map(
            lambda u: struct_paths.get(u, "") if u else ""
        )
        candidates["has_alphafold_structure"] = candidates["alphafold_structure_path"] != ""
    else:
        candidates["alphafold_structure_path"] = ""
        candidates["has_alphafold_structure"] = False

    # 6b. Disorder signal: per-model mean pLDDT (AlphaFold confidence, 0-100),
    # read straight from the cached mmCIF B-factor column. Always surfaced; only
    # gates carry-forward when ``min_mean_plddt`` is set. A mostly-disordered /
    # low-confidence model cannot be reliably designed against.
    candidates["mean_plddt"] = candidates["alphafold_structure_path"].map(
        lambda pth: mean_plddt(resolved) if (resolved := resolve_run_path(run_root, pth)) else None
    )
    if p.min_mean_plddt > 0:
        low_conf = (
            candidates["has_alphafold_structure"]
            & candidates["mean_plddt"].notna()
            & (candidates["mean_plddt"] < p.min_mean_plddt)
        )
    else:
        low_conf = pd.Series(False, index=candidates.index)
    candidates["low_confidence_structure"] = low_conf
    # A model whose pLDDT could not be read is not a model that passed. The gate
    # above tests `mean_plddt.notna()`, so an unreadable confidence fell through
    # to the accepting side and an unmeasured structure was carried forward as
    # though it had cleared the bar. Recorded rather than gated, mirroring
    # `normal_tissue_unassessed`: what a reader needs is the difference between
    # a model that passed and one never measured, and dropping the second for an
    # infrastructure reason would be its own error.
    candidates["structure_confidence_unassessed"] = (
        candidates["has_alphafold_structure"]
        & candidates["mean_plddt"].isna()
        & (p.min_mean_plddt > 0)
    )
    if bool(candidates["structure_confidence_unassessed"].any()):
        LOG.info(
            "pLDDT gate: %d candidate(s) carry a structure whose confidence could not "
            "be read; recorded as structure_confidence_unassessed, not as passing",
            int(candidates["structure_confidence_unassessed"].sum()),
        )
    if bool(low_conf.any()):
        # Distinct from no_alphafold_model: the model exists but is too disordered.
        candidates.loc[low_conf, "has_alphafold_structure"] = False
        LOG.info(
            "pLDDT gate: %d candidate(s) below mean pLDDT %.0f -> low_confidence_structure",
            int(low_conf.sum()),
            p.min_mean_plddt,
        )

    # 6c. Membrane topology (extracellular-domain awareness) — opt-in (UniProt).
    # A binder only reaches the extracellular part of a surface protein, so when
    # enabled we annotate each candidate's extracellular ranges (and target the
    # ECD for whole-surface design). Off by default — requires UniProt network.
    topo_map: dict[str, Topology] = {}
    if p.use_uniprot_topology and not candidates.empty:
        topo_client = topology_client or UniProtTopologyClient()
        topo_fetch = sorted(
            {
                u
                for u in candidates.head(max(p.top_n, _STRUCTURE_FETCH_CAP))["uniprot_id"]
                .dropna()
                .unique()
                if u
            }
        )
        for uid in topo_fetch:
            try:
                t = topo_client.fetch(uid)
            except Exception as e:  # network/parse — fall back to whole-surface
                LOG.warning("UniProt topology fetch failed for %s: %s", uid, e)
                t = None
            if t is not None:
                topo_map[uid] = t
        candidates["has_extracellular_domain"] = candidates["uniprot_id"].map(
            lambda u: topo_map[u].has_extracellular if u in topo_map else None
        )
        candidates["extracellular_ranges"] = candidates["uniprot_id"].map(
            lambda u: [list(r) for r in topo_map[u].extracellular_ranges] if u in topo_map else None
        )
        if p.require_extracellular_domain:
            no_ecd = candidates["uniprot_id"].map(
                lambda u: u in topo_map and not topo_map[u].has_extracellular
            )
            candidates["no_extracellular_domain"] = no_ecd
            if bool(no_ecd.any()):
                # Not antibody-accessible — drop from design carry-forward.
                candidates.loc[no_ecd, "has_alphafold_structure"] = False
                LOG.info(
                    "topology gate: %d candidate(s) with no extracellular domain", int(no_ecd.sum())
                )

    # 6d. Normal-tissue safety (GTEx) — opt-in. A binder against a target that is
    # also highly expressed in vital normal tissue risks on-target/off-tumor
    # toxicity. Flag candidates over the vital-tissue TPM threshold and drop them
    # from design carry-forward. Off by default — requires the GTEx download.
    if p.use_gtex_safety and not candidates.empty:
        gtex = gtex_client or GTExTissueExpression()
        # assess() separates a *measured* pass from an absent measurement. Using
        # max_expression() directly conflated the two: a gene GTEx has no entry
        # for returned None, which compared False against the ceiling and so was
        # published as having cleared a safety gate that never ran on it.
        verdicts = {
            str(g): gtex.assess(str(g), p.vital_tissues, p.vital_tissue_max_tpm)
            for g in candidates["gene_id"]
            if g is not None
        }
        candidates["max_vital_tissue_tpm"] = candidates["gene_id"].map(
            lambda g: verdicts[str(g)].max_tpm if g is not None and str(g) in verdicts else None
        )
        candidates["gtex_safety_status"] = candidates["gene_id"].map(
            lambda g: (
                verdicts[str(g)].status if g is not None and str(g) in verdicts else "unassessed"
            )
        )
        tissue_unsafe = candidates["gtex_safety_status"] == "unsafe"
        tissue_unassessed = candidates["gtex_safety_status"] == "unassessed"
        candidates["high_normal_tissue_expression"] = tissue_unsafe
        candidates["normal_tissue_unassessed"] = tissue_unassessed & p.gtex_require_measured
        if bool(tissue_unsafe.any()):
            candidates.loc[tissue_unsafe, "has_alphafold_structure"] = False
            LOG.info(
                "GTEx tissue-safety: %d candidate(s) over %.1f TPM in a vital tissue "
                "-> high_normal_tissue_expression",
                int(tissue_unsafe.sum()),
                p.vital_tissue_max_tpm,
            )
        if bool(tissue_unassessed.any()):
            if p.gtex_require_measured:
                candidates.loc[tissue_unassessed, "has_alphafold_structure"] = False
            LOG.info(
                "GTEx tissue-safety: %d candidate(s) have no GTEx entry -> %s",
                int(tissue_unassessed.sum()),
                "normal_tissue_unassessed (withheld)"
                if p.gtex_require_measured
                else "unassessed (accepted; gtex_require_measured is False)",
            )

    # 7. Rank by the combined DE score π = log2fc × −log10(padj) (Xiao et al.
    #    2014). Higher π = more confidently over-expressed. π is the *only* rank
    #    key, so a published rank is a deterministic function of the statistics:
    #    structure availability is network-dependent (fetched only for a capped
    #    head of the list, and a failed fetch is indistinguishable from a missing
    #    model), so ranking on it let a transient AlphaFoldDB outage reorder the
    #    table. Gene/accession break π ties so equal scores order identically
    #    across runs.
    if "pi_score" not in candidates.columns:
        candidates["pi_score"] = _pi_score(candidates)
    candidates = candidates.sort_values(
        by=["pi_score", "gene_id", "uniprot_id"],
        ascending=[False, True, True],
        kind="stable",
    ).reset_index(drop=True)
    candidates["rank"] = range(1, len(candidates) + 1)
    # Design eligibility is a separate criterion, carried by the
    # has_alphafold_structure column rather than by the rank: only
    # structure-bearing candidates can proceed to design, so the design
    # shortlist takes those first, in rank order.
    design_shortlist = candidates.sort_values(
        by=["has_alphafold_structure", "rank"],
        ascending=[False, True],
        kind="stable",
    ).index[: p.top_n]
    candidates["rank_in_top_n"] = candidates.index.isin(design_shortlist)

    # 8. Build the epitopes table from SURFACE-Bind targetable sites when the
    # data is vendored; otherwise design against the whole surface, recorded
    # honestly in ``epitope_status``.
    epitopes = _build_epitopes(
        candidates[candidates["rank_in_top_n"]],
        surface_bind_client,
        p,
        topology_map=topo_map,
        run_root=run_root,
    )

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
        structure_queried=frozenset(structure_queried),
        surfaceome_gene_ids=surfaceome_gene_ids,
    )
    return candidates, epitopes, taxonomy


# Negative-result taxonomy: the ordered dispositions a DEG gene can land in, from
# "never in contention" to "surfaced". The funnel is exhaustive, so the per-
# disposition counts always sum to the total DEG gene count.
#
# ``uniprot_lookup_failed`` and ``structure_not_queried`` are *not* findings: they
# mark genes whose lookup errored or was never attempted. Only a lookup that ran
# and came back empty earns ``no_uniprot`` / ``no_alphafold_model``, so a network
# outage can never be published as a negative result.
TAXONOMY_DISPOSITIONS: tuple[str, ...] = (
    "not_significant",
    "down_regulated",
    "below_enrichment_cutoff",
    "uniprot_lookup_failed",
    "no_uniprot",
    "not_surfaceome",
    "fails_tractability",
    "fails_safety",
    "safety_unassessed",
    "high_normal_tissue_expression",
    "normal_tissue_unassessed",
    "no_extracellular_domain",
    "structure_not_queried",
    "no_alphafold_model",
    "low_confidence_structure",
    "structure_confidence_unassessed",
    "not_top_n",
    "no_surface_bind_site",
    "surface_bind_lookup_failed",
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
    structure_queried: frozenset[str],
    surfaceome_gene_ids: frozenset[str] = frozenset(),
) -> pd.DataFrame:
    """One disposition per DEG gene explaining why it is / isn't a surfaced candidate.

    Re-derives each gene's fate from the same signals the pipeline used — without
    perturbing the candidate/epitope outputs — so the failure modes (the "negative
    results") become an auditable, first-class artifact. The funnel is exhaustive:
    the per-disposition counts always sum to the total DEG gene count.

    Args:
        deg: The full DEG table; every gene in it gets exactly one row out.
        enriched_gene_ids: Genes carried into Open Targets enrichment.
        enriched_all: Enrichment rows before any filter, one per gene × UniProt.
        candidates: The surviving candidates, ranked.
        epitopes: The epitope table for the design shortlist.
        surfy_set: The resolved SURFY surfaceome.
        p: Target-discovery parameters.
        surface_bind_active: Whether SURFACE-Bind data was actually vendored.
        structure_queried: UniProt accessions whose AlphaFoldDB lookup actually
            ran to completion. Accessions outside this set were never assessed,
            so their genes are reported as ``structure_not_queried`` rather than
            as an absent model.
        surfaceome_gene_ids: Genes on the surfaceome, when the pre-filter ran.
            A significant, up-regulated gene outside this set was dropped before
            the enrichment cut could apply, so it is reported as
            ``not_surfaceome`` rather than blamed on a gate that never saw it.
            Empty when the pre-filter is off, which restores the old behaviour.

    Returns:
        One row per DEG gene with its disposition and the Open Targets status
        that produced it.
    """
    wanted = {m for m in (p.require_tractable_modality or [])}

    # Per-gene "furthest stage reached", collapsed over a gene's UniProt rows.
    reach: dict[str, dict[str, bool]] = {}
    sym_map: dict[str, object] = {}
    ot_status_map: dict[str, str] = {}
    for r in enriched_all.itertuples(index=False):
        gid = str(r.gene_id)
        sym_map.setdefault(gid, getattr(r, "symbol", None))
        ot_status = str(getattr(r, "open_targets_status", "") or "")
        # An errored lookup dominates: it is the reason the gene has no mapping.
        if gid not in ot_status_map or ot_status.startswith("error:"):
            ot_status_map[gid] = ot_status
        uniprot = getattr(r, "uniprot_id", None)
        has_u = bool(uniprot) and pd.notna(uniprot)
        surf = has_u and (not p.require_surfy or is_surface_protein(str(uniprot), surfy=surfy_set))
        mods = {
            m.strip()
            for m in str(getattr(r, "tractable_modalities", "") or "").split(";")
            if m.strip()
        }
        tract = surf and (not wanted or bool(wanted & mods))
        # A gene whose safety count was never measured has not passed the gate;
        # it was never put to it. Old taxonomies carry no such column, and a
        # disabled gate claims nothing, so both default to measured.
        safety_measured = (not (p.use_open_targets and p.open_targets_require_measured)) or bool(
            getattr(r, "safety_events_measured", True)
        )
        safe = (
            tract
            and safety_measured
            and (int(getattr(r, "n_safety_events", 0) or 0) <= p.max_safety_events)
        )
        d = reach.setdefault(
            gid,
            {"u": False, "surf": False, "tract": False, "safe": False, "safety_measured": False},
        )
        d["u"] |= has_u
        d["surf"] |= surf
        d["tract"] |= tract
        d["safety_measured"] |= tract and safety_measured
        d["safe"] |= safe

    cand_gids: set[str] = set()
    struct_gids: set[str] = set()
    queried_gids: set[str] = set()
    topn_gids: set[str] = set()
    low_conf_gids: set[str] = set()
    unassessed_conf_gids: set[str] = set()
    no_ecd_gids: set[str] = set()
    tissue_unsafe_gids: set[str] = set()
    tissue_unassessed_gids: set[str] = set()
    if not candidates.empty:
        cand_gids = {str(g) for g in candidates["gene_id"]}
        struct_gids = {
            str(g) for g in candidates.loc[candidates["has_alphafold_structure"], "gene_id"]
        }
        was_queried = candidates["uniprot_id"].map(
            lambda u: isinstance(u, str) and u in structure_queried
        )
        queried_gids = {str(g) for g in candidates.loc[was_queried, "gene_id"]}
        topn_gids = {str(g) for g in candidates.loc[candidates["rank_in_top_n"], "gene_id"]}
        if "low_confidence_structure" in candidates.columns:
            low_conf_gids = {
                str(g) for g in candidates.loc[candidates["low_confidence_structure"], "gene_id"]
            }
        if "structure_confidence_unassessed" in candidates.columns:
            unassessed_conf_gids = {
                str(g)
                for g in candidates.loc[candidates["structure_confidence_unassessed"], "gene_id"]
            }
        if "no_extracellular_domain" in candidates.columns:
            no_ecd_gids = {
                str(g) for g in candidates.loc[candidates["no_extracellular_domain"], "gene_id"]
            }
        if "high_normal_tissue_expression" in candidates.columns:
            tissue_unsafe_gids = {
                str(g)
                for g in candidates.loc[candidates["high_normal_tissue_expression"], "gene_id"]
            }
        if "normal_tissue_unassessed" in candidates.columns:
            tissue_unassessed_gids = {
                str(g) for g in candidates.loc[candidates["normal_tissue_unassessed"], "gene_id"]
            }
    site_gids: set[str] = set()
    # Genes whose site lookup errored. They are not genes without a site: the
    # lookup said nothing about them at all, and the taxonomy derived
    # "no_surface_bind_site" purely from the absence of a row, so an outage
    # became a biological finding about every protein it touched.
    lookup_failed_gids: set[str] = set()
    if surface_bind_active and not epitopes.empty and "epitope_status" in epitopes.columns:
        site_gids = {
            str(g)
            for g in epitopes.loc[epitopes["epitope_status"] == "surface_bind_site", "gene_id"]
        }
        lookup_failed_gids = {
            str(g)
            for g in epitopes.loc[
                epitopes["epitope_status"] == "surface_bind_lookup_failed", "gene_id"
            ]
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
            if gid in lookup_failed_gids:
                disp = "surface_bind_lookup_failed"
            elif surface_bind_active and gid not in site_gids:
                disp = "no_surface_bind_site"
            else:
                disp = "surfaced"
        elif gid in cand_gids:
            # passed the filters but can't proceed to design: over-expressed in vital
            # tissue, not antibody-accessible (no ECD), low-confidence model, no
            # structure, or out of top-N.
            if gid in tissue_unsafe_gids:
                disp = "high_normal_tissue_expression"
            elif gid in tissue_unassessed_gids:
                disp = "normal_tissue_unassessed"
            elif gid in no_ecd_gids:
                disp = "no_extracellular_domain"
            elif gid in unassessed_conf_gids:
                disp = "structure_confidence_unassessed"
            elif gid in low_conf_gids:
                disp = "low_confidence_structure"
            elif gid not in struct_gids:
                # Past the fetch cap, or the lookup errored: nothing was measured.
                disp = "no_alphafold_model" if gid in queried_gids else "structure_not_queried"
            else:
                disp = "not_top_n"
        elif gid in enriched_gene_ids:
            d = reach.get(
                gid,
                {
                    "u": False,
                    "surf": False,
                    "tract": False,
                    "safe": False,
                    "safety_measured": False,
                },
            )
            if not d["u"]:
                disp = (
                    "uniprot_lookup_failed"
                    if ot_status_map.get(gid, "").startswith("error:")
                    else "no_uniprot"
                )
            elif p.require_surfy and not d["surf"]:
                disp = "not_surfaceome"
            elif wanted and not d["tract"]:
                disp = "fails_tractability"
            elif not d["safety_measured"]:
                # Withheld for want of an answer, not for failing one. Reporting
                # this as fails_safety would publish a network outage as a
                # negative result about the gene.
                disp = "safety_unassessed"
            else:
                disp = "fails_safety"
        elif not significant:
            disp = "not_significant"
        elif (log2fc or 0.0) <= 0.0:
            disp = "down_regulated"
        elif surfaceome_gene_ids and gid not in surfaceome_gene_ids:
            # Dropped by the surfaceome pre-filter, before the enrichment cut
            # could apply. Recording it as below_enrichment_cutoff would blame a
            # gate that never saw this gene.
            disp = "not_surfaceome"
        else:
            disp = "below_enrichment_cutoff"
        rows.append(
            {
                "gene_id": gid,
                "symbol": sym_map.get(gid),
                "log2fc": log2fc,
                "padj": padj,
                "disposition": disp,
                # Kept alongside the disposition so a reader can tell a real
                # negative from a lookup that never ran; it is dropped from the
                # candidates table for genes that never became candidates.
                "open_targets_status": ot_status_map.get(gid),
            }
        )
    return pd.DataFrame(
        rows,
        columns=["gene_id", "symbol", "log2fc", "padj", "disposition", "open_targets_status"],
    )


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
            "mean_plddt",
            "low_confidence_structure",
            "gtex_safety_status",
            "normal_tissue_unassessed",
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
    top: pd.DataFrame,
    client: SurfaceBindClient | None,
    p: TargetDiscoveryParams,
    *,
    topology_map: dict[str, Topology] | None = None,
    run_root: Path | None = None,
) -> pd.DataFrame:
    """Build the epitopes table for the top-N candidates.

    With a SURFACE-Bind client whose data is vendored, each candidate gets one
    row per qualifying targetable site (real residues → focused RFdiffusion
    design). The ``epitope_status`` is honest about what happened:

    - ``surface_bind_site``           — a real vendored site (focused design);
    - ``no_surface_bind_site``        — data present, none for this protein;
    - ``surface_bind_lookup_failed``  — the client raised; nothing was learned
      about this protein, and that is not the same as learning it has no site;
    - ``surface_bind_not_configured`` — no SURFACE-Bind data vendored.

    ``require_surface_bind_site`` only bites when data is actually vendored: with
    a client, ``True`` carries *only* candidates that have ≥1 qualifying site,
    while ``False`` carries every top-N candidate (whole-surface where no site
    exists). Without vendored data there is nothing to require, so every
    candidate falls back to whole-surface design.

    Two columns describe the region a designer must restrict itself to:

    - ``design_ranges``       — list of ``[start, end]`` residue ranges, 1-based
      and inclusive, in UniProt numbering: the extracellular parts of the
      receptor. ``None`` when no topology was resolved, in which case the
      designer has no evidence to narrow the target and must say so rather than
      assume the whole chain is reachable;
    - ``design_range_source`` — ``uniprot_topology`` when the ranges came from a
      resolved UniProt topology, ``not_available`` when none was.

    A binder only ever reaches the extracellular part of a surface protein, so a
    consumer that ignores ``design_ranges`` designs against the transmembrane
    helix and cytoplasmic tail too.
    """
    tmap = topology_map or {}

    def _epitope_plddt(stored: Any, residues: list[int]) -> float | None:
        """Mean pLDDT over a region, resolving the run-relative path first.

        ``adopt_structure`` stores structure paths relative to the run root, so
        handing the raw value to ``region_plddt`` silently yields ``None`` for
        every row. The sibling ``mean_plddt`` column resolves it; this must too.
        """
        resolved = resolve_run_path(run_root, stored) if run_root is not None else stored
        return region_plddt(resolved, residues) if resolved else None

    rows: list[dict[str, Any]] = []
    for _, row in top.iterrows():
        uni = row["uniprot_id"]
        topo = tmap.get(uni) if isinstance(uni, str) else None
        design_ranges = (
            [[int(start), int(end)] for start, end in topo.extracellular_ranges] if topo else None
        )
        base = {
            "gene_id": row["gene_id"],
            "symbol": row["symbol"],
            "uniprot_id": uni,
            "structure_path": row["alphafold_structure_path"],
            "design_ranges": design_ranges,
            "design_range_source": "uniprot_topology" if topo else "not_available",
        }
        sites: list[Any] = []
        lookup_failed = False
        if client is not None and isinstance(uni, str) and uni:
            try:
                sites = [
                    s
                    for s in client.sites(uni)
                    if s.score is None or s.score >= p.min_surface_bind_score
                ]
            except Exception as e:  # malformed vendored data must not abort discovery
                LOG.warning("SURFACE-Bind lookup failed for %s: %s", uni, e)
                lookup_failed = True
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
                        "mean_epitope_plddt": _epitope_plddt(
                            row["alphafold_structure_path"], list(s.residues)
                        ),
                        "fraction_extracellular": (
                            topo.fraction_extracellular(list(s.residues)) if topo else None
                        ),
                    }
                )
        elif lookup_failed or client is None or not p.require_surface_bind_site:
            # whole-surface fallback (honest status); omitted only when data is
            # vendored AND a site is required but none exists for this protein.
            # A lookup that errored is not a biological negative.
            # ``no_surface_bind_site`` is documented as "data present, none for
            # this protein" — a finding about the protein. An exception in the
            # client said nothing about the protein at all, and reporting the
            # two identically turned an outage into evidence. The project's own
            # outcomes module states the rule: "a lookup that errored or never
            # ran is not a scientific negative."
            if lookup_failed:
                status = "surface_bind_lookup_failed"
            elif client is not None:
                status = "no_surface_bind_site"
            else:
                status = "surface_bind_not_configured"
            rows.append(
                {
                    **base,
                    "site_id": None,
                    "chain": "A",
                    "residues": [],
                    "score": None,
                    "seed_pdb_path": None,
                    "epitope_status": status,
                    "mean_epitope_plddt": _epitope_plddt(row["alphafold_structure_path"], []),
                    "fraction_extracellular": None,
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
            "design_ranges",
            "design_range_source",
            "site_id",
            "chain",
            "residues",
            "score",
            "seed_pdb_path",
            "epitope_status",
            "mean_epitope_plddt",
            "fraction_extracellular",
        ]
    )

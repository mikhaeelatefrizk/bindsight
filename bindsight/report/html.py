# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Self-contained HTML report renderer.

Reads a finished bindsight run directory (``deg/results.parquet``,
``targets/candidates.parquet``, ``epitopes/epitopes.parquet``,
``run_manifest.jsonld``) and emits one ``report.html`` you can email to a
collaborator or attach to a paper.

Design choices:

- **No Quarto / Jupyter dependency.** Pure Python with stdlib, jinja2, and
  matplotlib (which is already in the report extras). The output is one
  genuinely self-contained HTML file — CSS embedded, volcano plot embedded as
  a base64 PNG, and no external requests at all, so it survives being emailed
  or opened offline -- including the predicted complexes, drawn in 3-D by the
  same viewer the web interface uses. That used to be excluded on the grounds
  that "a structure viewer needs a script from a CDN", which was never true
  here: 3Dmol.js is vendored into the package. The real constraint is size, and
  it is handled as a budget rather than an exclusion -- see
  ``_STRUCTURE_BUDGET_BYTES``.
- **Looks like a paper, not a dashboard.** Sections, tables, captions,
  citations to the upstream tools — readable as a methods + results pair.
- **Provenance front and center.** The manifest table shows every stage's
  tool, version, license, and SHA-256 inputs/outputs.
"""

from __future__ import annotations

import base64
import io
import json
import logging
from collections.abc import Iterable, Mapping
from pathlib import Path, PurePosixPath
from typing import Any

import pandas as pd
from jinja2 import Environment, FileSystemLoader, StrictUndefined

from bindsight.pipelines.caveats import DISCOVERY_LIMITATIONS
from bindsight.report.format import ABSENT, fmt_p  # noqa: F401

LOG = logging.getLogger(__name__)

_TEMPLATES_DIR = Path(__file__).parent / "templates"


def render_run(
    run_dir: Path | str,
    out_path: Path | str | None = None,
    *,
    include_binders: bool = False,
    embed_structures: bool = True,
) -> Path:
    """Render a finished run as a single self-contained HTML file.

    Args:
        run_dir: directory produced by ``bindsight discover``.
        out_path: destination file. Defaults to ``<run_dir>/report.html``.
        include_binders: also embed each ranked binder's designed sequence.
            The sequences live in the design tarballs rather than the ranking
            table, so reading them costs a pass over those archives.
        embed_structures: embed the predicted complexes and the 3-D viewer,
            within ``_STRUCTURE_BUDGET_BYTES``. Off makes a much smaller file
            that shows the numbers without the structures behind them.

    Returns:
        Path to the rendered HTML.
    """
    run_dir = Path(run_dir)
    out_path = Path(out_path) if out_path else (run_dir / "report.html")

    deg_df = _maybe_read_parquet(run_dir / "deg" / "results.parquet")
    candidates_df = _maybe_read_parquet(run_dir / "targets" / "candidates.parquet")
    epitopes_df = _maybe_read_parquet(run_dir / "epitopes" / "epitopes.parquet")
    taxonomy_df = _maybe_read_parquet(run_dir / "taxonomy" / "failure_taxonomy.parquet")
    ranking_df = _maybe_read_parquet(run_dir / "rank" / "ranking.parquet")
    manifest = _maybe_read_jsonld(run_dir / "run_manifest.jsonld")

    deg_fdr, deg_log2fc = _deg_thresholds(manifest)
    volcano_b64 = (
        _render_volcano(deg_df, fdr_threshold=deg_fdr, log2fc_threshold=deg_log2fc)
        if deg_df is not None and len(deg_df)
        else ""
    )

    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        undefined=StrictUndefined,
        autoescape=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template("report.html.j2")
    # The shared design system first, then the report's own layer. One
    # stylesheet for both surfaces is the point: a reader who has seen the
    # served interface should recognise this file, and a rule enforced in one
    # place should not be absent from the other.
    _design_system = Path(__file__).resolve().parent / "web" / "static" / "bindsight.css"
    css = (
        _design_system.read_text(encoding="utf-8")
        + "\n"
        + (_TEMPLATES_DIR / "report.css").read_text(encoding="utf-8")
    )

    # Best-first, so a budget that cannot hold every complex holds the ones a
    # reader opens the report to see.
    ranked_ids = (
        [str(v) for v in ranking_df["binder_id"].tolist()]
        if ranking_df is not None and "binder_id" in ranking_df.columns
        else []
    )
    structures: dict[str, str] = {}
    structures_omitted = 0
    if embed_structures and ranked_ids:
        # Passed rather than defaulted: a default argument binds at import
        # time, so the end-to-end behaviour of a full budget could not be
        # exercised without monkeypatching the function itself.
        structures, structures_omitted = _binder_structures(
            run_dir, ranked_ids, _STRUCTURE_BUDGET_BYTES
        )

    viewer_js = ""
    viewer_lib = ""
    if structures:
        _static = Path(__file__).resolve().parent / "web" / "static"
        viewer_js = (_static / "binder_viewer.js").read_text(encoding="utf-8")
        viewer_lib = (_static / "vendor" / "3Dmol-min.js").read_text(encoding="utf-8")

    html = template.render(
        # Escaped so a structure can never close the <script> that carries
        # it. mmCIF has no reason to contain the sequence, which is exactly
        # when an assumption like that stops being checked.
        structures_json=json.dumps(structures).replace("<", "\\u003c"),
        structure_ids=list(structures),
        structures_omitted=structures_omitted,
        viewer_js=viewer_js,
        viewer_lib=viewer_lib,
        run_name=manifest.get("name") if manifest else run_dir.name,
        run_id=manifest.get("run_id", "") if manifest else "",
        created_at=manifest.get("created_at", "") if manifest else "",
        css=css,
        volcano_b64=volcano_b64,
        deg_fdr=deg_fdr,
        deg_log2fc=deg_log2fc,
        n_deg=len(deg_df) if deg_df is not None else 0,
        n_significant=(
            int(deg_df["significant"].sum())
            if deg_df is not None and "significant" in deg_df.columns
            else 0
        ),
        candidates_table=_df_to_records(candidates_df, _CANDIDATE_DISPLAY_COLS, head=20),
        epitopes_table=_df_to_records(epitopes_df, _EPITOPE_DISPLAY_COLS, head=20),
        # The run's counts, not the display tables'. The KPI read
        # ``candidates_table|length``, which is capped at 20, so every run with
        # more than twenty candidates published "20" as its candidate count.
        n_candidates=len(candidates_df) if candidates_df is not None else 0,
        # "could not be read" and "read, and empty" are different findings, and
        # the template said the second for both.
        candidates_unreadable=candidates_df is None,
        n_epitopes=len(epitopes_df) if epitopes_df is not None else 0,
        binders_table=_binders_table(ranking_df, run_dir, include_sequences=include_binders),
        n_binders=len(ranking_df) if ranking_df is not None else 0,
        include_binders=include_binders,
        taxonomy_counts=_disposition_counts(taxonomy_df),
        n_taxonomy=len(taxonomy_df) if taxonomy_df is not None else 0,
        manifest=manifest,
        stages=manifest.get("stages", []) if manifest else [],
        failed_stages=_failed_stages(manifest),
        limitations=[{"title": t, "body": b} for t, b in DISCOVERY_LIMITATIONS],
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8", newline="\n")
    LOG.info("wrote %s", out_path)
    return out_path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
_BINDER_DISPLAY_COLS = [
    "rank",
    "binder_id",
    "symbol",
    "target_uniprot",
    "iptm",
    "pae_interaction",
    "score",
    "passes_thresholds",
]


#: How many bytes of mmCIF a report may carry. A complex is ~150 kB and the
#: vendored viewer another ~525 kB, against a renderer whose whole purpose is a
#: file that survives being emailed. Structures are embedded best-first until
#: this is reached, and the report says how many it left out -- a report that
#: silently showed three of twenty would be the defect this project keeps
#: removing, wearing a size limit as an excuse.
_STRUCTURE_BUDGET_BYTES = 4 * 1024 * 1024


def _binder_structures(
    run_dir: Path, order: list[str], budget: int = _STRUCTURE_BUDGET_BYTES
) -> tuple[dict[str, str], int]:
    """Predicted complexes for ``order``, best-first, within a byte budget.

    Reads the per-target design archives, the same place ``_binder_sequences``
    reads from, because a validated complex is an output of the design stage
    rather than of the ranking table.

    Args:
        run_dir: the finished run.
        order: binder ids, best-ranked first.
        budget: hard ceiling on the embedded mmCIF, in bytes. Never exceeded,
            not even by the best-ranked structure -- a report too large to
            send is the failure this budget exists to prevent. A structure
            that does not fit is skipped, not treated as a stopping point.

    Returns:
        The embedded structures, best-ranked first among those that fit, and
        how many ranked binders have a complex in the archives that was left
        out. The second number counts only structures that really are in
        ``design/_targets/``, because that is what the report says about them;
        a ranked binder the design stage produced no complex for is not in the
        tally, since it is not there to be found.
    """
    import tarfile

    found: dict[str, str] = {}
    targets_dir = run_dir / "design" / "_targets"
    if not targets_dir.is_dir():
        return {}, 0

    for archive in sorted(targets_dir.glob("*.tar.gz")):
        try:
            with tarfile.open(archive, encoding="utf-8") as tf:
                for member in tf.getmembers():
                    name = PurePosixPath(member.name)
                    if name.suffix != ".cif" or not member.isfile():
                        continue
                    handle = tf.extractfile(member)
                    if handle is None:
                        continue
                    text = handle.read().decode("utf-8", errors="replace")
                    if text.strip():
                        # <id>_model_0.cif, and anything else keyed by its stem.
                        found[name.stem.removesuffix("_model_0")] = text
        except (OSError, tarfile.TarError) as e:  # a damaged archive is not fatal
            LOG.warning("could not read binder structures from %s (%s)", archive, e)

    embedded: dict[str, str] = {}
    spent = 0
    for binder_id in order:
        structure = found.get(binder_id)
        if structure is None:
            continue
        cost = len(structure.encode("utf-8"))
        if spent + cost > budget:
            # Skip this one and keep going. Two defects lived in the line this
            # replaced, ``if spent + cost > budget and embedded: break``.
            #
            # ``and embedded`` made the documented ceiling a floor: the first
            # structure was embedded whatever its size, so one oversized
            # complex produced a report larger than the budget it claims to
            # respect -- and "up to _STRUCTURE_BUDGET_BYTES" was false in the
            # one case the budget exists for.
            #
            # ``break`` charged every lower-ranked structure for that one. A
            # 5 KiB complex was dropped because a 50 KiB complex outranked it,
            # even with room to spare, so the report showed less than the
            # budget allowed and the reader lost a structure for no reason.
            continue
        embedded[binder_id] = structure
        spent += cost
    return embedded, max(0, len([b for b in order if b in found]) - len(embedded))


def _binder_sequences(run_dir: Path) -> dict[str, str]:
    """Designed sequence per binder id, read from the per-target design archives.

    The ranking table carries every metric and no sequence, because the sequence
    is an output of the design stage rather than of validation. A reader who
    wants to order a peptide needs it, so it is pulled from the archives on
    request rather than being absent from the report entirely.
    """
    import tarfile

    sequences: dict[str, str] = {}
    targets_dir = run_dir / "design" / "_targets"
    if not targets_dir.is_dir():
        return sequences
    for archive in sorted(targets_dir.glob("*.tar.gz")):
        try:
            with tarfile.open(archive, encoding="utf-8") as tf:
                for member in tf.getmembers():
                    name = PurePosixPath(member.name)
                    if name.suffix != ".fasta" or not member.isfile():
                        continue
                    handle = tf.extractfile(member)
                    if handle is None:
                        continue
                    body = handle.read().decode("utf-8", errors="replace")
                    seq = "".join(
                        line.strip()
                        for line in body.splitlines()
                        if line.strip() and not line.startswith(">")
                    )
                    if seq:
                        sequences[name.stem] = seq
        except (OSError, tarfile.TarError) as e:  # a damaged archive is not fatal
            LOG.warning("could not read binder sequences from %s (%s)", archive, e)
    return sequences


def _binders_table(
    ranking: pd.DataFrame | None,
    run_dir: Path,
    *,
    include_sequences: bool = False,
    head: int = 40,
) -> list[dict[str, Any]]:
    """The ranked binders, which are the run's actual output.

    The report rendered the discovery half and stopped: a run that designed
    forty binders, validated and ranked them produced a paper-style HTML in
    which none of them appeared. ``--include-binders`` was accepted, documented
    and recorded in the manifest, and never reached this module at all.
    """
    rows = _df_to_records(ranking, _BINDER_DISPLAY_COLS, head=head)
    if not rows or not include_sequences:
        return rows
    sequences = _binder_sequences(run_dir)
    for row in rows:
        row["sequence"] = sequences.get(str(row.get("binder_id", "")), "")
    return rows


_CANDIDATE_DISPLAY_COLS = [
    "rank",
    "symbol",
    "uniprot_id",
    "log2fc",
    "padj",
    "tractable_modalities",
    "n_safety_events",
    "max_vital_tissue_tpm",
    "has_alphafold_structure",
    "mean_plddt",
    "rank_in_top_n",
]
_EPITOPE_DISPLAY_COLS = [
    "symbol",
    "uniprot_id",
    "structure_path",
    "site_id",
    "epitope_status",
    "mean_epitope_plddt",
    "fraction_extracellular",
]


# Funnel order for the negative-result taxonomy (display only; the canonical list
# lives in bindsight.pipelines.discover.TAXONOMY_DISPOSITIONS — duplicated here so the
# report renders without importing the heavy discovery module).
#
# The copy had drifted by three: uniprot_lookup_failed, normal_tissue_unassessed
# and structure_not_queried were all missing, which are precisely the
# dispositions that separate "not measured" from "measured and rejected". The
# taxonomy is documented as exhaustive, so a funnel omitting them did not sum to
# the gene count it claimed to. tests/test_report_html.py fails if the two lists
# diverge again.
_DISPOSITION_ORDER = (
    "not_significant",
    "significance_unassessed",
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


def _failed_stages(manifest: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Return ``{name, error}`` for every stage the manifest records as failed.

    A crashed run leaves the same empty tables behind as a run that genuinely
    surfaced nothing. Only the manifest separates them, so the report reads it
    and refuses to offer "loosen the thresholds" advice for a pipeline that
    never got as far as applying them.

    Args:
        manifest: Parsed ``run_manifest.jsonld`` body, or ``None``.

    Returns:
        The failed stages in manifest order; empty when nothing failed.
    """
    stages = (manifest or {}).get("stages") or []
    return [
        {"name": str(s.get("name") or "?"), "error": s.get("error")}
        for s in stages
        if isinstance(s, dict) and s.get("status") == "failed"
    ]


def _disposition_counts(df: pd.DataFrame | None) -> list[dict[str, Any]]:
    """Per-disposition counts for the report, in funnel order (deepest drop → surfaced)."""
    if df is None or "disposition" not in df.columns or len(df) == 0:
        return []
    vc = df["disposition"].value_counts().to_dict()
    total = sum(vc.values()) or 1
    order = {d: i for i, d in enumerate(_DISPOSITION_ORDER)}
    items = sorted(vc.items(), key=lambda kv: order.get(kv[0], 999))
    return [{"disposition": k, "count": int(v), "pct": f"{100 * v / total:.0f}%"} for k, v in items]


def _maybe_read_parquet(path: Path) -> pd.DataFrame | None:
    """Read a Parquet file if it exists and is non-empty; else None."""
    if not path.exists() or path.stat().st_size == 0:
        return None
    try:
        return pd.read_parquet(path)
    except Exception as e:
        LOG.warning("failed to read %s: %s", path, e)
        return None


def _maybe_read_jsonld(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        body: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        body.pop("@context", None)
        return body
    except Exception as e:
        LOG.warning("failed to read %s: %s", path, e)
        return None


#: Columns whose zero is a floor, not a measurement.
_P_VALUE_COLS = frozenset({"padj", "pvalue", "p_value", "padj_adjusted", "fdr"})


def _fmt_cell(value: Any) -> str:
    """A float for a table cell, or empty when there is nothing behind it."""
    if value is None or (isinstance(value, float) and value != value):
        return ""
    if not pd.notna(value):
        return ""
    return f"{float(value):.3g}"


def _df_to_records(
    df: pd.DataFrame | None, cols: list[str], head: int = 20
) -> list[dict[str, Any]]:
    """Return up to ``head`` rows of ``df`` as a list of dicts (only ``cols``)."""
    if df is None or len(df) == 0:
        return []
    present_cols = [c for c in cols if c in df.columns]
    sub = df[present_cols].head(head).copy()
    # The same rules the served interface applies. `f"{v:.3g}"` printed CA9's
    # padj -- literally 0.0 in the artifact, below floating-point resolution --
    # as "0", which is not a p-value, in the one row a reader looks at first.
    for c in sub.select_dtypes(include="float").columns:
        rule = fmt_p if c in _P_VALUE_COLS else _fmt_cell
        sub[c] = sub[c].apply(rule)
    records: list[dict[str, Any]] = sub.to_dict(orient="records")
    return records


#: The conventional defaults, used only when a run did not record what it used.
#: They match :class:`bindsight.config` so a default run is labelled correctly;
#: they are never silently substituted for a run that chose something else.
_DEFAULT_FDR = 0.05

#: Points the volcano annotates, chosen by |log2FC| x -log10(padj). Labelling
#: every significant gene produced an unreadable figure on real cohorts, and
#: an unreadable figure communicates less than an unlabelled one.
_MAX_VOLCANO_LABELS = 20
_DEFAULT_LOG2FC = 1.0


def _deg_thresholds(manifest: Mapping[str, Any] | None) -> tuple[float | None, float | None]:
    """The FDR and |log2FC| cutoffs the ``deg`` stage ran with, if recorded.

    The results parquet carries a ``significant`` column but not the numbers
    behind it, so the plot used to draw its guide lines at the library defaults
    whatever the run had configured -- putting dashed lines through the middle of
    the red points for any run that chose something else. The manifest does
    record them, per stage; this reads them from there.
    """
    if not manifest:
        return (None, None)
    for stage in manifest.get("stages", []) or []:
        params = stage.get("params") or {}
        if "fdr_threshold" in params or "log2fc_threshold" in params:
            fdr = params.get("fdr_threshold")
            lfc = params.get("log2fc_threshold")
            return (
                float(fdr) if fdr is not None else None,
                float(lfc) if lfc is not None else None,
            )
    return (None, None)


def _significance_basis(
    columns: Iterable[str], fdr_threshold: float | None
) -> tuple[str, float | None]:
    """How the plot decides which points are significant.

    Returns ``(basis, cutoff)`` where basis is one of:

    * ``"column"`` -- the analysis' own ``significant`` column; authoritative,
      since it already applied both cutoffs.
    * ``"padj"`` -- no column, but the run recorded its FDR cutoff.
    * ``"assumed"`` -- neither; the conventional 0.05 is used and the report
      says so rather than presenting an assumption as the run's own choice.
    """
    if "significant" in set(columns):
        return ("column", None)
    if fdr_threshold is not None:
        return ("padj", fdr_threshold)
    return ("assumed", _DEFAULT_FDR)


def _render_volcano(
    deg_df: pd.DataFrame,
    *,
    fdr_threshold: float | None = None,
    log2fc_threshold: float | None = None,
) -> str:
    """Render a volcano plot as a base64-encoded PNG embedded in the HTML.

    ``fdr_threshold`` and ``log2fc_threshold`` are the cutoffs the run recorded.
    A guide line is drawn only for a cutoff that is known: an unlabelled dashed
    line at a value the run did not use is worse than no line at all.
    """
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return ""  # matplotlib not installed; skip plot

    import numpy as np

    fig, ax = plt.subplots(figsize=(7, 5), dpi=120)
    log2fc = deg_df["log2fc"].astype(float)
    padj = deg_df["padj"].astype(float).fillna(1.0)
    nlp = -np.log10(padj.clip(lower=1e-300))
    basis, cutoff = _significance_basis(deg_df.columns, fdr_threshold)
    # ``cutoff is None`` happens only on the column branch, where the analysis
    # already applied both cutoffs. Testing for it narrows the type without a
    # cast and says the same thing the branch means.
    if basis == "column" or cutoff is None:
        sig = deg_df["significant"].astype(bool)
        sig_label = "significant"
    else:
        sig = padj < cutoff
        sig_label = (
            f"significant (padj < {cutoff:g})"
            if basis == "padj"
            else f"significant (padj < {cutoff:g}, assumed)"
        )

    ax.scatter(log2fc[~sig], nlp[~sig], s=18, alpha=0.45, c="#888", label="ns")
    ax.scatter(log2fc[sig], nlp[sig], s=22, alpha=0.85, c="#d62728", label=sig_label)
    # Only the strongest few. Labelling every significant gene put ~4,400
    # overlapping annotations on a real run, which renders as a black bar across
    # the figure and identifies nothing.
    if "symbol" in deg_df.columns:
        labelled = deg_df[sig].copy()
        if not labelled.empty:
            labelled["_weight"] = labelled["log2fc"].abs() * nlp[sig]
            labelled = labelled.sort_values("_weight", ascending=False).head(_MAX_VOLCANO_LABELS)
        for _, row in labelled.iterrows():
            label = str(row.get("symbol") or "")[:20]
            if not label:
                continue
            ax.annotate(
                label,
                (row["log2fc"], -np.log10(max(row["padj"], 1e-300))),
                fontsize=7,
                alpha=0.75,
                xytext=(3, 3),
                textcoords="offset points",
            )
    # A guide line only where the run told us where the line is.
    if fdr_threshold is not None:
        ax.axhline(
            -np.log10(max(float(fdr_threshold), 1e-300)),
            color="grey",
            linestyle="--",
            linewidth=0.8,
            alpha=0.6,
            label=f"padj = {float(fdr_threshold):g}",
        )
    if log2fc_threshold is not None:
        for i, x in enumerate((float(log2fc_threshold), -float(log2fc_threshold))):
            ax.axvline(
                x,
                color="grey",
                linestyle="--",
                linewidth=0.8,
                alpha=0.6,
                label=f"|log2FC| = {abs(float(log2fc_threshold)):g}" if i == 0 else None,
            )
    ax.set_xlabel("log2 fold-change (tumor vs. normal)")
    ax.set_ylabel("-log10(padj)")
    ax.set_title("Differential expression — volcano")
    ax.legend(loc="best", fontsize=8)
    ax.grid(alpha=0.2)
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode()

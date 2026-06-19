"""Self-contained HTML report renderer.

Reads a finished bindsight run directory (``deg/results.parquet``,
``targets/candidates.parquet``, ``epitopes/epitopes.parquet``,
``run_manifest.jsonld``) and emits one ``report.html`` you can email to a
collaborator or attach to a paper.

Design choices:

- **No Quarto / Jupyter dependency.** Pure Python with stdlib, jinja2, and
  matplotlib (which is already in the report extras). The output is one
  self-contained HTML file (CSS embedded, plot embedded as base64 PNG, NGL
  viewer pulled from a CDN).
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
from pathlib import Path

import pandas as pd
from jinja2 import Environment, FileSystemLoader, StrictUndefined

LOG = logging.getLogger(__name__)

_TEMPLATES_DIR = Path(__file__).parent / "templates"


def render_run(run_dir: Path | str, out_path: Path | str | None = None) -> Path:
    """Render a finished run as a single self-contained HTML file.

    Args:
        run_dir: directory produced by ``bindsight discover``.
        out_path: destination file. Defaults to ``<run_dir>/report.html``.

    Returns:
        Path to the rendered HTML.
    """
    run_dir = Path(run_dir)
    out_path = Path(out_path) if out_path else (run_dir / "report.html")

    deg_df = _maybe_read_parquet(run_dir / "deg" / "results.parquet")
    candidates_df = _maybe_read_parquet(run_dir / "targets" / "candidates.parquet")
    epitopes_df = _maybe_read_parquet(run_dir / "epitopes" / "epitopes.parquet")
    taxonomy_df = _maybe_read_parquet(run_dir / "taxonomy" / "failure_taxonomy.parquet")
    manifest = _maybe_read_jsonld(run_dir / "run_manifest.jsonld")

    volcano_b64 = _render_volcano(deg_df) if deg_df is not None and len(deg_df) else ""

    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        undefined=StrictUndefined,
        autoescape=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template("report.html.j2")
    css = (_TEMPLATES_DIR / "report.css").read_text(encoding="utf-8")

    html = template.render(
        run_name=manifest.get("name") if manifest else run_dir.name,
        run_id=manifest.get("run_id", "") if manifest else "",
        created_at=manifest.get("created_at", "") if manifest else "",
        css=css,
        volcano_b64=volcano_b64,
        n_deg=len(deg_df) if deg_df is not None else 0,
        n_significant=(
            int(deg_df["significant"].sum())
            if deg_df is not None and "significant" in deg_df.columns
            else 0
        ),
        candidates_table=_df_to_records(candidates_df, _CANDIDATE_DISPLAY_COLS, head=20),
        epitopes_table=_df_to_records(epitopes_df, _EPITOPE_DISPLAY_COLS, head=20),
        taxonomy_counts=_disposition_counts(taxonomy_df),
        n_taxonomy=len(taxonomy_df) if taxonomy_df is not None else 0,
        manifest=manifest,
        stages=manifest.get("stages", []) if manifest else [],
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    LOG.info("wrote %s", out_path)
    return out_path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
_CANDIDATE_DISPLAY_COLS = [
    "rank",
    "symbol",
    "uniprot_id",
    "log2fc",
    "padj",
    "tractable_modalities",
    "n_safety_events",
    "has_alphafold_structure",
    "rank_in_top_n",
]
_EPITOPE_DISPLAY_COLS = [
    "symbol",
    "uniprot_id",
    "structure_path",
    "site_id",
    "epitope_status",
]


# Funnel order for the negative-result taxonomy (display only; the canonical list
# lives in bindsight.pipelines.discover.TAXONOMY_DISPOSITIONS — duplicated here so the
# report renders without importing the heavy discovery module).
_DISPOSITION_ORDER = (
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


def _disposition_counts(df: pd.DataFrame | None) -> list[dict]:
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


def _maybe_read_jsonld(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
        body.pop("@context", None)
        return body
    except Exception as e:
        LOG.warning("failed to read %s: %s", path, e)
        return None


def _df_to_records(df: pd.DataFrame | None, cols: list[str], head: int = 20) -> list[dict]:
    """Return up to ``head`` rows of ``df`` as a list of dicts (only ``cols``)."""
    if df is None or len(df) == 0:
        return []
    present_cols = [c for c in cols if c in df.columns]
    sub = df[present_cols].head(head).copy()
    # Format floats so the report stays readable; pandas prints ugly otherwise.
    for c in sub.select_dtypes(include="float").columns:
        sub[c] = sub[c].apply(lambda v: f"{v:.3g}" if pd.notna(v) else "")
    return sub.to_dict(orient="records")


def _render_volcano(deg_df: pd.DataFrame) -> str:
    """Render a volcano plot as a base64-encoded PNG embedded in the HTML."""
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
    sig = deg_df["significant"].astype(bool) if "significant" in deg_df.columns else (padj < 0.05)

    ax.scatter(log2fc[~sig], nlp[~sig], s=18, alpha=0.45, c="#888", label="ns")
    ax.scatter(log2fc[sig], nlp[sig], s=22, alpha=0.85, c="#d62728", label="significant")
    if "gene_id" in deg_df.columns:
        for _, row in deg_df[sig].iterrows():
            label = str(row.get("symbol") or row.get("gene_id"))[:20]
            ax.annotate(
                label,
                (row["log2fc"], -np.log10(max(row["padj"], 1e-300))),
                fontsize=7,
                alpha=0.75,
                xytext=(3, 3),
                textcoords="offset points",
            )
    ax.axhline(-np.log10(0.05), color="grey", linestyle="--", linewidth=0.8, alpha=0.6)
    ax.axvline(1.0, color="grey", linestyle="--", linewidth=0.8, alpha=0.6)
    ax.axvline(-1.0, color="grey", linestyle="--", linewidth=0.8, alpha=0.6)
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

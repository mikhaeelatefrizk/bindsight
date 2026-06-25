# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Rediscovery-benchmark scoring + report rendering.

Given one or more finished run directories (each with
``targets/candidates.parquet`` from ``bindsight discover``) and a known-antigen
table (``benchmarks/known.tsv``), compute, per run:

- the rank of each known antigen in the candidate shortlist (by UniProt),
- whether it was found at all, and whether it landed in the top-k,
- recall@k aggregated across the known set.

Then render a self-contained HTML report comparing the runs side by side. The
math is intentionally simple and transparent so the benchmark is defensible:
recall@k is just ``#{known antigens with rank ≤ k} / #{known antigens}``.
"""

from __future__ import annotations

import html
import logging
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

LOG = logging.getLogger(__name__)

DEFAULT_KS: tuple[int, ...] = (5, 10, 20)


@dataclass(frozen=True)
class KnownAntigen:
    """One held-out known antigen we expect a rediscovery run to surface."""

    symbol: str
    uniprot: str
    tumor_type: str = ""
    disease: str = ""
    expected_direction: str = "up"


@dataclass(frozen=True)
class _Hit:
    """A known antigen's match in a run's candidate shortlist."""

    rank: int
    log2fc: float | None
    padj: float | None
    symbol: str | None


@dataclass
class RunScore:
    """Per-run rediscovery score over the known-antigen set."""

    run_name: str
    run_dir: str
    per_antigen: list[dict[str, object]] = field(default_factory=list)  # one per known antigen
    recall_at: dict[int, float] = field(default_factory=dict)
    n_known: int = 0
    n_found: int = 0
    n_candidates: int = 0


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------
def load_known_antigens(path: Path | str) -> list[KnownAntigen]:
    """Load ``known.tsv`` into a list of :class:`KnownAntigen`.

    Requires at least ``symbol`` and ``uniprot`` columns; ``tumor_type``,
    ``disease`` and ``expected_direction`` are optional.
    """
    df = pd.read_csv(path, sep="\t", dtype=str).fillna("")
    missing = {"symbol", "uniprot"} - set(df.columns)
    if missing:
        raise ValueError(f"{path}: known-antigen table missing columns {sorted(missing)}")
    return [
        KnownAntigen(
            symbol=row["symbol"],
            uniprot=row["uniprot"],
            tumor_type=row.get("tumor_type", ""),
            disease=row.get("disease", ""),
            expected_direction=row.get("expected_direction", "up"),
        )
        for _, row in df.iterrows()
    ]


def _load_candidates(run_dir: Path) -> pd.DataFrame | None:
    path = run_dir / "targets" / "candidates.parquet"
    if not path.exists() or path.stat().st_size == 0:
        LOG.warning("no candidates.parquet in %s", run_dir)
        return None
    try:
        return pd.read_parquet(path)
    except Exception as e:
        LOG.warning("failed to read %s: %s", path, e)
        return None


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------
def score_run(
    run_dir: Path | str,
    known: list[KnownAntigen],
    *,
    ks: tuple[int, ...] = DEFAULT_KS,
    run_name: str | None = None,
) -> RunScore:
    """Score one run directory against the known-antigen set.

    A known antigen is matched to a candidate row by UniProt accession
    (``candidates.uniprot_id``). Its ``rank`` is taken from the candidate table
    (the discover stage's 1-based rank). If the antigen never appears in the
    candidates it is recorded as not-found (rank ``None``).
    """
    run_dir = Path(run_dir)
    name = run_name or run_dir.name
    cands = _load_candidates(run_dir)

    # Build a uniprot -> _Hit lookup from the candidates.
    rank_by_uniprot: dict[str, _Hit] = {}
    n_candidates = 0
    if cands is not None and "uniprot_id" in cands.columns:
        n_candidates = int(cands["uniprot_id"].notna().sum())
        ranked = cands.dropna(subset=["uniprot_id"]).copy()
        # Prefer an explicit 'rank' column; otherwise rank by row order.
        if "rank" not in ranked.columns:
            ranked = ranked.reset_index(drop=True)
            ranked["rank"] = range(1, len(ranked) + 1)
        for _, r in ranked.iterrows():
            uid = str(r["uniprot_id"])
            if uid not in rank_by_uniprot:  # keep best (first) rank per uniprot
                sym = r.get("symbol")
                rank_by_uniprot[uid] = _Hit(
                    rank=int(r["rank"]),
                    log2fc=_f(r.get("log2fc")),
                    padj=_f(r.get("padj")),
                    symbol=str(sym) if pd.notna(sym) else None,
                )

    per_antigen: list[dict[str, object]] = []
    n_found = 0
    for ka in known:
        hit = rank_by_uniprot.get(ka.uniprot)
        found = hit is not None
        n_found += int(found)
        per_antigen.append(
            {
                "symbol": ka.symbol,
                "uniprot": ka.uniprot,
                "tumor_type": ka.tumor_type,
                "found": found,
                "rank": hit.rank if hit else None,
                "log2fc": hit.log2fc if hit else None,
                "padj": hit.padj if hit else None,
                **{f"in_top_{k}": (hit is not None and hit.rank <= k) for k in ks},
            }
        )

    recall_at = {
        k: (
            sum(
                1
                for ka in known
                if (h := rank_by_uniprot.get(ka.uniprot)) is not None and h.rank <= k
            )
            / len(known)
        )
        if known
        else 0.0
        for k in ks
    }

    return RunScore(
        run_name=name,
        run_dir=str(run_dir),
        per_antigen=per_antigen,
        recall_at=recall_at,
        n_known=len(known),
        n_found=n_found,
        n_candidates=n_candidates,
    )


def _f(v: object) -> float | None:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    try:
        return float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------
def render_benchmark_html(
    scores: list[RunScore],
    *,
    ks: tuple[int, ...] = DEFAULT_KS,
    known_source: str = "",
) -> str:
    """Render the benchmark scores as a self-contained HTML string."""
    e = html.escape

    def _cell(v: object) -> str:
        if v is None:
            return "<td class='miss'>—</td>"
        if isinstance(v, bool):
            return f"<td class='{'hit' if v else 'miss'}'>{'✓' if v else '·'}</td>"
        if isinstance(v, float):
            return f"<td>{v:.3g}</td>"
        return f"<td>{e(str(v))}</td>"

    # Summary table: one row per run, recall@k columns.
    summary_rows = ""
    for s in scores:
        cells = "".join(f"<td>{s.recall_at[k]:.0%}</td>" for k in ks)
        summary_rows += (
            f"<tr><td class='name'>{e(s.run_name)}</td>"
            f"<td>{s.n_found}/{s.n_known}</td><td>{s.n_candidates}</td>{cells}</tr>"
        )
    recall_headers = "".join(f"<th>recall@{k}</th>" for k in ks)

    # Per-run detail tables.
    detail_blocks = ""
    topk_headers = "".join(f"<th>top{k}</th>" for k in ks)

    def _rank_key(a: dict[str, object]) -> tuple[bool, int]:
        r = a["rank"]
        return (r is None, r if isinstance(r, int) else 0)

    for s in scores:
        rows = ""
        for a in sorted(s.per_antigen, key=_rank_key):
            topk = "".join(_cell(a[f"in_top_{k}"]) for k in ks)
            rows += (
                f"<tr><td class='name'>{e(str(a['symbol']))}</td>"
                f"<td>{e(str(a['uniprot']))}</td><td>{e(str(a['tumor_type']))}</td>"
                f"{_cell(a['found'])}{_cell(a['rank'])}{_cell(a['log2fc'])}{topk}</tr>"
            )
        detail_blocks += (
            f"<h3>{e(s.run_name)}</h3>"
            f"<div class='sub'>{e(s.run_dir)}</div>"
            "<table><thead><tr><th>antigen</th><th>uniprot</th><th>tumor</th>"
            f"<th>found</th><th>rank</th><th>log2fc</th>{topk_headers}</tr></thead>"
            f"<tbody>{rows}</tbody></table>"
        )

    return _HTML_TEMPLATE.format(
        recall_headers=recall_headers,
        summary_rows=summary_rows,
        detail_blocks=detail_blocks,
        known_source=e(known_source),
        n_runs=len(scores),
    )


def run_benchmark(
    run_dirs: list[Path | str],
    known_antigens_path: Path | str,
    *,
    out_html: Path | str,
    ks: tuple[int, ...] = DEFAULT_KS,
) -> tuple[Path, list[RunScore]]:
    """Score every run against the known set and write the HTML report.

    Returns ``(out_html_path, scores)``.
    """
    known = load_known_antigens(known_antigens_path)
    scores = [score_run(rd, known, ks=ks) for rd in run_dirs]
    out = Path(out_html)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        render_benchmark_html(scores, ks=ks, known_source=str(known_antigens_path)),
        encoding="utf-8",
    )
    LOG.info("wrote %s (%d runs, %d known antigens)", out, len(scores), len(known))
    return out, scores


_HTML_TEMPLATE = """\
<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>bindsight rediscovery benchmark</title>
<style>
 body {{ font-family: -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif;
        margin: 2rem auto; max-width: 980px; color: #1a1a1a; line-height: 1.45; }}
 h1 {{ font-size: 1.5rem; }} h3 {{ margin-top: 1.6rem; }}
 .sub {{ color: #666; font-size: .8rem; margin-bottom: .3rem; font-family: monospace; }}
 table {{ border-collapse: collapse; width: 100%; margin: .5rem 0 1.2rem; font-size: .9rem; }}
 th, td {{ border: 1px solid #ddd; padding: .35rem .55rem; text-align: center; }}
 th {{ background: #f4f4f6; }}
 td.name {{ text-align: left; font-weight: 600; }}
 td.hit {{ color: #137333; font-weight: 700; }}
 td.miss {{ color: #b00020; }}
 .foot {{ color: #777; font-size: .8rem; margin-top: 2rem; }}
</style></head><body>
<h1>bindsight — rediscovery benchmark</h1>
<p>How well each run resurfaces the held-out known antigens. Known set:
   <code>{known_source}</code> · {n_runs} run(s).
   <strong>recall@k</strong> = fraction of known antigens ranked in the top-k.</p>
<h2>Summary</h2>
<table><thead><tr><th>run</th><th>found</th><th>candidates</th>{recall_headers}</tr></thead>
<tbody>{summary_rows}</tbody></table>
<h2>Per-antigen detail</h2>
{detail_blocks}
<p class="foot">Generated by <code>bindsight benchmark</code>. Known antigens and
literature-validated binders: see <code>benchmarks/PROVENANCE.md</code>.</p>
</body></html>
"""

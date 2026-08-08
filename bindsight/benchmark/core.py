# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Rediscovery-benchmark scoring + report rendering.

Given one or more finished run directories (each with
``targets/candidates.parquet`` from ``bindsight discover``) and a known-antigen
table (``benchmarks/known.tsv``), compute, per run:

- the rank of each known antigen in the candidate shortlist (by UniProt),
- whether it was found at all, and whether it landed in the top-k,
- recall@k aggregated across the run's *on-indication* known antigens.

Then render a self-contained HTML report comparing the runs side by side. The
math is intentionally simple and transparent so the benchmark is defensible:
recall@k is ``#{on-indication known antigens with rank ≤ k} /
#{on-indication known antigens}``.

Rediscovery is indication-scoped: a run of a colorectal cohort surfacing a
breast antigen has not rediscovered anything, so a known antigen is credited
only when its own ``tumor_type`` is the run's indication. Known antigens from
other indications that do appear in a shortlist are reported separately as
cross-indication cross-reactivity and never enter recall@k. A run whose
indication is not supplied is scored over the whole known set and labelled as
such, because the gate cannot be applied without it.
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
    """Per-run rediscovery score over the known-antigen set.

    ``per_antigen`` holds one row per *on-indication* known antigen (the
    recall@k denominator); ``cross_indication`` holds the known antigens from
    other indications that happen to appear in the shortlist, which are
    cross-reactivity observations rather than rediscoveries. ``recall_basis``
    records which of the two regimes produced ``recall_at``:
    ``"on_indication"``, ``"indication_unknown"`` (no indication supplied for
    the run) or ``"no_known_antigen_for_indication"`` (nothing to score, so
    ``recall_at`` is left empty rather than reported as zero).
    """

    run_name: str
    run_dir: str
    tumor_type: str | None = None
    recall_basis: str = "indication_unknown"
    per_antigen: list[dict[str, object]] = field(default_factory=list)  # on-indication antigens
    cross_indication: list[dict[str, object]] = field(default_factory=list)
    recall_at: dict[int, float] = field(default_factory=dict)
    n_known: int = 0
    n_on_indication: int = 0
    n_found: int = 0
    n_cross_indication: int = 0
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
def _matches_indication(antigen_tumor_type: str, run_tumor_type: str) -> bool:
    """True when a known antigen's own indication is the run's indication."""
    return antigen_tumor_type.strip().casefold() == run_tumor_type.strip().casefold()


def score_run(
    run_dir: Path | str,
    known: list[KnownAntigen],
    *,
    ks: tuple[int, ...] = DEFAULT_KS,
    run_name: str | None = None,
    tumor_type: str | None = None,
) -> RunScore:
    """Score one run directory against the known-antigen set.

    A known antigen is matched to a candidate row by UniProt accession
    (``candidates.uniprot_id``). Its ``rank`` is taken from the candidate table
    (the discover stage's 1-based rank). If the antigen never appears in the
    candidates it is recorded as not-found (rank ``None``).

    Protein identity alone is not rediscovery: an antigen is credited (and
    enters recall@k) only when its ``tumor_type`` is also the run's indication.
    Matches from other indications are collected in
    :attr:`RunScore.cross_indication` instead.

    Args:
        run_dir: a finished run directory containing ``targets/candidates.parquet``.
        known: the known-antigen set to score against.
        ks: top-k cutoffs for recall@k.
        run_name: display name for the run (defaults to the directory name).
        tumor_type: the run's indication, using the same vocabulary as the
            known table's ``tumor_type`` column (e.g. ``"BRCA"``). When
            ``None`` the indication gate cannot be applied; every known antigen
            is then scored and ``recall_basis`` says so.
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

    on_indication: list[KnownAntigen] = []
    off_indication: list[KnownAntigen] = []
    for ka in known:
        on = tumor_type is None or _matches_indication(ka.tumor_type, tumor_type)
        (on_indication if on else off_indication).append(ka)

    def _row(ka: KnownAntigen, hit: _Hit | None, on: bool | None) -> dict[str, object]:
        return {
            "symbol": ka.symbol,
            "uniprot": ka.uniprot,
            "tumor_type": ka.tumor_type,
            "on_indication": on,
            "found": hit is not None,
            "rank": hit.rank if hit else None,
            "log2fc": hit.log2fc if hit else None,
            "padj": hit.padj if hit else None,
            **{f"in_top_{k}": (hit is not None and hit.rank <= k) for k in ks},
        }

    per_antigen = [
        _row(ka, rank_by_uniprot.get(ka.uniprot), None if tumor_type is None else True)
        for ka in on_indication
    ]
    n_found = sum(1 for a in per_antigen if a["found"])
    # Off-indication antigens are only worth reporting when they were surfaced;
    # a miss in another cancer type is neither a rediscovery nor a failure.
    cross_indication = [
        _row(ka, hit, False)
        for ka in off_indication
        if (hit := rank_by_uniprot.get(ka.uniprot)) is not None
    ]

    recall_at: dict[int, float] = {}
    if on_indication:
        for k in ks:
            hits = sum(1 for a in per_antigen if a[f"in_top_{k}"])
            recall_at[k] = hits / len(on_indication)

    if tumor_type is None:
        basis = "indication_unknown"
    elif on_indication:
        basis = "on_indication"
    else:
        basis = "no_known_antigen_for_indication"

    return RunScore(
        run_name=name,
        run_dir=str(run_dir),
        tumor_type=tumor_type,
        recall_basis=basis,
        per_antigen=per_antigen,
        cross_indication=cross_indication,
        recall_at=recall_at,
        n_known=len(known),
        n_on_indication=len(on_indication),
        n_found=n_found,
        n_cross_indication=len(cross_indication),
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

    # Summary table: one row per run, recall@k columns over the on-indication set.
    summary_rows = ""
    for s in scores:
        cells = "".join(
            f"<td>{s.recall_at[k]:.0%}</td>" if k in s.recall_at else "<td class='miss'>n/a</td>"
            for k in ks
        )
        indication = e(s.tumor_type) if s.tumor_type else "<span class='miss'>unknown</span>"
        summary_rows += (
            f"<tr><td class='name'>{e(s.run_name)}</td><td>{indication}</td>"
            f"<td>{s.n_found}/{s.n_on_indication}</td><td>{s.n_cross_indication}</td>"
            f"<td>{s.n_candidates}</td>{cells}</tr>"
        )
    recall_headers = "".join(f"<th>recall@{k}</th>" for k in ks)

    # Per-run detail tables.
    detail_blocks = ""
    topk_headers = "".join(f"<th>top{k}</th>" for k in ks)
    antigen_headers = (
        "<tr><th>antigen</th><th>uniprot</th><th>tumor</th>"
        f"<th>found</th><th>rank</th><th>log2fc</th>{topk_headers}</tr>"
    )

    def _rank_key(a: dict[str, object]) -> tuple[bool, int]:
        r = a["rank"]
        return (r is None, r if isinstance(r, int) else 0)

    def _antigen_table(antigens: list[dict[str, object]]) -> str:
        rows = ""
        for a in sorted(antigens, key=_rank_key):
            topk = "".join(_cell(a[f"in_top_{k}"]) for k in ks)
            rows += (
                f"<tr><td class='name'>{e(str(a['symbol']))}</td>"
                f"<td>{e(str(a['uniprot']))}</td><td>{e(str(a['tumor_type']))}</td>"
                f"{_cell(a['found'])}{_cell(a['rank'])}{_cell(a['log2fc'])}{topk}</tr>"
            )
        return f"<table><thead>{antigen_headers}</thead><tbody>{rows}</tbody></table>"

    for s in scores:
        detail_blocks += f"<h3>{e(s.run_name)}</h3><div class='sub'>{e(s.run_dir)}</div>"
        if s.recall_basis == "on_indication":
            detail_blocks += (
                f"<div class='scope'>Scored against the {e(str(s.tumor_type))} known "
                "antigen(s) — the only ones this run can rediscover.</div>"
            )
        elif s.recall_basis == "indication_unknown":
            detail_blocks += (
                "<div class='scope warn'>Indication not supplied for this run, so no "
                "indication gate could be applied: the whole known set is scored and a "
                "match may belong to another cancer type.</div>"
            )
        else:
            detail_blocks += (
                f"<div class='scope warn'>No known antigen is annotated for indication "
                f"{e(str(s.tumor_type))}, so recall@k is not defined for this run.</div>"
            )
        detail_blocks += _antigen_table(s.per_antigen)
        if s.cross_indication:
            detail_blocks += (
                "<h4>Cross-indication cross-reactivity — NOT rediscovery</h4>"
                "<div class='scope warn'>Known antigens of <em>other</em> cancer types that "
                "this run surfaced. They are excluded from recall@k above.</div>"
                + _antigen_table(s.cross_indication)
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
    tumor_types: list[str | None] | None = None,
) -> tuple[Path, list[RunScore]]:
    """Score every run against the known set and write the HTML report.

    Args:
        run_dirs: finished run directories to score.
        known_antigens_path: the known-antigen table (``benchmarks/known.tsv``).
        out_html: where to write the report.
        ks: top-k cutoffs for recall@k.
        tumor_types: each run's indication, positionally aligned with
            ``run_dirs``. Runs without one are scored over the whole known set
            and reported as indication-unknown, since rediscovery cannot be
            told apart from cross-indication cross-reactivity without it.

    Returns ``(out_html_path, scores)``.

    Raises:
        ValueError: if ``tumor_types`` is given with a different length than
            ``run_dirs``.
    """
    if tumor_types is not None and len(tumor_types) != len(run_dirs):
        raise ValueError(
            f"tumor_types has {len(tumor_types)} entries for {len(run_dirs)} run dir(s)"
        )
    known = load_known_antigens(known_antigens_path)
    indications = tumor_types if tumor_types is not None else [None] * len(run_dirs)
    scores = [
        score_run(rd, known, ks=ks, tumor_type=tt)
        for rd, tt in zip(run_dirs, indications, strict=True)
    ]
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
 h1 {{ font-size: 1.5rem; }} h3 {{ margin-top: 1.6rem; }} h4 {{ margin: 1.1rem 0 .2rem; }}
 .sub {{ color: #666; font-size: .8rem; margin-bottom: .3rem; font-family: monospace; }}
 .scope {{ color: #555; font-size: .82rem; margin-bottom: .25rem; }}
 .scope.warn {{ color: #8a4b00; }}
 table {{ border-collapse: collapse; width: 100%; margin: .5rem 0 1.2rem; font-size: .9rem; }}
 th, td {{ border: 1px solid #ddd; padding: .35rem .55rem; text-align: center; }}
 th {{ background: #f4f4f6; }}
 td.name {{ text-align: left; font-weight: 600; }}
 td.hit {{ color: #137333; font-weight: 700; }}
 td.miss {{ color: #b00020; }}
 .foot {{ color: #777; font-size: .8rem; margin-top: 2rem; }}
</style></head><body>
<h1>bindsight — rediscovery benchmark</h1>
<p>How well each run resurfaces the held-out known antigens of <em>its own</em>
   indication. Known set: <code>{known_source}</code> · {n_runs} run(s).
   <strong>recall@k</strong> = fraction of the run's on-indication known antigens
   ranked in the top-k. A known antigen of another cancer type is never counted as
   a rediscovery; where a run surfaces one it is listed under
   <em>cross-indication cross-reactivity</em>. Runs with no declared indication are
   marked <em>unknown</em> and are scored over the whole known set, which cannot
   distinguish rediscovery from cross-reactivity.</p>
<h2>Summary</h2>
<table><thead><tr><th>run</th><th>indication</th><th>on-indication found</th>
<th>cross-indication</th><th>candidates</th>{recall_headers}</tr></thead>
<tbody>{summary_rows}</tbody></table>
<h2>Per-antigen detail</h2>
{detail_blocks}
<p class="foot">Generated by <code>bindsight benchmark</code>. Known antigens and
literature-validated binders: see <code>benchmarks/PROVENANCE.md</code>.</p>
</body></html>
"""

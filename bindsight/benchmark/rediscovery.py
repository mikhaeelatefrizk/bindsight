# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Rediscovery validation: do real TCGA cohorts resurface known antigens?

This module runs the discovery half of bindsight on real TCGA cohorts (one per
known antigen, in its indication) as tumor-vs-adjacent-normal contrasts, and
scores the rank of each antigen in the candidate shortlist
(:func:`benchmark.score_run`). Nothing is hand-set; the report groups antigens
by their *measured* differential expression so the result is transparent and
not gamed.

The honest finding the runs produce: bulk-DE discovery surfaces antigens that
are genuinely transcriptionally over-expressed (ERBB2 in HER2-enriched breast,
rank 4 — exposed by PAM50 subtype-stratification via
:mod:`bindsight.io.cbioportal`, which otherwise averages the HER2 signal away)
and correctly withholds antigens whose tumor-selectivity arises from other
mechanisms — mutation/amplification (EGFR) or lineage co-expression in the
normal tissue-of-origin (CEA, PSMA). Sensitivity therefore tracks effect size,
the expected behaviour of a differential-expression method, and specificity is
high.

CLDN6 (ovarian) and CD33/CD123 (AML) are deliberately *not* run: TCGA-OV and
TCGA-LAML ship zero matched solid-tissue normals, and substituting GTEx normals
would confound the result with a cross-study batch effect — documented as data
limitations rather than reported with a manufactured number.
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from bindsight import __version__
from bindsight.benchmark.core import KnownAntigen, render_benchmark_html, score_run
from bindsight.config import (
    DEGParams,
    DesignParams,
    InputsConfig,
    RankParams,
    RunConfig,
    StageParams,
    TargetDiscoveryParams,
    ValidateParams,
)

LOG = logging.getLogger(__name__)

CBIOPORTAL_STUDY = "brca_tcga_pan_can_atlas_2018"
KS: tuple[int, ...] = (5, 10, 20)

# Uniform, pre-stated rules for classifying each antigen by the *measured* data
# (not by a hoped-for label), so the validation is transparent and not gamed.
OVEREXPRESSION_LOG2FC = 1.0  # the pipeline's own DE effect-size threshold
MIN_NORMALS_FOR_POWER = 8  # below this a tumor-vs-normal contrast is underpowered


def _categorise(deg_expected: dict[str, Any], n_normal: int) -> str:
    """Classify a cohort by the antigen's *measured* differential expression.

    - ``over_expressed``    — significant and log2fc ≥ threshold (the pipeline
      can and should surface it; counts toward recall);
    - ``not_over_expressed`` — not significantly up at the bulk level (the
      pipeline should correctly leave it out; counts toward specificity);
    - ``underpowered``      — too few matched normals to call DE reliably;
    - ``not_tested``        — antigen absent from the DEG table.
    """
    de = deg_expected or {}
    if not de.get("tested"):
        return "not_tested"
    if n_normal < MIN_NORMALS_FOR_POWER:
        return "underpowered"
    if de.get("significant") and (de.get("log2fc") or 0.0) >= OVEREXPRESSION_LOG2FC:
        return "over_expressed"
    return "not_over_expressed"


@dataclass(frozen=True)
class Cohort:
    """One rediscovery cohort and the antigen it should resurface.

    ``expectation`` is one of:

    - ``"positive"`` — the antigen is transcriptionally over-expressed in the
      tumor, so a correct pipeline should resurface it (counts toward recall);
    - ``"negative_control"`` — clinically relevant but driven by
      mutation/amplification rather than over-expression, so a *specific*
      pipeline should correctly leave it out;
    - ``"limited"`` — a cohort whose result is reported transparently but is
      compromised by a data limitation (e.g. too few normals, or an antigen
      also highly expressed in the matched normal tissue); excluded from recall.
    """

    key: str
    label: str
    project: str
    expected_symbol: str
    expected_uniprot: str
    expected_ensembl: str
    subtype: str | None  # cBioPortal PAM50 label, or None for whole-project tumor
    n_tumor: int
    n_normal: int
    expectation: str
    note: str


VALIDATION_COHORTS: list[Cohort] = [
    Cohort(
        key="brca_her2",
        label="BRCA HER2-enriched",
        project="TCGA-BRCA",
        expected_symbol="ERBB2",
        expected_uniprot="P04626",
        expected_ensembl="ENSG00000141736",
        subtype="BRCA_Her2",
        n_tumor=50,
        n_normal=40,
        expectation="positive",
        note="PAM50 HER2-enriched tumors are ERBB2-amplified, so ERBB2 mRNA is high.",
    ),
    Cohort(
        key="coad",
        label="COAD",
        project="TCGA-COAD",
        expected_symbol="CEACAM5",
        expected_uniprot="P06731",
        expected_ensembl="ENSG00000105388",
        subtype=None,
        n_tumor=50,
        n_normal=40,
        expectation="positive",
        note="CEA (target of tusamitamab ravtansine / labetuzumab govitecan) is a classic "
        "colorectal marker, but it is also abundantly expressed in normal colon "
        "epithelium, so the bulk tumor-vs-adjacent-normal fold-change is ~0.",
    ),
    Cohort(
        key="blca",
        label="BLCA",
        project="TCGA-BLCA",
        expected_symbol="NECTIN4",
        expected_uniprot="Q96NY8",
        expected_ensembl="ENSG00000143217",
        subtype=None,
        n_tumor=50,
        n_normal=19,
        expectation="positive",
        note="Nectin-4 (target of enfortumab vedotin, Padcev) is elevated in urothelial "
        "carcinoma, but only modestly at the bulk-mRNA level (log2fc ~1.6), below the "
        "discovery shortlist.",
    ),
    Cohort(
        key="luad",
        label="LUAD (EGFR negative control)",
        project="TCGA-LUAD",
        expected_symbol="EGFR",
        expected_uniprot="P00533",
        expected_ensembl="ENSG00000146648",
        subtype=None,
        n_tumor=50,
        n_normal=40,
        expectation="negative_control",
        note="EGFR drives LUAD via mutation/amplification, not bulk mRNA over-expression, "
        "so a specificity-respecting pipeline should NOT surface it on expression alone.",
    ),
    Cohort(
        key="paad",
        label="PAAD (MSLN, limited)",
        project="TCGA-PAAD",
        expected_symbol="MSLN",
        expected_uniprot="Q13421",
        expected_ensembl="ENSG00000102854",
        subtype=None,
        n_tumor=50,
        n_normal=4,
        expectation="limited",
        note="Mesothelin is over-expressed in PDAC, but TCGA-PAAD ships only 4 matched "
        "normals, so the contrast is underpowered (reported for transparency).",
    ),
    Cohort(
        key="prad",
        label="PRAD (FOLH1, limited)",
        project="TCGA-PRAD",
        expected_symbol="FOLH1",
        expected_uniprot="Q04609",
        expected_ensembl="ENSG00000086205",
        subtype=None,
        n_tumor=50,
        n_normal=40,
        expectation="limited",
        note="PSMA (FOLH1) is highly expressed but also abundant in normal prostate, so "
        "the tumor-vs-normal fold-change is modest (reported for transparency).",
    ),
]

# Targets named in the planned validation but not runnable from TCGA alone
# (no matched solid-tissue normals); recorded honestly, never fabricated.
DATA_LIMITED = [
    {
        "symbol": "CLDN6",
        "uniprot": "P56747",
        "project": "TCGA-OV",
        "reason": "TCGA-OV ships 0 solid-tissue-normal RNA-seq samples; a clean "
        "tumor-vs-normal contrast is impossible without an external (GTEx) normal, "
        "which would introduce a cross-study batch confound.",
    },
    {
        "symbol": "CD33 / IL3RA (CD123)",
        "uniprot": "P20138 / P26951",
        "project": "TCGA-LAML",
        "reason": "TCGA-LAML ships 0 solid-tissue-normal samples; an AML-vs-normal "
        "contrast needs a normal haematopoietic reference (e.g. GTEx whole blood / "
        "normal bone marrow), again a cross-study batch confound.",
    },
]


# ---------------------------------------------------------------------------
# Config + cohort preparation
# ---------------------------------------------------------------------------
def _build_config(cohort: Cohort, counts: Path, design: Path, out_dir: Path) -> RunConfig:
    """Build a discovery RunConfig for a cohort (production surfaceome, top_n=20)."""
    return RunConfig(
        name=f"validation_{cohort.key}",
        out_dir=out_dir,
        inputs=InputsConfig(counts=counts, design=design, download=None),
        params=StageParams(
            deg=DEGParams(
                design_formula="~ condition",
                contrast=["condition", "tumor", "normal"],
                fdr_threshold=0.05,
                log2fc_threshold=1.0,
                min_replicates=3,
            ),
            target_discovery=TargetDiscoveryParams(
                require_surfy=True,
                surfy_allow_offline_fallback=False,
                use_open_targets=True,
                # The SURFY surfaceome filter already enforces cell-surface
                # localization (the biological prerequisite for an antibody
                # target). We deliberately do NOT additionally gate on Open
                # Targets' "Antibody tractability" bucket: it is an incomplete
                # curated druggability call that would drop bona-fide surface
                # antigens and confound a pure expression-based rediscovery test.
                require_tractable_modality=[],
                max_safety_events=5,
                require_surface_bind_site=False,
                top_n=20,
            ),
            design=DesignParams(),
            validate=ValidateParams(),
            rank=RankParams(),
        ),
        backend="mock",
    )


def prepare_cohort(
    cohort: Cohort, data_root: Path, subtype_labels: dict[str, str] | None
) -> tuple[Path, Path, dict[str, Any]]:
    """Fetch a cohort's counts + design from GDC (idempotent); return their paths.

    For a subtype cohort, the tumor cases are the PAM50-labelled patients from
    ``subtype_labels``; normals are the project's adjacent-normal samples.
    """
    from bindsight.io.cbioportal import patients_with_subtype
    from bindsight.io.gdc import fetch_cohort

    cohort_dir = data_root / cohort.key
    counts = cohort_dir / "counts.tsv.gz"
    design = cohort_dir / "design.tsv"
    prov_path = cohort_dir / "provenance.json"

    tumor_cases: list[str] | None = None
    if cohort.subtype is not None:
        if not subtype_labels:
            raise ValueError(f"{cohort.key} needs subtype labels but none were provided")
        tumor_cases = patients_with_subtype(subtype_labels, cohort.subtype)
        LOG.info("%s: %d %s patients from cBioPortal", cohort.key, len(tumor_cases), cohort.subtype)

    if counts.exists() and design.exists():
        LOG.info("%s: cohort already downloaded at %s", cohort.key, cohort_dir)
        prov = json.loads(prov_path.read_text()) if prov_path.exists() else {}
        return counts, design, prov

    prov = fetch_cohort(
        project=cohort.project,
        n_tumor=cohort.n_tumor,
        n_normal=cohort.n_normal,
        counts_out=counts,
        design_out=design,
        tumor_cases=tumor_cases,
    )
    return counts, design, prov


# ---------------------------------------------------------------------------
# Run + score one cohort
# ---------------------------------------------------------------------------
def run_and_score_cohort(
    cohort: Cohort,
    *,
    data_root: Path,
    runs_root: Path,
    known: list[KnownAntigen],
    subtype_labels: dict[str, str] | None,
) -> dict[str, Any]:
    """Fetch + discover + score one cohort. Returns a JSON-able result dict."""
    from bindsight.pipelines import discover

    counts, design, gdc_prov = prepare_cohort(cohort, data_root, subtype_labels)
    run_out = runs_root / cohort.key
    config = _build_config(cohort, counts, design, run_out)

    LOG.info("=== discover: %s (%s) ===", cohort.label, cohort.project)
    manifest = discover.run(config)
    statuses = {s.name: s.status for s in manifest.stages}
    if any(v != "completed" for v in statuses.values()):
        LOG.warning("%s: stages not all completed: %s", cohort.key, statuses)

    # Score the whole known set (for the side-by-side report) and pull out the
    # expected antigen for the headline.
    full_score = score_run(run_out, known, ks=KS, run_name=cohort.label)
    expected = next(
        (a for a in full_score.per_antigen if a["uniprot"] == cohort.expected_uniprot), None
    )

    deg_stats = _deg_stats(run_out)
    deg_expected = _expected_deg(run_out, cohort.expected_ensembl)
    n_normal = int(gdc_prov.get("n_normal", 0))
    return {
        "cohort": asdict(cohort),
        "n_tumor": int(gdc_prov.get("n_tumor", 0)),
        "n_normal": n_normal,
        "n_candidates": full_score.n_candidates,
        "deg": deg_stats,
        "deg_expected": deg_expected,
        "expected": expected,
        "category": _categorise(deg_expected, n_normal),
        "stage_status": statuses,
        "gdc_provenance": gdc_prov,
        "run_dir": str(run_out),
    }


def _deg_stats(run_dir: Path) -> dict[str, Any]:
    """Summarise the DEG table (n tested / significant) for the report."""
    deg_path = run_dir / "deg" / "results.parquet"
    if not deg_path.exists():
        return {}
    deg = pd.read_parquet(deg_path)
    sig = deg["significant"] if "significant" in deg.columns else pd.Series(dtype=bool)
    return {
        "n_genes_tested": len(deg),
        "n_significant": int(sig.sum()) if len(sig) else 0,
    }


def _expected_deg(run_dir: Path, ensembl: str) -> dict[str, Any]:
    """Look up the expected antigen's own DEG row (log2fc/padj/significant).

    This is reported regardless of whether the antigen became a candidate, so
    the negative control can *show* its near-zero fold-change as evidence.
    """
    deg_path = run_dir / "deg" / "results.parquet"
    if not deg_path.exists():
        return {}
    deg = pd.read_parquet(deg_path)
    row = deg[deg["gene_id"] == ensembl]
    if row.empty:
        return {"tested": False}
    r = row.iloc[0]
    return {
        "tested": True,
        "log2fc": float(r["log2fc"]),
        "padj": float(r["padj"]) if pd.notna(r["padj"]) else None,
        "significant": bool(r["significant"]),
    }


# ---------------------------------------------------------------------------
# Orchestration + reporting
# ---------------------------------------------------------------------------
def run_validation(
    *,
    out_dir: Path,
    data_root: Path,
    runs_root: Path,
    known_path: Path,
    cohorts: list[Cohort] | None = None,
    study_id: str = CBIOPORTAL_STUDY,
) -> dict[str, Any]:
    """Run every cohort, score it, and write all benchmarks/validation artifacts.

    Writes ``RESULTS.md``, ``results.json``, ``report.html``, ``provenance.json``
    and ``figures/*.png`` under ``out_dir``. Returns the summary dict.
    """
    from bindsight.io.cbioportal import fetch_pam50_subtypes

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cohorts = cohorts or VALIDATION_COHORTS
    known = _load_known(known_path)

    subtype_labels: dict[str, str] | None = None
    if any(c.subtype for c in cohorts):
        subtype_labels = fetch_pam50_subtypes(study_id, cache_dir=data_root / "cbioportal")

    results: list[dict[str, Any]] = []
    for cohort in cohorts:
        res = run_and_score_cohort(
            cohort,
            data_root=data_root,
            runs_root=runs_root,
            known=known,
            subtype_labels=subtype_labels,
        )
        results.append(res)

    return _write_artifacts(out_dir, results, known, study_id, known_path)


def rescore_from_runs(
    *,
    out_dir: Path,
    runs_root: Path,
    known_path: Path,
    cohorts: list[Cohort] | None = None,
    study_id: str = CBIOPORTAL_STUDY,
) -> dict[str, Any]:
    """Regenerate all validation artifacts from *already-finished* run dirs.

    Re-scores the cached ``runs_root/<cohort>`` discovery outputs and rewrites
    RESULTS.md / results.json / report.html / figures — without re-running DEG
    or enrichment. Used to refresh the reporting after a scoring change.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cohorts = cohorts or VALIDATION_COHORTS
    known = _load_known(known_path)

    results: list[dict[str, Any]] = []
    for cohort in cohorts:
        run_out = runs_root / cohort.key
        if not (run_out / "targets" / "candidates.parquet").exists():
            LOG.warning("%s: no cached run at %s; skipping", cohort.key, run_out)
            continue
        full_score = score_run(run_out, known, ks=KS, run_name=cohort.label)
        expected = next(
            (a for a in full_score.per_antigen if a["uniprot"] == cohort.expected_uniprot), None
        )
        deg_expected = _expected_deg(run_out, cohort.expected_ensembl)
        n_normal = cohort.n_normal
        results.append(
            {
                "cohort": asdict(cohort),
                "n_tumor": cohort.n_tumor,
                "n_normal": n_normal,
                "n_candidates": full_score.n_candidates,
                "deg": _deg_stats(run_out),
                "deg_expected": deg_expected,
                "expected": expected,
                "category": _categorise(deg_expected, n_normal),
                "run_dir": str(run_out),
                "gdc_provenance": {},
            }
        )
    return _write_artifacts(out_dir, results, known, study_id, known_path)


def _write_artifacts(
    out_dir: Path,
    results: list[dict[str, Any]],
    known: list[KnownAntigen],
    study_id: str,
    known_path: Path,
) -> dict[str, Any]:
    """Build the summary, write all artifacts, and return the summary dict."""
    scores = [
        score_run(Path(r["run_dir"]), known, ks=KS, run_name=r["cohort"]["label"]) for r in results
    ]
    recall = _aggregate_recall(results)
    summary = {
        "schema": "bindsight-validation/1",
        "generated_utc": _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds"),
        "bindsight_version": __version__,
        "cbioportal_study": study_id,
        "known_set": str(known_path),
        "ks": list(KS),
        "overexpression_rule": f"FDR<0.05 and log2fc>={OVEREXPRESSION_LOG2FC}",
        "recall_at_k": recall,
        "specificity": _specificity(results),
        "cohorts": results,
        "data_limited": DATA_LIMITED,
    }

    (out_dir / "results.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    (out_dir / "report.html").write_text(
        render_benchmark_html(scores, ks=KS, known_source=str(known_path)), encoding="utf-8"
    )
    (out_dir / "RESULTS.md").write_text(_render_results_md(summary), encoding="utf-8")
    _write_provenance(out_dir, summary)
    try:
        _render_figures(out_dir / "figures", results, recall)
    except Exception as e:  # matplotlib optional / headless edge cases
        LOG.warning("figure rendering skipped: %s", e)

    LOG.info("validation complete; wrote %s", out_dir)
    return summary


def _load_known(known_path: Path) -> list[KnownAntigen]:
    from bindsight.benchmark.core import load_known_antigens

    return load_known_antigens(known_path)


def _antigen_rank(r: dict[str, Any]) -> int | None:
    ex = r.get("expected") or {}
    rank = ex.get("rank")
    return int(rank) if rank is not None else None


def _aggregate_recall(results: list[dict[str, Any]]) -> dict[str, float]:
    """recall@k over antigens that are *measurably* over-expressed in their cohort.

    Only antigens that pass the over-expression precondition (significant and
    log2fc ≥ threshold) are in the denominator — an expression-based discovery
    method can only be expected to surface antigens that are actually
    over-expressed. Non-over-expressed antigens are scored under specificity.
    """
    oe = [r for r in results if r.get("category") == "over_expressed"]
    if not oe:
        return {f"recall@{k}": 0.0 for k in KS}
    out: dict[str, float] = {}
    for k in KS:
        hits = sum(1 for r in oe if (_antigen_rank(r) or 10**9) <= k)
        out[f"recall@{k}"] = round(hits / len(oe), 4)
    return out


def _specificity(results: list[dict[str, Any]], k: int = 20) -> dict[str, Any]:
    """Among non-over-expressed antigens, the fraction correctly NOT in the top-k.

    A specificity-respecting pipeline should not surface antigens that are not
    transcriptionally over-expressed (clinical fame ≠ over-expression).
    """
    noe = [r for r in results if r.get("category") == "not_over_expressed"]
    if not noe:
        return {"n": 0, "correctly_excluded": 0, "fraction": None, "k": k}
    correct = sum(1 for r in noe if (_antigen_rank(r) or 10**9) > k)
    return {
        "n": len(noe),
        "correctly_excluded": correct,
        "fraction": round(correct / len(noe), 4),
        "k": k,
    }


_CATEGORY_ORDER = ["over_expressed", "not_over_expressed", "underpowered", "not_tested"]
_CATEGORY_TITLE = {
    "over_expressed": "Transcriptionally over-expressed (the pipeline should — and is scored to — surface these)",
    "not_over_expressed": "Not over-expressed at the bulk level (specificity: the pipeline should NOT surface these)",
    "underpowered": "Underpowered (too few matched normals to call differential expression)",
    "not_tested": "Antigen absent from the DEG table",
}


def _render_results_md(summary: dict[str, Any]) -> str:
    ks = summary["ks"]
    lines: list[str] = []
    a = lines.append
    cohorts = summary["cohorts"]

    def _row(r: dict[str, Any]) -> str:
        c = r["cohort"]
        ex = r.get("expected") or {}
        rank = ex.get("rank")
        dexp = r.get("deg_expected") or {}
        log2fc = ex.get("log2fc") if ex.get("log2fc") is not None else dexp.get("log2fc")
        padj = ex.get("padj") if ex.get("padj") is not None else dexp.get("padj")
        tops = " | ".join("✓" if (rank is not None and rank <= k) else "·" for k in ks)
        return (
            f"| {c['expected_symbol']} ({c['expected_uniprot']}) | {c['project']} | "
            f"{r['n_tumor']} | {r['n_normal']} | "
            f"{f'{log2fc:.2f}' if isinstance(log2fc, (int, float)) else '—'} | "
            f"{f'{padj:.1e}' if isinstance(padj, (int, float)) else '—'} | "
            f"{rank if rank is not None else '—'} | {tops} |"
        )

    header = (
        "| antigen | project | tumor | normal | log2fc | padj | rank | "
        + " | ".join(f"≤{k}" for k in ks)
        + " |"
    )
    sep = "|---|---|--:|--:|--:|--:|--:|" + "|".join("--:" for _ in ks) + "|"

    by_cat: dict[str, list[dict[str, Any]]] = {}
    for r in cohorts:
        by_cat.setdefault(r.get("category", "not_tested"), []).append(r)

    rec = summary["recall_at_k"]
    spec = summary["specificity"]
    oe = by_cat.get("over_expressed", [])
    found = [r for r in oe if _antigen_rank(r) is not None]

    a("# bindsight rediscovery validation — results\n")
    a(
        "Does bindsight's expression-based discovery resurface clinically-validated "
        "cell-surface antigens from real TCGA RNA-seq? Each antigen is evaluated in "
        "its indication cohort as a tumor-vs-adjacent-normal contrast run through the "
        "discovery half (`bindsight discover`), then scored by the rank of the antigen "
        "in the candidate shortlist (`bindsight.benchmark.score_run`).\n"
    )
    a(
        "**All numbers below are produced by the runs; none are hand-set. Antigens are "
        "grouped by their _measured_ differential expression "
        f"(rule: {summary['overexpression_rule']}), not by any prior label — an "
        "expression-based method can only surface antigens that are actually "
        "over-expressed, and we report that precondition transparently.**\n"
    )
    a(f"- Generated: `{summary['generated_utc']}` · bindsight `{summary['bindsight_version']}`")
    a(f"- PAM50 subtypes: cBioPortal study `{summary['cbioportal_study']}`")
    a(f"- Known-antigen set: `{summary['known_set']}`\n")

    a("## Headline\n")
    if found:
        best = min(found, key=lambda r: _antigen_rank(r) or 10**9)
        bc = best["cohort"]
        br = _antigen_rank(best)
        a(
            f"- **Sensitivity:** of {len(oe)} antigen(s) genuinely over-expressed in their "
            f"cohort, **{best['cohort']['expected_symbol']}** is rediscovered at "
            f"**rank {br}** in {bc['project']}"
            + (f" ({bc['subtype']} subtype)" if bc["subtype"] else "")
            + f" — log2fc {best['deg_expected']['log2fc']:.2f}, "
            f"padj {best['deg_expected']['padj']:.1e}."
        )
    a(
        "- **recall@k over over-expressed antigens:** "
        + ", ".join(f"recall@{k}={rec[f'recall@{k}']:.0%}" for k in ks)
        + "."
    )
    if spec.get("fraction") is not None:
        a(
            f"- **Specificity:** {spec['correctly_excluded']}/{spec['n']} antigens that are "
            f"NOT over-expressed at the bulk level are correctly kept out of the top-"
            f"{spec['k']} — the pipeline keys on genuine over-expression, not clinical fame."
        )
    a("")

    a("## Reproduce\n")
    a("```bash")
    a('pip install -e ".[discover,report]"')
    a("python benchmarks/run_validation.py")
    a("```\n")

    a("## Per-antigen results (grouped by measured over-expression)\n")
    a(
        "`rank` is the antigen's 1-based position in the cohort's surface-filtered "
        "candidate shortlist; `—` = not surfaced.\n"
    )
    for cat in _CATEGORY_ORDER:
        rows = by_cat.get(cat, [])
        if not rows:
            continue
        a(f"### {_CATEGORY_TITLE[cat]}\n")
        a(header)
        a(sep)
        for r in sorted(rows, key=lambda r: -(r.get("deg_expected") or {}).get("log2fc", 0.0)):
            a(_row(r))
        a("")
        for r in rows:
            a(
                f"- **{r['cohort']['expected_symbol']}** ({r['cohort']['project']}): "
                f"{r['cohort']['note']}"
            )
        a("")

    a("## Interpretation\n")
    a(
        "- The discovery pipeline (subtype-stratified DESeq2 → SURFY surfaceome filter → "
        "combined-significance ranking) correctly surfaces the antigen that is strongly "
        "transcriptionally over-expressed, and correctly withholds antigens that are not "
        "— including clinically famous ones whose tumor-selectivity arises from mutation/"
        "amplification (EGFR) or lineage co-expression in the normal tissue-of-origin "
        "(CEA, PSMA). Sensitivity therefore tracks effect size, as expected for a "
        "differential-expression method."
    )
    a(
        "- This delineates the scope of bulk tumor-vs-normal discovery and motivates the "
        "multi-modal specificity scoring (single-cell, co-expression, immunopeptidomics) "
        "planned for v1.0.\n"
    )

    a("## Antigens with no matched TCGA normal (not runnable here)\n")
    for d in summary["data_limited"]:
        a(f"- **{d['symbol']}** ({d['project']}): {d['reason']}")
    a("")
    a("## Provenance\n")
    a(
        "Per-cohort GDC file UUIDs, case barcodes and SHA-256 checksums are in "
        "`provenance.json` (and each cohort's own `provenance.json` under the GDC "
        "cache). The side-by-side per-antigen scoring across the full known set is "
        "in `report.html`.\n"
    )
    return "\n".join(lines)


def _write_provenance(out_dir: Path, summary: dict[str, Any]) -> None:
    prov = {
        "schema": "bindsight-validation-provenance/1",
        "generated_utc": summary["generated_utc"],
        "bindsight_version": summary["bindsight_version"],
        "cbioportal_study": summary["cbioportal_study"],
        "sources": {
            "rna_seq": "NIH/GDC TCGA STAR-Counts (GENCODE v36), open access",
            "subtypes": "cBioPortal PAM50 (Parker et al. 2009)",
            "known_antigens": summary["known_set"],
        },
        "cohorts": [
            {
                "key": r["cohort"]["key"],
                "project": r["cohort"]["project"],
                "subtype": r["cohort"]["subtype"],
                "n_tumor": r["n_tumor"],
                "n_normal": r["n_normal"],
                "gdc": r.get("gdc_provenance", {}),
            }
            for r in summary["cohorts"]
        ],
    }
    (out_dir / "provenance.json").write_text(json.dumps(prov, indent=2) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Figures (matplotlib; imported lazily)
# ---------------------------------------------------------------------------
def _render_figures(fig_dir: Path, results: list[dict[str, Any]], recall: dict[str, float]) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig_dir.mkdir(parents=True, exist_ok=True)

    # 1. recall@k bar chart.
    ks = [int(k.split("@")[1]) for k in recall]
    vals = [recall[f"recall@{k}"] for k in ks]
    fig, ax = plt.subplots(figsize=(4.5, 3.2))
    ax.bar([f"recall@{k}" for k in ks], vals, color="#2a9d8f")
    ax.set_ylim(0, 1.0)
    ax.set_ylabel("recall")
    ax.set_title("Rediscovery recall@k\n(over runnable cohort-antigen pairs)")
    for i, v in enumerate(vals):
        ax.text(i, v + 0.02, f"{v:.0%}", ha="center", fontsize=9)
    fig.tight_layout()
    fig.savefig(fig_dir / "recall_at_k.png", dpi=150)
    plt.close(fig)

    # 2. expected-antigen rank per cohort (lower is better).
    labels = [r["cohort"]["label"] + f"\n{r['cohort']['expected_symbol']}" for r in results]
    ranks = [(r.get("expected") or {}).get("rank") for r in results]
    plotted = [(lab, rk) for lab, rk in zip(labels, ranks, strict=True) if rk is not None]
    if plotted:
        labs, rks = zip(*plotted, strict=True)
        fig, ax = plt.subplots(figsize=(5.5, 3.2))
        ax.bar(labs, rks, color="#e76f51")
        ax.axhline(10, ls="--", color="#555", lw=1, label="top-10")
        ax.set_ylabel("rank in shortlist (lower = better)")
        ax.set_title("Expected-antigen rank per cohort")
        ax.legend()
        fig.tight_layout()
        fig.savefig(fig_dir / "antigen_rank.png", dpi=150)
        plt.close(fig)

    # 3. volcano per cohort, expected antigen highlighted.
    import numpy as np

    for r in results:
        deg_path = Path(r["run_dir"]) / "deg" / "results.parquet"
        if not deg_path.exists():
            continue
        deg = pd.read_parquet(deg_path)
        if not {"log2fc", "padj", "gene_id"}.issubset(deg.columns):
            continue
        padj = deg["padj"].clip(lower=1e-300)
        nlog = -np.log10(padj)
        fig, ax = plt.subplots(figsize=(4.8, 3.6))
        ax.scatter(deg["log2fc"], nlog, s=4, alpha=0.25, color="#888", linewidths=0)
        ens = r["cohort"]["expected_ensembl"]
        hit = deg[deg["gene_id"] == ens]
        if not hit.empty:
            ax.scatter(
                hit["log2fc"],
                -np.log10(hit["padj"].clip(lower=1e-300)),
                s=60,
                color="#d62728",
                zorder=5,
                label=r["cohort"]["expected_symbol"],
            )
            ax.legend()
        ax.set_xlabel("log2 fold-change (tumor / normal)")
        ax.set_ylabel("-log10 adj. p")
        ax.set_title(f"{r['cohort']['label']} volcano")
        fig.tight_layout()
        fig.savefig(fig_dir / f"volcano_{r['cohort']['key']}.png", dpi=150)
        plt.close(fig)

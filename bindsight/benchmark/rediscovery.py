# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Rediscovery validation: do real TCGA cohorts resurface known antigens?

This module runs the discovery half of bindsight on real TCGA cohorts (one per
known antigen, in its indication) as tumor-vs-adjacent-normal contrasts, and
scores the rank of each antigen in the candidate shortlist
(:func:`benchmark.score_run`), crediting only the cohort's own indication. The
report groups antigens by their *measured* differential expression so the result
is transparent and not gamed; the requested cohort sizes are the only hand-set
values and are reported as inputs next to the achieved per-arm counts.

The honest finding the runs produce: bulk-DE discovery surfaces antigens that
are genuinely transcriptionally over-expressed (ERBB2 in HER2-enriched breast,
rank 4 — exposed by PAM50 subtype-stratification via
:mod:`bindsight.io.cbioportal`, which otherwise averages the HER2 signal away)
and withholds antigens whose tumor-selectivity arises from other mechanisms —
mutation/amplification (EGFR) or lineage co-expression in the normal
tissue-of-origin (CEA, PSMA). Sensitivity therefore tracks effect size, the
expected behaviour of a differential-expression method. That withholding
follows from the DE gate by construction (a gene failing the over-expression
rule never becomes a candidate), so it is reported as an internal-consistency
check rather than as measured specificity.

CLDN6 (ovarian) and CD33/CD123 (AML) are deliberately *not* run: TCGA-OV and
TCGA-LAML ship zero matched solid-tissue normals, and substituting GTEx normals
would confound the result with a cross-study batch effect — documented as data
limitations rather than reported with a manufactured number.
"""

from __future__ import annotations

import datetime as _dt
import gzip
import hashlib
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
    - ``not_over_expressed`` — not significantly up at the bulk level (the DE
      gate excludes it from candidacy; counts toward the consistency check);
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

    ``requested_n_tumor`` / ``requested_n_normal`` are *inputs* to the GDC query,
    not measurements: GDC may hold fewer samples, and the one-sample-per-patient
    rule drops technical replicates. The achieved per-arm counts are derived from
    the run's own provenance (:func:`_achieved_sampling`) and reported separately.
    """

    key: str
    label: str
    project: str
    tumor_type: str  # indication code, matching the known table's ``tumor_type``
    expected_symbol: str
    expected_uniprot: str
    expected_ensembl: str
    subtype: str | None  # cBioPortal PAM50 label, or None for whole-project tumor
    requested_n_tumor: int
    requested_n_normal: int
    expectation: str
    note: str


VALIDATION_COHORTS: list[Cohort] = [
    Cohort(
        key="brca_her2",
        label="BRCA HER2-enriched",
        project="TCGA-BRCA",
        tumor_type="BRCA",
        expected_symbol="ERBB2",
        expected_uniprot="P04626",
        expected_ensembl="ENSG00000141736",
        subtype="BRCA_Her2",
        requested_n_tumor=50,
        requested_n_normal=40,
        expectation="positive",
        note="PAM50 HER2-enriched tumors are ERBB2-amplified, so ERBB2 mRNA is high.",
    ),
    Cohort(
        key="coad",
        label="COAD",
        project="TCGA-COAD",
        tumor_type="COAD",
        expected_symbol="CEACAM5",
        expected_uniprot="P06731",
        expected_ensembl="ENSG00000105388",
        subtype=None,
        requested_n_tumor=50,
        requested_n_normal=40,
        expectation="positive",
        note="CEA (target of tusamitamab ravtansine / labetuzumab govitecan) is a classic "
        "colorectal marker, but it is also abundantly expressed in normal colon "
        "epithelium, so the bulk tumor-vs-adjacent-normal fold-change is ~0.",
    ),
    Cohort(
        key="blca",
        label="BLCA",
        project="TCGA-BLCA",
        tumor_type="BLCA",
        expected_symbol="NECTIN4",
        expected_uniprot="Q96NY8",
        expected_ensembl="ENSG00000143217",
        subtype=None,
        requested_n_tumor=50,
        requested_n_normal=19,
        expectation="positive",
        note="Nectin-4 (target of enfortumab vedotin, Padcev) is elevated in urothelial "
        "carcinoma, but only modestly at the bulk-mRNA level (log2fc ~1.6), below the "
        "discovery shortlist.",
    ),
    Cohort(
        key="luad",
        label="LUAD (EGFR negative control)",
        project="TCGA-LUAD",
        tumor_type="LUAD",
        expected_symbol="EGFR",
        expected_uniprot="P00533",
        expected_ensembl="ENSG00000146648",
        subtype=None,
        requested_n_tumor=50,
        requested_n_normal=40,
        expectation="negative_control",
        note="EGFR drives LUAD via mutation/amplification, not bulk mRNA over-expression, "
        "so a specificity-respecting pipeline should NOT surface it on expression alone.",
    ),
    Cohort(
        key="paad",
        label="PAAD (MSLN, limited)",
        project="TCGA-PAAD",
        tumor_type="PAAD",
        expected_symbol="MSLN",
        expected_uniprot="Q13421",
        expected_ensembl="ENSG00000102854",
        subtype=None,
        requested_n_tumor=50,
        requested_n_normal=4,
        expectation="limited",
        note="Mesothelin is over-expressed in PDAC, but TCGA-PAAD ships only 4 matched "
        "normals, so the contrast is underpowered (reported for transparency).",
    ),
    Cohort(
        key="prad",
        label="PRAD (FOLH1, limited)",
        project="TCGA-PRAD",
        tumor_type="PRAD",
        expected_symbol="FOLH1",
        expected_uniprot="Q04609",
        expected_ensembl="ENSG00000086205",
        subtype=None,
        requested_n_tumor=50,
        requested_n_normal=40,
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


_DESIGN_COLUMNS = ("sample", "condition", "case_barcode", "sample_barcode")


def _one_sample_per_patient(samples: list[dict[str, Any]]) -> list[str]:
    """Choose at most one sample per (patient, arm) from a cohort's sample list.

    A GDC listing can return several aliquots of the same patient in one arm
    (e.g. ``-01A`` and ``-01B``); an unpaired ``~ condition`` design would treat
    those technical replicates as independent patients. The kept aliquot is the
    lexicographically first ``sample_barcode``, so re-running reproduces exactly
    the same cohort.

    Returns the sample ids to keep, in the input order.
    """
    best: dict[tuple[str, str], tuple[str, str]] = {}
    for s in samples:
        arm = (str(s["condition"]), str(s["case_barcode"]))
        aliquot = (str(s["sample_barcode"]), str(s["sample"]))
        if arm not in best or aliquot < best[arm]:
            best[arm] = aliquot
    kept = {sample_id for _, sample_id in best.values()}
    return [str(s["sample"]) for s in samples if str(s["sample"]) in kept]


def _sampling_summary(samples: list[dict[str, Any]], dropped: list[str]) -> dict[str, Any]:
    """Achieved per-arm sample/patient counts, measured from the sample list."""
    by_arm = {
        arm: [s for s in samples if str(s["condition"]) == arm] for arm in ("tumor", "normal")
    }
    patients = {arm: {str(s["case_barcode"]) for s in rows} for arm, rows in by_arm.items()}
    both = sorted(patients["tumor"] & patients["normal"])
    # Measured, not assumed: an older cohort fetched before the rule existed can
    # still carry two aliquots of one patient in one arm.
    arms_patients = {(str(s["condition"]), str(s["case_barcode"])) for s in samples}
    return {
        "n_tumor": len(by_arm["tumor"]),
        "n_normal": len(by_arm["normal"]),
        "n_patients_tumor": len(patients["tumor"]),
        "n_patients_normal": len(patients["normal"]),
        "n_patients_in_both_arms": len(both),
        "patients_in_both_arms": both,
        "dropped_replicate_samples": dropped,
        "one_sample_per_patient_per_arm": len(arms_patients) == len(samples),
        "unpaired_design_disclosure": (
            f"{len(both)} patient(s) contribute a sample to both arms; the DE design is "
            "unpaired (~ condition), so that pairing is not modelled."
        ),
    }


def _achieved_sampling(cohort_key: str, prov: dict[str, Any]) -> dict[str, Any]:
    """Read the achieved sampling out of a cohort's GDC provenance.

    Raises:
        ValueError: if the provenance carries no per-sample record, in which
            case the achieved cohort size is unknown and must not be replaced
            by the requested constants.
    """
    samples = prov.get("samples")
    if not isinstance(samples, list) or not samples:
        raise ValueError(
            f"{cohort_key}: GDC provenance has no per-sample record, so the achieved "
            "cohort size cannot be measured; re-fetch the cohort instead of reporting "
            "the requested sizes as if they were achieved"
        )
    summary = prov.get("patient_sampling")
    if isinstance(summary, dict):
        return summary
    return _sampling_summary(samples, [])


def _requested(cohort: Cohort) -> dict[str, Any]:
    """The cohort-size *inputs*, kept apart from the achieved counts."""
    return {"n_tumor": cohort.requested_n_tumor, "n_normal": cohort.requested_n_normal}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _enforce_one_sample_per_patient(
    cohort_key: str, counts: Path, design_path: Path, prov: dict[str, Any], prov_path: Path
) -> dict[str, Any]:
    """Reduce a fetched cohort to one sample per patient per arm, in place.

    Rewrites ``counts``/``design`` (and the cohort's ``provenance.json``) only
    when a replicate is actually dropped, so repeated calls are a no-op.
    Returns the achieved sampling summary.
    """
    design = pd.read_csv(design_path, sep="\t", dtype=str)
    missing = set(_DESIGN_COLUMNS) - set(design.columns)
    if missing:
        raise ValueError(
            f"{design_path}: design table missing columns {sorted(missing)}; cannot verify "
            "that each patient contributes one sample per arm"
        )
    samples: list[dict[str, Any]] = design.to_dict("records")
    keep = _one_sample_per_patient(samples)
    kept = set(keep)
    dropped = [str(s["sample"]) for s in samples if str(s["sample"]) not in kept]

    if dropped:
        LOG.warning(
            "%s: %d same-patient replicate sample(s) dropped before DE: %s",
            cohort_key,
            len(dropped),
            ", ".join(dropped),
        )
        design[design["sample"].isin(kept)].to_csv(
            design_path, sep="\t", index=False, lineterminator="\n"
        )
        counts_df = pd.read_csv(counts, sep="\t", index_col=0)
        with gzip.open(counts, "wt", newline="") as fh:
            counts_df[keep].to_csv(fh, sep="\t")
        samples = [s for s in samples if str(s["sample"]) in kept]

    summary = _sampling_summary(samples, dropped)
    if summary["n_patients_in_both_arms"]:
        LOG.warning("%s: %s", cohort_key, summary["unpaired_design_disclosure"])
    if prov:
        prov["samples"] = samples
        prov["n_tumor"] = summary["n_tumor"]
        prov["n_normal"] = summary["n_normal"]
        prov["patient_sampling"] = summary
        outputs = prov.get("outputs")
        if isinstance(outputs, dict) and dropped:
            for path in (counts, design_path):
                if path.name in outputs:
                    outputs[path.name] = {
                        "sha256": _sha256(path),
                        "bytes": path.stat().st_size,
                    }
        prov_path.write_text(json.dumps(prov, indent=2) + "\n", encoding="utf-8")
    return summary


def prepare_cohort(
    cohort: Cohort, data_root: Path, subtype_labels: dict[str, str] | None
) -> tuple[Path, Path, dict[str, Any]]:
    """Fetch a cohort's counts + design from GDC (idempotent); return their paths.

    For a subtype cohort, the tumor cases are the PAM50-labelled patients from
    ``subtype_labels``; normals are the project's adjacent-normal samples. The
    fetched cohort is then reduced to one sample per patient per arm, so no
    patient enters the unpaired contrast twice through the same arm.
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

    prov: dict[str, Any]
    if counts.exists() and design.exists():
        LOG.info("%s: cohort already downloaded at %s", cohort.key, cohort_dir)
        prov = json.loads(prov_path.read_text()) if prov_path.exists() else {}
    else:
        prov = fetch_cohort(
            project=cohort.project,
            n_tumor=cohort.requested_n_tumor,
            n_normal=cohort.requested_n_normal,
            counts_out=counts,
            design_out=design,
            tumor_cases=tumor_cases,
        )
    _enforce_one_sample_per_patient(cohort.key, counts, design, prov, prov_path)
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
    """Fetch + discover + score one cohort. Returns a JSON-able result dict.

    The dict separates ``requested`` (the cohort-size inputs to the GDC query)
    from ``achieved`` (the per-arm sample and patient counts of the samples the
    run actually used); ``n_tumor``/``n_normal`` mirror the achieved counts.
    """
    from bindsight.pipelines import discover

    counts, design, gdc_prov = prepare_cohort(cohort, data_root, subtype_labels)
    run_out = runs_root / cohort.key
    config = _build_config(cohort, counts, design, run_out)

    LOG.info("=== discover: %s (%s) ===", cohort.label, cohort.project)
    manifest = discover.run(config)
    statuses = {s.name: s.status for s in manifest.stages}
    if any(v != "completed" for v in statuses.values()):
        LOG.warning("%s: stages not all completed: %s", cohort.key, statuses)

    # Persist the GDC provenance into the run directory so a later
    # ``rescore_from_runs`` (which only sees ``runs_root``) can recover the real
    # file UUIDs / barcodes / checksums instead of emitting an empty object.
    run_out.mkdir(parents=True, exist_ok=True)
    (run_out / "gdc_provenance.json").write_text(
        json.dumps(gdc_prov, indent=2) + "\n", encoding="utf-8"
    )

    # Score the cohort's own indication (for the side-by-side report) and pull
    # out the expected antigen for the headline.
    full_score = score_run(
        run_out, known, ks=KS, run_name=cohort.label, tumor_type=cohort.tumor_type
    )
    expected = next(
        (a for a in full_score.per_antigen if a["uniprot"] == cohort.expected_uniprot), None
    )

    deg_stats = _deg_stats(run_out)
    deg_expected = _expected_deg(run_out, cohort.expected_ensembl)
    achieved = _achieved_sampling(cohort.key, gdc_prov)
    return {
        "cohort": asdict(cohort),
        "requested": _requested(cohort),
        "achieved": achieved,
        "n_tumor": achieved["n_tumor"],
        "n_normal": achieved["n_normal"],
        "n_candidates": full_score.n_candidates,
        "cross_indication": full_score.cross_indication,
        "deg": deg_stats,
        "deg_expected": deg_expected,
        "expected": expected,
        "category": _categorise(deg_expected, achieved["n_normal"]),
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

    Raises:
        FileNotFoundError: if a cached run has no ``gdc_provenance.json``, i.e.
            its achieved per-arm sample counts are unknown.
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
        full_score = score_run(
            run_out, known, ks=KS, run_name=cohort.label, tumor_type=cohort.tumor_type
        )
        expected = next(
            (a for a in full_score.per_antigen if a["uniprot"] == cohort.expected_uniprot), None
        )
        deg_expected = _expected_deg(run_out, cohort.expected_ensembl)
        # Recover the GDC provenance persisted by the fresh run (see
        # ``run_and_score_cohort``). A run dir without it cannot say how many
        # samples per arm it actually used, and the requested constants are not
        # a stand-in for that, so re-scoring it is an error.
        gdc_prov_path = run_out / "gdc_provenance.json"
        if not gdc_prov_path.exists():
            raise FileNotFoundError(
                f"{cohort.key}: {gdc_prov_path} is missing, so the achieved cohort size "
                "cannot be recovered; re-run the cohort with run_validation()"
            )
        gdc_prov: dict[str, Any] = json.loads(gdc_prov_path.read_text())
        achieved = _achieved_sampling(cohort.key, gdc_prov)
        results.append(
            {
                "cohort": asdict(cohort),
                "requested": _requested(cohort),
                "achieved": achieved,
                "n_tumor": achieved["n_tumor"],
                "n_normal": achieved["n_normal"],
                "n_candidates": full_score.n_candidates,
                "cross_indication": full_score.cross_indication,
                "deg": _deg_stats(run_out),
                "deg_expected": deg_expected,
                "expected": expected,
                "category": _categorise(deg_expected, achieved["n_normal"]),
                "run_dir": str(run_out),
                "gdc_provenance": gdc_prov,
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
        score_run(
            Path(r["run_dir"]),
            known,
            ks=KS,
            run_name=r["cohort"]["label"],
            tumor_type=r["cohort"]["tumor_type"],
        )
        for r in results
    ]
    recall = _aggregate_recall(results)
    summary = {
        "schema": "bindsight-validation/2",
        "generated_utc": _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds"),
        "bindsight_version": __version__,
        "cbioportal_study": study_id,
        "known_set": str(known_path),
        "ks": list(KS),
        "overexpression_rule": f"FDR<0.05 and log2fc>={OVEREXPRESSION_LOG2FC}",
        "recall_at_k": recall,
        "exclusion_consistency_check": _exclusion_consistency_check(results),
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
    over-expressed. Non-over-expressed antigens go to the exclusion
    consistency check instead.
    """
    oe = [r for r in results if r.get("category") == "over_expressed"]
    if not oe:
        return {f"recall@{k}": 0.0 for k in KS}
    out: dict[str, float] = {}
    for k in KS:
        hits = sum(1 for r in oe if (_antigen_rank(r) or 10**9) <= k)
        out[f"recall@{k}"] = round(hits / len(oe), 4)
    return out


def _exclusion_consistency_check(results: list[dict[str, Any]], k: int = 20) -> dict[str, Any]:
    """Internal-consistency check: non-over-expressed antigens stay out of the top-k.

    This is **not** a measure of ranking discrimination. ``not_over_expressed``
    is the exact complement of the rule a gene must pass (significant and
    log2fc ≥ threshold) to enter the candidate list at all, so such an antigen
    cannot appear in the shortlist by construction and the check cannot fail. It
    is kept because a failure would mean the DE filter and the shortlist had
    fallen out of step — a real bug — not because it demonstrates specificity.
    """
    noe = [r for r in results if r.get("category") == "not_over_expressed"]
    tautological = (
        "Antigens failing the over-expression rule are excluded from candidacy by "
        "construction, so this check confirms internal consistency between the DE "
        "filter and the shortlist; it does not measure ranking discrimination."
    )
    if not noe:
        return {
            "check": "non_over_expressed_absent_from_top_k",
            "n": 0,
            "consistent": 0,
            "fraction": None,
            "k": k,
            "tautological_by_construction": True,
            "interpretation": tautological,
        }
    consistent = sum(1 for r in noe if (_antigen_rank(r) or 10**9) > k)
    return {
        "check": "non_over_expressed_absent_from_top_k",
        "n": len(noe),
        "consistent": consistent,
        "fraction": round(consistent / len(noe), 4),
        "k": k,
        "tautological_by_construction": True,
        "interpretation": tautological,
    }


_CATEGORY_ORDER = ["over_expressed", "not_over_expressed", "underpowered", "not_tested"]
_CATEGORY_TITLE = {
    "over_expressed": "Transcriptionally over-expressed (the pipeline should — and is scored to — surface these)",
    "not_over_expressed": "Not over-expressed at the bulk level (excluded from candidacy by the DE rule)",
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
        ach = r["achieved"]
        req = r["requested"]
        tops = " | ".join("✓" if (rank is not None and rank <= k) else "·" for k in ks)
        return (
            f"| {c['expected_symbol']} ({c['expected_uniprot']}) | {c['project']} | "
            f"{ach['n_tumor']} ({req['n_tumor']}) | {ach['n_normal']} ({req['n_normal']}) | "
            f"{ach['n_patients_in_both_arms']} | "
            f"{f'{log2fc:.2f}' if isinstance(log2fc, (int, float)) else '—'} | "
            f"{f'{padj:.1e}' if isinstance(padj, (int, float)) else '—'} | "
            f"{rank if rank is not None else '—'} | {tops} |"
        )

    header = (
        "| antigen | project | tumor: got (asked) | normal: got (asked) | patients in both arms "
        "| log2fc | padj | rank | " + " | ".join(f"≤{k}" for k in ks) + " |"
    )
    sep = "|---|---|--:|--:|--:|--:|--:|--:|" + "|".join("--:" for _ in ks) + "|"

    by_cat: dict[str, list[dict[str, Any]]] = {}
    for r in cohorts:
        by_cat.setdefault(r.get("category", "not_tested"), []).append(r)

    rec = summary["recall_at_k"]
    check = summary["exclusion_consistency_check"]
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
        "**Every measured number below is produced by the runs. The only hand-set values "
        "are the _requested_ cohort sizes — inputs to the GDC query, shown in parentheses "
        "next to the achieved per-arm sample counts, which are derived from each run's own "
        "provenance. Antigens are grouped by their _measured_ differential expression "
        f"(rule: {summary['overexpression_rule']}), not by any prior label — an "
        "expression-based method can only surface antigens that are actually "
        "over-expressed, and we report that precondition transparently.**\n"
    )
    replicated = [
        r["cohort"]["label"] for r in cohorts if not r["achieved"]["one_sample_per_patient_per_arm"]
    ]
    if replicated:
        a(
            "**Pseudo-replication warning:** these cohorts still contain more than one "
            f"sample from the same patient in one arm: {', '.join(replicated)}. Re-fetch "
            "them so the one-sample-per-patient rule applies.\n"
        )
    else:
        a(
            "Each cohort takes at most one sample per patient per arm (the lexicographically "
            "first aliquot), so no patient enters an arm twice.\n"
        )
    a(
        "Patients contributing to both arms are counted per cohort below; the DE design is "
        "unpaired (`~ condition`), so that pairing is not modelled.\n"
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
    if check.get("fraction") is not None:
        a(
            f"- **Internal-consistency check (not a specificity measurement):** "
            f"{check['consistent']}/{check['n']} antigens that fail the over-expression rule "
            f"are absent from the top-{check['k']}. {check['interpretation']} This check "
            "cannot fail unless the DE filter and the shortlist disagree, and it says "
            "nothing about how the pipeline ranks antigens that *are* over-expressed."
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
        "candidate shortlist; `—` = not surfaced. Only the cohort's own indication "
        "antigen counts as a rediscovery.\n"
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

    a("## Cross-indication cross-reactivity (NOT rediscovery)\n")
    a(
        "Known antigens of *other* cancer types that a cohort's shortlist happens to "
        "contain. They are excluded from recall@k: surfacing a colorectal antigen in a "
        "breast cohort is a cross-reactivity observation, not a rediscovery.\n"
    )
    cross_any = False
    for r in cohorts:
        for x in r.get("cross_indication") or []:
            cross_any = True
            a(
                f"- **{r['cohort']['label']}** ({r['cohort']['tumor_type']}) surfaced "
                f"**{x['symbol']}** ({x['tumor_type']}) at rank {x['rank']}."
            )
    if not cross_any:
        a("- None: no cohort surfaced a known antigen from another indication.")
    a("")

    a("## Interpretation\n")
    a(
        "- The discovery pipeline (subtype-stratified DESeq2 → SURFY surfaceome filter → "
        "combined-significance ranking) surfaces the antigen that is strongly "
        "transcriptionally over-expressed. Antigens that are not over-expressed — "
        "including clinically famous ones whose tumor-selectivity arises from mutation/"
        "amplification (EGFR) or lineage co-expression in the normal tissue-of-origin "
        "(CEA, PSMA) — are withheld by the DE gate itself rather than by the ranking, so "
        "their absence is a property of the filter, not evidence about the ranker. "
        "Sensitivity therefore tracks effect size, as expected for a "
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
        "Per-cohort GDC file UUIDs, case barcodes, SHA-256 checksums and the "
        "requested-vs-achieved sample counts are in `provenance.json` (and each cohort's "
        "own `provenance.json` under the GDC cache). The side-by-side per-antigen "
        "scoring — on-indication antigens plus any cross-indication cross-reactivity — "
        "is in `report.html`.\n"
    )
    return "\n".join(lines)


def _write_provenance(out_dir: Path, summary: dict[str, Any]) -> None:
    prov = {
        "schema": "bindsight-validation-provenance/2",
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
                "tumor_type": r["cohort"]["tumor_type"],
                "subtype": r["cohort"]["subtype"],
                "requested": r["requested"],
                "achieved": r["achieved"],
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

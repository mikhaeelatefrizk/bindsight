# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Indication-scoped rediscovery scoring, and the provenance it must not invent.

Regression tests for the published-artifact defects the forensic audit found in
the benchmark half. Each pins behaviour that the shipped artifacts got wrong:

- **P1** — :func:`bindsight.benchmark.core.score_run` credited a known antigen by
  protein identity alone, so a BRCA run counted CEACAM5 (a *colorectal* antigen)
  as a rediscovery and divided recall@k by the whole known set. Rediscovery is
  now indication-scoped, and an off-indication appearance is reported under a
  separate ``cross_indication`` field that cannot be read as recall.
- **P2** — cohort results echoed the hand-set ``n_tumor``/``n_normal`` query
  inputs as if they were achieved measurements, and re-scoring a cached run
  silently substituted those constants when the run's own provenance was
  missing. The achieved counts must come from the run's sample list, and a
  missing provenance must fail loudly.
- **I3** — a cohort arm could carry two aliquots of one patient
  (``TCGA-A6-6780-01A`` and ``-01B``) as independent replicates of an unpaired
  design.
- **L5** — ``benchmarks/designer_benchmark/score_run.py`` stamped
  ``is_mock: false`` plus a "Real GPU run" claim onto any tarball, including one
  produced by the mock runner.
"""

from __future__ import annotations

import gzip
import io
import json
import os
import subprocess
import sys
import tarfile
from pathlib import Path

import pandas as pd
import pytest

from bindsight.benchmark import rediscovery as R
from bindsight.benchmark.core import (
    KnownAntigen,
    render_benchmark_html,
    run_benchmark,
    score_run,
)

ROOT = Path(__file__).resolve().parents[1]
SCORE_RUN = ROOT / "benchmarks" / "designer_benchmark" / "score_run.py"

KS: tuple[int, ...] = (5, 10, 20)

# The real antigens (and real accessions) from the audit finding: the committed
# report credited CEACAM5 at rank 3 as a BRCA rediscovery, above ERBB2 at rank 4.
ERBB2 = KnownAntigen("ERBB2", "P04626", "BRCA")
CEACAM5 = KnownAntigen("CEACAM5", "P06731", "COAD")
EGFR = KnownAntigen("EGFR", "P00533", "LUAD")
KNOWN = [ERBB2, CEACAM5, EGFR]


def _make_run_dir(root: Path, candidates: list[tuple[str, str, int]]) -> Path:
    """Create a run dir with a candidates.parquet of (symbol, uniprot, rank)."""
    cand = pd.DataFrame(
        [
            {"symbol": sym, "uniprot_id": uid, "rank": rank, "log2fc": 3.0, "padj": 0.01}
            for (sym, uid, rank) in candidates
        ]
    )
    (root / "targets").mkdir(parents=True, exist_ok=True)
    cand.to_parquet(root / "targets" / "candidates.parquet", index=False)
    return root


def _write_known(path: Path) -> Path:
    path.write_text(
        "symbol\tuniprot\ttumor_type\texpected_direction\n"
        + "".join(f"{k.symbol}\t{k.uniprot}\t{k.tumor_type}\tup\n" for k in KNOWN)
    )
    return path


def _sample(case: str, arm: str, aliquot: str) -> dict[str, str]:
    """One design-table row of the shape a cohort's GDC provenance carries."""
    return {
        "sample": f"{case}-{aliquot}",
        "condition": arm,
        "case_barcode": case,
        "sample_barcode": f"{case}-{aliquot}",
    }


def _arm(arm: str, n: int, aliquot: str) -> list[dict[str, str]]:
    return [_sample(f"TCGA-ZZ-{arm[0].upper()}{i:03d}", arm, aliquot) for i in range(n)]


# ---------------------------------------------------------------------------
# P1 — a known antigen is only a rediscovery in its own indication
# ---------------------------------------------------------------------------
def test_off_indication_antigen_is_not_credited_as_a_rediscovery(tmp_path: Path) -> None:
    """The exact committed-report failure: CEACAM5 ranked above ERBB2 in BRCA."""
    run = _make_run_dir(
        tmp_path / "brca_her2",
        [("CEACAM5", "P06731", 3), ("ERBB2", "P04626", 4)],
    )
    score = score_run(run, KNOWN, ks=KS, tumor_type="BRCA")

    # Only the BRCA antigen is scorable, and it is the only one found.
    assert score.recall_basis == "on_indication"
    assert score.n_on_indication == 1
    assert [a["symbol"] for a in score.per_antigen] == ["ERBB2"]
    assert score.n_found == 1
    assert score.recall_at[5] == 1.0
    assert score.recall_at[20] == 1.0

    # CEACAM5 is reported, but under a name that cannot be read as recall.
    assert "CEACAM5" not in {a["symbol"] for a in score.per_antigen}
    assert score.n_cross_indication == 1
    (cross,) = score.cross_indication
    assert cross["symbol"] == "CEACAM5"
    assert cross["tumor_type"] == "COAD"
    assert cross["rank"] == 3
    assert cross["on_indication"] is False


def test_off_indication_hit_does_not_inflate_recall(tmp_path: Path) -> None:
    """A BRCA run that surfaced only a colorectal antigen has recall 0, not 1/3."""
    run = _make_run_dir(
        tmp_path / "brca_her2",
        [("CEACAM5", "P06731", 3), ("SDC1", "P18827", 4)],
    )
    score = score_run(run, KNOWN, ks=KS, tumor_type="BRCA")

    assert score.n_on_indication == 1
    assert score.n_found == 0
    assert score.recall_at[5] == 0.0
    assert score.recall_at[20] == 0.0
    assert [a["symbol"] for a in score.cross_indication] == ["CEACAM5"]


def test_indication_gate_is_symmetric(tmp_path: Path) -> None:
    """Scoring the same shortlist as COAD credits CEACAM5 and not ERBB2."""
    run = _make_run_dir(
        tmp_path / "coad",
        [("CEACAM5", "P06731", 3), ("ERBB2", "P04626", 4)],
    )
    score = score_run(run, KNOWN, ks=KS, tumor_type="COAD")

    assert [a["symbol"] for a in score.per_antigen] == ["CEACAM5"]
    assert score.per_antigen[0]["rank"] == 3
    assert score.recall_at[5] == 1.0
    assert [a["symbol"] for a in score.cross_indication] == ["ERBB2"]
    assert score.cross_indication[0]["on_indication"] is False


def test_missing_indication_is_labelled_not_assumed(tmp_path: Path) -> None:
    """Without an indication the gate cannot be applied, and the score says so."""
    run = _make_run_dir(
        tmp_path / "unknown",
        [("CEACAM5", "P06731", 3), ("ERBB2", "P04626", 4)],
    )
    score = score_run(run, KNOWN, ks=KS)

    assert score.tumor_type is None
    assert score.recall_basis == "indication_unknown"
    assert {a["symbol"] for a in score.per_antigen} == {"ERBB2", "CEACAM5", "EGFR"}
    assert score.cross_indication == []
    assert score.recall_at[5] == pytest.approx(2 / 3)


def test_indication_without_a_known_antigen_leaves_recall_undefined(tmp_path: Path) -> None:
    """recall@k is left empty rather than reported as a zero it did not measure."""
    run = _make_run_dir(tmp_path / "paad", [("MSLN", "Q13421", 1)])
    score = score_run(run, KNOWN, ks=KS, tumor_type="PAAD")

    assert score.recall_basis == "no_known_antigen_for_indication"
    assert score.n_on_indication == 0
    assert score.recall_at == {}
    for k in KS:
        assert k not in score.recall_at


def test_report_separates_cross_indication_from_rediscovery(tmp_path: Path) -> None:
    """The rendered report gives the off-indication hit its own, honest heading."""
    run = _make_run_dir(
        tmp_path / "brca_her2",
        [("CEACAM5", "P06731", 3), ("ERBB2", "P04626", 4)],
    )
    scored = score_run(run, KNOWN, ks=KS, run_name="BRCA HER2-enriched", tumor_type="BRCA")
    unscoped = score_run(run, KNOWN, ks=KS, run_name="no indication")
    html = render_benchmark_html([scored, unscoped], ks=KS, known_source="known.tsv")

    assert "Cross-indication cross-reactivity" in html
    assert "NOT rediscovery" in html
    assert "Indication not supplied for this run" in html
    # The summary counts the on-indication denominator, not the whole known set.
    assert "<td>1/1</td>" in html


def test_run_benchmark_rejects_misaligned_indications(tmp_path: Path) -> None:
    """Indications are positional, so a length mismatch must not be scored."""
    known_path = _write_known(tmp_path / "known.tsv")
    run = _make_run_dir(tmp_path / "run1", [("ERBB2", "P04626", 1)])
    with pytest.raises(ValueError, match="tumor_types"):
        run_benchmark(
            [run],
            known_path,
            out_html=tmp_path / "report.html",
            tumor_types=["BRCA", "COAD"],
        )


# ---------------------------------------------------------------------------
# P1 — the indication-matched headline path is unchanged
# ---------------------------------------------------------------------------
# The antigen's *measured* differential expression in each shipped cohort. These
# are inputs: the categories and the headline recall below are derived from them
# by the production code, not copied out of the committed artifact.
_MEASURED_DEG: dict[str, tuple[float, float, bool, int | None]] = {
    "brca_her2": (4.36, 1.7e-59, True, 4),
    "blca": (1.59, 3.9e-03, True, None),
    "prad": (1.32, 3.4e-04, True, None),
    "luad": (0.42, 1.3e-01, False, None),
    "coad": (-0.31, 1.9e-01, False, None),
    "paad": (2.31, 1.3e-01, False, None),
}


def _cohort_result(cohort: R.Cohort) -> dict:
    log2fc, padj, sig, rank = _MEASURED_DEG[cohort.key]
    deg_expected = {"tested": True, "log2fc": log2fc, "padj": padj, "significant": sig}
    achieved = R._sampling_summary(
        _arm("tumor", cohort.requested_n_tumor, "01A")
        + _arm("normal", cohort.requested_n_normal, "11A"),
        [],
    )
    expected = (
        None
        if rank is None
        else {
            "symbol": cohort.expected_symbol,
            "uniprot": cohort.expected_uniprot,
            "found": True,
            "rank": rank,
            "log2fc": log2fc,
            "padj": padj,
        }
    )
    return {
        "cohort": {"key": cohort.key, "label": cohort.label},
        "deg_expected": deg_expected,
        "expected": expected,
        "category": R._categorise(deg_expected, achieved["n_normal"]),
    }


def test_headline_recall_over_the_six_cohort_shape() -> None:
    """The indication-matched headline path still yields 1/3, derived not asserted."""
    results = [_cohort_result(c) for c in R.VALIDATION_COHORTS]

    assert {r["cohort"]["key"]: r["category"] for r in results} == {
        "brca_her2": "over_expressed",
        "blca": "over_expressed",
        "prad": "over_expressed",
        "coad": "not_over_expressed",
        "luad": "not_over_expressed",
        "paad": "underpowered",
    }
    rec = R._aggregate_recall(results)
    # 3 over-expressed antigens; exactly one (ERBB2 at rank 4) inside every k.
    assert rec == {f"recall@{k}": round(1 / 3, 4) for k in R.KS}


# ---------------------------------------------------------------------------
# P2 — achieved cohort sizes are measured, never substituted
# ---------------------------------------------------------------------------
def test_achieved_sampling_refuses_to_substitute_the_requested_sizes() -> None:
    for prov in ({}, {"samples": []}, {"n_tumor": 50, "n_normal": 40}):
        with pytest.raises(ValueError, match="no per-sample record"):
            R._achieved_sampling("coad", prov)


def test_achieved_sampling_measures_the_runs_own_sample_list() -> None:
    """The recorded n_tumor is not evidence; the sample list is."""
    prov = {
        "n_tumor": 50,  # the requested size, echoed by the fetcher
        "n_normal": 40,
        "samples": _arm("tumor", 3, "01A") + _arm("normal", 2, "11A"),
    }
    achieved = R._achieved_sampling("coad", prov)
    assert achieved["n_tumor"] == 3
    assert achieved["n_normal"] == 2
    assert achieved["n_patients_tumor"] == 3
    assert achieved["one_sample_per_patient_per_arm"] is True


def test_rescore_from_runs_fails_loudly_without_run_provenance(tmp_path: Path) -> None:
    """A cached run that cannot say how many samples it used is an error."""
    cohort = {c.key: c for c in R.VALIDATION_COHORTS}["coad"]
    runs_root = tmp_path / "runs"
    _make_run_dir(runs_root / cohort.key, [("CEACAM5", "P06731", 1)])

    with pytest.raises(FileNotFoundError, match=r"gdc_provenance\.json"):
        R.rescore_from_runs(
            out_dir=tmp_path / "out",
            runs_root=runs_root,
            known_path=_write_known(tmp_path / "known.tsv"),
            cohorts=[cohort],
        )


def test_rescore_from_runs_reports_requested_and_achieved_apart(tmp_path: Path) -> None:
    """Requested 50/40 but only 3/2 samples used: both are published, distinctly."""
    cohort = {c.key: c for c in R.VALIDATION_COHORTS}["coad"]
    runs_root = tmp_path / "runs"
    run = _make_run_dir(runs_root / cohort.key, [("CEACAM5", "P06731", 1)])
    (run / "gdc_provenance.json").write_text(
        json.dumps({"samples": _arm("tumor", 3, "01A") + _arm("normal", 2, "11A")}),
        encoding="utf-8",
    )
    out_dir = tmp_path / "out"

    summary = R.rescore_from_runs(
        out_dir=out_dir,
        runs_root=runs_root,
        known_path=_write_known(tmp_path / "known.tsv"),
        cohorts=[cohort],
    )

    (entry,) = summary["cohorts"]
    assert entry["requested"] == {"n_tumor": 50, "n_normal": 40}
    assert entry["achieved"]["n_tumor"] == 3
    assert entry["achieved"]["n_normal"] == 2
    # The top-level counts mirror what the run achieved, not what was asked for.
    assert (entry["n_tumor"], entry["n_normal"]) == (3, 2)
    assert summary["schema"] == "bindsight-validation/2"
    assert "specificity" not in summary

    written = json.loads((out_dir / "results.json").read_text(encoding="utf-8"))
    assert written["cohorts"][0]["achieved"]["n_tumor"] == 3
    md = (out_dir / "RESULTS.md").read_text(encoding="utf-8")
    assert "tumor: got (asked)" in md
    assert "| 3 (50) | 2 (40) |" in md


def test_results_md_warns_about_surviving_pseudo_replication(tmp_path: Path) -> None:
    """A legacy cohort with two aliquots of one patient is named, not glossed."""
    cohort = {c.key: c for c in R.VALIDATION_COHORTS}["coad"]
    runs_root = tmp_path / "runs"
    run = _make_run_dir(runs_root / cohort.key, [("CEACAM5", "P06731", 1)])
    samples = [
        _sample("TCGA-A6-6780", "tumor", "01A"),
        _sample("TCGA-A6-6780", "tumor", "01B"),
        _sample("TCGA-ZZ-N000", "normal", "11A"),
    ]
    (run / "gdc_provenance.json").write_text(json.dumps({"samples": samples}), encoding="utf-8")

    summary = R.rescore_from_runs(
        out_dir=tmp_path / "out",
        runs_root=runs_root,
        known_path=_write_known(tmp_path / "known.tsv"),
        cohorts=[cohort],
    )

    assert summary["cohorts"][0]["achieved"]["one_sample_per_patient_per_arm"] is False
    md = (tmp_path / "out" / "RESULTS.md").read_text(encoding="utf-8")
    assert "Pseudo-replication warning" in md
    assert cohort.label in md


# ---------------------------------------------------------------------------
# I3 — at most one sample per patient per arm
# ---------------------------------------------------------------------------
def test_one_sample_per_patient_drops_the_replicate_aliquot() -> None:
    """TCGA-A6-6780 contributed -01A and -01B to COAD's tumor arm; one survives."""
    a = _sample("TCGA-A6-6780", "tumor", "01A")
    b = _sample("TCGA-A6-6780", "tumor", "01B")
    other = _sample("TCGA-A6-6781", "tumor", "01A")
    kept = ["TCGA-A6-6780-01A", "TCGA-A6-6781-01A"]

    # Deterministic: the lexicographically first aliquot, whatever the input order.
    assert R._one_sample_per_patient([a, b, other]) == kept
    assert R._one_sample_per_patient([b, a, other]) == kept


def test_one_sample_per_patient_keeps_one_sample_in_each_arm() -> None:
    """A patient in both arms contributes to both — the rule is per (patient, arm)."""
    rows = [
        _sample("TCGA-A6-6780", "tumor", "01A"),
        _sample("TCGA-A6-6780", "tumor", "01B"),
        _sample("TCGA-A6-6780", "normal", "11A"),
    ]
    assert R._one_sample_per_patient(rows) == ["TCGA-A6-6780-01A", "TCGA-A6-6780-11A"]


def test_sampling_summary_measures_replication_and_cross_arm_patients() -> None:
    rows = [
        _sample("TCGA-A6-6780", "tumor", "01A"),
        _sample("TCGA-A6-6780", "tumor", "01B"),
        _sample("TCGA-A6-6780", "normal", "11A"),
    ]
    summary = R._sampling_summary(rows, [])
    assert summary["n_tumor"] == 2
    assert summary["n_patients_tumor"] == 1
    assert summary["one_sample_per_patient_per_arm"] is False
    assert summary["n_patients_in_both_arms"] == 1
    assert summary["patients_in_both_arms"] == ["TCGA-A6-6780"]


def test_enforce_one_sample_per_patient_rewrites_counts_and_design(tmp_path: Path) -> None:
    """The replicate leaves counts.tsv.gz, design.tsv and the cohort provenance."""
    rows = [
        _sample("TCGA-A6-6780", "tumor", "01A"),
        _sample("TCGA-A6-6780", "tumor", "01B"),
        _sample("TCGA-A6-6781", "tumor", "01A"),
        _sample("TCGA-ZZ-N000", "normal", "11A"),
    ]
    names = [r["sample"] for r in rows]
    design_path = tmp_path / "design.tsv"
    pd.DataFrame(rows).to_csv(design_path, sep="\t", index=False)
    counts_path = tmp_path / "counts.tsv.gz"
    counts = pd.DataFrame(
        [[10, 11, 12, 13], [20, 21, 22, 23]], index=["ENSG1", "ENSG2"], columns=names
    )
    counts.index.name = "gene_id"
    with gzip.open(counts_path, "wt", newline="") as fh:
        counts.to_csv(fh, sep="\t")
    prov_path = tmp_path / "provenance.json"
    prov = {
        "samples": rows,
        "n_tumor": 3,
        "n_normal": 1,
        "outputs": {"counts.tsv.gz": {"sha256": "stale"}, "design.tsv": {"sha256": "stale"}},
    }

    summary = R._enforce_one_sample_per_patient("coad", counts_path, design_path, prov, prov_path)

    kept = ["TCGA-A6-6780-01A", "TCGA-A6-6781-01A", "TCGA-ZZ-N000-11A"]
    assert summary["dropped_replicate_samples"] == ["TCGA-A6-6780-01B"]
    assert summary["n_tumor"] == 2
    assert summary["one_sample_per_patient_per_arm"] is True
    assert pd.read_csv(design_path, sep="\t")["sample"].tolist() == kept
    with gzip.open(counts_path, "rt") as fh:
        rewritten = pd.read_csv(fh, sep="\t", index_col=0)
    assert list(rewritten.columns) == kept
    assert rewritten.loc["ENSG1", "TCGA-A6-6781-01A"] == 12

    on_disk = json.loads(prov_path.read_text())
    assert on_disk["n_tumor"] == 2
    assert [s["sample"] for s in on_disk["samples"]] == kept
    assert on_disk["outputs"]["counts.tsv.gz"]["sha256"] != "stale"

    # Idempotent: nothing is left to drop, and nothing is rewritten.
    again = R._enforce_one_sample_per_patient("coad", counts_path, design_path, prov, prov_path)
    assert again["dropped_replicate_samples"] == []
    assert pd.read_csv(design_path, sep="\t")["sample"].tolist() == kept


def test_enforce_one_sample_per_patient_requires_the_patient_columns(tmp_path: Path) -> None:
    design_path = tmp_path / "design.tsv"
    pd.DataFrame([{"sample": "s1", "condition": "tumor"}]).to_csv(
        design_path, sep="\t", index=False
    )
    with pytest.raises(ValueError, match="case_barcode"):
        R._enforce_one_sample_per_patient(
            "coad", tmp_path / "counts.tsv.gz", design_path, {}, tmp_path / "provenance.json"
        )


# ---------------------------------------------------------------------------
# L5 — a "real GPU run" claim must be derived from the tarball, not asserted
# ---------------------------------------------------------------------------
def _metric_row(validator: str, iptm: float) -> dict[str, object]:
    row: dict[str, object] = {"binder_id": f"binder_{iptm}", "iptm": iptm, "pae_interaction": 9.1}
    if validator:
        row["validator_name"] = validator
        row["validator_version"] = "2.0.1"
    return row


def _metrics_tarball(path: Path, rows: list[dict[str, object]]) -> Path:
    """A minimal results tarball carrying only ``metrics.jsonl``."""
    body = "".join(json.dumps(r) + "\n" for r in rows).encode()
    with tarfile.open(path, "w:gz") as tf:
        info = tarfile.TarInfo("metrics.jsonl")
        info.size = len(body)
        tf.addfile(info, io.BytesIO(body))
    return path


def _score_run(tar: Path, out: Path) -> subprocess.CompletedProcess[str]:
    # The script puts its own directory on sys.path, not the repo root, so point
    # PYTHONPATH at the checkout to score with *this* bindsight rather than
    # whichever one happens to be installed.
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    return subprocess.run(
        [sys.executable, str(SCORE_RUN), str(tar), "--out", str(out)],
        capture_output=True,
        text=True,
        check=False,
        cwd=ROOT,
        env=env,
    )


@pytest.mark.parametrize(
    ("case", "rows"),
    [
        ("mock", [_metric_row("mock", 0.71), _metric_row("mock", 0.66)]),
        ("mixed", [_metric_row("mock", 0.71), _metric_row("boltz2", 0.66)]),
        ("unstamped", [_metric_row("", 0.71)]),
        ("empty", []),
    ],
)
def test_score_run_refuses_to_publish_an_unproven_run(
    tmp_path: Path, case: str, rows: list[dict[str, object]]
) -> None:
    """No tarball that cannot prove it is a real run may become an artifact."""
    tar = _metrics_tarball(tmp_path / f"{case}.tar.gz", rows)
    out = tmp_path / f"{case}_out"

    proc = _score_run(tar, out)

    assert proc.returncode != 0, proc.stdout
    assert "refusing to claim a real run" in proc.stderr
    assert not out.exists()


def test_score_run_derives_the_validator_from_the_tarball(tmp_path: Path) -> None:
    """A boltz2-stamped tarball scores, and says which facts it derived."""
    tar = _metrics_tarball(
        tmp_path / "real.tar.gz",
        [_metric_row("boltz2", 0.71), _metric_row("boltz2", 0.66)],
    )
    out = tmp_path / "artifact"

    proc = _score_run(tar, out)

    assert proc.returncode == 0, proc.stderr
    data = json.loads((out / "results.json").read_text(encoding="utf-8"))
    assert data["validator"] == "boltz2"
    assert data["validator_version"] == "2.0.1"
    assert data["is_mock"] is False
    assert "derived" in data["provenance_basis"]["is_mock"]
    assert "operator-declared" in data["provenance_basis"]["backend"]
    assert "operator-declared" in data["provenance_basis"]["gpu"]

    md = (out / "RESULTS.md").read_text(encoding="utf-8")
    assert "Real GPU run" not in md
    assert "Not a mock run" in md
    assert "**Operator-declared**" in md

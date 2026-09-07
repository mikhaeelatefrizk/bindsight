# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the committed-benchmark loaders behind the Results page.

Two jobs here. First, pin the published claims. The Results page renders its
numbers straight from ``benchmarks/``, so a silent change to the committed data
would silently change what the project claims. These tests make that change
loud instead.

Second, prove the graceful-degradation contract: ``benchmarks/`` is not shipped
in the wheel, so every loader must return ``None`` rather than raise when the
tree is missing or damaged.
"""

from __future__ import annotations

import json

import pytest

from bindsight.report import showcase


# ---------------------------------------------------------------------------
# Location
# ---------------------------------------------------------------------------
def test_benchmarks_root_found_in_repo() -> None:
    """Running from a clone, the benchmarks tree is discoverable."""
    root = showcase.benchmarks_root()
    assert root is not None
    assert (root / "study").is_dir()
    assert (root / "designer_benchmark").is_dir()


def test_env_override_wins(tmp_path, monkeypatch) -> None:
    """``BINDSIGHT_BENCHMARKS_DIR`` takes precedence over the upward walk."""
    (tmp_path / "study").mkdir()
    monkeypatch.setenv(showcase.ENV_BENCHMARKS_DIR, str(tmp_path))
    assert showcase.benchmarks_root() == tmp_path


def test_env_override_ignored_when_not_a_directory(tmp_path, monkeypatch) -> None:
    """A bad override yields ``None`` rather than a misleading fallback."""
    monkeypatch.setenv(showcase.ENV_BENCHMARKS_DIR, str(tmp_path / "nope"))
    assert showcase.benchmarks_root() is None


# ---------------------------------------------------------------------------
# Rediscovery study
# ---------------------------------------------------------------------------
def test_study_loads() -> None:
    """The committed study results parse into the expected shape."""
    st = showcase.load_study()
    assert st is not None
    assert st.n_scored == 22
    assert st.n_projects == 15
    assert st.surfaceome_size > 4000


def test_study_headline_is_the_best_ranked_antigen() -> None:
    """CA9 ranks first, which is the result the surfaceome extension bought."""
    st = showcase.load_study()
    assert st is not None
    top = st.headline
    assert top is not None
    assert top["symbol"] == "CA9"
    assert top["rank"] == 1
    assert top["log2fc"] > 9


def test_surfaced_antigens_are_ordered_by_rank() -> None:
    st = showcase.load_study()
    assert st is not None
    ranks = [p["rank"] for p in st.surfaced]
    assert ranks == sorted(ranks)
    assert {p["symbol"] for p in st.surfaced} >= {"CA9", "GPC3", "MET", "FOLH1"}


def test_every_row_carries_the_set_its_rank_was_taken_within() -> None:
    """A rank without its shortlist size is not interpretable, so it is never shown alone."""
    st = showcase.load_study()
    assert st is not None
    rows = st.rows()
    assert len(rows) == 22
    for row in rows:
        if row["rank"] is not None:
            assert row["shortlist"], f"{row['antigen']} has a rank with no shortlist size"
        if row["counterfactual_rank"] is not None:
            assert row["eligible"], f"{row['antigen']} has a counterfactual rank with no set"


def test_rows_use_measured_expression_even_when_not_surfaced() -> None:
    """The antigens the study is most careful about are the ones it did not surface."""
    st = showcase.load_study()
    assert st is not None
    rows = {(r["antigen"], r["cohort"]): r for r in st.rows()}
    for key in (("NECTIN4", "BLCA"), ("ERBB2", "BRCA"), ("CLDN18", "ESCA")):
        assert rows[key]["log2fc"] is not None, f"{key} lost its fold change"
        assert rows[key]["rank"] is None
        assert rows[key]["why"], f"{key} must say why it was not surfaced"


def test_every_outcome_class_is_reported_separately() -> None:
    """Four different failures must never be collapsed into one rate."""
    st = showcase.load_study()
    assert st is not None
    counts = st.outcome_counts
    assert set(counts) == {"not_reachable", "gated_out", "ranked", "infrastructure"}
    assert sum(counts.values()) > 0
    # A lookup failure invalidates its pair, so a published run must have none.
    assert counts["infrastructure"] == 0


def test_the_design_records_that_cohorts_are_unstratified() -> None:
    """The circularity the previous study carried must be visibly absent."""
    st = showcase.load_study()
    assert st is not None
    assert "unstratified" in st.design["cohorts"]
    assert "case_barcode" in st.design["contrast"]
    assert "antigen under test" in st.design["admissible_stratifier_rule"]


def test_headline_stats_are_derived_not_hardcoded() -> None:
    labels = {s.label for s in showcase.headline_stats()}
    assert any("surfaced" in label for label in labels)
    values = {s.value for s in showcase.headline_stats()}
    assert any("rank" in v for v in values)


# ---------------------------------------------------------------------------
# Designer benchmark
# ---------------------------------------------------------------------------
def _committed_arm() -> dict:
    """The scored arm from the committed benchmark artifact.

    Read rather than hardcoded. These tests exist to catch a loader that
    silently returns defaults instead of the committed numbers, and pinning the
    figures themselves would only mean editing this file after every re-run —
    which is the drift the artifact-matching tests exist to prevent.
    """
    import json
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "benchmarks/designer_benchmark/results.json"
    if not path.is_file():
        pytest.skip("designer benchmark artifact not present")
    summary = json.loads(path.read_text(encoding="utf-8"))
    arms = [a for a in summary["designers"] if a.get("n_designs")]
    assert arms, "the committed benchmark records no arm with any designs"
    return arms[0]


def test_designer_benchmark_loads_real_designs() -> None:
    """The loader reports the committed run, not mock output or defaults."""
    arm = _committed_arm()
    d = showcase.load_designer_benchmark()
    assert d is not None
    assert d.is_mock is False
    assert d.validator == "boltz2"
    assert d.n_designs == arm["n_designs"]
    assert d.success_rate == pytest.approx(arm["success_rate"])
    # A real GPU run, not a stub: twenty designs is what the protocol produces
    # at ten trajectories, and a loader returning zero would pass a looser check.
    assert d.n_designs >= 20


def test_designer_best_iptm_and_structure() -> None:
    """The best design carries a real predicted complex and a sequence."""
    import json
    from pathlib import Path

    d = showcase.load_designer_benchmark()
    assert d is not None
    best = d.best
    assert best is not None

    metrics = Path(__file__).resolve().parents[1] / (
        "benchmarks/designer_benchmark/binders/metrics.jsonl"
    )
    rows = [json.loads(ln) for ln in metrics.read_text(encoding="utf-8").splitlines() if ln.strip()]
    expected = max(r["iptm"] for r in rows if r.get("iptm") is not None)
    assert best.iptm == pytest.approx(expected, abs=1e-6)

    assert best.complex_cif is not None
    assert best.complex_cif.is_file()
    assert best.sequence
    assert best.sequence.isalpha()


def test_designer_every_scored_design_is_joined() -> None:
    """Metrics, developability, embedding coords and structures all join up."""
    d = showcase.load_designer_benchmark()
    assert d is not None
    assert len(d.scored) == 20
    assert len(d.with_structures()) == 20
    for b in d.binders:
        assert b.developability.get("developability_score") is not None
        assert b.pc1 is not None
        assert b.pc2 is not None


def test_scored_is_sorted_best_first() -> None:
    """``scored`` is ordered by descending ipTM."""
    d = showcase.load_designer_benchmark()
    assert d is not None
    iptms = [b.iptm for b in d.scored]
    assert iptms == sorted(iptms, reverse=True)


# ---------------------------------------------------------------------------
# Headline stats
# ---------------------------------------------------------------------------
def test_headline_stats_derived_not_hardcoded() -> None:
    """The landing-page numbers come from the committed results, not from prose."""
    stats = showcase.headline_stats()
    assert stats
    rendered = " ".join(f"{s.value} {s.label} {s.detail}" for s in stats)
    # The best-ranked antigen and the panel's breadth, both read from the study.
    assert "CA9" in rendered
    assert "rank 1" in rendered
    assert "15 TCGA cohorts" in rendered
    # The retracted claim must not reappear anywhere on the landing page.
    assert "rank 4" not in rendered


# ---------------------------------------------------------------------------
# Graceful degradation — benchmarks/ is not packaged into the wheel
# ---------------------------------------------------------------------------
def test_loaders_return_none_when_tree_absent(tmp_path) -> None:
    """A wheel install has no benchmarks tree; loaders must not raise."""
    assert showcase.load_study(root=tmp_path) is None
    assert showcase.load_designer_benchmark(root=tmp_path) is None


def test_loaders_return_none_on_malformed_json(tmp_path) -> None:
    """Corrupt results files degrade to ``None`` rather than exploding."""
    for sub in ("study", "designer_benchmark"):
        d = tmp_path / sub
        d.mkdir()
        (d / "results.json").write_text("{ not json", encoding="utf-8")
    assert showcase.load_study(root=tmp_path) is None
    assert showcase.load_designer_benchmark(root=tmp_path) is None


def test_designer_tolerates_missing_side_files(tmp_path) -> None:
    """results.json alone is enough; the joined artifacts are all optional."""
    d = tmp_path / "designer_benchmark"
    (d / "binders").mkdir(parents=True)
    (d / "results.json").write_text(
        json.dumps({"validator": "boltz2", "designers": [], "targets": []}),
        encoding="utf-8",
    )
    show = showcase.load_designer_benchmark(root=tmp_path)
    assert show is not None
    assert show.binders == []
    assert show.best is None
    assert show.success_rate is None


def test_headline_stats_empty_without_benchmarks(tmp_path, monkeypatch) -> None:
    """With no benchmarks tree the landing page simply shows no stats."""
    monkeypatch.setenv(showcase.ENV_BENCHMARKS_DIR, str(tmp_path / "missing"))
    assert showcase.headline_stats() == []

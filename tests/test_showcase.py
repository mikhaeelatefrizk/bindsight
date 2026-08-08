# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the committed-benchmark loaders behind the Results page.

Two jobs here. First, pin the published claims: the README, the docs site and
the paper all state that ERBB2 is rediscovered at rank 4 and that the designer
benchmark produced 20 real binders with a best ipTM of 0.84. The Results page
now renders those numbers straight from ``benchmarks/``, so a silent change to
the committed data would silently change the marketing surface. These tests
make that change loud instead.

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
    assert (root / "validation").is_dir()
    assert (root / "designer_benchmark").is_dir()


def test_env_override_wins(tmp_path, monkeypatch) -> None:
    """``BINDSIGHT_BENCHMARKS_DIR`` takes precedence over the upward walk."""
    (tmp_path / "validation").mkdir()
    monkeypatch.setenv(showcase.ENV_BENCHMARKS_DIR, str(tmp_path))
    assert showcase.benchmarks_root() == tmp_path


def test_env_override_ignored_when_not_a_directory(tmp_path, monkeypatch) -> None:
    """A bad override yields ``None`` rather than a misleading fallback."""
    monkeypatch.setenv(showcase.ENV_BENCHMARKS_DIR, str(tmp_path / "nope"))
    assert showcase.benchmarks_root() is None


# ---------------------------------------------------------------------------
# Rediscovery validation
# ---------------------------------------------------------------------------
def test_validation_loads() -> None:
    """The committed rediscovery results parse into the expected shape."""
    v = showcase.load_validation()
    assert v is not None
    assert v.recall_at_k["recall@5"] == pytest.approx(0.3333)
    assert len(v.cohorts) == 6
    assert len(v.figures) == 8
    assert "volcano_brca_her2" in v.figures
    assert "recall_at_k" in v.figures
    assert v.report_html is not None


def test_validation_headline_is_erbb2_at_rank_4() -> None:
    """Pins the sensitivity claim made by the README, docs and paper."""
    v = showcase.load_validation()
    assert v is not None
    top = v.headline
    assert top is not None
    assert top["expected"]["symbol"] == "ERBB2"
    assert top["expected"]["rank"] == 4
    assert top["expected"]["uniprot"] == "P04626"


def test_validation_rows_use_measured_expression() -> None:
    """Fold-change comes from deg_expected, which is populated for every cohort.

    ``expected`` only carries log2fc/padj when the antigen was actually
    surfaced, so reading it alone blanks exactly the antigens the benchmark is
    most careful to report — NECTIN4, FOLH1 and MSLN were not in the shortlist
    but their measured over-expression is the whole point of the disclosure.
    """
    v = showcase.load_validation()
    assert v is not None
    rows = {r["antigen"]: r for r in v.rows()}
    assert len(rows) == 6

    for symbol in ("ERBB2", "CEACAM5", "NECTIN4", "EGFR", "MSLN", "FOLH1"):
        assert rows[symbol]["log2fc"] is not None, f"{symbol} lost its fold-change"
        assert rows[symbol]["padj"] is not None

    assert rows["NECTIN4"]["log2fc"] == pytest.approx(1.59, abs=0.01)
    assert rows["NECTIN4"]["rank"] is None
    assert rows["FOLH1"]["log2fc"] == pytest.approx(1.32, abs=0.01)
    assert rows["ERBB2"]["rank"] == 4


def test_validation_rows_flag_over_expression() -> None:
    """The over-expressed flag mirrors the cohort categorisation."""
    v = showcase.load_validation()
    assert v is not None
    flagged = {r["antigen"] for r in v.rows() if r["over_expressed"]}
    assert flagged == {"ERBB2", "NECTIN4", "FOLH1"}


def test_validation_cohort_partition() -> None:
    """Over-expressed and not-over-expressed cohorts partition the cohort list."""
    v = showcase.load_validation()
    assert v is not None
    assert len(v.over_expressed) + len(v.not_over_expressed) == len(v.cohorts)
    assert v.exclusion_check["consistent"] == v.exclusion_check["n"]


def test_exclusion_check_is_not_presented_as_specificity() -> None:
    """The check is tautological, so it must not be surfaced as a measurement.

    A gene that fails the over-expression rule is excluded from candidacy by that
    same rule, so it can never reach the top-k. Labelling the result
    "specificity" claims the ranking discriminates when nothing was discriminated.
    """
    v = showcase.load_validation()
    assert v is not None
    assert v.exclusion_check["tautological_by_construction"] is True
    labels = {s.label for s in showcase.headline_stats()}
    assert "specificity" not in labels
    assert "consistency check" in labels


# ---------------------------------------------------------------------------
# Designer benchmark
# ---------------------------------------------------------------------------
def test_designer_benchmark_loads_real_designs() -> None:
    """Pins the designer-benchmark claim: 20 real binders, not mock output."""
    d = showcase.load_designer_benchmark()
    assert d is not None
    assert d.is_mock is False
    assert d.n_designs == 20
    assert d.validator == "boltz2"
    assert d.success_rate == pytest.approx(0.5)


def test_designer_best_iptm_and_structure() -> None:
    """The best design carries a real predicted complex and a sequence."""
    d = showcase.load_designer_benchmark()
    assert d is not None
    best = d.best
    assert best is not None
    assert best.iptm == pytest.approx(0.84, abs=0.005)
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
    """The landing-page numbers come from the committed results."""
    stats = showcase.headline_stats()
    assert len(stats) == 4
    rendered = " ".join(f"{s.value} {s.label} {s.detail}" for s in stats)
    assert "ERBB2" in rendered
    assert "rank 4" in rendered
    assert "0.84" in rendered
    assert "50%" in rendered


# ---------------------------------------------------------------------------
# Graceful degradation — benchmarks/ is not packaged into the wheel
# ---------------------------------------------------------------------------
def test_loaders_return_none_when_tree_absent(tmp_path) -> None:
    """A wheel install has no benchmarks tree; loaders must not raise."""
    assert showcase.load_validation(root=tmp_path) is None
    assert showcase.load_designer_benchmark(root=tmp_path) is None


def test_loaders_return_none_on_malformed_json(tmp_path) -> None:
    """Corrupt results files degrade to ``None`` rather than exploding."""
    for sub in ("validation", "designer_benchmark"):
        d = tmp_path / sub
        d.mkdir()
        (d / "results.json").write_text("{ not json", encoding="utf-8")
    assert showcase.load_validation(root=tmp_path) is None
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

# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The study's null models, which were declared and never run.

`bindsight/benchmark/statistics.py` calls `decoy_null_p` "the primary null"
twice in its own source. It had no call site outside tests, and neither did
`match_decoys`, `permutation_null_p` or `benjamini_hochberg`.
`StudyConfig.n_decoys` and `n_permutations` were documented as configuring them
and read by nothing. What the study actually published as inference was three
interval estimators, and the one null that did run — the uniform rank, which the
module itself calls the weakest and cheapest — never reached the human-readable
report at all.

These tests pin the wiring and, just as importantly, the honesty of what it
reports: the resolution floor beside every p, the multiple-testing correction
beside every nominal hit, and the named exclusions beside the panel statistic.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from bindsight.benchmark import outcomes as O
from bindsight.benchmark import study as ST

REPO = Path(__file__).resolve().parents[1]
STUDY = REPO / "benchmarks" / "study"


def _ranking(n: int = 60, *, best_gene: str = "G000", se_cycle: int = 5) -> Any:
    """A synthetic eligible ranking with controllable strata.

    ``se_cycle`` sets how many distinct dispersion values there are, which is
    what controls stratum size: one value puts every gene of a given abundance
    quintile into the same cell, five splits them.
    """
    rows = []
    for i in range(n):
        gene = f"G{i:03d}"
        rows.append(
            {
                "gene_id": gene,
                "log2fc": 5.0 - i * 0.01,
                "padj": 1e-10,
                "baseMean": 100.0 + i,
                "lfc_se": 0.5 + (i % se_cycle) * 0.01,
            }
        )
    deg = pd.DataFrame(rows)
    ordered = O.eligible_ranking(deg, eligible_gene_ids={r["gene_id"] for r in rows})
    assert ordered.iloc[0]["gene_id"] == best_gene
    return ordered


class TestTheDecoyNullRuns:
    """The primary null, over the counterfactual rank so no gate needs matching."""

    def test_the_best_gene_in_its_stratum_lands_on_its_own_floor(self) -> None:
        """No decoy beat it, so p is the smallest the stratum could express."""
        ordered = _ranking()
        out = ST._decoy_null_by_gene(ordered, gene_ids={"G000"}, n_decoys=1000, seed=0)
        result = out["G000"]
        assert result["p_decoy"] == pytest.approx(result["p_decoy_floor"])
        assert result["decoy_exact"] is True

    def test_the_floor_is_reported_so_a_null_is_not_confused_with_a_limit(self) -> None:
        """A p of 0.1 from nine decoys is not a result; it is the whole range."""
        ordered = _ranking()
        out = ST._decoy_null_by_gene(ordered, gene_ids={"G000"}, n_decoys=1000, seed=0)
        result = out["G000"]
        assert result["p_decoy_floor"] == pytest.approx(1 / (1 + result["decoy_n_used"]))
        assert result["decoy_pool_size"] > 0

    def test_a_worse_ranked_gene_gets_a_larger_p(self) -> None:
        ordered = _ranking()
        out = ST._decoy_null_by_gene(ordered, gene_ids={"G000", "G055"}, n_decoys=1000, seed=0)
        assert out["G055"]["p_decoy"] > out["G000"]["p_decoy"]

    def test_the_tail_is_exact_when_the_stratum_fits_under_the_cap(self) -> None:
        """A deterministic rank deserves an exact tail, not Monte Carlo noise."""
        ordered = _ranking()
        out = ST._decoy_null_by_gene(ordered, gene_ids={"G000"}, n_decoys=1000, seed=0)
        assert out["G000"]["decoy_exact"] is True
        assert out["G000"]["decoy_n_used"] == out["G000"]["decoy_pool_size"]

    def test_a_tight_cap_forces_the_sampler_and_says_so(self) -> None:
        """n_decoys is a cap, and when it binds the result stops being exact.

        One dispersion value puts a whole abundance quintile in one cell, so the
        stratum is large enough for the cap to bite.
        """
        ordered = _ranking(se_cycle=1)
        out = ST._decoy_null_by_gene(ordered, gene_ids={"G000"}, n_decoys=3, seed=0)
        assert out["G000"]["decoy_pool_size"] > 3, "the cap never bound; nothing was tested"
        assert out["G000"]["decoy_exact"] is False
        assert out["G000"]["decoy_n_used"] == 3

    def test_missing_strata_columns_collapse_rather_than_drop_genes(self) -> None:
        """A gene with no abundance recorded must still be scored, not vanish."""
        ordered = _ranking().drop(columns=["baseMean", "lfc_se"])
        out = ST._decoy_null_by_gene(ordered, gene_ids={"G000"}, n_decoys=1000, seed=0)
        assert out["G000"]["p_decoy"] is not None
        assert out["G000"]["base_mean_decile"] == -1


class TestTheCorrectionTravelsWithTheNominalHits:
    def test_benjamini_hochberg_is_applied_across_the_panel(self) -> None:
        pairs: list[dict[str, Any]] = [
            {"p_decoy": 0.001},
            {"p_decoy": 0.02},
            {"p_decoy": 0.5},
        ]
        ST._adjust_decoy_p(pairs)
        assert all(p["p_decoy_bh"] >= p["p_decoy"] for p in pairs)
        assert pairs[0]["p_decoy_bh"] < pairs[2]["p_decoy_bh"]

    def test_a_pair_without_a_decoy_p_still_carries_the_column(self) -> None:
        """A missing value must be explicit, not an absent key downstream."""
        pairs: list[dict[str, Any]] = [{"p_decoy": None}, {"p_decoy": 0.01}]
        ST._adjust_decoy_p(pairs)
        assert pairs[0]["p_decoy_bh"] is None
        assert isinstance(pairs[1]["p_decoy_bh"], float)


class TestTheCommittedStudyPublishesItsNulls:
    """The artifact, not the code path."""

    @pytest.fixture(scope="class")
    def summary(self) -> dict[str, Any]:
        path = STUDY / "results.json"
        if not path.is_file():
            pytest.skip("study artifact not present")
        return dict(json.loads(path.read_text(encoding="utf-8")))

    def test_every_scored_pair_carries_a_decoy_p_and_its_floor(
        self, summary: dict[str, Any]
    ) -> None:
        scored = [p for p in summary["pairs"] if p.get("p_decoy") is not None]
        assert scored, "the primary null produced nothing"
        for pair in scored:
            assert 0.0 < pair["p_decoy"] <= 1.0
            assert pair["p_decoy"] >= pair["p_decoy_floor"], (
                "a p below its own resolution floor is impossible"
            )
            assert pair["decoy_pool_size"] > 0

    def test_nominal_hits_carry_their_corrected_value(self, summary: dict[str, Any]) -> None:
        for pair in summary["pairs"]:
            if pair.get("p_decoy") is None:
                continue
            assert isinstance(pair["p_decoy_bh"], float)
            assert pair["p_decoy_bh"] >= pair["p_decoy"]

    def test_the_specificity_null_ran_and_names_what_it_left_out(
        self, summary: dict[str, Any]
    ) -> None:
        spec = summary.get("specificity_null")
        assert spec, "the panel-level specificity null did not run"
        assert 0.0 < spec["p_value"] <= 1.0
        assert spec["n_antigens"] >= 2
        assert spec["n_cohorts"] > spec["n_antigens"], (
            "this panel is non-square, which is the shape the permutation null used to mishandle"
        )
        # The exclusions are the part a reader needs and would not guess.
        assert spec["excluded_multi_indication"]
        assert "CA9" in spec["excluded_not_scored_everywhere"]

    def test_the_written_report_carries_a_null(self) -> None:
        """RESULTS.md published three intervals and no p-value of any kind."""
        path = STUDY / "RESULTS.md"
        if not path.is_file():
            pytest.skip("study report not present")
        text = path.read_text(encoding="utf-8")
        assert "## Null models" in text
        assert "Decoy null" in text
        assert "Benjamini-Hochberg" in text
        assert "floor" in text, "the resolution floor must be explained, not just tabulated"

    def test_the_report_does_not_present_uncorrected_hits_as_findings(self) -> None:
        """Three nominal hits, none surviving correction. Say so."""
        path = STUDY / "RESULTS.md"
        if not path.is_file():
            pytest.skip("study report not present")
        text = path.read_text(encoding="utf-8")
        assert "survive Benjamini-Hochberg" in text


class TestTheNullsAreActuallyWiredIn:
    """The artifact tests above read committed files, so they cannot catch a
    code regression on their own: deleting the wiring leaves yesterday's
    results.json untouched and green. These drive the real path."""

    @staticmethod
    def _run(root: Path, genes: list[str]) -> Path:
        (root / "deg").mkdir(parents=True, exist_ok=True)
        pd.DataFrame(
            [
                {
                    "gene_id": gene,
                    "log2fc": 6.0 - i * 0.1,
                    "padj": 1e-8,
                    "baseMean": 500.0 + i * 3,
                    "lfc_se": 0.4,
                    "significant": True,
                }
                for i, gene in enumerate(genes)
            ]
        ).to_parquet(root / "deg" / "results.parquet", index=False)
        return root

    def test_score_cohort_attaches_a_decoy_p_to_every_pair(self, tmp_path: Path) -> None:
        from bindsight.benchmark import panel as P
        from bindsight.surfaceome.surfy import load_surfy_gene_map

        entry = next(e for e in P.PANEL if e.symbol == "CA9")
        # Decoys must be drawn from the eligible surfaceome, so the filler genes
        # have to be real surfaceome members rather than invented ids.
        surfy = load_surfy_gene_map()
        filler = [g for g in sorted(surfy) if g != entry.ensembl][:80]
        genes = [entry.ensembl, *filler]
        run = self._run(tmp_path / "kirc", genes)

        result = ST.score_cohort(
            entry.project,
            run,
            surfaceome=frozenset({entry.uniprot, *(surfy[g] for g in filler)}),
            entries=[entry],
        )
        assert result.pairs, "no pairs scored"
        assert result.pairs[0]["p_decoy"] is not None, (
            "score_cohort produced no decoy p-value; the primary null is not wired in"
        )
        assert result.pairs[0]["p_decoy_floor"] is not None

    def test_summarise_corrects_and_runs_the_panel_null(self) -> None:
        from bindsight.benchmark import panel as P

        cognate = {e.symbol: e.project for e in P.PANEL}
        first, second = "CA9", "GPC3"
        projects = [cognate[first], cognate[second]]
        results = [
            ST.CohortResult(
                project=project,
                set_sizes={"n_candidates": 10},
                pairs=[
                    {
                        "project": project,
                        "symbol": first if project == cognate[first] else second,
                        "uniprot": "P00000",
                        "outcome_class": "gated_out",
                        "tier": "approved",
                        "rank": None,
                        "shortlist_size": 10,
                        "counts_in_denominator": True,
                        # summarise only scores pairs marked usable.
                        "usable": "scored",
                        "p_decoy": 0.01 if project == cognate[first] else 0.4,
                    }
                ],
                antigen_scores={first: 0.9, second: 0.8}
                if project == cognate[first]
                else {first: 0.2, second: 0.95},
            )
            for project in projects
        ]
        summary = ST.summarise(results, ST.StudyConfig(out_dir=Path("."), n_permutations=500))

        # `all()` over an empty list is vacuously true, so assert there is
        # something to check before checking it.
        assert len(summary["pairs"]) == 2, "no pairs reached the summary"
        assert all(isinstance(p["p_decoy_bh"], float) for p in summary["pairs"]), (
            "summarise did not apply the multiple-testing correction"
        )
        spec = summary.get("specificity_null")
        assert spec is not None, "summarise did not run the panel-level specificity null"
        assert spec["n_antigens"] == 2
        assert 0.0 < spec["p_value"] <= 1.0

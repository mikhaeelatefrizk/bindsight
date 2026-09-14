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
import math
from collections import Counter
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
        assert out["G000"]["base_mean_stratum"] == -1


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
        # This asserted "CA9" in excluded_not_scored_everywhere, which was the
        # bug's own consequence written down as expected behaviour: CA9 was
        # missing from every cohort's eligible set only because that set was
        # built from the SURFY-only gene map while the pipeline ran against the
        # extended one. With the reference corrected, CA9 is scored everywhere
        # and belongs in the test, so the test now pins the property that
        # matters — every excluded antigen is excluded for a stated, checkable
        # reason — rather than one antigen's membership.
        scored = set(spec["antigens"])
        for symbol in spec["excluded_not_scored_everywhere"]:
            assert symbol not in scored, f"{symbol} is listed as excluded and also as scored"
        assert not scored & set(spec["excluded_multi_indication"])
        assert spec["n_antigens"] == len(scored)

    def test_the_specificity_p_value_is_reported_against_its_floor(
        self, summary: dict[str, Any]
    ) -> None:
        """A permutation p sitting on its floor is a ceiling on evidence, not a vanishing one.

        Correcting the eligible surfaceome put this p on the floor for 10,000
        permutations, which is exactly when the difference between "as extreme
        as this many draws can show" and "vanishingly small" stops being
        pedantic.
        """
        spec = summary["specificity_null"]
        floor = spec.get("p_value_floor")
        assert floor is not None, "the permutation floor is not reported"
        assert spec["p_value"] >= floor
        if spec.get("exact"):
            # Enumerated. The identity permutation is always counted, but it is
            # not counted once: antigens sharing a cohort are interchangeable,
            # so every distinct assignment is reproduced by one permutation per
            # ordering within each shared cohort. This panel has FOLH1 and
            # STEAP1 both on PRAD, so the smallest p it can express is 2/5040.
            #
            # Asserting 1/n! here pinned the defect: the published p sat exactly
            # on the true floor while the report claimed a floor half that size,
            # which silenced the "p equals its floor" warning on the one result
            # in the study that is not a negative control. The multiplicity is
            # derived from the committed pairs, so a panel change cannot leave
            # this stale.
            tested = set(spec["antigens"])
            own: dict[str, str] = {}
            for row in summary["pairs"]:
                if row["symbol"] in tested:
                    own.setdefault(row["symbol"], row["project"])
            assert set(own) == tested, sorted(tested - set(own))
            repeats = math.prod(math.factorial(k) for k in Counter(own.values()).values())
            assert floor == pytest.approx(repeats / spec["n_permutations"])
        else:
            assert floor == pytest.approx(1.0 / (spec["n_permutations"] + 1))

    def test_the_floor_actually_accounts_for_a_shared_cohort(self, summary: dict[str, Any]) -> None:
        """Guards the guard: if no antigen shared a cohort the check above would
        reduce to the 1/n! it replaced, and prove nothing."""
        spec = summary["specificity_null"]
        tested = set(spec["antigens"])
        own: dict[str, str] = {}
        for row in summary["pairs"]:
            if row["symbol"] in tested:
                own.setdefault(row["symbol"], row["project"])

        shared = {c: n for c, n in Counter(own.values()).items() if n > 1}

        assert shared, (
            "no tested antigen shares a cohort, so the multiplicity correction is "
            "untested by the committed panel; add a case that exercises it"
        )

    def test_the_specificity_null_is_enumerated_not_sampled(self, summary: dict[str, Any]) -> None:
        """Seven antigens give 5,040 permutations, so there is an exact answer.

        A p-value that can be exact should not carry Monte Carlo error, and the
        distinction matters here: the previous number sat on a *sampling* floor,
        which is what an observation outside its own null looks like.
        """
        spec = summary["specificity_null"]
        assert spec.get("exact") is True
        import math

        assert spec["n_permutations"] == math.factorial(spec["n_antigens"])

    def test_the_observation_is_inside_the_null_it_is_compared_against(
        self, summary: dict[str, Any]
    ) -> None:
        """Two panel antigens share an indication, and the null must allow it.

        FOLH1 and STEAP1 are both single-indication and both TCGA-PRAD. The
        previous null dealt each antigen a distinct cohort, so the observed
        assignment was a zero-probability event under it.
        """
        from bindsight.benchmark import panel as P

        spec = summary["specificity_null"]
        usable = set(spec["antigens"])
        cognate: dict[str, set[str]] = {}
        for c in P.PANEL:
            cognate.setdefault(c.symbol, set()).add(c.project)
        assigned = [next(iter(cognate[s])) for s in sorted(usable)]
        # The panel really does assign one cohort twice; if that ever stops
        # being true this test still passes, but the defect it guards is gone.
        if len(set(assigned)) < len(assigned):
            assert spec["p_value"] > 0.0
            assert spec["p_value"] >= spec["p_value_floor"]

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


class TestTheCalibrationCohortsFinallyDoSomething:
    """`NULL_CALIBRATION_PROJECTS` was declared, downloaded, run, scored — and
    contributed to no reported number. Both cohorts now enter the permutation
    null as assignments an antigen should not fit, and answer directly the
    question recall cannot: where does a panel antigen land in a cancer that is
    not its own?"""

    @pytest.fixture(scope="class")
    def summary(self) -> dict[str, Any]:
        path = STUDY / "results.json"
        if not path.is_file():
            pytest.skip("study artifact not present")
        return dict(json.loads(path.read_text(encoding="utf-8")))

    def test_the_calibration_cohorts_are_reported(self, summary: dict[str, Any]) -> None:
        from bindsight.benchmark import panel as P

        calib = summary.get("null_calibration")
        assert calib, "the null-calibration cohorts still contribute nothing"
        assert set(calib["projects"]) <= set(P.NULL_CALIBRATION_PROJECTS)
        assert calib["n_antigen_standings"] > 0

    def test_no_expectation_is_invented_for_them(self, summary: dict[str, Any]) -> None:
        """They were chosen for carrying no antigen; scoring one would be a fiction."""
        assert summary["null_calibration"]["n_scored_pairs"] == 0

    def test_an_antigen_stands_higher_in_its_own_indication(self, summary: dict[str, Any]) -> None:
        """The calibration's whole point: if these are equal, the ranker is
        surfacing generic biology rather than the right target."""
        calib = summary["null_calibration"]
        assert calib["mean_standing_in_own_indication"] > calib["mean_standing_off_indication"]

    def test_the_report_states_the_comparison(self) -> None:
        path = STUDY / "RESULTS.md"
        if not path.is_file():
            pytest.skip("study report not present")
        text = path.read_text(encoding="utf-8")
        assert "Calibration" in text
        assert "no panel antigen" in text


# ---------------------------------------------------------------------------
# A crashed cohort is not a cohort that found nothing
# ---------------------------------------------------------------------------
class TestTheStageStatusIsReadNotAsserted:
    """`stage_status` was the literal `{"deg": "completed", "discover": "completed"}`.

    A cohort whose discover stage crashed still has its DEG table, so
    `score_cohort`'s only guard passed and the cohort was scored — with an empty
    shortlist, every panel antigen counted as gated out and folded into the
    study's headline recall as a miss, and both stages asserted complete in the
    result.

    The principle was already written down one function below, for the DEG
    table: *a cohort that did not run is not a cohort that found nothing.* It
    was simply not applied to the stage that builds the shortlist.
    """

    @staticmethod
    def _manifest(run: Path, **stages: str) -> Path:
        import json

        run.mkdir(parents=True, exist_ok=True)
        (run / "run_manifest.jsonld").write_text(
            json.dumps({"stages": [{"name": k, "status": v} for k, v in stages.items()]}),
            encoding="utf-8",
        )
        return run

    def test_it_reports_what_the_manifest_recorded(self, tmp_path: Path) -> None:
        from bindsight.benchmark.study import stage_status_from_manifest

        run = self._manifest(tmp_path / "kirc", deg="completed", discover="failed")
        assert stage_status_from_manifest(run) == {"deg": "completed", "discover": "failed"}

    def test_an_absent_manifest_is_not_reported_as_completed(self, tmp_path: Path) -> None:
        """The one answer that must never be invented is the reassuring one."""
        from bindsight.benchmark.study import UNRECORDED_STAGE, stage_status_from_manifest

        run = tmp_path / "bare"
        run.mkdir()
        status = stage_status_from_manifest(run)
        assert set(status.values()) == {UNRECORDED_STAGE}
        assert "completed" not in status.values()

    def test_an_unreadable_manifest_is_not_reported_as_completed(self, tmp_path: Path) -> None:
        from bindsight.benchmark.study import UNRECORDED_STAGE, stage_status_from_manifest

        run = tmp_path / "broken"
        run.mkdir()
        (run / "run_manifest.jsonld").write_text("{not json", encoding="utf-8")
        assert set(stage_status_from_manifest(run).values()) == {UNRECORDED_STAGE}

    def test_a_stage_the_manifest_omits_is_unrecorded(self, tmp_path: Path) -> None:
        from bindsight.benchmark.study import UNRECORDED_STAGE, stage_status_from_manifest

        run = self._manifest(tmp_path / "partial", deg="completed")
        assert stage_status_from_manifest(run)["discover"] == UNRECORDED_STAGE

    def test_a_rerun_stage_supersedes_its_earlier_attempt(self, tmp_path: Path) -> None:
        """Stages are appended in execution order, so the last one is current."""
        import json

        from bindsight.benchmark.study import stage_status_from_manifest

        run = tmp_path / "rerun"
        run.mkdir()
        (run / "run_manifest.jsonld").write_text(
            json.dumps(
                {
                    "stages": [
                        {"name": "discover", "status": "failed"},
                        {"name": "discover", "status": "completed"},
                    ]
                }
            ),
            encoding="utf-8",
        )
        assert stage_status_from_manifest(run)["discover"] == "completed"

    def test_the_unrecorded_sentinel_is_not_a_status_word(self) -> None:
        """It must not be mistakable for one of the manifest's own values."""
        from bindsight.benchmark.study import UNRECORDED_STAGE

        assert UNRECORDED_STAGE not in {
            "running",
            "completed",
            "failed",
            "skipped",
            "skipped_cache",
        }

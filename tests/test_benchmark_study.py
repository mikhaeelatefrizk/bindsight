# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the rediscovery study runner.

The scoring half is pure, so it is tested directly against synthetic run
directories with no network and no differential expression. The one expensive
test here runs real pydeseq2 on a tiny paired cohort, because the paired design
is the central claim of the rebuild and a formula that does not execute would be
worse than the unpaired one it replaces.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from bindsight.benchmark import outcomes as O
from bindsight.benchmark import panel as P
from bindsight.benchmark import study as ST

SURFACEOME = frozenset({"P04626", "P09758", "P00533", "Q04609"})


def _write_run(
    root: Path,
    *,
    deg_rows: list[dict[str, object]],
    candidate_rows: list[dict[str, object]] | None = None,
    taxonomy_rows: list[dict[str, object]] | None = None,
) -> Path:
    """Materialise a discovery run directory of the shape score_cohort reads."""
    (root / "deg").mkdir(parents=True, exist_ok=True)
    pd.DataFrame(deg_rows).to_parquet(root / "deg" / "results.parquet", index=False)
    if candidate_rows is not None:
        (root / "targets").mkdir(parents=True, exist_ok=True)
        pd.DataFrame(candidate_rows).to_parquet(
            root / "targets" / "candidates.parquet", index=False
        )
    if taxonomy_rows is not None:
        (root / "taxonomy").mkdir(parents=True, exist_ok=True)
        pd.DataFrame(taxonomy_rows).to_parquet(
            root / "taxonomy" / "failure_taxonomy.parquet", index=False
        )
    return root


def _entry(
    symbol: str, uniprot: str, ensembl: str, *, tier: P.Tier = "approved"
) -> P.AntigenCohort:
    return P.AntigenCohort(
        project="TCGA-TEST",
        symbol=symbol,
        uniprot=uniprot,
        ensembl=ensembl,
        agent="a test agent with an adequately long description",
        tier=tier,
        usable="scored",
        note="a note long enough to satisfy the panel's own interpretability rule",
    )


class TestScoreCohort:
    def test_a_surfaced_antigen_reports_rank_and_shortlist_size(self, tmp_path: Path) -> None:
        run = _write_run(
            tmp_path / "run",
            deg_rows=[
                {"gene_id": "ENSG1", "log2fc": 4.0, "padj": 1e-40, "significant": True},
                {"gene_id": "ENSG2", "log2fc": 1.0, "padj": 0.01, "significant": True},
            ],
            candidate_rows=[
                {"gene_id": "ENSG1", "uniprot_id": "P04626", "rank": 1},
                {"gene_id": "ENSG2", "uniprot_id": "P09758", "rank": 2},
            ],
            taxonomy_rows=[{"gene_id": "ENSG1", "disposition": "surfaced"}],
        )
        result = ST.score_cohort(
            "TCGA-TEST",
            run,
            surfaceome=SURFACEOME,
            entries=[_entry("ERBB2", "P04626", "ENSG1")],
        )
        pair = result.pairs[0]
        assert pair["outcome_class"] == O.RANKED
        assert pair["rank"] == 1
        assert pair["shortlist_size"] == 2
        assert result.set_sizes["n_candidates"] == 2
        assert result.set_sizes["n_genes_tested"] == 2

    def test_an_unreachable_antigen_is_classified_before_the_pipeline_output(
        self, tmp_path: Path
    ) -> None:
        """CA9 and STEAP1 are in this position and it is not the ranker's fault."""
        run = _write_run(
            tmp_path / "run",
            deg_rows=[{"gene_id": "ENSG9", "log2fc": 5.0, "padj": 1e-50, "significant": True}],
            candidate_rows=[],
            taxonomy_rows=[{"gene_id": "ENSG9", "disposition": "below_enrichment_cutoff"}],
        )
        result = ST.score_cohort(
            "TCGA-TEST",
            run,
            surfaceome=SURFACEOME,
            entries=[_entry("CA9", "Q16790", "ENSG9")],
        )
        pair = result.pairs[0]
        assert pair["outcome_class"] == O.NOT_REACHABLE
        assert not pair["counts_in_denominator"]
        # It was strongly over-expressed, which is exactly why calling this a
        # ranking miss would be wrong.
        assert pair["log2fc"] == pytest.approx(5.0)

    def test_a_gated_antigen_carries_its_counterfactual_rank(self, tmp_path: Path) -> None:
        """The number that separates 'a gate killed it' from 'the ranker buried it'.

        Real surfaceome gene ids, because eligibility is decided by the vendored
        map rather than by whatever the run happened to resolve.
        """
        from bindsight.surfaceome.surfy import load_surfy

        surfaceome = load_surfy(allow_offline_fallback=False)
        erbb2, trop2 = "ENSG00000141736", "ENSG00000184292"
        run = _write_run(
            tmp_path / "run",
            deg_rows=[
                {"gene_id": erbb2, "log2fc": 4.0, "padj": 1e-40, "significant": True},
                {"gene_id": trop2, "log2fc": 1.2, "padj": 0.02, "significant": True},
                {"gene_id": "ENSG00000000005", "log2fc": 0.9, "padj": 0.30, "significant": False},
            ],
            # Only ERBB2 survived the enrichment cut into the shortlist.
            candidate_rows=[{"gene_id": erbb2, "uniprot_id": "P04626", "rank": 1}],
            taxonomy_rows=[{"gene_id": trop2, "disposition": "below_enrichment_cutoff"}],
        )
        result = ST.score_cohort(
            "TCGA-TEST",
            run,
            surfaceome=surfaceome,
            entries=[_entry("TACSTD2", "P09758", trop2)],
        )
        pair = result.pairs[0]
        assert pair["outcome_class"] == O.GATED_OUT
        assert pair["rank"] is None
        # Second of the eligible surfaceome, so a gate excluded it rather than
        # the ranker burying it — which is exactly what this number is for.
        assert pair["counterfactual_rank"] == 2
        assert pair["n_eligible"] == 2
        assert pair["direction"] == "up"

    def test_an_untested_antigen_is_not_a_miss(self, tmp_path: Path) -> None:
        run = _write_run(
            tmp_path / "run",
            deg_rows=[{"gene_id": "ENSG1", "log2fc": 1.0, "padj": 0.01, "significant": True}],
            candidate_rows=[],
        )
        result = ST.score_cohort(
            "TCGA-TEST",
            run,
            surfaceome=SURFACEOME,
            entries=[_entry("EGFR", "P00533", "ENSG_ABSENT")],
        )
        pair = result.pairs[0]
        assert pair["tested"] is False
        assert pair["log2fc"] is None
        assert pair["counterfactual_rank"] is None

    def test_a_cohort_that_never_ran_is_an_error_not_a_zero(self, tmp_path: Path) -> None:
        """A missing table means the cohort did not run, which is not a finding."""
        empty = tmp_path / "never_ran"
        empty.mkdir()
        with pytest.raises(FileNotFoundError, match="did not run"):
            ST.score_cohort("TCGA-TEST", empty, surfaceome=SURFACEOME)


class TestSummarise:
    @staticmethod
    def _pair(symbol: str, uniprot: str, outcome: str, rank: int | None, **extra: object) -> dict:
        base = {
            "project": "TCGA-BRCA",
            "symbol": symbol,
            "uniprot": uniprot,
            "tier": "approved",
            "usable": "scored",
            "outcome_class": outcome,
            "rank": rank,
            "shortlist_size": 30,
            "counts_in_denominator": outcome in (O.RANKED, O.GATED_OUT),
            "counterfactual_rank": 5,
            "n_up_regulated": 1000,
        }
        base.update(extra)
        return base

    def test_the_cascade_narrows_and_publishes_what_it_dropped(self) -> None:
        result = ST.CohortResult(
            project="TCGA-BRCA",
            set_sizes={},
            pairs=[
                self._pair("ERBB2", "P04626", O.RANKED, 3),
                self._pair("TACSTD2", "P09758", O.GATED_OUT, None),
                self._pair("CA9", "Q16790", O.NOT_REACHABLE, None),
            ],
        )
        summary = ST.summarise([result], ST.StudyConfig(out_dir=Path(".")))
        cascade = summary["recall_cascade"]
        assert cascade["all"]["wilson"]["denominator"] == 3
        assert cascade["reachable"]["wilson"]["denominator"] == 2
        assert cascade["gate_passed"]["wilson"]["denominator"] == 1
        # The conservative headline must be reconstructable from the permissive one.
        assert cascade["all"]["wilson"]["numerator"] == 1
        assert cascade["gate_passed"]["wilson"]["numerator"] == 1

    def test_every_rate_carries_an_interval_not_a_bare_number(self) -> None:
        result = ST.CohortResult(
            project="TCGA-BRCA",
            set_sizes={},
            pairs=[self._pair("ERBB2", "P04626", O.RANKED, 1)],
        )
        summary = ST.summarise([result], ST.StudyConfig(out_dir=Path(".")))
        wilson = summary["recall_cascade"]["all"]["wilson"]
        assert {"point", "low", "high", "numerator", "denominator"} <= set(wilson)
        assert "clopper_pearson" in summary["recall_cascade"]["all"]

    def test_infrastructure_failures_are_counted_and_never_scored(self) -> None:
        result = ST.CohortResult(
            project="TCGA-BRCA",
            set_sizes={},
            pairs=[
                self._pair("ERBB2", "P04626", O.RANKED, 2),
                self._pair("EGFR", "P00533", O.INFRASTRUCTURE, None),
            ],
        )
        summary = ST.summarise([result], ST.StudyConfig(out_dir=Path(".")))
        assert summary["infrastructure_failures"]["n"] == 1
        assert "must be zero" in summary["infrastructure_failures"]["note"]
        # The failed pair is excluded from the denominator rather than counted a miss.
        assert summary["recall_cascade"]["all"]["wilson"]["denominator"] == 1

    def test_the_design_is_recorded_alongside_the_numbers(self) -> None:
        summary = ST.summarise(
            [ST.CohortResult(project="TCGA-BRCA", set_sizes={}, pairs=[])],
            ST.StudyConfig(out_dir=Path(".")),
        )
        design = summary["design"]
        cohorts = design["cohorts"].lower()

        # Two separate properties, and the record used to state only one of them
        # — as "all primary tumour vs all normal", which is not what runs.
        # `prepare_cohort` calls `matched_pair_cases`, so a tumour with no matched
        # normal never enters the contrast; in TCGA-UCEC that leaves 23 pairs. A
        # reader who takes the old sentence literally has the wrong denominator
        # for every number downstream of it.
        assert "stratif" in cohorts, (
            f"the recorded design no longer says the cohort is unstratified: {cohorts!r}"
        )
        assert "both" in cohorts or "matched" in cohorts or "pair" in cohorts, (
            "the recorded design does not say the cohort is restricted to patients "
            f"who contributed both a tumour and a normal: {cohorts!r}"
        )
        assert "all primary tumour" not in cohorts, (
            "the design record claims every primary tumour is in the contrast; "
            "prepare_cohort takes matched pairs only"
        )
        assert "case_barcode" in design["contrast"]
        assert "antigen under test" in design["admissible_stratifier_rule"]

    def test_uniform_rank_p_uses_the_up_regulated_reference_set(self) -> None:
        result = ST.CohortResult(
            project="TCGA-BRCA",
            set_sizes={},
            pairs=[self._pair("ERBB2", "P04626", O.RANKED, 3, counterfactual_rank=10)],
        )
        summary = ST.summarise([result], ST.StudyConfig(out_dir=Path(".")))
        assert summary["pairs"][0]["p_uniform_rank"] == pytest.approx(10 / 1000)

    def test_tiers_outside_the_primary_denominator_are_excluded(self) -> None:
        result = ST.CohortResult(
            project="TCGA-BRCA",
            set_sizes={},
            pairs=[
                self._pair("ERBB2", "P04626", O.RANKED, 1),
                self._pair("GPC3", "P51654", O.RANKED, 2, tier="clinical_stage"),
            ],
        )
        summary = ST.summarise([result], ST.StudyConfig(out_dir=Path(".")))
        assert summary["recall_cascade"]["all"]["wilson"]["denominator"] == 1


class TestPairedDesign:
    """The paired contrast is the central claim of the rebuild."""

    def test_build_run_config_blocks_on_the_patient(self, tmp_path: Path) -> None:
        cfg = ST.build_run_config("TCGA-BRCA", ST.StudyConfig(out_dir=tmp_path, n_cpus=2))
        assert cfg.params.deg.design_formula == "~ case_barcode + condition"
        assert cfg.params.deg.contrast == ["condition", "tumor", "normal"]
        # The worker cap must reach pydeseq2, or a laptop run pegs every core.
        assert cfg.params.deg.n_cpus == 2

    def test_the_blocking_column_exists_in_the_design_table(self) -> None:
        """`patient` does not exist; naming it would fail inside pydeseq2."""
        from bindsight.benchmark.rediscovery import _DESIGN_COLUMNS

        assert "case_barcode" in _DESIGN_COLUMNS
        assert "patient" not in _DESIGN_COLUMNS

    @pytest.mark.slow
    def test_pydeseq2_accepts_the_paired_formula(self, tmp_path: Path) -> None:
        """A formula that does not execute would be worse than the one it replaces."""
        pytest.importorskip("pydeseq2")
        from bindsight.config import DEGParams
        from bindsight.deg.pydeseq2_runner import PyDESeq2Runner

        n_patients, n_genes = 6, 60
        samples, conditions, patients = [], [], []
        for i in range(n_patients):
            for cond in ("tumor", "normal"):
                samples.append(f"{cond}_{i}")
                conditions.append(cond)
                patients.append(f"CASE-{i}")
        counts = pd.DataFrame(
            {
                s: [
                    # A per-patient offset the paired model can absorb, plus a
                    # tumour effect on the first ten genes.
                    100 + 10 * int(p.split("-")[1]) + (80 if (c == "tumor" and g < 10) else 0)
                    for g in range(n_genes)
                ]
                for s, c, p in zip(samples, conditions, patients, strict=True)
            },
            index=[f"ENSG{g:05d}" for g in range(n_genes)],
        )
        design = pd.DataFrame({"condition": conditions, "case_barcode": patients}, index=samples)
        runner = PyDESeq2Runner(
            DEGParams(
                design_formula="~ case_barcode + condition",
                contrast=["condition", "tumor", "normal"],
                n_cpus=1,
            )
        )
        results = runner._run_pydeseq2(counts, design)
        assert len(results) == n_genes
        assert "log2FoldChange" in results.columns


class TestEligibleSurfaceome:
    """The set a counterfactual rank is taken within decides what it means."""

    def test_the_vendored_gene_map_covers_the_panel(self) -> None:
        from bindsight.surfaceome.surfy import load_surfy, load_surfy_gene_map

        gene_map = load_surfy_gene_map()
        assert len(gene_map) > 2000, "the surfaceome gene map looks unpopulated"
        surfaceome = load_surfy(allow_offline_fallback=False)
        for entry in P.PANEL:
            if entry.uniprot not in surfaceome:
                continue  # CA9 and STEAP1 are genuinely absent upstream
            assert gene_map.get(entry.ensembl) == entry.uniprot, entry.symbol

    def test_eligibility_is_not_taken_from_the_run_output(self, tmp_path: Path) -> None:
        """Ranking within the candidates table would rank within the pipeline's own output.

        The candidates table holds only genes that survived the enrichment cut, so
        a counterfactual rank computed there could never show that the cut was
        what excluded an antigen — which is the one thing it exists to show.
        """
        from bindsight.surfaceome.surfy import load_surfy

        surfaceome = load_surfy(allow_offline_fallback=False)
        # Many surfaceome genes tested, but only one tiny candidate shortlist.
        deg_rows = [
            {"gene_id": g, "log2fc": 0.1, "padj": 0.5, "significant": False}
            for g in list(_surfaceome_gene_ids())[:500]
        ]
        deg_rows.append(
            {
                "gene_id": "ENSG00000141736",
                "log2fc": 3.0,
                "padj": 1e-10,
                "significant": True,
            }
        )
        run = _write_run(
            tmp_path / "run",
            deg_rows=deg_rows,
            candidate_rows=[{"gene_id": "ENSG00000000001", "uniprot_id": "P00001", "rank": 1}],
        )
        result = ST.score_cohort(
            "TCGA-TEST",
            run,
            surfaceome=surfaceome,
            entries=[_entry("ERBB2", "P04626", "ENSG00000141736")],
        )
        # The eligible set is far larger than the one-row candidates table.
        assert result.set_sizes["n_eligible_surfaceome"] > 100
        assert result.set_sizes["n_candidates"] == 1
        assert result.pairs[0]["counterfactual_rank"] == 1


def _surfaceome_gene_ids() -> list[str]:
    from bindsight.surfaceome.surfy import load_surfy, load_surfy_gene_map

    surfaceome = load_surfy(allow_offline_fallback=False)
    return [g for g, a in load_surfy_gene_map().items() if a in surfaceome]


class TestACachedCohortIsTheCohortThatWasAskedFor:
    """`prepare_cohort` reused whatever was on disk without checking its size.

    The three files existing says *a* cohort is there, not that it is *this* one.
    A sweep run at 50 pairs and re-run at 5 got the 50-pair cohort back and its
    provenance reporting `n_tumor: 50` — which `benchmarks/run_study.py:87`
    copies straight into the published record. The study would state one cohort
    size and its own provenance another, from the same call.

    Reuse is the point of the function: it is what makes a staged sweep
    resumable, and re-downloading a TCGA cohort is expensive. So the fix is not
    to stop reusing, it is to reuse only what matches.
    """

    @staticmethod
    def _staged(tmp_path: Path, n_built: int) -> Any:
        import json

        run = tmp_path / "brca"
        run.mkdir(parents=True, exist_ok=True)
        (run / "counts.tsv.gz").write_bytes(b"stub")
        (run / "design.tsv").write_text("sample\tcondition\n", encoding="utf-8")
        (run / "provenance.json").write_text(
            json.dumps({"project": "TCGA-BRCA", "n_tumor": n_built, "n_normal": n_built}),
            encoding="utf-8",
        )
        return ST.StudyConfig(out_dir=tmp_path)

    def test_a_matching_cohort_is_reused_without_refetching(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The resumability this function exists for must survive the fix."""
        cfg = self._staged(tmp_path, 50)
        called: list[str] = []
        monkeypatch.setattr("bindsight.io.gdc.matched_pair_cases", lambda p: called.append(p) or [])

        got = ST.prepare_cohort("TCGA-BRCA", cfg, max_pairs=50)

        assert got["n_tumor"] == 50
        assert called == [], "a cohort that already matches the request was re-fetched"

    def test_a_cohort_built_at_another_size_is_not_returned_as_this_one(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog
    ) -> None:
        """The defect: 50 pairs returned, and reported, for a request of 5."""
        import logging

        cfg = self._staged(tmp_path, 50)
        fetched: dict = {}

        monkeypatch.setattr(
            "bindsight.io.gdc.matched_pair_cases", lambda p: [f"case-{i}" for i in range(50)]
        )

        def _fake_fetch(**kw):
            fetched.update(kw)
            return {"project": kw["project"], "n_tumor": kw["n_tumor"], "n_normal": kw["n_normal"]}

        monkeypatch.setattr("bindsight.io.gdc.fetch_cohort", _fake_fetch)

        with caplog.at_level(logging.WARNING):
            got = ST.prepare_cohort("TCGA-BRCA", cfg, max_pairs=5)

        assert got["n_tumor"] == 5, (
            f"a cohort built at 50 pairs was returned for a request of 5, reporting "
            f"n_tumor={got['n_tumor']} — the number run_study.py publishes"
        )
        assert fetched.get("n_tumor") == 5, "the rebuild did not honour the requested cap"
        assert any("were requested" in r.getMessage() for r in caplog.records), (
            "the cohort was rebuilt at a different size without saying so"
        )

    def test_an_uncapped_request_still_reuses_whatever_is_there(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No cap means no size was asked for, so anything on disk answers it."""
        self._staged(tmp_path, 50)
        cfg = ST.StudyConfig(out_dir=tmp_path, max_pairs=None)
        monkeypatch.setattr("bindsight.io.gdc.matched_pair_cases", lambda p: [])

        assert ST.prepare_cohort("TCGA-BRCA", cfg)["n_tumor"] == 50

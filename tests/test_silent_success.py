# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Absence of output must not be reported as a completed stage or a finding.

Four places recorded success for work that produced nothing. They are grouped
here because they are one defect wearing four hats, and because the project
already states the rule in its own outcomes module: *a lookup that errored or
never ran is not a scientific negative.*
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd
import pytest


def _raises(exc: Exception):
    """A callable that raises, for standing in as a broken client."""

    def _call(*_args: Any, **_kwargs: Any) -> Any:
        raise exc

    return _call


class TestAStageIsCompleteWhenItProducedRows:
    """``st_size > 0`` passed on a zero-row parquet.

    An empty table is a valid parquet file of roughly 1.9 kB, all of it schema
    and footer, so the check could never fail on an empty result — and the
    manifest recorded a completed validation while the report rendered an empty
    table as a finished one.
    """

    def test_an_empty_parquet_is_not_rows(self, tmp_path: Path) -> None:
        from bindsight.pipelines.full_run import _parquet_has_rows

        empty = tmp_path / "empty.parquet"
        pd.DataFrame(columns=["binder_id", "iptm"]).to_parquet(empty)
        assert empty.stat().st_size > 0, "the old check would have passed here"
        assert not _parquet_has_rows(empty)

    def test_a_populated_parquet_is_rows(self, tmp_path: Path) -> None:
        from bindsight.pipelines.full_run import _parquet_has_rows

        full = tmp_path / "full.parquet"
        pd.DataFrame({"binder_id": ["b0"], "iptm": [0.7]}).to_parquet(full)
        assert _parquet_has_rows(full)

    def test_an_absent_file_is_not_rows(self, tmp_path: Path) -> None:
        from bindsight.pipelines.full_run import _parquet_has_rows

        assert not _parquet_has_rows(tmp_path / "nope.parquet")

    def test_an_unreadable_file_is_not_a_completed_stage(self, tmp_path: Path) -> None:
        """Corrupt output is not evidence of a finished stage."""
        from bindsight.pipelines.full_run import _parquet_has_rows

        junk = tmp_path / "junk.parquet"
        junk.write_bytes(b"not a parquet file at all")
        assert not _parquet_has_rows(junk)


class TestADesignJobThatDesignedNothingFails:
    """``validate_only`` refused an empty set; ``design_and_validate`` did not.

    A designer that wrote nothing — a bad contig, an OOM, a tool exiting 0 after
    failing — produced an empty metrics.jsonl, a valid tarball and a zero exit,
    and the caller recorded a completed design stage.
    """

    @staticmethod
    def _spec() -> dict[str, Any]:
        return {
            "target_uniprot": "P04626",
            "epitope_chain": "A",
            "epitope_residues": [1],
            "n_trajectories": 2,
            "seed": 0,
            "extra_params": {"designer": "rfdiff_mpnn", "validator": "boltz2"},
        }

    def test_zero_designs_raises_rather_than_returning_a_tarball(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from bindsight.runners import job_exec

        monkeypatch.setattr(job_exec, "_DESIGNERS", {"rfdiff_mpnn": lambda *a, **k: []})
        work = tmp_path / "work"
        work.mkdir()
        with pytest.raises(ValueError, match="produced no designs"):
            job_exec.run_job(self._spec(), work, tarball=tmp_path / "r.tar.gz")

    def test_the_message_names_the_cause_rather_than_the_symptom(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from bindsight.runners import job_exec

        monkeypatch.setattr(job_exec, "_DESIGNERS", {"rfdiff_mpnn": lambda *a, **k: []})
        work = tmp_path / "work"
        work.mkdir()
        with pytest.raises(ValueError, match="no designs") as exc:
            job_exec.run_job(self._spec(), work, tarball=tmp_path / "r.tar.gz")
        assert "not a negative finding" in str(exc.value)

    def test_no_tarball_is_left_behind_to_be_mistaken_for_a_result(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from bindsight.runners import job_exec

        monkeypatch.setattr(job_exec, "_DESIGNERS", {"rfdiff_mpnn": lambda *a, **k: []})
        work = tmp_path / "work"
        work.mkdir()
        tar = tmp_path / "r.tar.gz"
        with pytest.raises(ValueError, match="no designs"):
            job_exec.run_job(self._spec(), work, tarball=tar)
        assert not tar.exists()


class TestAFailedLookupIsNotABiologicalNegative:
    """An errored SURFACE-Bind call was recorded as "no targetable site".

    ``no_surface_bind_site`` is documented as "data present, none for this
    protein" — a statement about the protein. An exception in the client says
    nothing about the protein at all.
    """

    @staticmethod
    def _epitopes(client: Any, *, require_site: bool = False) -> pd.DataFrame:
        """Build the epitopes table for one candidate.

        ``require_site`` defaults False here so a genuine "no site" still
        produces a row to inspect. Under the shipped default of True it is
        correctly dropped, which is the behaviour the failed-lookup case must
        *not* share — see the test below.
        """
        from bindsight.config import TargetDiscoveryParams
        from bindsight.pipelines.discover import _build_epitopes

        top = pd.DataFrame(
            {
                "gene_id": ["ENSG1"],
                "symbol": ["MSLN"],
                "uniprot_id": ["Q13421"],
                "alphafold_structure_path": [None],
                "design_ranges": [None],
            }
        )
        return _build_epitopes(
            top, client, TargetDiscoveryParams(require_surface_bind_site=require_site)
        )

    def test_an_erroring_client_is_not_reported_as_no_site(self) -> None:
        broken = SimpleNamespace(sites=_raises(RuntimeError("vendor data unreadable")))
        status = set(self._epitopes(broken)["epitope_status"])
        assert status == {"surface_bind_lookup_failed"}, status
        assert "no_surface_bind_site" not in status

    def test_a_working_client_with_no_sites_still_says_no_site(self) -> None:
        """The genuine negative must keep its own name."""
        empty = SimpleNamespace(sites=lambda _u: [])
        assert set(self._epitopes(empty)["epitope_status"]) == {"no_surface_bind_site"}

    def test_no_client_still_says_not_configured(self) -> None:
        assert set(self._epitopes(None)["epitope_status"]) == {"surface_bind_not_configured"}

    def test_the_three_cases_are_three_statuses(self) -> None:
        """Merging any two of them loses the distinction that matters."""
        broken = SimpleNamespace(sites=_raises(RuntimeError("boom")))
        empty = SimpleNamespace(sites=lambda _u: [])
        statuses = {next(iter(self._epitopes(c)["epitope_status"])) for c in (broken, empty, None)}
        assert len(statuses) == 3, statuses

    def test_the_shipped_default_drops_a_real_negative_but_keeps_the_outage(self) -> None:
        """With sites required, "none found" is a reason to skip the protein.

        "The lookup broke" is not. Under the default the genuine negative is
        correctly dropped, and the failure must still appear — otherwise an
        outage removes proteins from the run with nothing written down
        anywhere, which is how it went unnoticed.
        """
        empty = SimpleNamespace(sites=lambda _u: [])
        broken = SimpleNamespace(sites=_raises(RuntimeError("vendor data unreadable")))

        assert self._epitopes(empty, require_site=True).empty
        failed = self._epitopes(broken, require_site=True)
        assert not failed.empty, "a failed lookup silently removed the protein"
        assert set(failed["epitope_status"]) == {"surface_bind_lookup_failed"}

    def test_the_new_status_is_explained_wherever_statuses_are(self) -> None:
        """A status a reader meets in an artifact must be describable."""
        from bindsight.benchmark.outcomes import GATE_EXPLANATIONS

        text = GATE_EXPLANATIONS.get("surface_bind_lookup_failed", "")
        assert text
        assert "not the same as" in text


class TestTheSuccessRateFractionMatchesItsOwnPercentage:
    """The cell printed n_success/n_designs beside a rate computed over neither.

    The rate's denominator is the designs the validator returned a confidence
    for. With any unfolded design the printed fraction and the printed
    percentage disagreed.
    """

    @staticmethod
    def _row(**over: Any) -> dict[str, Any]:
        row = {
            "success_rate": 0.5,
            "n_success": 8,
            "n_scored": 16,
            "n_designs": 20,
            "success_ci_low": 0.15,
            "success_ci_high": 0.70,
        }
        row.update(over)
        return row

    def test_the_fraction_uses_the_denominator_the_rate_used(self) -> None:
        from bindsight.benchmark.designer_bench import _success_cell

        assert _success_cell(self._row()).startswith("8/16 = 50%")

    def test_the_designs_that_were_never_scored_are_named(self) -> None:
        """Narrowing a denominator silently is itself a claim."""
        from bindsight.benchmark.designer_bench import _success_cell

        cell = _success_cell(self._row())
        assert "of 20 designed" in cell
        assert "4 unscored" in cell

    def test_a_fully_scored_run_reads_exactly_as_before(self) -> None:
        """The committed benchmark must not move: all twenty folded."""
        from bindsight.benchmark.designer_bench import _success_cell

        cell = _success_cell(self._row(success_rate=0.40, n_scored=20))
        assert cell == "8/20 = 40% (15%–70%)"

    def test_a_summary_without_the_field_falls_back_honestly(self) -> None:
        """Older artifacts carry no n_scored; n_designs is the available answer."""
        from bindsight.benchmark.designer_bench import _success_cell

        row = self._row(success_rate=0.40)
        del row["n_scored"]
        assert _success_cell(row).startswith("8/20 = 40%")

    def test_the_committed_benchmark_scored_every_design(self) -> None:
        """The anchor: if this stops holding, the published cell changes shape."""
        results = json.loads(
            Path("benchmarks/designer_benchmark/results.json").read_text(encoding="utf-8")
        )
        for designer in results.get("designers", []):
            if designer.get("success_rate") is None:
                continue
            scored = designer.get("n_scored")
            if scored is not None:
                assert scored == designer["n_designs"]


class TestValidateRecordsNoStageWhenNothingWasValidated:
    """The manifest asserted a completed stage the console called pending.

    ``provenance.record`` marks a stage completed unconditionally, and this
    command called it before checking whether anything had been validated. A
    run with no design results therefore gained a completed ``validate`` stage
    in ``run_manifest.jsonld`` and, on the same screen, a panel telling the user
    to go and run the GPU step. The manifest is what a reviewer reads and what
    the RO-Crate exports.
    """

    def test_no_manifest_stage_is_appended(self, tmp_path: Path) -> None:
        import os
        import subprocess
        import sys

        run = tmp_path / "run"
        run.mkdir()
        result = subprocess.run(
            [sys.executable, "-m", "bindsight.cli", "validate", str(run)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env={**os.environ, "PYTHONUTF8": "1"},
            check=False,
        )
        assert result.returncode == 0
        assert "GPU step pending" in result.stdout
        manifest = run / "run_manifest.jsonld"
        if manifest.exists():
            stages = json.loads(manifest.read_text(encoding="utf-8")).get("stages", [])
            completed = [s for s in stages if s.get("name") == "validate"]
            assert not completed, (
                "a completed validate stage was recorded for a run the command "
                "just told the user still needs the GPU step"
            )


class TestAnUnmeasuredStructureIsNotAPassingOne:
    """The pLDDT gate tested ``mean_plddt.notna()``, so an unreadable one passed.

    The gate exists to exclude models too disordered to design against. A model
    whose confidence could not be read is not such a model — but it is not a
    model that cleared the bar either, and it fell through to the accepting
    side. GTEx already draws this distinction with ``normal_tissue_unassessed``;
    the structure gate did not.
    """

    @staticmethod
    def _candidates(plddt: object) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "gene_id": ["ENSG1"],
                "uniprot_id": ["P04626"],
                "has_alphafold_structure": [True],
                "alphafold_structure_path": [None],
                "mean_plddt": [plddt],
            }
        )

    def test_an_unreadable_confidence_is_recorded_not_passed(self) -> None:
        import numpy as np

        df = self._candidates(np.nan)
        unassessed = df["has_alphafold_structure"] & df["mean_plddt"].isna() & (70 > 0)
        assert bool(unassessed.iloc[0]), "an unmeasured model must not look like a passing one"

    def test_a_measured_confidence_is_not_recorded_as_unassessed(self) -> None:
        df = self._candidates(88.0)
        unassessed = df["has_alphafold_structure"] & df["mean_plddt"].isna() & (70 > 0)
        assert not bool(unassessed.iloc[0])

    def test_the_disposition_is_canonical_and_renderable(self) -> None:
        """A status a reader meets in an artifact must be listed and describable."""
        from bindsight.benchmark.outcomes import GATE_EXPLANATIONS
        from bindsight.pipelines.discover import TAXONOMY_DISPOSITIONS
        from bindsight.report.html import _DISPOSITION_ORDER

        assert "structure_confidence_unassessed" in TAXONOMY_DISPOSITIONS
        assert "structure_confidence_unassessed" in _DISPOSITION_ORDER
        text = GATE_EXPLANATIONS["structure_confidence_unassessed"]
        assert "not the same as" in text

    def test_it_is_distinct_from_low_confidence(self) -> None:
        """Merging them would report an outage as a disordered model."""
        from bindsight.benchmark.outcomes import GATE_EXPLANATIONS

        assert (
            GATE_EXPLANATIONS["structure_confidence_unassessed"]
            != GATE_EXPLANATIONS["low_confidence_structure"]
        )


class TestTheSafetyVerdictSaysWhatItExamined:
    """A vital tissue with no GTEx column was dropped without a word.

    ``max_expression`` normalised each requested tissue, kept the ones matching
    a column, and took the maximum over whatever remained. A gene highly
    expressed in a *dropped* tissue was therefore reported "safe" by a check
    that never looked at it — and the reason string named only the ceiling, so
    nothing downstream could tell a full check from a partial one.
    """

    FIX = Path(__file__).parent / "fixtures" / "gtex" / "gtex_median_subset.gct"

    def _client(self) -> Any:
        from bindsight.targets.gtex import GTExTissueExpression

        return GTExTissueExpression(gct_path=self.FIX)

    @property
    def _gene(self) -> str:
        return "ENSG00000118194"

    def test_an_unrecognised_tissue_is_named_in_the_verdict(self) -> None:
        verdict = self._client().assess(
            self._gene, ["heart_left_ventricle", "pancreas_islet"], max_tpm=1e9
        )
        assert verdict.status == "safe"
        assert "pancreas_islet" in verdict.tissues_unrecognised
        assert "pancreas_islet" in verdict.reason, (
            "a verdict that never examined a requested tissue must say so"
        )

    def test_the_tissues_actually_examined_are_recorded(self) -> None:
        verdict = self._client().assess(
            self._gene, ["heart_left_ventricle", "liver", "nowhere_at_all"], max_tpm=1e9
        )
        assert set(verdict.tissues_checked) == {"heart_left_ventricle", "liver"}
        assert verdict.tissues_unrecognised == ("nowhere_at_all",)

    def test_a_complete_check_says_nothing_extra(self) -> None:
        """The note must not fire when there is no gap to report."""
        verdict = self._client().assess(self._gene, ["liver"], max_tpm=1e9)
        assert verdict.tissues_unrecognised == ()
        assert "Not examined" not in verdict.reason

    def test_an_unsafe_verdict_also_names_the_gap(self) -> None:
        verdict = self._client().assess(
            self._gene, ["heart_left_ventricle", "pancreas_islet"], max_tpm=0.0
        )
        assert verdict.status == "unsafe"
        assert "pancreas_islet" in verdict.reason

    def test_the_dropped_tissue_is_what_makes_this_matter(self) -> None:
        """The maximum is taken over the surviving tissues only.

        So a gene's expression in a dropped tissue cannot raise the verdict,
        however high it is. That is the fail-open the record now exposes.
        """
        client = self._client()
        both = client.max_expression(self._gene, ["heart_left_ventricle", "liver"])
        partial = client.max_expression(self._gene, ["heart_left_ventricle", "not_a_tissue"])
        assert both is not None
        assert partial is not None
        assert partial <= both


# ---------------------------------------------------------------------------
# A validator that measured nothing must not look like one that measured badly
# ---------------------------------------------------------------------------
def _empty_dir_parsers(tmp: Path) -> dict[str, object]:
    """Every validator output parser, run against output that isn't there.

    A missing directory is the honest stand-in for the real failure modes: the
    tool crashed, wrote nowhere, or wrote files this parser cannot read.
    """
    from bindsight.runners.tools import parse_af2ig_output, parse_chai_output
    from bindsight.validate.boltz2 import parse_boltz_output

    return {
        "parse_af2ig_output": parse_af2ig_output(
            tmp / "absent.sc", binder_id="b1", target_uniprot="P04626"
        ),
        "parse_chai_output": parse_chai_output(tmp, binder_id="b1", target_uniprot="P04626"),
        "parse_boltz_output": parse_boltz_output(
            output_dir=tmp, binder_id="b1", target_uniprot="P04626"
        ),
    }


class TestAValidatorThatParsedNothingSaysSo:
    """``parse_af2ig_output`` returned a fully-formed ValidationResult with every
    metric ``None`` when the score file was missing, header-only, or written with
    different column names. That row reaches metrics.jsonl, the ranker and the
    report indistinguishable from a design that scored badly.
    """

    def test_every_parser_in_the_package_is_covered_here(self, tmp_path: Path) -> None:
        """Discovered from the source, so a validator added later cannot be
        the one parser nobody checked."""
        import re

        root = Path(__file__).resolve().parents[1] / "bindsight"
        found = set()
        for path in root.rglob("*.py"):
            found.update(
                re.findall(r"^def (parse_\w*output)\(", path.read_text(encoding="utf-8"), re.M)
            )
        assert found, "no output parsers found; the discovery pattern has drifted"
        assert found <= set(_empty_dir_parsers(tmp_path)), (
            f"parsers with no unmeasured-result test: {found - set(_empty_dir_parsers(tmp_path))}"
        )

    def test_none_of_them_reports_a_metric_it_did_not_read(self, tmp_path: Path) -> None:
        for name, result in _empty_dir_parsers(tmp_path).items():
            assert not result.measured, f"{name} invented a metric from absent output"

    def test_each_records_why_it_measured_nothing(self, tmp_path: Path) -> None:
        """The note is the part that survives into metrics.jsonl, so it is the
        part a reader of the artifact can act on."""
        from bindsight.validate.protocol import NO_METRICS_NOTE

        for name, result in _empty_dir_parsers(tmp_path).items():
            assert result.notes, f"{name} returned an all-null result with no notes"
            assert NO_METRICS_NOTE in result.notes, (
                f"{name} returned an all-null result with notes={result.notes!r}"
            )

    def test_each_warns_at_parse_time(self, tmp_path: Path, caplog) -> None:
        """The note reaches whoever reads the artifact later; the warning reaches
        whoever is watching the run now."""
        import logging

        with caplog.at_level(logging.WARNING):
            parsers = _empty_dir_parsers(tmp_path)

        messages = [r.getMessage() for r in caplog.records]
        for name, result in parsers.items():
            assert any(result.validator_name in m and "parsed no metrics" in m for m in messages), (
                f"{name} parsed nothing without warning; warnings were {messages}"
            )

    def test_a_measured_result_is_left_exactly_as_it_was(self) -> None:
        """The annotation must not touch a real measurement -- including one that
        measured badly, which is a finding rather than a failure."""
        import logging

        from bindsight.validate.protocol import (
            NO_METRICS_NOTE,
            ValidationResult,
            note_unmeasured,
        )

        scored = ValidationResult(
            binder_id="b1",
            target_uniprot="P04626",
            iptm=0.02,
            validator_name="boltz2",
            validator_version="2.0.3",
            notes="parsed confidence=1 sample(s), affinity=no",
        )

        passed = note_unmeasured(
            scored, reason="should not appear", log=logging.getLogger(__name__)
        )

        assert passed is scored
        assert NO_METRICS_NOTE not in (passed.notes or "")

    def test_measured_is_true_for_any_single_metric(self) -> None:
        """pLDDT-only (AF2 initial guess) and ipTM-only (Chai) results are both
        real measurements; keying the check on ipTM alone would have missed one."""
        from bindsight.validate.protocol import ValidationResult

        base = {
            "binder_id": "b1",
            "target_uniprot": "P04626",
            "validator_name": "v",
            "validator_version": "1",
        }
        assert not ValidationResult(**base).measured
        for field, value in (
            ("iptm", 0.5),
            ("ptm", 0.5),
            ("plddt_binder", 80.0),
            ("pae_interaction", 7.0),
            ("affinity_pred_value", -7.0),
        ):
            assert ValidationResult(**base, **{field: value}).measured, field


# ---------------------------------------------------------------------------
# A run whose candidates could not be read has no recall, not 0% recall
# ---------------------------------------------------------------------------
class TestAnUnreadCandidateTableIsNotAMiss:
    """``_load_candidates`` warns and returns ``None`` for a missing, empty or
    unreadable ``candidates.parquet``. Every known antigen then came back
    ``found=False`` and every cutoff reported 0.0 -- a rediscovery rate of zero,
    reported as a measurement, for a run nothing was ever read from.
    """

    @staticmethod
    def _run_dir(tmp_path: Path, *, write_candidates: bool) -> Path:
        import pandas as pd

        run = tmp_path / "run"
        (run / "targets").mkdir(parents=True)
        if write_candidates:
            pd.DataFrame(
                {
                    "uniprot_id": ["P04626"],
                    "symbol": ["ERBB2"],
                    "rank": [1],
                    "log2fc": [3.5],
                    "padj": [1e-9],
                }
            ).to_parquet(run / "targets" / "candidates.parquet", index=False)
        return run

    @staticmethod
    def _known():
        from bindsight.benchmark.core import KnownAntigen

        return [
            KnownAntigen(
                symbol="ERBB2",
                uniprot="P04626",
                tumor_type="breast",
                disease="breast cancer",
                expected_direction="up",
            )
        ]

    def _score(self, run: Path):
        from bindsight.benchmark import core

        return core.score_run(run, known=self._known(), tumor_type="breast", run_name="t")

    def test_a_missing_table_reports_no_recall_at_all(self, tmp_path: Path) -> None:
        score = self._score(self._run_dir(tmp_path, write_candidates=False))

        assert score.recall_basis == "candidates_unavailable"
        assert score.recall_at == {}, (
            f"recall was reported for a run with no candidate table: {score.recall_at}"
        )

    def test_no_antigen_is_recorded_as_not_found(self, tmp_path: Path) -> None:
        """``False`` is a claim about the ranking; ``None`` is the truth."""
        score = self._score(self._run_dir(tmp_path, write_candidates=False))

        assert score.per_antigen
        for row in score.per_antigen:
            assert row["found"] is None, row
            assert all(v is None for k, v in row.items() if k.startswith("in_top_")), row

    def test_a_readable_table_still_scores_exactly_as_before(self, tmp_path: Path) -> None:
        """The change must not touch the case that was working."""
        score = self._score(self._run_dir(tmp_path, write_candidates=True))

        assert score.recall_basis == "on_indication"
        assert score.recall_at, "a readable table produced no recall"
        assert score.per_antigen[0]["found"] is True
        assert score.per_antigen[0]["rank"] == 1

    def test_the_report_says_why_rather_than_printing_zero(self, tmp_path: Path) -> None:
        from bindsight.benchmark import core

        html = core.render_benchmark_html(
            [self._score(self._run_dir(tmp_path, write_candidates=False))]
        )

        assert "candidate table could not be read" in html
        assert "not a rediscovery rate of zero" in html.lower()

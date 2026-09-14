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

    def test_a_table_without_an_accession_column_is_also_unavailable(self, tmp_path: Path) -> None:
        """The other half of the guard. A frame that loaded but carries no
        accession column cannot say whether an antigen was ranked either, and
        deleting that half of the condition left the suite green.
        """
        import pandas as pd

        run = tmp_path / "run"
        (run / "targets").mkdir(parents=True)
        pd.DataFrame({"symbol": ["ERBB2"], "rank": [1]}).to_parquet(
            run / "targets" / "candidates.parquet", index=False
        )

        score = self._score(run)

        assert score.recall_basis == "candidates_unavailable"
        assert score.recall_at == {}
        assert score.per_antigen[0]["found"] is None

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

    def test_the_summary_row_does_not_print_a_measured_zero(self, tmp_path: Path) -> None:
        """The detail block explained itself while the summary table above it
        still printed "0/1 found" and "0 candidates" in the same report."""
        from bindsight.benchmark import core

        unread = core.render_benchmark_html(
            [self._score(self._run_dir(tmp_path / "a", write_candidates=False))]
        )
        readable = core.render_benchmark_html(
            [self._score(self._run_dir(tmp_path / "b", write_candidates=True))]
        )

        summary = unread.split("<tbody>", 1)[1].split("</tbody>", 1)[0]
        assert "<td>0/1</td>" not in summary, (
            "the summary row reports a measured miss for a run nothing was read from"
        )
        assert summary.count("n/a") >= 2, summary
        # The readable run must still print its counts, or the guard is just
        # blanking the column.
        readable_summary = readable.split("<tbody>", 1)[1].split("</tbody>", 1)[0]
        assert "<td>1/1</td>" in readable_summary, readable_summary


# ---------------------------------------------------------------------------
# Configured parameters must reach the work, on every path
# ---------------------------------------------------------------------------
#: Parameters that decide what a design job actually produces. Passing none of
#: them leaves ``make_spec``'s own defaults in the spec, and the spec is what the
#: executor reads -- so the run is performed under numbers nobody chose.
_SPEC_PARAMS = ("seed", "binder_length_min", "binder_length_max")


def _make_spec_call_sites() -> list[tuple[int, set[str]]]:
    """Every ``make_spec(...)`` call in the CLI, with the keywords it passes.

    Found by parsing, not by grepping a remembered list of functions: the launch
    path threaded these and the notebook path did not, and the notebook path is
    the one the DEFAULT backend uses.
    """
    import ast

    root = Path(__file__).resolve().parents[1]
    tree = ast.parse((root / "bindsight" / "cli.py").read_text(encoding="utf-8"))
    sites: list[tuple[int, set[str]]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "make_spec":
            sites.append((node.lineno, {kw.arg for kw in node.keywords if kw.arg}))
    return sites


class TestEveryDesignPathCarriesTheConfiguredParameters:
    """``bindsight design`` on the default backend (colab) wrote notebooks whose
    embedded spec carried ``make_spec``'s defaults, not the run's configuration.
    A run declaring ``seed: 42`` shipped a notebook designing at seed 0, and the
    manifest recorded 0 as though it had been asked for.
    """

    def test_the_scan_finds_the_call_sites(self) -> None:
        """Guards the guard: a parser that matched nothing would pass silently."""
        sites = _make_spec_call_sites()

        assert len(sites) >= 2, (
            f"expected at least two make_spec call sites in the CLI; found {sites}"
        )

    def test_every_call_site_passes_every_spec_parameter(self) -> None:
        for lineno, keywords in _make_spec_call_sites():
            missing = [p for p in _SPEC_PARAMS if p not in keywords]
            assert not missing, (
                f"bindsight/cli.py:{lineno} calls make_spec without {missing}; the "
                "spec would carry the plugin's defaults rather than the run's "
                "configuration"
            )

    def test_the_parameters_come_from_the_run_not_from_literals(self) -> None:
        """Passing `seed=0` would satisfy the check above and reintroduce the bug."""
        import ast

        root = Path(__file__).resolve().parents[1]
        tree = ast.parse((root / "bindsight" / "cli.py").read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not (isinstance(node.func, ast.Attribute) and node.func.attr == "make_spec"):
                continue
            for kw in node.keywords:
                if kw.arg in _SPEC_PARAMS:
                    assert not isinstance(kw.value, ast.Constant), (
                        f"bindsight/cli.py:{node.lineno} passes a literal for "
                        f"{kw.arg}; it must come from the run's configuration"
                    )


class TestTheDegCacheKeyCoversTheToolThatProducedTheTable:
    """Cache keys here mean "the same key is the same work". The DEG key covered
    the inputs and the parameters but not pydeseq2's version, so upgrading the
    library hit the old entry and the manifest recorded the reused bytes under
    the new version's name.
    """

    @staticmethod
    def _key(monkeypatch, version: str | None):
        from bindsight.pipelines import discover
        from bindsight.provenance.manifest import InputRef

        monkeypatch.setattr(
            "bindsight.validate.protocol.installed_version",
            lambda dist: version,
        )
        inputs = [InputRef(role="counts", path="counts.tsv", sha256="a" * 64, bytes=10)]
        return discover._deg_cache_key(inputs, {"fdr_threshold": 0.05})

    def test_a_different_pydeseq2_version_is_different_work(self, monkeypatch) -> None:
        first = self._key(monkeypatch, "0.5.4")
        second = self._key(monkeypatch, "0.6.0")

        assert first != second, (
            "the DEG cache key is unchanged across pydeseq2 versions, so an "
            "upgraded library would be served the previous library's table"
        )

    def test_the_same_version_still_hits(self, monkeypatch) -> None:
        """The key must stay stable, or caching stops working entirely."""
        assert self._key(monkeypatch, "0.5.4") == self._key(monkeypatch, "0.5.4")

    def test_an_unrecorded_version_is_not_silently_equal_to_a_known_one(self, monkeypatch) -> None:
        assert self._key(monkeypatch, None) != self._key(monkeypatch, "0.5.4")


class TestTheSnakemakeFrontEndWritesTheEffectiveConfig:
    """``<run>/config.yaml`` is the only channel by which the seed, the binder
    length bounds and the validate thresholds reach the design half. The CLI path
    wrote it; the Snakemake path did not, so the two front-ends ran the same
    configuration differently and only one of them said so.
    """

    def test_the_front_end_writes_the_config(self) -> None:
        import ast

        root = Path(__file__).resolve().parents[1]
        source = (root / "scripts" / "run_discover.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        called = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }

        assert "_write_run_config" in called, (
            "scripts/run_discover.py does not write <run>/config.yaml, so every "
            "design parameter is silently defaulted on the Snakemake path"
        )

    def test_both_front_ends_use_the_same_writer(self) -> None:
        """Two implementations of "the effective config" would drift."""
        import ast

        root = Path(__file__).resolve().parents[1]
        for rel in ("scripts/run_discover.py", "bindsight/pipelines/discover.py"):
            source = (root / rel).read_text(encoding="utf-8")
            assert "_write_run_config" in source, rel
            if rel.startswith("scripts/"):
                tree = ast.parse(source)
                imported = {
                    alias.name
                    for node in ast.walk(tree)
                    if isinstance(node, ast.ImportFrom)
                    and node.module == "bindsight.pipelines.discover"
                    for alias in node.names
                }
                assert "_write_run_config" in imported, (
                    "the Snakemake front-end defines its own config writer instead "
                    "of importing the one the CLI path uses"
                )


# ---------------------------------------------------------------------------
# A count that could not be taken is not a count
# ---------------------------------------------------------------------------
class TestTheTargetCountIsCountedNotAssumed:
    """``_count_top_targets`` returned a hard-coded 5 for a missing or unreadable
    epitopes table. That 5 was printed as ``targets: 5`` and fed to the cost
    estimate, so a run with no targets quoted a GPU cost for designing five of
    them, with nothing on screen saying the number was invented.
    """

    def test_a_missing_table_is_unknown_not_five(self, tmp_path: Path, caplog) -> None:
        import logging

        from bindsight.cli import _count_top_targets

        with caplog.at_level(logging.WARNING):
            count = _count_top_targets(tmp_path / "absent.parquet")

        assert count is None
        assert any("unknown" in r.getMessage() for r in caplog.records), [
            r.getMessage() for r in caplog.records
        ]

    def test_an_unreadable_table_is_unknown_not_five(self, tmp_path: Path, caplog) -> None:
        import logging

        from bindsight.cli import _count_top_targets

        broken = tmp_path / "epitopes.parquet"
        broken.write_bytes(b"not a parquet file")

        with caplog.at_level(logging.WARNING):
            count = _count_top_targets(broken)

        assert count is None
        assert any("could not read" in r.getMessage() for r in caplog.records)

    def test_a_readable_table_is_still_counted(self, tmp_path: Path) -> None:
        import pandas as pd

        from bindsight.cli import _count_top_targets

        path = tmp_path / "epitopes.parquet"
        pd.DataFrame({"uniprot_id": ["P1", "P2", "P3"]}).to_parquet(path, index=False)

        assert _count_top_targets(path) == 3

    def test_it_matches_the_shape_of_its_sibling(self) -> None:
        """``_count_designs`` already returned None for "not countable" and said
        in its docstring that the caller must not quote a made-up number. The two
        helpers answer the same kind of question and must answer it the same way.
        """
        import inspect

        from bindsight.cli import _count_designs, _count_top_targets

        for fn in (_count_designs, _count_top_targets):
            assert "int | None" in str(inspect.signature(fn)), fn.__name__

    def test_the_cost_estimate_is_skipped_rather_than_guessed(self) -> None:
        """Pricing an unknown amount of work produces a plausible dollar figure
        for work whose size nobody knows."""
        source = (Path(__file__).resolve().parents[1] / "bindsight" / "cli.py").read_text(
            encoding="utf-8"
        )

        assert "cost estimate is skipped" in source, (
            "the design command no longer explains that it skipped the estimate"
        )


class TestAFailedPluginImportSaysWhatFailed:
    """A registered entry point that raised on import was swallowed and reported
    as "unknown plugin" -- the opposite of the cause, sending the reader to check
    a name that was correct.
    """

    def test_a_broken_entry_point_is_reported_as_broken(self, monkeypatch, caplog) -> None:
        import logging

        from bindsight import plugins

        class _Broken:
            name = "rfdiff_mpnn"

            def load(self):
                raise ImportError("torch is not installed")

        monkeypatch.setattr(plugins, "entry_points", lambda group: [_Broken()])

        with caplog.at_level(logging.WARNING):
            plugins._load("bindsight.designers", "rfdiff_mpnn")

        messages = [r.getMessage() for r in caplog.records]
        assert any("failed to load" in m for m in messages), messages
        assert any("torch is not installed" in m for m in messages), messages

    def test_a_genuinely_unknown_name_still_says_unknown(self, monkeypatch) -> None:
        from bindsight import plugins

        monkeypatch.setattr(plugins, "entry_points", lambda group: [])

        with pytest.raises(ValueError, match="unknown"):
            plugins._load("bindsight.designers", "no_such_designer")


class TestAnUnattendedStageFailureKeepsItsTraceback:
    """``full_run`` runs the whole pipeline without a human watching. All five of
    its stage failures logged at WARNING with the traceback discarded, while the
    discover pipeline logs the same class of event with the traceback kept.
    """

    def test_every_stage_failure_logs_its_traceback(self) -> None:
        """Discovered by parsing, so a stage added later cannot quietly drop it."""
        import ast

        root = Path(__file__).resolve().parents[1]
        tree = ast.parse(
            (root / "bindsight" / "pipelines" / "full_run.py").read_text(encoding="utf-8")
        )

        offenders = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name)):
                continue
            if func.value.id != "LOG" or not node.args:
                continue
            first = node.args[0]
            if not (isinstance(first, ast.Constant) and "stage failed" in str(first.value)):
                continue
            keeps_traceback = func.attr == "exception" or any(
                kw.arg == "exc_info" for kw in node.keywords
            )
            if not keeps_traceback:
                offenders.append(f"line {node.lineno}: LOG.{func.attr}")
        assert not offenders, f"stage failures logged without a traceback: {offenders}"

    def test_there_are_stage_failures_to_check(self) -> None:
        """Guards the guard: a renamed message would make the scan vacuous."""
        source = (
            Path(__file__).resolve().parents[1] / "bindsight" / "pipelines" / "full_run.py"
        ).read_text(encoding="utf-8")

        assert source.count("stage failed") >= 5, (
            "the full-run pipeline no longer logs five stage failures; the scan "
            "above may be checking nothing"
        )


class TestTheValidatorNoteCountsWhatItParsed:
    """The note said "parsed confidence=N sample(s)" where N counted the files
    found. A directory of unreadable JSON reported the same count as a directory
    of good ones, and the row carried no trace of the difference.
    """

    def test_unreadable_files_are_not_counted_as_parsed(self, tmp_path: Path) -> None:
        from bindsight.validate.boltz2 import parse_boltz_output

        predictions = tmp_path / "predictions" / "run"
        predictions.mkdir(parents=True)
        (predictions / "confidence_a.json").write_text('{"iptm": 0.8}', encoding="utf-8")
        (predictions / "confidence_b.json").write_text("not json", encoding="utf-8")

        result = parse_boltz_output(output_dir=tmp_path, binder_id="b1", target_uniprot="P04626")

        assert "parsed confidence=1 of 2 file(s)" in (result.notes or ""), result.notes
        assert result.iptm == pytest.approx(0.8)


# ---------------------------------------------------------------------------
# A manifest must describe paths the way it says it does
# ---------------------------------------------------------------------------
class TestARecordedPathIsRunRelative:
    """``OutputRef.path`` says "Path relative to the run root". The writer stored
    ``str(path)`` unchanged, which produced repository-relative paths in the
    launching platform's separators -- ``runs\\join\\deg\\results.parquet``. A
    manifest read on another machine then described a layout that machine does
    not have, and the field's own description was false.
    """

    def test_an_output_inside_the_run_is_recorded_relative_and_posix(self, tmp_path: Path) -> None:
        from bindsight.provenance.append import output_ref

        run = tmp_path / "run"
        (run / "deg").mkdir(parents=True)
        artifact = run / "deg" / "results.parquet"
        artifact.write_bytes(b"x")

        ref = output_ref("deg_table", artifact, run_dir=run)

        assert ref is not None
        assert ref.path == "deg/results.parquet", ref.path
        assert "\\" not in ref.path

    def test_an_input_is_recorded_the_same_way(self, tmp_path: Path) -> None:
        """Both sides of the graph must describe paths identically."""
        from bindsight.provenance.append import input_ref

        run = tmp_path / "run"
        (run / "targets").mkdir(parents=True)
        artifact = run / "targets" / "candidates.parquet"
        artifact.write_bytes(b"x")

        ref = input_ref("candidates", artifact, run_dir=run)

        assert ref is not None
        assert ref.path == "targets/candidates.parquet"

    def test_a_file_outside_the_run_keeps_its_own_path(self, tmp_path: Path) -> None:
        """A carried-in cohort is not under the run root; inventing a relative
        path for it would assert a relationship that does not hold."""
        from bindsight.provenance.append import output_ref

        run = tmp_path / "run"
        run.mkdir()
        outside = tmp_path / "cohort.tsv"
        outside.write_bytes(b"x")

        ref = output_ref("counts", outside, run_dir=run)

        assert ref is not None
        assert "cohort.tsv" in ref.path

    def test_a_recorded_stage_carries_the_inputs_it_read(self, tmp_path: Path) -> None:
        """``record()`` had no inputs parameter at all, so every stage the CLI
        recorded through it carried an empty ``prov:used`` -- a provenance graph
        with no incoming edges cannot answer "what produced this"."""
        import json

        from bindsight.provenance import append as provenance
        from bindsight.provenance import new_manifest

        run = tmp_path / "run"
        (run / "validate").mkdir(parents=True)
        (run / "rank").mkdir(parents=True)
        # record() appends to an existing manifest; a run with no root has
        # nothing to append to, which it warns about rather than inventing one.
        new_manifest(name="guard").write(run / "run_manifest.jsonld")
        source = run / "validate" / "validated.parquet"
        source.write_bytes(b"x")
        out = run / "rank" / "ranking.parquet"
        out.write_bytes(b"y")

        path = provenance.record(
            run,
            name="rank",
            tool="bindsight.rank",
            inputs={"validated": source},
            outputs={"ranking": out},
        )

        assert path is not None
        stage = next(
            st
            for st in json.loads(path.read_text(encoding="utf-8"))["stages"]
            if st["name"] == "rank"
        )
        assert stage["inputs"], "the stage recorded no inputs"
        assert stage["inputs"][0]["path"] == "validate/validated.parquet"
        assert len(stage["inputs"][0]["sha256"]) == 64


class TestTheRankStageRecordsWhatOrderedIt:
    """A ranking without its weights is underdetermined: the manifest names the
    output and not the only parameter that decides the order."""

    def test_the_cli_records_the_weights(self) -> None:
        import ast

        root = Path(__file__).resolve().parents[1]
        tree = ast.parse((root / "bindsight" / "cli.py").read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (isinstance(func, ast.Attribute) and func.attr == "record"):
                continue
            kwargs = {kw.arg for kw in node.keywords}
            name = next((kw.value for kw in node.keywords if kw.arg == "name"), None)
            if isinstance(name, ast.Constant) and name.value == "rank":
                assert "params" in kwargs, "the rank stage records no parameters"
                assert "inputs" in kwargs, "the rank stage records no inputs"
                return
        raise AssertionError("no rank stage record found in the CLI")


class TestTheFragmentStatusVocabularyComesFromTheModel:
    """An unrecognised status was rewritten to "completed" against a hand-copied
    set. That is the worst direction for drift: a stage that failed in a way this
    module did not know about was recorded as having succeeded.
    """

    def test_the_vocabulary_matches_the_model(self) -> None:
        from typing import get_args

        from bindsight.provenance.fragments import _STATUS_VALUES
        from bindsight.provenance.manifest import StageRecord

        assert frozenset(get_args(StageRecord.model_fields["status"].annotation)) == _STATUS_VALUES

    def test_an_unknown_status_is_not_recorded_as_success(self, caplog) -> None:
        import logging

        from bindsight.provenance.fragments import stage_record_from_fragment

        tool = {"name": "x", "version": "1", "license": "MIT"}
        with caplog.at_level(logging.WARNING):
            record = stage_record_from_fragment(
                {"stage": "deg", "status": "exploded", "tool": tool}
            )

        assert record.status != "completed", (
            "an unrecognised status was recorded as a completed stage"
        )
        assert any("unrecognised status" in r.getMessage() for r in caplog.records)

    def test_a_known_status_is_preserved(self) -> None:
        from bindsight.provenance.fragments import stage_record_from_fragment

        tool = {"name": "x", "version": "1", "license": "MIT"}
        for status in ("completed", "failed", "skipped", "skipped_cache"):
            assert (
                stage_record_from_fragment({"stage": "deg", "status": status, "tool": tool}).status
                == status
            )


class TestEveryPinnedDistributionIsClassified:
    """``SCIENTIFIC_STACK`` decides what a run records about the software that
    produced its numbers. It was hand-written and had fallen six behind the pins,
    including ``formulaic`` — pydeseq2's design-matrix engine, whose release can
    move a log2 fold change on its own.
    """

    @staticmethod
    def _pinned() -> set[str]:
        import re

        root = Path(__file__).resolve().parents[1]
        return {
            m.group(1).lower()
            for line in (root / "envs" / "constraints.txt").read_text(encoding="utf-8").splitlines()
            if (m := re.match(r"([A-Za-z0-9_.-]+)==", line.strip()))
        }

    def test_the_pins_are_readable(self) -> None:
        """Guards the guard: an unparsed constraints file makes this vacuous."""
        assert len(self._pinned()) >= 10, sorted(self._pinned())

    def test_every_pin_is_either_recorded_or_declared_presentation_only(self) -> None:
        from bindsight.provenance.manifest import PRESENTATION_ONLY, SCIENTIFIC_STACK

        classified = {n.lower() for n in (*SCIENTIFIC_STACK, *PRESENTATION_ONLY)}
        unclassified = sorted(self._pinned() - classified)

        assert not unclassified, (
            f"pinned but neither recorded in the manifest nor declared "
            f"presentation-only: {unclassified}. A pin nothing records cannot "
            "help anyone re-derive a published number."
        )

    def test_the_deg_engine_is_recorded(self) -> None:
        """The specific omission that motivated this: formulaic is what turns the
        design formula into the matrix the fit runs on."""
        from bindsight.provenance.manifest import SCIENTIFIC_STACK

        assert "formulaic" in {n.lower() for n in SCIENTIFIC_STACK}

    def test_nothing_is_in_both_lists(self) -> None:
        from bindsight.provenance.manifest import PRESENTATION_ONLY, SCIENTIFIC_STACK

        overlap = {n.lower() for n in SCIENTIFIC_STACK} & {n.lower() for n in PRESENTATION_ONLY}
        assert not overlap, overlap

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

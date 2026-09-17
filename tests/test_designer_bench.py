# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the three-way designer benchmark harness (mock backend, CPU only)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bindsight.benchmark.designer_bench import (
    Target,
    _floats,
    _read_metrics,
    run_designer_benchmark,
    run_one_designer,
)


def test_read_metrics_and_floats(tmp_path: Path) -> None:
    p = tmp_path / "metrics.jsonl"
    p.write_text(
        json.dumps({"iptm": 0.7, "affinity_pred_value": -7.0})
        + "\n"
        + "\n"  # blank line tolerated
        + json.dumps({"iptm": 0.8, "affinity_pred_value": None})
        + "\n"
    )
    rows = _read_metrics(p)
    assert len(rows) == 2
    assert _floats(rows, "iptm") == [0.7, 0.8]
    # None / missing values are skipped, not coerced.
    assert _floats(rows, "affinity_pred_value") == [-7.0]


def test_read_metrics_missing_file(tmp_path: Path) -> None:
    assert _read_metrics(tmp_path / "nope.jsonl") == []


def test_run_one_designer_mock() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        score = run_one_designer(
            "rfdiff_mpnn",
            [Target("P04626", "ERBB2"), Target("P00533", "EGFR")],
            backend="mock",
            validator="boltz2",
            n_trajectories=4,
            seed=0,
            structures_dir=None,
            scratch=Path(tmp),
        )
    assert score.error is None
    assert score.designer == "rfdiff_mpnn"
    assert score.n_designs > 0
    assert score.mean_iptm is not None
    assert 0.0 <= score.success_rate <= 1.0  # type: ignore[operator]
    # Mock backend never spends money.
    assert score.cost_usd == 0.0
    assert len(score.per_target) == 2


def test_run_designer_benchmark_mock(tmp_path: Path) -> None:
    summary = run_designer_benchmark(
        out_dir=tmp_path / "out",
        backend="mock",
        designers=("rfdiff_mpnn", "bindcraft", "boltzgen"),
        validator="boltz2",
        targets=[Target("P04626", "ERBB2")],
        n_trajectories=2,
    )
    assert summary["is_mock"] is True
    assert {d["designer"] for d in summary["designers"]} == {
        "rfdiff_mpnn",
        "bindcraft",
        "boltzgen",
    }
    for d in summary["designers"]:
        assert d["error"] is None
        assert d["n_designs"] > 0

    # Artifacts written, and the mock result is clearly labelled synthetic.
    assert (tmp_path / "out" / "results.json").exists()
    md = (tmp_path / "out" / "RESULTS.md").read_text()
    assert "MOCK" in md
    assert "rfdiff_mpnn" in md


class TestBinderArtifactStaging:
    """results.json and binders/ must describe the same run.

    A benchmark that rewrites its metrics but leaves the previous run's
    structures in place produces a directory whose numbers and whose molecules
    come from different runs — and the Real-results page renders those
    structures, so the mismatch would be published as one coherent result.
    """

    @staticmethod
    def _archive(tmp_path: Path, binder_id: str) -> Path:
        import tarfile

        work = tmp_path / "work"
        (work / "design").mkdir(parents=True, exist_ok=True)
        (work / "validate" / binder_id).mkdir(parents=True, exist_ok=True)
        (work / "design" / f"{binder_id}.fasta").write_text(f">{binder_id}\nMKT\n")
        (work / "validate" / binder_id / "model_0.cif").write_text("data_mock\n")
        (work / "metrics.jsonl").write_text(
            json.dumps({"binder_id": binder_id, "iptm": 0.8}) + "\n"
        )
        archive = tmp_path / f"{binder_id}.tar.gz"
        with tarfile.open(archive, "w:gz") as tf:
            for sub in ("design", "validate", "metrics.jsonl"):
                tf.add(work / sub, arcname=sub)
        return archive

    def test_superseded_artifacts_are_removed(self, tmp_path: Path) -> None:
        from bindsight.benchmark.designer_bench import stage_binder_artifacts

        out = tmp_path / "bench"
        binders = out / "binders"
        binders.mkdir(parents=True)
        # A previous run's artifacts, under the old un-namespaced id scheme.
        (binders / "binder_0_seq0.fasta").write_text(">old\nMKT\n")
        (binders / "binder_0_seq0_complex.cif").write_text("data_old\n")

        counts = stage_binder_artifacts([self._archive(tmp_path, "P04626_binder_0_seq0")], out)

        assert counts["removed"] == 2
        assert not (binders / "binder_0_seq0.fasta").exists()
        assert not (binders / "binder_0_seq0_complex.cif").exists()

    def test_new_artifacts_are_written_with_their_complex(self, tmp_path: Path) -> None:
        from bindsight.benchmark.designer_bench import stage_binder_artifacts

        out = tmp_path / "bench"
        stage_binder_artifacts([self._archive(tmp_path, "P04626_binder_0_seq0")], out)
        binders = out / "binders"
        assert (binders / "P04626_binder_0_seq0.fasta").is_file()
        assert (binders / "P04626_binder_0_seq0_complex.cif").is_file()
        assert (binders / "metrics.jsonl").is_file()

    def test_a_missing_archive_is_warned_not_fatal(self, tmp_path: Path) -> None:
        """Losing one target's tarball must not discard the others."""
        from bindsight.benchmark.designer_bench import stage_binder_artifacts

        out = tmp_path / "bench"
        counts = stage_binder_artifacts(
            [tmp_path / "absent.tar.gz", self._archive(tmp_path, "P04626_binder_1_seq0")], out
        )
        assert counts["written"] >= 2
        assert (out / "binders" / "P04626_binder_1_seq0.fasta").is_file()

    def test_derived_files_are_left_alone(self, tmp_path: Path) -> None:
        """Developability and embedding files are regenerated by their own scripts."""
        from bindsight.benchmark.designer_bench import stage_binder_artifacts

        out = tmp_path / "bench"
        binders = out / "binders"
        binders.mkdir(parents=True)
        (binders / "developability.tsv").write_text("keep\n")
        stage_binder_artifacts([self._archive(tmp_path, "P04626_binder_0_seq0")], out)
        assert (binders / "developability.tsv").is_file()


class TestStructureResolution:
    """A real GPU backend must never design against the placeholder.

    The placeholder is a three-residue stub for offline mock runs. On a real
    backend RFdiffusion will design binders against it, Boltz-2 will score them,
    and the run reports ipTM figures for a target that was never present — GPU
    hours spent producing numbers that look real. This was observed: a Kaggle run
    reached `contigmap.contigs=[A1-3/0 50-100]` against a 242-byte target.
    """

    @staticmethod
    def _no_alphafold(monkeypatch: pytest.MonkeyPatch) -> None:
        """Make the AlphaFold fallback fail, isolating the resolution logic."""
        import bindsight.structures.alphafolddb as afdb

        class _Empty:
            def fetch(self, uniprot: str) -> None:
                return None

        monkeypatch.setattr(afdb, "AlphaFoldDBClient", _Empty)

    def test_a_real_backend_refuses_to_use_the_placeholder(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from bindsight.benchmark.designer_bench import Target, _resolve_structure

        self._no_alphafold(monkeypatch)
        with pytest.raises(FileNotFoundError, match="placeholder"):
            _resolve_structure(
                Target("P00000", "NOPE"), tmp_path, tmp_path, allow_placeholder=False
            )

    def test_the_error_names_how_to_fix_it(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from bindsight.benchmark.designer_bench import Target, _resolve_structure

        self._no_alphafold(monkeypatch)
        with pytest.raises(FileNotFoundError) as exc:
            _resolve_structure(
                Target("P00000", "NOPE"), tmp_path, tmp_path, allow_placeholder=False
            )
        assert "prepare_erbb2_target" in str(exc.value)

    def test_the_mock_backend_may_still_use_it(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from bindsight.benchmark.designer_bench import Target, _resolve_structure

        self._no_alphafold(monkeypatch)
        path = _resolve_structure(
            Target("P00000", "NOPE"), tmp_path, tmp_path, allow_placeholder=True
        )
        assert path.is_file()

    def test_a_prepared_structure_wins(self, tmp_path: Path) -> None:
        from bindsight.benchmark.designer_bench import Target, _resolve_structure

        real = tmp_path / "P04626.pdb"
        real.write_text("ATOM      1  CA  ALA A   1       0.000   0.000   0.000\n")
        got = _resolve_structure(Target("P04626", "ERBB2"), tmp_path, tmp_path)
        assert got == real

    def test_the_default_directory_is_searched_when_none_is_given(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Passing no directory used to mean 'write a placeholder' immediately."""
        from bindsight.benchmark import designer_bench as db

        monkeypatch.setattr(db, "DEFAULT_STRUCTURES_DIR", tmp_path)
        real = tmp_path / "P04626.pdb"
        real.write_text("ATOM      1  CA  ALA A   1       0.000   0.000   0.000\n")
        assert db._resolve_structure(db.Target("P04626", "ERBB2"), None, tmp_path) == real

    def test_a_missing_structure_aborts_the_designer(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Submitting the remaining targets would spend GPU on an incomplete run."""
        from bindsight.benchmark.designer_bench import Target, run_one_designer

        self._no_alphafold(monkeypatch)
        score = run_one_designer(
            "rfdiff_mpnn",
            [Target("P00000", "NOPE")],
            backend="kaggle",
            validator="boltz2",
            n_trajectories=1,
            seed=0,
            structures_dir=tmp_path,
            scratch=tmp_path,
        )
        assert score.error is not None
        assert "placeholder" in score.error
        assert score.n_designs == 0


# ---------------------------------------------------------------------------
# Designs sharing a backbone are not independent trials
# ---------------------------------------------------------------------------
class TestTheSuccessIntervalIsClusteredOverBackbones:
    """A binomial interval over designs reads narrower than the run earns.

    ProteinMPNN produces several sequences per RFdiffusion trajectory, so twenty
    designs from ten backbones are ten attempts, not twenty. On the committed
    ERBB2 run success clusters hard — five backbones yield nothing and three
    yield two — and the binomial interval gave (22%, 61%) where clustering gives
    (15%, 70%).

    This is the same error the study half was already fixed for, where one
    antigen across several cohorts is one piece of evidence.
    `cluster_bootstrap_interval` existed, was tested, and was simply never
    called from here.
    """

    def test_a_backbone_groups_its_sequences(self) -> None:
        from bindsight.benchmark.designer_bench import _backbone_of

        assert _backbone_of("Q16790_binder_0_seq0") == "Q16790_binder_0"
        assert _backbone_of("Q16790_binder_0_seq1") == "Q16790_binder_0"
        assert _backbone_of("Q16790_binder_1_seq0") == "Q16790_binder_1"

    def test_an_id_without_sequences_is_its_own_cluster(self) -> None:
        """Nothing may be assumed correlated that is not known to be."""
        from bindsight.benchmark.designer_bench import _backbone_of, _success_intervals

        assert _backbone_of("boltzgen_design_3") == "boltzgen_design_3"
        singletons = {f"d{i}": [i < 4] for i in range(10)}
        fields = _success_intervals(singletons)
        assert fields["n_backbones"] == 10
        # With one design per cluster there is nothing to correct for, so the
        # clustered interval should sit close to the independent one.
        assert abs(fields["success_ci_low"] - fields["success_ci_independent_low"]) < 0.2

    def test_clustering_widens_the_interval_when_success_is_correlated(self) -> None:
        """The whole point: correlated designs carry less information."""
        from bindsight.benchmark.designer_bench import _success_intervals

        # Five backbones all-hit, five all-miss: maximal within-cluster
        # correlation, and exactly the shape the real run has.
        outcomes = {f"bb{i}": [i < 5, i < 5] for i in range(10)}
        f = _success_intervals(outcomes)
        clustered_width = f["success_ci_high"] - f["success_ci_low"]
        independent_width = f["success_ci_independent_high"] - f["success_ci_independent_low"]
        assert clustered_width > independent_width, (
            "clustering must not report more precision than a binomial over designs"
        )

    def test_the_backbone_level_rate_is_reported(self) -> None:
        from bindsight.benchmark.designer_bench import _success_intervals

        outcomes = {"a": [True, False], "b": [False, False], "c": [True, True]}
        f = _success_intervals(outcomes)
        assert f["n_backbones"] == 3
        assert f["n_backbones_with_success"] == 2

    def test_the_committed_artifact_carries_the_clustered_interval(self) -> None:
        """Regression on the published figure itself.

        The artifact must not carry the binomial bounds as its reported
        interval. 0.2188/0.6134 are the independence-assuming ones and belong
        only in the field named for them.
        """
        repo = Path(__file__).resolve().parents[1]
        artifact = repo / "benchmarks" / "designer_benchmark" / "results.json"
        if not artifact.is_file():
            pytest.skip("designer benchmark artifact not present")
        arm = next(
            d
            for d in json.loads(artifact.read_text(encoding="utf-8"))["designers"]
            if d.get("n_designs")
        )
        assert arm["success_ci_method"].startswith("cluster-bootstrap"), (
            "the reported interval is not clustered over backbones"
        )
        assert arm["n_backbones"] == 10
        assert arm["n_backbones_with_success"] == 5
        assert arm["success_ci_low"] == pytest.approx(0.15)
        assert arm["success_ci_high"] == pytest.approx(0.70)
        # The narrower binomial bounds survive only under their own name.
        assert arm["success_ci_independent_low"] == pytest.approx(0.2188)
        assert arm["success_ci_low"] < arm["success_ci_independent_low"]
        assert arm["success_ci_high"] > arm["success_ci_independent_high"]


# ---------------------------------------------------------------------------
# Forecasts must not sit unmarked in a row of measurements
# ---------------------------------------------------------------------------
REPO = Path(__file__).resolve().parents[1]
BENCH_DIR = REPO / "benchmarks" / "designer_benchmark"


class TestGpuHoursSaysWhereItCameFrom:
    """The GPU-hours column printed ``bindsight.cost``'s pre-run forecast beside
    measured ipTMs, unmarked. 0.722 looked like something the run observed; the
    run observed nothing of the kind, and recorded no duration to check it.
    """

    def test_a_forecast_is_marked_as_one(self) -> None:
        from bindsight.benchmark.designer_bench import _gpu_hours_cell

        assert _gpu_hours_cell({"gpu_hours": 0.722}) == "0.722 (est.)"

    def test_a_measurement_is_preferred_and_marked_as_one(self) -> None:
        """A measured wall-clock beats the forecast for the same run."""
        from bindsight.benchmark.designer_bench import _gpu_hours_cell

        cell = _gpu_hours_cell({"gpu_hours": 99.0, "wall_seconds": 3600.0})

        assert cell == "1 (measured)"
        assert "est." not in cell

    def test_neither_renders_as_a_dash_not_a_zero(self) -> None:
        """An absent figure must not become 0, which would read as "free"."""
        from bindsight.benchmark.designer_bench import _gpu_hours_cell

        assert _gpu_hours_cell({}) == "—"

    def test_a_real_run_records_its_own_wall_clock(self) -> None:
        """Measured going forward, so the next run does not need the forecast."""
        from bindsight.benchmark.designer_bench import run_one_designer

        score = run_one_designer(
            "rfdiff_mpnn",
            [],
            backend="mock",
            validator="boltz2",
            n_trajectories=1,
            seed=0,
            structures_dir=None,
            scratch=REPO / "does-not-matter-no-targets",
        )

        assert score.wall_seconds is not None
        assert score.wall_seconds >= 0.0

    def test_the_note_explains_which_is_which(self) -> None:
        from bindsight.benchmark.designer_bench import _render_md

        md = _render_md(
            {
                "generated_utc": "2026-01-01T00:00:00+00:00",
                "bindsight_version": "0.0.0",
                "backend": "mock",
                "validator": "boltz2",
                "n_trajectories": 1,
                "is_mock": True,
                "targets": [],
                "designers": [],
            }
        )

        assert "(est.)" in md, md[-600:]
        assert "(measured)" in md, md[-600:]
        assert "forecasts made before" in md


class TestTheCommittedTableIsARender:
    """``RESULTS.md`` is written from ``results.json`` in the same call. Nothing
    checked that it still matched afterwards, so an edited table -- or a
    regenerated JSON -- would leave a page whose numbers came from nowhere.
    """

    @staticmethod
    def _committed() -> tuple[dict, str]:
        results = BENCH_DIR / "results.json"
        page = BENCH_DIR / "RESULTS.md"
        if not results.is_file() or not page.is_file():
            pytest.skip("designer benchmark artifacts not present")
        return (
            json.loads(results.read_text(encoding="utf-8")),
            page.read_text(encoding="utf-8"),
        )

    def test_the_page_is_exactly_what_the_artifact_renders_to(self) -> None:
        from bindsight.benchmark.designer_bench import _render_md

        summary, page = self._committed()

        assert _render_md(summary) == page, (
            "benchmarks/designer_benchmark/RESULTS.md is not what results.json "
            "renders to. Regenerate it rather than editing the table by hand."
        )

    def test_the_renderer_depends_on_the_numbers(self) -> None:
        """Guards the guard: a renderer ignoring the summary would make the
        comparison above pass against any artifact."""
        from bindsight.benchmark.designer_bench import _render_md

        summary, page = self._committed()
        altered = json.loads(json.dumps(summary))
        assert altered["designers"], "the committed summary scores no designer"
        altered["designers"][0]["mean_iptm"] = 0.123456

        assert _render_md(altered) != page


class TestTheSummaryRecordsItsSeed:
    """``results.json`` recorded backend, validator, trajectory count, version
    and the wheel that ran — every input except the seed. A run could name
    everything about itself except the one parameter that decides which draw it
    is, which is the parameter someone reproducing it needs.
    """

    def test_a_run_records_the_seed_it_was_given(self, tmp_path: Path) -> None:
        from bindsight.benchmark.designer_bench import run_designer_benchmark

        run_designer_benchmark(
            designers=["rfdiff_mpnn"],
            targets=[],
            backend="mock",
            validator="boltz2",
            n_trajectories=1,
            seed=4242,
            out_dir=tmp_path,
        )

        summary = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))
        assert summary["seed"] == 4242, summary

    def test_a_seed_of_zero_is_recorded_rather_than_treated_as_absent(self, tmp_path: Path) -> None:
        """Zero is a real seed. Falsy-checking it away would make the commonest
        seed in the project indistinguishable from no seed at all."""
        from bindsight.benchmark.designer_bench import _render_md, run_designer_benchmark

        run_designer_benchmark(
            designers=["rfdiff_mpnn"],
            targets=[],
            backend="mock",
            validator="boltz2",
            n_trajectories=1,
            seed=0,
            out_dir=tmp_path,
        )

        summary = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))
        assert summary["seed"] == 0
        assert "- Seed: `0`" in _render_md(summary)

    def test_an_older_artifact_renders_as_unrecorded_not_as_zero(self) -> None:
        """The committed run predates this field. It must not render as seed 0,
        which is a real and different run."""
        from bindsight.benchmark.designer_bench import _render_md

        summary = {
            "generated_utc": "2026-01-01T00:00:00+00:00",
            "bindsight_version": "0.0.0",
            "backend": "kaggle",
            "validator": "boltz2",
            "n_trajectories": 10,
            "is_mock": False,
            "targets": ["ERBB2"],
            "designers": [],
        }

        rendered = _render_md(summary)

        assert "- Seed: **unrecorded**" in rendered
        assert "`0`" not in rendered.split("- Targets:")[0]

    def test_the_committed_page_says_which_case_it_is(self) -> None:
        summary, page = TestTheCommittedTableIsARender._committed()

        if summary.get("seed") is None:
            assert "Seed: **unrecorded**" in page, (
                "the committed artifact records no seed and the page does not say so"
            )
        else:
            assert f"- Seed: `{summary['seed']}`" in page


class TestTheSuccessCellKnowsItsOwnDenominator:
    """The rate was computed over one number and printed beside another.

    `_success_cell` reads `n_scored` — the designs the rate was actually computed
    over — and discloses any gap from `n_designs`. But `_score_dict` never wrote
    `n_scored`, so the fallback fired every time and the cell rendered
    `8/20 = 50%`: a rate over sixteen beside a denominator of twenty. The two
    numbers in one cell did not describe the same thing, and 8/20 is 40%.
    """

    @staticmethod
    def _score(**kw):
        from bindsight.benchmark.designer_bench import DesignerScore

        s = DesignerScore(
            designer="rfdiff_mpnn",
            n_designs=kw.get("n_designs", 20),
            n_success=kw.get("n_success", 8),
            success_rate=kw.get("success_rate", 0.5),
            success_ci_low=0.3,
            success_ci_high=0.7,
        )
        s.n_scored = kw.get("n_scored", 16)
        return s

    def test_the_denominator_reaches_the_serialised_artifact(self) -> None:
        from bindsight.benchmark.designer_bench import _score_dict

        assert _score_dict(self._score())["n_scored"] == 16, (
            "n_scored is not written to results.json, so the report cannot know "
            "which denominator the rate belongs to"
        )

    def test_the_cell_prints_the_denominator_the_rate_was_computed_over(self) -> None:
        from bindsight.benchmark.designer_bench import _score_dict, _success_cell

        cell = _success_cell(_score_dict(self._score()))

        assert "8/16" in cell, f"the cell prints a denominator the rate is not over: {cell}"
        assert "8/20" not in cell

    def test_the_gap_is_disclosed_rather_than_hidden(self) -> None:
        """Narrowing a denominator is itself a claim, so it is stated."""
        from bindsight.benchmark.designer_bench import _score_dict, _success_cell

        cell = _success_cell(_score_dict(self._score()))

        assert "20" in cell and "unscored" in cell, (
            f"the cell narrows the denominator without saying so: {cell}"
        )

    def test_an_older_summary_without_n_scored_still_renders(self) -> None:
        """Guards the guard: artifacts written before this field must not break."""
        from bindsight.benchmark.designer_bench import _success_cell

        cell = _success_cell(
            {
                "success_rate": 0.5,
                "n_success": 8,
                "n_designs": 16,
                "success_ci_low": 0.3,
                "success_ci_high": 0.7,
            }
        )

        assert "8/16" in cell

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

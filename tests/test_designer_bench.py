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

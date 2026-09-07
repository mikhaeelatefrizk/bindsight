# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Regression tests for defects that produced plausible-but-wrong output.

Every test here pins a bug that the suite could not previously detect, because
the affected code was asserted only for shape or ordering and never against a
known-correct value. Each one fails against the pre-fix code.

The defects, in the order they appear below:

1. ``affinity_pred_value`` is a log(IC50)-like quantity where lower is stronger,
   and the ranker normalised it without inverting, so it preferred the weakest
   designs.
2. The composite score had no numeric assertion anywhere, so (1) was invisible.
3. Two validators wrote a structure-confidence metric into the affinity field,
   which the ranker then weighted as if it were an orthogonal signal.
4. Every target produced the same binder ids, so validation output collided on
   disk and ``validated.parquet`` carried duplicate keys.
5. Validators scored binders against the full-length receptor rather than the
   trimmed region the designer actually saw.
6. The design cache key was computed and never consulted, so an identical rerun
   paid for the GPU again.
7. Epitope pLDDT was read from an unresolved run-relative path, so it was
   ``None`` for every row of a normal run.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from bindsight.rank import rank_validated
from bindsight.runners import job_exec, tools


# ---------------------------------------------------------------------------
# 1 + 2. The ranking math, asserted numerically
# ---------------------------------------------------------------------------
class TestAffinityDirection:
    """A stronger predicted binder must score higher, not lower."""

    @staticmethod
    def _frame() -> pd.DataFrame:
        # Only the affinity column varies, so the composite isolates it.
        return pd.DataFrame(
            [
                {"binder_id": "strong", "target_uniprot": "P1", "affinity_pred_value": -8.0},
                {"binder_id": "middle", "target_uniprot": "P1", "affinity_pred_value": -6.0},
                {"binder_id": "weak", "target_uniprot": "P1", "affinity_pred_value": -4.0},
            ]
        )

    def test_lower_affinity_value_scores_higher(self) -> None:
        ranked = rank_validated(self._frame()).set_index("binder_id")
        # Min-max over (-8, -4), inverted: -8 is the tightest binder -> 1.0.
        assert ranked.loc["strong", "score_affinity"] == pytest.approx(1.0)
        assert ranked.loc["middle", "score_affinity"] == pytest.approx(0.5)
        assert ranked.loc["weak", "score_affinity"] == pytest.approx(0.0)

    def test_strongest_binder_ranks_first(self) -> None:
        ranked = rank_validated(self._frame())
        assert list(ranked["binder_id"]) == ["strong", "middle", "weak"]
        assert ranked.iloc[0]["rank"] == 1

    def test_composite_is_the_documented_weighted_mean(self) -> None:
        """Hand-computed composite, so a silent change of direction or weight fails here."""
        df = pd.DataFrame(
            [
                {
                    "binder_id": "a",
                    "target_uniprot": "P1",
                    "iptm": 0.9,
                    "affinity_pred_value": -9.0,
                },
                {
                    "binder_id": "b",
                    "target_uniprot": "P1",
                    "iptm": 0.7,
                    "affinity_pred_value": -7.0,
                },
                {
                    "binder_id": "c",
                    "target_uniprot": "P1",
                    "iptm": 0.5,
                    "affinity_pred_value": -5.0,
                },
            ]
        )
        ranked = rank_validated(df).set_index("binder_id")
        # structure = min-max(iptm); affinity = inverted min-max(affinity_pred_value).
        # Both components present, so the composite is their equally-weighted mean
        # (iptm 0.30, affinity 0.30) renormalised over the present weights.
        for binder, structure, affinity, composite in (
            ("a", 1.0, 1.0, 1.0),
            ("b", 0.5, 0.5, 0.5),
            ("c", 0.0, 0.0, 0.0),
        ):
            assert ranked.loc[binder, "score_structure"] == pytest.approx(structure)
            assert ranked.loc[binder, "score_affinity"] == pytest.approx(affinity)
            assert ranked.loc[binder, "score"] == pytest.approx(composite)

    def test_specificity_penalty_is_applied_to_evidence(self) -> None:
        """The evidence component divides by vital-tissue safety events, as documented."""
        validated = pd.DataFrame(
            [
                {"binder_id": "clean", "target_uniprot": "P1"},
                {"binder_id": "risky", "target_uniprot": "P2"},
            ]
        )
        candidates = pd.DataFrame(
            [
                {"uniprot_id": "P1", "log2fc": 4.0, "n_safety_events": 0},
                {"uniprot_id": "P2", "log2fc": 4.0, "n_safety_events": 3},
            ]
        )
        ranked = rank_validated(validated, candidates).set_index("binder_id")
        # Equal log2fc, so min-max gives both 0.5; the penalty is what separates them.
        assert ranked.loc["clean", "score_evidence"] == pytest.approx(0.5)
        assert ranked.loc["risky", "score_evidence"] == pytest.approx(0.5 / 4.0)


# ---------------------------------------------------------------------------
# 3. Confidence metrics are not affinities
# ---------------------------------------------------------------------------
class TestConfidenceIsNotAffinity:
    """A validator that predicts no affinity must leave the affinity field empty."""

    def test_chai_ptm_does_not_become_an_affinity(self, tmp_path: Path) -> None:
        np = pytest.importorskip("numpy")
        out = tmp_path / "chai"
        out.mkdir()
        np.savez(out / "scores.model_idx_0.npz", iptm=np.array(0.72), ptm=np.array(0.81))
        result = tools.parse_chai_output(out, binder_id="b0", target_uniprot="P04626")
        assert result.affinity_pred_value is None
        assert result.ptm == pytest.approx(0.81)
        assert result.iptm == pytest.approx(0.72)

    def test_af2ig_plddt_does_not_become_an_affinity(self, tmp_path: Path) -> None:
        sc = tmp_path / "af2_scores.sc"
        sc.write_text("pae_interaction plddt_binder\n6.5 88.0\n")
        result = tools.parse_af2ig_output(sc, binder_id="b0", target_uniprot="P04626")
        assert result.affinity_pred_value is None
        assert result.plddt_binder == pytest.approx(88.0)
        assert result.pae_interaction == pytest.approx(6.5)

    def test_a_confidence_metric_cannot_be_ranked_as_affinity(self) -> None:
        """With no affinity anywhere, the affinity component must be absent, not invented."""
        df = pd.DataFrame(
            [
                {"binder_id": "a", "target_uniprot": "P1", "iptm": 0.8, "ptm": 0.9},
                {"binder_id": "b", "target_uniprot": "P1", "iptm": 0.4, "ptm": 0.5},
            ]
        )
        ranked = rank_validated(df)
        assert ranked["score_affinity"].isna().all()
        # pTM still counts, but as structure confidence.
        assert ranked.set_index("binder_id").loc["a", "score_structure"] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# 4. Binder identity is unique across targets
# ---------------------------------------------------------------------------
class TestBinderIdentity:
    """``binder_id`` is the key the provenance chain is walked by."""

    def test_prefix_is_derived_from_the_target(self) -> None:
        assert job_exec._binder_id_prefix({"target_uniprot": "P04626"}) == "P04626"
        assert job_exec._binder_id_prefix({"target_uniprot": ""}) == "target"
        assert job_exec._binder_id_prefix({}) == "target"
        # Anything that would break a path or a column name is neutralised.
        assert "/" not in job_exec._binder_id_prefix({"target_uniprot": "P0/46 26"})

    def test_two_targets_do_not_produce_colliding_ids(self, tmp_path: Path) -> None:
        """The same designer output under two targets must yield distinct ids."""
        ids: list[str] = []
        for uniprot in ("P04626", "P00533"):
            work = tmp_path / uniprot
            out = work / "designer_out"
            out.mkdir(parents=True)
            # Both targets produce an identically-named backbone, which is exactly
            # what RFdiffusion's fixed output prefix does.
            (out / "binder_0.pdb").write_text(
                "ATOM      1  CA  ALA A   1      0.000   0.000   0.000  1.00  0.00           C\n"
            )
            designs = job_exec._collect_designs_from_dir(
                out, work, prefix="boltzgen", spec={"target_uniprot": uniprot}
            )
            ids += [d.binder_id for d in designs]
        assert len(ids) == 2
        assert len(set(ids)) == 2, f"binder ids collided across targets: {ids}"
        assert all(uid.startswith(("P04626_", "P00533_")) for uid in ids)


# ---------------------------------------------------------------------------
# 5. Validators score the region the designer saw
# ---------------------------------------------------------------------------
def _write_pdb(path: Path, *, chain: str = "A", first: int = 1, n: int = 10) -> Path:
    """A CA-only chain of ``n`` alanines numbered from ``first``."""
    lines = []
    for i in range(n):
        resi = first + i
        lines.append(
            f"ATOM  {i + 1:>5}  CA  ALA {chain}{resi:>4}      "
            f"{0.0:>8.3f}{0.0:>8.3f}{0.0:>8.3f}  1.00  0.00           C"
        )
    path.write_text("\n".join(lines) + "\n")
    return path


class TestValidationUsesTheDesignRegion:
    """A binder designed against a trimmed domain must not be scored against the whole receptor."""

    def test_sequence_is_restricted_to_the_design_ranges(self, tmp_path: Path) -> None:
        work = tmp_path / "work"
        work.mkdir()
        _write_pdb(work / "target.pdb", first=1, n=10)
        spec: dict[str, Any] = {"epitope_chain": "A", "design_ranges": [[3, 6]]}
        seq = job_exec._target_sequence_for_design(spec, work, "A")
        assert len(seq) == 4, "validation must see only residues 3-6, not the full chain"
        assert len(tools.chain_sequence_from_pdb(work / "target.pdb", "A")) == 10

    def test_absent_ranges_fall_back_to_the_whole_chain(self, tmp_path: Path) -> None:
        work = tmp_path / "work"
        work.mkdir()
        _write_pdb(work / "target.pdb", first=1, n=10)
        seq = job_exec._target_sequence_for_design({"epitope_chain": "A"}, work, "A")
        assert len(seq) == 10

    def test_boltz_yaml_carries_the_trimmed_target(self, tmp_path: Path) -> None:
        """End-to-end through the spec the validator actually submits."""
        work = tmp_path / "work"
        work.mkdir()
        _write_pdb(work / "target.pdb", first=1, n=12)
        spec = {"epitope_chain": "A", "design_ranges": [[2, 5]]}
        target_seq = job_exec._target_sequence_for_design(spec, work, "A")
        yaml_spec = tools.build_boltz_yaml(
            target_id="T",
            target_sequence=target_seq,
            binder_id="b0",
            binder_sequence="AAAA",
            predict_affinity=False,
        )
        target_chain = yaml_spec["sequences"][0]["protein"]
        assert len(target_chain["sequence"]) == 4


# ---------------------------------------------------------------------------
# 6. Idempotency: an identical rerun must not resubmit
# ---------------------------------------------------------------------------
class _CountingRunner:
    """Minimal GPURunner double that records how many jobs were submitted."""

    name = "counting"

    def __init__(self, archive: Path) -> None:
        self.archive = archive
        self.submits = 0

    def estimate_cost(self, spec_size: int) -> Any:  # pragma: no cover - unused here
        raise NotImplementedError

    def submit(self, spec_path: Path, *, results_dir: Path) -> Any:
        self.submits += 1
        results_dir.mkdir(parents=True, exist_ok=True)
        return {"id": "job"}

    def poll(self, handle: Any) -> Any:  # pragma: no cover - fetch is synchronous here
        raise NotImplementedError

    def fetch(self, handle: Any) -> Path:
        return self.archive


class TestDesignCacheIsConsulted:
    """ARCHITECTURE 4.4 promises reruns skip completed work; it must actually happen."""

    @staticmethod
    def _spec(structure: Path) -> Any:
        from bindsight.design.protocol import DesignSpec

        return DesignSpec(
            target_uniprot="P04626",
            target_structure_path=str(structure),
            epitope_chain="A",
            epitope_residues=[1, 2, 3],
            design_ranges=[(1, 10)],
            n_trajectories=2,
            seed=0,
            extra_params={"designer": "rfdiff_mpnn"},
        )

    def test_second_identical_submit_is_a_cache_hit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import tarfile

        from bindsight.design._common import make_cache_key, submit_via_runner

        monkeypatch.chdir(tmp_path)
        structure = _write_pdb(tmp_path / "target.pdb", n=10)

        work = tmp_path / "payload"
        work.mkdir()
        (work / "metrics.jsonl").write_text(json.dumps({"binder_id": "b0", "iptm": 0.7}) + "\n")
        archive = tmp_path / "results.tar.gz"
        with tarfile.open(archive, "w:gz") as tf:
            tf.add(work / "metrics.jsonl", arcname="metrics.jsonl")

        spec = self._spec(structure)
        key = make_cache_key(spec)
        runner = _CountingRunner(archive)

        first = submit_via_runner(
            spec,
            runner,
            designer_name="rfdiff_mpnn",
            designer_version="0.1.0",
            designer_commit_sha=None,
            cache_key=key,
        )
        assert runner.submits == 1
        assert first.cache_status == "miss"

        second = submit_via_runner(
            spec,
            runner,
            designer_name="rfdiff_mpnn",
            designer_version="0.1.0",
            designer_commit_sha=None,
            cache_key=key,
        )
        assert runner.submits == 1, "an identical rerun resubmitted instead of reusing the result"
        assert second.cache_status == "hit"

    def test_key_changes_when_the_target_structure_changes(self, tmp_path: Path) -> None:
        """A new AlphaFold model for the same accession is different work."""
        from bindsight.design._common import make_cache_key

        structure = _write_pdb(tmp_path / "target.pdb", n=10)
        before = make_cache_key(self._spec(structure))
        _write_pdb(structure, n=11)
        after = make_cache_key(self._spec(structure))
        assert before != after


# ---------------------------------------------------------------------------
# 7. Epitope pLDDT resolves the stored run-relative path
# ---------------------------------------------------------------------------
def test_epitope_plddt_resolves_a_run_relative_path(tmp_path: Path, fixtures_dir: Path) -> None:
    """``adopt_structure`` stores run-relative paths; the epitope column must resolve them."""
    from bindsight.config import TargetDiscoveryParams
    from bindsight.pipelines.discover import _build_epitopes

    cif = fixtures_dir / "plddt" / "AF-TEST1-F1-model_v6.cif"
    if not cif.exists():  # pragma: no cover - fixture is committed
        pytest.skip("pLDDT fixture not present")

    run_root = tmp_path / "run"
    (run_root / "structures").mkdir(parents=True)
    stored = "structures/AF-TEST1-F1-model_v6.cif"
    (run_root / stored).write_bytes(cif.read_bytes())

    top = pd.DataFrame(
        [
            {
                "gene_id": "ENSG1",
                "symbol": "TEST1",
                "uniprot_id": "TEST1",
                "alphafold_structure_path": stored,
            }
        ]
    )
    epitopes = _build_epitopes(
        top, None, TargetDiscoveryParams(), topology_map={}, run_root=run_root
    )
    assert len(epitopes) == 1
    assert epitopes.iloc[0]["mean_epitope_plddt"] is not None, (
        "mean_epitope_plddt was None: the run-relative structure path was not resolved"
    )


# ---------------------------------------------------------------------------
# 8. dl_binder_design needs its silent_tools submodule
# ---------------------------------------------------------------------------
def test_af2ig_clone_requests_submodules(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """predict.py imports silent_tools at module scope, and it is a git submodule.

    A plain clone leaves that directory empty, so the AF2 initial-guess validator
    fails on import rather than at any legible point.
    """
    calls: list[list[str]] = []

    def _fake_run(cmd: list[str], *, cwd: Path | None = None) -> Any:
        calls.append(list(cmd))
        # git clone must appear to have created the destination.
        if cmd[:2] == ["git", "clone"]:
            Path(cmd[-1]).mkdir(parents=True, exist_ok=True)
        return None

    monkeypatch.setattr(job_exec, "_run", _fake_run)
    job_exec._git_clone("https://example/repo", "abc123", tmp_path / "dl", submodules=True)
    assert any(c[:2] == ["git", "submodule"] for c in calls), (
        "submodules were not initialised: silent_tools would be missing"
    )


def test_plain_clone_does_not_fetch_submodules(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[list[str]] = []

    def _fake_run(cmd: list[str], *, cwd: Path | None = None) -> Any:
        calls.append(list(cmd))
        if cmd[:2] == ["git", "clone"]:
            Path(cmd[-1]).mkdir(parents=True, exist_ok=True)
        return None

    monkeypatch.setattr(job_exec, "_run", _fake_run)
    job_exec._git_clone("https://example/repo", "abc123", tmp_path / "plain")
    assert not any(c[:2] == ["git", "submodule"] for c in calls)


# ---------------------------------------------------------------------------
# 9. The enrichment cut is spent on surface proteins, not the whole genome
# ---------------------------------------------------------------------------
class TestSurfaceomePrefilter:
    """Enrichment slots are scarce; spending them on non-targets discards the surfaceome.

    Measured on real data before this change: in bladder cancer 4,418 genes were
    significant, the top 300 by combined score went to enrichment, and only 24 of
    them were surface proteins. NECTIN4 — the target of an approved drug for that
    exact indication, genuinely over-expressed at log2fc 1.52 — ranked 259th of
    2,104 surface proteins and was still excluded, because it was competing
    against every gene in the genome rather than against other surface proteins.
    """

    def test_the_prefilter_is_on_by_default(self) -> None:
        from bindsight.config import TargetDiscoveryParams

        assert TargetDiscoveryParams().surfaceome_prefilter is True

    def test_a_non_surface_gene_is_recorded_as_such_not_blamed_on_the_cut(self) -> None:
        """The disposition must name the filter that actually excluded the gene."""
        import pandas as pd

        from bindsight.config import TargetDiscoveryParams
        from bindsight.pipelines.discover import _build_taxonomy

        deg = pd.DataFrame(
            [
                {"gene_id": "ENSG_SURFACE", "log2fc": 3.0, "padj": 1e-9, "significant": True},
                {"gene_id": "ENSG_CYTOSOL", "log2fc": 3.0, "padj": 1e-9, "significant": True},
            ]
        )
        taxonomy = _build_taxonomy(
            deg,
            {"ENSG_SURFACE"},  # only the surface gene was enriched
            pd.DataFrame(),
            pd.DataFrame(),
            pd.DataFrame(),
            frozenset(),
            TargetDiscoveryParams(),
            surface_bind_active=False,
            structure_queried=frozenset(),
            surfaceome_gene_ids=frozenset({"ENSG_SURFACE"}),
        )
        disposition = dict(zip(taxonomy["gene_id"], taxonomy["disposition"], strict=True))
        assert disposition["ENSG_CYTOSOL"] == "not_surfaceome"

    def test_without_the_prefilter_the_old_disposition_is_preserved(self) -> None:
        """An empty gene set means the pre-filter did not run, so the cut is to blame."""
        import pandas as pd

        from bindsight.config import TargetDiscoveryParams
        from bindsight.pipelines.discover import _build_taxonomy

        deg = pd.DataFrame(
            [{"gene_id": "ENSG_X", "log2fc": 3.0, "padj": 1e-9, "significant": True}]
        )
        taxonomy = _build_taxonomy(
            deg,
            set(),
            pd.DataFrame(),
            pd.DataFrame(),
            pd.DataFrame(),
            frozenset(),
            TargetDiscoveryParams(),
            surface_bind_active=False,
            structure_queried=frozenset(),
            surfaceome_gene_ids=frozenset(),
        )
        assert taxonomy.iloc[0]["disposition"] == "below_enrichment_cutoff"


# ---------------------------------------------------------------------------
# 10. Differential expression is reused when its inputs are unchanged
# ---------------------------------------------------------------------------
class TestDegCache:
    """The most expensive stage must not re-run for an identical computation.

    Measured on a real cohort of 32 matched pairs, this stage alone exceeds ten
    minutes. Re-running it because something downstream changed spends that time
    to arrive at exactly the same table.
    """

    @staticmethod
    def _inputs(counts_sha: str, design_sha: str) -> list[Any]:
        from bindsight.provenance.manifest import InputRef

        # The schema requires a real 64-character digest, so the short labels are
        # expanded rather than weakening the model to suit the test.
        def _digest(label: str) -> str:
            return (label * 64)[:64]

        return [
            InputRef(role="counts", path="c.tsv", sha256=_digest(counts_sha), bytes=1),
            InputRef(role="design", path="d.tsv", sha256=_digest(design_sha), bytes=1),
        ]

    def test_identical_inputs_and_params_give_the_same_key(self) -> None:
        from bindsight.pipelines.discover import _deg_cache_key

        params = {"design_formula": "~ condition", "fdr_threshold": 0.05}
        a = _deg_cache_key(self._inputs("aa", "bb"), params)
        b = _deg_cache_key(self._inputs("aa", "bb"), dict(params))
        assert a == b

    def test_changed_counts_change_the_key(self) -> None:
        """Keying on the path rather than the content would reuse a stale table."""
        from bindsight.pipelines.discover import _deg_cache_key

        params = {"design_formula": "~ condition"}
        assert _deg_cache_key(self._inputs("aa", "bb"), params) != _deg_cache_key(
            self._inputs("cc", "bb"), params
        )

    def test_changed_parameters_change_the_key(self) -> None:
        """A run recorded under one configuration must not be reported under another."""
        from bindsight.pipelines.discover import _deg_cache_key

        inputs = self._inputs("aa", "bb")
        unpaired = _deg_cache_key(inputs, {"design_formula": "~ condition"})
        paired = _deg_cache_key(inputs, {"design_formula": "~ case_barcode + condition"})
        assert unpaired != paired

    def test_input_order_does_not_change_the_key(self) -> None:
        from bindsight.pipelines.discover import _deg_cache_key

        inputs = self._inputs("aa", "bb")
        assert _deg_cache_key(inputs, {}) == _deg_cache_key(list(reversed(inputs)), {})


class TestKaggleHardwareIsDescribedConsistently:
    """The pinned accelerator and the costed one must be the same card.

    Pinning ``machine_shape`` to a T4 fixed the real problem — Kaggle's default
    P100 cannot run the current stack — but left ``KaggleRunner`` defaulting to
    ``gpu_type="P100"``. Nothing failed. Estimates simply applied the P100's
    3.0x slowdown factor where the T4's 4.0x was correct, under-quoting every
    Kaggle runtime by a quarter, on hardware no run would ever be given.
    """

    def test_the_runner_costs_the_card_the_kernel_pins(self) -> None:
        from bindsight.runners.kaggle import KaggleRunner
        from bindsight.runners.kaggle_kernel import (
            KAGGLE_ACCELERATOR,
            KAGGLE_COST_GPU,
        )

        # "NvidiaTeslaT4" and "T4" are the same card under two vocabularies:
        # Kaggle's metadata name and the cost table's key.
        assert KAGGLE_COST_GPU.lower() in KAGGLE_ACCELERATOR.lower().replace("nvidiatesla", "")
        assert KaggleRunner().gpu_type == KAGGLE_COST_GPU

    def test_the_costed_card_is_priced_and_has_a_slowdown_factor(self) -> None:
        """An unknown GPU key would fall back to a default and quote silently wrong."""
        from bindsight.cost import _GPU_SLOWDOWN, GPU_PRICE_USD_PER_HOUR
        from bindsight.runners.kaggle_kernel import KAGGLE_COST_GPU

        assert ("kaggle", KAGGLE_COST_GPU) in GPU_PRICE_USD_PER_HOUR
        assert KAGGLE_COST_GPU in _GPU_SLOWDOWN

    def test_the_pinned_card_clears_the_compute_capability_gate(self) -> None:
        """A pin below the gate would make every kernel exit on its own check."""
        from bindsight.runners.kaggle_kernel import (
            KAGGLE_ACCELERATOR,
            MIN_COMPUTE_CAPABILITY,
        )

        # Turing (T4) is 7.5; Pascal (P100) is 6.0 and must not satisfy the gate.
        assert MIN_COMPUTE_CAPABILITY >= (7, 5)
        assert "P100" not in KAGGLE_ACCELERATOR

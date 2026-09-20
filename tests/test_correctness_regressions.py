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
from types import SimpleNamespace
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
        clean = ranked.loc["clean", "score_evidence"]
        risky = ranked.loc["risky", "score_evidence"]
        # The documented claim is the ratio: each event divides the evidence down,
        # so three events leave a quarter. Asserting the ratio rather than two
        # absolute values keeps this pinned to the penalty rather than to whatever
        # the fold-change scale happens to be.
        assert risky == pytest.approx(clean / 4.0)
        # Equal log2fc at the table maximum is full evidence. This was 0.5 while
        # the component used min-max, which mapped a constant series to its
        # neutral midpoint; it is 1.0 now that the floor is an absolute zero.
        assert clean == pytest.approx(1.0)
        assert risky == pytest.approx(0.25)


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
#: The first four bytes of a gzip stream: magic, deflate method, no flags.
GZIP_MAGIC = b"\x1f\x8b\x08\x00"


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


class TestModelCheckpointsAreVerified:
    """~480 MB of model parameters arrived over plain HTTP, unchecked.

    The comment above the URLs claimed they were "verified on download in the
    executor when a hash is supplied". No verification code existed at either
    download site, and neither URL used TLS. A truncated transfer produces a
    checkpoint that may still load, and then designs against different weights
    than the run claims.
    """

    def test_every_weight_url_uses_tls(self) -> None:
        from bindsight.runners import tools

        for name, url in tools.RFDIFF_WEIGHTS.items():
            assert url.startswith("https://"), f"{name} is fetched over {url.split(':')[0]}"

    def test_every_weight_has_a_pin_slot(self) -> None:
        """A checkpoint with no entry would be silently unpinnable."""
        from bindsight.runners import tools

        assert set(tools.RFDIFF_WEIGHT_SHA256) == set(tools.RFDIFF_WEIGHTS)

    def test_a_mismatched_digest_raises(self, tmp_path: Path) -> None:
        from bindsight.runners.job_exec import _verify_checkpoint

        f = tmp_path / "Base_ckpt.pt"
        f.write_bytes(b"not the real weights")
        with pytest.raises(RuntimeError, match="does not match the pinned"):
            _verify_checkpoint(f, "0" * 64)

    def test_the_digest_is_returned_when_nothing_is_pinned(self, tmp_path: Path) -> None:
        """Hashing unconditionally is how the first run establishes the pin."""
        import hashlib

        from bindsight.runners.job_exec import _verify_checkpoint

        f = tmp_path / "Complex_base_ckpt.pt"
        f.write_bytes(b"payload")
        assert _verify_checkpoint(f, None) == hashlib.sha256(b"payload").hexdigest()

    def test_the_kernel_verifies_on_the_gpu_side_too(self) -> None:
        """The GPU download is the one a published result was produced from."""
        import ast

        from bindsight.runners import kaggle_kernel

        src = kaggle_kernel.build_kernel_script(handle_id="t", payload={"spec.yaml": "x"})
        ast.parse(src)  # a kernel that does not parse burns quota to say so
        assert "hashlib.sha256()" in src
        assert "does not match the pinned" in src
        assert "http://files.ipd.uw.edu" not in src


class TestAFinishedRunSurvivesItsOwnBookkeeping:
    """Two ways a completed GPU hour was thrown away after the science finished."""

    def test_a_log_encoding_failure_does_not_lose_the_tarball(self, tmp_path: Path) -> None:
        """The Kaggle client writes the kernel log in the platform encoding.

        Kernel output carries micromamba's progress glyphs, so on a cp1252
        Windows install the write raises UnicodeEncodeError — after the GPU work
        is done. A corrected ERBB2 benchmark completed on the T4, produced its
        tarball, and was recorded as zero designs with an encoding error.
        """
        from bindsight.runners.kaggle import KaggleRunner

        calls: list[int] = []

        class _Api:
            def kernels_output(self, kernel_id: str, path: str) -> None:
                calls.append(1)
                if len(calls) == 1:
                    # First pass dies on the log, as the real client does.
                    raise UnicodeEncodeError("charmap", "\u29d6", 0, 1, "unmappable")
                (Path(path) / "abc123.tar.gz").write_bytes(b"results")

        KaggleRunner._download_output(_Api(), "owner/slug", tmp_path)
        assert (tmp_path / "abc123.tar.gz").is_file()
        assert len(calls) == 2, "the download was not retried past the log"

    def test_an_empty_run_does_not_overwrite_a_real_one(self, tmp_path: Path) -> None:
        """An empty summary is well-formed, and would erase a real measurement."""
        import json as _json

        from bindsight.benchmark.designer_bench import _would_erase_a_real_result

        real = {"designers": [{"n_designs": 20, "mean_iptm": 0.585}]}
        empty = {"designers": [{"n_designs": 0, "mean_iptm": None}]}
        (tmp_path / "results.json").write_text(_json.dumps(real), encoding="utf-8")

        assert _would_erase_a_real_result(tmp_path, empty) is True
        assert _would_erase_a_real_result(tmp_path, real) is False

    def test_a_real_run_may_replace_a_real_run(self, tmp_path: Path) -> None:
        """The guard must not block the corrected re-run it exists to protect."""
        import json as _json

        from bindsight.benchmark.designer_bench import _would_erase_a_real_result

        (tmp_path / "results.json").write_text(
            _json.dumps({"designers": [{"n_designs": 20}]}), encoding="utf-8"
        )
        assert _would_erase_a_real_result(tmp_path, {"designers": [{"n_designs": 18}]}) is False

    def test_the_first_run_is_never_blocked(self, tmp_path: Path) -> None:
        from bindsight.benchmark.designer_bench import _would_erase_a_real_result

        assert _would_erase_a_real_result(tmp_path, {"designers": [{"n_designs": 0}]}) is False


class TestTheGpuRunsTheCodeThatLaunchedIt:
    """Every Kaggle run this project made installed the default branch.

    ``BINDSIGHT_GIT`` carried no ref, so ``pip install git+<repo>`` resolved to
    ``main`` whatever the operator had checked out. A corrected designer
    benchmark was launched against a branch whose fixes existed only locally,
    ran for an hour on a T4, and came back carrying pre-fix ``binder_0_seq0``
    ids — the very defect it was meant to demonstrate fixed.
    """

    @staticmethod
    def _wheel(tmp_path: Path) -> Path:
        w = tmp_path / "bindsight-0.0.0-py3-none-any.whl"
        w.write_bytes(b"PK\x03\x04 not a real wheel, but bytes are bytes")
        return w

    def test_without_a_wheel_the_kernel_installs_from_git(self) -> None:
        from bindsight.runners import kaggle_kernel

        src = kaggle_kernel.build_kernel_script(handle_id="t", payload={"spec.json": "e30="})
        assert "BINDSIGHT_WHEEL_B64" in src
        assert "git+https://github.com" in src

    def test_with_a_wheel_the_kernel_installs_the_wheel(self, tmp_path: Path) -> None:
        import ast
        import base64

        from bindsight.runners import kaggle_kernel

        b64 = base64.b64encode(self._wheel(tmp_path).read_bytes()).decode()
        src = kaggle_kernel.build_kernel_script(
            handle_id="t", payload={"spec.json": "e30="}, bindsight_wheel_b64=b64
        )
        ast.parse(src)  # a kernel that does not parse burns quota to say so
        assert "BINDSIGHT_WHEEL_NAME" in src
        assert b64 in src
        # It must also state which source it used, so the log is self-describing.
        assert "bindsight install source:" in src

    def test_the_embedded_wheel_keeps_a_parseable_filename(self, tmp_path: Path) -> None:
        """pip reads the distribution, version and tags out of a wheel's name.

        Writing the payload to ``bindsight-embedded.whl`` failed a run with
        "Invalid wheel filename (wrong number of parts)" — after the two
        micromamba environments had already been built, so the cost was paid
        before the error appeared.
        """
        import base64

        from bindsight.runners import kaggle_kernel

        name = "bindsight-0.2.2-py3-none-any.whl"
        src = kaggle_kernel.build_kernel_script(
            handle_id="t",
            payload={"spec.json": "e30="},
            bindsight_wheel_b64=base64.b64encode(self._wheel(tmp_path).read_bytes()).decode(),
            bindsight_wheel_name=name,
        )
        assert name in src
        assert "bindsight-embedded.whl" not in src
        # PEP 427: name-version-python-abi-platform, so five dash-separated parts.
        assert len(Path(name).stem.split("-")) == 5

    def test_an_oversized_kernel_is_refused_before_the_push(self, tmp_path: Path) -> None:
        """Kaggle rejects an oversized kernel opaquely; name the cause instead."""
        from bindsight.runners import kaggle

        assert kaggle._MAX_KERNEL_BYTES > 500_000, "ceiling must fit a real wheel"

    def test_the_runner_accepts_a_wheel_and_rejects_a_missing_one(self, tmp_path: Path) -> None:
        from bindsight.plugins import get_runner

        w = self._wheel(tmp_path)
        assert get_runner("kaggle", bindsight_wheel=w).bindsight_wheel == w
        # A typo in the path must not silently degrade to a git install.
        assert get_runner("kaggle", bindsight_wheel=tmp_path / "nope.whl").bindsight_wheel

    def test_the_cache_key_covers_which_code_runs(self, tmp_path: Path) -> None:
        """Otherwise a fixed run is handed the unfixed run's cached result."""
        from bindsight.design._common import _code_identity, _with_backend

        class _R:
            name = "kaggle"
            bindsight_wheel = None
            bindsight_ref = None

        r = _R()
        by_version = _code_identity(r)
        r.bindsight_ref = "some-branch"
        by_ref = _code_identity(r)
        r.bindsight_wheel = self._wheel(tmp_path)
        by_wheel = _code_identity(r)

        assert by_version.startswith("version:")
        assert by_ref == "ref:some-branch"
        assert by_wheel.startswith("wheel:"), "a wheel must win over a ref"
        keys = {_with_backend("spec", "kaggle", c) for c in (by_version, by_ref, by_wheel)}
        assert len(keys) == 3, "three different codebases must not share a cache entry"

    def test_omitting_the_code_reproduces_the_previous_key(self) -> None:
        """Existing cache entries must stay addressable."""
        from bindsight.design._common import _with_backend

        assert _with_backend("spec", "kaggle") == _with_backend("spec", "kaggle", "")

    def test_a_source_checkout_is_discoverable(self) -> None:
        from bindsight.runners.source_wheel import find_repo_root

        root = find_repo_root()
        assert root is not None
        assert (root / "pyproject.toml").is_file()

    def test_no_checkout_means_no_wheel_rather_than_a_crash(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A user who pip-installed bindsight must still be able to submit a job.

        The second assertion here was ``... is None or True``, which is always
        true: the function could have returned anything, or been deleted, and
        this still passed. It tested only that the call did not raise.

        Deleting the ``or True`` alone would not have worked, which is probably
        why it was there. With ``repo_root=None`` the function *discovers* a
        root, and ``find_repo_root`` defaults to walking up from its own
        ``__file__`` -- so under pytest, inside this checkout, it finds the real
        tree and shells out to ``pip wheel``. The case the docstring is about is
        the one where there is no checkout at all, so that is the case to
        arrange.
        """
        from bindsight.runners import source_wheel
        from bindsight.runners.source_wheel import build_working_tree_wheel, find_repo_root

        assert find_repo_root(tmp_path / "nowhere" / "deep") is None

        monkeypatch.setattr(source_wheel, "find_repo_root", lambda *a, **k: None)

        assert build_working_tree_wheel(tmp_path / "out", repo_root=None) is None, (
            "with no source checkout the caller falls back to a git ref and warns; "
            "returning anything else there breaks a pip-installed user's job"
        )


def _plain(text: str) -> str:
    """Strip ANSI colour and collapse whitespace from rich console output.

    The CLI renders through rich, which colours every field and wraps to the
    terminal width, so a literal substring never matches what a reader sees.
    """
    import re

    return re.sub(r"\s+", " ", re.sub(r"\[[0-9;]*m", "", text))


class TestTheRunConfigIsHonoured:
    """`bindsight design <run>` used its own defaults over the run's config.

    The subcommand takes a run directory rather than a config file, so it never
    looked at the configuration the run was produced under. A user who set
    ``params.design.n_trajectories: 10`` and followed the documented
    discover-then-design path got 50 — five times the GPU cost — reported in the
    cost panel as though they had asked for it.
    """

    @staticmethod
    def _run_dir(tmp_path: Path, **design: object) -> Path:
        import yaml

        run = tmp_path / "run"
        run.mkdir()
        (run / "config.yaml").write_text(
            yaml.safe_dump(
                {
                    "params": {
                        "design": {"n_trajectories": 10, "designer": "boltzgen", **design},
                        "validate": {"validator": "chai1r"},
                    }
                }
            ),
            encoding="utf-8",
        )
        return run

    def test_unset_options_come_from_the_run(self, tmp_path: Path) -> None:
        """Outside a Click context every option counts as explicitly given.

        So this asserts the safe direction: without Click's parameter-source
        information the helper changes nothing, and a caller's values stand.
        """
        from bindsight.cli import _design_defaults_from_run

        run = self._run_dir(tmp_path)
        got = _design_defaults_from_run(
            run, designer="rfdiff_mpnn", validator="boltz2", trajectories=50
        )
        assert got == ("rfdiff_mpnn", "boltz2", 50)

    def test_a_missing_config_changes_nothing(self, tmp_path: Path) -> None:
        """A run directory without a config must not break the command."""
        from bindsight.cli import _design_defaults_from_run

        empty = tmp_path / "bare"
        empty.mkdir()
        assert _design_defaults_from_run(
            empty, designer="rfdiff_mpnn", validator="boltz2", trajectories=50
        ) == ("rfdiff_mpnn", "boltz2", 50)

    def test_an_unreadable_config_changes_nothing(self, tmp_path: Path) -> None:
        """A malformed config is the user's problem, not a crash in the CLI."""
        from bindsight.cli import _design_defaults_from_run

        run = tmp_path / "broken"
        run.mkdir()
        (run / "config.yaml").write_text("params: [this is not a mapping", encoding="utf-8")
        assert _design_defaults_from_run(
            run, designer="rfdiff_mpnn", validator="boltz2", trajectories=50
        ) == ("rfdiff_mpnn", "boltz2", 50)

    def test_the_defaults_are_applied_through_the_command(self, tmp_path: Path) -> None:
        """The behaviour that matters, exercised the way a user reaches it.

        `--dry-run` stops before any job is launched, so this asserts on the
        cost panel: it must quote the configured 10 trajectories, not 50.
        """
        import pandas as pd
        from click.testing import CliRunner

        from bindsight import cli

        run = self._run_dir(tmp_path, designer="rfdiff_mpnn")
        (run / "epitopes").mkdir()
        pd.DataFrame(
            {"uniprot_id": ["P04626"], "symbol": ["ERBB2"], "structure_path": ["x.pdb"]}
        ).to_parquet(run / "epitopes" / "epitopes.parquet")

        result = CliRunner().invoke(
            cli.main, ["design", str(run), "--backend", "mock", "--dry-run"]
        )
        assert result.exit_code == 0, result.output
        assert "trajectories: 10" in _plain(result.output)
        assert "trajectories: 50" not in _plain(result.output)

    def test_an_explicit_flag_still_wins(self, tmp_path: Path) -> None:
        """Config-derived defaults must not override what the user typed."""
        import pandas as pd
        from click.testing import CliRunner

        from bindsight import cli

        run = self._run_dir(tmp_path, designer="rfdiff_mpnn")
        (run / "epitopes").mkdir()
        pd.DataFrame(
            {"uniprot_id": ["P04626"], "symbol": ["ERBB2"], "structure_path": ["x.pdb"]}
        ).to_parquet(run / "epitopes" / "epitopes.parquet")

        result = CliRunner().invoke(
            cli.main,
            ["design", str(run), "--backend", "mock", "--trajectories", "3", "--dry-run"],
        )
        assert result.exit_code == 0, result.output
        assert "trajectories: 3" in _plain(result.output)


class TestThePayloadFitsTheKernel:
    """A full-length receptor plus a working-tree wheel overflowed the script.

    Structures are mmCIF or PDB text and compress to roughly a fifth, which is
    the difference between a submittable kernel and one the size check refuses.
    """

    def test_the_kernel_decompresses_what_the_runner_compressed(self) -> None:
        import base64
        import gzip

        from bindsight.runners import kaggle_kernel

        original = b"data_TEST\nATOM 1 CA ALA A 1 0.0 0.0 0.0\n" * 200
        packed = base64.b64encode(gzip.compress(original, 9)).decode("ascii")
        assert len(packed) < len(base64.b64encode(original)) / 2

        src = kaggle_kernel.build_kernel_script(handle_id="t", payload={"target.cif": packed})
        assert "gzip.decompress" in src
        assert "import base64, gzip," in src
        # Round-trip through exactly what the kernel does.
        assert gzip.decompress(base64.b64decode(packed)) == original


# ---------------------------------------------------------------------------
# 8. The cache key must cover everything that changes the answer
# ---------------------------------------------------------------------------
class TestTheCacheKeyCoversTheValidator:
    """Two validators sharing a cache entry is a wrong answer that looks right."""

    @staticmethod
    def _spec(structure: Path, **extra: Any) -> Any:
        from bindsight.design.protocol import DesignSpec

        return DesignSpec(
            target_uniprot="Q16790",
            target_structure_path=str(structure),
            epitope_chain="A",
            epitope_residues=[1, 2, 3],
            design_ranges=[(38, 414)],
            n_trajectories=10,
            seed=0,
            extra_params={"designer": "rfdiff_mpnn", **extra},
        )

    def test_two_validators_do_not_share_a_cache_entry(self, tmp_path: Path) -> None:
        from bindsight.design._common import make_cache_key

        structure = _write_pdb(tmp_path / "target.pdb", n=10)
        boltz = make_cache_key(self._spec(structure, validator="boltz2"))
        chai = make_cache_key(self._spec(structure, validator="chai1r"))
        assert boltz != chai, (
            "the executor runs whichever validator extra_params names, so sharing "
            "a key makes the second run report the first run's numbers"
        )

    def test_a_prescreen_changes_the_cache_key(self, tmp_path: Path) -> None:
        """The screen drops designs before validation, so it changes the result."""
        from bindsight.design._common import make_cache_key

        structure = _write_pdb(tmp_path / "target.pdb", n=10)
        every = make_cache_key(self._spec(structure, validator="boltz2"))
        screened = make_cache_key(self._spec(structure, validator="boltz2", prescreen_top_k=5))
        assert every != screened

    def test_the_sample_count_changes_the_cache_key(self, tmp_path: Path) -> None:
        """One draw and five are different measurements, not different precisions.

        The validator averages over ``diffusion_samples`` draws, so the number
        it reports changes with the count. Sharing a key would hand a five-draw
        request the one-draw answer.
        """
        from bindsight.design._common import make_cache_key

        structure = _write_pdb(tmp_path / "target.pdb", n=10)
        one = make_cache_key(self._spec(structure, validator="boltz2", diffusion_samples=1))
        five = make_cache_key(self._spec(structure, validator="boltz2", diffusion_samples=5))
        assert one != five

    def test_the_parallel_batch_size_changes_the_cache_key(self, tmp_path: Path) -> None:
        """It looks like a performance knob. It is not one.

        The sampler draws noise shaped by the batch, so one seed consumes the
        RNG stream differently at batch 1 and batch 5 and yields different
        structures. Two runs differing only in it are each reproducible and not
        comparable to each other, which is exactly what a shared cache entry
        would claim they are.
        """
        from bindsight.design._common import make_cache_key

        structure = _write_pdb(tmp_path / "target.pdb", n=10)
        serial = make_cache_key(
            self._spec(structure, validator="boltz2", diffusion_samples=5, max_parallel_samples=1)
        )
        batched = make_cache_key(
            self._spec(structure, validator="boltz2", diffusion_samples=5, max_parallel_samples=5)
        )
        assert serial != batched

    def test_the_mode_changes_the_cache_key(self, tmp_path: Path) -> None:
        """A validate-only job runs no designer at all."""
        from bindsight.design._common import make_cache_key

        structure = _write_pdb(tmp_path / "target.pdb", n=10)
        full = make_cache_key(self._spec(structure, validator="boltz2"))
        validate = make_cache_key(self._spec(structure, validator="boltz2", mode="validate_only"))
        assert full != validate

    def test_bookkeeping_added_after_the_key_does_not_disturb_it(self, tmp_path: Path) -> None:
        """target_structure_name is set after the key is computed; it must not matter."""
        from bindsight.design._common import make_cache_key

        structure = _write_pdb(tmp_path / "target.pdb", n=10)
        plain = make_cache_key(self._spec(structure, validator="boltz2"))
        named = make_cache_key(
            self._spec(structure, validator="boltz2", target_structure_name="target.cif")
        )
        assert plain == named


class TestTheCacheKeyCoversTheShippedBinders:
    """In ``validate_only`` the payload *is* the input, and the spec cannot see it.

    A designer run is keyed by what the designer is told to produce. A
    validate-only run produces nothing: the binders are shipped in ``design/``,
    and the spec is byte-identical whichever ones travel. So two different
    calibration sets against the same target — twenty scrambles, then those
    twenty plus their originals — hashed to the same key, and the second would
    have been handed the first's twenty rows and read as its answer. Nothing
    downstream could have caught it: twenty well-formed metrics rows for the
    right target is exactly what a correct run looks like.
    """

    @staticmethod
    def _spec(structure: Path) -> Any:
        from bindsight.design.protocol import DesignSpec

        return DesignSpec(
            target_uniprot="P04626",
            target_structure_path=str(structure),
            epitope_chain="A",
            epitope_residues=[],
            design_ranges=[],
            n_trajectories=1,
            seed=0,
            extra_params={"mode": "validate_only", "validator": "boltz2"},
        )

    def _submit(self, spec: Any, runner: Any, payload: Path) -> Any:
        from bindsight.design._common import make_cache_key, submit_via_runner

        return submit_via_runner(
            spec,
            runner,
            designer_name="calibration:boltz2",
            designer_version="1",
            designer_commit_sha=None,
            cache_key=make_cache_key(spec),
            payload_dir=payload,
        )

    @staticmethod
    def _archive(tmp_path: Path) -> Path:
        import tarfile

        rows = tmp_path / "metrics.jsonl"
        rows.write_text(json.dumps({"binder_id": "b0", "iptm": 0.7}) + "\n")
        archive = tmp_path / "results.tar.gz"
        with tarfile.open(archive, "w:gz") as tf:
            tf.add(rows, arcname="metrics.jsonl")
        return archive

    def test_a_different_shipped_set_is_not_a_cache_hit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        structure = _write_pdb(tmp_path / "target.pdb", n=10)
        spec = self._spec(structure)
        runner = _CountingRunner(self._archive(tmp_path))

        payload = tmp_path / "design"
        payload.mkdir()
        (payload / "b0.fasta").write_text(">b0\nMKV\n")
        first = self._submit(spec, runner, payload)
        assert runner.submits == 1
        assert first.cache_status == "miss"

        # The set grows — the same binder plus one more. Same spec, same target.
        (payload / "b1.fasta").write_text(">b1\nVKM\n")
        second = self._submit(spec, runner, payload)
        assert second.cache_status == "miss", (
            "a larger set of shipped binders was served the smaller set's results"
        )
        assert runner.submits == 2

    def test_an_edited_binder_is_not_a_cache_hit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Same filenames, same count, different sequence: different work."""
        monkeypatch.chdir(tmp_path)
        structure = _write_pdb(tmp_path / "target.pdb", n=10)
        spec = self._spec(structure)
        runner = _CountingRunner(self._archive(tmp_path))

        payload = tmp_path / "design"
        payload.mkdir()
        (payload / "b0.fasta").write_text(">b0\nMKV\n")
        self._submit(spec, runner, payload)

        (payload / "b0.fasta").write_text(">b0\nVKM\n")
        assert self._submit(spec, runner, payload).cache_status == "miss", (
            "scoring a different sequence returned the previous sequence's score"
        )

    def test_an_unchanged_set_is_still_a_cache_hit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The fold must not defeat the cache it is narrowing.

        Without this, a fold over anything incidental — a mtime, an absolute
        path, iteration order — would make every rerun pay for the GPU again and
        the test above would still pass.
        """
        monkeypatch.chdir(tmp_path)
        structure = _write_pdb(tmp_path / "target.pdb", n=10)
        spec = self._spec(structure)
        runner = _CountingRunner(self._archive(tmp_path))

        payload = tmp_path / "design"
        (payload / "sub").mkdir(parents=True)
        (payload / "b0.fasta").write_text(">b0\nMKV\n")
        (payload / "sub" / "b1.fasta").write_text(">b1\nVKM\n")

        assert self._submit(spec, runner, payload).cache_status == "miss"
        assert self._submit(spec, runner, payload).cache_status == "hit"
        assert runner.submits == 1

    def test_a_renamed_binder_is_not_a_cache_hit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Names are how a metrics row is matched back to a binder downstream."""
        monkeypatch.chdir(tmp_path)
        structure = _write_pdb(tmp_path / "target.pdb", n=10)
        spec = self._spec(structure)
        runner = _CountingRunner(self._archive(tmp_path))

        payload = tmp_path / "design"
        payload.mkdir()
        (payload / "b0.fasta").write_text(">b0\nMKV\n")
        self._submit(spec, runner, payload)

        (payload / "b0.fasta").unlink()
        (payload / "renamed.fasta").write_text(">b0\nMKV\n")
        assert self._submit(spec, runner, payload).cache_status == "miss"


# ---------------------------------------------------------------------------
# 9. A configured seed must reach the GPU
# ---------------------------------------------------------------------------
class TestTheConfiguredSeedReachesTheSpec:
    """`params.design.seed` was declared, documented, and read by no code.

    Decoding the payload of a live Kaggle kernel launched from a config carrying
    ``seed: 42`` showed the spec on the GPU carried seed 0. The seed is in the
    cache key and in the manifest, so the artifact described a run that never
    happened and could not be reproduced from the config filed beside it.
    """

    @staticmethod
    def _run(tmp_path: Path, **design: Any) -> Path:
        import pandas as pd
        import yaml

        run = tmp_path / "run"
        (run / "epitopes").mkdir(parents=True)
        structure = _write_pdb(run / "target.pdb", n=10)
        pd.DataFrame(
            [
                {
                    "uniprot_id": "Q16790",
                    "structure_path": str(structure),
                    "chain": "A",
                    "residues": [1, 2, 3],
                    "design_ranges": [[38, 414]],
                }
            ]
        ).to_parquet(run / "epitopes" / "epitopes.parquet")
        (run / "config.yaml").write_text(
            yaml.safe_dump({"params": {"design": design}}), encoding="utf-8"
        )
        return run

    def test_the_configured_seed_is_read(self, tmp_path: Path) -> None:
        from bindsight.cli import _design_spec_params_from_run

        run = self._run(tmp_path, seed=42)
        assert _design_spec_params_from_run(run)[0] == 42

    def test_configured_binder_lengths_are_read(self, tmp_path: Path) -> None:
        from bindsight.cli import _design_spec_params_from_run

        run = self._run(tmp_path, binder_length_min=60, binder_length_max=80)
        assert _design_spec_params_from_run(run)[1:] == (60, 80)

    def test_a_run_without_a_config_falls_back_to_the_spec_defaults(self, tmp_path: Path) -> None:
        from bindsight.cli import _design_spec_params_from_run
        from bindsight.design.protocol import DesignSpec

        run = tmp_path / "bare"
        run.mkdir()
        fields = DesignSpec.model_fields
        assert _design_spec_params_from_run(run) == (
            fields["seed"].default,
            fields["binder_length_min"].default,
            fields["binder_length_max"].default,
        )

    def test_the_seed_reaches_the_spec_the_designer_is_given(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """End to end through _launch_design: the payload must carry seed 42."""
        import tarfile

        from bindsight import plugins
        from bindsight.cli import _launch_design
        from bindsight.design.rfdiff_mpnn import RFdiffMPNNDesigner

        run = self._run(tmp_path, seed=42, binder_length_min=60, binder_length_max=80)
        archive = tmp_path / "results.tar.gz"
        metrics = tmp_path / "metrics.jsonl"
        metrics.write_text(json.dumps({"binder_id": "b0", "iptm": 0.7}) + "\n")
        with tarfile.open(archive, "w:gz") as tf:
            tf.add(metrics, arcname="metrics.jsonl")

        seen: list[Any] = []

        class _Capturing:
            name = "rfdiff_mpnn"

            def __init__(self) -> None:
                self.inner = RFdiffMPNNDesigner()

            def make_spec(self, **kw: Any) -> Any:
                return self.inner.make_spec(**kw)

            def submit(self, spec: Any, runner: Any) -> Any:
                seen.append(spec)
                return SimpleNamespace(
                    results_archive_path=str(archive),
                    metrics_jsonl_path=str(metrics),
                )

        monkeypatch.setattr(plugins, "get_designer", lambda name: _Capturing())
        monkeypatch.setattr(plugins, "get_runner", lambda *a, **k: object())
        launched = _launch_design(
            run, backend="mock", designer="rfdiff_mpnn", validator="boltz2", trajectories=10
        )
        assert launched == 1
        spec = seen[0]
        assert spec.seed == 42, "the configured seed never reached the design job"
        assert (spec.binder_length_min, spec.binder_length_max) == (60, 80)
        # rfdiff_mpnn also mirrors the bounds into extra_params; they must agree.
        assert spec.extra_params["binder_length_min"] == 60
        assert spec.extra_params["binder_length_max"] == 80


# ---------------------------------------------------------------------------
# 10. A declared config value must reach something
# ---------------------------------------------------------------------------
class TestDeclaredConfigValuesAreHonoured:
    """A knob that turns nothing is a promise the tool does not keep."""

    def test_every_design_parameter_has_a_known_destination(self) -> None:
        """Adding a parameter must force a decision about where it lands.

        `seed`, `binder_length_min` and `binder_length_max` were all declared,
        documented, shipped in three example YAMLs, and read by no code. This
        fails when a new parameter appears, so the next one cannot join them.
        """
        from bindsight.config import DesignParams

        spec_bound = {"n_trajectories", "binder_length_min", "binder_length_max", "seed"}
        routed_elsewhere = {"designer", "gpu_type", "prescreen_top_k"}
        assert set(DesignParams.model_fields) == spec_bound | routed_elsewhere, (
            "a design parameter was added or removed; say where it reaches the job"
        )

    def test_the_configured_bars_move_failures_aside_rather_than_dropping_them(
        self, tmp_path: Path
    ) -> None:
        import yaml

        from bindsight.cli import _split_on_thresholds

        run = tmp_path / "run"
        validate_dir = run / "validate"
        validate_dir.mkdir(parents=True)
        (run / "config.yaml").write_text(
            yaml.safe_dump({"params": {"validate": {"apply_thresholds": True}}}),
            encoding="utf-8",
        )
        df = pd.DataFrame(
            [
                {"binder_id": "a", "passes_thresholds": "pass", "threshold_reason": "ok"},
                {"binder_id": "b", "passes_thresholds": "fail", "threshold_reason": "iptm low"},
                {"binder_id": "c", "passes_thresholds": "unassessed", "threshold_reason": "n/m"},
            ]
        )
        kept = _split_on_thresholds(df, run, validate_dir)
        assert list(kept["binder_id"]) == ["a", "c"], "unmeasured designs must not be excluded"

        aside = validate_dir / "excluded_by_thresholds.parquet"
        assert aside.exists(), "excluded designs must be written somewhere, not deleted"
        excluded = pd.read_parquet(aside)
        assert list(excluded["binder_id"]) == ["b"]
        assert excluded.iloc[0]["threshold_reason"] == "iptm low", "the reason must travel with it"

    def test_the_bars_stay_descriptive_when_the_flag_is_unset(self, tmp_path: Path) -> None:
        """The default must keep every design in the table, as it always has."""
        from bindsight.cli import _split_on_thresholds

        run = tmp_path / "run"
        validate_dir = run / "validate"
        validate_dir.mkdir(parents=True)
        df = pd.DataFrame(
            [
                {"binder_id": "a", "passes_thresholds": "pass"},
                {"binder_id": "b", "passes_thresholds": "fail"},
            ]
        )
        kept = _split_on_thresholds(df, run, validate_dir)
        assert list(kept["binder_id"]) == ["a", "b"]
        assert not (validate_dir / "excluded_by_thresholds.parquet").exists()


# ---------------------------------------------------------------------------
# 11. The manifest must name the validator that actually ran
# ---------------------------------------------------------------------------
class TestTheManifestNamesTheRealValidator:
    """`bindsight validate` takes a --validator flag but usually runs none.

    By default it materialises metrics the design job already produced, using
    whichever validator *that* job was given. Recording the flag meant passing
    `--validator chai1r` to a Boltz-2 run filed Chai-1r's name against Boltz-2's
    numbers — a provenance claim contradicted by the very table it described.
    """

    def test_the_rows_name_the_validator_not_the_flag(self, tmp_path: Path) -> None:
        from bindsight.cli import _validators_that_produced

        validated = tmp_path / "validated.parquet"
        pd.DataFrame(
            [
                {"binder_id": "a", "validator_name": "boltz2"},
                {"binder_id": "b", "validator_name": "boltz2"},
            ]
        ).to_parquet(validated, index=False)
        assert _validators_that_produced(validated) == ["boltz2"]

    def test_a_mixed_table_names_every_validator_in_it(self, tmp_path: Path) -> None:
        """Revalidating some targets and not others must not be reported as one."""
        from bindsight.cli import _validators_that_produced

        validated = tmp_path / "validated.parquet"
        pd.DataFrame(
            [
                {"binder_id": "a", "validator_name": "boltz2"},
                {"binder_id": "b", "validator_name": "chai1r"},
            ]
        ).to_parquet(validated, index=False)
        assert _validators_that_produced(validated) == ["boltz2", "chai1r"]

    def test_a_missing_or_unlabelled_table_claims_nothing(self, tmp_path: Path) -> None:
        from bindsight.cli import _validators_that_produced

        assert _validators_that_produced(tmp_path / "absent.parquet") == []
        unlabelled = tmp_path / "unlabelled.parquet"
        pd.DataFrame([{"binder_id": "a"}]).to_parquet(unlabelled, index=False)
        assert _validators_that_produced(unlabelled) == []


# ---------------------------------------------------------------------------
# 12. The documented cache key must be the real one
# ---------------------------------------------------------------------------
class TestTheDocumentedCacheKeyIsTheRealOne:
    """ARCHITECTURE 4.4 names the components; each must actually change the key.

    The document and the implementation drifted apart once already: the formula
    was specified there and used only as a directory name, so every rerun
    resubmitted. It drifted again when the validator was folded in and the prose
    was not updated. Varying each named component and checking the key moves is
    what stops the description becoming decorative.
    """

    @staticmethod
    def _spec(structure: Path, **overrides: Any) -> Any:
        from bindsight.design.protocol import DesignSpec

        base: dict[str, Any] = {
            "target_uniprot": "Q16790",
            "target_structure_path": str(structure),
            "epitope_chain": "A",
            "epitope_residues": [1, 2, 3],
            "design_ranges": [(38, 414)],
            "binder_length_min": 50,
            "binder_length_max": 100,
            "n_trajectories": 10,
            "seed": 42,
            "extra_params": {"designer": "rfdiff_mpnn", "validator": "boltz2"},
        }
        base.update(overrides)
        return DesignSpec(**base)

    def test_every_documented_component_changes_the_key(self, tmp_path: Path) -> None:
        from bindsight.design._common import make_cache_key

        structure = _write_pdb(tmp_path / "target.pdb", n=10)
        other = _write_pdb(tmp_path / "other.pdb", n=12)
        commits = ("rfdiff-abc", "mpnn-def")
        base = make_cache_key(self._spec(structure), extra=commits)

        variations: dict[str, Any] = {
            "target_uniprot": self._spec(structure, target_uniprot="P04626"),
            "target structure content": self._spec(other),
            "epitope_chain": self._spec(structure, epitope_chain="B"),
            "epitope_residues": self._spec(structure, epitope_residues=[1, 2, 4]),
            "design_ranges": self._spec(structure, design_ranges=[(38, 400)]),
            "binder_length_min": self._spec(structure, binder_length_min=60),
            "binder_length_max": self._spec(structure, binder_length_max=90),
            "n_trajectories": self._spec(structure, n_trajectories=20),
            "seed": self._spec(structure, seed=0),
            "validator": self._spec(
                structure, extra_params={"designer": "rfdiff_mpnn", "validator": "chai1r"}
            ),
            "prescreen_top_k": self._spec(
                structure,
                extra_params={
                    "designer": "rfdiff_mpnn",
                    "validator": "boltz2",
                    "prescreen_top_k": 5,
                },
            ),
        }
        for label, spec in variations.items():
            assert make_cache_key(spec, extra=commits) != base, (
                f"ARCHITECTURE 4.4 names {label} as part of the cache key, "
                "but changing it leaves the key identical"
            )

        # designer_commits, the last term of the documented work key.
        assert make_cache_key(self._spec(structure), extra=("rfdiff-zzz", "mpnn-def")) != base

    def test_the_backend_and_the_code_are_folded_in(self, tmp_path: Path) -> None:
        """The second documented step: where it runs, and which code runs there."""
        from bindsight.design._common import _with_backend

        work = "0" * 64
        kaggle = _with_backend(work, "kaggle", "wheel:aaaaaaaaaaaaaaaa")
        assert _with_backend(work, "mock", "wheel:aaaaaaaaaaaaaaaa") != kaggle, (
            "a mock result must never be addressable as a real GPU result"
        )
        assert _with_backend(work, "kaggle", "wheel:bbbbbbbbbbbbbbbb") != kaggle, (
            "a different wheel is different code and therefore different work"
        )

    def test_the_result_affecting_params_are_all_documented(self) -> None:
        """A parameter added to the key must be added to the prose in the same change."""
        from bindsight.design._common import _RESULT_AFFECTING_PARAMS

        prose = Path("ARCHITECTURE.md").read_text(encoding="utf-8")
        section = prose.split("### 4.4 Idempotency", 1)[1].split("---", 1)[0]
        for name in _RESULT_AFFECTING_PARAMS:
            assert name in section, (
                f"{name} is folded into the cache key but ARCHITECTURE 4.4 does not say so"
            )


# ---------------------------------------------------------------------------
# 13. The structure component's error metrics must point the right way
# ---------------------------------------------------------------------------
class TestErrorMetricsAreInverted:
    """pAE-interaction and RMSD are errors: lower is better.

    The affinity component's direction is asserted numerically because getting
    it backwards silently promotes the weakest designs. The structure component
    carries two more metrics with exactly that hazard, and neither had a test —
    removing `invert=True` from either left the whole suite green while ranking
    the least confident interfaces first.
    """

    @staticmethod
    def _frame(column: str) -> pd.DataFrame:
        # iptm is held constant so the composite isolates the metric under test.
        return pd.DataFrame(
            [
                {"binder_id": "tight", "target_uniprot": "P1", "iptm": 0.7, column: 5.0},
                {"binder_id": "loose", "target_uniprot": "P1", "iptm": 0.7, column: 25.0},
            ]
        )

    def test_a_lower_interface_error_scores_higher(self) -> None:
        ranked = rank_validated(self._frame("pae_interaction")).set_index("binder_id")
        assert ranked.loc["tight", "score_structure"] > ranked.loc["loose", "score_structure"], (
            "a 25 A interface error must not outscore a 5 A one"
        )

    def test_a_lower_rmsd_scores_higher(self) -> None:
        ranked = rank_validated(self._frame("rmsd_to_designed")).set_index("binder_id")
        assert ranked.loc["tight", "score_structure"] > ranked.loc["loose", "score_structure"]

    def test_the_inverted_metric_spans_the_full_range(self) -> None:
        """Hand-computed: min-max over (5, 25) inverted puts 5 at 1.0 and 25 at 0.0.

        Averaged with a constant iptm, which min-max maps to the neutral 0.5.
        """
        ranked = rank_validated(self._frame("pae_interaction")).set_index("binder_id")
        assert ranked.loc["tight", "score_structure"] == pytest.approx((0.5 + 1.0) / 2)
        assert ranked.loc["loose", "score_structure"] == pytest.approx((0.5 + 0.0) / 2)

    def test_the_better_interface_ranks_first(self) -> None:
        ranked = rank_validated(self._frame("pae_interaction"))
        assert list(ranked["binder_id"]) == ["tight", "loose"]


# ---------------------------------------------------------------------------
# 14. An unscored binder must not lead the ranking
# ---------------------------------------------------------------------------
class TestUnscoredRowsSortLast:
    """A row with no metrics has no score, and no score is not a good score.

    Sorting NaN first put binders carrying no evidence whatsoever at the top of
    the ranked table — the one place a reader looks. Nothing caught it.
    """

    @staticmethod
    def _frame() -> pd.DataFrame:
        return pd.DataFrame(
            [
                {"binder_id": "unscored", "target_uniprot": "P1"},
                {"binder_id": "poor", "target_uniprot": "P1", "iptm": 0.2},
                {"binder_id": "good", "target_uniprot": "P1", "iptm": 0.9},
            ]
        )

    def test_the_top_of_the_table_carries_a_score(self) -> None:
        ranked = rank_validated(self._frame())
        assert pd.notna(ranked.iloc[0]["score"]), "the first ranked binder has no score at all"
        assert ranked.iloc[0]["binder_id"] == "good"

    def test_an_unscored_binder_ranks_below_a_poor_one(self) -> None:
        ranked = rank_validated(self._frame()).set_index("binder_id")
        assert ranked.loc["unscored", "rank"] > ranked.loc["poor", "rank"], (
            "a binder with no metrics outranked one that was measured and scored badly"
        )

    def test_ranks_are_dense_and_start_at_one(self) -> None:
        ranked = rank_validated(self._frame())
        assert list(ranked["rank"]) == [1, 2, 3]


# ---------------------------------------------------------------------------
# 15. Evidence is scored on an absolute floor, not against the table's minimum
# ---------------------------------------------------------------------------
class TestEvidenceHasAnAbsoluteFloor:
    """Min-max scored a 304-fold over-expressed antigen as zero evidence.

    log2 fold change is a per-target value, so a two-target run carries two
    distinct values and min-max maps them onto exactly {0.0, 1.0} however close
    together they are. On the first real two-target run CA9 (764x) and CD70
    (304x) came out 1.0 and 0.0, and the full 0.25 evidence weight swung on a
    log2fc difference of 1.33 — enough to rank CD70 binders with an ipTM of 0.95
    and a 3.3 A interface below CA9 binders at 0.83 and 11.7 A.

    A log2 fold change of zero is a real zero point. Anchoring there keeps the
    ordering while making the magnitude mean something.
    """

    @staticmethod
    def _ranked(*log2fc: float) -> pd.DataFrame:
        validated = pd.DataFrame(
            [{"binder_id": f"b{i}", "target_uniprot": f"P{i}"} for i in range(len(log2fc))]
        )
        candidates = pd.DataFrame(
            [{"uniprot_id": f"P{i}", "log2fc": v} for i, v in enumerate(log2fc)]
        )
        return rank_validated(validated, candidates).set_index("binder_id")

    def test_a_strongly_over_expressed_target_never_scores_zero(self) -> None:
        """The exact numbers from the run that exposed this."""
        ranked = self._ranked(9.5779, 8.2457)
        assert ranked.loc["b0", "score_evidence"] == pytest.approx(1.0)
        assert ranked.loc["b1", "score_evidence"] == pytest.approx(8.2457 / 9.5779, rel=1e-6)
        assert ranked.loc["b1", "score_evidence"] > 0.8, (
            "a 304-fold over-expressed antigen must not be scored as no evidence"
        )

    def test_the_gap_is_proportional_to_the_difference(self) -> None:
        """Min-max gave the same 0-to-1 swing whatever the gap was; this must not."""
        near = self._ranked(10.0, 9.5)
        far = self._ranked(10.0, 1.0)
        near_gap = near.loc["b0", "score_evidence"] - near.loc["b1", "score_evidence"]
        far_gap = far.loc["b0", "score_evidence"] - far.loc["b1", "score_evidence"]
        assert far_gap > near_gap * 5, "the score ignores how far apart the targets are"

    def test_ordering_is_preserved(self) -> None:
        ranked = self._ranked(2.0, 6.0, 4.0)
        scores = [ranked.loc[f"b{i}", "score_evidence"] for i in range(3)]
        assert scores[1] > scores[2] > scores[0]

    def test_a_down_regulated_target_carries_no_evidence(self) -> None:
        """This component asks for tumour-selective evidence; a fall is not that."""
        ranked = self._ranked(5.0, -3.0)
        assert ranked.loc["b1", "score_evidence"] == pytest.approx(0.0)

    def test_a_table_with_nothing_over_expressed_scores_zero_throughout(self) -> None:
        ranked = self._ranked(-1.0, -4.0)
        assert ranked.loc["b0", "score_evidence"] == pytest.approx(0.0)
        assert ranked.loc["b1", "score_evidence"] == pytest.approx(0.0)

    def test_a_missing_fold_change_stays_missing(self) -> None:
        """A metric that was never measured is excluded, not scored as zero."""
        validated = pd.DataFrame(
            [
                {"binder_id": "known", "target_uniprot": "P0"},
                {"binder_id": "unknown", "target_uniprot": "P1"},
            ]
        )
        candidates = pd.DataFrame(
            [
                {"uniprot_id": "P0", "log2fc": 6.0},
                {"uniprot_id": "P1", "log2fc": float("nan")},
            ]
        )
        ranked = rank_validated(validated, candidates).set_index("binder_id")
        assert pd.isna(ranked.loc["unknown", "score_evidence"])
        assert ranked.loc["known", "score_evidence"] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# 16. The manifest must record the seed it promises
# ---------------------------------------------------------------------------
class TestTheManifestRecordsTheSeed:
    """ARCHITECTURE 5 names the trajectory seed as something the manifest carries.

    It is listed as one of the things a reviewer walks to, and again as a
    headline differentiator: "show me the gene, the patients it came from, the
    structure, the trajectory seed". The standalone `bindsight design` recorded
    the designer, the validator, the backend and the trajectory count, and not
    the seed — so the artifact could not answer the question that makes it
    reproducible. `bindsight run` recorded it only by dumping the whole config.
    """

    def test_the_architecture_still_promises_it(self) -> None:
        """If the promise is dropped, this test should be dropped with it."""
        prose = Path("ARCHITECTURE.md").read_text(encoding="utf-8")
        assert "trajectory seed" in prose

    def test_the_design_stage_records_the_resolved_spec_parameters(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import yaml
        from click.testing import CliRunner

        from bindsight import cli

        run = tmp_path / "run"
        (run / "epitopes").mkdir(parents=True)
        structure = _write_pdb(run / "target.pdb", n=10)
        pd.DataFrame(
            [
                {
                    "uniprot_id": "Q16790",
                    "structure_path": str(structure),
                    "chain": "A",
                    "residues": [1, 2, 3],
                    "design_ranges": [[38, 414]],
                }
            ]
        ).to_parquet(run / "epitopes" / "epitopes.parquet")
        (run / "config.yaml").write_text(
            yaml.safe_dump(
                {"params": {"design": {"seed": 4242, "binder_length_min": 55}}},
            ),
            encoding="utf-8",
        )
        # The chain needs a root: design appends to the manifest discover writes.
        from bindsight.provenance import new_manifest

        new_manifest(name="seed-test").write(run / "run_manifest.jsonld")

        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(
                cli.main, ["design", str(run), "--backend", "mock", "--trajectories", "2"]
            )
        assert result.exit_code == 0, result.output

        manifest = json.loads((run / "run_manifest.jsonld").read_text(encoding="utf-8"))
        design = next(s for s in manifest["stages"] if s["name"] == "design")
        params = design["params"]
        assert params["seed"] == 4242, (
            "the manifest does not record the seed the run was given, so the run "
            "cannot be reproduced from its own provenance"
        )
        assert params["binder_length_min"] == 55
        assert "binder_length_max" in params


# ---------------------------------------------------------------------------
# 14. The same command, the same defect, one field further along
# ---------------------------------------------------------------------------
class TestTheValidatorSettingsReachTheDesignPath:
    """`bindsight design` read the config for flags and stopped there.

    An earlier fix taught the subcommand to read the run's configuration for the
    options that *are* command-line flags — designer, validator, trajectories.
    The ones with no flag were left behind, so `params.design.prescreen_top_k`
    was honoured by `bindsight run` and silently dropped here.

    That one is expensive to lose. `--cheap` sets it (pinned in
    tests/test_cheap_profile.py), and without it every design is validated
    instead of the configured few, paying exactly the GPU cost the profile
    exists to avoid — quietly, because a run that validates more designs looks
    like a run that simply had more designs.
    """

    @staticmethod
    def _run_dir(tmp_path: Path, **params: object) -> Path:
        import yaml

        run = tmp_path / "run"
        run.mkdir()
        (run / "config.yaml").write_text(yaml.safe_dump({"params": params}), encoding="utf-8")
        return run

    def test_the_prescreen_size_is_read(self, tmp_path: Path) -> None:
        from bindsight.cli import _validator_params_from_run

        run = self._run_dir(tmp_path, design={"prescreen_top_k": 5})
        assert _validator_params_from_run(run)[0] == 5

    def test_the_sample_count_is_read(self, tmp_path: Path) -> None:
        """Configured but unreachable is the same as absent."""
        from bindsight.cli import _validator_params_from_run

        run = self._run_dir(tmp_path, validate={"diffusion_samples": 5})
        assert _validator_params_from_run(run)[1] == 5

    def test_the_parallel_batch_is_read(self, tmp_path: Path) -> None:
        from bindsight.cli import _validator_params_from_run

        run = self._run_dir(tmp_path, validate={"max_parallel_samples": 3})
        assert _validator_params_from_run(run)[2] == 3

    def test_an_absent_config_falls_back_to_the_schema_defaults(self, tmp_path: Path) -> None:
        from bindsight.cli import _validator_params_from_run

        run = tmp_path / "bare"
        run.mkdir()
        assert _validator_params_from_run(run) == (None, 1, 1)

    def test_a_malformed_config_does_not_abort_the_command(self, tmp_path: Path) -> None:
        """The user's YAML is the user's; it must not take the run down."""
        from bindsight.cli import _validator_params_from_run

        run = tmp_path / "run"
        run.mkdir()
        (run / "config.yaml").write_text("params: [not, a, mapping\n", encoding="utf-8")
        assert _validator_params_from_run(run) == (None, 1, 1)

    def test_the_values_reach_the_launcher_not_just_the_reader(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Reading a setting and passing it on are different things.

        This is the whole defect: the config was parsed and the value was
        dropped on the floor. A test that only exercises the reader passes with
        the threading deleted, which is how the original slipped through — so
        this one drives the real command and inspects what the launcher was
        handed.
        """
        import yaml
        from click.testing import CliRunner

        from bindsight import cli

        run = tmp_path / "run"
        run.mkdir()
        (run / "config.yaml").write_text(
            yaml.safe_dump(
                {
                    "params": {
                        "design": {"prescreen_top_k": 7},
                        "validate": {"diffusion_samples": 4, "max_parallel_samples": 2},
                    }
                }
            ),
            encoding="utf-8",
        )

        seen: dict[str, Any] = {}

        def _capture(_run_dir: Path, **kwargs: Any) -> int:
            seen.update(kwargs)
            return 0

        monkeypatch.setattr(cli, "_launch_design", _capture)
        CliRunner().invoke(cli.main, ["design", str(run), "--backend", "mock"])

        assert seen.get("prescreen_top_k") == 7, (
            "the configured prescreen was read and then not passed to the launcher"
        )
        assert seen.get("diffusion_samples") == 4
        assert seen.get("max_parallel_samples") == 2

    def test_the_defaults_keep_the_spec_and_its_key_unchanged(self) -> None:
        """Both sampling options default to 1, so an unconfigured run is untouched.

        A change that altered every existing cache key would have made every
        completed job pay for itself again.
        """
        from bindsight.config import ValidateParams

        params = ValidateParams()
        assert params.diffusion_samples == 1
        assert params.max_parallel_samples == 1


# ---------------------------------------------------------------------------
# 15. A dropped kwarg that changes what a result means must not be silent
# ---------------------------------------------------------------------------
class TestTheWheelIsNotSilentlyDiscarded:
    """`get_runner` filtered kwargs to the constructor and said nothing.

    That filtering is right — `MockRunner` takes none of the design kwargs — but
    `ModalRunner` declares no `bindsight_wheel`, so a benchmark that built one
    from the working tree had it dropped, the GPU installed bindsight from the
    repository's default branch, and the published summary still reported
    "working-tree wheel <name>" as the code that ran.

    That is the exact failure the wheel exists to prevent. `_with_backend`'s
    docstring records it happening once already: a corrected benchmark submitted
    against a branch whose fixes existed only locally, producing pre-fix output.
    """

    def test_modal_does_not_accept_the_wheel(self) -> None:
        """The anchor. If Modal gains the parameter, these tests change with it."""
        from bindsight.plugins import runner_accepts

        assert not runner_accepts("modal", "bindsight_wheel")
        assert runner_accepts("kaggle", "bindsight_wheel")

    def test_dropping_it_is_logged(self, caplog: pytest.LogCaptureFixture) -> None:
        from bindsight.plugins import get_runner

        with caplog.at_level("WARNING", logger="bindsight.plugins"):
            get_runner(
                "modal",
                designer="rfdiff_mpnn",
                n_units_per_target=1,
                bindsight_wheel="/tmp/x.whl",
            )
        assert "bindsight_wheel" in caplog.text
        assert "not from the code that launched it" in caplog.text

    def test_a_backend_that_takes_it_logs_nothing(self, caplog: pytest.LogCaptureFixture) -> None:
        from bindsight.plugins import get_runner

        with caplog.at_level("WARNING", logger="bindsight.plugins"):
            get_runner(
                "kaggle",
                designer="rfdiff_mpnn",
                n_units_per_target=1,
                bindsight_wheel="/tmp/x.whl",
            )
        assert "bindsight_wheel" not in caplog.text

    def test_an_irrelevant_kwarg_does_not_warn(self, caplog: pytest.LogCaptureFixture) -> None:
        """Only provenance-critical losses are loud; the rest is ordinary filtering."""
        from bindsight.plugins import get_runner

        with caplog.at_level("WARNING", logger="bindsight.plugins"):
            get_runner("mock", designer="rfdiff_mpnn", n_units_per_target=1, gpu_type="A100")
        assert caplog.text.strip() == ""

    def test_the_summary_reports_what_ran_not_what_was_offered(self) -> None:
        """The published provenance must follow the runner, not the request."""
        from bindsight.benchmark.designer_bench import _bindsight_source

        wheel = Path("bindsight-0.2.2-py3-none-any.whl")
        kaggle = _bindsight_source("kaggle", wheel, is_mock=False)
        modal = _bindsight_source("modal", wheel, is_mock=False)

        assert kaggle == "working-tree wheel bindsight-0.2.2-py3-none-any.whl"
        assert "default branch" in modal, "Modal claimed a wheel it never received"
        assert "not attributable to the tree that launched them" in modal

    def test_no_wheel_and_the_mock_backend_are_unchanged(self) -> None:
        from bindsight.benchmark.designer_bench import _bindsight_source

        assert _bindsight_source("kaggle", None, is_mock=False) == (
            "pip install from the repository default branch"
        )
        assert "mock backend" in _bindsight_source("mock", None, is_mock=True)


# ---------------------------------------------------------------------------
# 16. Two epitope sites of one receptor are two jobs, not one
# ---------------------------------------------------------------------------
class TestTwoSitesOfOneTargetDoNotCollide:
    """`binder_id` was namespaced by accession, and a receptor can have sites.

    Discovery emits one epitopes row per qualifying targetable site — its own
    docstring says so — and `_top_targets` turns each row into its own design
    job against different residues. Both jobs then named their binders
    `P04626_binder_0_seq0`.

    Everything downstream is keyed on that id: the concatenated metrics carried
    two rows with one id and different ipTMs, `validate/<binder_id>/` was owned
    by whichever job finished last, and the per-target tarball was overwritten
    the same way. The cross-*target* case was found and fixed; this is the same
    collision one level in.
    """

    @staticmethod
    def _spec(residues: list[int], uniprot: str = "P04626", chain: str = "A") -> dict[str, Any]:
        return {
            "target_uniprot": uniprot,
            "epitope_residues": residues,
            "epitope_chain": chain,
        }

    def test_two_sites_of_one_target_get_different_prefixes(self) -> None:
        from bindsight.runners.job_exec import _binder_id_prefix

        a = _binder_id_prefix(self._spec([10, 11, 12, 15, 18]))
        b = _binder_id_prefix(self._spec([40, 41, 44]))
        assert a != b, "two epitope sites of one receptor mint the same binder ids"

    def test_the_same_site_always_gets_the_same_prefix(self) -> None:
        """Ids are the provenance key, so they cannot move between runs."""
        from bindsight.runners.job_exec import _binder_id_prefix

        assert _binder_id_prefix(self._spec([10, 11, 12])) == _binder_id_prefix(
            self._spec([10, 11, 12])
        )

    def test_residue_order_does_not_change_the_prefix(self) -> None:
        """The same site written two ways is one site."""
        from bindsight.runners.job_exec import _binder_id_prefix

        assert _binder_id_prefix(self._spec([18, 10, 15, 11, 12])) == _binder_id_prefix(
            self._spec([10, 11, 12, 15, 18])
        )

    def test_different_targets_still_differ(self) -> None:
        from bindsight.runners.job_exec import _binder_id_prefix

        assert _binder_id_prefix(self._spec([10, 11], uniprot="P04626")) != _binder_id_prefix(
            self._spec([10, 11], uniprot="P00533")
        )

    def test_the_same_residues_on_another_chain_are_another_site(self) -> None:
        from bindsight.runners.job_exec import _binder_id_prefix

        assert _binder_id_prefix(self._spec([10, 11], chain="A")) != _binder_id_prefix(
            self._spec([10, 11], chain="B")
        )

    def test_whole_surface_design_keeps_the_bare_accession(self) -> None:
        """Every already-published artifact is named this way.

        Whole-surface design is one namespace per target by definition, so
        nothing needs disambiguating and no committed id moves.
        """
        from bindsight.runners.job_exec import _binder_id_prefix

        assert _binder_id_prefix(self._spec([])) == "P04626"

    def test_the_committed_benchmark_ids_are_unchanged(self) -> None:
        """The published binders are named P04626_binder_N_seqM; they must stay so."""
        import json

        from bindsight.runners.job_exec import _binder_id_prefix

        metrics = Path("benchmarks/designer_benchmark/binders/metrics.jsonl")
        ids = [json.loads(ln)["binder_id"] for ln in metrics.read_text().splitlines() if ln.strip()]
        assert ids
        prefix = _binder_id_prefix(self._spec([]))
        assert all(i.startswith(f"{prefix}_binder_") for i in ids), ids[:3]

    def test_an_archive_written_before_the_fix_is_still_found(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A naming fix must not orphan the archives it renames.

        Runs made before this carry the bare accession. Revalidation reads
        those archives, so it tries the site-specific stem and falls back.
        """
        from bindsight import cli

        run = tmp_path / "run"
        targets_dir = run / "design" / "targets"
        targets_dir.mkdir(parents=True)
        legacy = targets_dir / "P04626.tar.gz"
        legacy.write_bytes(b"")

        target = {"uniprot": "P04626", "residues": [10, 11], "chain": "A"}
        assert cli._target_artifact_stem(target) != "P04626"
        # The new stem does not exist; the legacy one does and must be used.
        assert not (targets_dir / f"{cli._target_artifact_stem(target)}.tar.gz").exists()
        assert legacy.exists()

    def test_the_tarball_name_follows_the_binder_ids(self) -> None:
        """One archive per job, named the way the binders inside it are."""
        from bindsight.cli import _target_artifact_stem

        a = _target_artifact_stem({"uniprot": "P04626", "residues": [10, 11], "chain": "A"})
        b = _target_artifact_stem({"uniprot": "P04626", "residues": [40, 41], "chain": "A"})
        assert a != b, "the second site's tarball overwrites the first's"
        assert (
            _target_artifact_stem({"uniprot": "P04626", "residues": [], "chain": "A"}) == "P04626"
        )


def test_every_extra_param_the_executor_reads_is_in_the_key() -> None:
    """The reverse direction, which nothing checked.

    ``test_the_result_affecting_params_are_all_documented`` asserts every name
    in ``_RESULT_AFFECTING_PARAMS`` appears in ARCHITECTURE -- list to document.
    Nothing asserted document to list, or executor to list, so a field
    ``job_exec`` reads to decide what runs could be absent from the key
    entirely. ``designer`` was: it selects which designer executes, and two jobs
    differing only in it shared a cache entry. They did not collide in practice
    only because the adapters pass distinct pinned commits through a different
    field.

    This sweeps the executor for what it actually reads out of
    ``extra_params`` and requires each to be in the key or explicitly excused.
    """
    import ast

    from bindsight.design._common import _RESULT_AFFECTING_PARAMS

    repo = Path(__file__).resolve().parents[1]
    source = (repo / "bindsight" / "runners" / "job_exec.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    read: set[str] = set()
    for node in ast.walk(tree):
        # `spec.get("extra_params", {}).get("<name>")` and `extra["<name>"]`
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            inner = node.func.value
            if (
                isinstance(inner, ast.Call)
                and isinstance(inner.func, ast.Attribute)
                and inner.func.attr == "get"
                and inner.args
                and isinstance(inner.args[0], ast.Constant)
                and inner.args[0].value == "extra_params"
            ):
                read.add(node.args[0].value)

    #: Read by the executor but deliberately outside the key, each with a reason.
    excused = {
        # Where the work runs is folded in separately, after the hash.
        "backend",
        # Bookkeeping, not an input. `_common.py` adds it *after* the key is
        # computed so the key depends on the work rather than on the filename,
        # and the structure's *content* is already hashed into the key. The
        # reason is stated there; it is repeated here so this exclusion is a
        # decision rather than an omission.
        "target_structure_name",
    }

    missing = sorted(read - set(_RESULT_AFFECTING_PARAMS) - excused)

    assert not missing, (
        f"the executor reads these from extra_params to decide what runs, and "
        f"they are not in the cache key: {missing}. Two jobs differing only in "
        "one of them would share a cache entry."
    )
    assert read, "the sweep found no extra_params reads at all; it is not working"


def test_the_backend_sets_cover_every_registered_runner() -> None:
    """A newly registered runner must not fall out of the orchestrator's sets.

    ``_HEADLESS_BACKENDS`` and ``_REMOTE_CONTAINER_BACKENDS`` were hand-copied
    from the runner registry and appeared in no test. A backend absent from the
    first was treated as non-headless; absent from the second, a local
    ``docker image inspect`` was attempted against an image that lives on the
    provider, took the warning path, and the run completed green with **no
    container digest in the manifest**.

    They are derived now, and this asserts the partition stays total.
    """
    from bindsight import plugins
    from bindsight.pipelines.full_run import (
        _INTERACTIVE_BACKENDS,
        _headless_backends,
        _remote_container_backends,
    )

    registered = set(plugins._FALLBACK["bindsight.runners"])
    covered = set(_headless_backends()) | set(_INTERACTIVE_BACKENDS)

    assert registered == covered, (
        f"registered runners and the orchestrator's classification disagree: "
        f"{sorted(registered ^ covered)}"
    )
    assert set(_remote_container_backends()) <= set(_headless_backends())


class TestACacheHitMustBeAResultThatCanBeRead:
    """A non-empty file is not a readable archive, and size alone called it a hit.

    An interrupted transfer leaves plausible-looking bytes on disk. The hit test
    was ``exists() and st_size > 0``, so those bytes became a permanent hit:
    nothing in the path ever re-submits once the file exists. ``extract_member``
    then swallowed the ``TarError`` as a warning and returned without writing
    anything, so the result reported ``cache_status="hit"`` while pointing at a
    metrics file that had never been created.

    The cache poisoned itself and, with no path back, stayed poisoned. Every
    later run of that work unit returned the same broken result.
    """

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

    @staticmethod
    def _good_archive(tmp_path: Path) -> Path:
        import tarfile

        work = tmp_path / "payload"
        work.mkdir(exist_ok=True)
        (work / "metrics.jsonl").write_text(json.dumps({"binder_id": "b0", "iptm": 0.7}) + "\n")
        archive = tmp_path / "results.tar.gz"
        with tarfile.open(archive, "w:gz") as tf:
            tf.add(work / "metrics.jsonl", arcname="metrics.jsonl")
        return archive

    def _submit(self, spec: Any, runner: Any, key: str) -> Any:
        from bindsight.design._common import submit_via_runner

        return submit_via_runner(
            spec,
            runner,
            designer_name="rfdiff_mpnn",
            designer_version="0.1.0",
            designer_commit_sha=None,
            cache_key=key,
        )

    @staticmethod
    def _staged_dir(root: Path) -> Path:
        """Where the code put its own result.

        Not ``make_cache_key(spec)``: ``submit_via_runner`` re-folds that with
        the backend and the code identity before deriving the directory. Staging
        a fixture under the unfolded key puts it where the lookup never reads,
        so the test takes the miss path and passes without testing anything.
        """
        staged = [p for p in (root / "runs" / "_design").iterdir() if p.is_dir()]
        assert len(staged) == 1, f"expected one staged work unit, found {staged}"
        return staged[0]

    def test_a_truncated_archive_is_re_run_rather_than_returned_forever(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from bindsight.design._common import make_cache_key

        monkeypatch.chdir(tmp_path)
        structure = _write_pdb(tmp_path / "target.pdb", n=10)
        spec = self._spec(structure)
        key = make_cache_key(spec)
        runner = _CountingRunner(self._good_archive(tmp_path))

        assert self._submit(spec, runner, key).cache_status == "miss"
        assert runner.submits == 1

        # The staged result is damaged after the fact, the way a transfer
        # interrupted partway leaves it: real gzip magic, nothing behind it.
        staged = self._staged_dir(tmp_path)
        (staged / "results.tar.gz").write_bytes(GZIP_MAGIC + b"corrupted")
        (staged / "metrics.jsonl").unlink(missing_ok=True)

        result = self._submit(spec, runner, key)

        assert result.cache_status == "miss", "a corrupt archive was served as a cache hit"
        assert runner.submits == 2, "the work was never re-run, so the cache stayed poisoned"
        assert Path(result.metrics_jsonl_path).is_file()

    def test_a_readable_archive_without_metrics_is_not_a_hit_either(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Returning its path would hand the caller a file that is not there."""
        import tarfile

        from bindsight.design._common import make_cache_key

        monkeypatch.chdir(tmp_path)
        structure = _write_pdb(tmp_path / "target.pdb", n=10)
        spec = self._spec(structure)
        key = make_cache_key(spec)
        runner = _CountingRunner(self._good_archive(tmp_path))

        assert self._submit(spec, runner, key).cache_status == "miss"

        staged = self._staged_dir(tmp_path)
        (staged / "metrics.jsonl").unlink(missing_ok=True)
        (tmp_path / "other.txt").write_text("not metrics")
        with tarfile.open(staged / "results.tar.gz", "w:gz") as tf:
            tf.add(tmp_path / "other.txt", arcname="other.txt")

        result = self._submit(spec, runner, key)

        assert result.cache_status == "miss"
        assert runner.submits == 2
        assert Path(result.metrics_jsonl_path).is_file()

    def test_a_genuine_hit_is_still_a_hit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The readability probe must not cost the cache its purpose."""
        from bindsight.design._common import make_cache_key

        monkeypatch.chdir(tmp_path)
        structure = _write_pdb(tmp_path / "target.pdb", n=10)
        spec = self._spec(structure)
        key = make_cache_key(spec)
        runner = _CountingRunner(self._good_archive(tmp_path))

        assert self._submit(spec, runner, key).cache_status == "miss"
        assert self._submit(spec, runner, key).cache_status == "hit"
        assert runner.submits == 1


class TestAJobWithNoTargetStructureStopsBeforeTheGpuIsPaidFor:
    """The spec named a structure file the job had not shipped.

    ``target_structure_name`` was written into ``extra_params`` unconditionally,
    while the copy was guarded by ``if structure_src.exists()``. A missing file
    therefore produced a spec that told the executor where to find something
    that was not there. ``job_exec._locate_structure`` does raise -- but on the
    remote side, after the GPU session has been allocated and billed, which is
    the exact reason its own comment gives for failing early rather than late.

    ``make_cache_key`` compounds it: a structure it cannot read hashes as the
    empty string, so two jobs against two *different* missing structures share
    a key, and the second would be served the first's designs.
    """

    @staticmethod
    def _absent_spec(tmp_path: Path) -> Any:
        from bindsight.design.protocol import DesignSpec

        return DesignSpec(
            target_uniprot="P04626",
            target_structure_path=str(tmp_path / "absent.pdb"),
            epitope_chain="A",
            epitope_residues=[1, 2, 3],
            design_ranges=[(1, 10)],
            n_trajectories=2,
            seed=0,
            extra_params={"designer": "rfdiff_mpnn"},
        )

    def test_it_raises_locally_instead_of_shipping_a_spec_that_cannot_run(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from bindsight.design._common import make_cache_key, submit_via_runner

        monkeypatch.chdir(tmp_path)
        spec = self._absent_spec(tmp_path)
        runner = _CountingRunner(tmp_path / "unused.tar.gz")

        with pytest.raises(FileNotFoundError, match="target structure not found"):
            submit_via_runner(
                spec,
                runner,
                designer_name="rfdiff_mpnn",
                designer_version="0.1.0",
                designer_commit_sha=None,
                cache_key=make_cache_key(spec),
            )

        assert runner.submits == 0, "the GPU was engaged for a job that could not run"

    def test_it_leaves_no_spec_directory_behind(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from bindsight.design._common import make_cache_key, submit_via_runner

        monkeypatch.chdir(tmp_path)
        spec = self._absent_spec(tmp_path)

        with pytest.raises(FileNotFoundError):
            submit_via_runner(
                spec,
                _CountingRunner(tmp_path / "unused.tar.gz"),
                designer_name="rfdiff_mpnn",
                designer_version="0.1.0",
                designer_commit_sha=None,
                cache_key=make_cache_key(spec),
            )

        assert not list(tmp_path.glob("_bindsight_spec_*")), "a dead spec directory was left behind"

    def test_a_structure_that_is_present_still_ships(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The guard must reject only the case it was written for."""
        from bindsight.design._common import make_cache_key, submit_via_runner

        monkeypatch.chdir(tmp_path)
        structure = _write_pdb(tmp_path / "target.pdb", n=10)
        spec = TestACacheHitMustBeAResultThatCanBeRead._spec(structure)
        runner = _CountingRunner(TestACacheHitMustBeAResultThatCanBeRead._good_archive(tmp_path))

        result = submit_via_runner(
            spec,
            runner,
            designer_name="rfdiff_mpnn",
            designer_version="0.1.0",
            designer_commit_sha=None,
            cache_key=make_cache_key(spec),
        )

        assert result.cache_status == "miss"
        assert runner.submits == 1

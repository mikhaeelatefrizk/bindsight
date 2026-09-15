# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Executor dispatch tests — real assembly logic, subprocess mocked (no GPU).

Monkeypatches the single subprocess seam (`job_exec._run`) to drop canned
RFdiffusion / ProteinMPNN / Boltz-2 outputs, then asserts the executor produces
the downstream-correct tarball layout (metrics.jsonl + validate/<binder>/...).
"""

from __future__ import annotations

import inspect
import json
import logging
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from bindsight.runners import job_exec, tools

_TINY_PDB = (
    "ATOM      1  CA  MET A   1      0.0  0.0  0.0  1.0  0.0           C\n"
    "ATOM      2  CA  ALA A   2      0.0  0.0  0.0  1.0  0.0           C\n"
    "ATOM      3  CA  GLY A   3      0.0  0.0  0.0  1.0  0.0           C\n"
)
#: The diffused binder chain's length. The stub's FASTA and the stub's backbone
#: are built from one constant: ProteinMPNN returns a sequence for the chain it
#: was given, so a 15-residue sequence against a 60-residue chain is a
#: combination no real run produces, and the executor now refuses it rather than
#: writing a structure that does not describe the design it is named for.
_BINDER_LEN = 60
_DESIGNED_SEQ = ("GSHMSLEQKKGADII" * 4)[:_BINDER_LEN]
_MPNN_FASTA = (
    f">native, score=2.0\n{'G' * _BINDER_LEN}\n>T=0.1, sample=1, score=0.8\n{_DESIGNED_SEQ}\n"
)

#: Chain letters RFdiffusion gives the output complex. The target moves to B and
#: the diffused binder takes A — deliberately *not* the input target's letter, so
#: a chain choice made by letter rather than by content would pick the antigen.
_TARGET_CHAIN = "B"
_BINDER_CHAIN = "A"


def _atom_line(serial: int, resname: str, chain: str, resi: int) -> str:
    """One CA ATOM record in fixed PDB columns."""
    return (
        f"ATOM  {serial:>5d}  CA  {resname} {chain}{resi:>4d}"
        "      0.0  0.0  0.0  1.0  0.0           C"
    )


def _backbone_pdb() -> str:
    """An RFdiffusion binder-design backbone: target chain + diffused binder chain.

    The target block carries the native residues copied off ``target.pdb``; the
    binder is the poly-glycine RFdiffusion emits before ProteinMPNN gives it a
    sequence. Two chains is what the real tool produces — a single-chain output
    is not a binder-design complex at all.
    """
    lines = [
        _atom_line(i, res, _TARGET_CHAIN, i) for i, res in enumerate(("MET", "ALA", "GLY"), start=1)
    ]
    lines += [_atom_line(3 + i, "GLY", _BINDER_CHAIN, i) for i in range(1, _BINDER_LEN + 1)]
    return "\n".join(lines) + "\n"


def _fake_run(cmd, *, cwd=None):
    """Mimic the design tools by writing their expected output files."""
    s = " ".join(cmd)
    if "run_inference.py" in s:
        prefix = next(a.split("=", 1)[1] for a in cmd if a.startswith("inference.output_prefix="))
        outdir = Path(prefix).parent
        outdir.mkdir(parents=True, exist_ok=True)
        for i in range(2):
            (outdir / f"binder_{i}.pdb").write_text(_backbone_pdb())
    elif "protein_mpnn_run.py" in s:
        out_folder = Path(cmd[cmd.index("--out_folder") + 1])
        seqs = out_folder / "seqs"
        seqs.mkdir(parents=True, exist_ok=True)
        (seqs / "bb.fa").write_text(_MPNN_FASTA)
    elif cmd[0] == "boltz":
        out_dir = Path(cmd[cmd.index("--out_dir") + 1])
        pred = out_dir / "predictions" / "run"
        pred.mkdir(parents=True, exist_ok=True)
        (pred / "confidence_run_model_0.json").write_text(
            json.dumps({"iptm": 0.77, "pae_interaction": 5.0})
        )
        (pred / "affinity_run.json").write_text(
            json.dumps({"affinity_pred_value": -7.0, "affinity_probability_binary": 0.9})
        )
    elif "wget" in cmd[0]:
        # The executor now hashes every checkpoint it fetched, so a stub that
        # writes nothing fails verification instead of the behaviour under test.
        dst = Path(cmd[cmd.index("-O") + 1])
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(b"stub checkpoint bytes")
    # git clone / checkout: no-ops
    return SimpleNamespace(returncode=0, stdout="", stderr="")


@pytest.fixture
def mock_run(monkeypatch):
    """Patch the subprocess seam; yields the argv lists the executor ran."""
    calls: list[list[str]] = []

    def _record(cmd, *, cwd=None):
        calls.append(list(cmd))
        return _fake_run(cmd, cwd=cwd)

    monkeypatch.setattr(job_exec, "_run", _record)
    return calls


def _spec() -> dict:
    return {
        "target_uniprot": "P04626",
        "target_structure_path": "target.pdb",
        "epitope_chain": "A",
        "epitope_residues": [1, 2],
        "binder_length_min": 50,
        "binder_length_max": 100,
        "n_trajectories": 2,
        "seed": 0,
        "extra_params": {"designer": "rfdiff_mpnn", "validator": "boltz2"},
    }


def test_run_job_rfdiff_boltz_produces_correct_layout(mock_run, tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    (work / "target.pdb").write_text(_TINY_PDB)

    tar = job_exec.run_job(_spec(), work, tarball=tmp_path / "results.tar.gz")
    assert tar.exists()

    # metrics.jsonl has one ValidationResult-shaped row per design, parsed real.
    metrics = [
        json.loads(ln) for ln in (work / "metrics.jsonl").read_text().splitlines() if ln.strip()
    ]
    assert len(metrics) == 2  # 2 backbones × 1 design each
    assert metrics[0]["iptm"] == 0.77
    assert metrics[0]["affinity_pred_value"] == -7.0
    assert metrics[0]["validator_name"] == "boltz2"

    # validate/<binder_id>/ holds the per-binder Boltz JSONs for downstream use.
    binder_dirs = list((work / "validate").iterdir())
    assert binder_dirs
    assert any(p.name.startswith("confidence_") for p in binder_dirs[0].iterdir())

    # The tarball carries the downstream-correct members.
    with tarfile.open(tar) as tf:
        names = tf.getnames()
    assert "metrics.jsonl" in names
    assert any(n.startswith("validate/") for n in names)
    assert any(n.startswith("design/") for n in names)

    # ProteinMPNN was told to design the binder chain only — the antigen is held
    # fixed. Without --pdb_path_chains it designs every chain, i.e. rewrites the
    # target and optimises the binder against a surface it partly invented.
    mpnn_cmds = [c for c in mock_run if any("protein_mpnn_run.py" in a for a in c)]
    assert len(mpnn_cmds) == 2  # one per backbone
    for cmd in mpnn_cmds:
        assert "--pdb_path_chains" in cmd
        chains = cmd[cmd.index("--pdb_path_chains") + 1].split()
        assert chains == [_BINDER_CHAIN]
        assert _TARGET_CHAIN not in chains


def test_run_job_rejects_unknown_designer(tmp_path: Path) -> None:
    spec = _spec()
    spec["extra_params"]["designer"] = "nope"
    with pytest.raises(ValueError, match="unknown designer"):
        job_exec.run_job(spec, tmp_path / "w")


def test_run_job_rejects_unknown_validator(mock_run, tmp_path: Path) -> None:
    spec = _spec()
    spec["extra_params"]["validator"] = "nope"
    (tmp_path / "w").mkdir()
    (tmp_path / "w" / "target.pdb").write_text(_TINY_PDB)
    with pytest.raises(ValueError, match="unknown validator"):
        job_exec.run_job(spec, tmp_path / "w")


class TestTheDesignerIsSeeded:
    """The backbone generator — the *first* stochastic stage — ran unseeded.

    Fixing the validator's seed was necessary and not sufficient: a
    reproducibly folded sequence is no use when the sequence itself came from an
    unseeded draw. RFdiffusion seeds torch/numpy/random only inside
    ``if conf.inference.deterministic``, and its pinned ``base.yaml`` ships
    ``deterministic: False`` — verified against commit 2d0c003 upstream, which
    also confirms there is no ``inference.seed`` key to set.

    Both runs would still have recorded ``"seed": 42`` in the manifest and
    hashed to the same cache key, so the artifacts asserted sameness the code
    could not deliver.
    """

    @staticmethod
    def _cmd(**kw: object) -> list[str]:
        from bindsight.runners import tools

        args: dict[str, object] = {
            "rfdiff_dir": Path("/r"),
            "input_pdb": Path("t.pdb"),
            "output_prefix": Path("/o/binder"),
            "num_designs": 10,
            "hotspot": "[A1]",
            "contig": "[X]",
        }
        args.update(kw)
        return tools.build_rfdiff_cmd(**args)  # type: ignore[arg-type]

    def test_a_seeded_run_asks_for_determinism(self) -> None:
        """Without the flag upstream never calls torch.manual_seed at all."""
        assert "inference.deterministic=True" in self._cmd(seed=42)

    def test_the_seed_actually_changes_the_draws(self) -> None:
        """A seed that changes nothing is the defect wearing a fix's clothes.

        There is no ``inference.seed``; the design index is the seed, so the
        run's seed has to move ``design_startnum``.
        """
        a = self._cmd(seed=42)
        b = self._cmd(seed=43)
        assert a != b
        start = "inference.design_startnum="
        assert [x for x in a if x.startswith(start)] != [x for x in b if x.startswith(start)]

    def test_adjacent_seeds_get_disjoint_index_blocks(self) -> None:
        """The subtle half: the index is the seed, so blocks must not overlap.

        Passing the seed straight through as ``design_startnum`` would give
        seeds 42 and 43 the index ranges 42-51 and 43-52 — nine of ten shared,
        so nine of the ten backbones would be identical between two runs
        reported as different.
        """
        start = "inference.design_startnum="

        def block(seed: int, n: int) -> set[int]:
            cmd = self._cmd(seed=seed, num_designs=n)
            base = int(next(x for x in cmd if x.startswith(start)).split("=", 1)[1])
            return set(range(base, base + n))

        for n in (1, 5, 10, 50):
            assert not block(42, n) & block(43, n), f"blocks overlap at num_designs={n}"

    def test_the_same_seed_reproduces_the_same_argv(self) -> None:
        assert self._cmd(seed=7) == self._cmd(seed=7)

    def test_the_index_stays_in_range_for_any_seed_a_user_writes(self) -> None:
        """The index reaches torch.manual_seed, which rejects values ≥ 2**64."""
        start = "inference.design_startnum="
        for seed in (0, 1, 2**31, 2**63, 10**18):
            cmd = self._cmd(seed=seed, num_designs=1000)
            value = int(next(x for x in cmd if x.startswith(start)).split("=", 1)[1])
            assert 0 <= value + 1000 < 2**64

    def test_a_negative_seed_is_refused(self) -> None:
        """It would become a negative design index, which upstream cannot use."""
        with pytest.raises(ValueError, match="negative"):
            self._cmd(seed=-1)

    def test_the_unseeded_form_is_still_reachable(self) -> None:
        """Only so the argv this project already published can be rebuilt."""
        cmd = self._cmd()
        assert not [x for x in cmd if x.startswith("inference.deterministic")]
        assert not [x for x in cmd if x.startswith("inference.design_startnum")]

    def test_the_run_seed_reaches_the_designer(self, mock_run, tmp_path: Path) -> None:
        """End to end: the configured seed must leave the spec and arrive here."""
        work = tmp_path / "work"
        work.mkdir()
        (work / "target.pdb").write_text(_TINY_PDB)
        spec = _spec()
        spec["seed"] = 42
        job_exec.run_job(spec, work, tarball=tmp_path / "r.tar.gz")

        rf = [c for c in mock_run if any("run_inference.py" in a for a in c)]
        assert rf, "RFdiffusion was never invoked"
        for cmd in rf:
            assert "inference.deterministic=True" in cmd, "the designer ran unseeded"
            start = next(a for a in cmd if a.startswith("inference.design_startnum="))
            assert int(start.split("=", 1)[1]) == 42 * int(spec["n_trajectories"])


class TestTheSequenceDesignerIsSeeded:
    """ProteinMPNN reads 0 as "pick a random seed", and 0 was the default.

    Verified against pinned commit 8907e66::

        argparser.add_argument("--seed", type=int, default=0,
            help="If set to 0 then a random seed will be picked;")
        if args.seed:
            seed = args.seed
        else:
            seed = int(np.random.randint(0, high=999, size=1, dtype=int)[0])

    So the value that reads as "plain default, no offset" is the one that turns
    seeding off — and it is the default of ``build_mpnn_cmd``'s parameter and of
    ``DesignSpec.seed`` on several paths, including the validate-only specs this
    project submits. A run seeded 0 drew a different sequence set every time
    while recording ``"seed": 0`` as its provenance.
    """

    @staticmethod
    def _seed_arg(seed: int) -> str:
        from bindsight.runners import tools

        cmd = tools.build_mpnn_cmd(
            mpnn_dir=Path("/m"),
            pdb_path=Path("b.pdb"),
            out_folder=Path("/o"),
            designed_chains=["A"],
            seed=seed,
        )
        return cmd[cmd.index("--seed") + 1]

    def test_zero_never_reaches_proteinmpnn(self) -> None:
        assert self._seed_arg(0) != "0", "0 is upstream's switch for random seeding"

    def test_the_substitute_is_not_itself_the_sentinel(self) -> None:
        from bindsight.runners import tools

        assert tools._MPNN_SEED_FOR_ZERO != 0

    def test_a_run_seeded_zero_is_reproducible(self) -> None:
        """Substituting a *fixed* value, not a random one — the point is repeatability."""
        assert self._seed_arg(0) == self._seed_arg(0)

    def test_every_other_seed_is_passed_through_unchanged(self) -> None:
        """Only the sentinel moves, so no reproducible run changes its results."""
        for seed in (1, 2, 42, 999, 20260913):
            assert self._seed_arg(seed) == str(seed)

    def test_distinct_seeds_stay_distinct(self) -> None:
        """A substitution that collided with a real seed would merge two runs."""
        from bindsight.runners import tools

        seeds = [0, 1, 42, tools._MPNN_SEED_FOR_ZERO]
        mapped = [self._seed_arg(s) for s in seeds]
        # 0 and the substitute deliberately coincide; everything else is 1:1.
        assert len(set(mapped)) == len(set(seeds)) - 1

    def test_the_executor_passes_the_run_seed(self, mock_run, tmp_path: Path) -> None:
        work = tmp_path / "work"
        work.mkdir()
        (work / "target.pdb").write_text(_TINY_PDB)
        spec = _spec()
        spec["seed"] = 42
        job_exec.run_job(spec, work, tarball=tmp_path / "r.tar.gz")
        mpnn = [c for c in mock_run if any("protein_mpnn_run.py" in a for a in c)]
        assert mpnn
        for cmd in mpnn:
            assert cmd[cmd.index("--seed") + 1] == "42"


class TestTheValidatorIsSeeded:
    """The configured seed reached the designer and stopped there.

    Boltz-2 builds structures by diffusion; its ``--seed`` defaults to ``None``
    — "no seeding" in its own help — and ``--diffusion_samples`` to 1. So the
    stochastic half of the pipeline, the half that produces every confidence
    number the project publishes, ran unseeded and drew once.

    The calibration run measured the cost: refolding the same twenty sequences
    moved ipTM by a median of 0.129 and a maximum of 0.667, flipped eight of
    twenty verdicts at the shipped 0.65 threshold, and left the two runs
    correlated at Spearman 0.065. This is the same defect the suite already
    records for ``params.design.seed`` — declared, documented, read by no code —
    one stage further along.
    """

    @staticmethod
    def _boltz_calls(calls: list[list[str]]) -> list[list[str]]:
        return [c for c in calls if c and c[0] == "boltz"]

    def test_every_boltz_call_carries_a_seed(self, mock_run, tmp_path: Path) -> None:
        work = tmp_path / "work"
        work.mkdir()
        (work / "target.pdb").write_text(_TINY_PDB)
        job_exec.run_job(_spec(), work, tarball=tmp_path / "results.tar.gz")

        boltz = self._boltz_calls(mock_run)
        assert boltz, "no boltz invocation to check"
        for cmd in boltz:
            assert "--seed" in cmd, "the validator was invoked without a seed"

    def test_each_binder_gets_its_own_seed(self, mock_run, tmp_path: Path) -> None:
        """One seed across every design would correlate their draws."""
        work = tmp_path / "work"
        work.mkdir()
        (work / "target.pdb").write_text(_TINY_PDB)
        job_exec.run_job(_spec(), work, tarball=tmp_path / "results.tar.gz")

        seeds = [c[c.index("--seed") + 1] for c in self._boltz_calls(mock_run)]
        assert len(seeds) == len(set(seeds)), f"binders shared a seed: {seeds}"

    def test_the_same_run_seed_reproduces_the_same_binder_seed(self) -> None:
        """Derived from the id, so a rerun repeats rather than re-rolls."""
        assert job_exec._binder_seed(0, "b0") == job_exec._binder_seed(0, "b0")
        assert job_exec._binder_seed(0, "b0") != job_exec._binder_seed(0, "b1")
        assert job_exec._binder_seed(0, "b0") != job_exec._binder_seed(1, "b0")

    def test_a_binder_seed_is_not_derived_from_enumeration_order(self) -> None:
        """Order-derived seeds change when a design is added or dropped."""
        ids = ["z_last", "a_first", "m_middle"]
        by_id = {i: job_exec._binder_seed(3, i) for i in ids}
        reordered = {i: job_exec._binder_seed(3, i) for i in reversed(ids)}
        assert by_id == reordered

    def test_the_seed_stays_inside_the_accepted_range(self) -> None:
        """Lightning's seed_everything rejects values outside 32 bits."""
        for binder_id in ("b0", "P04626_binder_19_seq1_scram", "x" * 200):
            assert 0 <= job_exec._binder_seed(0, binder_id) < 2**32

    def test_the_configured_run_seed_is_what_reaches_the_validator(
        self, mock_run, tmp_path: Path
    ) -> None:
        """A spec seed that changed nothing downstream is the original defect."""
        work = tmp_path / "work"
        work.mkdir()
        (work / "target.pdb").write_text(_TINY_PDB)
        spec = _spec()
        spec["seed"] = 12345
        job_exec.run_job(spec, work, tarball=tmp_path / "results.tar.gz")

        seeds = {int(c[c.index("--seed") + 1]) for c in self._boltz_calls(mock_run)}
        expected = {
            job_exec._binder_seed(12345, binder_id)
            for binder_id in (d.stem for d in (work / "design").glob("*.fasta"))
        }
        assert seeds == expected, "the validator's seed does not follow the run's seed"

    def test_diffusion_samples_defaults_to_one_and_is_configurable(
        self, mock_run, tmp_path: Path
    ) -> None:
        """Averaging costs GPU time linearly, so it stays the caller's choice."""
        work = tmp_path / "work"
        work.mkdir()
        (work / "target.pdb").write_text(_TINY_PDB)
        job_exec.run_job(_spec(), work, tarball=tmp_path / "r.tar.gz")
        assert all("--diffusion_samples" not in c for c in self._boltz_calls(mock_run))

        mock_run.clear()
        work2 = tmp_path / "work2"
        work2.mkdir()
        (work2 / "target.pdb").write_text(_TINY_PDB)
        spec = _spec()
        spec["extra_params"]["diffusion_samples"] = 5
        job_exec.run_job(spec, work2, tarball=tmp_path / "r2.tar.gz")
        for cmd in self._boltz_calls(mock_run):
            assert cmd[cmd.index("--diffusion_samples") + 1] == "5"

    def test_a_nonsensical_sample_count_is_refused(self) -> None:
        from bindsight.runners import tools

        for bad in (0, -1):
            with pytest.raises(ValueError, match="diffusion_samples"):
                tools.build_boltz_cmd(
                    yaml_path=Path("x.yaml"), out_dir=Path("o"), diffusion_samples=bad
                )
            with pytest.raises(ValueError, match="max_parallel_samples"):
                tools.build_boltz_cmd(
                    yaml_path=Path("x.yaml"), out_dir=Path("o"), max_parallel_samples=bad
                )

    def test_extra_samples_are_drawn_sequentially_unless_asked_otherwise(self) -> None:
        """Boltz-2 batches all of them by default, and the T4 has no room.

        ``--max_parallel_samples`` is documented as "Default is None" and is
        actually 5, so asking for five draws silently diffuses five at once. The
        instrumented run peaked at 10,917 MiB of the T4's 15,360 with a *single*
        draw, so the default would spend a multi-hour job to find out it does
        not fit.
        """
        from bindsight.runners import tools

        cmd = tools.build_boltz_cmd(
            yaml_path=Path("x.yaml"), out_dir=Path("o"), diffusion_samples=5
        )
        assert "--max_parallel_samples" in cmd, (
            "the parallel batch size is left to Boltz-2's undocumented default"
        )
        assert cmd[cmd.index("--max_parallel_samples") + 1] == "1"

    def test_a_caller_with_the_vram_can_still_batch(self) -> None:
        from bindsight.runners import tools

        cmd = tools.build_boltz_cmd(
            yaml_path=Path("x.yaml"),
            out_dir=Path("o"),
            diffusion_samples=8,
            max_parallel_samples=4,
        )
        assert cmd[cmd.index("--max_parallel_samples") + 1] == "4"

    def test_a_single_draw_adds_no_sampling_flags(self) -> None:
        """The default path must stay byte-identical to what has always run."""
        from bindsight.runners import tools

        cmd = tools.build_boltz_cmd(yaml_path=Path("x.yaml"), out_dir=Path("o"))
        assert "--diffusion_samples" not in cmd
        assert "--max_parallel_samples" not in cmd


def test_materialise_target_copies_pdb(tmp_path: Path) -> None:
    spec_dir = tmp_path / "spec"
    spec_dir.mkdir()
    (spec_dir / "target.pdb").write_text(_TINY_PDB)
    spec = {"extra_params": {"target_structure_name": "target.pdb"}}
    work = tmp_path / "work"
    job_exec.materialise_target(spec, spec_dir, work)
    assert (work / "target.pdb").read_text() == _TINY_PDB


# ---------------------------------------------------------------------------
# Designers the pinned upstream cannot seed
# ---------------------------------------------------------------------------
class TestUnseedableDesigners:
    """``spec["seed"]`` is part of the design cache key, which says "same seed,
    same work". Two of the three designers cannot honour that, because their
    pinned upstream exposes no way to set a seed. These tests keep the exception
    declared, evidenced, and audible rather than silent.
    """

    def test_every_designer_threads_the_seed_or_is_declared_unseedable(self) -> None:
        """Discovered from the registry, not from a list written beside it, so a
        designer added later cannot quietly join without answering the question."""
        for name, fn in job_exec._DESIGNERS.items():
            if name in job_exec.UNSEEDABLE_DESIGNERS:
                continue
            source = inspect.getsource(fn)
            assert 'spec.get("seed"' in source, (
                f"designer {name!r} neither reads spec['seed'] nor appears in "
                "UNSEEDABLE_DESIGNERS; the seed is in its cache key either way"
            )

    def test_the_declarations_are_all_real_designers(self) -> None:
        """A stale entry would make the warning unreachable and the claim untestable."""
        unknown = set(job_exec.UNSEEDABLE_DESIGNERS) - set(job_exec._DESIGNERS)
        assert not unknown, f"UNSEEDABLE_DESIGNERS names no-such-designer(s): {unknown}"

    def test_each_reason_cites_the_commit_that_is_actually_pinned(self) -> None:
        """The evidence was read at a specific commit. Bumping the pin without
        re-reading it would leave a citation that no longer describes the code,
        which is worse than no citation at all.
        """
        pinned = {
            "bindcraft": tools.BINDCRAFT_COMMIT,
            "boltzgen": tools.BOLTZGEN_COMMIT,
        }
        for designer, reason in job_exec.UNSEEDABLE_DESIGNERS.items():
            commit = pinned[designer]
            cited = [w.strip(".,;:()") for w in reason.split() if len(w.strip(".,;:()")) >= 8]
            assert any(commit.startswith(c) for c in cited), (
                f"the {designer} reason cites no prefix of the pinned commit "
                f"{commit}; re-read the upstream at this commit and restate it"
            )

    def test_running_an_unseedable_designer_warns_through_run_job(
        self, mock_run, monkeypatch, tmp_path: Path, caplog
    ) -> None:
        """Drives the real dispatch. The warning has to be wired into ``run_job``;
        a test that called ``warn_if_unseeded`` directly would still pass with the
        call site deleted, which is the failure this is written to prevent.

        BindCraft's own implementation is not what is under test, so the registry
        entry points at the designer the fake tools can drive. ``run_job`` still
        sees ``designer == "bindcraft"``, and that is what selects the branch.
        """
        registry = dict(job_exec._DESIGNERS)
        registry["bindcraft"] = job_exec._design_rfdiff_mpnn
        monkeypatch.setattr(job_exec, "_DESIGNERS", registry)

        work = tmp_path / "work"
        work.mkdir()
        (work / "target.pdb").write_text(_TINY_PDB)
        spec = _spec()
        spec["seed"] = 4242
        spec["extra_params"]["designer"] = "bindcraft"

        with caplog.at_level(logging.WARNING, logger=job_exec.LOG.name):
            job_exec.run_job(spec, work, tarball=tmp_path / "r.tar.gz")

        warnings = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
        seed_warnings = [m for m in warnings if "ignores the configured seed" in m]
        assert seed_warnings, f"no unseeded-designer warning; got {warnings}"
        assert "bindcraft" in seed_warnings[0]
        assert "4242" in seed_warnings[0], "the warning must name the seed being ignored"
        assert "not reproducible" in seed_warnings[0]

    def test_a_seeded_designer_does_not_warn(self, mock_run, tmp_path: Path, caplog) -> None:
        """The warning must stay specific; firing it for rfdiff_mpnn — which does
        thread the seed — would teach readers to ignore it."""
        work = tmp_path / "work"
        work.mkdir()
        (work / "target.pdb").write_text(_TINY_PDB)

        with caplog.at_level(logging.WARNING, logger=job_exec.LOG.name):
            job_exec.run_job(_spec(), work, tarball=tmp_path / "r.tar.gz")

        assert not [
            r.getMessage()
            for r in caplog.records
            if "ignores the configured seed" in r.getMessage()
        ]


def test_the_archive_carries_the_prescreen_record(mock_run, tmp_path: Path) -> None:
    """The record of whether the ESM-2 screen ran must leave the GPU host.

    It did not. ``prescreen.txt`` was written into the work directory and the
    tarball packed only ``design``, ``validate`` and ``metrics.jsonl`` -- so the
    file was created and discarded on the machine that made it.

    That matters because ``prescreen_top_k`` is part of the cache key while the
    screen itself fails open: a job whose embedding died keeps every design and
    is cached under a key asserting it kept the top k, and the next run with a
    working embedder is served the unscreened set. This file is the only thing
    that distinguishes the two, and nothing anywhere else records it.
    """
    import tarfile

    work = tmp_path / "work"
    work.mkdir()
    (work / "target.pdb").write_text(_TINY_PDB)

    tar = job_exec.run_job(_spec(), work, tarball=tmp_path / "results.tar.gz")

    with tarfile.open(tar, "r:gz") as tf:
        members = set(tf.getnames())

    assert "prescreen.txt" in members, (
        f"the results archive does not carry the pre-screen record: {sorted(members)}"
    )


def test_the_prescreen_record_is_written_even_when_nothing_was_screened(
    mock_run, tmp_path: Path
) -> None:
    """Absence of the file must not be the way "no screen" is expressed.

    A missing file used to mean either "the screen ran and had nothing to say"
    or "the screen was never reached", and a reader could not tell which.
    """
    work = tmp_path / "work"
    work.mkdir()
    (work / "target.pdb").write_text(_TINY_PDB)

    job_exec.run_job(_spec(), work, tarball=tmp_path / "results.tar.gz")

    note = (work / "prescreen.txt").read_text(encoding="utf-8")
    assert note.strip(), "prescreen.txt is empty, so it says nothing either way"


def test_the_external_tool_seam_has_a_wall_clock() -> None:
    """The one seam through which GPU tools run had no timeout.

    ``_run`` dispatches RFdiffusion, ProteinMPNN and Boltz-2 on rented or
    quota-limited hardware. Without a timeout a tool that stopped making
    progress burned the whole session with nothing to stop it and nothing in the
    log to say so.

    Checked by driving ``_run`` and inspecting what it passed, rather than by
    reading the source: a structural check would pass against a timeout that is
    computed and then not forwarded.
    """
    import subprocess as _sp
    from unittest.mock import patch

    seen: dict[str, object] = {}

    def _fake_run(cmd, **kwargs):
        seen.update(kwargs)
        return _sp.CompletedProcess(cmd, 0, "", "")

    with patch.object(_sp, "run", _fake_run):
        job_exec._run(["true"])

    assert "timeout" in seen, "the external-tool seam runs without a wall clock"
    assert isinstance(seen["timeout"], (int, float))
    assert seen["timeout"] > 0


def test_the_tool_timeout_is_configurable_and_sane() -> None:
    """Long enough not to cut real work short, short enough to bound a hang."""
    assert 60 * 60 <= job_exec._TOOL_TIMEOUT_S <= 24 * 60 * 60

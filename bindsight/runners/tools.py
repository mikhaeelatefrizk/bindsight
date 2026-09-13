# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Single source of truth for the design/validation tools.

Pure, CPU-importable command-builders + output-parsers shared by BOTH the
generated Colab/Modal notebook (:mod:`bindsight.runners.notebook_content`) and
the real headless executor (:mod:`bindsight.runners.job_exec`). Keeping the
exact CLI invocations and pinned revisions in one place means the notebook and
the runners can never drift.

Nothing here imports torch / boltz / GPU libraries — the builders just return
``list[str]`` argv that the executor runs as subprocesses on a CUDA box. The
parsers read the tools' output files (NumPy is lazy-imported only where needed).

Pinned upstream revisions (real HEAD SHAs, resolved via ``git ls-remote``):
"""

from __future__ import annotations

import json
import logging
import os
import statistics
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from bindsight.validate.boltz2 import (
    PINNED_BOLTZ2_VERSION,
    build_boltz_yaml,
    parse_boltz_output,
)
from bindsight.validate.protocol import (
    UNRECORDED_VERSION,
    ValidationResult,
    installed_version,
)

LOG = logging.getLogger(__name__)


def _design_python() -> str:
    """Interpreter for the design subprocesses (RFdiffusion / ProteinMPNN).

    Defaults to ``python`` on PATH. Hosts that run the *designer* in a different
    Python env than the orchestrator (e.g. the Kaggle split-env build, where
    RFdiffusion needs a legacy py3.9/torch1.12 env while ``job_exec`` itself runs
    under the modern Boltz-2 env) point this at that env's interpreter via
    ``BINDSIGHT_DESIGN_PYTHON``.
    """
    return os.environ.get("BINDSIGHT_DESIGN_PYTHON") or "python"


def _boltz_bin() -> str:
    """Executable for the Boltz-2 validator (``boltz`` on PATH by default).

    Overridable via ``BINDSIGHT_BOLTZ_BIN`` for split-env hosts where Boltz-2
    lives in its own environment.
    """
    return os.environ.get("BINDSIGHT_BOLTZ_BIN") or "boltz"


# ---------------------------------------------------------------------------
# Pinned upstream tool revisions + weights (real, verifiable).
# ---------------------------------------------------------------------------
RFDIFF_REPO = "https://github.com/RosettaCommons/RFdiffusion"
RFDIFF_COMMIT = "2d0c003df46b9db41d119321f15403dec3716cd9"
# IPD's public weight mirror (see the RFdiffusion README). HTTPS, not HTTP:
# these are ~480 MB of model parameters that get loaded and executed, and the
# comment that used to sit here claimed they were "verified on download in the
# executor when a hash is supplied" while no verification code existed at either
# download site. Plain HTTP with no integrity check is how a truncated transfer
# becomes a checkpoint that loads and quietly produces different structures.
RFDIFF_WEIGHTS: dict[str, str] = {
    "Base_ckpt.pt": "https://files.ipd.uw.edu/pub/RFdiffusion/6f5902ac237024bdd0c176cb93063dc4/Base_ckpt.pt",
    "Complex_base_ckpt.pt": "https://files.ipd.uw.edu/pub/RFdiffusion/e29311f6f1bf1af907f9ef9f44b8328b/Complex_base_ckpt.pt",
}

#: sha256 of each checkpoint, or None where one has not been established yet.
#:
#: Both download sites now hash what they fetched and log it, and refuse to
#: proceed when a hash here disagrees. Pinning is therefore a two-step process
#: on purpose: run once, read the hash out of the run log, paste it here. A
#: hash invented locally would only certify whatever this machine happened to
#: download, which is the thing being checked.
#:
#: The 32-hex path segment in each URL is IPD's own content digest, so a change
#: upstream arrives as a new URL rather than as different bytes at the same one.
#: That makes a silent substitution unlikely; it does not make a truncated or
#: corrupted transfer detectable, which is what these hashes are for.
RFDIFF_WEIGHT_SHA256: dict[str, str | None] = {
    "Base_ckpt.pt": None,
    "Complex_base_ckpt.pt": None,
}

PROTEINMPNN_REPO = "https://github.com/dauparas/ProteinMPNN"
PROTEINMPNN_COMMIT = "8907e6671bfbfc92303b5f79c4b5e6ce47cdef57"

#: Pinned exactly, like every other external tool here.
#:
#: This was ``boltz>=2.0,<3.0`` — a range — which made Boltz-2 the one tool in
#: this file free to change between runs. It is also the tool that produces
#: every confidence number the project publishes, so two runs a month apart
#: could report ipTM from two different models under one label. The artifacts
#: could not have told them apart either: ``validator_version`` was a hardcoded
#: ``"2.0.1"`` written into every metrics row whatever was installed, so the one
#: field that looked like it recorded this was answering from a constant. It is
#: read from the environment now. RFdiffusion, ProteinMPNN, BindCraft and
#: BoltzGen are all pinned to a commit; there was no argument for exempting the
#: validator, only an oversight.
#:
#: 2.0.3 is the version the precision audit in ``benchmarks/calibration``
#: examined line by line (wheel sha256
#: 5851dd10c7819d4c011534a4e5c9cc495d95e42e0e1336617a1e9e78d6c4cf12). Raising
#: this pin invalidates that audit, and — because this file ships inside the
#: wheel whose hash is folded into the cache key — correctly invalidates every
#: cached result produced under the old one.
BOLTZ_PIP = f"boltz=={PINNED_BOLTZ2_VERSION}"

BINDCRAFT_REPO = "https://github.com/martinpacesa/BindCraft"
BINDCRAFT_COMMIT = "b971db42ba6e091afab63ccb30ae02215150a990"

BOLTZGEN_REPO = "https://github.com/HannesStark/boltzgen"
BOLTZGEN_COMMIT = "a3149cf18eeb58648d1abbb27539bd73f746cdda"

CHAI_PIP = "chai_lab>=0.6"
CHAI_REPO = "https://github.com/chaidiscovery/chai-lab"
CHAI_COMMIT = "c544fb183e865c4950909444db860a9d50604f66"

# AF2 initial-guess (Bennett/Baker dl_binder_design). NON-commercial AF2 weights.
DL_BINDER_DESIGN_REPO = "https://github.com/nrbennet/dl_binder_design"
DL_BINDER_DESIGN_COMMIT = "cafa3853ac94dceb1b908c8d9e6954d71749871a"

_AA3TO1 = {
    "ALA": "A",
    "ARG": "R",
    "ASN": "N",
    "ASP": "D",
    "CYS": "C",
    "GLN": "Q",
    "GLU": "E",
    "GLY": "G",
    "HIS": "H",
    "ILE": "I",
    "LEU": "L",
    "LYS": "K",
    "MET": "M",
    "PHE": "F",
    "PRO": "P",
    "SER": "S",
    "THR": "T",
    "TRP": "W",
    "TYR": "Y",
    "VAL": "V",
}


# ---------------------------------------------------------------------------
# Pure string helpers (highest-risk — exhaustively unit-tested)
# ---------------------------------------------------------------------------
def build_hotspot_str(chain: str, residues: list[int]) -> str:
    """RFdiffusion ``ppi.hotspot_res`` token, e.g. ``[A30,A31,A45]``."""
    return "[" + ",".join(f"{chain}{r}" for r in residues) + "]"


def build_contig_str(
    target_chain: str,
    target_lo: int,
    target_hi: int,
    binder_len_min: int,
    binder_len_max: int,
) -> str:
    """RFdiffusion ``contigmap.contigs`` token.

    ``[A<lo>-<hi>/0 <bmin>-<bmax>]`` = keep target chain residues lo–hi, insert a
    chain break (``/0``), then diffuse a new binder of length bmin–bmax. The span
    is derived from the actual structure (not hard-coded ``A1-9999``).
    """
    return build_ranges_contig_str(
        target_chain, [(target_lo, target_hi)], binder_len_min, binder_len_max
    )


def build_ranges_contig_str(
    target_chain: str,
    ranges: Sequence[tuple[int, int]],
    binder_len_min: int,
    binder_len_max: int,
) -> str:
    """RFdiffusion contig keeping only ``ranges`` of the target chain.

    Segments of the same chain are joined by ``/`` and the residues between them
    are dropped, so a single-pass receptor can be presented by its extracellular
    ranges alone — ``[A23-652/A700-720/0 50-100]``. Without this the diffusion
    model sees the transmembrane helix and the cytoplasmic tail as part of the
    binding surface, which no extracellular binder can reach.
    """
    if not ranges:
        raise ValueError("at least one target range is required to build a contig")
    segments = "/".join(f"{target_chain}{lo}-{hi}" for lo, hi in ranges)
    return f"[{segments}/0 {binder_len_min}-{binder_len_max}]"


# ---------------------------------------------------------------------------
# Command builders (return argv lists; no shell)
# ---------------------------------------------------------------------------
#: What a configured seed of 0 becomes for ProteinMPNN.
#:
#: Any non-zero constant would do; this one is fixed so that a run seeded 0 is
#: reproducible rather than merely non-random. It must never itself be 0.
_MPNN_SEED_FOR_ZERO = 20260912


#: Bound on the run seed before it is turned into a design-index block.
#:
#: ``design_startnum`` becomes ``seed * num_designs``, and that index is handed
#: to ``torch.manual_seed``, which requires a value below 2**64. Reducing the
#: seed first keeps the product small for any seed a user might write. Two run
#: seeds congruent modulo this share a block; with a million blocks that is not
#: a collision anyone meets by accident.
_SEED_BLOCKS = 1_000_000


def build_rfdiff_cmd(
    *,
    rfdiff_dir: Path,
    input_pdb: Path,
    output_prefix: Path,
    num_designs: int,
    hotspot: str,
    contig: str,
    seed: int | None = None,
) -> list[str]:
    """RFdiffusion ``scripts/run_inference.py`` argv for binder backbone design.

    RFdiffusion is a diffusion model and it is the *first* stochastic stage: the
    backbones it draws determine the sequences ProteinMPNN writes and therefore
    every confidence number downstream. At the pinned commit it seeds
    ``torch``/``numpy``/``random`` only inside ``if conf.inference.deterministic``,
    and ``config/inference/base.yaml`` ships ``deterministic: False``. This
    builder passed neither that flag nor anything else, so the backbone
    generator ran unseeded — the same defect as the unseeded validator, one
    stage upstream, and the stage that defeats the fix applied downstream: a
    reproducibly folded sequence is no use when the sequence itself is not
    reproducible.

    **How the seed is injected.** There is no ``inference.seed``. Upstream does::

        if conf.inference.deterministic:
            make_deterministic()              # seed 0, once
        for i_des in range(design_startnum, design_startnum + num_designs):
            if conf.inference.deterministic:
                make_deterministic(i_des)     # seed = the design's index

    so the design index *is* the seed, and ``design_startnum`` chooses it. The
    run's seed therefore selects a block of ``num_designs`` consecutive indices.
    It is multiplied by ``num_designs`` rather than used directly so that
    adjacent seeds get **disjoint** blocks: seeds 42 and 43 with ten designs
    would otherwise share nine of their ten indices and produce nine identical
    backbones while claiming to be different runs.

    ``design_startnum`` does not leak into the results: the executor names
    designs by enumeration order, not by RFdiffusion's file numbering.

    Args:
        rfdiff_dir: the RFdiffusion checkout.
        input_pdb: the target structure.
        output_prefix: where RFdiffusion writes its backbones.
        num_designs: trajectories to draw.
        hotspot: ``ppi.hotspot_res`` token.
        contig: ``contigmap.contigs`` token.
        seed: the run's seed. ``None`` reproduces the previous unseeded
            behaviour, which is left reachable only so the argv this project
            already published can still be built.

    Returns:
        The argv list.

    Raises:
        ValueError: If ``seed`` is negative.
    """
    cmd = [
        _design_python(),
        str(Path(rfdiff_dir) / "scripts" / "run_inference.py"),
        f"inference.input_pdb={input_pdb}",
        f"inference.output_prefix={output_prefix}",
        f"inference.num_designs={num_designs}",
        f"ppi.hotspot_res={hotspot}",
        f"contigmap.contigs={contig}",
    ]
    if seed is not None:
        if seed < 0:
            raise ValueError(f"seed must not be negative; got {seed}")
        cmd += [
            "inference.deterministic=True",
            f"inference.design_startnum={(seed % _SEED_BLOCKS) * num_designs}",
        ]
    return cmd


def build_mpnn_cmd(
    *,
    mpnn_dir: Path,
    pdb_path: Path,
    out_folder: Path,
    designed_chains: Sequence[str],
    num_seq_per_target: int = 2,
    sampling_temp: float = 0.1,
    seed: int = 0,
) -> list[str]:
    """ProteinMPNN ``protein_mpnn_run.py`` argv for sequence design on a backbone.

    ``designed_chains`` is mandatory: ProteinMPNN designs *every* chain when
    ``--pdb_path_chains`` is absent, so on a binder–target complex it would
    redesign the target too and the binder would be optimised against a surface
    the model partly invented. Chains left out of ``--pdb_path_chains`` are kept
    as fixed context, which is the conditioning binder design needs — whole
    chains are held, so per-position ``--fixed_positions_jsonl`` is not required,
    and ``--chain_id_jsonl`` only applies to the folder-of-PDBs input mode.
    """
    if not designed_chains:
        raise ValueError("designed_chains must name at least one chain to design")
    return [
        _design_python(),
        str(Path(mpnn_dir) / "protein_mpnn_run.py"),
        "--pdb_path",
        str(pdb_path),
        "--pdb_path_chains",
        " ".join(designed_chains),
        "--out_folder",
        str(out_folder),
        "--num_seq_per_target",
        str(num_seq_per_target),
        "--sampling_temp",
        str(sampling_temp),
        "--seed",
        # Never the literal 0. ProteinMPNN documents it as a sentinel — its
        # argparse help reads "If set to 0 then a random seed will be picked",
        # and the code is `if args.seed: seed = args.seed else: seed =
        # np.random.randint(...)`. So the one value that reads as "no offset,
        # plain default" is the value that silently turns seeding off, and it is
        # the default of this parameter and of DesignSpec.seed on several paths.
        # Only the sentinel is substituted, so every non-zero seed keeps the
        # exact value it has always had and no reproducible run moves.
        str(seed or _MPNN_SEED_FOR_ZERO),
    ]


def build_boltz_cmd(
    *,
    yaml_path: Path,
    out_dir: Path,
    use_msa_server: bool = True,
    seed: int | None = None,
    diffusion_samples: int = 1,
    max_parallel_samples: int = 1,
) -> list[str]:
    """Boltz-2 ``boltz predict`` argv for structure + affinity prediction.

    Boltz-2 generates structures by diffusion. Its ``--seed`` defaults to
    ``None``, which its own help text spells "no seeding", and
    ``--diffusion_samples`` defaults to 1. Passing neither — which this builder
    did — makes every reported ipTM a single unseeded draw from a stochastic
    model, and the project's calibration run measured what that costs: refolding
    the same twenty sequences moved ipTM by a median of 0.129 and a maximum of
    0.667, flipped eight of twenty verdicts at the 0.65 threshold, and left the
    two runs correlated at Spearman 0.065. A number that does not survive its own
    rerun cannot support a per-design claim.

    The seed makes a run repeatable. It does not make one draw representative —
    only ``diffusion_samples`` does that, at linear GPU cost — so the two are
    separate knobs and the caller chooses what to spend.

    Args:
        yaml_path: the Boltz-2 spec to predict.
        out_dir: where Boltz-2 writes predictions.
        use_msa_server: use the hosted MSA server.
        seed: RNG seed. ``None`` leaves Boltz-2 unseeded, which is only
            appropriate when drawing deliberately independent samples.
        diffusion_samples: how many structures to draw per input.
        max_parallel_samples: how many of those to diffuse at once.

    Returns:
        The argv list.

    Raises:
        ValueError: If either count is not positive.
    """
    if diffusion_samples < 1:
        raise ValueError(f"diffusion_samples must be at least 1; got {diffusion_samples}")
    if max_parallel_samples < 1:
        raise ValueError(f"max_parallel_samples must be at least 1; got {max_parallel_samples}")
    cmd = [_boltz_bin(), "predict", str(yaml_path), "--out_dir", str(out_dir)]
    if use_msa_server:
        cmd.append("--use_msa_server")
    if seed is not None:
        cmd += ["--seed", str(seed)]
    if diffusion_samples != 1:
        cmd += ["--diffusion_samples", str(diffusion_samples)]
        # Always explicit, and sequential by default. Boltz-2's own default is
        # 5 — its ``--max_parallel_samples`` help text says "Default is None"
        # while the click option says ``default=5`` — so asking for five draws
        # silently diffuses all five at once. The instrumented run measured a
        # peak of 10,917 MiB of the T4's 15,360 with a single draw of a
        # ~230-token complex, leaving about 4 GB of headroom, and this project
        # targets free-tier cards. Sequential trades wall-clock for not losing
        # the whole job to an out-of-memory kill hours in; a caller with the
        # VRAM can raise it.
        cmd += ["--max_parallel_samples", str(max_parallel_samples)]
    return cmd


def build_chai_cmd(*, fasta_path: Path, out_dir: Path, seed: int | None = None) -> list[str]:
    """Chai-1 ``chai-lab fold`` argv (structure + confidence prediction).

    Chai-1 diffuses like Boltz-2 and is unseeded by the same default: at the
    pinned commit ``run_inference`` takes ``seed: int | None = None`` and
    ``num_diffn_samples: int = 5``. This builder passed no seed, so the
    validator was nondeterministic exactly as Boltz-2 was before it was fixed.

    No published number comes from here — ``plugin_support`` marks chai1r
    unsupported on every bundled backend, because it needs bfloat16 and the free
    tiers pin pre-Ampere cards — so the defect is latent. It is fixed anyway,
    for the same reason the hardcoded ``validator_version`` beside it was: a
    plugin that has not run yet is the one place a defect can sit unnoticed
    until it is producing results.

    Args:
        fasta_path: the complex to fold.
        out_dir: where Chai-1 writes its predictions.
        seed: RNG seed. ``None`` leaves Chai-1 unseeded.

    Returns:
        The argv list.

    Raises:
        ValueError: If ``seed`` is negative.
    """
    cmd = ["chai-lab", "fold", str(fasta_path), str(out_dir)]
    if seed is not None:
        if seed < 0:
            raise ValueError(f"seed must not be negative; got {seed}")
        cmd += ["--seed", str(seed)]
    return cmd


def build_bindcraft_cmd(
    *, bindcraft_dir: Path, settings_json: Path, filters_json: Path, advanced_json: Path
) -> list[str]:
    """BindCraft ``bindcraft.py`` argv (one-shot AF2-based binder design)."""
    return [
        "python",
        str(Path(bindcraft_dir) / "bindcraft.py"),
        "--settings",
        str(settings_json),
        "--filters",
        str(filters_json),
        "--advanced",
        str(advanced_json),
    ]


#: BoltzGen protocols, from the upstream README. ``protein-anything`` is the one
#: that designs proteins against protein targets, which is what bindsight does.
BOLTZGEN_PROTOCOLS = (
    "protein-anything",
    "peptide-anything",
    "protein-small_molecule",
    "nanobody-anything",
    "antibody-anything",
)


def build_boltzgen_spec(
    *,
    target_file: str,
    target_chain: str,
    binding_indices: list[int],
    binder_length_min: int,
    binder_length_max: int,
    binder_chain: str = "B",
) -> dict[str, Any]:
    """Build a BoltzGen design-specification mapping.

    BoltzGen is driven by a design-spec YAML listing ``entities``: the protein to
    design (given as a length range, which BoltzGen samples) and the target,
    pulled from a structure file with an optional binding-site restriction.

    Args:
        target_file: Structure filename **relative to the YAML's own directory** —
            BoltzGen resolves file references relative to the spec, not the cwd.
        target_chain: Chain in that file to use as the target.
        binding_indices: Residues the binder should bind, as **1-based ordinals
            within the chain as it appears in the file** (BoltzGen's canonical
            ``label_seq_id`` convention), not author numbering. Empty means bind
            anywhere, which is BoltzGen's documented default.
        binder_length_min: Shortest binder to sample.
        binder_length_max: Longest binder to sample.
        binder_chain: Chain id for the designed protein.

    Returns:
        A mapping ready to serialise as the design-spec YAML.
    """
    target: dict[str, Any] = {
        "path": target_file,
        "include": [{"chain": {"id": target_chain}}],
    }
    if binding_indices:
        target["binding_types"] = [
            {
                "chain": {
                    "id": target_chain,
                    "binding": ",".join(str(i) for i in sorted(set(binding_indices))),
                }
            }
        ]
    return {
        "entities": [
            {
                "protein": {
                    "id": binder_chain,
                    "sequence": f"{int(binder_length_min)}..{int(binder_length_max)}",
                }
            },
            {"file": target},
        ]
    }


def build_boltzgen_cmd(
    *,
    design_spec: Path,
    out_dir: Path,
    num_designs: int,
    protocol: str = "protein-anything",
    use_kernels: str = "auto",
    budget: int | None = None,
    devices: int | None = None,
    diffusion_batch_size: int | None = None,
) -> list[str]:
    """BoltzGen ``boltzgen run`` argv.

    The previous form of this function built ``boltzgen design --target ...
    --out_dir ... --hotspots ...``. Upstream has no ``design`` subcommand and
    none of those flags, so that command could never have executed; this is the
    real interface (``boltzgen run <spec.yaml> --output <dir>``), taken from the
    README at the pinned commit.

    ``use_kernels`` matters on free hardware: BoltzGen's Triton kernels need
    compute capability 8.0 or newer, and its ``auto`` default enables them on
    exactly that test. A T4 is 7.5 and a P100 is 6.0, so both need ``"false"``.

    Args:
        design_spec: Path to the design-specification YAML.
        out_dir: Output directory for pipeline results.
        num_designs: Total designs to generate before filtering.
        protocol: One of :data:`BOLTZGEN_PROTOCOLS`.
        use_kernels: ``"auto"``, ``"true"`` or ``"false"``.
        budget: Size of the final diversity-optimised set. Defaults to
            ``num_designs`` so a small run keeps everything it generated.
        devices: Number of devices; ``None`` lets BoltzGen use all available.
        diffusion_batch_size: Diffusion samples per trunk run. Small runs want 1,
            since a large batch shares one sampled binder length across the batch.

    Returns:
        The argv list.

    Raises:
        ValueError: On an unknown protocol or an invalid ``use_kernels`` value.
    """
    if protocol not in BOLTZGEN_PROTOCOLS:
        raise ValueError(f"unknown boltzgen protocol {protocol!r}; one of {BOLTZGEN_PROTOCOLS}")
    if use_kernels not in {"auto", "true", "false"}:
        raise ValueError(f"use_kernels must be auto/true/false, got {use_kernels!r}")
    cmd = [
        "boltzgen",
        "run",
        str(design_spec),
        "--output",
        str(out_dir),
        "--protocol",
        protocol,
        "--num_designs",
        str(int(num_designs)),
        "--use_kernels",
        use_kernels,
        "--budget",
        str(int(budget if budget is not None else num_designs)),
    ]
    if devices is not None:
        cmd += ["--devices", str(int(devices))]
    if diffusion_batch_size is not None:
        cmd += ["--diffusion_batch_size", str(int(diffusion_batch_size))]
    return cmd


def label_indices_for_residues(pdb_path: Path, chain: str, residues: list[int]) -> list[int]:
    """Map author residue numbers to 1-based ordinals within the chain.

    BoltzGen indexes residues by their canonical position in the chain, starting
    at 1, and its README is explicit that author numbering is *not* what it
    reads. bindsight carries epitope residues in author numbering (UniProt
    positions, preserved through the trimmed target), so they must be converted
    or the binding site silently lands on the wrong residues.

    Residues absent from the structure are dropped rather than guessed.
    """
    order = {resi: i + 1 for i, (resi, _aa) in enumerate(chain_residues_from_pdb(pdb_path, chain))}
    return [order[r] for r in residues if r in order]


def build_af2ig_cmd(*, dl_binder_design_dir: Path, silent_or_pdb: Path, out_dir: Path) -> list[str]:
    """AF2 initial-guess (dl_binder_design) argv. NON-commercial AF2 weights."""
    return [
        "python",
        str(Path(dl_binder_design_dir) / "af2_initial_guess" / "predict.py"),
        "-pdbdir",
        str(silent_or_pdb),
        "-outpdbdir",
        str(out_dir),
        "-scorefilename",
        str(Path(out_dir) / "af2_scores.sc"),
    ]


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------
def chain_residues_from_pdb(pdb_path: Path, chain: str = "A") -> list[tuple[int, str]]:
    """Extract ``(residue number, 1-letter code)`` for a chain (CA atoms, in order)."""
    residues: list[tuple[int, str]] = []
    seen: set[int] = set()
    for line in Path(pdb_path).read_text().splitlines():
        if line.startswith("ATOM") and line[12:16].strip() == "CA":
            if line[21] != chain:
                continue
            resi = int(line[22:26])
            if resi not in seen:
                seen.add(resi)
                residues.append((resi, _AA3TO1.get(line[17:20].strip(), "X")))
    return residues


_AA1TO3: dict[str, str] = {one: three for three, one in _AA3TO1.items()}


def write_designed_backbone(backbone: Path, dest: Path, *, chain: str, sequence: str) -> None:
    """Copy a backbone, rewriting one chain's residues to the designed sequence.

    Every ProteinMPNN sequence for a trajectory used to be staged as a
    byte-identical copy of the same RFdiffusion backbone. Twenty designs
    produced twenty files with ten distinct contents, each named for a design
    whose sequence it did not carry: the residues in it were the ones diffusion
    happened to emit, and the designed sequence lived only in the sibling FASTA.
    A reviewer opening ``..._seq0.pdb`` and ``..._seq1.pdb`` found the same file
    twice.

    Rewriting the residue names is a complete fix here rather than an
    approximation, because RFdiffusion emits backbone atoms only — N, CA, C and
    O, verified on the committed output — so there are no side chains to be left
    inconsistent with the new identities. The coordinates are the design's
    backbone and the residue names are now the design's sequence.

    Only the binder chain is touched. The target chain is the native structure
    the binder was designed against, and rewriting it is exactly the defect the
    ``--pdb_path_chains`` fix exists to prevent.

    Args:
        backbone: the RFdiffusion output to copy.
        dest: where to write the design.
        chain: the binder chain id to rewrite.
        sequence: the designed one-letter sequence for that chain.

    Raises:
        ValueError: If the chain is absent, or its residue count does not match
            the sequence. A mismatch means the file would describe a molecule
            that was never scored, which is worse than the duplicate it replaces.
    """
    lines = backbone.read_text(encoding="utf-8").splitlines(keepends=True)

    order: list[str] = []
    for line in lines:
        if line.startswith(("ATOM", "HETATM")) and line[21:22] == chain:
            residue = line[22:27]
            if not order or order[-1] != residue:
                order.append(residue)
    if not order:
        raise ValueError(f"{backbone.name}: chain {chain!r} has no residues to rewrite")
    if len(order) != len(sequence):
        raise ValueError(
            f"{backbone.name}: chain {chain!r} has {len(order)} residues but the "
            f"designed sequence is {len(sequence)}; refusing to write a structure "
            "that does not describe the design it is named for"
        )
    position = {residue: index for index, residue in enumerate(order)}

    out: list[str] = []
    for line in lines:
        if line.startswith(("ATOM", "HETATM")) and line[21:22] == chain:
            three = _AA1TO3.get(sequence[position[line[22:27]]].upper(), "UNK")
            line = line[:17] + f"{three:<3}" + line[20:]
        out.append(line)
    dest.write_text("".join(out), encoding="utf-8")


def chain_sequence_from_pdb(pdb_path: Path, chain: str = "A") -> str:
    """Extract a chain's 1-letter sequence from a PDB (CA atoms, in order)."""
    return "".join(aa for _, aa in chain_residues_from_pdb(pdb_path, chain))


def chain_sequences_from_cif(cif_path: Path) -> dict[str, str]:
    """Every chain's 1-letter sequence from an mmCIF, keyed by label_asym_id.

    Validator output is mmCIF, so checking what a predicted complex actually
    contains needs this rather than :func:`chain_sequence_from_pdb`. The check
    it exists for is whether a designed complex still carries the native target:
    ProteinMPNN will rewrite every chain it is given, and the difference between
    a real result and a design scored against a surface it invented is exactly
    one command-line flag.

    Args:
        cif_path: an mmCIF file with an ``_atom_site`` loop.

    Returns:
        chain id -> sequence, residues ordered by ``label_seq_id``. Empty when
        the file carries no atom records.
    """
    from Bio.PDB.MMCIF2Dict import MMCIF2Dict

    data = MMCIF2Dict(str(cif_path))
    chains = data.get("_atom_site.label_asym_id")
    comps = data.get("_atom_site.label_comp_id")
    seq_ids = data.get("_atom_site.label_seq_id")
    if not chains or not comps or not seq_ids:
        return {}
    by_chain: dict[str, dict[int, str]] = {}
    for chain, comp, seq_id in zip(chains, comps, seq_ids, strict=False):
        try:
            index = int(seq_id)
        except (TypeError, ValueError):  # heteroatoms carry "." here
            continue
        by_chain.setdefault(str(chain), {})[index] = _AA3TO1.get(str(comp).upper(), "X")
    return {
        chain: "".join(residues[i] for i in sorted(residues))
        for chain, residues in sorted(by_chain.items())
    }


def pdb_chain_ids(pdb_path: Path) -> list[str]:
    """Chain ids present in a PDB, in first-appearance order (CA atoms)."""
    chains: list[str] = []
    for line in Path(pdb_path).read_text().splitlines():
        if line.startswith("ATOM") and line[12:16].strip() == "CA":
            ch = line[21]
            if ch not in chains:
                chains.append(ch)
    return chains


def _target_likeness(seq: str, target_sequence: str, k: int = 6) -> float:
    """Fraction of ``seq``'s k-mers that also occur in ``target_sequence`` (0–1).

    A k-mer profile rather than string equality, so a target chain that RFdiffusion
    trimmed or renumbered still scores ~1 while a diffused (poly-glycine) binder
    scores ~0.
    """
    if not seq or not target_sequence:
        return 0.0
    if len(seq) < k:
        return 1.0 if seq in target_sequence else 0.0
    kmers = [seq[i : i + k] for i in range(len(seq) - k + 1)]
    return sum(1 for km in kmers if km in target_sequence) / len(kmers)


#: k-mer identity above which a backbone chain is considered part of the target.
_TARGET_LIKENESS_CUTOFF = 0.5


def binder_chain_from_backbone(backbone_pdb: Path, *, target_sequence: str) -> str:
    """Chain id of the diffused binder in an RFdiffusion binder-design backbone.

    RFdiffusion assigns output chain letters from the contig, so the binder's
    letter is not the input structure's and must not be hard-coded. The target
    block keeps its native residue identities while the diffused binder does not,
    so the binder is identified as the chain that does not match the target.

    Args:
        backbone_pdb: An RFdiffusion output backbone (target + binder complex).
        target_sequence: The target sequence RFdiffusion was given — the
            concatenation of the contig's kept target segments.

    Returns:
        The binder's chain id.

    Raises:
        ValueError: When exactly one non-target chain cannot be identified.
            Guessing here would hand ProteinMPNN the wrong chain to hold fixed,
            which silently redesigns the antigen.
    """
    chains = pdb_chain_ids(backbone_pdb)
    scores = {
        ch: _target_likeness(chain_sequence_from_pdb(backbone_pdb, ch), target_sequence)
        for ch in chains
    }
    binders = [ch for ch, s in scores.items() if s < _TARGET_LIKENESS_CUTOFF]
    targets = [ch for ch, s in scores.items() if s >= _TARGET_LIKENESS_CUTOFF]
    if len(binders) != 1 or not targets:
        raise ValueError(
            f"cannot identify the binder chain in {backbone_pdb}: "
            f"target-likeness per chain = { {c: round(s, 3) for c, s in scores.items()} }; "
            "refusing to run ProteinMPNN without knowing which chain to hold fixed"
        )
    return binders[0]


def parse_mpnn_fasta(fasta_path: Path) -> list[tuple[str, str]]:
    """Parse a ProteinMPNN output FASTA into ``[(header, sequence), ...]``.

    ProteinMPNN writes the input/native sequence as the FIRST record (header
    contains ``score=...`` for the original), then one record per sampled design
    (header contains ``sample=...``). Sequences are returned verbatim; callers
    that want only designs should skip the first (native) record. This parses by
    record, not by line index, so it is robust to the multi-line layout.
    """
    records: list[tuple[str, str]] = []
    header: str | None = None
    chunks: list[str] = []
    for line in Path(fasta_path).read_text().splitlines():
        if line.startswith(">"):
            if header is not None:
                records.append((header, "".join(chunks)))
            header, chunks = line[1:].strip(), []
        elif header is not None:
            chunks.append(line.strip())
    if header is not None:
        records.append((header, "".join(chunks)))
    return records


def mpnn_design_sequences(fasta_path: Path) -> list[str]:
    """Return only the *designed* binder sequences from a ProteinMPNN FASTA.

    Skips the first (native/input) record. ProteinMPNN can emit multi-chain
    sequences joined by ``/``; for binder design the binder is the last chain,
    so we take the final ``/``-segment of each design.
    """
    records = parse_mpnn_fasta(fasta_path)
    designs = records[1:] if len(records) > 1 else records
    return [seq.split("/")[-1] for _, seq in designs if seq]


def parse_chai_output(output_dir: Path, *, binder_id: str, target_uniprot: str) -> ValidationResult:
    """Parse Chai-1 output scores into a ValidationResult (lazy NumPy import)."""
    iptm = ptm = None
    iptm_samples: list[float] = []
    ptm_samples: list[float] = []
    # Every draw, not the first. chai-lab writes one scores npz per diffusion
    # sample — scores.model_idx_0.npz through model_idx_4.npz at its default of
    # five — and this took whichever the directory walk yielded first. That is
    # the same defect found and fixed in the Boltz-2 parser: a number that
    # improves as more samples are bought, with no change to the design being
    # scored. The mean estimates the centre of the distribution the model is
    # sampling from; one draw estimates nothing.
    for npz in sorted(Path(output_dir).rglob("scores*.npz")):
        try:
            import numpy as np

            data = np.load(npz)
            value = _to_float(data["iptm"]) if "iptm" in data else None
            if value is not None:
                iptm_samples.append(value)
            value = _to_float(data["ptm"]) if "ptm" in data else None
            if value is not None:
                ptm_samples.append(value)
        except Exception as e:  # pragma: no cover - depends on chai output shape
            LOG.warning("failed to parse chai npz %s: %s", npz, e)
    if iptm_samples:
        iptm = statistics.fmean(iptm_samples)
    if ptm_samples:
        ptm = statistics.fmean(ptm_samples)
    return ValidationResult(
        binder_id=binder_id,
        target_uniprot=target_uniprot,
        iptm=iptm,
        iptm_n_samples=len(iptm_samples) or None,
        iptm_sd=statistics.stdev(iptm_samples) if len(iptm_samples) > 1 else None,
        ptm=ptm,
        pae_interaction=None,
        # Chai-1 predicts no affinity. pTM is a structure-confidence score and
        # belongs in ``ptm``; writing it here would make the ranker weight
        # confidence a second time as though it were an orthogonal signal.
        affinity_pred_value=None,
        validator_name="chai1r",
        # chai_lab is a pip distribution, so the installed version is
        # readable. CHAI_PIP is still a range, which is why it is read
        # rather than assumed.
        validator_version=installed_version("chai_lab") or UNRECORDED_VERSION,
        notes=f"parsed chai scores={len(iptm_samples)} sample(s)",
    )


def parse_af2ig_output(
    score_file: Path, *, binder_id: str, target_uniprot: str
) -> ValidationResult:
    """Parse an AF2 initial-guess ``.sc`` score table into a ValidationResult."""
    pae_interaction = plddt = None
    sc = Path(score_file)
    if sc.exists():
        lines = [ln.split() for ln in sc.read_text().splitlines() if ln.strip()]
        if len(lines) >= 2:
            header, row = lines[0], lines[1]
            cols = dict(zip(header, row, strict=False))
            pae_interaction = _to_float(cols.get("pae_interaction"))
            plddt = _to_float(cols.get("plddt_binder"))
    return ValidationResult(
        binder_id=binder_id,
        target_uniprot=target_uniprot,
        iptm=None,
        plddt_binder=plddt,
        pae_interaction=pae_interaction,
        # AF2 initial-guess predicts no affinity. ``plddt_binder`` is a 0-100
        # confidence score, not a binding constant.
        affinity_pred_value=None,
        validator_name="af2_ig",
        # Cloned from git at a pinned SHA rather than pip-installed, so
        # there is no distribution to interrogate. The SHA is the better
        # record anyway: it is content-addressed, so a clone either yields
        # exactly that tree or fails, and request and receipt coincide.
        validator_version=f"dl_binder_design@{DL_BINDER_DESIGN_COMMIT}",
        notes="AF2 initial-guess (non-commercial weights)",
    )


def _to_float(v: object) -> float | None:
    if v is None:
        return None
    try:
        return float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


# Re-export the canonical Boltz YAML builder + JSON parser so there is exactly
# one of each in the codebase.
__all__ = [
    "binder_chain_from_backbone",
    "build_af2ig_cmd",
    "build_bindcraft_cmd",
    "build_boltz_cmd",
    "build_boltz_yaml",
    "build_boltzgen_cmd",
    "build_boltzgen_spec",
    "build_chai_cmd",
    "build_contig_str",
    "build_hotspot_str",
    "build_mpnn_cmd",
    "build_ranges_contig_str",
    "build_rfdiff_cmd",
    "chain_residues_from_pdb",
    "chain_sequence_from_pdb",
    "label_indices_for_residues",
    "mpnn_design_sequences",
    "parse_af2ig_output",
    "parse_boltz_output",
    "parse_chai_output",
    "parse_mpnn_fasta",
    "pdb_chain_ids",
]


def write_metrics_jsonl(metrics: list[dict[str, object]], path: Path) -> Path:
    """Write per-design metrics as JSONL (one ValidationResult-shaped row/line)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for m in metrics:
            f.write(json.dumps(m) + "\n")
    return path

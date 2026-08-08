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
from collections.abc import Sequence
from pathlib import Path

from bindsight.validate.boltz2 import build_boltz_yaml, parse_boltz_output
from bindsight.validate.protocol import ValidationResult

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
# IPD public weight mirror (see the RFdiffusion README). sha256 left None: the
# multi-GB checkpoints are verified on download in the executor when a hash is
# supplied, but we don't hard-pin one we couldn't compute offline.
RFDIFF_WEIGHTS: dict[str, str] = {
    "Base_ckpt.pt": "http://files.ipd.uw.edu/pub/RFdiffusion/6f5902ac237024bdd0c176cb93063dc4/Base_ckpt.pt",
    "Complex_base_ckpt.pt": "http://files.ipd.uw.edu/pub/RFdiffusion/e29311f6f1bf1af907f9ef9f44b8328b/Complex_base_ckpt.pt",
}

PROTEINMPNN_REPO = "https://github.com/dauparas/ProteinMPNN"
PROTEINMPNN_COMMIT = "8907e6671bfbfc92303b5f79c4b5e6ce47cdef57"

BOLTZ_PIP = "boltz>=2.0,<3.0"

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
def build_rfdiff_cmd(
    *,
    rfdiff_dir: Path,
    input_pdb: Path,
    output_prefix: Path,
    num_designs: int,
    hotspot: str,
    contig: str,
) -> list[str]:
    """RFdiffusion ``scripts/run_inference.py`` argv for binder backbone design."""
    return [
        _design_python(),
        str(Path(rfdiff_dir) / "scripts" / "run_inference.py"),
        f"inference.input_pdb={input_pdb}",
        f"inference.output_prefix={output_prefix}",
        f"inference.num_designs={num_designs}",
        f"ppi.hotspot_res={hotspot}",
        f"contigmap.contigs={contig}",
    ]


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
        str(seed),
    ]


def build_boltz_cmd(*, yaml_path: Path, out_dir: Path, use_msa_server: bool = True) -> list[str]:
    """Boltz-2 ``boltz predict`` argv for structure + affinity prediction."""
    cmd = [_boltz_bin(), "predict", str(yaml_path), "--out_dir", str(out_dir)]
    if use_msa_server:
        cmd.append("--use_msa_server")
    return cmd


def build_chai_cmd(*, fasta_path: Path, out_dir: Path) -> list[str]:
    """Chai-1 ``chai-lab fold`` argv (structure + confidence prediction)."""
    return ["chai-lab", "fold", str(fasta_path), str(out_dir)]


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


def build_boltzgen_cmd(
    *, target_pdb: Path, out_dir: Path, num_designs: int, hotspot: str
) -> list[str]:
    """BoltzGen ``boltzgen design`` argv (universal generative binder design)."""
    return [
        "boltzgen",
        "design",
        "--target",
        str(target_pdb),
        "--out_dir",
        str(out_dir),
        "--num_designs",
        str(num_designs),
        "--hotspots",
        hotspot,
    ]


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


def chain_sequence_from_pdb(pdb_path: Path, chain: str = "A") -> str:
    """Extract a chain's 1-letter sequence from a PDB (CA atoms, in order)."""
    return "".join(aa for _, aa in chain_residues_from_pdb(pdb_path, chain))


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
    npz = next(Path(output_dir).rglob("scores*.npz"), None)
    if npz is not None:
        try:
            import numpy as np

            data = np.load(npz)
            iptm = _to_float(data["iptm"]) if "iptm" in data else None
            ptm = _to_float(data["ptm"]) if "ptm" in data else None
        except Exception as e:  # pragma: no cover - depends on chai output shape
            LOG.warning("failed to parse chai npz %s: %s", npz, e)
    return ValidationResult(
        binder_id=binder_id,
        target_uniprot=target_uniprot,
        iptm=iptm,
        pae_interaction=None,
        affinity_pred_value=ptm,
        validator_name="chai1r",
        validator_version="0.6",
        notes=f"parsed chai scores={'yes' if npz else 'no'}",
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
        pae_interaction=pae_interaction,
        affinity_pred_value=plddt,
        validator_name="af2_ig",
        validator_version="1.0",
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
    "build_chai_cmd",
    "build_contig_str",
    "build_hotspot_str",
    "build_mpnn_cmd",
    "build_ranges_contig_str",
    "build_rfdiff_cmd",
    "chain_residues_from_pdb",
    "chain_sequence_from_pdb",
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

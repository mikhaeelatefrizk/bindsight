# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Headless design+validation executor — the real GPU work, runnable anywhere.

This module is what actually runs RFdiffusion → ProteinMPNN → Boltz-2 (and the
BindCraft / BoltzGen / Chai-1 / AF2-IG alternatives) end-to-end on a CUDA
machine. It is invoked identically by:

- the **local/Docker runner** (`python -m bindsight.runners.job_exec spec.json out.tar.gz`),
- the **Modal runner** (the same function, executed inside a GPU container), and
- the **Kaggle runner** (the same module, run inside a pushed kernel).

It reads a :class:`bindsight.design.protocol.DesignSpec` JSON plus the
co-located target structure, runs the chosen designer + validator as
subprocesses (commands from :mod:`bindsight.runners.tools` — one source of
truth shared with the Colab notebook), and writes a ``results.tar.gz`` laid out
so the local orchestrator consumes it directly:

    <work>/metrics.jsonl                         # one ValidationResult per line
    <work>/validate/<binder_id>/confidence_*.json + affinity_*.json
    <work>/design/<binder_id>.pdb + .fasta

No GPU libraries are imported at module load (torch/boltz live only inside the
subprocesses), so ``import bindsight`` stays clean on a CPU box. ``_run`` is the
single subprocess seam, monkeypatched in tests to exercise the dispatch + output
assembly without a GPU.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import tarfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bindsight.runners import tools

LOG = logging.getLogger(__name__)


@dataclass
class Design:
    """One designed binder: id, sequence, and backbone PDB path."""

    binder_id: str
    sequence: str
    pdb_path: Path


def _run(cmd: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    """Run a subprocess, capturing output; raise on non-zero exit.

    The single subprocess seam — monkeypatched in tests so the dispatch +
    output-assembly logic is exercised without a GPU.
    """
    LOG.info("exec: %s", " ".join(cmd))
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        LOG.error(
            "command failed (%d): %s\n%s", proc.returncode, " ".join(cmd), proc.stderr[-2000:]
        )
        raise RuntimeError(f"{cmd[0]} failed with code {proc.returncode}")
    return proc


# ---------------------------------------------------------------------------
# Tool setup (idempotent; no-ops when an image already ships the tools)
# ---------------------------------------------------------------------------
def _git_clone(repo: str, commit: str, dest: Path, *, submodules: bool = False) -> Path:
    """Clone ``repo`` at ``commit`` into ``dest``, optionally with submodules.

    ``submodules`` matters for dl_binder_design: its ``af2_initial_guess``
    predict.py imports ``silent_tools`` at module scope, and that is a git
    submodule. A plain clone leaves the directory empty, so the AF2
    initial-guess validator fails on import rather than at a legible point.
    """
    if dest.exists():
        return dest
    _run(["git", "clone", "--quiet", repo, str(dest)])
    _run(["git", "checkout", "--quiet", commit], cwd=dest)
    if submodules:
        _run(["git", "submodule", "update", "--init", "--recursive", "--quiet"], cwd=dest)
    return dest


def _verify_checkpoint(path: Path, expected_sha256: str | None) -> str:
    """Hash a downloaded checkpoint, log it, and fail on a pinned mismatch.

    Always hashing, rather than only when a pin exists, is what makes pinning
    possible at all: the first run publishes the digest into its own log, and
    that is where the pinned value comes from. Inventing one locally would
    certify whatever this machine downloaded.

    Args:
        path: the checkpoint on disk.
        expected_sha256: the pinned digest, or None if none is established.

    Returns:
        The hex digest of the file.

    Raises:
        RuntimeError: if a pinned digest is present and does not match.
    """
    import hashlib

    if not path.is_file():
        # wget exiting 0 without producing a file is a silent failure. Before
        # this check the run continued to RFdiffusion, which failed later with a
        # message about the model rather than about the download.
        raise RuntimeError(
            f"{path.name} is missing after the download step. The fetch reported "
            f"no error but produced no file at {path}. Re-run with network access, "
            "or place the checkpoint there yourself."
        )

    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    digest = h.hexdigest()
    size = path.stat().st_size
    LOG.info("checkpoint %s: %d bytes sha256=%s", path.name, size, digest)
    if expected_sha256 and digest != expected_sha256:
        raise RuntimeError(
            f"{path.name}: sha256 {digest} does not match the pinned "
            f"{expected_sha256}. Refusing to design against a checkpoint that is "
            "not the one this result claims. Delete the file and re-fetch; if the "
            "mismatch persists, upstream has republished and the pin needs review."
        )
    return digest


def _ensure_rfdiff_mpnn(tools_root: Path) -> tuple[Path, Path]:
    rfdiff_dir = tools_root / "RFdiffusion"
    fresh = not rfdiff_dir.exists()
    rfdiff = _git_clone(tools.RFDIFF_REPO, tools.RFDIFF_COMMIT, rfdiff_dir)
    weights = rfdiff / "models"
    weights.mkdir(parents=True, exist_ok=True)
    for name, url in tools.RFDIFF_WEIGHTS.items():
        dst = weights / name
        if not dst.exists():
            _run(["wget", "-q", url, "-O", str(dst)])
        _verify_checkpoint(dst, tools.RFDIFF_WEIGHT_SHA256.get(name))
    if fresh:
        # Install RFdiffusion's SE3-Transformer deps so the executor is
        # self-sufficient on a *bare* GPU (headless Kaggle / a fresh box), not
        # only inside the prebuilt Docker image. Mirrors the proven Colab
        # install cell; no-ops when the image already ships an installed tree.
        req = rfdiff / "env" / "SE3Transformer" / "requirements.txt"
        if req.exists():
            _run([sys.executable, "-m", "pip", "install", "-q", "-r", str(req)])
        _run([sys.executable, "-m", "pip", "install", "-q", "-e", str(rfdiff)])
    mpnn = _git_clone(tools.PROTEINMPNN_REPO, tools.PROTEINMPNN_COMMIT, tools_root / "ProteinMPNN")
    return rfdiff, mpnn


# ---------------------------------------------------------------------------
# Identity + target sequence (shared by every designer and validator)
# ---------------------------------------------------------------------------
def _binder_id_prefix(spec: dict[str, Any]) -> str:
    """Per-target namespace for binder ids.

    RFdiffusion writes every trajectory under a fixed ``binder_*`` prefix, so
    without a target namespace two different targets both produce
    ``binder_0_seq0``. That collides in ``validated.parquet`` and, worse, makes
    each target's ``validate/<binder_id>/`` overwrite the previous target's on
    disk. ``binder_id`` is the key the provenance chain is walked by, so it has
    to be unique across the whole run.
    """
    raw = str(spec.get("target_uniprot") or "").strip()
    safe = "".join(ch if (ch.isalnum() or ch in "-_") else "_" for ch in raw)
    return safe or "target"


def _target_sequence_for_design(spec: dict[str, Any], work: Path, chain: str) -> str:
    """The target sequence the designer actually saw: the kept ranges only.

    ``design_ranges`` carries the extracellular region discovery annotated from
    UniProt topology, and the designer is given only that. Validating against the
    full-length chain instead would score the binder against a surface it was
    never designed for, so every validator must use this same sequence.
    """
    target_pdb = work / "target.pdb"
    ranges = _target_ranges(spec, target_pdb, chain)
    return "".join(
        aa
        for resi, aa in tools.chain_residues_from_pdb(target_pdb, chain)
        if any(lo <= resi <= hi for lo, hi in ranges)
    )


# ---------------------------------------------------------------------------
# Designers
# ---------------------------------------------------------------------------
def _design_rfdiff_mpnn(spec: dict[str, Any], work: Path, tools_root: Path) -> list[Design]:
    rfdiff_dir, mpnn_dir = _ensure_rfdiff_mpnn(tools_root)
    target_pdb = work / "target.pdb"
    chain = spec.get("epitope_chain", "A")
    residues = [int(r) for r in spec.get("epitope_residues", [])]
    ranges = _target_ranges(spec, target_pdb, chain)
    # The sequence RFdiffusion is given — the kept segments only, which is what
    # the output backbone's target chain will carry, and what the validator
    # must later score against.
    target_seq = _target_sequence_for_design(spec, work, chain)

    rfdiff_out = work / "rfdiff_out"
    rfdiff_out.mkdir(parents=True, exist_ok=True)
    cmd = tools.build_rfdiff_cmd(
        rfdiff_dir=rfdiff_dir,
        input_pdb=target_pdb,
        output_prefix=rfdiff_out / "binder",
        num_designs=int(spec.get("n_trajectories", 5)),
        hotspot=tools.build_hotspot_str(chain, residues),
        contig=tools.build_ranges_contig_str(
            chain,
            ranges,
            int(spec.get("binder_length_min", 50)),
            int(spec.get("binder_length_max", 100)),
        ),
    )
    if not residues:
        # whole-target design: drop the empty ppi.hotspot_res token
        cmd = [a for a in cmd if not a.startswith("ppi.hotspot_res=")]
    _run(cmd, cwd=rfdiff_dir)

    designs: list[Design] = []
    design_dir = work / "design"
    design_dir.mkdir(parents=True, exist_ok=True)
    for backbone in sorted(rfdiff_out.glob("binder_*.pdb")):
        mpnn_out = work / "mpnn_out" / backbone.stem
        mpnn_out.mkdir(parents=True, exist_ok=True)
        # Design the binder chain only; the target is context ProteinMPNN must
        # not rewrite (its default is to design every chain).
        binder_chain = tools.binder_chain_from_backbone(backbone, target_sequence=target_seq)
        _run(
            tools.build_mpnn_cmd(
                mpnn_dir=mpnn_dir,
                pdb_path=backbone,
                out_folder=mpnn_out,
                designed_chains=[binder_chain],
                seed=int(spec.get("seed", 0)),
            )
        )
        fasta = next((mpnn_out / "seqs").glob("*.fa"), None)
        if fasta is None:
            continue
        seqs = tools.mpnn_design_sequences(fasta)
        for i, seq in enumerate(seqs):
            binder_id = f"{_binder_id_prefix(spec)}_{backbone.stem}_seq{i}"
            pdb_copy = design_dir / f"{binder_id}.pdb"
            pdb_copy.write_bytes(backbone.read_bytes())
            (design_dir / f"{binder_id}.fasta").write_text(f">{binder_id}\n{seq}\n")
            designs.append(Design(binder_id=binder_id, sequence=seq, pdb_path=pdb_copy))
    return designs


def _design_boltzgen(spec: dict[str, Any], work: Path, tools_root: Path) -> list[Design]:
    """Run BoltzGen against the target and collect its ranked designs.

    BoltzGen is driven by a design-specification YAML rather than command-line
    hotspot flags, and it resolves file references relative to that YAML, so the
    spec and the target structure are written into one directory together.
    """
    import yaml

    _git_clone(tools.BOLTZGEN_REPO, tools.BOLTZGEN_COMMIT, tools_root / "boltzgen")
    out = work / "boltzgen_out"
    out.mkdir(parents=True, exist_ok=True)
    chain = spec.get("epitope_chain", "A")
    residues = [int(r) for r in spec.get("epitope_residues", [])]

    spec_dir = work / "boltzgen_spec"
    spec_dir.mkdir(parents=True, exist_ok=True)
    target = _target_structure_for_design(spec, work, chain)
    staged_target = spec_dir / "target.pdb"
    staged_target.write_bytes(target.read_bytes())

    # BoltzGen indexes residues by their canonical 1-based position in the chain,
    # not by author numbering. Converting is the difference between binding the
    # intended epitope and binding an arbitrary stretch of the receptor.
    binding = tools.label_indices_for_residues(staged_target, chain, residues)
    if residues and not binding:
        LOG.warning(
            "none of the %d epitope residue(s) are present in the target chain; "
            "BoltzGen will design against the whole surface",
            len(residues),
        )

    extra = spec.get("extra_params", {}) or {}
    design_spec = spec_dir / "design_spec.yaml"
    design_spec.write_text(
        yaml.safe_dump(
            tools.build_boltzgen_spec(
                target_file=staged_target.name,
                target_chain=chain,
                binding_indices=binding,
                binder_length_min=int(spec.get("binder_length_min", 50)),
                binder_length_max=int(spec.get("binder_length_max", 100)),
            ),
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    n = int(spec.get("n_trajectories", 5))
    _run(
        tools.build_boltzgen_cmd(
            design_spec=design_spec,
            out_dir=out,
            num_designs=n,
            protocol=str(extra.get("boltzgen_protocol", "protein-anything")),
            # Triton kernels need compute capability 8.0 or newer. Every free-tier
            # GPU is older, and BoltzGen's "auto" default would try to enable them.
            use_kernels=str(extra.get("boltzgen_use_kernels", "auto")),
            budget=n,
            diffusion_batch_size=1 if n < 10 else None,
        )
    )
    return _collect_designs_from_dir(out, work, prefix="boltzgen", spec=spec)


def _design_bindcraft(spec: dict[str, Any], work: Path, tools_root: Path) -> list[Design]:
    bindcraft = _git_clone(tools.BINDCRAFT_REPO, tools.BINDCRAFT_COMMIT, tools_root / "BindCraft")
    out = work / "bindcraft_out"
    out.mkdir(parents=True, exist_ok=True)
    settings = work / "bindcraft_settings.json"
    settings.write_text(
        json.dumps(
            {
                "design_path": str(out),
                "binder_name": spec.get("target_uniprot", "binder"),
                "starting_pdb": str(
                    _target_structure_for_design(spec, work, spec.get("epitope_chain", "A"))
                ),
                "chains": spec.get("epitope_chain", "A"),
                "target_hotspot_residues": ",".join(
                    str(r) for r in spec.get("epitope_residues", [])
                ),
                "lengths": [
                    int(spec.get("binder_length_min", 50)),
                    int(spec.get("binder_length_max", 100)),
                ],
                "number_of_final_designs": int(spec.get("n_trajectories", 5)),
            }
        )
    )
    _run(
        tools.build_bindcraft_cmd(
            bindcraft_dir=bindcraft,
            settings_json=settings,
            filters_json=bindcraft / "settings_filters" / "default_filters.json",
            advanced_json=bindcraft / "settings_advanced" / "default_4stage_multimer.json",
        ),
        cwd=bindcraft,
    )
    return _collect_designs_from_dir(out, work, prefix="bindcraft", spec=spec)


_DESIGNERS = {
    "rfdiff_mpnn": _design_rfdiff_mpnn,
    "boltzgen": _design_boltzgen,
    "bindcraft": _design_bindcraft,
}


# ---------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------
def _validate_boltz2(
    spec: dict[str, Any], designs: list[Design], work: Path
) -> list[dict[str, Any]]:
    target_seq = _target_sequence_for_design(spec, work, spec.get("epitope_chain", "A"))
    boltz_root = work / "boltz_out"
    validate_root = work / "validate"
    metrics: list[dict[str, Any]] = []
    for d in designs:
        # predict_affinity=False: Boltz-2 affinity prediction is ligand-only
        # ("Chain B is not a ligand!"), and bindsight designs *protein* binders —
        # requesting it makes Boltz-2 skip the whole input. ipTM + PAE-interaction
        # from the protein–protein structure prediction are the binder-quality
        # metrics we want; affinity_pred_value stays None for protein binders.
        yaml_spec = tools.build_boltz_yaml(
            target_id="T",
            target_sequence=target_seq,
            binder_id=d.binder_id,
            binder_sequence=d.sequence,
            predict_affinity=False,
        )
        from bindsight.validate.boltz2 import write_boltz_yaml

        yaml_path = boltz_root / f"{d.binder_id}.yaml"
        write_boltz_yaml(yaml_spec, yaml_path)
        out_dir = boltz_root / d.binder_id
        proc = _run(tools.build_boltz_cmd(yaml_path=yaml_path, out_dir=out_dir))
        result = tools.parse_boltz_output(
            output_dir=out_dir,
            binder_id=d.binder_id,
            target_uniprot=str(spec.get("target_uniprot", "")),
        )
        # Fill PAE-interaction from the predicted PAE matrix (mean inter-chain PAE)
        # when Boltz's confidence JSON didn't carry it. Token order is target then
        # binder (per the YAML), so the chain lengths split the matrix.
        if result.pae_interaction is None:
            pae_i = _boltz_pae_interaction(
                out_dir, target_len=len(target_seq), binder_len=len(d.sequence)
            )
            if pae_i is not None:
                result = result.model_copy(update={"pae_interaction": pae_i})
        if result.iptm is None:
            # Boltz-2 exits 0 even when it *skips* a bad input, so surface its own
            # output here rather than recording a silent null.
            LOG.warning(
                "boltz2 produced no confidence for %s (no confidence_*.json under %s).\n"
                "boltz stdout tail:\n%s\nboltz stderr tail:\n%s",
                d.binder_id,
                out_dir,
                (proc.stdout or "")[-2000:],
                (proc.stderr or "")[-2000:],
            )
        _stage_validate_outputs(out_dir, validate_root / d.binder_id)
        metrics.append(result.model_dump())
    return metrics


def _boltz_pae_interaction(out_dir: Path, *, target_len: int, binder_len: int) -> float | None:
    """Mean inter-chain PAE (Å) from a Boltz-2 ``pae_*.npz``, or None if unavailable.

    The PAE matrix is over all residue tokens in chain order (target, then binder),
    so the off-diagonal blocks [target × binder] and [binder × target] are the
    interface PAE — lower means a more confident interface.
    """
    npz = next(Path(out_dir).rglob("pae_*.npz"), None)
    if npz is None:
        return None
    try:
        import numpy as np

        data = np.load(npz)
        pae = data["pae"] if "pae" in data.files else data[data.files[0]]
        n = target_len + binder_len
        if pae.ndim != 2 or pae.shape != (n, n):
            return None
        t = target_len
        inter = np.concatenate([pae[:t, t:].ravel(), pae[t:, :t].ravel()])
        return float(inter.mean()) if inter.size else None
    except Exception as e:  # malformed npz must not abort the job
        LOG.warning("failed to compute PAE-interaction from %s: %s", npz, e)
        return None


def _validate_chai1r(
    spec: dict[str, Any], designs: list[Design], work: Path
) -> list[dict[str, Any]]:
    target_seq = _target_sequence_for_design(spec, work, spec.get("epitope_chain", "A"))
    chai_root = work / "chai_out"
    metrics: list[dict[str, Any]] = []
    for d in designs:
        fasta = chai_root / f"{d.binder_id}.fasta"
        fasta.parent.mkdir(parents=True, exist_ok=True)
        fasta.write_text(f">protein|T\n{target_seq}\n>protein|{d.binder_id}\n{d.sequence}\n")
        out_dir = chai_root / d.binder_id
        _run(tools.build_chai_cmd(fasta_path=fasta, out_dir=out_dir))
        result = tools.parse_chai_output(
            out_dir, binder_id=d.binder_id, target_uniprot=str(spec.get("target_uniprot", ""))
        )
        metrics.append(result.model_dump())
    return metrics


def _validate_af2_ig(
    spec: dict[str, Any], designs: list[Design], work: Path
) -> list[dict[str, Any]]:
    tools_root = work / "_tools"
    dl = _git_clone(
        tools.DL_BINDER_DESIGN_REPO,
        tools.DL_BINDER_DESIGN_COMMIT,
        tools_root / "dl_binder_design",
        # predict.py does `from silent_tools import silent_tools` at import time,
        # and silent_tools is a submodule.
        submodules=True,
    )
    af2_root = work / "af2_out"
    metrics: list[dict[str, Any]] = []
    for d in designs:
        out_dir = af2_root / d.binder_id
        out_dir.mkdir(parents=True, exist_ok=True)
        _run(
            tools.build_af2ig_cmd(
                dl_binder_design_dir=dl, silent_or_pdb=d.pdb_path, out_dir=out_dir
            )
        )
        result = tools.parse_af2ig_output(
            out_dir / "af2_scores.sc",
            binder_id=d.binder_id,
            target_uniprot=str(spec.get("target_uniprot", "")),
        )
        metrics.append(result.model_dump())
    return metrics


_VALIDATORS = {
    "boltz2": _validate_boltz2,
    "chai1r": _validate_chai1r,
    "af2_ig": _validate_af2_ig,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _target_ranges(spec: dict[str, Any], target_pdb: Path, chain: str) -> list[tuple[int, int]]:
    """Target residue ranges to present to the designer, clipped to the structure.

    ``spec['design_ranges']`` carries the extracellular ranges discovery annotated
    from UniProt topology. Absent (or empty) means no topology was available, and
    the whole chain — transmembrane helix and cytoplasmic tail included — becomes
    the design surface; that is recorded loudly rather than assumed.

    Args:
        spec: The design spec dict.
        target_pdb: The materialised target structure.
        chain: The target chain id.

    Returns:
        Inclusive ``(lo, hi)`` ranges in the structure's numbering.

    Raises:
        ValueError: When ``design_ranges`` is given but overlaps no modelled residue.
    """
    lo, hi = _chain_span(target_pdb, chain)
    raw = spec.get("design_ranges") or []
    if not raw:
        LOG.warning(
            "no design_ranges in the spec: designing against the full length of chain %s "
            "(%d-%d), including any transmembrane and cytoplasmic regions",
            chain,
            lo,
            hi,
        )
        return [(lo, hi)]
    clipped = [
        (max(int(r[0]), lo), min(int(r[1]), hi)) for r in raw if int(r[0]) <= hi and int(r[1]) >= lo
    ]
    if not clipped:
        raise ValueError(
            f"design_ranges {[list(r) for r in raw]} do not overlap chain {chain} "
            f"residues {lo}-{hi} of {target_pdb}"
        )
    LOG.info(
        "designing against %d extracellular range(s) of chain %s: %s", len(clipped), chain, clipped
    )
    return clipped


def _target_structure_for_design(spec: dict[str, Any], work: Path, chain: str) -> Path:
    """Target structure trimmed to the spec's ``design_ranges``.

    The one-shot designers take a structure rather than a contig, so the ranges
    are applied by writing a trimmed copy. Returns ``target.pdb`` unchanged when
    the ranges already span the whole chain.
    """
    target_pdb = work / "target.pdb"
    ranges = _target_ranges(spec, target_pdb, chain)
    if ranges == [_chain_span(target_pdb, chain)]:
        return target_pdb
    kept: list[str] = []
    for line in target_pdb.read_text().splitlines():
        if line.startswith(("ATOM", "HETATM")) and line[21] == chain:
            try:
                resi = int(line[22:26])
            except ValueError:
                continue
            if not any(lo <= resi <= hi for lo, hi in ranges):
                continue
        kept.append(line)
    trimmed = work / "target_design_region.pdb"
    trimmed.write_text("\n".join(kept) + "\n")
    return trimmed


def _chain_span(pdb_path: Path, chain: str) -> tuple[int, int]:
    """Return (min, max) residue number for a chain in a PDB (default 1, 9999)."""
    nums: list[int] = []
    if pdb_path.exists():
        for line in pdb_path.read_text().splitlines():
            if line.startswith(("ATOM", "HETATM")) and line[21] == chain:
                try:
                    nums.append(int(line[22:26]))
                except ValueError:
                    continue
    return (min(nums), max(nums)) if nums else (1, 9999)


def load_existing_designs(work: Path) -> list[Design]:
    """Reconstruct designs from a staged ``<work>/design/`` directory.

    Validation-only jobs ship the designs a previous run produced rather than
    generating new ones, so a user can point a different validator at the same
    binders instead of paying to redesign them. Each design is a ``<id>.fasta``
    with its ``<id>.pdb`` backbone alongside; a FASTA with no backbone is
    skipped and named, because a validator that needs the structure would
    otherwise fail obscurely.
    """
    design_dir = work / "design"
    designs: list[Design] = []
    if not design_dir.is_dir():
        return designs
    for fasta in sorted(design_dir.glob("*.fasta")):
        binder_id = fasta.stem
        seq = "".join(ln.strip() for ln in fasta.read_text().splitlines() if not ln.startswith(">"))
        pdb = design_dir / f"{binder_id}.pdb"
        if not seq:
            LOG.warning("skipping %s: no sequence", fasta.name)
            continue
        if not pdb.exists():
            LOG.warning("skipping %s: no backbone PDB alongside it", fasta.name)
            continue
        designs.append(Design(binder_id=binder_id, sequence=seq, pdb_path=pdb))
    LOG.info("loaded %d existing design(s) from %s", len(designs), design_dir)
    return designs


def _collect_designs_from_dir(
    out: Path, work: Path, *, prefix: str, spec: dict[str, Any] | None = None
) -> list[Design]:
    """Collect (pdb + sequence) designs a one-shot designer wrote to ``out``.

    ``spec`` supplies the per-target namespace; see :func:`_binder_id_prefix`.
    """
    design_dir = work / "design"
    design_dir.mkdir(parents=True, exist_ok=True)
    target = _binder_id_prefix(spec or {})
    designs: list[Design] = []
    for i, structure in enumerate(_designer_output_structures(out)):
        binder_id = f"{target}_{prefix}_{i}"
        pdb_copy = design_dir / f"{binder_id}.pdb"
        if structure.suffix.lower() in {".cif", ".mmcif"}:
            # BoltzGen writes mmCIF; the rest of the pipeline expects PDB, so
            # normalise here rather than at every downstream reader.
            try:
                _cif_to_pdb(structure, pdb_copy)
            except Exception as e:
                LOG.warning("could not convert %s to PDB: %s", structure, e)
                continue
        else:
            pdb_copy.write_bytes(structure.read_bytes())
        seq = tools.chain_sequence_from_pdb(pdb_copy, _last_chain(pdb_copy))
        if not seq:
            LOG.warning("no chain sequence recovered from %s; skipping", structure)
            pdb_copy.unlink(missing_ok=True)
            continue
        (design_dir / f"{binder_id}.fasta").write_text(f">{binder_id}\n{seq}\n")
        designs.append(Design(binder_id=binder_id, sequence=seq, pdb_path=pdb_copy))
    return designs


def _designer_output_structures(out: Path) -> list[Path]:
    """Structures a one-shot designer produced, most-refined stage first.

    BoltzGen lays its output out in stages and only the last one is filtered
    and ranked, so globbing the whole output root would mix ranked final
    designs with unfiltered intermediates. The preference order below follows
    the upstream pipeline; anything unrecognised falls back to a plain
    recursive search so a different designer still collects.
    """
    preferred = (
        "final_ranked_designs",
        "intermediate_designs_inverse_folded/refold_design_cif",
        "intermediate_designs_inverse_folded",
        "intermediate_designs",
    )
    for rel in preferred:
        sub = out / Path(rel)
        if sub.is_dir():
            found = sorted(p for p in sub.rglob("*") if p.suffix.lower() in {".cif", ".pdb"})
            if found:
                return found
    return sorted(p for p in out.rglob("*") if p.suffix.lower() in {".cif", ".pdb"})


def _last_chain(pdb_path: Path) -> str:
    chains = [line[21] for line in pdb_path.read_text().splitlines() if line.startswith("ATOM")]
    return chains[-1] if chains else "A"


def _stage_validate_outputs(src_dir: Path, dst_dir: Path) -> None:
    """Copy Boltz outputs into <work>/validate/<binder_id>/ for the results tarball.

    Retains not just the confidence/affinity JSONs but the **predicted complex
    structure** (``*_model_0.cif``/``.pdb``) and the PAE / pLDDT arrays — the real,
    inspectable folded binder–target complex and its per-residue confidence. (The
    earlier version kept only the JSONs, so the structures were lost.)
    """
    dst_dir.mkdir(parents=True, exist_ok=True)
    patterns = (
        "confidence_*.json",
        "affinity_*.json",
        "*_model_0.cif",
        "*_model_0.pdb",
        "pae_*.npz",
        "plddt_*.npz",
    )
    for pattern in patterns:
        for path in src_dir.rglob(pattern):
            (dst_dir / path.name).write_bytes(path.read_bytes())


def _apply_prescreen(
    spec: dict[str, Any], designs: list[Design]
) -> tuple[list[Design], str | None]:
    """Screen designs before validation, if the spec asks for it.

    Args:
        spec: The design spec; ``extra_params['prescreen_top_k']`` opts in.
        designs: Designs produced by the designer, in design order.

    Returns:
        ``(designs_to_validate, note)`` where ``note`` is a provenance-ready
        summary, or ``None`` when no screen was requested.
    """
    raw = spec.get("extra_params", {}).get("prescreen_top_k")
    if raw in (None, "", 0, "0"):
        return designs, None
    try:
        top_k = int(raw)
    except (TypeError, ValueError):
        LOG.warning("ignoring non-integer prescreen_top_k=%r", raw)
        return designs, None

    from bindsight.design.prescreen import prescreen_report, select_representative

    result = select_representative([d.sequence for d in designs], top_k)
    note = prescreen_report(result, [d.binder_id for d in designs])
    LOG.info("%s", note)
    if not result.applied:
        return designs, note
    return [designs[i] for i in result.kept], note


def run_job(spec: dict[str, Any], work_dir: Path, *, tarball: Path | None = None) -> Path:
    """Run design + validation for one spec; write the results tarball.

    Args:
        spec: a ``DesignSpec.model_dump()`` dict (with the target structure
            materialised next to it, see :func:`materialise_target`).
        work_dir: scratch dir; outputs are assembled here then tarred.
        tarball: output ``.tar.gz`` path (default ``<work_dir>.tar.gz``).

    Returns:
        Path to the results tarball.
    """
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    # A pre-provisioned image/notebook can install the design tools once and
    # point here via BINDSIGHT_TOOLS_ROOT so we reuse them instead of re-cloning.
    tools_root = Path(os.environ.get("BINDSIGHT_TOOLS_ROOT") or (work_dir / "_tools"))

    designer = str(spec.get("extra_params", {}).get("designer") or "rfdiff_mpnn")
    validator = str(spec.get("extra_params", {}).get("validator") or "boltz2")
    mode = str(spec.get("extra_params", {}).get("mode") or "design_and_validate")
    if mode not in {"design_and_validate", "validate_only"}:
        raise ValueError(f"unknown mode: {mode}")
    if mode == "design_and_validate" and designer not in _DESIGNERS:
        raise ValueError(f"unknown designer: {designer}")
    if validator not in _VALIDATORS:
        raise ValueError(f"unknown validator: {validator}")

    LOG.info(
        "job: mode=%s designer=%s validator=%s target=%s",
        mode,
        designer if mode == "design_and_validate" else "-",
        validator,
        spec.get("target_uniprot"),
    )
    prescreen_note: str | None = None
    if mode == "validate_only":
        # Re-validating binders that already exist: no designer runs, so the
        # pre-screen is skipped too (it exists to cut GPU spend before
        # validation, and here the caller has explicitly chosen what to validate).
        designs = load_existing_designs(work_dir)
        if not designs:
            raise ValueError(
                f"validate_only: no staged designs under {work_dir / 'design'}; "
                "run `bindsight design` first, or ship the design directory with the spec"
            )
    else:
        designs = _DESIGNERS[designer](spec, work_dir, tools_root)
        LOG.info("designer produced %d designs", len(designs))

        # ESM-2 pre-screen, between design and validation — the only point where
        # dropping a design actually saves GPU time. Off unless prescreen_top_k is
        # set, and it keeps everything if the optional `embed` extra is absent.
        designs, prescreen_note = _apply_prescreen(spec, designs)

    metrics = _VALIDATORS[validator](spec, designs, work_dir)
    if prescreen_note:
        (work_dir / "prescreen.txt").write_text(prescreen_note + "\n", encoding="utf-8")

    tools.write_metrics_jsonl(metrics, work_dir / "metrics.jsonl")

    out_tar = Path(tarball) if tarball else work_dir.with_suffix(".tar.gz")
    out_tar.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(out_tar, "w:gz") as tf:
        for sub in ("design", "validate", "metrics.jsonl"):
            p = work_dir / sub
            if p.exists():
                tf.add(p, arcname=sub)
    LOG.info("wrote %s", out_tar)
    return out_tar


def materialise_target(spec: dict[str, Any], spec_dir: Path, work_dir: Path) -> None:
    """Copy the target structure referenced by the spec into ``work_dir/target.pdb``.

    The designer's ``submit`` writes the structure next to the spec JSON and
    records its filename in ``extra_params['target_structure_name']``; this
    reconstructs it on the remote/work side (the structure is never embedded in
    the spec).
    """
    name = spec.get("extra_params", {}).get("target_structure_name")
    src = (spec_dir / name) if name else Path(spec.get("target_structure_path", ""))
    work_dir.mkdir(parents=True, exist_ok=True)
    dst = work_dir / "target.pdb"
    if not src or not Path(src).exists():
        LOG.warning("target structure not found (%s); designer will fail without it", src)
        return
    src = Path(src)
    if src.suffix.lower() in {".cif", ".mmcif"}:
        _cif_to_pdb(src, dst)
    else:
        dst.write_bytes(src.read_bytes())


def materialise_designs(spec_dir: Path, work_dir: Path) -> int:
    """Copy a ``design/`` directory shipped next to the spec into ``work_dir``.

    Validation-only jobs carry the binders to validate alongside the spec, the
    same way ``materialise_target`` carries the receptor. Returns how many
    design files were staged.
    """
    src = Path(spec_dir) / "design"
    if not src.is_dir():
        return 0
    dst = Path(work_dir) / "design"
    dst.mkdir(parents=True, exist_ok=True)
    n = 0
    for f in sorted(src.iterdir()):
        if f.is_file():
            (dst / f.name).write_bytes(f.read_bytes())
            n += 1
    LOG.info("staged %d design file(s) from %s", n, src)
    return n


def _cif_to_pdb(cif_path: Path, pdb_path: Path) -> None:
    """Convert an mmCIF (e.g. AlphaFoldDB) to PDB; RFdiffusion needs PDB input."""
    from Bio.PDB import PDBIO, MMCIFParser  # lazy: biopython only on the GPU side

    parser = MMCIFParser(QUIET=True)
    structure = parser.get_structure("target", str(cif_path))
    io = PDBIO()
    io.set_structure(structure)
    io.save(str(pdb_path))


def main(argv: list[str] | None = None) -> int:
    """CLI entry: ``python -m bindsight.runners.job_exec <spec.json> <out.tar.gz>``."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) < 2:
        print("usage: job_exec <spec.json> <out.tar.gz>", file=sys.stderr)
        return 2
    spec_path, out_tar = Path(args[0]), Path(args[1])
    spec = json.loads(spec_path.read_text())
    work_dir = out_tar.parent / (out_tar.stem.replace(".tar", "") + "_work")
    materialise_target(spec, spec_path.parent, work_dir)
    materialise_designs(spec_path.parent, work_dir)
    run_job(spec, work_dir, tarball=out_tar)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

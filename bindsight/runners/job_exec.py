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
def _git_clone(repo: str, commit: str, dest: Path) -> Path:
    if dest.exists():
        return dest
    _run(["git", "clone", "--quiet", repo, str(dest)])
    _run(["git", "checkout", "--quiet", commit], cwd=dest)
    return dest


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
# Designers
# ---------------------------------------------------------------------------
def _design_rfdiff_mpnn(spec: dict[str, Any], work: Path, tools_root: Path) -> list[Design]:
    rfdiff_dir, mpnn_dir = _ensure_rfdiff_mpnn(tools_root)
    target_pdb = work / "target.pdb"
    chain = spec.get("epitope_chain", "A")
    residues = [int(r) for r in spec.get("epitope_residues", [])]
    lo, hi = _chain_span(target_pdb, chain)

    rfdiff_out = work / "rfdiff_out"
    rfdiff_out.mkdir(parents=True, exist_ok=True)
    cmd = tools.build_rfdiff_cmd(
        rfdiff_dir=rfdiff_dir,
        input_pdb=target_pdb,
        output_prefix=rfdiff_out / "binder",
        num_designs=int(spec.get("n_trajectories", 5)),
        hotspot=tools.build_hotspot_str(chain, residues),
        contig=tools.build_contig_str(
            chain,
            lo,
            hi,
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
        _run(
            tools.build_mpnn_cmd(
                mpnn_dir=mpnn_dir,
                pdb_path=backbone,
                out_folder=mpnn_out,
                seed=int(spec.get("seed", 0)),
            )
        )
        fasta = next((mpnn_out / "seqs").glob("*.fa"), None)
        if fasta is None:
            continue
        seqs = tools.mpnn_design_sequences(fasta)
        for i, seq in enumerate(seqs):
            binder_id = f"{backbone.stem}_seq{i}"
            pdb_copy = design_dir / f"{binder_id}.pdb"
            pdb_copy.write_bytes(backbone.read_bytes())
            (design_dir / f"{binder_id}.fasta").write_text(f">{binder_id}\n{seq}\n")
            designs.append(Design(binder_id=binder_id, sequence=seq, pdb_path=pdb_copy))
    return designs


def _design_boltzgen(spec: dict[str, Any], work: Path, tools_root: Path) -> list[Design]:
    _git_clone(tools.BOLTZGEN_REPO, tools.BOLTZGEN_COMMIT, tools_root / "boltzgen")
    out = work / "boltzgen_out"
    out.mkdir(parents=True, exist_ok=True)
    chain = spec.get("epitope_chain", "A")
    residues = [int(r) for r in spec.get("epitope_residues", [])]
    _run(
        tools.build_boltzgen_cmd(
            target_pdb=work / "target.pdb",
            out_dir=out,
            num_designs=int(spec.get("n_trajectories", 5)),
            hotspot=tools.build_hotspot_str(chain, residues),
        )
    )
    return _collect_designs_from_dir(out, work, prefix="boltzgen")


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
                "starting_pdb": str(work / "target.pdb"),
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
    return _collect_designs_from_dir(out, work, prefix="bindcraft")


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
    target_seq = tools.chain_sequence_from_pdb(work / "target.pdb", spec.get("epitope_chain", "A"))
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
    target_seq = tools.chain_sequence_from_pdb(work / "target.pdb", spec.get("epitope_chain", "A"))
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
        tools.DL_BINDER_DESIGN_REPO, tools.DL_BINDER_DESIGN_COMMIT, tools_root / "dl_binder_design"
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


def _collect_designs_from_dir(out: Path, work: Path, *, prefix: str) -> list[Design]:
    """Collect (pdb + sequence) designs a one-shot designer wrote to ``out``."""
    design_dir = work / "design"
    design_dir.mkdir(parents=True, exist_ok=True)
    designs: list[Design] = []
    for i, pdb in enumerate(sorted(out.rglob("*.pdb"))):
        binder_id = f"{prefix}_{i}"
        seq = tools.chain_sequence_from_pdb(pdb, _last_chain(pdb))
        pdb_copy = design_dir / f"{binder_id}.pdb"
        pdb_copy.write_bytes(pdb.read_bytes())
        (design_dir / f"{binder_id}.fasta").write_text(f">{binder_id}\n{seq}\n")
        designs.append(Design(binder_id=binder_id, sequence=seq, pdb_path=pdb_copy))
    return designs


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
    if designer not in _DESIGNERS:
        raise ValueError(f"unknown designer: {designer}")
    if validator not in _VALIDATORS:
        raise ValueError(f"unknown validator: {validator}")

    LOG.info(
        "job: designer=%s validator=%s target=%s", designer, validator, spec.get("target_uniprot")
    )
    designs = _DESIGNERS[designer](spec, work_dir, tools_root)
    LOG.info("designer produced %d designs", len(designs))
    metrics = _VALIDATORS[validator](spec, designs, work_dir)

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
    run_job(spec, work_dir, tarball=out_tar)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

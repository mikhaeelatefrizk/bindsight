# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shared designer plumbing: ship the spec+structure to a runner, stage results.

All designer plugins (RFdiffusion+ProteinMPNN, BindCraft, BoltzGen) submit the
same way — write the ``DesignSpec`` JSON and the target structure into one dir,
launch the chosen :class:`~bindsight.runners.protocol.GPURunner`, block on
``fetch``, then stage the tarball and extract ``metrics.jsonl``. The only
difference is which designer the remote executor dispatches to (recorded in
``extra_params['designer']``). This module is that shared body.
"""

from __future__ import annotations

import logging
import shutil
import tarfile
from pathlib import Path

from bindsight.design.protocol import DesignResult, DesignSpec
from bindsight.runners.protocol import GPURunner

LOG = logging.getLogger(__name__)


def submit_via_runner(
    spec: DesignSpec,
    runner: GPURunner,
    *,
    designer_name: str,
    designer_version: str,
    designer_commit_sha: str | None,
    cache_key: str,
    payload_dir: Path | None = None,
) -> DesignResult:
    """Ship spec + structure to ``runner``, block, stage results, return DesignResult.

    ``payload_dir`` is an optional local ``design/`` directory shipped alongside
    the spec. Validation-only jobs use it to send binders that already exist, so
    a different validator can be run against them without redesigning.
    """
    spec_dir = Path(f"_bindsight_spec_{cache_key[:8]}")
    spec_dir.mkdir(parents=True, exist_ok=True)
    if payload_dir is not None and Path(payload_dir).is_dir():
        shutil.copytree(payload_dir, spec_dir / "design", dirs_exist_ok=True)

    # Ship the target structure next to the spec (it is not embedded in the
    # spec). Record the filename in extra_params so the executor can find it.
    structure_src = Path(spec.target_structure_path)
    target_name = "target" + (structure_src.suffix or ".pdb")
    if structure_src.exists():
        shutil.copy2(structure_src, spec_dir / target_name)
    spec_to_send = spec.model_copy(
        update={"extra_params": {**spec.extra_params, "target_structure_name": target_name}}
    )
    spec_path = spec_dir / "spec.json"
    spec_path.write_text(spec_to_send.model_dump_json(indent=2))

    # Idempotency (ARCHITECTURE.md 4.4): a completed unit of work is identified
    # by its cache key, so a rerun with identical inputs must not pay for the GPU
    # again. The key was previously computed and then used only as a directory
    # name, so every rerun resubmitted. Check it before submitting, and record
    # the hit or miss so the manifest can show which units were reused.
    results_dir = Path("./runs/_design") / cache_key
    staged_archive = results_dir / "results.tar.gz"
    metrics_path = results_dir / "metrics.jsonl"
    cache_hit = staged_archive.exists() and staged_archive.stat().st_size > 0
    if cache_hit:
        LOG.info("cache hit for %s; skipping submit (%s)", cache_key[:8], staged_archive)
        shutil.rmtree(spec_dir, ignore_errors=True)
        if not metrics_path.exists():
            extract_member(staged_archive, "metrics.jsonl", metrics_path)
        return DesignResult(
            spec=spec,
            results_archive_path=str(staged_archive),
            metrics_jsonl_path=str(metrics_path),
            designer_name=designer_name,
            designer_version=designer_version,
            designer_commit_sha=designer_commit_sha,
            weights_sha256=None,
            cache_key=cache_key,
            cache_status="hit",
        )

    try:
        handle = runner.submit(spec_path, results_dir=Path("./runs/_design"))
        archive_path = runner.fetch(handle)
    finally:
        shutil.rmtree(spec_dir, ignore_errors=True)

    results_dir.mkdir(parents=True, exist_ok=True)
    if archive_path.resolve() != staged_archive.resolve():
        shutil.copy2(archive_path, staged_archive)
    extract_member(staged_archive, "metrics.jsonl", metrics_path)

    return DesignResult(
        spec=spec,
        results_archive_path=str(staged_archive),
        metrics_jsonl_path=str(metrics_path),
        designer_name=designer_name,
        designer_version=designer_version,
        designer_commit_sha=designer_commit_sha,
        weights_sha256=None,  # multi-GB checkpoints; verified on download
        cache_key=cache_key,
        cache_status="miss",
    )


def extract_member(tar_path: Path, member: str, dest: Path) -> None:
    """Extract a single named member from a .tar.gz to ``dest`` (best-effort)."""
    if not tar_path.exists():
        return
    try:
        with tarfile.open(tar_path, "r:gz") as tf:
            names = {Path(n).name: n for n in tf.getnames()}
            if member in names:
                src = tf.extractfile(names[member])
                if src is not None:
                    dest.write_bytes(src.read())
    except (tarfile.TarError, OSError) as e:
        LOG.warning("could not extract %s from %s: %s", member, tar_path, e)


def make_cache_key(spec: DesignSpec, *, extra: tuple[str, ...] = ()) -> str:
    """SHA-256 over the deterministic inputs to a design job.

    Covers the target (accession *and* structure content), the epitope, the
    design ranges, the binder length bounds, the trajectory count, the seed, and
    whatever the caller adds via ``extra`` (the designer's pinned commit and
    resolved parameters). Two jobs sharing a key are the same work.
    """
    import hashlib

    structure = Path(spec.target_structure_path)
    structure_digest = ""
    if structure.is_file():
        # A new AlphaFold model for the same accession is different work. Without
        # the content in the key, a rerun would reuse a result computed against
        # the superseded structure.
        structure_digest = hashlib.sha256(structure.read_bytes()).hexdigest()
    bits = "|".join(
        [
            spec.target_uniprot,
            structure_digest,
            spec.epitope_chain,
            ",".join(str(r) for r in sorted(spec.epitope_residues)),
            ",".join(f"{lo}-{hi}" for lo, hi in spec.design_ranges),
            str(spec.binder_length_min),
            str(spec.binder_length_max),
            str(spec.n_trajectories),
            str(spec.seed),
            *extra,
        ]
    )
    return hashlib.sha256(bits.encode()).hexdigest()

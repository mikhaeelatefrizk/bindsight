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
) -> DesignResult:
    """Ship spec + structure to ``runner``, block, stage results, return DesignResult."""
    spec_dir = Path(f"_bindsight_spec_{cache_key[:8]}")
    spec_dir.mkdir(parents=True, exist_ok=True)

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

    try:
        handle = runner.submit(spec_path, results_dir=Path("./runs/_design"))
        archive_path = runner.fetch(handle)
    finally:
        shutil.rmtree(spec_dir, ignore_errors=True)

    results_dir = Path("./runs/_design") / cache_key
    results_dir.mkdir(parents=True, exist_ok=True)
    staged_archive = results_dir / "results.tar.gz"
    if archive_path.resolve() != staged_archive.resolve():
        shutil.copy2(archive_path, staged_archive)
    metrics_path = results_dir / "metrics.jsonl"
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
    """SHA-256 over the deterministic inputs to a design job."""
    import hashlib

    bits = "|".join(
        [
            spec.target_uniprot,
            spec.epitope_chain,
            ",".join(str(r) for r in sorted(spec.epitope_residues)),
            str(spec.binder_length_min),
            str(spec.binder_length_max),
            str(spec.n_trajectories),
            str(spec.seed),
            *extra,
        ]
    )
    return hashlib.sha256(bits.encode()).hexdigest()

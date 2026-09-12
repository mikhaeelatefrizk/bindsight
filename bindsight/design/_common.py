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
from bindsight.runners.protocol import GPURunner, JobHandle

LOG = logging.getLogger(__name__)


def _code_identity(runner: object) -> str:
    """Identify the bindsight that will actually execute on the runner.

    A remote runner pip-installs bindsight before running anything, so the code
    that produces a result is not necessarily the code that submitted it. When
    the runner carries a working-tree wheel, that wheel's content hash is the
    exact answer. When it carries only a git ref, the honest answer is the ref
    name, which is weaker: a branch resolves to different commits over time.
    With neither, the local package version is the best available.

    Args:
        runner: the GPU runner about to receive the job.

    Returns:
        A short string identifying the code, for folding into the cache key.
    """
    import hashlib

    wheel = getattr(runner, "bindsight_wheel", None)
    if wheel is not None:
        try:
            digest = hashlib.sha256(Path(wheel).read_bytes()).hexdigest()[:16]
            return f"wheel:{digest}"
        except OSError:
            return f"wheel:{Path(wheel).name}"
    ref = getattr(runner, "bindsight_ref", None)
    if ref:
        return f"ref:{ref}"
    from bindsight import __version__

    return f"version:{__version__}"


def _with_backend(cache_key: str, backend: str, code: str = "") -> str:
    """Fold the backend, and the code that will run, into a cache key.

    Two runs that differ only in where they executed are not the same work: one
    may be synthetic. Mixing them is the difference between a real result and a
    mock's canned numbers wearing a real result's label.

    The same applies to which bindsight runs. A corrected designer benchmark was
    submitted against a branch whose fixes existed only locally, so the GPU
    pip-installed the default branch and produced pre-fix output. Had that run
    succeeded and been cached, a later run of the fixed code would have been
    handed the unfixed result under the same key.

    Args:
        cache_key: the spec-derived key.
        backend: the runner's name.
        code: identity of the bindsight that will execute, from
            :func:`_code_identity`. Empty reproduces the previous key exactly,
            which keeps existing cache entries addressable.

    Returns:
        The folded key.
    """
    import hashlib

    bits = f"{cache_key}|backend={backend}"
    if code:
        bits += f"|code={code}"
    return hashlib.sha256(bits.encode()).hexdigest()


def _with_payload(cache_key: str, payload_dir: Path) -> str:
    """Fold a shipped ``design/`` directory into a cache key.

    The spec-derived key covers what a *designer* would be told to produce. For
    a ``validate_only`` job nothing is produced: the binders travel in the
    payload, and the spec is identical no matter which ones. Two calibration
    sets — twenty scrambles, and the same twenty plus their originals — hashed
    to the same key against the same target, so the second would have been
    served the first's twenty rows and read as the answer to a question it never
    asked. That is the same failure the validator fold in :func:`make_cache_key`
    exists to prevent, one level further in.

    Both the relative path and the content of every shipped file are covered:
    renaming a binder changes which row is which downstream.

    Args:
        cache_key: the key so far.
        payload_dir: the local directory shipped as ``design/``.

    Returns:
        The folded key.
    """
    import hashlib

    digest = hashlib.sha256()
    for path in sorted(p for p in payload_dir.rglob("*") if p.is_file()):
        digest.update(path.relative_to(payload_dir).as_posix().encode())
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return hashlib.sha256(f"{cache_key}|payload={digest.hexdigest()}".encode()).hexdigest()


def _record_handle(handle_path: Path, handle: object) -> None:
    """Persist a launched job's handle, without ever failing the job to do it.

    Recording happens *after* the remote job is launched, which makes this the
    one place where raising would destroy exactly what it exists to protect: the
    run would abort with a kernel already consuming quota and no record of how
    to reach it. So every failure here is a warning. A runner whose handle
    cannot be serialised simply loses reattachability, which is where the tool
    stood before this existed.

    Args:
        handle_path: where to write the record.
        handle: the handle returned by ``runner.submit``.
    """
    try:
        handle_path.parent.mkdir(parents=True, exist_ok=True)
        dump = getattr(handle, "model_dump_json", None)
        if dump is None:
            LOG.warning(
                "runner returned a %s rather than a JobHandle, so this job cannot "
                "be reattached to if the client dies",
                type(handle).__name__,
            )
            return
        handle_path.write_text(dump(indent=2))
    except (OSError, TypeError, ValueError) as e:
        LOG.warning(
            "could not record the job handle at %s (%s); a crashed wait will not "
            "be able to reattach to this job",
            handle_path,
            e,
        )


def _recorded_handle(handle_path: Path, runner: GPURunner) -> JobHandle | None:
    """Return a still-live job recorded by an earlier client, if there is one.

    A remote job outlives the process that launched it. When the client dies
    mid-wait — a dropped connection, a closed laptop, a killed terminal — the
    kernel keeps running and keeps spending a fixed weekly GPU quota, but
    nothing is left that knows how to collect its output. Resubmitting is the
    obvious response and the wrong one: it pays for the same work twice and
    orphans the first job for good. This is the recovery path, and it is why
    :func:`submit_via_runner` records the handle before it starts waiting.

    A job that ended badly is not reattachable, so its record is cleared and the
    caller submits afresh. But a job whose state cannot be *determined* is
    reattached anyway: the cost of waiting on a job that turns out to be dead is
    one more poll, while the cost of resubmitting a job that is actually alive is
    hours of quota. :meth:`fetch` retries through transient failures, so the
    reattached wait recovers on its own once the network does.

    Args:
        handle_path: where the handle was recorded.
        runner: the runner to ask about the job's state.

    Returns:
        The handle to reattach to, or None if the caller should submit.
    """
    if not handle_path.is_file():
        return None
    try:
        handle = JobHandle.model_validate_json(handle_path.read_text())
    except (OSError, ValueError) as e:
        LOG.warning("ignoring unreadable job record %s (%s)", handle_path, e)
        return None
    try:
        state = runner.poll(handle).state
    except Exception as e:
        LOG.warning(
            "could not determine the state of recorded job %s (%s); reattaching "
            "rather than resubmitting, because a duplicate submission would "
            "spend GPU quota on work that may already be running.",
            handle.id,
            e,
        )
        return handle
    if state in {"queued", "running", "succeeded"}:
        LOG.info(
            "reattaching to %s job %s (state=%s) instead of resubmitting",
            handle.backend,
            handle.id,
            state,
        )
        return handle
    LOG.info("recorded job %s ended in state %s; submitting a new one", handle.id, state)
    handle_path.unlink(missing_ok=True)
    return None


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
    # The backend belongs in the key. Without it, a run on --backend mock and a
    # run on a real GPU share a cache entry, so a later real run silently returns
    # the mock's synthetic tarball and reports it as a genuine result. The
    # designer's commit is already folded in by the caller; the runner is not.
    cache_key = _with_backend(cache_key, getattr(runner, "name", "unknown"), _code_identity(runner))
    payload = Path(payload_dir) if payload_dir is not None else None
    if payload is not None and payload.is_dir():
        # Folded here rather than by the caller: this is the function the
        # payload is handed to, so keying it cannot be forgotten by whoever
        # ships one next. It must precede spec_dir, which is named after the key.
        cache_key = _with_payload(cache_key, payload)
    else:
        payload = None
    spec_dir = Path(f"_bindsight_spec_{cache_key[:8]}")
    spec_dir.mkdir(parents=True, exist_ok=True)
    if payload is not None:
        shutil.copytree(payload, spec_dir / "design", dirs_exist_ok=True)

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

    # Record the handle before waiting on it. A remote job outlives its client,
    # so without this a crashed wait leaves a running kernel that nothing can
    # collect, and the rerun pays for the same GPU hours again. See
    # :func:`_recorded_handle`.
    handle_path = results_dir / "handle.json"
    try:
        handle = _recorded_handle(handle_path, runner)
        if handle is None:
            handle = runner.submit(spec_path, results_dir=Path("./runs/_design"))
            _record_handle(handle_path, handle)
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


#: ``extra_params`` entries that change the result, and so belong in the key.
#:
#: Deliberately not the whole dict. ``target_structure_name`` is added *after*
#: the key is computed, so hashing everything would make the key depend on
#: bookkeeping rather than on the work. These are the entries the remote
#: executor actually acts on: which validator scores the designs, and whether an
#: ESM-2 prescreen drops some before they are scored at all.
#: ``extra_params`` keys that change what a job produces, and so belong in its key.
#:
#: ``diffusion_samples`` is here because it changes the reported number, not
#: just its precision: the validator averages over that many draws, so one draw
#: and five are different measurements of the same design. ``mode`` is here
#: because a validate-only job runs no designer at all.
_RESULT_AFFECTING_PARAMS = ("validator", "prescreen_top_k", "diffusion_samples", "mode")


def make_cache_key(spec: DesignSpec, *, extra: tuple[str, ...] = ()) -> str:
    """SHA-256 over the deterministic inputs to a design job.

    Covers the target (accession *and* structure content), the epitope, the
    design ranges, the binder length bounds, the trajectory count, the seed, the
    result-affecting ``extra_params``, and whatever the caller adds via ``extra``
    (the designer's pinned commit and resolved parameters). Two jobs sharing a
    key are the same work.

    The validator belongs here for the same reason the backend does. The remote
    executor runs whichever validator ``extra_params`` names, so without it a run
    validated by Boltz-2 and a run validated by Chai-1r shared a cache entry, and
    the second silently returned the first's numbers under the other validator's
    name — a wrong answer that looks entirely plausible.
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
            *(f"{k}={spec.extra_params.get(k)}" for k in _RESULT_AFFECTING_PARAMS),
            *extra,
        ]
    )
    return hashlib.sha256(bits.encode()).hexdigest()

# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Per-stage provenance fragments, shared by the Snakemake front-end.

The Snakemake rules run in separate processes, so they cannot append to a live
:class:`~bindsight.provenance.Manifest` the way the Click CLI does. Each rule
writes a fragment instead, and ``scripts/assemble_manifest.py`` stitches them
into the run manifest.

Those fragments used to carry only a stage name, a status and a metrics blob.
Every Snakemake manifest therefore had empty ``inputs``, empty ``outputs``, no
sha256 anywhere, no per-stage params, no real timings, and the same placeholder
tool for all six stages — while ``ARCHITECTURE.md`` claimed the CLI and
Snakemake front-ends produce identical artifacts, and
``assemble_manifest.py``'s own docstring claimed it emitted "the same populated
provenance artifact the Click CLI does". It did not.

This module closes that gap by making both front-ends build the *same*
:class:`~bindsight.provenance.StageRecord` objects out of the same helpers, so
a Snakemake run is as auditable as a CLI run.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from bindsight.provenance.manifest import (
    InputRef,
    OutputRef,
    StageRecord,
    ToolRef,
    _now_iso,
    sha256_file,
)

#: Media types for the artifact kinds the pipeline emits.
_MEDIA_TYPES = {
    ".parquet": "application/x-parquet",
    ".tsv": "text/tab-separated-values",
    ".gz": "application/gzip",
    ".jsonl": "application/x-ndjson",
    ".jsonld": "application/ld+json",
    ".json": "application/json",
    ".html": "text/html",
    ".cif": "chemical/x-mmcif",
    ".pdb": "chemical/x-pdb",
    ".yaml": "application/yaml",
}


def media_type_for(path: Path | str) -> str | None:
    """Best-effort IANA media type for a pipeline artifact."""
    return _MEDIA_TYPES.get(Path(path).suffix.lower())


def artifact_ref(
    path: Path | str,
    *,
    role: str,
    run_root: Path | str | None = None,
) -> dict[str, Any] | None:
    """Describe an artifact the way ``InputRef``/``OutputRef`` require.

    Args:
        path: The artifact on disk.
        role: Its logical role within the stage (e.g. ``"counts"``).
        run_root: When given, the recorded path is made relative to it, so the
            manifest describes the run rather than the machine.

    Returns:
        A dict carrying role, path, sha256, bytes and media type, or ``None``
        when the file does not exist.
    """
    p = Path(path)
    if not p.is_file():
        return None
    recorded = p
    if run_root is not None:
        try:
            recorded = p.resolve().relative_to(Path(run_root).resolve())
        except ValueError:
            # Outside the run (e.g. an input cohort); record it as given.
            recorded = p
    return {
        "role": role,
        "path": recorded.as_posix(),
        "sha256": sha256_file(p),
        "bytes": p.stat().st_size,
        "media_type": media_type_for(p),
    }


def write_fragment(
    path: Path | str,
    *,
    stage: str,
    status: str = "completed",
    tool: dict[str, Any] | None = None,
    inputs: list[dict[str, Any] | None] | None = None,
    outputs: list[dict[str, Any] | None] | None = None,
    params: dict[str, Any] | None = None,
    notes: str | None = None,
    started_at: str | None = None,
    error: str | None = None,
) -> Path:
    """Write one stage's provenance fragment.

    ``None`` entries in ``inputs``/``outputs`` are dropped, so callers can pass
    :func:`artifact_ref` results directly without guarding each one.

    Args:
        path: Fragment destination.
        stage: Stage name, matching the CLI's naming.
        status: Terminal status for the stage.
        tool: Serialised :class:`ToolRef`; defaults to bindsight itself.
        inputs: Artifact refs consumed.
        outputs: Artifact refs produced.
        params: The stage's resolved parameters.
        notes: Human-readable summary.
        started_at: ISO timestamp for the stage start; defaults to now.
        error: Failure detail, when ``status`` is ``"failed"``.

    Returns:
        The fragment path.
    """
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "stage": stage,
        "status": status,
        "tool": tool or default_tool(),
        "inputs": [r for r in (inputs or []) if r],
        "outputs": [r for r in (outputs or []) if r],
        "params": params or {},
        "notes": notes,
        "started_at": started_at or _now_iso(),
        "ended_at": _now_iso(),
        "error": error,
    }
    out.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return out


def default_tool(**overrides: Any) -> dict[str, Any]:
    """Serialised :class:`ToolRef` for bindsight itself."""
    from bindsight import __version__

    ref = {
        "name": "bindsight",
        "version": __version__,
        "license": "AGPL-3.0-or-later",
        "repo_url": "https://github.com/mikhaeelatefrizk/bindsight",
    }
    ref.update(overrides)
    return ref


def stage_record_from_fragment(payload: dict[str, Any]) -> StageRecord:
    """Rebuild a full :class:`StageRecord` from a fragment.

    Tolerates the older, thinner fragment shape (stage/status/metrics only) so
    a part-finished run from a previous version still assembles.

    Args:
        payload: Parsed fragment JSON.

    Returns:
        The reconstructed stage record.
    """
    name = str(payload.get("stage") or "unknown")
    status = str(payload.get("status") or "completed")
    if status not in {"running", "completed", "failed", "skipped_cache"}:
        status = "completed"

    tool_payload = payload.get("tool") or default_tool()
    notes = payload.get("notes")
    if notes is None and payload.get("metrics") is not None:
        # Legacy fragments carried their only real content here.
        notes = json.dumps({"metrics": payload["metrics"]})

    record = StageRecord(
        name=name,
        status=status,  # type: ignore[arg-type]
        tool=ToolRef(**tool_payload),
        inputs=[InputRef(**r) for r in payload.get("inputs") or []],
        outputs=[OutputRef(**r) for r in payload.get("outputs") or []],
        params=payload.get("params") or {},
        notes=notes,
        error=payload.get("error"),
    )
    if payload.get("started_at"):
        record.started_at = str(payload["started_at"])
    record.ended_at = str(payload["ended_at"]) if payload.get("ended_at") else _now_iso()
    return record

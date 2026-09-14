# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Append a stage to a run's manifest, from wherever that stage ran.

The provenance chain is the project's central claim: a reader should be able to
walk from a designed binder back to the patient samples it came from. That only
works if every stage records itself.

Until now only ``bindsight run`` did. The individual subcommands — the ones the
README Quickstart tells you to use — left the manifest stopped at ``discover``,
so following the documented path produced a run whose chain broke at the point
the interesting half begins. The stage-building logic already existed inside
``pipelines/full_run.py``; it was simply unreachable from the CLI.

This module is the seam. Each subcommand builds its own ``StageRecord`` and calls
:func:`append_stage`, which reads the manifest already on disk, adds the record,
and rewrites it. Appending is idempotent by stage name: re-running a stage
replaces its record rather than accumulating duplicates, so a run that was
validated twice does not claim to have two validation stages.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from bindsight.provenance.manifest import (
    InputRef,
    Manifest,
    OutputRef,
    StageRecord,
    ToolRef,
    sha256_file,
)

LOG = logging.getLogger(__name__)

#: ``record`` is the entry point every caller uses (the CLI imports this
#: module as ``provenance`` and calls it five times); it was absent from
#: ``__all__`` while four helpers nothing outside this module calls were in it.
__all__ = [
    "MANIFEST_NAME",
    "append_stage",
    "input_ref",
    "output_ref",
    "record",
    "stage_tool",
]

#: The manifest filename inside a run directory.
MANIFEST_NAME = "run_manifest.jsonld"


def stage_tool(name: str, version: str | None = None) -> ToolRef:
    """A ToolRef for a bindsight stage, versioned by the package."""
    from bindsight import __version__

    return ToolRef(
        name=name,
        version=version or __version__,
        license="AGPL-3.0-or-later",
        repo_url="https://github.com/mikhaeelatefrizk/bindsight",
    )


def output_ref(role: str, path: Path, *, run_dir: Path | str | None = None) -> OutputRef | None:
    """An OutputRef for a file that exists, or ``None``.

    Returning ``None`` for an absent file keeps a manifest from asserting an
    artifact that was never written, which is the same class of error as
    reporting a lookup that never ran.

    ``path`` is recorded relative to ``run_dir`` in POSIX form, because that is
    what :class:`OutputRef` says it is: "Path relative to the run root". It used
    to store ``str(path)`` unchanged, which produced repository-relative paths in
    the launching platform's separator style -- ``runs\\join\\deg\\results.parquet``
    on Windows. A manifest read on another machine then described a layout that
    machine does not have, and the field's own description was false.
    """
    path = Path(path)
    if not path.is_file():
        return None
    from bindsight.provenance.fragments import media_type_for

    recorded = path
    if run_dir is not None:
        try:
            recorded = path.resolve().relative_to(Path(run_dir).resolve())
        except ValueError:
            # Outside the run directory (a carried-in cohort, say). Keep the path
            # as given rather than inventing a relationship that does not hold.
            recorded = path
    return OutputRef(
        role=role,
        path=recorded.as_posix(),
        sha256=sha256_file(path),
        bytes=path.stat().st_size,
        media_type=media_type_for(path),
    )


def append_stage(run_dir: Path | str, stage: StageRecord) -> Path | None:
    """Add ``stage`` to the run's manifest, replacing any record of the same name.

    Args:
        run_dir: the run directory holding ``run_manifest.jsonld``.
        stage: the record to add.

    Returns:
        The manifest path, or ``None`` if there is no manifest to append to —
        which happens when a stage is run against a directory ``discover`` never
        produced. That is logged rather than raised, because failing a completed
        design job over its bookkeeping would be worse than the missing record.
    """
    run_dir = Path(run_dir)
    path = run_dir / MANIFEST_NAME
    if not path.is_file():
        LOG.warning(
            "no %s in %s; the %s stage ran but could not be recorded. Run "
            "`bindsight discover` first so the chain has a root.",
            MANIFEST_NAME,
            run_dir,
            stage.name,
        )
        return None
    try:
        manifest = Manifest.read(path)
    except Exception as e:  # a damaged manifest must not lose completed work
        LOG.warning("could not read %s (%s); leaving it untouched", path, e)
        return None

    # Replace rather than accumulate: re-running validate must not make the run
    # claim two validation stages.
    manifest.stages = [s for s in manifest.stages if s.name != stage.name]
    manifest.append(stage)
    manifest.write(path)
    LOG.info("recorded stage %r in %s", stage.name, path)
    return path


def record(
    run_dir: Path | str,
    *,
    name: str,
    tool: str,
    outputs: dict[str, Path],
    inputs: dict[str, Path] | None = None,
    params: dict[str, Any] | None = None,
    notes: str | None = None,
) -> Path | None:
    """Build and append a completed stage record in one call.

    Outputs that do not exist on disk are omitted rather than asserted, and so
    are inputs: a manifest must not claim to have consumed a file that is not
    there.

    ``inputs`` exists because it did not. Every stage the CLI recorded through
    this helper carried an empty ``prov:used``, so the provenance graph had no
    edge from a stage to the artifacts it read -- and a graph whose whole purpose
    is "show me what produced this" cannot answer that with no incoming edges.
    """
    stage = StageRecord(name=name, tool=stage_tool(tool), params=params or {})
    stage.notes = notes
    stage.inputs = [
        ref
        for role, path in (inputs or {}).items()
        if (ref := input_ref(role, path, run_dir=run_dir)) is not None
    ]
    refs = [
        ref
        for role, path in outputs.items()
        if (ref := output_ref(role, path, run_dir=run_dir)) is not None
    ]
    stage.mark_completed(outputs=refs)
    return append_stage(run_dir, stage)


def input_ref(role: str, path: Path, *, run_dir: Path | str | None = None) -> InputRef | None:
    """An InputRef for a file that exists, or ``None``.

    The mirror of :func:`output_ref`, and recorded the same way, so the two sides
    of the provenance graph describe paths identically.
    """
    path = Path(path)
    if not path.is_file():
        return None
    recorded = path
    if run_dir is not None:
        try:
            recorded = path.resolve().relative_to(Path(run_dir).resolve())
        except ValueError:
            recorded = path
    return InputRef(
        role=role,
        path=recorded.as_posix(),
        sha256=sha256_file(path),
        bytes=path.stat().st_size,
    )

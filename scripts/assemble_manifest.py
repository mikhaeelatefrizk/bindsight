# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Snakemake script: stitch per-rule manifest fragments into run_manifest.jsonld.

Each pipeline rule writes a small ``manifest_fragment.jsonld`` summary
(``{"stage", "status", "metrics"}``) next to its outputs. This script folds
every fragment into a :class:`bindsight.provenance.StageRecord` and writes the
assembled :class:`bindsight.provenance.Manifest` to the run root, so the
Snakemake front-end emits the same populated provenance artifact the Click CLI
does (``bindsight.pipelines`` builds an equivalent manifest).

The :func:`assemble` helper is pure (no Snakemake globals) so it is unit-tested
directly; :func:`main` is the thin Snakemake entrypoint.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any, Literal, cast

from bindsight import __version__ as BINDSIGHT_VERSION
from bindsight.provenance import Manifest, StageRecord, ToolRef, new_manifest

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
LOG = logging.getLogger("bindsight.assemble_manifest")

# StageRecord.status is a Literal; fall back to "completed" for anything else.
_Status = Literal["running", "completed", "failed", "skipped_cache"]
_VALID_STATUS: frozenset[str] = frozenset({"running", "completed", "failed", "skipped_cache"})


def _fragment_to_stage(fragment: dict[str, Any], *, fallback_name: str) -> StageRecord:
    """Fold one per-rule fragment dict into a :class:`StageRecord`.

    The fragment carries ``stage``/``status``/``metrics``; ``stage`` defaults to
    the fragment's parent directory name and metrics are preserved verbatim in
    ``StageRecord.notes`` (the record schema has no metrics field of its own).
    """
    name = str(fragment.get("stage") or fallback_name)
    raw_status = str(fragment.get("status", "completed"))
    status: _Status = cast(_Status, raw_status if raw_status in _VALID_STATUS else "completed")
    metrics = fragment.get("metrics")
    notes = json.dumps({"metrics": metrics}, sort_keys=True) if metrics is not None else None
    return StageRecord(
        name=name,
        status=status,
        tool=ToolRef(name="bindsight", version=BINDSIGHT_VERSION, license="AGPL-3.0-or-later"),
        notes=notes,
    )


def assemble(fragments: list[Path], *, name: str = "snakemake-run") -> Manifest:
    """Build a :class:`Manifest` from per-rule fragment files.

    Empty, missing, or malformed fragments are skipped (and logged), so a
    partial run still yields a valid manifest of the stages that did complete.
    """
    manifest = new_manifest(name=name)
    for frag in fragments:
        if not frag.exists() or frag.stat().st_size == 0:
            LOG.info("skipping empty/missing fragment: %s", frag)
            continue
        try:
            payload = json.loads(frag.read_text())
        except json.JSONDecodeError as e:
            LOG.warning("malformed fragment %s: %s", frag, e)
            continue
        if not isinstance(payload, dict):
            LOG.warning("unexpected fragment shape %s: %r", frag, payload)
            continue
        stage = _fragment_to_stage(payload, fallback_name=frag.parent.name)
        manifest.append(stage)
        LOG.info("folded fragment %s -> stage '%s' (%s)", frag, stage.name, stage.status)
    return manifest


def main() -> int:
    """Snakemake entrypoint: read the injected ``snakemake`` global and write the manifest."""
    smk = globals()["snakemake"]  # injected by Snakemake at runtime
    fragments = [Path(p) for p in smk.input.fragments]
    out = Path(smk.output.manifest)

    manifest = assemble(fragments)
    out.parent.mkdir(parents=True, exist_ok=True)
    manifest.write(out)
    LOG.info("wrote manifest: %s (%d stages)", out, len(manifest.stages))
    return 0


if __name__ == "__main__":
    sys.exit(main())

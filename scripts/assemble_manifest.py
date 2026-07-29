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

# NOTE: no `from __future__ import annotations` here. Snakemake prepends its
# own preamble to script files before executing them, which pushes a
# __future__ import off line 1 and makes Python raise
# "SyntaxError: from __future__ imports must occur at the beginning of the
# file". This rule had never run because of it. Python 3.11 is the floor, so
# builtin generics and X | None work without it.

import json
import logging
import sys
from pathlib import Path
from typing import Any

from bindsight.provenance import Manifest, StageRecord, new_manifest
from bindsight.provenance.fragments import stage_record_from_fragment

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
LOG = logging.getLogger("bindsight.assemble_manifest")


def _fragment_to_stage(fragment: dict[str, Any], *, fallback_name: str) -> StageRecord:
    """Fold one per-rule fragment dict into a :class:`StageRecord`.

    Rebuilding goes through :mod:`bindsight.provenance.fragments`, which is the
    same code the rules write with, so the Snakemake manifest now carries the
    inputs, outputs, sha256 digests, params and timings that make it a real
    provenance record. It previously carried a stage name, a status, and a
    metrics blob stuffed into ``notes`` — no digests at all — while claiming to
    emit what the Click CLI does.

    Older, thinner fragments still assemble, so a run left part-finished by a
    previous version does not become unreadable.
    """
    payload = dict(fragment)
    payload.setdefault("stage", fallback_name)
    return stage_record_from_fragment(payload)


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

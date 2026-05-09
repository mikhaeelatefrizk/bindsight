"""Snakemake script: stitch per-rule manifest fragments into run_manifest.jsonld.

Reads each ``manifest_fragment.jsonld`` written by an earlier rule, builds a
single :class:`xpr2bind.provenance.Manifest`, and writes it to the run root.

v0.0.x: minimal placeholder — full assembly logic lands in v0.0.2 once the
discovery half emits real fragments.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

from xpr2bind.provenance import new_manifest

snakemake = snakemake  # type: ignore[name-defined]  # noqa: F821

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
LOG = logging.getLogger("xpr2bind.assemble_manifest")


def main() -> int:
    fragments = [Path(p) for p in snakemake.input.fragments]
    out = Path(snakemake.output.manifest)

    manifest = new_manifest(name="snakemake-run")
    for frag in fragments:
        if not frag.exists() or frag.stat().st_size == 0:
            LOG.info("skipping empty/missing fragment: %s", frag)
            continue
        # In v0.0.x fragments are placeholder JSON; in v0.0.2 they will be
        # full StageRecord dicts and we'll deserialize + append.
        try:
            payload = json.loads(frag.read_text())
            LOG.info("read fragment: %s -> %s", frag, payload)
        except json.JSONDecodeError as e:
            LOG.warning("malformed fragment %s: %s", frag, e)

    manifest.write(out)
    LOG.info("wrote manifest: %s", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())

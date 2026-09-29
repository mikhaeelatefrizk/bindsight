# SPDX-License-Identifier: AGPL-3.0-or-later
"""Content and execution identities for trustworthy differential-expression reuse."""

from __future__ import annotations

import json
import os
import platform
from pathlib import Path
from typing import Any

from bindsight.provenance import sha256_file
from bindsight.provenance.manifest import SCIENTIFIC_STACK

_PACKAGE_ROOT = Path(__file__).resolve().parents[1]
_DEG_SOURCES = (
    "config.py",
    "deg/cache.py",
    "deg/diagnostics.py",
    "deg/inference.py",
    "deg/pydeseq2_runner.py",
    "pipelines/discover.py",
)


def execution_identity() -> dict[str, Any]:
    """Identify the numerical code and installed stack without embedding host paths.

    GPU tools and structure parsers do not produce the DEG table. The remaining
    scientific stack, plus the inference library's parallel/statistical helpers,
    does. File content hashes work for source checkouts and ordinary wheels and
    invalidate repaired adapters even when the package version stays unchanged.
    """
    from bindsight.validate.protocol import installed_version

    distributions = (set(SCIENTIFIC_STACK) - {"biopython", "torch", "transformers"}) | {
        "joblib",
        "statsmodels",
    }
    return {
        "schema_version": 1,
        "source_sha256": {name: sha256_file(_PACKAGE_ROOT / name) for name in _DEG_SOURCES},
        "libraries": {name: installed_version(name) for name in sorted(distributions)},
        "python": platform.python_version(),
        "platform": {"system": platform.system(), "machine": platform.machine()},
        "numeric_thread_environment": {
            name: os.environ.get(name)
            for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")
        },
    }


def verified_cached_digest(table: Path, cache_key: str) -> str | None:
    """Accept only a versioned cache record whose recorded output bytes still match.

    Historical plain key files lack an output checksum and conservatively miss.
    A nonempty but edited/truncated table must never be re-attributed as a new
    successful fit merely because its input key still matches.
    """
    try:
        metadata = json.loads(table.with_suffix(".cache_key").read_text(encoding="utf-8"))
        if (
            not isinstance(metadata, dict)
            or metadata.get("schema_version") != 2
            or metadata.get("cache_key") != cache_key
            or table.stat().st_size <= 0
            or metadata.get("output_bytes") != table.stat().st_size
        ):
            return None
        digest = sha256_file(table)
        return digest if metadata.get("output_sha256") == digest else None
    except (OSError, ValueError):
        return None


def write_cache_record(table: Path, cache_key: str) -> None:
    """Atomically attest a completed table only after its output bytes exist."""
    path = table.with_suffix(".cache_key")
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "cache_key": cache_key,
                "output_sha256": sha256_file(table),
                "output_bytes": table.stat().st_size,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(path)

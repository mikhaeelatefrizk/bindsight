"""Pydantic v2 schema for ``run_manifest.jsonld`` — the xpr2bind provenance contract.

Every pipeline stage emits a :class:`StageRecord` and appends it to the
:class:`Manifest`. The manifest serializes as PROV-O JSON-LD so that downstream
RO-Crate packaging and external provenance tooling can consume it natively.

The shape and semantics here are stable; bump :data:`MANIFEST_SCHEMA_VERSION`
when changing them.
"""

from __future__ import annotations

import hashlib
import json
import platform
import sys
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Bumped when the schema changes in a backwards-incompatible way.
MANIFEST_SCHEMA_VERSION = "1.0.0"

# PROV-O context. The manifest is valid JSON-LD against the W3C PROV ontology.
PROV_CONTEXT = {
    "@vocab": "http://www.w3.org/ns/prov#",
    "xpr2bind": "https://github.com/mikhaeelatefrizk/xpr2bind/ns#",
    "schema": "http://schema.org/",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def sha256_file(path: Path | str, *, chunk_size: int = 1 << 20) -> str:
    """Compute the lowercase hex SHA-256 of a file.

    Streams the file in ``chunk_size`` byte chunks to bound memory use on
    large structure or counts files.
    """
    digest = hashlib.sha256()
    p = Path(path)
    with p.open("rb") as fh:
        while chunk := fh.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def _now_iso() -> str:
    """ISO-8601 UTC timestamp suitable for JSON-LD ``xsd:dateTime``."""
    return datetime.now(UTC).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Component models
# ---------------------------------------------------------------------------
class ToolRef(BaseModel):
    """A pinned reference to an external tool a stage depends on."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(..., description="Canonical tool name (e.g. 'pydeseq2', 'rfdiffusion').")
    version: str = Field(..., description="Tool version string as reported by the tool itself.")
    license: str = Field(..., description="SPDX identifier or short license name.")
    repo_url: str | None = Field(None, description="Upstream source repository URL.")
    commit_sha: str | None = Field(
        None, description="Pinned commit SHA when relying on a specific tree."
    )
    weights_sha256: str | None = Field(
        None,
        description="SHA-256 of the model weights file (for ML components — required for "
        "reproducibility of stochastic outputs).",
    )
    citation: str | None = Field(
        None, description="DOI or BibTeX key. Aggregated into ``software.bib`` at export time."
    )


class ContainerRef(BaseModel):
    """A pinned container image used to execute a stage."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    image: str = Field(..., description="Image name (e.g. 'ghcr.io/mikhaeelatefrizk/xpr2bind').")
    tag: str | None = Field(None, description="Tag at submission time (informational only).")
    digest: str = Field(
        ...,
        description="Immutable digest, e.g. 'sha256:abc123…'. Required — tags are mutable.",
        pattern=r"^sha256:[0-9a-f]{64}$",
    )
    runtime: Literal["docker", "apptainer", "podman", "none"] = "docker"


class InputRef(BaseModel):
    """A pinned reference to a single input artifact consumed by a stage."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    role: str = Field(..., description="Logical role within the stage (e.g. 'counts', 'design').")
    path: str = Field(..., description="Path relative to the run root.")
    sha256: str = Field(..., min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    bytes: int = Field(..., ge=0)
    media_type: str | None = Field(
        None,
        description="IANA media type (e.g. 'text/tab-separated-values', "
        "'application/x-parquet', 'chemical/x-mmcif').",
    )


class OutputRef(BaseModel):
    """A pinned reference to a single output artifact produced by a stage."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    role: str = Field(..., description="Logical role within the stage (e.g. 'targets').")
    path: str = Field(..., description="Path relative to the run root.")
    sha256: str = Field(..., min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    bytes: int = Field(..., ge=0)
    media_type: str | None = None


class StageRecord(BaseModel):
    """One stage of the pipeline.

    Stages are appended to :attr:`Manifest.stages` in execution order. A stage
    with the same ``cache_key`` as an earlier stage (across runs) MAY be
    skipped if its outputs already exist on disk and validate against the
    recorded sha256.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., description="Stage name (e.g. 'deg', 'discover', 'design').")
    started_at: str = Field(default_factory=_now_iso)
    ended_at: str | None = None
    status: Literal["running", "completed", "failed", "skipped_cache"] = "running"

    tool: ToolRef
    container: ContainerRef | None = None
    inputs: list[InputRef] = Field(default_factory=list)
    outputs: list[OutputRef] = Field(default_factory=list)
    params: dict[str, Any] = Field(default_factory=dict)

    cache_key: str | None = Field(
        None,
        description="SHA-256 over (input shas + tool + container + params) for idempotent reruns.",
    )
    notes: str | None = None
    error: str | None = Field(None, description="Stack trace or error string if status='failed'.")

    @field_validator("status")
    @classmethod
    def _check_terminal_status(cls, v: str) -> str:
        # Allow all defined statuses; this validator is a hook for future rules.
        return v

    def mark_completed(
        self,
        *,
        outputs: Iterable[OutputRef] = (),
    ) -> None:
        """Mark this stage as completed and stamp the end time."""
        self.outputs.extend(outputs)
        self.status = "completed"
        self.ended_at = _now_iso()

    def mark_failed(self, error: str) -> None:
        """Mark this stage as failed with an error message."""
        self.status = "failed"
        self.ended_at = _now_iso()
        self.error = error


class RuntimeRef(BaseModel):
    """Capture of the local runtime environment.

    Recorded once per run. Includes Python version, platform, key library
    versions. Reproducibility requires matching the container digest, not just
    this — but this is useful triage when a container can't be rebuilt.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    python: str
    platform: str
    machine: str
    xpr2bind_version: str


class Manifest(BaseModel):
    """Top-level pipeline manifest. Serializes to ``run_manifest.jsonld``."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = MANIFEST_SCHEMA_VERSION
    run_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    created_at: str = Field(default_factory=_now_iso)
    name: str | None = Field(None, description="Optional human label for the run.")
    config_path: str | None = Field(
        None, description="Path to the pipeline config YAML used to launch this run."
    )

    runtime: RuntimeRef
    stages: list[StageRecord] = Field(default_factory=list)

    def jsonld(self) -> dict[str, Any]:
        """Return the manifest as a JSON-LD dict with the PROV-O context."""
        body = self.model_dump(mode="json")
        return {"@context": PROV_CONTEXT, **body}

    def write(self, path: Path | str) -> Path:
        """Atomically write the manifest as JSON-LD to ``path``.

        Writes to ``path + '.tmp'`` first, then replaces, so an interrupted
        write never leaves a half-written manifest behind.
        """
        p = Path(path)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(json.dumps(self.jsonld(), indent=2, sort_keys=False))
        tmp.replace(p)
        return p

    @classmethod
    def read(cls, path: Path | str) -> Manifest:
        """Load a manifest from disk, stripping the JSON-LD ``@context``."""
        raw = json.loads(Path(path).read_text())
        raw.pop("@context", None)
        return cls.model_validate(raw)

    def append(self, stage: StageRecord) -> None:
        """Append a stage record to this manifest."""
        self.stages.append(stage)


# ---------------------------------------------------------------------------
# Constructors
# ---------------------------------------------------------------------------
def _capture_runtime() -> RuntimeRef:
    from xpr2bind import __version__ as xpr_version

    return RuntimeRef(
        python=sys.version.split()[0],
        platform=platform.platform(),
        machine=platform.machine(),
        xpr2bind_version=xpr_version,
    )


def new_manifest(
    *,
    name: str | None = None,
    config_path: str | Path | None = None,
) -> Manifest:
    """Create a fresh :class:`Manifest` with the local runtime captured."""
    return Manifest(
        name=name,
        config_path=str(config_path) if config_path is not None else None,
        runtime=_capture_runtime(),
    )

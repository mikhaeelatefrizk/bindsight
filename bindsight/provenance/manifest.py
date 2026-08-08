# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pydantic v2 schema for ``run_manifest.jsonld`` — the bindsight provenance contract.

Every pipeline stage emits a :class:`StageRecord` and appends it to the
:class:`Manifest`. The manifest serializes as PROV-O JSON-LD so that downstream
RO-Crate packaging and external provenance tooling can consume it natively.

"PROV-O JSON-LD" is a claim about the *expanded* document, not just the file
extension: :meth:`Manifest.jsonld` types the run as a ``prov:Bundle``, each
stage as a ``prov:Activity``, each artifact as a content-addressed
``prov:Entity`` and each tool/image as a ``prov:SoftwareAgent``, and
:data:`PROV_CONTEXT` binds every key to a term that actually exists — in PROV-O
where PROV-O defines one, under the ``bindsight:`` namespace otherwise. The
key names themselves are unchanged, so the file still reads as plain JSON.

The shape and semantics here are stable; bump :data:`MANIFEST_SCHEMA_VERSION`
when changing them.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform
import sys
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Bumped when the schema changes in a backwards-incompatible way. 1.1.0 added
# RuntimeRef.libraries and the "skipped" stage status: manifests written at
# 1.1.0 do not validate against a 1.0.0 reader (the models forbid extras).
MANIFEST_SCHEMA_VERSION = "1.1.0"

#: Namespace for bindsight's own terms and node identifiers. Everything PROV-O
#: and schema.org do not define lives here, rather than being minted by an
#: ``@vocab`` default into IRIs that resolve to nothing.
BINDSIGHT_NS = "https://github.com/mikhaeelatefrizk/bindsight/ns#"

# JSON-LD 1.1 context for the manifest. Every key is bound explicitly and there
# is no ``@vocab``, so a PROV-aware consumer sees real PROV-O predicates
# (prov:startedAtTime, prov:used, prov:generated, prov:wasAssociatedWith …) and
# an undeclared key is dropped on expansion instead of being invented.
PROV_CONTEXT: dict[str, Any] = {
    # Required for the @json literals and the property-scoped context below.
    "@version": 1.1,
    "prov": "http://www.w3.org/ns/prov#",
    "schema": "http://schema.org/",
    "xsd": "http://www.w3.org/2001/XMLSchema#",
    "bindsight": BINDSIGHT_NS,
    # ---- run (prov:Bundle) ----
    "schema_version": "bindsight:schemaVersion",
    "run_id": "bindsight:runId",
    "created_at": {"@id": "prov:generatedAtTime", "@type": "xsd:dateTime"},
    "name": "schema:name",
    "config_path": "bindsight:configPath",
    "runtime": "bindsight:runtimeEnvironment",
    # PROV-O has no predicate from a bundle to the activities it describes
    # (prov:hadMember ranges over entities), so this one is ours; the stage
    # nodes themselves carry the PROV links a consumer traverses.
    "stages": "bindsight:stage",
    # ---- runtime environment ----
    "python": "bindsight:pythonVersion",
    "platform": "bindsight:platform",
    "machine": "bindsight:machine",
    "bindsight_version": "bindsight:bindsightVersion",
    "libraries": {"@id": "bindsight:libraryVersions", "@type": "@json"},
    # ---- stage (prov:Activity) ----
    "started_at": {"@id": "prov:startedAtTime", "@type": "xsd:dateTime"},
    "ended_at": {"@id": "prov:endedAtTime", "@type": "xsd:dateTime"},
    "status": "bindsight:status",
    "tool": "prov:wasAssociatedWith",
    # Inside a container reference, ``runtime`` names the container engine, not
    # the run's environment — rebound in this property's scope (JSON-LD 1.1).
    "container": {
        "@id": "prov:wasAssociatedWith",
        "@context": {"runtime": "bindsight:containerRuntime"},
    },
    "inputs": "prov:used",
    "outputs": "prov:generated",
    # Stage parameters are free-form, so they are carried as a JSON literal
    # rather than expanded key by key.
    "params": {"@id": "bindsight:params", "@type": "@json"},
    "cache_key": "bindsight:cacheKey",
    "notes": "schema:description",
    "error": "bindsight:error",
    # ---- tool / container image (prov:SoftwareAgent) ----
    "version": "schema:softwareVersion",
    "license": "schema:license",
    "repo_url": {"@id": "schema:codeRepository", "@type": "@id"},
    "commit_sha": "bindsight:commitSha",
    "weights_sha256": "bindsight:weightsSha256",
    "citation": "schema:citation",
    "image": "bindsight:containerImage",
    "tag": "bindsight:containerTag",
    "digest": "bindsight:containerDigest",
    # ---- artifacts (prov:Entity) ----
    "role": "bindsight:role",
    "path": "bindsight:path",
    "sha256": "bindsight:sha256",
    "bytes": {"@id": "schema:contentSize", "@type": "xsd:nonNegativeInteger"},
    "media_type": "schema:encodingFormat",
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


def _slug(value: str) -> str:
    """Percent-encode ``value`` so it is safe inside one IRI segment."""
    return quote(value, safe="")


def _entity_node(ref: dict[str, Any]) -> dict[str, Any]:
    """Type one input/output reference as a ``prov:Entity``.

    Identity is the content digest, so an artifact generated by one stage and
    consumed by the next is a single node in the graph rather than two
    unrelated ones.
    """
    return {"@id": f"urn:sha256:{ref['sha256']}", "@type": "prov:Entity", **ref}


def _agent_node(tool: dict[str, Any]) -> dict[str, Any]:
    """Type a tool reference as a ``prov:SoftwareAgent``, identified by name+version."""
    name = _slug(str(tool["name"]))
    version = _slug(str(tool["version"]))
    return {"@id": f"{BINDSIGHT_NS}tool/{name}/{version}", "@type": "prov:SoftwareAgent", **tool}


def _container_node(container: dict[str, Any]) -> dict[str, Any]:
    """Type a container image as a ``prov:SoftwareAgent``, identified by its digest."""
    image = _slug(str(container["image"]))
    digest = _slug(str(container["digest"]))
    return {
        "@id": f"{BINDSIGHT_NS}container/{image}/{digest}",
        "@type": "prov:SoftwareAgent",
        **container,
    }


def _activity_node(stage: dict[str, Any], *, run_iri: str, index: int) -> dict[str, Any]:
    """Type one serialized stage as a ``prov:Activity`` with typed sub-nodes."""
    node: dict[str, Any] = {
        "@id": f"{run_iri}#stage/{index}/{_slug(str(stage['name']))}",
        "@type": "prov:Activity",
        **stage,
    }
    node["tool"] = _agent_node(stage["tool"])
    if stage.get("container") is not None:
        node["container"] = _container_node(stage["container"])
    node["inputs"] = [_entity_node(r) for r in stage.get("inputs") or []]
    node["outputs"] = [_entity_node(r) for r in stage.get("outputs") or []]
    return node


def _strip_jsonld(value: Any) -> Any:
    """Recursively drop JSON-LD keywords (``@context``, ``@id``, ``@type``).

    The models forbid extra fields, so the framing added at serialization time
    has to come back off before validation. ``params`` is stage-supplied data
    rather than provenance framing, so it is passed through untouched.
    """
    if isinstance(value, dict):
        return {
            k: (v if k == "params" else _strip_jsonld(v))
            for k, v in value.items()
            if not k.startswith("@")
        }
    if isinstance(value, list):
        return [_strip_jsonld(v) for v in value]
    return value


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

    image: str = Field(..., description="Image name (e.g. 'ghcr.io/mikhaeelatefrizk/bindsight').")
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
    # "skipped" = the stage was not attempted (opt-out flag, or an upstream
    # stage produced nothing to work on); distinct from "skipped_cache", which
    # means its outputs already existed and validated.
    status: Literal["running", "completed", "failed", "skipped", "skipped_cache"] = "running"

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

    def mark_skipped(self, reason: str) -> None:
        """Mark this stage as not attempted, recording why in ``notes``."""
        self.status = "skipped"
        self.ended_at = _now_iso()
        self.notes = reason


class RuntimeRef(BaseModel):
    """Capture of the local runtime environment.

    Recorded once per run: the Python version, the platform, and the resolved
    version of every library whose release can move the numbers a run reports
    (see :data:`SCIENTIFIC_STACK`). Reproducibility requires matching the
    container digest, not just this — but this is useful triage when a
    container can't be rebuilt.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    python: str
    platform: str
    machine: str
    bindsight_version: str
    libraries: dict[str, str | None] = Field(
        default_factory=dict,
        description="Resolved version of each tracked scientific dependency. "
        "``null`` means the package is not installed in this environment; an "
        "empty mapping means the manifest predates library capture.",
    )


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
        """Return the manifest as PROV-O JSON-LD.

        Node identity and typing are applied here rather than stored on the
        models: the run is a ``prov:Bundle`` identified by its run UUID, each
        stage a ``prov:Activity``, each artifact a content-addressed
        ``prov:Entity``, and each tool or container image a
        ``prov:SoftwareAgent``. Key names are untouched — :data:`PROV_CONTEXT`
        maps them onto PROV-O and schema.org — so the document expands to real
        provenance triples while staying readable as plain JSON.
        """
        body = self.model_dump(mode="json")
        run_iri = f"urn:uuid:{self.run_id}"
        body["runtime"] = {
            "@id": f"{run_iri}#runtime",
            "@type": ["prov:Entity", "bindsight:RuntimeEnvironment"],
            **body["runtime"],
        }
        body["stages"] = [
            _activity_node(s, run_iri=run_iri, index=i)
            for i, s in enumerate(body.get("stages") or [])
        ]
        return {"@context": PROV_CONTEXT, "@id": run_iri, "@type": "prov:Bundle", **body}

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
        """Load a manifest from disk, stripping the JSON-LD framing."""
        raw = json.loads(Path(path).read_text())
        return cls.model_validate(_strip_jsonld(raw))

    def append(self, stage: StageRecord) -> None:
        """Append a stage record to this manifest."""
        self.stages.append(stage)


# ---------------------------------------------------------------------------
# Constructors
# ---------------------------------------------------------------------------
#: Distributions whose release can change the numbers a run reports — the DEG
#: statistics, the parquet encoding, the structure parsing, the ESM-2 prescreen.
#: pyproject.toml bounds them and ``envs/constraints.txt`` pins them; recording
#: what actually resolved is what lets a published number be re-derived later.
SCIENTIFIC_STACK: tuple[str, ...] = (
    "numpy",
    "scipy",
    "pandas",
    "pyarrow",
    "pydeseq2",
    "biopython",
    "scikit-learn",
    "anndata",
    "torch",
    "transformers",
)


def _capture_libraries() -> dict[str, str | None]:
    """Resolve the installed version of every distribution in :data:`SCIENTIFIC_STACK`.

    A distribution that is not installed maps to ``None`` rather than being
    omitted or given a placeholder, so a reader can tell "absent from this
    environment" from "never recorded".
    """
    versions: dict[str, str | None] = {}
    for dist in SCIENTIFIC_STACK:
        try:
            versions[dist] = importlib.metadata.version(dist)
        except importlib.metadata.PackageNotFoundError:
            versions[dist] = None
    return versions


def _capture_runtime() -> RuntimeRef:
    from bindsight import __version__ as xpr_version

    return RuntimeRef(
        python=sys.version.split()[0],
        platform=platform.platform(),
        machine=platform.machine(),
        bindsight_version=xpr_version,
        libraries=_capture_libraries(),
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

"""Tests for ``xpr2bind.provenance.manifest`` — the inter-module contract."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from xpr2bind.provenance import (
    ContainerRef,
    InputRef,
    Manifest,
    OutputRef,
    StageRecord,
    ToolRef,
    new_manifest,
    sha256_file,
)
from xpr2bind.provenance.manifest import MANIFEST_SCHEMA_VERSION, PROV_CONTEXT


# ---------------------------------------------------------------------------
# Constructors
# ---------------------------------------------------------------------------
def test_new_manifest_captures_runtime() -> None:
    m = new_manifest(name="t")
    assert m.name == "t"
    assert m.runtime.python
    assert m.runtime.platform
    assert m.runtime.xpr2bind_version
    assert m.schema_version == MANIFEST_SCHEMA_VERSION


def test_new_manifest_run_id_is_unique() -> None:
    a = new_manifest()
    b = new_manifest()
    assert a.run_id != b.run_id


# ---------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------
def test_input_ref_rejects_short_sha() -> None:
    with pytest.raises(ValidationError):
        InputRef(role="counts", path="x.tsv", sha256="abc", bytes=10)


def test_container_ref_requires_sha256_digest() -> None:
    with pytest.raises(ValidationError):
        ContainerRef(image="x", digest="latest")  # not sha256:...


def test_container_ref_accepts_sha256_digest() -> None:
    cr = ContainerRef(image="x", digest="sha256:" + "0" * 64)
    assert cr.digest.startswith("sha256:")


# ---------------------------------------------------------------------------
# StageRecord lifecycle
# ---------------------------------------------------------------------------
def test_stage_record_lifecycle(tmp_path: Path) -> None:
    out = tmp_path / "out.txt"
    out.write_text("hello\n")

    stage = StageRecord(
        name="deg",
        tool=ToolRef(name="pydeseq2", version="0.5.4", license="MIT"),
        inputs=[],
        params={"fdr_threshold": 0.05},
    )
    assert stage.status == "running"
    stage.mark_completed(
        outputs=[
            OutputRef(role="deg", path="out.txt", sha256=sha256_file(out), bytes=out.stat().st_size)
        ]
    )
    assert stage.status == "completed"
    assert stage.ended_at is not None
    assert len(stage.outputs) == 1


def test_stage_record_failure() -> None:
    stage = StageRecord(
        name="design",
        tool=ToolRef(name="rfdiffusion", version="1.1.0", license="BSD-3"),
    )
    stage.mark_failed("CUDA OOM")
    assert stage.status == "failed"
    assert stage.error == "CUDA OOM"


# ---------------------------------------------------------------------------
# Round-trip serialization
# ---------------------------------------------------------------------------
def test_manifest_round_trip(tmp_path: Path) -> None:
    m = new_manifest(name="round-trip")
    m.append(
        StageRecord(
            name="deg",
            tool=ToolRef(name="pydeseq2", version="0.5.4", license="MIT"),
        )
    )
    out = tmp_path / "manifest.jsonld"
    m.write(out)

    loaded = Manifest.read(out)
    assert loaded.name == "round-trip"
    assert loaded.run_id == m.run_id
    assert len(loaded.stages) == 1
    assert loaded.stages[0].name == "deg"


def test_jsonld_includes_prov_context() -> None:
    m = new_manifest()
    body = m.jsonld()
    assert "@context" in body
    assert body["@context"] == PROV_CONTEXT


def test_atomic_write_leaves_no_tmp(tmp_path: Path) -> None:
    m = new_manifest()
    out = tmp_path / "manifest.jsonld"
    m.write(out)
    assert out.exists()
    assert not (tmp_path / "manifest.jsonld.tmp").exists()


# ---------------------------------------------------------------------------
# Hashing helper
# ---------------------------------------------------------------------------
def test_sha256_file_known_value(tmp_path: Path) -> None:
    p = tmp_path / "x.txt"
    p.write_bytes(b"hello\n")
    # echo -n "hello\n" | sha256sum  => 5891b5b522d5df086d0ff0b110fbd9d21bb4fc7163af34d08286a2e846f6be03
    assert sha256_file(p) == "5891b5b522d5df086d0ff0b110fbd9d21bb4fc7163af34d08286a2e846f6be03"


# ---------------------------------------------------------------------------
# Forbidden-extra protection (catches drift in the schema)
# ---------------------------------------------------------------------------
def test_extra_field_rejected_on_tool_ref() -> None:
    with pytest.raises(ValidationError):
        ToolRef.model_validate({"name": "x", "version": "1", "license": "MIT", "rogue_field": True})


def test_manifest_jsonld_is_valid_json(tmp_path: Path) -> None:
    m = new_manifest()
    out = tmp_path / "manifest.jsonld"
    m.write(out)
    # Just round-tripping through the std json parser is enough as a smoke test.
    json.loads(out.read_text())

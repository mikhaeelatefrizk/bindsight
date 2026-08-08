# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for ``bindsight.provenance.manifest`` — the inter-module contract."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from bindsight.provenance import (
    ContainerRef,
    InputRef,
    Manifest,
    OutputRef,
    StageRecord,
    ToolRef,
    new_manifest,
    sha256_file,
)
from bindsight.provenance import manifest as manifest_module
from bindsight.provenance.manifest import (
    MANIFEST_SCHEMA_VERSION,
    PROV_CONTEXT,
    SCIENTIFIC_STACK,
)

PROV = "http://www.w3.org/ns/prov#"
SCHEMA = "http://schema.org/"
#: Prefix declarations, not manifest keys — excluded when auditing term coverage.
_PREFIX_KEYS = {"prov", "schema", "xsd", "bindsight"}
#: Their values are free-form JSON literals, so their inner keys are not terms.
_JSON_LITERAL_KEYS = {"params", "libraries"}


def _term_id(term: str) -> str:
    """The compact IRI a context term maps to (terms may be dicts or strings)."""
    entry = PROV_CONTEXT[term]
    return str(entry["@id"] if isinstance(entry, dict) else entry)


def _expanded(term: str) -> str:
    """Expand a context term's compact IRI against the context's own prefixes."""
    prefix, _, local = _term_id(term).partition(":")
    return str(PROV_CONTEXT[prefix]) + local


def _populated_manifest() -> Manifest:
    """A manifest exercising every field the JSON-LD framing has to type."""
    m = new_manifest(name="populated", config_path="examples/demo/config.yaml")
    m.append(
        StageRecord(
            name="deg",
            tool=ToolRef(
                name="pydeseq2",
                version="0.5.4",
                license="MIT",
                repo_url="https://github.com/owkin/PyDESeq2",
                commit_sha="a" * 40,
                weights_sha256="b" * 64,
                citation="10.1093/bioinformatics/btad547",
            ),
            container=ContainerRef(image="ghcr.io/x/y", tag="dev", digest="sha256:" + "c" * 64),
            inputs=[
                InputRef(
                    role="counts",
                    path="cohort/counts.tsv.gz",
                    sha256="1" * 64,
                    bytes=12,
                    media_type="application/gzip",
                )
            ],
            outputs=[
                OutputRef(
                    role="deg_table",
                    path="deg/results.parquet",
                    sha256="2" * 64,
                    bytes=34,
                    media_type="application/x-parquet",
                )
            ],
            params={"fdr_threshold": 0.05},
            cache_key="3" * 64,
            notes="ran clean",
            error=None,
        )
    )
    return m


# ---------------------------------------------------------------------------
# Constructors
# ---------------------------------------------------------------------------
def test_new_manifest_captures_runtime() -> None:
    m = new_manifest(name="t")
    assert m.name == "t"
    assert m.runtime.python
    assert m.runtime.platform
    assert m.runtime.bindsight_version
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


def test_stage_record_skipped_records_the_reason() -> None:
    """An unattempted stage is 'skipped' with a reason — not a claimed cache hit."""
    stage = StageRecord(
        name="design",
        tool=ToolRef(name="rfdiffusion", version="1.1.0", license="BSD-3"),
    )
    stage.mark_skipped("backend 'colab' is not headless; run the GPU half by hand")
    assert stage.status == "skipped"
    assert stage.status != "skipped_cache"  # would assert a cache hit that never happened
    assert stage.ended_at is not None
    assert "not headless" in (stage.notes or "")


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
    # Not `== PROV_CONTEXT`: that compares the constant with itself and passed
    # just as happily when the context bound nothing but a bogus @vocab.
    ctx = body["@context"]
    assert ctx["prov"] == PROV
    assert ctx["started_at"]["@id"] == "prov:startedAtTime"


# ---------------------------------------------------------------------------
# PROV-O context (I7): real ontology terms, no @vocab, nothing left undeclared
# ---------------------------------------------------------------------------
def test_prov_context_has_no_vocab() -> None:
    # @vocab minted every unrecognised key into http://www.w3.org/ns/prov#<key>
    # — 36 IRIs that PROV-O does not define. An undeclared key must now be
    # dropped on expansion rather than invented.
    assert "@vocab" not in PROV_CONTEXT


@pytest.mark.parametrize(
    ("term", "iri"),
    [
        ("started_at", PROV + "startedAtTime"),
        ("ended_at", PROV + "endedAtTime"),
        ("created_at", PROV + "generatedAtTime"),
        ("inputs", PROV + "used"),
        ("outputs", PROV + "generated"),
        # Both the tool and the image are agents the activity was associated
        # with; they merge into one array on expansion, which is intended.
        ("tool", PROV + "wasAssociatedWith"),
        ("container", PROV + "wasAssociatedWith"),
    ],
)
def test_prov_context_binds_real_prov_o_predicates(term: str, iri: str) -> None:
    assert _expanded(term) == iri


def test_prov_context_types_the_timestamps_as_datetimes() -> None:
    for term in ("created_at", "started_at", "ended_at"):
        assert PROV_CONTEXT[term]["@type"] == "xsd:dateTime"


def test_prov_context_declares_every_term_under_a_real_prefix() -> None:
    """No term may fall through to an invented IRI."""
    for term in PROV_CONTEXT:
        if term.startswith("@") or term in _PREFIX_KEYS:
            continue
        compact = _term_id(term)
        prefix = compact.partition(":")[0]
        assert prefix in _PREFIX_KEYS, f"{term} -> {compact} is not under a declared prefix"
        assert _expanded(term).startswith((PROV, SCHEMA, manifest_module.BINDSIGHT_NS))


def test_every_emitted_key_is_declared_in_the_context() -> None:
    """Walk a fully-populated document: nothing on disk is left to be minted."""
    body = _populated_manifest().jsonld()

    def walk(node: object) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key.startswith("@"):
                    continue
                assert key in PROV_CONTEXT, f"key {key!r} is emitted but undeclared"
                if key not in _JSON_LITERAL_KEYS:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk({k: v for k, v in body.items() if k != "@context"})


def test_container_runtime_is_rebound_away_from_the_run_runtime() -> None:
    # `runtime` means the container engine inside a container ref and the
    # environment at the top level; the property-scoped context keeps them apart.
    assert _expanded("runtime") == manifest_module.BINDSIGHT_NS + "runtimeEnvironment"
    scoped = PROV_CONTEXT["container"]["@context"]["runtime"]
    assert scoped == "bindsight:containerRuntime"


# ---------------------------------------------------------------------------
# PROV-O node identity + typing (I7)
# ---------------------------------------------------------------------------
def test_jsonld_types_the_run_as_a_prov_bundle() -> None:
    m = _populated_manifest()
    body = m.jsonld()
    assert body["@type"] == "prov:Bundle"
    assert body["@id"] == f"urn:uuid:{m.run_id}"


def test_jsonld_types_stages_agents_and_artifacts() -> None:
    m = _populated_manifest()
    body = m.jsonld()
    run_iri = f"urn:uuid:{m.run_id}"

    stage = body["stages"][0]
    assert stage["@type"] == "prov:Activity"
    assert stage["@id"].startswith(run_iri)
    assert stage["name"] == "deg"

    assert stage["tool"]["@type"] == "prov:SoftwareAgent"
    assert stage["container"]["@type"] == "prov:SoftwareAgent"

    for ref in (*stage["inputs"], *stage["outputs"]):
        assert ref["@type"] == "prov:Entity"
        assert ref["@id"] == f"urn:sha256:{ref['sha256']}"

    assert body["runtime"]["@type"] == ["prov:Entity", "bindsight:RuntimeEnvironment"]
    assert body["runtime"]["@id"] == f"{run_iri}#runtime"


def test_same_artifact_gets_one_entity_id_across_stages() -> None:
    """An output consumed by the next stage must be ONE node, not two."""
    digest = "d" * 64
    m = new_manifest(name="linked")
    m.append(
        StageRecord(
            name="deg",
            tool=ToolRef(name="pydeseq2", version="0.5.4", license="MIT"),
            outputs=[
                OutputRef(role="deg_table", path="deg/results.parquet", sha256=digest, bytes=9)
            ],
        )
    )
    m.append(
        StageRecord(
            name="discover",
            tool=ToolRef(name="bindsight.discover", version="0.2.1", license="AGPL-3.0-or-later"),
            inputs=[InputRef(role="deg_table", path="deg/results.parquet", sha256=digest, bytes=9)],
        )
    )
    stages = m.jsonld()["stages"]
    produced = stages[0]["outputs"][0]["@id"]
    consumed = stages[1]["inputs"][0]["@id"]
    assert produced == consumed == f"urn:sha256:{digest}"


def test_stage_ids_are_distinct_for_repeated_stage_names() -> None:
    m = new_manifest()
    for _ in range(2):
        m.append(
            StageRecord(
                name="design",
                tool=ToolRef(name="rfdiffusion", version="1.1.0", license="BSD-3"),
            )
        )
    ids = [s["@id"] for s in m.jsonld()["stages"]]
    assert len(set(ids)) == 2


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


# ---------------------------------------------------------------------------
# Framing round-trip (I7): the framing comes off, the stage data does not
# ---------------------------------------------------------------------------
def test_read_strips_framing_but_leaves_params_untouched(tmp_path: Path) -> None:
    m = new_manifest(name="framed")
    m.append(
        StageRecord(
            name="deg",
            tool=ToolRef(name="pydeseq2", version="0.5.4", license="MIT"),
            container=ContainerRef(image="ghcr.io/x/y", digest="sha256:" + "e" * 64),
            inputs=[
                InputRef(role="counts", path="cohort/counts.tsv.gz", sha256="1" * 64, bytes=12)
            ],
            outputs=[
                OutputRef(role="deg_table", path="deg/results.parquet", sha256="2" * 64, bytes=34)
            ],
            # params is stage data, not provenance framing: an '@' key in it is
            # the user's, and stripping it would silently corrupt the record.
            params={"@weird": 1, "fdr_threshold": 0.05},
        )
    )
    out = tmp_path / "manifest.jsonld"
    m.write(out)

    on_disk = json.loads(out.read_text())
    assert on_disk["@type"] == "prov:Bundle"
    assert on_disk["stages"][0]["@type"] == "prov:Activity"
    assert on_disk["stages"][0]["params"]["@weird"] == 1

    loaded = Manifest.read(out)
    stage = loaded.stages[0]
    assert stage.params == {"@weird": 1, "fdr_threshold": 0.05}
    assert stage.container is not None
    assert stage.container.digest == "sha256:" + "e" * 64
    assert stage.inputs[0].sha256 == "1" * 64
    assert stage.outputs[0].sha256 == "2" * 64


def test_read_round_trips_a_skipped_stage(tmp_path: Path) -> None:
    m = new_manifest()
    stage = StageRecord(
        name="rank",
        tool=ToolRef(name="bindsight.rank", version="0.2.1", license="AGPL-3.0-or-later"),
    )
    stage.mark_skipped("no validation output to rank")
    m.append(stage)
    out = tmp_path / "manifest.jsonld"
    m.write(out)

    loaded = Manifest.read(out)
    assert loaded.stages[0].status == "skipped"
    assert loaded.stages[0].notes == "no validation output to rank"


def test_fragment_preserves_skipped_status() -> None:
    """A Snakemake fragment must not be normalised from 'skipped' to 'completed'."""
    from bindsight.provenance.fragments import default_tool, stage_record_from_fragment

    record = stage_record_from_fragment(
        {"stage": "design", "status": "skipped", "tool": default_tool(), "notes": "no GPU"}
    )
    assert record.status == "skipped"
    # Unknown statuses still normalise, as before.
    assert stage_record_from_fragment({"stage": "design", "status": "bogus"}).status == "completed"


# ---------------------------------------------------------------------------
# Runtime library capture (I8)
# ---------------------------------------------------------------------------
def test_runtime_records_every_tracked_library() -> None:
    libs = new_manifest().runtime.libraries
    assert set(libs) == set(SCIENTIFIC_STACK)
    # numpy is a hard test dependency here, so its version must be a real string.
    assert isinstance(libs["numpy"], str)
    assert libs["numpy"].strip()


def test_absent_library_maps_to_none_rather_than_vanishing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """'Not installed' has to be distinguishable from 'never recorded'."""
    monkeypatch.setattr(
        manifest_module,
        "SCIENTIFIC_STACK",
        ("numpy", "bindsight-no-such-distribution"),
    )
    libs = manifest_module._capture_libraries()
    assert "bindsight-no-such-distribution" in libs
    assert libs["bindsight-no-such-distribution"] is None
    assert isinstance(libs["numpy"], str)


def test_libraries_survive_the_jsonld_round_trip(tmp_path: Path) -> None:
    m = new_manifest()
    out = tmp_path / "manifest.jsonld"
    m.write(out)
    assert Manifest.read(out).runtime.libraries == m.runtime.libraries


# ---------------------------------------------------------------------------
# Backwards compatibility: a 1.0.0-era manifest must still load
# ---------------------------------------------------------------------------
def test_reads_a_1_0_0_era_manifest_without_libraries(tmp_path: Path) -> None:
    legacy = {
        "@context": {"@vocab": "http://www.w3.org/ns/prov#"},
        "schema_version": "1.0.0",
        "run_id": "11111111-2222-3333-4444-555555555555",
        "created_at": "2026-01-01T00:00:00+00:00",
        "name": "legacy",
        "config_path": None,
        "runtime": {
            "python": "3.11.9",
            "platform": "Linux-6.1.0-x86_64",
            "machine": "x86_64",
            "bindsight_version": "0.2.0",
        },
        "stages": [
            {
                "name": "deg",
                "started_at": "2026-01-01T00:00:01+00:00",
                "ended_at": "2026-01-01T00:00:02+00:00",
                "status": "completed",
                "tool": {"name": "pydeseq2", "version": "0.5.4", "license": "MIT"},
                "container": None,
                "inputs": [],
                "outputs": [],
                "params": {},
                "cache_key": None,
                "notes": None,
                "error": None,
            }
        ],
    }
    path = tmp_path / "legacy.jsonld"
    path.write_text(json.dumps(legacy))

    loaded = Manifest.read(path)
    assert loaded.schema_version == "1.0.0"
    assert loaded.runtime.libraries == {}  # never recorded, not "absent"
    assert loaded.stages[0].name == "deg"

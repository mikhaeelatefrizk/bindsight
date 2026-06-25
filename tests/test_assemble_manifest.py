"""Tests for the Snakemake provenance assembler (``scripts/assemble_manifest.py``).

The script lives under ``scripts/`` (not an installed package) and is normally
invoked by Snakemake with an injected ``snakemake`` global. We load it by path
and exercise the pure :func:`assemble` helper, which needs no Snakemake runtime.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

from bindsight.provenance import Manifest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "assemble_manifest.py"


def _load_assembler() -> ModuleType:
    spec = importlib.util.spec_from_file_location("bindsight_assemble_manifest", _SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write_fragment(root: Path, stage: str, payload: dict | str) -> Path:
    d = root / stage
    d.mkdir(parents=True, exist_ok=True)
    frag = d / "manifest_fragment.jsonld"
    frag.write_text(payload if isinstance(payload, str) else json.dumps(payload))
    return frag


def test_assemble_folds_fragments_into_stages(tmp_path: Path) -> None:
    mod = _load_assembler()
    frags = [
        _write_fragment(
            tmp_path, "deg", {"stage": "deg", "status": "completed", "metrics": {"n": 5}}
        ),
        _write_fragment(
            tmp_path,
            "discover",
            {"stage": "discover", "status": "completed", "metrics": {"n_candidates": 3}},
        ),
    ]
    manifest = mod.assemble(frags, name="test-run")

    assert isinstance(manifest, Manifest)
    assert manifest.name == "test-run"
    assert [s.name for s in manifest.stages] == ["deg", "discover"]
    assert all(s.status == "completed" for s in manifest.stages)
    assert all(s.tool.name == "bindsight" for s in manifest.stages)
    # Metrics are preserved verbatim in notes (StageRecord has no metrics field).
    discover = manifest.stages[1]
    assert discover.notes is not None
    assert json.loads(discover.notes)["metrics"]["n_candidates"] == 3


def test_assemble_skips_empty_and_malformed(tmp_path: Path) -> None:
    mod = _load_assembler()
    good = _write_fragment(tmp_path, "deg", {"stage": "deg", "status": "completed", "metrics": {}})
    empty = _write_fragment(tmp_path, "discover", "")
    malformed = _write_fragment(tmp_path, "rank", "{not valid json")
    missing = tmp_path / "report" / "manifest_fragment.jsonld"  # never created

    manifest = mod.assemble([good, empty, malformed, missing])

    assert [s.name for s in manifest.stages] == ["deg"]


def test_assemble_derives_stage_name_from_parent_dir(tmp_path: Path) -> None:
    mod = _load_assembler()
    # Fragment with no explicit "stage" key -> name comes from the directory.
    frag = _write_fragment(tmp_path, "validate", {"status": "completed", "metrics": {"x": 1}})
    manifest = mod.assemble([frag])
    assert manifest.stages[0].name == "validate"


def test_assemble_normalizes_unknown_status(tmp_path: Path) -> None:
    mod = _load_assembler()
    frag = _write_fragment(tmp_path, "deg", {"stage": "deg", "status": "weird", "metrics": {}})
    manifest = mod.assemble([frag])
    assert manifest.stages[0].status == "completed"


def test_assembled_manifest_round_trips_on_disk(tmp_path: Path) -> None:
    mod = _load_assembler()
    frags = [
        _write_fragment(
            tmp_path, "deg", {"stage": "deg", "status": "completed", "metrics": {"n": 1}}
        ),
        _write_fragment(
            tmp_path, "report", {"stage": "report", "status": "completed", "metrics": {}}
        ),
    ]
    manifest = mod.assemble(frags)
    out = tmp_path / "run_manifest.jsonld"
    manifest.write(out)

    reloaded = Manifest.read(out)
    assert [s.name for s in reloaded.stages] == ["deg", "report"]
    assert reloaded.runtime.bindsight_version  # runtime captured


def test_assemble_empty_input_yields_valid_manifest(tmp_path: Path) -> None:
    mod = _load_assembler()
    manifest = mod.assemble([])
    assert manifest.stages == []
    # Still writable / valid.
    out = tmp_path / "run_manifest.jsonld"
    manifest.write(out)
    assert Manifest.read(out).stages == []


@pytest.mark.parametrize("status", ["running", "completed", "failed", "skipped_cache"])
def test_assemble_preserves_valid_statuses(tmp_path: Path, status: str) -> None:
    mod = _load_assembler()
    frag = _write_fragment(tmp_path, "deg", {"stage": "deg", "status": status, "metrics": {}})
    manifest = mod.assemble([frag])
    assert manifest.stages[0].status == status

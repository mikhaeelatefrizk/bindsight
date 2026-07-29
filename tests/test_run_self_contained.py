# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Run directories, and the crates built from them, must be portable.

``io/paths.py`` has always documented ``<run>/structures/`` and ``<run>/
config.yaml`` as part of the run layout. Neither was ever written: the
structure stayed in the machine-local cache and the candidate table stored its
absolute path, so a run — and every RO-Crate exported from one — was valid on
exactly one machine. That undercuts the project's central claim, which is that
a designed binder can be walked back to its evidence.

These tests pin the replacement: structures are adopted into the run, paths are
stored run-relative, pre-existing absolute paths still resolve, and an exported
crate resolves its own references when unpacked somewhere unrelated.
"""

from __future__ import annotations

import json
import zipfile

import pytest

from bindsight.export.ro_crate import export_ro_crate
from bindsight.io.paths import (
    ENV_CACHE_DIR,
    adopt_structure,
    cache_root,
    resolve_run_path,
    run_dir,
)


# ---------------------------------------------------------------------------
# adopt_structure
# ---------------------------------------------------------------------------
def test_adopt_structure_copies_and_returns_relative(tmp_path) -> None:
    """A cached structure is copied in and referenced run-relatively."""
    run = run_dir(tmp_path / "run")
    cached = tmp_path / "cache" / "AF-P04626-F1-model_v6.cif"
    cached.parent.mkdir(parents=True)
    cached.write_text("data_model\n", encoding="utf-8")

    rel = adopt_structure(run, cached)

    assert rel == "structures/AF-P04626-F1-model_v6.cif"
    assert not rel.startswith("/")
    assert (run / rel).is_file()
    assert (run / rel).read_text(encoding="utf-8") == "data_model\n"


def test_adopt_structure_survives_cache_eviction(tmp_path) -> None:
    """The adopted copy outlives the cache entry it came from.

    A symlink or hard link would let an unrelated cache prune silently gut a
    finished run, which is why this copies.
    """
    run = run_dir(tmp_path / "run")
    cached = tmp_path / "cache" / "AF-P00533-F1-model_v6.cif"
    cached.parent.mkdir(parents=True)
    cached.write_text("data_model\n", encoding="utf-8")

    rel = adopt_structure(run, cached)
    cached.unlink()

    assert (run / rel).is_file()


def test_adopt_structure_is_idempotent(tmp_path) -> None:
    """Re-adopting the same structure does not duplicate or corrupt it."""
    run = run_dir(tmp_path / "run")
    cached = tmp_path / "cache" / "AF-X-F1.cif"
    cached.parent.mkdir(parents=True)
    cached.write_text("one\n", encoding="utf-8")

    first = adopt_structure(run, cached)
    second = adopt_structure(run, cached)

    assert first == second
    assert len(list((run / "structures").iterdir())) == 1


# ---------------------------------------------------------------------------
# resolve_run_path — both forms, deliberately
# ---------------------------------------------------------------------------
def test_resolve_relative_path(tmp_path) -> None:
    """New-style run-relative references resolve against the run root."""
    run = run_dir(tmp_path / "run")
    target = run / "structures" / "s.cif"
    target.write_text("x", encoding="utf-8")
    assert resolve_run_path(run, "structures/s.cif") == target


def test_resolve_absolute_path_still_works(tmp_path) -> None:
    """Runs made before this change stored absolute paths and must keep working."""
    run = run_dir(tmp_path / "run")
    external = tmp_path / "elsewhere" / "s.cif"
    external.parent.mkdir(parents=True)
    external.write_text("x", encoding="utf-8")
    assert resolve_run_path(run, str(external)) == external


@pytest.mark.parametrize("stored", ["", None, "structures/missing.cif", "/nope/missing.cif"])
def test_resolve_returns_none_for_unusable_references(tmp_path, stored) -> None:
    """Empty or unresolvable references yield None rather than a bad path."""
    run = run_dir(tmp_path / "run")
    assert resolve_run_path(run, stored) is None


# ---------------------------------------------------------------------------
# Cache override — the cross-platform seam
# ---------------------------------------------------------------------------
def test_cache_root_honours_the_env_override(tmp_path, monkeypatch) -> None:
    """BINDSIGHT_CACHE_DIR redirects the cache root.

    XDG_CACHE_HOME is ignored by platformdirs on macOS, and monkeypatch cannot
    reach a subprocess, so this is the only seam that works everywhere.
    """
    monkeypatch.setenv(ENV_CACHE_DIR, str(tmp_path / "mycache"))
    assert cache_root() == tmp_path / "mycache"
    assert cache_root().is_dir()


def test_cache_root_default_without_override(monkeypatch) -> None:
    """Without the override the platform cache location is used."""
    monkeypatch.delenv(ENV_CACHE_DIR, raising=False)
    assert "bindsight" in str(cache_root())


# ---------------------------------------------------------------------------
# Crate portability
# ---------------------------------------------------------------------------
def _make_run_with_structure(tmp_path):
    """Build a minimal run whose candidate table references an adopted structure."""
    pd = pytest.importorskip("pandas")
    run = run_dir(tmp_path / "run")

    cached = tmp_path / "cache" / "AF-P04626-F1-model_v6.cif"
    cached.parent.mkdir(parents=True)
    cached.write_text("data_model\n_entry.id model\n", encoding="utf-8")
    rel = adopt_structure(run, cached)

    pd.DataFrame(
        {"uniprot_id": ["P04626"], "alphafold_structure_path": [rel], "rank": [1]}
    ).to_parquet(run / "targets" / "candidates.parquet")
    pd.DataFrame({"gene_id": ["ENSG1"], "significant": [True]}).to_parquet(
        run / "deg" / "results.parquet"
    )
    (run / "taxonomy").mkdir(exist_ok=True)
    pd.DataFrame({"disposition": ["surfaced"], "count": [1]}).to_parquet(
        run / "taxonomy" / "failure_taxonomy.parquet"
    )
    (run / "config.yaml").write_text("name: t\n", encoding="utf-8")
    (run / "run_manifest.jsonld").write_text(
        json.dumps({"run_id": "r", "name": "t", "stages": []}), encoding="utf-8"
    )
    return run, rel


def test_crate_carries_the_structures_it_references(tmp_path) -> None:
    """Structure references resolve inside the crate, on any machine.

    Before this, a crate contained candidate rows pointing at
    ``~/.cache/bindsight/alphafolddb/...`` on the machine that produced it.
    """
    run, rel = _make_run_with_structure(tmp_path)
    crate = export_ro_crate(run, tmp_path / "out.crate.zip")

    with zipfile.ZipFile(crate) as zf:
        names = set(zf.namelist())

    assert rel in names, "the referenced structure is missing from the crate"
    assert "taxonomy/failure_taxonomy.parquet" in names
    assert "config.yaml" in names


def test_crate_unpacks_and_resolves_elsewhere(tmp_path) -> None:
    """Unzipped on an unrelated path, every reference still resolves."""
    pd = pytest.importorskip("pandas")
    run, _ = _make_run_with_structure(tmp_path)
    crate = export_ro_crate(run, tmp_path / "out.crate.zip")

    dest = tmp_path / "somewhere" / "else"
    dest.mkdir(parents=True)
    with zipfile.ZipFile(crate) as zf:
        zf.extractall(dest)

    cand = pd.read_parquet(dest / "targets" / "candidates.parquet")
    refs = [p for p in cand["alphafold_structure_path"] if p]
    assert refs
    for ref in refs:
        assert (dest / ref).is_file(), f"{ref} does not resolve inside the unpacked crate"


def test_crate_metadata_propagates_manifest_digests(tmp_path) -> None:
    """sha256 digests recorded in the manifest reach the crate metadata."""
    run, _ = _make_run_with_structure(tmp_path)
    digest = "a" * 64
    (run / "run_manifest.jsonld").write_text(
        json.dumps(
            {
                "run_id": "r",
                "name": "t",
                "stages": [
                    {
                        "name": "deg",
                        "outputs": [{"path": "deg/results.parquet", "sha256": digest}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    crate = export_ro_crate(run, tmp_path / "out.crate.zip")

    with zipfile.ZipFile(crate) as zf:
        meta = json.loads(zf.read("ro-crate-metadata.json"))

    entry = next(n for n in meta["@graph"] if n.get("@id") == "deg/results.parquet")
    assert entry["sha256"] == digest

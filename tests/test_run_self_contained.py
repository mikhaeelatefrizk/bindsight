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


def test_digests_survive_a_manifest_written_on_another_platform(monkeypatch) -> None:
    """A manifest written on Windows must still yield digests when exported on POSIX.

    ``test_crate_metadata_propagates_manifest_digests`` above writes the manifest
    and exports the crate in one call on one machine, so both sides always agree
    about what a separator is and the disagreement is structurally invisible to
    it.

    It was a real disagreement. ``_resolve_recorded`` replaced backslashes;
    ``_manifest_digests`` relied on ``Path.as_posix()``, which converts
    separators only on the platform whose separator they are. On POSIX a
    backslash is an ordinary filename character, so a manifest recording a
    Windows-style path produced a one-segment key that none of ``_digest_for``'s
    three lookups could match. Every ``sha256`` silently disappeared from crates
    exported on Linux and macOS -- an archive deposited as a run's integrity
    record, containing no integrity record, with no error.

    This calls ``_manifest_digests`` directly rather than exporting a crate,
    because going through the filesystem makes the test platform-dependent in
    exactly the way the defect is: reintroducing the bug and running the
    end-to-end version on Windows **passes**, since Windows ``Path`` converts
    backslashes natively. A guard that only fires on the platform that was never
    broken is decoration. This one fires everywhere.
    """
    from pathlib import PurePosixPath

    from bindsight.export import ro_crate
    from bindsight.export.ro_crate import _digest_for, _manifest_digests

    # Run the function under POSIX path semantics. Without this the test is
    # decoration on Windows: the defective expression,
    # ``PurePosixPath(Path(path).as_posix()).as_posix()``, *also* produces the
    # right key there, because Windows ``Path`` treats a backslash as a
    # separator. Reintroducing the bug and running this test on Windows passed.
    # Substituting ``PurePosixPath`` for the module's ``Path`` makes a backslash
    # an ordinary character, which is precisely what a Linux runner sees.
    monkeypatch.setattr(ro_crate, "Path", PurePosixPath)

    sep = chr(92)
    digest = "b" * 64
    manifest = {
        "stages": [
            {
                "name": "deg",
                "outputs": [
                    {"path": sep.join(["runs", "join", "deg", "results.parquet"]), "sha256": digest}
                ],
            }
        ]
    }

    digests = _manifest_digests(manifest)

    assert all(sep not in key for key in digests), (
        f"a recorded path kept its foreign separator as a key: {sorted(digests)}"
    )
    assert _digest_for(digests, "deg/results.parquet") == digest, (
        "a digest recorded with foreign path separators is unreachable; a crate "
        "exported from this manifest would carry no integrity record"
    )


def test_a_crate_built_from_a_foreign_manifest_carries_its_digest(tmp_path) -> None:
    """The same property end to end, which is what actually ships.

    Kept alongside the unit test above rather than instead of it: this one only
    exercises the defect on POSIX, but it is the path a real deposit takes.
    """
    run, _ = _make_run_with_structure(tmp_path)
    digest = "c" * 64
    sep = chr(92)

    manifest = {
        "run_id": "r",
        "name": "t",
        "stages": [
            {
                "name": "deg",
                "outputs": [
                    {"path": sep.join(["runs", "join", "deg", "results.parquet"]), "sha256": digest}
                ],
            }
        ],
    }
    (run / "run_manifest.jsonld").write_text(json.dumps(manifest), encoding="utf-8", newline="\n")
    crate = export_ro_crate(run, tmp_path / "out.crate.zip")

    with zipfile.ZipFile(crate) as zf:
        meta = json.loads(zf.read("ro-crate-metadata.json"))

    entry = next(n for n in meta["@graph"] if n.get("@id") == "deg/results.parquet")
    assert entry.get("sha256") == digest


def test_both_path_consumers_normalise_through_one_function() -> None:
    """Guards the guard: two functions reading manifest paths must not drift apart.

    The defect above existed because ``_resolve_recorded`` and
    ``_manifest_digests`` each had their own idea of a separator. One shared
    normaliser is the fix; this asserts both still use it.
    """
    import inspect

    from bindsight.export import ro_crate

    for fn in (ro_crate._resolve_recorded, ro_crate._manifest_digests):
        source = inspect.getsource(fn)
        assert "_posix_key" in source, (
            f"{fn.__name__} no longer normalises manifest paths through _posix_key; "
            "the two consumers can drift apart again"
        )

    sep = chr(92)
    assert ro_crate._posix_key(sep.join(["a", "b", "c.txt"])) == "a/b/c.txt"
    assert ro_crate._posix_key("a/b/c.txt") == "a/b/c.txt"


def test_every_recorded_output_reaches_the_deposit(tmp_path) -> None:
    """A file the manifest says the run produced must be in the crate.

    ``_PIPELINE_FILES`` is an allowlist -- a tuple of names that alone decides
    what the deposited archive contains -- and ``grep -rn _PIPELINE_FILES
    tests/`` returned nothing. No test, no sweep, no discovery. A new stage's
    artifact would be dropped from every future deposit and nothing would go red.

    Two consequences were already visible when this was written: ``config.yaml``
    shipped in the crate while being registered as no ``OutputRef``, so it
    carried no digest; and ``prescreen.txt`` -- the only record of whether the
    ESM-2 screen actually applied -- was in neither the files nor the trees, and
    was in fact discarded on the GPU host before the tarball was even built.

    So the property is stated the way it matters: whatever the manifest claims
    the run produced, the archive must carry.
    """
    run, _ = _make_run_with_structure(tmp_path)

    recorded = {
        "deg/results.parquet": "deg",
        "targets/candidates.parquet": "discover",
        "taxonomy/failure_taxonomy.parquet": "discover",
        "config.yaml": "discover",
    }
    manifest = {
        "run_id": "r",
        "name": "t",
        "stages": [
            {
                "name": stage,
                "outputs": [{"path": rel, "sha256": "d" * 64}],
            }
            for rel, stage in recorded.items()
        ],
    }
    (run / "run_manifest.jsonld").write_text(json.dumps(manifest), encoding="utf-8", newline="\n")

    crate = export_ro_crate(run, tmp_path / "out.crate.zip")
    with zipfile.ZipFile(crate) as zf:
        packed = set(zf.namelist())

    missing = sorted(rel for rel in recorded if rel not in packed)

    assert not missing, (
        f"the manifest records these outputs but the crate does not carry them: "
        f"{missing}. _PIPELINE_FILES decides what is deposited and does not "
        "cover them."
    )


def test_the_deposit_allowlist_is_not_silently_narrowed(tmp_path) -> None:
    """Guards the guard: shrinking the allowlist must fail something.

    The test above only notices a file it names. This one asserts the list still
    covers the artifacts a discovery run produces, so removing an entry cannot
    pass unnoticed just because no test happened to mention it.
    """
    from bindsight.export.ro_crate import _PIPELINE_FILES, _PIPELINE_TREES

    required = {
        "config.yaml",
        "run_manifest.jsonld",
        "deg/results.parquet",
        "targets/candidates.parquet",
        "design/metrics.jsonl",
        "design/prescreen.txt",
    }
    covered = set(_PIPELINE_FILES)
    still_missing = sorted(
        rel
        for rel in required
        if rel not in covered and not any(rel.startswith(f"{t}/") for t in _PIPELINE_TREES)
    )

    assert not still_missing, f"these artifacts are no longer deposited: {still_missing}"

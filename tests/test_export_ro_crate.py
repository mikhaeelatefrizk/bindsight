# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the RO-Crate export module."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pandas as pd
import pytest

from bindsight.export import export_ro_crate
from bindsight.provenance import (
    InputRef,
    OutputRef,
    StageRecord,
    ToolRef,
    new_manifest,
)


def _make_run(tmp_path: Path) -> Path:
    """Build a minimal but valid run directory."""
    run = tmp_path / "run"
    (run / "deg").mkdir(parents=True)
    (run / "targets").mkdir(parents=True)

    pd.DataFrame({"gene_id": ["g1"], "log2fc": [3.0]}).to_parquet(
        run / "deg" / "results.parquet", index=False
    )
    pd.DataFrame({"uniprot_id": ["P04626"], "rank": [1]}).to_parquet(
        run / "targets" / "candidates.parquet", index=False
    )

    counts = run / "counts.tsv"
    counts.write_text("g\ts\n1\t10\n")
    m = new_manifest(name="export-test")
    m.append(
        StageRecord(
            name="deg",
            tool=ToolRef(
                name="pydeseq2",
                version="0.5.4",
                license="MIT",
                repo_url="https://github.com/owkin/PyDESeq2",
                citation="10.1093/bioinformatics/btad547",
            ),
            inputs=[InputRef(role="counts", path="counts.tsv", sha256="0" * 64, bytes=10)],
            outputs=[OutputRef(role="deg", path="deg/results.parquet", sha256="1" * 64, bytes=100)],
        )
    )
    m.stages[0].mark_completed()
    m.write(run / "run_manifest.jsonld")
    return run


def test_export_ro_crate_produces_valid_zip(tmp_path: Path) -> None:
    run = _make_run(tmp_path)
    out = export_ro_crate(run)
    assert out.exists()
    assert out.suffix == ".zip"

    with zipfile.ZipFile(out) as zf:
        names = set(zf.namelist())
        assert "ro-crate-metadata.json" in names
        assert "software.bib" in names
        assert "deg/results.parquet" in names
        assert "targets/candidates.parquet" in names
        assert "run_manifest.jsonld" in names

        # Metadata is valid JSON-LD
        meta = json.loads(zf.read("ro-crate-metadata.json"))
        assert "@context" in meta
        assert "@graph" in meta
        graph = meta["@graph"]
        assert any(node.get("@type") == "Dataset" for node in graph)

        # software.bib references the upstream tool used
        bib = zf.read("software.bib").decode()
        assert "pydeseq2" in bib.lower()
        assert "@software" in bib


def test_export_ro_crate_custom_out_path(tmp_path: Path) -> None:
    run = _make_run(tmp_path)
    out = export_ro_crate(run, tmp_path / "elsewhere" / "my.crate.zip")
    assert out == tmp_path / "elsewhere" / "my.crate.zip"
    assert out.exists()


def test_export_ro_crate_missing_run_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        export_ro_crate(tmp_path / "nope")


def test_export_ro_crate_omits_missing_artifacts(tmp_path: Path) -> None:
    """Crate only includes files that actually exist (graceful partial run)."""
    run = tmp_path / "skinny"
    (run / "deg").mkdir(parents=True)
    pd.DataFrame({"gene_id": ["g"], "log2fc": [1.0]}).to_parquet(
        run / "deg" / "results.parquet", index=False
    )
    out = export_ro_crate(run)
    with zipfile.ZipFile(out) as zf:
        names = set(zf.namelist())
        assert "deg/results.parquet" in names
        # No targets / epitopes — they shouldn't appear
        assert "targets/candidates.parquet" not in names


# ---------------------------------------------------------------------------
# The crate must reach the patients, not stop at the DEG table
# ---------------------------------------------------------------------------
def _make_run_with_external_counts(tmp_path: Path) -> tuple[Path, Path]:
    """A run whose cohort lives outside the run directory, as real runs do."""
    run = tmp_path / "run"
    (run / "deg").mkdir(parents=True)
    pd.DataFrame({"gene_id": ["g1"], "log2fc": [3.0]}).to_parquet(
        run / "deg" / "results.parquet", index=False
    )
    cohort = tmp_path / "study" / "kirc"
    cohort.mkdir(parents=True)
    counts = cohort / "counts.tsv.gz"
    counts.write_bytes(b"\x1f\x8b\x08\x00barcodes-live-here")
    design = cohort / "design.tsv"
    design.write_text("sample\tcase_barcode\tcondition\nT1\tTCGA-AA-0001\ttumor\n")

    m = new_manifest(name="external-inputs")
    m.append(
        StageRecord(
            name="deg",
            tool=ToolRef(
                name="pydeseq2",
                version="0.5.4",
                license="MIT",
                repo_url="https://github.com/owkin/PyDESeq2",
                citation="10.1093/bioinformatics/btad547",
            ),
            inputs=[
                InputRef(role="counts", path=str(counts), sha256="a" * 64, bytes=18),
                InputRef(role="design", path=str(design), sha256="b" * 64, bytes=52),
            ],
            outputs=[OutputRef(role="deg", path="deg/results.parquet", sha256="1" * 64, bytes=100)],
        )
    )
    m.stages[0].mark_completed()
    m.write(run / "run_manifest.jsonld")
    return run, counts


def test_the_crate_carries_a_cohort_stored_outside_the_run(tmp_path: Path) -> None:
    """Without the counts there are no case barcodes, and the chain breaks.

    The allowlist named counts.tsv.gz, but a run configured with inputs.counts
    pointing elsewhere keeps it outside the run directory, so the allowlist
    matched nothing and the exported crate stopped at the DEG table.
    """
    run, _ = _make_run_with_external_counts(tmp_path)
    out = export_ro_crate(run, tmp_path / "c.zip")
    with zipfile.ZipFile(out) as zf:
        names = set(zf.namelist())
        assert "inputs/counts.tsv.gz" in names
        assert "inputs/design.tsv" in names
        assert b"TCGA-AA-0001" in zf.read("inputs/design.tsv")


def test_a_carried_in_input_keeps_its_recorded_digest(tmp_path: Path) -> None:
    run, _ = _make_run_with_external_counts(tmp_path)
    out = export_ro_crate(run, tmp_path / "c.zip")
    with zipfile.ZipFile(out) as zf:
        graph = json.loads(zf.read("ro-crate-metadata.json"))["@graph"]
    entry = next(e for e in graph if e.get("@id") == "inputs/counts.tsv.gz")
    assert entry["sha256"] == "a" * 64
    assert entry["@type"] == "File"
    root = next(e for e in graph if e.get("@id") == "./")
    assert {"@id": "inputs/counts.tsv.gz"} in root["hasPart"]


def test_an_input_already_inside_the_run_is_not_duplicated(tmp_path: Path) -> None:
    """The allowlist already carries those; a second copy under inputs/ is noise."""
    from bindsight.export.ro_crate import _external_inputs

    run = _make_run(tmp_path)  # records counts.tsv at the run root
    assert _external_inputs(run) == []


def test_an_input_missing_from_this_machine_does_not_break_the_export(
    tmp_path: Path,
) -> None:
    """A crate that cannot be built at all is worse than one that says what is absent."""
    run, counts = _make_run_with_external_counts(tmp_path)
    counts.unlink()
    out = export_ro_crate(run, tmp_path / "c.zip")
    with zipfile.ZipFile(out) as zf:
        names = set(zf.namelist())
    assert "inputs/counts.tsv.gz" not in names
    assert "inputs/design.tsv" in names, "the input that is present must still travel"


# ---------------------------------------------------------------------------
# The crate is a citation record, so it must credit the right software
# ---------------------------------------------------------------------------
REPO = Path(__file__).resolve().parents[1]


class TestTheBibliographyCreditsTheToolsThatDidTheWork:
    """software.bib is deposited to Zenodo as the run's citation record. It named
    ``bindsight.design.rfdiff_mpnn`` and ``bindsight.validate.boltz2`` -- both
    bindsight's own wrappers, at bindsight's version, under bindsight's AGPL --
    so it credited none of RFdiffusion, ProteinMPNN or Boltz-2, and asserted a
    copyleft licence over BSD-3 and MIT work.
    """

    @staticmethod
    def _run_that_used_the_wrappers(tmp_path: Path) -> Path:
        """A run directory whose manifest names the design and validate tools.

        Built here rather than read from ``runs/join``. That directory is
        gitignored, so these tests skipped with "committed run not present"
        everywhere except the machine that produced it -- and what stopped being
        enforced was the attribution obligation itself: that ``software.bib``
        credits RFdiffusion, ProteinMPNN and Boltz-2, and that no upstream tool
        is relicensed under bindsight's AGPL. BSD-3 and MIT both require that
        credit, and the crate is the artifact a depositor points a licence
        question at.

        A skip reason that reads like an environment quirk, for a condition that
        is permanent everywhere but one laptop, is worse than a failure.
        """
        import json

        run = tmp_path / "run"
        run.mkdir()
        manifest = {
            "run_id": "r",
            "name": "attribution fixture",
            "stages": [
                {
                    "name": "design",
                    "tool": {"name": "bindsight.design.rfdiff_mpnn", "version": "0.3.0"},
                },
                {
                    "name": "validate",
                    "tool": {"name": "bindsight.validate.boltz2", "version": "0.3.0"},
                },
            ],
        }
        (run / "run_manifest.jsonld").write_text(
            json.dumps(manifest), encoding="utf-8", newline="\n"
        )
        return run

    def test_a_run_using_a_wrapper_cites_what_the_wrapper_ran(self, tmp_path: Path) -> None:
        from bindsight.export.ro_crate import _build_software_bib

        bib = _build_software_bib(self._run_that_used_the_wrappers(tmp_path))

        for tool in ("RFdiffusion", "ProteinMPNN", "Boltz-2"):
            assert tool in bib, f"software.bib does not credit {tool}"

    def test_no_upstream_tool_is_relicensed_as_bindsight(self, tmp_path: Path) -> None:
        """Attribution, not pedantry: BSD-3 and MIT both require it, and the
        crate is the artifact a depositor points a licence question at."""
        from bindsight.export.ro_crate import _build_software_bib

        bib = _build_software_bib(self._run_that_used_the_wrappers(tmp_path))

        for entry in bib.split("@software")[1:]:
            title = entry.split("title = {", 1)[1].split("}", 1)[0]
            licence = entry.split("license = {", 1)[1].split("}", 1)[0]
            if title.startswith("bindsight"):
                continue
            assert "AGPL" not in licence, (
                f"{title} is credited under {licence}; that is bindsight's licence, not this tool's"
            )

    def test_every_registry_licence_matches_the_licensing_document(self) -> None:
        """LICENSING.md is the authority and states when its upstream LICENSE
        files were last re-verified. A second copy of those terms in code is only
        safe while something checks the two agree.
        """
        from bindsight.export.ro_crate import _upstream_tools

        licensing = (REPO / "LICENSING.md").read_text(encoding="utf-8")
        checked = 0
        for entries in _upstream_tools().values():
            for entry in entries:
                row = [
                    line
                    for line in licensing.splitlines()
                    if line.startswith("|") and entry["url"] in line
                ]
                if not row:
                    continue  # not listed by URL; covered by the tools-table test
                checked += 1
                assert entry["license"].split(";")[0].strip() in row[0], (
                    f"{entry['name']} is cited as {entry['license']!r}, which does "
                    f"not appear in its LICENSING.md row:\n  {row[0]}"
                )
        assert checked >= 3, f"only {checked} registry entries cross-checked"

    def test_the_registry_pins_track_the_runner_constants(self) -> None:
        """A bumped commit pin must move the citation with it, not leave the
        crate citing a tree the run did not use."""
        from bindsight.export.ro_crate import _upstream_tools
        from bindsight.runners import tools as T

        entries = {e["name"]: e for es in _upstream_tools().values() for e in es}

        assert entries["RFdiffusion"]["version"] == T.RFDIFF_COMMIT
        assert entries["ProteinMPNN"]["version"] == T.PROTEINMPNN_COMMIT
        assert entries["BoltzGen"]["version"] == T.BOLTZGEN_COMMIT

    def test_every_shipped_designer_and_validator_has_a_citation(self) -> None:
        """Discovered from the plugin registries, so a backend added later cannot
        ship without one."""
        from bindsight.export.ro_crate import _upstream_tools

        registry = _upstream_tools()
        for module in ("design", "validate"):
            for name in _plugin_names(module):
                key = f"bindsight.{module}.{name}"
                assert key in registry, (
                    f"{key} runs upstream software with no citation entry, so a "
                    "crate from a run using it would credit only bindsight"
                )


def _plugin_names(module: str) -> list[str]:
    """Shipped plugin names, read from the entry-point table in pyproject."""
    import tomllib

    data = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    groups = data.get("project", {}).get("entry-points", {})
    group = groups.get(f"bindsight.{'designers' if module == 'design' else 'validators'}", {})
    return sorted(group)


class TestTheCrateDoesNotAssertItsOwnDigest:
    """`bindsight export` sealed the zip, hashed it, then wrote that hash into the
    run manifest -- a copy of which is already inside the zip. The crate's own
    manifest therefore named a digest that was not the crate's.
    """

    def test_the_export_stage_records_no_digested_crate(self, tmp_path: Path) -> None:
        import ast

        source = (REPO / "bindsight" / "cli.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (isinstance(func, ast.Attribute) and func.attr == "record"):
                continue
            kwargs = {kw.arg: kw.value for kw in node.keywords}
            name = kwargs.get("name")
            if not (isinstance(name, ast.Constant) and name.value == "export"):
                continue
            outputs = kwargs.get("outputs")
            assert isinstance(outputs, ast.Dict), "the export stage's outputs is not a literal"
            assert not outputs.keys, (
                "the export stage records a digested output again; a crate cannot "
                "contain its own sha256"
            )
            assert "notes" in kwargs, "the omission is unexplained in the manifest"
            return
        raise AssertionError("no export stage record found in the CLI")

    def test_the_note_tells_a_reader_where_the_digest_lives(self) -> None:
        source = (REPO / "bindsight" / "cli.py").read_text(encoding="utf-8")

        assert "SHA256SUMS" in source, (
            "nothing points the reader at where the crate's digest is published"
        )

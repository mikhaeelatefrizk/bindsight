# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The join: counts in, ranked binders out, with a chain back to the patients.

This is the project's central claim, and until now nothing exercised it. The
audit found that only ``bindsight run`` wrote provenance past ``discover``, so
following the documented Quickstart produced a run whose chain broke exactly
where the interesting half begins — and that no committed artifact demonstrated
the chain at all.

These tests drive the documented subcommand path on the mock backend and assert
the properties that make the chain a chain:

1. Every stage records itself, whichever command ran it.
2. Binder ids are unique across targets, because ``binder_id`` is the key the
   chain is walked by.
3. A mock result can never be mistaken for a real one, because the backend is
   part of the design cache key.
4. The exported crate carries the cohort, so the walk reaches actual patient
   barcodes rather than stopping at a DEG table.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pandas as pd
import pytest
from click.testing import CliRunner

from bindsight import cli

_STAGES = ("deg", "discover", "design", "validate", "rank", "report", "export")


def _tiny_cohort(root: Path) -> Path:
    """A two-patient paired cohort, small enough to run in a test."""
    genes = [f"ENSG{i:011d}" for i in range(60)]
    # ERBB2 and CA9, so the run has something a panel would recognise.
    genes[0], genes[1] = "ENSG00000141736", "ENSG00000107159"
    samples, conditions, cases = [], [], []
    for i in range(4):
        for cond in ("tumor", "normal"):
            samples.append(f"{cond}_{i}")
            conditions.append(cond)
            cases.append(f"TCGA-XX-{i:04d}")

    counts = pd.DataFrame(
        {
            s: [
                200 + 10 * int(c.split("-")[-1]) + (900 if (cond == "tumor" and g < 4) else 0)
                for g in range(len(genes))
            ]
            for s, cond, c in zip(samples, conditions, cases, strict=True)
        },
        index=genes,
    )
    counts.index.name = "gene_id"
    root.mkdir(parents=True, exist_ok=True)
    counts_path = root / "counts.tsv"
    counts.to_csv(counts_path, sep="\t")
    design = pd.DataFrame({"sample": samples, "condition": conditions, "case_barcode": cases})
    design.to_csv(root / "design.tsv", sep="\t", index=False)
    # A cohort provenance file, as the GDC fetcher writes: this is what carries
    # the patient barcodes the chain must reach.
    (root / "provenance.json").write_text(
        json.dumps(
            {
                "schema": "bindsight-gdc-cohort/1",
                "project": "TCGA-XX",
                "samples": [
                    {"sample": s, "condition": c, "case_barcode": b, "sample_barcode": f"{b}-01A"}
                    for s, c, b in zip(samples, conditions, cases, strict=True)
                ],
            }
        ),
        encoding="utf-8",
    )
    return counts_path


def _config(root: Path, out: Path) -> Path:
    """A discovery config over the tiny cohort, with every network gate off."""
    import yaml

    cfg = {
        "name": "join_test",
        "out_dir": str(out),
        "inputs": {"counts": str(root / "counts.tsv"), "design": str(root / "design.tsv")},
        "params": {
            "deg": {
                "design_formula": "~ case_barcode + condition",
                "contrast": ["condition", "tumor", "normal"],
                "fdr_threshold": 0.5,
                "log2fc_threshold": 0.5,
                "min_replicates": 2,
                "min_count": 0,
                "n_cpus": 1,
            },
            "target_discovery": {
                "require_surfy": False,
                "surfaceome_prefilter": False,
                "use_open_targets": False,
                "require_tractable_modality": [],
                "require_surface_bind_site": False,
                "top_n": 3,
            },
            "design": {},
            "validate": {},
            "rank": {},
        },
        "backend": "mock",
    }
    path = root / "config.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return path


@pytest.fixture(scope="module")
def joined_run(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Drive the documented Quickstart path end to end on the mock backend."""
    pytest.importorskip("pydeseq2")
    base = tmp_path_factory.mktemp("join")
    src = base / "cohort"
    _tiny_cohort(src)
    out = base / "run"
    config = _config(src, out)

    runner = CliRunner()
    # The design cache lives under the working directory, so isolate it.
    with runner.isolated_filesystem(temp_dir=base):
        result = runner.invoke(cli.main, ["discover", str(config), "--out", str(out)])
        assert result.exit_code == 0, result.output

        # The cohort deliberately stays where the config points, outside the run
        # directory, because that is where real cohorts live. This fixture used
        # to copy it in so the crate's allowlist could see it — which meant the
        # crate test verified its own setup step rather than the exporter, and
        # passed for months while real exports shipped with no cohort at all.
        # The exporter now resolves the inputs the manifest records.

        for args in (
            ["design", str(out), "--backend", "mock", "--trajectories", "2"],
            ["validate", str(out), "--backend", "mock"],
            ["rank", str(out)],
            ["report", str(out), "--format", "html"],
            ["export", str(out), "--out", str(base / "run.crate.zip")],
        ):
            result = runner.invoke(cli.main, args)
            assert result.exit_code == 0, f"{args[0]} failed: {result.output}"
    return out


class TestChainIsComplete:
    def test_every_stage_records_itself(self, joined_run: Path) -> None:
        """The documented subcommand path must produce the whole chain.

        Only ``bindsight run`` used to write provenance past ``discover``, so the
        Quickstart produced a manifest that stopped exactly where the design half
        begins.
        """
        manifest = json.loads((joined_run / "run_manifest.jsonld").read_text(encoding="utf-8"))
        recorded = [s["name"] for s in manifest.get("stages", [])]
        for stage in _STAGES:
            assert stage in recorded, f"{stage} left no provenance record"

    def test_no_stage_is_recorded_twice(self, joined_run: Path) -> None:
        """Re-running a stage replaces its record rather than accumulating one."""
        manifest = json.loads((joined_run / "run_manifest.jsonld").read_text(encoding="utf-8"))
        recorded = [s["name"] for s in manifest.get("stages", [])]
        assert len(recorded) == len(set(recorded))

    def test_every_stage_completed(self, joined_run: Path) -> None:
        manifest = json.loads((joined_run / "run_manifest.jsonld").read_text(encoding="utf-8"))
        for stage in manifest.get("stages", []):
            assert stage["status"] == "completed", f"{stage['name']}: {stage.get('error')}"


class TestBinderIdentity:
    def test_binder_ids_are_unique_across_targets(self, joined_run: Path) -> None:
        """binder_id is the key the chain is walked by, so it must be unique.

        The mock runner used to emit a fixed pair of ids for every target, which
        meant it could not exercise this invariant at all — a mock that permits
        the bug it exists to guard against.
        """
        validated = pd.read_parquet(joined_run / "validate" / "validated.parquet")
        assert len(validated) > 0
        assert validated["binder_id"].nunique() == len(validated)

    def test_each_binder_names_its_own_target(self, joined_run: Path) -> None:
        validated = pd.read_parquet(joined_run / "validate" / "validated.parquet")
        for binder_id, target in zip(
            validated["binder_id"], validated["target_uniprot"], strict=True
        ):
            assert str(binder_id).startswith(str(target)), binder_id

    def test_ranking_preserves_the_keys(self, joined_run: Path) -> None:
        ranking = pd.read_parquet(joined_run / "rank" / "ranking.parquet")
        assert ranking["binder_id"].nunique() == len(ranking)


class TestCrateReachesThePatients:
    @staticmethod
    def _crate(joined_run: Path) -> zipfile.ZipFile:
        return zipfile.ZipFile(joined_run.parent / "run.crate.zip")

    def test_crate_carries_the_cohort(self, joined_run: Path) -> None:
        """A crate that stops at the DEG table documents an analysis, not its origin.

        The cohort lives outside the run directory, as configured, so this is
        only satisfied by the exporter resolving what the manifest recorded.
        """
        names = set(self._crate(joined_run).namelist())
        assert "run_manifest.jsonld" in names
        for required in ("inputs/design.tsv", "inputs/provenance.json"):
            assert required in names, f"crate omits {required}"
        assert any(n.startswith("inputs/counts.tsv") for n in names), (
            "crate omits the counts matrix, so it carries no patients"
        )

    def test_the_walk_reaches_patient_barcodes(self, joined_run: Path) -> None:
        """From a ranked binder to the patients, using only what the crate carries."""
        crate = self._crate(joined_run)
        import io

        ranking = pd.read_parquet(io.BytesIO(crate.read("rank/ranking.parquet")))
        assert len(ranking) > 0
        target = str(ranking.iloc[0]["target_uniprot"])
        assert target

        cohort = json.loads(crate.read("inputs/provenance.json"))
        barcodes = {s["case_barcode"] for s in cohort["samples"]}
        assert barcodes, "the crate carries no patient barcodes"
        # The design table ties those barcodes to the samples the contrast used.
        design = pd.read_csv(io.BytesIO(crate.read("inputs/design.tsv")), sep="\t")
        assert set(design["case_barcode"]) <= barcodes


class TestCacheCannotConfuseBackends:
    def test_backend_changes_the_design_cache_key(self) -> None:
        """A mock result must never be returned for a real GPU run.

        The key previously covered the spec and the designer commits but not
        where the job executed, so a run on --backend mock and a later real run
        shared a cache entry.
        """
        from bindsight.design._common import _with_backend, make_cache_key
        from bindsight.design.protocol import DesignSpec

        spec = DesignSpec(
            target_uniprot="P04626",
            target_structure_path="missing.pdb",
            epitope_chain="A",
            epitope_residues=[1, 2],
            design_ranges=[(1, 10)],
            n_trajectories=2,
            seed=0,
        )
        base = make_cache_key(spec)
        assert _with_backend(base, "mock") != _with_backend(base, "kaggle")
        assert _with_backend(base, "mock") == _with_backend(base, "mock")

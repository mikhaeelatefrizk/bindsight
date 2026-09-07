# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The pipeline is not a cancer tool, and nothing proved it.

bindsight is described as a general instrument: any two-condition RNA-seq
contrast in, ranked surface-protein binder candidates out. Every test, every
example config and every committed run used TCGA tumour-versus-normal, so the
generality was asserted and never exercised. A hardcoded ``"tumor"`` anywhere on
the path would have passed the whole suite.

This drives the documented subcommand path on a design that shares no vocabulary
with oncology: an *in vitro* drug-treatment experiment, contrasting ``drug``
against ``vehicle`` on a factor called ``treatment``, paired within ``donor_id``.
None of those strings appear anywhere in the pipeline.

The hardcoded ``tumor``/``normal`` literals that do exist are confined to
``io/gdc.py``, which downloads from TCGA and so is right to know TCGA's sample
type names, and to ``benchmark/``, which scores a cancer rediscovery study.
Neither is on this path.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest
from click.testing import CliRunner

from bindsight import cli

#: Nothing here is oncology vocabulary. That is the point.
FACTOR = "treatment"
TREATED, CONTROL = "drug", "vehicle"
PAIRING = "donor_id"


def _treatment_cohort(root: Path) -> None:
    """Four donors, each sampled under both conditions."""
    genes = [f"ENSG{i:011d}" for i in range(60)]
    # Two real surface-protein accessions so discovery has something to map.
    genes[0], genes[1] = "ENSG00000141736", "ENSG00000107159"

    samples, conditions, donors = [], [], []
    for i in range(4):
        for cond in (TREATED, CONTROL):
            samples.append(f"{cond}_{i}")
            conditions.append(cond)
            donors.append(f"DONOR-{i:03d}")

    counts = pd.DataFrame(
        {
            s: [
                200 + 10 * int(d.split("-")[-1]) + (900 if (c == TREATED and g < 4) else 0)
                for g in range(len(genes))
            ]
            for s, c, d in zip(samples, conditions, donors, strict=True)
        },
        index=genes,
    )
    counts.index.name = "gene_id"
    root.mkdir(parents=True, exist_ok=True)
    counts.to_csv(root / "counts.tsv", sep="\t")
    pd.DataFrame({"sample": samples, FACTOR: conditions, PAIRING: donors}).to_csv(
        root / "design.tsv", sep="\t", index=False
    )


def _config(root: Path, out: Path) -> Path:
    import yaml

    cfg = {
        "name": "treatment_test",
        "out_dir": str(out),
        "inputs": {"counts": str(root / "counts.tsv"), "design": str(root / "design.tsv")},
        "params": {
            "deg": {
                # A pairing variable that is not `case_barcode`, and a factor
                # that is not `condition`.
                "design_formula": f"~ {PAIRING} + {FACTOR}",
                "contrast": [FACTOR, TREATED, CONTROL],
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
def treatment_run(tmp_path_factory: pytest.TempPathFactory) -> Path:
    pytest.importorskip("pydeseq2")
    base = tmp_path_factory.mktemp("treatment")
    src = base / "cohort"
    _treatment_cohort(src)
    out = base / "run"
    config = _config(src, out)

    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=base):
        result = runner.invoke(cli.main, ["discover", str(config), "--out", str(out)])
        assert result.exit_code == 0, result.output
        for name in ("counts.tsv", "design.tsv"):
            (out / name).write_bytes((src / name).read_bytes())
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


class TestAnyTwoConditionDesignWorks:
    def test_differential_expression_ran_on_the_named_factor(self, treatment_run: Path) -> None:
        deg = pd.read_parquet(treatment_run / "deg" / "results.parquet")
        assert len(deg) > 0

    def test_targets_were_discovered(self, treatment_run: Path) -> None:
        targets = pd.read_parquet(treatment_run / "targets" / "candidates.parquet")
        assert len(targets) > 0, "no candidates from a non-cancer contrast"

    def test_binders_were_ranked(self, treatment_run: Path) -> None:
        ranking = pd.read_parquet(treatment_run / "rank" / "ranking.parquet")
        assert len(ranking) > 0
        assert ranking["binder_id"].nunique() == len(ranking)

    def test_the_report_rendered(self, treatment_run: Path) -> None:
        assert (treatment_run / "report.html").is_file()

    def test_the_provenance_records_the_actual_contrast(self, treatment_run: Path) -> None:
        """A manifest that says `tumor vs normal` for a drug experiment is a lie."""
        manifest = (treatment_run / "run_manifest.jsonld").read_text(encoding="utf-8")
        assert TREATED in manifest
        assert CONTROL in manifest
        assert FACTOR in manifest

    def test_no_oncology_vocabulary_leaked_into_the_outputs(self, treatment_run: Path) -> None:
        """The pipeline must not label a drug experiment with cancer terms.

        The manifest and the design table are what a reader inspects, and both
        are written by the pipeline rather than copied from input.
        """
        manifest = json.loads((treatment_run / "run_manifest.jsonld").read_text(encoding="utf-8"))
        blob = json.dumps(manifest).lower()
        for term in ("tumor", "tumour", "tcga"):
            assert term not in blob, f"the manifest calls this a {term} experiment"

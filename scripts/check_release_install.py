# SPDX-License-Identifier: AGPL-3.0-or-later
"""Exercise an installed release outside the checkout, with synthetic counts.

Run with the wheel environment's Python and ``-I`` so a source checkout cannot
mask missing packaged modules or assets. This is a software smoke test, not
biological validation or a replacement for the recorded numerical audits.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from importlib.metadata import version
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi.testclient import TestClient
from packaging.version import Version

import bindsight
from bindsight.config import DEGParams
from bindsight.deg.inference import INFERENCE_ADAPTER_REVISION
from bindsight.deg.pydeseq2_runner import PyDESeq2Runner
from bindsight.report.web.app import create_app


def check(expected_version: str) -> None:
    """Require the installed package to fit counts and serve its bundled UI."""
    package = Path(bindsight.__file__).resolve()
    if not package.is_relative_to(Path(sys.prefix).resolve()):
        raise RuntimeError(f"Expected an installed wheel, imported {package}")
    if bindsight.__version__ != expected_version:
        raise RuntimeError(f"Expected {expected_version}, found {bindsight.__version__}")
    if Version(version("certifi")) < Version("2026.10.19"):
        raise RuntimeError("Installed certificate bundle predates the emSign fix")

    with tempfile.TemporaryDirectory(prefix="bindsight-release-smoke-") as temporary:
        root = Path(temporary)
        samples = [f"sample_{i}" for i in range(8)]
        rng = np.random.default_rng(101)
        counts = pd.DataFrame(
            rng.negative_binomial(20, 0.3, size=(200, 8)),
            index=[f"gene_{i}" for i in range(200)],
            columns=samples,
        )
        counts.iloc[:20, 4:] *= 3
        design = pd.DataFrame({"condition": ["control"] * 4 + ["treated"] * 4}, index=samples)
        counts.to_csv(root / "counts.tsv", sep="\t")
        design.to_csv(root / "design.tsv", sep="\t")
        params = DEGParams(
            design_formula="~ condition",
            contrast=["condition", "treated", "control"],
            min_count=0,
            n_cpus=1,
        )
        metrics = PyDESeq2Runner(params).run(
            root / "counts.tsv", root / "design.tsv", root / "result.parquet"
        )
        result = pd.read_parquet(root / "result.parquet")
        if len(result) != 200 or not np.isfinite(result["log2fc"]).all():
            raise RuntimeError("The installed numerical pipeline did not produce a valid table")
        with TestClient(create_app(run_root=root / "runs")) as client:
            for path in ("/", "/workbench", "/static/workbench.js", "/static/workbench.css"):
                response = client.get(path)
                if response.status_code != 200 or not response.content:
                    raise RuntimeError(f"Installed UI request failed: {path}")
        print(
            json.dumps(
                {
                    "version": bindsight.__version__,
                    "python": sys.version.split()[0],
                    "certifi": version("certifi"),
                    "inference_adapter": INFERENCE_ADAPTER_REVISION,
                    "synthetic_genes_tested": metrics["n_genes_tested"],
                    "installed_ui": "passed",
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-version", required=True)
    check(parser.parse_args().expected_version)

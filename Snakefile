# bindsight — Snakemake DAG
# ============================================================================
# A Snakemake front-end over the same bindsight pipeline functions the Click
# CLI uses (each rule's script calls into `bindsight.*`), so `snakemake` and the
# `bindsight` CLI are two equivalent ways to run the pipeline end-to-end:
# discover -> design -> validate -> rank -> report (+ provenance manifest).
#
# Usage (needs a headless backend for the GPU stages — mock/modal/local_docker/
# kaggle; use the CLI's `--backend colab` for interactive Colab runs):
#   snakemake --configfile examples/tcga_luad.yaml --cores 4 --use-conda
#   snakemake --configfile examples/demo/config.yaml --config backend=mock --cores 4
#   snakemake --configfile examples/tcga_luad.yaml --until discover --cores 4
# ============================================================================

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
configfile: "examples/tcga_luad.yaml"

OUT = Path(config.get("out_dir", "runs/default"))
RUN_NAME = config.get("name", OUT.name)

# The conda envs are kept lean — one per stage — so users only install what
# they actually need.
ENV_DISCOVER = "envs/discover.yaml"
ENV_DESIGN   = "envs/design.yaml"     # v0.1
ENV_VALIDATE = "envs/validate.yaml"   # v0.1
ENV_REPORT   = "envs/report.yaml"     # v0.1

# ---------------------------------------------------------------------------
# Top-level target
# ---------------------------------------------------------------------------
rule all:
    input:
        OUT / "report.html",
        OUT / "run_manifest.jsonld",

# ---------------------------------------------------------------------------
# Discovery half (CPU only)
# ---------------------------------------------------------------------------
rule deg:
    input:
        counts = config["inputs"]["counts"],
        design = config["inputs"]["design"],
    output:
        deg_table = OUT / "deg" / "results.parquet",
        manifest_fragment = OUT / "deg" / "manifest_fragment.jsonld",
    params:
        deg = config["params"]["deg"],
    conda:
        ENV_DISCOVER
    log:
        OUT / "deg" / "log.txt",
    script:
        "scripts/run_deg.py"


rule discover:
    input:
        deg_table = OUT / "deg" / "results.parquet",
    output:
        targets = OUT / "targets" / "candidates.parquet",
        epitopes = OUT / "epitopes" / "epitopes.parquet",
        manifest_fragment = OUT / "discover" / "manifest_fragment.jsonld",
    params:
        target = config["params"]["target_discovery"],
    conda:
        ENV_DISCOVER
    log:
        OUT / "discover" / "log.txt",
    script:
        "scripts/run_discover.py"


# ---------------------------------------------------------------------------
# Design half (GPU; dispatched to the selected runner backend).
# ---------------------------------------------------------------------------
rule design:
    input:
        epitopes = OUT / "epitopes" / "epitopes.parquet",
    output:
        results = OUT / "design" / "results.tar.gz",
        manifest_fragment = OUT / "design" / "manifest_fragment.jsonld",
    params:
        design = config["params"]["design"],
        backend = config.get("backend", "colab"),
    log:
        OUT / "design" / "log.txt",
    script:
        "scripts/run_design.py"


rule validate:
    input:
        design_results = OUT / "design" / "results.tar.gz",
    output:
        validated = OUT / "validate" / "validated.parquet",
        manifest_fragment = OUT / "validate" / "manifest_fragment.jsonld",
    params:
        validate = config["params"]["validate"],
        backend = config.get("backend", "colab"),
    log:
        OUT / "validate" / "log.txt",
    script:
        "scripts/run_validate.py"


rule rank:
    input:
        validated = OUT / "validate" / "validated.parquet",
        targets = OUT / "targets" / "candidates.parquet",
    output:
        ranking = OUT / "rank" / "ranking.parquet",
        manifest_fragment = OUT / "rank" / "manifest_fragment.jsonld",
    params:
        rank = config["params"].get("rank", {}),
    log:
        OUT / "rank" / "log.txt",
    script:
        "scripts/run_rank.py"


rule report:
    input:
        ranking = OUT / "rank" / "ranking.parquet",
        targets = OUT / "targets" / "candidates.parquet",
        epitopes = OUT / "epitopes" / "epitopes.parquet",
    output:
        html = OUT / "report.html",
        manifest_fragment = OUT / "report" / "manifest_fragment.jsonld",
    log:
        OUT / "report" / "log.txt",
    script:
        "scripts/run_report.py"


# ---------------------------------------------------------------------------
# Provenance assembly — stitches all per-rule manifest fragments into a
# single run_manifest.jsonld and (optionally) packages an RO-Crate zip.
# ---------------------------------------------------------------------------
rule manifest:
    input:
        fragments = expand(
            OUT / "{stage}" / "manifest_fragment.jsonld",
            stage=["deg", "discover", "design", "validate", "rank", "report"],
        ),
    output:
        manifest = OUT / "run_manifest.jsonld",
    script:
        "scripts/assemble_manifest.py"

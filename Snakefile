# xpr2bind — Snakemake DAG
# ============================================================================
# This Snakefile is the source of truth for pipeline execution. The Click CLI
# (`xpr2bind discover` etc.) is a thin wrapper that calls Snakemake with
# `--until <rule>` and a config that this file consumes.
#
# Usage:
#   snakemake --configfile examples/tcga_luad.yaml --cores 4 --use-conda
#   snakemake --configfile examples/tcga_luad.yaml --until discover --cores 4
#
# v0.0.x scope: only the `discover` rule is wired up. Design / validate /
# rank / report rules ship as stubs.
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
# Design half (GPU offloaded). Stubs in v0.0.x.
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

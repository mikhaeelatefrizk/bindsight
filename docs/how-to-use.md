---
description: Install bindsight and run it end to end — RNA-seq counts to ranked surface-antigen targets on CPU, then RFdiffusion / ProteinMPNN / Boltz-2 binder design on a GPU backend, with full PROV-O / RO-Crate provenance.
---

# How to use `bindsight`

> Practical end-to-end walkthrough. The discovery half (RNA-seq → ranked
> surface-antigen targets) runs on CPU; the design half (RFdiffusion →
> ProteinMPNN → Boltz-2) runs on a GPU backend you choose.

---

## Install

`bindsight` is installed from source (not yet on PyPI):

```bash
git clone https://github.com/mikhaeelatefrizk/bindsight
cd bindsight
python -m venv .venv
source .venv/bin/activate          # macOS / Linux
# .venv\Scripts\activate            # Windows
pip install -e ".[discover,report]"
```

Then:

```bash
bindsight --version           # 0.1.0
bindsight doctor              # check the install + cache state
bindsight verify-licenses     # see the per-component license inventory
```

`bindsight doctor` is the first thing to run if anything looks off later — it
tells you what's installed, what's cached, and what's missing.

Optional extras: `.[runners]` (Modal/Kaggle clients), `.[workflow]` (the
Snakemake front-end). `.[all]` installs everything.

---

## Quick start: the demo

```bash
bindsight demo
```

This runs the full discovery half on a **real TCGA-BRCA** tumor-vs-adjacent-normal
cohort: on first run it auto-downloads the cohort (STAR-Counts) from the NIH/GDC
open-access API, populates the full SURFY surfaceome, runs real DESeq2 + Open
Targets enrichment, and writes a ranked candidate table + a self-contained HTML
report. First run needs internet (cohort + SURFY cached afterwards) and takes a
few minutes; CPU-only, no GPU.

---

## Concept: a "run"

A *run* is one invocation of the pipeline against one config, producing one
self-contained output directory:

```
runs/my_run/
├── deg/results.parquet           # one row per gene (DESeq2)
├── targets/candidates.parquet    # one row per (gene, UniProt) candidate
├── epitopes/epitopes.parquet     # one row per top-N target
├── design/                       # binder designs (bindsight design)
├── validate/validated.parquet    # structure + affinity metrics (bindsight validate)
├── rank/ranking.parquet          # composite-ranked binders (bindsight rank)
├── report.html                   # self-contained HTML report (bindsight report)
└── run_manifest.jsonld           # PROV-O audit trail of every stage
```

`run_manifest.jsonld` is what makes the run reproducible. Treat it like a lab
notebook entry: never edit, always keep.

---

## Two front-ends, one pipeline

You can drive the exact same pipeline two ways:

- **CLI** (recommended): `bindsight discover|design|validate|rank|report|export`,
  or `bindsight run <config>` for the whole chain.
- **Snakemake** (optional, `pip install -e ".[workflow]"`): `snakemake
  --configfile <config> --cores 4`. Each rule calls the same `bindsight.*`
  functions, so artifacts are identical.

---

## Step 1 — Author a config

Configs are YAML validated by `bindsight.config.RunConfig` (validation runs at
load time, so a typo fails loudly *before* any compute). Start from an example:

```bash
cp examples/tcga_luad.yaml my_config.yaml
```

A minimal config:

```yaml
name: my_first_run
out_dir: runs/my_first_run

inputs:
  counts: data/my_counts.tsv.gz        # gene × sample, integer counts
  design: data/my_design.tsv           # sample, condition, ...
  # Optional: auto-download a real TCGA cohort if the files above are absent:
  # download: { project: TCGA-BRCA, n_tumor: 20, n_normal: 20 }

params:
  deg:
    design_formula: "~ condition"
    contrast: ["condition", "tumor", "normal"]
    fdr_threshold: 0.05
    log2fc_threshold: 1.0
  target_discovery:
    require_surfy: true
    use_open_targets: true
    require_tractable_modality: ["Antibody"]
    max_safety_events: 5
    top_n: 10

backend: modal     # GPU backend for the design half: modal | local_docker | kaggle | colab | mock
```

---

## Step 2 — Provide the data

Two TSVs (the counts may be gzipped):

**counts** — gene IDs in column 1, samples in the rest, integer counts:

```
gene_id          sample_001  sample_002  ...
ENSG00000141736  1245        1389        ...
```

**design** — sample IDs in column 1, factors after; the `condition` column (or
whatever your `design_formula` references) must contain the `contrast` levels:

```
sample        condition
sample_001    tumor
normal_001    normal
```

**Where to get real data:** set `inputs.download` to auto-fetch a TCGA cohort
from NIH/GDC (see `bindsight/io/gdc.py`), or bring your own aligner output
(STAR/Salmon/kallisto counts), or pull pre-aligned counts from
[recount3](https://rna.recount.bio/).

---

## Step 3 — Reference data (auto on first use)

`bindsight` caches external data under your OS cache dir; `bindsight doctor`
shows the state. On first real run these populate automatically:

- **SURFY surfaceome** (full ~2,886-protein list) — downloaded from
  [wlab.ethz.ch/surfaceome](https://wlab.ethz.ch/surfaceome) (CC-BY).
- **AlphaFoldDB** structures + **Open Targets** evidence — fetched per target.
- **SURFACE-Bind** targetable-site lookup is a roadmap item; until then the
  design step targets the whole surface (set `require_surface_bind_site: false`,
  the default).

No manual setup is required for a standard run.

---

## Step 4 — Discover (CPU)

```bash
bindsight discover my_config.yaml --out runs/my_first_run
```

DESeq2 → surfaceome filter → Open Targets enrichment → AlphaFoldDB structures →
`candidates.parquet` + `epitopes.parquet` + `run_manifest.jsonld`. Inspect:

```bash
python -c "import pandas as pd; print(pd.read_parquet('runs/my_first_run/targets/candidates.parquet').head())"
```

---

## Step 5 — Design + validate (GPU)

```bash
# Estimate cost first (no GPU needed):
bindsight design runs/my_first_run --backend modal --dry-run

# Run it: RFdiffusion → ProteinMPNN → Boltz-2 on the chosen backend
bindsight design   runs/my_first_run --backend modal --designer rfdiff_mpnn --trajectories 50
bindsight validate runs/my_first_run
```

The GPU work runs in `bindsight.runners.job_exec` on the backend you pick:

| Backend | Cost | When to use |
|---|---|---|
| `colab` | Free (T4) / Pro (A100) | Writes a ready-to-run notebook you execute in Colab |
| `kaggle` | Free (T4×2, quota) | Headless via the Kaggle API |
| `modal` | ~$0.6–4/GPU-hr | Headless cloud GPUs, no queue |
| `local_docker` | Your hardware | A local NVIDIA GPU (native or Docker) |
| `mock` | Free, instant | CI / testing (mock results only) |

Designers: `rfdiff_mpnn` (default), `bindcraft`, `boltzgen`. Validators:
`boltz2` (default), `chai1r`, `af2_ig` (non-commercial AF2 weights — a banner is
shown). `--dry-run` always works without a GPU.

---

## Step 6 — Rank, report, export

```bash
bindsight rank   runs/my_first_run
bindsight report runs/my_first_run --format html
bindsight export runs/my_first_run --format ro-crate --out runs/my_first_run.crate.zip
```

The HTML report is a single self-contained file (embedded volcano plot, ranked
tables, and the full PROV-O manifest). The RO-Crate zip is ready for Zenodo /
Figshare deposit. `bindsight report --format streamlit` launches an interactive
dashboard instead.

Run the whole chain at once with `bindsight run my_config.yaml --out runs/x`
(CPU stages always run; GPU stages run on the configured headless backend).

---

## Step 7 — Benchmark against the held-out set

```bash
bindsight benchmark runs/my_first_run --known-antigens benchmarks/known.tsv --out bench.html
```

Scores how well the run rediscovers the literature-validated known antigens in
`benchmarks/` (recall@k, per-antigen ranks). See `benchmarks/PROVENANCE.md`.

---

## Reproducibility

1. Commit the config YAML and the `run_manifest.jsonld`.
2. A collaborator runs the same config (pin the Docker image for byte-identical
   environments).
3. Compare manifests — SHA-256s of every artifact match.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `dep: pydeseq2 = not installed` in `doctor` | `pip install -e ".[discover]"` |
| config `validation error` | Read it — Pydantic names the exact field |
| `samples in counts but not design` | Sample IDs must match across both files |
| `AlphaFoldDB has no model for X` | Expected for some accessions; the row is tagged and the run continues |
| design `nothing to do` | Run `discover` first so `epitopes.parquet` (with structures) exists |
| Modal/Kaggle "install the runners extra" | `pip install -e ".[runners]"` + provide credentials |

---

## Learn more

- [What is bindsight?](what-is-bindsight.md) · [Use cases](use-cases.md) ·
  [Designing on Colab](colab-design-howto.md)
- [ARCHITECTURE.md](../ARCHITECTURE.md) · [LICENSING.md](../LICENSING.md) ·
  [CONTRIBUTING.md](../CONTRIBUTING.md)

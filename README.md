# bindsight

> **Expression → Binder.** The first open-source pipeline that takes RNA-seq counts and outputs ranked de novo protein binder candidates, with full provenance back to the patient cohort.

[![HF Space](https://img.shields.io/badge/%F0%9F%A4%97%20HF%20Space-bindsight-yellow.svg)](https://huggingface.co/spaces/Mikhaeelatefrizk/bindsight)
[![Open in Streamlit](https://static.streamlit.io/badges/streamlit_badge_black_white.svg)](https://bindsight.streamlit.app/)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.20121496.svg)](https://doi.org/10.5281/zenodo.20121496)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python: 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![CI](https://github.com/mikhaeelatefrizk/bindsight/actions/workflows/ci.yml/badge.svg)](https://github.com/mikhaeelatefrizk/bindsight/actions/workflows/ci.yml)
[![Workflow: Snakemake](https://img.shields.io/badge/workflow-Snakemake-brightgreen.svg)](https://snakemake.github.io/)

## 👉 Try it live

**Primary** (Hugging Face Space, 16 GB CPU): **[huggingface.co/spaces/Mikhaeelatefrizk/bindsight](https://huggingface.co/spaces/Mikhaeelatefrizk/bindsight)**
**Mirror** (Streamlit Community Cloud, 1 GB CPU): [bindsight.streamlit.app](https://bindsight.streamlit.app/)

Zero install — runs in your browser. Click the **Demo** tab and watch the **discovery half** surface antibody-tractable cell-surface antigens from a **real TCGA breast-cancer cohort** (NIH/GDC), with full provenance. (Binder *design* and *validation* are GPU-only — you run those locally via Modal / Docker / Kaggle / Colab, so they don't execute in the browser.)

> Both hosts are free-tier and will sleep after several days without traffic; a GitHub Actions cron pings both URLs every 6 hours so the next visitor lands on a warm container. If you hit either link after a long quiet stretch, give the wake-up screen 30–60 s and reload once.

> 🚀 **v0.1.0** — discovery half end-to-end on CPU (real TCGA data); design + validation run end-to-end on a GPU backend (Modal / local Docker / Kaggle / Colab); web UI deployed on Streamlit Cloud.

**New here?** → [What is bindsight?](docs/what-is-bindsight.md) (5-min read) · [How to use it](docs/how-to-use.md) · [Use cases](docs/use-cases.md) · [Designing on Colab](docs/colab-design-howto.md)

---

## Three ways to try it

### 1. Web app — [Hugging Face Space](https://huggingface.co/spaces/Mikhaeelatefrizk/bindsight) (zero install) · [Streamlit mirror](https://bindsight.streamlit.app/)

Anyone visiting either URL above gets:
- The Home page with what bindsight is
- A **Demo** button that runs the discovery half live and renders a report
- A **Run on my data** page (upload counts.tsv + design.tsv → get results)
- A **Browse a run** page to inspect any output directory

The Hugging Face Space is the primary mirror (16 GB CPU). The Streamlit Cloud deploy at `bindsight.streamlit.app` is the same app on smaller free-tier infrastructure (1 GB CPU). Both hosts sleep after several days of inactivity; a 6-hourly GitHub Actions ping keeps them warm, but the very first visit after a long quiet period can still take ~30–120 s to wake.

### 2. Local web app (one command)

```bash
pip install -e ".[discover,report]"
bindsight ui
# → opens http://localhost:8501 with the same multi-page interface
```

### 3. CLI

```bash
bindsight demo
```

Runs the full discovery half on a **real TCGA-BRCA tumor-vs-adjacent-normal cohort** auto-downloaded from NIH/GDC, and produces a real HTML report you can open in a browser. The pipeline discovers antibody-tractable cell-surface antigens over-expressed in tumor — entirely from RNA-seq counts, with full provenance (well-known targets such as ERBB2/HER2 surface among the candidates when their signal is present). First run needs internet (cohort + SURFY downloaded, then cached) and takes a few minutes of real DESeq2 + enrichment; CPU-only, no GPU.

```
$ bindsight demo
╭──────────────── Demo run ────────────────╮
│ Real TCGA-BRCA tumor-vs-adjacent-normal  │
│ cohort (NIH/GDC). Discovers antibody-    │
│ tractable cell-surface antigens, with    │
│ full provenance.                         │
╰──────────────────────────────────────────╯
INFO  GDC: downloading TCGA-BRCA cohort (20 tumor + 20 normal)…
INFO  SURFY cache empty; populating the full surfaceome list (2886)
INFO  DEGs: 17019 total, 4011 significant; enriching top 300 up-regulated
INFO  surfaceome filter: 300 → 42
INFO  wrote runs/demo/report.html
╭───────────── bindsight demo ─────────────╮
│ Demo complete!                           │
│ Report HTML: runs/demo/report.html       │
╰──────────────────────────────────────────╯
```

---

## Why this exists

Two ecosystems in computational biology operate side-by-side and barely talk to each other:

- **Genomics** (DESeq2, edgeR, Seurat, scanpy, TCGA, recount3) stops at *"here are the interesting genes."*
- **Protein design** (RFdiffusion, ProteinMPNN, BindCraft, BoltzGen, AlphaFold, Boltz-2) starts from *"given a target..."*

The bridge between them — *"this gene is up in disease, low in healthy tissue, surface-exposed, has a known targetable site, here is a docked binder seed and a designed binder ranked by predicted affinity, with the receipts back to the patient cohort"* — is missing. People build it ad-hoc, per project, never reproducibly. **bindsight ships that bridge as one tool.**

## What it does

```
  RNA-seq counts (bulk or sc)                       Designed protein binders
              │                                              ▲
              │                                              │
              ▼                                              │
   Differential expression  ──►  Surface-exposed  ──►  De novo backbone
   (pydeseq2 or DESeq2)         (SURFY)              (RFdiffusion / BindCraft / BoltzGen)
                                     │                       │
                                     ▼                       ▼
                              Targetable sites          Sequence design
                              (SURFACE-Bind, v0.2)      (ProteinMPNN)
                                     │                       │
                                     ▼                       ▼
                              AlphaFoldDB structure     Affinity + structure
                                                        validation
                                                        (Boltz-2 / Chai-1r)
                                                              │
                                                              ▼
                                                  Multi-objective ranking
                                                              │
                                                              ▼
                                       HTML report + RO-Crate (Zenodo)
                                       with full PROV-O provenance
```

## Who it's for

- **Translational researchers** who want a free, reproducible "data → designed binder" pipeline.
- **Clinical biologists** who need an audit trail back from a binder to the patient cohort.
- **Method developers** who want a held-out evaluation harness (rediscovery of known antigens) to benchmark new designers/validators.
- **Pharma early-discovery teams** who want an open comparator they can extend with proprietary designers via the plugin interface.

## What's distinctive

| | Existing protein-design tools | bindsight |
|---|---|---|
| Input | Target structure | RNA-seq counts |
| Provenance | PDB + maybe a log | PROV-O JSON-LD + RO-Crate, audit trail to patient cohort |
| Hardware | HPC assumed | CPU laptop + offload to free Colab / Modal / Kaggle |
| Cost-awareness | None | `--dry-run` estimates GPU $ before running |
| Negative results | Discarded | Catalogued (`failure_taxonomy.parquet`) |
| Citability | Code dump | DOI per release, JSON-Schema-validated outputs, JOSS-style |

For the full landscape comparison, see [ARCHITECTURE.md](ARCHITECTURE.md#8-comparison-vs-existing-tools).

## What works today (v0.1.0)

| Capability | Status | How to try |
|---|---|---|
| **Web UI** — multi-page Streamlit app (Home / Demo / Run on my data / Browse / About) | ✅ ready | `bindsight ui`  *or*  Streamlit Cloud |
| **`bindsight demo`** — full discovery on shipped example + paper-style report | ✅ ready | `bindsight demo` |
| **`bindsight discover`** — your own RNA-seq cohort → ranked targets | ✅ ready | `bindsight discover my.yaml --out runs/x` |
| **`bindsight rank`** — multi-objective composite scoring of validated binders | ✅ ready | `bindsight rank runs/x` |
| **`bindsight report --format html`** — paper-style HTML, embedded volcano + tables + provenance | ✅ ready | `bindsight report runs/x` |
| **`bindsight report --format streamlit`** — interactive dashboard for one run | ✅ ready | `bindsight report runs/x --format streamlit` |
| **`bindsight run`** — full pipeline orchestrator (discover → design → validate → rank → report → export) | ✅ ready | `bindsight run my.yaml --out runs/x` |
| **`bindsight export`** — RO-Crate zip for Zenodo deposit | ✅ ready | `bindsight export runs/x --out runs/x.crate.zip` |
| **`bindsight design`** — RFdiffusion + ProteinMPNN + Boltz-2 (and BindCraft / BoltzGen / Chai-1r / AF2-IG) run end-to-end on a GPU backend | ✅ ready | `bindsight design runs/x --backend modal` (or `local_docker` / `kaggle` / `colab`) |
| **`bindsight design --dry-run`** — GPU cost estimate for any backend | ✅ ready | `bindsight design runs/x --backend modal --dry-run` |
| **`bindsight validate`** — materialise structure/affinity metrics → `validated.parquet` | ✅ ready | `bindsight validate runs/x` |
| **`bindsight benchmark`** — score rediscovery of the held-out known antigens (recall@k) | ✅ ready | `bindsight benchmark runs/x --known-antigens benchmarks/known.tsv` |
| **Snakemake front-end** — same pipeline as the CLI, end-to-end | ✅ ready | `snakemake --configfile my.yaml --cores 4` (`pip install -e ".[workflow]"`) |
| **`bindsight doctor`** — diagnose deps, caches, vendored data | ✅ ready | `bindsight doctor` |
| **`bindsight verify-licenses`** — per-component license inventory | ✅ ready | `bindsight verify-licenses` |

> **Note on GPU stages.** The design/validation models require CUDA, so they
> run on the GPU backend you choose (Modal / local Docker / Kaggle, or a
> generated Colab notebook), not on the CPU host. The held-out evaluation set
> lives in [`benchmarks/`](benchmarks/) with full provenance.

## Status & roadmap

- ✅ **v0.1.0** (current) — discovery on real TCGA data; full design half (RFdiffusion + ProteinMPNN + Boltz-2, plus BindCraft / BoltzGen / Chai-1r / AF2-IG) on Modal / local Docker / Kaggle / Colab; rank + report + export; benchmark + held-out eval set; CLI **and** Snakemake front-ends; web UI.
- ✅ **Rediscovery validation** — the discovery half, run on six real indication-matched TCGA cohorts, resurfaces **ERBB2 at rank 4** in HER2-enriched breast cancer (via PAM50 subtype stratification — versus rank 25 in the unsplit BRCA cohort, where averaging across subtypes dilutes the HER2 signal) and is specific (non-over-expressed antigens such as EGFR/CEA are correctly not surfaced). Reproducible artifacts in [`benchmarks/validation/`](benchmarks/validation/RESULTS.md); write-up in [`paper/validation/`](paper/validation/manuscript.md).
- ✅ **De novo binder design validated** — the design half (RFdiffusion → ProteinMPNN → Boltz-2) run on a **free Kaggle Tesla P100** produced **20 real binders** against the ERBB2 extracellular **domain IV** (the clinically validated trastuzumab epitope): mean **ipTM 0.60**, best **0.83**, and **40 %** of designs pass the ipTM ≥ 0.65 success bar — at **$0**, no local GPU. Designs (PDB + FASTA) and per-design metrics in [`benchmarks/designer_benchmark/RESULTS.md`](benchmarks/designer_benchmark/RESULTS.md); reproduce on a free GPU via [`RUN_FREE_GPU.md`](benchmarks/designer_benchmark/RUN_FREE_GPU.md).
- ⏳ **v0.2.0** — single-cell RNA-seq input, async (non-blocking) Modal job submission, and extending the [designer benchmark](benchmarks/designer_benchmark/DESIGNER_BENCHMARK.md) from the committed `rfdiff_mpnn` arm to the full three-way comparison (BindCraft / BoltzGen need ≥24–32 GB GPUs, so those arms run on paid backends). (SURFACE-Bind targetable-site lookup is now implemented — it reads a vendored data tree and falls back to whole-surface design when the data isn't present.)
- ⏳ **v1.0.0** — JOSS submission; multi-modal tumor-selectivity scoring (single-cell + co-expression + immunopeptidomics) to extend discovery beyond bulk differential expression.

See [ARCHITECTURE.md § Phased Roadmap](ARCHITECTURE.md#11-phased-roadmap) for details.

## Install

`bindsight` is not yet on PyPI. Install from source (Windows / macOS / Linux,
Python 3.11+):

```bash
git clone <repo-url> bindsight
cd bindsight
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate

pip install -e ".[dev,discover,report]"
bindsight --version
bindsight doctor                # confirm install is clean
bindsight demo                  # run the 60-second demo
```

For Conda users, `envs/discover.yaml` provides the same set of dependencies:

```bash
mamba env create -f envs/discover.yaml
mamba activate bindsight-discover
pip install -e ".[dev,report]"
```

## Quickstart

```bash
# 1. Discover targets from a TCGA cohort (CPU only, ~10 minutes on a laptop)
bindsight discover examples/tcga_luad.yaml --out runs/luad_v01

# 2. Inspect the discovered targets
bindsight report runs/luad_v01 --format html
open runs/luad_v01/report.html

# 3. (v0.1+) Design binders for the top 5 targets via Colab GPU
bindsight design runs/luad_v01 --backend colab --trajectories 50

# 4. (v0.1+) Validate with Boltz-2
bindsight validate runs/luad_v01 --backend colab --validator boltz2

# 5. (v0.1+) Rank, report, export as RO-Crate
bindsight rank runs/luad_v01
bindsight report runs/luad_v01 --format html --include-binders
bindsight export runs/luad_v01 --format ro-crate --out runs/luad_v01.crate.zip
```

## Repository layout

```
bindsight/                 # Python package
├── io/                   # Parquet, FASTA, PDB, mmCIF, manifest readers
├── deg/                  # pydeseq2 wrapper (+ optional R bridge)
├── targets/              # Open Targets client + bundled ENSG→UniProt fallback
├── surfaceome/           # SURFY filter + SURFACE-Bind client
├── structures/           # AlphaFoldDB + RCSB/PDBe fetch
├── epitopes/             # SURFACE-Bind site lookup; fpocket fallback (v0.2)
├── design/               # Designer plugin interface
├── runners/              # Colab / Modal / Kaggle / local-Docker adapters
├── validate/             # Boltz-2 default; Chai-1r, AF2-IG opt-in
├── rank/                 # Multi-objective scoring
├── benchmark/            # Rediscovery + designer-benchmark scoring harness
├── provenance/           # PROV-O JSON-LD schema + RO-Crate emitter
├── report/               # HTML report template + Streamlit app
└── cli.py                # Click entrypoint

envs/                     # Conda environment files (one per stage)
examples/                 # Example pipeline configs (TCGA-LUAD, etc.)
benchmarks/               # Held-out known-antigen eval set + validation & designer-benchmark harnesses
paper/                    # JOSS + bioRxiv manuscripts and the validation write-up
data/                     # Local cache for auto-downloaded TCGA cohorts (gitignored)
tests/                    # Pytest smoke + integration tests + fixtures
docs/                     # mkdocs-material site source
.github/workflows/        # CI + Zenodo deposit on tag

ARCHITECTURE.md           # Architectural source of truth
LICENSING.md              # Per-dependency license inventory
CONTRIBUTING.md           # How to contribute
CHANGELOG.md              # Per-version changes
CITATION.cff              # Zenodo / GitHub citation metadata
Snakefile                 # Snakemake DAG
pyproject.toml            # Python packaging
```

## Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md) — system design, module contracts, design rationale
- [LICENSING.md](LICENSING.md) — per-dependency license inventory and commercial-use guidance
- [CONTRIBUTING.md](CONTRIBUTING.md) — dev setup, testing, commit conventions
- [CHANGELOG.md](CHANGELOG.md) — per-version changes
- `docs/` — long-form docs (built with `mkdocs build`)

## Acknowledgments

`bindsight` is an opinionated wrapper. Real intellectual credit belongs to the upstream tool authors. See [LICENSING.md](LICENSING.md) for the full inventory; the work this builds on most directly:

- [SURFACE-Bind](https://github.com/hamedkhakzad/SURFACE-Bind) (Khakzad et al., PNAS 2025) — the targetable-sites catalog that makes the bridge tractable
- [pydeseq2](https://github.com/owkin/PyDESeq2) (Muzellec et al., Bioinformatics 2023) — Python DESeq2 implementation
- [RFdiffusion](https://github.com/RosettaCommons/RFdiffusion) (Watson et al., Nature 2023) — backbone generation
- [ProteinMPNN](https://github.com/dauparas/ProteinMPNN) (Dauparas et al., Science 2022) — sequence design
- [Boltz-2](https://github.com/jwohlwend/boltz) (Wohlwend et al., 2025) — structure + affinity prediction
- [BindCraft](https://github.com/martinpacesa/BindCraft) (Pacesa et al., Nature 2025) — one-shot binder design
- [Snakemake](https://github.com/snakemake/snakemake) (Mölder et al., F1000Research 2021) — workflow orchestration

## Citation

If you use `bindsight` in your work, please cite it via the Zenodo DOI:

> Wahba, M. A. R. (2026). *bindsight: a reproducible bridge from RNA-seq to de novo protein binder design* (v0.1.0). Zenodo. https://doi.org/10.5281/zenodo.20121496

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.20121496.svg)](https://doi.org/10.5281/zenodo.20121496)

BibTeX:

```bibtex
@software{wahba_bindsight_2026,
  author       = {Wahba, Mikhaeel Atef Rizk},
  title        = {bindsight: a reproducible bridge from RNA-seq to de novo protein binder design},
  year         = {2026},
  publisher    = {Zenodo},
  version      = {v0.1.0},
  doi          = {10.5281/zenodo.20121496},
  url          = {https://doi.org/10.5281/zenodo.20121496},
  orcid        = {https://orcid.org/0009-0006-1069-9558}
}
```

GitHub also exposes a "Cite this repository" button on the right sidebar of the [repo page](https://github.com/mikhaeelatefrizk/bindsight) that auto-generates citations in BibTeX, APA, and other formats from [CITATION.cff](CITATION.cff). Please also cite the upstream tools you used (the per-run manifest emits a `software.bib` to make this easy).

## About the author

`bindsight` is built and maintained by **Mikhaeel Atef Rizk Wahba** — PharmD graduate of the German University in Cairo (GUC), currently finishing the Egyptian post-PharmD applied-pharmacy term (Imtiyaz). Earlier in 2026 he had a research rotation at the German International University in Berlin (GIU Berlin) where he picked up R / RStudio.

- ORCID: [0009-0006-1069-9558](https://orcid.org/0009-0006-1069-9558)
- GitHub: [@mikhaeelatefrizk](https://github.com/mikhaeelatefrizk)
- Email: `mikhaeelatefrizk@proton.me`
- Languages: Arabic (native), English (full professional), German (professional working ≈ B2), French, Russian

### Sister projects on GitHub

`bindsight` sits at the deep end of an ongoing bioinformatics portfolio:

- **[bioinformatics-portfolio](https://github.com/mikhaeelatefrizk/bioinformatics-portfolio)** — an end-to-end bioinformatics portfolio with three subprojects, each fully reproducible from raw data to figures:
  - [`01-rnaseq-fox-domestication`](https://github.com/mikhaeelatefrizk/bioinformatics-portfolio/tree/main/01-rnaseq-fox-domestication) — RNA-seq differential expression on GEO GSE76517, replicating the Kukekova et al. *PNAS* 2018 silver-fox domestication study
  - [`02-tcga-survival-kidney-cancer`](https://github.com/mikhaeelatefrizk/bioinformatics-portfolio/tree/main/02-tcga-survival-kidney-cancer) — TCGA-KIRC clinical survival analysis identifying EPAS1 / HIF-2α as a prognostic biomarker (target of FDA-approved belzutifan)
  - [`03-scrnaseq-pbmc-seurat`](https://github.com/mikhaeelatefrizk/bioinformatics-portfolio/tree/main/03-scrnaseq-pbmc-seurat) — Seurat v5 single-cell RNA-seq workflow on the 10x PBMC 3k dataset, recovering 8 immune populations
- **[affect-labeling-review](https://github.com/mikhaeelatefrizk/affect-labeling-review)** — a pre-registered systematic review + meta-analysis of affect labeling (Lieberman et al. 2007 paradigm). Real random-effects meta-analysis (k=9), PRISMA 2020, RoB 2 / ROBINS-I, ~14,000-word manuscript, open data + open code, `.zenodo.json` for citable archival
- **[awesome-protein-design-software](https://github.com/mikhaeelatefrizk/awesome-protein-design-software)** — curated list of protein-design / structure-prediction software (RFdiffusion, ProteinMPNN, Boltz, AlphaFold, ESMFold, etc.)
- **[Awesome-Bioinformatics](https://github.com/mikhaeelatefrizk/Awesome-Bioinformatics)** — curated list of bioinformatics libraries and tools

## License

MIT. See [LICENSE](LICENSE) and [LICENSING.md](LICENSING.md) for component-level details.

# bindsight

> **Expression → Binder.** An open-source pipeline that joins cohort RNA-seq target discovery to de novo protein binder design in one reproducible workflow, with machine-readable provenance from every ranked binder back to the patient samples it came from.

Binder-design workflows — [BindCraft](https://github.com/martinpacesa/BindCraft), [BinderFlow](https://doi.org/10.1371/journal.pcbi.1013747), [`dl_binder_design`](https://github.com/nrbennet/dl_binder_design), Seqera's [nf-proteindesign](https://github.com/seqeralabs/nf-proteindesign) — all start from a target you have already chosen. Expression- and surfaceome-based target-discovery work (pan-cancer surfaceome screens, [pVACtools](https://pvactools.readthedocs.io/) for neoantigens) stops at a ranked list of genes or peptides. bindsight is, as far as we are aware, the first open-source tool that runs **both halves end-to-end** and carries a machine-readable audit trail *across the join* — from a designed binder back through the epitope, the structure, the surfaceome call, and the differential-expression contrast to the individual patient samples. The individual steps are the community's; the join, its defaults, and its provenance are what bindsight contributes.

[![HF Space](https://img.shields.io/badge/%F0%9F%A4%97%20HF%20Space-bindsight-yellow.svg)](https://huggingface.co/spaces/Mikhaeelatefrizk/bindsight)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.20121495.svg)](https://doi.org/10.5281/zenodo.20121495)
[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](LICENSE)
[![Python: 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![CI](https://github.com/mikhaeelatefrizk/bindsight/actions/workflows/ci.yml/badge.svg)](https://github.com/mikhaeelatefrizk/bindsight/actions/workflows/ci.yml)
[![Workflow: Snakemake](https://img.shields.io/badge/workflow-Snakemake-brightgreen.svg)](https://snakemake.github.io/)

## 👉 See it / try it

**The evidence, no waiting:** **[Real results](https://mikhaeelatefrizk.github.io/bindsight/results/)** — ERBB2 rediscovered at rank 4 from real TCGA-BRCA RNA-seq, the six-cohort validation, and 20 de novo ERBB2 binders rendered in 3-D against their target. Static, always current with `main`, nothing to wake up.

**Run it in your browser** (Hugging Face Space, 16 GB CPU): [huggingface.co/spaces/Mikhaeelatefrizk/bindsight](https://huggingface.co/spaces/Mikhaeelatefrizk/bindsight) — tracks `main`. Click the **Demo** tab and watch the **discovery half** surface antibody-tractable cell-surface antigens from a **real TCGA breast-cancer cohort** (NIH/GDC), with full provenance. (Binder *design* and *validation* are GPU-only — you run those via Modal / Docker / Kaggle / Colab, so they don't execute in the browser.) `.github/workflows/sync-hf-space.yml` republishes the Space's landing page and factory-rebuilds it on every release (requires the `HF_TOKEN` secret; skipped otherwise).

> The free-tier Space sleeps after a quiet spell; a GitHub Actions cron pings it every 6 hours so the next visitor lands on a warm container. After a long quiet stretch, give the wake-up screen 30–60 s and reload once.

> 🚀 **v0.2.2** — discovery half end-to-end on CPU (real TCGA data); design + validation demonstrated end-to-end on a **free GPU** — bindsight's first real de novo binders (20 ERBB2 designs, best ipTM 0.84, 50% success@0.65, with the real Boltz-2-predicted complexes) ship in the [designer benchmark](benchmarks/designer_benchmark/RESULTS.md); web UI deployed as a Hugging Face Space.

> ⚠️ **The committed binder figures predate a protocol fix shipped in this same release.** That run invoked ProteinMPNN without `--pdb_path_chains`, so it redesigned the HER2 target chain as well as the binder: the designs were optimised against a partly-invented target surface and then scored against the native one. The measurements are real and reproduce exactly from the committed artifacts, but the protocol was mis-set, and a corrected re-run will supersede them. Treat ipTM 0.84 / 50 % success@0.65 as provisional. Details in [`benchmarks/designer_benchmark/RESULTS.md`](benchmarks/designer_benchmark/RESULTS.md).

**New here?** → [Documentation site](https://mikhaeelatefrizk.github.io/bindsight/) · [What is bindsight?](https://mikhaeelatefrizk.github.io/bindsight/what-is-bindsight/) (5-min read) · [How to use it](https://mikhaeelatefrizk.github.io/bindsight/how-to-use/) · [Use cases](https://mikhaeelatefrizk.github.io/bindsight/use-cases/) · [Designing on Colab](https://mikhaeelatefrizk.github.io/bindsight/colab-design-howto/)

**Want the evidence first?** → [Real results](https://mikhaeelatefrizk.github.io/bindsight/results/) — ERBB2 rediscovered at rank 4 from real TCGA-BRCA RNA-seq, and 20 de novo ERBB2 binders (best ipTM 0.84, pre-fix protocol — see the caveat above) with their Boltz-2 predicted complexes.

---

## Three ways to try it

### 1. Web app — [Hugging Face Space](https://huggingface.co/spaces/Mikhaeelatefrizk/bindsight) (zero install)

Anyone visiting the Space gets:
- A **Home** page with what bindsight is and the headline results
- A **Real results** page — the committed benchmarks, including the 20 real ERBB2 binders rendered in 3-D against their target from the actual Boltz-2 predicted complexes (no run required, nothing to wait for)
- A **Demo** button that runs the discovery half live and renders a report
- A **Run on my data** page (upload counts.tsv + design.tsv → get results)
- A **Browse a run** page to inspect any output directory

The Hugging Face Space (16 GB CPU) is factory-rebuilt from `main` on every release by `sync-hf-space.yml` (requires the `HF_TOKEN` secret; skipped otherwise). The free tier sleeps after a quiet spell; a 6-hourly GitHub Actions ping keeps it warm, but the first visit after a long quiet period can still take ~30–120 s to wake.

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

Runs the full discovery half on a **real TCGA-BRCA tumor-vs-adjacent-normal cohort** auto-downloaded from NIH/GDC, and produces a real HTML report you can open in a browser. The pipeline discovers antibody-tractable cell-surface antigens over-expressed in tumor — entirely from RNA-seq counts, with full provenance (well-known targets such as ERBB2/HER2 surface among the candidates when their signal is present). First run needs internet (the cohort is downloaded from GDC and enrichment queries Open Targets / AlphaFoldDB, then cached; the surfaceome list is vendored in the package and never fetched) and takes a few minutes of real DESeq2 + enrichment; CPU-only, no GPU.

Sketch of the run — **illustrative, not a captured transcript**. The log lines
use the pipeline's actual format strings (`bindsight/io/gdc.py`,
`bindsight/pipelines/discover.py`, `bindsight/report/html.py`); the counts
depend on your cohort, and the Rich panels wrap to your terminal width.

```
$ bindsight demo
╭──────────────── Demo run ────────────────╮
│ bindsight demo                           │
│                                          │
│ config: examples/demo/config.yaml        │
│ out:    runs/demo                        │
│                                          │
│ Real TCGA-BRCA tumor-vs-adjacent-normal  │
│ cohort (NIH/GDC). …                      │
╰──────────────────────────────────────────╯
INFO  bindsight discover: out=runs/demo name=tcga-brca-demo
INFO  inputs missing; auto-downloading TCGA-BRCA cohort from GDC
INFO  GDC: listing TCGA-BRCA files (20 tumor + 20 normal)…
INFO  DEGs: 17019 total, 4011 significant; enriching top 300 by combined score (π)
INFO  surfaceome filter: 301 → 32
INFO  wrote runs/demo/report.html
INFO  bindsight discover complete; manifest=runs/demo/run_manifest.jsonld
╭───────────── bindsight demo ─────────────╮
│ Demo complete!                           │
│                                          │
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
  bulk RNA-seq counts                               Designed protein binders
              │                                              ▲
              │                                              │
              ▼                                              │
   Differential expression  ──►  Surface-exposed  ──►  De novo backbone
   (pydeseq2)                   (SURFY)              (RFdiffusion / BindCraft / BoltzGen)
                                     │                       │
                                     ▼                       ▼
                              Targetable sites          Sequence design
                              (SURFACE-Bind)            (ProteinMPNN)
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

## What works today (v0.2.2)

| Capability | Status | How to try |
|---|---|---|
| **Web UI** — multi-page Streamlit app (Home / Real results / Demo / Run on my data / Browse a run / Glossary / About) | ✅ ready | `bindsight ui`  *or*  the Hugging Face Space |
| **`bindsight demo`** — full discovery on shipped example + paper-style report | ✅ ready | `bindsight demo` |
| **`bindsight discover`** — your own RNA-seq cohort → ranked targets | ✅ ready | `bindsight discover my.yaml --out runs/x` |
| **`bindsight rank`** — multi-objective composite scoring of validated binders | ✅ ready | `bindsight rank runs/x` |
| **`bindsight report --format html`** — paper-style HTML, embedded volcano + tables + provenance | ✅ ready | `bindsight report runs/x` |
| **`bindsight report --format streamlit`** — interactive dashboard for one run | ✅ ready | `bindsight report runs/x --format streamlit` |
| **`bindsight run`** — full pipeline orchestrator (discover → design → validate → rank → report → export) | ✅ ready | `bindsight run my.yaml --out runs/x` |
| **`bindsight export`** — RO-Crate zip for Zenodo deposit | ✅ ready | `bindsight export runs/x --out runs/x.crate.zip` |
| **`bindsight design`** — RFdiffusion + ProteinMPNN + Boltz-2 on a free Kaggle T4 | ✅ verified | `bindsight design runs/x --backend kaggle` |
| **`bindsight design`** — BindCraft / BoltzGen / Chai-1r / AF2-IG designers and validators | ⚠️ implemented, not yet executed | see [runner and plugin status](#runner-and-plugin-status) |
| **`bindsight design --dry-run`** — GPU cost estimate for any backend | ✅ ready | `bindsight design runs/x --backend modal --dry-run` |
| **`bindsight validate`** — materialise the design job's metrics → `validated.parquet` | ✅ ready | `bindsight validate runs/x` |
| **`bindsight validate --revalidate`** — run a *different* validator against binders that already exist, without redesigning | ✅ ready | `bindsight validate runs/x --validator chai1r --revalidate --backend kaggle` |
| **`bindsight benchmark`** — score rediscovery of the held-out known antigens (recall@k) | ✅ ready | `bindsight benchmark runs/x --known-antigens benchmarks/known.tsv` |
| **Snakemake front-end** — same pipeline as the CLI, end-to-end | ✅ ready | `snakemake --configfile my.yaml --cores 4` (`pip install -e ".[workflow]"`) |
| **`bindsight doctor`** — diagnose deps, caches, vendored data | ✅ ready | `bindsight doctor` |
| **`bindsight verify-licenses`** — per-component license inventory | ✅ ready | `bindsight verify-licenses` |

### Runner and plugin status

Not every backend and plugin carries the same weight of evidence, and presenting
them as peers would be misleading. What each one actually is:

| | Status | Why |
|---|---|---|
| **Kaggle** | The verified free path | Headless via the Kaggle API, so a reader can re-run the exact job on their own free quota. Pinned to a T4: Kaggle's own docs warn its default P100 cannot run current PyTorch. |
| **local_docker** | For your own GPU | Native and containerised modes; the native mode is what CPU tests exercise. |
| **Modal** | Prepared, not executed | The paid escape hatch for what free hardware cannot reach. Its image is built to carry the whole design stack, but running it costs money and it has not been run end to end. |
| **Colab** | Interactive on-ramp only | Google's API does not permit launching a free-tier notebook from a CLI, so this path needs a human with a browser tab open. That is a demo, not a reproducibility path. |
| **RFdiffusion, ProteinMPNN, Boltz-2** | Verified on free hardware | The committed benchmark run. |
| **AF2 initial-guess** | Buildable free | PyRosetta is credential-free for non-commercial use since 2024. Non-commercial weights. |
| **BindCraft, BoltzGen** | Reduced-target only on free hardware | Both fit a 16 GB card against a small domain, not a full receptor. BoltzGen's integration was rewritten after its command was found not to exist upstream. |
| **Chai-1r** | Needs Ampere or newer | It requires bfloat16, which no free-tier GPU has. Verifying it means renting roughly an hour of a modern card. |

> **Note on GPU stages.** The design/validation models require CUDA, so they
> run on the GPU backend you choose (Modal / local Docker / Kaggle, or a
> generated Colab notebook), not on the CPU host. The held-out evaluation set
> lives in [`benchmarks/`](benchmarks/) with full provenance.

> **Discovery quality filters (opt-in).** Beyond the core
> DE → surfaceome → structure path, discovery can apply real-data refinements via
> `target_discovery` config flags: an AlphaFold-pLDDT disorder gate
> (`min_mean_plddt`), UniProt extracellular-domain / topology restriction
> (`use_uniprot_topology`, `require_extracellular_domain`), and GTEx normal-tissue
> safety (`use_gtex_safety`) — each adds a negative-result disposition and a
> per-candidate column. Binder developability scoring (Biopython ProtParam) is a
> ranking component; an ESM-2 → PCA embedding visualizer (`pip install -e ".[embed]"`)
> shows the designed-binder sequence space before any GPU spend; and the report
> carries a Limitations section (mRNA ≠ surface protein, bulk-purity confounding).
> All are documented in the [CHANGELOG](CHANGELOG.md).

## Status & roadmap

- ✅ **v0.2.2** (current) — a distribution and metadata release on top of v0.2.1: every release ships a wheel, an sdist and a `SHA256SUMS` file so a pinned build installs without PyPI, and the stale Hugging Face mirror pointers are corrected. No code behaviour changes.
- ✅ **v0.2.1** — the v0.2.0 feature set with a release of correctness and honesty fixes (see the [CHANGELOG](CHANGELOG.md)), notably the ProteinMPNN target-chain fix that supersedes the protocol behind the committed binder benchmark.
- ✅ **v0.2.0** — everything in v0.1.0 (discovery on real TCGA data; full design half — RFdiffusion + ProteinMPNN + Boltz-2, plus BindCraft / BoltzGen / Chai-1r / AF2-IG — on Modal / local Docker / Kaggle / Colab; rank + report + export; benchmark + held-out eval set; CLI **and** Snakemake front-ends; web UI) **plus** the first real de novo binders, the free Kaggle split-environment backend, the negative-result taxonomy, SURFACE-Bind targetable-site lookup, opt-in discovery-quality filters (AlphaFold-pLDDT disorder gate, UniProt extracellular-domain/topology restriction, GTEx normal-tissue safety), binder developability scoring, an ESM-2 pre-GPU embedding visualizer, and surfaced discovery caveats (mRNA ≠ surface protein, bulk-purity confounding).
- ✅ **Rediscovery validation** — the discovery half, run on six real indication-matched TCGA cohorts, resurfaces **ERBB2 at rank 4** in HER2-enriched breast cancer (via PAM50 subtype stratification — versus a much lower rank in the unsplit BRCA cohort, where averaging across subtypes dilutes the HER2 signal; that unsplit run is not committed, so no rank is quoted). Antigens with no measured bulk over-expression (EGFR/CEA) do not appear in the shortlist — an internal consistency check that the over-expression rule is applied as documented, not a measurement of ranking discrimination, since that rule excludes them from candidacy by construction. Reproducible artifacts in [`benchmarks/validation/`](benchmarks/validation/RESULTS.md); write-up in [`paper/validation/`](paper/validation/manuscript.md).
- ✅ **De novo binder design demonstrated end-to-end** — the design half (RFdiffusion → ProteinMPNN → Boltz-2) run on a **free Kaggle Tesla P100** produced **20 real binders** against the ERBB2 extracellular **domain IV** (the clinically validated trastuzumab epitope): mean **ipTM 0.59**, best **0.84**, **50 %** of designs pass the ipTM ≥ 0.65 success bar (mean PAE-interaction 13.7 Å) — at **$0**, no local GPU. **These figures predate the ProteinMPNN target-chain fix in v0.2.1** (the run redesigned the target chain as well as the binder) and will be superseded by a corrected re-run; the numbers themselves are real and reproduce exactly. The real Boltz-2-predicted **complexes** (CIF) + FASTAs + per-design metrics are in [`benchmarks/designer_benchmark/RESULTS.md`](benchmarks/designer_benchmark/RESULTS.md); reproduce on a free GPU via [`RUN_FREE_GPU.md`](benchmarks/designer_benchmark/RUN_FREE_GPU.md).
- ⏳ **v0.3.0** — single-cell RNA-seq input, async (non-blocking) Modal job submission, and extending the [designer benchmark](benchmarks/designer_benchmark/DESIGNER_BENCHMARK.md) from the committed `rfdiff_mpnn` arm to the full three-way comparison (BindCraft / BoltzGen need ≥24–32 GB GPUs, so those arms run on paid backends).
- ⏳ **v1.0.0** — JOSS submission; multi-modal tumor-selectivity scoring (single-cell + co-expression + immunopeptidomics) to extend discovery beyond bulk differential expression.

See [ARCHITECTURE.md § Phased Roadmap](ARCHITECTURE.md#11-phased-roadmap) for details.

## Install

`bindsight` is not on PyPI yet. Every release ships a built wheel, an sdist and a
`SHA256SUMS` file as [release assets](https://github.com/mikhaeelatefrizk/bindsight/releases/latest),
so you can install a pinned, verifiable build without cloning (Windows / macOS /
Linux, Python 3.11+):

```bash
# a specific release, straight from the attached wheel
pip install https://github.com/mikhaeelatefrizk/bindsight/releases/download/v0.2.2/bindsight-0.2.2-py3-none-any.whl

# or resolve the extras from the tagged source
pip install "bindsight[discover,report] @ git+https://github.com/mikhaeelatefrizk/bindsight.git@v0.2.2"
```

Verify a downloaded artifact against the published checksums with
`sha256sum -c SHA256SUMS`.

For development, install from a checkout so tests and the example configs are
present:

```bash
git clone https://github.com/mikhaeelatefrizk/bindsight.git
cd bindsight
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate

pip install -e ".[dev,discover,report]"
bindsight --version
bindsight doctor                # confirm install is clean
bindsight demo                  # run the demo (a few minutes, real TCGA data)
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

# 3. Design binders for the top 5 targets via Colab GPU
bindsight design runs/luad_v01 --backend colab --trajectories 50

# 4. Validate with Boltz-2
bindsight validate runs/luad_v01 --backend colab --validator boltz2

# 5. Rank, report, export as RO-Crate
bindsight rank runs/luad_v01
bindsight report runs/luad_v01 --format html --include-binders
bindsight export runs/luad_v01 --format ro-crate --out runs/luad_v01.crate.zip
```

## Repository layout

```
bindsight/                 # Python package
├── io/                   # Parquet, FASTA, PDB, mmCIF, manifest readers
├── deg/                  # pydeseq2 wrapper
├── targets/              # Open Targets client + ENSG→UniProt fallback + GTEx safety
├── surfaceome/           # SURFY filter + SURFACE-Bind client
├── structures/           # AlphaFoldDB fetch (RCSB/PDBe planned); pLDDT + UniProt topology
├── epitopes/             # SURFACE-Bind site lookup; fpocket fallback (planned)
├── design/               # Designer plugin interface; developability + ESM-2 embeddings
├── runners/              # Colab / Modal / Kaggle / local-Docker adapters
├── validate/             # Boltz-2 default; Chai-1r, AF2-IG opt-in
├── rank/                 # Multi-objective scoring
├── benchmark/            # Rediscovery + designer-benchmark scoring harness
├── pipelines/            # Discovery orchestrator (discover.py) + honesty caveats
├── provenance/           # PROV-O JSON-LD schema + RO-Crate emitter
├── report/               # HTML report template + Streamlit app
├── config.py             # Pydantic run-configuration models
└── cli.py                # Click entrypoint

envs/                     # Conda environment file for the discovery half + pinned constraints
examples/                 # Example pipeline configs (TCGA-LUAD, etc.)
benchmarks/               # Held-out known-antigen eval set + validation & designer-benchmark harnesses
paper/                    # JOSS + bioRxiv manuscripts and the validation write-up
data/                     # Local cache for auto-downloaded TCGA cohorts (gitignored)
tests/                    # Pytest smoke + integration tests + fixtures
docs/                     # mkdocs-material site source
.github/workflows/        # CI, docs, docker, release artifacts, HF sync

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

- [SURFACE-Bind](https://github.com/hamedkhakzad/SURFACE-Bind) (Balbi et al., PNAS 2026) — the targetable-sites catalog that makes the bridge tractable
- [pydeseq2](https://github.com/owkin/PyDESeq2) (Muzellec et al., Bioinformatics 2023) — Python DESeq2 implementation
- [RFdiffusion](https://github.com/RosettaCommons/RFdiffusion) (Watson et al., Nature 2023) — backbone generation
- [ProteinMPNN](https://github.com/dauparas/ProteinMPNN) (Dauparas et al., Science 2022) — sequence design
- [Boltz-2](https://github.com/jwohlwend/boltz) (Wohlwend et al., 2025) — structure + affinity prediction
- [BindCraft](https://github.com/martinpacesa/BindCraft) (Pacesa et al., Nature 2025) — one-shot binder design
- [Snakemake](https://github.com/snakemake/snakemake) (Mölder et al., F1000Research 2021) — workflow orchestration

## Citation

If you use `bindsight` in your work, please cite it via the Zenodo **concept DOI**
`10.5281/zenodo.20121495` — it always resolves to the latest archived version, which
is what you want when citing "the software". Cite a version DOI instead only when you
need to pin the exact release you ran.

> Wahba, M. A. R. (2026). *bindsight: a reproducible bridge from RNA-seq to de novo protein binder design* (v0.2.2). Zenodo. https://doi.org/10.5281/zenodo.20121495

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.20121495.svg)](https://doi.org/10.5281/zenodo.20121495)

BibTeX:

```bibtex
@software{wahba_bindsight_2026,
  author       = {Wahba, Mikhaeel Atef Rizk},
  title        = {bindsight: a reproducible bridge from RNA-seq to de novo protein binder design},
  year         = {2026},
  publisher    = {Zenodo},
  version      = {v0.2.2},
  doi          = {10.5281/zenodo.20121495},
  url          = {https://doi.org/10.5281/zenodo.20121495},
  orcid        = {https://orcid.org/0009-0006-1069-9558}
}
```

GitHub also exposes a "Cite this repository" button on the right sidebar of the [repo page](https://github.com/mikhaeelatefrizk/bindsight) that auto-generates citations in BibTeX, APA, and other formats from [CITATION.cff](CITATION.cff). Please also cite the upstream tools you used (the per-run manifest emits a `software.bib` to make this easy).

## About the author

`bindsight` is built and maintained by **Mikhaeel Atef Rizk Wahba**, independent researcher.

- ORCID: [0009-0006-1069-9558](https://orcid.org/0009-0006-1069-9558)
- GitHub: [@mikhaeelatefrizk](https://github.com/mikhaeelatefrizk)
- Email: `mikhaeelatefrizk@proton.me`

### Related project

- **[affect-labeling-review](https://github.com/mikhaeelatefrizk/affect-labeling-review)** — a systematic review and random-effects meta-analysis of affect labeling (Lieberman et al. 2007 paradigm): PRISMA 2020, RoB 2 / ROBINS-I, *k* = 8 psychophysiological effect sizes from six studies, ~10,500-word manuscript, open data and code, archived on Zenodo (v1.1.1).

## License

- **Code:** [GNU AGPL-3.0-or-later](LICENSE). You may use, study, modify, and
  redistribute bindsight freely; if you distribute a modified version **or run it
  as a network service**, you must make your source available under the same
  license, with attribution preserved. See [LICENSING.md](LICENSING.md) for
  component-level details (bindsight orchestrates external tools that keep their
  own licenses).
- **Documentation, manuscripts, figures, and generated results** (e.g. `paper/`):
  [CC BY 4.0](paper/LICENSE) — reuse freely with attribution.

© 2026 Mikhaeel Atef Rizk Wahba. Commercial licensing on other terms is available
from the author on request.

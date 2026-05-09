# xpr2bind

> **Expression → Binder.** A reproducible, open-source bridge from RNA-seq counts to ranked de novo protein binder candidates, with end-to-end provenance.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Status: alpha](https://img.shields.io/badge/status-alpha-orange.svg)]()
[![Python: 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)]()
[![Workflow: Snakemake](https://img.shields.io/badge/workflow-Snakemake-brightgreen.svg)](https://snakemake.github.io/)

> ⚠️ **Pre-release.** v0.0.1-dev. APIs and outputs are subject to change. See [CHANGELOG.md](CHANGELOG.md).

---

## Why this exists

Two ecosystems in computational biology operate side-by-side and barely talk to each other:

- **Genomics** (DESeq2, edgeR, Seurat, scanpy, TCGA, recount3) stops at *"here are the interesting genes."*
- **Protein design** (RFdiffusion, ProteinMPNN, BindCraft, BoltzGen, AlphaFold, Boltz-2) starts from *"given a target..."*

The bridge between them — *"this gene is up in disease, low in healthy tissue, surface-exposed, has a known targetable site, here is a docked binder seed and a designed binder ranked by predicted affinity, with the receipts back to the patient cohort"* — is missing. People build it ad-hoc, per project, never reproducibly. **xpr2bind ships that bridge as one tool.**

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
                                       Quarto report + RO-Crate (Zenodo)
                                       with full PROV-O provenance
```

## Who it's for

- **Translational researchers** who want a free, reproducible "data → designed binder" pipeline.
- **Clinical biologists** who need an audit trail back from a binder to the patient cohort.
- **Method developers** who want a held-out evaluation harness (rediscovery of known antigens) to benchmark new designers/validators.
- **Pharma early-discovery teams** who want an open comparator they can extend with proprietary designers via the plugin interface.

## What's distinctive

| | Existing protein-design tools | xpr2bind |
|---|---|---|
| Input | Target structure | RNA-seq counts |
| Provenance | PDB + maybe a log | PROV-O JSON-LD + RO-Crate, audit trail to patient cohort |
| Hardware | HPC assumed | CPU laptop + offload to free Colab / Modal / Kaggle |
| Cost-awareness | None | `--dry-run` estimates GPU $ before running |
| Negative results | Discarded | Catalogued (`failure_taxonomy.parquet`) |
| Citability | Code dump | DOI per release, JSON-Schema-validated outputs, JOSS-style |

For the full landscape comparison, see [ARCHITECTURE.md](ARCHITECTURE.md#comparison-vs-existing-tools).

## Status & roadmap

- ✅ **v0.0.1-dev** (current) — repo skeleton, manifest schema, CLI shell
- 🚧 **v0.0.x** — discovery half (CPU only): pydeseq2, Open Targets, SURFY/SURFACE-Bind, AlphaFoldDB
- ⏳ **v0.1.0** — design half (GPU offload): RFdiffusion+ProteinMPNN backbone, Boltz-2 validation, Quarto report, RO-Crate export
- ⏳ **v0.2.0** — BindCraft + BoltzGen designer plugins, fpocket epitope fallback, scRNA-seq input
- ⏳ **v1.0.0** — JOSS submission, validation paper

See [ARCHITECTURE.md § Phased Roadmap](ARCHITECTURE.md#phased-roadmap) for details.

## Installation

> `xpr2bind` is not yet on PyPI. Install from source:

```bash
git clone https://github.com/mikhaeelatefrizk/xpr2bind.git
cd xpr2bind
mamba env create -f envs/discover.yaml
mamba activate xpr2bind-discover
pip install -e ".[dev]"
xpr2bind --version
```

## Quickstart (target: v0.0.x)

```bash
# 1. Discover targets from a TCGA cohort (CPU only, ~10 minutes on a laptop)
xpr2bind discover examples/tcga_luad.yaml --out runs/luad_v01

# 2. Inspect the discovered targets
xpr2bind report runs/luad_v01 --format html
open runs/luad_v01/report.html

# 3. (v0.1+) Design binders for the top 5 targets via Colab GPU
xpr2bind design runs/luad_v01 --backend colab --trajectories 50

# 4. (v0.1+) Validate with Boltz-2
xpr2bind validate runs/luad_v01 --backend colab --validator boltz2

# 5. (v0.1+) Rank, report, export as RO-Crate
xpr2bind rank runs/luad_v01
xpr2bind report runs/luad_v01 --format html --include-binders
xpr2bind export runs/luad_v01 --format ro-crate --out runs/luad_v01.crate.zip
```

## Repository layout

```
xpr2bind/                 # Python package
├── io/                   # Parquet, FASTA, PDB, mmCIF, manifest readers
├── deg/                  # pydeseq2 wrapper (+ optional R bridge)
├── targets/              # Open Targets, HPA, GTEx, recount3 clients
├── surfaceome/           # SURFY filter + SURFACE-Bind client
├── structures/           # AlphaFoldDB + RCSB/PDBe fetch
├── epitopes/             # SURFACE-Bind site lookup; fpocket fallback (v0.2)
├── design/               # Designer plugin interface
├── runners/              # Colab / Modal / Kaggle / local-Docker adapters
├── validate/             # Boltz-2 default; Chai-1r, AF2-IG opt-in
├── rank/                 # Multi-objective scoring
├── provenance/           # PROV-O JSON-LD schema + RO-Crate emitter
├── report/               # Quarto template + Streamlit app
└── cli.py                # Click entrypoint

envs/                     # Conda environment files (one per stage)
examples/                 # Example pipeline configs (TCGA-LUAD, etc.)
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

`xpr2bind` is an opinionated wrapper. Real intellectual credit belongs to the upstream tool authors. See [LICENSING.md](LICENSING.md) for the full inventory; the work this builds on most directly:

- [SURFACE-Bind](https://github.com/hamedkhakzad/SURFACE-Bind) (Khakzad et al., PNAS 2025) — the targetable-sites catalog that makes the bridge tractable
- [pydeseq2](https://github.com/owkin/PyDESeq2) (Muzellec et al., Bioinformatics 2023) — Python DESeq2 implementation
- [RFdiffusion](https://github.com/RosettaCommons/RFdiffusion) (Watson et al., Nature 2023) — backbone generation
- [ProteinMPNN](https://github.com/dauparas/ProteinMPNN) (Dauparas et al., Science 2022) — sequence design
- [Boltz-2](https://github.com/jwohlwend/boltz) (Wohlwend et al., 2025) — structure + affinity prediction
- [BindCraft](https://github.com/martinpacesa/BindCraft) (Pacesa et al., Nature 2025) — one-shot binder design
- [Snakemake](https://github.com/snakemake/snakemake) (Mölder et al., F1000Research 2021) — workflow orchestration

## Citation

If you use `xpr2bind` in your work, please cite it via [CITATION.cff](CITATION.cff). Once a Zenodo DOI is issued (on first tagged release), it will appear here. Please also cite the upstream tools you used (the per-run manifest emits a `software.bib` to make this easy).

## License

MIT. See [LICENSE](LICENSE) and [LICENSING.md](LICENSING.md) for component-level details.

---
description: Where bindsight fits in the protein-design and target-discovery landscape — who it is for, the RNA-seq-to-binder gap it fills, and how it compares to existing tools.
---

# Where bindsight fits — positioning & landscape

> A short, honest map of where `bindsight` sits in the protein-design / target-discovery ecosystem:
> who it's for, the gap it fills, and what's on the roadmap. If you're evaluating bindsight for your
> group, start here.

## The gap bindsight fills

Two mature ecosystems sit side by side and barely talk to each other:

- **Genomics / transcriptomics** (DESeq2, edgeR, Seurat, scanpy, TCGA, recount3) stops at
  *"here are the interesting genes."*
- **De novo protein / binder design** (RFdiffusion, ProteinMPNN, BindCraft, BoltzGen, AlphaFold,
  Boltz-2) starts from *"given a target structure…"*

Every open binder-design tool we surveyed — [BindCraft](https://www.nature.com/articles/s41586-025-09429-6),
[BinderFlow](https://journals.plos.org/ploscompbiol/article?id=10.1371/journal.pcbi.1013747),
PXDesign, Latent-X — begins with a **known target**. The path *from expression data to a designed,
ranked, provenance-tracked binder candidate* is built ad-hoc, per project, rarely reproducibly.

**bindsight ships that bridge as one open, reproducible tool** — and records the receipts all the way
back to the patient cohort.

## Who it's for

| Audience | What bindsight gives you |
|---|---|
| **Translational researchers** | A free, reproducible "data → designed binder" path on a laptop, with free-GPU offload. |
| **Clinical / cancer biologists** | An audit trail from any binder candidate back to the cohort it came from. |
| **Method developers** | A held-out evaluation harness (rediscovery of known antigens) to benchmark new designers/validators behind a stable plugin interface. |
| **Early-discovery teams** | An open, extensible comparator you can plug proprietary designers into — no fork required. |

## How it relates to neighboring tools

bindsight is an **orchestration + provenance layer**, not a new model. It stands on, and credits, the
best open tools in each step (see [Acknowledgments](../README.md#acknowledgments)). Its contribution
is the *connective tissue*: the surfaceome/targetable-site filter
([SURFACE-Bind](https://www.pnas.org/doi/10.1073/pnas.2506269123)), the multi-objective ranking, the
cost-aware GPU offload, the failure taxonomy, and the [PROV-O](https://www.w3.org/TR/prov-o/) +
[RO-Crate](https://www.researchobject.org/ro-crate/) provenance that makes a run citable and
reproducible.

| | Typical binder-design tool | bindsight |
|---|---|---|
| Input | Target structure | RNA-seq counts |
| Provenance | PDB + maybe a log | PROV-O JSON-LD + RO-Crate, audit trail to cohort |
| Hardware | HPC assumed | CPU laptop + free Colab/Modal/Kaggle offload |
| Cost-awareness | None | `--dry-run` estimates GPU $ before running |
| Negative results | Discarded | Catalogued (`failure_taxonomy.parquet`) |
| Citability | Code dump | DOI per release, JSON-Schema-validated outputs |

## Roadmap

- **v0.1.0 (now)** — discovery half end-to-end on CPU; design + validation wired for free Colab;
  multi-page web UI live.
- **v0.1.x** — first full end-to-end GPU case study on a public TCGA cohort, published as a worked
  example.
- **v0.2.0** — live Modal/Colab job submission; BindCraft + BoltzGen plugins fully wired; scRNA-seq
  input.
- **v1.0.0** — JOSS submission + validation paper (blinded rediscovery of HER2/EGFR/MSLN/CLDN6).

## Get involved

bindsight is MIT-licensed and built in the open. If you run target discovery or binder design and
want to compare notes — or you'd like to try it on your own cohort — open an issue or reach the author
([@mikhaeelatefrizk](https://github.com/mikhaeelatefrizk),
[ORCID 0009-0006-1069-9558](https://orcid.org/0009-0006-1069-9558)). Feedback from real workflows
directly shapes the roadmap.

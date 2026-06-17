---
title: bindsight — RNA-seq to de novo protein binder design
description: bindsight is an open-source pipeline by Mikhaeel Atef Rizk that turns RNA-seq counts into ranked de novo protein-binder candidates against tumour cell-surface antigens, with full PROV-O / RO-Crate provenance back to the patient cohort.
---

# bindsight

**Expression → Binder.** An open-source pipeline that takes RNA-seq counts and
outputs ranked *de novo* protein-binder candidates against over-expressed
cell-surface antigens, with full PROV-O / RO-Crate provenance back to the
patient cohort.

## Start here

- **[What is bindsight?](what-is-bindsight.md)** — the 5-minute pitch.
- **[How to use it](how-to-use.md)** — install, the `bindsight demo`, and the
  full `discover → design → validate → rank → report → export` flow.
- **[Use cases](use-cases.md)** — concrete scenarios.
- **[Designing on Colab](colab-design-howto.md)** — the GPU half on free Colab.

## One-command demo

```bash
pip install -e ".[discover,report]"
bindsight demo
```

Runs the discovery half on a **real TCGA-BRCA** cohort (auto-downloaded from
NIH/GDC), discovering antibody-tractable surface antigens with full provenance.

## How it fits together

The CLI (`bindsight …`) and an optional Snakemake front-end both drive the same
Python pipeline. The discovery half is CPU-only; the design half (RFdiffusion →
ProteinMPNN → Boltz-2, plus BindCraft / BoltzGen / Chai-1r / AF2-IG) runs on a
GPU backend you choose (Modal / local Docker / Kaggle / Colab).

See [`ARCHITECTURE.md`](https://github.com/mikhaeelatefrizk/bindsight/blob/main/ARCHITECTURE.md),
[`LICENSING.md`](https://github.com/mikhaeelatefrizk/bindsight/blob/main/LICENSING.md),
and [`CONTRIBUTING.md`](https://github.com/mikhaeelatefrizk/bindsight/blob/main/CONTRIBUTING.md)
in the repository for design rationale, the per-component license inventory, and
how to add a designer / validator / runner plugin.

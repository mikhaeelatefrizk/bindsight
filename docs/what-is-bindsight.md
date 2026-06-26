---
description: What bindsight is — an open-source pipeline that turns RNA-seq counts into ranked de novo protein-binder candidates against tumour cell-surface antigens. A 5-minute introduction to the discovery-to-design bridge, by Mikhaeel Atef Rizk.
---

# What is bindsight, and why does it matter?

> A 5-minute read for anyone — biologist, data scientist, PI, investor, or
> recruiter — who wants to understand what this tool is, what it does, and why
> it's a genuine deal-breaker rather than yet another wrapper.

---

## The one-sentence pitch

**`bindsight` is the first open-source tool that takes RNA-seq counts as input
and produces ranked, structurally-validated de novo protein binder candidates
as output, with a complete audit trail back to the patient cohort the targets
came from.**

That's it. Counts in, designed binders out, every step documented.

---

## The two worlds it bridges

In computational biology in 2026, two ecosystems run side-by-side and barely
talk to each other:

| World | Tooling | Where it stops |
|---|---|---|
| **Genomics** | DESeq2, edgeR, Seurat, scanpy, TCGA, recount3, GTEx | "Here are the differentially-expressed genes." |
| **Protein design** | RFdiffusion, ProteinMPNN, BindCraft, BoltzGen, AlphaFold, Boltz-2, Chai-1 | "Given this target structure, here are some designed binders." |

Between them sits a chasm. Going from *"this gene is interesting"* to *"here's
a protein I designed to bind it"* requires:

1. Mapping gene IDs → UniProt accessions
2. Filtering for surface-exposed proteins (else you can't drug them)
3. Filtering for tissue specificity (else you'll hit healthy organs)
4. Pulling structures from AlphaFoldDB or PDB
5. Identifying druggable epitopes on those structures
6. Running a backbone diffusion model (RFdiffusion, etc.) on each
7. Designing sequences with ProteinMPNN
8. Validating each design with Boltz-2 / AlphaFold
9. Multi-objective ranking
10. Tracking provenance so a reviewer can audit the chain

**Today, doing all of this for one disease takes a competent grad student 4–6
weeks of glue scripting, four different conda environments, and at least one
HPC allocation.** The work is rarely reproducible across labs. The Apr 2026
bioRxiv preprint that did it for *one* cancer (DSRCT) needed a custom agent
framework just to keep state.

`bindsight` does it in a single command, on a CPU laptop, with reproducibility
that survives review.

---

## Why this is a deal-breaker, not yet-another-wrapper

### 1. It closes a structural gap, not a polish gap

There is no other open-source tool that takes RNA-seq counts as its input
type. [ProteinDJ](https://www.biorxiv.org/content/10.1101/2025.09.24.678028v2),
[Ovo](https://www.biorxiv.org/content/10.1101/2025.11.27.691041v1),
[BindCraft](https://github.com/martinpacesa/BindCraft),
[dl_binder_design](https://github.com/nrbennet/dl_binder_design),
[nf-binder-design](https://github.com/Australian-Protein-Design-Initiative/nf-binder-design),
and [Tamarind.bio](https://www.tamarind.bio/) all start with *"give us a target
structure."* They polish the protein-design half of the pipeline. The discovery
half — the genomics-to-structure bridge — is where we live, and where nobody
else has shipped.

### 2. The keystone (SURFACE-Bind) just dropped

The [SURFACE-Bind](https://github.com/hamedkhakzad/SURFACE-Bind) catalog
([PNAS 2025](https://www.pnas.org/doi/10.1073/pnas.2506269123)) ships
pre-computed targetable interfaces + binder seeds for ~2,800 surface proteins
under a BSD-3 license. Before this, "find a druggable site on an arbitrary
surface protein" was its own project. Now it's a UniProt-keyed lookup. This
unlocks the bridge for a one-person team — exactly the right moment to build.

### 3. CPU laptop is enough

The orchestrator runs on the user's machine. GPU work runs end-to-end on free
Colab T4s, free Kaggle T4×2s, paid Modal A100s, or a local NVIDIA GPU — the
user picks the backend per command. The user's $0/month research budget is no longer the
bottleneck; the same setup that works for a PhD student in Cairo works for
a clinician in Lagos.

### 4. Provenance is the moat

Every binder PDB the pipeline outputs is one click from:

- the patient cohort it came from,
- the differential-expression statistics that flagged the target,
- the AlphaFoldDB structure used,
- the SURFACE-Bind site predicted,
- the trajectory seed and designer commit SHA,
- the validator metrics,
- the container digest of every step.

This is recorded as a [PROV-O](https://www.w3.org/TR/prov-o/) JSON-LD manifest
and packaged as an [RO-Crate](https://www.researchobject.org/ro-crate/) — both
W3C/FAIR-friendly standards. Reviewers can audit the chain. Clinicians can
defend the choice in IND filings. No other protein-design tool offers this.

### 5. Failure-honest by default

The pipeline catalogs *why* targets fail (no AlphaFoldDB model, no
SURFACE-Bind site, fails specificity, designer fails to converge, validator
rejects), publishing a `failure_taxonomy.parquet` next to the successes. Every
existing tool quietly drops failures. We surface them, because that's what
users actually need to triage.

### 6. Commercially defensible

The default config uses only MIT / Apache / BSD / CC-BY components. Every
non-permissive opt-in (e.g. AlphaFold2 weights for the AF2-IG validator) is
behind a CLI banner and documented in [LICENSING.md](../LICENSING.md). A
pharma early-discovery team can run it without legal review.

---

## What you can do with it

### Discovery half — CPU, no GPU

```bash
bindsight discover examples/tcga_luad.yaml --out runs/luad_v01
```

Produces:

- `runs/luad_v01/deg/results.parquet` — DEG table from pydeseq2
- `runs/luad_v01/targets/candidates.parquet` — surface-restricted, druggable,
  tissue-specific target shortlist
- `runs/luad_v01/epitopes/epitopes.parquet` — top-N candidates with structure
  paths
- `runs/luad_v01/run_manifest.jsonld` — PROV-O audit trail

Useful right now if you're a translational researcher trying to triage a
cancer cohort for surface-antigen targets without writing 600 lines of glue.

### Design + validation half — GPU-backed

```bash
bindsight design runs/luad_v01 --backend colab --trajectories 50
bindsight validate runs/luad_v01 --backend colab --validator boltz2
bindsight rank runs/luad_v01
bindsight report runs/luad_v01 --format html
```

Adds:

- Per-target de novo binder PDBs from RFdiffusion + ProteinMPNN
- Boltz-2 affinity + iPTM scores per design
- Composite ranking
- Self-contained HTML report (embedded volcano plot + tables + PROV-O manifest)
- RO-Crate export for Zenodo deposit

### Validation (done — discovery half)

A [companion report](https://github.com/mikhaeelatefrizk/bindsight/blob/main/paper/validation/manuscript.md)
runs the discovery half on six real indication-matched TCGA cohorts. It
rediscovers **ERBB2 at rank 4** in HER2-enriched breast cancer (using PAM50
subtype stratification — versus rank 25 in the unsplit BRCA cohort, where the
HER2 signal is averaged away) and is **specific**: antigens that are not
transcriptionally over-expressed at the bulk level (EGFR, which is
mutation-driven; CEA, co-expressed in normal colon) are correctly not surfaced.
Reproducible artifacts are in `benchmarks/validation/`. The three-way *designer*
benchmark is GPU-only; a runnable, CPU-tested harness + protocol ship in
`benchmarks/designer_benchmark/`.

### v1.0

Multi-modal tumor-selectivity scoring (single-cell + co-expression +
immunopeptidomics) to extend discovery beyond bulk differential expression,
plus the populated designer benchmark.

---

## Who this is for

| Audience | What they get |
|---|---|
| **Translational researcher** with a TCGA cohort and limited compute | A reproducible "data → designed binder" pipeline without paying SaaS prices |
| **Clinical biologist** who needs an audit trail | A PROV-O / RO-Crate trace from binder back to expression evidence — defensible at thesis defense and useful for IND filings |
| **Method developer** building a new designer or validator | A held-out evaluation harness (rediscovery of known antigens) to benchmark against a fixed upstream pipeline |
| **Pharma early discovery team** | A free open-source comparator they can layer their proprietary designers into via the plugin interface |
| **Educator** teaching computational biology | A working end-to-end example that touches DEG, structural biology, deep learning, and software engineering — in one repo |
| **PI hiring** for a bioinformatics + ML role | A CV artifact that demonstrates real cross-domain competence |

---

## What it is NOT

- **Not a wet-lab pipeline.** Output is *in silico* binder candidates. Wet
  validation (yeast display, biolayer interferometry, etc.) is the user's job.
- **Not a regulated GxP tool.** The provenance graph is a starting point for
  an audit trail, not a substitute for a GxP-validated system.
- **Not a structure predictor itself.** It wraps Boltz-2 / Chai-1 / AlphaFold;
  the predictions are theirs, attributed in every manifest.
- **Not a replacement for domain expertise.** A surface-protein hit list still
  needs a human to apply biological judgment about safety, specificity,
  immunogenicity, and developability.

---

## The honest limits in v0.x

We're transparent about what doesn't work yet. From [ARCHITECTURE.md § 10](../ARCHITECTURE.md#10-risks-honest):

- pydeseq2 is not bit-equivalent to R DESeq2 (documented)
- SURFACE-Bind covers ~2,800 surface proteins, not all of them (graceful drop)
- Free Colab sessions die mid-job (per-trajectory checkpointing mitigates)
- Designer choice (RFdiff vs BindCraft vs BoltzGen) will keep evolving
  (plugin interface; the rfdiff_mpnn arm is benchmarked today — see the designer
  benchmark — with BindCraft/BoltzGen on paid ≥24–32 GB GPUs as it grows)
- mRNA abundance is not cell-surface protein abundance — SURFY confirms a protein
  *can* reach the surface, not how much is actually there. Surfaced candidates are
  hypotheses to confirm at the protein level (flow cytometry / IHC / Human Protein
  Atlas) before trusting them. (Stated in every run's report Limitations section.)
- Bulk expression can come from non-tumour cells — high apparent over-expression may
  reflect infiltrating immune/stromal cells or tumour purity rather than a
  tumour-intrinsic target; single-cell / deconvolution evidence is needed to be sure
  (the multi-modal tumour-selectivity layer for v1.0).
- Disease specificity is hard — "up in cancer, low in vital tissue" predictably
  finds known antigens (a feature for the v0.1 rediscovery paper, a problem
  layer for v1.0)

---

## Why this is the right project at the right time

- **The OSS protein-design stack just consolidated.** Boltz-2 (MIT, code +
  weights), BoltzGen (MIT), Chai-1r (Apache-2), and BindCraft (MIT) all
  shipped permissive licenses in 2025. A year earlier, the "what validator
  do we ship?" question had no clean answer.
- **SURFACE-Bind closed the epitope-prediction gap** for a meaningful slice
  of the surfaceome. Before late 2025, you'd have built that yourself.
- **Free GPU tiers** (Colab T4, Kaggle T4×2) became powerful enough to run
  RFdiffusion + ProteinMPNN at meaningful scale. A year earlier, you'd have
  needed an institutional cluster.
- **Cancer omics is publicly available** (TCGA, recount3, GTEx) — the
  upstream data is *already* in the open.
- **The clinical translation gap is widely acknowledged** (e.g. [Springer
  J Transl Med 2026](https://link.springer.com/article/10.1186/s12967-026-07784-0)).
  Reviewers want to see the bridge built.

All four conditions — permissive validators, the SURFACE-Bind catalog, free
GPU, and acknowledged demand — held simultaneously starting in late 2025.
That's the window.

---

## How is this different from "just calling AlphaFold + RFdiffusion"?

Anyone with a GPU can run the existing tools. The work `bindsight` does is the
*opinionated, validated, reproducible join*. Specifically:

1. **Empirical defense of the defaults.** The discovery half is validated by
   rediscovery on six real TCGA cohorts (`benchmarks/validation/`): it surfaces
   ERBB2 at rank 4 in HER2-enriched breast and is specific against antigens that
   aren't transcriptionally over-expressed. See the
   [validation report](https://github.com/mikhaeelatefrizk/bindsight/blob/main/paper/validation/manuscript.md).
2. **Container-pinned, seed-pinned, weights-pinned reproducibility.** Two runs
   of the same config on the same data should produce byte-identical outputs
   modulo logged stochastic seeds.
3. **Negative-result curation.** A `failure_taxonomy.parquet` per run — every
   target that *didn't* make it, with a reason.
4. **Cost-aware orchestration.** `--dry-run` estimates GPU $ before running.
   Existing tools assume HPC and don't think about cost.
5. **Plugin-not-fork extensibility.** New designers / validators / runners
   ship as separate Python packages that register via entry points. Nobody
   has to fork to extend.

---

## Summary

> Two ecosystems that should be one. A keystone catalog (SURFACE-Bind) that
> just shipped. Permissive validator licenses that just landed. Free GPU
> tiers that just got good enough. Public cancer omics. A reproducibility
> crisis everyone agrees on. One person can connect all of this for the
> first time. That's `bindsight`.

If you want the architectural detail, see [ARCHITECTURE.md](../ARCHITECTURE.md).
If you want to use it now, see [how-to-use.md](how-to-use.md). If you want to
see what it can do, see [use-cases.md](use-cases.md).

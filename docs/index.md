---
title: bindsight — RNA-seq to de novo protein binder design
description: bindsight is an open-source pipeline by Mikhaeel Atef Rizk that turns RNA-seq counts into ranked de novo protein-binder candidates against tumour cell-surface antigens, with full PROV-O / RO-Crate provenance back to the patient cohort.
hide:
  - navigation
---

<div class="bs-hero" markdown="0">
  <h1>Expression → Binder</h1>
  <p class="bs-lede">
    An open-source pipeline that joins cohort RNA-seq target discovery to
    <em>de novo</em> protein-binder design in one reproducible workflow — with
    machine-readable provenance from every ranked binder back to the patient
    samples it came from.
  </p>
  <p class="bs-sub">
    Genomics stops at &ldquo;here are the interesting genes&rdquo;. Protein design starts at
    &ldquo;given a target structure&rdquo;. bindsight is the reproducible, citable bridge between them.
  </p>
  <div class="bs-cta">
    <a class="primary" href="https://huggingface.co/spaces/Mikhaeelatefrizk/bindsight">Try it live</a>
    <a href="results/">See real results</a>
    <a href="what-is-bindsight/">What is bindsight?</a>
    <a href="https://github.com/mikhaeelatefrizk/bindsight">GitHub</a>
  </div>
</div>

<div class="admonition info" markdown="0">
  <p class="admonition-title">In plain terms</p>
  <p>
    bindsight reads a tumour's gene-activity data and looks for proteins that stud the
    surface of cancer cells but not healthy ones. It then designs small custom proteins —
    molecular &ldquo;keys&rdquo; — shaped to latch onto those targets, checks each design with
    an AI structure model to see whether it would actually stick, ranks the best candidates,
    and keeps a complete record of how it reached every answer.
    New to the terms? See the <a href="glossary/">Glossary</a>.
  </p>
</div>

<div class="bs-stats" markdown="0">
  <div class="bs-stat">
    <div class="v">rank 4</div>
    <div class="k">ERBB2 rediscovered</div>
    <div class="d">from real TCGA-BRCA RNA-seq, HER2-enriched subtype</div>
  </div>
  <div class="bs-stat">
    <div class="v">0.84</div>
    <div class="k">best ipTM</div>
    <div class="d">20 de novo ERBB2 binders on a free Kaggle P100</div>
  </div>
  <div class="bs-stat">
    <div class="v">50%</div>
    <div class="k">success @ ipTM 0.65</div>
    <div class="d">validated with Boltz-2</div>
  </div>
  <div class="bs-stat">
    <div class="v">2/2</div>
    <div class="k">consistency check</div>
    <div class="d">antigens with no measured over-expression stay out of the top 20</div>
  </div>
</div>

Those numbers are not illustrative — they come from runs whose inputs, outputs
and provenance are committed in the repository. **[See exactly how they were
produced](results.md).**

!!! warning "Read the binder numbers as provisional"
    The ipTM figures above come from a real Boltz-2 run whose metrics reproduce
    exactly, but the run predates the ProteinMPNN target-chain fix shipped in
    v0.2.1: ProteinMPNN was invoked without `--pdb_path_chains`, so it redesigned
    the HER2 target chain as well as the binder. The designs were therefore
    optimised against a partly-invented target surface and scored against the
    native one. A corrected re-run will supersede them.

!!! note "What 2/2 does and does not show"
    Antigens that fail the over-expression rule (FDR&nbsp;<&nbsp;0.05,
    log2fc&nbsp;≥&nbsp;1.0) are excluded from candidacy **by construction**, so
    finding them outside the top 20 confirms the rule is applied as documented.
    It is an internal consistency check, not a measurement of how well the
    ranking discriminates between real over-expression and clinical fame.

## How it works

<div class="bs-flow" markdown="0">
  <div class="s">Patient RNA-seq<small>counts + design</small></div>
  <div class="s">Differential expression<small>pydeseq2</small></div>
  <div class="s">Cell-surface filter<small>SURFY surfaceome</small></div>
  <div class="s">Safety + tractability<small>GTEx · Open Targets</small></div>
  <div class="s">Targetable site<small>SURFACE-Bind · AlphaFold</small></div>
  <div class="s gpu">Binder design<small>RFdiffusion + MPNN</small></div>
  <div class="s gpu">Structure + affinity<small>Boltz-2</small></div>
  <div class="s">Ranked candidates<small>multi-objective</small></div>
  <div class="s">Provenance<small>PROV-O · RO-Crate</small></div>
</div>

Amber stages need a GPU and are offloaded to Colab, Kaggle, Modal or your own
Docker host. Everything else runs on a CPU laptop — and in your browser on the
hosted app.

## Try it, three ways

<div class="bs-cards" markdown="0">
  <div class="bs-card">
    <h3>In your browser</h3>
    <p>Zero install. The hosted app runs the discovery half live on a real TCGA
    cohort, and lets you explore the designed binders in 3-D.</p>
  </div>
  <div class="bs-card">
    <h3>One command</h3>
    <p><code>bindsight demo</code> runs the whole discovery half locally on a real
    NIH/GDC cohort and writes a self-contained HTML report.</p>
  </div>
  <div class="bs-card">
    <h3>Your own cohort</h3>
    <p>Point it at your counts matrix and sample design, choose a GPU backend
    when you are ready to design, and export an RO-Crate for Zenodo.</p>
  </div>
</div>

```bash
pip install -e ".[discover,report]"
bindsight demo      # real TCGA-BRCA cohort, CPU only, full provenance
bindsight ui        # the web interface, locally
```

## Start here

- **[Real results](results.md)** — what it has actually demonstrated.
- **[What is bindsight?](what-is-bindsight.md)** — the 5-minute pitch.
- **[How to use it](how-to-use.md)** — install, the demo, and the full
  `discover → design → validate → rank → report → export` flow.
- **[Use cases](use-cases.md)** — concrete scenarios.
- **[Designing on Colab](colab-design-howto.md)** — the GPU half on free Colab.

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

## Cite it

bindsight is AGPL-3.0-or-later and archived on Zenodo with a DOI. If it helps
your work, please cite the concept DOI
[10.5281/zenodo.20121495](https://doi.org/10.5281/zenodo.20121495) — it always
resolves to the latest archived version, which is what you want when citing the
software rather than one specific release. Ready-made entries are in
[`CITATION.cff`](https://github.com/mikhaeelatefrizk/bindsight/blob/main/CITATION.cff).

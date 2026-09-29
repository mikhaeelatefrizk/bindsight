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
    <a class="primary" href="https://bindsight-research.mikha-50.chatgpt.site">Open research workspace</a>
    <a href="results/">See real results</a>
    <a href="what-is-bindsight/">What is bindsight?</a>
    <a href="how-to-use/">Run it yourself</a>
    <a href="https://github.com/mikhaeelatefrizk/bindsight">GitHub</a>
  </div>
</div>

<div class="admonition info" markdown="0">
  <p class="admonition-title">In plain terms</p>
  <p>
    bindsight compares RNA-seq counts between conditions to prioritise candidate
    cell-surface targets. It can design protein sequences and assess their predicted
    complexes while recording inputs, settings and outputs. RNA abundance is not
    surface protein abundance, and model confidence does not establish binding,
    specificity or clinical safety.
    New to the terms? See the <a href="glossary/">Glossary</a>.
  </p>
</div>

<div class="bs-stats" markdown="0">
  <div class="bs-stat">
    <div class="v">1 of 291</div>
    <div class="k">CA9 surfaced</div>
    <div class="d">clear-cell kidney, patient-matched TCGA-KIRC contrast without biomarker stratification</div>
  </div>
  <div class="bs-stat">
    <div class="v">0.88</div>
    <div class="k">best ipTM</div>
    <div class="d">20 de novo ERBB2 binders on a free Kaggle T4</div>
  </div>
  <div class="bs-stat">
    <div class="v">30% / 50%</div>
    <div class="k">designs / shuffled controls</div>
    <div class="d">6/20 designs and 10/20 shuffles exceed ipTM 0.65 under the seeded
    five-draw calibration. The threshold-crossing rate is withdrawn as a measure
    of design quality.</div>
  </div>
  <div class="bs-stat">
    <div class="v">1 of 17</div>
    <div class="k">recall @ rank 20</div>
    <div class="d">approved-agent antigens, 95% CI 0.01–0.27</div>
  </div>
</div>

Those numbers come from recorded computations. Committed summaries, predicted
structures and provenance metadata can be inspected here; the raw calibration
inputs, cohort caches and complete provenance crate are not all included.
**[See the evidence and its reproducibility limits](results.md).**

!!! success "These figures come from the corrected protocol"
    An earlier run invoked ProteinMPNN without `--pdb_path_chains`, so it
    redesigned the HER2 target chain as well as the binder, and its numbers
    (best ipTM 0.84, 50% success) are withdrawn. The run above holds the target
    fixed, and that is checked rather than asserted: all 20 designs carry a
    target chain byte-identical to the native 142-residue domain IV. The
    corrected mean ipTM is *lower* — 0.51 against 0.59 — which is what you would
    expect once designs stop being scored against a surface they helped invent.

!!! note "What 1 of 17 does and does not show"
    That is the recall of clinically approved antigens across a pre-registered
    panel of 22 antigen-cohort pairs across fifteen TCGA projects, using patient-matched
    tumour/normal samples without biomarker stratification. The interval matters at
    this panel size, and repeated antigens make the pairs correlated. Eleven of the
    seventeen fail the composite significance rule, one is downregulated, and three
    fall beyond the enrichment cutoff. These are different outcomes, not a blanket
    claim of absent overexpression. Approved-agent tier does not mean approval in
    every listed cancer. An
    earlier six-cohort version reported ERBB2 at rank 4 and recall@5 of 33%; it
    is withdrawn, because its breast cohort was stratified by a PAM50 subtype
    call and ERBB2 is one of the fifty genes that classifier is built from.

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

Amber stages need a GPU. A free Kaggle T4 is the verified route, and the one the
committed benchmark used. Local protein design requires a separately configured
NVIDIA/CUDA environment; the default Docker image is CPU-only. CPU discovery is
subject to dataset memory requirements. See the [local workspace guide](local-workspace.md)
for the downloadable setup and platform limitations.

## Try it, three ways

<div class="bs-cards" markdown="0">
  <div class="bs-card">
    <h3>In your browser</h3>
    <p><code>bindsight ui</code> serves the interface locally in seconds: the
    committed evidence, the twenty designed binders in 3-D, and a one-click run
    of the discovery half on a real TCGA cohort. Its evidence surface is
    published here too, with nothing to install: <a href="results/">the twenty
    complexes</a> draw in this page's browser, and <a href="try-your-data/">the
    input checker</a> is the same file <code>bindsight ui</code> loads.</p>
  </div>
  <div class="bs-card">
    <h3>One command</h3>
    <p><code>bindsight demo</code> runs the whole discovery half locally on a real
    NIH/GDC cohort and writes a self-contained HTML report.</p>
  </div>
  <div class="bs-card">
    <h3>Your own cohort</h3>
    <p>Point it at your counts matrix and sample design, choose a GPU backend
    when you are ready to design, and export an RO-Crate for deposit.</p>
  </div>
</div>

```bash
pip install "bindsight[discover,report]"
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

bindsight is AGPL-3.0-or-later. This release is not archived under a DOI — if it
helps your work, cite the repository, the tag you ran and the checksums attached
to the release.
Ready-made entries are in
[`CITATION.cff`](https://github.com/mikhaeelatefrizk/bindsight/blob/main/CITATION.cff).

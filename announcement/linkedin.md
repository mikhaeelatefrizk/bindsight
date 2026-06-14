# LinkedIn announcement — copy-paste ready

Two versions: a short one (most engagement) and a long-form one (better for
thought-leadership / job search visibility).

---

## Short version (recommended)

> 🧬 I'm releasing **bindsight** today — the first open-source pipeline that
> takes RNA-seq counts and outputs ranked de novo protein binder candidates,
> with a complete audit trail back to the patient cohort.
>
> The bridge between genomics and protein design has been an ad-hoc, weeks-of-
> glue-scripting exercise for years. bindsight is that bridge as one tool. CPU
> laptop is enough; the GPU half offloads to free Google Colab.
>
> 🌐 Live demo (zero install — runs in your browser):
> https://bindsight.streamlit.app
>
> 🐙 Source: https://github.com/mikhaeelatefrizk/bindsight
>
> 📄 Citable: https://doi.org/10.5281/zenodo.20121496
>
> The pipeline rediscovers HER2 (ERBB2) and EGFR — the textbook cancer
> immunotherapy targets — appear among the candidates when their signal is
> present, discovered from a real TCGA breast-cancer cohort (NIH/GDC) with full
> provenance. 200+ tests passing across Linux/macOS/Windows. MIT licensed.
>
> Built solo over the past few weeks. Particularly grateful to the upstream
> open-source teams whose work made this constructible: PyDESeq2, RFdiffusion,
> ProteinMPNN, Boltz-2, SURFACE-Bind, AlphaFoldDB, Open Targets, Streamlit.
>
> Open to collaborators for the v0.2 validation paper (rediscovery of known
> antigens from blinded TCGA cohorts).
>
> #Bioinformatics #ProteinDesign #OpenScience #DrugDiscovery #AlphaFold

---

## Long version (better for thought-leadership / portfolio)

> **🧬 Releasing bindsight: closing the gap between genomics and protein design**
>
> Today I'm publishing v0.1.0 of an open-source tool I've been building:
> **bindsight** — the first pipeline that takes RNA-seq counts as input and
> outputs ranked de novo protein binder candidates as output, with a complete
> audit trail back to the patient cohort the targets came from.
>
> **The problem:**
>
> Computational biology has two ecosystems that rarely talk to each other:
>
> ▸ **Genomics** (DESeq2, edgeR, Seurat, scanpy, TCGA) reliably tells us
>    which genes are dysregulated in disease — but stops at the gene list.
>
> ▸ **Protein design** (RFdiffusion, ProteinMPNN, BindCraft, AlphaFold,
>    Boltz-2) makes remarkable strides at producing binders against arbitrary
>    targets — but assumes the user has already chosen the target.
>
> Bridging the two — *"this gene is up in disease, low in healthy tissue,
> surface-exposed, and here is a designed binder candidate ranked by predicted
> affinity"* — used to take a competent researcher several weeks of glue
> scripting per project, was rarely reproducible across labs, and had no
> citable software artifact.
>
> **What I built:**
>
> bindsight runs on a CPU laptop. Discovery (differential expression →
> surfaceome filter → druggability → AlphaFoldDB structure pull) takes ~30
> seconds. The GPU half (RFdiffusion backbone → ProteinMPNN sequence →
> Boltz-2 validation) is templated to free Google Colab notebooks, paid Modal
> serverless GPU, or local NVIDIA Docker.
>
> Every output is one click away from its evidence chain — the patient cohort,
> the differential expression statistics, the AlphaFoldDB model, the
> SURFACE-Bind site, the trajectory seed, the validator metrics, the container
> digest of every step. All packaged as a W3C PROV-O JSON-LD manifest plus an
> RO-Crate zip ready for Zenodo deposit.
>
> **Why now:**
>
> Three things had to align in late 2025 for one person to build this:
> (1) the SURFACE-Bind catalog (PNAS 2025) shipped pre-computed targetable
> sites for ~2,800 surface proteins; (2) Boltz-2 and BoltzGen released both
> code and model weights under MIT — the first commercially permissive
> state-of-the-art validators; (3) free Google Colab T4 GPUs became powerful
> enough to run RFdiffusion at meaningful scale. None of these were true a
> year ago.
>
> **Try it:**
>
> 🌐 Web demo (no install — runs in your browser):
> https://bindsight.streamlit.app
>
> 🐙 Source code (MIT):
> https://github.com/mikhaeelatefrizk/bindsight
>
> 📄 Citable Zenodo DOI:
> https://doi.org/10.5281/zenodo.20121496
>
> **What's next:**
>
> A v0.2 validation manuscript is planned: rediscovery of HER2/EGFR/MSLN/CLDN6
> from blinded TCGA cohorts, plus a three-way designer benchmark
> (RFdiff+MPNN vs BindCraft vs BoltzGen). I'd love collaborators on that —
> particularly people with TCGA-LUAD/BRCA/PAAD/OV cohorts already processed,
> or wet-lab capacity for downstream binder validation.
>
> Massive thanks to the open-source maintainers whose work made bindsight
> possible: the PyDESeq2 team at Owkin, Joe Watson + Justas Dauparas + the
> Baker Lab for RFdiffusion + ProteinMPNN, Jeremy Wohlwend + Hannes Stark for
> Boltz-2 + BoltzGen, Hamed Khakzad for SURFACE-Bind, and the maintainers of
> AlphaFoldDB, Open Targets, Streamlit, Snakemake. This is a wrapper around
> their work; the intellectual credit is theirs.
>
> #Bioinformatics #ProteinDesign #ComputationalBiology #OpenScience
> #DrugDiscovery #AlphaFold #RNAseq #TranslationalResearch

---

## When to post

LinkedIn engagement peaks Tuesday–Thursday, 08:00–10:00 in your audience's
timezone. Most likely best windows for you:

- **For European bio audience:** Tuesday/Wednesday/Thursday, 08:00–10:00 CET
- **For US bio audience:** Tuesday/Wednesday/Thursday, 14:00–16:00 CET (= 08:00–10:00 EST)

Pick one window. If posting at both, leave 24 hours between the two posts.

---

## Who to tag (after posting, in comments)

Reply to your own post with comments tagging:

- The maintainers of upstream tools (look up their LinkedIn profiles)
- Any PI / lab in your network whose research aligns
- EMBL-EBI and bioinformatics / protein-design groups whose work aligns with bindsight

This both gives proper credit AND multiplies your post's reach into adjacent
audiences.

---

## Image to attach

Attach a screenshot of bindsight.streamlit.app showing the **Home** page with
the colorful badges and the "✨ Click Demo" callout. Reach this by:

1. Open https://bindsight.streamlit.app/
2. Wait for it to fully render
3. Take a full-window screenshot
4. Crop to the upper third (sidebar + headline + KPI badges visible)

Posts with images get ~2x the impressions of text-only posts on LinkedIn.

---

## Optional: poll variant for higher engagement

LinkedIn's poll feature can boost engagement. Example:

> 🧬 If you could automate one bottleneck in your translational research, what
> would it be?
>
> ▸ Going from RNA-seq to designable target candidates (this is bindsight)
> ▸ Designing protein binders against a chosen target
> ▸ Validating designed binders in silico
> ▸ Wet-lab protein synthesis + assay
>
> Check out the live demo we just shipped: https://bindsight.streamlit.app

(Use this only if you're comfortable with the slightly more "marketing-y"
tone. Polls drive engagement but can feel less authentic.)

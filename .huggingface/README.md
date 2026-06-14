---
title: bindsight
emoji: 🧬
colorFrom: blue
colorTo: green
sdk: docker
app_port: 8501
pinned: false
license: mit
short_description: RNA-seq counts → ranked de novo protein binder candidates
tags:
  - streamlit
  - bioinformatics
  - rna-seq
  - protein-design
  - alphafold
  - reproducibility
  - prov-o
  - de-novo-binder-design
---

# bindsight

> **Expression → Binder.** The first open-source pipeline that takes
> RNA-seq counts and outputs ranked de novo protein binder candidates,
> with full provenance back to the patient cohort.

This Hugging Face Space is the **primary** hosted demo of bindsight.
The canonical source repo, full documentation, JOSS submission, and
bioRxiv preprint live at <https://github.com/mikhaeelatefrizk/bindsight>;
a Streamlit Community Cloud mirror lives at
<https://bindsight.streamlit.app/>.

> Free-tier Spaces sleep after about 48 h of no traffic. A GitHub Actions
> cron in the source repo pings this URL every 6 h *and* checks the
> Space's runtime stage via the HF API, so most visits land on a hot
> app; if you arrive after a long quiet stretch, the wake-up screen
> typically clears in 30–60 s. Upgrading the Space hardware tier in
> Settings disables auto-sleep entirely.

## Deployment

This Space is a Docker-based deployment that pulls `bindsight` from the
GitHub `main` branch at build time (see `requirements.txt` and
`Dockerfile` on this Space). To update the deployed code:

1. Push to <https://github.com/mikhaeelatefrizk/bindsight> `main`.
2. On this Space: Settings → "Factory rebuild" (forces a fresh `pip
   install` from the new `main`).

The `.huggingface/README.md` in the source repo is a **documentation
mirror** of the metadata block above; the file actually rendered on
this page lives in the Space's own git repo at
`https://huggingface.co/spaces/Mikhaeelatefrizk/bindsight`. Keep the
two in sync by hand when you change wording.

## Quick start

Click **Demo** in the sidebar for a guided run on a real TCGA breast-cancer
cohort (NIH/GDC, tumor vs. adjacent normal).  The pipeline discovers
antibody-tractable cell-surface antigens over-expressed in tumor, with full
provenance; known targets such as HER2 (ERBB2, UniProt P04626) appear among
the candidates when their expression signal is present.

The first visitor on a fresh container pays a ~60 s cold-run cost
(real PyDESeq2 + Open Targets + AlphaFoldDB pulls); every subsequent
visitor gets the cached result in ~0.1 s thanks to
`@st.cache_resource` / `@st.cache_data` in
`bindsight/report/webapp.py`.

## What this is

Two ecosystems in computational biology have run in parallel for years:

- **Genomics** stops at *"here are the interesting genes."*
- **Protein design** starts at *"given a target structure."*

bindsight is the first open-source tool that connects them: from RNA-seq
counts to ranked de novo protein binder candidates, with end-to-end W3C
PROV-O JSON-LD provenance and an RO-Crate export for reproducibility.

The discovery half (PyDESeq2 → SURFY → Open Targets → AlphaFoldDB →
SURFACE-Bind) runs on this Space's free CPU.  The design half templates
Colab/Modal GPU jobs (RFdiffusion + ProteinMPNN + Boltz-2) — see the
Colab recipe in the GitHub repo.

## License

MIT.  See [LICENSE](https://github.com/mikhaeelatefrizk/bindsight/blob/main/LICENSE)
on GitHub for the full text and per-component commercial-use audit.

## Citation

If you use bindsight in research, please cite the Zenodo DOI:
[10.5281/zenodo.20121496](https://doi.org/10.5281/zenodo.20121496).

JOSS paper and bioRxiv preprint are currently in review; both will be
linked from the GitHub README when published.

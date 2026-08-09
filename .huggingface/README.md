---
title: bindsight
emoji: 🧬
colorFrom: blue
colorTo: green
sdk: docker
app_port: 8501
pinned: false
license: agpl-3.0
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

> **Expression → Binder.** An open-source pipeline that joins cohort
> RNA-seq target discovery to de novo protein binder design in one
> reproducible workflow, with machine-readable provenance from every
> ranked binder back to the patient samples it came from.

This Space hosts the bindsight web app. The canonical source repo and the
full documentation live at
<https://github.com/mikhaeelatefrizk/bindsight>; a Streamlit Community
Cloud deployment of the same app lives at
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
`Dockerfile` on this Space).

Both the deployed code and this page follow `main` automatically:
`sync-hf-space.yml` in the source repo uploads `.huggingface/README.md`
over this file and issues a **factory** rebuild on every published
release. A plain restart would reuse the cached image and keep serving
whatever bindsight revision the last build resolved, so only a factory
reboot picks up new code. Do not edit this page on the Space — the next
release overwrites it; edit `.huggingface/README.md` in the repo instead.

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

Binder-design workflows (BindCraft, BinderFlow, `dl_binder_design`,
nf-proteindesign) start from a target you have already picked;
expression- and surfaceome-based target-discovery work (pan-cancer
surfaceome screens, pVACtools for neoantigens) stops at a ranked gene or
peptide list.  bindsight is, as far as we are aware, the first
open-source tool that runs **both halves end-to-end** and keeps a
machine-readable audit trail *across the join*: from a designed binder
back through the epitope, the structure, the surfaceome call and the
differential-expression contrast to the individual patient samples —
W3C PROV-O JSON-LD throughout, with an RO-Crate export.  The individual
steps are the community's; the join, its defaults and its provenance are
what bindsight contributes.

The discovery half (PyDESeq2 → SURFY → Open Targets → AlphaFoldDB →
SURFACE-Bind) runs on this Space's free CPU.  The design half templates
Colab/Modal GPU jobs (RFdiffusion + ProteinMPNN + Boltz-2) — see the
Colab recipe in the GitHub repo.

## License

AGPL-3.0-or-later.  See [LICENSE](https://github.com/mikhaeelatefrizk/bindsight/blob/main/LICENSE)
on GitHub for the full text and per-component commercial-use audit.

## Citation

If you use bindsight in research, please cite the Zenodo concept DOI
[10.5281/zenodo.20121495](https://doi.org/10.5281/zenodo.20121495), which
always resolves to the latest archived version (v0.2.2 at the time of
writing).

A JOSS software paper and a bioRxiv preprint are drafted but not yet
submitted (sources under `paper/` in the GitHub repo); both will be
linked from the GitHub README if and when they are published.

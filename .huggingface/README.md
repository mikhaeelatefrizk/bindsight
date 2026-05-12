---
title: bindsight
emoji: 🧬
colorFrom: blue
colorTo: green
sdk: streamlit
sdk_version: 1.36.0
app_file: streamlit_app.py
pinned: false
license: mit
short_description: RNA-seq counts → ranked de novo protein binder candidates
tags:
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

This Hugging Face Space hosts the live web demo of bindsight.  The
canonical source repo, full documentation, JOSS submission, and bioRxiv
preprint live at <https://github.com/mikhaeelatefrizk/bindsight>.

## Quick start

Click **Demo** in the sidebar for a 60-second guided run on a shipped
10-gene tumor-vs-normal cohort.  The pipeline rediscovers HER2 (ERBB2)
and EGFR — the textbook cancer immunotherapy targets — as the top-2
antibody-tractable surface antigens.

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

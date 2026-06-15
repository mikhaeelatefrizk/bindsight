---
title: 'bindsight: a reproducible bridge from RNA-seq counts to de novo protein binder design'
tags:
  - Python
  - bioinformatics
  - protein design
  - de novo binder design
  - RNA-seq
  - target discovery
  - reproducibility
  - PROV-O
  - RO-Crate
authors:
  - name: Mikhaeel Atef Rizk Wahba
    orcid: 0009-0006-1069-9558
    corresponding: true
    affiliation: 1
affiliations:
  - name: Independent Researcher, Cairo, Egypt
    index: 1
date: 11 May 2026
bibliography: paper.bib
---

# Summary

Modern computational biology has two parallel ecosystems that rarely talk to
each other. Bulk and single-cell **RNA-seq analysis** [@Love2014; @Anders2010;
@Stuart2019] reliably tells us which genes are differentially expressed in a
disease, but stops at the gene list. **De novo protein-binder design**
[@Watson2023; @Dauparas2022; @Pacesa2025; @Wohlwend2025], conversely, has made
remarkable strides in producing binders against arbitrary protein targets, but
assumes the user has already chosen the target. Going from one ecosystem to
the other — *"this gene is up in disease, low in healthy tissue, surface-
exposed, and here is a designed binder candidate ranked by predicted
affinity"* — is currently an ad-hoc, project-specific exercise that takes a
competent researcher several weeks of glue-scripting and is rarely
reproducible across labs.

`bindsight` closes this gap. It is the first open-source command-line tool
and web application that takes RNA-seq counts as input and produces ranked,
structurally-validated *de novo* protein-binder candidates as output, with a
complete `PROV-O` JSON-LD [@PROVO] / RO-Crate [@SoilandReyes2022] audit trail
back to the patient cohort the targets came from. The pipeline runs entirely
on a CPU laptop for the discovery half (differential expression →
surfaceome filter → druggability → structural pre-flight); the GPU half
(`RFdiffusion` [@Watson2023] backbone generation, `ProteinMPNN`
[@Dauparas2022] sequence design, `Boltz-2` [@Wohlwend2025] structural and
affinity validation) runs end-to-end on free Google Colab notebooks, paid Modal
serverless GPU, or local NVIDIA Docker.

A **public web demo** at <https://bindsight.streamlit.app> lets anyone run
the full discovery pipeline in their browser without installing anything. A
guided demo over a **real TCGA breast-carcinoma cohort** (tumor vs. adjacent
normal, auto-downloaded from NIH/GDC) shows the pipeline discovering
antibody-tractable cell-surface antigens over-expressed in tumor, with full
provenance; established targets such as ERBB2 (HER2) appear among the
candidates when their expression signal is present in the sampled cohort.
A companion rediscovery validation (`benchmarks/validation/`,
`paper/validation/manuscript.md`) runs the discovery half on six real
indication-matched TCGA cohorts: it resurfaces ERBB2 at rank 4 in
HER2-enriched breast cancer (using PAM50 subtype stratification) and is
specific — antigens not transcriptionally over-expressed at the bulk level
(e.g. EGFR, CEA) are correctly not surfaced, so sensitivity tracks
differential-expression effect size.

# Statement of need

Three structural conditions for `bindsight` to exist as a one-person open-
source project all became true in late 2025 and not before:

1. The **`SURFACE-Bind`** catalogue [@Khakzad2025] published pre-computed
   targetable interfaces and binder seeds for ~2,800 human cell-surface
   proteins. Before this, identifying a druggable epitope on an arbitrary
   surface antigen was itself a multi-month research effort.
2. **Permissive licensing** for state-of-the-art structure-and-affinity
   predictors became the norm. `Boltz-2` [@Wohlwend2025] released both code
   and weights under MIT; `Chai-1r` followed with Apache-2; `BoltzGen`
   [@Stark2025] released MIT-licensed binder-design weights. Before late
   2025, every viable validator carried non-commercial restrictions
   inherited from `AlphaFold2`'s weights license.
3. **Free GPU tiers** (Google Colab T4, Kaggle T4×2) became powerful enough
   to run `RFdiffusion` and `ProteinMPNN` at meaningful scale. A year
   earlier, an institutional cluster was required.

The result is a window in which any individual researcher can build —
without HPC access, without commercial licences, and without writing a
new model — the bridge that the field has been treating as a per-project
chore. `bindsight` is that bridge, packaged as software anyone can install
and cite.

The intended user audiences:

- **Translational researchers** with a TCGA cohort and limited compute who
  want a reproducible "data → designed binder" pipeline without paying for
  commercial SaaS.
- **Clinical biologists** who need a defensible audit trail (PROV-O / RO-
  Crate) from each binder back to its patient-cohort evidence — a
  requirement for thesis-defense scrutiny and increasingly for IND filings.
- **Method developers** building new designers or validators, who benefit
  from a held-out evaluation harness on known antigens with a fixed upstream
  pipeline.
- **Pharma early-discovery teams** wanting an open, license-defensible
  comparator they can extend with proprietary designers via a plugin
  interface.

# Software description

`bindsight` is a Python package (Python ≥ 3.11) installable via
`pip install -e ".[discover,report]"` from source. The discovery half wraps
`pydeseq2` [@Muzellec2023] for differential expression analysis, the
Open Targets Platform [@Ochoa2023] for druggability and safety annotation,
the `SURFY` surfaceome list [@BauschFluck2018] for surface-protein
filtering, and the `AlphaFoldDB` [@Varadi2024] REST API for structure
retrieval. (Targetable-site prediction via `SURFACE-Bind` [@Khakzad2025] is a
planned enhancement; the design step currently targets the whole surface.)
Outputs are written as Apache Parquet with a single
PROV-O JSON-LD `run_manifest.jsonld` enumerating every stage's tool,
version, license, container digest, parameters, and SHA-256 of all input
and output artifacts. A final RO-Crate 1.1 [@SoilandReyes2022] zip,
generated by `bindsight export`, is suitable for direct deposit on Zenodo
or Figshare.

The GPU half — design with `RFdiffusion` + `ProteinMPNN` + `Boltz-2` (plus
optional `BindCraft`, `BoltzGen`, `Chai-1r`, and AF2-initial-guess) — runs
end-to-end through a single executor (`bindsight.runners.job_exec`) on the
backend the user selects: serverless `Modal`, a local NVIDIA GPU (native or
Docker), `Kaggle`, or a self-contained `Colab` notebook patterned on the
canonical upstream notebooks (`ColabDesign`, `dl_binder_design` [@Bennett2023]).

A multi-page web interface, deployed to Streamlit Community Cloud at
<https://bindsight.streamlit.app>, exposes the same pipeline through a
zero-install browser UI with five views: a Home page, a one-click Demo, a
"Run on my data" file-upload form, a "Browse a run" inspector, and an About
page.

# Quality assurance

The package ships **200+ unit and integration tests** that run in a few
minutes and cover: the Pydantic v2 manifest schema, every API client
(Open Targets, AlphaFoldDB), the SURFY filter, the discovery pipeline end-
to-end with mocked GPU runners, the rank module, the RO-Crate exporter, and
the Streamlit-Cloud entry point. Continuous integration on GitHub Actions
runs the suite on Linux, macOS, and Windows for both Python 3.11 and 3.12;
the v0.1.0 release is green across all six platforms.

# Acknowledgements

`bindsight` is an opinionated wrapper; intellectual credit belongs to the
upstream tool authors cited throughout. The author thanks the open-source
maintainers of `pydeseq2`, `Boltz-2`, `RFdiffusion`, `ProteinMPNN`,
`SURFACE-Bind`, `Streamlit`, and `Snakemake` whose work made this bridge
constructible.

# References

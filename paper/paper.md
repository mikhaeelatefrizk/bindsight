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
date: 20 September 2026
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
affinity"* — is an ad-hoc, project-specific exercise that takes a competent
researcher several weeks of glue-scripting and is rarely reproducible across
labs.

`bindsight` closes this gap. It is an open-source command-line tool and web
application that takes RNA-seq counts as input and produces ranked,
structure-scored *de novo* protein-binder candidates as output, with a
complete `PROV-O` JSON-LD [@PROVO] / RO-Crate [@SoilandReyes2022] audit trail
back to the patient cohort the targets came from.

"Structure-scored" is deliberate, and narrower than "validated". Each candidate
carries a Boltz-2 interface confidence, and a paired control shipped with the
tool folds every design beside a shuffle of its own sequence — same length, same
composition, order destroyed. On the committed ERBB2 run the shuffles cleared
the customary ipTM 0.65 bar more often than the designs (50% against 30%; paired
difference −0.043, 95% CI −0.142 to +0.054). The confidence numbers are
therefore a triage order for wet-lab work, not evidence of binding, and
`bindsight` reports them as such. The contribution claimed here is the
reproducible bridge and its provenance, not a demonstration of binder efficacy.

# Statement of need

Three structural conditions for `bindsight` to exist as a one-person open-
source project became true between late 2024 and 2026, and not before:

1. The **`SURFACE-Bind`** catalogue [@Balbi2026] (2026) published pre-computed
   targetable interfaces and binder seeds for ~2,800 human cell-surface
   proteins. Before this, identifying a druggable epitope on an arbitrary
   surface antigen was itself a multi-month research effort.
2. **Permissive licensing** for state-of-the-art structure-and-affinity
   predictors became the norm. `Boltz-2` [@Wohlwend2025] released both code
   and weights under MIT, `Chai-1r` under Apache-2, and `BoltzGen`
   [@Stark2025] released MIT-licensed binder-design weights, where the
   field's most capable predictor, AlphaFold 3, restricts commercial use of
   its weights.
3. **Free GPU tiers** (Google Colab T4, Kaggle T4×2) became powerful enough
   to run `RFdiffusion` and `ProteinMPNN` at meaningful scale. A year
   earlier, an institutional cluster was required.

The result is a window in which any individual researcher can build —
without HPC access, without commercial licences, and without writing a
new model — the bridge that the field has been treating as a per-project
chore. `bindsight` is that bridge, packaged as software anyone can install
and cite. It is written for translational researchers with a TCGA cohort and
limited compute; for clinical biologists who need a defensible audit trail from
each binder back to its patient-cohort evidence; for method developers who want
a held-out evaluation harness on known antigens with the upstream pipeline held
fixed; and for early-discovery teams wanting an open, license-defensible
comparator they can extend with proprietary designers through a plugin
interface.

# State of the field

Open binder-design workflows — BindCraft [@Pacesa2025], BinderFlow,
`dl_binder_design` [@Bennett2023] and nf-proteindesign — all begin at a target
the user has already chosen. Expression- or surfaceome-based target-discovery
workflows end at a ranked gene or peptide list: differential expression with
DESeq2 [@Love2014] or edgeR [@Robinson2010], followed by hand-curated filters
that are rewritten for every project. To our knowledge `bindsight` is the first
open-source tool to run both halves end-to-end and to carry machine-readable
provenance across the join. The individual steps are the community's —
`pydeseq2` [@Muzellec2023] for differential expression, the Open Targets
Platform [@Ochoa2023] for druggability and safety annotation, the `SURFY`
surfaceome list [@BauschFluck2018], the `AlphaFoldDB` REST API [@Varadi2024]
for structures, and the design and validation models above — and the join,
its defaults and its provenance are the contribution.

# Software design

`bindsight` is a Python package (Python ≥ 3.11) installable from PyPI with
`pip install "bindsight[discover,report]"`. Its first design decision is
the split the hardware imposes. The discovery half — differential expression,
druggability and safety annotation, the surfaceome filter, structure retrieval
and a structural pre-flight — runs on a CPU laptop, because a reviewer with no
GPU must be able to re-run it. Targetable-site lookup against `SURFACE-Bind`
(`bindsight/epitopes/surface_bind.py`) reads a vendored catalogue and focuses
the design step on the mapped site, falling back to the whole surface when the
catalogue has no entry for a target.

The GPU half — design with `RFdiffusion` + `ProteinMPNN`, validation with
`Boltz-2` — is dispatched through a single executor
(`bindsight.runners.job_exec`) rather than one integration per backend. The
same executor targets a free `Kaggle` T4, serverless `Modal`, a local NVIDIA
GPU (native or Docker) and a generated `Colab` notebook patterned on the
canonical upstream notebooks (`ColabDesign`, `dl_binder_design`), and the same
plugin protocol admits `BindCraft`, `BoltzGen`, `Chai-1r` and AF2-initial-guess.
The trade-off is stated coverage: only the Kaggle path has been executed end to
end, and it is the path the committed binder benchmark used. Modal and local
Docker are implemented but have not been run end to end; the Colab path needs
a human with a browser tab open, because Google's API does not permit launching
a free-tier notebook from a CLI, so it is a demonstration rather than a
reproducibility path; and no shipped backend yet builds an environment in which
the four additional designers and validators can run, Chai-1r additionally
requiring bfloat16, which no free-tier GPU provides.

Provenance is an output, not a log. Every stage writes its tool, version,
licence, container digest, parameters and the SHA-256 of every input and
output artifact into one PROV-O JSON-LD `run_manifest.jsonld`; results are
Apache Parquet; `bindsight export` packs a run as an RO-Crate 1.1 zip suitable
for direct deposit in a data repository. The manifest is the interface between
the halves, which is what lets a GPU run on another machine be joined back to
the cohort it came from.

The evidence surface is built to be checked without installing anything.
`bindsight ui` serves a five-section interface locally — an Overview, an
Evidence page backed by the committed benchmarks, including the twenty
predicted binder–target complexes rendered in 3-D, a one-click demo, a "Your
data" page that validates a counts matrix and design table in the browser
without uploading them, and a Runs inspector — with no build step and no
network fetch of its own; there is no hosted deployment of it. Two of those
surfaces are also published as static pages on the documentation site, where
they need no installation: the 3-D complexes at
<https://mikhaeelatefrizk.github.io/bindsight/results/> and the input checker
at <https://mikhaeelatefrizk.github.io/bindsight/try-your-data/>.

The package ships **over 2,000 unit and integration tests** that run in a few
minutes and cover the Pydantic v2 manifest schema, every API client (Open
Targets, AlphaFoldDB), the SURFY filter, the discovery pipeline end-to-end with
mocked GPU runners, the rank module, the RO-Crate exporter and the served web
interface. Many are guards on published claims rather than on code: every
number in this paper is pinned to the committed artifact it comes from.
Continuous integration runs the suite on Linux, macOS and Windows for Python
3.11, 3.12 and 3.13 — nine jobs — alongside a lint job, a job that installs the
pinned environment the release records and regenerates the published pages to
confirm they do not change, and a wheel build.

# Research impact statement

The software's own evidence of use is a companion rediscovery study
(`benchmarks/study/`, `paper/validation/manuscript.md`, typeset for bioRxiv
from `paper/biorxiv/`) that runs the discovery half on **fifteen whole,
unstratified TCGA projects** as patient-paired tumour-versus-normal contrasts,
scored against a pre-registered panel of 22 antigen-cohort pairs covering 13
distinct antigens. Nothing in a cohort's definition refers to the antigen being
sought. Under the pre-registered primary denominator, recall at rank 20 is 1 of
17 (95% CI 0.01–0.27); across every regulatory tier it is 3 of 22. Five antigens
reach the shortlist, led by CA9 at rank 1 of 291 in clear-cell renal carcinoma
and GPC3 at 9 of 289 in hepatocellular carcinoma.

The study's more useful output is diagnostic rather than a rate. Eleven of the
seventeen approved-tier pairs fail the significance rule, and a twelfth is
measured as down-regulated: their targeting agents are licensed, so the
antigens are real, but they are not significantly over-expressed in an
unstratified bulk contrast. That delineates the scope of bulk differential
expression as a discovery signal, and motivates the multi-modal specificity
scoring planned for v1.0. The study also found two defects in the pipeline
itself — an enrichment cut applied before the surfaceome filter, and a
surfaceome reference missing CA9, the largest effect in the panel — both since
corrected, with CA9 moving from unreachable to first place.

An earlier six-cohort version of this analysis reported ERBB2 at rank 4 and
recall@5 of 33%. Both figures are withdrawn: the breast cohort had been
stratified by a PAM50 subtype call, and ERBB2 is one of the fifty genes that
classifier is built on, so the tumour arm was selected partly by expression of
the gene then reported as discovered.

Beyond the study, the reproducible materials are the near-term impact claimed:
a guided demo over a real TCGA breast-carcinoma cohort (tumour vs. adjacent
normal, auto-downloaded from NIH/GDC) that runs on a laptop with full
provenance, twenty committed Boltz-2 complexes with per-design metrics, the
paired shuffle control, and a held-out antigen panel against which a method
developer can score a new designer or validator with the upstream pipeline held
fixed.

# AI usage disclosure

The software, its tests, its documentation and this paper were written with
Anthropic's Claude models used as a coding assistant through Claude Code. Every
change was specified, reviewed and accepted by the author, and commits made
with that assistance carry a `Co-Authored-By` trailer naming the model. No
generative model produced, selected or altered any datum, prediction or figure
reported here: every number in this paper is computed by committed scripts from
committed artifacts, and the tests that pin each number to its artifact run in
continuous integration.

# Acknowledgements

`bindsight` is an opinionated wrapper; intellectual credit belongs to the
upstream tool authors cited throughout. The author thanks the open-source
maintainers of `pydeseq2`, `Boltz-2`, `RFdiffusion`, `ProteinMPNN`,
`SURFACE-Bind`, `FastAPI` [@FastAPI], and `Snakemake` [@Molder2021] whose
work made this bridge constructible.

# References

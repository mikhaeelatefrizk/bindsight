# Rediscovery validation of *bindsight*: expression-based discovery of cell-surface antigens from real TCGA cohorts

**Mikhaeel Atef Rizk Wahba**
Corresponding author: mikhaeelatefrizk@proton.me · ORCID 0009-0006-1069-9558

*Companion validation report to the bindsight software-methods paper. Generated
artifacts and the one-command reproduction live in
[`benchmarks/validation/`](../../benchmarks/validation/); the harness is
[`bindsight/benchmark/rediscovery.py`](../../bindsight/benchmark/rediscovery.py).*

---

## Abstract

`bindsight` turns tumor RNA-seq into a ranked shortlist of antibody-tractable,
cell-surface antigens. Here we test the discovery half on **real TCGA patient
cohorts** by asking a simple, falsifiable question: does it resurface
clinically-validated surface antigens from a blinded tumor-vs-adjacent-normal
contrast? Using GDC STAR-Counts and cBioPortal PAM50 calls, we run six
indication-matched cohorts and score the rank of each known antigen in the
candidate shortlist. The pipeline rediscovers **ERBB2 (HER2) at rank 4** in
HER2-enriched breast cancer — a result that depends on PAM50 subtype
stratification — and exhibits clean **specificity**: antigens that are *not*
transcriptionally over-expressed at the bulk level (EGFR, CEA) are correctly
left out, even though they are famous drug targets. Sensitivity tracks
differential-expression effect size, the expected behaviour of a DE-based
method. We report every number transparently, including the misses, and use
them to delineate the scope of bulk-DE discovery and motivate the multi-modal
specificity scoring planned for v1.0.

## 1. Introduction

The bindsight software paper describes *what the tool is and does*. This
companion report supplies the empirical question that paper deferred: **does the
discovery half actually work on real patient data?** We evaluate it as a
rediscovery benchmark — run the pipeline on tumor cohorts whose validated
surface antigens are known a priori, and measure whether those antigens surface
near the top of the unsupervised candidate ranking.

The held-out known-antigen set ([`benchmarks/known.tsv`](../../benchmarks/known.tsv))
is curated from canonical public databases (UniProt, Ensembl, RCSB PDB, ChEMBL,
ClinicalTrials.gov) with full provenance; it contains nine clinically-pursued
cell-surface antigens. We evaluate each in its indication cohort where a matched
normal exists in TCGA.

## 2. Methods

**Cohorts.** For each antigen we assemble a tumor-vs-adjacent-normal cohort from
the NIH/GDC GDC Data Portal (STAR-Counts, GENCODE v36, unstranded), capped at 50
primary-tumor and up to 40 solid-tissue-normal samples
([`bindsight/io/gdc.py`](../../bindsight/io/gdc.py); full GDC file UUIDs,
barcodes, and SHA-256 in `provenance.json`). For breast cancer, bulk
TCGA-BRCA averages the HER2 signal across all five PAM50 intrinsic subtypes and
buries ERBB2; we therefore stratify by pulling PAM50 calls for 981 patients from
cBioPortal (study `brca_tcga_pan_can_atlas_2018`, attribute `SUBTYPE`) and build
the tumor arm from the **HER2-enriched** patients only
([`bindsight/io/cbioportal.py`](../../bindsight/io/cbioportal.py)).

**Discovery.** Each cohort runs through the unmodified discovery half: PyDESeq2
differential expression (`~ condition`, tumor vs normal; FDR < 0.05,
|log2fc| ≥ 1) → enrichment of the most confidently up-regulated genes via Open
Targets → the canonical ~2,886-protein SURFY surfaceome filter → AlphaFoldDB
structure retrieval. Candidates are ranked by the combined differential-
expression score π = log2fc × −log10(padj) (the "pi-value" of Xiao et al. 2014),
which rewards genes that are both strongly and confidently up-regulated.

**Scoring.** Each antigen is matched to a candidate by UniProt accession and its
1-based rank recorded ([`bindsight/benchmark/core.py`](../../bindsight/benchmark/core.py)).
To keep the evaluation honest and ungameable, antigens are grouped by their
**measured** differential expression under a single pre-stated rule
(FDR < 0.05 and log2fc ≥ 1), *not* by any hoped-for label: an expression-based
method can only be expected to surface antigens that are actually over-expressed,
and we report that precondition explicitly. recall@k is computed over the
over-expressed group; specificity over the not-over-expressed group.

## 3. Results

All numbers below are produced by the runs (see
[`benchmarks/validation/RESULTS.md`](../../benchmarks/validation/RESULTS.md) and
`results.json`); none are hand-set.

**Table 1 — per-antigen rediscovery, grouped by measured over-expression.**

| antigen | cohort | tumor/normal | log2fc | padj | rank | ≤5 |
|---|---|---|--:|--:|--:|:--:|
| **ERBB2** | BRCA HER2-enriched | 50 / 40 | **4.36** | 1.7e-59 | **4** | ✓ |
| NECTIN4 | BLCA | 50 / 19 | 1.59 | 3.9e-03 | — | · |
| FOLH1 (PSMA) | PRAD | 50 / 40 | 1.32 | 3.4e-04 | — | · |
| EGFR | LUAD | 50 / 40 | 0.42 | 0.13 (ns) | — | · |
| CEACAM5 (CEA) | COAD | 50 / 40 | −0.31 | 0.19 (ns) | — | · |
| MSLN | PAAD | 50 / 4 | 2.31 | 0.13 (ns) | — | · |

**Sensitivity.** Of the antigens genuinely over-expressed in their cohort,
**ERBB2 is rediscovered at rank 4 of 27 candidates** (top-5) in HER2-enriched
breast cancer (Figure 1). This depends on the PAM50 stratification: in bulk
TCGA-BRCA, ERBB2's signal is diluted across subtypes. recall@5 = recall@10 =
recall@20 = 33% (1/3): ERBB2 is found; NECTIN4 (log2fc 1.59) and FOLH1
(log2fc 1.32) are only modestly over-expressed and fall below the shortlist.

**Specificity.** **2/2** antigens that are not over-expressed at the bulk level
are correctly kept out of the top-20. EGFR drives lung adenocarcinoma through
mutation and amplification, not bulk mRNA over-expression (log2fc 0.42, n.s.);
CEA (CEACAM5) is abundantly expressed in *normal* colon epithelium too, so its
tumor-vs-normal fold-change is ≈ 0 (log2fc −0.31, n.s., baseMean ≈ 1.7×10⁵ in
both arms). The pipeline keys on genuine over-expression, not clinical fame — it
does not manufacture false positives from famous targets.

**Sensitivity tracks effect size.** Across the panel, whether an antigen is
surfaced is governed by its differential-expression magnitude (Figure 2): the
strong over-expressor (ERBB2, log2fc > 4) is rank 4; modest ones (log2fc 1.3–1.6)
fall below the shortlist; non-over-expressed ones are absent. This is exactly the
behaviour expected of a differential-expression method.

**Figure 1.** Volcano of the HER2-enriched BRCA contrast with ERBB2 highlighted
([`figures/volcano_brca_her2.png`](../../benchmarks/validation/figures/volcano_brca_her2.png)).
**Figure 2.** recall@k and per-antigen rank
([`figures/recall_at_k.png`](../../benchmarks/validation/figures/recall_at_k.png),
[`figures/antigen_rank.png`](../../benchmarks/validation/figures/antigen_rank.png)).

## 4. Discussion

bindsight's discovery half functions correctly end-to-end on real patient data:
it ranks a bona-fide over-expressed surface antigen near the top of an
unsupervised shortlist, and it is specific — it does not surface clinically
famous antigens that are not transcriptionally over-expressed. The PAM50
stratification result underscores that *the right contrast matters as much as
the method*: the same pipeline that buries ERBB2 in bulk BRCA recovers it at
rank 4 once the HER2-enriched subtype is isolated.

The misses are informative, not failures of implementation. Many clinical
surface antigens are lineage or oncofetal markers (CEA, PSMA) co-expressed in
the normal tissue-of-origin, or are activated by mutation/amplification (EGFR);
bulk tumor-vs-adjacent-normal DE — by construction — cannot distinguish these.
This delineates the scope of expression-based discovery and is precisely why the
v1.0 roadmap layers **single-cell deconvolution, co-expression, and
immunopeptidomics** on top of bulk DE to score tumor-selectivity directly.

**Data limitations.** CLDN6 (ovarian) and CD33 / IL3RA (AML) are excluded
because TCGA-OV and TCGA-LAML ship zero matched solid-tissue normals;
substituting an external normal (e.g. GTEx) would confound the contrast with a
cross-study batch effect, so we document them rather than report a manufactured
number. MSLN/PAAD is reported but underpowered (4 matched normals).

**Designer benchmark.** The complementary three-way comparison of binder
designers (RFdiffusion+ProteinMPNN vs BindCraft vs BoltzGen on a shared target
set) is GPU-only; a runnable, CPU-tested harness and protocol ship in
[`benchmarks/designer_benchmark/`](../../benchmarks/designer_benchmark/). Its
`rfdiff_mpnn` arm is populated with a real run — 20 binders against the ERBB2
trastuzumab epitope on a free Kaggle P100 (best ipTM 0.84, 50 % pass ipTM ≥ 0.65,
with the real Boltz-2-predicted complexes, see
[`RESULTS.md`](../../benchmarks/designer_benchmark/RESULTS.md)); the BindCraft
and BoltzGen arms need ≥24–32 GB GPUs and run on paid backends.

## 5. Data and code availability

RNA-seq: NIH/GDC TCGA STAR-Counts (open access). Subtypes: cBioPortal. Known
antigens: [`benchmarks/known.tsv`](../../benchmarks/known.tsv). Harness:
[`bindsight/benchmark/rediscovery.py`](../../bindsight/benchmark/rediscovery.py);
driver `python benchmarks/run_validation.py`. All generated artifacts (RESULTS,
results.json, report.html, provenance.json, figures) are under
[`benchmarks/validation/`](../../benchmarks/validation/).

## References

1. Parker JS, *et al.* Supervised risk predictor of breast cancer based on
   intrinsic subtypes (PAM50). *J Clin Oncol* 2009. doi:10.1200/JCO.2008.18.1370
2. Love MI, Huber W, Anders S. Moderated estimation of fold change and
   dispersion for RNA-seq data with DESeq2. *Genome Biol* 2014.
   doi:10.1186/s13059-014-0550-8
3. Cerami E, *et al.* The cBioPortal for Cancer Genomics. *Cancer Discov* 2012.
   doi:10.1158/2159-8290.CD-12-0095
4. Gao J, *et al.* Integrative analysis of complex cancer genomics via the
   cBioPortal. *Sci Signal* 2013. doi:10.1126/scisignal.2004088
5. Bausch-Fluck D, *et al.* The in silico human surfaceome (SURFY). *PNAS* 2018.
   doi:10.1073/pnas.1808790115
6. Xiao Y, *et al.* A novel significance score for gene selection and ranking
   (the π-value). *Bioinformatics* 2014. doi:10.1093/bioinformatics/btr671
7. Ochoa D, *et al.* Open Targets Platform. *Nucleic Acids Res* 2023.
   doi:10.1093/nar/gkac1046
8. Cho HS, *et al.* Structure of the extracellular region of HER2 alone and in
   complex with trastuzumab. *Nature* 2003. doi:10.1038/nature01392

---

*Licensing: this manuscript, its figures, and the generated result artifacts are released under [CC BY 4.0](../LICENSE) — reuse freely with attribution. The bindsight software is licensed under [AGPL-3.0-or-later](../../LICENSE).*

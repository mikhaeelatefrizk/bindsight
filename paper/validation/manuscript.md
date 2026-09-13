# Rediscovery study of *bindsight*: expression-based discovery of cell-surface antigens across fifteen TCGA cohorts

**Mikhaeel Atef Rizk Wahba**
Corresponding author: mikhaeelatefrizk@proton.me · ORCID 0009-0006-1069-9558

*Companion report to the bindsight software-methods paper. Generated artifacts
and the one-command reproduction live in
[`benchmarks/study/`](../../benchmarks/study/); the harness is
[`bindsight/benchmark/study.py`](../../bindsight/benchmark/study.py), the panel
is [`bindsight/benchmark/panel.py`](../../bindsight/benchmark/panel.py).*

> **This report supersedes an earlier six-cohort version, and reverses its
> headline.** That version reported ERBB2 rediscovered at rank 4 and recall@5 of
> 33%. Both figures are withdrawn. The breast cohort had been stratified by PAM50
> subtype, and ERBB2 is one of the fifty genes the PAM50 centroid classifier is
> built on, so the tumour arm was selected partly by high expression of the gene
> then reported as discovered. The denominator of three was also chosen after
> seeing which antigens turned out to be over-expressed. Section 5 states what
> changed and why. The numbers below are much weaker and they are the honest ones.

---

## Abstract

`bindsight` turns tumour RNA-seq into a ranked shortlist of antibody-tractable
cell-surface antigens. We test the discovery half on real TCGA patient cohorts by
asking whether it resurfaces clinically validated surface antigens without being
told where to look. Fifteen whole, unstratified TCGA projects are run as paired
tumour-versus-normal contrasts, blocking on the patient, and scored against a
pre-registered panel of 22 antigen-cohort pairs covering 13 distinct antigens.
Nothing in the cohort definition refers to the antigen under test.

Under the pre-registered primary denominator — antigens whose targeting agent is
approved — recall at rank 20 is 1 of 17 (95% CI 0.01–0.27), and 2 of 17 at rank
50. Across every regulatory tier it is 3 of 22 at rank 20. Five antigens reach
the candidate shortlist: CA9 at rank 1 of 291 in clear-cell renal carcinoma,
GPC3 at 9 of 289 in hepatocellular carcinoma, MET at 10 of 287 in papillary renal
carcinoma, FOLH1 at 34 of 285 in prostate adenocarcinoma, and STEAP1 at 158 of
285 in the same cohort.

Two findings matter more than the rate. Eleven of the seventeen approved-tier
pairs fail the significance rule outright, and a twelfth is measured as
down-regulated: their agents are licensed, so the
antigens are real, but they are not significantly over-expressed in an
unstratified bulk contrast. This is a limit of bulk differential expression as a
discovery signal, not of the ranking. Separately, CA9 measures a log2 fold change
of 9.58 — the largest effect in the panel — and was invisible to the pipeline
because its accession was absent from the surfaceome reference. That is an
instrument-coverage failure rather than a ranking failure, and extending the
reference moved it from unreachable to first place.

We report every pair, every denominator and every set size, and separate four
distinct reasons an antigen can fail to appear rather than merging them into one
rate.

## 1. Introduction

The bindsight software paper describes what the tool is and does. This companion
report supplies the empirical question that paper defers: does the discovery half
work on real patient data?

We evaluate it as a rediscovery benchmark. Run the pipeline on tumour cohorts
whose validated surface antigens are known in advance, and measure where those
antigens land in the candidate ranking. The design question that determines
whether such a benchmark means anything is what defines the cohort. If cohort
membership depends, however indirectly, on expression of the antigen being
sought, the benchmark measures its own construction.

## 2. Methods

### 2.1 Cohort definition, and what may not define it

Every cohort is a **whole, unstratified TCGA project**: all primary tumour
samples against all solid-tissue normals, with no subtype, receptor-status or
histology selection.

Stratification is governed by one rule, stated in advance and applied identically
to every cohort. A stratifying variable is admissible only if **both** hold:

1. it is computable without the run's own counts matrix, and
2. it is not a measurement of the antigen under test on any analyte.

These are different properties and conflating them is what produced the earlier
error. PAM50 and every other mRNA-cluster subtype fails the first. Clinical HER2
immunohistochemistry passes the first — it is a protein assay, so it is not
circular — but fails the second, because it still selects for the antigen being
sought. An arm stratified on HER2 status may therefore appear only as a labelled
sensitivity analysis answering "can the pipeline find HER2 in a HER2-enriched
population", and may never contribute a recall number. No such arm is reported
here.

### 2.2 Paired design

Cohorts are assembled from patients contributing **both** a primary tumour and a
solid-tissue normal, and the contrast blocks on the patient
(`~ case_barcode + condition`). In most TCGA projects nearly every normal has a
matching tumour — 113 of 113 in breast, 72 of 72 in clear-cell kidney — so
pairing costs almost no data and removes between-patient variance. It is the
largest power gain available at no cost in samples.

Differential expression uses PyDESeq2 with FDR < 0.05 and |log2fc| ≥ 1. A median
of 17,348 genes is tested per cohort.

### 2.3 The panel

The panel comprises 22 antigen-cohort pairs across 15 TCGA projects and 13
distinct antigens
([`bindsight/benchmark/panel.py`](../../bindsight/benchmark/panel.py)). ERBB2
appears in four indications and EGFR in four, which permits within-antigen
comparison across cancers rather than a single-antigen demonstration. Two
projects with ample normals but no validated surface antigen, thyroid and
chromophobe kidney, are run for null calibration and shortlist audit.

Every solid-tissue-normal count was verified against the GDC files API, and every
Ensembl gene identifier was resolved from the UniProt cross-reference for its
accession rather than recalled.

Each pair carries the regulatory standing of its targeting agent: approved, late
clinical, or clinical stage. The primary denominator is pre-registered on
approved agents alone; wider tiers are reported as labelled sensitivity analyses.
Three pairs are pre-registered as expected nulls because the antigen is abundant
in the matched normal tissue: FOLH1 in prostate, CEACAM5 in colon and CLDN18 in
stomach. Recording that expectation in advance is what prevents a miss being
explained away afterwards.

Pairs excluded from every denominator, and published for transparency: MSLN in
pancreatic adenocarcinoma, which has only four solid-tissue normals; and FOLR1,
CLDN6, CD33 and IL3RA, whose indications have none.

### 2.4 Scoring: four outcomes, never merged

An antigen can fail to appear for four distinct reasons, and reporting them as
one rate tells a reader nothing about which part of the system to fix.

- **Not reachable.** Decidable before the run from static references: the
  accession is absent from the surfaceome list, or no accession resolves. This is
  an instrument-coverage failure and is excluded from every rate.
- **Gated out.** Measured, then excluded by a named filter. Every gate is named,
  including the enrichment cut.
- **Ranked.** Entered the candidate shortlist. The rank is reported with the size
  of that shortlist, because one without the other is not interpretable.
- **Infrastructure.** A lookup errored or never ran. This is not a scientific
  negative; any pair here invalidates itself and must be re-run. The count is
  zero in what follows.

Reachability is computed from the surfaceome reference **before** any pipeline
output is consulted, because the pipeline's own disposition cascade cannot
express it reliably: a surfaceome-absent antigen that also misses the enrichment
cut is recorded there as excluded by the cut.

### 2.5 Counterfactual rank

For every pair, we report where the antigen **would** have ranked with all gates
removed: its position by the combined score among the eligible surfaceome, a
median of 2,174 tested genes per cohort. A low counterfactual rank beside no
shortlist rank means a gate excluded an antigen the ranking would have placed
well; a high one means the ranking itself placed it low. Ranking is over the
whole eligible set with no sign restriction, so the value stays defined for the
lineage antigens it exists to adjudicate.

### 2.6 Denominators and intervals

Three nested denominators are pre-registered, each with its own numerator and
interval, and never merged: all scored pairs; pairs the instrument could reach;
and pairs that entered the shortlist, which alone measures the ranking.

Recall is reported at five cutoffs rather than one, alongside the median
shortlist size. An absolute cutoff is only comparable between shortlists of
similar size, and the shortlist here is roughly 295 candidates.

Intervals are Wilson score with Clopper-Pearson as a conservative cross-check.
Because one antigen appears in several cohorts, the primary interval is computed
over a de-duplicated panel of one cohort per antigen, chosen by sample count and
never by outcome; a cluster bootstrap over antigens is reported alongside.

## 3. Results

### 3.1 Headline

Approved-tier agents, the pre-registered primary denominator:

| Cutoff | Surfaced | 95% CI |
|---|--:|---|
| recall@5 | 0/17 | 0.000–0.184 |
| recall@10 | 1/17 | 0.010–0.270 |
| recall@20 | 1/17 | 0.010–0.270 |
| recall@50 | 2/17 | 0.033–0.343 |

Across every regulatory tier, as a labelled sensitivity analysis: 1/22 at rank 5,
3/22 at rank 10 and 20, and 4/22 at rank 50. Over the de-duplicated panel of
eight independent approved-tier antigens, recall at rank 20 is 0/8 (95% CI
0.000–0.324).

The interval, not the point estimate, is the finding at this panel size.

### 3.2 Antigens that surfaced

| Antigen | Cohort | Tier | Rank | Eligible surfaceome | log2FC |
|---|---|---|--:|--:|--:|
| CA9 | Clear-cell renal | Clinical stage | 1 of 291 | 1 of 3,727 | 9.58 |
| GPC3 | Hepatocellular | Clinical stage | 9 of 289 | 9 of 3,510 | 3.97 |
| MET | Papillary renal | Approved | 10 of 287 | 10 of 3,674 | 2.34 |
| FOLH1 | Prostate | Approved | 34 of 285 | 36 of 3,710 | 2.21 |
| STEAP1 | Prostate | Late clinical | 158 of 285 | 244 of 3,710 | 1.14 |

All five come from whole unstratified cohorts with no selection on the antigen.
Two of them — MET and FOLH1 — are in the pre-registered approved-tier
denominator; the table spans every tier, as the labelled sensitivity analysis in
section 2 does.
The three strongest are oncofetal or driver antigens with large effects, which is
what a differential-expression method should find.

### 3.3 Why the others did not surface

Of the 15 gated-out approved-tier pairs: 11 failed the significance rule, 3 fell
outside the enrichment cut, and one was measured as down-regulated. Across all
three tiers the 17 gated-out pairs break down as 13, 3 and 1. No pair was lost to
infrastructure.

Four cases are individually informative:

- **ERBB2 in whole breast** measures log2fc 0.92 at an adjusted p of 5.6 × 10⁻¹¹.
  The evidence is overwhelming and the fold change falls 0.08 below the floor.
  HER2-positive disease is a minority of the cohort, so averaging dilutes it.
  This is precisely the dilution the earlier study removed by stratifying, and
  removing it was what made that result circular.
- **NECTIN4 in bladder** measures log2fc 1.52 at an adjusted p of 0.0526, missing
  the threshold by 0.0026 with only 19 matched pairs available.
- **FOLR1 in endometrial** is significant at log2fc 1.51 and still excluded,
  ranking 379th of 2,140 when the enrichment cut takes 300.
- **CA9 in clear-cell renal** was, under the original surfaceome reference,
  unreachable at any expression level. See §3.4.

### 3.4 Two defects the study found in the pipeline

**The enrichment cut preceded the surfaceome filter.** Discovery took the top 300
significant genes by combined score and only then filtered to surface proteins,
so surface antigens competed against the entire genome for those slots. In
bladder cancer 4,418 genes were significant, 300 reached enrichment, and 24 were
surface proteins. The ordering was forced rather than careless: the filter needs
UniProt accessions, which only existed after enrichment. Vendoring an
Ensembl-to-accession map removed that dependency. Filtering first costs nothing —
the number of enrichment calls is unchanged — and raised the shortlist from
roughly 40 candidates to roughly 295.

**The surfaceome reference was incomplete.** CA9 and STEAP1 are absent from the
SURFY list, verified against both the vendored file and the upstream one. Neither
could be surfaced at any expression level, and CA9 carries the largest effect in
the panel. Extending the reference with UniProt's curated cell-membrane
annotations added 1,915 accessions, taking it from 2,886 to 4,801, and moved CA9
from unreachable to rank 1 and STEAP1 to rank 158. The extension is additive and
every entry records its source, so a SURFY-only run reproduces exactly.

Both were found because the four-outcome scheme separates an antigen the
instrument cannot see from one the ranking placed low. A single recall number
would have shown neither.

## 4. Discussion

**Most clinically validated surface antigens are not significantly
over-expressed in unstratified bulk tumour-versus-normal contrasts.** Eleven of
seventeen approved-tier pairs fail the significance rule, and a twelfth is
measured as down-regulated. Their agents are
licensed, so the antigens are real and the targeting works; the signal simply is
not present in this measurement. Mechanisms differ. ERBB2 in breast and lung is
diluted by intra-cohort heterogeneity. FOLH1, CEACAM5 and CLDN18 are abundant in
the matched normal tissue, so tumour-versus-normal fold change is small by
construction. EGFR in lung adenocarcinoma is driven by mutation and
amplification rather than transcript abundance.

This is a statement about the scope of bulk differential expression as a
discovery signal, not about the ranker. It is also the honest version of what
the earlier stratified analysis concealed: subtype selection removed the
dilution, and did so by using the answer.

**What the method does find** is antigens with large, tumour-restricted effects:
CA9, GPC3 and MET, all in the top ten of their shortlists. That is a real and
useful capability, narrower than the earlier report implied.

**Limitations.** The panel is small, and every interval is correspondingly wide;
at eight independent approved-tier antigens the primary interval spans zero to
0.32. The fold-change floor of 1.0 is a shipped default rather than a tuned
parameter, and it excludes ERBB2 in breast at an adjusted p of 5.6 × 10⁻¹¹; we
report this rather than lower the floor, because changing a threshold after
seeing which antigens it excludes is the practice that made the earlier study
untrustworthy. mRNA abundance is not surface-protein abundance. Bulk expression
cannot distinguish tumour-cell-intrinsic signal from infiltrating stroma.
Antigens whose indication has no TCGA solid-tissue normal cannot be tested at all
without a cross-study batch confound.

**Planned work.** Extending discovery beyond bulk differential expression —
single-cell input, co-expression and immunopeptidomics — addresses the dominant
failure mode identified here directly.

## 5. What changed from the previous version

| | Previous | This report |
|---|---|---|
| Cohorts | 6, breast stratified by PAM50 | 15, all unstratified |
| Contrast | Unpaired | Paired on patient |
| Panel | 9 antigens, 6 evaluated | 13 antigens, 22 pairs |
| Denominator | Chosen after seeing the data | Pre-registered, three nested |
| Headline | ERBB2 rank 4; recall@5 33% | 1/17 at rank 20 (CI 0.01–0.27) |
| Failure reporting | One rate | Four separated outcomes |
| Interval | None | Wilson, Clopper-Pearson, cluster bootstrap |
| Shortlist size | Not reported | Reported beside every rank |

The previous headline is withdrawn. It arose from two errors that compound: a
cohort defined by a classifier keyed on the antigen sought, and a denominator
restricted, after the fact, to the antigens that turned out to be over-expressed.

## 6. Data and code availability

All artifacts are committed. `benchmarks/study/results.json` carries every pair,
denominator, interval and set size; `benchmarks/study/RESULTS.md` is generated
from it and never hand-edited. Per-cohort GDC file UUIDs, case barcodes and
SHA-256 checksums are written into each run directory.

Reproduce with:

```bash
pip install -e ".[discover,report]"
python benchmarks/run_study.py --list
python benchmarks/run_study.py --all --cpus 2
```

`--score-only` re-derives every number above from the run directories already on
disk without repeating any differential expression, so the scoring rules can be
changed and re-argued at no compute cost.

## References

1. Bausch-Fluck D. *et al.* The in silico human surfaceome. *PNAS* 115:E10988 (2018).
2. Muzellec B. *et al.* PyDESeq2: a python package for bulk RNA-seq differential expression analysis. *Bioinformatics* 39:btad547 (2023).
3. Love M.I., Huber W., Anders S. Moderated estimation of fold change and dispersion for RNA-seq data with DESeq2. *Genome Biology* 15:550 (2014).
4. Xiao Y. *et al.* A novel significance score for gene selection and ranking. *Bioinformatics* 30:801 (2014).
5. Wilson E.B. Probable inference, the law of succession, and statistical inference. *JASA* 22:209 (1927).
6. Clopper C.J., Pearson E.S. The use of confidence or fiducial limits illustrated in the case of the binomial. *Biometrika* 26:404 (1934).
7. Benjamini Y., Hochberg Y. Controlling the false discovery rate. *JRSS B* 57:289 (1995).
8. Parker J.S. *et al.* Supervised risk predictor of breast cancer based on intrinsic subtypes. *J Clin Oncol* 27:1160 (2009).
9. The UniProt Consortium. UniProt: the Universal Protein Knowledgebase in 2025. *Nucleic Acids Research* 53:D609 (2025).

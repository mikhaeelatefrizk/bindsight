# bindsight rediscovery study — results

Does bindsight's expression-based discovery resurface clinically validated cell-surface antigens from real TCGA RNA-seq?

## How this study is built

- **Cohorts:** whole unstratified TCGA project, all primary tumour vs all normal.
- **Contrast:** `~ case_barcode + condition (paired on patient)`.
- **Denominators are pre-registered**, not chosen after seeing the data.
- **Every rate carries an interval.** At these panel sizes the interval, not the point estimate, is the finding.

### Why cohorts are not stratified

A stratifying variable is admissible only if BOTH hold: (a) it is computable without the run's own counts matrix, and (b) it is not a measurement of the antigen under test on any analyte. PAM50 and every other mRNA-cluster subtype fails (a). Clinical HER2 IHC/FISH passes (a) but fails (b), so it may appear only as a labelled sensitivity analysis and never in a recall denominator. Receptor status for a different receptor, histology and stage pass both.

### Antigens the instrument cannot reach

CA9 (Q16790) and STEAP1 (Q9UHE8) are absent from the SURFY surfaceome list — verified against both the vendored file and the upstream one, so a genuine reference gap rather than a build error. Under SURFY alone neither could enter the candidate table at any expression level, and CA9 measures a log2 fold change of 9.58 in clear-cell kidney, the largest effect anywhere in this panel. That is an instrument-coverage failure, not a ranking failure, and the fix was a better instrument: the extended reference adds UniProt's curated cell-membrane annotations, 1,915 further accessions, and makes both reachable. Runs with `use_extended_surfaceome=False` reproduce the SURFY-only behaviour, under which these two are still reported as unreachable rather than as misses.

## Headline

Three nested denominators. Each is a different question, and merging them would answer none of them.

| Denominator | What it asks | Recall@20 |
|---|---|---|
| `all (approved)` | Of every scored **approved**-tier pair, how many were surfaced? | 1/17 = 0.059 (95% CI 0.010–0.270) |
| `reachable` | Of those the instrument could see at all? | 1/17 = 0.059 (95% CI 0.010–0.270) |
| `gate_passed` | Of those that reached the shortlist? This alone measures the ranking. | 1/2 = 0.500 (95% CI 0.095–0.905) |

### Recall across cutoffs

An absolute cutoff is only comparable between cohorts whose shortlists are of similar size, so the median shortlist is printed beside each row.

| Denominator | Median shortlist | @5 | @10 | @20 | @50 | @100 |
|---|--:|--:|--:|--:|--:|--:|
| `all (approved)` | 295 | 0/17 | 1/17 | 1/17 | 2/17 | 2/17 |
| `reachable` | 295 | 0/17 | 1/17 | 1/17 | 2/17 | 2/17 |
| `gate_passed` | 286 | 0/2 | 1/2 | 1/2 | 2/2 | 2/2 |

### Sensitivity to the regulatory tier

Every scored pair regardless of regulatory tier, reported as a sensitivity analysis. The primary denominator remains ['approved'].

| Cutoff | Every scored pair |
|---|--:|
| recall@5 | 1/22 |
| recall@10 | 3/22 |
| recall@20 | 3/22 |
| recall@50 | 4/22 |
| recall@100 | 4/22 |

### Interval over independent antigens

One cohort per antigen, so the trials are independent. This is the interval to quote; the cascade above is computed over correlated pairs.

- Wilson: 0/8 = 0.000 (95% CI 0.000–0.324)
- Clopper-Pearson: 0/8 = 0.000 (95% CI 0.000–0.369)
- Distinct antigens: 8

- Cluster bootstrap over antigens: 1/17 = 0.059 (95% CI 0.000–0.200)
  `cluster-bootstrap(n_clusters=8, B=10000)`

### Invalid pairs

**0**. A lookup that errored or never ran is not a negative result. This count must be zero in anything published; any pair here invalidates itself and must be re-run.

## Null models

### Decoy null — the primary one

Each antigen is compared against the genes matched to it on abundance and dispersion quintile, drawn from the same eligible surfaceome and ranked by the same counterfactual score. The question it answers: would a gene that merely *looks* like this antigen have ranked as well?

Taken over the **counterfactual** rank rather than the shortlist rank, so no gate has to be matched and the tail is computed exactly rather than sampled — 22 of 22 pairs used their whole stratum.

**`floor` is the smallest p the stratum could have produced.** A p equal to its floor means no decoy beat the antigen and the stratum had no finer resolution to offer; it is not the same statement as a p of that size drawn from a large pool.

| antigen | cohort | counterfactual rank | p | BH | floor | decoys |
|---|---|--:|--:|--:|--:|--:|
| **MET** | KIRP | 10 | 0.0047 | 0.102 | 0.0047 | 214 |
| **CA9** | KIRC | 1 | 0.0185 | 0.204 | 0.0185 | 53 |
| **GPC3** | LIHC | 9 | 0.0417 | 0.306 | 0.0417 | 23 |
| **FOLH1** | PRAD | 36 | 0.0645 | 0.355 | 0.0323 | 30 |
| **ERBB2** | BRCA | 476 | 0.1212 | 0.432 | 0.0101 | 98 |
| **MET** | LUAD | 713 | 0.1525 | 0.432 | 0.0169 | 58 |
| **ERBB2** | LUAD | 841 | 0.1702 | 0.432 | 0.0043 | 234 |
| **TACSTD2** | LUAD | 1286 | 0.2182 | 0.432 | 0.0091 | 109 |
| **EGFR** | LUSC | 648 | 0.2200 | 0.432 | 0.0200 | 49 |
| **EGFR** | HNSC | 413 | 0.2275 | 0.432 | 0.0047 | 210 |
| **EGFR** | LUAD | 1443 | 0.2364 | 0.432 | 0.0091 | 109 |
| **ERBB2** | UCEC | 937 | 0.2423 | 0.432 | 0.0052 | 193 |
| **STEAP1** | PRAD | 244 | 0.2553 | 0.432 | 0.0213 | 46 |
| **ERBB2** | STAD | 997 | 0.3182 | 0.500 | 0.0091 | 109 |
| **NECTIN4** | BLCA | 438 | 0.3699 | 0.542 | 0.0137 | 72 |
| **CEACAM5** | COAD | 1753 | 0.4000 | 0.550 | 0.0250 | 39 |
| **TACSTD2** | BRCA | 1375 | 0.5000 | 0.647 | 0.0172 | 57 |
| **CLDN18** | STAD | 1835 | 0.6000 | 0.733 | 0.0133 | 74 |
| **FGFR2** | STAD | 2333 | 0.6545 | 0.748 | 0.0091 | 109 |
| **CLDN18** | ESCA | 2265 | 0.6923 | 0.748 | 0.0192 | 51 |
| **FOLR1** | UCEC | 669 | 0.7143 | 0.748 | 0.0476 | 20 |
| **EGFR** | COAD | 2715 | 0.8170 | 0.817 | 0.0043 | 234 |

**3 of 22 pairs are nominally significant at 0.05 (CA9, GPC3, MET), and 0 survive Benjamini-Hochberg across the panel.**

That is the finding, and it is a negative one: against background matched on abundance and dispersion, no antigen in this panel is distinguishable once the panel is corrected for its own size. Reporting the three nominal hits without the correction would be the error this column exists to prevent.

### Indication-specificity null

Antigens ranked in their own indication versus a permuted assignment. The statistic is the mean standing of each antigen in its cohort, where 1.0 is the top of the eligible surfaceome and 0.0 the bottom. Restricted to antigens with a single indication in the panel, because the test assigns one cohort per antigen.

- Observed mean standing: **0.858** (1.0 is the top of the eligible surfaceome, 0.0 the bottom)
- p = **3.97e-04** over 5040 enumerated permutations
- Computed over 7 antigens and 15 cohorts: CA9, FGFR2, FOLH1, FOLR1, GPC3, NECTIN4, STEAP1

Excluded, several indications each: CLDN18, EGFR, ERBB2, MET, TACSTD2. The test assigns one cohort per antigen, so an antigen with four indications has no single 'own' cohort to hold fixed.

**Calibration.** KICH, THCA carry no panel antigen and were run to show what no signal looks like on this scale. Panel antigens land at a mean standing of **0.418** there — the middle of the eligible surfaceome — against **0.738** in their own indication. Neither cohort contributes a scored pair (0), because inventing an expectation for a cohort chosen for having none is the error they exist to avoid.

Excluded, not scored in every cohort: CEACAM5. A complete matrix is required, or the observed statistic and the permuted one would be built from different sets of cohorts.

## Results by outcome class

### Reached the shortlist (5)

These entered the candidate shortlist. The rank is only interpretable beside the shortlist size, so both are printed.

| Cohort | Antigen | Agent | Tier | log2FC | padj | Rank / shortlist | Counterfactual rank / eligible | Direction | Why |
|---|---|---|---|--:|--:|--:|--:|---|---|
| TCGA-KIRC | **CA9** (Q16790) | [89Zr]Zr-girentuximab (imaging, under FDA review) | clinical_stage | 9.58 | 0.000 | 1 / 291 | 1 / 3727 | up | reached the candidate shortlist at rank 1 of 291 (carried through to design) |
| TCGA-KIRP | **MET** (P08581) | telisotuzumab vedotin | approved | 2.34 | 8.39e-58 | 10 / 287 | 10 / 3674 | up | reached the candidate shortlist at rank 10 of 287 (carried through to design) |
| TCGA-LIHC | **GPC3** (P51654) | GPC3 CAR-T and bispecifics (phase 1/2) | clinical_stage | 3.97 | 8.17e-33 | 9 / 289 | 9 / 3510 | up | reached the candidate shortlist at rank 9 of 289 (carried through to design) |
| TCGA-PRAD | **FOLH1** (Q04609) | [177Lu]Lu-PSMA-617 (Pluvicto) | approved | 2.21 | 2.35e-15 | 34 / 285 | 36 / 3710 | up | reached the candidate shortlist at rank 34 of 285 (past the structure-fetch cap; no lookup was attempted) |
| TCGA-PRAD | **STEAP1** (Q9UHE8) | xaluritamig (phase 3) | late_clinical | 1.14 | 1.13e-06 | 158 / 285 | 244 / 3710 | up | reached the candidate shortlist at rank 158 of 285 (past the structure-fetch cap; no lookup was attempted) |

### Measured, then excluded by a stated filter (17)

These were measured and then excluded by a named filter. The counterfactual rank says whether the filter or the ranking was responsible: a low counterfactual rank means a gate excluded an antigen the ranking would have placed well.

| Cohort | Antigen | Agent | Tier | log2FC | padj | Rank / shortlist | Counterfactual rank / eligible | Direction | Why |
|---|---|---|---|--:|--:|--:|--:|---|---|
| TCGA-BLCA | **NECTIN4** (Q96NY8) | enfortumab vedotin (Padcev) | approved | 1.52 | 0.053 | — | 438 / 3576 | up | did not clear the significance rule, which requires BOTH an adjusted p-value below the FDR threshold AND an absolute log2 fold change at or above the floor — naming only the FDR would misattribute an antigen that is statistically solid but modestly changed, such as ERBB2 in the unstratified breast cohort at log2fc 0.92 |
| TCGA-BRCA | **ERBB2** (P04626) | trastuzumab, pertuzumab, T-DXd | approved | 0.92 | 5.64e-11 | — | 476 / 3817 | up | did not clear the significance rule, which requires BOTH an adjusted p-value below the FDR threshold AND an absolute log2 fold change at or above the floor — naming only the FDR would misattribute an antigen that is statistically solid but modestly changed, such as ERBB2 in the unstratified breast cohort at log2fc 0.92 |
| TCGA-BRCA | **TACSTD2** (P09758) | sacituzumab govitecan, datopotamab deruxtecan | approved | 0.16 | 0.363 | — | 1375 / 3817 | up | did not clear the significance rule, which requires BOTH an adjusted p-value below the FDR threshold AND an absolute log2 fold change at or above the floor — naming only the FDR would misattribute an antigen that is statistically solid but modestly changed, such as ERBB2 in the unstratified breast cohort at log2fc 0.92 |
| TCGA-COAD | **CEACAM5** (P06731) | tusamitamab ravtansine, labetuzumab govitecan (phase 2/3) | late_clinical | -0.48 | 0.045 | — | 1753 / 3582 | down | did not clear the significance rule, which requires BOTH an adjusted p-value below the FDR threshold AND an absolute log2 fold change at or above the floor — naming only the FDR would misattribute an antigen that is statistically solid but modestly changed, such as ERBB2 in the unstratified breast cohort at log2fc 0.92 |
| TCGA-COAD | **EGFR** (P00533) | cetuximab, panitumumab | approved | -1.04 | 3.46e-14 | — | 2715 / 3582 | down | measured as down-regulated in tumour |
| TCGA-ESCA | **CLDN18** (P56856) | zolbetuximab (Vyloy) | approved | -0.39 | 0.693 | — | 2265 / 3748 | down | did not clear the significance rule, which requires BOTH an adjusted p-value below the FDR threshold AND an absolute log2 fold change at or above the floor — naming only the FDR would misattribute an antigen that is statistically solid but modestly changed, such as ERBB2 in the unstratified breast cohort at log2fc 0.92 |
| TCGA-HNSC | **EGFR** (P00533) | cetuximab | approved | 1.03 | 2.88e-07 | — | 413 / 3671 | up | outside the top-K enrichment cut, so it never became a candidate at all (this is a gate, not a ranking outcome) |
| TCGA-LUAD | **EGFR** (P00533) | cetuximab, necitumumab | approved | 0.06 | 0.755 | — | 1443 / 3761 | up | did not clear the significance rule, which requires BOTH an adjusted p-value below the FDR threshold AND an absolute log2 fold change at or above the floor — naming only the FDR would misattribute an antigen that is statistically solid but modestly changed, such as ERBB2 in the unstratified breast cohort at log2fc 0.92 |
| TCGA-LUAD | **ERBB2** (P04626) | T-DXd (tumour-agnostic, HER2 IHC3+) | approved | 0.41 | 0.001 | — | 841 / 3761 | up | did not clear the significance rule, which requires BOTH an adjusted p-value below the FDR threshold AND an absolute log2 fold change at or above the floor — naming only the FDR would misattribute an antigen that is statistically solid but modestly changed, such as ERBB2 in the unstratified breast cohort at log2fc 0.92 |
| TCGA-LUAD | **MET** (P08581) | telisotuzumab vedotin | approved | 0.67 | 6.57e-04 | — | 713 / 3761 | up | did not clear the significance rule, which requires BOTH an adjusted p-value below the FDR threshold AND an absolute log2 fold change at or above the floor — naming only the FDR would misattribute an antigen that is statistically solid but modestly changed, such as ERBB2 in the unstratified breast cohort at log2fc 0.92 |
| TCGA-LUAD | **TACSTD2** (P09758) | datopotamab deruxtecan | approved | 0.15 | 0.356 | — | 1286 / 3761 | up | did not clear the significance rule, which requires BOTH an adjusted p-value below the FDR threshold AND an absolute log2 fold change at or above the floor — naming only the FDR would misattribute an antigen that is statistically solid but modestly changed, such as ERBB2 in the unstratified breast cohort at log2fc 0.92 |
| TCGA-LUSC | **EGFR** (P00533) | necitumumab | approved | 1.07 | 1.43e-06 | — | 648 / 3771 | up | outside the top-K enrichment cut, so it never became a candidate at all (this is a gate, not a ranking outcome) |
| TCGA-STAD | **CLDN18** (P56856) | zolbetuximab (Vyloy) | approved | -0.06 | 0.931 | — | 1835 / 3799 | down | did not clear the significance rule, which requires BOTH an adjusted p-value below the FDR threshold AND an absolute log2 fold change at or above the floor — naming only the FDR would misattribute an antigen that is statistically solid but modestly changed, such as ERBB2 in the unstratified breast cohort at log2fc 0.92 |
| TCGA-STAD | **ERBB2** (P04626) | trastuzumab, T-DXd | approved | 0.44 | 0.152 | — | 997 / 3799 | up | did not clear the significance rule, which requires BOTH an adjusted p-value below the FDR threshold AND an absolute log2 fold change at or above the floor — naming only the FDR would misattribute an antigen that is statistically solid but modestly changed, such as ERBB2 in the unstratified breast cohort at log2fc 0.92 |
| TCGA-STAD | **FGFR2** (P21802) | bemarituzumab (phase 3) | late_clinical | -0.33 | 0.279 | — | 2333 / 3799 | down | did not clear the significance rule, which requires BOTH an adjusted p-value below the FDR threshold AND an absolute log2 fold change at or above the floor — naming only the FDR would misattribute an antigen that is statistically solid but modestly changed, such as ERBB2 in the unstratified breast cohort at log2fc 0.92 |
| TCGA-UCEC | **ERBB2** (P04626) | T-DXd (tumour-agnostic accelerated approval) | approved | 0.48 | 0.032 | — | 937 / 3631 | up | did not clear the significance rule, which requires BOTH an adjusted p-value below the FDR threshold AND an absolute log2 fold change at or above the floor — naming only the FDR would misattribute an antigen that is statistically solid but modestly changed, such as ERBB2 in the unstratified breast cohort at log2fc 0.92 |
| TCGA-UCEC | **FOLR1** (P15328) | mirvetuximab soravtansine (Elahere) | approved | 1.51 | 0.022 | — | 669 / 3631 | up | outside the top-K enrichment cut, so it never became a candidate at all (this is a gate, not a ranking outcome) |

## Set sizes

A rank means nothing without the size of the set it was taken within, so those sizes are published rather than left to be inferred.

| Cohort | Genes tested | Significant | Eligible surfaceome | Candidate shortlist |
|---|--:|--:|--:|--:|
| TCGA-BLCA | 16875 | 4418 | 3576 | 291 |
| TCGA-BRCA | 17851 | 4369 | 3817 | 295 |
| TCGA-COAD | 16787 | 5006 | 3582 | 290 |
| TCGA-ESCA | 17592 | 3445 | 3748 | 291 |
| TCGA-HNSC | 17362 | 3959 | 3671 | 290 |
| TCGA-KICH | 16932 | 5948 | 3612 | 290 |
| TCGA-KIRC | 17348 | 5121 | 3727 | 291 |
| TCGA-KIRP | 17173 | 4586 | 3674 | 287 |
| TCGA-LIHC | 16766 | 3650 | 3510 | 289 |
| TCGA-LUAD | 17578 | 4426 | 3761 | 296 |
| TCGA-LUSC | 17741 | 6407 | 3771 | 294 |
| TCGA-PRAD | 17361 | 2381 | 3710 | 285 |
| TCGA-STAD | 17806 | 3508 | 3799 | 295 |
| TCGA-THCA | 17066 | 3151 | 3630 | 293 |
| TCGA-UCEC | 17059 | 5776 | 3631 | 297 |

## Published but excluded from every denominator

These are reported so a reader can see what was left out and why. A rate computed over them would be meaningless.

| Cohort | Antigen | Reason |
|---|---|---|
| TCGA-PAAD | **MSLN** (Q13421) | only 4 solid-tissue normals, below the floor of 10 |
| TCGA-OV | **FOLR1** (P15328) | no solid-tissue normals, so no tumour-vs-normal contrast is possible |
| TCGA-LAML | **CD33** (P20138) | no solid-tissue normals, so no tumour-vs-normal contrast is possible |
| TCGA-LAML | **IL3RA** (P26951) | no solid-tissue normals, so no tumour-vs-normal contrast is possible |
| TCGA-OV | **CLDN6** (P56747) | no solid-tissue normals, so no tumour-vs-normal contrast is possible |

## Reproduce

```bash
pip install -e ".[discover,report]"
python benchmarks/run_study.py --list
python benchmarks/run_study.py --all --cpus 2
```

`--score-only` re-derives every number above from the run directories already on disk, without re-running any differential expression.


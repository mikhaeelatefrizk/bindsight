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
| `all` | Of every scored pair, how many were surfaced? | 1/17 = 0.059 (95% CI 0.010–0.270) |
| `reachable` | Of the pairs the instrument could see at all? | 1/17 = 0.059 (95% CI 0.010–0.270) |
| `gate_passed` | Of the pairs that reached the shortlist? This alone measures the ranking. | 1/2 = 0.500 (95% CI 0.095–0.905) |

### Recall across cutoffs

An absolute cutoff is only comparable between cohorts whose shortlists are of similar size, so the median shortlist is printed beside each row.

| Denominator | Median shortlist | @5 | @10 | @20 | @50 | @100 |
|---|--:|--:|--:|--:|--:|--:|
| `all` | 295 | 0/17 | 1/17 | 1/17 | 2/17 | 2/17 |
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

## Results by outcome class

### Reached the shortlist (5)

These entered the candidate shortlist. The rank is only interpretable beside the shortlist size, so both are printed.

| Cohort | Antigen | Agent | Tier | log2FC | padj | Rank / shortlist | Counterfactual rank / eligible | Direction | Why |
|---|---|---|---|--:|--:|--:|--:|---|---|
| TCGA-KIRC | **CA9** (Q16790) | [89Zr]Zr-girentuximab (imaging, under FDA review) | clinical_stage | 9.58 | 0.000 | 1 / 291 | 1 / 2210 | up | reached the candidate shortlist at rank 1 of 291 (carried through to design) |
| TCGA-KIRP | **MET** (P08581) | telisotuzumab vedotin | approved | 2.34 | 8.39e-58 | 10 / 287 | 7 / 2170 | up | reached the candidate shortlist at rank 10 of 287 (carried through to design) |
| TCGA-LIHC | **GPC3** (P51654) | GPC3 CAR-T and bispecifics (phase 1/2) | clinical_stage | 3.97 | 8.17e-33 | 9 / 289 | 6 / 2057 | up | reached the candidate shortlist at rank 9 of 289 (carried through to design) |
| TCGA-PRAD | **FOLH1** (Q04609) | [177Lu]Lu-PSMA-617 (Pluvicto) | approved | 2.21 | 2.35e-15 | 34 / 285 | 24 / 2208 | up | reached the candidate shortlist at rank 34 of 285 (past the structure-fetch cap; no lookup was attempted) |
| TCGA-PRAD | **STEAP1** (Q9UHE8) | xaluritamig (phase 3) | late_clinical | 1.14 | 1.13e-06 | 158 / 285 | 151 / 2208 | up | reached the candidate shortlist at rank 158 of 285 (past the structure-fetch cap; no lookup was attempted) |

### Measured, then excluded by a stated filter (17)

These were measured and then excluded by a named filter. The counterfactual rank says whether the filter or the ranking was responsible: a low counterfactual rank means a gate excluded an antigen the ranking would have placed well.

| Cohort | Antigen | Agent | Tier | log2FC | padj | Rank / shortlist | Counterfactual rank / eligible | Direction | Why |
|---|---|---|---|--:|--:|--:|--:|---|---|
| TCGA-BLCA | **NECTIN4** (Q96NY8) | enfortumab vedotin (Padcev) | approved | 1.52 | 0.053 | — | 259 / 2104 | up | did not clear the significance rule, which requires BOTH an adjusted p-value below the FDR threshold AND an absolute log2 fold change at or above the floor — naming only the FDR would misattribute an antigen that is statistically solid but modestly changed, such as ERBB2 in the unstratified breast cohort at log2fc 0.92 |
| TCGA-BRCA | **ERBB2** (P04626) | trastuzumab, pertuzumab, T-DXd | approved | 0.92 | 5.64e-11 | — | 263 / 2284 | up | did not clear the significance rule, which requires BOTH an adjusted p-value below the FDR threshold AND an absolute log2 fold change at or above the floor — naming only the FDR would misattribute an antigen that is statistically solid but modestly changed, such as ERBB2 in the unstratified breast cohort at log2fc 0.92 |
| TCGA-BRCA | **TACSTD2** (P09758) | sacituzumab govitecan, datopotamab deruxtecan | approved | 0.16 | 0.363 | — | 754 / 2284 | up | did not clear the significance rule, which requires BOTH an adjusted p-value below the FDR threshold AND an absolute log2 fold change at or above the floor — naming only the FDR would misattribute an antigen that is statistically solid but modestly changed, such as ERBB2 in the unstratified breast cohort at log2fc 0.92 |
| TCGA-COAD | **CEACAM5** (P06731) | tusamitamab ravtansine, labetuzumab govitecan (phase 2/3) | late_clinical | -0.48 | 0.045 | — | 972 / 2098 | down | did not clear the significance rule, which requires BOTH an adjusted p-value below the FDR threshold AND an absolute log2 fold change at or above the floor — naming only the FDR would misattribute an antigen that is statistically solid but modestly changed, such as ERBB2 in the unstratified breast cohort at log2fc 0.92 |
| TCGA-COAD | **EGFR** (P00533) | cetuximab, panitumumab | approved | -1.04 | 3.46e-14 | — | 1547 / 2098 | down | measured as down-regulated in tumour |
| TCGA-ESCA | **CLDN18** (P56856) | zolbetuximab (Vyloy) | approved | -0.39 | 0.693 | — | 1362 / 2229 | down | did not clear the significance rule, which requires BOTH an adjusted p-value below the FDR threshold AND an absolute log2 fold change at or above the floor — naming only the FDR would misattribute an antigen that is statistically solid but modestly changed, such as ERBB2 in the unstratified breast cohort at log2fc 0.92 |
| TCGA-HNSC | **EGFR** (P00533) | cetuximab | approved | 1.03 | 2.88e-07 | — | 278 / 2174 | up | outside the top-K enrichment cut, so it never became a candidate at all (this is a gate, not a ranking outcome) |
| TCGA-LUAD | **EGFR** (P00533) | cetuximab, necitumumab | approved | 0.06 | 0.755 | — | 844 / 2241 | up | did not clear the significance rule, which requires BOTH an adjusted p-value below the FDR threshold AND an absolute log2 fold change at or above the floor — naming only the FDR would misattribute an antigen that is statistically solid but modestly changed, such as ERBB2 in the unstratified breast cohort at log2fc 0.92 |
| TCGA-LUAD | **ERBB2** (P04626) | T-DXd (tumour-agnostic, HER2 IHC3+) | approved | 0.41 | 0.001 | — | 508 / 2241 | up | did not clear the significance rule, which requires BOTH an adjusted p-value below the FDR threshold AND an absolute log2 fold change at or above the floor — naming only the FDR would misattribute an antigen that is statistically solid but modestly changed, such as ERBB2 in the unstratified breast cohort at log2fc 0.92 |
| TCGA-LUAD | **MET** (P08581) | telisotuzumab vedotin | approved | 0.67 | 6.57e-04 | — | 429 / 2241 | up | did not clear the significance rule, which requires BOTH an adjusted p-value below the FDR threshold AND an absolute log2 fold change at or above the floor — naming only the FDR would misattribute an antigen that is statistically solid but modestly changed, such as ERBB2 in the unstratified breast cohort at log2fc 0.92 |
| TCGA-LUAD | **TACSTD2** (P09758) | datopotamab deruxtecan | approved | 0.15 | 0.356 | — | 757 / 2241 | up | did not clear the significance rule, which requires BOTH an adjusted p-value below the FDR threshold AND an absolute log2 fold change at or above the floor — naming only the FDR would misattribute an antigen that is statistically solid but modestly changed, such as ERBB2 in the unstratified breast cohort at log2fc 0.92 |
| TCGA-LUSC | **EGFR** (P00533) | necitumumab | approved | 1.07 | 1.43e-06 | — | 385 / 2250 | up | outside the top-K enrichment cut, so it never became a candidate at all (this is a gate, not a ranking outcome) |
| TCGA-STAD | **CLDN18** (P56856) | zolbetuximab (Vyloy) | approved | -0.06 | 0.931 | — | 1109 / 2273 | down | did not clear the significance rule, which requires BOTH an adjusted p-value below the FDR threshold AND an absolute log2 fold change at or above the floor — naming only the FDR would misattribute an antigen that is statistically solid but modestly changed, such as ERBB2 in the unstratified breast cohort at log2fc 0.92 |
| TCGA-STAD | **ERBB2** (P04626) | trastuzumab, T-DXd | approved | 0.44 | 0.152 | — | 633 / 2273 | up | did not clear the significance rule, which requires BOTH an adjusted p-value below the FDR threshold AND an absolute log2 fold change at or above the floor — naming only the FDR would misattribute an antigen that is statistically solid but modestly changed, such as ERBB2 in the unstratified breast cohort at log2fc 0.92 |
| TCGA-STAD | **FGFR2** (P21802) | bemarituzumab (phase 3) | late_clinical | -0.33 | 0.279 | — | 1367 / 2273 | down | did not clear the significance rule, which requires BOTH an adjusted p-value below the FDR threshold AND an absolute log2 fold change at or above the floor — naming only the FDR would misattribute an antigen that is statistically solid but modestly changed, such as ERBB2 in the unstratified breast cohort at log2fc 0.92 |
| TCGA-UCEC | **ERBB2** (P04626) | T-DXd (tumour-agnostic accelerated approval) | approved | 0.48 | 0.032 | — | 545 / 2140 | up | did not clear the significance rule, which requires BOTH an adjusted p-value below the FDR threshold AND an absolute log2 fold change at or above the floor — naming only the FDR would misattribute an antigen that is statistically solid but modestly changed, such as ERBB2 in the unstratified breast cohort at log2fc 0.92 |
| TCGA-UCEC | **FOLR1** (P15328) | mirvetuximab soravtansine (Elahere) | approved | 1.51 | 0.022 | — | 379 / 2140 | up | outside the top-K enrichment cut, so it never became a candidate at all (this is a gate, not a ranking outcome) |

## Set sizes

A rank means nothing without the size of the set it was taken within, so those sizes are published rather than left to be inferred.

| Cohort | Genes tested | Significant | Eligible surfaceome | Candidate shortlist |
|---|--:|--:|--:|--:|
| TCGA-BLCA | 16875 | 4418 | 2104 | 291 |
| TCGA-BRCA | 17851 | 4369 | 2284 | 295 |
| TCGA-COAD | 16787 | 5006 | 2098 | 290 |
| TCGA-ESCA | 17592 | 3445 | 2229 | 291 |
| TCGA-HNSC | 17362 | 3959 | 2174 | 290 |
| TCGA-KICH | 16932 | 5948 | 2119 | 290 |
| TCGA-KIRC | 17348 | 5121 | 2210 | 291 |
| TCGA-KIRP | 17173 | 4586 | 2170 | 287 |
| TCGA-LIHC | 16766 | 3650 | 2057 | 289 |
| TCGA-LUAD | 17578 | 4426 | 2241 | 296 |
| TCGA-LUSC | 17741 | 6407 | 2250 | 294 |
| TCGA-PRAD | 17361 | 2381 | 2208 | 285 |
| TCGA-STAD | 17806 | 3508 | 2273 | 295 |
| TCGA-THCA | 17066 | 3151 | 2140 | 293 |
| TCGA-UCEC | 17059 | 5776 | 2140 | 297 |

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


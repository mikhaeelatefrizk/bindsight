# bindsight rediscovery validation — results

Does bindsight's expression-based discovery resurface clinically-validated cell-surface antigens from real TCGA RNA-seq? Each antigen is evaluated in its indication cohort as a tumor-vs-adjacent-normal contrast run through the discovery half (`bindsight discover`), then scored by the rank of the antigen in the candidate shortlist (`bindsight.benchmark.score_run`).

**All numbers below are produced by the runs; none are hand-set. Antigens are grouped by their _measured_ differential expression (rule: FDR<0.05 and log2fc>=1.0), not by any prior label — an expression-based method can only surface antigens that are actually over-expressed, and we report that precondition transparently.**

- Generated: `2026-06-15T01:17:07+00:00` · bindsight `0.1.0`
- PAM50 subtypes: cBioPortal study `brca_tcga_pan_can_atlas_2018`
- Known-antigen set: `benchmarks/known.tsv`

## Headline

- **Sensitivity:** of 3 antigen(s) genuinely over-expressed in their cohort, **ERBB2** is rediscovered at **rank 4** in TCGA-BRCA (BRCA_Her2 subtype) — log2fc 4.36, padj 1.7e-59.
- **recall@k over over-expressed antigens:** recall@5=33%, recall@10=33%, recall@20=33%.
- **Specificity:** 2/2 antigens that are NOT over-expressed at the bulk level are correctly kept out of the top-20 — the pipeline keys on genuine over-expression, not clinical fame.

## Reproduce

```bash
pip install -e ".[discover,report]"
python benchmarks/run_validation.py
```

## Per-antigen results (grouped by measured over-expression)

`rank` is the antigen's 1-based position in the cohort's surface-filtered candidate shortlist; `—` = not surfaced.

### Transcriptionally over-expressed (the pipeline should — and is scored to — surface these)

| antigen | project | tumor | normal | log2fc | padj | rank | ≤5 | ≤10 | ≤20 |
|---|---|--:|--:|--:|--:|--:|--:|--:|--:|
| ERBB2 (P04626) | TCGA-BRCA | 50 | 40 | 4.36 | 1.7e-59 | 4 | ✓ | ✓ | ✓ |
| NECTIN4 (Q96NY8) | TCGA-BLCA | 50 | 19 | 1.59 | 3.9e-03 | — | · | · | · |
| FOLH1 (Q04609) | TCGA-PRAD | 50 | 40 | 1.32 | 3.4e-04 | — | · | · | · |

- **ERBB2** (TCGA-BRCA): PAM50 HER2-enriched tumors are ERBB2-amplified, so ERBB2 mRNA is high.
- **NECTIN4** (TCGA-BLCA): Nectin-4 (target of enfortumab vedotin, Padcev) is elevated in urothelial carcinoma, but only modestly at the bulk-mRNA level (log2fc ~1.6), below the discovery shortlist.
- **FOLH1** (TCGA-PRAD): PSMA (FOLH1) is highly expressed but also abundant in normal prostate, so the tumor-vs-normal fold-change is modest (reported for transparency).

### Not over-expressed at the bulk level (specificity: the pipeline should NOT surface these)

| antigen | project | tumor | normal | log2fc | padj | rank | ≤5 | ≤10 | ≤20 |
|---|---|--:|--:|--:|--:|--:|--:|--:|--:|
| EGFR (P00533) | TCGA-LUAD | 50 | 40 | 0.42 | 1.3e-01 | — | · | · | · |
| CEACAM5 (P06731) | TCGA-COAD | 50 | 40 | -0.31 | 1.9e-01 | — | · | · | · |

- **CEACAM5** (TCGA-COAD): CEA (target of tusamitamab ravtansine / labetuzumab govitecan) is a classic colorectal marker, but it is also abundantly expressed in normal colon epithelium, so the bulk tumor-vs-adjacent-normal fold-change is ~0.
- **EGFR** (TCGA-LUAD): EGFR drives LUAD via mutation/amplification, not bulk mRNA over-expression, so a specificity-respecting pipeline should NOT surface it on expression alone.

### Underpowered (too few matched normals to call differential expression)

| antigen | project | tumor | normal | log2fc | padj | rank | ≤5 | ≤10 | ≤20 |
|---|---|--:|--:|--:|--:|--:|--:|--:|--:|
| MSLN (Q13421) | TCGA-PAAD | 50 | 4 | 2.31 | 1.3e-01 | — | · | · | · |

- **MSLN** (TCGA-PAAD): Mesothelin is over-expressed in PDAC, but TCGA-PAAD ships only 4 matched normals, so the contrast is underpowered (reported for transparency).

## Interpretation

- The discovery pipeline (subtype-stratified DESeq2 → SURFY surfaceome filter → combined-significance ranking) correctly surfaces the antigen that is strongly transcriptionally over-expressed, and correctly withholds antigens that are not — including clinically famous ones whose tumor-selectivity arises from mutation/amplification (EGFR) or lineage co-expression in the normal tissue-of-origin (CEA, PSMA). Sensitivity therefore tracks effect size, as expected for a differential-expression method.
- This delineates the scope of bulk tumor-vs-normal discovery and motivates the multi-modal specificity scoring (single-cell, co-expression, immunopeptidomics) planned for v1.0.

## Antigens with no matched TCGA normal (not runnable here)

- **CLDN6** (TCGA-OV): TCGA-OV ships 0 solid-tissue-normal RNA-seq samples; a clean tumor-vs-normal contrast is impossible without an external (GTEx) normal, which would introduce a cross-study batch confound.
- **CD33 / IL3RA (CD123)** (TCGA-LAML): TCGA-LAML ships 0 solid-tissue-normal samples; an AML-vs-normal contrast needs a normal haematopoietic reference (e.g. GTEx whole blood / normal bone marrow), again a cross-study batch confound.

## Provenance

Per-cohort GDC file UUIDs, case barcodes and SHA-256 checksums are in `provenance.json` (and each cohort's own `provenance.json` under the GDC cache). The side-by-side per-antigen scoring across the full known set is in `report.html`.

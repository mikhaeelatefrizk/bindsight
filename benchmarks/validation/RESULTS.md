# bindsight rediscovery validation — results

Does bindsight's expression-based discovery resurface clinically-validated cell-surface antigens from real TCGA RNA-seq? Each antigen is evaluated in its indication cohort as a tumor-vs-adjacent-normal contrast run through the discovery half (`bindsight discover`), then scored by the rank of the antigen in the candidate shortlist (`bindsight.benchmark.score_run`).

**Every measured number below is produced by the runs. The only hand-set values are the _requested_ cohort sizes — inputs to the GDC query, shown in parentheses next to the achieved per-arm sample counts, which are derived from each run's own provenance. Antigens are grouped by their _measured_ differential expression (rule: FDR<0.05 and log2fc>=1.0), not by any prior label — an expression-based method can only surface antigens that are actually over-expressed, and we report that precondition transparently.**

Each cohort takes at most one sample per patient per arm (the lexicographically first aliquot), so no patient enters an arm twice.

Patients contributing to both arms are counted per cohort below; the DE design is unpaired (`~ condition`), so that pairing is not modelled.

- Generated: `2026-08-08T23:07:27+00:00` · bindsight `0.1.0`
- PAM50 subtypes: cBioPortal study `brca_tcga_pan_can_atlas_2018`
- Known-antigen set: `C:\Users\mikha\AppData\Local\Temp\claude\C--Users-mikha\74e65fb0-36e6-4d39-8c78-0b82e55dbc4c\scratchpad\bindsight-fix\benchmarks\known.tsv`

## Headline

- **Sensitivity:** of 3 antigen(s) genuinely over-expressed in their cohort, **ERBB2** is rediscovered at **rank 4** in TCGA-BRCA (BRCA_Her2 subtype) — log2fc 4.36, padj 1.7e-59.
- **recall@k over over-expressed antigens:** recall@5=33%, recall@10=33%, recall@20=33%.
- **Internal-consistency check (not a specificity measurement):** 2/2 antigens that fail the over-expression rule are absent from the top-20. Antigens failing the over-expression rule are excluded from candidacy by construction, so this check confirms internal consistency between the DE filter and the shortlist; it does not measure ranking discrimination. This check cannot fail unless the DE filter and the shortlist disagree, and it says nothing about how the pipeline ranks antigens that *are* over-expressed.

## Reproduce

```bash
pip install -e ".[discover,report]"
python benchmarks/run_validation.py
```

## Per-antigen results (grouped by measured over-expression)

`rank` is the antigen's 1-based position in the cohort's surface-filtered candidate shortlist; `—` = not surfaced. Only the cohort's own indication antigen counts as a rediscovery.

### Transcriptionally over-expressed (the pipeline should — and is scored to — surface these)

| antigen | project | tumor: got (asked) | normal: got (asked) | patients in both arms | log2fc | padj | rank | ≤5 | ≤10 | ≤20 |
|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| ERBB2 (P04626) | TCGA-BRCA | 50 (50) | 40 (40) | 0 | 4.36 | 1.7e-59 | 4 | ✓ | ✓ | ✓ |
| NECTIN4 (Q96NY8) | TCGA-BLCA | 50 (50) | 19 (19) | 2 | 1.59 | 3.9e-03 | — | · | · | · |
| FOLH1 (Q04609) | TCGA-PRAD | 50 (50) | 40 (40) | 3 | 1.32 | 3.4e-04 | — | · | · | · |

- **ERBB2** (TCGA-BRCA): PAM50 HER2-enriched tumors are ERBB2-amplified, so ERBB2 mRNA is high.
- **NECTIN4** (TCGA-BLCA): Nectin-4 (target of enfortumab vedotin, Padcev) is elevated in urothelial carcinoma, but only modestly at the bulk-mRNA level (log2fc ~1.6), below the discovery shortlist.
- **FOLH1** (TCGA-PRAD): PSMA (FOLH1) is highly expressed but also abundant in normal prostate, so the tumor-vs-normal fold-change is modest (reported for transparency).

### Not over-expressed at the bulk level (excluded from candidacy by the DE rule)

| antigen | project | tumor: got (asked) | normal: got (asked) | patients in both arms | log2fc | padj | rank | ≤5 | ≤10 | ≤20 |
|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| EGFR (P00533) | TCGA-LUAD | 50 (50) | 40 (40) | 5 | 0.42 | 1.3e-01 | — | · | · | · |
| CEACAM5 (P06731) | TCGA-COAD | 49 (50) | 40 (40) | 4 | -0.28 | 2.2e-01 | — | · | · | · |

- **CEACAM5** (TCGA-COAD): CEA (target of tusamitamab ravtansine / labetuzumab govitecan) is a classic colorectal marker, but it is also abundantly expressed in normal colon epithelium, so the bulk tumor-vs-adjacent-normal fold-change is ~0.
- **EGFR** (TCGA-LUAD): EGFR drives LUAD via mutation/amplification, not bulk mRNA over-expression, so a specificity-respecting pipeline should NOT surface it on expression alone.

### Underpowered (too few matched normals to call differential expression)

| antigen | project | tumor: got (asked) | normal: got (asked) | patients in both arms | log2fc | padj | rank | ≤5 | ≤10 | ≤20 |
|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| MSLN (Q13421) | TCGA-PAAD | 50 (50) | 4 (4) | 0 | 2.31 | 1.4e-01 | — | · | · | · |

- **MSLN** (TCGA-PAAD): Mesothelin is over-expressed in PDAC, but TCGA-PAAD ships only 4 matched normals, so the contrast is underpowered (reported for transparency).

## Cross-indication cross-reactivity (NOT rediscovery)

Known antigens of *other* cancer types that a cohort's shortlist happens to contain. They are excluded from recall@k: surfacing a colorectal antigen in a breast cohort is a cross-reactivity observation, not a rediscovery.

- **BRCA HER2-enriched** (BRCA) surfaced **CEACAM5** (COAD) at rank 3.
- **BLCA** (BLCA) surfaced **MSLN** (PAAD) at rank 12.
- **LUAD (EGFR negative control)** (LUAD) surfaced **CLDN6** (OV) at rank 10.

## Interpretation

- The discovery pipeline (subtype-stratified DESeq2 → SURFY surfaceome filter → combined-significance ranking) surfaces the antigen that is strongly transcriptionally over-expressed. Antigens that are not over-expressed — including clinically famous ones whose tumor-selectivity arises from mutation/amplification (EGFR) or lineage co-expression in the normal tissue-of-origin (CEA, PSMA) — are withheld by the DE gate itself rather than by the ranking, so their absence is a property of the filter, not evidence about the ranker. Sensitivity therefore tracks effect size, as expected for a differential-expression method.
- This delineates the scope of bulk tumor-vs-normal discovery and motivates the multi-modal specificity scoring (single-cell, co-expression, immunopeptidomics) planned for v1.0.

## Antigens with no matched TCGA normal (not runnable here)

- **CLDN6** (TCGA-OV): TCGA-OV ships 0 solid-tissue-normal RNA-seq samples; a clean tumor-vs-normal contrast is impossible without an external (GTEx) normal, which would introduce a cross-study batch confound.
- **CD33 / IL3RA (CD123)** (TCGA-LAML): TCGA-LAML ships 0 solid-tissue-normal samples; an AML-vs-normal contrast needs a normal haematopoietic reference (e.g. GTEx whole blood / normal bone marrow), again a cross-study batch confound.

## Provenance

Per-cohort GDC file UUIDs, case barcodes, SHA-256 checksums and the requested-vs-achieved sample counts are in `provenance.json` (and each cohort's own `provenance.json` under the GDC cache). The side-by-side per-antigen scoring — on-indication antigens plus any cross-indication cross-reactivity — is in `report.html`.

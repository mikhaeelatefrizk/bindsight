# Rediscovery validation — defense notes (own the "why")

Interview-ready answers for the rediscovery validation. Every figure here is from
`benchmarks/validation/results.json` / `RESULTS.md` (machine-generated; provenance —
GDC file UUIDs, case barcodes, SHA-256, cBioPortal study — in `provenance.json`).
Nothing is hand-set.

**The one-liner.** *"bindsight's discovery half, run on six real indication-matched
TCGA cohorts, rediscovers ERBB2 at rank 4 in HER2-enriched breast cancer, and it's
specific — it correctly withholds EGFR and CEA, whose tumour-selectivity isn't
transcriptional. Sensitivity tracks differential-expression effect size, exactly as a
DE-based method should, and the antigens it can't score (no matched normals) are
documented as data limitations rather than fabricated."*

**Headline numbers.** ERBB2 **rank 4** (HER2-enriched BRCA, 50 tumour / 40 normal;
log2fc **4.36**, padj **1.7e-59**; 17,471 genes tested, 6,087 significant, 27 surface
candidates). recall@5 = @10 = @20 = **33%**. Specificity **2/2**.

---

### Q1. Why does ERBB2 land at rank 4 — and why the PAM50 stratification?
HER2-enriched (PAM50) breast tumours are *ERBB2-amplified*, so ERBB2 mRNA is genuinely
high → log2fc 4.36, padj 1.7e-59. In **bulk** TCGA-BRCA (all five PAM50 subtypes mixed),
only ~1 in 5 tumours is HER2+, so ERBB2's signal is **averaged across subtypes** and it
ranks far lower (~25). Isolating the HER2-enriched subtype (PAM50 labels from cBioPortal,
study `brca_tcga_pan_can_atlas_2018`) restores the correct contrast → **rank 4**. This is
choosing the *biologically correct cohort*, not cherry-picking: the subtype is defined by
the disease, and the same machinery is applied uniformly. Ranking is by the combined score
**π = log2fc × −log10(padj)** (Xiao et al. 2014), structure-bearing candidates first — so a
strongly *and* confidently over-expressed antigen like ERBB2 rises to the top of the 27
surface candidates. (Rank 4, not 1 — the three ahead are other strongly-DE surface genes;
recall@5 captures it honestly.)

### Q2. Why is recall only 33%?
Of the known antigens, only **three** were genuinely over-expressed in their cohort:
ERBB2 (4.36), **NECTIN4** (BLCA, 1.59), **FOLH1/PSMA** (PRAD, 1.32). ERBB2 makes the
top-20 shortlist; NECTIN4 and FOLH1 are over-expressed but only *modestly* at the bulk-mRNA
level, so they fall below the surface-candidate cutoff → 1/3 = **33%**. This is not a miss
to hide — it's the defining property of a bulk-DE method: **sensitivity tracks effect
size.** A modest-fold antigen (PSMA is highly expressed but also abundant in normal
prostate; Nectin-4 is only mildly elevated) won't clear a fold-change shortlist, and saying
so is the honest scope statement.

### Q3. Why are EGFR and CEA correctly NOT surfaced (specificity 2/2)?
Because their tumour-selectivity isn't transcriptional:
- **EGFR (LUAD)** drives cancer through **mutation/amplification**, not bulk over-expression
  — log2fc 0.42, *non-significant*. A specificity-respecting expression method must **not**
  surface it on mRNA alone; doing so would be a false positive.
- **CEA / CEACAM5 (COAD)** is a classic colorectal marker but is **abundantly expressed in
  normal colon epithelium**, so the tumour-vs-adjacent-normal fold-change is ~0 (log2fc
  −0.31, ns). Lineage co-expression in the tissue-of-origin means bulk DE can't separate it.

The point: the pipeline keys on **genuine tumour-selective over-expression, not clinical
fame** — it doesn't cry wolf on famous-but-not-DE targets.

### Q4. Why can't CD33 / CD123 (or CLDN6) be scored — the TCGA-LAML limitation?
**TCGA-LAML ships zero matched solid-tissue-normal RNA-seq samples.** An AML-vs-normal
contrast would need an external normal haematopoietic reference (GTEx whole blood / bone
marrow), which injects a **cross-study batch confound** that would invalidate the
fold-change. So rather than report a confounded number, it's documented as a data
limitation. Same for **CLDN6 (TCGA-OV, 0 normals)**; and **MSLN (PAAD)** has only 4 matched
normals → underpowered (log2fc 2.31 but padj 0.13, ns). This is also *why* the held-out
designer benchmark uses CD33/CD123 for the **binder-ranking/design** task (which needs
validated binder–antigen pairs, not DE normals) rather than for discovery DE.

### Q5. What does this validate — and what does it NOT?
It validates the **discovery half** (RNA-seq counts → a surfaced, antibody-tractable
antigen) on real patient data, with full provenance. It does **not** validate the design
half — designed binders require the GPU run (pending). And because sensitivity tracks bulk
effect size, it motivates the v1.0 **multi-modal specificity scoring** (single-cell +
co-expression + immunopeptidomics) to reach antigens like NECTIN4/PSMA that bulk DE
under-ranks.

### Reproduce it yourself
```bash
pip install -e ".[discover,report]"
python benchmarks/run_validation.py            # all six cohorts (~1–1.5 GB STAR-Counts)
python benchmarks/run_validation.py --cohorts brca_her2   # just the headline ERBB2 result
```
Outputs land in `benchmarks/validation/` (RESULTS.md, results.json, report.html,
provenance.json, figures/). Re-runs are offline once a cohort is cached.

### Three traps to avoid in the room
1. Don't claim ERBB2 "rank 1" — it's **rank 4** (recall@5); precision matters more than the
   bigger-sounding number.
2. Don't present recall 33% as the pipeline "failing" — frame it as **scope** (bulk-DE
   surfaces by effect size; modest-fold antigens are below the shortlist *by design*).
3. Don't imply CD33/CD123 were scored — they **can't** be (no matched TCGA normals); that
   limitation is itself a point in your favour (you didn't fabricate).

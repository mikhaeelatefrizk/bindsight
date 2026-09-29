# Scientific validation status

**The recorded reproducibility checks pass; scientific validation remains limited.**
The workflow uses real public RNA-seq observations, but using real data does not
make every estimate correct. The audit found and corrected a lost dispersion
prior and inconsistent fitted-mean floors. An observation-based ordering policy
now prevents sample names from selecting a different numerical input order.
This enforces reproducibility at the workflow boundary; it does not establish
that the underlying estimator is stable under arbitrary row order. The workflow must not be described as fully validated,
100% accurate, or a demonstrated biological breakthrough.

This page records the numerical audits and independent R comparison performed
on **2026-09-29**. The
[numerical audit protocol](https://github.com/mikhaeelatefrizk/bindsight/blob/main/benchmarks/numerical_validation/README.md)
explains the inputs, comparisons and reproducibility requirements. The
[three-pair five-fit result](https://github.com/mikhaeelatefrizk/bindsight/blob/main/benchmarks/numerical_validation/results/canonical_three/validation.json)
and [eight-pair result](https://github.com/mikhaeelatefrizk/bindsight/blob/main/benchmarks/numerical_validation/results/canonical_eight/validation.json)
retain their declared tolerances. Earlier failed reports remain available separately.

## What was measured

The focused audit used **three matched tumor/normal pairs from TCGA-KIRC**:
six samples, 19,944 input protein-coding genes and 15,697 genes after the
configured count filter. The counts came from the NIH Genomic Data Commons
STAR–Counts workflow, using its unstranded count column, with sample identities
and file hashes retained. These are observed counts, not generated examples.
See the [GDC expression pipeline documentation](https://docs.gdc.cancer.gov/Data/Bioinformatics_Pipelines/Expression_mRNA_Pipeline/)
for the upstream processing method.

The model included patient pairing (`~ case_barcode + condition`). Its design
matrix had rank four, leaving only **two residual degrees of freedom**. This is
a deliberately small numerical check, not a representative clinical validation
cohort. Reported significance means adjusted p < 0.05 and absolute log2 fold
change ≥ 1 under this model.

| Check | Recorded observation-based-ordering outcome | What it supports |
|---|---|---|
| Wald statistic, two-sided probability and Benjamini–Hochberg arithmetic | Passed | The output columns agree with independently reconstructed arithmetic |
| Identical repeated fit | Passed | Reproducibility for these inputs and this recorded environment |
| Reverse tumor/normal contrast | Passed | Directional statistics reverse while nondirectional statistics agree |
| Reverse input sample order, preserving identifiers | Passed | Canonical ordering protects this file-order change |
| Consistently rename samples without changing observations or pairing | Passed | The wrapper preserves identical numerical input by construction |
| Independent R DESeq2 comparison | Completed; estimates and decisions differ | Numerical equivalence is not established |

The final recorded three-pair audit tests 15,697 genes and reports **3,852
significant genes** in all five fits. The eight-pair audit tests **16,485 genes**
in sixteen samples and reports **4,922 significant genes** in all fits. Repeats,
direction-adjusted contrast reversals, reordered columns and renamed sample IDs
have exactly matching compared numeric values and zero changed decisions. The
runs completed at **09:27:15 and 09:28:02 UTC**. Exact source snapshots identify
the executed audit versions; these outcomes are not blanket claims about every
later source change, numerical environment, or cohort.

## Retained failures before observation-based ordering

With the mean-floor correction and earlier label-based ordering, renaming samples changed the significant-gene
count from **3,851 to 3,854**. The largest absolute difference was **0.00188730**
for a raw p-value and **0.00318541** for an adjusted p-value. These exceed the
declared numerical tolerances. **Thirteen genes changed classification: eight
gained significance and five lost it.** Passing the arithmetic checks cannot validate the
dispersion estimates that produced those statistics.

A [second audit with eight matched pairs](https://github.com/mikhaeelatefrizk/bindsight/blob/main/benchmarks/numerical_validation/results/mean_floor_eight/validation.json)
tested 16,485 genes in sixteen samples. All five fits reported 4,922 significant
genes, with no changed significance decisions after renaming. However, the
identifier test still **failed its numerical tolerances**: maximum differences
were 0.00050627 for raw p-values and 0.00049960 for adjusted p-values. Stable
decisions in this second sample set do not erase the first cohort's failure or
establish numerical equivalence.

The earlier regularization-only results remain separate: three pairs had
14 changed decisions (3,855 to 3,865 significant), and eight pairs had no
changed decisions (4,924 significant). Those reports are not rewritten with
the later correction's numbers. Exact source snapshots and report hashes
identify each stage even though the fits ran during development.

## Independent R DESeq2 comparison

The same public counts were fitted separately with **R 4.6.1 and DESeq2 1.52.0**,
then compared with the mean-floor-corrected Python fits using the current
observation-based ordering. The tested genes, patient pairing,
contrast and significance rule were aligned; implementation-specific estimation
procedures remain distinct. This is an independent software comparison, not a
claim that R results are biological ground truth.

| Cohort | Genes compared | Significant in R | Significant in repaired Python | Different significance decisions |
|---|---|---|---|---|
| Three matched pairs | 15,697 | 3,938 | 3,852 | **204**: 145 R-only, 59 Python-only |
| Eight matched pairs | 16,485 | 4,923 | 4,922 | **1**: one R-only, zero Python-only |

The [three-pair comparison](https://github.com/mikhaeelatefrizk/bindsight/blob/main/benchmarks/numerical_validation/reference/cohort_3/canonical/comparison.json)
and [eight-pair comparison](https://github.com/mikhaeelatefrizk/bindsight/blob/main/benchmarks/numerical_validation/reference/cohort_8/canonical/comparison.json)
preserve the denominators, differences and settings. Neither comparison has
missing p-values or adjusted p-values, so these disagreements are not simply
different missing-data classifications. Numerical equivalence has not been
demonstrated. The three-pair model's limited residual degrees of freedom also
exposes a difference in dispersion-prior estimation between the implementations.
The comparison is useful precisely because it identifies disagreement that
internal repeatability checks cannot detect.

For eight pairs, the median, 90th percentile and maximum absolute raw p-value
differences are 0.00001858, 0.00018742 and 0.01366803. Good aggregate agreement
does not remove the largest discrepancies. The earlier regularization-only
comparisons remain preserved with 213 and three differing decisions; the
mean-floor correction with the earlier ordering had 211 and one. No old
comparison was overwritten. The comparison helper requires exactly equal,
unique gene sets and reports missing-value exclusions for every numeric metric.

## Corrections and their limits

**Dispersion fallback.** In the inspected PyDESeq2 0.5.4 code, an unsuccessful
optimizer calls a grid search without passing the requested prior settings.
The grid defaults to no prior. The new inference adapter preserves those
settings when recomputing failed fallbacks and retains the original convergence
flags. This corrects a specific objective mismatch; it does not prove all fits
are accurate. The source evidence is the versioned
[optimizer fallback](https://raw.githubusercontent.com/scverse/PyDESeq2/v0.5.4/pydeseq2/utils.py)
and [grid-search implementation](https://raw.githubusercontent.com/scverse/PyDESeq2/v0.5.4/pydeseq2/grid_search.py).
The [recorded objective comparison](https://github.com/mikhaeelatefrizk/bindsight/blob/main/benchmarks/numerical_validation/diagnostics/objective-proof.json)
shows the effect on actual fitted genes.

**Fitted-mean floors.** Independent R comparison localized a second defect:
fitted means below the specified minimum of 0.5 reached dispersion fitting and
Wald covariance calculations without the intended floor. The adapter now
applies that floor at those stages. The
[saved diagnostic inputs and replay](https://github.com/mikhaeelatefrizk/bindsight/blob/main/benchmarks/numerical_validation/reference/diagnostics/README.md)
separate the dispersion and covariance effects with fixed inputs. The largest
historical standard-error discrepancy involved a separate R dispersion-outlier
heuristic; it was not copied into the Python method. Correcting the floor does
not establish equivalence between the methods.

**Deterministic input and selection.** The workflow orders aligned observations
using modeled covariates and complete retained count columns, without sample
names. Renaming samples therefore preserves the same numerical input. This is
an explicit reproducibility policy, not a statistical repair of backend order
sensitivity; it does not establish invariance to relabeling modeled covariates.
Equal discovery scores also use gene identifiers before enrichment and
structure-fetch cutoffs, preventing file order from arbitrarily selecting a
different candidate.

**Traceable reuse and execution.** Differential-expression cache identity now
includes the scientific code, numerical stack and execution settings, and cache
reuse verifies the output bytes. An old cached fit cannot silently inherit a
changed adapter. A
[recorded local workflow check](https://github.com/mikhaeelatefrizk/bindsight/blob/main/benchmarks/numerical_validation/local_workflow_canonical.json)
ran the real six-sample counts through upload, fitting, discovery, reporting and
all eight downloads in 53.8 seconds on this host. Artifact hashes, the exact
source hashes and fitting warnings were checked. This measures local software
execution; it does not erase historical numerical failures or measure
biological performance.

**Measured versus missing safety evidence.** Open Targets liability counts now
carry their measurement status into ranking. An explicitly unmeasured or invalid
count no longer receives the benefit of a measured zero. This count is separate
from GTEx tissue expression. Neither a zero liability count nor a GTEx threshold
establishes clinical safety.

**Backbone-aware calibration.** The recorded ERBB2 control contains 20 designed
sequence/shuffle pairs from ten RFdiffusion backbones. Current inference uses
backbone means: design minus shuffle is **−0.04348 ipTM**, with a 95% bootstrap
interval **[−0.13673, +0.06309]** and a two-sided cluster sign-flip p-value of
**0.439453125**. This calculation assumes independent backbone clusters and,
for the sign-flip test, symmetric differences under the null. Historical
sequence-level statistics and original scores remain preserved and labelled.
See the [calibration report](https://github.com/mikhaeelatefrizk/bindsight/blob/main/benchmarks/calibration/CALIBRATION.md).

At ipTM 0.65, 6/20 designs and 10/20 shuffles pass. Shuffles have not been
experimentally established as nonbinders, so their pass rate is not a measured
biological false-positive rate. The data establish neither a positive design
advantage nor equivalence nor absence of binding. Controlled cross-target
inference cannot be recomputed over backbones because the historical summary
lacks the required per-design decoy-shuffle scores.

## Companion and local workflow checks

A second [real CPU/API run](audits/local-workflow-companion-2026-09-29.json)
completed on 2026-09-29 at 18:47 UTC. It checked the same 19,944 input genes,
completed discovery and reporting, verified all eight downloadable artifacts
against their recorded hashes, and exposed five eligible structure targets with
original-file hashes for GPU continuation. It took 423.362 seconds with one
analysis worker while other software checks shared the computer; this is not a
performance benchmark. Numerical fitting warnings remain visible in the record.
Its source hashes identify the tested development snapshot, rather than claiming
that every subsequent edit was part of that run.

The [Windows companion development record](https://github.com/mikhaeelatefrizk/bindsight/blob/main/companion/validation-evidence.json)
records a real isolated CPU installation and a packaged executable launching the
managed Python workspace. That installation used the previous published source
revision, explicitly identified in the record. The development binary is not a
release artifact. Publication requires clean, matching builds and packaged
self-tests on Windows, both Mac architectures and Linux. The CI dependency check
installs and imports the actual RFdiffusion, ProteinMPNN and Boltz environments
on a CPU runner; it cannot verify CUDA or scientific inference.

The later local software suite passed over 2,400 tests, with 15 skipped and two
deselected. Its one failure was a declaration check that did not yet recognize
the new local `companion` package. After adding that namespace to the check,
all 18 tests in the dependency-declaration and companion-publication groups
passed. Coverage was 83.62%. Final release checks are reported separately by
[GitHub Actions](https://github.com/mikhaeelatefrizk/bindsight/actions/workflows/ci.yml).

These checks do not establish binding, biological effectiveness, comprehensive
security, or compatibility with every visitor's computer. Desktop application
signing/notarization, real WSL setup and a complete new GPU design run have not
been verified here.

## What remains unverified

The [recorded local software checks](audits/local-software-checks-2026-09-29.json)
completed with over 2,300 tests passed and one failure; the dated record retains
the exact passing, skipped and deselected counts and the original log checksum.
That earlier failure was the Windows Application Control restriction described
below; it did not recur in the later run above. The dated record is retained
unchanged. Software checks do not establish scientific validity.

The independent [R DESeq2](https://bioconductor.org/packages/release/bioc/html/DESeq2.html)
comparison above has been performed; the remaining implementation differences
have not been reconciled. No machine-precision equivalence is claimed. The historical multi-cohort
benchmark has not been regenerated by this focused numerical audit, so its
stored results cannot silently inherit the new correction.

The CPU dependency set is pinned, and the [recorded post-update advisory audit](audits/dependency-audit-2026-09-29.json)
reported no known advisories across 103 audited packages. This is a dated
package-database result, not proof of software security, numerical correctness,
or coverage of optional GPU environments. The inference correction is guarded
for PyDESeq2 0.5.4 and requires review before changing that version.

The earlier local software suite encountered Windows Application Control
blocking the compiled `Bio.Align._codonaligner` import used by a
calibration-staging PDB sequence test. The same enabled test passed in the later
run; no operating-system security setting was changed. This does not establish
which host-policy condition changed. Software checks and scientific validation
answer different questions.

No new complete GPU design run was performed for this audit. The local 2 GB
MX450 cannot be presented as reproducing the committed workload that used
14,859 MiB peak memory on a T4. CPU tests and hardware detection do not exercise
the folding models. See [local workspace requirements](local-workspace.md).

There are no new laboratory binding, specificity, off-target, toxicity or
functional measurements in this audit. Expression ranking and predicted
structures remain evidence for selecting experiments, not evidence of a safe
or effective therapeutic binder. Characterizing estimator order sensitivity,
explaining cross-implementation discrepancies and experimentally testing candidates are
distinct requirements; none can substitute for the others.

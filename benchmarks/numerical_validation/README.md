# Numerical validation on public RNA-seq counts

**Recorded workflow reproducibility status on 2026-09-29: PASS for both cohorts
under observation-based input ordering.** Earlier failures remain preserved.
Renaming samples now preserves identical numerical input by construction; this
does not establish backend stability under arbitrary row order. The independent
R comparison still finds differing estimates and gene decisions. This directory
supports a numerical investigation, not completed biological validation or
equivalence to R DESeq2. The
[validation status page](../../docs/validation-status.md) gives the broader interpretation.

## Inputs and scope

[`cohort_3/provenance.json`](cohort_3/provenance.json) identifies the six public
GDC files and three matched TCGA-KIRC tumor/normal pairs. Counts use the
STAR–Counts unstranded column, GENCODE v36 and protein-coding genes. The
[GDC expression pipeline](https://docs.gdc.cancer.gov/Data/Bioinformatics_Pipelines/Expression_mRNA_Pipeline/)
describes the upstream quantification. No synthetic counts are used by this
audit. The larger [`cohort_8`](cohort_8/provenance.json) input set is separately
identified; the three-pair findings below must not be attributed to it.

| Input | SHA-256 |
|---|---|
| `cohort_3/counts.tsv.gz` | `ce5c5c6670707568b28a6e2ce561a05b708121f150ad1d093775a05d5503229c` |
| `cohort_3/design.tsv` | `4f7e3fa2b16811d4e294ede695a777776846fa91caf247eeee43df93f44603a4` |

The [configuration](config.yaml) specifies `~ case_barcode + condition`, tumor
versus normal, adjusted p < 0.05, absolute log2 fold change ≥ 1, `min_count=10`
and one CPU worker. The recorded fit contains 19,944 input genes and 15,697
tested genes. Six samples and a rank-four design leave two residual degrees of
freedom. This sample size limits biological generalization and makes numerical
diagnostics particularly important.

The recorded environment was Windows 11, Python 3.13.14, PyDESeq2 0.5.4,
NumPy 2.2.6, SciPy 1.16.3, pandas 2.3.2 and PyArrow 23.0.1. Reports retain the
full package list relevant to fitting, numerical thread settings, input/output
hashes, source hashes, Git revision and whether the working tree was dirty.
The source hashes are essential because this audit ran during development;
the Git revision alone does not identify the executed code.

## Protocol

[`scripts/validate_real_counts.py`](../../scripts/validate_real_counts.py) runs
five fresh fits of the same observations:

1. The configured forward contrast.
2. An identical repeat.
3. The reversed contrast, requiring fold changes and Wald statistics to change
   sign while standard errors, probabilities and significance decisions agree.
4. Reversed sample columns with the original identifiers.
5. A consistent bijective renaming of sample identifiers in counts and metadata,
   preserving observations, conditions and patient pairing. In the historical
   label-based policy this reversed estimator input order and exposed backend
   sensitivity. The current observation-based policy preserves identical
   numerical input by construction. A pass now tests that wrapper contract,
   not whether the backend estimator is stable under arbitrary row order.

Every fit is checked for valid identifiers, positive finite standard errors,
probability bounds, Wald arithmetic, independently reconstructed two-sided
normal probabilities and Benjamini–Hochberg adjusted values on the retained
genes. The significance rule is reconstructed separately. These checks validate
output arithmetic; they do not independently estimate the model parameters or
validate the choice of genes retained by independent filtering.

The comparison uses relative tolerance `1e-6` and absolute tolerance `1e-8`,
with matching missing-value locations and identical significance decisions.
An all-missing comparison does not pass. The script writes `passed: false`
and exits with status 1 if any check fails. Do not remove a failed check,
increase tolerances retrospectively or overwrite an old run to obtain a pass.

## Current recorded observation-based ordering

The workflow now orders modeled covariate values and the complete retained
count columns independently of sample identifiers. SHA-256 fingerprints order
the count columns; full count bytes break any hash collisions. Gene rows are
ordered by gene ID. Identical modeled observations may tie. This fixes the
wrapper's representation without changing observations, pairing, model formula,
fitting objective or declared tolerances. It is a reproducibility policy, not
evidence that arbitrary estimator row orders or relabeled covariates give the
same estimates. The retained failures below show why that distinction matters.

| Recorded audit | Tested genes | Significant in each of five fits | Changed decisions on renaming | Outcome |
|---|---|---|---|---|
| [Three pairs](results/canonical_three/validation.json) | 15,697 | 3,852 | 0 | Pass |
| [Eight pairs](results/canonical_eight/validation.json) | 16,485 | 4,922 | 0 | Pass |

Both cohorts pass per-fit arithmetic, identical repeats, reversed contrasts,
reversed sample columns and consistent sample renaming at the original
`rtol=1e-6`, `atol=1e-8` tolerances. All compared numbers match exactly after
contrast direction is accounted for. Runs completed at **09:27:15 UTC** and
**09:28:02 UTC** on 2026-09-29. All ten Parquet hashes, both source-snapshot
hashes and every embedded executed-source hash were verified, and the R
comparison records identify those exact forward tables. Snapshot bytes identify
the audited source version; the Git revision or subsequent source files alone
do not.

The same independently fitted R reference gives these comparisons with the new
canonical forward results:

| Comparison | Genes | R significant | Python significant | Both | R-only | Python-only | Differing decisions |
|---|---|---|---|---|---|---|---|
| [Three pairs](reference/cohort_3/canonical/comparison.json) | 15,697 | 3,938 | 3,852 | 3,793 | 145 | 59 | **204** |
| [Eight pairs](reference/cohort_8/canonical/comparison.json) | 16,485 | 4,923 | 4,922 | 4,922 | 1 | 0 | **1** |

All tested genes match exactly, with no missing or excluded raw/adjusted
probabilities. For eight pairs, absolute raw p-value differences have median
**0.0000185758**, 90th percentile **0.0001874245** and maximum **0.01366803**;
the maximum adjusted p-value difference is **0.02356185**. For three pairs the
maximum raw/adjusted p-value differences are **0.06234514 / 0.09346180**. The
three-pair model's low residual degrees of freedom expose distinct prior
estimation procedures, while other localized method differences remain.
These are descriptive comparisons, not a new pass threshold or a claim that R
is biological ground truth. Passing the wrapper audit does not reconcile them.

Each comparison directory preserves sanitized metadata, two compressed
gene-difference tables and a manifest with raw/published hashes and exact
comparison-helper source. The historical mean-floor and regularization-only
comparisons below are separate, unchanged records.

## Historical mean-floor correction with label-based ordering

The subsequent correction applies the configured `min_mu=0.5` at dispersion
and Wald covariance boundaries. It retains the inherited IRLS output for other
stages and the earlier regularization repair. The
[controlled diagnostic replay](reference/diagnostics/README.md) preserves the
historical fitted means, priors, coefficients and dispersions needed to isolate
these effects. Those ten genes were selected to investigate discrepancies, not
as an unbiased validation cohort. The largest historical SE discrepancy also
involved a distinct R `noIncrease`/dispersion-outlier heuristic; that heuristic
was not copied into Python to force agreement.

New complete five-fit runs, rather than edits to prior reports, record the
correction's effects:

| Audit | Tested genes | Forward significant | Renamed significant | Changed decisions | Result |
|---|---|---|---|---|---|
| [Three pairs](results/mean_floor_three/validation.json) | 15,697 | 3,851 | 3,854 | **13**: eight gained, five lost | **Fail** |
| [Eight pairs](results/mean_floor_eight/validation.json) | 16,485 | 4,922 | 4,922 | **0** | **Fail** |

Both runs pass the arithmetic, identical-repeat, contrast-reversal and
reversed-column checks. Both retain failed numerical comparisons after sample
renaming. Their completion times were **01:53:53 UTC** and **01:54:50 UTC** on
2026-09-29. Maximum rename discrepancies are:

| Column | Three pairs | Eight pairs |
|---|---|---|
| log2 fold change | 0.005216918450043906 | 0.0001981593051842978 |
| standard error | 0.006195907849618987 | 0.00034407233391658965 |
| Wald statistic | 0.05195277317224978 | 0.0039026240666357737 |
| raw p-value | 0.0018872954933460973 | 0.00050627362935729 |
| adjusted p-value | 0.0031854079848961936 | 0.0004996006661647789 |

Each run directory contains all five result tables and `source_snapshot.json`.
The snapshot preserves exact executed source bytes as base64 with SHA-256;
`validation.json` records the snapshot hash and checks that the source stayed
unchanged during execution. This is necessary because these audits ran in a
development working tree. A later source revision must not inherit their
outcomes without another recorded run.

The same saved R fits were compared with the new mean-floor forward tables:

| Comparison | Genes | R significant | Python significant | Both | R-only | Python-only | Differing decisions |
|---|---|---|---|---|---|---|---|
| [Three pairs](reference/cohort_3/mean_floor/comparison.json) | 15,697 | 3,938 | 3,851 | 3,789 | 149 | 62 | **211** |
| [Eight pairs](reference/cohort_8/mean_floor/comparison.json) | 16,485 | 4,923 | 4,922 | 4,922 | 1 | 0 | **1** |

No raw or adjusted probabilities are missing or excluded in these comparisons.
The eight-pair absolute raw p-value differences have median **0.0000192961**,
90th percentile **0.0001890984** and maximum **0.01366803**; the largest adjusted
p-value difference is **0.02356185**. For three pairs the largest raw and adjusted
p-value differences are **0.06328050** and **0.09476758**. High overall agreement
does not imply per-gene numerical equivalence, and R is not biological ground
truth. Historical regularization-only comparisons below remain unchanged.

The hardened comparison helper rejects duplicate, missing or mismatched gene
IDs, rather than silently intersecting gene sets. It includes all genes in
decision agreement; each numeric statistic reports the full denominator,
jointly finite denominator and excluded counts. Positive finite probabilities
alone enter log-probability differences, with zero/missing values counted
explicitly. Undefined correlations are null. The export manifests preserve raw
and published hashes and exact helper source; host paths alone are sanitized
in metadata, while compressed TSV cells remain unchanged.

```bash
python scripts/compare_deseq2_reference.py \
  --r benchmarks/numerical_validation/reference/cohort_3 \
  --python benchmarks/numerical_validation/results/mean_floor_three/forward.parquet \
  --out runs/r-comparison-mean-floor-three
```

`--out` must be a new directory. The comparison records differences without
creating a post-hoc agreement threshold.

## Local execution and cache provenance

The [observation-based-ordering local workflow check](local_workflow_canonical.json)
completed the real six-sample workflow in **53.838 seconds**, from 09:24:33 to
09:25:27 UTC on 2026-09-29. All nine recorded checks passed: stages completed,
all eight downloads were nonempty, artifact hashes matched, fit/table and
annotation/report records agreed, warnings were visible, and sources stayed
unchanged. This uses four CPU workers and checks the local software path, not
biological validity or performance on other hosts.

The [mean-floor local workflow check](local_workflow_mean_floor.json) completed
on the real six-sample inputs in **59.833 seconds**, from 09:10:37 to 09:11:37 UTC
on 2026-09-29. This separate execution used four CPU workers; the numerical
five-fit audits used one. Upload, fitting, discovery, coverage and reporting
completed. All eight downloadable artifacts were nonempty and their hashes
matched the manifest. The fit record matched the DEG table, recorded numerical
warnings appeared in the report, and sources were unchanged during execution.
This verifies the local API/software path; it does not erase numerical failures,
establish biological validity, or benchmark other hosts.

DEG cache keys now incorporate input content, configuration, scientific source
hashes, numerical package versions and execution settings. Reuse also verifies
the output table's byte size and SHA-256; old records without this attestation
miss conservatively. This prevents a stale result from being attributed to a
new adapter solely because the package version stayed unchanged. The check's
manifest records source identities and fit warnings, including nonconverged
dispersion flags; a returned fallback estimate is not labelled convergence.

## Historical regularization-only three-pair result

The [machine-readable report](results/repaired_three/validation.json) and its
five adjacent Parquet tables preserve the complete result, including failure.

| Comparison | Outcome | Recorded result |
|---|---|---|
| Per-fit arithmetic | Pass | All five fits pass the listed arithmetic checks |
| Identical repeat | Pass | Numeric tables match exactly |
| Contrast reversal | Pass | Direction-adjusted numeric tables match exactly |
| Reversed sample columns | Pass | Numeric tables match exactly after canonical ordering |
| Consistent sample renaming | **Fail** | Five numeric columns and significance decisions differ |

The forward, repeat, reversed-contrast and reversed-order fits each contain
**3,855 significant genes**. The renamed fit contains **3,865**. For the rename
comparison, maximum absolute discrepancies are:

| Column | Maximum absolute difference |
|---|---|
| log2 fold change | 0.004435359922521087 |
| standard error | 0.005603367435964346 |
| Wald statistic | 0.055870403009434355 |
| raw p-value | 0.0020030928053353936 |
| adjusted p-value | 0.0032786183451607998 |

The base-mean comparison passes; its largest absolute difference is
2.3283064365386963e-10. Comparing the stored gene-level decisions shows
**14 changes: 12 gained significance and two lost it**, for a net increase of ten.
The forward fit reports 32 failed
gene-wise and nine failed MAP optimizer calls; the rename fit reports 48 and
ten respectively. Repaired grid estimates are retained alongside those failure
flags, not relabelled as optimizer convergence.

## Historical regularization-only eight-pair result

The [second five-fit report](results/repaired_eight/validation.json), completed
at 01:24:42 UTC, uses sixteen samples and tests 16,485 of 19,944 input genes.
All fits report 4,924 significant genes. Arithmetic, repeatability, contrast
reversal and the reversed-column comparison pass. Sample renaming again fails
the declared numerical tolerances, although **no gene changes its significance
decision** in this set.

| Column | Maximum absolute rename difference |
|---|---|
| log2 fold change | 0.00001780400436457441 |
| standard error | 0.0003436540670728738 |
| Wald statistic | 0.015619210126086358 |
| raw p-value | 0.00039244139828895075 |
| adjusted p-value | 0.0004906804049515934 |

Base means agree exactly. Stable significance decisions for this cohort do not
turn its failed numerical comparison into a pass or resolve the smaller
cohort's changed decisions.

## Historical regularization-only R DESeq2 comparison

[`scripts/reference_deseq2.R`](../../scripts/reference_deseq2.R) fits the same
observations using R 4.6.1, DESeq2 1.52.0 and Bioconductor 3.23.1. The paired
formula, tumor-versus-normal contrast, low-count filter and significance rule
match the Python audit. The R script requests a parametric dispersion trend,
ratio size factors, Wald testing without LFC shrinkage, alpha 0.05 and default
Cook's/independent filtering. Secondary outputs without filtering are labelled
as diagnostics rather than substituted for the primary comparison.

| Cohort | Same tested gene set | Significant in both | R-only | Python-only | Total differing decisions |
|---|---|---|---|---|---|
| [Three pairs](reference/cohort_3/comparison.json) | 15,697 | 3,790 | 148 | 65 | **213** |
| [Eight pairs](reference/cohort_8/comparison.json) | 16,485 | 4,922 | 1 | 2 | **3** |

Thus R reports 3,938 significant genes versus repaired Python's 3,855 for three
pairs, and 4,923 versus 4,924 for eight pairs. These are gene-level decision
comparisons, not the net difference between aggregate counts. Both comparisons
contain complete p-values and adjusted p-values; neither R fit reports failed
coefficient convergence. Normalized base means agree to about 3.03e-9 at worst,
but that agreement does not establish equivalence of dispersion estimates,
standard errors or test probabilities.

The largest absolute differences between implementations are retained rather
than hidden by aggregate agreement:

| Cohort | log2 fold change | Raw p-value | Adjusted p-value |
|---|---|---|---|
| Three pairs | 0.2072886754460601 | 0.06457038958371897 | 0.09634457578121042 |
| Eight pairs | 0.14646175291549524 | 0.07125851207217584 | 0.08733354157684639 |

These maxima can occur at different genes. They are cross-implementation
differences and must not be confused with the smaller sample-renaming
differences reported above.

The three-pair model has only two residual degrees of freedom. R's recorded
dispersion-prior variance is 0.768768768768769, versus approximately 0.503 in
the Python implementation; the low-residual-df estimation procedures differ.
The eight-pair design has seven residual degrees of freedom and does not enter
that low-df branch. These distinctions mean that identical high-level settings
do not imply identical estimation procedures. The comparison does not identify
either implementation as biological ground truth or justify changing one
method's settings merely to force agreement.

The primary R fits began at 01:25:22 and 01:26:04 UTC respectively. Their
versioned scripts, settings, session information, saved diagnostics and result
hashes support inspection of the disagreement. This completed comparison
replaces the earlier pending status; it does not turn either numerical audit
into a pass or validate any biological target.

## Confirmed upstream objective mismatch

The inspected PyDESeq2 0.5.4 fallback omits prior settings when calling
`grid_fit_alpha`; its default disables the prior. The Bindsight inference
adapter repeats failed grid searches with the requested regularization settings
and retains the original convergence flags. The regularization-only repair
left successful optimizations unchanged; the separate mean-floor correction
described above also changes stage inputs. The adapter is guarded to that
dependency version. Primary source:
[versioned optimizer code](https://raw.githubusercontent.com/scverse/PyDESeq2/v0.5.4/pydeseq2/utils.py),
[versioned grid code](https://raw.githubusercontent.com/scverse/PyDESeq2/v0.5.4/pydeseq2/grid_search.py).

The [independent objective evaluation](diagnostics/objective-proof.json) on the
original run illustrates the defect.
For `ENSG00000255302`, the saved dispersion was 0.00019671957006654, exactly
the unregularized grid result. Including the requested prior gave a grid
estimate of 0.10542821198428566; independent minimization of that same MAP
objective gave 0.10528345343073095. The objective value decreased from
102.52673608964542 at the saved estimate to 61.682510337951335 at the independent
optimum. This supports the specific lost-prior diagnosis, not independent
validation of the full pipeline.

The saved diagnostic arrays, variable table, fit metadata and result table are
included beside the proof. Re-evaluate the ten selected genes from those saved
values, without fitting the cohort again:

```bash
python benchmarks/numerical_validation/diagnostics/reproduce_objective.py \
  --out runs/objective-proof-reproduced.json
```

This script requires PyDESeq2 0.5.4 and refuses an existing output file. Its
likelihood uses SciPy's negative-binomial probability function, independently
of PyDESeq2's likelihood implementation, while retaining the same Cox–Reid and
prior terms. The original and reproduced records can be compared directly;
the source environment reproduced the saved record exactly. The ten genes are
selected by the largest original sample-order discrepancies, so this diagnostic
selection is not an unbiased genome-wide validation sample.

The correction removes that objective mismatch. Historical sample-renaming
failures show that it did not settle numerical reliability. Current
observation-based sorting makes the wrapper reproducible under renaming,
without establishing the estimator's stability under arbitrary row order.
Historical benchmark results have not been silently recomputed or replaced.

## Reproduce without replacing evidence

From the repository root, install the pinned CPU environment described in
[`envs/constraints.txt`](../../envs/constraints.txt), then choose a new output
directory. For example:

```bash
python scripts/validate_real_counts.py \
  --counts benchmarks/numerical_validation/cohort_3/counts.tsv.gz \
  --design benchmarks/numerical_validation/cohort_3/design.tsv \
  --config benchmarks/numerical_validation/config.yaml \
  --out runs/numerical-audit-cohort3 \
  --cpus 1
```

The harness refuses an existing output directory. Retain the generated
`validation.json`, five result tables and source/input hashes even when the
command exits with failure. Each new correction requires a separately recorded
rerun, not an edited outcome in an existing report.

## Boundaries of this evidence

- The independent [R DESeq2](https://bioconductor.org/packages/release/bioc/html/DESeq2.html)
  comparison has been performed, with the disagreements above retained.
  Internal arithmetic and repeatability do not establish cross-implementation
  equivalence; R results are not biological ground truth.
- Dependency pins and the [recorded advisory audit](../../docs/audits/dependency-audit-2026-09-29.json) describe a specific CPU
  environment. The post-update audit found no known advisories across 103
  audited packages; this is not a security guarantee or validation of optional
  GPU dependencies. PyArrow was raised to 23.0.1, while the inference adapter
  explicitly requires the inspected PyDESeq2 0.5.4 release.
- Windows Application Control blocks the compiled `Bio.Align._codonaligner`
  import used by a calibration-staging PDB sequence test. The failure remains
  visible; it was not skipped and no operating-system security setting was
  changed. The actual local CPU/API workflows above succeed. This environment
  limitation is separate from numerical and scientific validation.
- No new GPU folding run was performed here. A local 2 GB MX450 does not
  reproduce the published workload that used 14,859 MiB peak on a T4. Hardware
  checks, dry runs and CPU regression tests do not establish model execution.
- This audit contains no laboratory binding, specificity, toxicity or functional
  measurements. The recorded workflow reproducibility pass does not establish
  those outcomes or justify a claim of 100% scientific correctness.

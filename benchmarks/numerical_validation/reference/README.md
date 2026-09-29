# Independent R DESeq2 reference

These are genuine fits of the public TCGA-KIRC paired count cohorts using R 4.6.1 and Bioconductor DESeq2 1.52.0. R is an independent implementation, not biological ground truth. Numerical agreement, sample-order stability, and biological validity are separate questions. No acceptance tolerance was selected after observing these comparisons.

The `cohort_3` and `cohort_8` directories retain R results, dispersion/convergence diagnostics, design matrices, size factors, session information and manifests. Their original `comparison.json` files compare the **regularization-only** PyDESeq2 adapter (before the later mean-floor correction). New comparisons must identify their Python result hashes and be preserved separately. See the parent [validation overview](../README.md) for the latest audit stage.

## Reproduce the R reference

Run from the repository root on 64-bit Windows. The recorded setup uses official binary packages; it does not need Rtools or a compiler. The setup script downloads the exact archives in [setup-provenance.json](setup-provenance.json), verifies their SHA256 values, extracts R without executing its installer, and installs binary R packages into the selected directory. It sets environment variables only in the current PowerShell process; it does not change global PATH, file associations, registry entries or system configuration.

```powershell
& .\benchmarks\numerical_validation\reference\setup_reference.ps1 -Destination .\work\r-reference
$rReference = (Resolve-Path .\work\r-reference).Path
& "$rReference\runtime\app\bin\Rscript.exe" --vanilla scripts/reference_deseq2.R benchmarks/numerical_validation/cohort_3/counts.tsv.gz benchmarks/numerical_validation/cohort_3/design.tsv "$rReference\reproduced\cohort_3"
& "$rReference\runtime\app\bin\Rscript.exe" --vanilla scripts/reference_deseq2.R benchmarks/numerical_validation/cohort_8/counts.tsv.gz benchmarks/numerical_validation/cohort_8/design.tsv "$rReference\reproduced\cohort_8"
```

Run the fits sequentially. Each reference fit uses one R process with `parallel=FALSE` and `SerialParam`. The reference script refuses an existing output directory. For a later shell, set `R_USER` to the reference directory's `user`, `R_LIBS_USER` and `R_LIBS_SITE` to its `library`, `TMPDIR` to its `tmp`, and `OMP_NUM_THREADS`, `OPENBLAS_NUM_THREADS` and `MKL_NUM_THREADS` to `1` before launching R. The binary package versions and session details are recorded in [installed-packages.csv](installed-packages.csv) and [setup-session-info.txt](setup-session-info.txt). Upstream archive URLs can expire; the manifests identify exact required bytes and the original local download cache is retained outside the repository.

The convenient setup helper was assembled from the successful extraction/installation workflow and syntax-checked; a second cold installation was not run. Exact original installation/fit launch scripts are retained in the diagnostic source manifest. The two original R fits and the ten-gene diagnostic replay were actually executed.

The R script checks sample and gene identifiers and raw nonnegative integer counts, sorts samples and genes, applies `count >= 10 in >= 3 samples`, and fits `~ case_barcode + condition` with the contrast tumor versus normal. It requests parametric dispersion fitting, ratio size factors, a Wald test, `betaPrior=FALSE`, `minReplicatesForReplace=7`, `useT=FALSE`, and `minmu=0.5`. Results use alpha 0.05, default Cook's cutoff and independent filtering. The post-fit decision rule is `padj < 0.05` and `abs(log2FoldChange) >= 1`, without LFC shrinkage. The recorded design matrices and factors make the actual encodings reviewable.

For a descriptive comparison against a saved Python forward fit:

```powershell
python scripts/compare_deseq2_reference.py --r benchmarks/numerical_validation/reference/cohort_8 --python benchmarks/numerical_validation/results/repaired_eight/forward.parquet --out work/reference-comparison-eight
```

The helper checks gene sets and reports differences and decision counts; it does not declare either implementation correct or choose a pass threshold. Use a new output name for each adapter revision.

## Provenance and archive transformations

The [CRAN Windows distribution](https://cran.r-project.org/bin/windows/base/) supplied R 4.6.1. The installer matched its [published MD5](https://cran.r-project.org/bin/windows/base/md5sum.R-4.6.1.txt), `7907f3a20ec8ec88cd0da279024b8e27`; its local SHA256 is `c5424c40cd70ef85765a55d2ff96bb602b5f30ed536938ff004f14db5db3c2df`. R was extracted with [innoextract 1.9](https://constexpr.org/innoextract/), whose ZIP matched published MD5 `72d0d0dd874b6236eaa44411f4470ee1` and local SHA256 `6989342c9b026a00a72a38f23b62a8e6a22cc5de69805cf47d68ac2fec993065`. The [R Windows FAQ](https://cran.r-project.org/bin/windows/base/rw-FAQ.html) documents relocatable basic installations. These are HTTPS source/checksum checks, not a claim of independent signature verification.

DESeq2 came from the [official Bioconductor release](https://bioconductor.org/packages/release/bioc/html/DESeq2.html). All 49 downloaded archives, including 46 binary package ZIPs, the R installer, extractor and exact [DESeq2 1.52.0 source archive](https://bioconductor.org/packages/3.23/bioc/src/contrib/DESeq2_1.52.0.tar.gz), have URLs, byte sizes and hashes in the setup manifest. The source archive SHA256 is `8c91699286336350e66eec132ce6fdf5bb4af78e2a4d015a5a61224f62a95984`.

Each cohort's `artifact-manifest.json` records raw-source and published hashes. TSVs are gzip compressed with a fixed timestamp. `gene_diagnostics.tsv.gz` is an explicitly recorded column projection preserving retained cell strings; full raw TSVs and RDS models remain in the original isolated workspace. The omitted RDS files have sizes and hashes in the manifest and are recreated by the R commands above. In both observed fits the separately requested results without independent filtering were byte-identical to the default results and are omitted as redundant. There were no missing p-values or adjusted p-values; all R coefficient `betaConv` flags were true. This does not assert convergence of every dispersion optimizer: some gene-wise dispersion fits reached their iteration limit.

Absolute host prefixes were removed from public metadata and logs deterministically. Public plain-text files use LF newlines so manifest hashes survive a Git checkout; compressed TSV content is unchanged. Raw originals remain unmodified; this was not a fit rerun. Public original input checksum keys are repository-relative. Common-file transformations are recorded in [provenance-transformations.json](provenance-transformations.json). The current R script uses input basenames for future metadata; that metadata-only edit did not generate the recorded fits. Exact bytes of the originally executed R script are stored as base64 with SHA256 in [diagnostics/artifact-manifest.json](diagnostics/artifact-manifest.json), so its recorded source can be reconstructed without relying on Git newline normalization.

## Historical comparison and localized findings

The regularization-only adapter comparison tested all 15,697 retained genes for three pairs and all 16,485 for eight pairs:

| Pairs | Significant in both | R only | Python only | Neither |
| --- | ---: | ---: | ---: | ---: |
| 3 | 3,790 | 148 | 65 | 11,694 |
| 8 | 4,922 | 1 | 2 | 11,560 |

These historical comparisons are not numerically equivalent. The largest absolute LFC/SE differences were 0.207289/1.245536 for three pairs and 0.146462/0.365888 for eight pairs. High overall correlations do not remove these per-gene differences or the 213/3 changed decisions. The three-pair R dispersion-prior variance was 0.7687687688 versus approximately 0.503 in Python. In the exact R release, `estimateDispersionsPriorVar` uses a simulation/grid/loess procedure when residual degrees of freedom are at most three. PyDESeq2 0.5.4 uses the squared-MAD/trigamma approximation with a warning. This is a known methodological difference; it has not been shown to explain every disagreement.

Eight-pair localization identified two distinct mechanisms. The ten selected genes, raw means, saved-fit metadata and bounded proof results are under [diagnostics](diagnostics/README.md). They were selected to investigate extreme differences and changed decisions, not as a representative sample or an acceptance set.

* For `ENSG00000074803`, the largest SE difference, R retained gene-wise dispersion 2.505196 as an outlier; Python used MAP dispersion 1.155398. The two MAP estimates were already close (R 1.156166). R's gene-wise `noIncrease` rule can retain the initial dispersion when objective improvement is too small, changing the subsequent outlier classification. `ENSG00000167580` showed a similar pattern. The adapter does not copy this R-specific heuristic or force agreement.
* Several sparse genes exposed a separate general stage-boundary error: unfloored IRLS means reached dispersion and Wald covariance stages. Exact R 1.52.0 source floors means at `minmu` before dispersion and in `src/DESeq2.cpp::fitBeta` before final weights/covariance. PyDESeq2 0.5.4 returns raw IRLS means and its downstream stages do not consistently restore this floor. Holding the Python prior fixed, flooring only dispersion means moved `ENSG00000139800` MAP dispersion from 5.096570 to 8.955560 (R 9.068652); substituting the R means and prior gave 9.069180. For `ENSG00000156096`, holding coefficients and dispersion fixed, flooring only covariance means changed SE 1.030699 to 0.993707 (R 0.994860). These controlled changes localize an objective/covariance mismatch rather than relying on aggregate correlation.

The subsequent adapter repair floors means locally at those two boundaries and preserves inherited IRLS behavior in other stages. Its independent regression tests check the scalar MAP objective and explicitly assembled covariance, not a requirement to reproduce an R output. It retains optimizer failure flags and the earlier correction for a grid fallback that discarded requested dispersion regularization. The exact regularization-only adapter used for the historical comparisons is preserved in [the source snapshot](../source_snapshots/regularization_only.json), SHA256 `62a98b187accc69483e58fd266ae53bc94b306561576585ef4beb94ed2d7f764`.

Neither repair establishes biological correctness or guarantees sample-label invariance. The separate five-fit audit and final independent comparisons must remain visible even when they fail strict numeric criteria. No change to the R dispersion-outlier heuristic, post-hoc threshold adjustment, or favorable-result selection was made.

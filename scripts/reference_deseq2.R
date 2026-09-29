# SPDX-License-Identifier: AGPL-3.0-or-later
# Genuine R DESeq2 reference on supplied observations, with saved fit diagnostics.
# Usage: Rscript --vanilla scripts/reference_deseq2.R counts.tsv.gz design.tsv new-output-dir
# The caller selects an isolated package library through R_LIBS_USER/R_LIBS_SITE.

args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 3L) {
    stop("Expected counts.tsv[.gz], design.tsv, and a new output directory")
}
suppressPackageStartupMessages(library(DESeq2))
suppressPackageStartupMessages(library(BiocParallel))
stopifnot(requireNamespace("jsonlite", quietly = TRUE))
options(digits = 17, Ncpus = 1L)
register(SerialParam())

counts_path <- normalizePath(args[[1]], winslash = "/", mustWork = TRUE)
design_path <- normalizePath(args[[2]], winslash = "/", mustWork = TRUE)
out <- args[[3]]
if (dir.exists(out)) stop("Output directory already exists; retain previous evidence")
dir.create(out, recursive = TRUE)
out <- normalizePath(out, winslash = "/", mustWork = TRUE)
warnings_seen <- character()
started <- Sys.time()

withCallingHandlers({
    counts <- as.matrix(read.delim(counts_path, row.names = 1L, check.names = FALSE,
                                  quote = "", comment.char = ""))
    design <- read.delim(design_path, row.names = 1L, check.names = FALSE,
                         colClasses = "character", quote = "", comment.char = "")
    stopifnot(!anyDuplicated(rownames(counts)), !anyDuplicated(colnames(counts)),
              !anyDuplicated(rownames(design)),
              setequal(colnames(counts), rownames(design)),
              all(is.finite(counts)), all(counts >= 0), all(counts == floor(counts)),
              max(counts) <= .Machine$integer.max,
              all(c("condition", "case_barcode") %in% colnames(design)))
    # Match the wrapper's deterministic identifier order, preserving all values
    # and pairings. Sorting does not independently validate the statistical model.
    samples <- sort(colnames(counts), method = "radix")
    counts <- counts[sort(rownames(counts), method = "radix"), samples, drop = FALSE]
    design <- design[samples, , drop = FALSE]
    design$condition <- factor(design$condition, levels = c("normal", "tumor"))
    design$case_barcode <- factor(design$case_barcode,
                                 levels = sort(unique(design$case_barcode), method = "radix"))
    stopifnot(!anyNA(design$condition), !anyNA(design$case_barcode),
              all(table(design$condition) >= 3L))
    n_input <- nrow(counts)
    keep <- rowSums(counts >= 10L) >= 3L
    counts <- counts[keep, , drop = FALSE]
    storage.mode(counts) <- "integer"
    model <- model.matrix(~ case_barcode + condition, data = design)
    stopifnot(qr(model)$rank == ncol(model), nrow(model) > ncol(model))
    write.table(data.frame(sample = rownames(model), model, check.names = FALSE),
                file.path(out, "design_matrix.tsv"), sep = "\t", quote = FALSE, row.names = FALSE)
    dds <- DESeqDataSetFromMatrix(countData = counts, colData = design,
                                 design = ~ case_barcode + condition)
    # Current R DESeq2 defaults, made explicit where PyDESeq2 has matching options.
    # Cook's replacement requires seven replicates; results() retains its default
    # Cook's cutoff. No LFC shrinkage or thresholded-null hypothesis test is used.
    dds <- DESeq(dds, test = "Wald", fitType = "parametric", sfType = "ratio",
                 betaPrior = FALSE, minReplicatesForReplace = 7L, useT = FALSE,
                 minmu = 0.5, parallel = FALSE, quiet = FALSE)
    res <- results(dds, contrast = c("condition", "tumor", "normal"),
                   alpha = 0.05, independentFiltering = TRUE, parallel = FALSE)
    export_results <- function(result, path) {
        tab <- as.data.frame(result)
        tab$significant <- !is.na(tab$padj) & tab$padj < 0.05 & abs(tab$log2FoldChange) >= 1
        write.table(data.frame(gene_id = rownames(tab), tab, check.names = FALSE), path,
                    sep = "\t", quote = FALSE, row.names = FALSE, na = "NA")
    }
    export_results(res, file.path(out, "results.tsv"))
    # A labeled secondary diagnostic disentangles missingness/filtering from the
    # fitted model. It does not replace the default-filter reference above.
    res_unfiltered <- results(dds, contrast = c("condition", "tumor", "normal"),
                              alpha = 0.05, independentFiltering = FALSE,
                              cooksCutoff = FALSE, parallel = FALSE)
    export_results(res_unfiltered, file.path(out, "results_without_filtering.tsv"))
    gene_diagnostics <- as.data.frame(mcols(dds))
    write.table(data.frame(gene_id = rownames(dds), gene_diagnostics, check.names = FALSE),
                file.path(out, "gene_diagnostics.tsv"), sep = "\t", quote = FALSE,
                row.names = FALSE, na = "NA")
    write.table(data.frame(sample = colnames(dds), size_factor = sizeFactors(dds)),
                file.path(out, "size_factors.tsv"), sep = "\t", quote = FALSE, row.names = FALSE)
    saveRDS(dds, file.path(out, "dds.rds"), compress = "gzip")
    saveRDS(res, file.path(out, "results.rds"), compress = "gzip")
    writeLines(capture.output(sessionInfo()), file.path(out, "session-info.txt"))
    settings <- list(
        design = "~ case_barcode + condition", contrast = c("condition", "tumor", "normal"),
        low_count_filter = "count >= 10 in >= 3 samples", test = "Wald",
        fit_type_requested = "parametric", size_factor_type = "ratio", beta_prior = FALSE,
        min_replicates_for_replace = 7L, use_t = FALSE, min_mu = 0.5,
        alpha = 0.05, independent_filtering = TRUE, cooks_cutoff = "DESeq2 default",
        parallel = FALSE, workers = 1L, significance = "padj < .05 AND abs(log2FoldChange) >= 1"
    )
    metadata <- list(
        schema = "bindsight-r-deseq2-reference/1", purpose = "Independent implementation comparison; not biological ground truth",
        started_at = format(started, tz = "UTC", usetz = TRUE),
        elapsed_seconds = as.numeric(difftime(Sys.time(), started, units = "secs")),
        R = R.version.string, DESeq2 = as.character(packageVersion("DESeq2")),
        Bioconductor = as.character(packageVersion("BiocVersion")),
        inputs_md5 = setNames(as.list(tools::md5sum(c(counts_path, design_path))),
                              c(basename(counts_path), basename(design_path))),
        settings = settings, n_input_genes = n_input, n_tested_genes = nrow(dds),
        n_samples = ncol(dds), design_rank = qr(model)$rank,
        residual_df = nrow(model) - qr(model)$rank, sample_order = colnames(dds),
        result_names = resultsNames(dds),
        n_significant = sum(!is.na(res$padj) & res$padj < .05 & abs(res$log2FoldChange) >= 1),
        n_missing_p = sum(is.na(res$pvalue)), n_missing_padj = sum(is.na(res$padj)),
        beta_not_converged = if ("betaConv" %in% colnames(gene_diagnostics)) sum(!gene_diagnostics$betaConv, na.rm = TRUE) else NA_integer_,
        dispersion_function = attributes(dispersionFunction(dds)),
        independent_filter_metadata = metadata(res), warnings = warnings_seen,
        library_paths = .libPaths(),
        thread_environment = as.list(Sys.getenv(c("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")))
    )
    jsonlite::write_json(metadata, file.path(out, "metadata.json"), pretty = TRUE,
                         auto_unbox = TRUE, digits = NA, na = "null")
    cat("Reference complete:", out, "\n")
    cat("Tested:", nrow(dds), "Significant:", metadata$n_significant, "\n")
}, warning = function(w) {
    warnings_seen <<- c(warnings_seen, conditionMessage(w))
    message("Recorded warning: ", conditionMessage(w))
    invokeRestart("muffleWarning")
})

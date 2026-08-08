# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""pydeseq2 wrapper.

Wraps `pydeseq2 <https://github.com/owkin/PyDESeq2>`_ (MIT) so the rest of
the pipeline gets a clean, Pydantic-validated DEG result regardless of which
backend ran.

.. note::
   pydeseq2 is **not bit-equivalent** to R's DESeq2. Numeric results agree to
   within machine precision for default settings on the supported test
   matrices, but any user expecting cross-paper-equivalent statistics should
   use the optional R-bridge runner. See LICENSING.md for the GPL caveat.

Output schema (Parquet):

==========  =========  ==========================================================
column      dtype      meaning
==========  =========  ==========================================================
gene_id     str        feature ID as it appears in the counts matrix index
log2fc      float64    log2 fold-change for the configured contrast
lfc_se      float64    standard error of log2fc
stat        float64    Wald statistic
pvalue      float64    raw p-value
padj        float64    FDR-adjusted p-value (Benjamini-Hochberg)
baseMean    float64    mean of normalized counts across all samples
contrast    str        e.g. ``condition__tumor_vs_normal``
significant bool       padj < params.fdr_threshold AND |log2fc| ≥ log2fc_threshold
==========  =========  ==========================================================
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from bindsight.config import DEGParams

LOG = logging.getLogger(__name__)


class PyDESeq2Runner:
    """Run pydeseq2 against a counts matrix + sample design."""

    name = "pydeseq2"

    def __init__(self, params: DEGParams) -> None:
        self.params = params

    # ------------------------------------------------------------------ #
    # I/O                                                                #
    # ------------------------------------------------------------------ #
    @staticmethod
    def load_counts(path: Path) -> pd.DataFrame:
        """Read a counts TSV (gene × sample, integer counts)."""
        return pd.read_csv(
            path,
            sep="\t",
            index_col=0,
            compression="infer",
        )

    @staticmethod
    def load_design(path: Path) -> pd.DataFrame:
        """Read a sample design TSV. The first column must be the sample ID."""
        return pd.read_csv(path, sep="\t", index_col=0)

    # ------------------------------------------------------------------ #
    # Validation                                                         #
    # ------------------------------------------------------------------ #
    @staticmethod
    def _require_integer_counts(counts: pd.DataFrame) -> None:
        """Reject a counts matrix holding non-integer values.

        DESeq2's negative-binomial model is defined on raw counts. A TPM/FPKM/
        normalised matrix silently truncates toward zero on the integer cast
        (0.7 → 0, 3.9 → 3), after which the test still returns confident
        p-values that mean nothing. Integral floats (``5.0``) are accepted —
        count matrices routinely round-trip through float dtypes. Non-finite
        values are left to the cast, which rejects them on its own.

        Args:
            counts: Gene × sample matrix as read from disk.

        Raises:
            ValueError: If any value is finite but not integral, naming a few
                offending gene/sample cells.
        """
        values = np.asarray(counts.to_numpy(), dtype=np.float64)
        non_integer = np.isfinite(values) & (values != np.trunc(values))
        if not bool(non_integer.any()):
            return
        rows, cols = np.nonzero(non_integer)
        examples = ", ".join(
            f"{counts.index[i]}/{counts.columns[j]}={values[i, j]:g}"
            for i, j in zip(rows[:3], cols[:3], strict=True)
        )
        raise ValueError(
            "counts matrix contains non-integer values — DESeq2 requires raw integer "
            "counts, not TPM/FPKM/normalised expression; "
            f"{int(non_integer.sum())} of {values.size} values are non-integer "
            f"(e.g. {examples})"
        )

    def _require_replicated_contrast_levels(self, design: pd.DataFrame) -> None:
        """Reject a design whose contrast levels are not both replicated.

        The total-sample check upstream is blind to how the samples split: a
        5-tumour / 1-normal cohort clears ``2 * min_replicates`` yet leaves
        DESeq2 estimating a within-group dispersion from a single sample.

        Args:
            design: Sample design restricted to the samples actually analysed.

        Raises:
            ValueError: If the contrast factor is absent, or either contrast
                level has fewer than ``min_replicates`` samples.
        """
        factor, numerator, denominator = self.params.contrast
        if factor not in design.columns:
            raise ValueError(
                f"contrast factor {factor!r} is not a column of the design "
                f"(columns: {sorted(map(str, design.columns))})"
            )
        per_level = design[factor].astype(str).value_counts()
        for level in (numerator, denominator):
            n_level = int(per_level.get(level, 0))
            if n_level < self.params.min_replicates:
                raise ValueError(
                    f"contrast level {factor}={level!r} has {n_level} sample(s); "
                    f"need at least min_replicates={self.params.min_replicates} per level "
                    "for a valid dispersion estimate"
                )

    # ------------------------------------------------------------------ #
    # Filtering                                                          #
    # ------------------------------------------------------------------ #
    def _low_count_filter(self, counts: pd.DataFrame) -> pd.DataFrame:
        """Drop genes with fewer than ``min_count`` counts in ``min_replicates`` samples."""
        keep = (counts >= self.params.min_count).sum(axis=1) >= self.params.min_replicates
        n_dropped = int((~keep).sum())
        if n_dropped:
            LOG.info(
                "low-count filter: dropping %d / %d genes (min_count=%d, min_replicates=%d)",
                n_dropped,
                len(counts),
                self.params.min_count,
                self.params.min_replicates,
            )
        return counts.loc[keep]

    # ------------------------------------------------------------------ #
    # Run                                                                #
    # ------------------------------------------------------------------ #
    def run(
        self,
        counts_path: Path,
        design_path: Path,
        out_path: Path,
    ) -> dict[str, Any]:
        """Run pydeseq2 and write the DEG table as Parquet to ``out_path``.

        Returns a metrics dict suitable for embedding in the manifest's
        ``params``/``notes`` field.
        """
        counts = self.load_counts(counts_path)
        design = self.load_design(design_path)

        # Sanity-check sample alignment.
        common = counts.columns.intersection(design.index)
        missing_in_design = set(counts.columns) - set(common)
        missing_in_counts = set(design.index) - set(common)
        if missing_in_design:
            LOG.warning("samples in counts but not design: %s", sorted(missing_in_design))
        if missing_in_counts:
            LOG.warning("samples in design but not counts: %s", sorted(missing_in_counts))
        if len(common) < 2 * self.params.min_replicates:
            raise ValueError(
                f"only {len(common)} samples in common between counts and design; "
                f"need at least {2 * self.params.min_replicates}"
            )

        counts = counts[common]
        design = design.loc[common]

        self._require_integer_counts(counts)
        self._require_replicated_contrast_levels(design)

        # Filter low-count genes BEFORE pydeseq2 (faster + more stable estimates).
        counts = self._low_count_filter(counts)

        results_df = self._run_pydeseq2(counts, design)
        results_df = self._postprocess(results_df)

        out_path.parent.mkdir(parents=True, exist_ok=True)
        results_df.to_parquet(out_path, index=False)

        n_sig = int(results_df["significant"].sum())
        LOG.info(
            "wrote %s: %d genes tested, %d significant (FDR<%g, |log2fc|≥%g)",
            out_path,
            len(results_df),
            n_sig,
            self.params.fdr_threshold,
            self.params.log2fc_threshold,
        )
        return {
            "n_samples": len(common),
            "n_genes_tested": len(results_df),
            "n_significant": n_sig,
            "fdr_threshold": self.params.fdr_threshold,
            "log2fc_threshold": self.params.log2fc_threshold,
        }

    # ------------------------------------------------------------------ #
    # pydeseq2 invocation (split out so tests can mock it)               #
    # ------------------------------------------------------------------ #
    def _run_pydeseq2(self, counts: pd.DataFrame, design: pd.DataFrame) -> pd.DataFrame:
        """Invoke pydeseq2; returns the raw results_df keyed by gene ID."""
        # Lazy-import so the module loads cleanly even if pydeseq2 isn't installed.
        from pydeseq2.dds import DeseqDataSet
        from pydeseq2.default_inference import DefaultInference
        from pydeseq2.ds import DeseqStats

        # pydeseq2 wants samples × genes (rows = samples).
        counts_t = counts.T.astype(int)
        dds = DeseqDataSet(
            counts=counts_t,
            metadata=design,
            design=self.params.design_formula,
            refit_cooks=True,
            inference=DefaultInference(),
            quiet=True,
        )
        dds.deseq2()

        # alpha drives pydeseq2's independent filtering, so it must be the FDR the
        # user configured — otherwise the filter is tuned for a threshold nobody asked for.
        ds = DeseqStats(
            dds,
            contrast=self.params.contrast,
            alpha=self.params.fdr_threshold,
            quiet=True,
        )
        ds.summary()
        return ds.results_df

    # ------------------------------------------------------------------ #
    # Postprocess: standardise column names + add ``significant``        #
    # ------------------------------------------------------------------ #
    def _postprocess(self, df: pd.DataFrame) -> pd.DataFrame:
        # pydeseq2's columns: log2FoldChange, lfcSE, stat, pvalue, padj, baseMean
        out = df.rename(
            columns={
                "log2FoldChange": "log2fc",
                "lfcSE": "lfc_se",
            }
        )
        out = out.reset_index().rename(columns={"index": "gene_id"})
        contrast_label = (
            f"{self.params.contrast[0]}__{self.params.contrast[1]}_vs_{self.params.contrast[2]}"
        )
        out["contrast"] = contrast_label
        out["significant"] = (out["padj"].fillna(1.0) < self.params.fdr_threshold) & (
            out["log2fc"].abs() >= self.params.log2fc_threshold
        )
        cols = [
            "gene_id",
            "log2fc",
            "lfc_se",
            "stat",
            "pvalue",
            "padj",
            "baseMean",
            "contrast",
            "significant",
        ]
        return out[cols]

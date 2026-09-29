# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""pydeseq2 wrapper.

Wraps `pydeseq2 <https://github.com/scverse/PyDESeq2>`_ (MIT) so the rest of
the pipeline gets a clean, Pydantic-validated DEG result regardless of which
backend ran.

.. note::
   PyDESeq2 is a separate implementation of the DESeq2 method. This repository
   does not establish numerical equivalence to R's DESeq2 and does not ship an
   R-bridge runner. Cross-implementation comparisons require a separately
   specified R workflow, matched versions, inputs, design and filtering settings.

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

import hashlib
import logging
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from bindsight.config import DEGParams

LOG = logging.getLogger(__name__)
INPUT_ORDERING_POLICY = "modeled-covariates-and-complete-counts-v1"


class PyDESeq2Runner:
    """Run pydeseq2 against a counts matrix + sample design."""

    name = "pydeseq2"

    def __init__(self, params: DEGParams) -> None:
        self.params = params
        self.fit_diagnostics: dict[str, Any] = {}

    # ------------------------------------------------------------------ #
    # I/O                                                                #
    # ------------------------------------------------------------------ #
    @staticmethod
    def _require_unique_header(path: Path, table: str) -> None:
        """Reject ambiguous raw headings before pandas can rename duplicates."""
        header = (
            pd.read_csv(
                path,
                sep="\t",
                header=None,
                nrows=1,
                dtype=str,
                keep_default_na=False,
                compression="infer",
            )
            .iloc[0]
            .tolist()
        )
        # An empty first heading is conventional for an unnamed dataframe
        # index; the actual row IDs are checked separately after reading.
        if len(header) < 2 or any(not value.strip() for value in header[1:]):
            raise ValueError(f"{table} table needs nonblank sample/factor column names")
        if len(set(header)) != len(header):
            raise ValueError(f"{table} table contains duplicate column names in its raw header")

    @staticmethod
    def _require_unique_ids(identifiers: pd.Index, label: str) -> None:
        """Require unambiguous row identities before alignment or filtering."""
        if identifiers.isna().any() or any(not str(value).strip() for value in identifiers):
            raise ValueError(f"{label} must be nonblank")
        if not identifiers.is_unique:
            examples = identifiers[identifiers.duplicated()].unique().tolist()[:3]
            raise ValueError(f"{label} must be unique; duplicate IDs: {examples}")

    @staticmethod
    def load_counts(path: Path) -> pd.DataFrame:
        """Read a counts TSV (gene × sample, integer counts)."""
        PyDESeq2Runner._require_unique_header(path, "Counts")
        counts = pd.read_csv(
            path,
            sep="\t",
            index_col=0,
            dtype={0: str},
            keep_default_na=False,
            compression="infer",
        )
        PyDESeq2Runner._require_unique_ids(counts.index, "Counts gene IDs")
        PyDESeq2Runner._require_unique_ids(counts.columns, "Counts sample IDs")
        return counts

    @staticmethod
    def load_design(path: Path, categorical_factors: list[str] | None = None) -> pd.DataFrame:
        """Read a sample design TSV. The first column must be the sample ID."""
        PyDESeq2Runner._require_unique_header(path, "Design")
        literal: dict[str | int, type[str]] = {0: str}
        literal.update({name: str for name in categorical_factors or []})
        design = pd.read_csv(path, sep="\t", index_col=0, dtype=literal, keep_default_na=False)
        PyDESeq2Runner._require_unique_ids(design.index, "Design sample IDs")
        for name in categorical_factors or []:
            if name not in design:
                raise ValueError(f"Categorical factor {name!r} is absent from the design table")
            design[name] = pd.Categorical(design[name])
        return design

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

    def _canonical_input_order(
        self, counts: pd.DataFrame, design: pd.DataFrame
    ) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
        """Order identical observations independently of sample identifiers.

        This is a reproducibility policy, not evidence of backend row-order
        stability. Covariate values referenced by the formula come first; the
        complete retained count column breaks ties. Hash collisions are resolved
        by the complete bytes, so sample names never select an estimator order.
        Identical keys represent identical modeled observations and may tie.
        """
        from formulaic import Formula  # type: ignore[import-untyped]

        modeled = sorted(map(str, Formula(self.params.design_formula).required_variables))
        missing = set(modeled) - set(design.columns)
        if missing:
            raise ValueError(f"Modeled covariates absent from design table: {sorted(missing)}")
        counts = counts.sort_index()
        # Match the integer numerical input, including integral float files;
        # fix endianness so the fingerprint is portable across platforms.
        integer_counts = counts.astype(np.dtype("<i8"))
        keys = []
        for sample in counts.columns:
            covariates = tuple(
                (type(design.loc[sample, column]).__name__, str(design.loc[sample, column]))
                for column in modeled
            )
            count_bytes = integer_counts[sample].to_numpy(dtype="<i8").tobytes()
            keys.append((covariates, hashlib.sha256(count_bytes).digest(), count_bytes))
        positions = sorted(range(len(keys)), key=keys.__getitem__)
        counts = counts.iloc[:, positions]
        design = design.loc[counts.columns]
        diagnostics = {
            "policy": INPUT_ORDERING_POLICY,
            "modeled_covariates": modeled,
            "gene_order": "gene identifier ascending",
            "count_fingerprint": "SHA256 of complete filtered count column as little-endian int64",
            "collision_tiebreak": "complete count-column bytes",
            "sample_identifiers_used": False,
            "limitation": (
                "Identical numerical input under sample renaming is enforced by construction; "
                "this does not establish backend row-order stability, covariate-label "
                "invariance, R equivalence, or biological validity."
            ),
        }
        return counts, design, diagnostics

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
        design = self.load_design(design_path, self.params.categorical_factors)

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

        counts = counts.loc[:, common]
        design = design.loc[common]

        self._require_integer_counts(counts)
        self._require_replicated_contrast_levels(design)

        # Filter low-count genes BEFORE pydeseq2 (faster + more stable estimates).
        counts = self._low_count_filter(counts)

        # Real paired-cohort audits exposed backend order sensitivity. Fix the
        # wrapper's representation independently of arbitrary sample names,
        # without changing values, sample pairing, or fitting objectives.
        counts, design, ordering = self._canonical_input_order(counts, design)

        results_df = self._run_pydeseq2(counts, design)
        self.fit_diagnostics["input_ordering"] = ordering
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
            "n_cpus": self.params.n_cpus,
            "fit_diagnostics": self.fit_diagnostics,
        }

    # ------------------------------------------------------------------ #
    # pydeseq2 invocation (split out so tests can mock it)               #
    # ------------------------------------------------------------------ #
    def _run_pydeseq2(self, counts: pd.DataFrame, design: pd.DataFrame) -> pd.DataFrame:
        """Invoke pydeseq2; returns the raw results_df keyed by gene ID."""
        # Lazy-import so the module loads cleanly even if pydeseq2 isn't installed.
        from pydeseq2.dds import DeseqDataSet
        from pydeseq2.ds import DeseqStats

        from bindsight.deg.inference import (
            DEFAULT_MIN_MU,
            INFERENCE_ADAPTER_REVISION,
            RegularizedInference,
        )

        # pydeseq2 wants samples × genes (rows = samples).
        counts_t = counts.T.astype(int)
        inference = RegularizedInference(n_cpus=self.params.n_cpus, min_mu=DEFAULT_MIN_MU)
        dds = DeseqDataSet(
            counts=counts_t,
            metadata=design,
            design=self.params.design_formula,
            refit_cooks=True,
            min_mu=DEFAULT_MIN_MU,
            # n_cpus=None lets pydeseq2 use every core, which is correct on a
            # server and hostile on a laptop running a multi-hour cohort sweep.
            inference=inference,
            quiet=True,
        )
        dds.deseq2()

        self.fit_diagnostics = {
            "inference_adapter": INFERENCE_ADAPTER_REVISION,
            "minimum_fitted_mean": DEFAULT_MIN_MU,
            "dispersion_fallback_repairs": getattr(inference, "dispersion_fallback_repairs", []),
            "convergence": {},
        }
        if "design_matrix" in getattr(dds, "obsm", {}):
            matrix = np.asarray(dds.obsm["design_matrix"], dtype=float)
            rank = int(np.linalg.matrix_rank(matrix))
            self.fit_diagnostics["design_rank"] = rank
            self.fit_diagnostics["residual_degrees_of_freedom"] = int(matrix.shape[0] - rank)
        variables = getattr(dds, "var", pd.DataFrame())
        for name in ["_genewise_converged", "_MAP_converged", "_LFC_converged"]:
            if name in variables:
                values = variables[name]
                self.fit_diagnostics["convergence"][name] = {
                    "not_converged": int(values.eq(False).sum()),
                    "unreported": int(values.isna().sum()),
                }

        # alpha drives pydeseq2's independent filtering, so it must be the FDR the
        # user configured — otherwise the filter is tuned for a threshold nobody asked for.
        stats_inference = RegularizedInference(n_cpus=self.params.n_cpus, min_mu=DEFAULT_MIN_MU)
        ds = DeseqStats(
            dds,
            contrast=self.params.contrast,
            alpha=self.params.fdr_threshold,
            inference=stats_inference,
            quiet=True,
        )
        ds.summary()
        self.fit_diagnostics["mean_floor_applications"] = getattr(
            inference, "mean_floor_applications", []
        ) + getattr(stats_inference, "mean_floor_applications", [])
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

"""pydeseq2 wrapper.

Wraps `pydeseq2 <https://github.com/owkin/PyDESeq2>`_ (MIT) so the rest of
the pipeline gets a clean, Pydantic-validated DEG result regardless of which
backend ran.

.. note::
   pydeseq2 is **not bit-equivalent** to R's DESeq2. Numeric results agree to
   within machine precision for default settings on the supported test
   matrices, but any user expecting cross-paper-equivalent statistics should
   use the optional R-bridge runner. See LICENSING.md for the GPL caveat.

This module is a stub in v0.0.x. The real implementation will:

1. Read counts (TSV/Parquet) and design (TSV) into ``pandas.DataFrame``.
2. Build a ``pydeseq2.dds.DeseqDataSet``.
3. Run ``DeseqStats`` for the configured contrast.
4. Emit a Parquet with columns:
   ``gene_id, symbol, log2fc, lfc_se, stat, pvalue, padj, baseMean, contrast``.
5. Append a :class:`xpr2bind.provenance.StageRecord` to the manifest.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class DEGParams(BaseModel):
    """User-facing DEG parameters."""

    model_config = ConfigDict(extra="forbid")

    design_formula: str = Field(
        ..., description="Design formula in patsy form, e.g. '~ condition'."
    )
    contrast: list[str] = Field(
        ..., description="Three-element list e.g. ['condition', 'tumor', 'normal']."
    )
    fdr_threshold: float = Field(0.05, ge=0.0, le=1.0)
    log2fc_threshold: float = Field(1.0, ge=0.0)
    min_replicates: int = Field(3, ge=2)


class PyDESeq2Runner:
    """Stub for the pydeseq2 backend. Real implementation lands in v0.0.x."""

    def __init__(self, params: DEGParams) -> None:
        self.params = params

    def run(
        self,
        counts_path: Path,
        design_path: Path,
        out_path: Path,
    ) -> dict[str, Any]:
        """Run pydeseq2 and write the DEG table to ``out_path``.

        Returns a metrics dict (e.g. ``{'n_genes_tested': N, 'n_significant': K}``)
        that will be embedded in the manifest's ``params``.
        """
        raise NotImplementedError(
            "PyDESeq2Runner.run will land in v0.0.2. See ARCHITECTURE.md § 11 (Phased roadmap)."
        )

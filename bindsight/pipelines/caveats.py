# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""User-facing scientific caveats for the discovery half.

Single source of truth so the pipeline logs, the run manifest, and the HTML
report all state the *same* limitations in the same words. Kept dependency-free
(stdlib only) so the report renderer can import it without pulling in the heavy
discovery module — the same reason the disposition list is duplicated in
``bindsight.report.html``.

These are inherent limits of expression-based discovery, not bugs: bindsight
surfaces them rather than hiding them, consistent with its failure-honest design.
"""

from __future__ import annotations

# Each entry is (title, body). Rendered as a "Limitations" section in the HTML
# report, logged at WARNING when discovery runs, and summarised into the run
# manifest's discover-stage notes.
DISCOVERY_LIMITATIONS: tuple[tuple[str, str], ...] = (
    (
        "mRNA abundance is not cell-surface protein abundance",
        "Discovery ranks candidates from RNA-seq transcript abundance and a curated "
        "surfaceome (SURFY). SURFY establishes that a protein *can* reach the cell "
        "surface; it does not measure how much protein is actually there. Transcript "
        "level is an imperfect proxy for surface-protein abundance — translation rate, "
        "membrane trafficking and ectodomain shedding all intervene. Treat surfaced "
        "candidates as hypotheses to confirm at the protein level (e.g. flow cytometry, "
        "immunohistochemistry, or the Human Protein Atlas) before committing design effort.",
    ),
    (
        "Bulk expression can originate from non-tumour cells",
        "Bulk tumour-vs-normal differential expression cannot tell whether a transcript "
        "comes from tumour cells or from infiltrating immune and stromal cells. High "
        "apparent over-expression can reflect tumour-purity / cell-composition "
        "differences between the tumour and normal samples rather than a tumour-intrinsic "
        "target. Single-cell or deconvolution evidence is needed to establish "
        "tumour-cell-intrinsic expression (planned for v1.0).",
    ),
)


def caveat_titles() -> tuple[str, ...]:
    """Return just the short titles, for logging."""
    return tuple(title for title, _ in DISCOVERY_LIMITATIONS)


def caveat_summary() -> str:
    """One-line marker for the manifest discover-stage notes."""
    return "caveats: " + "; ".join(caveat_titles()) + " (see report Limitations)"

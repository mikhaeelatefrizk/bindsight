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

They are also worded for *any* two-condition contrast, because they are stamped
into every run manifest and every report. One of them used to be written purely
in tumour vocabulary, so a drug-versus-vehicle experiment came back carrying a
note about tumour purity — a limitation that is real and general, described in a
domain the run was not in.
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
        "Bulk expression cannot attribute a transcript to a cell type",
        "A bulk contrast measures the average over whatever cells each sample "
        "contained. It cannot tell whether a transcript rose because the cells of "
        "interest express more of it, or because the two arms hold different "
        "mixtures of cells. Apparent over-expression can therefore reflect "
        "composition rather than biology: in a tumour-versus-normal contrast that "
        "is tumour purity and immune or stromal infiltration; in a treated-versus-"
        "untreated contrast it is a shift in which cells survived or proliferated; "
        "between two tissues it is simply that they are made of different cells. "
        "Single-cell data or deconvolution is what establishes cell-intrinsic "
        "expression, and neither is implemented (planned for v1.0).",
    ),
)


def caveat_titles() -> tuple[str, ...]:
    """Return just the short titles, for logging."""
    return tuple(title for title, _ in DISCOVERY_LIMITATIONS)


def caveat_summary() -> str:
    """One-line marker for the manifest discover-stage notes."""
    return "caveats: " + "; ".join(caveat_titles()) + " (see report Limitations)"

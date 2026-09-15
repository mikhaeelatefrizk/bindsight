# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shared brand constants and CSS for every bindsight presentation surface.

Before this module the brand navy, the page title, and the page icon were
re-declared independently in the app and the report
and ``report/templates/report.css``, and the docs site used an unrelated teal.
Three surfaces of one product drifted apart.

This is the single source of truth, in the same spirit as
:mod:`bindsight.pipelines.caveats` — which already shares one limitations list
between the pipeline logs, the manifest, and the HTML report.

The module deliberately imports nothing beyond the standard library so it stays
importable without the web extra (see ``tests/test_package_imports.py``).
"""

from __future__ import annotations

from typing import Literal

# --- Identity --------------------------------------------------------------

PAGE_TITLE = "bindsight"
PAGE_ICON = "🧬"
#: Literal, not a bare str: st.set_page_config types this parameter as
#: Literal["centered", "wide"], so a plain str fails strict type checking.
PAGE_LAYOUT: Literal["centered", "wide"] = "wide"

TAGLINE = (
    "RNA-seq counts → ranked de novo protein binder candidates, "
    "with full provenance back to the patient cohort."
)

# --- Palette ---------------------------------------------------------------
# The navy is the established brand colour (report.css and the web interface
# already used it); everything else is derived from it.

NAVY = "#0b5394"
NAVY_DARK = "#083b6b"
NAVY_TINT = "#e8f0fb"
ACCENT = "#0f9d8f"

INK = "#1b1f24"
MUTED = "#6c757d"
RULE = "#e3e6ea"
SURFACE = "#ffffff"
CANVAS = "#f7f9fc"

OK = "#2e7d32"
OK_TINT = "#e8f5e9"
WARN = "#b08400"
WARN_TINT = "#fff8e1"
ERR = "#c62828"
ERR_TINT = "#ffebee"

# --- Canonical URLs --------------------------------------------------------
# These were previously hardcoded (and in the About page, pointed at raw GitHub
# blob URLs rather than the deployed documentation site).

GITHUB_URL = "https://github.com/mikhaeelatefrizk/bindsight"
DOCS_URL = "https://mikhaeelatefrizk.github.io/bindsight/"
HF_SPACE_URL = "https://huggingface.co/spaces/Mikhaeelatefrizk/bindsight"
# The concept DOI, which always resolves to the latest release; a version DOI
# would pin readers to whichever release happened to be current when this was
# written.
ZENODO_DOI = "10.5281/zenodo.PENDING"
ZENODO_DOI_URL = f"https://doi.org/{ZENODO_DOI}"

#: Whether the DOI above is still the shipped placeholder. The repository ships
#: a deliberately invalid identifier until the first Zenodo deposit, and
#: ``scripts/set_doi.py`` replaces it -- but the app rendered it as a live link
#: behind a button labelled "Cite", so the one thing a reader is most likely to
#: click during a demonstration resolved to a 404.
DOI_IS_PENDING = ZENODO_DOI.endswith("PENDING")


def citation_line() -> str:
    """How to cite, or an honest statement that the DOI does not exist yet."""
    if DOI_IS_PENDING:
        return (
            "DOI pending — assigned at the first Zenodo deposit. "
            "Cite the repository and its version in the meantime."
        )
    return f"[{ZENODO_DOI}]({ZENODO_DOI_URL})"


LICENSE_NAME = "AGPL-3.0-or-later"


# --- Plain-language framing ------------------------------------------------
# A one-paragraph, jargon-free description for a non-specialist visitor. Kept
# here so the web app and the docs site tell the same story. This is the
# on-ramp; the technical framing (TAGLINE) sits directly beneath it.
PLAIN_SUMMARY = (
    "In plain terms: bindsight reads a tumour's gene-activity data and looks for "
    "proteins that stud the surface of cancer cells but not healthy ones. It then "
    "designs small custom proteins — molecular “keys” — shaped to latch onto those "
    "targets, checks each design with an AI structure model to see whether it would "
    "actually stick, ranks the best candidates, and keeps a complete record of how "
    "it reached every answer."
)

#: Plain-English glossary of the core terms the app and docs use. Single source
#: of truth: the web app's Glossary page renders this, and
#: ``scripts/build_docs_results.py`` regenerates ``docs/glossary.md`` from it, so
#: the two can never drift. Each entry is ``(term, plain-language definition)``.
GLOSSARY: tuple[tuple[str, str], ...] = (
    (
        "RNA-seq",
        "A lab method that measures which genes are switched on in a tissue sample, "
        "and how strongly, by sequencing its RNA. It is the starting input to bindsight.",
    ),
    (
        "Differential expression (DEG)",
        "Comparing gene activity between two groups — here tumour versus healthy "
        "tissue — to find the genes turned notably up or down in disease.",
    ),
    (
        "log2 fold-change (log2FC)",
        "How many times higher or lower a gene's activity is between the two groups, "
        "on a log2 scale: a value of 4 means about 16× higher in tumour.",
    ),
    (
        "padj / FDR",
        "A confidence figure that a difference is real rather than chance, adjusted "
        "for testing thousands of genes at once. Smaller is stronger (e.g. 1e-59 is "
        "overwhelming evidence).",
    ),
    (
        "Antigen",
        "A molecule a drug or the immune system can recognise and target. In bindsight "
        "the antigens of interest are proteins sitting on the cell surface.",
    ),
    (
        "Surfaceome",
        "The full set of proteins that sit on the outer surface of cells — the ones a "
        "binder could physically reach. bindsight keeps only surface proteins as targets.",
    ),
    (
        "De novo protein binder",
        "A small protein designed from scratch (rather than borrowed from nature) to "
        "stick tightly and specifically to a chosen target protein.",
    ),
    (
        "RFdiffusion + ProteinMPNN",
        "Two AI models used together: RFdiffusion invents a plausible 3-D shape for a "
        "binder against the target, and ProteinMPNN chooses an amino-acid sequence that "
        "would fold into that shape.",
    ),
    (
        "Boltz-2",
        "An AI model that predicts the 3-D structure of the binder and target locked "
        "together, and reports how confident it is in that predicted interface. "
        "Confidence is not a binding measurement: bindsight's own paired control "
        "folded each design beside a shuffle of its own sequence, and the shuffles "
        "scored as well. Treat these numbers as a filter to triage wet-lab work, "
        "never as evidence that a design binds.",
    ),
    (
        "ipTM",
        "A 0–1 score of how confident the structure model is in the predicted "
        "interface between two proteins. 0.65 is the threshold the de novo design "
        "literature commonly uses, and bindsight reports against it for "
        "comparability — but its own scramble control could not separate real "
        "designs from shuffles of the same composition at that cutoff, so a value "
        "above 0.65 is not on its own evidence of a binder. See the calibration.",
    ),
    (
        "PAE (interaction)",
        "Predicted Aligned Error at the binding interface, in ångströms — how uncertain "
        "the model is about the contact. Lower means a more trustworthy predicted grip.",
    ),
    (
        "Developability",
        "How practical a designed protein would be to actually make and use: is it "
        "stable, soluble, and free of trouble-prone residues? Good scores mean fewer "
        "surprises in the lab.",
    ),
    (
        "Provenance / RO-Crate",
        "A complete, machine-readable record of every input, tool version and step, "
        "packaged (as an RO-Crate) so anyone can retrace and reproduce a result — and "
        "cite it.",
    ),
    (
        "ERBB2 (HER2)",
        "A well-known breast-cancer cell-surface antigen and an approved drug target — "
        "the canonical positive control for a discovery pipeline. bindsight does *not* "
        "rediscover it: in the whole unstratified TCGA-BRCA cohort it measures log2fc "
        "0.92, below the fold-change floor, so it does not clear the "
        "significance rule. That is a limit of bulk differential expression, not of "
        "the ranking; see benchmarks/study/RESULTS.md.",
    ),
)


def docs_url(page: str = "") -> str:
    """Build a URL into the deployed documentation site.

    Args:
        page: Page slug without extension, e.g. ``"what-is-bindsight"``.
            Empty string returns the docs home.

    Returns:
        Absolute URL on the GitHub Pages documentation site.
    """
    if not page:
        return DOCS_URL
    return f"{DOCS_URL}{page.strip('/')}/"


# The Streamlit stylesheet lived here. It is gone with the app it styled:
# the interface is server-rendered now, and its design system is one CSS
# file under ``report/web/static/`` shared with the standalone HTML report,
# rather than a Python f-string emitting a <style> block into a widget.

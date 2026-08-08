# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shared brand constants and CSS for every bindsight presentation surface.

Before this module the brand navy, the page title, and the page icon were
re-declared independently in ``report/webapp.py``, ``report/streamlit_app.py``
and ``report/templates/report.css``, and the docs site used an unrelated teal.
Three surfaces of one product drifted apart.

This is the single source of truth, in the same spirit as
:mod:`bindsight.pipelines.caveats` — which already shares one limitations list
between the pipeline logs, the manifest, and the HTML report.

The module deliberately imports nothing beyond the standard library so it stays
importable when Streamlit is absent (see ``tests/test_package_imports.py``).
"""

from __future__ import annotations

from typing import Literal

# --- Identity --------------------------------------------------------------

PAGE_TITLE = "bindsight"
PAGE_ICON = "🧬"
#: Literal, not a bare str: st.set_page_config types this parameter as
#: Literal["centered", "wide"], so a plain str fails strict type checking.
PAGE_LAYOUT: Literal["centered", "wide"] = "wide"
#: Back-compat alias.
LAYOUT = PAGE_LAYOUT

TAGLINE = (
    "RNA-seq counts → ranked de novo protein binder candidates, "
    "with full provenance back to the patient cohort."
)

# --- Palette ---------------------------------------------------------------
# The navy is the established brand colour (report.css and the Streamlit app
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
STREAMLIT_URL = "https://bindsight.streamlit.app/"
# The concept DOI, which always resolves to the latest release; a version DOI
# would pin readers to whichever release happened to be current when this was
# written.
ZENODO_DOI_URL = "https://doi.org/10.5281/zenodo.20121495"
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
        "together, so bindsight can judge whether a design would actually bind before "
        "anyone runs a wet-lab experiment.",
    ),
    (
        "ipTM",
        "A 0–1 score of how confident the structure model is that two proteins really "
        "bind at their interface. Higher is better; roughly 0.65 and up is promising.",
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
        "A well-known breast-cancer cell-surface antigen and an approved drug target. "
        "bindsight rediscovering it from raw data, with no hint that it should, is a "
        "sanity check that the pipeline works.",
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


# --- Streamlit CSS ---------------------------------------------------------


def app_css() -> str:
    """Return the app stylesheet, including the mobile rules.

    The previous stylesheet had no media queries at all, while the module
    docstring claimed the layout worked on phones. These rules make that claim
    true: the hero scales down, KPI columns stop being crushed, and the
    embedded report iframe stops overflowing the viewport.

    Returns:
        A ``<style>`` block ready to pass to ``st.markdown``.
    """
    return f"""
    <style>
      .block-container {{ max-width: 1080px; padding-top: 2rem; }}
      h1 {{ color: {NAVY}; letter-spacing: -0.02em; }}
      h2 {{
        color: {NAVY}; border-bottom: 1px solid {RULE}; padding-bottom: .3rem;
      }}
      h3 {{ color: {NAVY_DARK}; letter-spacing: -0.01em; }}
      .stButton button[kind="primary"] {{
        background-color: {NAVY}; color: white; font-weight: 600;
      }}
      .small-muted {{ color: {MUTED}; font-size: 0.85rem; }}
      .pill {{
        display: inline-block; padding: .15rem .55rem;
        background: {NAVY_TINT}; color: {NAVY}; border-radius: 999px;
        font-size: .75rem; font-weight: 600; margin-right: .3rem;
      }}
      .ok-pill   {{ background: {OK_TINT}; color: {OK}; }}
      .warn-pill {{ background: {WARN_TINT}; color: {WARN}; }}
      .err-pill  {{ background: {ERR_TINT}; color: {ERR}; }}

      /* Hero ---------------------------------------------------------- */
      .bs-hero {{
        background: linear-gradient(135deg, {NAVY} 0%, {NAVY_DARK} 100%);
        color: #fff; border-radius: 14px;
        padding: 2rem 2.2rem; margin-bottom: 1.4rem;
      }}
      .bs-hero h1 {{
        color: #fff; margin: 0 0 .4rem 0; font-size: 2.4rem; line-height: 1.1;
      }}
      .bs-hero p {{ margin: 0; font-size: 1.05rem; opacity: .94; }}
      .bs-hero .bs-hero-sub {{ margin-top: .9rem; font-size: .92rem; opacity: .85; }}

      /* Stat strip ---------------------------------------------------- */
      .bs-stats {{
        display: grid; gap: .8rem; margin: 1rem 0 1.4rem 0;
        grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
      }}
      .bs-stat {{
        background: {CANVAS}; border: 1px solid {RULE};
        border-radius: 10px; padding: .85rem 1rem;
      }}
      .bs-stat .v {{
        font-size: 1.5rem; font-weight: 700; color: {NAVY}; line-height: 1.15;
      }}
      .bs-stat .k {{
        font-size: .76rem; color: {MUTED}; text-transform: uppercase;
        letter-spacing: .04em; margin-top: .15rem;
      }}

      /* Pipeline strip ------------------------------------------------ */
      .bs-flow {{
        display: flex; flex-wrap: wrap; gap: .45rem; align-items: stretch;
        margin: .6rem 0 1.1rem 0;
      }}
      .bs-flow .s {{
        flex: 1 1 118px; background: {NAVY_TINT}; border: 1px solid #cfe0f5;
        border-radius: 9px; padding: .55rem .6rem; font-size: .78rem;
        color: {NAVY_DARK}; font-weight: 600; text-align: center;
      }}
      .bs-flow .s small {{
        display: block; font-weight: 400; color: {MUTED};
        font-size: .69rem; margin-top: .15rem;
      }}
      .bs-flow .s.gpu {{ background: {WARN_TINT}; border-color: #f0e0a8; color: #7a5c00; }}

      /* Mobile -------------------------------------------------------- */
      @media (max-width: 640px) {{
        .block-container {{ padding-top: 1rem; padding-left: .8rem; padding-right: .8rem; }}
        .bs-hero {{ padding: 1.3rem 1.1rem; border-radius: 11px; }}
        .bs-hero h1 {{ font-size: 1.7rem; }}
        .bs-hero p {{ font-size: .95rem; }}
        .bs-stats {{ grid-template-columns: repeat(auto-fit, minmax(132px, 1fr)); }}
        .bs-stat .v {{ font-size: 1.25rem; }}
        .bs-flow .s {{ flex: 1 1 100%; }}
        iframe {{ max-width: 100%; }}
      }}
    </style>
    """

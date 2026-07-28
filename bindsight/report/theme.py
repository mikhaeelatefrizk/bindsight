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

# --- Identity --------------------------------------------------------------

PAGE_TITLE = "bindsight"
PAGE_ICON = "🧬"
LAYOUT = "wide"

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
ZENODO_DOI_URL = "https://doi.org/10.5281/zenodo.20121496"
LICENSE_NAME = "AGPL-3.0-or-later"


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

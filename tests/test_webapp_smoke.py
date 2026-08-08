# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""End-to-end smoke tests for the Streamlit web app.

Until now CI only asserted that ``bindsight.report.webapp`` *imports*
(``tests/test_package_imports.py``). Every page could raise on render and the
build would stay green -- which matters, because the app is the primary public
face of the project on the Hugging Face Space.

These tests drive the real app through Streamlit's ``AppTest`` harness: every
page must render without raising, navigation must work, and the published
numbers must reach the screen. ``AppTest`` ships with Streamlit itself, so no
new dependency is involved.

Nothing here touches the network: the Demo and "Run on my data" pages only
execute a pipeline on button click, and no test clicks those buttons.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("streamlit")

from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parents[1] / "streamlit_app.py"

PAGES = [
    "🏠 Home",
    "🔬 Real results",
    "✨ Demo",
    "📤 Run on my data",
    "🔎 Browse a run",
    "📖 Glossary",
    "ℹ️ About",
]


@pytest.fixture
def app() -> AppTest:
    """A booted app instance."""
    at = AppTest.from_file(str(APP), default_timeout=120)
    at.run()
    return at


def test_app_boots(app: AppTest) -> None:
    """The entry point renders without raising."""
    assert not app.exception


def test_navigation_lists_every_page(app: AppTest) -> None:
    """The sidebar exposes exactly the documented set of pages."""
    assert app.sidebar.radio[0].options == PAGES


@pytest.mark.parametrize("page", PAGES)
def test_every_page_renders(app: AppTest, page: str) -> None:
    """No page raises on render.

    The router dispatches on the emoji prefix of these labels, so this also
    guards against a label being edited without its branch.
    """
    app.sidebar.radio[0].set_value(page).run()
    assert not app.exception, f"{page} raised: {app.exception}"


def test_theme_css_is_injected(app: AppTest) -> None:
    """The shared stylesheet from report.theme reaches the page."""
    from bindsight.report import theme

    assert any(theme.NAVY in m.value for m in app.markdown)


def test_home_shows_derived_headline_numbers(app: AppTest) -> None:
    """The landing page reports the committed benchmark results."""
    rendered = " ".join(m.value for m in app.markdown)
    assert "bs-hero" in rendered
    assert "bs-flow" in rendered
    assert "ERBB2 rediscovered" in rendered
    assert "rank 4" in rendered


def test_results_page_shows_published_metrics(app: AppTest) -> None:
    """The Results page surfaces the numbers the README and paper cite."""
    app.sidebar.radio[0].set_value("🔬 Real results").run()
    assert not app.exception

    metrics = {m.label: m.value for m in app.metric}
    assert metrics["ERBB2 rank"] == "4"
    assert metrics["Designs"] == "20"
    assert metrics["Best ipTM"] == "0.84"
    assert metrics["Success @ ipTM 0.65"] == "50%"


def test_results_page_renders_a_structure(app: AppTest) -> None:
    """A real predicted complex is offered for viewing."""
    app.sidebar.radio[0].set_value("🔬 Real results").run()
    assert not app.exception
    labels = [s.label for s in app.selectbox]
    assert "Design" in labels
    design_picker = next(s for s in app.selectbox if s.label == "Design")
    assert len(design_picker.options) == 20


def test_home_cta_navigates_to_results(app: AppTest) -> None:
    """The primary call to action switches pages.

    Regression guard: Streamlit refuses assignment to a widget's own key once
    that widget exists, so the navigation buttons route through a pending key
    that ``main()`` applies before the radio is built.
    """
    app.button[0].click().run()
    assert not app.exception
    assert app.sidebar.radio[0].value == "🔬 Real results"
    assert [t.value for t in app.title] == ["Real results"]


def test_browse_page_offers_local_runs_without_a_path(app: AppTest) -> None:
    """Browse works without typing a server-side path.

    The hosted deployments give a visitor no filesystem to point at, so the
    page must degrade to a picker or an explanation rather than a dead input.
    """
    app.sidebar.radio[0].set_value("🔎 Browse a run").run()
    assert not app.exception
    assert app.text_input
    assert app.selectbox or app.info

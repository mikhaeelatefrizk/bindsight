# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Guard the generated documentation results page against drift.

``docs/results.md`` is produced by ``scripts/build_docs_results.py`` from the
committed benchmark data and is checked in so ``mkdocs serve`` works from a
fresh clone. That convenience creates a failure mode: re-run the benchmarks,
forget to regenerate, and the public site quietly keeps publishing the old
numbers.

These tests make that drift a test failure instead.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_docs_results.py"
GENERATED = ROOT / "docs" / "results.md"
FIG_DIR = ROOT / "docs" / "assets" / "figures"


@pytest.fixture(scope="module")
def builder():
    """Import the generator script as a module."""
    spec = importlib.util.spec_from_file_location("build_docs_results", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_generated_page_is_committed() -> None:
    """The page ships in the repo so a fresh clone can serve the docs."""
    assert GENERATED.is_file()
    assert "do not edit by hand" in GENERATED.read_text(encoding="utf-8")


def test_generated_page_is_up_to_date(builder) -> None:
    """docs/results.md matches what the generator produces right now.

    If this fails, run ``python scripts/build_docs_results.py`` and commit.
    """
    assert GENERATED.read_text(encoding="utf-8") == builder.build()


def test_generated_glossary_is_up_to_date(builder) -> None:
    """docs/glossary.md matches what the generator produces from theme.GLOSSARY.

    ``theme.GLOSSARY`` is the source and this is what keeps the committed file
    honest to it. If this fails, run ``python scripts/build_docs_results.py``
    and commit.

    This docstring used to say it kept the docs glossary and "the app's Glossary
    page" from drifting. The served interface has no glossary page, so there was
    never a second renderer to drift from.
    """
    glossary = ROOT / "docs" / "glossary.md"
    assert glossary.is_file()
    assert glossary.read_text(encoding="utf-8") == builder.build_glossary()


def test_glossary_covers_core_terms() -> None:
    """The published glossary defines the jargon the app leads with."""
    text = (ROOT / "docs" / "glossary.md").read_text(encoding="utf-8")
    for term in ("RNA-seq", "Surfaceome", "ipTM", "PAE", "Provenance", "ERBB2"):
        assert term in text, f"glossary missing: {term}"


def test_page_reports_the_published_numbers() -> None:
    """The public page states the same results the tests pin elsewhere.

    This asserted 0.84 and 50% under a comment calling them "the designer
    benchmark's committed figures". They are the *withdrawn* ones, from the run
    that redesigned the target chain. It never asserted the current 0.88 or
    40%, so the generator could have dropped the corrected block entirely and
    this test would still have passed — it was pinning the retraction sentence
    while claiming to pin the results.
    """
    import json

    text = GENERATED.read_text(encoding="utf-8")
    # The best-ranked antigen, always printed with the list it was ranked within.
    assert "CA9" in text
    assert "rank **1 of 291**" in text
    # The retracted circular claim must not reappear on the public page.
    assert "rank 4" not in text

    artifact = ROOT / "benchmarks" / "designer_benchmark" / "results.json"
    if not artifact.is_file():
        pytest.skip("designer benchmark artifact not present")
    arm = next(
        a
        for a in json.loads(artifact.read_text(encoding="utf-8"))["designers"]
        if a.get("n_designs")
    )
    # The current figures, read from the artifact rather than written here, so a
    # re-run that moves them fails this test instead of silently disagreeing.
    assert f"{arm['success_rate'] * 100:.0f}%" in text
    assert f"{arm['mean_iptm']:.2f}" in text
    low, high = arm["success_ci_low"], arm["success_ci_high"]
    assert f"{low * 100:.0f}–{high * 100:.0f}%" in text, (
        "the page states a success rate with no interval beside it"
    )


def test_referenced_figures_exist() -> None:
    """Every figure the page links resolves inside the docs tree.

    MkDocs only serves files beneath ``docs_dir``, so the benchmark figures are
    copied in; a missing copy is a broken image on the live site.
    """
    text = GENERATED.read_text(encoding="utf-8")
    referenced = {
        line.split("assets/figures/")[1].split(".png")[0]
        for line in text.splitlines()
        if "assets/figures/" in line
    }
    assert referenced
    for name in referenced:
        assert (FIG_DIR / f"{name}.png").is_file(), f"missing figure: {name}.png"

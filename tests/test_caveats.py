"""Tests for the discovery honesty caveats (single source of truth)."""

from __future__ import annotations

from bindsight.pipelines.caveats import (
    DISCOVERY_LIMITATIONS,
    caveat_summary,
    caveat_titles,
)


def test_limitations_are_well_formed() -> None:
    assert len(DISCOVERY_LIMITATIONS) >= 2
    for entry in DISCOVERY_LIMITATIONS:
        title, body = entry  # each is a (title, body) pair
        assert title.strip()
        assert len(body) > 40  # a real sentence, not a placeholder


def test_limitations_cover_the_two_known_confounders() -> None:
    blob = " ".join(t + " " + b for t, b in DISCOVERY_LIMITATIONS).lower()
    # mRNA != surface protein
    assert "surface" in blob
    assert "protein abundance" in blob
    # bulk purity / infiltrating cells
    assert "infiltrating" in blob or "purity" in blob


def test_caveat_summary_and_titles_consistent() -> None:
    titles = caveat_titles()
    assert len(titles) == len(DISCOVERY_LIMITATIONS)
    summary = caveat_summary()
    assert summary.startswith("caveats:")
    assert "see report Limitations" in summary
    for t in titles:
        assert t in summary

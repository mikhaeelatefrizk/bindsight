# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""JOSS names six sections and a word band, and its bot checks them before a human does.

The pre-review of the 2026-06-07 submission (openjournals/joss-reviews#10660)
ran against a `paper.md` with two of the six headings the author guide now
lists. The guide, read on 2026-09-20, requires in this order: Summary,
Statement of need, State of the field, Software design, Research impact
statement, AI usage disclosure -- and a length between 750 and 1,750 words. A
paper that drifts outside either is turned back before anyone reads it, so the
shape is pinned here. What the sections *say* is held elsewhere: every number
in the paper is pinned to its artifact by tests/test_published_numbers_match_artifacts.py
and tests/test_docs_claims.py, and the author metadata by
tests/test_author_metadata_agrees.py.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PAPER = REPO / "paper" / "paper.md"

#: The six headings JOSS's author guide requires, in the order it lists them.
REQUIRED_SECTIONS = (
    "Summary",
    "Statement of need",
    "State of the field",
    "Software design",
    "Research impact statement",
    "AI usage disclosure",
)

#: JOSS: "between 750-1750 words"; longer papers "may be asked to reduce the length".
WORD_BAND = (750, 1750)


def _split() -> tuple[str, str]:
    text = PAPER.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    assert match, "paper/paper.md does not open with a YAML front-matter block"
    return match.group(1), match.group(2)


def _level_one_headings(body: str) -> list[str]:
    return [line[2:].strip() for line in body.splitlines() if line.startswith("# ")]


def test_the_six_required_sections_are_present_in_josss_order() -> None:
    """Every required heading, as a level-one heading, in the guide's order.

    Other sections (Acknowledgements, References) may follow; none may be
    interleaved out of order, because the bot matches headings by name and a
    reviewer reads them by position.
    """
    _, body = _split()
    headings = _level_one_headings(body)
    positions = []
    for required in REQUIRED_SECTIONS:
        assert required in headings, (
            f"paper/paper.md has no `# {required}` heading; JOSS requires it. "
            f"Headings present: {headings}"
        )
        positions.append(headings.index(required))
    assert positions == sorted(positions), (
        f"the required sections are out of JOSS's order: {headings}"
    )


def test_the_body_is_inside_josss_word_band() -> None:
    """Counted after the front matter, headings included, the way a reviewer
    pasting the file into a counter would see it."""
    _, body = _split()
    words = len(body.split())
    low, high = WORD_BAND
    assert low <= words <= high, f"paper/paper.md body is {words} words; JOSS asks for {low}-{high}"


def test_the_disclosure_section_says_something() -> None:
    """A heading with nothing under it satisfies a bot and no reviewer."""
    _, body = _split()
    section = re.search(r"^# AI usage disclosure\n(.*?)(?=^# |\Z)", body, re.S | re.M)
    assert section is not None
    assert len(section.group(1).split()) >= 40, (
        "the AI usage disclosure is a heading with nothing under it"
    )


def test_every_citation_key_has_a_bibliography_entry() -> None:
    """`[@Key]` with no entry renders as a question mark in the PDF the bot builds."""
    _, body = _split()
    bib = (REPO / "paper" / "paper.bib").read_text(encoding="utf-8")
    defined = set(re.findall(r"^@\w+\{([^,\s]+),", bib, re.M))
    cited = set(re.findall(r"@([A-Za-z][\w:-]*)", body))
    missing = sorted(cited - defined)
    assert not missing, f"cited in paper.md but not in paper.bib: {missing}"

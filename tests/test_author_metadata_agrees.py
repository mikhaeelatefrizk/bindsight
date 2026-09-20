# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
r"""One author, eight files, and two ways of writing a name.

Scholarly metadata records a person twice: as a **display form** a reader sees
("Mikhaeel Atef Rizk Wahba") and as a **structured form** a machine sorts and
disambiguates on (family "Wahba", given names "Mikhaeel Atef Rizk"). Both are
correct. The defect is that nothing derived one from the other, so each file
hand-wrote whichever it needed and they stopped agreeing.

``codemeta.json`` recorded ``familyName: "Atef Rizk Wahba"`` while
``paper.bib`` wrote ``Wahba, Mikhaeel Atef Rizk`` and ``CITATION.cff`` held
``Wahba`` as the family name with the middle names in ``name-particle`` -- a
field the CFF schema reserves for "van" and "von", which citation renderers
therefore glue to the surname. Same person, two surnames: every software
indexer reading the codemeta filed this author under *A*, every bibliography
reading the bib filed them under *W*, and GitHub's "Cite this repository"
button rendered a third form. None of the three files is wrong on its face,
which is why it survived -- a defect visible only when the files are read
together, and nothing read them together.

The affiliation had the same shape: ``paper.md``, ``manuscript.tex`` and the
bioRxiv submission fields said "Independent Researcher, Cairo, Egypt" while
``CITATION.cff`` and ``codemeta.json`` said "Independent researcher". A
submission form filled from the wrong one contradicts the manuscript it is
attached to.

So the constants below are declared once and the display form is *computed*
from the structured one. A test that hand-wrote both would reproduce the defect
it exists to catch.

``CHANGELOG.md`` is deliberately not read here. It records what the metadata
used to say, and a guard that forbade the old spelling everywhere would forbid
the record of its correction.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]

#: The structured form. Everything else is derived.
FAMILY = "Wahba"
GIVEN = "Mikhaeel"
MIDDLE = "Atef Rizk"

#: The given names as a citation format wants them, and the display form,
#: both computed rather than typed.
GIVEN_NAMES = f"{GIVEN} {MIDDLE}"
FULL_NAME = f"{GIVEN_NAMES} {FAMILY}"

ORCID = "0009-0006-1069-9558"
ORCID_URL = f"https://orcid.org/{ORCID}"
AFFILIATION = "Independent Researcher, Cairo, Egypt"


def _read(rel: str) -> str:
    path = REPO / rel
    assert path.is_file(), f"{rel} is missing; this guard reads it"
    return path.read_text(encoding="utf-8")


def _front_matter(text: str) -> dict:
    """The YAML block a pandoc-style Markdown paper opens with.

    Parsed rather than regexed because the author block is nested: JOSS wants
    ``authors[].affiliation`` as an *index* into ``affiliations[]``, so reading
    the name out needs the structure, not a line.
    """
    match = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    assert match, "paper/paper.md does not open with a YAML front-matter block"
    return yaml.safe_load(match.group(1))


#: ``\author[1]{Mikhaeel Atef Rizk Wahba%`` -- the name runs to the ``%`` that
#: comments out the line break before ``\thanks``. Stopping at the first ``}``
#: would instead capture into the middle of the ``\thanks`` argument.
_TEX_AUTHOR = re.compile(r"\\author\[\d+\]\{\s*([^%\\{}\n]+)")
_TEX_AFFIL = re.compile(r"\\affil\[\d+\]\{([^{}]*)\}")


class TestTheStructuredNameIsOneName:
    def test_citation_cff_splits_it_the_agreed_way(self) -> None:
        """``given-names`` is where CFF puts every given name; ``name-particle``
        is for nobiliary particles and must stay absent, or the renderer files
        the author under the middle name."""
        author = yaml.safe_load(_read("CITATION.cff"))["authors"][0]

        assert author["family-names"] == FAMILY
        assert author["given-names"] == GIVEN_NAMES
        assert "name-particle" not in author, (
            "CITATION.cff carries the middle names as a name-particle; "
            "renderers glue that to the surname"
        )

    def test_codemeta_splits_it_the_same_way(self) -> None:
        """``familyName: "Atef Rizk Wahba"`` is the defect this file was written
        for: it files the author under A in every index that reads codemeta,
        while CITATION.cff and paper.bib file them under W."""
        author = json.loads(_read("codemeta.json"))["author"][0]

        assert author["familyName"] == FAMILY, (
            f"codemeta.json says familyName {author['familyName']!r}; "
            f"CITATION.cff says {FAMILY!r}. Two surnames for one person."
        )
        assert author["givenName"] == GIVEN
        assert author.get("additionalName") == MIDDLE

    def test_the_bibliography_entry_splits_it_the_same_way(self) -> None:
        """BibTeX's ``Family, Given`` order is the structured form in disguise."""
        bib = _read("paper/paper.bib")
        entry = re.search(r"@misc\{wahba_bindsight_2026,(.*?)\n\}", bib, re.S)
        assert entry, "the self-citation entry wahba_bindsight_2026 is missing from paper.bib"
        match = re.search(r"author\s*=\s*\{([^}]+)\}", entry.group(1))
        assert match, "the self-citation entry in paper.bib has no author field"
        family, _, given = match.group(1).partition(",")

        assert family.strip() == FAMILY
        assert given.strip() == GIVEN_NAMES


class TestTheDisplayNameIsTheSameEverywhere:
    #: Every surface that writes the name out for a human, with how to find it.
    DISPLAY_SURFACES = (
        ("paper/paper.md", lambda t: _front_matter(t)["authors"][0]["name"]),
        ("paper/biorxiv/manuscript.tex", lambda t: _TEX_AUTHOR.search(t).group(1).strip()),
        ("pyproject.toml", lambda t: tomllib.loads(t)["project"]["authors"][0]["name"]),
    )

    @pytest.mark.parametrize(
        ("rel", "extract"), DISPLAY_SURFACES, ids=[s[0] for s in DISPLAY_SURFACES]
    )
    def test_the_display_form_is_the_structured_form_joined(self, rel, extract) -> None:
        assert extract(_read(rel)) == FULL_NAME, (
            f"{rel} writes a different display name than {GIVEN_NAMES} + {FAMILY} produces"
        )

    def test_the_submission_instructions_name_the_same_author(self) -> None:
        assert FULL_NAME in _read("paper/README.md"), (
            "paper/README.md tells a submitter what to type into the bioRxiv "
            "author field; it must be the name the manuscript carries"
        )

    def test_the_readme_and_the_copyright_notice_use_the_full_name(self) -> None:
        """A licence notice names a legal person, not a byline."""
        assert FULL_NAME in _read("README.md")
        assert FULL_NAME in _read("COPYRIGHT")
        assert FULL_NAME in _read("mkdocs.yml")


class TestTheAffiliationIsOneAffiliation:
    #: Every surface that states where the author works, and how to read it.
    AFFILIATION_SURFACES = (
        ("CITATION.cff", lambda t: yaml.safe_load(t)["authors"][0]["affiliation"]),
        ("codemeta.json", lambda t: json.loads(t)["author"][0]["affiliation"]["name"]),
        ("paper/paper.md", lambda t: _front_matter(t)["affiliations"][0]["name"]),
        ("paper/biorxiv/manuscript.tex", lambda t: _TEX_AFFIL.search(t).group(1).strip()),
        ("paper/README.md", lambda t: re.search(r'affiliation\s+"([^"]+)"', t).group(1)),
    )

    @pytest.mark.parametrize(
        ("rel", "extract"),
        AFFILIATION_SURFACES,
        ids=[s[0] for s in AFFILIATION_SURFACES],
    )
    def test_it_is_the_agreed_string(self, rel, extract) -> None:
        """Not "close enough": the bioRxiv form is filled by copying
        paper/README.md, and the reviewer compares it to the manuscript."""
        assert extract(_read(rel)) == AFFILIATION, (
            f"{rel} states a different affiliation than {AFFILIATION!r}"
        )

    def test_the_readme_places_the_author_in_the_same_city(self) -> None:
        """README.md writes the affiliation as prose rather than as a field."""
        assert "independent researcher in Cairo, Egypt" in _read("README.md")

    def test_every_extractor_still_finds_something(self) -> None:
        """Guards the guard: a regex that stopped matching would raise
        AttributeError above, but a YAML key silently renamed would not --
        ``.get`` chains are not used here for exactly that reason."""
        assert len(self.AFFILIATION_SURFACES) >= 5


class TestTheOrcidIsOneOrcid:
    ORCID_SURFACES = (
        "CITATION.cff",
        "codemeta.json",
        "paper/paper.md",
        "paper/biorxiv/manuscript.tex",
        "paper/README.md",
        "README.md",
        "COPYRIGHT",
    )

    @pytest.mark.parametrize("rel", ORCID_SURFACES, ids=ORCID_SURFACES)
    def test_the_bare_identifier_appears(self, rel: str) -> None:
        """Checked as the bare id, because the surfaces spell it three ways:
        a full URL (CITATION.cff, codemeta), bare (paper.md front matter), and
        both at once (the manuscript's \\thanks, which links it)."""
        assert ORCID in _read(rel), f"{rel} no longer carries the author's ORCID"

    def test_the_url_forms_agree_with_the_bare_one(self) -> None:
        assert yaml.safe_load(_read("CITATION.cff"))["authors"][0]["orcid"] == ORCID_URL
        assert json.loads(_read("codemeta.json"))["author"][0]["@id"] == ORCID_URL

    def test_the_paper_front_matter_carries_it_unquoted_but_readable(self) -> None:
        """YAML would happily turn a bare identifier into something else."""
        assert str(_front_matter(_read("paper/paper.md"))["authors"][0]["orcid"]) == ORCID


class TestTheShortPublicBylineIsDeliberate:
    """The site uses a shorter byline, and that is a decision, not drift.

    ``mkdocs.yml`` and ``overrides/main.html`` publish "Mikhaeel Atef Rizk" --
    the name the author goes by online, tied to the same ORCID in the JSON-LD's
    ``sameAs`` block. It is pinned here so it cannot silently become a fourth
    spelling, and so the next person to sweep for the full name finds the reason
    written down instead of "fixing" it.
    """

    BYLINE = GIVEN_NAMES

    def test_the_site_author_is_the_short_byline(self) -> None:
        match = re.search(r"^site_author:\s*(.+)$", _read("mkdocs.yml"), re.M)
        assert match is not None, "mkdocs.yml no longer sets site_author"
        assert match.group(1).strip() == self.BYLINE

    def test_the_structured_data_ties_the_short_byline_to_the_orcid(self) -> None:
        html = _read("overrides/main.html")
        block = re.search(r'"author":\s*\{(.*?)\n    \}', html, re.S)
        assert block, "overrides/main.html no longer carries an author block"

        assert f'"name": "{self.BYLINE}"' in block.group(1)
        assert ORCID_URL in block.group(1), (
            "the short byline is only safe because the ORCID disambiguates it"
        )

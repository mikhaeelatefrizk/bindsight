# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A preprint DOI may not be claimed before one exists.

Between 2026-09-21 and 2026-09-25 this repository said in two dozen places that
a bioRxiv preprint was hours away, then that it was in hand. bioRxiv declined the
submission on 2026-09-25 -- it requires an organizational affiliation, and the
author has none -- and those sentences outlived the submission by four days,
including two ``10.1101/YOURDOI`` placeholders sitting in a block a submitter is
told to paste into a form.

This is the second time the same shape of defect has shipped here.
``tests/test_no_zenodo.py`` documents the first: ``10.5281/zenodo.PENDING``, a
deliberately invalid identifier, was published as a real one through
``CITATION.cff``'s ``doi`` key, ``codemeta.json`` and the documentation site's
JSON-LD. "An identifier that cannot resolve is not a citation, and a placeholder
announced as one is worse than none." A submission announced as pending after it
was declined is that same mistake in a different tense.

So ``paper/SUBMISSIONS.md`` is now the single source of truth for submission
state, and this file holds every other document to it.

**The primary check derives legitimacy rather than listing it.** Preprint-server
DOIs are not forbidden outright -- this project cites nine of other people's, one
of which reaches the provenance manifest of every run. Instead, every
preprint-server DOI found anywhere in the tree must be *either* a third party's,
evidenced by its presence in the shared bibliography ``paper/paper.bib``, *or*
recorded as posted in ``paper/SUBMISSIONS.md``. A DOI that is neither is this
project claiming an identifier it does not have. That test cannot be satisfied by
narrowing a list, because it has no list: add a preprint server tomorrow and the
rule already covers it.

The prose check below it is a backstop and is honestly an enumeration -- a
sentence claiming a preprint exists can be phrased in unboundedly many ways, and
no regex closes that. It catches the phrasings that actually occurred. The DOI
rule is the one that generalises.
"""

from __future__ import annotations

import functools
import re
import subprocess
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]

RECORD = "paper/SUBMISSIONS.md"

#: The record itself and the dated history. ``CHANGELOG.md`` is exempt for the
#: reason ``tests/test_no_zenodo.py`` gives for the same exemption: its entries
#: are dated records of what happened, and "deleting the word there would
#: falsify the history rather than correct it".
MAY_CLAIM = frozenset({RECORD, "CHANGELOG.md"})


def _is_exempt(rel: str) -> bool:
    """Whether a path may name an identifier this project does not have.

    Everything under ``tests/`` may: a guard has to be able to name what it
    forbids, and none of it is a published claim. ``test_no_zenodo.py`` holds
    ``10.5281/zenodo.PENDING`` on purpose, and ``test_docs_claims.py`` holds the
    Boltz-2 DOI that 404s so it can keep it out of the manuscripts.
    """
    return rel in MAY_CLAIM or rel.startswith("tests/")


#: DOI prefixes that identify a preprint or a general-purpose deposit rather
#: than a journal. Zenodo is here for completeness even though
#: ``tests/test_no_zenodo.py`` already forbids it outright -- if that guard is
#: ever relaxed, this one should still hold a Zenodo DOI to the record.
PREPRINT_DOI = re.compile(
    r"""10\.(?:
          1101/[^\s"'<>)\]},`]+          # bioRxiv, medRxiv
        | 20944/preprints[^\s"'<>)\]},`]+ # Preprints.org
        | 21203/rs\.[^\s"'<>)\]},`]+      # Research Square
        | 48550/arXiv\.[^\s"'<>)\]},`]+   # arXiv
        | 31219/[^\s"'<>)\]},`]+          # OSF Preprints
        | 5281/zenodo\.[^\s"'<>)\]},`]+   # Zenodo
        | 32942/[^\s"'<>)\]},`]+          # Qeios
      )""",
    re.VERBOSE | re.IGNORECASE,
)

#: A DOI-shaped string with a placeholder where the identifier belongs. These
#: are the ones that were actually in the tree; ``PENDING`` is the Zenodo
#: episode's, kept because it is the precedent this file exists to prevent
#: repeating.
PLACEHOLDER_DOI = re.compile(
    r"10\.\d{4,9}(?:/|%2F)[^\s\"'<>)\]},]*(?:YOURDOI|YOUR_DOI|PENDING|TODO|X{4,}|N{4,}|<doi>)",
    re.IGNORECASE,
)

#: Prose asserting a preprint of *this* work exists. A backstop, not the primary
#: check -- see the module docstring. Each of these was in the tree on
#: 2026-09-25, after the decline.
CLAIMS_A_PREPRINT = (
    re.compile(r"preprint\s+in\s+hand", re.IGNORECASE),
    re.compile(r"\b(?:our|the\s+bindsight)\s+preprint\s+is\s+(?:up|live|posted)", re.IGNORECASE),
    re.compile(r"after\s+(?:your|the)\s+preprint\s+is\s+up", re.IGNORECASE),
    re.compile(r"once\s+(?:it|the\s+preprint)\s+has\s+a\s+DOI", re.IGNORECASE),
)

LEGAL_STATUSES = frozenset({"open", "posted", "rejected", "declined", "withdrawn"})


@functools.lru_cache(maxsize=1)
def _tracked_text() -> tuple[tuple[str, str], ...]:
    """Every tracked file that decodes as UTF-8, with its contents.

    Decoding is the filter, as in ``tests/test_no_zenodo.py``: structures and
    images drop out of their own accord rather than through a suffix list that
    would go stale.
    """
    listed = subprocess.run(
        ["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=False
    ).stdout.split()
    out: list[tuple[str, str]] = []
    for rel in listed:
        path = REPO / rel
        if not path.is_file():
            continue
        try:
            out.append((rel, path.read_text(encoding="utf-8")))
        except (UnicodeDecodeError, OSError):
            continue
    return tuple(out)


@functools.lru_cache(maxsize=1)
def _rows() -> tuple[dict[str, str], ...]:
    """The submission table, parsed.

    The header row names the columns, so a column added to the record does not
    need a change here.
    """
    text = (REPO / RECORD).read_text(encoding="utf-8")
    lines = [ln.strip() for ln in text.splitlines() if ln.strip().startswith("|")]
    assert len(lines) >= 3, f"{RECORD} has no submission table"

    def cells(line: str) -> list[str]:
        return [c.strip() for c in line.strip("|").split("|")]

    header = [c.lower() for c in cells(lines[0])]
    rows: list[dict[str, str]] = []
    for line in lines[2:]:  # [1] is the |---|---| separator
        values = cells(line)
        if len(values) != len(header):
            continue
        rows.append(dict(zip(header, values, strict=True)))
    return tuple(rows)


def _posted_dois() -> frozenset[str]:
    """Every DOI the record says is live."""
    return frozenset(
        row["doi"]
        for row in _rows()
        if row.get("status") == "posted" and row.get("doi", "none").lower() != "none"
    )


#: Third-party preprints linked from prose but cited by neither manuscript, so
#: legitimately absent from ``paper/paper.bib``. Both are other people's tools
#: in the related-work comparisons in ``ARCHITECTURE.md`` and
#: ``docs/what-is-bindsight.md``.
#:
#: This is a list, and lists go stale -- the defect this repository keeps
#: finding in itself. It is tolerable here only because going stale makes the
#: test *red*, not blind: link a new preprint and the check fails with a message
#: saying to declare it or cite it. The failure is the safe direction.
THIRD_PARTY_PROSE = frozenset(
    {
        "10.1101/2025.09.24.678028v2",  # ProteinDJ
        "10.1101/2025.11.27.691041v1",  # Ovo
    }
)


@functools.lru_cache(maxsize=1)
def _bibliography_dois() -> frozenset[str]:
    """Every DOI in the shared bibliography -- that is, other people's."""
    bib = (REPO / "paper" / "paper.bib").read_text(encoding="utf-8")
    return frozenset(m.group(0) for m in PREPRINT_DOI.finditer(bib)) | THIRD_PARTY_PROSE


class TestTheRecordIsWellFormed:
    def test_the_record_exists(self) -> None:
        assert (REPO / RECORD).is_file(), (
            f"{RECORD} is the single source of truth for what has been submitted "
            "where and what came back. Without it the checks below have nothing "
            "to hold the rest of the repository to."
        )

    def test_every_row_carries_a_legal_status(self) -> None:
        bad = [
            (row.get("venue"), row.get("status"))
            for row in _rows()
            if row.get("status") not in LEGAL_STATUSES
        ]
        assert not bad, (
            f"these rows in {RECORD} carry a status outside "
            f"{sorted(LEGAL_STATUSES)}: {bad}. 'pending' is not one of them -- a "
            "submission is either open, decided, or withdrawn."
        )

    def test_the_table_is_not_empty(self) -> None:
        assert _rows(), (
            f"{RECORD} parses to zero rows. Two submissions have been made and "
            "both were refused; a record that forgets them lets the same "
            "mistake be made a third time."
        )

    @pytest.mark.parametrize(
        ("venue", "status"),
        [("JOSS", "rejected"), ("bioRxiv", "declined")],
    )
    def test_a_refusal_that_happened_stays_in_the_record(self, venue: str, status: str) -> None:
        """The record must not be quietly emptied.

        ``tests/test_no_zenodo.py`` runs in both directions for the same reason:
        a scan that can be satisfied by deleting the evidence is pointed at the
        wrong thing.
        """
        matching = [row for row in _rows() if row.get("venue", "").lower() == venue.lower()]
        assert matching, f"{RECORD} no longer records the {venue} submission"
        assert any(row.get("status") == status for row in matching), (
            f"{RECORD} records {venue} but not as {status!r}. That decision "
            "happened; changing its status here does not change what the venue "
            "said."
        )

    @pytest.mark.parametrize(
        "sentence",
        [
            "bioRxiv requires authors to have an organizational affiliation",
            "at minimum one instance of the software being used in published or preprint research",
        ],
    )
    def test_the_decision_is_quoted_verbatim(self, sentence: str) -> None:
        """Whitespace is normalised on both sides.

        The record wraps its quotes to the file's column width, so a quote that
        is present reads as absent under a plain substring test -- which is how
        this check first went red against a record that did contain both
        sentences.
        """
        raw = (REPO / RECORD).read_text(encoding="utf-8")
        # Every wrapped line of a Markdown blockquote begins "> ", which
        # collapsing whitespace would leave sitting inside the sentence.
        unquoted = "\n".join(re.sub(r"^\s*>\s?", "", line) for line in raw.splitlines())
        text = " ".join(unquoted.split())
        assert " ".join(sentence.split()) in text, (
            f"{RECORD} no longer quotes {sentence!r}. The reason a venue gave is "
            "the part that decides what to do next, and a reason paraphrased "
            "drifts into a reason invented."
        )


class TestNothingClaimsADOIItDoesNotHave:
    def test_no_preprint_doi_is_claimed_unless_it_is_cited_or_posted(self) -> None:
        """The primary check. Derived, not listed.

        A preprint-server DOI in this tree is legitimate when it is a third
        party's -- evidenced by ``paper/paper.bib`` -- or when the record says we
        posted it. Anything else is this project asserting an identifier for
        itself that no venue has minted.
        """
        allowed = _bibliography_dois() | _posted_dois()
        offenders: dict[str, set[str]] = {}
        for rel, text in _tracked_text():
            if _is_exempt(rel):
                continue
            found = {m.group(0) for m in PREPRINT_DOI.finditer(text)} - allowed
            if found:
                offenders[rel] = found
        assert not offenders, (
            "these files carry a preprint DOI that is neither cited in "
            f"paper/paper.bib nor recorded as posted in {RECORD}: "
            f"{ {k: sorted(v) for k, v in offenders.items()} }. If it is a "
            "citation, add it to the bibliography. If it is ours, the record is "
            "where that becomes true."
        )

    def test_no_file_carries_a_placeholder_where_a_doi_belongs(self) -> None:
        offenders = {
            rel: sorted({m.group(0) for m in PLACEHOLDER_DOI.finditer(text)})
            for rel, text in _tracked_text()
            if not _is_exempt(rel) and PLACEHOLDER_DOI.search(text)
        }
        assert not offenders, (
            f"these files hold a DOI-shaped placeholder: {offenders}. This is the "
            "Zenodo episode exactly -- 10.5281/zenodo.PENDING reached readers' "
            "bibliographies through CITATION.cff. Write the instruction without "
            "a fake identifier in it."
        )

    def test_citation_metadata_offers_no_preferred_citation_while_none_is_posted(self) -> None:
        """``CITATION.cff``'s ``preferred-citation`` is what GitHub's "Cite this
        repository" button hands a reader. It must not name a paper that has no
        identifier."""
        if _posted_dois():
            pytest.skip("something is posted; a preferred citation may name it")
        meta = yaml.safe_load((REPO / "CITATION.cff").read_text(encoding="utf-8"))
        preferred = meta.get("preferred-citation") or {}
        assert not preferred.get("doi"), (
            "CITATION.cff offers a preferred-citation with a DOI while "
            f"{RECORD} records nothing posted. GitHub emits that straight into a "
            "reader's bibliography."
        )
        assert not meta.get("doi"), (
            "CITATION.cff carries a top-level doi while nothing is posted or "
            "archived. This is the key the Zenodo placeholder was published "
            "through."
        )

    def test_no_badge_advertises_a_venue_that_refused_us(self) -> None:
        """Derived from the record: a venue that said no does not get a badge."""
        refused = [
            row["venue"]
            for row in _rows()
            if row.get("status") in {"rejected", "declined"} and row.get("venue")
        ]
        offenders: dict[str, list[str]] = {}
        for rel, text in _tracked_text():
            if _is_exempt(rel):
                continue
            hits = [
                venue
                for venue in refused
                if re.search(rf"shields\.io/badge/{re.escape(venue)}", text, re.IGNORECASE)
            ]
            if hits:
                offenders[rel] = hits
        assert not offenders, (
            f"these files carry a status badge for a venue that refused this "
            f"work: {offenders}. A badge is a claim."
        )


class TestNoProseClaimsAPreprintExists:
    def test_no_tracked_file_says_a_preprint_is_in_hand(self) -> None:
        if _posted_dois():
            pytest.skip("a preprint is posted; prose may say so")
        offenders: dict[str, list[str]] = {}
        for rel, text in _tracked_text():
            if _is_exempt(rel):
                continue
            hits = [m.group(0) for pattern in CLAIMS_A_PREPRINT for m in pattern.finditer(text)]
            if hits:
                offenders[rel] = sorted(set(hits))
        assert not offenders, (
            "these files state that a preprint of this work exists or is about "
            f"to, while {RECORD} records none posted: {offenders}. Plans belong "
            "in the future tense and name the condition they wait on."
        )


class TestTheGuardCanActuallyFail:
    """A guard never seen red is a guard never seen.

    Each check above is exercised against text that should trip it, so a
    regression that makes the patterns match nothing -- an escaped ``?``, a
    ``VERBOSE`` pattern with an unescaped space -- is caught here rather than by
    passing silently forever.
    """

    @pytest.mark.parametrize(
        "text",
        [
            "see 10.1101/2026.09.21.753186 for the preprint",
            "posted at 10.20944/preprints202609.1234.v1",
            "https://doi.org/10.21203/rs.3.rs-9999999/v1",
            "arXiv: 10.48550/arXiv.2609.01234",
        ],
    )
    def test_a_preprint_doi_is_recognised(self, text: str) -> None:
        assert PREPRINT_DOI.search(text), f"{text!r} should read as a preprint DOI"

    def test_a_third_partys_doi_is_recognised_as_such(self) -> None:
        """The bibliography really does supply the allow-set, so the primary
        check is not vacuously passing on an empty one."""
        assert _bibliography_dois(), (
            "paper/paper.bib yielded no preprint DOIs. It cites several; if this "
            "is empty the primary check above allows nothing and would be "
            "failing, or the pattern has stopped matching."
        )

    @pytest.mark.parametrize(
        "text",
        [
            "[![bioRxiv](https://img.shields.io/badge/bioRxiv-10.1101%2FYOURDOI-red.svg)]",
            "doi: 10.1101/YOURDOI",
            "10.5281/zenodo.PENDING",
            "10.1101/2026.MM.DD.NNNNNN",
            # Five N's, not six. The pattern listed the literal `NNNNNN` and this
            # sat two lines from a caught case in paper/README.md, unnoticed,
            # because the count differed.
            "10.21105/joss.NNNNN",
        ],
    )
    def test_a_placeholder_is_recognised(self, text: str) -> None:
        assert PLACEHOLDER_DOI.search(text), f"{text!r} should read as a placeholder"

    @pytest.mark.parametrize(
        "text",
        [
            "with the bioRxiv preprint in hand (paper/README.md says why)",
            "## After your preprint is up",
            "the bioRxiv preprint, once it has a DOI",
        ],
    )
    def test_a_prose_claim_is_recognised(self, text: str) -> None:
        assert any(p.search(text) for p in CLAIMS_A_PREPRINT), (
            f"{text!r} should read as claiming a preprint exists"
        )

    def test_a_journal_doi_is_not_mistaken_for_a_preprint(self) -> None:
        """PyDESeq2's paper reaches the provenance manifest of every run. A scan
        that flagged it would be narrowed until it was blind."""
        assert not PREPRINT_DOI.search("10.1093/bioinformatics/btad547")
        assert not PREPRINT_DOI.search("10.1186/s13059-014-0550-8")

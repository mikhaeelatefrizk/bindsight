# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
r"""The LaTeX manuscript must typeset what it means.

`paper/biorxiv/manuscript.tex:328` read `commit to <TAB>exttt{main}`: a
`\texttt` whose leading backslash had been resolved as a Python escape by
whatever wrote the line, so `\t` became a tab and the macro's own first letter
went with it. It typesets as a tab followed by the raw characters
`exttt{main}`, in the document that goes to a preprint server.

Every backslash-initial macro in a file a program edits carries this hazard, and
the residue is always the same: a control character where none belongs. `\t`
leaves a tab, `\n` a stray newline, `\b` a backspace, `\f` a form feed, `\v` a
vertical tab, `\a` a bell. LaTeX source has no use for any of them, so their
presence is the fingerprint -- which is why this scans for the character class
rather than for any particular macro.

Also checked here: the paper directory's two documents described the same test
suite as "over 1,300" and "200+", a factor of eight apart in one folder.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

TEX_FILES = ("paper/biorxiv/manuscript.tex",)

#: What a resolved backslash escape leaves behind. `\n` is excluded because a
#: newline is how the file is structured; the rest have no meaning in LaTeX.
ESCAPE_RESIDUE = {
    "\t": r"\t (tab)",
    "\x08": r"\b (backspace)",
    "\x0c": r"\f (form feed)",
    "\x0b": r"\v (vertical tab)",
    "\x07": r"\a (bell)",
    "\r": r"\r (carriage return)",
    "\x00": r"\0 (null)",
}


def _doc(rel: str) -> str:
    path = REPO / rel
    if not path.is_file():
        pytest.skip(f"{rel} not present")
    return path.read_text(encoding="utf-8")


def _escape_residue(text: str) -> list[str]:
    """Lines carrying a control character a resolved backslash escape leaves."""
    offenders: list[str] = []
    for number, line in enumerate(text.split("\n"), 1):
        for char, name in ESCAPE_RESIDUE.items():
            if char in line:
                offenders.append(f"line {number}: {name} — {line.strip()[:60]!r}")
    return offenders


class TestNoMacroLostItsBackslash:
    @pytest.mark.parametrize("rel", TEX_FILES)
    def test_no_line_carries_a_resolved_escape(self, rel: str) -> None:
        offenders = _escape_residue(_doc(rel))

        assert not offenders, (
            "a control character in LaTeX source is almost always a macro whose "
            "backslash was resolved as an escape:\n  " + "\n  ".join(offenders)
        )

    def test_the_scan_catches_the_defect_it_was_written_for(self) -> None:
        r"""Guards the guard: the real corrupted line must be caught.

        Built from `chr(9)` rather than written as `\t`, so this fixture cannot
        be silently repaired by the same mechanism it describes.
        """
        broken = "pass on every commit to " + chr(9) + "exttt{main}, alongside a lint job,"

        assert _escape_residue(broken), "the scan would have passed the original defect"

    def test_the_scan_does_not_flag_correct_latex(self) -> None:
        fine = "pass on every commit to " + chr(92) + "texttt{main}, alongside a lint job,"

        assert _escape_residue(fine) == []

    @pytest.mark.parametrize("rel", TEX_FILES)
    def test_the_macro_that_was_corrupted_is_spelled_correctly_now(self, rel: str) -> None:
        """Named, so the specific fix cannot lapse unnoticed."""
        text = _doc(rel)

        assert chr(92) + "texttt{main}" in text, (
            "the macro this file was written for is no longer spelled correctly"
        )


class TestThePaperDirectoryAgreesWithItself:
    """`paper.md` said "over 1,300"; `manuscript.tex` said "200+".

    Both were true of a suite of 1,800, which is the problem: a reader
    comparing two files in one directory saw a factor of eight between them.
    """

    CLAIMS = (
        ("paper/paper.md", r"over ([\d,]+) unit and integration tests"),
        ("paper/biorxiv/manuscript.tex", r"textbf\{([\d,]+)\+ unit and"),
    )

    def _read(self) -> dict[str, int]:
        found: dict[str, int] = {}
        for rel, pattern in self.CLAIMS:
            match = re.search(pattern, _doc(rel))
            if match:
                found[rel] = int(match.group(1).replace(",", ""))
        return found

    def test_both_claims_are_readable(self) -> None:
        """Without this, a pattern that stopped matching would pass the check below."""
        claims = self._read()

        assert len(claims) == len(self.CLAIMS), (
            f"could not read a test count from every paper document; got {claims}"
        )

    def test_they_describe_the_same_suite(self) -> None:
        claims = self._read()
        low, high = min(claims.values()), max(claims.values())

        assert high <= low * 2, (
            f"the paper directory states {claims}; two documents in one folder "
            "describing the same test suite should not differ by a factor of two"
        )

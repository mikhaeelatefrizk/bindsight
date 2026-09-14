# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Write a freshly minted Zenodo concept DOI into every file that cites one.

A DOI cannot exist before the deposit it names, so the repository ships a
placeholder and this script replaces it. Doing that by hand across a dozen
files is how a project ends up citing two different identifiers -- which is the
same class of defect as citing two different result sets, and just as invisible
until someone follows the wrong one.

Usage::

    python scripts/set_doi.py 10.5281/zenodo.1234567

Run it once, after the first Zenodo deposit of this repository. ``--check``
reports whether the placeholder is still present without changing anything,
which is what the release guard uses.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: The value the repository ships with. Deliberately not a valid DOI: a
#: plausible-looking placeholder is one that gets published by accident.
PLACEHOLDER = "10.5281/zenodo.PENDING"

#: Every file that names the concept DOI. Checked for completeness by
#: ``tests/test_docs_claims.py`` rather than trusted, because a hand-written
#: list of files is exactly what this repository keeps finding stale.
FILES = (
    "CITATION.cff",
    "codemeta.json",
    "SECURITY.md",
    "docs/index.md",
    "paper/README.md",
    ".huggingface/README.md",
    "bindsight/report/theme.py",
    "tests/test_docs_claims.py",
    "tests/test_packaging_pins.py",
    "paper/biorxiv/manuscript.tex",
    "README.md",
    # The CHANGELOG names the concept DOI in a historical entry describing the
    # move to it. That statement becomes true once the identifier is real, and
    # stays a placeholder forever if this file does not reach it.
    "CHANGELOG.md",
)

_DOI = re.compile(r"^10\.\d{4,9}/[-._;()/:A-Za-z0-9]+$")


def _targets() -> list[Path]:
    return [ROOT / rel for rel in FILES]


def check() -> int:
    """Report where the placeholder still sits. Returns a process exit code."""
    outstanding = [rel for rel in FILES if PLACEHOLDER in (ROOT / rel).read_text(encoding="utf-8")]
    if not outstanding:
        print("no placeholder DOI remains")
        return 0
    print(f"placeholder DOI still in {len(outstanding)} file(s):")
    for rel in outstanding:
        print(f"  {rel}")
    print("\nrun: python scripts/set_doi.py <the minted DOI>")
    return 1


def apply(doi: str) -> int:
    if not _DOI.match(doi):
        print(f"{doi!r} does not look like a DOI (expected e.g. 10.5281/zenodo.1234567)")
        return 2

    changed = 0
    for path in _targets():
        text = path.read_text(encoding="utf-8")
        if PLACEHOLDER not in text:
            continue
        path.write_text(text.replace(PLACEHOLDER, doi), encoding="utf-8", newline="\n")
        print(f"  {path.relative_to(ROOT).as_posix()}")
        changed += 1

    if not changed:
        print("nothing to do: no file carries the placeholder")
        return 0
    print(f"\nwrote {doi} into {changed} file(s).")
    print("Now re-run the tests, then commit.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("doi", nargs="?", help="the minted concept DOI")
    parser.add_argument(
        "--check",
        action="store_true",
        help="report whether the placeholder is still present, changing nothing",
    )
    args = parser.parse_args(argv)

    if args.check:
        return check()
    if not args.doi:
        parser.error("give a DOI, or pass --check")
    return apply(args.doi)


if __name__ == "__main__":
    sys.exit(main())

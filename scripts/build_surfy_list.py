# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Regenerate the vendored SURFY surfaceome accession list.

Why this exists
---------------
The SURFY master table is no longer retrievable as a spreadsheet. The URL the
package shipped with (``wlab.ethz.ch``) now serves an HTML landing page, so
``pandas.read_excel`` fails with ``BadZipFile``; the relocated site
(``wollscheidlab.org``) serves a 132-byte Git-LFS pointer rather than the file
itself. Discovery could therefore not populate the surfaceome on any machine.

What still works is ``surfaceome_ids.txt``, which lists all 2,886 surface
proteins by UniProt *entry name* (``1A01_HUMAN``). bindsight matches on
*accessions* (``P30443``), so this script resolves the mapping once, against
UniProt, and vendors the result. Discovery then needs no network for the
surfaceome at all.

Regenerate when SURFY publishes a new release:

    python scripts/build_surfy_list.py

Requires network access to UniProt and wollscheidlab.org. The output is
committed; ``tests/test_surfy_vendored.py`` guards its integrity.

Licensing: the SURFY list is CC-BY (Bausch-Fluck et al., PNAS 2018). The
attribution required by that licence is written into the file header.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "bindsight" / "surfaceome" / "data" / "surfy_v1.uniprot.txt"

SURFY_IDS_URL = "https://wollscheidlab.org/SURFY/surfaceome_ids.txt"
UNIPROT_STREAM = "https://rest.uniprot.org/uniprotkb/stream"
UNIPROT_SEARCH = "https://rest.uniprot.org/uniprotkb/search"

EXPECTED_COUNT = 2886
CITATION = (
    "Bausch-Fluck et al., 'The in silico human surfaceome', PNAS 2018, doi:10.1073/pnas.1808790115"
)


def fetch_entry_names(session: requests.Session) -> list[str]:
    """Fetch the SURFY surface-protein entry names."""
    resp = session.get(SURFY_IDS_URL, timeout=120)
    resp.raise_for_status()
    names = [line.strip() for line in resp.text.split() if line.strip()]
    if not names:
        raise RuntimeError(f"no entry names parsed from {SURFY_IDS_URL}")
    return names


def bulk_entry_name_map(session: requests.Session) -> dict[str, str]:
    """Map every reviewed human entry name to its accession in one request."""
    resp = session.get(
        UNIPROT_STREAM,
        params={
            "query": "reviewed:true AND organism_id:9606",
            "fields": "accession,id",
            "format": "tsv",
        },
        timeout=300,
    )
    resp.raise_for_status()
    mapping: dict[str, str] = {}
    for line in resp.text.strip().splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) >= 2:
            mapping[parts[1].strip()] = parts[0].strip()
    if not mapping:
        raise RuntimeError("UniProt returned no entry-name -> accession rows")
    return mapping


def resolve_one(session: requests.Session, entry_name: str) -> str | None:
    """Resolve a single entry name, including names retired since 2018."""
    resp = session.get(
        UNIPROT_SEARCH,
        params={"query": f"id:{entry_name}", "fields": "accession", "format": "tsv", "size": 1},
        timeout=60,
    )
    resp.raise_for_status()
    rows = resp.text.strip().splitlines()[1:]
    return rows[0].strip() if rows else None


def build() -> tuple[list[str], int]:
    """Resolve the full accession list. Returns (accessions, n_individual_lookups)."""
    session = requests.Session()
    names = fetch_entry_names(session)
    print(f"SURFY entry names: {len(names)}", file=sys.stderr)

    bulk = bulk_entry_name_map(session)
    print(f"UniProt reviewed human entries: {len(bulk)}", file=sys.stderr)

    accessions: list[str] = []
    unresolved: list[str] = []
    looked_up = 0
    for name in names:
        acc = bulk.get(name)
        if acc is None:
            looked_up += 1
            acc = resolve_one(session, name)
        if acc:
            accessions.append(acc)
        else:
            unresolved.append(name)

    if unresolved:
        raise RuntimeError(
            f"{len(unresolved)} SURFY entry name(s) could not be resolved to an "
            f"accession, e.g. {unresolved[:5]}. Refusing to vendor a partial list."
        )

    unique = sorted(set(accessions))
    if len(unique) != len(accessions):
        print(
            f"note: {len(accessions) - len(unique)} duplicate accession(s) collapsed",
            file=sys.stderr,
        )
    return unique, looked_up


def render(accessions: list[str], looked_up: int) -> str:
    """Render the vendored file, including the CC-BY attribution."""
    today = dt.datetime.now(dt.UTC).date().isoformat()
    header = [
        "# SURFY human surfaceome — UniProt accessions, one per line.",
        "#",
        f"# {CITATION}",
        "# Licence: CC BY 4.0. Redistributed with attribution.",
        "#",
        f"# {len(accessions)} accessions, resolved from {EXPECTED_COUNT} SURFY entry names.",
        f"# Sources: {SURFY_IDS_URL}",
        "#          https://rest.uniprot.org/uniprotkb (entry name -> accession)",
        f"# Retrieved: {today} ({looked_up} name(s) needed an individual lookup)",
        "#",
        "# Generated by scripts/build_surfy_list.py — do not edit by hand.",
        "# The upstream .xlsx is no longer retrievable (the host serves an HTML",
        "# page; the mirror serves a Git-LFS pointer), which is why this list is",
        "# vendored rather than downloaded at run time.",
        "",
    ]
    return "\n".join(header) + "\n".join(accessions) + "\n"


def main() -> int:
    """Regenerate the vendored SURFY accession list."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--allow-count-mismatch",
        action="store_true",
        help="Write the list even if the count differs from the published 2,886.",
    )
    args = parser.parse_args()

    accessions, looked_up = build()
    if len(accessions) != EXPECTED_COUNT and not args.allow_count_mismatch:
        raise SystemExit(
            f"resolved {len(accessions)} accessions, expected {EXPECTED_COUNT}. "
            "Upstream may have been revised; re-run with --allow-count-mismatch "
            "and update SURFY_PROTEIN_COUNT if that is intended."
        )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(render(accessions, looked_up), encoding="utf-8")
    print(f"wrote {len(accessions)} accessions to {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

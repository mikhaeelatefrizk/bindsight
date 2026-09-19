# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Zenodo is gone -- and the citations that must not go with it.

The archive was removed because it could not be repaired from inside this
repository. Zenodo keys repositories by GitHub id; this one was deleted and
recreated on 2026-09-14, so Zenodo still holds the previous object under this
name, answers HTTP 403 to enabling the new one, and answered the v0.3.1
release with "The repository does not exist". Only Zenodo can fix that.

Leaving it in place was not neutral. ``10.5281/zenodo.PENDING`` is a
deliberately invalid identifier -- and it was being published as a real one.
GitHub's "Cite this repository" button reads ``CITATION.cff``'s ``doi`` key and
emitted it into readers' bibliographies; ``codemeta.json`` published it to
software indexers; the JSON-LD in ``overrides/main.html`` published it as
``sameAs`` on every page of the documentation site. Around it, nine documents
said in the present tense that the software *is archived*, including a
manuscript abstract and a block of text the author is instructed to paste
verbatim into a submission form. An identifier that cannot resolve is not a
citation, and a placeholder announced as one is worse than none.

So this file has two halves, and the second is the one that matters.

Removing "every DOI" would have been the larger defect. Forty DOIs in this
repository belong to *other people* -- PyDESeq2, DESeq2, edgeR, AlphaFold,
RFdiffusion, ProteinMPNN, Boltz-2, SURFY, SURFACE-Bind, Snakemake, Open
Targets, and the clinical trials behind ``benchmarks/binders.tsv``. One of them
is written into the provenance manifest of every single run. They are how this
project credits the work it stands on, and a scan that could be satisfied by
deleting them would be a scan pointed at the wrong thing. So the checks below
run in both directions: Zenodo must stay out, and the citations must stay in.

What is deliberately NOT asserted is the absence of the word from
``CHANGELOG.md``. Its entries are dated records of what happened, and the whole
Zenodo episode is in them. Deleting the word there would falsify the history
rather than correct it -- and a reason deleted is a change waiting to be
reverted.
"""

from __future__ import annotations

import functools
import json
import re
import subprocess
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]

#: The only tracked files allowed to name Zenodo: the dated record of its
#: removal, and this file, which has to name what it forbids.
MAY_NAME_IT = frozenset({"CHANGELOG.md", f"tests/{Path(__file__).name}"})

#: Paths that existed only to deposit on Zenodo.
DELETED = (
    ".zenodo.json",
    ".github/workflows/zenodo.yml",
    "scripts/zenodo_deposit.py",
    "scripts/set_doi.py",
    "tests/test_zenodo_deposit.py",
)

WORD = re.compile(r"zenodo", re.IGNORECASE)

#: A Zenodo DOI. The ``/zenodo.`` segment is load-bearing, not decoration: the
#: prefix ``10.5281`` on its own matches ``10.52814``, an atomic coordinate,
#: which appears in every committed ``.cif`` structure. A scan written without
#: it fails on twenty benchmark artifacts and gets narrowed until it is blind.
ZENODO_DOI = re.compile(r"10\.5281/zenodo\.[A-Za-z0-9]+", re.IGNORECASE)

#: PyDESeq2's paper. ``bindsight/pipelines/discover.py`` attaches it to the
#: differential-expression tool reference, so it reaches the manifest of every
#: run this project produces.
PYDESEQ2_DOI = "10.1093/bioinformatics/btad547"


@functools.lru_cache(maxsize=1)
def _tracked_text() -> tuple[tuple[str, str], ...]:
    """Every tracked file that decodes as UTF-8, with its contents.

    Decoding is the filter: structure files and images drop out of their own
    accord rather than through a suffix list that would go stale.
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


class TestTheMachineryIsGone:
    @pytest.mark.parametrize("rel", DELETED)
    def test_the_file_is_gone(self, rel: str) -> None:
        assert not (REPO / rel).exists(), (
            f"{rel} is back. It exists only to deposit this software on Zenodo, "
            "which this repository no longer does."
        )


class TestNothingShippedNamesIt:
    def test_no_tracked_file_names_zenodo(self) -> None:
        offenders = [
            rel for rel, text in _tracked_text() if rel not in MAY_NAME_IT and WORD.search(text)
        ]
        assert not offenders, (
            "these files name Zenodo, which this project no longer uses: "
            f"{offenders}. If one of them describes depositing a *run* somewhere, "
            "name no service -- the RO-Crate exporter is not tied to one."
        )

    def test_no_tracked_file_names_a_zenodo_doi(self) -> None:
        offenders = {
            rel: sorted(set(ZENODO_DOI.findall(text)))
            for rel, text in _tracked_text()
            if rel not in MAY_NAME_IT and ZENODO_DOI.search(text)
        }
        assert not offenders, f"a Zenodo DOI is still shipped: {offenders}"

    def test_citation_cff_declares_no_doi(self) -> None:
        """GitHub's "Cite this repository" button reads this file.

        It emitted the placeholder straight into readers' bibliographies, which
        is the single widest path a dead identifier had out of this repository.
        No ``doi`` key means the button generates BibTeX and APA without one,
        which is ordinary for software that is not archived.
        """
        cff = yaml.safe_load((REPO / "CITATION.cff").read_text(encoding="utf-8"))

        assert "doi" not in cff, f"CITATION.cff still declares doi: {cff.get('doi')!r}"
        doi_ids = [
            item
            for item in cff.get("identifiers", [])
            if str(item.get("type", "")).lower() == "doi"
        ]
        assert not doi_ids, f"CITATION.cff still declares a doi identifier: {doi_ids}"
        # The file still has to identify the work, or this check is satisfied
        # by an empty file.
        assert cff["title"]
        assert cff["version"]
        assert cff["repository-code"]

    def test_codemeta_declares_no_identifier(self) -> None:
        codemeta = json.loads((REPO / "codemeta.json").read_text(encoding="utf-8"))

        assert "identifier" not in codemeta, (
            f"codemeta.json still publishes an identifier to software indexers: "
            f"{codemeta.get('identifier')!r}"
        )
        assert codemeta["codeRepository"], "codemeta names nothing at all"

    def test_the_theme_carries_no_doi_constants(self) -> None:
        """The web report rendered the placeholder behind a button reading "Cite"."""
        from bindsight.report import theme

        for name in ("ZENODO_DOI", "ZENODO_DOI_URL", "DOI_IS_PENDING"):
            assert not hasattr(theme, name), f"theme.{name} is back"


class TestTheCitationsOfOtherPeoplesWorkSurvive:
    """The half a careless removal would have broken.

    Every check here is on a DOI belonging to someone else. If the scans above
    could be satisfied by deleting these, they would be pointed at the wrong
    thing entirely.

    Unlike the scans above, these were green before Zenodo was removed and must
    stay green: they are a guard on the removal itself, so a run where they go
    red is a run that took the citations with it.
    """

    def test_the_bibliography_still_credits_its_sources(self) -> None:
        bib = (REPO / "paper" / "paper.bib").read_text(encoding="utf-8")
        dois = re.findall(r"doi\s*=\s*\{([^}]+)\}", bib)
        others = [d for d in dois if not ZENODO_DOI.search(d)]

        assert len(others) >= 15, (
            f"paper.bib is down to {len(others)} third-party DOIs; it credits the "
            "tools and papers this work is built on"
        )

    def test_every_known_binder_still_names_the_trial_that_validated_it(self) -> None:
        rows = (REPO / "benchmarks" / "binders.tsv").read_text(encoding="utf-8").splitlines()
        header = rows[0].split("\t")

        assert "doi" in header, "binders.tsv lost its doi column"
        column = header.index("doi")
        cited = [r for r in rows[1:] if r.strip() and r.split("\t")[column].strip()]
        assert len(cited) >= 10, (
            f"only {len(cited)} evaluation binders still cite their literature; "
            "these are the clinical trials the held-out set is built from"
        )

    def test_the_pipeline_still_credits_pydeseq2_in_every_manifest(self) -> None:
        source = (REPO / "bindsight" / "pipelines" / "discover.py").read_text(encoding="utf-8")

        assert PYDESEQ2_DOI in source, (
            "the differential-expression stage no longer cites PyDESeq2, so every "
            "run manifest this project emits would stop crediting it"
        )

    def test_a_tool_reference_can_still_carry_a_citation(self) -> None:
        from bindsight.provenance.manifest import ToolRef

        assert "citation" in ToolRef.model_fields, "ToolRef lost its citation field"
        ref = ToolRef(name="pydeseq2", version="0.5.4", license="MIT", citation=PYDESEQ2_DOI)
        assert ref.citation == PYDESEQ2_DOI

    def test_the_crate_still_writes_those_dois_into_software_bib(self) -> None:
        source = (REPO / "bindsight" / "export" / "ro_crate.py").read_text(encoding="utf-8")

        assert "doi = {" in source, (
            "the RO-Crate exporter no longer emits doi fields into software.bib, "
            "so an exported run would credit its upstream tools without their papers"
        )


class TestTheScanWouldCatchWhatItLooksFor:
    """Each pattern proved against a sample, so none can go quietly blind."""

    @pytest.mark.parametrize("sample", ["Zenodo", "zenodo", "ZENODO", "a zenodo.org link"])
    def test_the_word_scan_matches_the_word(self, sample: str) -> None:
        assert WORD.search(sample)

    @pytest.mark.parametrize(
        "sample",
        [
            "10.5281/zenodo.20121495",
            "10.5281/zenodo.PENDING",
            "https://doi.org/10.5281/zenodo.21855928",
        ],
    )
    def test_the_doi_scan_matches_a_zenodo_doi(self, sample: str) -> None:
        assert ZENODO_DOI.search(sample)

    def test_the_doi_scan_ignores_an_atomic_coordinate(self) -> None:
        """The reason the pattern is not simply the ``10.5281`` prefix.

        This line is copied from a committed Boltz-2 complex.
        """
        atom = "ATOM 1154 C CB . ILE 10 10 ? B -2.96127 7.16902 10.52814 1 2 B ILE"
        assert not ZENODO_DOI.search(atom)

    @pytest.mark.parametrize(
        "sample",
        [
            PYDESEQ2_DOI,
            "10.1038/s41586-021-03819-2",
            "10.1016/S0140-6736(12)60485-1",
            "10.1073/pnas.2506269123",
        ],
    )
    def test_the_doi_scan_ignores_other_peoples_dois(self, sample: str) -> None:
        assert not ZENODO_DOI.search(sample)

    def test_the_listing_is_not_empty(self) -> None:
        """Every scan above iterates it; an empty listing passes all of them."""
        tracked = _tracked_text()

        assert len(tracked) > 200, (
            f"git ls-files yielded {len(tracked)} readable files, so the scans "
            "above checked almost nothing"
        )
        assert any(rel == "README.md" for rel, _ in tracked)

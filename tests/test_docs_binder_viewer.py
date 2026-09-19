# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The published results page draws the complexes, and must keep being able to.

The documentation site now renders the twenty predicted binder-target complexes
in 3-D, from files committed to this repository, with no server and no secret.
That page used to promise them and then tell the reader to install something --
a promise that was a redirect, and before that a redirect to a hosted build this
repository cannot keep running on its own.

What makes it work is an arrangement that can quietly come apart:

* One viewer script, authored once at ``bindsight/report/web/static``, loaded by
  both ``bindsight ui`` and the docs page. Two copies of a viewer diverge.
* Copies of the structures, the vendored library and the script beneath
  ``docs/``, because MkDocs serves nothing outside it. Every copy is
  byte-identical, which is why git stores one blob for both and the repository
  did not grow by 2.8 MB.
* A page that offers exactly the designs whose files are actually published.

Each of those is asserted below, in both directions, because the failure this
guards against is silent: a page that offers a structure it cannot serve renders
a blank rectangle, and a blank rectangle is indistinguishable from a design that
produced nothing. That distinction is the one thing the viewer itself is written
to preserve.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Iterable
from pathlib import Path

import pytest
import yaml

from bindsight.report import showcase

REPO = Path(__file__).resolve().parents[1]

RESULTS = REPO / "docs" / "results.md"
DOCS_STRUCTURES = REPO / "docs" / "assets" / "structures"
DOCS_VENDOR = REPO / "docs" / "assets" / "vendor"
DOCS_JS = REPO / "docs" / "assets" / "js" / "binder_viewer.js"

WEB_STATIC = REPO / "bindsight" / "report" / "web" / "static"
SOURCE_JS = WEB_STATIC / "binder_viewer.js"
SOURCE_VENDOR = WEB_STATIC / "vendor"
TEMPLATES = REPO / "bindsight" / "report" / "web" / "templates"
GENERATOR = REPO / "scripts" / "build_docs_results.py"

#: Markers that only the viewer's own logic carries. If any of these turn up in
#: a template or in the generator, a second copy of the viewer has been started.
VIEWER_LOGIC = ("$3Dmol.createViewer", "webglAvailable", "selectedAtoms")


def _offered(page: str) -> set[str]:
    """The design ids the picker offers.

    Scoped to the picker element rather than the page: ``docs/results.md`` names
    all twenty ids again in the metrics table, so a page-wide scan would report
    a full set for a page carrying no viewer at all.
    """
    if "data-binder-picker" not in page:
        return set()
    block = page.split("data-binder-picker", 1)[1].split("</select>", 1)[0]
    return set(re.findall(r'<option value="([^"]+)"', block))


def _publish_diff(pairs: Iterable[tuple[Path, Path]]) -> tuple[list[str], list[str]]:
    """Compare ``(source, published)`` pairs byte for byte.

    Returns the published names that are absent, and the ones that differ.
    Both publishing sweeps below wrote this loop inline, which left their
    positive controls nothing real to call: they wrote a temporary file, read
    it back from the same path and compared it to itself. Those controls would
    have stayed green with every sweep in this file deleted.
    """
    missing: list[str] = []
    differing: list[str] = []
    for source, published in pairs:
        if not published.is_file():
            missing.append(published.name)
        elif published.read_bytes() != source.read_bytes():
            differing.append(published.name)
    return missing, differing


def _tracked() -> set[str]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=False
    ).stdout.split()
    return set(out)


class TestThePageOffersWhatItCanActuallyServe:
    def test_the_benchmark_is_present_in_this_checkout(self) -> None:
        """Guards the guard.

        Every check below compares against ``with_structures()``. Installed from
        a wheel there are no benchmarks and that list is empty, which would make
        the comparisons below agree about nothing. In a clone it must not be.
        """
        if "benchmarks/designer_benchmark/results.json" not in _tracked():
            pytest.skip("benchmarks/ is not part of this checkout")
        d = showcase.load_designer_benchmark()
        assert d is not None, "the designer benchmark is committed but did not load"
        assert d.with_structures(), "the benchmark loaded but offers no structures"

    def test_the_page_offers_every_structure_the_benchmark_has(self) -> None:
        d = showcase.load_designer_benchmark()
        if d is None or not d.with_structures():
            pytest.skip("no designer benchmark in this checkout")

        expected = {b.binder_id for b in d.with_structures()}
        offered = _offered(RESULTS.read_text(encoding="utf-8"))

        assert offered == expected, (
            "the published page and the benchmark disagree about which designs "
            f"exist: only on the page {sorted(offered - expected)}, only in the "
            f"benchmark {sorted(expected - offered)}"
        )

    def test_every_design_the_page_offers_is_published_as_an_asset(self) -> None:
        """Existence is not enough: the copy must be the same bytes.

        A stale copy left behind by a superseded run would serve a structure
        that no longer matches the metrics printed beside it.
        """
        d = showcase.load_designer_benchmark()
        if d is None or not d.with_structures():
            pytest.skip("no designer benchmark in this checkout")

        offered = _offered(RESULTS.read_text(encoding="utf-8"))
        assert offered, "the page offers no designs at all"

        by_id = {b.binder_id: b for b in d.with_structures()}
        pairs = []
        for binder_id in sorted(offered):
            source = by_id[binder_id].complex_cif
            assert source is not None
            pairs.append((source, DOCS_STRUCTURES / source.name))
        missing, differing = _publish_diff(pairs)

        assert not missing, f"the page offers structures the site does not serve: {missing}"
        assert not differing, f"published copies differ from the benchmark's: {differing}"

    def test_no_published_structure_is_orphaned(self) -> None:
        """The other direction: nothing served that the page does not offer."""
        if not DOCS_STRUCTURES.is_dir():
            pytest.skip("no published structures in this checkout")

        published = {p.name.removesuffix("_complex.cif") for p in DOCS_STRUCTURES.glob("*.cif")}
        offered = _offered(RESULTS.read_text(encoding="utf-8"))

        assert published == offered, (
            f"published but not offered: {sorted(published - offered)}; "
            f"offered but not published: {sorted(offered - published)}"
        )

    def test_the_published_page_names_no_server_route(self) -> None:
        """The whole claim is that this page needs no server."""
        assert "/api/structure/" not in RESULTS.read_text(encoding="utf-8"), (
            "docs/results.md names the app's structure route; the published page "
            "must read its structures from files served beside it"
        )


class TestTheTwoSurfacesShareOneViewer:
    def test_every_vendored_asset_is_published_with_its_licence(self) -> None:
        """Discovered, not listed: a second library is covered the day it lands,
        and its licence with it, because a licence is a file in that directory
        rather than a name this test knows."""
        sources = sorted(p for p in SOURCE_VENDOR.iterdir() if p.is_file())
        assert sources, "nothing is vendored, so this test compared nothing"

        missing, differing = _publish_diff((src, DOCS_VENDOR / src.name) for src in sources)

        assert not missing, f"vendored files the docs site does not serve: {missing}"
        assert not differing, f"published vendored copies have drifted: {differing}"
        assert any("LICENSE" in p.name.upper() for p in sources), (
            "the vendored directory carries no licence file, so publishing it "
            "copies someone else's code without its terms"
        )

    def test_the_two_surfaces_load_the_same_viewer_script(self) -> None:
        source = SOURCE_JS.read_bytes()

        assert DOCS_JS.is_file(), "the docs site does not publish the viewer script"
        assert DOCS_JS.read_bytes() == source, "the published viewer has drifted from the source"
        # An empty file would satisfy byte-equality perfectly.
        text = source.decode("utf-8")
        assert "data-binder-viewer" in text, "the viewer script lost its host hook"
        assert "BINDER_CHAIN" in text, "the viewer script lost its chain colouring"

        evidence = (TEMPLATES / "evidence.html.j2").read_text(encoding="utf-8")
        assert "binder_viewer.js" in evidence, "bindsight ui stopped loading the shared viewer"
        mkdocs = (REPO / "mkdocs.yml").read_text(encoding="utf-8")
        assert "assets/js/binder_viewer.js" in mkdocs, "the docs site stopped loading it"

    def test_neither_surface_keeps_its_own_copy_of_the_viewer_logic(self) -> None:
        """The anti-divergence check.

        Pasting the viewer back into a template, or generating it into the docs
        page, is how the two copies start drifting -- and the drift is invisible
        until one of them renders the wrong thing.
        """
        source = SOURCE_JS.read_text(encoding="utf-8")
        for marker in VIEWER_LOGIC:
            assert marker in source, f"{marker} is not in the viewer script at all"

        offenders: list[str] = []
        for path in [*TEMPLATES.rglob("*.j2"), GENERATOR]:
            text = path.read_text(encoding="utf-8")
            if any(marker in text for marker in VIEWER_LOGIC):
                offenders.append(path.relative_to(REPO).as_posix())

        assert not offenders, f"these carry a second copy of the viewer logic: {offenders}"

    def test_the_library_is_not_loaded_on_every_page(self) -> None:
        """``extra_javascript`` loads on all eight pages; 3Dmol is half a
        megabyte and is injected only where a viewer exists.

        Reads the entries rather than the file, so the comment above them
        explaining this is not itself a violation of it.
        """
        loaded = yaml.safe_load((REPO / "mkdocs.yml").read_text(encoding="utf-8")).get(
            "extra_javascript", []
        )

        assert loaded, "mkdocs.yml loads no javascript, so the viewer never boots"
        assert not any("3dmol" in str(entry).lower() for entry in loaded), (
            f"mkdocs.yml loads the structure library site-wide: {loaded}. The "
            "viewer script fetches it on demand instead."
        )

    def test_the_generator_copies_bytes_not_text(self) -> None:
        """A text round-trip on Windows rewrites LF as CRLF, and ``.gitattributes``
        checks these files out as LF -- so the generator would leave ``git diff``
        dirty on every machine that ran it."""
        source = GENERATOR.read_text(encoding="utf-8")
        body = source.split("def _copy_assets", 1)[1].split("\ndef ", 1)[0]

        assert "shutil.copyfile" in body
        assert "read_text" not in body, "_copy_assets reads text; it must copy bytes"
        assert "write_text" not in body, "_copy_assets writes text; it must copy bytes"


class TestTheDataCheckerIsPublishedToo:
    """The counts/design checker runs on the docs site, from the same script.

    Its promise -- that nothing is uploaded -- is load-bearing on a public
    website in a way it never was on localhost, and it is true only because the
    script has no network call at all. That is asserted in tests/test_web_ui.py
    against the script itself; what is asserted here is that the published page
    really loads that script and really gives it the elements it needs.
    """

    CHECKER = WEB_STATIC / "your_data_check.js"
    PAGE = REPO / "docs" / "try-your-data.md"
    TEMPLATE = TEMPLATES / "your_data.html.j2"

    #: The contract between the checker and whatever page hosts it.
    ELEMENT_IDS = ("counts", "design", "checks")

    def test_the_published_checker_is_the_same_script(self) -> None:
        published = REPO / "docs" / "assets" / "js" / "your_data_check.js"
        assert published.is_file(), "the docs site does not publish the checker"
        assert published.read_bytes() == self.CHECKER.read_bytes(), "the copy has drifted"
        assert b"getElementById" in self.CHECKER.read_bytes(), "the checker is empty"

    def test_both_surfaces_give_the_checker_the_elements_it_needs(self) -> None:
        """One script, two pages: a renamed id breaks one of them silently."""
        script = self.CHECKER.read_text(encoding="utf-8")
        page = self.PAGE.read_text(encoding="utf-8")
        template = self.TEMPLATE.read_text(encoding="utf-8")

        for element_id in self.ELEMENT_IDS:
            assert f'"{element_id}"' in script, f"the checker no longer looks for #{element_id}"
            assert f'id="{element_id}"' in page, f"docs/try-your-data.md has no #{element_id}"
            assert f'id="{element_id}"' in template, f"your_data.html.j2 has no #{element_id}"

    def test_the_published_page_repeats_the_promise_it_can_keep(self) -> None:
        page = self.PAGE.read_text(encoding="utf-8").lower()
        assert "uploaded" in page or "never leave" in page, (
            "the published checker page does not tell the reader their files stay "
            "in the browser, which is the one thing that makes it safe to use"
        )

    def test_the_page_is_in_the_navigation(self) -> None:
        """A page MkDocs builds but never links is a page nobody reaches."""
        nav = yaml.safe_load((REPO / "mkdocs.yml").read_text(encoding="utf-8"))["nav"]
        flat = yaml.dump(nav)
        assert "try-your-data.md" in flat


class TestTheScansWouldCatchTheirOwnDefect:
    def test_the_picker_scan_distinguishes_a_picker_from_a_table(self) -> None:
        picker = '<select data-binder-picker><option value="X">X</option></select>'
        assert _offered(picker) == {"X"}
        # docs/results.md names every id again in the metrics table. A page-wide
        # scan would pass on a page whose viewer had been deleted entirely.
        assert _offered("| `X` | 0.88 | 5.2 |") == set()
        assert _offered("") == set()

    def test_a_missing_structure_would_be_caught(self, tmp_path: Path) -> None:
        """Calls the comparison the publishing sweeps call.

        What this replaced wrote a file, read it back from the same path and
        compared it to itself -- true of any filesystem, and green with every
        sweep in this file deleted.
        """
        source = tmp_path / "a.cif"
        source.write_bytes(b"data_model\n")
        site = tmp_path / "published"
        site.mkdir()

        missing, differing = _publish_diff([(source, site / source.name)])
        assert missing == ["a.cif"], "an unpublished file was not reported missing"
        assert differing == []

        (site / source.name).write_bytes(source.read_bytes())
        assert _publish_diff([(source, site / source.name)]) == ([], [])

    def test_a_diverged_copy_would_be_caught(self, tmp_path: Path) -> None:
        """One byte of drift, in the direction that matters.

        A published copy that has silently stopped matching its source is what
        the byte comparison exists for -- a viewer script edited under
        ``docs/assets`` and not in the package, or the reverse.
        """
        source = tmp_path / "viewer.js"
        source.write_bytes(b"var BINDER_CHAIN = 'B';")
        published = tmp_path / "published.js"
        published.write_bytes(b"var BINDER_CHAIN = 'b';")

        missing, differing = _publish_diff([(source, published)])
        assert missing == []
        assert differing == ["published.js"], "a one-byte divergence went unreported"

        published.write_bytes(source.read_bytes())
        assert _publish_diff([(source, published)]) == ([], [])

    def test_the_comparison_reports_every_offender_not_just_the_first(self, tmp_path: Path) -> None:
        """Returning on the first mismatch would hide the rest of the drift."""
        site = tmp_path / "published"
        site.mkdir()
        pairs = []
        for i in range(3):
            source = tmp_path / f"s{i}.cif"
            source.write_bytes(f"data_{i}".encode())
            pairs.append((source, site / source.name))
        # s0 published correctly, s1 diverged, s2 never published at all.
        (site / "s0.cif").write_bytes(b"data_0")
        (site / "s1.cif").write_bytes(b"data_X")

        missing, differing = _publish_diff(pairs)

        assert missing == ["s2.cif"]
        assert differing == ["s1.cif"]

    def test_the_repository_listing_is_not_empty(self) -> None:
        """Every sweep above walks a directory; an empty one passes them all."""
        assert len(_tracked()) > 200
        assert SOURCE_VENDOR.is_dir()

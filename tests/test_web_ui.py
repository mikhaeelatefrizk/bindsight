# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The web interface, and the presentation rules it exists to keep.

Replaces the four Streamlit test modules. Those encoded real properties -- a
crashed run must not be shown in the layout that means "completed and found
nothing", a degraded lookup must be surfaced, every page must be reachable --
and the properties survive the framework that carried them.

Two rules are new here, and both are about honesty rather than looks:

* **An absent measurement renders as an em dash, never as zero.** Four crisp
  zeros in metric chrome read as a measurement, and a broken run then looks like
  an empty one.
* **A rate appears with its denominator or its interval, on screen.** The old
  interface promised this in prose and put intervals -- including one spanning
  15-70% -- inside hover tooltips, which do not print, do not exist on touch,
  and are absent from a photograph of the screen.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

fastapi = pytest.importorskip("fastapi", reason="the web interface needs the report extra")
from fastapi.testclient import TestClient  # noqa: E402

from bindsight.report.web.app import (  # noqa: E402
    ABSENT,
    create_app,
    fmt,
    fmt_int,
    fmt_p,
    interval,
    load_run_manifest,
    open_targets_degradation,
    stage_failures,
)

PAGES = ("/", "/evidence", "/try", "/your-data", "/runs")


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(create_app())


# ---------------------------------------------------------------------------
# Reachability
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("path", PAGES)
def test_every_page_serves(client: TestClient, path: str) -> None:
    response = client.get(path)
    assert response.status_code == 200
    assert "<html" in response.text.lower()


def test_every_navigation_link_resolves(client: TestClient) -> None:
    """A section in the sidebar that 404s is a dead end mid-demonstration."""
    body = client.get("/").text
    hrefs = set(re.findall(r'<a href="(/[^"]*)"', body))
    internal = {h for h in hrefs if not h.startswith("/static")}

    assert internal, "the shell renders no internal links at all"
    for href in sorted(internal):
        assert client.get(href).status_code == 200, f"{href} does not resolve"


def test_the_stylesheet_and_script_are_served(client: TestClient) -> None:
    for asset in ("/static/bindsight.css", "/static/charts.js"):
        assert client.get(asset).status_code == 200, f"{asset} is missing"


def test_the_structure_viewer_is_vendored_not_fetched(client: TestClient) -> None:
    """The previous viewer pulled 3Dmol.js from a CDN, so it needed internet.

    ``bindsight ui`` is meant to work on a laptop with no connection once
    installed. A page that silently requires a CDN does not.
    """
    response = client.get("/static/vendor/3Dmol-min.js")

    assert response.status_code == 200
    assert len(response.content) > 100_000

    for page in PAGES:
        body = client.get(page).text
        assert "cdn.jsdelivr.net" not in body, f"{page} loads a script from a CDN"
        assert "unpkg.com" not in body


# ---------------------------------------------------------------------------
# Absence is not zero
# ---------------------------------------------------------------------------
class TestAbsenceIsNotZero:
    """``None`` must never become ``0`` on the way to the screen."""

    @pytest.mark.parametrize("value", [None, float("nan"), "not a number", object()])
    def test_a_missing_number_renders_as_a_dash(self, value: object) -> None:
        assert fmt(value) == ABSENT
        assert fmt_int(value) == ABSENT

    def test_a_real_zero_still_renders_as_zero(self) -> None:
        """Guards the guard: only absence becomes a dash, not a measured zero."""
        assert fmt(0) == "0.00"
        assert fmt_int(0) == "0"

    def test_a_p_value_of_zero_is_not_printed_as_zero(self) -> None:
        """CA9's padj is literally 0.0 -- below floating-point resolution.

        ``%.2e`` rendered it ``0.00e+00``. A p of zero is not a p, and it was
        the headline row that carried it.
        """
        assert fmt_p(0.0) == "<1e-300"
        assert fmt_p(None) == ABSENT
        assert "e-" in fmt_p(3.97e-4)

    def test_an_interval_without_bounds_is_absent(self) -> None:
        assert interval(None, 0.5) == ABSENT
        assert interval(0.1, None) == ABSENT

    def test_a_confidence_level_is_read_not_assumed(self) -> None:
        assert interval(0.1, 0.5, confidence=0.95).startswith("95% CI")
        assert interval(0.1, 0.5).startswith("CI "), (
            "a confidence level was invented for an interval that recorded none"
        )


# ---------------------------------------------------------------------------
# A crashed run is not an empty one
# ---------------------------------------------------------------------------
class TestACrashedRunIsNotAnEmptyOne:
    """The distinction the deleted Streamlit guard existed for.

    "This cohort has no surface-antigen candidates" is a finding. "The
    differential-expression step crashed" is a bug. They leave behind the same
    empty tables.
    """

    def test_a_failed_stage_is_reported(self) -> None:
        manifest = {
            "stages": [
                {"name": "deg", "status": "failed", "error": "pydeseq2 rejected the matrix"},
                {"name": "discover", "status": "completed"},
            ]
        }

        assert stage_failures(manifest) == [
            {"name": "deg", "error": "pydeseq2 rejected the matrix"}
        ]

    def test_a_completed_run_reports_no_failures(self) -> None:
        assert stage_failures({"stages": [{"name": "deg", "status": "completed"}]}) == []

    @pytest.mark.parametrize("manifest", [None, "text", 42, [], {"stages": "not a list"}])
    def test_a_shapeless_manifest_is_tolerated(self, manifest: object) -> None:
        assert stage_failures(manifest) == []  # type: ignore[arg-type]

    def test_a_failed_stage_with_no_error_still_names_itself(self) -> None:
        failures = stage_failures({"stages": [{"name": "deg", "status": "failed"}]})

        assert failures[0]["name"] == "deg"
        assert failures[0]["error"], "a failed stage rendered with an empty error string"

    def test_an_absent_manifest_is_none_not_empty(self, tmp_path: Path) -> None:
        """``{}`` would let a caller conclude the run recorded no failures."""
        assert load_run_manifest(tmp_path) is None

    def test_a_corrupt_manifest_is_none(self, tmp_path: Path) -> None:
        (tmp_path / "run_manifest.jsonld").write_text("{not json", encoding="utf-8")

        assert load_run_manifest(tmp_path) is None

    def test_a_non_object_manifest_is_none(self, tmp_path: Path) -> None:
        (tmp_path / "run_manifest.jsonld").write_text("[1, 2]", encoding="utf-8")

        assert load_run_manifest(tmp_path) is None

    def test_a_real_manifest_parses(self, tmp_path: Path) -> None:
        (tmp_path / "run_manifest.jsonld").write_text(
            json.dumps({"run_id": "r", "stages": []}), encoding="utf-8"
        )

        assert (load_run_manifest(tmp_path) or {}).get("run_id") == "r"

    def test_the_runs_page_names_the_failed_stage(self, tmp_path: Path) -> None:
        """End to end: the error text reaches the page, not just the data layer."""
        run = tmp_path / "broken"
        run.mkdir()
        (run / "run_manifest.jsonld").write_text(
            json.dumps(
                {
                    "run_id": "r",
                    "stages": [
                        {"name": "deg", "status": "failed", "error": "matrix was not normalised"}
                    ],
                }
            ),
            encoding="utf-8",
        )

        body = TestClient(create_app(run_root=tmp_path)).get("/runs").text

        assert "matrix was not normalised" in body
        assert "a stage failed" in body
        assert "did not complete" in body


# ---------------------------------------------------------------------------
# Empty states
# ---------------------------------------------------------------------------
class TestTheEmptyStatesSayWhatIsMissing:
    def test_no_runs_offers_a_way_forward(self, tmp_path: Path) -> None:
        """The old empty state was prose with no route out of it."""
        body = TestClient(create_app(run_root=tmp_path / "nothing")).get("/runs").text

        assert "Nothing here yet" in body
        assert 'href="/try"' in body, "the empty state offers no way to produce a run"

    def test_the_evidence_page_without_benchmarks_says_so(self, monkeypatch) -> None:
        """On a wheel install ``benchmarks/`` is absent.

        The old primary call to action landed on a page whose entire content
        told the reader to leave and go to GitHub -- a dead end highlighted as
        the main action.
        """
        from bindsight.report import showcase

        monkeypatch.setattr(showcase, "load_study", lambda *a, **k: None)
        monkeypatch.setattr(showcase, "load_designer_benchmark", lambda *a, **k: None)

        body = TestClient(create_app()).get("/evidence").text

        assert "ships with the repository" in body
        assert "github.com" in body


# ---------------------------------------------------------------------------
# What may and may not appear
# ---------------------------------------------------------------------------
class TestTheRetractedFigureIsNotAHeadline:
    def test_no_page_headlines_the_withdrawn_rate(self, client: TestClient) -> None:
        """``success@0.65`` is withdrawn as a measure of design quality.

        It may be named -- the withdrawal has to say what was withdrawn -- but
        it must not be rendered as a figure.
        """
        for path in PAGES:
            body = client.get(path).text
            for stat in re.findall(r'<span class="stat__value">([^<]*)</span>', body):
                assert "%" not in stat or "success" not in body[: body.find(stat)][-200:], (
                    f"{path} renders a success rate as a headline figure: {stat!r}"
                )

    def test_the_withdrawal_travels_with_any_mention(self, client: TestClient) -> None:
        body = client.get("/evidence").text
        if "success@0.65" in body:
            assert "withdrawn" in body, (
                "the evidence page names the rate without withdrawing it"
            )

    def test_a_placeholder_doi_is_not_a_live_link(self, client: TestClient) -> None:
        """A 404 behind a button labelled "Cite" is the worst possible click."""
        from bindsight.report import theme

        body = client.get("/").text
        if theme.DOI_IS_PENDING:
            # Assembled, not written out: a literal here reads to the DOI
            # sweep as a surface that scripts/set_doi.py has to update, and
            # a test asserting the placeholder's absence is the one file
            # that must keep naming it after the DOI is minted.
            placeholder = f"doi.org/10.5281/zenodo.{theme.ZENODO_DOI.rsplit('.', 1)[-1]}"
            assert placeholder not in body, (
                "the placeholder DOI is rendered as a resolvable link"
            )
            assert "pending" in body.lower()


class TestEveryFigureCarriesWhatMakesItReadable:
    def test_each_stat_has_a_denominator_or_an_interval(self, client: TestClient) -> None:
        """The rule the previous interface promised and broke in six places.

        Every ``.stat`` block must carry a ``.stat__of`` (its denominator) or a
        ``.stat__ci`` (its interval). Hover is not a disclosure.
        """
        blocks = 0
        for path in PAGES:
            body = client.get(path).text
            for block in re.findall(r'<div class="stat[^"]*">(.*?)</div>\s*(?=<div|</div>)', body, re.S):
                if "stat__value" not in block:
                    continue
                blocks += 1
                has_context = "stat__of" in block or "stat__ci" in block or "stat__note" in block
                label = re.search(r'stat__label">([^<]*)<', block)
                assert has_context, (
                    f"{path}: the figure labelled "
                    f"{(label.group(1) if label else '?')!r} appears with neither a "
                    "denominator nor an interval"
                )
        assert blocks, "no figures were found at all; this guard is checking nothing"

    def test_the_evidence_page_states_its_intervals_in_the_text(self, client: TestClient) -> None:
        """Not in a tooltip: the interval must be in the served markup."""
        body = client.get("/evidence").text

        assert "CI 0.188–0.513" in body or "CI 0.188-0.513" in body, (
            "the within-antigen interval is not on the page"
        )


class TestTheChartsCarryRealSpecifications:
    def test_every_chart_host_has_a_parseable_spec(self, client: TestClient) -> None:
        found = 0
        for path in PAGES:
            body = client.get(path).text
            for kind, spec in re.findall(
                r"data-chart=\"([^\"]+)\" data-spec='([^']*)'", body
            ):
                found += 1
                parsed = json.loads(spec)
                assert parsed, f"{path}: the {kind} chart carries an empty specification"
        assert found, "no charts were rendered at all"

    def test_the_paired_control_chart_shows_every_pair(self, client: TestClient) -> None:
        """The chart that shows the withdrawal: designs against their own shuffles."""
        body = client.get("/evidence").text
        match = re.search(r"data-chart=\"pairedStrip\" data-spec='([^']*)'", body)
        if match is None:
            pytest.skip("the calibration artifact is not present in this install")

        spec = json.loads(match.group(1))

        assert len(spec["pairs"]) >= 20
        assert spec["threshold"] == 0.65
        for pair in spec["pairs"]:
            assert pair["a"] is not None
            assert pair["b"] is not None


class TestADegradedLookupIsNotASilentOne:
    """Open Targets is the only genome-wide mapping; when it falls back, say so.

    Ported from the deleted Streamlit module. The property is not about the
    framework: when the Ensembl -> UniProt mapping degrades, every gene absent
    from the small bundled table is dropped *before* the surfaceome filter, so
    the shortlist is drawn from that handful rather than from the cohort. A
    reader who is not told this will read a short list as a negative result.
    """

    @staticmethod
    def _table(*statuses: str):
        """A candidates table carrying the enrichment-status column."""
        pd = pytest.importorskip("pandas")
        return pd.DataFrame(
            {
                "gene_symbol": [f"GENE{i}" for i in range(len(statuses))],
                "open_targets_status": list(statuses),
            }
        )

    def test_a_fully_live_enrichment_stays_silent(self) -> None:
        """The normal case must not produce a warning; noise is not honesty."""
        assert open_targets_degradation(self._table("ok", "ok", "ok")) is None

    def test_no_candidates_at_all_is_not_a_degraded_lookup(self) -> None:
        """A run with no table must not crash the page, nor claim degradation."""
        assert open_targets_degradation(None) is None

    def test_a_table_without_the_column_cannot_be_judged(self) -> None:
        """An older table carries no status, and silence is the honest answer."""
        pd = pytest.importorskip("pandas")
        assert open_targets_degradation(pd.DataFrame({"gene_symbol": ["CA9"]})) is None

    def test_a_total_outage_is_reported_as_not_genome_wide(self) -> None:
        """Nothing came back live, so the shortlist is not a discovery at all."""
        report = open_targets_degradation(self._table("error", "error"))
        assert report is not None
        assert report["total_outage"] is True
        assert (report["degraded"], report["total"]) == (2, 2)

    def test_open_targets_disabled_degrades_exactly_like_an_outage(self) -> None:
        """``skipped`` is an offline run; the mapping is just as partial."""
        report = open_targets_degradation(self._table("skipped", "skipped"))
        assert report is not None
        assert report["total_outage"] is True

    def test_a_partial_degradation_is_incomplete_not_absent(self) -> None:
        """Some genes mapped live, so the honest claim is weaker, not nothing."""
        report = open_targets_degradation(self._table("ok", "error", "ok"))
        assert report is not None
        assert report["total_outage"] is False
        assert (report["degraded"], report["total"]) == (1, 3)

    def test_the_breakdown_counts_every_distinct_failure(self) -> None:
        """Two outages and one skip are three degraded rows, in two kinds."""
        report = open_targets_degradation(self._table("ok", "error", "error", "skipped"))
        assert report is not None
        assert report["breakdown"] == [
            {"status": "error", "count": 2},
            {"status": "skipped", "count": 1},
        ]

    def test_the_warning_reaches_the_page_not_a_tooltip(self, tmp_path: Path) -> None:
        """The counts and the consequence must be in the served HTML itself."""
        pd = pytest.importorskip("pandas")
        pytest.importorskip("pyarrow")
        run = tmp_path / "run-degraded"
        (run / "targets").mkdir(parents=True)
        (run / "run_manifest.jsonld").write_text(
            json.dumps({"stages": [{"name": "rank", "status": "completed"}]}),
            encoding="utf-8",
            newline="\n",
        )
        pd.DataFrame(
            {
                "gene_symbol": ["CA9", "EGFR", "MET"],
                "open_targets_status": ["ok", "error", "error"],
            }
        ).to_parquet(run / "targets" / "candidates.parquet")

        with TestClient(create_app(run_root=tmp_path)) as c:
            body = c.get("/runs").text

        assert "2 of 3" in body, "the counts must be on screen"
        assert "incomplete" in body.lower(), "a partial outage weakens the claim"
        assert "error" in body, "the breakdown names the status it saw"


class TestTheDemoCanActuallyStart:
    """The demo button called a loader that does not exist.

    ``_demo_config`` imported ``load_config`` from ``bindsight.config``, which
    has no such name — so every press raised ImportError into the broad handler
    around the job and reported it to the page as a failed run. mypy sees it,
    but the module sat outside the type-check scope until that scope was
    widened; nothing else did, because no test ever called the function.
    """

    def test_the_bundled_config_loads(self) -> None:
        from bindsight.config import RunConfig
        from bindsight.report.web.app import _demo_config

        try:
            cfg = _demo_config()
        except FileNotFoundError:
            pytest.skip("the demo cohort ships with the repository, not the wheel")

        assert isinstance(cfg, RunConfig), (
            "the demo did not produce a config the pipeline can run"
        )

    def test_the_stages_it_advertises_are_the_stages_it_runs(self) -> None:
        """Named stages are a progress claim; an empty list is a spinner."""
        from bindsight.report.web.app import _DEMO_STAGES

        assert len(_DEMO_STAGES) >= 2
        assert all(isinstance(name, str) and name for name in _DEMO_STAGES)


class TestTheStructuresAreActuallyShown:
    """538 kB of 3Dmol.js shipped in the wheel and no page referenced it.

    Twenty predicted binder-target complexes are committed to this repository —
    real validator output, the strongest artifact here, and the reason a reader
    can rotate one instead of taking an ipTM on trust. ARCHITECTURE.md said the
    interface rendered them. Nothing did: the library was vendored, the licence
    was credited, the file was served, and no template loaded it.

    The last test below is the one that would have caught it, and it is a sweep
    rather than a list of the assets that exist today.
    """

    def test_every_vendored_asset_is_referenced_by_something(self) -> None:
        """A vendored library nobody loads is dead weight in every install.

        It is also a licence obligation carried for no benefit, and — worse —
        a claim: the file's presence is what made "renders in 3-D" look true.
        """
        web = REPO / "bindsight" / "report" / "web"
        sources = "\n".join(
            p.read_text(encoding="utf-8", errors="ignore")
            for p in web.rglob("*")
            if p.suffix in {".j2", ".py", ".css"} and p.is_file()
        )

        vendored = [
            p for p in (web / "static" / "vendor").iterdir()
            if p.is_file() and p.suffix in {".js", ".css"}
        ]
        assert vendored, "the sweep found no vendored assets; it has stopped reaching them"

        unused = [p.name for p in vendored if p.name not in sources]
        assert not unused, (
            "these are shipped in every wheel and referenced by nothing, so they "
            f"cost the user bytes and the project a licence obligation for no benefit: {unused}"
        )

    def test_the_evidence_page_loads_the_vendored_copy(self, client: TestClient) -> None:
        body = client.get("/evidence").text
        if "binder-pick" not in body:
            pytest.skip("the designer benchmark ships with the repository, not the wheel")

        assert "/static/vendor/3Dmol-min.js" in body
        assert "cdn." not in body, "the viewer is being fetched from a network"

    def test_a_real_design_serves_a_real_structure(self, client: TestClient) -> None:
        from bindsight.report import showcase

        designer = showcase.load_designer_benchmark()
        if designer is None or not designer.with_structures():
            pytest.skip("the designer benchmark ships with the repository, not the wheel")

        binder = designer.with_structures()[0]
        response = client.get(f"/api/structure/{binder.binder_id}")

        assert response.status_code == 200
        assert "cif" in response.headers["content-type"]
        assert "_atom_site" in response.text, "the response is not an mmCIF"

    def test_every_design_the_page_offers_actually_resolves(self, client: TestClient) -> None:
        """A dead option in the picker is a viewer that silently stays empty."""
        body = client.get("/evidence").text
        offered = re.findall(r'<option value="([^"]+)"', body)
        if not offered:
            pytest.skip("the designer benchmark ships with the repository, not the wheel")

        for binder_id in offered:
            assert client.get(f"/api/structure/{binder_id}").status_code == 200, (
                f"the page offers {binder_id} and the route does not serve it"
            )

    def test_an_unknown_design_is_not_found(self, client: TestClient) -> None:
        assert client.get("/api/structure/not-a-design").status_code == 404

    @pytest.mark.parametrize(
        "attempt",
        ["../../pyproject.toml", "..%2F..%2Fpyproject.toml", "/etc/passwd", "....//pyproject.toml"],
    )
    def test_the_identifier_is_matched_never_joined_to_a_path(
        self, client: TestClient, attempt: str
    ) -> None:
        """A path built from a request parameter is a file-read primitive.

        The route resolves by comparing against the designs the benchmark
        loaded, so there is no directory for a ``..`` to climb out of.
        """
        response = client.get(f"/api/structure/{attempt}")

        assert response.status_code == 404
        assert "[project]" not in response.text, "the route served a file off disk"

    def test_every_structure_names_its_chains_the_way_the_viewer_expects(self) -> None:
        """The viewer colours chain ``B`` as the binder; that is a claim.

        It styled chains ``A`` and ``B`` at first. The files use ``T`` and
        ``B``, so the target matched nothing, kept 3Dmol's default line style,
        and rendered as a wireframe haze under a caption saying it was grey
        cartoon — no error anywhere. The viewer now paints everything before
        overriding the binder, so a change here degrades to *uniform* rather
        than to *wrong*, and this test says so out loud.
        """
        from bindsight.report import showcase

        designer = showcase.load_designer_benchmark()
        if designer is None or not designer.with_structures():
            pytest.skip("the designer benchmark ships with the repository, not the wheel")

        def chains(path: Path) -> set[str]:
            """Read the ``_atom_site`` loop header rather than guessing a column."""
            columns: list[str] = []
            found: set[str] = set()
            for raw in path.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if line.startswith("_atom_site."):
                    columns.append(line.split(".", 1)[1])
                elif line.startswith(("ATOM", "HETATM")) and columns:
                    fields = line.split()
                    for name in ("auth_asym_id", "label_asym_id"):
                        if name in columns:
                            found.add(fields[columns.index(name)])
                            break
            return found

        for binder in designer.with_structures():
            assert binder.complex_cif is not None
            present = chains(binder.complex_cif)
            assert "B" in present, (
                f"{binder.binder_id} has chains {sorted(present)}; the viewer colours "
                "chain B as the designed binder and would colour nothing"
            )


class TestBothSurfacesWriteTheSameNumberTheSameWay:
    """One design system means one set of rules, not just one stylesheet.

    The report picked up ``bindsight.css`` and still printed CA9's ``padj`` as
    ``0``, because the rule that a p-value never renders as zero lived inside
    the web app's module while the report kept its own ``f"{v:.3g}"``. Same
    number, same run, two answers — and the disagreement is *harder* to notice
    once the two surfaces look alike.
    """

    def test_the_report_embeds_the_shared_stylesheet(self) -> None:
        """Not a copy of it: a second copy is how the tokens drifted before."""
        from bindsight.report import html as report_html

        shared = (
            REPO / "bindsight" / "report" / "web" / "static" / "bindsight.css"
        ).read_text(encoding="utf-8")
        source = Path(report_html.__file__).read_text(encoding="utf-8")

        assert "bindsight.css" in source, (
            "the report no longer embeds the design system, so the two surfaces "
            "can look like different products again"
        )
        assert "--ink:" in shared, "the design system has no tokens to share"

    def test_the_report_stylesheet_is_a_layer_not_a_second_system(self) -> None:
        """It must not redeclare the tokens it is supposed to be inheriting."""
        layer = (
            REPO / "bindsight" / "report" / "templates" / "report.css"
        ).read_text(encoding="utf-8")

        redeclared = [t for t in ("--ink:", "--navy:", "--ok:", "--rule:") if t in layer]
        assert not redeclared, (
            f"report.css declares its own copy of {redeclared}; that is the "
            "arrangement that let the two surfaces drift apart"
        )

    @pytest.mark.parametrize("value", [0.0, 3.97e-4, 1e-300, 0.5])
    def test_a_p_value_reads_identically_in_both(self, value: float) -> None:
        """The web helper and the report's table formatter are one function."""
        from bindsight.report import format as shared_format
        from bindsight.report.html import _P_VALUE_COLS, _df_to_records

        pd = pytest.importorskip("pandas")
        frame = pd.DataFrame({"padj": [value]})
        rendered = _df_to_records(frame, ["padj"])[0]["padj"]

        assert "padj" in _P_VALUE_COLS
        assert rendered == shared_format.fmt_p(value), (
            f"the report writes {value} as {rendered!r} and the interface writes "
            f"it as {shared_format.fmt_p(value)!r}"
        )

    def test_a_p_value_of_zero_is_not_zero_in_the_report(self) -> None:
        """The specific row this was found on: CA9, padj literally 0.0."""
        from bindsight.report.html import _df_to_records

        pd = pytest.importorskip("pandas")
        frame = pd.DataFrame({"symbol": ["CA9"], "padj": [0.0]})

        assert _df_to_records(frame, ["symbol", "padj"])[0]["padj"] == "<1e-300"


class TestNoConditionIsDecorative:
    """A condition that cannot change the answer is worse than no condition.

    The "your data" page decided a card's severity with
    ``factor && (!samples || samples.length === 0 || true)`` — which reduces to
    ``factor``. Two checks that look load-bearing had never been consulted, and
    the page showed a green tick beside "none match, so the contrast cannot be
    built", then offered the command to run.

    Driving the page is what found it. This is the cheap guard for the shape.
    """

    TAUTOLOGIES = ("|| true", "||true", "&& false", "&&false", "or True", "and False")

    def test_no_inline_script_short_circuits_its_own_check(self) -> None:
        web = REPO / "bindsight" / "report" / "web"
        offenders: list[str] = []
        for path in sorted(web.rglob("*.j2")):
            text = path.read_text(encoding="utf-8")
            for lineno, line in enumerate(text.splitlines(), 1):
                if line.lstrip().startswith(("//", "*", "/*", "{#")):
                    continue
                for tautology in self.TAUTOLOGIES:
                    if tautology in line:
                        offenders.append(f"{path.name}:{lineno} {line.strip()[:80]}")

        assert not offenders, (
            "these conditions cannot change their own result, so whatever they "
            f"appear to check is not being checked:\n  " + "\n  ".join(offenders)
        )

    def test_the_readiness_verdict_reaches_the_advice(self) -> None:
        """The severity and the "here is the command" card must agree.

        Verified in a browser across four design tables — all names matching, a
        partial overlap, none matching, and no two-level column. This asserts the
        wiring that makes those agree still exists.
        """
        page = (
            REPO / "bindsight" / "report" / "web" / "templates" / "your_data.html.j2"
        ).read_text(encoding="utf-8")

        assert "designBlocked" in page, (
            "the design table's verdict no longer reaches the card that tells the "
            "reader to run the pipeline"
        )
        assert "Not ready to run" in page, (
            "a blocked design no longer has a card of its own, so the page falls "
            "back to offering a command that cannot work"
        )

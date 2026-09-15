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
            assert pair["a"] is not None and pair["b"] is not None


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

# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A run that crashed must never be presented as a successful, empty result.

A pipeline that dies in DESeq2 leaves behind exactly the same artifacts as a
cohort that genuinely surfaced nothing: no candidates, no epitopes, zeroed
counts. Only ``run_manifest.jsonld`` separates them. Rendering the two alike
invites a scientist to read a crash as a negative finding — and then to act on
it by loosening thresholds that were never reached.

Every reporting surface is covered here, because the defect was per-surface:

* ``webapp._show_run_summary`` — the inner guard no caller can bypass, and the
  Browse page that used to hand it ``manifest=None`` and print "Candidates 0";
* ``streamlit_app.main`` — the standalone viewer that advised "Loosen filters
  in the config and re-run" for a pipeline that never reached the filters;
* ``report.html`` — the paper-style report that rendered a crash as clean,
  zeroed KPIs.

The final section pins the same principle one level up: a benchmark artifact
that never recorded whether it came from a GPU or the mock backend must load as
*unknown*, never as "real".
"""

from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

pytest.importorskip("streamlit")

from streamlit.testing.v1 import AppTest

from bindsight.provenance import StageRecord, ToolRef, new_manifest
from bindsight.report import html as report_html
from bindsight.report import showcase, streamlit_app, webapp

APP = Path(__file__).resolve().parents[1] / "streamlit_app.py"

#: The error a real crashed run records — pydeseq2 rejecting a normalised matrix.
DEG_ERROR = "ValueError: counts matrix contains non-integer values"


class _RecordingStreamlit:
    """A minimal ``st`` stand-in that records which widgets a page drew.

    Every attribute resolves to a recorder that stores its first positional
    argument under the attribute name and returns the fake itself, so
    ``st.columns(4)[0].metric(...)``, ``with st.expander(...)`` and
    ``st.sidebar.radio(...)`` all work without special-casing.
    """

    def __init__(self, **returns: Any) -> None:
        self.calls: dict[str, list[Any]] = {}
        self.session_state: dict[str, Any] = {}
        self._returns = returns

    def __getattr__(self, name: str) -> Any:
        def _record(*args: Any, **kwargs: Any) -> Any:
            self.calls.setdefault(name, []).append(args[0] if args else None)
            return self._returns.get(name, self)

        return _record

    def __enter__(self) -> _RecordingStreamlit:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def __getitem__(self, index: object) -> _RecordingStreamlit:
        return self

    def text(self, name: str) -> str:
        """Join every recorded body for ``name`` into one searchable string."""
        return " ".join(str(v) for v in self.calls.get(name, []))


def _failed_manifest(stage: str = "deg", error: str = DEG_ERROR) -> Any:
    """A live manifest object whose ``stage`` crashed."""
    m = new_manifest(name="failed-run")
    m.append(StageRecord(name=stage, tool=ToolRef(name="pydeseq2", version="0.5.4", license="MIT")))
    m.stages[0].mark_failed(error)
    return m


def _completed_manifest() -> Any:
    """A live manifest object for a run that finished and found nothing."""
    m = new_manifest(name="empty-run")
    m.append(StageRecord(name="deg", tool=ToolRef(name="pydeseq2", version="0.5.4", license="MIT")))
    m.stages[0].mark_completed()
    m.append(
        StageRecord(name="discover", tool=ToolRef(name="bindsight", version="0.0.1", license="MIT"))
    )
    m.stages[1].mark_completed()
    return m


def _deg_frame() -> pd.DataFrame:
    """A small, real-shaped DEG table so the report has something to plot."""
    return pd.DataFrame(
        {
            "gene_id": ["ENSG00000141736", "ENSG00000142208"],
            "symbol": ["ERBB2", "AKT1"],
            "log2fc": [3.5, 0.1],
            "padj": [1e-9, 0.95],
            "significant": [True, False],
        }
    )


def _make_failed_run(tmp_path: Path) -> Path:
    """A run directory whose DEG stage crashed: manifest only, no tables."""
    run = tmp_path / "failed_run"
    run.mkdir(parents=True)
    _failed_manifest().write(run / "run_manifest.jsonld")
    return run


def _make_completed_empty_run(tmp_path: Path) -> Path:
    """A run directory that genuinely finished and surfaced no candidates."""
    run = tmp_path / "empty_run"
    (run / "deg").mkdir(parents=True)
    _deg_frame().to_parquet(run / "deg" / "results.parquet", index=False)
    _completed_manifest().write(run / "run_manifest.jsonld")
    return run


# --------------------------------------------------------------------------- #
# L3 — the guard accepts both manifest shapes
# --------------------------------------------------------------------------- #
def test_stage_failures_reads_a_manifest_dict_from_disk() -> None:
    """The Browse page holds plain dicts, and they must reach the guard."""
    manifest = {
        "stages": [
            {"name": "deg", "status": "failed", "error": DEG_ERROR},
            {"name": "discover", "status": "completed", "error": None},
        ]
    }
    assert webapp._stage_failures(manifest) == [("deg", DEG_ERROR)]


def test_stage_failures_reads_a_live_manifest_object() -> None:
    """A live run hands over model objects, and they must reach the same guard."""
    failures = webapp._stage_failures(_failed_manifest())
    assert failures == [("deg", DEG_ERROR)]


def test_stage_failures_agrees_across_both_shapes(tmp_path: Path) -> None:
    """Reading a manifest back off disk must not change the verdict."""
    run = _make_failed_run(tmp_path)
    live = _failed_manifest()
    from_disk = webapp._load_run_manifest(run)
    assert webapp._stage_failures(from_disk) == webapp._stage_failures(live)


@pytest.mark.parametrize(
    "manifest",
    [None, {}, {"stages": None}, {"stages": "deg"}, ["not", "a", "manifest"], 7],
)
def test_stage_failures_tolerates_shapeless_manifests(manifest: Any) -> None:
    """An unreadable manifest yields no failures rather than an exception."""
    assert webapp._stage_failures(manifest) == []


# --------------------------------------------------------------------------- #
# L3 — reading the manifest off disk
# --------------------------------------------------------------------------- #
def test_load_run_manifest_returns_none_without_a_manifest(tmp_path: Path) -> None:
    assert webapp._load_run_manifest(tmp_path) is None


def test_load_run_manifest_returns_none_for_a_corrupt_manifest(tmp_path: Path) -> None:
    (tmp_path / "run_manifest.jsonld").write_text("{ not json", encoding="utf-8")
    assert webapp._load_run_manifest(tmp_path) is None


def test_load_run_manifest_returns_none_for_a_non_object_body(tmp_path: Path) -> None:
    """A JSON list is not a manifest; treating it as one would crash the page."""
    (tmp_path / "run_manifest.jsonld").write_text("[1, 2, 3]", encoding="utf-8")
    assert webapp._load_run_manifest(tmp_path) is None


def test_load_run_manifest_parses_a_real_manifest(tmp_path: Path) -> None:
    """A manifest written by the provenance layer round-trips into the guard."""
    run = _make_failed_run(tmp_path)
    manifest = webapp._load_run_manifest(run)
    assert manifest is not None
    assert manifest["stages"][0]["name"] == "deg"
    assert manifest["stages"][0]["status"] == "failed"
    assert manifest["stages"][0]["error"] == DEG_ERROR


# --------------------------------------------------------------------------- #
# L3 — _show_run_summary is the unbypassable guard
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("shape", ["object", "dict"])
def test_show_run_summary_refuses_the_success_layout_for_a_failed_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, shape: str
) -> None:
    """No caller can reach the KPI row with a manifest that records a crash."""
    run = _make_failed_run(tmp_path)
    manifest: Any = _failed_manifest() if shape == "object" else webapp._load_run_manifest(run)
    fake = _RecordingStreamlit()
    monkeypatch.setattr(webapp, "st", fake)

    webapp._show_run_summary(run, manifest, report_path=None)

    assert "did not finish" in fake.text("error")
    assert DEG_ERROR in fake.text("code")
    # The success layout is what makes a crash look like a measured negative.
    assert "columns" not in fake.calls
    assert "metric" not in fake.calls


def test_show_run_summary_draws_the_kpis_for_a_completed_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The guard must not swallow a genuine, finished run with no hits."""
    run = _make_completed_empty_run(tmp_path)
    fake = _RecordingStreamlit()
    monkeypatch.setattr(webapp, "st", fake)

    webapp._show_run_summary(run, webapp._load_run_manifest(run), report_path=None)

    assert "error" not in fake.calls
    assert fake.calls["metric"] == [
        "Genes tested",
        "Significant DEGs",
        "Candidates",
        "Top-N epitopes",
    ]


# --------------------------------------------------------------------------- #
# L3 — the Browse page loads the manifest and routes it through the guard
# --------------------------------------------------------------------------- #
def test_browse_page_routes_the_on_disk_manifest_through_the_guard(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Browsing a crashed run shows the failure, never "Genes tested 0"."""
    run = _make_failed_run(tmp_path)
    fake = _RecordingStreamlit(text_input=str(run), selectbox="—")
    monkeypatch.setattr(webapp, "st", fake)
    monkeypatch.setattr(webapp, "_discover_local_runs", lambda limit=25: [])

    webapp._page_browse()

    assert "did not finish" in fake.text("error")
    assert DEG_ERROR in fake.text("code")
    assert "metric" not in fake.calls


def test_browse_page_warns_when_the_run_has_no_manifest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Without provenance there is nothing to confirm the run finished at all."""
    run = tmp_path / "unverifiable"
    run.mkdir()
    fake = _RecordingStreamlit(text_input=str(run), selectbox="—")
    monkeypatch.setattr(webapp, "st", fake)
    monkeypatch.setattr(webapp, "_discover_local_runs", lambda limit=25: [])

    webapp._page_browse()

    warning = fake.text("warning")
    assert "run_manifest.jsonld" in warning
    assert "crash rather than a negative result" in warning


# --------------------------------------------------------------------------- #
# L3 — the standalone single-run viewer
# --------------------------------------------------------------------------- #
def test_streamlit_app_failed_stages_is_empty_without_a_manifest() -> None:
    assert streamlit_app._failed_stages(None) == []


def test_streamlit_app_failed_stages_ignores_a_completed_run() -> None:
    manifest = {"stages": [{"name": "deg", "status": "completed"}]}
    assert streamlit_app._failed_stages(manifest) == []


def test_streamlit_app_failed_stages_returns_the_failing_stage() -> None:
    failed = {"name": "deg", "status": "failed", "error": DEG_ERROR}
    manifest = {"stages": [failed, {"name": "discover", "status": "skipped_cache"}]}
    assert streamlit_app._failed_stages(manifest) == [failed]


def _run_viewer(monkeypatch: pytest.MonkeyPatch, run: Path) -> _RecordingStreamlit:
    """Drive ``streamlit_app.main`` against ``run`` with a recording ``st``."""
    fake = _RecordingStreamlit()
    monkeypatch.setitem(sys.modules, "streamlit", fake)
    monkeypatch.setattr(sys, "argv", ["streamlit_app.py", str(run)])
    streamlit_app.main()
    return fake


def test_viewer_shows_the_incompleteness_banner_instead_of_the_kpis(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A crashed run gets the banner and its provenance, not a summary."""
    fake = _run_viewer(monkeypatch, _make_failed_run(tmp_path))

    error = fake.text("error")
    assert "These results are incomplete" in error
    assert "deg stage failed" in error
    assert "no filter should be loosened" in error
    assert "metric" not in fake.calls
    assert "Loosen filters in the config" not in fake.text("info")
    # The failing stage is still published — the banner points the reader at it.
    assert "stage: deg — failed" in fake.text("expander")


def test_viewer_keeps_the_loosen_advice_for_a_run_that_really_found_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The advice is correct for a completed run, and must survive the fix."""
    fake = _run_viewer(monkeypatch, _make_completed_empty_run(tmp_path))

    assert "error" not in fake.calls
    assert fake.calls["metric"][0] == "Genes tested"
    assert "Loosen filters in the config and re-run." in fake.text("info")


# --------------------------------------------------------------------------- #
# L3 — the paper-style HTML report
# --------------------------------------------------------------------------- #
def test_html_failed_stages_extracts_name_and_error() -> None:
    manifest = {
        "stages": [
            {"name": "deg", "status": "failed", "error": DEG_ERROR},
            {"name": "discover", "status": "completed", "error": None},
        ]
    }
    assert report_html._failed_stages(manifest) == [{"name": "deg", "error": DEG_ERROR}]


def test_html_failed_stages_is_empty_without_a_manifest() -> None:
    assert report_html._failed_stages(None) == []


def test_report_for_a_crashed_run_is_marked_incomplete(tmp_path: Path) -> None:
    """The emailed report must carry the crash, and withdraw the filter advice."""
    run = _make_failed_run(tmp_path)
    text = report_html.render_run(run).read_text(encoding="utf-8")

    assert "Incomplete run" in text
    assert "These results are incomplete" in text
    assert DEG_ERROR in text
    # The zeroed KPI row is disowned rather than presented as a measurement.
    assert "The counts above are whatever the crashed run left on disk" in text
    # The filters were never reached, so loosening them answers nothing.
    assert "Loosen thresholds in the config" not in text
    assert "The filters were never reached" in text


def test_report_for_a_completed_empty_run_still_advises_loosening(tmp_path: Path) -> None:
    """A genuine zero-hit run keeps the advice: the filters really did run."""
    run = _make_completed_empty_run(tmp_path)
    text = report_html.render_run(run).read_text(encoding="utf-8")

    assert "Incomplete run" not in text
    assert "Loosen thresholds in the config and re-run." in text


# --------------------------------------------------------------------------- #
# L5 — unrecorded provenance is unknown, never "real GPU run"
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, None),
        (False, False),
        (True, True),
        ("false", False),
        ("TRUE", True),
        ("maybe", None),
        (0, None),
        (1, None),
    ],
)
def test_as_optional_bool_only_trusts_an_explicit_statement(raw: object, expected: Any) -> None:
    """Anything the artifact did not clearly state must read as unknown."""
    assert showcase._as_optional_bool(raw) is expected


def _write_designer_results(root: Path, payload: dict[str, Any]) -> None:
    """Write a minimal designer-benchmark tree under ``root``."""
    base = root / "designer_benchmark"
    (base / "binders").mkdir(parents=True)
    (base / "results.json").write_text(json.dumps(payload), encoding="utf-8")


def test_designer_benchmark_without_is_mock_loads_as_unknown(tmp_path: Path) -> None:
    """A missing flag used to become ``False``, i.e. "this was a real GPU run"."""
    _write_designer_results(tmp_path, {"validator": "boltz2", "backend": "kaggle"})
    show = showcase.load_designer_benchmark(root=tmp_path)
    assert show is not None
    assert show.is_mock is None


@pytest.mark.parametrize("raw", ["not-a-boolean", 1, []])
def test_designer_benchmark_with_an_unreadable_is_mock_loads_as_unknown(
    tmp_path: Path, raw: object
) -> None:
    """An uninterpretable value is not evidence of a real run either."""
    _write_designer_results(tmp_path, {"validator": "boltz2", "is_mock": raw})
    show = showcase.load_designer_benchmark(root=tmp_path)
    assert show is not None
    assert show.is_mock is None


def test_designer_benchmark_with_an_explicit_false_is_a_real_run(tmp_path: Path) -> None:
    """The committed artifact states ``"is_mock": false``, and that still loads."""
    _write_designer_results(tmp_path, {"validator": "boltz2", "is_mock": False})
    show = showcase.load_designer_benchmark(root=tmp_path)
    assert show is not None
    assert show.is_mock is False


@pytest.fixture
def real_designer():
    """The committed designer benchmark, as the Results page loads it."""
    d = showcase.load_designer_benchmark()
    if d is None:
        pytest.skip("designer benchmark not available in this checkout")
    return d


def test_results_page_flags_unrecorded_provenance(monkeypatch, real_designer) -> None:
    """Unknown provenance must be stated, never rendered as "not a simulation"."""
    monkeypatch.setattr(
        showcase,
        "load_designer_benchmark",
        lambda: dataclasses.replace(real_designer, is_mock=None),
    )
    at = AppTest.from_file(str(APP), default_timeout=120)
    at.run()
    at.sidebar.radio[0].set_value("🔬 Real results").run()

    assert not at.exception
    warnings = " ".join(w.value for w in at.warning)
    body = " ".join(m.value for m in at.markdown)
    assert "Provenance unrecorded" in warnings
    assert "must not be cited as GPU results" in warnings
    assert "not a simulation" not in body

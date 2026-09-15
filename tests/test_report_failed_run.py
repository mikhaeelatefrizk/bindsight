# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A run that crashed must never be presented as a successful, empty result.

A pipeline that dies in DESeq2 leaves behind exactly the same artifacts as a
cohort that genuinely surfaced nothing: no candidates, no epitopes, zeroed
counts. Only ``run_manifest.jsonld`` separates them. Rendering the two alike
invites a scientist to read a crash as a negative finding — and then to act on
it by loosening thresholds that were never reached.

The defect was per-surface, so each surface carries its own guard. What is
covered here is ``report.html`` — the paper-style report that rendered a crash
as clean, zeroed KPIs — and the showcase loaders underneath it.

The final section pins the same principle one level up: a benchmark artifact
that never recorded whether it came from a GPU or the mock backend must load as
*unknown*, never as "real".

The Streamlit-specific half of this module moved to ``test_web_ui.py`` when
that interface was replaced. The properties came with it: a crashed run must
not be shown in the layout that means "completed and found nothing", a
manifest that cannot be read is ``None`` rather than empty, and a shapeless
manifest is tolerated. What stays here is what still exists -- the standalone
HTML report, and the showcase loaders both surfaces read.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from bindsight.provenance import StageRecord, ToolRef, new_manifest
from bindsight.report import html as report_html
from bindsight.report import showcase

#: The error a real crashed run records — pydeseq2 rejecting a normalised matrix.
DEG_ERROR = "ValueError: counts matrix contains non-integer values"


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
    """A run directory that genuinely finished and surfaced no candidates.

    It writes an **empty** candidates table rather than none at all, because
    that is what a completed discover produces: the write at
    ``bindsight/pipelines/discover.py`` is unconditional once the stage runs.
    The fixture used to omit the file, which is indistinguishable from a table
    that could not be read — and the report now says so, correctly, for that
    case. Omitting it here was testing the wrong finding.
    """
    import pandas as pd

    run = tmp_path / "empty_run"
    (run / "deg").mkdir(parents=True)
    (run / "targets").mkdir(parents=True)
    _deg_frame().to_parquet(run / "deg" / "results.parquet", index=False)
    pd.DataFrame(
        {"gene_id": [], "symbol": [], "uniprot_id": [], "log2fc": [], "padj": []}
    ).to_parquet(run / "targets" / "candidates.parquet", index=False)
    _completed_manifest().write(run / "run_manifest.jsonld")
    return run


# --------------------------------------------------------------------------- #
# L3 — the guard accepts both manifest shapes
# --------------------------------------------------------------------------- #
# --------------------------------------------------------------------------- #
# L3 — reading the manifest off disk
# --------------------------------------------------------------------------- #
# --------------------------------------------------------------------------- #
# L3 — _show_run_summary is the unbypassable guard
# --------------------------------------------------------------------------- #
# --------------------------------------------------------------------------- #
# L3 — the Browse page loads the manifest and routes it through the guard
# --------------------------------------------------------------------------- #
# --------------------------------------------------------------------------- #
# L3 — the standalone single-run viewer
# --------------------------------------------------------------------------- #
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


def test_report_for_an_unreadable_candidates_table_says_so(tmp_path: Path) -> None:
    """ "Could not be read" and "read, and empty" are different findings.

    A completed discover always writes candidates.parquet, so an absent or
    corrupt file means something went wrong — and the report told the reader
    "No candidates survived the filters. Loosen thresholds", which is a
    scientific conclusion drawn from a table nobody read.
    """
    run = _make_completed_empty_run(tmp_path)
    (run / "targets" / "candidates.parquet").write_bytes(b"not a parquet file")

    text = report_html.render_run(run).read_text(encoding="utf-8")

    assert "could not be read" in text
    assert "Loosen thresholds in the config and re-run." not in text, (
        "an unreadable table is reported as a filter that excluded everything"
    )


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

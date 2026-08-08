# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Degraded Open Targets enrichment must be visible on the run summary.

Open Targets is the only genome-wide Ensembl → UniProt source in the pipeline.
When it is unreachable — or was never enabled — the only mapping left is the
bundled table of a handful of well-known genes, so every other gene in the
cohort loses its accession and is dropped before the surfaceome filter. The
shortlist that survives is drawn from that fixed handful, not from the cohort.

Before the fix the "Run on my data" page built its config with
``use_open_targets=False``, so a stranger's real cohort could only ever yield a
"discovery" from the bundled table, and nothing on screen said so — the
``open_targets_status`` column was written by the pipeline and read by nobody.

These tests pin both halves: the page now asks for live enrichment, and
``_render_open_targets_warning`` says so loudly whenever it degrades.
"""

from __future__ import annotations

import contextlib
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd
import pytest

pytest.importorskip("streamlit")

from bindsight.report import webapp


def _candidates(*statuses: str) -> pd.DataFrame:
    """A candidates table carrying the enrichment-status column and a symbol."""
    return pd.DataFrame(
        {
            "symbol": [f"GENE{i}" for i in range(len(statuses))],
            "open_targets_status": list(statuses),
        }
    )


@pytest.fixture
def warnings(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Capture the body of every ``st.warning`` the module emits."""
    captured: list[str] = []
    monkeypatch.setattr(
        webapp,
        "st",
        SimpleNamespace(warning=lambda body, **kwargs: captured.append(str(body))),
    )
    return captured


# --------------------------------------------------------------------------- #
# L1 — the warning itself
# --------------------------------------------------------------------------- #
def test_no_warning_when_every_candidate_was_enriched_live(warnings) -> None:
    """A fully live enrichment is the normal case and must stay silent."""
    webapp._render_open_targets_warning(_candidates("ok", "ok", "ok"))
    assert warnings == []


def test_fully_degraded_run_is_declared_not_genome_wide(warnings) -> None:
    """Nothing came back live, so the shortlist is not a discovery at all."""
    webapp._render_open_targets_warning(_candidates("bundled_fallback", "no_record"))
    assert len(warnings) == 1
    msg = warnings[0]
    assert "not a genome-wide discovery" in msg
    assert "absence from it is no evidence" in msg
    # The count is named, not just the fact.
    assert "2 of 2 candidates" in msg
    assert "`bundled_fallback` × 1" in msg
    assert "`no_record` × 1" in msg


def test_offline_run_with_open_targets_skipped_is_also_not_genome_wide(warnings) -> None:
    """``skipped`` (Open Targets disabled) degrades exactly like an outage."""
    webapp._render_open_targets_warning(_candidates("skipped", "skipped", "skipped"))
    assert len(warnings) == 1
    assert "not a genome-wide discovery" in warnings[0]
    assert "`skipped` × 3" in warnings[0]


def test_partial_degradation_says_the_shortlist_is_incomplete(warnings) -> None:
    """Some genes mapped live, so the honest claim is weaker, not absent."""
    webapp._render_open_targets_warning(_candidates("ok", "ok", "error:ConnectionError"))
    assert len(warnings) == 1
    msg = warnings[0]
    assert "This shortlist is incomplete." in msg
    # Overstating the damage is its own dishonesty: most genes *were* mapped.
    assert "not a genome-wide discovery" not in msg
    assert "1 of 3 candidates" in msg
    assert "`error:ConnectionError` × 1" in msg


def test_no_warning_without_a_candidates_table(warnings) -> None:
    """A run that produced no candidates at all must not crash the summary."""
    webapp._render_open_targets_warning(None)
    assert warnings == []


def test_no_warning_when_the_status_column_is_absent(warnings) -> None:
    """An older run predates the column; unknown is reported by silence, not a claim."""
    webapp._render_open_targets_warning(pd.DataFrame({"symbol": ["ERBB2"], "rank": [1]}))
    assert warnings == []


# --------------------------------------------------------------------------- #
# L1 — the Run page asks for real, genome-wide enrichment
# --------------------------------------------------------------------------- #
def _upload(name: str, data: bytes) -> SimpleNamespace:
    """Stand in for a Streamlit ``UploadedFile``."""
    return SimpleNamespace(getvalue=lambda: data, name=name)


def test_run_page_enables_open_targets_for_uploaded_cohorts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The uploaded-cohort run must ask for live, genome-wide gene → protein mapping.

    With ``use_open_targets=False`` the whole upload path collapses onto the
    bundled 18-gene table, so this single flag is the difference between a real
    discovery and a fixed shortlist. No network is touched: the pipeline entry
    point is replaced with a recorder.
    """
    captured: dict[str, Any] = {}

    def _fake_pipeline_run(cfg: Any, *, out_dir: Path) -> Any:
        captured["cfg"] = cfg
        return SimpleNamespace(stages=[SimpleNamespace(name="deg", status="completed", error=None)])

    from bindsight.pipelines import discover as discover_pipeline

    monkeypatch.setattr(discover_pipeline, "run", _fake_pipeline_run)
    monkeypatch.setattr("bindsight.report.html.render_run", lambda d: Path(d) / "report.html")
    monkeypatch.setattr(webapp, "_show_run_summary", lambda *a, **k: None)
    monkeypatch.setattr("tempfile.mkdtemp", lambda **kwargs: str(tmp_path))

    counts = b"gene_id\tT1\tN1\nENSG00000141736\t180\t4\n"
    design = b"sample\tcondition\nT1\ttumor\nN1\tnormal\n"
    fake_st = SimpleNamespace(
        title=lambda *a, **k: None,
        markdown=lambda *a, **k: None,
        file_uploader=lambda label, **k: (
            _upload("counts.tsv", counts) if "Counts" in label else _upload("design.tsv", design)
        ),
        text_input=lambda label, default="", **k: default,
        number_input=lambda label, *a, **k: a[2],
        button=lambda *a, **k: True,
        spinner=lambda *a, **k: contextlib.nullcontext(),
        error=lambda *a, **k: None,
        success=lambda *a, **k: None,
        session_state={},
    )
    monkeypatch.setattr(webapp, "st", fake_st)

    webapp._page_run()

    cfg = captured["cfg"]
    assert cfg.params.target_discovery.use_open_targets is True
    # The contrast the form collected still reaches the pipeline unchanged.
    assert cfg.params.deg.contrast == ["condition", "tumor", "normal"]

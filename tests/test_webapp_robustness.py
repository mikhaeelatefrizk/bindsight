# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Robustness tests for the web app's failure and edge paths.

The smoke tests (``test_webapp_smoke.py``) prove every page *renders*. These
tests cover what a real visitor can trigger that a bare render does not:

* a pipeline stage that fails *without raising* must never be shown as success
  (the most dangerous failure mode — a broken run read as a real negative);
* a gzipped upload must be persisted so pandas can actually read it;
* a mock designer benchmark must never be labelled "not a simulation".
"""

from __future__ import annotations

import dataclasses
import gzip
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("streamlit")

from streamlit.testing.v1 import AppTest

from bindsight.report import webapp

APP = Path(__file__).resolve().parents[1] / "streamlit_app.py"


def _stage(name: str, status: str, error: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(name=name, status=status, error=error)


# --------------------------------------------------------------------------- #
# C1 — a failed stage is never a success
# --------------------------------------------------------------------------- #
def test_stage_failures_flags_failed_stage() -> None:
    manifest = SimpleNamespace(
        stages=[
            _stage("deg", "failed", "ValueError: non-integer counts"),
            _stage("discover", "running"),
        ]
    )
    failures = webapp._stage_failures(manifest)
    assert [n for n, _ in failures] == ["deg"]
    assert "non-integer" in failures[0][1]


def test_stage_failures_ignores_completed_and_cached() -> None:
    """A ``skipped_cache`` stage is a success, not a failure."""
    manifest = SimpleNamespace(
        stages=[_stage("deg", "completed"), _stage("discover", "skipped_cache")]
    )
    assert webapp._stage_failures(manifest) == []


def test_stage_failures_handles_none_manifest() -> None:
    assert webapp._stage_failures(None) == []


# --------------------------------------------------------------------------- #
# C3 — uploads preserve gzip compression
# --------------------------------------------------------------------------- #
def test_persist_upload_plain_tsv(tmp_path: Path) -> None:
    up = SimpleNamespace(getvalue=lambda: b"gene\ts1\nENSG1\t5\n", name="counts.tsv")
    path = webapp._persist_upload(up, tmp_path, "counts")
    assert path.name == "counts.tsv"
    assert path.read_bytes().startswith(b"gene")


def test_persist_upload_gzip_by_magic_bytes(tmp_path: Path) -> None:
    """Even if named .tsv, gzip content is stored as .tsv.gz so pandas infers it."""
    raw = gzip.compress(b"gene\ts1\nENSG1\t5\n")
    up = SimpleNamespace(getvalue=lambda: raw, name="counts.tsv")
    path = webapp._persist_upload(up, tmp_path, "counts")
    assert path.name == "counts.tsv.gz"
    # Round-trips through pandas' compression inference.
    import pandas as pd

    df = pd.read_csv(path, sep="\t", compression="infer")
    assert list(df.columns) == ["gene", "s1"]


def test_persist_upload_gz_by_name(tmp_path: Path) -> None:
    raw = gzip.compress(b"x\n")
    up = SimpleNamespace(getvalue=lambda: raw, name="counts.TSV.GZ")
    path = webapp._persist_upload(up, tmp_path, "counts")
    assert path.name == "counts.tsv.gz"


# --------------------------------------------------------------------------- #
# C4 — a mock benchmark is never labelled "not a simulation"
# --------------------------------------------------------------------------- #
@pytest.fixture
def real_designer():
    from bindsight.report import showcase

    d = showcase.load_designer_benchmark()
    if d is None:
        pytest.skip("designer benchmark not available in this checkout")
    return d


def test_results_labels_real_run_as_not_simulation(monkeypatch, real_designer) -> None:
    from bindsight.report import showcase

    monkeypatch.setattr(
        showcase,
        "load_designer_benchmark",
        lambda: dataclasses.replace(real_designer, is_mock=False),
    )
    at = AppTest.from_file(str(APP), default_timeout=120)
    at.run()
    at.sidebar.radio[0].set_value("🔬 Real results").run()
    text = " ".join(m.value for m in at.markdown)
    assert "not a simulation" in text


def test_results_labels_mock_run_as_mock(monkeypatch, real_designer) -> None:
    from bindsight.report import showcase

    monkeypatch.setattr(
        showcase,
        "load_designer_benchmark",
        lambda: dataclasses.replace(real_designer, is_mock=True),
    )
    at = AppTest.from_file(str(APP), default_timeout=120)
    at.run()
    at.sidebar.radio[0].set_value("🔬 Real results").run()
    assert not at.exception
    warnings = " ".join(w.value for w in at.warning)
    body = " ".join(m.value for m in at.markdown)
    assert "Mock backend" in warnings
    assert "not a simulation" not in body

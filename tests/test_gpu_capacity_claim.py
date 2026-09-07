# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The published VRAM figure must be the one in the committed kernel log.

The docs carried "~16 GB" for the free arm, which was an estimate wearing a
number's clothes. Worse, the instrumentation that was supposed to replace it
reported 0 MiB for every stage of a 3h49m GPU run, so the first attempt at a
measurement would have been a fabrication had anyone quoted it.

There is now a real measurement and a committed log behind it. These tests tie
the two together, so the prose cannot drift from the artifact and the artifact
cannot quietly disappear.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
LOG = REPO / "benchmarks" / "gpu_capacity" / "t4-ca9-377aa.log"
CAPACITY_README = REPO / "benchmarks" / "gpu_capacity" / "README.md"
RUN_FREE_GPU = REPO / "benchmarks" / "designer_benchmark" / "RUN_FREE_GPU.md"


def _peak_mib() -> int:
    """The high-water mark the sampler actually recorded, read from the log."""
    peaks: list[int] = []
    for line in LOG.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip().lstrip(",")
        if not line.startswith("{"):
            continue
        try:
            data = json.loads(line).get("data", "")
        except json.JSONDecodeError:
            continue
        if "peak so far" in data:
            peaks.append(int(data.split("peak so far ", 1)[1].split(" MiB", 1)[0]))
    assert peaks, "the committed log records no VRAM samples at all"
    return max(peaks)


def test_the_log_is_committed() -> None:
    """A number without its artifact is an estimate again."""
    assert LOG.is_file(), "the kernel log backing the VRAM figure is missing"
    assert LOG.stat().st_size > 10_000


def test_the_log_records_a_real_measurement() -> None:
    """0 MiB across a GPU run is what the old instrumentation reported."""
    peak = _peak_mib()
    assert peak > 1_000, f"peak of {peak} MiB is not a plausible measurement"
    assert peak <= 15_360, f"peak of {peak} MiB exceeds the T4's memory"


def test_the_log_names_the_card_it_was_measured_on() -> None:
    """The card is part of the measurement, not context for it."""
    text = LOG.read_text(encoding="utf-8", errors="replace")
    assert "Tesla T4" in text
    assert "15360" in text


@pytest.mark.parametrize("doc", [CAPACITY_README, RUN_FREE_GPU])
def test_the_published_figure_matches_the_log(doc: Path) -> None:
    peak = _peak_mib()
    text = doc.read_text(encoding="utf-8")
    assert f"{peak:,}" in text or str(peak) in text, (
        f"{doc.name} does not state the measured peak of {peak:,} MiB"
    )


def test_the_prose_does_not_present_the_measurement_as_comfortable() -> None:
    """97% of the card is the finding; a reader must not be told it fits easily."""
    peak = _peak_mib()
    pct = round(peak / 15_360 * 100)
    text = CAPACITY_README.read_text(encoding="utf-8")
    assert f"{pct}%" in text, f"the capacity note does not state the {pct}% it measured"


def test_the_unmeasured_designers_are_still_marked_as_estimates() -> None:
    """One measurement must not launder the two figures beside it."""
    text = RUN_FREE_GPU.read_text(encoding="utf-8")
    for designer in ("boltzgen", "bindcraft"):
        row = next(ln for ln in text.splitlines() if f"`{designer}`" in ln and "GB" in ln)
        assert "estimate" in row.lower(), (
            f"the {designer} VRAM figure is presented without saying it is an estimate"
        )


def test_the_measured_target_size_travels_with_the_number() -> None:
    """Attention memory grows with length, so 14.9 GB is meaningless unqualified."""
    text = CAPACITY_README.read_text(encoding="utf-8")
    assert "377" in text, "the capacity note does not say what size was measured"
    assert re.search(r"larger.{0,200}exhaust", text, re.IGNORECASE | re.DOTALL), (
        "the note does not warn that a larger target may exhaust the card"
    )

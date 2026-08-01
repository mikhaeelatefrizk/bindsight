# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The ``--cheap`` profile and the ESM-2 pre-screen it enables.

ARCHITECTURE.md §10 specified the profile as "RFdiff+MPNN on T4, 10
trajectories, ESM-2 pre-screen". The flag was accepted by Click, bound to a
parameter, and then never referenced: a user asking for the cheap profile got
the full-price run, and ``--dry-run`` quoted A100 pricing for it.

The pre-screen is the part that can change scientific output, so it is tested
hardest: off by default, deterministic, order-preserving, and degrading to
"validate everything" rather than losing an already-successful GPU run.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from click.testing import CliRunner

from bindsight.cli import (
    CHEAP_GPU_TYPE,
    CHEAP_PRESCREEN_TOP_K,
    CHEAP_TRAJECTORIES,
    _apply_cheap_profile,
    main,
)
from bindsight.config import RunConfig
from bindsight.design.prescreen import prescreen_report, select_representative
from bindsight.runners.job_exec import _apply_prescreen

CONFIG = "examples/demo/config.yaml"


# ---------------------------------------------------------------------------
# Profile application
# ---------------------------------------------------------------------------
def test_profile_sets_every_documented_field() -> None:
    """All three parts of the documented profile take effect."""
    cfg = RunConfig.from_yaml(CONFIG)
    _apply_cheap_profile(cfg)

    design = cfg.params.design
    assert design.designer == "rfdiff_mpnn"
    assert design.n_trajectories == CHEAP_TRAJECTORIES
    assert design.gpu_type == CHEAP_GPU_TYPE
    assert design.prescreen_top_k == CHEAP_PRESCREEN_TOP_K


def test_defaults_are_untouched_without_the_flag() -> None:
    """A normal run keeps the expensive-but-thorough defaults."""
    design = RunConfig.from_yaml(CONFIG).params.design
    assert design.n_trajectories == 50
    assert design.gpu_type is None
    assert design.prescreen_top_k is None


def test_cheap_dry_run_costs_less_than_the_default(tmp_path) -> None:
    """The estimate reflects the profile, on a backend that actually charges.

    Previously ``--cheap`` was ignored entirely, so both invocations printed
    the same A100 figure.
    """
    cfg_path = tmp_path / "modal.yaml"
    cfg_path.write_text(
        Path(CONFIG).read_text(encoding="utf-8").replace("backend: colab", "backend: modal"),
        encoding="utf-8",
    )
    runner = CliRunner()
    base = runner.invoke(main, ["run", str(cfg_path), "--out", str(tmp_path / "o"), "--dry-run"])
    cheap = runner.invoke(
        main, ["run", str(cfg_path), "--out", str(tmp_path / "o"), "--cheap", "--dry-run"]
    )

    assert base.exit_code == 0, base.output
    assert cheap.exit_code == 0, cheap.output
    assert "A100" in base.output
    assert "T4" in cheap.output
    assert _usd(cheap.output) < _usd(base.output)


def _usd(output: str) -> float:
    """Pull the dollar figure out of a rendered cost panel."""
    import re

    m = re.search(r"\$([\d,]+\.\d+)", output)
    assert m, f"no USD figure in output:\n{output}"
    return float(m.group(1).replace(",", ""))


# ---------------------------------------------------------------------------
# Pre-screen selection
# ---------------------------------------------------------------------------
@pytest.fixture
def _fake_embeddings(monkeypatch):
    """Deterministic 1-D embeddings so selection is exactly predictable.

    Sequence length stands in for position, which makes "closest to the
    centroid" something the test can compute by hand.
    """

    def _embed(sequences, **_kwargs):
        return np.array([[float(len(s))] for s in sequences])

    monkeypatch.setattr("bindsight.design.embeddings.esm2_embed", _embed)


def test_no_top_k_keeps_everything() -> None:
    """Default behaviour is bit-identical to having no screen at all."""
    result = select_representative(["AAA", "BBBB"], None)
    assert result.applied is False
    assert result.kept == [0, 1]
    assert result.dropped == []


def test_top_k_at_or_above_batch_size_is_a_no_op() -> None:
    """Nothing is dropped when there is nothing to gain."""
    assert select_representative(["AA", "BB"], 5).applied is False


@pytest.mark.usefixtures("_fake_embeddings")
def test_keeps_the_designs_nearest_the_centroid() -> None:
    """Outliers are screened out; representative designs survive."""
    seqs = ["A" * 10, "A" * 11, "A" * 12, "A" * 100]
    result = select_representative(seqs, 3)

    assert result.applied is True
    assert result.kept == [0, 1, 2]
    assert result.dropped == [3]


@pytest.mark.usefixtures("_fake_embeddings")
def test_kept_indices_preserve_design_order() -> None:
    """Selection must not reorder designs; downstream output depends on it."""
    seqs = ["A" * n for n in (50, 1, 51, 2, 49)]
    result = select_representative(seqs, 3)
    assert result.kept == sorted(result.kept)


@pytest.mark.usefixtures("_fake_embeddings")
def test_selection_is_deterministic() -> None:
    """The same batch always yields the same selection."""
    seqs = ["A" * n for n in (10, 20, 30, 40, 50)]
    first = select_representative(seqs, 2)
    second = select_representative(seqs, 2)
    assert first.kept == second.kept


def test_missing_embed_extra_keeps_everything(monkeypatch) -> None:
    """A missing optional dependency must not lose a successful GPU run."""

    def _boom(*_a, **_k):
        raise ImportError("no torch")

    monkeypatch.setattr("bindsight.design.embeddings.esm2_embed", _boom)
    result = select_representative(["AAA", "BBB", "CCC"], 1)
    assert result.applied is False
    assert result.kept == [0, 1, 2]


def test_embedding_failure_keeps_everything(monkeypatch) -> None:
    """Any embedding error degrades to validating everything."""

    def _boom(*_a, **_k):
        raise RuntimeError("CUDA out of memory")

    monkeypatch.setattr("bindsight.design.embeddings.esm2_embed", _boom)
    result = select_representative(["AAA", "BBB", "CCC"], 1)
    assert result.applied is False
    assert "CUDA out of memory" in result.reason


def test_empty_sequence_disables_the_screen() -> None:
    """A malformed design set is not silently pruned."""
    assert select_representative(["AAA", ""], 1).applied is False


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------
@pytest.mark.usefixtures("_fake_embeddings")
def test_report_names_what_was_dropped() -> None:
    """Screened-out designs are recorded, not silently discarded."""
    seqs = ["A" * 10, "A" * 11, "A" * 100]
    result = select_representative(seqs, 2)
    note = prescreen_report(result, ["b0", "b1", "b2"])
    assert "validated 2 of 3" in note
    assert "b2" in note


def test_report_is_explicit_when_not_applied() -> None:
    """A skipped screen says so rather than implying filtering happened."""
    result = select_representative(["A", "B"], None)
    assert "not applied" in prescreen_report(result, ["b0", "b1"])


# ---------------------------------------------------------------------------
# Executor integration — the seam where GPU is actually saved
# ---------------------------------------------------------------------------
class _Design:
    """Stand-in for runners.job_exec.Design."""

    def __init__(self, binder_id: str, sequence: str) -> None:
        self.binder_id = binder_id
        self.sequence = sequence


@pytest.mark.usefixtures("_fake_embeddings")
def test_executor_screens_between_design_and_validation() -> None:
    """The screen runs before the validator, which is what saves GPU."""
    designs = [_Design(f"b{i}", "A" * n) for i, n in enumerate((10, 11, 12, 100))]
    kept, note = _apply_prescreen({"extra_params": {"prescreen_top_k": 3}}, designs)

    assert [d.binder_id for d in kept] == ["b0", "b1", "b2"]
    assert note is not None
    assert "b3" in note


def test_executor_is_a_no_op_without_the_setting() -> None:
    """No spec setting means every design is validated, as before."""
    designs = [_Design("b0", "AAA"), _Design("b1", "BBB")]
    kept, note = _apply_prescreen({"extra_params": {}}, designs)
    assert kept == designs
    assert note is None


@pytest.mark.parametrize("bad", ["not-a-number", None, 0, ""])
def test_executor_ignores_unusable_settings(bad) -> None:
    """A malformed setting never drops designs."""
    designs = [_Design("b0", "AAA"), _Design("b1", "BBB")]
    kept, _ = _apply_prescreen({"extra_params": {"prescreen_top_k": bad}}, designs)
    assert kept == designs

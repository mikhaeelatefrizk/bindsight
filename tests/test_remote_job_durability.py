# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A remote job must survive the client that launched it.

A GPU job outlives its client process. When the client dies mid-wait, the job
keeps running and keeps spending a fixed weekly quota, but nothing is left that
knows how to collect its output. Two defects made that outcome routine, and both
were observed rather than theorised: a dropped TLS handshake during a routine
poll ended the client for a design job two and a half hours into a T4, and
because no record tied the running kernel to its cache entry, the obvious
recovery -- rerun the command -- would have pushed a *second* kernel and
orphaned the first for good.

These tests pin both halves: a poll failure means "ask again", and a launched
job is recorded before it is waited on, so a crashed wait reattaches instead of
resubmitting.
"""

from __future__ import annotations

import json
import tarfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from bindsight.design._common import submit_via_runner
from bindsight.design.protocol import DesignSpec
from bindsight.runners import kaggle
from bindsight.runners.protocol import JobHandle, JobStatus

_HANDLE = JobHandle(backend="kaggle", id="owner/bindsight-abc", submitted_at="2026-09-07T16:52:00")


def _runner(monkeypatch: pytest.MonkeyPatch) -> kaggle.KaggleRunner:
    """A KaggleRunner whose sleeps are instant and whose client is never built."""
    monkeypatch.setattr(kaggle.time, "sleep", lambda _s: None)
    monkeypatch.setattr(kaggle, "_require_kaggle", lambda: SimpleNamespace())
    return kaggle.KaggleRunner(poll_interval_s=0)


def _boom(_handle: Any) -> Path:
    """Stand in for a client that dies after launching but before staging."""
    raise OSError("client died")


class TestPollingSurvivesTheNetwork:
    """One dropped connection must not abandon hours of GPU work."""

    def test_a_transient_poll_failure_is_retried_not_fatal(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        runner = _runner(monkeypatch)
        # The exact shape of the incident: a blip, progress, another blip, done.
        script: list[Any] = [
            OSError("EOF occurred in violation of protocol"),
            "running",
            OSError("connection reset"),
            "succeeded",
        ]
        seen: list[Any] = []

        def fake_poll(handle: JobHandle) -> JobStatus:
            item = script[len(seen)]
            seen.append(item)
            if isinstance(item, Exception):
                raise item
            return JobStatus(handle=handle, state=item)

        monkeypatch.setattr(runner, "poll", fake_poll)
        assert runner._await_terminal(_HANDLE).state == "succeeded"
        assert len(seen) == 4, "every poll, including the failures, must be attempted"

    def test_a_sustained_outage_gives_up_and_names_the_reattach_path(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        runner = _runner(monkeypatch)
        attempts = 0

        def always_fails(handle: JobHandle) -> JobStatus:
            nonlocal attempts
            attempts += 1
            raise OSError("network is down")

        monkeypatch.setattr(runner, "poll", always_fails)
        with pytest.raises(RuntimeError, match="reattach"):
            runner._await_terminal(_HANDLE)
        assert attempts == kaggle._POLL_FAILURE_LIMIT

    def test_a_missing_kaggle_client_is_not_retried(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """No amount of retrying installs a package, so fail fast on that one."""
        runner = _runner(monkeypatch)
        attempts = 0

        def unavailable(handle: JobHandle) -> JobStatus:
            nonlocal attempts
            attempts += 1
            raise kaggle.KaggleUnavailable("needs the runners extra")

        monkeypatch.setattr(runner, "poll", unavailable)
        with pytest.raises(kaggle.KaggleUnavailable):
            runner._await_terminal(_HANDLE)
        assert attempts == 1

    def test_the_client_authenticates_once_not_once_per_poll(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """authenticate() is a network call; doing it per poll was the root enabler."""
        built = 0

        def build() -> SimpleNamespace:
            nonlocal built
            built += 1
            return SimpleNamespace()

        monkeypatch.setattr(kaggle, "_require_kaggle", build)
        runner = kaggle.KaggleRunner()
        for _ in range(5):
            runner._api()
        assert built == 1
        # A failed poll drops the client, so a stale session can be recovered.
        runner._reset_api()
        runner._api()
        assert built == 2


class _RecordingRunner:
    """GPURunner double that counts submissions and reports a scripted state."""

    name = "recording"

    def __init__(
        self,
        archive: Path,
        state: str = "running",
        poll_raises: bool = False,
        id_prefix: str = "job",
    ) -> None:
        self.archive = archive
        self.id_prefix = id_prefix
        self.state = state
        self.poll_raises = poll_raises
        self.submits = 0
        self.fetched: list[str] = []

    def estimate_cost(self, spec_size: int) -> Any:  # pragma: no cover - unused
        raise NotImplementedError

    def submit(self, spec_path: Path, *, results_dir: Path) -> Any:
        self.submits += 1
        results_dir.mkdir(parents=True, exist_ok=True)
        return JobHandle(
            backend=self.name,
            id=f"{self.id_prefix}-{self.submits}",
            submitted_at="2026-09-07T16:52:00",
        )

    def poll(self, handle: JobHandle) -> JobStatus:
        if self.poll_raises:
            raise OSError("cannot reach the API")
        return JobStatus(handle=handle, state=self.state)  # type: ignore[arg-type]

    def fetch(self, handle: JobHandle) -> Path:
        self.fetched.append(handle.id)
        return self.archive


def _archive(tmp_path: Path) -> Path:
    metrics = tmp_path / "metrics.jsonl"
    metrics.write_text(json.dumps({"binder_id": "b0", "iptm": 0.7}) + "\n")
    archive = tmp_path / "results.tar.gz"
    with tarfile.open(archive, "w:gz") as tf:
        tf.add(metrics, arcname="metrics.jsonl")
    return archive


def _spec(tmp_path: Path) -> DesignSpec:
    structure = tmp_path / "target.pdb"
    structure.write_text("ATOM      1  CA  MET A   1       0.0   0.0   0.0  1.0  0.0           C\n")
    return DesignSpec(
        target_uniprot="Q16790",
        target_structure_path=str(structure),
        epitope_chain="A",
        epitope_residues=[1, 2, 3],
        design_ranges=[(38, 414)],
        n_trajectories=10,
        seed=0,
        extra_params={"designer": "rfdiff_mpnn"},
    )


def _submit(spec: DesignSpec, runner: Any, key: str) -> Any:
    return submit_via_runner(
        spec,
        runner,
        designer_name="rfdiff_mpnn",
        designer_version="0.1.0",
        designer_commit_sha=None,
        cache_key=key,
    )


class TestACrashedClientReattaches:
    """The recovery path that was missing when a poll killed a live T4 job."""

    def test_a_launched_job_is_recorded_before_it_is_waited_on(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        runner = _RecordingRunner(_archive(tmp_path))
        _submit(_spec(tmp_path), runner, "k" * 64)
        records = list(Path("runs/_design").rglob("handle.json"))
        assert len(records) == 1, "a launched job must leave a record to reattach to"
        assert json.loads(records[0].read_text())["id"] == "job-1"

    def test_a_still_running_job_is_reattached_not_resubmitted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The incident, in miniature: rerunning must not push a second kernel."""
        monkeypatch.chdir(tmp_path)
        spec, key = _spec(tmp_path), "k" * 64
        archive = _archive(tmp_path)

        # First client launches, then dies before staging anything.
        crashed = _RecordingRunner(archive, state="running")
        crashed.fetch = _boom  # type: ignore[method-assign]
        with pytest.raises(OSError, match="client died"):
            _submit(spec, crashed, key)
        assert crashed.submits == 1

        # Second client finds the record and picks the same job back up.
        resumed = _RecordingRunner(archive, state="running")
        _submit(spec, resumed, key)
        assert resumed.submits == 0, "reran against a live job; it must not resubmit"
        assert resumed.fetched == ["job-1"], "must have waited on the original job"

    def test_an_undeterminable_state_reattaches_rather_than_paying_twice(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Unknown is not dead. Resubmitting a live job costs hours; a poll costs nothing."""
        monkeypatch.chdir(tmp_path)
        spec, key = _spec(tmp_path), "k" * 64
        archive = _archive(tmp_path)

        first = _RecordingRunner(archive, state="running")
        first.fetch = _boom  # type: ignore[method-assign]
        with pytest.raises(OSError, match="client died"):
            _submit(spec, first, key)

        blind = _RecordingRunner(archive, poll_raises=True)
        _submit(spec, blind, key)
        assert blind.submits == 0
        assert blind.fetched == ["job-1"]

    def test_a_job_that_ended_badly_is_cleared_and_resubmitted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Reattaching forever to a dead job would be its own trap."""
        monkeypatch.chdir(tmp_path)
        spec, key = _spec(tmp_path), "k" * 64
        archive = _archive(tmp_path)

        first = _RecordingRunner(archive, state="running")
        first.fetch = _boom  # type: ignore[method-assign]
        with pytest.raises(OSError, match="client died"):
            _submit(spec, first, key)

        retried = _RecordingRunner(archive, state="failed", id_prefix="fresh")
        _submit(spec, retried, key)
        assert retried.submits == 1, "a failed job must not block a fresh submission"
        assert retried.fetched == ["fresh-1"], "must have waited on the new job, not the dead one"

    def test_recording_a_handle_never_fails_a_launched_job(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Raising here would abort a run with a kernel already burning quota."""
        monkeypatch.chdir(tmp_path)

        class _DictRunner(_RecordingRunner):
            def submit(self, spec_path: Path, *, results_dir: Path) -> Any:
                self.submits += 1
                results_dir.mkdir(parents=True, exist_ok=True)
                return {"id": "not-a-handle"}

            def fetch(self, handle: Any) -> Path:
                return self.archive

        runner = _DictRunner(_archive(tmp_path))
        result = _submit(_spec(tmp_path), runner, "k" * 64)
        assert result.cache_status == "miss"
        assert runner.submits == 1

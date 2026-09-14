# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Mock GPU runner for CI.

Returns canned-but-realistically-shaped results immediately so CI (and the
Snakemake DAG / ``bindsight run --backend mock``) can exercise the full
orchestration — design → validate → rank → report → export — end-to-end without
a real GPU. The numeric values are clearly labelled as synthetic.
"""

from __future__ import annotations

import json
import logging
import shutil
import tarfile
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path

from bindsight.runners.protocol import CostEstimate, JobHandle, JobStatus

# A minimal valid PDB (3 CA atoms) so downstream parsers have something real.
LOG = logging.getLogger(__name__)

_MOCK_PDB = (
    "ATOM      1  CA  GLY A   1      0.000   0.000   0.000  1.00  0.00           C\n"
    "ATOM      2  CA  SER A   2      3.800   0.000   0.000  1.00  0.00           C\n"
    "ATOM      3  CA  HIS A   3      7.600   0.000   0.000  1.00  0.00           C\n"
    "END\n"
)


class MockRunner:
    """Returns a canned tarball of fake results."""

    name = "mock"

    def __init__(self, canned_archive: Path | None = None) -> None:
        self.canned = canned_archive
        # handle id -> target accession, so fetch() can namespace binder ids.
        self._targets: dict[str, str] = {}

    def estimate_cost(self, spec_size: int) -> CostEstimate:
        """Return a zero-cost estimate; the mock runner never spends money."""
        return CostEstimate(
            backend=self.name,
            gpu_type="mock",
            gpu_hours=0.0,
            usd_estimate=0.0,
            queue_minutes_estimate=0.0,
            notes="Mock runner — no real compute.",
        )

    def submit(self, spec_path: Path, *, results_dir: Path) -> JobHandle:
        """Pretend to submit a job; returns a unique handle immediately.

        The spec's target is recorded against the handle so :meth:`fetch` can
        namespace the binder ids it invents. A mock that returns the same ids for
        every target cannot exercise the invariant that binder ids are unique
        across a run — and that is exactly the bug this mock is meant to catch,
        since ``binder_id`` is the key the provenance chain is walked by.
        """
        results_dir.mkdir(parents=True, exist_ok=True)
        handle_id = str(uuid.uuid4())
        target = "MOCK"
        try:
            spec = json.loads(Path(spec_path).read_text(encoding="utf-8"))
            target = str(spec.get("target_uniprot") or "MOCK")
        except (OSError, ValueError) as e:  # a malformed spec must not break CI
            LOG.warning("mock runner could not read %s: %s", spec_path, e)
        self._targets[handle_id] = target
        return JobHandle(
            backend=self.name,
            id=handle_id,
            submitted_at=datetime.now(UTC).isoformat(timespec="seconds"),
        )

    def poll(self, handle: JobHandle) -> JobStatus:
        """Always report 'succeeded' immediately."""
        return JobStatus(handle=handle, state="succeeded", progress=1.0, log_tail=None)

    def fetch(self, handle: JobHandle) -> Path:
        """Return the canned archive, or build a realistically-shaped mock one.

        The mock tarball mirrors what :mod:`bindsight.runners.job_exec` produces
        (``metrics.jsonl`` + ``validate/<binder>/`` JSONs + ``design/<binder>``),
        with clearly-synthetic numbers, so the whole orchestration runs E2E.

        Binder ids carry the target accession, exactly as the real executor's do.
        Without that, a multi-target run produces the same ids for every target,
        the per-binder validation directories overwrite each other on disk, and
        ``validated.parquet`` acquires duplicate keys — a mock that permits the
        bug it is supposed to guard against is worse than no mock.
        """
        if self.canned is not None:
            return self.canned
        target = self._targets.get(handle.id, "MOCK")
        root = Path(tempfile.mkdtemp(prefix="bindsight_mock_"))
        work = root / "work"
        design = work / "design"
        validate = work / "validate"
        design.mkdir(parents=True, exist_ok=True)

        metrics = []
        for i in range(2):
            bid = f"{target}_mock_binder_{i}"
            (design / f"{bid}.pdb").write_text(_MOCK_PDB, encoding="utf-8", newline="\n")
            (design / f"{bid}.fasta").write_text(
                f">{bid}\nGSHMSLEQKKGADIISKIL\n", encoding="utf-8", newline="\n"
            )
            vdir = validate / bid
            vdir.mkdir(parents=True, exist_ok=True)
            (vdir / f"confidence_{bid}_model_0.json").write_text(
                json.dumps({"iptm": 0.70 + 0.05 * i, "pae_interaction": 6.0 - i}),
                encoding="utf-8",
                newline="\n",
            )
            (vdir / f"affinity_{bid}.json").write_text(
                json.dumps({"affinity_pred_value": -7.0 - i, "affinity_probability_binary": 0.80}),
                encoding="utf-8",
                newline="\n",
            )
            metrics.append(
                {
                    "binder_id": bid,
                    "target_uniprot": target,
                    "iptm": 0.70 + 0.05 * i,
                    "pae_interaction": 6.0 - i,
                    "affinity_pred_value": -7.0 - i,
                    "affinity_probability_binary": 0.80,
                    "validator_name": "mock",
                    "validator_version": "0",
                    "notes": "mock runner — synthetic metrics for CI/orchestration only",
                }
            )
        (work / "metrics.jsonl").write_text(
            "\n".join(json.dumps(m) for m in metrics) + "\n", encoding="utf-8", newline="\n"
        )

        tarball = root / "results.tar.gz"
        with tarfile.open(tarball, "w:gz", encoding="utf-8") as tf:
            for sub in ("design", "validate", "metrics.jsonl"):
                tf.add(work / sub, arcname=sub)
        return tarball

    @staticmethod
    def cleanup(path: Path) -> None:
        """Remove a temp directory created by :meth:`fetch`."""
        if path.parent.name.startswith("bindsight_mock_"):
            shutil.rmtree(path.parent, ignore_errors=True)

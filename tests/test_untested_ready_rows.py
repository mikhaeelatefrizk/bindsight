# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Three rows the README marks ready had no test at all.

`validate --revalidate` is roughly 110 lines of CLI and `_launch_revalidate`,
and `grep -rn revalidate tests/` returned nothing. `bindsight ui` and
`report --format streamlit` are the "How to try" instruction for two more ready
rows and neither had a CLI-level test, so the entrypoint resolution and the
missing-Streamlit path could both break silently.

Nothing here launches Streamlit or a GPU: the subprocess seam and the submit
seam are patched, and what is asserted is the command assembled and the spec
shipped.
"""

from __future__ import annotations

import json
import tarfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd
import pytest
from click.testing import CliRunner

from bindsight import cli


def _run_dir(tmp_path: Path, *, with_designs: bool = True, fastas: bool = True) -> Path:
    """A run with one top target and, optionally, a design tarball to rescore."""
    run = tmp_path / "run"
    (run / "epitopes").mkdir(parents=True)
    structure = run / "target.pdb"
    structure.write_text("ATOM      1  CA  MET A   1       0.0   0.0   0.0  1.0  0.0           C\n")
    pd.DataFrame(
        [
            {
                "uniprot_id": "Q16790",
                "structure_path": str(structure),
                "chain": "A",
                "residues": [1, 2, 3],
                "design_ranges": [[38, 414]],
            }
        ]
    ).to_parquet(run / "epitopes" / "epitopes.parquet")

    if with_designs:
        targets = run / "design" / "_targets"
        targets.mkdir(parents=True)
        staging = tmp_path / "staging"
        (staging / "design").mkdir(parents=True)
        if fastas:
            (staging / "design" / "Q16790_binder_0_seq0.fasta").write_text(
                ">Q16790_binder_0_seq0\nMKTAYIAKQRQISFVKSHFSRQ\n"
            )
        else:
            (staging / "design" / "notes.txt").write_text("no designs here\n")
        with tarfile.open(targets / "Q16790.tar.gz", "w:gz") as tf:
            tf.add(staging / "design", arcname="design")
    return run


class TestRevalidateShipsTheBindersNotANewDesign:
    """The point of --revalidate is a second opinion on the *same* binders."""

    @staticmethod
    def _capture(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[dict[str, Any]]:
        """Patch the submit seam and record what each call was given."""
        from bindsight.design import _common

        calls: list[dict[str, Any]] = []
        metrics = tmp_path / "revalidated.jsonl"
        metrics.write_text(json.dumps({"binder_id": "b0", "iptm": 0.71}) + "\n")
        archive = tmp_path / "revalidated.tar.gz"
        # The returned archive carries the designs back, as a real executor's
        # does. It matters: _launch_revalidate overwrites the per-target tarball
        # with whatever it is handed, so an archive without them destroys the
        # binders a second opinion would have rescored.
        fasta = tmp_path / "Q16790_binder_0_seq0.fasta"
        fasta.write_text(">Q16790_binder_0_seq0\nMKTAYIAKQRQISFVKSHFSRQ\n")
        with tarfile.open(archive, "w:gz") as tf:
            tf.add(metrics, arcname="metrics.jsonl")
            tf.add(fasta, arcname="design/Q16790_binder_0_seq0.fasta")

        def fake_submit(spec: Any, runner: Any, **kw: Any) -> Any:
            payload = kw.get("payload_dir")
            calls.append(
                {
                    "spec": spec,
                    "cache_key": kw.get("cache_key"),
                    "designer_name": kw.get("designer_name"),
                    "payload_files": sorted(p.name for p in Path(payload).iterdir())
                    if payload
                    else [],
                }
            )
            return SimpleNamespace(
                results_archive_path=str(archive), metrics_jsonl_path=str(metrics)
            )

        monkeypatch.setattr(_common, "submit_via_runner", fake_submit)
        return calls

    def test_no_designer_runs(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """`mode: validate_only` is what makes this one pass instead of a redesign."""
        calls = self._capture(monkeypatch, tmp_path)
        run = _run_dir(tmp_path)
        done = cli._launch_revalidate(run, backend="mock", validator="chai1r")
        assert done == 1
        assert len(calls) == 1
        spec = calls[0]["spec"]
        assert spec.extra_params["mode"] == "validate_only"
        assert spec.extra_params["validator"] == "chai1r"
        assert spec.n_trajectories == 1, "a revalidation must not ask for trajectories"

    def test_the_existing_designs_travel_with_the_spec(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Without the payload the GPU has nothing to rescore."""
        calls = self._capture(monkeypatch, tmp_path)
        cli._launch_revalidate(_run_dir(tmp_path), backend="mock", validator="boltz2")
        assert calls[0]["payload_files"] == ["Q16790_binder_0_seq0.fasta"]

    def test_two_validators_do_not_share_a_cache_entry(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Otherwise the second run returns the first's numbers under its name."""
        run = _run_dir(tmp_path)
        keys = set()
        for validator in ("boltz2", "chai1r"):
            calls = self._capture(monkeypatch, tmp_path)
            cli._launch_revalidate(run, backend="mock", validator=validator)
            keys.add(calls[0]["cache_key"])
        assert len(keys) == 2, "the validator must be part of the key it is cached under"

    def test_the_provenance_names_the_revalidation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = self._capture(monkeypatch, tmp_path)
        cli._launch_revalidate(_run_dir(tmp_path), backend="mock", validator="af2_ig")
        assert calls[0]["designer_name"] == "revalidate:af2_ig"

    def test_the_new_metrics_are_written_back(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._capture(monkeypatch, tmp_path)
        run = _run_dir(tmp_path)
        cli._launch_revalidate(run, backend="mock", validator="boltz2")
        rows = [
            json.loads(line)
            for line in (run / "design" / "metrics.jsonl").read_text().splitlines()
            if line.strip()
        ]
        assert [r["binder_id"] for r in rows] == ["b0"]

    def test_a_target_with_no_tarball_is_skipped_not_fatal(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = self._capture(monkeypatch, tmp_path)
        run = _run_dir(tmp_path, with_designs=False)
        assert cli._launch_revalidate(run, backend="mock", validator="boltz2") == 0
        assert calls == []

    def test_a_tarball_carrying_no_designs_is_skipped(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An archive without a FASTA has nothing to rescore; sending it wastes GPU."""
        calls = self._capture(monkeypatch, tmp_path)
        run = _run_dir(tmp_path, fastas=False)
        assert cli._launch_revalidate(run, backend="mock", validator="boltz2") == 0
        assert calls == []


class TestRevalidateAtTheCommandLine:
    def test_colab_is_refused_because_it_cannot_be_dispatched(self, tmp_path: Path) -> None:
        """Google's API does not permit launching a free-tier notebook from a CLI."""
        run = _run_dir(tmp_path)
        result = CliRunner().invoke(
            cli.main, ["validate", str(run), "--revalidate", "--backend", "colab"]
        )
        assert result.exit_code == 2
        assert "colab" in result.output.lower()

    def test_nothing_to_revalidate_exits_non_zero(self, tmp_path: Path) -> None:
        """Silence here would read as a successful second opinion that never ran."""
        run = _run_dir(tmp_path, with_designs=False)
        result = CliRunner().invoke(
            cli.main, ["validate", str(run), "--revalidate", "--backend", "mock"]
        )
        assert result.exit_code == 2
        assert "Nothing to revalidate" in result.output


class TestTheStreamlitEntrypoints:
    """Two ready rows whose "How to try" command nothing exercised."""

    @staticmethod
    def _capture(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
        import subprocess

        seen: list[list[str]] = []

        def fake_run(cmd: list[str], **kw: Any) -> Any:
            seen.append(list(cmd))
            return SimpleNamespace(returncode=0)

        monkeypatch.setattr(subprocess, "run", fake_run)
        return seen

    def test_ui_launches_streamlit_on_the_requested_port(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen = self._capture(monkeypatch)
        result = CliRunner().invoke(cli.main, ["ui", "--port", "8899"])
        assert result.exit_code == 0, result.output
        assert len(seen) == 1
        cmd = seen[0]
        assert cmd[1:4] == ["-m", "streamlit", "run"]
        assert "8899" in cmd
        assert cmd[cmd.index("--server.port") + 1] == "8899"

    def test_ui_keeps_its_no_telemetry_promise(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The docstring says telemetry is disabled explicitly; that is a claim.

        `.streamlit/config.toml` covers a repo checkout, and a packaged install
        launched from elsewhere never sees it — so the flag has to be on the
        command line, and has to stay there.
        """
        seen = self._capture(monkeypatch)
        CliRunner().invoke(cli.main, ["ui"])
        cmd = seen[0]
        assert cmd[cmd.index("--browser.gatherUsageStats") + 1] == "false"

    def test_no_browser_runs_headless(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen = self._capture(monkeypatch)
        CliRunner().invoke(cli.main, ["ui", "--no-browser"])
        cmd = seen[0]
        assert cmd[cmd.index("--server.headless") + 1] == "true"

    def test_ui_says_how_to_fix_a_missing_streamlit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import subprocess

        def missing(cmd: list[str], **kw: Any) -> Any:
            raise FileNotFoundError("streamlit")

        monkeypatch.setattr(subprocess, "run", missing)
        result = CliRunner().invoke(cli.main, ["ui"])
        assert result.exit_code == 2
        assert "report" in result.output, "the message must name the extra to install"

    def test_report_streamlit_launches_the_dashboard_for_the_run(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen = self._capture(monkeypatch)
        run = _run_dir(tmp_path, with_designs=False)
        result = CliRunner().invoke(cli.main, ["report", str(run), "--format", "streamlit"])
        assert result.exit_code == 0, result.output
        cmd = seen[0]
        assert cmd[1:4] == ["-m", "streamlit", "run"]
        assert str(run) in cmd, "the dashboard must be pointed at the run"

    def test_report_streamlit_says_how_to_fix_a_missing_streamlit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import subprocess

        def missing(cmd: list[str], **kw: Any) -> Any:
            raise FileNotFoundError("streamlit")

        monkeypatch.setattr(subprocess, "run", missing)
        run = _run_dir(tmp_path, with_designs=False)
        result = CliRunner().invoke(cli.main, ["report", str(run), "--format", "streamlit"])
        assert result.exit_code == 2
        assert "report" in result.output


class TestRevalidateDoesNotDestroyTheDesigns:
    """Rescoring must not cost you the binders being rescored.

    `_launch_revalidate` overwrites each target's tarball with whatever the run
    returns. Found while writing the coverage above: the first revalidation
    replaced the archive, and the second reported "no designs inside" and
    skipped the target. In production the executor ships the designs back, so
    the overwrite is usually right — but nothing required it, and the FASTA is
    the only record of a design's sequence, the staged PDBs being byte-identical
    per backbone.

    The designer benchmark already refuses to replace a real result with an
    empty one. This is the same rule one layer down.
    """

    def test_an_archive_without_designs_does_not_replace_the_originals(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from bindsight.design import _common

        metrics = tmp_path / "m.jsonl"
        metrics.write_text(json.dumps({"binder_id": "b0", "iptm": 0.71}) + "\n")
        stripped = tmp_path / "stripped.tar.gz"
        with tarfile.open(stripped, "w:gz") as tf:
            tf.add(metrics, arcname="metrics.jsonl")  # validator output, no designs

        monkeypatch.setattr(
            _common,
            "submit_via_runner",
            lambda spec, runner, **kw: SimpleNamespace(
                results_archive_path=str(stripped), metrics_jsonl_path=str(metrics)
            ),
        )
        run = _run_dir(tmp_path)
        tarball = run / "design" / "_targets" / "Q16790.tar.gz"
        before = tarball.read_bytes()

        assert cli._launch_revalidate(run, backend="mock", validator="boltz2") == 1
        assert tarball.read_bytes() == before, "the designs were overwritten"

        # The metrics are still taken: the validator did run.
        rows = (run / "design" / "metrics.jsonl").read_text().splitlines()
        assert json.loads(rows[0])["iptm"] == pytest.approx(0.71)

    def test_a_second_revalidation_still_finds_the_designs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Cross-validator agreement needs more than one pass over the same binders."""
        from bindsight.design import _common

        metrics = tmp_path / "m.jsonl"
        metrics.write_text(json.dumps({"binder_id": "b0", "iptm": 0.71}) + "\n")
        stripped = tmp_path / "stripped.tar.gz"
        with tarfile.open(stripped, "w:gz") as tf:
            tf.add(metrics, arcname="metrics.jsonl")
        monkeypatch.setattr(
            _common,
            "submit_via_runner",
            lambda spec, runner, **kw: SimpleNamespace(
                results_archive_path=str(stripped), metrics_jsonl_path=str(metrics)
            ),
        )
        run = _run_dir(tmp_path)
        assert cli._launch_revalidate(run, backend="mock", validator="boltz2") == 1
        assert cli._launch_revalidate(run, backend="mock", validator="chai1r") == 1

    def test_an_archive_carrying_designs_does_replace_them(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The guard must not block the normal path, where the designs come back."""
        from bindsight.design import _common

        metrics = tmp_path / "m.jsonl"
        metrics.write_text(json.dumps({"binder_id": "b0", "iptm": 0.71}) + "\n")
        fasta = tmp_path / "Q16790_binder_0_seq0.fasta"
        fasta.write_text(">Q16790_binder_0_seq0\nMKTAYIAKQRQISFVKSHFSRQ\n")
        full = tmp_path / "full.tar.gz"
        with tarfile.open(full, "w:gz") as tf:
            tf.add(metrics, arcname="metrics.jsonl")
            tf.add(fasta, arcname="design/Q16790_binder_0_seq0.fasta")
        monkeypatch.setattr(
            _common,
            "submit_via_runner",
            lambda spec, runner, **kw: SimpleNamespace(
                results_archive_path=str(full), metrics_jsonl_path=str(metrics)
            ),
        )
        run = _run_dir(tmp_path)
        tarball = run / "design" / "_targets" / "Q16790.tar.gz"
        before = tarball.read_bytes()
        assert cli._launch_revalidate(run, backend="mock", validator="boltz2") == 1
        assert tarball.read_bytes() != before, "the fresh validator output was not staged"

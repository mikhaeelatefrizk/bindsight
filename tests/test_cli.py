# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""CLI smoke tests."""

from __future__ import annotations

import io
import tarfile
from pathlib import Path

from click.testing import CliRunner

from bindsight import __version__
from bindsight.cli import main


def test_cli_help() -> None:
    r = CliRunner().invoke(main, ["--help"])
    assert r.exit_code == 0
    assert "Bridge from RNA-seq" in r.output


def test_cli_version() -> None:
    r = CliRunner().invoke(main, ["--version"])
    assert r.exit_code == 0
    assert __version__ in r.output


def test_cli_verify_licenses() -> None:
    r = CliRunner().invoke(main, ["verify-licenses"])
    assert r.exit_code == 0
    assert "bindsight" in r.output
    assert "Boltz-2" in r.output


def test_cli_discover_rejects_invalid_config(tmp_path) -> None:
    """An ill-shaped YAML must raise a Pydantic ValidationError, not silently run."""
    from pydantic import ValidationError

    cfg = tmp_path / "config.yaml"
    cfg.write_text("name: x\n")
    r = CliRunner().invoke(main, ["discover", str(cfg), "--out", str(tmp_path / "run")])
    assert r.exit_code != 0
    assert isinstance(r.exception, ValidationError)


def _run_with_targets(tmp_path, n: int = 3):
    """A run directory carrying an epitopes table, so the target count is known."""
    import pandas as pd

    run = tmp_path / "run"
    (run / "epitopes").mkdir(parents=True)
    pd.DataFrame(
        {
            "uniprot_id": [f"P{i:05d}" for i in range(n)],
            "symbol": [f"SYM{i}" for i in range(n)],
            "chain": ["A"] * n,
            "residues": [[] for _ in range(n)],
            "structure_path": [""] * n,
            "epitope_status": ["surface_bind_not_configured"] * n,
        }
    ).to_parquet(run / "epitopes" / "epitopes.parquet", index=False)
    return run


def test_cli_design_dry_run_prints_cost_and_exits_zero(tmp_path) -> None:
    """``design --dry-run`` prints a cost estimate and exits cleanly without launching.

    The run now carries an epitopes table. It did not before, and the command
    still printed a cost — because the target count fell back to a hard-coded 5.
    This test was asserting that a run with no targets is priced as though it had
    five, which is the defect, not the feature.
    """
    run = _run_with_targets(tmp_path)
    r = CliRunner().invoke(main, ["design", str(run), "--backend", "modal", "--dry-run"])
    assert r.exit_code == 0
    assert "Cost estimate" in r.output
    assert "modal" in r.output


def test_cli_design_without_a_target_count_prices_nothing(tmp_path) -> None:
    """A run with no epitopes table has an unknown number of targets, and an
    unknown amount of work cannot be costed. Saying so beats a plausible figure."""
    run = tmp_path / "run"
    run.mkdir()
    r = CliRunner().invoke(main, ["design", str(run), "--backend", "modal", "--dry-run"])
    # Rich wraps at the terminal width and emits ANSI styling, and the reset
    # sequence lands between "targets:" and its value. Strip both before
    # comparing, or the assertion tests the renderer rather than the message.
    import re as _re

    flat = " ".join(_re.sub(r"\[[0-9;]*m", "", r.output).split()).lower()
    assert "targets: unknown" in flat, flat[:300]
    assert "cost estimate is skipped" in flat, flat[:300]
    assert "cost estimate ─" not in flat, "a cost panel was rendered for an unknown amount of work"


def test_cli_design_without_targets_exits_2(tmp_path) -> None:
    """Without --dry-run on a run with no designable targets, design exits 2."""
    run = tmp_path / "run"
    run.mkdir()
    r = CliRunner().invoke(main, ["design", str(run), "--backend", "modal"])
    assert r.exit_code == 2
    assert "nothing to do" in r.output.lower()


def test_cli_validate_without_designs_reports_cost_unknown(tmp_path) -> None:
    """An empty run has no designs, so there is no per-design cost to quote."""
    run = tmp_path / "run"
    run.mkdir()
    r = CliRunner().invoke(
        main, ["validate", str(run), "--backend", "modal", "--validator", "boltz2"]
    )
    # validate says the cost is unknown, then a 'pending' panel pointing the
    # user at the GPU step. Exit code is 0 (work to do but not an error).
    assert r.exit_code == 0
    assert "No designs found" in r.output
    assert "Cost estimate" not in r.output
    assert "GPU step pending" in r.output


def _write_design_tarball(path: Path, *, n_designs: int) -> None:
    """Stage a per-target results tarball holding ``n_designs`` design PDBs."""
    path.parent.mkdir(parents=True, exist_ok=True)

    def _add(tf: tarfile.TarFile, name: str, body: str) -> None:
        raw = body.encode()
        info = tarfile.TarInfo(name)
        info.size = len(raw)
        tf.addfile(info, io.BytesIO(raw))

    with tarfile.open(path, "w:gz") as tf:
        for i in range(n_designs):
            _add(tf, f"design/binder_{i}.pdb", "ATOM\n")
            _add(tf, f"design/binder_{i}.fasta", ">b\nGSH\n")
        # Validator output is a prediction *of* a design, not another design.
        _add(tf, "validate/binder_0/binder_0_model_0.pdb", "ATOM\n")


def test_cli_validate_prints_cost_panel_for_designs_in_tarball(tmp_path) -> None:
    """The panel quotes the designs actually on disk, tarball members included."""
    run = tmp_path / "run"
    run.mkdir()
    _write_design_tarball(run / "design" / "_targets" / "P04626.tar.gz", n_designs=3)
    r = CliRunner().invoke(
        main, ["validate", str(run), "--backend", "modal", "--validator", "boltz2"]
    )
    assert r.exit_code == 0
    assert "Cost estimate" in r.output
    assert "3 designs" in r.output
    assert "No designs found" not in r.output


def test_cli_validate_af2_ig_shows_license_banner(tmp_path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    r = CliRunner().invoke(main, ["validate", str(run_dir), "--validator", "af2_ig"])
    assert "non-commercial" in r.output


# ---------------------------------------------------------------------------
# Help text is a claim about behaviour
# ---------------------------------------------------------------------------
REPO = Path(__file__).resolve().parents[1]


def _cli_source() -> str:
    return (REPO / "bindsight" / "cli.py").read_text(encoding="utf-8")


class TestTheHelpDescribesWhatTheCommandDoes:
    """``bindsight run --help`` said the GPU stages "run only if the
    corresponding outputs are already present from a previous GPU session".
    ``full_run`` calls ``_launch_design`` whenever the backend is headless, so on
    every backend but colab the command spends GPU quota the help says it will
    not spend.
    """

    def test_run_does_not_claim_it_only_reuses_gpu_outputs(self) -> None:
        from bindsight.cli import run

        doc = " ".join((run.__doc__ or "").split())

        assert "run only if the corresponding outputs are already" not in doc, doc
        assert "launch real work" in doc, (
            "the help does not say that the GPU stages launch work on a headless "
            "backend, which is what this command does"
        )

    def test_run_still_launches_the_gpu_half(self) -> None:
        """The premise. If this stops being true the help must change with it."""
        source = (REPO / "bindsight" / "pipelines" / "full_run.py").read_text(encoding="utf-8")

        assert "_launch_design" in source

    def test_no_dry_run_help_promises_a_dag(self) -> None:
        """Two --dry-run options promised to "print the DAG"; no code path does."""
        source = _cli_source()
        promises = [
            line for line in source.splitlines() if "help=" in line and "DAG" in line.upper()
        ]

        assert not promises, f"--dry-run help still promises a DAG: {promises}"

    def test_full_run_documents_no_flag_that_does_not_exist(self) -> None:
        """Its docstring offered ``--no-design``; no command exposes it."""
        import re

        from bindsight.pipelines import full_run

        doc = full_run.__doc__ or ""
        flags = set(re.findall(r"``(--[a-z-]+)``", doc))
        source = _cli_source()
        missing = sorted(f for f in flags if f'"{f}"' not in source)

        assert not missing, f"full_run's docstring documents absent flags: {missing}"


class TestTheGpuPreflightIsNotSkipped:
    """``design`` refuses an unsupported designer/backend pair locally, for free.
    ``run`` launches the same GPU half and never called that check.
    """

    def test_every_command_that_launches_gpu_work_preflights(self) -> None:
        import ast

        tree = ast.parse(_cli_source())
        for node in tree.body:
            if not isinstance(node, ast.FunctionDef) or node.name not in {"run", "design"}:
                continue
            calls = {
                n.func.id
                for n in ast.walk(node)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
            }
            assert "_preflight_backend" in calls, (
                f"`bindsight {node.name}` launches GPU work without the preflight "
                "refusal that exists to stop it spending quota on a combination "
                "no backend can run"
            )


class TestNumericOptionsCannotSmuggleInvalidValues:
    """These values are assigned straight onto the pydantic model, and assignment
    does not re-validate. ``--top-n 0`` reached the pipeline and produced an empty
    shortlist that read as a finding.
    """

    def test_no_option_accepts_an_unbounded_integer(self) -> None:
        import re

        source = _cli_source()
        bare = [match.start() for match in re.finditer(r"^\s*type=int,\s*$", source, re.M)]

        assert not bare, (
            f"{len(bare)} click option(s) still take a bare `type=int`; use "
            "click.IntRange so a value the schema forbids is refused at the "
            "boundary rather than assigned past it"
        )

    def test_a_zero_top_n_is_refused(self) -> None:
        from click.testing import CliRunner

        from bindsight.cli import main

        result = CliRunner().invoke(main, ["discover", "--help"])
        assert result.exit_code == 0

    def test_the_range_is_enforced_end_to_end(self, tmp_path) -> None:
        from click.testing import CliRunner

        from bindsight.cli import main

        run = tmp_path / "run"
        run.mkdir()
        result = CliRunner().invoke(
            main, ["design", str(run), "--backend", "mock", "--trajectories", "0", "--dry-run"]
        )

        assert result.exit_code != 0
        assert "0" in result.output


class TestTheDryRunPricesTheConfiguredHardware:
    """``run`` passed ``gpu_type`` to the estimate; ``design --dry-run`` did not,
    so it quoted A100 prices for a run configured for a T4."""

    def test_every_cost_estimate_names_the_gpu(self) -> None:
        import ast

        tree = ast.parse(_cli_source())
        sites = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "estimate_full_run"
        ]
        assert sites, "no cost estimates found in the CLI"
        for node in sites:
            assert "gpu_type" in {kw.arg for kw in node.keywords}, (
                f"bindsight/cli.py:{node.lineno} prices a run without naming the GPU, "
                "so the figure may be for different hardware than the job requests"
            )


class TestAFailedLaunchDoesNotExitZero:
    """`bindsight ui` printed "Launching bindsight UI" and exited 0 whatever the
    server did, because the launch ran with ``check=False`` and its status was
    discarded.

    The server runs in-process now, so the discarded-status bug cannot recur in
    that shape. The failure it protected against still can: a port already in
    use is the ordinary way this command fails, and a shell that sees 0 will go
    on to open a browser at a URL nothing is serving.
    """

    def test_a_port_already_in_use_is_not_a_successful_launch(self) -> None:
        """Driven against a real occupied socket, not a mocked return value.

        A source check for the error path passes against ``if False:`` — the
        strings stay and the behaviour goes.
        """
        import socket

        from click.testing import CliRunner

        from bindsight.cli import main

        with socket.socket() as taken:
            taken.bind(("127.0.0.1", 0))
            taken.listen(1)
            port = taken.getsockname()[1]

            result = CliRunner().invoke(main, ["ui", "--no-browser", "--port", str(port)])

        assert result.exit_code != 0, (
            f"the port was already bound and the command exited {result.exit_code}; "
            "a UI that failed to start must not report success"
        )

    def test_a_clean_shutdown_still_exits_zero(self, monkeypatch) -> None:
        """The guard must not turn every launch into a failure.

        ``serve`` is replaced rather than run: the real one blocks until
        interrupted, and a test that waits for a keyboard is not a test.
        """
        from click.testing import CliRunner

        from bindsight.cli import main
        from bindsight.report.web import app as web_app

        served: dict[str, object] = {}
        monkeypatch.setattr(web_app, "serve", lambda **kw: served.update(kw))

        result = CliRunner().invoke(main, ["ui", "--no-browser", "--port", "8765"])

        assert result.exit_code == 0, result.output
        assert served == {"port": 8765, "open_browser": False}, (
            f"the command did not pass its own options through to the server: {served}"
        )


class TestTheFixItMessageIsTheCommandToRun:
    """Rich reads ``[report]`` as a style tag and drops it.

    Every "install the extra" hint therefore rendered as ``pip install -e "."``:
    the base package, which is what the user already had. The message appears
    only on the path where something is already broken, prints a command that
    changes nothing, and reads as though it fixed it. Three sites had it.

    Rendered rather than grepped -- a source check for a backslash passes
    against a string that Rich mangles some other way, and the thing that
    matters is what lands in the terminal.
    """

    @staticmethod
    def _install_hints() -> list[tuple[int, str]]:
        """Every string literal in the CLI that tells someone what to install."""
        import ast

        source = (REPO / "bindsight" / "cli.py").read_text(encoding="utf-8")
        found: list[tuple[int, str]] = []
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if "pip install" in node.value:
                    found.append((node.lineno, node.value))
        return found

    def test_the_sweep_finds_the_hints_it_exists_to_check(self) -> None:
        """Guards the guard: an empty sweep would pass silently forever."""
        assert len(self._install_hints()) >= 3, (
            "no install hints found in bindsight/cli.py; the sweep has stopped "
            "reaching the strings it is meant to check"
        )

    def test_every_extra_survives_being_rendered(self) -> None:
        import io
        import re

        from rich.console import Console

        broken: list[str] = []
        for lineno, text in self._install_hints():
            # Just the command, not the whole literal: an f-string arrives from
            # ``ast`` in pieces, and a piece beginning ``[/dim]`` is not markup
            # anything can render on its own.
            for command in re.findall(r'pip install -e "[^"]*"', text):
                wanted = re.findall(r'"\.\\?\[([a-z,]+)\]"', command)
                if not wanted:
                    continue
                buf = io.StringIO()
                Console(file=buf, width=200, no_color=True, highlight=False).print(command)
                rendered = buf.getvalue()
                for extra in wanted:
                    if f".[{extra}]" not in rendered:
                        broken.append(
                            f"bindsight/cli.py:{lineno} renders as "
                            f"{rendered.strip()!r}, dropping [{extra}]"
                        )

        assert not broken, (
            "these messages tell the user to run a command that does not install "
            "what they are missing:\n  " + "\n  ".join(broken)
        )

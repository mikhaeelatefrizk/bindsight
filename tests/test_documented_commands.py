# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Every ``bindsight`` command in the documentation has to be one you can run.

``docs/how-to-use.md`` told a reader to run ``bindsight report --format web``.
It exits with ``Error: Missing argument 'RUN_DIR'``. Three more were the same
shape: a designer plugin selected with a top-level ``--designer`` that does not
exist, a teaching syllabus whose ``bindsight design --backend colab`` names no
run directory, and a benchmark page passing a ``.yaml`` config to a subcommand
whose positional argument must be an existing directory.

Nothing checked this. ``tests/test_docs_claims.py`` sweeps documented shell
commands, but its pattern covers ``python``, ``bash`` and ``sh`` invocations --
the console script itself was outside it, which is most of what the
documentation actually tells people to type.

Checked by introspection rather than invocation, deliberately. Running these
would fail on ``runs/my_first_run`` not existing, so the test would have to
build fixtures for every path in the documentation, and would then be testing
the fixtures. Click already knows which subcommands exist, which flags each
accepts and which arguments are required, so that is what is asked. The
consequence is that a placeholder passes: ``<config>``, ``my.yaml`` and
``runs/x`` are all just a token in a positional slot, which is correct --
documentation is allowed to say ``<config>``.

One thing introspection cannot see is a token of the wrong *kind*: a config
file handed to an argument that must be a directory is structurally valid and
fails only at runtime. That was the fourth defect, so there is a narrow check
for exactly it, and no attempt to generalise beyond what can be decided from
the parameter's own declared type.
"""

from __future__ import annotations

import re
import shlex
import subprocess
from pathlib import Path

import click
import pytest

from bindsight.cli import main

REPO = Path(__file__).resolve().parents[1]

#: Fence languages whose contents are commands a reader is meant to type. A
#: fence tagged ``text`` is a diagram or a table, not an instruction --
#: ``ARCHITECTURE.md`` uses one for a CLI-to-Snakemake equivalence table, whose
#: rows are not invocations and were retagged rather than carved out here.
_SHELL_FENCES = {"", "bash", "sh", "shell", "console", "shell-session"}

#: The two ways the CLI is spelled in shipped documents.
_PROGRAMS = ("bindsight", "python -m bindsight.cli")

#: Options on the group itself, valid with no subcommand.
_GROUP_ONLY = {"--version", "--help", "-h"}

#: A history is a record of what was true, not advice. ``bindsight report
#: --format streamlit`` appears there because it was once the command, and the
#: same file documents its replacement. Rewriting it would falsify the record.
_EXCLUDED = {"CHANGELOG.md"}

#: Extensions that name a file. Used only against an argument whose declared
#: type refuses files, which is the one mix-up this CLI invites.
_FILE_SUFFIXES = (".yaml", ".yml", ".json", ".tsv", ".csv", ".txt", ".parquet")

#: Stands for "whatever subcommand you like", not for a command.
_NAMING = {"…", "...", "<...>", "<command>", "<subcommand>"}

_INLINE = re.compile(r"`([^`\n]+)`")
_FENCE = re.compile(r"^\s*```+\s*([A-Za-z0-9_-]*)\s*$")
_PROMPT = re.compile(r"^\$\s+")


def _tracked_markdown() -> list[Path]:
    """Shipped documents, from git rather than a glob, so nothing is missed."""
    out = subprocess.run(
        ["git", "ls-files", "*.md"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    return [REPO / rel for rel in out if Path(rel).name not in _EXCLUDED]


def _candidates(text: str) -> list[tuple[int, str]]:
    """Every ``bindsight ...`` invocation in *text*, with its line number.

    Reads shell fences line by line (joining backslash continuations) and
    inline code spans outside them.
    """
    found: list[tuple[int, str]] = []
    fence_lang: str | None = None
    pending: list[str] = []
    pending_line = 0

    for lineno, raw in enumerate(text.splitlines(), 1):
        fence = _FENCE.match(raw)
        if fence is not None:
            fence_lang = None if fence_lang is not None else fence.group(1).lower()
            pending = []
            continue

        if fence_lang is not None:
            if fence_lang not in _SHELL_FENCES:
                continue
            line = raw.strip()
            if pending:
                pending.append(line.rstrip("\\").strip())
                if not line.endswith("\\"):
                    found.append((pending_line, " ".join(pending)))
                    pending = []
                continue
            if not line.startswith(_PROGRAMS):
                continue
            if line.endswith("\\"):
                pending = [line.rstrip("\\").strip()]
                pending_line = lineno
                continue
            found.append((lineno, line))
            continue

        for span in _INLINE.findall(raw):
            candidate = _PROMPT.sub("", span.strip())
            if candidate.startswith(_PROGRAMS):
                found.append((lineno, candidate))

    return found


def _tokens(command: str) -> list[str] | None:
    """Split *command* into argv, or None if it is not a single invocation."""
    text = _PROMPT.sub("", command.strip())
    if "|" in text:
        # A pipe, or an alternation like `bindsight discover|design|report`.
        # Neither is one command, and neither is this test's business.
        return None
    try:
        argv = shlex.split(text, comments=True)
    except ValueError:
        return None
    # `python -m bindsight.cli ...` spends three tokens naming the program;
    # `bindsight ...` spends one. Either way, what follows is the argv Click sees.
    lead = 3 if argv[:1] == ["python"] else 1
    return argv[lead:]


def _option_map(cmd: click.Command) -> dict[str, click.Parameter]:
    flags: dict[str, click.Parameter] = {}
    for param in cmd.params:
        for flag in list(param.opts) + list(param.secondary_opts):
            if flag.startswith("-"):
                flags[flag] = param
    return flags


def _check(argv: list[str]) -> str | None:
    """Return a one-line complaint about *argv*, or None if it would run."""
    if not argv:
        return None  # `bindsight` alone prints help; that is a real thing to say.

    if any(tok in _NAMING for tok in argv):
        return None  # `bindsight …` stands for "any subcommand"

    if len(argv) == 1 and argv[0] in main.commands:
        # A lone subcommand names the command rather than invoking it, which is
        # how prose refers to one: "`bindsight export`, which writes the crate".
        # The cost of this rule is that a genuinely incomplete bare mention goes
        # unchecked; the benefit is that every mention carrying a flag or an
        # argument is held to being complete, and that is where all four real
        # defects lived. The two documents that sat between the two forms were
        # reworked to pick one, rather than the rule being bent around them.
        return None

    head = argv[0]
    if head.startswith("-"):
        if head.split("=")[0] not in _GROUP_ONLY:
            return f"no top-level option {head!r}; it may belong to a subcommand"
        return None

    cmd = main.commands.get(head)
    if cmd is None:
        return f"no subcommand {head!r} (have: {', '.join(sorted(main.commands))})"

    flags = _option_map(cmd)
    positionals: list[str] = []
    seen: set[str] = set()
    rest = argv[1:]
    i = 0
    while i < len(rest):
        token = rest[i]
        if token.startswith("-") and token != "-":
            name, sep, _ = token.partition("=")
            if name in _GROUP_ONLY and name not in flags:
                return None  # `--help` short-circuits everything after it
            param = flags.get(name)
            if param is None:
                return f"{head} has no option {name!r}"
            seen.add(param.name or name)
            if not sep and not getattr(param, "is_flag", False) and param.nargs == 1:
                i += 1  # it takes a value
        else:
            positionals.append(token)
        i += 1

    arguments = [p for p in cmd.params if isinstance(p, click.Argument)]
    options = [p for p in cmd.params if isinstance(p, click.Option)]

    for param in options:
        if param.required and (param.name or "") not in seen:
            flag = next((o for o in param.opts if o.startswith("--")), param.name)
            return f"{head} requires {flag}"

    supplied = list(positionals)
    for param in arguments:
        if param.nargs == -1:
            if param.required and not supplied:
                return f"{head} requires at least one {(param.name or '').upper()}"
            matched, supplied = supplied, []
        else:
            if param.required and len(supplied) < param.nargs:
                return f"{head} requires the argument {(param.name or '').upper()}"
            matched, supplied = supplied[: param.nargs], supplied[param.nargs :]

        kind = param.type
        directory_only = isinstance(kind, click.Path) and not getattr(kind, "file_okay", True)
        if directory_only:
            for token in matched:
                if token.lower().endswith(_FILE_SUFFIXES):
                    return (
                        f"{head} takes a directory as {(param.name or '').upper()}, "
                        f"but {token!r} names a file"
                    )
    return None


class TestEveryDocumentedCommandWouldRun:
    def test_the_sweep_finds_the_documents_and_the_commands(self) -> None:
        """Without this, a bad glob would make the check below pass on nothing."""
        docs = _tracked_markdown()
        assert len(docs) >= 10, [p.name for p in docs]
        assert not any(p.name in _EXCLUDED for p in docs)

        total = sum(len(_candidates(p.read_text(encoding="utf-8"))) for p in docs)
        assert total >= 40, f"the extractor found only {total} commands"

        names = {p.name for p in docs}
        for expected in ("how-to-use.md", "use-cases.md", "README.md"):
            assert expected in names, f"{expected} is not being swept"

    def test_no_documented_command_is_one_a_reader_cannot_run(self) -> None:
        broken: list[str] = []
        for path in _tracked_markdown():
            rel = path.relative_to(REPO).as_posix()
            for lineno, command in _candidates(path.read_text(encoding="utf-8")):
                argv = _tokens(command)
                if argv is None:
                    continue
                complaint = _check(argv)
                if complaint is not None:
                    broken.append(f"{rel}:{lineno}  {command}\n      -> {complaint}")

        assert not broken, "documented commands that fail before doing anything:\n" + "\n".join(
            broken
        )

    @pytest.mark.parametrize(
        ("command", "fragment"),
        [
            # The four real lines, as they were written, before the fix.
            ("bindsight report --format web", "requires the argument RUN_DIR"),
            ("bindsight design --backend colab", "requires the argument RUN_DIR"),
            ("bindsight --designer internal_designer", "no top-level option"),
            (
                "bindsight design --dry-run examples/benchmark_held_out.yaml "
                '--backend modal --designer "$d"',
                "names a file",
            ),
            # And the two the survey raised as borderline, which are real.
            ("bindsight run <config>", "requires --out"),
            ("bindsight discover my.yaml", "requires --out"),
            # Shapes the checker must not miss.
            ("bindsight nosuchthing runs/x", "no subcommand"),
            ("bindsight report runs/x --format=nope --bogus", "no option '--bogus'"),
        ],
    )
    def test_the_checker_catches_the_defects_it_exists_for(
        self, command: str, fragment: str
    ) -> None:
        """Positive controls, taken from the repository rather than invented."""
        argv = _tokens(command)
        assert argv is not None, command
        complaint = _check(argv)

        assert complaint is not None, f"the checker would have passed: {command}"
        assert fragment in complaint, f"{command!r} -> {complaint!r}"

    @pytest.mark.parametrize(
        "command",
        [
            "bindsight --version",
            "bindsight doctor",
            "bindsight verify-licenses",
            "bindsight discover my.yaml --out runs/x",
            "bindsight discover <config> --out <run_dir>",
            "bindsight report runs/x",
            "bindsight report runs/x --format html --include-binders",
            "bindsight design runs/x --backend kaggle --trajectories 50",
            "bindsight benchmark runs/a runs/b --known-antigens benchmarks/known.tsv",
            "bindsight export runs/x --format ro-crate --out runs/x.crate.zip",
            "python -m bindsight.cli rank runs/join",
            "bindsight design runs/x --dry-run  # estimate the cost",
        ],
        ids=range(12),
    )
    def test_the_checker_passes_commands_that_really_work(self, command: str) -> None:
        """The other direction: a correct line, including placeholders, is fine.

        Without these the checker could reject everything and the sweep above
        would still be green only because the documents had been emptied.
        """
        argv = _tokens(command)
        assert argv is not None, command

        assert _check(argv) is None, f"{command!r} was rejected: {_check(argv)}"

    def test_a_value_taking_option_does_not_swallow_a_required_argument(self) -> None:
        """``--out runs/x`` consumes its value; ``runs/x`` is not then a positional.

        Getting this backwards would make ``bindsight discover --out runs/x``
        look complete, which is the mistake that hides a missing CONFIG.
        """
        assert _check(_tokens("bindsight discover --out runs/x") or []) is not None
        assert _check(_tokens("bindsight discover c.yaml --out runs/x") or []) is None

    def test_an_alternation_is_not_read_as_a_command(self) -> None:
        """``bindsight discover|design|report`` names commands; it is not one."""
        assert _tokens("bindsight discover|design|validate|rank|report|export") is None

    def test_a_non_shell_fence_is_not_read_as_instructions(self) -> None:
        text = "```text\nbindsight discover   ~  snakemake --until discover\n```\n"
        assert _candidates(text) == []

        shell = "```bash\nbindsight discover c.yaml --out runs/x\n```\n"
        assert _candidates(shell) == [(2, "bindsight discover c.yaml --out runs/x")]

    def test_a_continuation_is_joined_before_it_is_checked(self) -> None:
        """Split across lines, the second half carries the required option."""
        text = "```bash\nbindsight run c.yaml --designer rfdiff_mpnn \\\n    --out runs/x\n```\n"
        found = _candidates(text)

        assert found == [(2, "bindsight run c.yaml --designer rfdiff_mpnn --out runs/x")]
        assert _check(_tokens(found[0][1]) or []) is None

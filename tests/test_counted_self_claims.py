# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Counts the repository states about itself must still be true.

The scientific numbers in this project are guarded closely -- every rate,
interval and p-value is checked against the artifact that produced it. The
repository's descriptions *of itself* were not, and drifted: "78 test modules"
when there were 80, "nine are skipped without snakemake" when five are, "~50
lines" for a file of 111.

Individually trivial. Together they are the first thing a careful reader checks,
because they are the cheapest claims to verify -- and a reader who finds the
easy numbers wrong has no reason to trust the hard ones.

Counts are stated as floors wherever they can be, which is this project's
existing norm: a floor survives the suite growing and fails when it shrinks past
what was promised. Exact counts are checked exactly.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def _doc(rel: str) -> str:
    path = REPO / rel
    if not path.is_file():
        pytest.skip(f"{rel} not present")
    return path.read_text(encoding="utf-8")


def _test_modules() -> int:
    return len(list((REPO / "tests").glob("test_*.py")))


def _package_modules() -> int:
    return len(list((REPO / "bindsight").rglob("*.py")))


class TestTheTestSuiteCountsAreFloorsThatHold:
    """Every surface states the suite's size; none of them recomputed it."""

    #: (file, regex capturing the number, which count it is a floor on).
    #:
    #: Two metrics, deliberately kept apart. A claim about "tests" means what
    #: pytest collects; a claim about "test functions" means ``def test_`` lines,
    #: and the suite is parametrised enough that the two differ by hundreds.
    #: Binding one claim to the other number would assert something nobody wrote.
    #:
    #: Two paper surfaces were outside this tuple entirely -- it named three
    #: files while five made the claim -- so the JOSS paper understated the
    #: suite by seven hundred and nothing noticed. That is the enumeration
    #: defect this module exists to catch, found in this module.
    FLOORS = (
        ("README.md", r"# ([\d,]{3,6})\+ tests, no network", "collected"),
        ("README.md", r"\| ([\d,]{3,6})\+ tests\.", "collected"),
        ("tests/README.md", r"^# `tests/` — ([\d,]{3,6})\+ tests", "collected"),
        ("paper/paper.md", r"over ([\d,]{3,6}) unit and integration tests", "collected"),
        ("paper/README.md", r"over ([\d,]{3,6}) test functions", "functions"),
    )

    @pytest.mark.parametrize(("rel", "pattern", "metric"), FLOORS)
    def test_the_stated_floor_still_holds(
        self,
        collected_tests: int,
        test_functions: int,
        rel: str,
        pattern: str,
        metric: str,
    ) -> None:
        text = _doc(rel)
        match = re.search(pattern, text, re.M)
        assert match, f"{rel} no longer states a {metric} floor in the expected form"

        claimed = int(match.group(1).replace(",", ""))
        actual = collected_tests if metric == "collected" else test_functions
        counted = "pytest collects" if metric == "collected" else "the suite defines"

        assert actual >= claimed, (
            f"{rel} promises {claimed}+ ({metric}); {counted} {actual}. "
            "Either the claim is stale or the suite lost tests."
        )


class TestTheModuleCountsAreRight:
    def test_the_test_module_count_is_a_floor_that_holds(self) -> None:
        match = re.search(r"^(\d+) test modules", _doc("tests/README.md"), re.M)
        assert match, "tests/README.md no longer opens with a test-module count"

        claimed, actual = int(match.group(1)), _test_modules()

        assert actual >= claimed, f"tests/README.md says {claimed} test modules; there are {actual}"

    def test_the_package_module_count_is_a_floor_that_holds(self) -> None:
        match = re.search(r"Over (\d+) modules", _doc("bindsight/README.md"))
        assert match, "bindsight/README.md no longer states a module count"

        claimed, actual = int(match.group(1)), _package_modules()

        assert actual >= claimed, (
            f"bindsight/README.md says over {claimed} modules; there are {actual}"
        )

    def test_the_counts_are_not_absurd_floors(self) -> None:
        """A floor of 1 would pass forever and describe nothing.

        The point of stating a number is to tell a reader the size of the thing.
        Within a factor of two is a description; an order of magnitude is not.
        """
        module_match = re.search(r"Over (\d+) modules", _doc("bindsight/README.md"))
        assert module_match
        claimed = int(module_match.group(1))

        assert claimed * 2 >= _package_modules(), (
            f"bindsight/README.md says over {claimed} modules against an actual "
            f"{_package_modules()}; the floor is too low to inform anyone"
        )


class TestTheSnakemakeSkipCountIsRight:
    """Not a floor: a reader counting skipped tests can check this exactly."""

    def test_it_matches_the_file(self) -> None:
        match = re.search(r"(\w+) are skipped without `snakemake`", _doc("tests/README.md"))
        assert match, "tests/README.md no longer states how many tests skip without snakemake"

        words = {
            "One": 1,
            "Two": 2,
            "Three": 3,
            "Four": 4,
            "Five": 5,
            "Six": 6,
            "Seven": 7,
            "Eight": 8,
            "Nine": 9,
            "Ten": 10,
        }
        claimed = words.get(match.group(1).capitalize())
        assert claimed is not None, f"unrecognised count word {match.group(1)!r}"

        source = (REPO / "tests" / "test_snakemake_dag.py").read_text(encoding="utf-8")
        actual = len(re.findall(r"^\s*def test_", source, re.M))

        assert claimed == actual, (
            f"tests/README.md says {claimed} tests skip without snakemake; "
            f"test_snakemake_dag.py defines {actual}"
        )


class TestTheModalPriceRangeCoversWhatCostPrices:
    """`how-to-use.md` quoted a ceiling below the most expensive card priced."""

    def test_the_quoted_range_contains_every_modal_price(self) -> None:
        from bindsight.cost import GPU_PRICE_USD_PER_HOUR

        prices = [v for (backend, _gpu), v in GPU_PRICE_USD_PER_HOUR.items() if backend == "modal"]
        assert prices, "no modal prices in cost.py; this test no longer checks anything"

        match = re.search(r"\| `modal` \| \$([\d.]+)–([\d.]+)/GPU-hr", _doc("docs/how-to-use.md"))
        assert match, "docs/how-to-use.md no longer quotes a modal price range"

        low, high = float(match.group(1)), float(match.group(2))

        assert low <= min(prices), (
            f"the table's floor ${low} is above the cheapest modal card at ${min(prices)}"
        )
        assert high >= max(prices), (
            f"the table's ceiling ${high} is below the most expensive modal card "
            f"at ${max(prices)}; a reader budgeting against it under-provisions"
        )


class TestNoTwoRoadmapEntriesShareAVersion:
    """`positioning.md` labelled a shipped release and unbuilt work both v0.3.0.

    A reader takes the union as the release, which is how BindCraft and BoltzGen
    came to look "fully wired" on a page whose own README says no shipped
    backend can run them.
    """

    def test_each_version_appears_once_in_the_roadmap(self) -> None:
        text = _doc("docs/positioning.md")
        roadmap = text.split("## Roadmap", 1)
        assert len(roadmap) == 2, "positioning.md no longer has a Roadmap section"
        body = roadmap[1].split("\n## ", 1)[0]

        versions = re.findall(r"^- \*\*(v\d+\.\d+\.\d+)", body, re.M)
        duplicates = {v for v in versions if versions.count(v) > 1}

        assert not duplicates, (
            f"the roadmap lists {sorted(duplicates)} more than once, so a reader "
            "cannot tell which features are in the release and which are not"
        )
        assert versions, "the roadmap no longer lists any versions"

    def test_the_shipped_version_is_the_packages_version(self) -> None:
        import tomllib

        pyproject = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
        version = pyproject["project"]["version"]

        assert f"**v{version} (now)**" in _doc("docs/positioning.md"), (
            f"the roadmap does not mark v{version} -- the version in pyproject.toml "
            "-- as the current one"
        )


class TestTheNumbersCopiedOutOfArtifactsStillMatchThem:
    """Two figures were restated in a second document and checked in neither.

    The generated pages that carry these numbers are guarded -- the calibration
    page is compared byte for byte against what its artifact renders to. What
    was not guarded is the *restatement*: a human copied each number into
    another document, and from that moment the two could drift with nothing
    saying so. Both are correct today. That is the only reason this is a guard
    rather than a correction.
    """

    def test_the_power_analysis_figure_matches_the_calibration_artifact(self) -> None:
        """README states the paired-design count the calibration computed."""
        import json

        artifact = REPO / "benchmarks" / "calibration" / "RESULTS.json"
        if not artifact.is_file():
            pytest.skip("no calibration artifact in this checkout")

        needed = json.loads(artifact.read_text(encoding="utf-8"))
        pairs = {
            round(float(row["effect"]), 3): int(row["n_pairs"])
            for row in needed["variance_decomposition"]["pairs_needed"]
        }
        assert pairs, "the artifact records no power analysis; nothing to compare"

        text = _doc("README.md")
        match = re.search(
            r"\*\*([\d,]+) paired designs\*\* at 80% power to\s+"
            r"detect a (0\.\d+) ipTM difference",
            text,
        )
        assert match, (
            "README.md no longer states the power analysis in the expected form; "
            "if the sentence moved, move this pattern with it rather than "
            "deleting the check"
        )

        claimed = int(match.group(1).replace(",", ""))
        effect = round(float(match.group(2)), 3)

        assert effect in pairs, (
            f"README quotes an effect size of {effect}, which the artifact does "
            f"not compute; it has {sorted(pairs)}"
        )
        assert claimed == pairs[effect], (
            f"README says {claimed} paired designs at effect {effect}; the "
            f"calibration artifact says {pairs[effect]}"
        )

    def test_the_advertised_ci_job_count_is_what_the_matrix_produces(self) -> None:
        """`paper/README.md` tells a JOSS editor how many jobs run."""
        workflow = (REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

        oses = re.search(r"os:\s*\[([^\]]+)\]", workflow)
        pythons = re.search(r"python-version:\s*\[([^\]]+)\]", workflow)
        assert oses, "ci.yml no longer declares an os matrix in the expected form"
        assert pythons, "ci.yml no longer declares a python-version matrix"

        produced = len(oses.group(1).split(",")) * len(pythons.group(1).split(","))
        assert produced >= 4, f"only read {produced} matrix cells; the parse is wrong"

        match = re.search(r"(\d+) platform/Python jobs", _doc("paper/README.md"))
        assert match, "paper/README.md no longer states a platform job count"

        assert int(match.group(1)) == produced, (
            f"paper/README.md advertises {match.group(1)} platform/Python jobs; "
            f"the ci.yml matrix produces {produced}"
        )


class TestTheSupportedPythonsAreTheOnesCiRuns:
    """`bindsight doctor` reported a plain "ok" for any Python >= 3.11.

    `requires-python` is `>=3.11` with no ceiling and the CI matrix runs
    3.11-3.13, so on 3.14 everything installs, `doctor` says ok, and the first
    thing the tool tells a newcomer about their setup is not true of it.
    Supported means tested.

    The list is now kept in one place and checked against the workflow that
    actually runs, and against the classifiers that advertise it.
    """

    @staticmethod
    def _matrix_pythons() -> set[tuple[int, int]]:
        """The versions `.github/workflows/ci.yml` runs the suite on."""
        workflow = (REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        match = re.search(r"python-version:\s*\[([^\]]+)\]", workflow)
        assert match, "ci.yml no longer declares a python-version matrix"
        return {
            tuple(int(n) for n in v.strip().strip('"' + "'").split("."))  # type: ignore[misc]
            for v in match.group(1).split(",")
        }

    def test_the_matrix_is_readable(self) -> None:
        """Guards the guard: an unreadable matrix would make the checks vacuous."""
        assert len(self._matrix_pythons()) >= 2, (
            f"only read {self._matrix_pythons()} from the CI matrix"
        )

    def test_the_code_lists_exactly_what_ci_runs(self) -> None:
        from bindsight.cli import TESTED_PYTHONS

        assert set(TESTED_PYTHONS) == self._matrix_pythons(), (
            f"cli.TESTED_PYTHONS is {sorted(TESTED_PYTHONS)} but CI runs "
            f"{sorted(self._matrix_pythons())}; doctor would report a version as "
            "tested that nothing tested, or refuse one that CI covers"
        )

    def test_the_classifiers_advertise_exactly_what_ci_runs(self) -> None:
        import tomllib

        pyproject = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
        advertised = {
            tuple(int(n) for n in c.rsplit(" ", 1)[-1].split("."))
            for c in pyproject["project"]["classifiers"]
            if c.startswith("Programming Language :: Python :: 3.")
        }

        assert advertised == self._matrix_pythons(), (
            f"pyproject advertises {sorted(advertised)}; CI runs {sorted(self._matrix_pythons())}"
        )

    def test_the_minimum_matches_requires_python(self) -> None:
        import tomllib

        pyproject = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
        floor = tuple(
            int(n) for n in pyproject["project"]["requires-python"].lstrip(">=").split(".")
        )

        from bindsight.cli import TESTED_PYTHONS

        assert floor == min(TESTED_PYTHONS), (
            f"requires-python is {floor} but the lowest tested version is "
            f"{min(TESTED_PYTHONS)}; pip would install onto an untested interpreter "
            "without saying so"
        )

    def test_an_untested_version_is_not_reported_as_fine(self) -> None:
        import bindsight.cli as cli_module
        from bindsight.cli import _python_support_note

        original = cli_module.sys.version_info
        try:
            cli_module.sys.version_info = (99, 0, 0, "final", 0)  # type: ignore[assignment]
            note = _python_support_note()
        finally:
            cli_module.sys.version_info = original  # type: ignore[assignment]

        assert "untested" in note, f"a future Python is described as {note!r}"

    def test_a_tested_version_gets_no_caveat(self) -> None:
        import bindsight.cli as cli_module
        from bindsight.cli import TESTED_PYTHONS, _python_support_note

        original = cli_module.sys.version_info
        try:
            major, minor = min(TESTED_PYTHONS)
            cli_module.sys.version_info = (major, minor, 0, "final", 0)  # type: ignore[assignment]
            note = _python_support_note()
        finally:
            cli_module.sys.version_info = original  # type: ignore[assignment]

        assert note == "", f"a tested Python was caveated as {note!r}"

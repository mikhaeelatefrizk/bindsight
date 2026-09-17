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


@pytest.fixture(scope="session")
def collected_tests() -> int:
    """How many tests pytest collects in this repository.

    Session-scoped because it costs a subprocess: the three surfaces that state
    a floor share one collection rather than paying for three.

    Deliberately NOT marked `slow`. CI runs `-m "not gpu and not slow"`, so a
    slow-marked guard never runs where it matters -- the same shape of failure
    this module exists to catch in prose, which is how the marker came to be
    here in the first place.

    Counted by collection rather than by counting `def test_` lines: the suite
    is heavily parametrised, so the two differ by hundreds, and a claim about
    "tests" means the first.
    """
    import subprocess
    import sys

    out = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=900,
    ).stdout
    match = re.search(r"(\d+) tests? collected", out)
    assert match, f"could not read a collection count from pytest:\n{out[-500:]}"
    return int(match.group(1))


class TestTheTestSuiteCountsAreFloorsThatHold:
    """Every surface states the suite's size; none of them recomputed it."""

    #: (file, regex capturing the number, what it counts).
    FLOORS = (
        ("README.md", r"# (1,?\d{3})\+ tests, no network", "collected tests"),
        ("README.md", r"\| (1,?\d{3})\+ tests\.", "collected tests"),
        ("tests/README.md", r"^# `tests/` — (1,?\d{3})\+ tests", "collected tests"),
    )

    @pytest.mark.parametrize(("rel", "pattern", "what"), FLOORS)
    def test_the_stated_floor_still_holds(
        self, collected_tests: int, rel: str, pattern: str, what: str
    ) -> None:
        text = _doc(rel)
        match = re.search(pattern, text, re.M)
        assert match, f"{rel} no longer states a {what} floor in the expected form"

        claimed = int(match.group(1).replace(",", ""))
        actual = collected_tests

        assert actual >= claimed, (
            f"{rel} promises {claimed}+ {what}; pytest collects {actual}. "
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

# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the packaging metadata that makes a published number re-derivable.

These files are not code, but they decide which numeric stack a fresh install
resolves to and which licence a Zenodo deposit claims — the historical v0.1.0
record asserted MIT for AGPL-3.0-or-later code because nothing here checked.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
PYPROJECT = REPO_ROOT / "pyproject.toml"
ZENODO = REPO_ROOT / ".zenodo.json"
CODEMETA = REPO_ROOT / "codemeta.json"
CONSTRAINTS = REPO_ROOT / "envs" / "constraints.txt"


def _dockerfiles() -> list[Path]:
    """Every Dockerfile the repository ships, found rather than named.

    This module read ``REPO_ROOT / "Dockerfile"`` and nothing else, so the
    public demo Space's image — the one image real users actually meet — was
    outside the scope of both the digest-pin and the constraints checks for as
    long as that single path went unrevised.
    """
    found = [
        p
        for p in REPO_ROOT.rglob("Dockerfile*")
        if p.is_file() and not set(p.relative_to(REPO_ROOT).parts) & {".git", "node_modules"}
    ]
    return sorted(found)


DOCKERFILES = _dockerfiles()
DOCKERFILE = REPO_ROOT / "Dockerfile"

#: Libraries whose release can move the numbers a run reports. An unbounded
#: `>=` on any of these lets a resolver silently cross a breaking boundary.
RESULT_AFFECTING = ["pydeseq2", "numpy", "scipy", "pandas", "pyarrow", "biopython", "matplotlib"]

_REQ_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")


def _pyproject() -> dict:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))


def _requirements() -> dict[str, str]:
    """Every requirement pyproject declares, mapped name -> specifier text."""
    project = _pyproject()["project"]
    specs: dict[str, str] = {}
    groups = [project.get("dependencies", [])]
    groups += list(project.get("optional-dependencies", {}).values())
    for group in groups:
        for req in group:
            match = _REQ_NAME.match(req)
            if match is None:  # pragma: no cover - malformed requirement
                continue
            name = match.group(1).lower()
            specs[name] = req[match.end() :]
    return specs


# ---------------------------------------------------------------------------
# Zenodo deposit metadata
# ---------------------------------------------------------------------------
def test_zenodo_metadata_parses() -> None:
    data = json.loads(ZENODO.read_text(encoding="utf-8"))
    assert data["title"].strip()
    assert data["upload_type"] == "software"
    assert data["creators"]


def test_zenodo_license_is_agpl_and_matches_pyproject() -> None:
    """The v0.1.0 record said MIT for AGPL code; the deposit must state the SPDX id."""
    data = json.loads(ZENODO.read_text(encoding="utf-8"))
    assert data["license"] == "AGPL-3.0-or-later"
    assert data["license"] == _pyproject()["project"]["license"]


def test_zenodo_version_matches_the_package_version() -> None:
    data = json.loads(ZENODO.read_text(encoding="utf-8"))
    assert data["version"].lstrip("v") == _pyproject()["project"]["version"]


# ---------------------------------------------------------------------------
# Dependency bounds
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("package", RESULT_AFFECTING)
def test_result_affecting_dependency_has_an_upper_bound(package: str) -> None:
    spec = _requirements().get(package)
    assert spec is not None, f"{package} is not declared in pyproject"
    assert "<" in spec, f"{package}{spec} is unbounded above; a resolver may cross a major"


def test_scipy_is_declared_explicitly_not_left_transitive() -> None:
    # scipy arrives via pydeseq2, but its numerics move DEG results, so the
    # bound has to be stated here rather than inherited from whatever resolves.
    assert "scipy" in _requirements()


# ---------------------------------------------------------------------------
# Pinned environment
# ---------------------------------------------------------------------------
def test_constraints_file_exists_and_pins_the_scientific_stack() -> None:
    assert CONSTRAINTS.is_file()
    lines = [
        line.strip()
        for line in CONSTRAINTS.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    assert lines, "constraints.txt carries no pins"
    pinned = {line.split("==")[0].lower() for line in lines if "==" in line}
    assert len(pinned) == len(lines), "every constraint must be an exact `==` pin"
    for package in ("pydeseq2", "numpy", "scipy", "pandas", "pyarrow"):
        assert package in pinned


def test_constraints_respect_the_pyproject_bounds() -> None:
    """A pin outside its own declared range would be unresolvable."""
    specs = _requirements()
    for line in CONSTRAINTS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "==" not in line:
            continue
        name, _, version = line.partition("==")
        spec = specs.get(name.lower())
        if spec is None:
            continue  # a transitive pin (e.g. formulaic); nothing to compare against
        upper = re.search(r"<\s*(\d+)", spec)
        assert upper is not None, f"{name} is pinned but unbounded in pyproject"
        assert int(version.split(".")[0]) <= int(upper.group(1))


# ---------------------------------------------------------------------------
# Container base image
# ---------------------------------------------------------------------------
def test_the_dockerfile_scan_finds_both_images() -> None:
    """Guards the guard. These checks read one hard-coded path, so the public
    demo Space's image — the one real users meet — was outside both of them."""
    names = {p.relative_to(REPO_ROOT).as_posix() for p in DOCKERFILES}

    assert "Dockerfile" in names, names
    assert ".huggingface/Dockerfile" in names, f"the Space image is not in scope; found {names}"


@pytest.mark.parametrize("path", DOCKERFILES, ids=lambda p: p.relative_to(REPO_ROOT).as_posix())
def test_every_dockerfile_pins_its_base_image_by_digest(path: Path) -> None:
    """A tag is republished on patch; only the digest identifies an image."""
    text = path.read_text(encoding="utf-8")
    from_lines = [line for line in text.splitlines() if line.strip().startswith("FROM ")]
    assert from_lines, f"{path.name} declares no base image"
    for line in from_lines:
        assert re.search(r"@sha256:[0-9a-f]{64}\b", line), (
            f"{path.relative_to(REPO_ROOT).as_posix()}: {line.strip()!r} is not digest-pinned"
        )


@pytest.mark.parametrize("path", DOCKERFILES, ids=lambda p: p.relative_to(REPO_ROOT).as_posix())
def test_every_dockerfile_installs_through_pinned_versions(path: Path) -> None:
    """Two mechanisms are acceptable and both are pinned: ``-c envs/constraints.txt``
    (the root image) and ``-r requirements.txt`` (the Space, whose file is kept in
    step with pyproject by tests/test_requirements_mirror.py). An unpinned
    ``pip install`` in either is a build that cannot be reproduced.
    """
    text = path.read_text(encoding="utf-8")
    installs = [line for line in text.splitlines() if re.search(r"\bpip3?\s+install\b", line)]
    assert installs, f"{path.name} installs nothing"
    for line in installs:
        pinned = re.search(r"-c\s+envs/constraints\.txt", line) or re.search(
            r"-r\s+requirements\.txt", line
        )
        assert pinned, (
            f"{path.relative_to(REPO_ROOT).as_posix()}: {line.strip()!r} installs "
            "without a constraints or requirements file, so the build is not reproducible"
        )


# ---------------------------------------------------------------------------
# codemeta.json — read by software registries and citation indexers
# ---------------------------------------------------------------------------
def test_codemeta_agrees_with_pyproject_and_zenodo() -> None:
    """Three metadata files describe one release; drift misattributes it."""
    codemeta = json.loads(CODEMETA.read_text(encoding="utf-8"))
    pyproject = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]
    zenodo = json.loads(ZENODO.read_text(encoding="utf-8"))

    assert codemeta["version"] == pyproject["version"]
    assert codemeta["version"] == zenodo["version"].removeprefix("v")
    # SPDX identifier, expressed as the licence URL codemeta expects.
    assert codemeta["license"].rstrip("/").endswith(pyproject["license"])
    assert zenodo["license"] == pyproject["license"]


def test_codemeta_cites_the_concept_doi() -> None:
    """A version DOI would pin indexers to one release forever."""
    codemeta = json.loads(CODEMETA.read_text(encoding="utf-8"))
    assert codemeta["identifier"].endswith("10.5281/zenodo.PENDING")


# ---------------------------------------------------------------------------
# A command must work from what the wheel actually contains
# ---------------------------------------------------------------------------
def _wheel_paths() -> set[str]:
    """Every path the built wheel would contain, from the build config.

    Read from pyproject rather than by building, so this test costs nothing and
    runs everywhere; the packaged-data claims below are about configuration.
    """
    import tomllib

    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    return set(
        data.get("tool", {})
        .get("hatch", {})
        .get("build", {})
        .get("targets", {})
        .get("wheel", {})
        .get("shared-data", {})
    )


class TestEntryPointsResolveFromTheInstall:
    """`bindsight ui` looked for a root-level streamlit_app.py, which the wheel
    does not contain, so the command worked only from a source checkout. Its
    sibling — `report --format streamlit` — already imported the packaged module,
    so one file held both the right and the wrong way to find the same app.
    """

    @staticmethod
    def _cli_source() -> str:
        return (REPO_ROOT / "bindsight" / "cli.py").read_text(encoding="utf-8")

    def test_no_command_launches_a_path_outside_the_package(self) -> None:
        source = self._cli_source()

        assert 'repo_root / "streamlit_app.py"' not in source, (
            "a command resolves its entry point relative to the repository root; "
            "that path does not exist in an installed wheel"
        )

    def test_the_ui_launches_the_packaged_module(self) -> None:
        source = self._cli_source()

        assert source.count("from bindsight.report import streamlit_app") >= 2, (
            "the ui and the streamlit report should both resolve the packaged "
            "module; one of them is resolving something else"
        )

    def test_the_packaged_entry_point_exists(self) -> None:
        """The module the commands launch must actually be in the package."""
        assert (REPO_ROOT / "bindsight" / "report" / "streamlit_app.py").is_file()

    def test_the_demo_can_find_its_config_from_an_installed_layout(self) -> None:
        """The wheel installs the demo config as shared-data under sys.prefix.
        Nothing read that location, so `bindsight demo` — the one-button entry
        point — could only ever run from a source checkout."""
        source = self._cli_source()
        shared = _wheel_paths()

        assert shared, "pyproject declares no shared-data; the demo config ships nowhere"
        assert "Path(sys.prefix)" in source, (
            "no command resolves the shared-data location, so an installed "
            f"bindsight cannot find files shipped to it (declared: {sorted(shared)})"
        )
        assert "bindsight_demo" in source, (
            "the shared-data directory pyproject installs into is never referenced "
            "by the code that needs to read from it"
        )


class TestAnImageInstallsWhatItsHeaderPromises:
    """The CPU image's header said the Snakemake front-end runs in it; the
    install line omitted the `workflow` extra, so snakemake was simply absent.
    """

    def test_the_cpu_image_installs_the_workflow_extra(self) -> None:
        text = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
        if "Snakemake" not in text:
            pytest.skip("the image no longer promises the Snakemake front-end")

        install = [ln for ln in text.splitlines() if "pip install" in ln]
        assert install, "the image installs nothing"
        assert any("workflow" in ln for ln in install), (
            "the image's header promises the Snakemake front-end and the install "
            f"line does not include the extra that provides it: {install}"
        )


class TestTheDocumentedExtrasMatchTheDeclaredOnes:
    """The docs said `.[all]` installs everything. It deliberately excludes two."""

    def test_the_all_extra_is_described_by_what_it_contains(self) -> None:
        import tomllib

        extras = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"][
            "optional-dependencies"
        ]
        covered: list[str] = []
        for dep in extras["all"]:
            if "[" in dep:
                covered = [e.strip() for e in dep.split("[", 1)[1].rstrip("]").split(",")]
        uncovered = sorted(set(extras) - set(covered) - {"all", "dev"})
        text = (REPO_ROOT / "docs" / "how-to-use.md").read_text(encoding="utf-8")

        assert "`.[all]` installs everything" not in text, (
            f"the docs claim `.[all]` installs everything; it omits {uncovered}"
        )
        for extra in uncovered:
            assert f"`{extra}`" in text, (
                f"`.[all]` omits the `{extra}` extra and the docs never mention it"
            )


class TestThePythonVersionsAgreeAcrossTheProject:
    """The hosted demo Space ran a Python the classifiers did not claim and the CI
    matrix did not test. Three files describe one supported set; two of them
    disagreed with the one that is actually deployed.
    """

    @staticmethod
    def _classifier_versions() -> set[str]:
        import re

        text = PYPROJECT.read_text(encoding="utf-8")
        return set(re.findall(r"Programming Language :: Python :: (\d+\.\d+)", text))

    @staticmethod
    def _matrix_versions() -> set[str]:
        import re

        text = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        match = re.search(r"python-version:\s*\[([^\]]+)\]", text)
        assert match, "no python-version matrix found in ci.yml"
        return set(re.findall(r"\d+\.\d+", match.group(1)))

    @staticmethod
    def _deployed_version() -> str:
        import re

        text = (REPO_ROOT / ".huggingface" / "Dockerfile").read_text(encoding="utf-8")
        match = re.search(r"FROM python:(\d+\.\d+)", text)
        assert match, "the Space Dockerfile names no Python version"
        return match.group(1)

    def test_the_deployed_interpreter_is_tested(self) -> None:
        deployed = self._deployed_version()

        assert deployed in self._matrix_versions(), (
            f"the public demo runs Python {deployed}, which the CI matrix "
            f"{sorted(self._matrix_versions())} never tests"
        )

    def test_the_deployed_interpreter_is_claimed(self) -> None:
        deployed = self._deployed_version()

        assert deployed in self._classifier_versions(), (
            f"the public demo runs Python {deployed}, which the classifiers "
            f"{sorted(self._classifier_versions())} do not claim"
        )

    def test_every_tested_version_is_claimed(self) -> None:
        """Testing a version the package does not claim tells users nothing."""
        untested_claim = self._matrix_versions() - self._classifier_versions()

        assert not untested_claim, (
            f"CI tests {sorted(untested_claim)} but the classifiers do not list them"
        )

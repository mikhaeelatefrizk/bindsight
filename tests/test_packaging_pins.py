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
def test_dockerfile_pins_its_base_image_by_digest() -> None:
    """A tag is republished on patch; only the digest identifies an image."""
    text = DOCKERFILE.read_text(encoding="utf-8")
    from_lines = [line for line in text.splitlines() if line.strip().startswith("FROM ")]
    assert from_lines, "Dockerfile declares no base image"
    for line in from_lines:
        assert re.search(r"@sha256:[0-9a-f]{64}\b", line), f"{line.strip()!r} is not digest-pinned"


def test_dockerfile_installs_through_the_constraints_file() -> None:
    text = DOCKERFILE.read_text(encoding="utf-8")
    assert "envs/constraints.txt" in text
    assert re.search(r"pip install[^\n]*-c\s+envs/constraints\.txt", text)


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
    assert codemeta["identifier"].endswith("10.5281/zenodo.20121495")

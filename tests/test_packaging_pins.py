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
from packaging.requirements import Requirement
from packaging.version import Version

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


def _result_affecting() -> list[str]:
    """Libraries whose release can move a number, read from the project's own list.

    This was a seven-name list, hand-written, and it omitted eight distributions
    that ``provenance.manifest.SCIENTIFIC_STACK`` declares result-affecting and
    records in every manifest: formulaic, formulaic-contrasts, scikit-learn,
    anndata, h5py, zarr, numcodecs, torch, transformers. ``torch`` and
    ``transformers`` drive the ESM-2 prescreen that decides which designs reach
    validation, and both are declared ``>=`` with no ceiling -- so a resolver
    could cross a major boundary, change the design set, and this test would
    stay green because the package was outside its own scope.

    One declaration, two consumers. If a library is worth recording in a
    manifest because it can move a number, it is worth bounding.
    """
    from bindsight.provenance.manifest import PRESENTATION_ONLY, SCIENTIFIC_STACK

    return sorted(set(SCIENTIFIC_STACK) - set(PRESENTATION_ONLY))


RESULT_AFFECTING = _result_affecting()

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
def _constraint_pins() -> dict[str, str]:
    """``name -> version`` from ``envs/constraints.txt``."""
    pins: dict[str, str] = {}
    for line in CONSTRAINTS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "==" not in line:
            continue
        name, _, version = line.partition("==")
        pins[name.strip().lower()] = version.strip()
    return pins


@pytest.mark.parametrize("package", RESULT_AFFECTING)
def test_result_affecting_dependency_is_bounded_somewhere(package: str) -> None:
    """Every library that can move a number must have its version constrained.

    There are two honest ways to do that, and this checks the right one applies:

    - **Declared in pyproject** -- then it needs an upper bound, or a resolver
      may cross a breaking boundary. ``torch`` and ``transformers`` sit here and
      had none, while driving the ESM-2 prescreen that decides which designs
      reach validation.
    - **Arrives transitively** (formulaic, anndata, h5py, zarr, numcodecs and
      the rest come in through pydeseq2) -- then pyproject has nothing to bound,
      and the constraint has to be an exact pin in ``envs/constraints.txt``.

    The previous scope was a seven-name list that omitted eight of these, so the
    check passed for packages nothing constrained at all. It is now derived from
    ``SCIENTIFIC_STACK`` -- the project's own declaration of what moves a number.
    """
    spec = _requirements().get(package)
    if spec is not None:
        assert "<" in spec, (
            f"{package}{spec} is declared in pyproject and unbounded above; "
            "a resolver may cross a major boundary and move a published number"
        )
        return

    pins = _constraint_pins()
    assert package.lower() in pins, (
        f"{package} is recorded as result-affecting in SCIENTIFIC_STACK but is "
        "neither declared in pyproject nor pinned in envs/constraints.txt, so "
        "nothing constrains the version that produces a number"
    )


def test_every_constraint_pin_is_applied_where_results_are_produced() -> None:
    """A pin nothing applies is a decoration.

    ``envs/constraints.txt`` describes itself as "the exact versions this release
    was resolved and tested against". Only the Dockerfile ever passed ``-c``;
    CI installed without it. So the pins governed the container and nothing
    else, and the ranges in pyproject were the only real constraint -- which is
    why a Dependabot PR that widened one range was the only one of four that
    changed what CI resolved.
    """
    appliers = [
        path.name
        for path in (*DOCKERFILES, REPO_ROOT / ".github" / "workflows" / "ci.yml")
        if path.is_file() and "-c envs/constraints.txt" in path.read_text(encoding="utf-8")
    ]

    assert "ci.yml" in appliers, (
        "CI installs without -c envs/constraints.txt, so the pinned versions the "
        f"project claims to be tested against are never the versions tested. "
        f"Applied by: {appliers or 'nothing'}"
    )


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
        # Resolve the pin against the declared specifier itself rather than
        # comparing major digits. Two defects lived in that arithmetic: it used
        # ``<=`` against an exclusive ``<`` bound, so ``pyarrow==25.0.1`` under
        # ``<25`` computed ``25 <= 25`` and passed; and it only ever read the
        # major, so ``pydeseq2==0.5.4`` under ``<0.6`` compared 0 against 0 and
        # could not see a minor ceiling at all. The one test whose job is
        # catching a pin outside its range was blind to both boundary cases.
        requirement = Requirement(f"{name}{spec}")
        assert any(op in spec for op in ("<", "==")), (
            f"{name} is pinned but unbounded above in pyproject ({spec!r})"
        )
        assert requirement.specifier.contains(Version(version), prereleases=True), (
            f"{name}=={version} falls outside the range {spec!r} that pyproject "
            "declares; pip cannot resolve this combination"
        )


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
    """`bindsight ui` looked for a root-level file the wheel does not contain,
    so the command worked only from a source checkout.

    The interface is served from inside the package now, which moves the risk:
    it is no longer a wrong path but a **missing file**. Its templates and
    assets are not importable modules, so they ship only if `force-include`
    names them, and that list is written by hand. A template added next month
    renders in every test -- the tests read the source tree -- and 404s in the
    wheel. So the guard below is a sweep rather than a list.
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

    def test_the_ui_launches_the_packaged_interface(self) -> None:
        """Both `ui` and `report --format web` must resolve the same module."""
        source = self._cli_source()

        assert source.count("from bindsight.report.web.app import serve") >= 2, (
            "the ui and the web report should both resolve the packaged "
            "interface; one of them is resolving something else"
        )

    def test_the_packaged_entry_point_exists(self) -> None:
        """The module the commands launch must actually be in the package."""
        assert (REPO_ROOT / "bindsight" / "report" / "web" / "app.py").is_file()

    def test_every_template_and_asset_the_interface_needs_is_in_the_wheel(
        self, tmp_path: Path
    ) -> None:
        """Built and opened, because the config cannot answer this.

        An earlier version of this guard compared the tree against the
        ``force-include`` table and would have passed a build that shipped
        nothing -- those entries were duplicates of what ``packages`` already
        collects, and re-adding them as directories broke the build. Templates
        and static files are not importable modules: if they are absent, every
        test still passes, because tests read the source tree, and a
        pip-installed user gets a 404 on every page.
        """
        import subprocess
        import sys
        import zipfile

        out = tmp_path / "dist"
        built = subprocess.run(
            [sys.executable, "-m", "build", "--wheel", "--no-isolation", "--outdir", str(out)],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        if built.returncode != 0:
            pytest.skip(f"wheel build unavailable here: {built.stderr.strip()[-200:]}")

        wheels = sorted(out.glob("*.whl"))
        assert wheels, "the build reported success and produced no wheel"
        shipped = set(zipfile.ZipFile(wheels[-1]).namelist())

        web = REPO_ROOT / "bindsight" / "report" / "web"
        needed = {
            p.relative_to(REPO_ROOT).as_posix()
            for d in ("templates", "static")
            for p in (web / d).rglob("*")
            if p.is_file()
        }
        assert needed, "the interface has no templates or assets; the sweep found nothing"

        missing = sorted(needed - shipped)
        assert not missing, (
            "these files are served by the interface and are not in the wheel, so "
            f"a pip-installed user gets a 404 where a clone works: {missing}"
        )

    def test_the_shipped_list_has_no_entries_that_left_the_tree(self) -> None:
        """A force-include naming a deleted file is a build error on some
        backends and silent rot on the rest."""
        import tomllib

        pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        shipped = pyproject["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]

        absent = sorted(rel for rel in shipped if not (REPO_ROOT / rel).exists())
        assert not absent, f"force-include names files that are not in the tree: {absent}"

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


def test_the_space_ships_what_its_pages_render() -> None:
    """The Space image must carry the artifacts its Real results page reads.

    ``bindsight/report/showcase.py`` locates evidence by walking up for a
    ``benchmarks/`` directory, and the README tells visitors the Space renders
    twenty binders in 3-D. The Dockerfile copies a named set of paths and
    ``benchmarks/`` was not one of them, so ``benchmarks_root()`` returned
    ``None``, the page rendered nothing, and the module docstring asserted the
    opposite -- that the Space "deploys the full repository".

    A promise on the front page about a hosted demo is the one claim a reader
    can check in ten seconds without installing anything.
    """
    dockerfile = (REPO_ROOT / ".huggingface" / "Dockerfile").read_text(encoding="utf-8")

    copied = {
        line.split()[1].rstrip("/")
        for line in dockerfile.splitlines()
        if line.strip().startswith("COPY ") and len(line.split()) >= 3
    }

    assert "benchmarks" in copied, (
        "the Space image does not copy benchmarks/, so its Real results page "
        f"renders nothing. It copies: {sorted(copied)}"
    )
    assert "examples" in copied, "the demo cohort is not shipped"


def test_the_showcase_docstring_does_not_claim_a_full_deploy() -> None:
    """Guards the guard: the docstring was the reason nobody looked."""
    source = (REPO_ROOT / "bindsight" / "report" / "showcase.py").read_text(encoding="utf-8")

    # Flattened, because the sentence wrapped across two lines and a
    # substring check on the raw text would miss it for that reason alone.
    flattened = " ".join(source.split())

    assert "deploys the full repository" not in flattened, (
        "showcase.py claims the Space deploys the full repository; it deploys "
        "the paths .huggingface/Dockerfile names"
    )


def test_the_result_affecting_scope_covers_the_recorded_stack() -> None:
    """The scope must be the project's own declaration, not a subset of it.

    Guards the guard. Narrowing ``RESULT_AFFECTING`` back to a hand-written list
    fails nothing on its own -- every package left in it is bounded, so the
    tests still pass while checking less. That is exactly how the original
    seven-name list came to omit eight distributions ``SCIENTIFIC_STACK``
    declares result-affecting, including ``torch`` and ``transformers``, both
    unbounded and both driving the prescreen that decides which designs reach
    validation.

    A scope that can silently cover less is not a scope.
    """
    from bindsight.provenance.manifest import PRESENTATION_ONLY, SCIENTIFIC_STACK

    declared = set(SCIENTIFIC_STACK) - set(PRESENTATION_ONLY)
    missing = sorted(declared - set(RESULT_AFFECTING))

    assert not missing, (
        f"these are recorded as result-affecting in SCIENTIFIC_STACK but are "
        f"outside the scope this file checks: {missing}"
    )


def test_ci_installs_with_the_constraints_file() -> None:
    """Checking that the filename *appears* is not checking that it is applied.

    The first version of this guard searched for the string ``constraints.txt``
    anywhere in the workflow -- which a comment satisfies. It has to look for
    the install flag.
    """
    ci = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "-c envs/constraints.txt" in ci, (
        "no CI job installs with -c envs/constraints.txt, so the versions the "
        "project records as tested are never the versions tested"
    )


class TestTheInterfaceTestsCanActuallyRun:
    """A test that does not run is not a test.

    ``tests/test_web_ui.py`` opens with ``importorskip("fastapi")``, so a
    missing extra makes it vanish rather than fail. That is the right behaviour
    for an optional extra and the wrong behaviour for a *broken* one: on CI the
    extra was installed and the module still could not run, because
    ``starlette.testclient`` needs ``httpx2``/``httpx`` and nothing declared it.

    It errored there, which was luck -- an error is loud. One layer of
    ``importorskip`` further and it would have skipped instead, and CI would
    have reported success with 67 guards running nowhere.

    The first test below is static, so it runs in every environment including
    the ones where the extra is absent. That matters: a guard that skips
    alongside the thing it guards protects nothing.
    """

    #: What ``starlette.testclient`` will try to import, in its own order.
    TEST_CLIENT_BACKENDS = ("httpx2", "httpx")

    def test_the_test_client_backend_is_declared_somewhere(self) -> None:
        """Static: no imports, so this cannot skip with what it is guarding."""
        declared = set(_requirements())

        assert declared & set(self.TEST_CLIENT_BACKENDS), (
            "nothing in pyproject.toml declares the package starlette.testclient "
            f"needs (one of {list(self.TEST_CLIENT_BACKENDS)}), so a clean install "
            "cannot run tests/test_web_ui.py — which is how 67 interface guards "
            "came to run nowhere on CI while passing locally off a leftover "
            "transitive dependency of the deleted Streamlit package"
        )

    def test_the_interface_extra_is_enough_to_drive_the_interface(self) -> None:
        """Dynamic: where the extra IS installed, the client must be usable.

        Declaring the dependency is not the same as it working — a wrong pin or
        an incompatible starlette would leave this red while the static check
        above stays green.
        """
        pytest.importorskip("fastapi", reason="the report extra is not installed here")

        from starlette.testclient import TestClient  # must not raise

        assert TestClient is not None

    def test_the_web_interface_suite_is_not_empty(self) -> None:
        """And it must still contain the guards it is supposed to contain."""
        module = REPO_ROOT / "tests" / "test_web_ui.py"
        body = module.read_text(encoding="utf-8")

        assert body.count("def test_") >= 40, (
            f"tests/test_web_ui.py declares {body.count('def test_')} tests; the "
            "interface guards have been removed rather than fixed"
        )

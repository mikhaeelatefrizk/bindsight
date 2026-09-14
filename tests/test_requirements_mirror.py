# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""``requirements.txt`` must stay an exact mirror of the pyproject extras.

The repository carries the same dependency list twice: once as
``[project.optional-dependencies]`` in ``pyproject.toml``, and once flattened
into ``requirements.txt`` for hosts that install from a requirements file. A
second copy of a list is a thing that drifts, and this one had: it omitted
``openpyxl``, which parses the SURFY surfaceome workbook. Without it discovery
has no surfaceome to filter against, so a deployment installed from that file
would start cleanly and then find nothing, with no error naming the cause.

It also carried ``gql`` and ``seaborn``, which nothing in the package imports.

Rather than delete the file or trust it to hand-maintenance, these tests make
the two lists provably identical in both directions.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
#: The extras the flat file claims to mirror. Its own header states this pair.
MIRRORED_EXTRAS = ("discover", "report")


def _pyproject_requirements() -> set[str]:
    """The union of the mirrored extras, as written in pyproject.toml."""
    data = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    extras = data["project"]["optional-dependencies"]
    out: set[str] = set()
    for name in MIRRORED_EXTRAS:
        assert name in extras, f"pyproject has no {name!r} extra to mirror"
        # Strip trailing comments; the extras annotate several entries.
        out |= {spec.split("#", 1)[0].strip() for spec in extras[name]}
    return out


def _flat_requirements() -> set[str]:
    """The pinned lines of requirements.txt, minus comments and the self-install."""
    text = (REPO / "requirements.txt").read_text(encoding="utf-8")
    out: set[str] = set()
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line in {"-e .", "."}:
            continue
        out.add(line)
    return out


def _name(spec: str) -> str:
    """The distribution name from a requirement specifier, lowercased."""
    for sep in ("[", ">", "<", "=", "!", "~", ";", " "):
        spec = spec.split(sep, 1)[0]
    return spec.strip().lower()


class TestMirrorIsExact:
    def test_the_flat_file_installs_the_self_package(self) -> None:
        """Without ``-e .`` the file installs bindsight's dependencies but not bindsight."""
        text = (REPO / "requirements.txt").read_text(encoding="utf-8")
        assert any(ln.strip() == "-e ." for ln in text.splitlines())

    def test_nothing_in_the_extras_is_missing_from_the_flat_file(self) -> None:
        """The failure this catches is silent: a host installs and then finds nothing.

        ``openpyxl`` was the real instance. It parses the SURFY workbook, so
        omitting it leaves discovery with an empty surfaceome rather than an
        import error.
        """
        missing = {_name(s) for s in _pyproject_requirements()} - {
            _name(s) for s in _flat_requirements()
        }
        assert not missing, (
            f"requirements.txt omits {sorted(missing)}, which "
            f"pip install -e '.[{','.join(MIRRORED_EXTRAS)}]' would install"
        )

    def test_the_flat_file_declares_nothing_extra(self) -> None:
        """A dependency here and nowhere else is one every deployer installs for nothing.

        ``gql`` and ``seaborn`` were both in this state: declared here, imported
        by no module. ``gql`` in particular pulls a whole GraphQL stack, while
        the Open Targets client is plain ``requests``.
        """
        extra = {_name(s) for s in _flat_requirements()} - {
            _name(s) for s in _pyproject_requirements()
        }
        assert not extra, (
            f"requirements.txt declares {sorted(extra)}, which no pyproject extra does. "
            "Add it to the extra it belongs to, or drop it."
        )

    def test_the_version_bounds_agree(self) -> None:
        """Same package, different ceiling, is how two lists resolve to two environments."""
        flat = {_name(s): s for s in _flat_requirements()}
        for spec in _pyproject_requirements():
            name = _name(spec)
            assert flat.get(name) == spec, (
                f"{name}: pyproject says {spec!r}, requirements.txt says {flat.get(name)!r}"
            )


#: Distributions whose import name differs from the name pip installs. Only the
#: handful that differ; everything else maps to itself.
_IMPORT_NAMES: dict[str, str] = {
    "pyyaml": "yaml",
    "scikit-learn": "sklearn",
    "biopython": "Bio",
    "pydantic-settings": "pydantic_settings",
    "python-dateutil": "dateutil",
    "pillow": "PIL",
    "typing-extensions": "typing_extensions",
    "formulaic-contrasts": "formulaic_contrasts",
}

#: Declared dependencies that no module imports directly, each with its reason.
#: A dependency reaches the environment for a purpose; when that purpose is not
#: an import, the purpose is written down here rather than left to be guessed.
_INDIRECT: dict[str, str] = {
    "openpyxl": "pandas.read_excel's engine for the SURFY .xlsx; imported by pandas",
    "pyarrow": "pandas' parquet engine; imported by pandas, not by bindsight",
}


def _imported_top_level_modules() -> set[str]:
    """Every third-party module the package imports, found by parsing."""
    import ast

    found: set[str] = set()
    for path in (REPO / "bindsight").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                found.add(node.module.split(".")[0])
    return found


class TestNoDeadDependencies:
    """Every declared dependency should be imported by something.

    This class asserted that three historically-removed names stay removed. That
    keeps three packages out; it says nothing about the dozens declared now, so a
    dependency added and never used would sit in every user's environment
    unnoticed — which is exactly how the three got there.
    """

    def test_the_import_scan_finds_the_obvious_ones(self) -> None:
        """Guards the guard: a parse that found nothing would pass everything."""
        imported = _imported_top_level_modules()

        assert {"pandas", "pydantic", "click"} <= imported, sorted(imported)[:20]

    @staticmethod
    def _all_declared() -> set[str]:
        """The mirrored extras **and** the base dependencies.

        ``_pyproject_requirements`` covers only the extras it mirrors into
        requirements.txt, so ``project.dependencies`` — the set every single
        install receives — was outside this check entirely.
        """
        import tomllib

        data = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
        base = {spec.split("#", 1)[0].strip() for spec in data["project"]["dependencies"]}
        return base | _pyproject_requirements()

    def test_the_scan_covers_the_base_dependencies(self) -> None:
        """Guards the guard: the extras-only scope is what let this miss them."""
        import tomllib

        data = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
        base = {_name(spec) for spec in data["project"]["dependencies"]}
        covered = {_name(spec) for spec in self._all_declared()}

        assert base, "pyproject declares no base dependencies"
        assert base <= covered, sorted(base - covered)

    def test_every_declared_dependency_is_imported_or_explained(self) -> None:
        imported = _imported_top_level_modules()
        unexplained: list[str] = []
        for spec in self._all_declared():
            name = _name(spec)
            module = _IMPORT_NAMES.get(name, name.replace("-", "_"))
            # Case-insensitively: PyPI names are case-insensitive and pip
            # normalises them, so the distribution `py3Dmol` is declared as
            # `py3dmol` while the module it installs is `py3Dmol`.
            if module.lower() in {m.lower() for m in imported} or name in _INDIRECT:
                continue
            unexplained.append(name)

        assert not unexplained, (
            f"declared but never imported, and with no stated indirect use: "
            f"{unexplained}. Add the import, drop the dependency, or record why "
            "it is needed in _INDIRECT."
        )

    def test_the_indirect_list_has_no_stale_entries(self) -> None:
        """An entry for a dependency that no longer exists hides the next one."""
        declared = {_name(spec) for spec in self._all_declared()}
        stale = sorted(set(_INDIRECT) - declared)

        assert not stale, f"_INDIRECT explains dependencies that are gone: {stale}"

    def test_the_removed_three_stay_removed(self) -> None:
        """gql, seaborn and pydantic-settings were declared and never imported.

        pydantic-settings was the costliest: a mandatory runtime dependency in
        the conda environment, so every user installed it for nothing.
        """
        watched = ("gql", "seaborn", "pydantic-settings", "pydantic_settings")
        for path in ("requirements.txt", "envs/discover.yaml", "pyproject.toml"):
            text = (REPO / path).read_text(encoding="utf-8")
            body = "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))
            for pkg in watched:
                assert pkg not in body, f"{path} declares {pkg}, which nothing imports"

# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Check the installed environment against what the project declares.

Two claims are checked, both of which were silently false:

1. **Every version in ``envs/constraints.txt`` is the version installed.** That
   file describes itself as "the exact versions this release was resolved and
   tested against". Nothing applied it outside the Dockerfile, so it described
   an environment no test ever ran in — it recorded ``pyarrow==20.0.0`` while
   the resolver installed 24.

2. **Every installed distribution satisfies the range pyproject declares.**
   Nothing checked this either: the working environment carried
   ``pyarrow 24`` against a pin of ``20``, and a UI dependency two minor
   versions under its own declared floor.

Run by the ``pinned`` CI job, and useful locally::

    python scripts/check_pinned_environment.py
    python scripts/check_pinned_environment.py --ranges-only
"""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONSTRAINTS = ROOT / "envs" / "constraints.txt"
PYPROJECT = ROOT / "pyproject.toml"

_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")


def _installed(name: str) -> str | None:
    try:
        return version(name)
    except PackageNotFoundError:
        return None


def _declared_ranges() -> dict[str, str]:
    """``name -> specifier`` across base dependencies and every extra."""
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    project = data["project"]
    specs: dict[str, str] = {}
    groups = [project.get("dependencies") or []]
    groups += list((project.get("optional-dependencies") or {}).values())
    for group in groups:
        for raw in group:
            raw = raw.split("#", 1)[0].strip()
            match = _NAME.match(raw)
            if not match or raw.startswith("bindsight["):
                continue
            specs[match.group(1).lower()] = raw[match.end() :].strip()
    return specs


def check_pins() -> list[str]:
    """Constraint pins that are not what is installed."""
    problems: list[str] = []
    if not CONSTRAINTS.is_file():
        return ["envs/constraints.txt is missing"]
    for line in CONSTRAINTS.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or "==" not in line:
            continue
        name, _, pinned = line.partition("==")
        name, pinned = name.strip(), pinned.strip()
        got = _installed(name)
        if got is None:
            continue  # an extra this environment did not install
        if got != pinned:
            problems.append(f"{name}: pinned {pinned}, installed {got}")
    return problems


def check_ranges() -> list[str]:
    """Installed distributions that fall outside their declared range."""
    try:
        from packaging.requirements import Requirement
        from packaging.version import Version
    except ImportError:  # pragma: no cover
        return []

    problems: list[str] = []
    for name, spec in _declared_ranges().items():
        if not spec:
            continue
        got = _installed(name)
        if got is None:
            continue
        try:
            requirement = Requirement(f"{name}{spec}")
            if not requirement.specifier.contains(Version(got), prereleases=True):
                problems.append(f"{name}: declared {spec}, installed {got}")
        except Exception:  # pragma: no cover - a spec packaging cannot parse
            continue
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ranges-only",
        action="store_true",
        help="skip the exact-pin check; only verify declared ranges are satisfied",
    )
    args = parser.parse_args(argv)

    failures: list[str] = []

    if not args.ranges_only:
        pins = check_pins()
        if pins:
            failures.append("installed versions differ from envs/constraints.txt:")
            failures += [f"  {line}" for line in pins]

    ranges = check_ranges()
    if ranges:
        failures.append("installed versions fall outside the ranges pyproject declares:")
        failures += [f"  {line}" for line in ranges]

    if failures:
        print("\n".join(failures))
        return 1

    print("the installed environment matches what the project declares")
    return 0


if __name__ == "__main__":
    sys.exit(main())

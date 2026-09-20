# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Point README.md's relative links at GitHub for the PyPI long description.

PyPI renders a package's long description with no base URL, so every relative
link in README.md -- the licence badge's target, the glossary, the repository
map, `docs/`, `paper/` -- is dead on the project page, while the same file
renders perfectly on GitHub. Two READMEs would drift; one README rewritten at
build time does not. `release-artifacts.yml` runs this with ``--write`` on its
checkout, never commits the result, and builds the wheel and sdist from it, so
the description PyPI shows links to the tag the release was built from.

Files become ``blob/<ref>/<path>`` links, directories ``tree/<ref>/<path>``,
and images ``raw.githubusercontent.com`` URLs so they display. Absolute URLs,
in-page anchors and ``mailto:`` targets are left alone. The tree's README keeps
its relative links; ``tests/test_pypi_readme.py`` holds both halves.

    python scripts/pypi_readme.py --check              # would anything stay relative?
    python scripts/pypi_readme.py --write --ref v0.3.5 # rewrite README.md in place
"""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
REPO_URL = "https://github.com/mikhaeelatefrizk/bindsight"
RAW_URL = "https://raw.githubusercontent.com/mikhaeelatefrizk/bindsight"

#: A link target that already points somewhere PyPI can follow.
_ABSOLUTE = re.compile(r"^(https?://|#|mailto:)")
#: ``![alt](target)`` -- an image; the alt text carries no nested brackets.
_IMAGE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)\)")
#: ``](target)`` -- the tail of any link, so a badge wrapped in a link
#: (``[![alt](img)](LICENSE)``) is reached even though its label nests brackets.
_LINK_TAIL = re.compile(r"\]\(([^)\s]+)\)")


def package_version() -> str:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "version"
    ]


def _absolute(target: str, ref: str, root: Path, *, image: bool) -> str:
    path, _, fragment = target.partition("#")
    local = root / path
    if image:
        url = f"{RAW_URL}/{ref}/{path}"
    elif local.is_dir():
        url = f"{REPO_URL}/tree/{ref}/{path.rstrip('/')}"
    else:
        url = f"{REPO_URL}/blob/{ref}/{path}"
    return f"{url}#{fragment}" if fragment else url


def rewrite(text: str, ref: str, root: Path = ROOT) -> str:
    """Return ``text`` with every relative link target made absolute at ``ref``."""

    def image(match: re.Match[str]) -> str:
        alt, target = match.groups()
        if _ABSOLUTE.match(target):
            return match.group(0)
        return f"![{alt}]({_absolute(target, ref, root, image=True)})"

    def tail(match: re.Match[str]) -> str:
        target = match.group(1)
        if _ABSOLUTE.match(target):
            return match.group(0)
        return f"]({_absolute(target, ref, root, image=False)})"

    return _LINK_TAIL.sub(tail, _IMAGE.sub(image, text))


def relative_targets(text: str) -> list[str]:
    """Every link target in ``text`` that PyPI could not follow."""
    return [t for t in _LINK_TAIL.findall(text) if not _ABSOLUTE.match(t)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument(
        "--ref", default=None, help="git ref to link to (default: v<pyproject version>)"
    )
    parser.add_argument("--write", action="store_true", help="rewrite README.md in place")
    parser.add_argument(
        "--check", action="store_true", help="exit 1 if a relative link would survive the rewrite"
    )
    args = parser.parse_args(argv)
    ref = args.ref or f"v{package_version()}"

    text = README.read_text(encoding="utf-8")
    before = relative_targets(text)
    out = rewrite(text, ref)
    after = relative_targets(out)
    print(
        f"{len(before)} relative link(s) pointed at {ref}; {len(after)} would remain",
        file=sys.stderr,
    )
    if args.check and after:
        print("\n".join(after), file=sys.stderr)
        return 1
    if args.write:
        README.write_text(out, encoding="utf-8", newline="\n")
        print(f"wrote {README.relative_to(ROOT)}", file=sys.stderr)
    else:
        sys.stdout.write(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())

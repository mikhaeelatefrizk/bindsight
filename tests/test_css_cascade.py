# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A responsive override placed above the rule it overrides does nothing.

`.bs-viewer` was given `height: 17rem` inside `@media (max-width: 600px)` so the
3-D viewer would stop pushing its own picker and legend off a phone screen. The
media block sits near the top of `extra.css`; the base `.bs-viewer { height:
26rem }` is declared forty lines further down. Equal specificity, so source
order decides, and the base rule won. The stylesheet parsed, the build passed,
the media query matched at 375px, and the height never changed.

Nothing could have caught it. Contrast is checked, print rules are checked, but
"this declaration is unreachable" is not a thing either of those looks for, and
a browser is the only place it shows -- which means it shows to a reader before
it shows to anyone working on the file.

The rule here is narrow on purpose: a property declared for a selector inside a
media block, where the *same selector* declares the *same property* unconditionally
further down the file, is dead. That comparison needs no cascade model and no
specificity arithmetic, because the selectors are identical -- and it is exactly
the mistake that is easy to make, since media blocks feel like they belong
together at the bottom, or in this case at the top.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

#: Every stylesheet this project ships, found rather than listed: a new one
#: should be covered the day it lands, not the day someone remembers it.
_SEARCH_ROOTS = (
    REPO / "bindsight" / "report" / "web" / "static",
    REPO / "bindsight" / "report" / "templates",
    REPO / "docs" / "stylesheets",
)

_COMMENT = re.compile(r"/\*.*?\*/", re.S)


def _stylesheets() -> list[Path]:
    found: list[Path] = []
    for root in _SEARCH_ROOTS:
        if root.is_dir():
            found += [p for p in sorted(root.rglob("*.css")) if "vendor" not in p.parts]
    return found


def _declarations(css: str) -> tuple[list[tuple[str, str, int]], list[tuple[str, str, int]]]:
    """Split *css* into (unconditional, inside-a-media-block) declarations.

    Each entry is ``(selector, property, position)``. Positions are offsets into
    the source, which is all the ordering comparison below needs.
    """
    text = _COMMENT.sub(lambda m: " " * len(m.group()), css)

    media_spans: list[tuple[int, int]] = []
    for match in re.finditer(r"@media[^{]*\{", text):
        depth, i = 1, match.end()
        while i < len(text) and depth:
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
            i += 1
        media_spans.append((match.end(), i - 1))

    def in_media(pos: int) -> bool:
        return any(start <= pos < end for start, end in media_spans)

    plain: list[tuple[str, str, int]] = []
    conditional: list[tuple[str, str, int]] = []
    for rule in re.finditer(r"([^{}]+)\{([^{}]*)\}", text):
        head = rule.group(1)
        if "@" in head:
            continue
        body = rule.group(2)
        selectors = [" ".join(s.split()) for s in head.split(",")]
        selectors = [s for s in selectors if s]
        for declaration in re.finditer(r"([-a-zA-Z]+)\s*:", body):
            prop = declaration.group(1).lower()
            if prop.startswith("--"):
                continue
            where = conditional if in_media(rule.start()) else plain
            for selector in selectors:
                where.append((selector, prop, rule.start()))
    return plain, conditional


def _dead_overrides(css: str) -> list[str]:
    """Media declarations the file later overrides unconditionally."""
    plain, conditional = _declarations(css)
    latest: dict[tuple[str, str], int] = {}
    for selector, prop, pos in plain:
        latest[(selector, prop)] = max(latest.get((selector, prop), -1), pos)

    dead = []
    for selector, prop, pos in conditional:
        overriding = latest.get((selector, prop))
        if overriding is not None and overriding > pos:
            dead.append(f"{selector} {{ {prop} }} at {pos}, overridden at {overriding}")
    return sorted(set(dead))


class TestNoResponsiveRuleIsDeadOnArrival:
    def test_the_sweep_finds_the_stylesheets(self) -> None:
        """Without this, a moved directory would make the check pass on nothing."""
        sheets = _stylesheets()

        assert len(sheets) >= 2, [p.name for p in sheets]
        names = {p.name for p in sheets}
        assert {"bindsight.css", "extra.css"} <= names, names
        assert any("@media" in p.read_text("utf-8") for p in sheets)

    @pytest.mark.parametrize("sheet", _stylesheets(), ids=lambda p: p.name)
    def test_every_media_declaration_can_take_effect(self, sheet: Path) -> None:
        dead = _dead_overrides(sheet.read_text("utf-8"))

        assert not dead, (
            f"{sheet.name} declares these inside @media, then overrides the same "
            f"property for the same selector further down the file: {dead}. Equal "
            "specificity means source order decides, so the media rule never "
            "applies. Move it below the rule it is meant to override."
        )

    def test_it_catches_the_shape_that_shipped(self) -> None:
        """The control is the real mistake, written the way it was written."""
        broken = (
            "@media screen and (max-width: 600px) {\n"
            "  .bs-viewer { height: 17rem; }\n"
            "}\n"
            ".bs-viewer { width: 100%; height: 26rem; }\n"
        )

        dead = _dead_overrides(broken)
        assert dead, "the scan would have missed the rule that shipped doing nothing"
        assert ".bs-viewer" in dead[0], dead
        assert "height" in dead[0], dead

    def test_it_permits_the_order_that_works(self) -> None:
        """And the other direction, or it could pass by rejecting everything."""
        fixed = (
            ".bs-viewer { width: 100%; height: 26rem; }\n"
            "@media screen and (max-width: 600px) {\n"
            "  .bs-viewer { height: 17rem; }\n"
            "}\n"
        )

        assert _dead_overrides(fixed) == []

    def test_a_different_property_is_not_a_conflict(self) -> None:
        """Only the same property on the same selector is dead; nothing else."""
        unrelated = (
            "@media screen and (max-width: 600px) {\n"
            "  .bs-viewer { height: 17rem; }\n"
            "}\n"
            ".bs-viewer { border-radius: 11px; }\n"
            ".other { height: 4rem; }\n"
        )

        assert _dead_overrides(unrelated) == []

    def test_a_commented_out_rule_is_not_read_as_one(self) -> None:
        """Comments describing the fix must not be mistaken for the defect."""
        commented = (
            "@media screen and (max-width: 600px) {\n"
            "  .bs-viewer { height: 17rem; }\n"
            "}\n"
            "/* .bs-viewer { height: 26rem; } -- what this replaced */\n"
        )

        assert _dead_overrides(commented) == []

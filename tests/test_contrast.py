# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Text the interface draws must be legible to read, not only to look at.

`--ink-faint` was `#7d8896`: 3.6:1 against the page, below WCAG AA's 4.5:1 for
text smaller than 18.7px. Every `.stat__label` and `.stat__note` is 12px, so the
words naming each headline number -- "RECALL @ 20", "CA9 RANK", "LOG2 FOLD
CHANGE" -- and the caveats attached to them sat below the threshold while the
numbers themselves stayed crisp.

That is backwards for a design whose stated rule is that the limitation belongs
beside the claim. A caveat nobody can read on a projector, in a bright room, or
with ordinary age-related vision loss is not beside the claim in any sense that
matters.

The palette is checked here rather than in a browser because the tokens are the
thing: a ratio measured on one rendered page says nothing about the other four.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
CSS = REPO / "bindsight" / "report" / "web" / "static" / "bindsight.css"

#: WCAG 2.1 AA for body text. Large text (>=24px, or >=18.66px bold) may use 3.0,
#: but every token below is used at body size somewhere, so the stricter bar is
#: the honest one to hold them to.
AA_NORMAL = 4.5


def _channel(value: float) -> float:
    v = value / 255
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


def _luminance(hex_colour: str) -> float:
    h = hex_colour.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    r, g, b = (int(h[i : i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def contrast(a: str, b: str) -> float:
    la, lb = _luminance(a), _luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def _tokens() -> dict[str, str]:
    return dict(re.findall(r"--([a-z0-9-]+):\s*(#[0-9a-fA-F]{3,8})\s*;", CSS.read_text("utf-8")))


#: Tokens used as text colour. `*-tint` tokens are backgrounds and are checked
#: from the other side, as the ground their own text sits on.
TEXT_TOKENS = ("ink", "ink-soft", "ink-faint", "ok", "warn", "err")

#: The two backgrounds text is drawn on: the page, and the cards on it.
GROUNDS = ("ground", "surface")


class TestTheContrastMathIsRight:
    """Checked against the two anchors WCAG defines exactly."""

    def test_black_on_white_is_twenty_one_to_one(self) -> None:
        assert round(contrast("#000000", "#ffffff"), 1) == 21.0

    def test_a_colour_against_itself_is_one_to_one(self) -> None:
        assert round(contrast("#68727f", "#68727f"), 2) == 1.00

    def test_it_would_have_failed_the_old_value(self) -> None:
        """Guards the guard: the defect this file exists for must be catchable."""
        assert contrast("#7d8896", "#ffffff") < AA_NORMAL


class TestEveryTextTokenClearsAa:
    def test_the_stylesheet_declares_the_tokens(self) -> None:
        """Without this, a renamed token would make every check below vacuous."""
        tokens = _tokens()

        missing = [t for t in TEXT_TOKENS if t not in tokens]
        assert not missing, f"the stylesheet no longer declares {missing}"

        missing_grounds = [g for g in GROUNDS if g not in tokens]
        assert not missing_grounds, (
            f"the stylesheet no longer declares {missing_grounds}, so there is "
            "nothing to measure the text against"
        )

    @pytest.mark.parametrize("token", TEXT_TOKENS)
    @pytest.mark.parametrize("ground", GROUNDS)
    def test_it_is_readable_on_every_ground_it_is_drawn_on(self, token: str, ground: str) -> None:
        """Both grounds, because `.stat__label` sits on a card, not on the page."""
        tokens = _tokens()
        ratio = contrast(tokens[token], tokens[ground])

        assert ratio >= AA_NORMAL, (
            f"--{token} ({tokens[token]}) is {ratio:.2f}:1 against --{ground} "
            f"({tokens[ground]}); WCAG AA needs {AA_NORMAL}:1 for text under "
            "18.7px, and this token is used at 12px"
        )

    @pytest.mark.parametrize("token", ["ok", "warn", "err"])
    def test_a_status_colour_is_readable_on_its_own_tint(self, token: str) -> None:
        """Status text sits on its tinted panel, not on the page."""
        tokens = _tokens()
        tint = f"{token}-tint"
        if tint not in tokens:
            pytest.skip(f"--{tint} is not declared")

        ratio = contrast(tokens[token], tokens[tint])

        assert ratio >= AA_NORMAL, (
            f"--{token} on --{tint} is {ratio:.2f}:1; the status panels would be "
            "harder to read than the page they sit on"
        )


class TestTheChartFallbackMatchesTheToken:
    """`charts.js` repeats the colour as a fallback for `cssVar`.

    A fallback that disagrees with the token is a second palette that nobody
    maintains, and it applies exactly when the stylesheet failed to load -- the
    moment a reader is least able to notice.
    """

    def test_it_is_the_same_colour(self) -> None:
        js = (REPO / "bindsight" / "report" / "web" / "static" / "charts.js").read_text("utf-8")

        for token, declared in _tokens().items():
            for fallback in re.findall(rf'cssVar\("--{token}",\s*"(#[0-9a-fA-F]{{3,8}})"\)', js):
                assert fallback.lower() == declared.lower(), (
                    f"charts.js falls back to {fallback} for --{token}, which the "
                    f"stylesheet declares as {declared}"
                )

    def test_the_scan_finds_the_fallbacks(self) -> None:
        js = (REPO / "bindsight" / "report" / "web" / "static" / "charts.js").read_text("utf-8")

        assert re.search(r'cssVar\("--[a-z0-9-]+",\s*"#', js), (
            "no cssVar fallbacks found in charts.js; the check above tests nothing"
        )

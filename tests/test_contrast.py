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


# --- the documentation site -------------------------------------------------

#: The published site's brand layer. It mirrors the app palette but draws it on
#: different grounds -- lighter tinted panels -- so a token that clears AA in
#: the app can miss here, and `--bs-muted` did.
DOCS_CSS = REPO / "docs" / "stylesheets" / "extra.css"

#: mkdocs-material switches schemes with an attribute, not a media query.
SLATE = '[data-md-color-scheme="slate"]'

_HEX = r"#[0-9a-fA-F]{3,8}"
_RULE = re.compile(r"([^{}]+)\{([^{}]*)\}")
_COLOUR = re.compile(r"(?<![-a-z])color:\s*([^;]+);")
_GROUND = re.compile(r"background(?:-color)?:\s*([^;]+);")
_VAR = re.compile(r"var\(\s*--([a-z0-9-]+)")


def _docs_rules() -> dict[str, dict[str, str]]:
    """Selector -> its declared colour and background, comma groups split out."""
    text = DOCS_CSS.read_text("utf-8")
    rules: dict[str, dict[str, str]] = {}
    for match in _RULE.finditer(text):
        head, body = match.group(1), match.group(2)
        if head.lstrip().startswith(("@", "/*")):
            continue
        declared = {}
        colour = _COLOUR.search(body)
        ground = _GROUND.search(body)
        if colour:
            declared["color"] = colour.group(1).strip()
        if ground:
            declared["background"] = ground.group(1).strip()
        if not declared:
            continue
        for selector in head.split(","):
            selector = " ".join(selector.split())
            if selector:
                rules.setdefault(selector, {}).update(declared)
    return rules


def _docs_palette() -> tuple[dict[str, str], dict[str, str]]:
    """The light tokens, and the dark ones with the slate block applied."""
    text = DOCS_CSS.read_text("utf-8")

    def block(pattern: str) -> str:
        found = re.search(pattern + r"\s*\{([^{}]*)\}", text)
        return found.group(1) if found else ""

    light = dict(re.findall(rf"--([a-z0-9-]+):\s*({_HEX})\s*;", block(r":root")))
    dark = dict(light)
    dark.update(dict(re.findall(rf"--([a-z0-9-]+):\s*({_HEX})\s*;", block(re.escape(SLATE)))))
    return light, dark


def _resolve(value: str | None, palette: dict[str, str]) -> str | None:
    if not value:
        return None
    named = _VAR.match(value)
    if named:
        return palette.get(named.group(1))
    literal = re.match(rf"({_HEX})\b", value)
    return literal.group(1) if literal else None


def _ground_for(selector: str, rules: dict[str, dict[str, str]]) -> str | None:
    """The background this text is drawn on: its own, else its nearest ancestor.

    Derived from the selector rather than listed. `.bs-stat .k` has no
    background of its own, so the ground is `.bs-stat`'s -- which is how a
    reader sees it, and which means a panel added tomorrow is covered without
    anyone remembering to add it here.
    """
    parts = selector.split()
    for cut in range(len(parts), 0, -1):
        prefix = " ".join(parts[:cut])
        ground = rules.get(prefix, {}).get("background")
        if ground:
            return ground
    return None


def _docs_pairs() -> list[tuple[str, str, str, str]]:
    """(scheme, selector, foreground, background) for everything measurable."""
    rules = _docs_rules()
    light, dark = _docs_palette()
    pairs: list[tuple[str, str, str, str]] = []

    for selector, declared in rules.items():
        if "color" not in declared:
            continue
        if selector.startswith(SLATE):
            base = selector[len(SLATE) :].strip()
            ground = _ground_for(selector, rules) or _ground_for(base, rules)
            fg = _resolve(declared["color"], dark)
            bg = _resolve(ground, dark)
            if fg and bg:
                pairs.append(("dark", selector, fg, bg))
            continue

        ground = _ground_for(selector, rules)
        fg = _resolve(declared["color"], light)
        bg = _resolve(ground, light)
        if fg and bg:
            pairs.append(("light", selector, fg, bg))

        # The same rule still applies in dark for whatever slate does not
        # override, and the tokens underneath it change.
        override = rules.get(f"{SLATE} {selector}", {})
        fg_dark = _resolve(override.get("color", declared["color"]), dark)
        bg_dark = _resolve(override.get("background", ground), dark)
        if fg_dark and bg_dark and (fg_dark, bg_dark) != (fg, bg):
            pairs.append(("dark", selector, fg_dark, bg_dark))

    return sorted(set(pairs))


DOCS_PAIRS = _docs_pairs()


class TestTheDocumentationSiteIsLegibleToo:
    """`bindsight.css` was checked; the site a reader lands on was not.

    `--bs-muted` was `#6c757d`: 4.08:1 on `--bs-navy-tint` and 4.45:1 on
    `--bs-canvas`. `.bs-stat .k` is the label under each headline number at
    .74rem, and `.bs-flow .s small` is the caption under each pipeline stage at
    .7rem -- so the words naming the numbers were below AA while the numbers
    stayed crisp. That is the same defect, on the same kind of element, as the
    one this file was written for, reproduced on the published site because the
    sweep read one stylesheet and the palette had since become two.
    """

    def test_the_sweep_reads_the_stylesheet(self) -> None:
        """Without this, a moved file would make every check below vacuous."""
        assert DOCS_CSS.is_file(), "the documentation stylesheet is not where the sweep looks"

        light, dark = _docs_palette()
        assert len(light) >= 8, f"only {len(light)} tokens parsed from :root"
        assert dark["bs-muted"] != light["bs-muted"], "the slate block was not parsed"
        assert len(DOCS_PAIRS) >= 10, f"only {len(DOCS_PAIRS)} measurable pairs found"

    def test_every_text_token_is_actually_measured(self) -> None:
        """A token nobody draws text with would pass by never being looked at."""
        light, _ = _docs_palette()
        measured = {fg.lower() for _, _, fg, _ in DOCS_PAIRS}

        for token in ("bs-muted", "bs-navy", "bs-navy-dark"):
            assert light[token].lower() in measured, (
                f"--{token} ({light[token]}) is never checked against a ground"
            )

    @pytest.mark.parametrize(
        ("scheme", "selector", "fg", "bg"),
        DOCS_PAIRS,
        ids=[f"{s}-{sel}" for s, sel, _, _ in DOCS_PAIRS],
    )
    def test_it_clears_aa_on_the_ground_it_is_drawn_on(
        self, scheme: str, selector: str, fg: str, bg: str
    ) -> None:
        ratio = contrast(fg, bg)

        assert ratio >= AA_NORMAL, (
            f"[{scheme}] {selector}: {fg} on {bg} is {ratio:.2f}:1, below WCAG "
            f"AA's {AA_NORMAL}:1. The text on this site is read at 12px or less "
            "in several places, so the stricter bar is the honest one."
        )

    def test_it_would_have_failed_the_value_this_site_shipped(self) -> None:
        """Guards the guard, with the real colours rather than invented ones."""
        light, _ = _docs_palette()

        assert contrast("#6c757d", "#e8f0fb") < AA_NORMAL, "the old muted grey now passes?"
        assert contrast("#6c757d", light["bs-canvas"]) < AA_NORMAL
        # And the value that replaced it clears both, with room.
        assert contrast(light["bs-muted"], "#e8f0fb") >= AA_NORMAL
        assert contrast(light["bs-muted"], light["bs-canvas"]) >= AA_NORMAL

    def test_the_ground_is_inherited_when_the_element_declares_none(self) -> None:
        """`.bs-stat .k` has no background; the pair is meaningless without one."""
        rules = _docs_rules()

        assert "background" not in rules.get(".bs-stat .k", {})
        assert _ground_for(".bs-stat .k", rules) == rules[".bs-stat"]["background"]
        # A selector with no ancestor that paints anything yields nothing,
        # rather than being silently measured against a guessed page colour.
        assert _ground_for(".nothing-like-this", rules) is None


class TestTheTwoPalettesAgree:
    """`extra.css` says its values mirror `theme.py`. Nothing checked that.

    Six of its seven brand tokens did match, by hand and by luck. Darkening
    `--bs-muted` for contrast broke the seventh, and nothing noticed -- the
    claim is a comment at the top of a stylesheet, and a comment cannot fail.

    Only tokens that exist in both are compared. `theme.py` carries names the
    documentation layer has no use for, and inventing a rule that every
    constant must appear in the stylesheet would be a different claim from the
    one the file actually makes.
    """

    @staticmethod
    def _theme_tokens() -> dict[str, str]:
        source = (REPO / "bindsight" / "report" / "theme.py").read_text("utf-8")
        return dict(re.findall(r"^([A-Z][A-Z_]*) = \"(#[0-9a-fA-F]{3,8})\"", source, re.M))

    @staticmethod
    def _docs_tokens() -> dict[str, str]:
        css = DOCS_CSS.read_text("utf-8")
        root = re.search(r":root\s*\{([^{}]*)\}", css)
        assert root is not None, "extra.css has no :root block"
        return dict(re.findall(r"--bs-([a-z0-9-]+):\s*(#[0-9a-fA-F]{3,8})\s*;", root.group(1)))

    def test_both_palettes_are_readable(self) -> None:
        """Without this, a renamed constant would make the check below vacuous."""
        theme, docs = self._theme_tokens(), self._docs_tokens()

        assert len(theme) >= 10, f"only {len(theme)} constants parsed from theme.py"
        assert len(docs) >= 6, f"only {len(docs)} tokens parsed from extra.css"

        shared = {n for n in docs if n.upper().replace("-", "_") in theme}
        assert len(shared) >= 5, f"only {sorted(shared)} are named in both"

    def test_every_shared_token_has_the_same_value(self) -> None:
        theme, docs = self._theme_tokens(), self._docs_tokens()

        drifted = []
        for name, value in sorted(docs.items()):
            declared = theme.get(name.upper().replace("-", "_"))
            if declared is not None and declared.lower() != value.lower():
                drifted.append(f"--bs-{name} is {value}, theme.py says {declared}")

        assert not drifted, (
            "extra.css says its values mirror bindsight/report/theme.py, and these "
            f"no longer do: {drifted}. One product, one palette -- change both, or "
            "change the sentence at the top of the stylesheet."
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


class TestThePrintedPageDoesNotDescribeAViewerItOmits:
    """`.viewer` is dropped in print; its furniture was not.

    A WebGL canvas prints as a blank rectangle, so hiding it is right. What
    stayed behind was the design picker, a colour legend for a picture that is
    not on the page, and a paragraph telling the reader to "Rotate it" -- on
    paper.

    The rule the rest of this interface follows applies here too: when a thing
    cannot be shown, say where it is rather than leaving its furniture behind.
    """

    @staticmethod
    def _print_rules() -> str:
        blocks = re.findall(r"@media print\s*\{(.*?)\n\}", CSS.read_text("utf-8"), re.S)
        assert blocks, "the stylesheet has no @media print block"
        return "\n".join(blocks)

    def test_the_print_block_exists(self) -> None:
        """Guards the guard: no print block means the checks below prove nothing."""
        assert "display" in self._print_rules()

    @pytest.mark.parametrize(
        "selector", [".viewer", ".viewer-picker", ".viewer-legend", ".screen-only"]
    )
    def test_the_viewer_and_its_furniture_are_hidden(self, selector: str) -> None:
        rules = self._print_rules()

        assert selector in rules, (
            f"{selector} is not mentioned in @media print, so it survives onto "
            "paper beside a viewer that does not"
        )

    def test_the_print_only_caption_is_shown(self) -> None:
        rules = self._print_rules()

        assert re.search(r"\.print-only\s*\{[^}]*display:\s*inline", rules), (
            "nothing replaces the viewer on paper, so the section names files "
            "the reader is given no way to find"
        )

    def test_the_print_only_caption_is_hidden_on_screen(self) -> None:
        """Otherwise every reader sees both halves of the sentence at once."""
        css = CSS.read_text("utf-8")
        outside_print = re.sub(r"@media print\s*\{.*?\n\}", "", css, flags=re.S)

        assert re.search(r"\.print-only\s*\{[^}]*display:\s*none", outside_print), (
            ".print-only has no default of display:none, so it shows on screen too"
        )

    def test_the_template_carries_both_halves_of_the_caption(self) -> None:
        template = (
            REPO / "bindsight" / "report" / "web" / "templates" / "evidence.html.j2"
        ).read_text("utf-8")

        assert 'class="screen-only"' in template
        assert 'class="print-only"' in template
        assert "benchmarks/designer_benchmark/" in template, (
            "the print caption does not say where the structures are"
        )


class TestTheInterfaceServesItsOwnStylesheet:
    """The app must actually serve the stylesheet its pages reference.

    This began as a check on a hosted deployment's health probe. That probe
    finished on `GET / -> 200` and called it healthy, while the deployment
    served an empty page titled "Streamlit" -- which answers 200 just as well.
    The fix was to ask for the interface's own stylesheet and require a token
    from inside it, which no other application serves.

    The deployment is retired and the probe went with it. The check it forced
    is worth more than the thing it was watching: a stylesheet the app fails to
    serve, or a marker the stylesheet has lost, breaks the interface itself --
    and nothing else in this suite asks the running app for it.
    """

    #: A custom property only this interface's stylesheet declares. A check for
    #: a string every server returns would pass forever.
    MARKER = "--ink-faint"

    def test_the_marker_is_in_the_stylesheet(self) -> None:
        assert self.MARKER in CSS.read_text("utf-8"), (
            f"{self.MARKER!r} is not in bindsight.css, so the end-to-end check "
            "below would be asserting on a string this project no longer uses"
        )

    def test_the_app_actually_serves_that_marker(self) -> None:
        """End to end, against the running app rather than the file on disk."""
        pytest.importorskip("fastapi", reason="the web interface needs the report extra")
        from fastapi.testclient import TestClient

        from bindsight.report.web.app import create_app

        response = TestClient(create_app()).get("/static/bindsight.css")

        assert response.status_code == 200
        assert self.MARKER in response.text

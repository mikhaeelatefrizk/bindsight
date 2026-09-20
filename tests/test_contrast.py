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
from html.parser import HTMLParser
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

#: Every token the interface paints a tinted panel for, read off the stylesheet
#: rather than named here -- see the guard beneath this module's parametrisation.
TINTED = tuple(sorted(name for name in _tokens() if f"{name}-tint" in _tokens()))


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

    def test_the_tinted_tokens_are_found_not_listed(self) -> None:
        """Guards the parametrisation below, which used to be three names.

        `--teal` has had a `--teal-tint` and a `.badge--teal` drawn on it for
        as long as the others, and was never in the list, so its 4.42:1 went
        unmeasured. Any token the stylesheet gives a `-tint` to is a token
        something is drawn on; the pairs are read off the stylesheet now, so
        the next one is covered before anyone thinks to add it.
        """
        assert set(TINTED) >= {"ok", "warn", "err", "teal"}, (
            f"the tint scan found only {TINTED}; it used to find ok/warn/err by "
            "hand and missed teal, so finding fewer than that is a regression"
        )

    @pytest.mark.parametrize("token", TINTED)
    def test_a_status_colour_is_readable_on_its_own_tint(self, token: str) -> None:
        """Status text sits on its tinted panel, not on the page."""
        tokens = _tokens()
        ratio = contrast(tokens[token], tokens[f"{token}-tint"])

        assert ratio >= AA_NORMAL, (
            f"--{token} on --{token}-tint is {ratio:.2f}:1; the status panels would "
            "be harder to read than the page they sit on"
        )


# --- the documentation site -------------------------------------------------

#: The published site's brand layer. It mirrors the app palette but draws it on
#: different grounds -- lighter tinted panels -- so a token that clears AA in
#: the app can miss here, and `--bs-muted` did.
DOCS = REPO / "docs"
DOCS_CSS = DOCS / "stylesheets" / "extra.css"

#: mkdocs-material switches schemes with an attribute, not a media query.
SLATE = '[data-md-color-scheme="slate"]'

_HEX = r"#[0-9a-fA-F]{3,8}"
_RULE = re.compile(r"([^{}]+)\{([^{}]*)\}")
_COLOUR = re.compile(r"(?<![-a-z])color:\s*([^;]+);")
_GROUND = re.compile(r"background(?:-color)?:\s*([^;]+);")
_VAR = re.compile(r"var\(\s*--([a-z0-9-]+)")


def _docs_rules() -> dict[str, dict[str, str]]:
    """Selector -> its declared colour and background, comma groups split out.

    Comments come out first. ``_RULE`` treats everything between one ``}`` and
    the next ``{`` as the selector, so a banner comment ahead of a rule became
    part of that rule's head, the head then started with ``/*``, and the rule
    was skipped as if it were the comment. ``.bs-hero`` disappeared exactly so
    -- and it is the ground the whole hero is drawn on.
    """
    text = re.sub(r"/\*.*?\*/", "", DOCS_CSS.read_text("utf-8"), flags=re.S)
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


#: Tags that never enclose anything, so they never open a level.
_VOID = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)


class _Nesting(HTMLParser):
    """Records, for every class it meets, the classes enclosing it."""

    def __init__(self, found: dict[str, set[str]]) -> None:
        super().__init__(convert_charrefs=True)
        self._found = found
        self._stack: list[list[str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        classes = (dict(attrs).get("class") or "").split()
        enclosing: set[str] = set()
        for level in self._stack:
            enclosing.update(level)
        for name in classes:
            self._found.setdefault(name, set()).update(enclosing)
        if tag not in _VOID:
            self._stack.append(classes)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in _VOID and self._stack:
            self._stack.pop()

    def handle_endtag(self, tag: str) -> None:
        if tag not in _VOID and self._stack:
            self._stack.pop()


def _markup_ancestors() -> dict[str, frozenset[str]]:
    """class -> every class that encloses it, read from the pages themselves.

    A stylesheet cannot say that ``.bs-cta`` only ever appears inside
    ``.bs-hero``; the markup can, and does. Deriving it from the pages means a
    panel nested tomorrow is covered without anyone remembering to add it to a
    list here -- and a list here is what this module would otherwise need, in a
    repository whose recurring defect is exactly that.
    """
    found: dict[str, set[str]] = {}
    for page in sorted(DOCS.glob("*.md")):
        source = page.read_text("utf-8")
        if "class=" in source:
            _Nesting(found).feed(source)
    return {name: frozenset(seen) for name, seen in found.items()}


MARKUP_ANCESTORS = _markup_ancestors()


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


#: What text with no panel of its own is drawn on: the page itself. Material's
#: ``--md-default-bg-color``, white under the default scheme and
#: ``hsla(232, 15%, 21%, 1)`` under slate, which are this site's two schemes.
PAGE = {"light": "#ffffff", "dark": "#2e303e"}

#: Values that name no colour, so no ratio exists to check. A rule whose text
#: colour is one of these takes whatever encloses it, which this stylesheet
#: does not set and Material does.
_NOT_A_COLOUR = frozenset({"inherit", "currentcolor", "transparent", "unset", "initial"})


def _colours_in(value: str, palette: dict[str, str]) -> list[str]:
    """Every colour a declaration resolves to.

    A list, not a value, because ``.bs-hero`` is a gradient between two stops
    and its text is drawn across both. Returning only the first would check the
    easier end of the ramp and call it covered.
    """
    found = [
        palette[name] for name in re.findall(r"var\(--([a-z0-9-]+)\)", value) if name in palette
    ]
    found += re.findall(r"#[0-9a-fA-F]{3,8}", value)
    return found


_RGBA = re.compile(
    r"rgba?\(" + r"\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)"
    r"(?:[,/\s]+([\d.]+))?\s*" + r"\)"
)


def _channels(colour: str) -> tuple[float, float, float]:
    """The three channels of a #rgb or #rrggbb literal."""
    digits = colour.lstrip("#")
    if len(digits) == 3:
        digits = "".join(c * 2 for c in digits)
    return tuple(int(digits[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _translucent(value: str) -> tuple[float, float, float, float] | None:
    """An ``rgba()`` layer, or None if the declaration is not one."""
    found = _RGBA.search(value)
    if not found:
        return None
    red, green, blue = (float(found.group(i)) for i in (1, 2, 3))
    alpha = float(found.group(4)) if found.group(4) is not None else 1.0
    return red, green, blue, alpha


def _flatten(layers: list[tuple[float, float, float, float]], base: str) -> str:
    """What the eye receives: translucent layers composited onto a solid base.

    `.bs-cta a:hover` paints white at 14%. That is not "no background" and it
    is not white either -- over the hero's navy it comes out a pale navy, and
    the white text on it has a real ratio that can be measured. Treating it as
    unresolvable dropped the rule; treating it as white would have invented a
    failure, the same way falling back to the page once did.
    """
    red, green, blue = (float(c) for c in _channels(base))
    for layer_r, layer_g, layer_b, alpha in reversed(layers):
        red = layer_r * alpha + red * (1 - alpha)
        green = layer_g * alpha + green * (1 - alpha)
        blue = layer_b * alpha + blue * (1 - alpha)
    return f"#{round(red):02x}{round(green):02x}{round(blue):02x}"


def _grounds_for(
    selector: str, rules: dict[str, dict[str, str]], palette: dict[str, str], page: str
):
    """The backgrounds this text is drawn on, nearest declaring ancestor first.

    Derived from the selector rather than listed, so a panel added tomorrow is
    covered without anyone remembering to add it here.

    Three outcomes, and the difference between the last two is the whole point:

    ``None``  no ancestor declares a background at all, so the text is on the
              page -- measure it against :data:`PAGE`.
    ``[]``    an ancestor declares one that names no colour (``inherit``), so
              there is nothing to measure and nothing to assume.
    ``[...]`` the colours it resolves to, every stop of them.

    Collapsing the middle case into the first is what an earlier version of
    this did: it fell back to the page whenever a ground would not resolve,
    and cheerfully reported ``.bs-hero h1`` as white on white -- a failure
    invented by the measurement, over text that is white on navy and correct.
    """
    layers: list[tuple[float, float, float, float]] = []

    def consider(declared: str | None) -> list[str] | None:
        """A solid ground ends the walk; a translucent one is carried down it."""
        if not declared:
            return None
        solid = _colours_in(declared, palette)
        if solid:
            return [_flatten(layers, base) for base in solid]
        layer = _translucent(declared)
        if layer and layer[3] < 1:
            layers.append(layer)
        return None

    parts = selector.split()
    for cut in range(len(parts), 0, -1):
        found = consider(rules.get(" ".join(parts[:cut]), {}).get("background"))
        if found:
            return found

    # Nothing in the selector's own chain paints anything solid. The markup
    # still knows what encloses it: `.bs-cta a` is white, and white is right,
    # because every `.bs-cta` on this site sits inside the navy `.bs-hero`.
    for name in reversed(re.findall(r"\.([a-z0-9-]+)", selector)):
        for ancestor in sorted(MARKUP_ANCESTORS.get(name, ())):
            found = consider(rules.get(f".{ancestor}", {}).get("background"))
            if found:
                return found
    return [_flatten(layers, page)] if layers else None


def _docs_pairs() -> list[tuple[str, str, str, str]]:
    """(scheme, selector, foreground, background) for everything measurable."""
    rules = _docs_rules()
    light, dark = _docs_palette()
    pairs: list[tuple[str, str, str, str]] = []

    def add(scheme: str, selector: str, fg: str | None, grounds, palette_page: str) -> None:
        if not fg:
            return
        for bg in grounds if grounds is not None else [palette_page]:
            pairs.append((scheme, selector, fg, bg))

    for selector, declared in rules.items():
        if "color" not in declared:
            continue
        if selector.startswith(SLATE):
            base = selector[len(SLATE) :].strip()
            grounds = _grounds_for(selector, rules, dark, PAGE["dark"])
            if grounds is None:
                grounds = _grounds_for(base, rules, dark, PAGE["dark"])
            add("dark", selector, _resolve(declared["color"], dark), grounds, PAGE["dark"])
            continue

        grounds = _grounds_for(selector, rules, light, PAGE["light"])
        add("light", selector, _resolve(declared["color"], light), grounds, PAGE["light"])

        # The same rule still applies in dark for whatever slate does not
        # override, and the tokens underneath it change.
        override = rules.get(f"{SLATE} {selector}", {})
        fg_dark = _resolve(override.get("color", declared["color"]), dark)
        if "background" in override:
            grounds_dark = _colours_in(override["background"], dark)
        else:
            grounds_dark = _grounds_for(selector, rules, dark, PAGE["dark"])
        add("dark", selector, fg_dark, grounds_dark, PAGE["dark"])

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

    def test_every_rule_that_sets_a_colour_is_measured(self) -> None:
        """Guards the guard: a dropped rule is a test that never existed.

        :func:`_docs_pairs` builds the parametrisation above, so a rule it
        cannot place produced no pair, was not checked, and was not reported.
        Thirteen of twenty-seven coloured rules sat outside the sweep that way
        -- every note glyph among them, one at 1.67:1 in dark mode, and a warn
        colour that was 3.42:1 on white. Nothing was wrong with the assertions.
        There simply were none for that text.

        The sweep is now asked what it left out, and may only answer with rules
        whose colour names no colour.
        """
        rules = _docs_rules()
        light, dark = _docs_palette()
        declares_colour = {s for s, d in rules.items() if "color" in d}
        measured = {selector for _scheme, selector, _fg, _bg in DOCS_PAIRS}

        assert declares_colour, "no rule in extra.css declares a colour; the parse is wrong"

        unplaced = declares_colour - measured
        for selector in sorted(unplaced):
            value = rules[selector]["color"].strip().lower()
            assert value in _NOT_A_COLOUR, (
                f"{selector} sets color: {value}, which names a colour, and yet "
                "nothing measured it -- so it is outside the contrast check "
                "while appearing to be inside it"
            )
            assert not _resolve(rules[selector]["color"], light), selector
            assert not _resolve(rules[selector]["color"], dark), selector

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

        light, _dark = _docs_palette()

        assert "background" not in rules.get(".bs-stat .k", {})
        assert _grounds_for(".bs-stat .k", rules, light, PAGE["light"]) == _colours_in(
            rules[".bs-stat"]["background"], light
        )
        # A selector with no painted ancestor -- in the stylesheet or in the
        # markup -- yields None rather than a colour, so the caller has to say
        # what the page is instead of being handed a guess.
        assert _grounds_for(".nothing-like-this", rules, light, PAGE["light"]) is None

    def test_a_translucent_ground_is_flattened_onto_what_is_behind_it(self) -> None:
        """`.bs-cta a:hover` is white at 14%, over the hero's navy.

        Neither "no ground" nor "white": the first drops the rule out of the
        sweep, the second invents a 1:1 failure over text that is perfectly
        readable. The ratio that exists is the one against the composite.
        """
        assert _flatten([(255.0, 255.0, 255.0, 0.14)], "#0b5394") == "#2d6ba3"
        assert _flatten([], "#0b5394") == "#0b5394"
        assert _flatten([(255.0, 255.0, 255.0, 1.0)], "#0b5394") == "#ffffff"

    def test_a_rule_that_follows_a_comment_is_still_parsed(self) -> None:
        """`.bs-hero` is preceded by a section banner, and vanished for it.

        Every rule in this stylesheet that follows a comment was skipped, and
        the stylesheet is written in commented sections. `.bs-hero` is the one
        that mattered: it paints the navy gradient the entire hero is read on,
        so its absence left the hero's white text with no ground at all.
        """
        rules = _docs_rules()

        assert ".bs-hero" in rules, (
            "the rule after the Hero banner is not parsed, so every rule that "
            "follows a comment is invisible to this module"
        )
        assert "linear-gradient" in rules[".bs-hero"]["background"]

    def test_the_markup_is_where_nesting_comes_from(self) -> None:
        """The ancestry is read, not listed, so it cannot go stale silently."""
        assert MARKUP_ANCESTORS, "no page declares a class; the markup parse is wrong"
        assert "bs-hero" in MARKUP_ANCESTORS.get("bs-cta", ()), (
            "docs/index.md no longer puts .bs-cta inside .bs-hero; if the hero "
            "was restructured, the white call-to-action text now sits on "
            "something else and this module needs to know what"
        )


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

    @staticmethod
    def _app_tokens() -> dict[str, str]:
        source = (REPO / "bindsight" / "report" / "web" / "static" / "bindsight.css").read_text(
            "utf-8"
        )
        root = re.search(r":root\s*\{([^{}]*)\}", source)
        assert root is not None, "bindsight.css has no :root block"
        return dict(re.findall(r"--([a-z0-9-]+):\s*(#[0-9a-fA-F]{3,8})\s*;", root.group(1)))

    def test_the_web_interface_uses_the_same_values(self) -> None:
        """The third surface theme.py names, and the one it was written for.

        Its docstring counts three surfaces that "drifted apart" and calls
        itself the single source of truth. Only the documentation site was
        ever held to it. The interface kept its own copy, and the copies
        disagreed on nine of eleven shared names -- the success colour alone
        existed as #2e7d32 here, #1f7a3d on the site and #1f6f35 in the app.
        Nothing said so, because nothing compared them.

        Names the two do not share are not drift: the app calls its page
        `--ground` and its brand accent `--teal`, and has scales this module
        has no opinion about. Only what both name is checked.
        """
        theme, app = self._theme_tokens(), self._app_tokens()

        shared = sorted(n for n in app if n.upper().replace("-", "_") in theme)
        assert len(shared) >= 9, (
            f"only {len(shared)} names are shared with bindsight.css; either the "
            "interface renamed its tokens or this parse has stopped working"
        )

        drifted = [
            f"--{name} is {app[name]}, theme.py says {theme[name.upper().replace('-', '_')]}"
            for name in shared
            if app[name].lower() != theme[name.upper().replace("-", "_")].lower()
        ]

        assert not drifted, (
            "bindsight/report/theme.py calls itself the single source of truth "
            f"for every presentation surface, and these no longer match it: {drifted}"
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
    serve, or a marker the stylesheet has lost, breaks the interface itself.
    ``tests/test_web_ui.py`` checks the stylesheet answers 200; nothing else
    checks what is inside it.
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

# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""There is no hosted demo -- and the true sentences beside it must survive.

The Hugging Face Space served a blank page titled "Streamlit", the framework
the interface release deleted, from a build it made before that release. It
could not be repaired from inside this repository: ``sync-hf-space.yml``
uploaded nothing without an ``HF_TOKEN`` secret only the owner can create, and
it reported success while skipping every step, so no check ever went red about
it. The owner has retired it rather than keep a deployment nobody maintains.

What replaced it is better and is already published: the documentation site
serves the twenty predicted complexes in 3-D at ``/results/`` and the input
checker at ``/try-your-data/``, both running in the reader's own browser with
nothing installed and nothing uploaded.

This file replaces ``test_hosted_demo_claims.py``, whose rule was narrower:
naming the Space as an address was permitted and only promising it *worked* was
forbidden. That distinction existed because the Space still existed. It does
not, so the rule is now flat -- nothing shipped refers to it -- and the promise
vocabulary is kept and widened, because "try it live" is a lie about a hosted
demo whether or not the sentence names where.

The second half is the one that matters, and it is why this is not a
``grep -rl huggingface | xargs sed``.

Three true sentences sat inside the blast radius. ``overrides/main.html`` lists
the author's own Hugging Face profile in the ``author.sameAs`` identity graph,
two lines above where the software's ``sameAs`` claimed the Space: one is a
real profile belonging to a person, the other was a false claim about where
this software lives, and a scan that could not tell them apart would take both.
``ARCHITECTURE.md`` and ``bindsight/runners/protocol.py`` named "HuggingFace
Spaces" (one word, plural) as a free compute tier -- a claim about the
landscape rather than about this project's deployment. Both were corrected in
the same commit for a different reason, on the merits: this project's Space ran
on free **CPU**, which is why its design half went to Kaggle for a GPU at all,
so listing it among free *GPU* tiers was wrong before the Space was retired and
would still be wrong today. The one-word/two-word discrimination is kept in the
pattern below anyway, because the next person to sweep for "Hugging Face" needs
to find the reason written down rather than infer it.

``CHANGELOG.md`` is exempt by design. Its entries are dated records of what
happened, and the whole episode is in them -- the drift, the false green, the
retirement. Deleting the word there would falsify the history rather than
correct it.
"""

from __future__ import annotations

import functools
import json
import re
import subprocess
from pathlib import Path

import pytest

from bindsight.report import theme

REPO = Path(__file__).resolve().parents[1]

#: The only tracked files allowed to name the Space: the dated record of its
#: retirement, and this file, which has to name what it forbids.
MAY_NAME_IT = frozenset({"CHANGELOG.md", f"tests/{Path(__file__).name}"})

#: Paths that existed only to run or watch the Space.
DELETED = (
    ".github/workflows/keep-warm.yml",
    ".github/workflows/sync-hf-space.yml",
    ".huggingface/Dockerfile",
    ".huggingface/README.md",
    ".huggingface/requirements.txt",
)

#: Constants that pointed at it, or recorded whether it was serving this build.
RETIRED_CONSTANTS = ("HF_SPACE_URL", "HF_SPACE_IS_SERVING_THIS_BUILD")

SPACE_HOST = "huggingface.co/spaces/Mikhaeelatefrizk/bindsight"

#: How a document refers to the deployment -- by address or by name. The name
#: alone matters: prose named the Space without linking it, so a sweep that only
#: looked for the URL would not read that sentence at all.
#:
#: "HuggingFace Spaces" (one word, plural) is the compute-tier category and is
#: deliberately NOT matched. Nothing in the tree says it today, but the pattern
#: has to keep the distinction: the day someone writes a true sentence about
#: free tiers, this scan must not eat it.
SPACE_MENTION = re.compile(re.escape(SPACE_HOST) + r"|Hugging Face Space\b", re.IGNORECASE)

#: The author's own profile, which is a person's identity and not this
#: software's deployment. It must survive every sweep above.
AUTHOR_PROFILE = "https://huggingface.co/Mikhaeelatefrizk"

#: Where a claim could be written. Everything else in the tree is data.
CLAIM_SUFFIXES = frozenset({".md", ".tex", ".html", ".j2", ".py", ".cff", ".yml", ".yaml", ".json"})

#: Phrases that tell a reader a hosted deployment will work for them.
#:
#: Every alternative was written in this repository, and each is exercised as a
#: fixture in ``TestTheScanWouldCatchWhatItLooksFor`` -- so narrowing this
#: pattern to nothing fails there rather than passing silently here. Two were
#: added when the Space was retired: "with no local installation" and "hosted
#: as a", both of which the old pattern missed while a manuscript shipped them.
PROMISE = re.compile(
    r"try it live"
    r"|lets anyone run"
    r"|runs the (full )?discovery (half|pipeline) (live )?in (their|any|your) browser"
    r"|runs the full pipeline in (their|any|your) browser"
    r"|zero[- ]install"
    r"|reachable in any"
    r"|in your browser on the hosted"
    r"|the hosted app runs"
    r"|\[live app\]"
    r"|deployed instance at"
    r"|with no local installation"
    r"|hosted as a"
    r"|hosted demo at",
    re.IGNORECASE,
)


@functools.lru_cache(maxsize=1)
def _tracked_text() -> tuple[tuple[str, str], ...]:
    """Every tracked file that could carry a claim, with its text.

    From git rather than a glob: a document added tomorrow is covered by this
    the moment it is committed, and a hand-written list is the defect class
    this repository keeps finding in itself.
    """
    listed = subprocess.run(
        ["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=False
    ).stdout.split()
    out: list[tuple[str, str]] = []
    for rel in listed:
        path = REPO / rel
        if path.suffix not in CLAIM_SUFFIXES or not path.is_file():
            continue
        try:
            out.append((rel, path.read_text(encoding="utf-8")))
        except (UnicodeDecodeError, OSError):  # pragma: no cover - binary stragglers
            continue
    return tuple(out)


def _sentences(text: str) -> list[str]:
    """Split on sentence ends, so a promise elsewhere is not blamed on a line."""
    flat = " ".join(text.split())
    return [p for p in re.split(r"(?<=[.!?])\s+", flat) if p]


class TestTheMachineryIsGone:
    @pytest.mark.parametrize("rel", DELETED, ids=DELETED)
    def test_the_file_is_gone(self, rel: str) -> None:
        assert not (REPO / rel).exists(), f"{rel} is back"

    def test_the_directory_is_gone(self) -> None:
        assert not (REPO / ".huggingface").exists(), ".huggingface/ is back"

    @pytest.mark.parametrize("name", RETIRED_CONSTANTS, ids=RETIRED_CONSTANTS)
    def test_the_theme_carries_no_space_constant(self, name: str) -> None:
        """A URL nothing points at is a URL something will point at again."""
        assert not hasattr(theme, name), f"theme.{name} is back"


class TestNothingShippedNamesIt:
    def test_the_sweep_reads_the_repository(self) -> None:
        """Without this, a broken `git ls-files` would pass every scan below."""
        tracked = _tracked_text()

        assert len(tracked) > 200, f"the sweep found only {len(tracked)} files"
        names = {rel for rel, _ in tracked}
        for expected in ("README.md", "paper/paper.md", "paper/biorxiv/manuscript.tex"):
            assert expected in names, f"{expected} is not being swept"

    def test_no_tracked_file_names_the_space(self) -> None:
        offenders = [
            f"{rel}: {s}"
            for rel, text in _tracked_text()
            if rel not in MAY_NAME_IT
            for s in _sentences(text)
            if SPACE_MENTION.search(s)
        ]

        assert not offenders, (
            "these name a hosted Space this project no longer runs: "
            f"{offenders}. It was retired; the evidence surface is published on "
            "the documentation site instead."
        )

    def test_no_tracked_file_promises_a_hosted_demo(self) -> None:
        """Wider than the address: "try it live" is a claim wherever it points."""
        offenders = [
            f"{rel}: {s}"
            for rel, text in _tracked_text()
            if rel not in MAY_NAME_IT
            for s in _sentences(text)
            if PROMISE.search(s)
        ]

        assert not offenders, (
            f"these promise a hosted demo that does not exist: {offenders}. "
            "`bindsight ui` runs locally; the documentation site publishes the "
            "evidence surface as static pages."
        )

    def test_no_tracked_file_refers_to_the_deleted_paths(self) -> None:
        """A reference to a file that is gone is a broken instruction."""
        offenders = []
        for rel, text in _tracked_text():
            if rel in MAY_NAME_IT:
                continue
            for gone in (".huggingface", "sync-hf-space", "keep-warm"):
                if gone in text:
                    offenders.append(f"{rel} still refers to {gone}")

        assert not offenders, offenders


class TestTheTrueSentencesSurvive:
    """The other direction. Removing a deployment must not remove a person.

    ``author.sameAs`` ties this software's author to their canonical profiles
    so a search engine can connect them. The Hugging Face entry there is a real
    profile, two lines from where the software's own ``sameAs`` claimed the
    dead Space. A sweep that could not tell a person from a deployment would
    take both, and nothing else in the tree would notice.
    """

    @staticmethod
    def _overrides() -> str:
        return (REPO / "overrides" / "main.html").read_text(encoding="utf-8")

    def test_the_authors_profile_is_still_listed(self) -> None:
        assert AUTHOR_PROFILE in self._overrides(), (
            "the author's Hugging Face profile was removed from author.sameAs. "
            "That is a person's identity, not this software's deployment -- the "
            "Space was the entry two lines below it."
        )

    def test_the_software_no_longer_claims_the_space_as_itself(self) -> None:
        assert SPACE_HOST not in self._overrides()

    def test_the_structured_data_still_parses(self) -> None:
        """Removing a line from JSON-LD leaves a trailing comma, silently.

        Nothing else reads this block. A stray comma costs the whole site its
        structured data and no page looks any different, which is exactly the
        kind of failure this repository exists to make loud.
        """
        html = self._overrides()
        blocks = re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)

        assert blocks, "overrides/main.html no longer carries any JSON-LD"
        for block in blocks:
            parsed = json.loads(block)  # raises on a trailing comma
            assert parsed, "the structured-data block is empty"


class TestTheHomePageStillLeadsSomewhere:
    """A button is clicked before it is read.

    The primary call to action used to send first-time visitors to the Space.
    What it must never be again is a link out to something this repository does
    not serve -- so the invariant kept here is not about Hugging Face at all.
    """

    def test_there_is_exactly_one_primary_call_to_action(self) -> None:
        index = (REPO / "docs" / "index.md").read_text(encoding="utf-8")
        block = re.search(r'<div class="bs-cta">(.*?)</div>', index, re.S)

        assert block, "docs/index.md lost its call-to-action block"
        primary = re.findall(r'<a class="primary"[^>]*href="([^"]+)"', block.group(1))

        assert len(primary) == 1, (
            f"expected exactly one primary call to action, found {primary} -- "
            "the fix for this is to re-point the button, not to delete it"
        )
        assert "huggingface" not in primary[0].lower()


class TestTheScanWouldCatchWhatItLooksFor:
    """Each pattern proved against what was actually written, so none goes blind."""

    @pytest.mark.parametrize(
        "sample",
        [
            # Every one of these shipped in this repository.
            '<a class="primary" href="https://huggingface.co/spaces/X">Try it live</a>',
            "A public web demo, a Hugging Face Space at <url>, lets anyone run the "
            "full discovery pipeline in their browser without installing anything.",
            "Zero install. The hosted app runs the discovery half live on a real TCGA cohort.",
            # Narrowed deliberately: a bare "runs the pipeline live" is true of
            # the local interface, so the branch requires a browser framing.
            "It lets anyone run the full discovery pipeline in their browser.",
            "Everything else runs on a CPU laptop, and in your browser on the hosted app.",
            "The same demo is reachable in any web browser at huggingface.co/spaces/X.",
            "The deployed instance at huggingface.co/spaces/X provides five sections.",
            "Rotate them in 3-D on the [live app](https://huggingface.co/spaces/X).",
            # These two the previous guard permitted, and a manuscript shipped them.
            "The same demo runs in a web browser with no local installation.",
            "The web demo is hosted as a Hugging Face Space at <url>.",
        ],
    )
    def test_it_catches_what_this_repository_used_to_say(self, sample: str) -> None:
        assert PROMISE.search(sample) or SPACE_MENTION.search(sample), sample

    @pytest.mark.parametrize(
        "sample",
        [
            # The compute-tier category, one word and plural. Not a deployment.
            "Free GPU tiers (Colab T4, Kaggle T4, HuggingFace Spaces) are powerful enough.",
            "None for free tiers (Colab/Kaggle/HF Spaces).",
            # A person, not a deployment.
            AUTHOR_PROFILE,
            # Ordinary prose that must not trip either pattern.
            "The first run on a fresh container pays the GDC download.",
            # True of `bindsight ui`, which is local. Must not trip the sweep.
            "It provides a one-click demo that runs the discovery pipeline live.",
            "`bindsight ui` serves the interface locally in seconds.",
        ],
    )
    def test_it_does_not_eat_a_true_sentence(self, sample: str) -> None:
        assert not SPACE_MENTION.search(sample), sample
        assert not PROMISE.search(sample), sample

    def test_the_alternation_has_not_been_gutted(self) -> None:
        assert PROMISE.pattern.count("|") >= 10, (
            "the promise vocabulary has been narrowed; it is easier to delete a "
            "branch of this pattern than to fix the sentence that trips it"
        )

    def test_sentence_splitting_does_not_swallow_the_page(self) -> None:
        """A whole-file match would blame a promise elsewhere on the page."""
        text = f"The demo runs the full pipeline in your browser. See {SPACE_HOST} for it."
        picked = [s for s in _sentences(text) if SPACE_MENTION.search(s)]

        assert len(picked) == 1
        assert not PROMISE.search(picked[0])

# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Nothing here refers to a hosted demo -- and the true sentences survive.

The Hugging Face Space served a blank page titled "Streamlit", the framework
the interface release deleted, from a build made before that release. It could
not be repaired from inside this repository: ``sync-hf-space.yml`` uploaded
nothing without an ``HF_TOKEN`` secret only the owner can create. For most of
that period it reported success while skipping every step; the commit before
the retirement changed it to report *skipped*, which is what it was. Either way
no check ever went red about the Space itself. The owner retired it rather than
keep a deployment nobody maintains.

The Space still exists. This repository cannot delete data on someone's
account, so what changed is that nothing shipped here refers to it, points at
it, or claims it works. It is unmaintained and unreferenced, not gone -- and
writing "gone" here would be the same class of false sentence this file exists
to prevent.

What replaced it was already published: the documentation site serves the
twenty predicted complexes in 3-D at ``/results/`` and the input checker at
``/try-your-data/``, both running in the reader's own browser with nothing
installed and nothing uploaded.

This file replaces ``test_hosted_demo_claims.py``, whose rule was narrower:
naming the Space as an address was permitted, and only promising it *worked*
was forbidden. That distinction existed because the Space was still something
this project ran. It is not, so the rule is flat -- nothing shipped refers to
it -- and the promise vocabulary is kept and widened, because "try it live" is
a lie about a hosted demo whether or not the sentence says where.

The second half is the one that matters, and it is why this is not a
``grep -rl huggingface | xargs sed``.

Two true sentences sat inside the blast radius. ``overrides/main.html`` lists
the author's own Hugging Face profile in the ``author.sameAs`` identity graph,
a few lines above where the software's own ``sameAs`` listed the dead Space:
one is a real profile belonging to a person, the other was a false claim about
where this software lives, and a scan that could not tell them apart would take
both. ``ARCHITECTURE.md`` and ``bindsight/runners/protocol.py`` named
"HuggingFace Spaces" (one word, plural) as a free compute tier -- a claim about
the landscape, not about this project's deployment. Both were corrected in the
same commit for a different reason and on the merits: this project's Space ran
on free **CPU**, which is why its design half went to Kaggle for a GPU at all,
so listing it among free *GPU* tiers was wrong before the Space was retired and
would still be wrong today. The one-word/two-word discrimination stays in the
pattern regardless, because the next person to sweep for "Hugging Face" needs
to find the reason written down rather than infer it.

``CHANGELOG.md`` is exempt by design. Its entries are dated records of what
happened, and the whole episode is in them. Deleting the word there would
falsify the history rather than correct it.

**On the sweep's own scope.** It reads every tracked file *except* the kinds
that cannot carry a sentence, rather than an allow-list of suffixes. The first
version of this file allow-listed suffixes and so never read ``Dockerfile``,
which has none -- the one file whose comments actually carried ``.huggingface``
and ``sync-hf-space``, hand-edited out by the very commit this guard was
written to protect. A guard that cannot read the file it exists for is the
defect this repository keeps finding in itself, and an allow-list is how it
happens.
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
#: ``Spaces?`` covers the plural, which the first version of this pattern missed:
#: "a Hugging Face Space" matched and "Hugging Face Spaces" did not. The
#: one-word "HuggingFace Spaces" is the compute-tier category and is deliberately
#: still NOT matched -- there is a fixture for it below. Nothing in the tree says
#: it today, but the distinction has to survive, because the day someone writes
#: a true sentence about free tiers this scan must not eat it.
SPACE_MENTION = re.compile(re.escape(SPACE_HOST) + r"|Hugging Face Spaces?\b", re.IGNORECASE)

#: The author's own profile: a person's identity, not this software's
#: deployment. It must survive every sweep above.
AUTHOR_PROFILE = "https://huggingface.co/Mikhaeelatefrizk"

#: File kinds that cannot carry a sentence: structures, sequences, images and
#: archives. Everything else tracked by git is swept, including files with no
#: suffix at all. A deny-list rather than an allow-list, because an allow-list
#: is what let ``Dockerfile`` out.
NOT_PROSE = frozenset(
    {".cif", ".pdb", ".fasta", ".png", ".jpg", ".jpeg", ".gz", ".zip", ".parquet"}
)

#: Each branch of the promise vocabulary, separately, so they can be counted and
#: pinned. Joined into one pattern below.
#:
#: Every branch but the last is a sentence this repository actually shipped.
#: ``hosted demo at`` never was -- it is here because it is the obvious next
#: phrasing -- and like every other branch it is pinned by a fixture in
#: ``TestTheScanWouldCatchWhatItLooksFor``, which is what stops any of them
#: being deleted silently.
BRANCHES = (
    r"try it live",
    r"lets anyone run",
    r"runs the (full )?discovery (half|pipeline) (live )?in (their|any|your) browser",
    r"runs the full pipeline in (their|any|your) browser",
    r"zero[- ]install",
    r"reachable in any",
    r"in your browser on the hosted",
    r"the hosted app runs",
    r"\[live app\]",
    r"deployed instance at",
    r"with no local installation",
    r"hosted as a",
    r"hosted demo at",
)

PROMISE = re.compile("|".join(BRANCHES), re.IGNORECASE)

#: One sentence per branch, at minimum. Overlaps are fine; gaps are not, and
#: ``test_every_branch_is_pinned_by_a_fixture`` fails on a gap.
PROMISED_SENTENCES = (
    '<a class="primary" href="https://example.org/hosted">Try it live</a>',
    "A public web demo lets anyone run the whole thing without installing it.",
    "It runs the discovery pipeline in their browser with nothing installed.",
    "The deployment runs the full pipeline in your browser.",
    "Zero install: open the page and go.",
    "The same demo is reachable in any web browser.",
    "Everything else runs on a CPU laptop, and in your browser on the hosted app.",
    "The hosted app runs the discovery half on a real TCGA cohort.",
    "Rotate them in 3-D on the [live app](https://example.org/hosted).",
    "The deployed instance at example.org provides five sections.",
    "The same demo runs in a web browser with no local installation.",
    "The web demo is hosted as a Hugging Face Space at <url>.",
    "Try the hosted demo at example.org, no setup required.",
)

#: Sentences the scans must NOT eat. Without these the patterns could be
#: widened until they flagged every true sentence in the repository.
TRUE_SENTENCES = (
    # The compute-tier category, one word and plural. Not a deployment.
    "Free GPU tiers (Colab T4, Kaggle T4, HuggingFace Spaces) are powerful enough.",
    "None for free tiers (Colab/Kaggle/HF Spaces).",
    # A person, not a deployment.
    AUTHOR_PROFILE,
    # Ordinary prose that must not trip either pattern.
    "The first run on a fresh container pays the GDC download.",
    "`bindsight ui` serves the interface locally in seconds.",
    # True of the LOCAL interface: it really does run the pipeline live.
    "It provides a one-click demo that runs the discovery pipeline live.",
    "The interface needs no build step and fetches nothing from a network.",
)


@functools.lru_cache(maxsize=1)
def _tracked_text() -> tuple[tuple[str, str], ...]:
    """Every tracked file that could carry a sentence, with its text.

    From git rather than a glob, and by exclusion rather than by allow-list: a
    document added tomorrow is covered the moment it is committed, whatever it
    is called and whether or not it has a suffix.
    """
    listed = subprocess.run(
        ["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=False
    ).stdout.split()
    out: list[tuple[str, str]] = []
    for rel in listed:
        path = REPO / rel
        if path.suffix.lower() in NOT_PROSE or not path.is_file():
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
        """A URL nothing points at is a URL something points at again."""
        assert not hasattr(theme, name), f"theme.{name} is back"


class TestNothingShippedNamesIt:
    def test_the_sweep_reads_the_repository(self) -> None:
        """Without this, a narrowed scope would pass every scan below.

        The anchors are one file per *kind*, not one per suffix that happens to
        be listed. ``Dockerfile`` and ``Snakefile`` are here because the first
        version of this sweep silently excluded every file without a suffix --
        and ``Dockerfile`` is the one whose comments actually carried the
        forbidden strings.
        """
        tracked = _tracked_text()

        assert len(tracked) > 200, f"the sweep found only {len(tracked)} files"

        names = {rel for rel, _ in tracked}
        for expected in (
            "Dockerfile",  # no suffix at all
            "Snakefile",  # ditto
            "pyproject.toml",
            "requirements.txt",
            "README.md",
            "paper/biorxiv/manuscript.tex",
            "mkdocs.yml",
            "codemeta.json",
            "CITATION.cff",
            "overrides/main.html",
            "bindsight/report/theme.py",
            "bindsight/report/web/static/binder_viewer.js",
        ):
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
            "these name a hosted Space this project no longer runs or refers to: "
            f"{offenders}. The evidence surface is published on the documentation "
            "site instead."
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
        offenders = [
            f"{rel} still refers to {gone}"
            for rel, text in _tracked_text()
            if rel not in MAY_NAME_IT
            for gone in (".huggingface", "sync-hf-space", "keep-warm")
            if gone in text
        ]

        assert not offenders, offenders


class TestTheTrueSentencesSurvive:
    """The other direction. Removing a deployment must not remove a person.

    ``author.sameAs`` ties this software's author to their canonical profiles so
    a search engine can connect them. The Hugging Face entry there is a real
    profile, a few lines from where the software's own ``sameAs`` listed the
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
            "Space was the entry a few lines below it."
        )

    def test_the_software_no_longer_lists_the_space_among_its_own_urls(self) -> None:
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

    @staticmethod
    def _index() -> str:
        return (REPO / "docs" / "index.md").read_text(encoding="utf-8")

    def test_there_is_exactly_one_primary_call_to_action(self) -> None:
        """Counted over the whole page, not inside one block.

        This was scoped to ``<div class="bs-cta">(.*?)</div>``, and a non-greedy
        match ends at the first *nested* ``</div>`` -- so a second primary
        button placed after any nested element was invisible to it.
        """
        index = self._index()

        assert '<div class="bs-cta">' in index, "docs/index.md lost its call-to-action block"
        primary = re.findall(r'<a class="primary"[^>]*href="([^"]+)"', index)

        assert len(primary) == 1, (
            f"expected exactly one primary call to action on the page, found "
            f"{primary} -- the fix for this is to re-point the button, not to "
            "delete it"
        )

    def test_the_primary_button_points_at_a_page_this_repository_serves(self) -> None:
        """Any external host, not only the retired one."""
        primary = re.findall(r'<a class="primary"[^>]*href="([^"]+)"', self._index())
        assert primary, "no primary call to action"
        href = primary[0]

        assert not href.startswith(("http://", "https://")), (
            f"the primary button leaves the site, to {href!r}. A first-time "
            "visitor clicks it before reading anything, so it must land on a "
            "page this repository publishes."
        )


class TestTheScanWouldCatchWhatItLooksFor:
    """Each pattern proved against what it is meant to catch, so none goes blind."""

    @pytest.mark.parametrize("sample", PROMISED_SENTENCES, ids=range(len(PROMISED_SENTENCES)))
    def test_it_catches_a_promise(self, sample: str) -> None:
        """PROMISE alone, not "PROMISE or a Space mention".

        Letting the address pattern satisfy this left branches of the promise
        vocabulary resting on sentences that named the Space, so they could be
        deleted without any fixture noticing.
        """
        assert PROMISE.search(sample), sample

    @pytest.mark.parametrize("branch", BRANCHES, ids=range(len(BRANCHES)))
    def test_every_branch_is_pinned_by_a_fixture(self, branch: str) -> None:
        """No branch may rest on nothing.

        Six of thirteen once did: deleting any of them left the whole module
        green while the docstring claimed each was exercised. A vocabulary
        nobody exercises is one that gets narrowed to fix the sentence that
        trips it.
        """
        pattern = re.compile(branch, re.IGNORECASE)
        hits = [s for s in PROMISED_SENTENCES if pattern.search(s)]

        assert hits, (
            f"no fixture exercises the branch {branch!r}, so deleting it would "
            "pass silently. Add a sentence to PROMISED_SENTENCES that matches it."
        )

    @pytest.mark.parametrize("sample", TRUE_SENTENCES, ids=range(len(TRUE_SENTENCES)))
    def test_it_does_not_eat_a_true_sentence(self, sample: str) -> None:
        assert not SPACE_MENTION.search(sample), sample
        assert not PROMISE.search(sample), sample

    def test_the_vocabulary_has_not_been_gutted(self) -> None:
        """Counted as branches, not as pipes.

        This counted ``PROMISE.pattern.count("|")``, which includes the pipes
        inside ``(half|pipeline)`` and ``(their|any|your)`` -- so two whole
        branches could be deleted and the floor still cleared.
        """
        assert len(BRANCHES) >= 13, (
            f"the promise vocabulary is down to {len(BRANCHES)} branches; it is "
            "easier to delete a branch than to fix the sentence that trips it"
        )
        assert PROMISE.groups == sum(re.compile(b).groups for b in BRANCHES), (
            "PROMISE is no longer built from BRANCHES, so the count above "
            "measures something other than the pattern being used"
        )

    def test_the_address_pattern_catches_both_numbers(self) -> None:
        """Singular and plural, since prose uses both."""
        assert SPACE_MENTION.search("published as a Hugging Face Space at <url>")
        assert SPACE_MENTION.search("deployed to Hugging Face Spaces last year")
        assert SPACE_MENTION.search(f"see {SPACE_HOST} for it")

    def test_sentence_splitting_does_not_swallow_the_page(self) -> None:
        """A whole-file match would blame a promise elsewhere on the page."""
        text = f"The demo runs the full pipeline in your browser. See {SPACE_HOST} for it."
        picked = [s for s in _sentences(text) if SPACE_MENTION.search(s)]

        assert len(picked) == 1
        assert not PROMISE.search(picked[0])

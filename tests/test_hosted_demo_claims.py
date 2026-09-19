# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""No document may promise a hosted demo that is not being served.

The Hugging Face Space serves a blank page titled "Streamlit" -- the framework
the interface release deleted -- and has since that release.
``.github/workflows/sync-hf-space.yml`` uploads nothing until an ``HF_TOKEN``
secret exists, and without it skips every step and reports success, so nothing
in CI ever went red about it.

One job did notice. ``keep-warm.yml``'s ``hf-build-identity`` fetches the
interface stylesheet and fails unless it carries this build's own token, and it
has been red every six hours since. But a red scheduled check is a signal to
whoever opens the Actions tab, and the reader this mattered to was following a
button on the documentation home page labelled "Try it live" -- straight onto
the blank page.

So the failure was never a lack of knowledge. ``CHANGELOG.md`` says plainly
that the release does not restore the demo, and ``report/showcase.py`` says the
Space does not deploy the full repository. The true sentence existed in two
places and the false one in ten. That is a propagation failure, and a guard is
what fixes it.

The rule here is a prohibition, not a fact table: while the Space is not known
to be serving this build, no shipped document may say a reader can use it.
Naming it as an address is fine -- that is true whatever it serves. Promising
that it runs is not. Wording chosen that way stays true after the Space is
rebuilt, so nothing here has to be un-written later; only the home page's
primary button, which is clicked before it is read and so cannot be hedged.
"""

from __future__ import annotations

import functools
import re
import subprocess
from pathlib import Path

import pytest
import yaml

from bindsight.report import theme

REPO = Path(__file__).resolve().parents[1]

SPACE_HOST = "huggingface.co/spaces/Mikhaeelatefrizk/bindsight"

#: How a document refers to the deployment -- by address or by name. The name
#: alone matters: the home page names the Space in prose without linking it, so
#: a sweep that only looked for the URL would not read that sentence at all.
#: "HuggingFace Spaces" (one word, plural) is the GPU-tier category and is
#: deliberately not matched.
SPACE_MENTION = re.compile(re.escape(SPACE_HOST) + r"|Hugging Face Space\b", re.IGNORECASE)

#: Where a promise could be written. Everything else in the tree is data.
CLAIM_SUFFIXES = frozenset({".md", ".tex", ".html", ".j2", ".py", ".cff", ".yml", ".yaml"})

#: Files whose whole subject is the dormancy, and which therefore have to
#: describe it in the words this scan forbids.
MAY_DESCRIBE_THE_PROBLEM = frozenset(
    {
        "CHANGELOG.md",
        f"tests/{Path(__file__).name}",
        ".github/workflows/keep-warm.yml",
        ".github/workflows/sync-hf-space.yml",
    }
)

#: Phrases that tell a reader the hosted deployment will work for them now.
#: Every alternative below was written in this repository and is exercised as a
#: fixture in ``TestTheScanWouldCatchWhatItLooksFor`` -- so narrowing this
#: pattern to nothing fails there rather than passing silently here.
PROMISE = re.compile(
    r"try it live"
    r"|lets anyone run"
    r"|runs the (full )?discovery (half|pipeline) (live|in (their|any|your) browser)"
    r"|runs the full pipeline in (their|any|your) browser"
    r"|zero[- ]install"
    r"|reachable in any"
    r"|in your browser on the hosted"
    r"|the hosted app runs"
    r"|\[live app\]"
    r"|deployed instance at",
    re.IGNORECASE,
)


@functools.lru_cache(maxsize=1)
def _documents_naming_the_space() -> tuple[str, ...]:
    """Every tracked document that names the Space, discovered rather than listed.

    A hand-written list is the defect class this repository keeps finding, and
    a document added tomorrow is covered by this the moment it exists.
    """
    listed = subprocess.run(
        ["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=False
    ).stdout.split()
    out: list[str] = []
    for rel in listed:
        path = REPO / rel
        if path.suffix not in CLAIM_SUFFIXES or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):  # pragma: no cover
            continue
        if SPACE_MENTION.search(text):
            out.append(rel)
    return tuple(out)


def _sentences_naming_the_space(text: str) -> list[str]:
    """The sentences that name the Space, so a promise elsewhere on the page is not
    blamed on it."""
    flat = " ".join(text.split())
    return [p for p in re.split(r"(?<=[.!?])\s+", flat) if SPACE_MENTION.search(p)]


DOCUMENTS = _documents_naming_the_space()
CHECKED = [rel for rel in DOCUMENTS if rel not in MAY_DESCRIBE_THE_PROBLEM]


def test_the_sweep_finds_the_documents_that_name_the_space() -> None:
    """Without this, a bad glob would make every scan below vacuously pass."""
    assert len(DOCUMENTS) >= 5, f"the sweep found only {DOCUMENTS}"
    for expected in (
        "docs/index.md",
        "paper/paper.md",
        "paper/biorxiv/manuscript.tex",
        "bindsight/report/theme.py",
    ):
        assert expected in DOCUMENTS, f"{expected} names the Space but the sweep missed it"
    assert CHECKED, "every document naming the Space is exempt; nothing is checked"


@pytest.mark.skipif(
    theme.HF_SPACE_IS_SERVING_THIS_BUILD,
    reason="the Space serves this build, so a reader can be told to use it",
)
@pytest.mark.parametrize("rel", CHECKED, ids=CHECKED)
def test_no_document_promises_a_working_hosted_demo_while_it_is_dormant(rel: str) -> None:
    text = (REPO / rel).read_text(encoding="utf-8")

    offending = [s for s in _sentences_naming_the_space(text) if PROMISE.search(s)]

    assert not offending, (
        f"{rel} tells a reader the hosted demo will work for them. It serves a "
        f"blank Streamlit page until an HF_TOKEN secret exists. Offending "
        f"sentence(s): {offending}. Naming the Space as an address is fine; "
        "promising it runs is not."
    )


@pytest.mark.skipif(
    theme.HF_SPACE_IS_SERVING_THIS_BUILD,
    reason="the Space serves this build, so the button may point at it",
)
def test_the_home_page_button_does_not_send_readers_to_a_dormant_space() -> None:
    """The one thing wording cannot fix: a button is clicked before it is read."""
    index = (REPO / "docs" / "index.md").read_text(encoding="utf-8")
    block = re.search(r'<div class="bs-cta">(.*?)</div>', index, re.S)

    assert block, "docs/index.md lost its call-to-action block"
    primary = re.findall(r'<a class="primary"[^>]*href="([^"]+)"', block.group(1))
    assert len(primary) == 1, (
        f"expected exactly one primary call to action, found {primary} -- "
        "the fix for this is to re-point the button, not to delete it"
    )
    assert SPACE_HOST not in primary[0], (
        "the home page's primary button sends a first-time visitor to the Space, "
        "which serves a blank Streamlit page"
    )


def test_the_flag_agrees_with_the_workflow_that_would_flip_it() -> None:
    """Fails in both directions, so the flag cannot drift from reality.

    Dormant-and-claiming-otherwise is the defect this file exists for. But
    serving-and-still-saying-dormant is a defect too: it would keep the
    prohibition above in force after it stopped being true, and the home page
    button pointed away from a working demo.
    """
    sync = (REPO / ".github" / "workflows" / "sync-hf-space.yml").read_text(encoding="utf-8")
    dormant_signature = "has_token=false" in sync and "has_token == 'true'" in sync

    if theme.HF_SPACE_IS_SERVING_THIS_BUILD:
        assert not dormant_signature, (
            "the flag says the Space serves this build, but sync-hf-space.yml "
            "still skips every step without a token, so nothing has been uploaded"
        )
    else:
        assert dormant_signature, (
            "sync-hf-space.yml no longer gates on a token, so the Space may now "
            "be receiving builds -- run keep-warm.yml and, if hf-build-identity "
            "is green, set theme.HF_SPACE_IS_SERVING_THIS_BUILD = True"
        )


def test_keep_warm_still_proves_build_identity_and_is_allowed_to_fail() -> None:
    """The premise every check above rests on.

    The prohibition is lifted by a green ``hf-build-identity``. If that job were
    made ``continue-on-error``, or stopped checking the stylesheet, it would go
    green without proving anything and the flag would be flipped on nothing.
    """
    workflow = yaml.safe_load(
        (REPO / ".github" / "workflows" / "keep-warm.yml").read_text(encoding="utf-8")
    )
    job = workflow["jobs"].get("hf-build-identity")

    assert job, "keep-warm.yml no longer has the job that proves what the Space serves"
    assert not job.get("continue-on-error", False), (
        "hf-build-identity is allowed to fail silently, so it proves nothing"
    )
    body = yaml.dump(job)
    assert "/static/bindsight.css" in body, "the job no longer fetches the interface stylesheet"
    assert "--ink-faint" in body, "the job no longer checks for this build's own CSS token"


class TestTheScanWouldCatchWhatItLooksFor:
    """Each pattern proved against what was actually written, so none goes blind."""

    @pytest.mark.parametrize(
        "sample",
        [
            '<a class="primary" href="https://huggingface.co/spaces/X">Try it live</a>',
            "A public web demo, a Hugging Face Space at <url>, lets anyone run the "
            "full discovery pipeline in their browser without installing anything.",
            "Zero install. The hosted app runs the discovery half live on a real TCGA cohort.",
            "Everything else runs on a CPU laptop, and in your browser on the hosted app.",
            "The same demo is reachable in any web browser at huggingface.co/spaces/X.",
            "The deployed instance at huggingface.co/spaces/X provides five sections.",
            "Rotate them in 3-D on the [live app](https://huggingface.co/spaces/X).",
        ],
    )
    def test_it_catches_what_this_repository_used_to_say(self, sample: str) -> None:
        assert PROMISE.search(sample), sample

    @pytest.mark.parametrize(
        "sample",
        [
            "The same interface is published as a public Hugging Face Space at <url>.",
            "It is launched locally with bindsight ui and published as a Hugging "
            "Face Space at <url>.",
            "The web demo is hosted as a Hugging Face Space at <url>.",
            "HF_SPACE_URL = 'https://huggingface.co/spaces/Mikhaeelatefrizk/bindsight'",
            "The first run on a fresh container pays the GDC download.",
        ],
    )
    def test_it_permits_naming_the_space_as_an_address(self, sample: str) -> None:
        assert not PROMISE.search(sample), sample

    def test_the_alternation_has_not_been_gutted(self) -> None:
        assert PROMISE.pattern.count("|") >= 8, (
            "the promise vocabulary has been narrowed; it is easier to delete a "
            "branch of this pattern than to fix the sentence that trips it"
        )

    def test_sentence_splitting_does_not_swallow_the_page(self) -> None:
        """A whole-file match would blame a promise elsewhere on the page."""
        text = f"The demo runs the full pipeline in your browser. See {SPACE_HOST} for it."
        picked = _sentences_naming_the_space(text)
        assert len(picked) == 1
        assert not PROMISE.search(picked[0])

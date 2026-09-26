# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
r"""The methods manuscript is built by CI, because it cannot be built here.

`paper/methods/manuscript.tex` needs pdflatex and biber, and the machine this
project is written on has neither. The obvious workaround does not work: the
manuscript reaches its bibliography with ``\addbibresource{../paper.bib}``, one
directory up, so uploading ``paper/methods/`` to an online compiler as a zip
uploads a project with no bibliography -- which compiles, and produces a PDF
with a question mark where every citation should be. A failure that renders is
worse than one that stops.

So the PDF is a CI artifact, which makes this workflow load-bearing in a way a
workflow usually is not: it is the only route this repository has to the
document it sends to a preprint server. Deleted, renamed, or quietly re-pointed
at some other ``.tex``, it would leave ``paper/README.md`` instructing a
submitter to download a file that no longer exists -- and nothing else in this
suite reads a workflow for *what it builds*.
``tests/test_packaging_pins.py`` checks how actions are pinned and what the CI
gate depends on; neither question reaches this one.

The three facts checked here are the three ``paper/README.md`` promises a
reader: the workflow exists, it compiles *this* manuscript, and a published
release carries the PDF as an asset. The JOSS paper's workflow, which already
built its PDF as an artifact, is held to the same release promise, and both
assets are named so a reader can tell them apart.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
WORKFLOW = REPO / ".github" / "workflows" / "manuscript-pdf.yml"
JOSS_WORKFLOW = REPO / ".github" / "workflows" / "draft-pdf.yml"

WORKING_DIRECTORY = "paper/methods"
ROOT_FILE = "manuscript.tex"
ARTIFACT = "methods-manuscript"
PDF = "paper/methods/manuscript.pdf"
JOSS_PDF = "paper/paper.pdf"

#: The validation study. It is Markdown, so pandoc renders it rather than
#: latexmk, and it is the document a preprint server receives -- see
#: `paper/SUBMISSIONS.md` for why that is the study and not the methods .tex.
STUDY_SOURCE = "paper/validation/manuscript.md"
STUDY_ARTIFACT = "study-manuscript"
STUDY_PDF = "paper/validation/manuscript.pdf"


@pytest.fixture(scope="module")
def workflow() -> dict[str, Any]:
    assert WORKFLOW.is_file(), (
        "`.github/workflows/manuscript-pdf.yml` is gone. `paper/README.md` "
        "tells a submitter to download the manuscript PDF from this workflow's "
        "run or from the release assets; without it the only remaining route "
        "is a local TeX Live install, which is the thing it exists to avoid."
    )
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def joss_workflow() -> dict[str, Any]:
    assert JOSS_WORKFLOW.is_file(), "`.github/workflows/draft-pdf.yml` is gone"
    return yaml.safe_load(JOSS_WORKFLOW.read_text(encoding="utf-8"))


def _triggers(workflow: dict[str, Any]) -> dict[str, Any]:
    """The ``on:`` block.

    YAML 1.1 resolves a bare ``on`` key to the boolean ``True``, so
    ``workflow["on"]`` is a ``KeyError`` on a file GitHub parses perfectly well.
    Both spellings are accepted here rather than quoting the key in the
    workflow, because an unquoted ``on:`` is what every other workflow in this
    repository writes and a test should not dictate that.
    """
    for key in ("on", True):
        if key in workflow:
            return workflow[key]
    raise AssertionError("the workflow declares no triggers at all")


def _steps(workflow: dict[str, Any]) -> list[dict[str, Any]]:
    return [step for job in workflow["jobs"].values() for step in job.get("steps", [])]


def _invokes(step: dict[str, Any], command: str) -> bool:
    """Whether a step's script actually runs ``command``.

    Substring tests are not enough here. ``true # pandoc manuscript.md`` contains
    "pandoc", and a guard written that way passed on a step that rendered
    nothing. Neither is "a line that starts with it": the apt-get install line
    wraps onto a continuation line beginning ``pandoc texlive-xetex ...``, which
    is an argument. So: a line that starts with the command and does not continue
    the line above it.
    """
    run = str(step.get("run", ""))
    continued = False
    for line in run.splitlines():
        stripped = line.strip()
        # A line that continues the previous one holds arguments, not a command.
        # `apt-get install ... \` followed by `pandoc texlive-xetex ...` reads as
        # a pandoc invocation to a naive check, and did.
        if not continued and stripped.startswith(command):
            return True
        continued = stripped.endswith("\\")
    return False


def _attaching_jobs(workflow: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        job
        for job in workflow["jobs"].values()
        if any("gh release upload" in str(s.get("run", "")) for s in job.get("steps", []))
    ]


class TestItBuildsTheManuscriptItClaimsTo:
    def test_a_latex_step_compiles_the_methods_manuscript(self, workflow: dict[str, Any]) -> None:
        compiling = [
            step for step in _steps(workflow) if "latex-action" in str(step.get("uses", ""))
        ]
        assert compiling, "no LaTeX action runs in this workflow, so nothing is compiled"

        for step in compiling:
            inputs = step.get("with", {})
            assert inputs.get("working_directory") == WORKING_DIRECTORY, (
                f"the LaTeX step compiles in {inputs.get('working_directory')!r}, "
                f"not {WORKING_DIRECTORY!r}"
            )
            assert ROOT_FILE in str(inputs.get("root_file", "")), (
                f"the LaTeX step's root file is {inputs.get('root_file')!r}; the "
                "manuscript this workflow is named for is manuscript.tex"
            )

    def test_the_manuscript_it_names_is_in_the_tree(self) -> None:
        """Guards the guard: the checks above would pass on a workflow pointed
        at a file nobody has written."""
        assert (REPO / WORKING_DIRECTORY / ROOT_FILE).is_file()

    def test_the_bibliography_it_needs_sits_outside_the_working_directory(self) -> None:
        r"""The reason the whole repository is checked out, written down.

        If ``paper.bib`` is ever copied into ``paper/methods/``, this test goes
        red and the comment in the workflow about Overleaf becomes false --
        which is the point. The shared bibliography is deliberate: one file
        means one place to fix a citation.
        """
        tex = (REPO / WORKING_DIRECTORY / ROOT_FILE).read_text(encoding="utf-8")

        assert r"\addbibresource{../paper.bib}" in tex, (
            "the manuscript no longer reaches the shared bibliography by the "
            "relative path this workflow is built around"
        )
        assert (REPO / "paper" / "paper.bib").is_file()
        assert not (REPO / WORKING_DIRECTORY / "paper.bib").exists(), (
            "a second bibliography appeared next to the manuscript; the two "
            "will drift, which is why there is only supposed to be one"
        )

    def test_an_undefined_citation_fails_the_build(self, workflow: dict[str, Any]) -> None:
        """latexmk exits 0 on a missing bibliography and leaves ``[?]`` in the
        PDF. The workflow must read the log and refuse that."""
        runs = " ".join(str(s.get("run", "")) for s in _steps(workflow))
        assert "manuscript.log" in runs, "nothing in the workflow reads the LaTeX log"
        assert "undefined" in runs, "nothing in the workflow fails the run on an undefined citation"


class TestThePdfReachesSomewhereAHumanCanClick:
    def test_the_run_carries_the_pdf_as_an_artifact(self, workflow: dict[str, Any]) -> None:
        uploads = [
            step.get("with", {})
            for step in _steps(workflow)
            if str(step.get("uses", "")).startswith("actions/upload-artifact@")
        ]
        assert uploads, "the workflow compiles a PDF and uploads nothing"

        named = [u for u in uploads if u.get("name") == ARTIFACT]
        assert named, (
            f"no artifact is named {ARTIFACT!r}; paper/README.md tells a reader "
            "to look for that name on the run page"
        )
        for upload in named:
            assert "manuscript.pdf" in str(upload.get("path", ""))
            assert upload.get("if-no-files-found") == "error", (
                "a build that produced no PDF must fail, not upload nothing"
            )

    def test_a_published_release_gets_the_pdf_attached(self, workflow: dict[str, Any]) -> None:
        """An artifact expires; a release asset does not.

        Artifact retention is 90 days by default. The tag a manuscript cites
        outlives that, so the copy that has to survive is the one on the
        release.
        """
        release = _triggers(workflow).get("release") or {}
        assert "published" in (release.get("types") or []), (
            "the workflow does not run on a published release, so a release is "
            "cut without the manuscript attached to it"
        )

        attaching = _attaching_jobs(workflow)
        assert attaching, "nothing in this workflow uploads an asset to a release"

        for job in attaching:
            assert job.get("if") == "github.event_name == 'release'", (
                "the attach job must run only on the release event; on a push "
                "there is no release to upload to and the step fails loudly"
            )
            assert job.get("permissions", {}).get("contents") == "write", (
                "the job that uploads a release asset needs contents: write; "
                "without it the upload fails on every release and the failure "
                "is only visible to someone who opens the run"
            )
            runs = " ".join(str(s.get("run", "")) for s in job.get("steps", []))
            assert PDF in runs, f"the release upload does not name {PDF}"
            assert "methods-manuscript.pdf" in runs, "the asset must be named for what it is"
            assert "--clobber" in runs, "the asset must be re-uploadable on a re-run"


class TestTheJossPaperTravelsWithTheReleaseToo:
    def test_the_joss_workflow_attaches_its_pdf_on_a_published_release(
        self, joss_workflow: dict[str, Any]
    ) -> None:
        release = _triggers(joss_workflow).get("release") or {}
        assert "published" in (release.get("types") or []), (
            "draft-pdf.yml does not run on a published release"
        )
        attaching = _attaching_jobs(joss_workflow)
        assert attaching, "draft-pdf.yml uploads no asset to a release"
        for job in attaching:
            assert job.get("if") == "github.event_name == 'release'"
            assert job.get("permissions", {}).get("contents") == "write"
            runs = " ".join(str(s.get("run", "")) for s in job.get("steps", []))
            assert JOSS_PDF in runs
            assert "joss-paper.pdf" in runs
            assert "--clobber" in runs

    def test_the_two_assets_cannot_be_confused(
        self, workflow: dict[str, Any], joss_workflow: dict[str, Any]
    ) -> None:
        """Both are `*.pdf`; the names on the release page must say which."""
        manuscript = " ".join(
            str(s.get("run", "")) for job in _attaching_jobs(workflow) for s in job["steps"]
        )
        paper = " ".join(
            str(s.get("run", "")) for job in _attaching_jobs(joss_workflow) for s in job["steps"]
        )
        assert "methods" in manuscript, (
            "the manuscript asset must name the document it is. It was "
            "'biorxiv-manuscript' until bioRxiv declined the submission and the "
            "directory was renamed to say what the file is rather than where it "
            "was going -- see paper/SUBMISSIONS.md."
        )
        assert "methods" not in paper
        assert "joss" in paper
        assert "joss" not in manuscript


class TestItRunsWhenTheDocumentChanges:
    def test_the_push_filter_covers_both_inputs_to_the_pdf(self, workflow: dict[str, Any]) -> None:
        """The bibliography is the one a path filter forgets.

        It lives outside `paper/methods/`, so a filter written as that
        directory alone would leave a citation fix unbuilt and the artifact
        stale -- silently, which is the failure mode.
        """
        paths = (_triggers(workflow).get("push") or {}).get("paths") or []

        for required in ("paper/methods/**", "paper/paper.bib"):
            assert required in paths, (
                f"{required!r} is not in the push filter, so a change to it "
                f"does not rebuild the PDF. The filter is {paths}."
            )

    def test_it_can_be_run_by_hand(self, workflow: dict[str, Any]) -> None:
        """Submission day is not a push day."""
        assert "workflow_dispatch" in _triggers(workflow)


class TestTheStudyIsTypesetToo:
    """The study had no PDF build at all until the bioRxiv decline moved it to
    the front. These hold the build that was added."""

    def test_the_source_it_renders_is_on_disk(self) -> None:
        assert (REPO / STUDY_SOURCE).is_file(), (
            f"{STUDY_SOURCE} is gone. It is the fifteen-cohort rediscovery "
            "study -- the instance of the software being used for research that "
            "JOSS's pre-review gate asks for."
        )

    def test_a_pandoc_step_renders_the_study(self, workflow: dict[str, Any]) -> None:
        """pandoc, not latexmk: the study's references are a hand-numbered list
        rather than \\cite keys, so there is no bibliography to resolve."""
        rendering = [step for step in _steps(workflow) if _invokes(step, "pandoc")]
        assert rendering, (
            "no step actually invokes pandoc. Without it the study has no PDF, "
            "and a preprint server takes a PDF. Note this looks for a command, "
            "not for the word: `true # pandoc manuscript.md` contains the word "
            "and renders nothing, and an earlier version of this test passed on "
            "exactly that."
        )
        for step in rendering:
            run = str(step["run"])
            assert "manuscript.md" in run, "pandoc must be pointed at the study"
            assert "--pdf-engine" in run, "pandoc needs a PDF engine named explicitly"
            assert "manuscript.pdf" in run, "the output must be named"

    def test_the_build_refuses_a_pdf_that_rendered_nothing(self, workflow: dict[str, Any]) -> None:
        """pandoc exits 0 on a document it rendered as one blank page.

        Silent success is the failure this repository names most often: a green
        check for work that did not happen. A size floor is crude and it is
        enough -- the study is ~2,800 words and cannot come back tiny.
        """
        measuring = [
            str(step.get("run", ""))
            for step in _steps(workflow)
            if "stat -c%s" in str(step.get("run", "")) and STUDY_PDF in str(step.get("run", ""))
        ]
        assert measuring, (
            "nothing measures the rendered study. pandoc returns 0 on an empty "
            "render, so a green run proves nothing on its own."
        )
        for run in measuring:
            assert "exit 1" in run, (
                "the size check must fail the run rather than log and continue. "
                "Checked inside this step, not across the workflow: the methods "
                "job's citation check also exits 1, and looking for it anywhere "
                "let this guard pass while the study's check was deleted."
            )

    def test_the_artifact_is_uploaded_under_its_own_name(self, workflow: dict[str, Any]) -> None:
        uploads = [
            step
            for step in _steps(workflow)
            if str(step.get("uses", "")).startswith("actions/upload-artifact")
            and step.get("with", {}).get("name") == STUDY_ARTIFACT
        ]
        assert uploads, f"no step uploads an artifact named {STUDY_ARTIFACT!r}"
        for step in uploads:
            with_ = step["with"]
            assert with_.get("path") == STUDY_PDF, (
                f"the {STUDY_ARTIFACT!r} artifact must carry {STUDY_PDF}"
            )
            assert with_.get("if-no-files-found") == "error", (
                "an upload that finds no file must fail; the default is a warning "
                "and a green run with an empty artifact"
            )

    def test_the_release_carries_both_manuscripts(self, workflow: dict[str, Any]) -> None:
        """A release that attached only one of them would leave the document
        under submission off the page it is cited from."""
        attaching = _attaching_jobs(workflow)
        assert attaching, "no job attaches anything to a release"
        runs = " ".join(str(s.get("run", "")) for job in attaching for s in job["steps"])
        uploaded = runs[runs.index("gh release upload") :] if "gh release upload" in runs else ""
        for asset, source in (
            ("methods-manuscript.pdf", PDF),
            ("validation-study.pdf", STUDY_PDF),
        ):
            # Both halves, deliberately. Deleting the `cp` leaves the name in the
            # upload's argument list, and an earlier version of this test passed
            # on a release that would upload a file nothing had created.
            assert f"cp {source}" in runs, (
                f"nothing copies {source} to its release name; the upload would "
                f"reference a {asset} that was never made"
            )
            assert asset in uploaded, f"{asset} is never handed to `gh release upload`"

    def test_attaching_waits_for_both_builds(self, workflow: dict[str, Any]) -> None:
        """``needs: build`` alone would attach a stale or missing study PDF."""
        for name, job in workflow["jobs"].items():
            if not any("gh release upload" in str(s.get("run", "")) for s in job.get("steps", [])):
                continue
            needs = job.get("needs")
            needs = [needs] if isinstance(needs, str) else list(needs or [])
            for required in ("build", "study"):
                assert required in needs, (
                    f"job {name!r} attaches PDFs but waits on {needs}; it must "
                    f"wait on {required} too, or it attaches a stale or missing PDF"
                )

    def test_a_push_that_touches_only_the_study_still_builds(
        self, workflow: dict[str, Any]
    ) -> None:
        """The study lives outside `paper/methods/`, so the original path filter
        would have ignored every change to it."""
        paths = _triggers(workflow)["push"]["paths"]
        assert any(p.startswith("paper/validation") for p in paths), (
            f"the push filter is {paths}; a change to the study would not rebuild its PDF"
        )

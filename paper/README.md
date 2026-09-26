# Manuscripts and submission instructions

This directory holds three documents about `bindsight`, the bibliography two
of them share, and the record of where each has been sent. They all describe the
current release: `paper.md` carries its date in its front matter,
`methods/manuscript.tex` names the version it presents, and
`tests/test_docs_claims.py` holds that version to `pyproject.toml`. The
repository README and CHANGELOG remain authoritative wherever they disagree
with a manuscript; the rest of this file is submission mechanics and the order
they happen in.

```
paper/
├── README.md          ← this file: what goes where, and in what order
├── SUBMISSIONS.md     ← every venue tried, and what came back, verbatim.
│                        The single source of truth for submission state;
│                        tests/test_submission_record.py holds the rest of
│                        the repository to it.
├── LICENSE            ← CC BY 4.0, covering everything else in this directory
├── paper.md           ← JOSS software paper (standard path; JOSS
│                        auto-discovers it, so it must stay here)
├── paper.bib          ← BibTeX bibliography, shared by paper.md and the
│                        methods manuscript
├── methods/
│   └── manuscript.tex ← long-form description of the software (LaTeX).
│                        Reaches the bibliography with
│                        \addbibresource{../paper.bib}, which is why it
│                        cannot be zipped up on its own. Not under
│                        submission anywhere — see SUBMISSIONS.md.
└── validation/
    └── manuscript.md  ← the fifteen-cohort rediscovery study. The document
                         that goes to a preprint server, because it is the
                         software *used in* research rather than described.
```

> ℹ️ **No compiled PDF is committed.** One used to be, but it predated the
> v0.2.1 corrections and carried the wrong licence ("MIT"), a superseded
> archive DOI and the pre-correction Boltz-2 reference — a deposit hazard sitting
> in the tree. It has been removed and `.gitignore` keeps it out. CI builds the
> PDF instead; see **Getting the PDF** below.

None of the three cites a software DOI. This release is not archived under a
DOI: cite the repository, the tag you ran and the checksums attached to the
release. Same author (Mikhaeel Atef Rizk Wahba, ORCID `0009-0006-1069-9558`),
same code, same evidence surface — different audiences and different review
processes.

---

## Three documents, three destinations

| | `paper.md` | `validation/manuscript.md` | `methods/manuscript.tex` |
|---|---|---|---|
| What it is | JOSS software paper | The fifteen-cohort rediscovery study | Long-form description of the software |
| Format | Markdown, 750–1,750 words | Markdown, ~2,800 words | LaTeX, ~3,300 words |
| Destination | **JOSS**, on or after 2026-12-07 | **Preprints.org**, now | Nowhere — built by CI, attached to every release |
| Review | Peer review, open, on GitHub, ~4–8 weeks | Editorial screening only, ~24 h | None |
| DOI | On acceptance | On posting | None |
| Cost | Free | Free | — |

The **Destination** row is the one that changed. bioRxiv declined this work on 2026-09-25
because it requires an organizational affiliation and the author has none;
`SUBMISSIONS.md` quotes the decision. So the preprint slot moved venue — and, more
importantly, moved *document*. The next section is why.

---

## Order of operations

Both, in this order, for a reason that is not about audience.

### 1. Preprints.org, with the *study* — now

The point of a preprint here is narrow: JOSS will not review software with no
evidence of research use, and a DOI on a piece of research done with bindsight is
that evidence. Which means the document that goes out is the rediscovery study,
not the methods manuscript, and that is a change from what this file used to say.

JOSS's pre-review gate is titled **Demonstrated research impact** and reads:

> There must be evidence that the software is being used for research — at
> minimum by the developers themselves, and ideally by others. Acceptable signals
> include: references in published papers or preprints … Aspirational statements
> about future use are not sufficient; JOSS will not publish papers that are meant
> to advertise software that is not yet being used in research.

"At minimum by the developers themselves" settles a question this file previously
treated as open: no third-party adopter is needed. The author running bindsight
across fifteen TCGA cohorts is the qualifying instance.

But the gate asks for the software *doing work*, and the sentence it ends on cuts
directly against offering a paper about the software as the evidence. There is a
precedent, [joss-reviews#10267](https://github.com/openjournals/joss-reviews/issues/10267),
closed by the same Editor-in-Chief a month before ours:

> The research impact statement in the paper describes the adoption of entropart,
> the predecessor package, rather than divent specifically… it is the software
> under review, and we need at least one instance of it being used in a published
> or preprint research context before we can proceed… a preprint is sufficient.

That submission died pointing at the wrong artifact. `methods/manuscript.tex` is a
paper about bindsight by bindsight's author; offering its DOI invites the same
reading. `validation/manuscript.md` is bindsight run on real patient data,
reporting a result — including the results that went against the author, and the
headline it withdrew. It is the right document, and JOSS's own
"Co-publication of science, methods, and software" section anticipates exactly
this pairing.

### 2. JOSS — on or after 2026-12-07

A JOSS submission was opened on 2026-06-07 (openjournals/joss-reviews#10660)
and closed the same day at pre-review, labelled `rejected`, with no editor
assigned. The editor's reason, verbatim:

> The repository is less than one month old, with no research applications of
> the software documented. JOSS requires a public development history of at
> least six months, with evidence of iterative development, and at minimum one
> instance of the software being used in published or preprint research. A web
> demonstration does not satisfy this requirement. We'd welcome a resubmission
> once the software has a longer development history and has been applied in
> actual research.

Two conditions, and the calendar decides one of them — but read the date
carefully, because there are two and they disagree.

The first commit is dated **2026-05-09**, so six months of public development
history is reached on **2026-11-09**. Separately, JOSS's guidance on desk
rejections says: "Fix the gaps, continue developing openly, and resubmit in six
months or more." Six months from the 2026-06-07 rejection is **2026-12-07**.
Take the later date. A second rejection on a ground that a month's patience would
have removed is the one outcome with nothing to recommend it.

The other half of that condition — "evidence of iterative development" — is no
longer arguable and does not need waiting out. The editorial bot saw 36 commits
and one release on 2026-06-07. The repository now holds **392 commits across five
months and eleven tags**.

**The complication, and it must be stated before an editor finds it.** GitHub
reports this repository as created **2026-09-14**, because it was deleted and
recreated on that date. The API says so plainly
(`gh api repos/mikhaeelatefrizk/bindsight --jq .created_at`), and an editor
checking the age of the project will see that number, not the first commit. A
resubmission that does not explain it looks like an attempt to restart the
clock.

So the resubmission carries a cover note. It is not part of `paper.md` — it goes
in the submission form's comment field and, if asked, in the review thread. It
should say, in this order:

1. That the repository object was recreated on 2026-09-14 and that GitHub's
   `created_at` therefore post-dates the work by four months.
2. That the git history in the repository runs from 2026-05-09 and is
   continuous — `git log --reverse --format='%ad %s' --date=short | head -1`
   gives the first commit; the full log is the evidence of iterative
   development the criterion asks for.
3. That the tags and their dated GitHub releases, v0.1.0 through the current
   tag, are independent timestamps on that history.
4. That the rediscovery study's preprint is the "used in published or preprint
   research" instance, with its DOI. This is why the preprint goes first.
5. What changed since #10660: the four sections the bot could not find are
   written, and the manuscripts report the corrected results.

Point 4 is the one the rejection actually turned on. Without a posted study
there is nothing to answer it with, and the calendar alone will not carry a
resubmission.

---

## How to submit to JOSS

JOSS (https://joss.theoj.org) is the Journal of Open Source Software. The
review happens transparently on GitHub.

> ⛔ **Not yet.** See *Order of operations* above: the earliest defensible
> resubmission date is 2026-12-07, and it needs the study's DOI. What
> follows is the form, filled in, for when that day comes.

### The form

1. Visit https://joss.theoj.org/papers/new
2. Sign in with GitHub
3. Fill the form:
   - **Repository address:** `https://github.com/mikhaeelatefrizk/bindsight`
   - **Branch:** `main`
   - **Version:** `v0.3.6` — whatever tag the manuscripts cite, and a tag, not
     a branch. JOSS reviews what the tag points at, so a moving `main` is not a
     submission. Check it against `CITATION.cff` before typing it.
   - **Path to paper:** `paper/paper.md` — the standard path, auto-discovered;
     leave the field blank.
   - **Software archive:** **none.** This release is not archived under a DOI
     and no archive DOI can be offered. JOSS asks for one *after* review rather
     than at submission, so this is not a blocker now; when the editor asks,
     say so rather than minting a placeholder.
   - **Comments:** the cover note from *Order of operations*.
4. Submit. The editor assigns a handling editor and at least two reviewers.
   Reviewers open issues in this repository; you address them; the editor
   publishes when the criteria are met. Typical timeline once accepted into
   review: **4–8 weeks**.
5. On acceptance, JOSS publishes under its own `10.21105/joss` DOI prefix, and
   supplies a badge for the README. Take both from the acceptance, not from a
   template.

### Criteria, checked

- ✅ **Open-source licence.** `LICENSE` is the FSF AGPL-3.0 text, and GitHub's
  licence detector reads it as AGPL-3.0 today —
  `gh api repos/mikhaeelatefrizk/bindsight --jq .license.spdx_id` prints
  `AGPL-3.0`. The bot on #10660 reported `License found: Other`, but that was
  against the *previous* repository object, before it was deleted and recreated
  on 2026-09-14. Re-run that one-liner before resubmitting; if it ever prints
  `NOASSERTION` or `Other`, something has been appended to `LICENSE` that
  belongs in `LICENSING.md`, where the per-component inventory lives.
- ✅ Repository on GitHub with version-controlled history — but see the
  `created_at` note above; the history is older than the repository object.
- ✅ Tagged release.
- ✅ Documentation (README + `docs/`).
- ✅ Tests with CI (over 1,600 test functions; 9 platform/Python jobs — 3 OS ×
  Python 3.11/3.12/3.13 — plus lint, a pinned-environment job, and a wheel build)
- ✅ Docker image published to `ghcr.io` on every push to `main` and every
  release (`.github/workflows/docker.yml`). Not a JOSS criterion; listed
  because it was once claimed as green while the push was being refused. As of
  0.3.1 the package grants this repository write access and the push succeeds.
- ✅ The six sections the author guide requires — Summary, Statement of need,
  State of the field, Software design, Research impact statement, AI usage
  disclosure — in its order, inside its 750–1,750-word band;
  `tests/test_joss_paper_sections.py` holds both.
- ✅ **Evidence of iterative development** — 392 commits over five months and
  eleven tags, against the 36 commits and one release the bot saw in June.
- ⛔ **Six months of public development history** — reached 2026-11-09, but the
  resubmission guidance says six months from the rejection, so **2026-12-07**.
- ⛔ **Demonstrated research impact** — the rediscovery study, once it is posted
  and carries a DOI.

### Before resubmitting

The bot on #10660 flagged four missing sections and a word count of 945. All
four are written and the paper sits inside the band; nothing about the text is
left for submission day. One item remains, and it waits on the preprint:

- [ ] **Cite the study's preprint.** Add an entry for it to `paper.bib`, cite it
      from the *Research impact statement* in `paper.md` — a bare citation key,
      because the paper is near the top of its 1,750-word band — re-run the
      *Draft PDF (JOSS)* workflow and read the References of the PDF it builds.
      Record the DOI in `SUBMISSIONS.md` first; `tests/test_submission_record.py`
      reads it from there and will refuse the rest until it is.

---

## How to submit to Preprints.org

**The document is `validation/manuscript.md` — the study, not the methods
manuscript.** *Order of operations* above says why, and it is the whole reason
this section exists in this form. Uploading the wrong one answers nothing.

Preprints.org accepts any standard manuscript format and prefers PDF. It runs no
peer review: a screening pass by its editors, stated as "typically 24 hours …
during the working day", and then the preprint is posted with a registered DOI.
Posting is free.

Two things to know before starting. First, **posting is not reversible** — their
instructions are explicit that "once a digital object identifier (DOI) is
registered, information about the preprint is permanently available", and
indexers copy it. Second, this venue was chosen because it accepts authors with
no organizational affiliation, which is the constraint that closed bioRxiv. Their
instructions require "affiliations for all authors" on the first page, and the
MDPI convention for an author without one is to write **Independent Researcher** —
which live Preprints.org postings do use. That is evidence of practice rather than
a policy sentence: their site blocks automated reading, so it could not be quoted
here from the source. If they decline on affiliation anyway, Research Square is
the next venue to try, and the affiliation does not get softened to get past a
gate.

### Step 1 — Getting the PDF

**You do not need LaTeX or pandoc installed.**
`.github/workflows/manuscript-pdf.yml` typesets both documents on every push that
touches either of them or the shared bibliography, and on every published
release. Two places to get the study's PDF:

1. **From a workflow run** (any time) — Actions → *Manuscript PDF* → the most
   recent green run → Artifacts → **`study-manuscript`**. That is a zip
   containing `manuscript.pdf`. If nothing has changed recently, run the workflow
   by hand: Actions → *Manuscript PDF* → **Run workflow**.
2. **From the release assets** (for a tagged version) — the release page carries
   `bindsight-<tag>-validation-study.pdf` alongside the wheel, the sdist,
   `SHA256SUMS`, the methods manuscript and the JOSS paper's PDF. This is the
   copy to submit: it is the one tied to the tag.

The study is rendered by pandoc, and the job fails if the PDF comes back under
40 kB — pandoc exits 0 on a document it rendered as one blank page, so the size
floor is what makes a green run mean something. Open the PDF anyway before
uploading; its tables are the part most likely to have rewrapped badly.

### The methods manuscript's PDF

Same workflow, artifact **`methods-manuscript`**, release asset
`bindsight-<tag>-methods-manuscript.pdf`. It is not under submission anywhere —
it ships with releases as the long-form description of the software. The workflow
fails on any citation left undefined, so a green run means the references
rendered.

**Fallback — build the methods manuscript locally.** Only if CI is
unavailable, and only for the `.tex`; the study needs nothing but pandoc. You
need a TeX distribution with `biber`; install TeX Live from
https://www.tug.org/texlive/, then from the repository root:

```bash
cd paper/methods
latexmk -pdf -interaction=nonstopmode -halt-on-error manuscript.tex
```

`latexmk` runs `biber` itself. Without `latexmk`, the manual sequence is
`pdflatex manuscript`, `biber manuscript`, `pdflatex manuscript`,
`pdflatex manuscript` — twice at the end to resolve cross-references. Either
way the output is `manuscript.pdf`, which `.gitignore` keeps untracked.

> **Do not use Overleaf's "upload a zip" route, or any online compiler you feed
> a single file to.** `manuscript.tex` reads its bibliography from
> `../paper.bib` — one directory up, shared with the JOSS paper so a citation is
> fixed in one place. Upload `paper/methods/` alone and the bibliography is
> simply absent; the project still compiles, and the PDF it hands back has a
> question mark where every citation should be. If you must use one, upload
> `paper.bib` alongside and change `\addbibresource{../paper.bib}` to
> `\addbibresource{paper.bib}` in your copy — and do not commit that change.

### Step 2 — Upload to Preprints.org

1. Visit https://www.preprints.org and use **Submit**. An account is needed;
   create it yourself — this is not a step to delegate.
2. Choose the article type **Article** (a full research report, which the study
   is: abstract, methods, results, discussion, data availability).
3. **Subject:** Biology and Life Sciences → Bioinformatics. Cancer biology is a
   reasonable second.
4. Fill metadata:
   - **Title:** *Rediscovery study of bindsight: expression-based discovery of
     cell-surface antigens across fifteen TCGA cohorts*
   - **Abstract:** copy the `## Abstract` section of
     `validation/manuscript.md`. Replace any en dash or em dash with a hyphen
     before pasting — the bioRxiv form rejected a U+2014 outright, and assuming
     a form accepts the character set a Markdown file uses is how an afternoon
     disappears.
   - **Authors:** Mikhaeel Atef Rizk Wahba (single author),
     affiliation "Independent Researcher, Cairo, Egypt",
     ORCID `0009-0006-1069-9558`, email `mikhaeelatefrizk@proton.me`
   - **Keywords:** target discovery, surfaceome, RNA-seq, TCGA, differential
     expression, reproducibility
5. Upload the PDF from Step 1 as the primary file.
6. Declare:
   - **Funding:** None
   - **Competing interests:** None
   - **Data availability:** "All source code, data, and materials are
     available at https://github.com/mikhaeelatefrizk/bindsight, at the
     release tag cited in the manuscript."
7. Review and submit. Screening is stated as about 24 hours on a working day;
   the DOI is registered when the preprint posts.
8. **Record it in `SUBMISSIONS.md` the same day** — venue, date, identifier,
   status `open`. Then update the row to `posted` with the DOI when it appears.
   Everything downstream reads that file, and the four days this repository spent
   asserting a preprint that had already been declined is the reason it exists.

A preprint here does not stop a later journal submission; state the preprint and
its DOI in the cover letter.

---

## Suggested journals for follow-up submission (after the preprint)

| Journal | Fit | Format change needed |
|---|---|---|
| Bioinformatics (Oxford) | Strong fit; software paper section | Reformat to journal LaTeX template |
| Briefings in Bioinformatics | Software review section | Light reformat |
| Genome Biology | Methods section | Major rewrite (longer) |
| Nature Communications | Possible, ambitious; would need v0.2 validation results | Major rewrite + experimental validation |

**A peer-reviewed software paper plus a citable study** remains the right
combination. Which venue supplies the preprint half matters less than that the
preprint is of the study.

> **Submission history lives in [`SUBMISSIONS.md`](SUBMISSIONS.md)**, with each
> decision quoted verbatim. In short: JOSS #10660, opened and closed at
> pre-review on 2026-06-07; bioRxiv BIORXIV/2026/753186, submitted 2026-09-21 and
> declined 2026-09-25 on affiliation. Read both before touching a form. A
> resubmission is a resubmission, not a clean slate: it should reference #10660
> by number and say what changed.

---

## Once the study is posted

Do these in order. Step 1 is first because every other step's guard reads it, and
`tests/test_submission_record.py` fails the suite until it is done.

1. **Record it in [`SUBMISSIONS.md`](SUBMISSIONS.md).** Set the row's status to
   `posted` and put the real DOI in the `DOI` column. No placeholder goes in
   here, or anywhere else. A deliberately invalid archive identifier was once
   published as a real one through `CITATION.cff` and the documentation site's
   JSON-LD, and the guard that took it out is still in place. An identifier that
   cannot resolve is not a citation, and a placeholder announced as one is worse
   than none.
2. **Add the DOI to the bibliography** — an entry in `paper.bib` for the study,
   which both the JOSS paper and the methods manuscript can then cite.
3. **Cite it from `paper.md`'s *Research impact statement*** as a bare citation
   key. The paper is near the top of its 1,750-word band, so a key is what fits;
   `tests/test_joss_paper_sections.py` holds the band.
4. **Add a badge to the README** for the venue that posted it, pointing at the
   real DOI.
5. **Update `CITATION.cff`.** The study is a companion report, not the citation
   for the software, so it does not become `preferred-citation` — the repository
   and the tag stay the way to cite bindsight itself.
6. **Announce it** through the usual channels once the DOI resolves. Check that
   it resolves first.
7. **Hand the DOI to JOSS** on or after 2026-12-07. It is the "used in published
   or preprint research" instance the 2026-06-07 rejection asked for, and nothing
   else in the resubmission answers that criterion.

---

## What's intentionally NOT in either paper

To stay honest:

- **GPU half: partially executed.** This bullet described v0.1.0, when the
  GPU stages were templated notebooks that had never been run. That is no
  longer accurate. The `rfdiff_mpnn` + `boltz2` path has since been executed
  end-to-end on a free Kaggle T4, under the corrected ProteinMPNN protocol
  (the target chain held fixed, so only the binder is redesigned),
  and produced the 20 committed ERBB2 binders (best ipTM 0.88, 8/20 = 40%
  success@0.65, 95% CI 15–70% clustered over backbones — withdrawn as a
  measure of design quality; shuffles of the designs' own sequences clear it more
  often (50% against 30%), see benchmarks/calibration/README.md). The other backends (BindCraft, BoltzGen, Chai-1r, AF2-IG)
  remain mock-tested only and have still never been run on real hardware. Both
  manuscripts report this run; the sentence that used to say they predated it
  is gone with the release that made it false.
- **Rediscovery study: done (discovery half).** A companion report
  (`paper/validation/manuscript.md`, artifacts in `benchmarks/study/`) runs the
  discovery half on fifteen whole, unstratified TCGA projects as patient-paired
  contrasts, against a pre-registered panel of 22 antigen-cohort pairs. Recall at
  rank 20 is 1/17 on approved-agent antigens (95% CI 0.01-0.27); CA9 surfaces at
  rank 1 of 291 in clear-cell kidney. Most validated antigens are not
  significantly over-expressed in an unstratified bulk contrast, which the report
  states as a limit of the signal rather than of the ranking. **This supersedes an
  earlier six-cohort version whose ERBB2-at-rank-4 headline is withdrawn**: that
  breast cohort was stratified by a PAM50 call, and ERBB2 is one of the fifty
  genes that classifier is built on. The
  single-arm *designer* benchmark has since been run:
  `benchmarks/designer_benchmark/` carries 20 real Boltz-2 complexes with
  per-design metrics. The
  full three-way comparison is still pending, because BindCraft and BoltzGen
  need 24–32 GB GPUs and so require paid backends.
- **No claims of experimental validation.** Wet-lab work is out of scope
  and would require a separate paper with real biochemistry data.

The papers describe what the software *is and does*, accurately, and what
the planned validation looks like — the standard for a software-methods
manuscript.

---

## License

The manuscripts, figures, and generated results in this directory are licensed
under [CC BY 4.0](LICENSE) — reuse freely with attribution. The bindsight
software is licensed under [AGPL-3.0-or-later](../LICENSE).

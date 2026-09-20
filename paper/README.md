# Manuscripts and submission instructions

This directory holds the two manuscripts about `bindsight`, the bibliography
they share, and the validation write-up both of them cite. Both describe the
current release: `paper.md` carries its date in its front matter,
`biorxiv/manuscript.tex` names the version it presents, and
`tests/test_docs_claims.py` holds that version to `pyproject.toml`. The
repository README and CHANGELOG remain authoritative wherever they disagree
with a manuscript; the rest of this file is submission mechanics and the order
they happen in.

```
paper/
├── README.md          ← this file: what goes where, and in what order
├── LICENSE            ← CC BY 4.0, covering everything else in this directory
├── paper.md           ← JOSS software paper (standard path; JOSS
│                        auto-discovers it, so it must stay here)
├── paper.bib          ← BibTeX bibliography, shared by BOTH manuscripts
├── biorxiv/
│   └── manuscript.tex ← full bioRxiv preprint (LaTeX). Reaches the
│                        bibliography with \addbibresource{../paper.bib},
│                        which is why it cannot be zipped up on its own.
└── validation/
    └── manuscript.md  ← the fifteen-cohort rediscovery study, cited by both
```

> ℹ️ **No compiled PDF is committed.** One used to be, but it predated the
> v0.2.1 corrections and carried the wrong licence ("MIT"), a superseded
> archive DOI and the pre-correction Boltz-2 reference — a deposit hazard sitting
> in the tree. It has been removed and `.gitignore` keeps it out. CI builds the
> PDF instead; see **Getting the PDF** below.

Neither manuscript cites a software DOI. This release is not archived under a
DOI: cite the repository, the tag you ran and the checksums attached to the
release. Same author (Mikhaeel Atef Rizk Wahba, ORCID `0009-0006-1069-9558`),
same code, same evidence surface — different audiences and different review
processes.

---

## Pick one (or both)

| | **JOSS** | **bioRxiv** |
|---|---|---|
| Format | Markdown (750–1,750 words) | LaTeX (~3500 words) |
| Audience | Open-source developers + practitioners | Wider biology / bioinformatics community |
| Review | Peer-reviewed (open review on GitHub, ~4–8 weeks) | Posted as preprint (editorial check, ~48 h), peer-reviewed downstream if you submit to a journal |
| DOI | Yes, on acceptance | Yes, on submission |
| Cost | Free | Free |
| Citation strength | Strong — peer-reviewed publication | Strong — preprint, citable immediately |
| **Recommendation** | **Second**, on or after 2026-11-09. Blocked today — see below. | **First**, now. Nothing blocks it, and the DOI it returns is part of what unblocks JOSS. |

---

## Order of operations

Both, in this order, for a reason that is not about audience.

### 1. bioRxiv — now

Nothing gates it. The manuscript is written, the PDF is built by CI, and the
editorial check is a formality measured in hours. Do this first.

### 2. JOSS — on or after 2026-11-09

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

Two conditions, and the calendar decides one of them. The first commit is dated
**2026-05-09**, so six months of public development history is reached on
**2026-11-09**. Do not resubmit before that date; a second rejection on the same
ground is worse than waiting.

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
4. That the bioRxiv preprint is the "used in published or preprint research"
   instance, with its DOI. This is why bioRxiv goes first.
5. What changed since #10660: the four sections the bot could not find are
   written, and the manuscripts report the corrected results.

Point 4 is the one the rejection actually turned on. Without a preprint there is
nothing to answer it with, and the calendar alone will not carry a resubmission.

---

## How to submit to JOSS

JOSS (https://joss.theoj.org) is the Journal of Open Source Software. The
review happens transparently on GitHub.

> ⛔ **Not yet.** See *Order of operations* above: the earliest defensible
> resubmission date is 2026-11-09, and it needs the bioRxiv DOI in hand. What
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
5. On acceptance, JOSS publishes with its own DOI (e.g. `10.21105/joss.NNNNN`)
   and a badge for the README.

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
- ⛔ **Six months of public development history** — 2026-05-09 + 6 months =
  2026-11-09.
- ⛔ **One instance of use in published or preprint research** — the bioRxiv
  preprint, once it has a DOI.

### Before resubmitting

The bot on #10660 flagged four missing sections and a word count of 945. All
four are written and the paper sits inside the band; nothing about the text is
left for submission day. One item remains, and it cannot be done before
bioRxiv answers:

- [ ] **Insert the bioRxiv DOI.** Add an entry for the preprint to `paper.bib`,
      cite it from the *Research impact statement* in `paper.md`, re-run the
      *Draft PDF (JOSS)* workflow and read the References of the PDF it builds.

---

## How to submit to bioRxiv

bioRxiv (https://www.biorxiv.org) accepts preprints in any standard
scientific manuscript format. They prefer PDF.

### Step 1 — Getting the PDF

**You do not need LaTeX installed.** `.github/workflows/manuscript-pdf.yml`
compiles `biorxiv/manuscript.tex` on every push that touches it or the shared
bibliography, and on every published release. Two places to get the file:

1. **From a workflow run** (any time) — Actions → *Manuscript PDF (bioRxiv)* →
   the most recent green run → Artifacts → **`biorxiv-manuscript`**. That is a
   zip containing `manuscript.pdf`. If the manuscript has not changed recently,
   run the workflow by hand: Actions → *Manuscript PDF (bioRxiv)* → **Run
   workflow**.
2. **From the release assets** (for a tagged version) — the release page for
   the tag the manuscript cites carries
   `bindsight-<tag>-biorxiv-manuscript.pdf` alongside the wheel, the sdist,
   `SHA256SUMS` and the JOSS paper's PDF. This is the copy to submit: it is
   the one tied to the tag.

The workflow fails on any citation left undefined, so a green run means the
references rendered. Open the References section anyway before uploading.

**Fallback — build it locally.** Only if CI is unavailable. You need a TeX
distribution with `biber`; install TeX Live from https://www.tug.org/texlive/,
then from the repository root:

```bash
cd paper/biorxiv
latexmk -pdf -interaction=nonstopmode -halt-on-error manuscript.tex
```

`latexmk` runs `biber` itself. Without `latexmk`, the manual sequence is
`pdflatex manuscript`, `biber manuscript`, `pdflatex manuscript`,
`pdflatex manuscript` — twice at the end to resolve cross-references. Either
way the output is `manuscript.pdf`, which `.gitignore` keeps untracked.

> **Do not use Overleaf's "upload a zip" route, or any online compiler you feed
> a single file to.** `manuscript.tex` reads its bibliography from
> `../paper.bib` — one directory up, shared with the JOSS paper so a citation is
> fixed in one place. Upload `paper/biorxiv/` alone and the bibliography is
> simply absent; the project still compiles, and the PDF it hands back has a
> question mark where every citation should be. If you must use one, upload
> `paper.bib` alongside and change `\addbibresource{../paper.bib}` to
> `\addbibresource{paper.bib}` in your copy — and do not commit that change.

### Step 2 — Upload to bioRxiv

1. Visit https://www.biorxiv.org/submit-a-manuscript
2. Sign in (or create an account)
3. Choose "New manuscript"
4. Fill metadata:
   - **Type:** "New Results" (for a software/methods paper) or "Methods"
   - **Subject:** "Bioinformatics" (primary), "Synthetic Biology"
     (secondary)
   - **Title:** *bindsight: a reproducible bridge from RNA-seq counts to
     de novo protein binder design*
   - **Abstract:** copy from manuscript.tex (the `\begin{abstract}` block)
   - **Authors:** Mikhaeel Atef Rizk Wahba (single author),
     affiliation "Independent Researcher, Cairo, Egypt",
     ORCID `0009-0006-1069-9558`, email `mikhaeelatefrizk@proton.me`
5. Upload the PDF from Step 1 as the primary file
6. Optional: add the LaTeX source as supplementary
7. Declare:
   - **Funding:** None
   - **Competing interests:** None
   - **Data availability:** "All source code, data, and materials are
     available at https://github.com/mikhaeelatefrizk/bindsight, at the
     release tag cited in the manuscript."
8. Review and submit. bioRxiv editors do an initial check (typically
   within 48 hours) and assign a DOI like `10.1101/2026.MM.DD.NNNNNN`.

After bioRxiv acceptance you can later submit the same manuscript to a
peer-reviewed journal — bioRxiv linking is automatic.

---

## Suggested journals for follow-up submission (after bioRxiv)

| Journal | Fit | Format change needed |
|---|---|---|
| Bioinformatics (Oxford) | Strong fit; software paper section | Reformat to journal LaTeX template |
| Briefings in Bioinformatics | Software review section | Light reformat |
| Genome Biology | Methods section | Major rewrite (longer) |
| Nature Communications | Possible, ambitious; would need v0.2 validation results | Major rewrite + experimental validation |

**JOSS + bioRxiv** remains the right combination.

> **Submission history.** One JOSS submission, #10660, opened and closed on
> 2026-06-07 at pre-review with no editor assigned. The editor's reason and what
> it requires are quoted in full under *Order of operations* above — read that
> before touching the form. A resubmission is a resubmission, not a clean
> slate: it should reference #10660 by number and say what changed.

---

## After your preprint is up

1. **Add the bioRxiv DOI** to the README:
   ```markdown
   [![bioRxiv](https://img.shields.io/badge/bioRxiv-10.1101%2FYOURDOI-red.svg)](https://doi.org/10.1101/YOURDOI)
   ```
2. **Update CITATION.cff** to include the preprint as the preferred
   citation:
   ```yaml
   preferred-citation:
     type: article
     title: "bindsight: a reproducible bridge from RNA-seq counts..."
     authors: ...
     doi: 10.1101/YOURDOI
     journal: bioRxiv
     year: 2026
   ```
3. **Announce the preprint** through the usual channels (lab page, mailing
   lists, social media) once the DOI is live.
4. **Hand the DOI to JOSS.** It is the "used in published or preprint research"
   instance the 2026-06-07 rejection asked for. Nothing else in the resubmission
   answers that criterion.

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

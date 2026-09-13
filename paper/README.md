# Manuscripts and submission instructions

This directory contains two academic manuscripts about `bindsight`. They were
drafted for v0.1.0 and have not been rewritten for the current release, so
treat the prose here as submission *mechanics* rather than an up-to-date
description of the software; the README and CHANGELOG are authoritative for
what bindsight currently does.

```
paper/
├── paper.md           ← JOSS-style ~1000-word software paper (standard path)
├── paper.bib          ← BibTeX bibliography (for JOSS)
└── biorxiv/
    ├── manuscript.tex ← Full bioRxiv preprint (LaTeX)
    (bibliography: ../paper.bib, shared with the JOSS paper via \addbibresource)
```

> ℹ️ **No compiled PDF is committed.** One used to be, but it predated the
> v0.2.1 corrections and carried the wrong licence ("MIT"), a superseded Zenodo
> version DOI and the pre-correction Boltz-2 reference — a deposit hazard sitting
> in the tree. It has been removed. Compile a fresh one from `manuscript.tex`
> (Step 1 below) at submission time, and do not commit the output.

Both cite the software by its Zenodo **concept DOI** `10.5281/zenodo.20121495`,
which always resolves to the latest archived version — the right thing to cite
for "the software"; use a version DOI only to pin an exact release.
Same author (Mikhaeel Atef Rizk Wahba, ORCID `0009-0006-1069-9558`). Same code
and demo. Different audiences and review processes.

---

## Pick one (or both)

| | **JOSS** | **bioRxiv** |
|---|---|---|
| Format | Markdown (~1000 words) | LaTeX (~3500 words) |
| Audience | Open-source developers + practitioners | Wider biology / bioinformatics community |
| Review | Peer-reviewed (open review on GitHub, ~4–8 weeks) | Posted as preprint (editorial check, ~48 h), peer-reviewed downstream if you submit to a journal |
| DOI | Yes, on acceptance | Yes, on submission |
| Cost | Free | Free |
| Citation strength | Strong — peer-reviewed publication | Strong — preprint, citable immediately |
| **Recommendation** | **Submit both.** They cover different audiences and don't compete. |

---

## How to submit to JOSS

JOSS (https://joss.theoj.org) is the Journal of Open Source Software. The
review happens transparently on GitHub.

### Steps

1. Visit https://joss.theoj.org/papers/new
2. Sign in with GitHub
3. Fill the form:
   - **Repository address:** `https://github.com/mikhaeelatefrizk/bindsight`
   - **Branch:** `main`
   - **Version:** the current tagged release (`v0.2.2` at time of writing)
   - **Path to paper:** `paper/paper.md` (JOSS bot auto-discovers this standard path; no need to specify)
   - **Software archive:** `https://doi.org/10.5281/zenodo.20121495`
4. Submit. The JOSS editor assigns a handling editor and at least two
   reviewers. Reviewers open issues in your GitHub repo with comments;
   you address them; the editor publishes when the criteria are met.
   Typical timeline: **4–8 weeks**.
5. On acceptance, JOSS publishes the paper with its own DOI (e.g.,
   `10.21105/joss.NNNNN`) and adds a "JOSS" badge you can put on your
   README.

JOSS submission criteria (already met):
- ✅ Open-source license (AGPL-3.0-or-later, OSI-approved)
- ✅ Repository on GitHub with version-controlled history
- ✅ Tagged release
- ✅ Documentation (README + `docs/`)
- ✅ Tests with CI (over 1000 tests; 6 platform/Python jobs — 3 OS × Python 3.11/3.12 — plus lint, build and docker)
- ✅ Statement of need in `paper.md`

---

## How to submit to bioRxiv

bioRxiv (https://www.biorxiv.org) accepts preprints in any standard
scientific manuscript format. They prefer PDF.

### Step 1 — Compile the LaTeX to PDF

You need a LaTeX distribution with `biber` for the bibliography. The most
common options on Windows:

**Option A — TeX Live (recommended, full distribution).** Install from
https://www.tug.org/texlive/, then:

```bash
cd paper/biorxiv
pdflatex manuscript.tex
biber manuscript
pdflatex manuscript.tex
pdflatex manuscript.tex   # twice to resolve cross-references
```

This produces `manuscript.pdf`.

**Option B — Overleaf (zero local install).** Visit https://overleaf.com,
click "New project" → "Upload project", upload the entire `paper/biorxiv/`
directory as a zip. Overleaf detects the project, compiles it, and
gives you a downloadable PDF in 30 seconds.

**Option C — Online compiler.** TeXfiddle (https://texfiddle.com) or any
LaTeX online compiler. Upload `manuscript.tex` and a copy of `../paper.bib`
(rename it `paper.bib` and change the `\addbibresource` path to match, or keep
the directory layout),
compile.

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
   - **Authors:** Mikhaeel Atef Rizk Wahba (single author), affiliation
     "Independent Researcher, Cairo, Egypt", ORCID
     `0009-0006-1069-9558`, email `mikhaeelatefrizk@proton.me`
5. Upload `manuscript.pdf` as the primary file
6. Optional: add the LaTeX source as supplementary
7. Declare:
   - **Funding:** None
   - **Competing interests:** None
   - **Data availability:** "All source code, data, and materials are
     available at https://github.com/mikhaeelatefrizk/bindsight and
     archived at Zenodo (concept DOI 10.5281/zenodo.20121495)."
8. Review and submit. bioRxiv editors do an initial check (typically
   within 48 hours) and assign a DOI like `10.1101/2026.05.11.NNNNNN`.

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

> **Submission history.** A JOSS submission was opened on 2026-06-07
> (openjournals/joss-reviews#10660) and closed the same day at pre-review,
> labelled `rejected`, with no editor assigned. Any resubmission should treat
> that as the starting point rather than assuming a clean slate, and should
> begin by rewriting `paper.md`, which still describes v0.1.0.

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

---

## What's intentionally NOT in either paper

To stay honest:

- **GPU half: partially executed.** This bullet described v0.1.0, when the
  GPU stages were templated notebooks that had never been run. That is no
  longer accurate. The `rfdiff_mpnn` + `boltz2` path has since been executed
  end-to-end on a free Kaggle T4, under the corrected ProteinMPNN protocol,
  and produced the 20 committed ERBB2 binders (best ipTM 0.88, 40%
  success@0.65 — withdrawn as a measure of design quality; shuffles of the
  designs' own sequences clear it at the same rate, see
  benchmarks/calibration/README.md). The other backends (BindCraft, BoltzGen, Chai-1r, AF2-IG)
  remain mock-tested only and have still never been run on real hardware. The
  manuscripts in this directory were written before that run and understate
  what has been executed.
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
  single-arm *designer* benchmark has since been run: `benchmarks/designer_
  benchmark/` carries 20 real Boltz-2 complexes with per-design metrics. The
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

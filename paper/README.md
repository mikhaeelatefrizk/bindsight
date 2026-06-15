# Manuscripts and submission instructions

This directory contains two ready-to-submit academic manuscripts about
`bindsight` v0.1.0:

```
paper/
├── paper.md           ← JOSS-style ~1000-word software paper (standard path)
├── paper.bib          ← BibTeX bibliography (for JOSS)
└── biorxiv/
    ├── manuscript.tex ← Full bioRxiv preprint (LaTeX)
    ├── manuscript.pdf ← Compiled (7 pages, 322 KB) — ready for direct upload
    └── references.bib ← BibTeX bibliography (same content + a few extras)
```

Both target the same v0.1.0 release (Zenodo DOI `10.5281/zenodo.20121496`).
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
   - **Version:** `v0.1.0`
   - **Path to paper:** `paper/paper.md` (JOSS bot auto-discovers this standard path; no need to specify)
   - **Software archive:** `https://doi.org/10.5281/zenodo.20121496`
4. Submit. The JOSS editor assigns a handling editor and at least two
   reviewers. Reviewers open issues in your GitHub repo with comments;
   you address them; the editor publishes when the criteria are met.
   Typical timeline: **4–8 weeks**.
5. On acceptance, JOSS publishes the paper with its own DOI (e.g.,
   `10.21105/joss.NNNNN`) and adds a "JOSS" badge you can put on your
   README.

JOSS submission criteria (already met):
- ✅ Open-source license (MIT)
- ✅ Repository on GitHub with version-controlled history
- ✅ Tagged release
- ✅ Documentation (README + `docs/`)
- ✅ Tests with CI (175 tests, 8 platform/Python jobs)
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
LaTeX online compiler. Upload `manuscript.tex` and `references.bib`,
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
     archived at Zenodo (DOI 10.5281/zenodo.20121496)."
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

For v0.1.0, **JOSS + bioRxiv** is the right combination.

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

- **No GPU half results.** The v0.1.0 release ships the GPU stages as
  templated Colab notebooks following canonical upstream patterns
  (ColabDesign, dl_binder_design); the author has not personally smoke-
  tested them on a real GPU. The papers describe the design and explicitly
  flag this in the Discussion as the limitation that v0.2 will close.
- **Rediscovery validation: done (discovery half).** A companion report
  (`paper/validation/manuscript.md`, artifacts in `benchmarks/validation/`)
  runs the discovery half on six real indication-matched TCGA cohorts: ERBB2
  is rediscovered at rank 4 in HER2-enriched breast (PAM50-stratified), with
  confirmed specificity (EGFR/CEA correctly not surfaced). The three-way
  *designer* benchmark is GPU-only; a runnable, CPU-tested harness + protocol
  ship in `benchmarks/designer_benchmark/`, pending a GPU run.
- **No claims of experimental validation.** Wet-lab work is out of scope
  and would require a separate paper with real biochemistry data.

The papers describe what the software *is and does*, accurately, and what
the planned validation looks like — the standard for a software-methods
manuscript.

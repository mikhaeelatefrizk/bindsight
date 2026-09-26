<!-- SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->

# Submission record

Every venue this work has been offered to, what came back, and in the venue's
own words. This file is the **single source of truth for submission state**:
`tests/test_submission_record.py` reads the table below and refuses to let any
other document in the repository claim a preprint exists, is imminent, or has a
DOI, while the table says otherwise.

That guard exists because the claims did drift. Between 2026-09-21 and
2026-09-25 this repository asserted in two dozen places that a bioRxiv preprint
was hours away, then that it was in hand, and those sentences outlived the
submission by four days. An identifier that cannot resolve is not a citation,
and a submission announced as pending after it was declined is the same mistake
in a different tense.

## The record

Statuses: `open` (submitted, no decision), `posted` (live, citable),
`rejected`/`declined` (closed by the venue), `withdrawn` (closed by the author).
A `DOI` of `none` means no identifier was ever minted — not that one is pending.

| Venue | Document | Submitted | Identifier | Status | DOI |
|---|---|---|---|---|---|
| JOSS | `paper/paper.md` | 2026-06-07 | [openjournals/joss-reviews#10660](https://github.com/openjournals/joss-reviews/issues/10660) | rejected | none |
| bioRxiv | `paper/methods/manuscript.tex` | 2026-09-21 | BIORXIV/2026/753186 | declined | none |

**No preprint of this work is posted anywhere, and no DOI has been minted for
it.** The software itself is also not archived under a DOI; cite the repository,
the tag you ran, and the checksums attached to the release.

## JOSS, 2026-06-07 — rejected at pre-review

Submitted as `v0.1.0`. Closed the same day, no editor assigned, labelled
`rejected`. The Editor-in-Chief's reason, verbatim
([comment](https://github.com/openjournals/joss-reviews/issues/10660#issuecomment-4641938239)):

> The repository is less than one month old, with no research applications of
> the software documented. JOSS requires a public development history of at
> least six months, with evidence of iterative development, and at minimum one
> instance of the software being used in published or preprint research. A web
> demonstration does not satisfy this requirement. We'd welcome a resubmission
> once the software has a longer development history and has been applied in
> actual research.

Two conditions. The development-history one has since been met on the merits —
the repository now holds 392 commits across five months and eleven tags, against
the 36 commits and one release the editorial bot saw that day. The research-use
one is what `paper/README.md` now plans around.

## bioRxiv, 2026-09-21 — declined, 2026-09-25

Submitted as BIORXIV/2026/753186. Declined without going to the affiliation
check's alternative, verbatim:

> Thank you for submitting your manuscript to bioRxiv. We regret to inform you
> that your manuscript cannot be considered for bioRxiv because bioRxiv requires
> authors to have an organizational affiliation. It is necessary for submissions
> to be associated with an organization that provides oversight of research
> activities so that it can adjudicate any ethical issues/disputes that arise.

The author is an independent researcher with no organizational affiliation, and
bioRxiv polices misrepresentation of affiliation explicitly. There is no version
of this submission that succeeds. bioRxiv and medRxiv — the same organization,
the same rule — are closed to this work, not delayed, and the repository should
not describe them as pending.

## What this changes

`paper/README.md` carries the plan that replaces it: which document goes out,
where, and why that venue. In short — the document that needs a DOI is the
fifteen-cohort rediscovery study, not the methods manuscript, because JOSS's
criterion asks for the software *used in* research rather than described by it.

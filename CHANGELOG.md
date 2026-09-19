# Changelog

All notable changes to `bindsight` are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.3.3] - 2026-09-20

Everything here is a defect in 0.3.2, most of it introduced by the demo work
that release shipped. That work went out without an adversarial pass; this is
the pass, and what it found.

### Fixed — a filename was markup, on a page anyone can be handed a file for

`your_data_check.js` built its verdict cards by concatenating strings and
assigned the result to `innerHTML`. Every interpolated value came from the
reader's own files: the two filenames, the counts-matrix column headers, and
the design-table cell values read as contrast levels. That was tolerable while
the page only ran on `localhost`. Publishing it at `docs/try-your-data.md` in
0.3.2 turned "a filename is whatever someone typed" into script execution in
the documentation origin, reachable by handing a collaborator a `.tsv`.

Escaping on the way in was considered and rejected. The levels were built into
`<option value="..">`, where a value of `" onmouseover=".." escapes the
attribute without using a single angle bracket, so a helper handling `<`, `>`
and `&` would not have caught it — and no reader of a call site can tell which
context an interpolation lands in. `charts.js` had the same shape in its
tooltips, fed by gene symbols out of the user's counts matrix and served by
`bindsight ui`.

Both now compose DOM nodes and set `textContent`. The rule that replaces care
is mechanical, because care is what produced the bug: `innerHTML` is only ever
assigned `""`, and a test sweeps every authored script under `report/web/` and
fails anything else. Its positive controls are the real pre-fix lines taken
from git rather than synthetic samples. Verified in a browser with a payload in
all three contexts — filename, TSV header, and a level crafted to break out of
the option attribute: no element is created from any of them.

### Fixed — `pip install bindsight` produced a command that could not start

`cli.py` read `DEFAULT_KS` from `bindsight.benchmark.core`, which imports
pandas at module scope. The value is needed at *import* time — it is
interpolated into the `--k` help string, which Click evaluates when the command
is defined — so the import ran on every invocation. pandas is declared under
the `discover` extra, not in `dependencies`, so a bare install raised
`ModuleNotFoundError` before `bindsight --version` could print. Every
documented first step began with an install that produced a broken command.

No CI job could see it: all of them install `.[dev,discover,report]`.

The constant moved to `bindsight/benchmark/defaults.py`, which is stdlib-only,
and `bindsight.benchmark` now resolves its scoring API through a PEP 562
`__getattr__` the way `bindsight.report` already did — the package `__init__`
was eagerly importing `core`, so reaching any submodule pulled pandas in
regardless. Proved on the built wheel in a clean virtualenv with no extras:
`--version`, `--help`, all twelve subcommand helps, and `bindsight doctor` run
with pandas genuinely absent.

### Fixed — the structure budget was a floor, and a large complex cost the small ones

`if spent + cost > budget and embedded: break` carried three defects.

`and embedded` made the documented ceiling a floor: the first structure was
embedded whatever its size, so a single oversized complex produced a report
larger than the budget that exists to keep it sendable. "Up to
`_STRUCTURE_BUDGET_BYTES`" was false in exactly the case the budget is for.
Measured before the fix, a 1 KiB budget embedded 51,200 bytes.

`break` charged every lower-ranked complex for that one: a 5 KiB structure was
dropped because a 50 KiB structure outranked it, with room to spare. It now
skips and keeps going, so the embedded set is the best-ranked ones that *fit*.

Honouring the budget strictly made a case reachable that the floor had hidden —
nothing fits — and the whole section sat inside `{% if structure_ids %}`, so it
would have vanished without a heading, an explanation, or a pointer to where
the structures went. It now says so and names the directory.

### Fixed — four documented commands exited before doing anything

`docs/how-to-use.md` told a reader to run `bindsight report --format web`,
which exits with `Error: Missing argument 'RUN_DIR'`. Also: a plugin selected
with a top-level `--designer` that exists only on `design` and `run`; a
teaching syllabus whose `bindsight design --backend colab` names no run
directory; and the designer-benchmark page passing a discovery config straight
to `design`, whose positional argument must be an existing directory. Each was
confirmed by invoking Click, not by reading.

Nothing guarded this class — the existing documentation sweep covers `python`,
`bash` and `sh` invocations, and the console script itself, which is most of
what the documentation tells people to type, fell outside it. Every
`bindsight …` line in every tracked Markdown file is now validated against
Click's own introspection: subcommand exists, every flag exists on it, required
arguments and required options present.

### Fixed — the site's own labels failed the contrast rule the app is held to

`--bs-muted` was `#6c757d`: 4.08:1 on `--bs-navy-tint` and 4.45:1 on
`--bs-canvas`, against WCAG AA's 4.5:1. `.bs-stat .k` is the label under each
headline number and `.bs-flow .s small` the caption under each pipeline stage,
both at well under 18.7px — so on the published site the words naming the
numbers sat below the threshold while the numbers stayed crisp. That is the
same defect `tests/test_contrast.py` was written for, reproduced because the
sweep read one stylesheet and the palette had since become two. Now `#5f6873`,
and the sweep covers `docs/stylesheets/extra.css` as well.

### Fixed — a responsive rule that could never apply

`.bs-viewer` was 26rem at every width. On a phone in portrait that is 520px —
mkdocs-material sets the root font to 125% — which pushed the design picker and
the chain legend below the fold, the two things that say what is being looked
at. The narrow-viewport override was first written *above* the rule it
overrides; equal specificity means source order decides, so it did nothing, and
every static gate passed on it. Caught in a browser, then made catchable: a
declaration inside `@media` that the same selector overrides unconditionally
further down the file is now a test failure.

### Added — the interface says what it is doing to a screen reader

`#checks`, where the data checker writes its verdict, gains `aria-live`: results
appeared without the focus moving, so a screen-reader user was told nothing had
happened. The 3-D viewer's fallbacks gain `role="alert"` — the static ones in
the report, the evidence page and the generated results page, and the two the
viewer builds at runtime, which replace a fallback the reader was already given.

### Changed — a privacy promise scoped to what it can keep

`docs/try-your-data.md` said the page "makes no network request of any kind".
That is true of the checker and false of the MkDocs page around it, which
fetches a web font like every other page on the site. The promise that matters
— no upload, no form action, your data never part of any request — is now what
it says, and the font is named rather than glossed over.

---

## [0.3.2] - 2026-09-19

### Added — the demo runs on the documentation site, with no server and no secret

The hosted Hugging Face Space serves a blank page titled "Streamlit" and cannot
be rebuilt without a secret only the repository owner can create. Meanwhile
`docs/results.md` promised the twenty predicted complexes and then told the
reader to install something — a promise that was a redirect, and before that a
redirect to a hosted build this repository cannot keep running on its own.

Nothing new was needed to fix that. 3Dmol.js was already vendored rather than
fetched from a CDN, the twenty complexes were already committed as mmCIF,
`showcase.py` was already stdlib-only and reading only committed files, and the
Evidence page's sole dependence on the server was one line —
`fetch("/api/structure/" + id)`. So the published page draws them now, from
files served beside it.

- The viewer is authored once, at `bindsight/report/web/static/binder_viewer.js`,
  and loaded by three surfaces: `bindsight ui`, the documentation site, and the
  self-contained HTML report. Copies of a viewer diverge, and the copy nobody is
  looking at is the one that drifts. What differs between the three is only
  where a structure comes from, and that is read off the host element rather
  than branched on by surface. A test asserts the viewer's own markers appear in
  no template and in no generator.
- Every URL resolves against the script's own location rather than the page's,
  which is what lets one file work under `mkdocs serve` at `/`, under Pages at
  `/bindsight/`, and in the app unchanged, with nothing encoding a site root.
  The boot subscribes to mkdocs-material's `document$` as well as
  `DOMContentLoaded`: `navigation.instant` is on, and without it a reader
  arriving from another docs page would find an inert picker and an empty box.
- The picker names the designs and not their scores. It was going to show ipTM
  beside each id until the withdrawn-figure guard caught it: 0.84 is a withdrawn
  figure, and a control listing twenty scores on one line cannot keep a
  retraction within a paragraph of the twentieth. The numbers stay in the table,
  where their caveat is.
- The counts and design checker is published too, at `Try your data`. It was
  already pure client-side — no fetch, no XHR, no form action — so it needed
  nothing but a page to live on, and its promise that nothing is uploaded is
  more load-bearing on a public site than it ever was on localhost. Verified on
  the built site by feeding it a counts matrix and a design table with `fetch`
  and `XMLHttpRequest.open` both instrumented: it found the two-level factor,
  matched four of four sample names, and made zero network calls.
- The copied structures are byte-identical to the originals, so git — being
  content-addressed — stores one blob for both. Measured: the pack was 7.17 MiB
  before the commit and 7.17 MiB after, for 2.8 MB of new working-tree files.
  The tests assert that identity, which is the thing that makes it true.

### Added — the HTML report draws its complexes, and is still one file

`bindsight/report/html.py` excluded 3-D viewing on the grounds that "a structure
viewer needs a script from a CDN and that would break self-containment". That
was never true here: the viewer is vendored into the package, and CDN-fetching
was rejected project-wide long ago. A false reason outlives the thing it was
invented for.

The real constraint is size, and it is a budget now rather than an exclusion:
structures are embedded best-ranked first within `_STRUCTURE_BUDGET_BYTES`, and
the report states in its own text how many it left out and where the rest are. A
report that silently showed three of twenty would be this project's own defect
class wearing a size limit as an excuse. On the committed provenance-join run
that is 4.79 MB with the complexes and 146 kB with `--no-embed-structures`, 23
of 40 embedded and the other 17 named, with zero external references either way.

The embedded JSON is escaped so a structure cannot close the `<script>` element
carrying it. mmCIF has no reason to contain that sequence, which is exactly when
an assumption like that stops being checked; a test feeds it one anyway.

### Fixed — a drift check that could not see a new file

The `pinned` job regenerated the published pages and ran `git diff --exit-code`
over them. `git diff` does not see untracked files, which did not matter while
the generator only overwrote two existing PNGs. With twenty per-design assets it
would: a re-run producing a new design would write an uncommitted `.cif`, the
page would offer it, the gate would stay green, and the published site would 404
on the one structure nobody had committed. The pathspec is the whole
`docs/assets` directory now — a list stops covering what is added after it — and
`git status --porcelain --untracked-files=all` runs beside the diff.

Two sweeps in `tests/test_web_ui.py` read only `.j2` and would have gone quietly
blind the moment the scripts moved out of the templates: the
unreferenced-vendored-asset scan and the tautology scan. Both read `.js` now,
excluding `vendor/`, which is not this project's code to answer for.


### Removed — the archive, and the identifier that was standing in for one

Zenodo is gone: `.zenodo.json`, `.github/workflows/zenodo.yml`,
`scripts/zenodo_deposit.py`, `scripts/set_doi.py` and the tests that held
them — 1,398 lines, and the entry that used to sit here announcing the first
three of them.

It could not be repaired from inside this repository. Zenodo keys repositories
by GitHub id, and the recreation on 2026-09-14 left it holding the previous
object under this name: it answers HTTP 403 to enabling the new one, and
answered the v0.3.1 release with "The repository does not exist". The deposit
script written last week was the way around that, and it was a good way around
it, but it needed a `ZENODO_TOKEN` that had to exist before any citation in the
tree resolved — so the tree's correctness was waiting on a setting outside it,
which is the shape of every other failure in the 0.3.1 entry below.

What the placeholder was actually doing while it waited is the part worth
recording. `10.5281/zenodo.PENDING` is deliberately invalid, and it was being
published as though it were not. GitHub's "Cite this repository" button reads
`CITATION.cff`'s `doi` key, so it went into readers' bibliographies as a 404;
`codemeta.json` published it to software indexers; the JSON-LD in
`overrides/main.html` published it as `sameAs` on every page of the
documentation site. Nine documents carried it and exactly one — the README —
said it was a placeholder. The other eight said the software **is archived**,
among them a manuscript abstract and the block of text `paper/README.md`
instructs the author to paste verbatim into a submission form.

No test failed, because the guard asserted that every file named the *same*
DOI. A placeholder satisfies that perfectly. Agreement was the wrong property
to check when the value agreed upon could not resolve.

A release is now identified by what this repository can actually produce: its
tag, the SHA-256 checksums published beside its wheel and sdist, the
digest-pinned container image, and the PROV-O manifest inside every run. There
is no DOI, and no document claims one.

Three things were deliberately **not** removed:

- **Forty DOIs belonging to other people.** PyDESeq2, DESeq2, edgeR, AlphaFold,
  RFdiffusion, ProteinMPNN, Boltz-2, SURFY, SURFACE-Bind, Snakemake, Open
  Targets, and the clinical trials behind `benchmarks/binders.tsv`. One of them
  is written into the provenance manifest of every run. A sweep for "DOI" that
  could be satisfied by deleting these would be pointed at the wrong thing, so
  `tests/test_no_zenodo.py` asserts they are still there — it fails in both
  directions.
- **The RO-Crate exporter.** It names no service now, but a run bundle is still
  built for deposit; where the depositor puts it is their choice.
- **This file's history.** The Zenodo episode is in the entries below and stays
  there. Deleting the word would falsify the record rather than correct it.

The records already published cannot be removed by anyone here — Zenodo records
are permanent by design — so five of them go on resolving to releases through
v0.2.2. This repository is simply silent about them.

### Fixed — a citation that would have rendered its own brackets

`bindsight.report.theme.citation_line` returned a *Markdown* link, and its one
consumer interpolates into HTML under Jinja's autoescape with no Markdown
filter, so the "Citing this" paragraph would have shown the brackets to every
visitor. It never did: the identifier was a placeholder, the placeholder branch
returned prose, and the branch that built the Markdown never ran. The test of
that paragraph was itself written as `if theme.DOI_IS_PENDING:` — so it would
have stopped running at the exact moment the defect started rendering. A flag
guarding both the bug and its test is a bug with no way to be found.

The function returns text, the template makes the link, and the test is
unconditional and checks for a literal `](`. The `doi_pending` value passed
into the template globals, which no template ever read, is gone with it.

### Fixed — ten documents said the hosted demo runs; two said it does not

The Hugging Face Space serves a blank page titled "Streamlit", the framework
the interface release deleted, and has since that release: `sync-hf-space.yml`
skips every step and reports success until an `HF_TOKEN` secret exists.

This was never unknown. The 0.3.1 entry below says the demo is not restored,
and `report/showcase.py` says the Space does not deploy the full repository.
Meanwhile a manuscript abstract said a public web demo "runs the full discovery
pipeline in any browser", and the documentation home page made "Try it live"
its primary button — the first thing a visitor clicks, landing on the blank
page. The true sentence existed twice and the false one ten times, which is a
propagation failure, not a gap in what anyone knew.

Every document now names the Space as an address rather than a promise, wording
that stays true once it is rebuilt, so none of it has to be un-written. The one
exception is that button, which is read after it is clicked and so cannot be
hedged: it points at the results page until the Space serves this build.
`theme.HF_SPACE_IS_SERVING_THIS_BUILD` records which of those two worlds we are
in, and `tests/test_hosted_demo_claims.py` holds it to the workflow in both
directions — it cannot be flipped early, and it cannot be forgotten late.

One claim was false regardless of any rebuild: the manuscript said a first
visitor's analysis "is cached for subsequent visitors". Only the GDC download
is cached, to disk, for a second run on the same container.

### Fixed — the one page that quoted a p-value without its denominator

The permuted-indication test reports p = 3.97e-04 over 5,040 orderings, and it
covers 7 of the 22 antigen-cohort pairs: those with a single indication, since
the test assigns one cohort per antigen and an antigen licensed in several
cancers has no single correct one to permute. The README, `what-is-bindsight.md`
and the study's own `RESULTS.md` all say so beside the number. `docs/results.md`
did not — and there the number sits two paragraphs under the decoy null's "Of
22 pairs", so the narrower denominator read as the same one. That page is the
one `docs/index.md` sends readers to for the headline figures.

The count was already in the study's output and already rendered by
`study_report.py`; `scripts/build_docs_results.py` was the one renderer not
reading it. It reads it now, so the denominator is generated rather than
written, and the page states it in the same bullet list as the p-value.

## [0.3.1] - 2026-09-18

A release that exists so that the archive has something to hold, carrying
the seventeen commits made after v0.3.0 was tagged.

This repository was recreated on GitHub on 2026-09-14. A new repository
object keeps the history and none of the settings: the Zenodo integration,
the `ghcr.io` package's access list, every secret and every variable. Three
publication channels stalled on that, and each reported it differently. The
container workflow went red on every push until it was taught to say why and
pass; the Space sync skips every step without a token and reports success;
and the archive has no workflow at all, so v0.3.0 — published 2026-09-17 and
described in its own entry below as "deposited under a new Zenodo concept
DOI" — was never deposited anywhere. `10.5281/zenodo.20121495` still resolved
to v0.2.2. Nothing in the tree could have said so: a deposit is a side effect
of a GitHub event that a setting outside the tree decides whether to forward.

### Changed — the archive is re-established

- The GitHub–Zenodo integration could not be re-enabled for the recreated
  repository, and this bullet said it had been. Zenodo keeps repositories by
  GitHub id, still holds the previous object under this name, answered the
  enable request with HTTP 403 and this release's webhook with "The
  repository does not exist". The archive is made by this repository instead
  — see the entry above — and the lineage is as this bullet intended: a new
  concept DOI rather than an extension of the one v0.1.0–v0.2.2 sit under.
  `.zenodo.json` declares that the new lineage `continues`
  `10.5281/zenodo.20121495`, so the record points back; the old record is not
  edited and does not point forward. The DOI-agreement guard reads that
  declaration as a reference to another record, not as a second concept DOI,
  and a test holds it to that.
- A DOI does not exist until the deposit that mints it, so the tree tagged
  v0.3.1 still carries the deliberately invalid `PENDING` placeholder, and the
  archived snapshot cites an identifier it does not know. The commit after
  this tag writes the minted value into every file that names one with
  `scripts/set_doi.py`, and the entry above this one records it.
- Two files still cited the previous concept DOI while the rest of the tree
  had moved to the placeholder: `paper/paper.bib`, whose entry for this
  software also still said `v0.2.1`, and the JSON-LD in `overrides/main.html`.
  The guard that discovers DOI-bearing files did not read `.bib` or `.html`,
  so "nothing left of the old deposit" was a claim about the file types it
  read. It reads them now, both files are in `scripts/set_doi.py`'s list, and
  the guard checks that list against what it finds. `CHANGELOG.md` leaves
  the list: its 0.2.1 entry describes a move to the identifier that was
  current then, and names it again.
- Version 0.3.1 across `pyproject.toml`, `CITATION.cff`, `.zenodo.json` and
  `codemeta.json`. `CITATION.cff` and `codemeta.json` had carried `2026-08-09`
  — v0.2.2's date — as the date of 0.3.0. The manuscript, the JOSS submission notes, the Space
  README, the issue form and the roadmap name v0.3.1, because that is the tag
  the archive holds; there is no archived v0.3.0 to name. Recorded provenance
  is untouched: `benchmarks/**` still says 0.2.2.
- The container image is published again. The `ghcr.io` package lists this
  repository under its Actions access with role Write, the `PUBLISH_GHCR`
  variable is set, and the root `Dockerfile` carries the
  `org.opencontainers.image.source` label so the connection to this
  repository object no longer depends on the access list alone.
  `ARCHITECTURE.md`, `paper/README.md` and the workflow's own comments no
  longer say the push is refused.
- The Space's `requirements.txt` is version-controlled here as
  `.huggingface/requirements.txt` and uploaded by the sync workflow, for the
  reason the Dockerfile already was: the Space's own copy still listed
  `streamlit>=1.36` after the release that removed Streamlit, and nothing in
  this repository could see it. The same workflow now deletes
  `src/streamlit_app.py` from the Space — the entry point that release
  removed, which nothing uploaded would overwrite. The live demo is not
  restored by this release: the workflow stays dormant until an `HF_TOKEN`
  secret exists, and `keep-warm.yml` stays red until the Space is rebuilt.

### Removed — four working-tree wheels, with their identities recorded first

`benchmarks/designer_benchmark/results.json` names its code identity as
`working-tree wheel bindsight-0.2.2-py3-none-any.whl`. Four files by that
name sat in gitignored directories of this working tree, no two alike, and
nothing committed recorded which was which. They are deleted, with this
entry; these are their digests, recorded first.

| Path | Bytes | SHA-256 |
|---|---|---|
| `benchmarks/designer_benchmark/run_t4/_wheel/` | 406,948 | `4f57bd0edbd376fcecc38c509f2e946576981cd540b8fffa82dfbf31341c53da` |
| `runs/calibration/_wheel/` | 437,764 | `c226f651e800cfc0b9b8c00b55fca809f0125a5ada791967a1e11a7eb0260bd3` |
| `runs/calibration_paired/_wheel/` | 454,954 | `053bf74d8ea77a535c9b8adf4ddde54b0cfe2d6cbd4b662371fae9c671fc189c` |
| `runs/join/_wheel/` | 418,547 | `8424f8bf36bac2a47936c5458c449a5d477d87700e340db198c672d0dd7eb30f` |

The one committed byte count of such a wheel, `wheel bytes: 418547` in
`benchmarks/gpu_capacity/t4-ca9-377aa.log`, matches the `runs/join/` file and
not the designer-benchmark one. The v0.2.2 tag can be rebuilt; a rebuild will
not reproduce these bytes.

### Fixed — a gene nobody tested was published as a gene that failed the test

pydeseq2's independent filtering removes low-power genes before testing them
and leaves their adjusted p-value empty. The taxonomy compared that empty
value as if it were 1.0, so an untested gene was indistinguishable from one
tested and found null, and was filed under a reason naming a comparison that
never ran. It is `significance_unassessed` now, in the `*_unassessed` family
that already sits outside every denominator; a gene that was tested and
failed is still `not_significant`. The committed study's 22 panel pairs all
carry an adjusted p-value, so its numbers do not move — but any cohort with a
low-power antigen would have published one as a miss.

### Fixed — an empty result read as an absent request

`_list_cohort_files` takes `cases: list[str] | None`, and every guard inside
it was `if cases:`, so a restriction that matched nobody took the `None`
branch — the unrestricted cohort. The query builder now raises on an empty
list, naming the project and condition, and `prepare_cohort` raises earlier
still when no patient carries the requested subtype, naming the cohort and
the subtype. The same shape at the other end of the pipeline: the RO-Crate
exporter swallowed a `JSONDecodeError` on `run_manifest.jsonld` with a bare
`pass` and shipped a crate with no run identity and no digests. It logs a
warning naming the file now.

### Fixed — the plugin interface the docs document could not be used

`docs/use-cases.md` walks a method developer through registering a designer
by entry point. The loader was correct and nothing could reach it:
`DesignParams.designer` was a `Literal` of the three bundled names, the CLI's
`click.Choice` lists rejected anything else before a command body ran, and the
`ALL_*` constants were frozen from the bundled dict at import. Those fields
validate against the registry now, resolved per call, and an unknown name is
rejected with a message naming what is registered and how to register more.
`verify-licenses` indexed a bare dict by name and, handed a plugin, would have
dropped it from the table and printed the green "all components are
commercial-friendly" banner; it now names what it could not assess and
withholds the clearance.

### Fixed — one sentence reported two analyses and gave them one p-value

The study holds two results under "the ranking is indication-specific", and
they are not the same measurement: a cluster bootstrap over the 13 antigens
in the calibration cohorts (a within-antigen difference of 0.348, 95% CI
0.188–0.513, no p-value) and an exact permutation test over the 7 antigens
with a single indication (mean standing 0.858, p = 3.97e-04 over all 5,040
orderings, which is 7!). README, `docs/what-is-bindsight.md` and the Evidence
page each stated the first and attached the second's p-value to it, naming
neither denominator. They present them in the order the study reports them
now — the permutation null first, the KICH/THCA comparison beneath it as a
calibration — and say which number carries a p-value and which does not.

On the same page, the headline recall interval printed with no level while
the artifact records `confidence: 0.95` on all forty-eight of its interval
blocks: `interval()` reads the level and never assumes one, and two of its
call sites did not pass it. The nulls chart hard-coded "95% CI" in the spec
and again in the renderer's fallback. Both read the artifact now, and a
page-level guard checks the level on the page against the artifact.

### Fixed — what the served interface told a reader

- **The design check chose a factor column and showed the choice as a
  finding.** A `condition` column with one level beside a `batch` column with
  two produced a tick, a filled contrast selector and a recommended run
  against `batch` — a technical covariate, contrasted, returning plausible
  genes to a question nobody asked. The check now collects every two-level
  column, prefers one named for the condition, and no longer presents a guess
  as a finding. The page still sends nothing anywhere: the check is
  client-side, and a counts matrix is patient data.
- **The caveats were the least legible text on the Evidence page.**
  `--ink-faint` was 3.6:1 against the background, under WCAG AA's 4.5:1 for
  text below 18.7px, while the numbers beside them stayed crisp. It is 4.9:1
  now, and `tests/test_contrast.py` checks every text token against both
  grounds it is drawn on, and the chart renderer's fallback colours against
  the stylesheet.
- **The structure viewer could draw nothing and say nothing.** The page
  checks for WebGL before creating the viewer instead of showing a dead
  canvas under a caption promising a rotatable complex.
- **The printed page described a viewer it does not print.** The print
  stylesheet dropped the canvas and kept the design picker, the colour legend
  and "Rotate it." beside the empty rectangle. They go with the viewer, and a
  print-only caption says where the mmCIF files are.

### Fixed — the live-demo monitor asked whether something answered, not whether it was ours

`keep-warm.yml` finished on `GET / → 200` and annotated the demo healthy. The
Space has spent this entire release serving the Streamlit application the
release removed, which answers 200 just as well. The probe now fetches
`/static/bindsight.css` and looks for a token inside it, and that assertion
is its own job rather than one swallowed by the keepalive's
`continue-on-error`. It is red, and stays red until the Space is rebuilt
against this code. That is the point.

### Fixed — the repository describing itself

- **Five counts stated and never recomputed:** "nine skipped without
  snakemake" (five), "78 test modules" (81 at the time of the fix, 86 now;
  the page states a checked floor of 80), a
  "~50 line" designer Protocol (26 lines), a Modal price of "~$0.6–4/GPU-hr"
  against the priced $0.59–4.56, and `positioning.md` labelling both a
  shipped feature set and an unbuilt one v0.3.0 — the unbuilt half is
  v0.4.0. `tests/test_counted_self_claims.py` recomputes each, collecting the
  suite in a subprocess to hold the "1,XXX+ tests" floors to the count.
- **The manuscript had a macro typeset as a literal tab.** `\texttt{main}` had
  lost its backslash to an escape, so `manuscript.tex` set a tab followed by
  `exttt{main}`; `tests/test_manuscript_typesets.py` scans the file for the
  control characters a resolved escape leaves behind, with a fixture built
  from `chr(9)` so it cannot be repaired by the mechanism it describes. The
  same file said "200+" tests beside a `paper.md` saying "over 1,300"; it
  says "1,800+" now, and its demo table says its 42 candidates are reproduced
  by `bindsight demo` rather than pinned to a committed artifact.
- **Four things that cost a newcomer their first hour.** `bindsight doctor`
  used to report "ok" for any Python at or above the floor — a floor check
  with no ceiling; it now names the tested range, 3.11–3.13, kept in one
  constant and checked against the CI matrix. The glossary was unreachable from the README. The optional
  SURFACE-Bind row in `doctor` did not say it was optional. `mkdocs.yml`
  still described the Streamlit app.
- **Two more hand-written lists are tied to what they enumerate:** the
  score-column/weight pairs in `rank/scoring.py` against the fields of
  `RankWeights`, in both directions, and the outcome taxonomy against the
  titles and notes the study report renders it with.
- **Streamlit mentions that described a world where the app still runs are
  corrected**, and the last API surface with no vendor name in it —
  `PAGE_TITLE`, `PAGE_ICON`, `PAGE_LAYOUT`, typed for `st.set_page_config` —
  is gone. `tests/test_no_streamlit.py` guards the dependency, the imports,
  the template calls and every requirements file, including the Space's. Four
  more stale claims were found by searching for the behaviour rather than
  the word: a glossary page the served interface does not have, described in
  two docstrings; a "Real results" page the generated results page still sent
  readers to; and a Dockerfile comment saying the Space's build lived in the
  Space's own repository. What this changelog records about the migration,
  and the comments explaining why the `httpx2` pin and the version-controlled
  Space Dockerfile exist, stay on purpose.

### Notes

Observed on the release machine (Windows 11, CPython 3.14.7) on 2026-09-18,
not recorded anywhere in the tree: `pytest -m "not gpu and not slow"` passed
1,862 tests with 13 skipped at 86% coverage, and `ruff check`, `ruff format
--check` and `mypy` were clean across `bindsight`, `tests`, `scripts` and
`benchmarks`. Seven test modules are new since v0.3.0. Before that run,
Streamlit and the ten packages nothing else on the machine required were
uninstalled from its system Python, and an import watch (`-X importtime` and a
`sys.meta_path` hook) saw none of them load during the suite. CI's matrix —
three operating systems, Python 3.11–3.13 — remains the gate.

## [0.3.0] - 2026-09-18

Prepared for publication as a fresh repository. The work below is of three kinds:
defects that were invisible because they only manifested on other people's
machines, claims the project's own controls had refuted, and a front door that
sent visitors somewhere else.

### Changed — the interface is served, not a Streamlit app

Streamlit is gone, replaced by a server-rendered interface under
`bindsight/report/web/`: FastAPI, uvicorn and Jinja over the same data layer the
standalone report reads. No build step, no bundler, no npm, nothing fetched from
a network once installed. It is a net *reduction* in dependency weight —
Streamlit declared 34 requirements — and the reason for the change is not
weight:

- **Every figure had to be expressed through a widget whose layout the caller
  does not control.** That is how confidence intervals — including one spanning
  15–70% — ended up inside hover tooltips, under a paragraph promising that every
  rate carried its interval. A tooltip does not print, does not exist on a touch
  screen, and is absent from a photograph of a slide.
- **`webapp.py` printed four zeros in metric chrome for absent parquets**, so a
  broken run rendered identically to a measured empty one.

`bindsight ui` serves it; `bindsight report --format streamlit` becomes
`--format web`. Five sections: Overview, Evidence, Try it, Your data, Runs.

The properties the deleted Streamlit tests encoded were ported, not dropped —
most importantly that a **degraded Open Targets lookup must be visible**. Open
Targets is the only genome-wide Ensembl → UniProt source in the pipeline; where
it does not answer, every gene missing from the small bundled table is dropped
*before* the surfaceome filter, so the shortlist is drawn from that handful
rather than from the cohort. A reader not told this reads a short list as a
negative result. It is on the page, with counts, not in a tooltip.

### Fixed — things the interface change exposed

- **The demo button could never have worked.** `_demo_config` imported
  `load_config` from `bindsight.config`, which has no such name; every press
  raised ImportError into the broad handler and reported it to the page as a
  failed run. mypy sees it immediately — the module was outside the type-check
  scope until this release widened it, and no test had ever called the function.
- **3Dmol.js was vendored, credited, served, and referenced by nothing.** 538 kB
  in every wheel, while ARCHITECTURE.md said the interface "renders the actual
  Boltz-2 predicted binder–target complexes in 3-D". Twenty real predicted
  complexes are committed to this repository and were reachable only through a
  file manager. They are on the evidence page now. Found while driving it in a
  browser: the first version styled chains `A` and `B`, the files use `T` and
  `B`, so the target matched nothing and rendered as a wireframe haze *under a
  caption saying it was grey cartoon*.
- **Rich ate every "install the extra" message.** `[report]` is markup, so
  `pip install -e ".[report]"` rendered as `pip install -e "."` — the base
  package, which the reader already had. Three sites, on the paths a user only
  reaches when something is already wrong.
- **The Space health check probed `/_stcore/health`**, a Streamlit endpoint.
  Nothing serves it, so the job whose purpose is to prove the Space is up would
  have reported it down on every run.
- **`report --format web` announced a run directory it never passed on**, and
  **`bindsight ui` discarded its launch status** — a port already in use exited 0.

### Changed — one design system, and one set of rules

`bindsight.css` is embedded by both the served interface and the standalone HTML
report. The report's own stylesheet had a second copy of the tokens, a `.badge`
and `.note` that looked alike but were not, and a `.kpi` component with **no
denominator slot** — which exempted its four headline numbers from the rule the
rest of the project enforces. They carry it now, and the denominators were
already on disk: 17,348 genes tested → 5,121 significant of those → 291
candidates after the surfaceome filter → 2 epitopes.

Sharing the stylesheet was not enough, and the way it failed is the point: the
report still printed CA9's `padj` as `0`, because the rule that a p-value never
renders as zero lived inside the web app while the report kept its own
`f"{v:.3g}"`. Same number, same run, two answers — and harder to notice once the
surfaces look alike. Those rules now live in `bindsight/report/format.py`, which
neither surface owns and both import.

### Fixed — six defects that worked only on the machine that wrote them

The worst class a repository can carry: the author cannot see them, and the
first stranger to clone it sees nothing else.

- **Three tests failed on a fresh clone.** The prose guards rglob `benchmarks/`,
  which is also where GPU runs leave gitignored build products, so
  `run_t4/RESULTS.md` had entered a hand-written list of public documents. File
  discovery is now git-aware, and a guard asserts every hand-written path is
  tracked. Collected tests are identical with and without the local artifact.
- **The calibration integrity check could never pass for a reader.** It recorded
  the digest of a Windows working copy (7,317 bytes); git stores the blob LF, so
  every clone holds 7,297. The generator now hashes LF-normalised bytes, and a
  new guard compares the recorded digest against the blob git carries rather
  than against the local checkout.
- **Every generator wrote the platform's line endings**, so "run the generator;
  it should not change" — the one reproducibility check a reader can run in
  seconds — reported a spurious failure on Windows. Sixteen `write_text` calls
  across nine generators now pin LF. Verified from a real clone: regenerating
  produces zero changes.
- **`mamba env create -f envs/discover.yaml` failed.** `openpyxl` was indented
  under `pandas`, so YAML fused them into one invalid spec and the library that
  parses the SURFY `.xlsx` silently vanished.
- **The `Snakefile` documented `--config`**, which Click rejects; `config` is
  positional. **The published reproduce command could not run**: `score_run.py`
  is a scorer and requires the archive a GPU run produces.
- **`ruff check bindsight tests scripts` was already red** — five errors in
  committed code, so the CI lint gate was failing before any of this began.

### Fixed — the study's positive result sat on a mis-computed floor

FOLH1 and STEAP1 both map to PRAD, so antigens are interchangeable within a
cohort and every distinct assignment is enumerated twice. The smallest p the
design can express is 2/5040 — exactly the observed value. Reporting 1/5040
silenced the report's own "p equals its floor" warning on the only result in the
study that is not a negative control. It now reads as the resolution limit it
is. One field of 1,295 changed; the science is untouched.

### Added — both null models, published

Neither reached a reader. `StudyShowcase` had no field for either, so every
generated surface was structurally incapable of rendering the study's primary
null (a negative) or its strongest positive result. Both now appear on the
results page and in the app, with equal room:

- **Decoy null, negative** — 3 of 22 nominally significant, none surviving
  Benjamini-Hochberg, reported beside the panel's resolution: the smallest
  adjusted value it could have produced is 0.022. Under 0.05, so a pair could
  genuinely have survived. A measurement, not a foregone conclusion, and not a
  sensitive one.
- **Specificity null, positive** — within-antigen difference 0.348 (95% CI
  0.188–0.513), interval excluding zero, exact permutation p at its floor.

A guard refuses a Fisher combination of the decoy p-values: it returns 0.006 and
is wrong, because ERBB2 and EGFR each appear in four cohorts and these are 13
antigens rather than 22 independent tests.

### Changed — nothing untrue on any surface

`success@0.65` is withdrawn as a measure of design quality, and the surfaces
that still stated it as an achievement no longer do: the README lede and roadmap
bullet, the landing cards in the web app, and the social preview card — which is
served as `og:image` on every documentation page and, being a raster, could not
carry the withdrawal beside it. Its tiles now state the instrument's scope, read
from the artifacts rather than typed.

Both manuscripts said "structurally-validated" binder candidates and mentioned
the calibration nowhere; they now say "structure-scored" and state the control's
numbers in the abstract. The glossary no longer tells readers that ipTM 0.65
"and up is promising" or that Boltz-2 judges "whether a design would actually
bind". The calibration report leads with its final answer rather than its
chronology, so a reader who stops early cannot leave with a superseded tie.

### Changed — the front page is a map

Eleven of thirteen first-screen calls to action used to leave the repository.
The README now opens with a "Start here" table of in-repo links, one install
command in place of fifteen conflicting entry points, what the evidence does and
does not show, three reproduction tiers with what each costs, and a repository
map where every path is clickable. Nine directory READMEs were added — only
`paper/` had one.

Added issue forms (including one for a published number that does not
reproduce), a PR template requiring new guards to be mutation-tested,
`dependabot.yml` that deliberately ignores the scientific stack, `CODEOWNERS`
and `SUPPORT.md`.

### Changed — recorded artifact fields and identity

- Version 0.3.0 across `pyproject.toml`, `CITATION.cff`, `.zenodo.json` and
  `codemeta.json`. This entry said the release "is deposited under a new Zenodo
  concept DOI". It was not deposited at all: the repository had been recreated
  on GitHub three days earlier, which severed the GitHub–Zenodo integration,
  and nothing in the tree could tell — see 0.3.1. Until a deposit exists the
  repository ships a deliberately invalid placeholder, so it cannot be
  published by accident, and `scripts/set_doi.py` writes the minted value into
  every file that names one. Recorded provenance is untouched: `benchmarks/**`
  and the run manifests still say 0.2.2, because that is the code that produced
  them.
- The Hugging Face Space now ships `benchmarks/`. `showcase.py` claimed it
  "deploys the full repository"; it does not, and the Real results page had been
  rendering nothing while the README promised twenty binders in 3-D.
- Eight orphaned figures removed, dated five weeks before the artifacts they
  depicted were re-scored.

### Fixed — six more, found by auditing for this release's own defect classes

Each was reproduced before it was touched, and each guard was mutation-tested.

- **Every generated HTML report closed twelve `</div>` it never opened.** The
  note conversion that rebuilt the interface applied a note block's
  `</p></div></div>` ending to "the first `</p>` after each rewritten opener",
  and seven of those were plain descriptive paragraphs. Browsers recover from it
  silently, which is why a visual check missed it; a validator, a print-to-PDF
  path, and anything that parses rather than renders do not — and this report is
  the artifact a collaborator opens from an email.

- **A cache key that differed between Linux and Windows.** `_with_payload`
  ordered the shipped binders by sorting `Path` objects, and `PurePath.__lt__`
  compares the parts tuple, case-insensitively on Windows. The same payload
  hashed to two different keys depending on the machine, so a rerun on CI could
  not reuse a local result and two keys that differed asserted the payloads
  differed when they did not.

- **`boltzgen_protocol` and `boltzgen_use_kernels` were missing from the cache
  key** while `job_exec` read both and acted on them, so two BoltzGen jobs
  running different design protocols shared an entry and the second returned the
  first's designs. That was the third entry the executor acts on to go missing
  from a hand-kept tuple, so the tuple is no longer trusted: a new guard walks
  `job_exec`'s AST for every `extra_params` key it reads and fails unless each is
  keyed or exempt with a written reason.

- **A cache that could poison itself permanently.** A hit was `exists() and
  st_size > 0`, so an interrupted transfer's bytes became a hit that nothing ever
  re-submitted past; `extract_member` then swallowed the `TarError` as a warning,
  and the result reported `cache_status="hit"` pointing at a metrics file that
  had never been created. A hit now has to open, list, and carry the metrics it
  is consulted for.

- **A job with no target structure paid for a GPU to find that out.** The spec
  recorded `target_structure_name` unconditionally while the copy was guarded by
  an existence check, so the executor was told to find a file that had not been
  shipped — and `make_cache_key` hashes an unreadable structure as the empty
  string, so two jobs against two different missing structures shared a key. It
  now fails locally, before submission.

- **Two filters admitted what they were configured to exclude.**
  `DesignParams` checked its binder-length range in a `field_validator` on
  `binder_length_max`, and Pydantic does not validate defaults, so
  `binder_length_min=200` alone built cleanly against a default max of 100 and
  handed the designer an empty range. And `min_surface_bind_score` admitted
  sites carrying no score at all — legal under the SURFACE-Bind contract — with
  nothing saying the threshold had not been applied to them. The site is still
  kept, because dropping it would make the run report `no_surface_bind_site`,
  documented as "data present, none for this protein", which would be a false
  claim about the biology. What changed is the silence.

Three smaller corrections in the same pass: `pca_2d` returned `(N, 1)` for a
single-feature embedding while promising `(N, 2)`, which the plotting function
unpacks as x and y; the ESM-2 prescreen reported "no top_k set" for a run that
had set one and simply had fewer designs than its cap; and `designer_version`
now says it versions the bindsight adapter rather than the upstream tool, beside
a field a reader meets next to `designer_name: "rfdiff_mpnn"`.

### Notes

1,729 tests pass locally with 13 skipped and nothing failing; `ruff check`,
`ruff format --check` and `mypy` are clean across `bindsight`, `tests`,
`scripts` and `benchmarks`. Every fix was mutation-tested: the defect
reintroduced, the guard confirmed to fail on exactly that defect, the tree
restored and the diff checked clean.

Two claims were checked and **not** published because they did not survive
inspection: that the decoy null's negative was forced by the panel's design (it
was not — the bound is 0.022), and the Fisher combination above. A finding that
fails verification is a result too.

---

## [Unreleased — folded into 0.3.0]

### Fixed — a 130-finding audit, and a CI gate that was already red

A twelve-dimension sweep of the repository, every finding verified against the
files before it was acted on, returned 130 confirmed defects. Two were not the
low-severity items the sweep was looking for.

**`mypy bindsight` was failing, and eight of its ten errors had been introduced
by the two commits before this one.** The step is blocking in CI; the habit that
let it rot was running `ruff` before committing and not `mypy`. It now also
covers `scripts/`, which is where the bug its own CI comment cites — "the arity
bug that left the Snakemake front-end dead for five weeks" — actually lived. The
ten errors blocking that widening are fixed, including declaring the
Snakemake-injected global rather than self-assigning it.

**Five surfaces published the first calibration run as the current result.** The
root README, ARCHITECTURE, two benchmark guides and the live Streamlit UI all
said designs and their own shuffles cleared ipTM 0.65 "at the same rate (40% and
40%, paired difference +0.030, exact sign-flip p = 0.57)". That run used an
unseeded validator at one diffusion draw and was declared superseded here months
ago. The seeded re-run at five draws — the committed artifact — measures the
shuffles **ahead**: 50% of shuffles clear 0.65 against 30% of designs, a paired
difference of −0.043 (95% CI −0.142 to +0.054, p = 0.404), with 9 of 20 designs
beating their own shuffle where 10 is chance. Five further surfaces said "at the
same rate" in softer words. The sign of a published comparison was inverted on
the first thing a reader meets.

The guard that should have caught it read two files by name. It now sweeps
`.md`, `.tex` **and** `.py` — the UI copy was in Python, where no documentation
sweep would ever have looked — checks the claim as well as the figures, and
permits the old numbers only in the two files that explicitly frame them as the
first run.

### Fixed — configured parameters that never reached the work

`bindsight design` on the **default** backend (`colab`) built its spec with the
plugin's own defaults, so a run configured with `seed: 42` shipped a notebook
designing at seed 0 and a manifest recording 0 as though it had been asked for.
The Snakemake front-end never wrote `<run>/config.yaml` at all — the only channel
by which the seed, the binder-length bounds and every validate threshold reach
the design half. The DEG cache key omitted pydeseq2's version, so an upgraded
library was served the previous library's table under the new version's name.

### Fixed — provenance that described things it did not have

`OutputRef.path` says "Path relative to the run root"; the writer stored
`str(path)`, producing `runs\join\deg\results.parquet` — relative to the
repository, in the launching platform's separators. `record()` had no `inputs`
parameter, so every stage the CLI recorded carried an empty `prov:used`: a
provenance graph with no incoming edges cannot answer "what produced this".
`bindsight export` hashed the crate and wrote that hash into a manifest sealed
*inside* it. The RO-Crate keyed its digest map by basename while its own
docstring said "run-relative artifact path", so two files named `metrics.jsonl`
merged into one entry. `software.bib` credited bindsight's wrappers, under
bindsight's AGPL, for work done by BSD-3 RFdiffusion, MIT ProteinMPNN and MIT
Boltz-2. The fragment reader rewrote any status it did not recognise to
**completed** — a stage that failed in an unfamiliar way was recorded as having
succeeded. `SCIENTIFIC_STACK` had fallen six pins behind, including `formulaic`,
pydeseq2's design-matrix engine, whose release can move a log2 fold change on its
own.

### Fixed — what the report told a reader

The "candidate targets" KPI counted the length of its own 20-row display table,
so the committed run published **20** where the truth is **291**. "How to read
this report" described a candidate ordering the pipeline had abandoned. The
epitope legend omitted `surface_bind_lookup_failed`, leaving a lookup that
errored to read as a measured absence of a targetable site. A candidates table
that could not be read was reported as "No candidates survived the filters.
Loosen thresholds" — a scientific conclusion drawn from a table nobody read. The
volcano plot text-labelled every significant gene, which on a real cohort is
~4,400 overlapping annotations. The web app published a rate with no n, a mean
over an unstated subset, and four outcome counters over an unnamed denominator.

### Fixed — packaging: commands that only worked from a source checkout

`bindsight ui` launched a root-level `streamlit_app.py` the wheel never ships,
while its sibling `report --format streamlit` already imported the packaged
module — one file held both the right and the wrong way to find the same app.
`bindsight demo` could not find its config from a pip install. The CPU image's
header promised the Snakemake front-end and its install line omitted the extra
that provides it. The public demo Space's image was neither digest-pinned nor in
scope of the container guards, because those read one hard-coded path. The Space
runs Python 3.13, which the classifiers did not claim and the CI matrix did not
test; all three now agree.

### Fixed — guards whose scope was typed by hand

The pattern behind most of these findings. The import smoke test read a list of
53 names against a package of 78 modules, so 25 were unchecked — including
`bindsight.plugins`, the entry-point loader every backend goes through. The
withdrawn-headline guard omitted the bioRxiv manuscript its own docstring names
as one of the six affected surfaces. `BINDER_FIGURE_DOCS` had gone stale by five
documents. The container checks read one Dockerfile. The "no dead dependencies"
test grepped for three historically-removed names and said nothing about the
dozens declared now. Each is replaced by discovery — globbing, AST parsing, or
introspection of the registry — or, where per-document semantics forbid that,
kept as a list with a sweep that fails when the list goes stale.

### Changed — recorded artifact fields

Re-scoring is required for these; `python benchmarks/run_study.py --score-only`
regenerates the study without refetching or re-running DESeq2.

- `base_mean_decile` / `dispersion_decile` are now `base_mean_stratum` /
  `dispersion_stratum`. `_DECOY_STRATA_BINS` is 5, so the labels 0–4 are
  quintiles; the old names told a reader the decoy matching was ten times finer
  than it is.
- Manifest artifact paths are recorded relative to the run root, in POSIX form.
- The `export` stage records the crate as a parameter rather than a digested
  output, because a file cannot contain its own hash. The digest belongs in the
  `SHA256SUMS` published beside the deposit.
- The `discover` stage records `surfaceome_source`: which surfaceome list the run
  resolved. The choice between a user cache and the vendored list was made
  silently, so two runs could use different lists — different eligible
  denominators, different counterfactual ranks — with nothing saying which.
- The designer benchmark summary records its `seed`. An older artifact renders as
  "Seed: **unrecorded**" rather than as 0, which is a real and different run.
- The published `rank` now comes from a stable sort, so tied composite scores keep
  their input order instead of numpy's introsort internals.

### Notes

The suite grew from 1,321 to 1,619 collected tests; 1,610 pass and 9 skip (5 of
them the Snakemake DAG tests, which need a `snakemake` that will not build on
Python 3.14 — they run in CI). `ruff` and `mypy` are clean across `bindsight`
and `scripts`.

Every fix was mutation-tested: the defect reintroduced, the guard confirmed to
fail, the tree restored. Eight mutations did not catch their defect on the first
attempt, and each exposed a guard that was decoration — a test asserting a string
appears in the source rather than driving the behaviour, a tie-ordering test
whose all-equal fixture no sort would ever reorder, a prose check that accepted
any interval where three were required, and one case where the prose claimed
"checked by tests" before that test had been written.

Three of the sweep's own claims were refuted on inspection and are recorded here
because a refuted finding is also a result: the vendored surfaceome and the
report templates **do** ship in the wheel; only two documents state the measured
VRAM peak, not three; and `study.py`'s duplicate-gene handling is sound across
all five committed cohorts.

### Fixed — the specificity null compared the observation against a null that excluded it

The panel-level p-value was not a tail probability of the observed statistic
under any distribution the code sampled.

`permutation_null_p` dealt each antigen a **distinct** cohort. The observed
statistic pairs each antigen with its own indication — and two panel antigens
share one. FOLH1 and STEAP1 are both single-indication and both TCGA-PRAD, so
the observation counts prostate twice while no draw without replacement ever
could. Both score near the top there, so the observed statistic was
systematically larger than anything the null could produce, and the p-value
collapsed onto its sampling floor. That collapse is exactly what an observation
outside its own null looks like.

**This became live today.** STEAP1 had been excluded from the null as "not
scored in every cohort" — an artefact of the SURFY-only gene map fixed a few
entries above. Correcting that map restored STEAP1 to the usable set and, with
it, the second prostate assignment. The fix that made the study's denominators
right is what made its specificity p-value wrong.

The null now shuffles **which antigen receives which of the observed cohorts**,
so the observation is the identity permutation and always in its own support.
It controls for cohort difficulty as a side effect: every permutation uses
exactly the cohorts the observation used, so a cohort whose standings run high
cannot inflate one arm and not the other.

With seven antigens the 5,040 permutations are enumerable, so the p-value is
exact rather than sampled — a p that can be exact should not carry Monte Carlo
error or a floor to reason about. **p = 3.97e-04**, meaning 2 of 5,040
permutations are as extreme: the observed assignment and the FOLH1/STEAP1 swap
that necessarily ties it. The previously published 9.99e-05 was the sampling
floor of an invalid comparison.

The observed statistic is now computed inside the null from the assignment it
is given, rather than by the caller under its own rule. That is how the two
came to disagree, and passing one number where the structure was needed is what
made the disagreement invisible.

The conclusion stands: indication specificity is real and now defensible. The
number under it was not.

### Fixed — the Chai-1 validator carried both defects Boltz-2 did

Verified against pinned commit c544fb1: `run_inference` takes
`seed: int | None = None` and `num_diffn_samples: int = 5`. So Chai-1 diffuses
five structures per binder and seeds none of them — exactly Boltz-2's position
before it was fixed — and `parse_chai_output` read whichever `scores*.npz` the
directory walk yielded first, which chai-lab ranks best-first.

No published number comes from here: `plugin_support` marks chai1r unsupported
on every bundled backend, because it needs bfloat16 and the free tiers pin
pre-Ampere cards. That is precisely why the defects survived — a plugin that has
not run is where a defect sits unnoticed until it is producing results, which is
the same reason the hardcoded `validator_version` beside it was fixed earlier.

Every draw is now read and averaged, `iptm_n_samples` and `iptm_sd` are
recorded, and the seed is derived per binder from the run's seed by the same
function the Boltz-2 path uses — so the two validators are reproducible in the
same way rather than one of them by accident.

### Fixed — GPI-anchored antigens were classified as having nothing a binder can reach

UniProt annotates topological domains *relative to* a transmembrane segment. A
GPI-anchored protein is held in the outer leaflet by a lipid and has no
transmembrane helix, so it carries no topological domain either — and reading
extracellular extent from topological domains alone returned "no extracellular
domain" for an entire class of cell-surface protein.

That class includes some of the best-validated antibody targets there are.
Verified against the live record for **MSLN** (Q13421), which is in this
project's own default target set and is the target of multiple clinical
antibody-drug conjugates and CAR-T programmes: no Transmembrane feature, no
Topological domain, one Lipidation reading "GPI-anchor amidated serine" at
residue 598, signal peptide 1–36, propeptide 599–622 "Removed in mature form".
CEACAM5, FOLR1 and CD59 have the same shape.

With `require_extracellular_domain` enabled, discovery dropped such candidates
from design carry-forward as "not antibody-accessible" — the opposite of the
truth. The gate defaults to off, so no committed result is affected, but
`has_extracellular_domain` was written as `False` into every candidates table
regardless, which is simply a wrong fact.

A GPI anchor is now recognised, and the reachable region derived as the mature
chain: after the signal peptide, up to and including the omega site. Residues
past it are the propeptide UniProt marks removed in the mature form — gone
before the protein reaches the surface, so designing against them would target
a sequence no cell displays. For MSLN that is 37–598 of 622.

The inference is a fallback, not an override: a protein with annotated
topological domains, or with a transmembrane helix, keeps the annotation.

### Fixed — the study ranked against a smaller surfaceome than the pipeline searched

`score_cohort` built its eligible-gene set from `load_surfy_gene_map()` — the
SURFY core, 3,366 gene ids — while `run_study` passes the **extended** accession
set (4,801) that discovery actually used. Every SURFY accession is already in the
extended set, so the filter beside it removed nothing and **2,108 genes the
pipeline can surface were simply absent from the denominator**.

`run_study._surfaceome` states the requirement in its own docstring — "this must
match what discovery actually used ... scoring against SURFY alone while the
pipeline ran against the extended reference would report antigens as unreachable
that the run could see perfectly well, which is exactly what happened the first
time the extension landed". It was applied to the accession set and not to the
gene map keyed against it. The gene map is now derived from the accessions
passed in, so the two agree by construction rather than by remembering to pass
the same flag twice.

The study has been re-scored from the cohort tables on disk. What changed:

- **Every counterfactual rank moved**, because each is taken among ~70% more
  competitors: ERBB2/BRCA 263 → 476 of 2,284 → 3,817, MET/KIRP 7 → 10, EGFR/COAD
  1,547 → 2,715. The **normalised** ranks barely moved (0.1231 → 0.1225 for the
  first pair), because numerator and denominator grew together.
- **CA9 and STEAP1 re-enter the specificity null.** They were excluded as "not
  scored in every cohort" purely because the SURFY map lacked them — the same
  omission the project already fixed once at the accession level. The null now
  runs over 7 antigens instead of 5; observed mean standing 0.817 → 0.858, and
  p falls to the permutation floor.
- The calibration separation widens slightly: own-indication 0.741 → 0.738
  against off-indication 0.461 → **0.418**.
- Recall, dispositions and outcome classes are **unchanged**. The conclusion —
  most clinically validated antigens are not surfaced by unstratified bulk
  expression — does not move.

Two things found while re-scoring:

- **The specificity null's p-value now sits on its floor**, so the report says
  so. "As extreme as 10,000 permutations can show" and "vanishingly small" are
  different claims, and the decoy null beside it already reported its own floor.
- **A BH-adjusted p-value could print one unit in the last place below the raw
  p-value it corrects.** `p * n / n` is not exactly `p` in floating point.
  Every term of the running minimum is `p_(j) * n / j` with `n / j >= 1`, so the
  exact adjusted value is always at least the raw one; the implementation now
  says so rather than relying on the arithmetic to land there.
- **A test had pinned the bug's own consequence as expected behaviour**,
  asserting CA9 appears in the specificity null's exclusion list. It now pins
  the property that actually matters: every excluded antigen is absent from the
  scored set, and the two lists do not overlap.

### Fixed — three collisions and a lie, found by auditing for today's defect classes

An audit swept the repository for the *classes* of defect the ipTM calibration
turned up. Each finding below was verified against the code, the artifact or the
pinned upstream source before it was acted on.

- **Modal silently dropped the working-tree wheel, and the summary published it
  anyway.** `get_runner` forwards only the kwargs a constructor declares — right
  for `MockRunner`, wrong to do quietly for `ModalRunner`, which declares no
  `bindsight_wheel`. A `--backend modal` benchmark therefore built the wheel,
  discarded it, installed bindsight from the repository's default branch on the
  GPU, and published "working-tree wheel …" as the code that ran. That is the
  failure the wheel exists to prevent, reported as prevented. Provenance-critical
  drops are now logged, and `bindsight_source` asks whether the backend *can
  carry* a wheel rather than whether one was built.
- **Two epitope sites of one receptor minted identical binder ids.** Discovery
  emits one epitopes row per qualifying targetable site and each becomes its own
  design job, so two sites of one target both produced `P04626_binder_0_seq0`.
  Since `binder_id` is the provenance key, the concatenated metrics carried two
  rows with one id, `validate/<id>/` belonged to whichever job finished last,
  and the per-target tarball was overwritten the same way. The epitope joins the
  namespace; whole-surface design keeps the bare accession, so no published id
  moves. Archives written before the fix are still found.
- **A cohort whose discovery crashed was scored as one that found nothing** —
  see below.

### Fixed — a wrong figure stood in six shipped documents at once

"Thirteen of the seventeen approved-tier pairs fail the significance rule"
appeared in the deposit-ready manuscript twice, the bioRxiv preprint, paper.md,
ARCHITECTURE.md and the public landing page. **Thirteen is the count across all
twenty-two pairs.** Across the seventeen approved-tier ones the artifact says
eleven fail the significance rule, with a twelfth measured as down-regulated —
so twelve are not over-expressed.

Every copy was written from another copy rather than from `results.json`, which
is how one arithmetic slip reached six surfaces and the guards that pin other
published figures never covered this one. A test now recomputes the
approved-tier dispositions from the artifact, refuses the wrong phrasing
outright, and requires every document discussing the tier to state a number the
artifact supports.

Nothing about the study's conclusion changes: most clinically validated surface
antigens are still not significantly over-expressed in unstratified bulk
contrasts. The count was wrong, not the finding.

### Withdrawn — the designer benchmark's success rate is not a design measurement

`DEFAULT_IPTM_SUCCESS = 0.65` carried the headline "40% success@0.65" and
arrived as a bare constant with no citation, so the project measured what it is
worth. Each of the twenty committed ERBB2 designs was folded in one job
alongside a shuffle of its own sequence — same length, same composition, same
target, same validator, same card, same session, only the residue order
different.

The rate is **withdrawn as a measure of design quality**.

**Settled by the seeded re-run.** Repeating the comparison with the designer and
validator both seeded, five diffusion draws averaged per binder, under a pinned
`boltz==2.0.3` the run recorded for itself: **shuffles clear 0.65 more often
than the designs do — 50% against 30%**. The paired difference is −0.043 (95% CI
−0.142 to +0.054, p = 0.40), and 9 of 20 designs beat their own shuffle where 10
is chance. Five times the sampling effort moved the answer slightly further
against the designs.

**The prediction that failed is the useful part.** Averaging five draws was
expected to cut the paired spread by √5. It did not move it at all: 0.230
against 0.231. Because each arm's standard error is now measured directly, the
split is exact — **15%** of the paired variance is the validator resampling the
same input and **85%** is real variation from one design/scramble pair to the
next. More draws attack the 15%; only more *pairs* touch the rest. Detecting a
0.05 difference at 80% power needs 142 pairs however many structures each gets,
so twenty pairs could never have seen it.

- **Designs and their own shuffles cleared 0.65 at the same rate: 40% and 40%.**
  The paired difference was +0.030 (95% bootstrap CI −0.070 to +0.127), 13 of
  20 designs beat their own shuffle where 10 is chance, and an exact sign-flip
  test over all 1,048,576 assignments gives p = 0.57. One shuffle scored 0.815,
  above nineteen of the twenty designs.
- Stated as what it is: the run **bounds** any real advantage at about 0.14
  ipTM. It was not powered to see anything smaller, and that is reported
  alongside the p-value rather than left for a reader to infer.
- The ipTM values themselves stand — they are what Boltz-2 returned. What is
  withdrawn is the claim that the rate measures the designs. Every surface that
  renders it now carries the notice, from one shared string, guarded by a test.

A cause was found in the source and fixed (below). Whether the designs are in
fact no better, or the metric was too noisy to tell, is not yet decided: a
seeded re-run with multiple diffusion samples is what settles it, and the full
control set the answer needs is sized in `benchmarks/calibration/README.md`.

### Added — the metric's own noise is measured rather than inferred

- **`iptm_sd` and `iptm_n_samples` on every row.** With more than one draw per
  binder, each row carries the spread of its own repeated draws: one input, one
  job, one installed version, nothing confounded with anything. Pooled across
  binders that is the metric's noise floor, and it is what any difference
  between two designs has to exceed to have been observed. Until this, the only
  handle on ipTM's spread was refolding across runs, which mixed sampling noise
  with everything else that differed between them.
- The calibration report states which side of that floor an effect falls on,
  rather than printing two numbers and leaving the reader to compare them.
- Pooled as a root-mean-square, because standard deviations do not average —
  variances do, and a plain mean understates the spread exactly when the
  per-binder values differ.

### Fixed — asking for five diffusion draws silently diffused five at once

- **`--max_parallel_samples` defaults to 5**, though its own help text says
  "Default is None". The instrumented run measured the headroom that leaves: a
  peak of 10,917 MiB of the T4's 15,360 for a *single* draw of a ~230-token
  complex. The flag is now always explicit and sequential by default; a caller
  with the VRAM can raise it.
- **It is not a performance knob.** The sampler draws noise shaped by the batch,
  so one seed consumes the RNG stream differently at batch 1 and batch 5 and
  produces different structures. It is folded into the cache key with
  `diffusion_samples` and `mode`, and documented in ARCHITECTURE 4.4 alongside
  the payload digest.

### Changed — the calibration works for any design run, not just this benchmark

- `stage_scrambles.py` takes `--binders`, `--target` and `--target-chain`;
  `submit_calibration.py` takes `--target`. A scramble control is meaningful for
  any design run, so a user can calibrate their own designs rather than only
  reproduce the committed ERBB2 one.
- The staging script gained thirteen tests. It builds the control the
  withdrawal rests on and had none: nothing checked that a "scramble" is a
  composition-preserving shuffle of its **own** design, or that each staged
  structure describes the sequence staged beside it. Both failures are silent —
  the files parse and the metrics row is well-formed and about a different
  molecule.

### Fixed — the *designer* ran unseeded too, and that defeated the validator fix

An integrity audit of the repository found the same defect one stage upstream,
verified against the pinned upstream sources rather than from memory.

- **RFdiffusion — the default designer, and a diffusion model — was invoked with
  no determinism control at all.** At pinned commit 2d0c003 it seeds
  torch/numpy/random only inside `if conf.inference.deterministic`, and
  `config/inference/base.yaml` ships `deterministic: False`. So every backbone
  was an unseeded draw, and the per-binder validator seed added above was
  reproducibly folding sequences that were themselves not reproducible. Both
  runs still recorded `"seed": 42` in the manifest and hashed to the same cache
  key, so the artifacts asserted sameness the code could not deliver.
- There is no `inference.seed` upstream; the *design index* is the seed
  (`make_deterministic(i_des)`), and `design_startnum` chooses it. The run's
  seed now selects a block of indices — multiplied by the trajectory count, so
  adjacent seeds get **disjoint** blocks. Passing the seed straight through
  would have given seeds 42 and 43 nine identical backbones out of ten while
  reporting them as different runs.
- **ProteinMPNN was handed `--seed 0`, which upstream documents as "pick a
  random seed".** Its code is `if args.seed: seed = args.seed else: seed =
  np.random.randint(...)`, so the one value that reads as a plain default is the
  one that turns seeding off — and it was the default of both the parameter and
  `DesignSpec.seed` on several paths. Only the sentinel is substituted, so every
  non-zero seed keeps the value it has always had and no reproducible run moves.

**Consequence for the committed benchmark:** those twenty designs were produced
before any of this, so they cannot be reproduced — not merely "differ in the
timestamp", but a different set of backbones and sequences each time. That is
now a property of the past runs rather than of the tool.

### Fixed — the validator ran unseeded, so every ipTM was a single random draw

- **Boltz-2 was invoked with neither `--seed` nor `--diffusion_samples`.** It
  builds structures by diffusion; its `--seed` defaults to `None`, which its own
  help spells "no seeding", and `--diffusion_samples` to 1. The calibration
  measured the cost: refolding the same twenty sequences moved ipTM by a median
  of 0.129 and a maximum of 0.667, flipped eight of twenty verdicts at 0.65, and
  left the two runs correlated at Spearman 0.065. The design published as best
  (0.881) refolded at 0.418. This is the defect already recorded for
  `params.design.seed` — declared, documented, read by no code — one stage
  further along: the seed reached the designer and stopped there.
- **Reading one confidence file reported the best draw, not an estimate.** Boltz
  writes one per diffusion sample and ranks them by confidence descending, so
  raising `--diffusion_samples` would have raised the reported score with no
  design changing. Every draw is now read and averaged, and `iptm_n_samples`
  and `iptm_sd` record how many and how far apart — the metric's own noise,
  measured on one input inside one job.

### Fixed — the validator's own provenance, found while auditing the fp32 patch

Auditing the one line the Kaggle kernel patches in Boltz-2 meant pinning down
which Boltz-2 that line was being audited *against*. It turned out nothing knew.

- **`validator_version` was a hardcoded constant.** Every metrics row carried
  `"2.0.1"` regardless of what was installed, sitting beside genuine
  measurements in the same line and reading as one of them. It is read from the
  environment now, and reports `"unrecorded"` — never a plausible-looking
  version — where Boltz is not importable.
- **The validator was the only external tool not pinned.** `BOLTZ_PIP` was the
  range `boltz>=2.0,<3.0` while RFdiffusion, ProteinMPNN, BindCraft and BoltzGen
  were all pinned to exact commits. The tool that produces every published
  confidence number was the one free to change between runs. It is now
  `boltz==2.0.3`, defined once and derived in both places that need it.
- **The kernel now logs the version it resolved.** The install is quiet, so no
  run before this recorded what it got. A pin is the request; the log line is
  the receipt.
- **The fp32 patch is audited rather than asserted**, in
  `benchmarks/calibration/PRECISION.md`: one `Trainer`, one `precision=`
  argument, a value upstream already ships for boltz1, and no dtype branch
  anywhere on the boltz2 code path. A test fails if the pin moves away from the
  audited version.

### Fixed — a validate-only job could be served another job's results

- **The cache key did not cover the shipped binders.** A designer run is keyed
  by what the designer is told to produce; a `validate_only` run produces
  nothing — the binders travel in the payload, and the spec is identical
  whichever ones go. Two calibration sets against the same target hashed alike,
  so the second would have been handed the first's rows: the right number of
  well-formed metrics for the right target, and wrong. The payload is folded in
  at the point it is received, so no future caller can forget it.
- **A `validate_only` kernel referenced a name its skipped branch defined.**
  Wrapping the designer setup in a mode guard left `wrapper` bound only inside
  it and read two hundred lines below, so the kernel built both environments and
  materialised its payload before dying on a `NameError`. The test now parses
  the generated script and fails on *any* name the skipped branch alone defines.

### Fixed — what running the documented chain on a real cohort exposed

Driving `discover → design` end to end on the clear-cell kidney cohort found
four defects the designer benchmark could not, because that benchmark uses a
hand-sliced 142-residue target and its own runner script rather than the CLI.

- **`bindsight design` never read the run's own configuration.** The subcommand
  takes a run directory, not a config file, so it used its flag defaults and
  silently replaced a configured `n_trajectories: 10` with 50 — five times the
  GPU cost, printed in the cost panel as though the user had chosen it. It now
  fills any option the user did not pass from the run's `config.yaml`; an
  explicit flag still wins. The same run went from an estimated 5.00 GPU-hours
  to 1.00.
- **The CLI design path installed bindsight from git**, exactly as the benchmark
  used to. A provenance run designed there would have produced colliding binder
  ids under `main`'s code — the defect the run exists to disprove. Both CLI call
  sites now ship a working-tree wheel; local backends skip the build.
- **The kernel payload was embedded uncompressed.** A full-length receptor plus
  that wheel came to 1,112,226 bytes against the 900,000-byte ceiling, so the
  run could not be submitted at all. The size check refused before pushing
  rather than failing opaquely at Kaggle, which is what it was added for.
  Structures are mmCIF text and compress to roughly a fifth; the CA9 kernel is
  now 677,871 bytes.
- **Discovery handed the designer the full-length chain**, transmembrane and
  cytoplasmic regions included. A binder against an intracellular region is
  meaningless for a cell-surface target, and CA9's 459 residues do not fit a
  16 GB T4 beside a binder. `examples/provenance_join.yaml` enables the topology
  restriction, giving CA9 residues 38–414 and CD70 39–193.

Two things the run confirmed rather than broke: the differential-expression
cache hit on the second discovery pass, turning a 3.5-minute DESeq2 fit into 26
seconds, and the shortlist reproduced the study exactly — 291 candidates, CA9
first, CD70 second.

`examples/provenance_join.yaml` is the committed configuration for this run. An
earlier commit message claimed to add it at `runs/join/config.yaml`; that was
wrong, because `runs/` is gitignored and the pipeline then overwrote the file
with the effective config it writes into every run directory.

### Added — the designer benchmark, re-run under the corrected protocol

- **20 de novo ERBB2 binders on a free Kaggle T4**, superseding the run whose
  figures this release had been disclaiming. Best ipTM **0.88**, mean 0.51,
  median 0.49, mean PAE-interaction 15.6 Å, **40%** success@0.65 (8 of 20),
  validated with Boltz-2, one GPU-hour, $0. This entry said "Boltz-2 2.0.1"
  until that number was checked: it came from a hardcoded constant written into
  every metrics row, not from the environment, while the installer pinned only
  `boltz>=2.0,<3.0`. The exact release behind these figures is not recoverable.
  Both halves are fixed under Unreleased. The ipTM figures themselves are
  unaffected — they are what Boltz-2 returned; only the label on the model was
  wrong.
- **The target chain is verified, not asserted.** All 20 designs carry a target
  chain byte-identical to the native 142-residue ERBB2 domain IV, checked by
  comparing every design's chains against the prepared structure. That is the
  direct evidence the `--pdb_path_chains` fix works on real hardware, which no
  previous run could provide.
- **The superseded figures are withdrawn**: best ipTM 0.84, mean 0.59, 50%
  success@0.65, on a P100. That run redesigned the target as well as the binder,
  so its designs were optimised against a partly-invented surface and then
  scored against the native one. The corrected mean is *lower* — 0.51 against
  0.59 — which is what that artefact predicts, while the best single design is
  better. Every surface that quoted the old numbers now quotes the new ones, and
  `tests/test_published_numbers_match_artifacts.py` fails if any drifts.
- The run installed a wheel built from the working tree, so `results.json`
  records `bindsight_source` and the result names its own code. Binder ids carry
  the target accession (`P04626_binder_0_seq1`), which is the id-collision fix
  demonstrated end to end rather than only in tests.
- Developability descriptors and ESM-2 embedding coordinates were regenerated
  for the new binders. They are derived by separate scripts, so staging alone
  would have left them describing designs that no longer exist.

### Withdrawn — the rediscovery headline

- **ERBB2 at rank 4, and recall@5 of 33%, are withdrawn.** The breast cohort behind
  them was stratified by a PAM50 subtype call, and ERBB2 is one of the fifty genes
  the PAM50 centroid classifier is built on, so the tumour arm was selected partly
  by expression of the gene then reported as discovered. The denominator of three
  was separately chosen after seeing which antigens proved over-expressed. Two
  errors that compound. Every surface that asserted the figure now retracts it:
  the README, the docs site, the landing page, the JOSS paper, the bioRxiv draft,
  the validation manuscript, and the social preview image — which said
  "ERBB2 — rediscovered, rank 4" and is the card anyone saw when the repository
  link was shared.

### Added — a rediscovery study that is not circular

- **Fifteen whole, unstratified TCGA projects**, run as patient-paired contrasts
  (`~ case_barcode + condition`) against a pre-registered panel of 22
  antigen-cohort pairs covering 13 antigens. No cohort's definition refers to the
  antigen being sought. The admissibility rule is stated once and separates two
  properties that the earlier error conflated: whether a stratifier is derived
  from the run's own counts, and whether it measures the antigen under test.
- **Recall at rank 20 is 1 of 17** on approved-agent antigens (95% CI 0.01–0.27),
  2 of 17 at rank 50, and 3 of 22 across every regulatory tier. Over eight
  independent antigens it is 0 of 8. The interval, not the point estimate, is the
  finding at this panel size.
- **Five antigens surface**: CA9 at rank 1 of 291 in clear-cell kidney, GPC3 at 9
  of 289 in liver, MET at 10 of 287 in papillary kidney, FOLH1 at 34 of 285 in
  prostate, STEAP1 at 158 of 285.
- **Four outcomes are reported separately** rather than merged into one rate: an
  antigen the surfaceome reference does not contain, one a stated filter excluded,
  one the ranking placed low, and one whose lookup failed are four different
  findings. Every non-surfaced pair carries a counterfactual rank saying which.
- **Every rank is published with the size of the list it sits in**, every rate with
  its numerator, denominator and interval, and recall at five cutoffs rather than
  one. The old page printed "rank 4" and "recall@5 = 33%" without either.
- The honest discussion: thirteen of seventeen approved-tier antigens are simply
  not significantly over-expressed in an unstratified bulk contrast. Their agents
  are licensed, so the antigens are real. That is a limit of the signal, not of
  the ranking, and it is what the stratified analysis was concealing.

### Fixed — defects that produced plausible-but-wrong output

- **Binder ids collided across targets.** Every target produced `binder_0_seq0`,
  so per-binder validation output overwrote itself on disk and
  `validated.parquet` carried duplicate keys. `binder_id` is the key the whole
  provenance claim is walked by. Ids now carry the target accession.
- **The affinity field was wrong twice.** Chai-1's pTM and AF2's binder pLDDT were
  written into `affinity_pred_value` and weighted at 0.30 as though they were
  affinities, double-counting structure confidence; and the ranker treated the
  field as higher-is-better when Boltz-2 reports a log(IC50)-like value where
  lower is stronger, so the composite promoted the weakest designs. Both fixed,
  and the ranking math now has numeric assertions — it previously had only
  ordinal ones, which is why this was invisible.
- **Validators scored the wrong target.** Binders designed against a trimmed
  extracellular region were scored against the full-length receptor.
- **The safety gate failed open.** An unmeasured GTEx answer compared False
  against the ceiling and was published as having cleared a gate that never ran.
- **`mean_epitope_plddt` was always null**, because the stored run-relative path
  was never resolved.
- **The idempotency guarantee was not implemented.** The cache key was computed
  and used only as a directory name; every rerun resubmitted. It is now consulted,
  covers the target structure's content, records hit or miss in the manifest, and
  includes the backend — without which a `--backend mock` run and a later real one
  shared a cache entry, so the real run would return synthetic numbers wearing a
  real result's label.
- **`bindsight validate` ran no validator.** `--revalidate` now dispatches the
  chosen validator against existing designs, which is what makes cross-validator
  agreement reachable without redesigning.
- **BoltzGen could never have executed.** bindsight built
  `boltzgen design --target ...`; upstream has no `design` subcommand and none of
  those flags. It now emits a design-spec YAML and calls `boltzgen run`, converts
  author residue numbering to the canonical indexing BoltzGen actually reads, and
  passes `--use_kernels false` because its Triton kernels need compute capability
  8.0 and every free-tier GPU is older.
- **The Kaggle kernel was heading for an unusable GPU.** `enable_gpu` alone gets
  Kaggle's default P100, which their own docs now say cannot run current PyTorch;
  the failure surfaces hours in, as CUDA reports available and the first kernel
  launch dies. The accelerator is pinned to a T4 and the kernel exits immediately
  if compute capability is below 7.5.
- **The Modal image could not run the designer** it exists to run: it installed
  bindsight from PyPI, where it does not exist, on a base with no CUDA.
- **dl_binder_design was cloned without its `silent_tools` submodule**, so the AF2
  initial-guess validator failed on import.

### Fixed — the provenance chain, which had never been demonstrated

- **Only `bindsight run` wrote provenance past `discover`.** The README Quickstart
  uses the individual subcommands, so following the documented path produced a
  manifest that stopped exactly where the design half begins. Design, validate,
  rank, report and export now each record themselves, idempotently by stage name.
- **The exported crate broke at the patient end.** It omitted `counts.tsv.gz`,
  `design.tsv` and `provenance.json` — the only artifacts carrying TCGA case and
  sample barcodes. A crate that stops at the DEG table documents an analysis, not
  its origin.
- **The mock runner could not exercise the invariant it exists to guard**, emitting
  a fixed pair of binder ids with `target_uniprot="MOCK"` for every target. It now
  namespaces by target, as the real executor does.
- Verified end to end on the real clear-cell kidney cohort: forty binders across
  twenty targets, all ids unique, the top-ranked resolving to CA9, and the crate
  carrying all seventy-two patient barcodes. `tests/test_join_end_to_end.py`
  drives the same path in CI.

### Changed — what the pipeline actually filters on

- **The enrichment cut now runs after the surfaceome filter, not before.** It
  previously took the top 300 significant genes from the whole genome and filtered
  to surface proteins afterwards, so surface antigens competed against every gene
  for those slots: in bladder cancer, 4,418 genes were significant, 300 reached
  enrichment, and 24 were surface proteins. NECTIN4 — an approved-drug target for
  that exact indication, over-expressed at log2fc 1.52 — ranked 259th of 2,104
  surface proteins and was still excluded. The ordering was forced, not careless:
  the filter needed UniProt accessions that only existed after enrichment. A
  vendored Ensembl-to-accession map removes that dependency, and filtering first
  costs nothing. Shortlists grew from roughly 40 candidates to roughly 295.
- **The surfaceome reference is extended** with UniProt's curated cell-membrane
  annotations: 1,915 further accessions, from 2,886 to 4,801. CA9 measures a log2
  fold change of 9.58 in clear-cell kidney — the largest effect in the panel — and
  was unreachable at any expression level because its accession was absent. So was
  STEAP1. The extension is additive, every entry records its source, and
  `use_extended_surfaceome=False` reproduces a SURFY-only run exactly.
- **Differential expression is cached** on the content of its inputs and every
  parameter. It dominates every run — over ten minutes for 32 matched pairs — and
  a downstream change previously forced hours of identical recomputation.
  Re-running fifteen cohorts against the new surfaceome took eight minutes rather
  than ten hours.
- **`iptm_threshold` and `pae_interaction_threshold` are applied.** They were
  declared, shipped in both example configs, and read by no code, so a user who
  tightened either was silently ignored. Designs are now annotated with
  `passes_thresholds` and a reason, and never dropped: a design vanishing without
  a recorded reason is the class of invisible filter this release exists to remove.
- **`enrich_top_k` is a declared parameter** rather than a module constant, so the
  most consequential filter in discovery lands in the run manifest.
- **The DESeq2 worker count is configurable.** Its default of every core is right
  on a server and hostile on a laptop running a multi-hour cohort sweep.
- The readiness table and ARCHITECTURE now match the code: `bindsight validate`
  materialises rather than validates unless `--revalidate` is passed; only the
  Kaggle backend is verified, with Modal prepared-but-unexecuted and Colab an
  interactive on-ramp that cannot be a reproducibility path because Google's API
  does not permit launching a free-tier notebook from a CLI; the idempotency
  section describes the implementation; and the claim that the CLI and Snakemake
  front-ends produce identical artifacts is retracted.

### Fixed — the GPU never ran the code you were testing

- **Every Kaggle run this project made installed the repository's default
  branch.** `BINDSIGHT_GIT` carried no ref and no caller ever set one, so
  `pip install git+<repo>` resolved to `main` regardless of what was checked
  out. A corrected ERBB2 designer benchmark was launched against a branch whose
  fixes existed only locally, ran an hour on a T4, and returned pre-fix
  `binder_0_seq0` binder ids — the exact defect it was launched to show fixed.
  Nothing in the run said which code it had installed.
- A git ref narrows that and does not close it: a branch resolves on the GPU, at
  pip time, to whatever it points at then, and an unpushed commit cannot be named
  at all. `bindsight/runners/source_wheel.py` now builds a wheel from the working
  tree and the kernel installs that. bindsight is pure Python, so the wheel is
  400 KB and travels inside the kernel script. The benchmark does this by
  default; `--install-from-git` opts out and says what it costs.
- **The design cache key covers which bindsight runs.** Had the mistaken run
  succeeded and cached, a later run of the fixed code would have been handed the
  unfixed result under the same key.
- **`results.json` records `bindsight_source`**, so an artifact names its own
  code rather than "the default branch at some past moment".

### Fixed — a finished run destroyed by its own bookkeeping

- **A log file killed an hour of GPU quota.** The Kaggle client writes the kernel
  log with the interpreter's locale encoding. Kernel output carries micromamba's
  progress glyphs, so on a default Windows install the write raised
  `UnicodeEncodeError` *after* the GPU work was done. The log is not the result:
  text writes now default to UTF-8 for the duration of the download, and a
  failure is a warning rather than the end of the run.
- **That empty run then overwrote twenty binders' worth of measurements** with
  dashes, while `binders/` still held the structures those measurements
  described. A summary recording no designs is now refused when the existing one
  records some, and is written to `results.failed.json` instead.
- The benchmark writes to a staging directory, so a failure cannot reach the
  committed artifacts at all.

### Fixed — the model checkpoints were unverified

- RFdiffusion's two checkpoints, about 480 MB of parameters that get loaded and
  executed, were fetched over **plain HTTP with no integrity check**, under a
  comment claiming they are "verified on download in the executor when a hash is
  supplied". No verification code existed at either download site. Both now hash
  every checkpoint, log the digest, and refuse a pinned mismatch; both use HTTPS.
  Hashing is unconditional because that is how a pin gets established — the first
  run publishes the digest into its own log.

### Fixed — bindsight is not a cancer tool, and now a test says so

- Every test, example and committed run used TCGA tumour-versus-normal, so the
  generality was asserted and never exercised. `tests/test_non_cancer_cohort.py`
  drives the documented path on a drug-versus-vehicle experiment paired within
  donor. It **failed on first run**: every manifest and report carried a caveat
  titled "Bulk expression can originate from non-tumour cells". The limitation is
  entirely general — a bulk contrast cannot say whether a transcript rose because
  the cells express more of it or because the arms hold different mixtures — and
  only the wording was oncological. It now states the general case and names the
  tumour-purity, treatment-selection and different-tissue instances as examples.
- The README states what the pipeline accepts, and which three parts are
  domain-specific: the optional GDC download, the rediscovery benchmark, and the
  human reference resources behind the safety gate.

### Fixed — claims that contradicted the tables beneath them

- **`.streamlit/config.toml` named the Hugging Face Space as covered** by its
  theme and its `gatherUsageStats = false`. The Space is a separate repository
  whose Dockerfile copied only `requirements.txt`, `src/` and `examples/`, so the
  file never arrived and neither setting ever applied to the hosted demo. That
  Dockerfile is now version-controlled at `.huggingface/Dockerfile`, copies the
  config, and is uploaded by the sync workflow.
- **ARCHITECTURE section 6 printed an invented Snakefile** — an `export_crate`
  rule that does not exist, every script misnamed, `deg` and `manifest` missing.
  Replaced with the real seven-rule DAG. The missing export rule is also the
  concrete reason the CLI and Snakemake paths are not interchangeable.
- **Section 7 was titled "verified"** above rows saying *not implemented*. It now
  carries a Status column, and three rows were wrong: Chai-1r cannot run on any
  free GPU, BoltzGen had never executed, and the surfaceome is 4,801 accessions.
- **Risk 7 claimed the approach "predictably finds known antigens."** The rebuilt
  study measures 1 of 17 at rank 20, interval 0.01 to 0.27.
- The README offered Colab, Modal and Kaggle as peers, and `bindsight run` told
  users to "run on Colab/Modal". Both now name the one backend that runs
  headlessly and free.
- **Pinning the accelerator to a T4 left `KaggleRunner` defaulting to P100**, so
  every Kaggle estimate applied a 3.0x slowdown where 4.0x was right,
  under-quoting by a quarter for a card no run would be given.

### Added — tests that pin the claims to the artifacts

- `tests/test_published_numbers_match_artifacts.py` reads the study and designer
  figures out of their `results.json` and requires every document that states
  them to match. The withdrawn headline was asserted on six surfaces at once;
  correcting one at a time is how a repository publishes two results.
- Writing it found the centrepiece table labelling a row `all` while counting 17
  of 22 pairs, with the printed question "Of every scored pair". The row now
  names the tier.
- `tests/test_requirements_mirror.py` fails when `requirements.txt` and the
  pyproject extras disagree. The file had already drifted both ways: it omitted
  `openpyxl`, without which the SURFY workbook cannot be parsed and discovery
  silently yields nothing, and carried `gql` and `seaborn`, which nothing
  imports. `pydantic-settings` was mandatory in the conda environment for
  nothing.

### Removed



- The Streamlit Community Cloud mirror (`bindsight.streamlit.app`) is no longer a
  supported deployment; the Hugging Face Space is the single hosted demo. The
  keep-warm workflow, README, JOSS and bioRxiv drafts and the docs site metadata now
  point only at the Space. The Streamlit code itself (`bindsight ui`, `streamlit_app.py`)
  is unchanged; the ``streamlit_app.py`` docstring no longer carries a Streamlit Cloud
  deployment recipe.
- Dead code that no caller reached: `bindsight.plugins.get_validator` and
  `AlphaFoldDBClient.fetch_many`.
- `paper/validation/DEFENSE_NOTES.md`, the README biography paragraph and the
  "sister projects" links to repositories that no longer exist.

### Changed

- Documentation no longer claims an optional R bridge to DESeq2/edgeR, RCSB/PDBe
  structure clients, single-cell input, a nightly test schedule, GPG-signed tags,
  PyPI publishing or a Zenodo deposit workflow — none of which exist in the code.
  `bindsight verify-licenses` drops the RCSB/PDBe row for the same reason.
- CONTRIBUTING describes the test markers, the release steps and the code of conduct
  as they actually are; `CODE_OF_CONDUCT.md` (Contributor Covenant 2.1) is added.
- The validation write-up quotes only numbers present in the committed benchmark
  artifacts and states that the absence of EGFR/CEA from the shortlist is a
  consistency check on the over-expression rule, not a specificity measurement.
- Package classifiers: Development Status 4 (Beta); Python 3.13 is not tested and is
  no longer listed.

## [0.2.2] - 2026-08-09

A distribution and metadata release. No code behaviour changes; the archived v0.2.1
snapshot still directed readers to a Hugging Face mirror that had not been rebuilt since
May 2026, and an archive is permanent, so the corrected pointers are cut into a release of
their own.

### Added

- Every release now ships a built wheel, an sdist and a `SHA256SUMS` file as release
  assets, so a pinned, verifiable build installs without PyPI:
  `pip install https://github.com/mikhaeelatefrizk/bindsight/releases/download/v0.2.2/bindsight-0.2.2-py3-none-any.whl`.
  `release-artifacts.yml` builds and attaches them automatically, and carries a PyPI job
  wired for trusted publishing (OIDC, no stored token) that stays inert until the project
  is registered as a trusted publisher.
- `sync-hf-space.yml` uploads this repository's own Space landing page to the Hugging Face
  Space and factory-rebuilds it on every release. A plain restart reuses the cached image
  and would keep serving whatever bindsight revision the last build resolved; only a
  factory reboot re-runs pip against `main`. Dormant, and skipped rather than failed, until
  an `HF_TOKEN` secret exists.
- `codemeta.json`, for software registries and citation indexers, pinned by tests to agree
  with `pyproject.toml` on version and licence and to cite the concept DOI.

### Changed

- The README leads with the surfaces that are current — the static results page and the
  Streamlit deploy, which tracks `main` — and states plainly that the Hugging Face mirror
  is serving an older build. Overstating a mirror's freshness is the same class of error
  v0.2.1 set out to fix.
- Install instructions document the release-asset and tagged `git+` paths, and checksum
  verification.

## [0.2.1] - 2026-08-09

A correctness-and-honesty release. No new capability: v0.2.1 fixes defects in what v0.2.0
already claimed to do, and corrects claims the evidence did not support.

> **Read this before quoting the binder numbers.** The 20 committed ERBB2 binders were
> produced *before* the ProteinMPNN target-chain fix in this release. They remain real,
> reproducible Boltz-2 output, but the protocol behind them was mis-set — see the first
> entry below, and the warning at the top of
> `benchmarks/designer_benchmark/RESULTS.md`.

### Fixed — ProteinMPNN was redesigning the target as well as the binder
- ProteinMPNN was invoked without `--pdb_path_chains`, so it treated **every** chain in the
  complex as designable and rewrote the target sequence alongside the binder. The binder was
  then optimised against a target surface that no longer matched the protein it was meant to
  bind, while the validator scored it against the native one. The target chain is now pinned
  and only the binder chain is redesigned.
- **The committed designer benchmark predates this fix and is not re-run here.** Its ipTM /
  PAE-interaction values are genuine and reproduce exactly from `results.json`, so nothing
  has been deleted or edited — but they are **provisional**: they measure designs optimised
  against a partly-invented HER2 domain IV, and cannot tell you whether that made them look
  better or worse than the corrected protocol will. `benchmarks/designer_benchmark/RESULTS.md`,
  `DESIGNER_BENCHMARK.md`, `ARCHITECTURE.md`, the docs home page and the README now say so at
  the point where the figures appear. A corrected re-run will supersede them.
- **Still to do:** `docs/results.md` is generated by `scripts/build_docs_results.py` and does
  not yet carry the caveat; the generator has to emit it so the committed page and the
  generator stay in sync (`tests/test_docs_results.py` enforces that).

### Fixed — every citation pointed at the wrong Zenodo record
- All 17 in-repo references cited a **version DOI** rather than the concept DOI — a
  snapshot under a different licence, containing neither the benchmarks nor the
  manuscripts. Anyone following the citation landed on a record that does not contain
  the work being cited. The specific identifier is not repeated here: it belongs to a
  deposit this repository does not have, and naming it would send a reader to it.
- Every reference now uses the **concept DOI `10.5281/zenodo.20121495`**, which always
  resolves to the latest archived version and is the correct identifier for citing "the
  software" rather than one release. Updated in the README badges, citation block and BibTeX,
  `CITATION.cff` (now also carrying `doi:` and `identifiers:`), `docs/index.md`,
  `paper/paper.bib`, `paper/README.md`, `paper/biorxiv/manuscript.tex`, `SECURITY.md` and
  `.huggingface/README.md`. Version labels read v0.2.1.

### Fixed — the bioRxiv manuscript stated the wrong licence
- `paper/biorxiv/manuscript.tex` described the software as "MIT-licensed" in the abstract,
  "licensed MIT throughout" in the quality-assurance section, and "(MIT license)" under code
  availability, while `LICENSE` and `pyproject.toml` are **AGPL-3.0-or-later**. A deposit-ready
  PDF misstating the licence is a legal defect, not a typo. Every statement now reads
  AGPL-3.0-or-later, with the permissive upstream components and the CC BY 4.0 manuscripts
  distinguished from the package licence.
- `paper/biorxiv/manuscript.pdf` is **stale** — it was compiled from the pre-correction source
  and must be recompiled before any deposit. `paper/README.md` now warns about this.

### Fixed — three wrong bibliography entries
- `Wohlwend2025` (Boltz-2) cited `10.1101/2025.01.20.633574`, which resolves to nothing (HTTP
  404); corrected to `10.1101/2025.06.14.659707`, "Boltz-2: Towards Accurate and Efficient
  Binding Affinity Prediction".
- `Khakzad2025` (SURFACE-Bind) is a **2026** article and its title is "Mapping targetable sites
  on the human surfaceome **for the design of novel binders**"; year and title corrected.
- `Stark2025` (BoltzGen) is titled "BoltzGen: Toward Universal Binder Design".
- Applied to both `paper/paper.bib` and `paper/biorxiv/references.bib`. The other 14 DOIs were
  verified and left alone.

### Fixed — the README's demo transcript was never produced by a real run
- Three of the four `INFO` lines matched no log statement in the code. It showed
  `DEGs: … enriching top 300 up-regulated` where `discover.py` logs `enriching top %d by
  combined score (π)`, and `SURFY cache empty; populating the full surfaceome list (2886)`,
  which describes network behaviour the vendored-list refactor removed — the surfaceome is now
  never fetched. The block is rewritten against the pipeline's actual format strings and is
  labelled **illustrative** rather than captured, since counts depend on the cohort. The
  surrounding prose no longer claims the first run downloads SURFY.
- The Hugging Face Space README said the JOSS paper and bioRxiv preprint were "currently in
  review"; neither has been submitted. It now says they are drafted.

### Changed — the headline claim is now one a reviewer can check
- "The first open-source pipeline that takes RNA-seq counts and outputs ranked de novo protein
  binder candidates" overstated the position: BindCraft, BinderFlow, `dl_binder_design` and
  nf-proteindesign are open binder-design workflows, and surfaceome / neoantigen pipelines
  (pVACtools, pan-cancer surfaceome screens) are open target-discovery workflows. What is
  unclaimed is the **join**. The claim now says bindsight runs both halves end-to-end and
  carries machine-readable provenance across the join, is qualified with "as far as we are
  aware", and names the prior art it is distinguishing itself from. Corrected in the README,
  `docs/index.md`, `docs/what-is-bindsight.md`, `paper/paper.md`,
  `paper/biorxiv/manuscript.tex` and the Hugging Face Space README.

### Changed — "specificity 2/2" is reported as what it is
- The 2/2 figure was presented as evidence that the pipeline keys on real over-expression
  rather than clinical fame. It cannot show that: antigens failing the over-expression rule
  (FDR < 0.05, log2fc ≥ 1.0) are excluded from candidacy **by construction**, so their absence
  from the top-20 is guaranteed by the design rather than earned by the ranking. It is now
  described as an internal consistency check on the documented rule, with a note on what
  measuring discrimination would actually require, in `docs/index.md`,
  `benchmarks/validation/RESULTS.md`, `paper/validation/manuscript.md`,
  `paper/validation/DEFENSE_NOTES.md`, `paper/paper.md`, `paper/biorxiv/manuscript.tex`,
  `paper/README.md`, `ARCHITECTURE.md` and the README. The generated `docs/results.md` still
  labels the figure "specificity"; that wording lives in `scripts/build_docs_results.py`
  (and `showcase.specificity`) and has to be changed there.

### Fixed — the discovery half could not populate the surfaceome at all
- **SURFY is now vendored.** The upstream spreadsheet is no longer retrievable: `wlab.ethz.ch`
  serves an HTML landing page (so pandas raised `BadZipFile: File is not a zip file`) and the
  relocated `wollscheidlab.org` serves a 132-byte Git-LFS pointer. With the default
  `surfy_allow_offline_fallback: false` a run hard-failed; with the demo's `true` it degraded
  silently to a **ten-protein** list, discarding 298 of 300 enriched genes as `not_surfaceome`
  and surfacing nothing. The full 2,886-accession list now ships in the package
  (`bindsight/surfaceome/data/surfy_v1.uniprot.txt`, CC BY 4.0, regenerated by
  `scripts/build_surfy_list.py`), and **discovery makes no network call for the surfaceome at
  all**. `bindsight demo` goes from `300 → 0` candidates to `301 → 32`.
- `populate_surfy_cache` survives as an explicit refresh path, with the `@retry` every other
  network client already had, and a content check that names what came back instead of
  `BadZipFile`.

### Fixed — the Snakemake front-end was dead, and had been for weeks
- `scripts/run_discover.py` called `_do_discover()` with six of its eight required
  keyword-only arguments, raising `TypeError` before doing any work; and
  `scripts/assemble_manifest.py` began with `from __future__ import annotations`, which
  Snakemake's script preamble pushes off line 1, so the manifest rule had **never** run. Both
  were hidden because `tests/test_snakemake_dag.py` was `slow`-marked and skipped in CI. It
  now runs offline, in CI, on every push.
- **Snakemake manifests are now real provenance.** They carried no inputs, no outputs, no
  sha256 digests, no params and no end timestamps — while `ARCHITECTURE.md` claimed the two
  front-ends produce identical artifacts. Both now build the same `StageRecord`s via the new
  `bindsight/provenance/fragments.py`.
- The manifest is assembled **before** the report renders. It used to be built afterwards, so
  every Snakemake-produced report shipped with an empty Provenance section.
- `scripts/run_rank.py` never passed `weights`, silently discarding the Snakefile's
  `params.rank` block.

### Fixed — runs and RO-Crates are now portable
- `<run>/structures/` was created by `run_dir()` and never written to, while
  `candidates.parquet` stored **absolute** cache paths — so a run, and every crate exported
  from one, was valid on exactly one machine. Structures are now copied into the run and
  referenced run-relatively (`io.paths.adopt_structure`), with `resolve_run_path` accepting
  both forms so existing runs keep working.
- `<run>/config.yaml` is written for the first time (the layout has always documented it), and
  the manifest's `config_path` points at it rather than at the counts *directory*.
- Crates now include the failure taxonomy, design metrics, per-target archives, per-binder
  validator output, the structures and the config, and carry the manifest's sha256 digests.

### Added — `--cheap` actually does something
- The flag was parsed and then never referenced, so a user asking for the cheap profile got
  the full-price run and `--dry-run` quoted A100 pricing. It now applies all three parts of
  the documented profile — `rfdiff_mpnn`, 10 trajectories, and a **new ESM-2 pre-screen**
  (`bindsight/design/prescreen.py`) applied between design and validation, the only point
  where dropping a design saves GPU. On the demo config against Modal the estimate goes from
  ~$27.89 to ~$4.26.
- The pre-screen is off unless `params.design.prescreen_top_k` is set, degrades to validating
  everything when the optional `embed` extra is missing, preserves design order, and records
  what it screened out.
- `DesignParams.gpu_type` is threaded into `cost.estimate_full_run`, which has always accepted
  the parameter and never had a caller pass it.

### Changed — CI actually enforces what the config asks for
- **mypy is blocking.** `pyproject` has set `strict = true` all along while CI ran
  `mypy bindsight || true`; 53 errors had accumulated behind it. Now zero across 70 files.
- **Coverage runs.** It was configured in `pyproject` and disabled by `--no-cov`. Now reported
  at 77%.
- `bindsight.report` resolves `render_run` lazily, so `report/theme.py` and
  `report/showcase.py` are genuinely stdlib-only as designed.

### Added — the presentation layer now shows the evidence
- **New "Real results" page in the web app.** `benchmarks/` already held the strongest evidence
  the project has — the rediscovery experiment across six real TCGA cohorts and 20 real ERBB2
  binders designed on a free Kaggle P100 — and none of it was reachable from the app. The page
  renders the rediscovery table, recall@k, the six cohort volcanoes, every scored design, the
  ESM-2 sequence-space projection, and the **actual Boltz-2 predicted complexes in 3-D** with the
  designed binder coloured against its target.
- **`bindsight/report/showcase.py`** — read-only loaders for the committed benchmark results, the
  single source of truth shared by the web app and the documentation site so the two can never
  disagree. Degrades to `None` when `benchmarks/` is absent (it is not shipped in the wheel).
- **`bindsight/report/theme.py`** and **`.streamlit/config.toml`** — one brand definition for the
  app, the HTML report, and the docs site, which had drifted into navy/navy/teal. The Streamlit
  theme also stops Streamlit's own chrome rendering in its default red against navy headings.
- **Documentation site is now the project's front door** — landing page, generated
  [Real results](https://mikhaeelatefrizk.github.io/bindsight/results/) page, logo, favicon, and a
  social-preview card. Links to the project previously previewed with no image anywhere.
- **`tests/test_webapp_smoke.py`** — the web app is exercised in CI for the first time. Previously
  only its *import* was checked, so any page could raise on render with CI still green.
- `tests/test_showcase.py` and `tests/test_docs_results.py` pin the published numbers (ERBB2 rank 4,
  20 designs, best ipTM 0.84, 50% success@0.65), so changing the committed benchmarks without
  updating the public surfaces is now a test failure.

### Fixed
- **Web-app results no longer vanish.** The app used no `st.session_state` at all, so demo and
  user-run output was rendered inside the button-click branch and disappeared the moment any other
  widget was touched — losing a completed run on your own cohort.
- **"Browse a run" is usable on the hosted deployments.** It asked for a server-side filesystem
  path, which a visitor to the Hugging Face Space or Streamlit Cloud does not have. It now lists
  local runs found by their provenance manifest.
- **Mobile navigation.** All navigation lives in the sidebar, which Streamlit collapses on phones,
  leaving mobile visitors with no visible way off the Home page. The sidebar state is now explicit
  and the stylesheet has real media queries — the module docstring had claimed phone support while
  containing no responsive rules.
- **Nine broken links on the live documentation site.** `mkdocs build` is now `--strict`, which
  immediately caught `../ARCHITECTURE.md`-style links in four pages that resolve nowhere once the
  site is built.
- `bindsight ui` now actually disables Streamlit telemetry, which its own help text has always
  promised.
- Docstrings that had drifted ahead of the code are corrected: the HTML report never embedded an
  NGL viewer, `report/streamlit_app.py` does not use `data_editor`, RO-Crate output is not
  bit-identical (only its payload files are), and `schemas/run_manifest.schema.json` does not exist.

### Fixed — post-v0.2.0 docs + packaging polish
- `bindsight ui` / `bindsight report --format streamlit` now work from a pip install: `streamlit`
  was missing from every `pyproject` extra (it lived only in `requirements.txt` and the conda env),
  so the documented `pip install -e ".[report]"` → `bindsight ui` quickstart failed. Added
  `streamlit>=1.36` to the `report` extra.
- Removed stale pre-v0.2 wording from the docs: `docs/what-is-bindsight.md` no longer frames the
  project as "v0.0.x / design half in flight"; the README Quickstart drops the `(v0.1+)` tags and
  the "60-second demo" label; `docs/how-to-use.md` + `docs/colab-design-howto.md` describe
  SURFACE-Bind as implemented and point at the real structure path; `SECURITY.md` de-pinned from
  v0.1.x; `CONTRIBUTING.md`'s smoke test now runs a command that exists. Reconciled the
  contradictory designer-benchmark figures inside CHANGELOG [0.2.0] to the shipped numbers.

## [0.2.0] - 2026-06-25

### Changed — relicensed to AGPL-3.0 (code) + CC BY 4.0 (docs); SPDX headers everywhere
- **bindsight is now licensed under the GNU Affero General Public License v3.0 or later
  (AGPL-3.0-or-later)** instead of MIT. It stays free and open-source, but the copyleft
  terms ensure anyone who distributes a modified version — **or runs one as a network
  service** — must release their corresponding source under the same license, preserving
  attribution. As sole copyright holder, the author can additionally grant commercial
  licenses on request. `LICENSE` now carries the full AGPL text; `pyproject.toml`
  (`License-Expression: AGPL-3.0-or-later`, deprecated license classifier dropped per
  PEP 639), `CITATION.cff`, `README`, `LICENSING.md`, `SECURITY.md`, the Streamlit/web UI,
  the docs-site metadata, the Hugging Face Space card, and the RO-Crate / provenance
  `ToolRef` license fields were all updated to match. Component (third-party tool) licenses
  are unchanged and remain documented in `LICENSING.md`.
- **Documentation, manuscripts, figures, and generated results** (`paper/`) are now licensed
  under **Creative Commons Attribution 4.0 (CC BY 4.0)** — see `paper/LICENSE`.
- Added **SPDX headers** (`SPDX-FileCopyrightText` + `SPDX-License-Identifier: AGPL-3.0-or-later`)
  to every first-party Python file (125 files), so the license and copyright travel with each
  source file. (The historical v0.1.0 bioRxiv preprint under `paper/biorxiv/` is left as-is —
  it accurately describes the MIT-era v0.1.0 release and its compiled PDF can't be regenerated
  here.)

### Fixed — Snakemake provenance manifest now populated + docs refreshed
- `scripts/assemble_manifest.py` now folds each per-rule `manifest_fragment.jsonld`
  (`{stage, status, metrics}`) into a real `bindsight.provenance.StageRecord`, so the
  Snakemake front-end's `run_manifest.jsonld` records the run's stages exactly like the
  Click CLI path does — previously it only logged the fragments and wrote an empty manifest.
  The assembly logic is a pure `assemble()` helper covered by `tests/test_assemble_manifest.py`
  (CI-safe, no Snakemake runtime); stale `v0.0.x` version references were removed.
- Documentation refreshed to match the shipped state: README "Status & roadmap" /
  "What works today" (the opt-in discovery-quality filters, developability, ESM-2 visualizer,
  honesty caveats) + repository layout (`pipelines/`, `config.py`); ARCHITECTURE module map
  (`pipelines/`, `benchmark/`, new submodules); and DESIGNER_BENCHMARK.md (PAE-interaction is
  now reported — mean 13.7 Å; `*_complex.cif` complexes replace the poly-glycine PDBs;
  SURFACE-Bind has landed). `examples/benchmark_held_out.yaml` surfaces the opt-in flags
  (commented, default off).

### Added — real Boltz-2 predicted binder complexes (+ PAE-interaction)
- `bindsight/runners/job_exec.py` now stages the Boltz-2 **predicted complex** (`*_model_0.cif`) plus
  the PAE / pLDDT arrays into the results tarball — previously only the confidence JSONs were kept, so
  the actual folded binder–target structures were lost — and fills `pae_interaction` (mean inter-chain
  PAE from the predicted PAE matrix). `score_run.py` stages those complexes into `binders/` as
  `<id>_complex.cif` and no longer stages the poly-glycine RFdiffusion backbones. Unit-tested in
  `tests/test_job_exec_retention.py`. New `--targets` flag on `run_designer_benchmark.py`.
- **Re-ran ERBB2 on the free P100 with the fix** → the committed designer benchmark now ships the
  **20 real folded Boltz-2 complexes** (`binders/*_complex.cif`): mean ipTM **0.59**, best **0.84**,
  **50 %** success@0.65, mean PAE-interaction **13.7 Å** (a fresh run — the v0.2.0 run's structures
  weren't retained). The misleading poly-glycine PDBs are removed; the developability and ESM-2
  embedding artifacts are regenerated from the new sequences so everything is consistent.

### Added — pLM embedding visualizer (ESM-2 → PCA, pre-GPU sequence space)
- New `bindsight/design/embeddings.py`: real protein-language-model embeddings via **ESM-2**
  (`facebook/esm2_t6_8M_UR50D`, CPU-capable) with mean-pooled per-protein vectors, plus a
  dependency-free NumPy `pca_2d` projection and a matplotlib `render_embedding_png`. Lets you *see*
  the designed-binder sequence space (which cluster / are outliers) before any GPU spend — the
  ProtSpace idea. ESM-2 lives behind a new optional extra `bindsight[embed]` (torch + transformers),
  kept out of `all` so the core stays CPU-lean; the PCA/PNG path needs no heavy deps.
- `benchmarks/designer_benchmark/embed_binders.py` produced real artifacts for the 20 ERBB2 binders:
  `binders/embedding_coords.tsv` + `binders/embedding_space.png` (real ESM-2 inference). Tests:
  `tests/test_embeddings.py` runs PCA/PNG on a committed real 20×320 ESM-2 fixture (CI-safe) and the
  live ESM-2 path under `importorskip` (verified locally).

### Added — binder developability scoring (sequence biophysics)
- New `bindsight/design/developability.py` computes deterministic, offline sequence descriptors:
  instability index, GRAVY, isoelectric point, aromaticity and molecular weight from Biopython
  ProtParam, plus length, total cysteine count and an aggregation-prone fraction (Kyte-Doolittle
  window) computed here. The composite `developability_score` ∈ [0,1] combines **three** of them —
  instability, GRAVY and the APR fraction; the rest are reported, not scored. (This entry said
  "free cysteines" and credited every descriptor to ProtParam; `n_cys` is the total count, pairing
  is not knowable from sequence alone, and three of the eight are computed in-module.) Wired into `rank/scoring.py` as a sequence-optional
  `score_developability` component (new `RankWeights.developability`; inert when no sequence column).
  `benchmarks/designer_benchmark/score_developability.py` computes it for the real committed binders
  → `binders/developability.tsv` (mean score 0.69, 11/20 predicted stable). Tests:
  `tests/test_developability.py` (exact ProtParam values on a real binder + rank integration).
  (T-cell-epitope / immunogenicity scoring is deliberately deferred — it needs a licensed/heavy MHC
  predictor this layer can't compute exactly offline.)

### Added — normal-tissue safety filter (GTEx, on-target/off-tumor toxicity)
- New `bindsight/targets/gtex.py` downloads + caches real GTEx v8 gene-median-TPM-by-tissue and
  exposes `max_expression(gene, tissues)`. A good antibody/ADC target is over-expressed in tumour
  but low in vital normal tissues; discovery previously only used Open Targets adverse-event counts
  and left the `vital_tissues` / `vital_tissue_max_tpm` config orphaned. Now, with opt-in
  `target_discovery.use_gtex_safety`, candidates whose median expression in any vital tissue exceeds
  the threshold are flagged `high_normal_tissue_expression` (new disposition) and dropped from design;
  `max_vital_tissue_tpm` is surfaced per candidate. Off by default (requires the GTEx download), so
  existing runs are unchanged. Tests: `tests/test_gtex.py` against a fixture built from real GTEx v8
  medians (ERBB2 ~47.8 TPM in lung — the trastuzumab cardiotox concern; NY-ESO-1/MAGEA4 = 0 in vital
  tissues) + gate tests in `tests/test_failure_taxonomy.py`.

### Added — topology-aware epitope selection (UniProt extracellular domain)
- New `bindsight/structures/topology.py` fetches real UniProt membrane topology (transmembrane,
  topological domains, signal peptide) and exposes the extracellular ranges. A binder can only
  reach the extracellular part of a surface protein, so when `target_discovery.use_uniprot_topology`
  is enabled discovery annotates each candidate's `extracellular_ranges` / `has_extracellular_domain`,
  targets the ECD for whole-surface design (`design_ranges`), and reports each SURFACE-Bind site's
  `fraction_extracellular`. Opt-in `require_extracellular_domain` drops non-accessible targets with a
  new `no_extracellular_domain` disposition. Both flags default off (UniProt network), so existing
  runs are unchanged. Tests: `tests/test_topology.py` against a real downloaded UniProt fixture
  (ERBB2 P04626) + gate/annotation tests in `tests/test_failure_taxonomy.py`.

### Added — disorder-aware filter (AlphaFold pLDDT)
- New `bindsight/structures/plddt.py` reads per-residue confidence (pLDDT) straight from the
  AlphaFold mmCIF B-factor column (no network, graceful on bad files). Discovery now surfaces a
  `mean_plddt` per candidate and a `mean_epitope_plddt` per epitope (don't design against a
  disordered region). A new opt-in `target_discovery.min_mean_plddt` gate (default 0 = off) drops
  models below the threshold with a new `low_confidence_structure` disposition in the failure
  taxonomy; the report shows pLDDT columns and the new disposition. Tests: `tests/test_plddt.py`
  (real fixture mmCIF) + a gate test in `tests/test_failure_taxonomy.py`.

### Added — first real de novo binders (designer benchmark populated)
- The designer benchmark now ships a **real result**, not an empty template:
  RFdiffusion → ProteinMPNN → Boltz-2, run on a **free Kaggle Tesla P100**, produced
  **20 binders** against ERBB2 extracellular domain IV (the trastuzumab epitope) —
  mean ipTM 0.59, best 0.84, 50 % pass ipTM ≥ 0.65 — at $0.
  **Those three figures are withdrawn.** That run invoked ProteinMPNN without
  `--pdb_path_chains`, so it redesigned the target chain as well as the binder;
  a corrected re-run on a T4 supersedes it with best ipTM 0.88, mean 0.51 and
  40 % success. This entry is left as the record of what v0.2.0 shipped.
  The designs (real Boltz-2-predicted complexes + FASTA),
  per-design metrics, `results.json`, and a populated `RESULTS.md` live in
  `benchmarks/designer_benchmark/`. New `prepare_erbb2_target.py` (extracts the
  domain-IV target from the AlphaFold model) and `score_run.py` (aggregates a returned
  results tarball into the committed artifacts).
- **Kaggle split-environment backend** (`bindsight/runners/kaggle_kernel.py`): the free
  Kaggle GPU is a P100 (sm_60) whose preinstalled stack runs neither RFdiffusion's
  legacy deps nor shares a Python env with the modern Boltz-2 validator, so the kernel
  builds two micromamba environments — `se3` (py3.9 / torch 1.12.1+cu113 → RFdiffusion +
  ProteinMPNN) and `boltz` (py3.11 / torch 2.2.2+cu118 → Boltz-2 + bindsight) — and runs
  `job_exec` across them. Boltz-2 is pinned to fp32 (the P100/T4 lack bfloat16).
- `bindsight/runners/tools.py`: the design and validator interpreters are overridable via
  `BINDSIGHT_DESIGN_PYTHON` / `BINDSIGHT_BOLTZ_BIN` — the minimal seam that lets one
  `job_exec` span a legacy designer env and a modern validator env (defaults unchanged).

### Fixed — Kaggle runner + Boltz-2 protein-binder validation
- `KaggleRunner.submit()` now embeds the spec + structure as base64 in a self-contained
  kernel instead of referencing a Kaggle dataset it never created; `poll()` reads the real
  `KernelWorkerStatus` enum (it previously mis-parsed the status and never saw completion).
- `job_exec` / `validate/boltz2.py`: disable Boltz-2 affinity for protein binders (it is
  ligand-only) and use valid single-letter chain IDs — previously Boltz-2 silently skipped
  every design, so all metrics came back null. ipTM is now produced; PAE-interaction and
  affinity are intentionally blank for protein binders.

### Added — negative-result taxonomy (failure modes as a first-class output)
- `bindsight/pipelines/discover.py` now emits `taxonomy/failure_taxonomy.parquet`:
  one disposition per differentially-expressed gene explaining why it did / didn't
  become a surfaced candidate — `not_significant`, `down_regulated`,
  `below_enrichment_cutoff`, `no_uniprot`, `not_surfaceome`, `fails_tractability`,
  `fails_safety`, `no_alphafold_model`, `not_top_n`, `no_surface_bind_site`,
  `surfaced`. The funnel is **exhaustive** (counts sum to the DEG total), so the
  failure modes are auditable rather than silently discarded. The HTML report
  renders a "Why candidates dropped" breakdown, and the per-disposition counts
  land in the run manifest. New `tests/test_failure_taxonomy.py`.

### Added — rediscovery validation + designer benchmark
- **Rediscovery validation** on six real indication-matched TCGA cohorts
  (`bindsight/benchmark/rediscovery.py`, driver `benchmarks/run_validation.py`,
  artifacts in `benchmarks/validation/`, write-up in `paper/validation/`). The
  discovery half resurfaces **ERBB2 at rank 4** in HER2-enriched breast cancer
  (PAM50-stratified) and is specific — antigens not transcriptionally
  over-expressed at the bulk level (EGFR, CEA) are correctly not surfaced.
  Results are grouped by *measured* over-expression under a uniform pre-stated
  rule; every number is produced by the runs, none hand-set.
- **cBioPortal PAM50 fetcher** (`bindsight/io/cbioportal.py`) and a GDC fetcher
  extension to select STAR-Counts by explicit case barcodes (subtype-stratified
  cohorts). Eval set extended with CEACAM5 (CEA) and NECTIN4 (Padcev target).
- **Three-way designer benchmark** harness + protocol
  (`bindsight/benchmark/designer_bench.py`, `benchmarks/designer_benchmark/`):
  RFdiffusion+ProteinMPNN vs BindCraft vs BoltzGen on a shared target set,
  CPU-tested with the mock backend, runnable for real on a GPU backend (the
  `rfdiff_mpnn` arm is now populated with a real run — see *first real de novo
  binders* above; the empty template is gone).
- **Free-GPU design path made runnable**: bindsight installs from GitHub (it is
  not on PyPI) and a $0 Kaggle runbook
  (`benchmarks/designer_benchmark/RUN_FREE_GPU.md`) walks through producing real
  binders on a free P100 via the split-environment kernel.

### Added — SURFACE-Bind targetable-site lookup
- **SURFACE-Bind site lookup implemented** (`bindsight/epitopes/surface_bind.py`):
  `SurfaceBindClient.has/sites/metadata` read a *vendored* data tree
  (`data/surface_bind/sites/<UNIPROT>/sites.json`; user-supplied — SURFACE-Bind
  has no public API). Wired into discovery (`pipelines/discover.py`): top-N
  candidates get real epitope residues when a qualifying site exists (focused
  RFdiffusion design), filtered by `min_surface_bind_score`, and
  `require_surface_bind_site` carries only sited candidates when data is vendored.
  With no vendored data, discovery falls back to whole-surface design and records
  an honest `epitope_status` (`surface_bind_site` / `no_surface_bind_site` /
  `surface_bind_not_configured`); the pinned commit SHA is exposed via
  `client.metadata()` for provenance.

### Changed — discovery ranking, license audit
- Discovery now ranks candidates by the combined DE score π = log2fc × −log10(padj)
  (Xiao et al. 2014), matching the documented intent (the code previously sorted
  by raw fold-change only). This moves strongly-and-confidently over-expressed
  antigens up the shortlist (e.g. ERBB2 in HER2-enriched breast: rank 25 → 4).
- `bindsight verify-licenses --config <cfg>` now performs a real per-config
  audit (resolves the chosen designer/validator/backend and flags any
  non-commercial component) instead of a stub.

### Removed — repository cleanup
- Removed ops/marketing residue not meant for a public scientific repo:
  `GO_LIVE.ps1`, `tools/keep-warm/`, `announcement/`, `CUSTOM_DOMAIN.md`,
  `PUBLISH_PYPI.md`, a redundant keep-warm workflow, and `docs/hf-spaces-deploy.md`
  / `docs/keeping-the-demo-warm.md` (with their dangling references). Fixed the
  PyPI `Homepage`/`Documentation` URLs to point at the live docs site.

### Added — docs site, container image, eval-set enrichment
- **mkdocs-material documentation site** (`mkdocs.yml` + `docs/index.md`) with a
  GitHub Pages deploy workflow (`.github/workflows/docs.yml`) and a `docs` extra.
- **Dockerfile** (CPU image for the discovery half + CLI) + a `Docker` workflow
  that builds it on every PR and publishes to GHCR on `main`/tags.
- Held-out eval set extended with **FOLH1/PSMA** (prostate, `Q04609`); the
  bundled ENSG→UniProt map gained FOLH1, CD33, and CD123/IL3RA so offline runs
  resolve those real targets.

### Changed — the demo now runs on REAL data
- **`bindsight demo` runs on a real TCGA-BRCA cohort** (NIH/GDC), not synthetic
  counts. A new GDC fetcher (`bindsight.io.gdc`) auto-downloads a tumor-vs-
  adjacent-normal STAR-Counts cohort on first run (cached after), the full
  ~2,886-protein SURFY surfaceome is auto-populated
  (`surfaceome.populate_surfy_cache`), and the top up-regulated DEGs are enriched
  via Open Targets — a genuine surfaceome-wide discovery with full provenance
  (`provenance.json` with GDC UUIDs + SHA-256). The fabricated
  `examples/demo/counts.tsv`/`design.tsv` are deleted. Config gains
  `inputs.download` (`bindsight.config.GDCSource`).
- Discovery scales to real cohorts: enrichment is capped to the top up-regulated
  DEGs and AlphaFold structures are fetched only for the carried-forward
  candidates.

### Changed — Snakemake front-end is now real
- The `Snakefile` + `scripts/run_*.py` were stubs (they wrote
  `"This is a placeholder"`) and never actually ran (a `from __future__` import
  ordering bug broke them under Snakemake's script wrapper). They now call the
  same `bindsight.*` pipeline functions as the CLI, so `snakemake --configfile
  <cfg> --cores N` runs discover → design → validate → rank → report → manifest
  end-to-end. Added a `workflow` extra and a Snakemake E2E test. Docs corrected:
  the CLI and Snakemake are two equivalent front-ends over the same functions
  (the CLI does **not** "drive Snakemake").
- The `mock` backend now emits a realistically-shaped results tarball
  (metrics.jsonl + per-binder dirs) so the whole orchestration runs E2E in CI.

### Docs
- Swept the docs/README/paper/announcements for stale claims now that the
  design half and Snakemake are real: removed "v0.1+/coming/stub/templated"
  language, fixed the version (`0.0.1.dev0` → `0.1.0`), "Quarto" → the actual
  self-contained HTML report, and the "synthetic 10-gene demo" → the real
  TCGA-BRCA demo. SURFACE-Bind targetable-site prediction is stated honestly as
  a roadmap item (the design step targets the whole surface today).

### Added — real design pipeline (all plugins, zero stubs)
- **RFdiffusion → ProteinMPNN → Boltz-2 run end-to-end for real** via a single
  executor (`bindsight.runners.job_exec`) shared by every backend. The Modal,
  local/Docker, and Kaggle runners now genuinely submit + fetch (no more
  `NotImplementedError`); the Colab notebook is a thin wrapper over the same
  executor. Commands + parsers live once in `bindsight.runners.tools` (pinned
  real upstream commit SHAs). `bindsight design`/`validate` actually launch and
  materialise `validated.parquet`.
- **All alternative plugins implemented for real** (no stubs): BindCraft +
  BoltzGen designers, Chai-1r + AF2-IG validators (AF2-IG keeps its
  non-commercial banner), and the Kaggle runner.

### Fixed
- **CLDN6 accession corrected**: the bundled map listed `Q14953` for CLDN6, but
  `Q14953` is **KIR2DS5**. The correct CLDN6 accession is **`P56747`**
  (`ENSG00000184697`); MSLN's gene id is corrected to `ENSG00000102854`
  (was `ENSG00000133110` = POSTN). Both verified against UniProt/Ensembl.
- **AlphaFoldDB model version** bumped `v4 → v6` (the old URLs now 404), so
  structure fetching works again.
- `parse_boltz_output` searches recursively (Boltz writes to
  `predictions/<name>/`), the target structure is now actually shipped to the
  GPU, and the designer's `metrics.jsonl` path is populated.

### Added — held-out evaluation set + benchmark tooling
- **Real held-out evaluation set** under `benchmarks/`: literature-validated
  binders for the AML targets **CD33** (P20138) and **CD123/IL3RA** (P26951) —
  gemtuzumab ozogamicin, lintuzumab, vadastuximab talirine, tagraxofusp,
  talacotuzumab/CSL362, flotetuzumab — plus the solid-tumor antigens HER2, EGFR,
  MSLN and CLDN6. Every binder carries a verifiable citation (ChEMBL / NCT /
  PMID / DOI / PDB); five structurally-resolved binders ship byte-exact VH/VL
  sequences pulled from their PDB co-crystals (`9VL2`, `4JZJ`, `1N8Z`, `1S78`,
  `1YY9`). `benchmarks/build_eval_set.py` regenerates everything from the public
  sources with full provenance + SHA-256 (`benchmarks/sources.json`,
  `benchmarks/PROVENANCE.md`).
- **`bindsight benchmark` command** (`bindsight.benchmark`): scores one or more
  finished run dirs by the rank of each known antigen in the candidate
  shortlist, computes recall@k, and renders a side-by-side HTML report — the
  workflow `docs/use-cases.md` referenced but never shipped.
- **`examples/benchmark_held_out.yaml`**: the held-out benchmark run config the
  docs referenced (previously missing).

### Fixed
- **CLDN6 accession corrected**: the bundled map listed `Q14953` for CLDN6, but
  `Q14953` is **KIR2DS5**. The correct CLDN6 accession is **`P56747`**
  (`ENSG00000184697`), verified against UniProt.

## [0.1.0] - 2026-05-11

The "real invention" release. Every CLI command works end-to-end (no
``_not_implemented`` calls). The Colab notebook generated by
``bindsight design --backend colab`` contains real RFdiffusion +
ProteinMPNN + Boltz-2 install + inference cells (patterned on the upstream
ColabDesign / dl_binder_design notebooks). A polished multi-page web UI
launches via ``bindsight ui`` and is one-click deployable to Streamlit
Cloud.

### Added — v0.1.0 highlights
- **Web UI** (`bindsight.report.webapp`): multi-page Streamlit app with
  Home / Demo / "Run on my data" / Browse / About pages. Polished CSS,
  inline volcano plot rendering, embedded HTML report viewer, file upload
  for user data, downloadable Parquet artifacts. Same app deploys to
  Streamlit Cloud via the root-level ``streamlit_app.py`` + ``requirements.txt``.
- **`bindsight ui` CLI command** — launches the local Streamlit server
  with the right port, headless flag, and clear output URL.
- **Real ranking module** (`bindsight.rank.scoring`): `rank_validated()`
  + `rank_run()` produce a composite score from iPTM, pAE_interaction,
  RMSD, affinity prediction, and DE evidence. Configurable weights;
  graceful when columns are missing. Output Parquet has both the
  composite and every component for downstream re-ranking.
- **Real RO-Crate exporter** (`bindsight.export.ro_crate`): emits a
  ``.crate.zip`` with `ro-crate-metadata.json` (RO-Crate 1.1 spec) and
  `software.bib` listing every upstream tool used in the run. Ready for
  direct Zenodo deposit.
- **Real full-pipeline orchestrator** (`bindsight.pipelines.full_run`):
  drives discover → design (artifact check) → validate (artifact check)
  → rank → report → export. Skip flags per stage; CPU stages always
  execute; GPU stages run when artifacts are present.
- **Real Boltz-2 validator** (`bindsight.validate.boltz2`): JSON parser
  for Boltz-2 output (``confidence_*.json`` + ``affinity_*.json``).
  Builds the Boltz YAML config from a target+binder pair. Raises
  ``MissingValidationError`` with a clear pointer to the GPU step when
  output is missing.
- **Real Colab design notebook** (`bindsight.runners.notebook_content`):
  16-cell notebook with proper RFdiffusion install (with weight
  downloads from IPD), ProteinMPNN install, Boltz-2 install via pip,
  spec loading, inference, packaging. Patterned on ColabDesign and
  dl_binder_design.
- **`bindsight run` CLI** wired to the orchestrator with `--dry-run`
  cost estimate.
- **`bindsight export` CLI** wired to the RO-Crate emitter.
- **`bindsight rank` CLI** wired to the scoring module.
- **`bindsight validate` CLI** prints clear "GPU step pending" panel
  pointing to the Colab notebook + how-to doc; exits 0.
- 18 new tests (rank, export, full_run): **175 fast tests passing** in
  under 4 minutes.

### Changed
- **Renamed** package: `xpr2bind` → `bindsight`. PyPI name, package
  directory, all imports, entry points, env vars (`BINDSIGHT_SURFACE_BIND_DATA`),
  conda env names, citation metadata, all docs.
- **Bumped version**: 0.0.1.dev0 → 0.1.0.
- **Removed** every `_not_implemented` call from `bindsight rank`,
  `bindsight run`, `bindsight export`. The CLI is now real end-to-end.

### Added — Phase 3 "perfect demo" (2026-05-11)
- **`bindsight demo`** — one-command end-to-end run on a shipped 10-gene
  tumor-vs-normal cohort. Takes ~30 s on a CPU laptop, no internet required,
  no GPU required. The pipeline rediscovers ERBB2 (HER2) and EGFR as top
  antibody-tractable surface antigens, producing a real HTML report.
- **`examples/demo/`** — bundled `counts.tsv`, `design.tsv`, `config.yaml`
  for the demo. Files ship with the wheel via `[tool.hatch.build.targets.wheel.force-include]`.
- **`bindsight.report.html.render_run`** — paper-style HTML report renderer.
  Self-contained single-file output: embedded CSS, base64 PNG volcano plot,
  candidates table with badges, epitopes table, full PROV-O provenance table,
  styled to look like a Nature methods page. Pure jinja2 + matplotlib, no
  Quarto / Jupyter dependency.
- **`bindsight.report.streamlit_app`** — interactive Streamlit dashboard for
  browsing a run. Launched via `bindsight report <run> --format streamlit`.
- **`bindsight report`** is now wired (was stub).
- **`bindsight.targets.ensembl_uniprot`** — bundled offline ENSG → UniProt
  fallback map (~15 well-known cancer surface antigens + drivers). Used when
  Open Targets is disabled or unreachable; status `bundled_fallback` is
  recorded in the candidates table.
- **`docs/colab-design-howto.md`** — step-by-step recipe for running
  RFdiffusion + ProteinMPNN + Boltz-2 on Colab against a `bindsight` discover
  output. Documents the manual flow until live runner integration in v0.1.0-rc2.
- **README polished**: feature matrix showing what works today vs. what's
  pending; 60-second quickstart; cleaner install instructions.
- 18 new tests (demo E2E, ensembl_uniprot fallback, HTML report renderer,
  CLI demo + report). Total: **156 fast tests passing**, all green.
- Windows console fix: `sys.stdout.reconfigure(encoding='utf-8')` at CLI
  startup so Rich box-drawing chars + ≥/×/→ glyphs render on cp1252 terminals
  without crashing.

### Added — Phase 2 GPU-half scaffold (2026-05-10)
- `bindsight.cost` — real GPU cost estimator. Pricing table for Modal /
  Colab Pro+ / Kaggle / local across A100 / H100 / L4 / T4 / RTX4090 etc.
  Per-designer + per-validator timing tables (45 s/trajectory for
  RFdiff+MPNN, 240 s for BindCraft, 20 s/design for Boltz-2). Powers
  `--dry-run`. 15 tests.
- `bindsight.runners.notebook` — Jinja2-backed Jupyter notebook builder
  (envelope, code/markdown cells, strict-undefined rendering).
- `bindsight.runners.colab` — real Colab runner. Builds a self-contained
  `.ipynb` Jupyter notebook with Colab GPU metadata, install + spec +
  designer + package cells; user runs it and drops the resulting tarball
  back into the results directory for `poll`/`fetch` to detect. 6 tests.
- `bindsight.runners.modal_runner`, `bindsight.runners.kaggle`,
  `bindsight.runners.local_docker` — runner stubs with working cost
  estimators. Live `submit` lands in v0.1.0-rc2. 5 tests.
- Designer plugins (entry-point registered):
  - `bindsight.design.rfdiff_mpnn` — default designer. Real cache-key
    construction; mock-runner round-trip works today (real RFdiffusion in
    v0.1.0-rc2).
  - `bindsight.design.bindcraft` — premium designer (≥32 GB VRAM), stub.
  - `bindsight.design.boltzgen` — newest designer (MIT weights), stub.
- Validator plugins (entry-point registered):
  - `bindsight.validate.boltz2` — default validator.
  - `bindsight.validate.chai1r` — alt for cross-model agreement.
  - `bindsight.validate.af2_ig` — opt-in (non-commercial weights, license
    banner shown by CLI).
- 14 designer/validator tests including entry-point loader checks against
  pyproject.toml.
- `bindsight design` now prints a Rich cost panel before exiting; with
  `--dry-run` it returns 0 cleanly.
- `bindsight validate` now prints a Rich cost panel.
- Total: 124 fast tests + 1 slow real-pydeseq2 test, all green.

### Added — docs (2026-05-10)
- `docs/what-is-bindsight.md` — 5-minute pitch / "deal-breaker" explanation.
- `docs/how-to-use.md` — end-to-end user guide with troubleshooting.
- `docs/use-cases.md` — four sized scenarios.
- README links the three docs at the top.

### Added — Phase 1 wiring (2026-05-09 batch 2)
- `bindsight.config` — Pydantic v2 `RunConfig` + per-stage param models with
  YAML loader. Validates the bundled `examples/tcga_luad.yaml` and rejects
  extras at every level so config drift fails loudly.
- `bindsight.deg.pydeseq2_runner.PyDESeq2Runner` — real pydeseq2 wrapper.
  Standardised Parquet output schema documented in the module docstring.
  ``slow`` test against the tiny fixture confirms end-to-end works.
- `bindsight.pipelines.discover` — orchestrator that joins:
  DEGs → Open Targets enrichment → SURFY surfaceome filter → tractability +
  safety filters → AlphaFoldDB structure pull → top-N ranking. Emits
  `targets/candidates.parquet`, `epitopes/epitopes.parquet`, and a per-run
  `run_manifest.jsonld` with PROV-O records for both stages.
- `bindsight discover` is now wired to the real pipeline (no longer a stub).
- `bindsight doctor` — diagnoses Python, optional deps, cache state, and
  vendored data root. Saves users from "why doesn't this work" tickets.
- `scripts/run_deg.py` and `scripts/run_discover.py` now call the real
  pipeline, not stubs.
- 24 new tests (config, deg runner, discover pipeline, doctor): 81/81 pass.
- `RENAME.md` — checklist for the eventual rename pass before publishing.

### Changed
- `bindsight discover` exits non-zero with a Pydantic ValidationError if the
  config is malformed (was: stub no-op).

### Added — Initial scaffold (2026-05-09 batch 1)
- Repository scaffold: README, ARCHITECTURE, LICENSING, CONTRIBUTING, CITATION.cff, LICENSE
- Python package skeleton with all module stubs (`io`, `deg`, `targets`, `surfaceome`, `structures`, `epitopes`, `design`, `runners`, `validate`, `rank`, `provenance`, `report`)
- `bindsight.provenance.manifest` — Pydantic v2 schema for `run_manifest.jsonld` (PROV-O JSON-LD)
- `bindsight` CLI shell (Click) with stubs for `discover`, `design`, `validate`, `rank`, `report`, `run`, `export`, `verify-licenses`
- Snakefile skeleton with `discover` rule
- Conda env `envs/discover.yaml` for the CPU discovery half
- Example pipeline config `examples/tcga_luad.yaml`
- pytest smoke test for the manifest schema
- GitHub Actions CI workflow (lint + test)
- `.gitignore`, `.editorconfig`

### Changed
- N/A (initial release)

### Removed
- N/A (initial release)

---

## [0.0.1-dev] - 2026-05-09

Initial scaffold. Not functional yet — see Phase 0 in [ARCHITECTURE.md](ARCHITECTURE.md#11-phased-roadmap).

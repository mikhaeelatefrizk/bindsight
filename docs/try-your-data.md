---
description: Check a counts matrix and a sample design table against what bindsight expects — entirely in your browser. Nothing is uploaded.
---

# Try your data

A counts matrix and a sample design table naming a two-level factor. Nothing on
this path knows about cancer — `tumor` and `normal` are values you supply, not
values the code expects.

**Nothing here is uploaded.** The files are read in your browser with
`File.slice().text()` and never leave your machine: this page has no upload, no
form action and makes no network request of any kind. It runs the same checker
`bindsight ui` runs, from the same file.

<div class="bs-card" markdown="0">
  <div class="bs-field">
    <label for="counts">Counts matrix <span class="bs-muted">(.tsv, .txt, .gz)</span></label>
    <input type="file" id="counts" accept=".tsv,.txt,.gz">
    <p class="bs-field__help">Genes as rows, samples as columns, integer counts.</p>
  </div>
  <div class="bs-field">
    <label for="design">Sample design table <span class="bs-muted">(.tsv, .txt, .gz)</span></label>
    <input type="file" id="design" accept=".tsv,.txt,.gz">
    <p class="bs-field__help">One row per sample, with a column naming the condition.</p>
  </div>
  <div id="checks"></div>
</div>

Files are checked the moment you choose them — shape, separator, and whether the
sample names in the two tables agree. The contrast levels are read from your
design file and offered back to you rather than typed: a mistyped level used to
surface as a generic pipeline failure minutes later, after the cohort had
already been processed.

If the checks pass, the same files will run under
[`bindsight discover`](how-to-use.md).

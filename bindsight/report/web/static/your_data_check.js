// SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// Check a counts matrix and a sample design table -- entirely in the browser.
//
// Authored once and loaded by two surfaces: `bindsight ui` (templates/
// your_data.html.j2) and the published documentation site (docs/try-your-data.md).
// Neither owns it, because two copies of one checker diverge and the published
// one would be the copy that silently stopped matching what the pipeline does.
//
// Nothing here uploads anything. There is no fetch, no XHR, no form action: the
// files are read with File.slice().text() and never leave the machine. That is
// a stronger promise on a public website than it was on localhost, and it is
// the reason this file may never grow a network call --
// tests/test_web_ui.py asserts exactly that.
//
// Every value this page shows comes from the reader's own files: the filename,
// the column headers, the cell values it reads as contrast levels. Those are
// composed as DOM nodes with textContent, never concatenated into markup. This
// file did concatenate them, and was then published on a public site, which
// turned "a filename is whatever the user typed" into script execution in the
// documentation's origin -- from a `.tsv` handed to someone by a stranger. The
// rule that replaced it is mechanical rather than careful: `innerHTML` is only
// ever assigned the empty string, and tests/test_web_ui.py fails any authored
// script that assigns anything else. Careful was what produced the bug.
//
// The contract with both surfaces is three element ids: `counts`, `design`
// and `checks`.

// --- nodes, not markup ------------------------------------------------------

function el(tag, className) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  return node;
}

function t(value) {
  return document.createTextNode(String(value));
}

function code(value) {
  const node = el("code");
  node.textContent = String(value);
  return node;
}

function strong(value) {
  const node = el("strong");
  node.textContent = String(value);
  return node;
}

function br() {
  return el("br");
}

// Parsed in the browser. A header and a few hundred rows are enough to tell a
// reader whether this is the file they meant, and it costs no round trip and no
// upload of data that may be sensitive.
async function head(file, n) {
  const text = await file.slice(0, 256 * 1024).text();
  return text.split(/\r?\n/).filter(function (l) { return l.trim(); }).slice(0, n);
}

function card(title, bodyNodes, kind) {
  const glyph = kind === "ok" ? "✓" : kind === "warn" ? "!" : "✗";
  const note = el("div", "note note--" + kind);

  const mark = el("span", "note__glyph");
  mark.setAttribute("aria-hidden", "true");
  mark.textContent = glyph;

  const wrap = el("div", "note__body");
  const heading = el("p");
  heading.style.margin = "0";
  heading.appendChild(strong(title));

  const body = el("div", "small");
  bodyNodes.forEach(function (node) {
    if (node) body.appendChild(node);
  });

  wrap.appendChild(heading);
  wrap.appendChild(body);
  note.appendChild(mark);
  note.appendChild(wrap);
  return note;
}

function splitRow(line) {
  return line.indexOf("\t") >= 0 ? line.split("\t") : line.split(/\s*,\s*/);
}

// Which run is allowed to render. Choosing both files fires two `change`
// events, so two runs are in flight at once and each awaits a file read. The
// older one must not write: while this built one string and assigned it at the
// end, a slow first run would overwrite the fresh verdict with a stale one;
// appending nodes instead, it would append a second copy of its cards. Neither
// is what the reader asked for, so the stale run returns without drawing.
var latestRun = 0;

async function check() {
  const thisRun = ++latestRun;
  // Reset every run: a fixed file must clear the previous verdict.
  var designBlocked = false;
  const counts = document.getElementById("counts").files[0];
  const design = document.getElementById("design").files[0];
  const out = document.getElementById("checks");
  if (!counts && !design) {
    out.innerHTML = "";
    return;
  }

  const cards = [];
  let countsSamples = null;

  if (counts) {
    if (counts.name.endsWith(".gz")) {
      cards.push(
        card("Counts matrix", [t(counts.name + " — compressed; checked when the run starts.")], "ok")
      );
    } else {
      const rows = await head(counts, 5);
      const header = rows.length ? splitRow(rows[0]) : [];
      countsSamples = header.slice(1);
      const thin = header.length < 3;
      const body = [
        t(counts.name),
        br(),
        t(
          header.length + " columns, " + (header.length - 1) + " samples, " +
            (rows.length - 1) + "+ genes read."
        ),
      ];
      if (thin) {
        body.push(t(" "), strong("That is too few columns"), t(" — is the file tab-separated?"));
      }
      cards.push(card("Counts matrix", body, thin ? "warn" : "ok"));
    }
  }

  if (design) {
    const rows = await head(design, 500);
    if (rows.length) {
      const header = splitRow(rows[0]);
      const body = rows.slice(1).map(splitRow);

      // Every two-level column, not just the winner. This used to keep only
      // the first match (preferring a name containing "cond") and report it as
      // "Two-level factor: x" with a tick. A design table whose `condition`
      // column has one level and whose `batch` column has two was therefore
      // reported ready to run -- against `batch` -- and the run it recommends
      // would contrast a technical covariate and return plausible genes
      // answering a question nobody asked.
      const candidates = [];
      const conditionish = [];
      header.forEach(function (name, i) {
        const values = Array.from(new Set(body.map(function (r) { return r[i]; }).filter(Boolean)));
        const named = name.toLowerCase().indexOf("cond") >= 0 || name.toLowerCase() === "group";
        if (named) { conditionish.push({ name: name, count: values.length }); }
        if (values.length === 2) {
          candidates.push({ name: name, levels: values, named: named });
        }
      });
      const named = candidates.filter(function (c) { return c.named; });
      const chosen = named.length ? named[0] : candidates[0] || null;
      const factor = chosen ? chosen.name : null;
      const levels = chosen ? chosen.levels : null;
      // Not a count of alternatives. The question is whether the page had any
      // basis for its pick beyond "this column happens to hold two values". A
      // name that reads as a condition is a basis; nothing else is, however few
      // columns were in the running. The case that prompted this had exactly
      // one candidate -- a `batch` column, in a file whose `condition` column
      // held a single level -- and reported it with a tick.
      const guessed = !!chosen && !chosen.named;

      const parts = [
        t(design.name),
        br(),
        t(body.length + " samples, " + header.length + " columns."),
      ];

      if (factor) {
        parts.push(br(), t("Two-level factor: "), code(factor), t(" — "));
        levels.forEach(function (l, i) {
          if (i) parts.push(t(" against "));
          parts.push(code(l));
        });

        const field = el("div", "field");
        field.style.marginTop = ".75rem";
        const label = el("label");
        label.setAttribute("for", "num");
        label.textContent = "Contrast";
        const select = el("select");
        select.id = "num";
        levels.forEach(function (l) {
          const option = el("option");
          // Set as properties. The value a reader's file supplied is data, and
          // an attribute built by concatenation is the one place a level like
          // `" onmouseover="…` escapes its quotes without ever using an angle
          // bracket -- which is why escaping-on-the-way-in was not the fix.
          option.value = String(l);
          option.textContent = String(l);
          select.appendChild(option);
        });
        field.appendChild(label);
        field.appendChild(select);
        parts.push(field);

        if (candidates.length > 1) {
          parts.push(br(), t("Columns with exactly two values: "));
          candidates.forEach(function (c, i) {
            if (i) parts.push(t(", "));
            parts.push(code(c.name));
          });
          parts.push(t("."));
        }
        if (guessed) {
          // The user's own factor, named, because that is what they have to fix.
          const wrongLevels = conditionish.filter(function (c) { return c.count !== 2; });
          parts.push(
            br(),
            strong("This column was chosen because it has two values, not because it is your factor."),
            t(" ")
          );
          if (wrongLevels.length) {
            parts.push(
              t("The column you probably meant, "),
              code(wrongLevels[0].name),
              t(
                ", holds " + wrongLevels[0].count +
                  (wrongLevels[0].count === 1 ? " level" : " levels") +
                  ", and a contrast needs exactly two. "
              )
            );
          } else {
            parts.push(t("No column here is named like a condition. "));
          }
          parts.push(
            t(
              "The pipeline contrasts whichever column your config names — check " +
                "that it is the comparison you mean."
            )
          );
        }
      } else {
        parts.push(
          br(),
          strong("No two-level column found."),
          t(" The contrast needs a column with exactly two distinct values.")
        );
      }

      // Three states, not two. The two files usually come from different
      // exports, so a name mismatch is the ordinary way this goes wrong.
      var overlap = null;
      if (countsSamples && countsSamples.length) {
        const designSamples = body.map(function (r) { return r[0]; }).filter(Boolean);
        const shared = designSamples.filter(function (s) { return countsSamples.indexOf(s) >= 0; });
        overlap = { shared: shared.length, total: designSamples.length };
        parts.push(
          br(),
          t("Sample names shared with the counts matrix: "),
          strong(shared.length),
          t(" of " + designSamples.length)
        );
        if (shared.length === 0) {
          parts.push(
            t(" — "),
            strong("none match"),
            t(
              ", so the contrast cannot be built. The two files are probably from" +
                " different exports; the design's first column has to hold the" +
                " counts matrix's column headers."
            )
          );
        } else if (shared.length < designSamples.length) {
          parts.push(
            t(
              " — the other " + (designSamples.length - shared.length) +
                " are not columns of the counts matrix and will be dropped."
            )
          );
        }
      }

      // The severity follows the finding. Marking this OK beside "the contrast
      // cannot be built" is the failure this page exists to prevent, one step
      // earlier in the pipeline.
      var blocked = !factor || (overlap && overlap.shared === 0);
      // A guessed factor is not a clean bill of health: the page chose by
      // column order, and only the reader knows whether that is the biology.
      var partial =
        guessed || (overlap && overlap.shared > 0 && overlap.shared < overlap.total);
      cards.push(card("Design table", parts, blocked ? "err" : partial ? "warn" : "ok"));
      designBlocked = blocked;
    }
  }

  if (counts && design) {
    const privacy =
      "Nothing on this page was sent anywhere — the checks above ran in this " +
      "browser, on the first 256 kB of each file, so a counts matrix of " +
      "patient data never left the machine. ";
    if (designBlocked) {
      cards.push(
        card(
          "Not ready to run",
          [
            t(
              privacy +
                "The pipeline would fail on these two files for the reason above, so " +
                "there is no command to give yet. Fix the design table and re-check."
            ),
          ],
          "err"
        )
      );
    } else {
      const pre = el("pre");
      pre.appendChild(code("bindsight discover my.yaml --out runs/mine"));
      cards.push(
        card(
          "Running it",
          [
            t(
              privacy +
                "To run the pipeline on it, point the CLI at a config naming these two files:"
            ),
            pre,
            t("then "),
            code("bindsight ui"),
            t(" to read the result here."),
          ],
          "ok"
        )
      );
    }
  }

  // Read after every await above: a newer run may have started while this one
  // was reading a file, and it owns the output now.
  if (thisRun !== latestRun) return;
  out.innerHTML = "";
  cards.forEach(function (node) {
    out.appendChild(node);
  });
}

function boot() {
  var counts = document.getElementById("counts");
  var design = document.getElementById("design");
  if (!counts || !design) return;
  // mkdocs-material's instant navigation swaps page content without a reload,
  // so this runs again on a page that may already be wired up.
  if (counts.dataset.checkReady === "1") return;
  counts.dataset.checkReady = "1";
  counts.addEventListener("change", check);
  design.addEventListener("change", check);
}

if (window.document$ && typeof window.document$.subscribe === "function") {
  window.document$.subscribe(boot);
} else if (document.readyState !== "loading") {
  boot();
} else {
  document.addEventListener("DOMContentLoaded", boot);
}

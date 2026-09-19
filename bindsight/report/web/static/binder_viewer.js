// SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// The predicted binder-target complexes, drawn in 3-D.
//
// This file is loaded by three surfaces and authored once, because copies of a
// viewer diverge and the copy nobody is looking at is the one that drifts:
//
//   `bindsight ui`         templates/evidence.html.j2, structures from a route
//   the documentation site docs/results.md, structures from files beside it
//   the HTML report        report/templates/report.html.j2, structures inside it
//
// None of them owns it. What differs is only where a structure comes from, and
// that is read off the host element rather than branched on by surface.
//
// The host element carries the contract:
//
//   data-binder-viewer                  marks the element to draw into
//   data-structure-url="<template>"     {id} is replaced with the design id
//   data-viewer-lib="<url>"             optional: load 3Dmol from here if absent
//
// and, where the page carries its structures rather than fetching them,
// `window.BINDSIGHT_STRUCTURES` maps design id to mmCIF text.
//
// and the picker carries `data-binder-picker`. Attributes, not ids, so the two
// surfaces can keep their own class names and their own stylesheets.
(function () {
  "use strict";

  // Captured at parse time: `document.currentScript` is null inside any later
  // callback. Every URL below resolves against THIS FILE's location rather than
  // the page's, which is what lets one script serve a docs site published under
  // a subpath (/bindsight/), a local `mkdocs serve` at /, and the app at / --
  // with nothing encoding a site root. mkdocs-material has already put the
  // correct base on this src; borrowing it is more reliable than deriving it.
  var SELF =
    (document.currentScript && document.currentScript.src) ||
    (document.querySelector('script[src*="binder_viewer.js"]') || {}).src ||
    window.location.href;
  var HERE = new URL(".", SELF).href;

  // bindsight writes the designed chain as B and the target it was designed
  // against as T. tests/test_web_ui.py asserts that of every committed
  // structure, so if it ever stops being true this stops being a silent
  // mis-colouring and becomes a failing test.
  var BINDER_CHAIN = "B";

  // Composed as nodes rather than markup, for the reason the fetch handler
  // below gives: a message that later starts carrying something a server said
  // must not be interpolated into innerHTML.
  function replaceViewerWith(host, text) {
    host.innerHTML = "";
    var note = document.createElement("p");
    note.className = "small";
    note.style.padding = "1rem";
    note.textContent = text;
    var where = document.createElement("p");
    where.className = "small muted";
    where.style.padding = "0 1rem 1rem";
    where.textContent =
      "Every complex is committed as mmCIF under " +
      "benchmarks/designer_benchmark/, which is the file this viewer reads.";
    host.appendChild(note);
    host.appendChild(where);
  }

  // WebGL is unavailable in more places than it looks: locked-down machines,
  // remote desktops, some VMs, browsers with hardware acceleration off. There
  // `createViewer` does not throw -- it returns a viewer over a canvas with a
  // dead context, so the page drew a white rectangle under a caption promising
  // a rotatable complex and said nothing. The rule is the one the fetch
  // handler below states: a blank viewer and a design that produced nothing
  // are different facts and must not look the same.
  function webglAvailable() {
    try {
      var probe = document.createElement("canvas");
      return !!(probe.getContext("webgl2") || probe.getContext("webgl"));
    } catch (e) {
      return false;
    }
  }

  function start(host, pick) {
    if (!webglAvailable()) {
      replaceViewerWith(
        host,
        "This browser cannot draw 3-D structures: WebGL is unavailable or " +
          "switched off. The structures are here, the viewer is not."
      );
      return;
    }

    host.innerHTML = "";
    var viewer;
    try {
      viewer = $3Dmol.createViewer(host, { backgroundColor: "white" });
    } catch (e) {
      replaceViewerWith(host, "Could not start the structure viewer: " + String(e && e.message));
      return;
    }
    if (!viewer) {
      replaceViewerWith(host, "Could not start the structure viewer.");
      return;
    }

    // The app serves structures from a route; the docs site serves them as
    // files beside this script. The id is never user input -- it comes from
    // the picker this page generated -- and encodeURIComponent keeps a
    // crafted one from walking out of the directory either way.
    var template = host.getAttribute("data-structure-url") || "/api/structure/{id}";

    // The self-contained HTML report has no server AND no sibling files: it
    // is one file that must survive being emailed, so its structures travel
    // inside it. Same viewer, third source -- rather than a second viewer that
    // would be the copy nobody noticed had drifted.
    var inline = window.BINDSIGHT_STRUCTURES || null;

    function load(id) {
      if (inline && Object.prototype.hasOwnProperty.call(inline, id)) {
        return Promise.resolve(inline[id]);
      }
      var url = new URL(template.replace("{id}", encodeURIComponent(id)), HERE).href;
      return fetch(url).then(function (r) {
        if (!r.ok) throw new Error("no structure for " + id);
        return r.text();
      });
    }

    function show(id) {
      load(id)
        .then(function (cif) {
          viewer.clear();
          var model = viewer.addModel(cif, "cif");
          // An mmCIF the parser did not understand yields a model with no atoms,
          // and 3Dmol renders that as an empty canvas without complaint -- the
          // same white rectangle a reader would get from a design that produced
          // nothing. Counted rather than assumed, for the reason the catch block
          // below gives.
          var atoms = 0;
          try {
            atoms = model && model.selectedAtoms ? model.selectedAtoms({}).length : 0;
          } catch (e) {
            atoms = 0;
          }
          if (!atoms) {
            throw new Error("the structure file for " + id + " parsed to no atoms");
          }
          // Paint everything first, then override the binder. Styling named
          // chains only meant a file whose chains are named something else kept
          // 3Dmol's default line style and rendered as a wireframe haze -- with
          // no error, and under a caption claiming it was grey cartoon.
          viewer.setStyle({}, { cartoon: { color: "#9aa5b1" } });
          viewer.setStyle({ chain: BINDER_CHAIN }, { cartoon: { color: "#0f7d73" } });
          viewer.zoomTo();
          viewer.render();
        })
        .catch(function (err) {
          // Said plainly. A viewer that stays blank is indistinguishable from a
          // design that produced nothing, and those are different facts.
          //
          // Built as a node with textContent rather than assembled into
          // innerHTML. The message is composed here today, but an error string
          // is exactly the kind of value that later starts carrying something a
          // server said, and by then the interpolation looks harmless.
          //
          // One case this reports honestly rather than hiding: opening the
          // built site from a file:// path, where fetch is refused by CORS.
          host.innerHTML = "";
          var note = document.createElement("p");
          note.className = "small";
          note.style.padding = "1rem";
          note.textContent = "Could not load this structure: " + String(err && err.message);
          host.appendChild(note);
        });
    }

    pick.addEventListener("change", function () {
      show(pick.value);
    });
    show(pick.value);
  }

  function boot() {
    var host = document.querySelector("[data-binder-viewer]");
    var pick = document.querySelector("[data-binder-picker]");
    if (!host || !pick) return;
    // mkdocs-material's instant navigation swaps page content without a
    // reload, so this runs again on a page that may already be wired up.
    if (host.dataset.viewerReady === "1") return;
    host.dataset.viewerReady = "1";

    if (typeof $3Dmol !== "undefined") {
      start(host, pick);
      return;
    }

    // The app loads the library itself, in a tag beside this one. The docs
    // page cannot: `extra_javascript` would put half a megabyte on all eight
    // pages to serve the one that draws structures. So it names the library
    // here and it is fetched only where a viewer exists.
    var lib = host.getAttribute("data-viewer-lib");
    if (!lib) {
      // The app and the report both ship the library in a tag beside this one,
      // so reaching here without one means it failed to parse or was stripped.
      replaceViewerWith(host, "The structure viewer library did not load.");
      return;
    }
    var tag = document.createElement("script");
    tag.src = new URL(lib, HERE).href;
    tag.onload = function () {
      start(host, pick);
    };
    tag.onerror = function () {
      // A 404 on the library would otherwise leave the bare host element on
      // screen: a blank rectangle under a caption promising a complex.
      replaceViewerWith(host, "Could not load the structure viewer.");
    };
    document.head.appendChild(tag);
  }

  // mkdocs-material publishes `document$` and re-emits it on every instant
  // navigation; without subscribing, a reader arriving at this page from
  // another docs page gets an inert picker and an empty box.
  if (window.document$ && typeof window.document$.subscribe === "function") {
    window.document$.subscribe(boot);
  } else if (document.readyState !== "loading") {
    boot();
  } else {
    document.addEventListener("DOMContentLoaded", boot);
  }
})();

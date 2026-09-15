// SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// Charts for bindsight, drawn as SVG with no dependencies.
//
// Written rather than vendored. The chart types this project needs are few and
// simple -- a strip of paired values, a forest of intervals, a bar row, a
// scatter -- and a hand-written renderer costs nothing, ships nothing, needs no
// CDN, adds no licence to the inventory, and takes its colours from the same
// custom properties as everything else.
//
// Two rules, both of which are about honesty rather than looks:
//
//   * A chart never carries information the surrounding text does not. Hover is
//     for detail, never for the finding: a tooltip does not print, does not
//     exist on a touch screen, and is absent from a photograph of the screen.
//   * Every series is distinguishable without colour. Shape and position do the
//     work; hue is a reinforcement.

(function () {
  "use strict";

  const NS = "http://www.w3.org/2000/svg";

  function el(name, attrs, parent) {
    const node = document.createElementNS(NS, name);
    for (const key in attrs || {}) {
      if (attrs[key] !== null && attrs[key] !== undefined) {
        node.setAttribute(key, String(attrs[key]));
      }
    }
    if (parent) parent.appendChild(node);
    return node;
  }

  function cssVar(name, fallback) {
    const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return v || fallback;
  }

  // ------------------------------------------------------------- tooltip
  let tip = null;
  function tooltip() {
    if (!tip) {
      tip = document.createElement("div");
      tip.className = "tooltip";
      tip.hidden = true;
      document.body.appendChild(tip);
    }
    return tip;
  }

  function bindTip(node, html) {
    node.addEventListener("pointerenter", function (ev) {
      const t = tooltip();
      t.innerHTML = html;
      t.hidden = false;
      move(ev);
    });
    node.addEventListener("pointermove", move);
    node.addEventListener("pointerleave", function () {
      tooltip().hidden = true;
    });
    // Keyboard reach: a chart whose detail is mouse-only is detail some
    // readers simply do not have.
    node.setAttribute("tabindex", "0");
    node.addEventListener("focus", function () {
      const t = tooltip();
      t.innerHTML = html;
      t.hidden = false;
      const r = node.getBoundingClientRect();
      t.style.left = r.right + 8 + "px";
      t.style.top = r.top + "px";
    });
    node.addEventListener("blur", function () {
      tooltip().hidden = true;
    });

    function move(ev) {
      const t = tooltip();
      const pad = 14;
      let x = ev.clientX + pad;
      let y = ev.clientY + pad;
      const r = t.getBoundingClientRect();
      if (x + r.width > window.innerWidth - 8) x = ev.clientX - r.width - pad;
      if (y + r.height > window.innerHeight - 8) y = ev.clientY - r.height - pad;
      t.style.left = x + "px";
      t.style.top = y + "px";
    }
  }

  // --------------------------------------------------------------- scales
  function linear(domain, range) {
    const [d0, d1] = domain;
    const [r0, r1] = range;
    const span = d1 - d0 || 1;
    const f = function (v) {
      return r0 + ((v - d0) / span) * (r1 - r0);
    };
    f.invert = function (p) {
      return d0 + ((p - r0) / (r1 - r0)) * span;
    };
    f.domain = domain;
    return f;
  }

  function ticks(lo, hi, count) {
    const span = hi - lo;
    if (!(span > 0)) return [lo];
    const raw = span / Math.max(1, count);
    const mag = Math.pow(10, Math.floor(Math.log10(raw)));
    const norm = raw / mag;
    const step = (norm >= 5 ? 10 : norm >= 2 ? 5 : norm >= 1 ? 2 : 1) * mag;
    const out = [];
    for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) {
      out.push(Number(v.toFixed(10)));
    }
    return out;
  }

  function frame(host, height) {
    host.innerHTML = "";
    const width = Math.max(320, host.clientWidth || 640);
    const svg = el("svg", {
      class: "chart",
      viewBox: `0 0 ${width} ${height}`,
      width: "100%",
      height: height,
      role: "img",
    }, host);
    return { svg: svg, width: width, height: height };
  }

  // ------------------------------------------------- paired strip (designs
  // vs their own shuffles). The comparison the calibration actually makes: a
  // line per pair, so a reader sees the pairing rather than two clouds.
  function pairedStrip(host, spec) {
    const { svg, width, height } = frame(host, spec.height || 300);
    const m = { top: 24, right: 24, bottom: 36, left: 52 };
    const iw = width - m.left - m.right;
    const ih = height - m.top - m.bottom;
    const g = el("g", { transform: `translate(${m.left},${m.top})` }, svg);

    const all = spec.pairs.flatMap((p) => [p.a, p.b]);
    const lo = Math.min.apply(null, all.concat([spec.threshold ?? Infinity]));
    const hi = Math.max.apply(null, all.concat([spec.threshold ?? -Infinity]));
    const pad = (hi - lo) * 0.08 || 0.05;
    const y = linear([lo - pad, hi + pad], [ih, 0]);
    const xa = iw * 0.3;
    const xb = iw * 0.7;

    ticks(lo - pad, hi + pad, 5).forEach(function (t) {
      el("line", { class: "gridline", x1: 0, x2: iw, y1: y(t), y2: y(t) }, g);
      el("text", { x: -8, y: y(t) + 4, "text-anchor": "end" }, g).textContent = t.toFixed(2);
    });

    if (spec.threshold !== undefined && spec.threshold !== null) {
      el("line", {
        x1: 0, x2: iw, y1: y(spec.threshold), y2: y(spec.threshold),
        stroke: cssVar("--err", "#a32020"), "stroke-width": 1.5, "stroke-dasharray": "5 4",
      }, g);
      el("text", {
        x: iw, y: y(spec.threshold) - 6, "text-anchor": "end",
        fill: cssVar("--err", "#a32020"), "font-weight": 600,
      }, g).textContent = spec.thresholdLabel || `threshold ${spec.threshold}`;
    }

    [[xa, spec.labelA || "A"], [xb, spec.labelB || "B"]].forEach(function (d) {
      el("text", { x: d[0], y: ih + 24, "text-anchor": "middle", "font-weight": 600 }, g)
        .textContent = d[1];
    });

    const navy = cssVar("--navy", "#0b5394");
    const teal = cssVar("--teal", "#0f7d73");

    spec.pairs.forEach(function (p) {
      // The connecting line is the point of this chart: it shows which member
      // of each pair won, which a pair of box plots hides entirely.
      const up = p.b > p.a;
      el("line", {
        x1: xa, y1: y(p.a), x2: xb, y2: y(p.b),
        stroke: up ? cssVar("--err", "#a32020") : cssVar("--ok", "#1f6f35"),
        "stroke-width": 1, opacity: 0.5,
      }, g);

      // Circle for A, square for B: the series are separable in greyscale.
      const ca = el("circle", { class: "mark", cx: xa, cy: y(p.a), r: 4.5, fill: navy }, g);
      const cb = el("rect", {
        class: "mark", x: xb - 4, y: y(p.b) - 4, width: 8, height: 8, fill: teal,
      }, g);
      const label =
        `<strong>${p.id}</strong><br>${spec.labelA}: ${p.a.toFixed(3)}` +
        `<br>${spec.labelB}: ${p.b.toFixed(3)}` +
        `<br>difference: ${(p.b - p.a).toFixed(3)}`;
      bindTip(ca, label);
      bindTip(cb, label);
    });

    if (spec.title) svg.setAttribute("aria-label", spec.title);
    return svg;
  }

  // ------------------------------------------------------ forest of intervals
  function forest(host, spec) {
    const rows = spec.rows;
    const rowH = 30;
    const { svg, width } = frame(host, rows.length * rowH + 56);
    const m = { top: 16, right: 28, bottom: 32, left: spec.labelWidth || 150 };
    const iw = width - m.left - m.right;
    const g = el("g", { transform: `translate(${m.left},${m.top})` }, svg);

    const lows = rows.map((r) => r.low);
    const highs = rows.map((r) => r.high);
    let lo = Math.min.apply(null, lows.concat([spec.reference ?? Infinity]));
    let hi = Math.max.apply(null, highs.concat([spec.reference ?? -Infinity]));
    const pad = (hi - lo) * 0.1 || 0.1;
    lo -= pad; hi += pad;
    const x = linear([lo, hi], [0, iw]);
    const ih = rows.length * rowH;

    ticks(lo, hi, 5).forEach(function (t) {
      el("line", { class: "gridline", x1: x(t), x2: x(t), y1: 0, y2: ih }, g);
      el("text", { x: x(t), y: ih + 20, "text-anchor": "middle" }, g).textContent = t.toFixed(2);
    });

    if (spec.reference !== undefined && spec.reference !== null) {
      el("line", {
        x1: x(spec.reference), x2: x(spec.reference), y1: 0, y2: ih,
        stroke: cssVar("--ink-faint", "#7d8896"), "stroke-width": 1.5, "stroke-dasharray": "4 3",
      }, g);
    }

    rows.forEach(function (r, i) {
      const cy = i * rowH + rowH / 2;
      const excludes =
        spec.reference === undefined || spec.reference === null
          ? null
          : r.low > spec.reference || r.high < spec.reference;
      const colour = excludes === null
        ? cssVar("--navy", "#0b5394")
        : excludes ? cssVar("--ok", "#1f6f35") : cssVar("--ink-soft", "#55606d");

      el("text", { x: -m.left + 4, y: cy + 4, "font-weight": 600 }, g).textContent = r.label;
      el("line", { x1: x(r.low), x2: x(r.high), y1: cy, y2: cy, stroke: colour, "stroke-width": 2 }, g);
      [r.low, r.high].forEach(function (v) {
        el("line", { x1: x(v), x2: x(v), y1: cy - 5, y2: cy + 5, stroke: colour, "stroke-width": 2 }, g);
      });
      const dot = el("circle", { class: "mark", cx: x(r.point), cy: cy, r: 5, fill: colour }, g);

      // The glyph, not the colour, states the conclusion.
      if (excludes !== null) {
        el("text", {
          x: iw + 6, y: cy + 4, "font-weight": 700, fill: colour,
        }, g).textContent = excludes ? "✓" : "–";
      }

      bindTip(
        dot,
        `<strong>${r.label}</strong><br>${r.point.toFixed(3)} ` +
          `(${r.ciLabel || "95% CI"} ${r.low.toFixed(3)} to ${r.high.toFixed(3)})` +
          (r.n ? `<br>n = ${r.n}` : "") +
          (excludes === null ? "" : `<br>${excludes ? "excludes" : "includes"} ${spec.reference}`)
      );
    });

    if (spec.title) svg.setAttribute("aria-label", spec.title);
    return svg;
  }

  // ------------------------------------------------------------------ bars
  function bars(host, spec) {
    const rows = spec.rows;
    const rowH = 30;
    const { svg, width } = frame(host, rows.length * rowH + 40);
    const m = { top: 12, right: 90, bottom: 24, left: spec.labelWidth || 120 };
    const iw = width - m.left - m.right;
    const g = el("g", { transform: `translate(${m.left},${m.top})` }, svg);
    const hi = Math.max.apply(null, rows.map((r) => r.value).concat([spec.max || 0])) || 1;
    const x = linear([0, hi], [0, iw]);

    rows.forEach(function (r, i) {
      const y0 = i * rowH + 4;
      el("text", { x: -8, y: y0 + 14, "text-anchor": "end", "font-weight": 600 }, g)
        .textContent = r.label;
      el("rect", { x: 0, y: y0, width: iw, height: rowH - 10, fill: cssVar("--rule", "#e3e8ef"), rx: 3 }, g);
      const bar = el("rect", {
        class: "mark", x: 0, y: y0, width: Math.max(1, x(r.value)), height: rowH - 10,
        fill: r.colour || cssVar("--navy", "#0b5394"), rx: 3,
      }, g);
      el("text", { x: iw + 8, y: y0 + 14, "font-weight": 600 }, g).textContent = r.display;
      bindTip(bar, `<strong>${r.label}</strong><br>${r.tip || r.display}`);
    });

    if (spec.title) svg.setAttribute("aria-label", spec.title);
    return svg;
  }

  // --------------------------------------------------------------- scatter
  function scatter(host, spec) {
    const { svg, width, height } = frame(host, spec.height || 340);
    const m = { top: 20, right: 24, bottom: 44, left: 56 };
    const iw = width - m.left - m.right;
    const ih = height - m.top - m.bottom;
    const g = el("g", { transform: `translate(${m.left},${m.top})` }, svg);

    const xs = spec.points.map((p) => p.x);
    const ys = spec.points.map((p) => p.y);
    const x = linear([Math.min.apply(null, xs), Math.max.apply(null, xs)], [0, iw]);
    const y = linear([Math.min.apply(null, ys), Math.max.apply(null, ys)], [ih, 0]);

    ticks(x.domain[0], x.domain[1], 6).forEach(function (t) {
      el("line", { class: "gridline", x1: x(t), x2: x(t), y1: 0, y2: ih }, g);
      el("text", { x: x(t), y: ih + 18, "text-anchor": "middle" }, g).textContent = String(t);
    });
    ticks(y.domain[0], y.domain[1], 5).forEach(function (t) {
      el("line", { class: "gridline", x1: 0, x2: iw, y1: y(t), y2: y(t) }, g);
      el("text", { x: -8, y: y(t) + 4, "text-anchor": "end" }, g).textContent = String(t);
    });

    if (spec.xLabel) {
      el("text", { x: iw / 2, y: ih + 38, "text-anchor": "middle", "font-weight": 600 }, g)
        .textContent = spec.xLabel;
    }
    if (spec.yLabel) {
      el("text", {
        x: -ih / 2, y: -40, "text-anchor": "middle", "font-weight": 600,
        transform: `rotate(-90 ${-ih / 2} ${-40})`,
      }, g).textContent = spec.yLabel;
    }

    spec.points.forEach(function (p) {
      const node = el("circle", {
        class: "mark", cx: x(p.x), cy: y(p.y), r: p.r || 5,
        fill: p.colour || cssVar("--navy", "#0b5394"), opacity: 0.85,
      }, g);
      bindTip(node, p.tip || `${p.label || ""}<br>${p.x}, ${p.y}`);
    });

    if (spec.title) svg.setAttribute("aria-label", spec.title);
    return svg;
  }

  // ------------------------------------------------------------ public API
  const api = { pairedStrip: pairedStrip, forest: forest, bars: bars, scatter: scatter };

  function drawAll() {
    document.querySelectorAll("[data-chart]").forEach(function (host) {
      const kind = host.getAttribute("data-chart");
      const fn = api[kind];
      if (!fn) return;
      let spec;
      try {
        spec = JSON.parse(host.getAttribute("data-spec") || "{}");
      } catch (e) {
        return;
      }
      try {
        fn(host, spec);
      } catch (e) {
        // A chart that cannot draw must not take the page with it: the numbers
        // it illustrates are already in the text beside it.
        host.innerHTML =
          '<p class="small muted">This chart could not be drawn. The figures it ' +
          "shows are stated in the text above.</p>";
      }
    });
  }

  window.bindsightCharts = api;
  document.addEventListener("DOMContentLoaded", drawAll);

  let resizeTimer = null;
  window.addEventListener("resize", function () {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(drawAll, 150);
  });
})();

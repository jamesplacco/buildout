  /* =====================================================================================
     ui.js: DOM, SVG, tooltip, tables and the generic XY chart
     ===================================================================================== */
  const NS = "http://www.w3.org/2000/svg";
  const $ = (s, r = document) => r.querySelector(s);

  /* ---------- the Buildout mark (v0.18): the Today desk's rosette, the green lotus, exactly as drawRosette draws it,
     one symbol (site/src/logo.html, from scripts/make_logo.py) used in the header, every desk, empty states and the
     brain ---------- */
  function lotusSvg(cls) {
    const s = document.createElementNS(NS, "svg");
    s.setAttribute("viewBox", "0 0 330 330");
    s.setAttribute("class", cls || "lotus");
    const u = document.createElementNS(NS, "use");
    u.setAttribute("href", "#lotus");
    s.append(u);
    return s;
  }
  function markEl(cls) {
    const wrap = document.createElement("span");
    wrap.className = cls || "vmark";
    wrap.setAttribute("aria-hidden", "true");
    wrap.append(lotusSvg());
    return wrap;
  }
  function placeMarks() {
    document.querySelectorAll(".view > .vhead > .eyebrow").forEach((e) => { if (!e.querySelector(".vmark")) e.prepend(markEl("vmark")); });
    document.querySelectorAll(".view > .foot").forEach((f) => {
      if (f.previousElementSibling && f.previousElementSibling.classList.contains("mark-end")) return;
      const end = h("div", "mark-end");
      end.setAttribute("aria-hidden", "true");
      end.append(markEl("brand-mark"), h("span", null, "Buildout"));
      f.before(end);
    });
  }

  /* ---------- DOM and SVG helpers ---------- */
  function h(tag, cls, txt) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (txt != null) { if (typeof txt === "object" && txt.nodeType) e.append(txt); else e.textContent = txt; }   // a node (a link, a coloured figure) is appended, not stringified
    return e;
  }
  function svg(tag, attrs, parent) {
    const e = document.createElementNS(NS, tag);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    // a labelled shape needs a role for assistive tech to read the label (a focusable data point is an image)
    if (tag !== "svg" && attrs && attrs["aria-label"] && !attrs.role) e.setAttribute("role", "img");
    if (parent) parent.appendChild(e);
    return e;
  }
  // a chart whose points can take focus is a group of images, not one image (an image hides its children)
  function fixChartRoles(root = document) {
    root.querySelectorAll('svg[role="img"]').forEach((s) => { if (s.querySelector("[tabindex]")) s.setAttribute("role", "group"); });
    // a table that scrolls sideways must be reachable from the keyboard
    root.querySelectorAll(".tablewrap").forEach((w) => {
      if (w.scrollWidth > w.clientWidth) { w.tabIndex = 0; w.setAttribute("role", "region"); w.setAttribute("aria-label", "Table, scrolls sideways"); }
      else if (w.getAttribute("role") === "region") { w.removeAttribute("tabindex"); w.removeAttribute("role"); w.removeAttribute("aria-label"); }
    });
  }
  function text(parent, x, y, str, cls, anchor = "start", extra = {}) {
    const t = svg("text", Object.assign({ x, y, class: cls, "text-anchor": anchor }, extra), parent);
    t.textContent = str;
    return t;
  }
  const boxWidth = (box) => Math.max(300, box.clientWidth || 0);

  /* ---------- tooltip: values lead, labels follow ---------- */
  const tip = $("#tip");
  function showTip(rows, cx, cy) {
    tip.replaceChildren();
    for (const [strong, weak] of rows) {
      const row = h("div", "tip-row");
      row.append(h("strong", null, strong), h("span", null, weak));
      tip.append(row);
    }
    tip.hidden = false;
    const pad = 14, r = tip.getBoundingClientRect();
    let x = cx + pad, y = cy + pad;
    if (x + r.width > innerWidth - 8) x = cx - r.width - pad;
    if (y + r.height > innerHeight - 8) y = cy - r.height - pad;
    tip.style.left = Math.max(8, x) + "px";
    tip.style.top = Math.max(8, y) + "px";
  }
  const hideTip = () => { tip.hidden = true; };
  function bindTip(node, rows) {
    node.addEventListener("pointermove", (e) => showTip(rows(), e.clientX, e.clientY));
    node.addEventListener("pointerleave", hideTip);
    node.addEventListener("focus", () => { const b = node.getBoundingClientRect(); showTip(rows(), b.right, b.top); });
    node.addEventListener("blur", hideTip);
  }
  function fillTable(table, head, rows, leftCols = 1) {
    table.replaceChildren();
    const thead = h("thead"), tr = h("tr");
    head.forEach((c, i) => tr.append(h("th", i >= leftCols ? "r" : null, c)));
    thead.append(tr);
    const tb = h("tbody");
    rows.forEach((r) => { const row = h("tr"); r.forEach((c, i) => row.append(h("td", i >= leftCols ? "r" : null, c))); tb.append(row); });
    table.append(thead, tb);
  }
  function tableBlock(head, rows, leftCols = 1) {
    const t = h("table");
    fillTable(t, head, rows, leftCols);
    const w = h("div", "tablewrap");
    w.append(t);
    return w;
  }
  function legendLines(el, items) {
    el.replaceChildren();
    items.forEach(([color, label]) => { const sp = h("span"); const i = h("i", "ln"); i.style.background = color; sp.append(i, document.createTextNode(label)); el.append(sp); });
  }

  /* ---------- generic XY chart with crosshair ---------- */
  function xyChart(box, cfg) {
    if (!box) return;
    const W = boxWidth(box), H = cfg.height || 240, padL = cfg.padL || 48, padR = cfg.padR || 18, top = 14, bottom = 30;
    const series = cfg.series.filter((s) => s.pts.length);
    if (!series.length) return;
    const xs = series.flatMap((s) => s.pts.map((p) => p[0]));
    const x0 = cfg.xDomain ? cfg.xDomain[0] : Math.min(...xs), x1 = cfg.xDomain ? cfg.xDomain[1] : Math.max(...xs);
    let ys = series.flatMap((s) => s.pts.map((p) => p[1])).filter(fin).concat((cfg.bands || []).flatMap((b) => b.pts.flatMap((p) => [p[1], p[2]])).filter(fin));
    ys = ys.concat((cfg.hlines || []).map((l) => l.y));
    let lo = Math.min(...ys), hi = Math.max(...ys);
    if (cfg.zero) { lo = Math.min(lo, 0); hi = Math.max(hi, 0); }
    if (cfg.yDomain) { lo = cfg.yDomain[0]; hi = cfg.yDomain[1]; }
    const ticks = niceTicks(lo, hi, cfg.yTicks || 5), y0 = ticks[0], y1 = ticks[ticks.length - 1];
    const sx = (x) => padL + ((x - x0) / (x1 - x0 || 1)) * (W - padL - padR);
    const sy = (y) => top + (1 - (y - y0) / (y1 - y0 || 1)) * (H - top - bottom);
    box.replaceChildren();
    const s = svg("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: "img", "aria-label": cfg.label || "Chart" }, box);
    ticks.forEach((t) => {
      svg("line", { x1: padL, x2: W - padR, y1: sy(t), y2: sy(t), class: cfg.zero && t === 0 ? "baseline" : "gridline" }, s);
      text(s, padL - 8, sy(t) + 4, cfg.yfmt ? cfg.yfmt(t) : String(t), "ax", "end");
    });
    (cfg.xticks || []).forEach(([x, label]) => {
      if (x < x0 - 1e-9 || x > x1 + 1e-9) return;
      text(s, sx(x), H - 9, label, "ax", "middle");
    });
    (cfg.vmarks || []).forEach((m) => {
      svg("line", { x1: sx(m.x), x2: sx(m.x), y1: top, y2: H - bottom, class: "crosshair", opacity: 0.5 }, s);
      if (m.label) text(s, sx(m.x) + 5, top + 10, m.label, "ax", "start");
    });
    (cfg.hlines || []).forEach((l) => {
      svg("line", { x1: padL, x2: W - padR, y1: sy(l.y), y2: sy(l.y), stroke: l.color || "var(--bad)", "stroke-width": 1.5 }, s);
      if (l.label) text(s, W - padR, sy(l.y) - 6, l.label, "lbl-strong", "end");
    });
    (cfg.bands || []).forEach((b) => {                          // shaded intervals: pts are [x, lo, hi]
      const ok = b.pts.filter((p) => fin(p[1]) && fin(p[2]));
      if (ok.length < 2) return;
      const d = ok.map((p, i) => (i ? "L" : "M") + sx(p[0]).toFixed(1) + "," + sy(p[2]).toFixed(1)).join("") +
        ok.slice().reverse().map((p) => "L" + sx(p[0]).toFixed(1) + "," + sy(p[1]).toFixed(1)).join("") + "Z";
      svg("path", { d, fill: b.color, opacity: b.opacity || 0.16, stroke: "none" }, s);
    });
    series.forEach((ser) => {
      let d = "", pen = false;
      ser.pts.forEach(([x, y]) => {
        if (!fin(y)) { pen = false; return; }
        d += (pen ? "L" : "M") + sx(x).toFixed(1) + "," + sy(y).toFixed(1);
        pen = true;
      });
      if (ser.area) svg("path", { d: d + `L${sx(ser.pts[ser.pts.length - 1][0])},${sy(Math.max(y0, Math.min(0, y1)))}L${sx(ser.pts[0][0])},${sy(Math.max(y0, Math.min(0, y1)))}Z`, fill: ser.color, opacity: 0.1 }, s);
      svg("path", { d, fill: "none", stroke: ser.color, "stroke-width": ser.width || 2, "stroke-linejoin": "round", "stroke-linecap": "round" }, s);
      if (ser.dots) ser.pts.forEach(([x, y]) => svg("circle", { cx: sx(x), cy: sy(y), r: 4, fill: ser.color, class: "mark-ring" }, s));
      if (ser.endLabel) {
        const [lx, ly] = ser.pts[ser.pts.length - 1];
        svg("circle", { cx: sx(lx), cy: sy(ly), r: 4.5, fill: ser.color, class: "mark-ring" }, s);
        text(s, sx(lx) - 8, sy(ly) - 9, ser.endLabel, "lbl-strong", "end");
      }
    });
    const snap = cfg.snapXs || series[0].pts.map((p) => p[0]);
    const cross = svg("line", { y1: top, y2: H - bottom, class: "crosshair", visibility: "hidden" }, s);
    const overlay = svg("rect", { x: padL, y: top, width: W - padL - padR, height: H - top - bottom, fill: "transparent", tabindex: "0", "aria-label": (cfg.label || "Chart") + "; use arrow keys to step" }, s);
    let idx = snap.length - 1;
    function nearest(ser, x) {
      let best = null, bd = Infinity;
      for (const p of ser.pts) { const dd = Math.abs(p[0] - x); if (dd < bd) { bd = dd; best = p; } }
      return best;
    }
    function at(i, cx, cy) {
      idx = Math.max(0, Math.min(snap.length - 1, i));
      const x = snap[idx], X = sx(x);
      cross.setAttribute("x1", X); cross.setAttribute("x2", X); cross.setAttribute("visibility", "visible");
      const rows = series.map((ser) => { const p = nearest(ser, x); return [cfg.yfmt ? cfg.yfmt(p[1]) : String(p[1]), `${ser.name} · ${cfg.xfmt ? cfg.xfmt(p[0]) : p[0]}`]; });
      const b = s.getBoundingClientRect();
      showTip(rows, cx ?? b.left + X * (b.width / W), cy ?? b.top + top);
    }
    overlay.addEventListener("pointermove", (e) => {
      const b = s.getBoundingClientRect(), xv = (e.clientX - b.left) * (W / b.width);
      const x = x0 + ((xv - padL) / (W - padL - padR)) * (x1 - x0);
      let best = 0;
      for (let i = 1; i < snap.length; i++) if (Math.abs(snap[i] - x) < Math.abs(snap[best] - x)) best = i;
      at(best, e.clientX, e.clientY);
    });
    const off = () => { cross.setAttribute("visibility", "hidden"); hideTip(); };
    overlay.addEventListener("pointerleave", off);
    overlay.addEventListener("blur", off);
    overlay.addEventListener("focus", () => at(idx));
    overlay.addEventListener("keydown", (e) => {
      if (e.key === "ArrowRight") { e.preventDefault(); at(idx + 1); }
      if (e.key === "ArrowLeft") { e.preventDefault(); at(idx - 1); }
    });
  }

  /* ---------- v0.5: generic bar charts. One scale per chart, recessive grid, labels in ink tokens ---------- */
  // horizontal bars; values may cross zero (diverging); rows: { label, v, color, tip: () => rows, lbl: "value label" }
  function barsH(box, rows, cfg = {}) {
    if (!box || !box.clientWidth || !rows.length) return;
    if (!rows.some((r) => fin(r.v) && (!cfg.log || r.v > 0))) { noData(box); return; }
    const W = boxWidth(box), rowH = cfg.rowH || 30, top = 4, bottom = 24;
    const labelW = cfg.labelW || Math.round(Math.min(230, Math.max(96, W * 0.34))), padR = cfg.padR || 64;
    const Hh = top + rows.length * rowH + bottom;
    const vals = rows.map((r) => r.v).filter(fin);
    const log = !!cfg.log;
    let lo, hi, sx;
    if (log) {
      const pos = vals.filter((v) => v > 0);
      lo = Math.floor(Math.log10(Math.min(...pos, cfg.min || Infinity))); hi = Math.ceil(Math.log10(Math.max(...pos)));
      sx = (v) => labelW + ((Math.log10(Math.max(v, Math.pow(10, lo))) - lo) / (hi - lo || 1)) * (W - labelW - padR);
    } else {
      const ticks = niceTicks(Math.min(0, ...vals, cfg.min ?? 0), Math.max(0, ...vals, cfg.max ?? 0), cfg.ticks || 4);
      lo = ticks[0]; hi = ticks[ticks.length - 1];
      sx = (v) => labelW + ((v - lo) / (hi - lo || 1)) * (W - labelW - padR);
    }
    box.replaceChildren();
    const s = svg("svg", { viewBox: `0 0 ${W} ${Hh}`, width: W, height: Hh, role: "img", "aria-label": cfg.label || "Bar chart" }, box);
    const tickVals = log ? Array.from({ length: hi - lo + 1 }, (_, i) => Math.pow(10, lo + i)).filter((_, i, a) => a.length <= 6 || i % 2 === 0) : niceTicks(lo, hi, cfg.ticks || 4);
    tickVals.forEach((t) => {
      const x = sx(t);
      svg("line", { x1: x, x2: x, y1: top, y2: Hh - bottom, class: !log && t === 0 ? "baseline" : "gridline" }, s);
      text(s, x, Hh - 8, cfg.tfmt ? cfg.tfmt(t) : log ? (t >= 1 ? String(t) : t.toExponential(0).replace("e-", "e−")) : String(t), "ax", "middle");
    });
    rows.forEach((r, i) => {
      const y = top + i * rowH + (rowH - 14) / 2;
      text(s, labelW - 10, y + 11, r.label, r.strong ? "lbl-strong" : "cat", "end");
      if (!fin(r.v)) { text(s, sx(log ? Math.pow(10, lo) : 0) + 6, y + 11, "n/a", "ax", "start"); return; }
      const x0 = log ? labelW : sx(0), x1 = sx(r.v);
      svg("path", { d: hbar(x0, x1, y, 14), fill: r.color || "var(--s1)" }, s);
      const lbl = r.lbl != null ? r.lbl : cfg.fmt ? cfg.fmt(r.v) : String(r.v);
      if (r.v >= 0 || log) text(s, Math.max(x0, x1) + 6, y + 11, lbl, "lbl-strong", "start");
      else if (Math.min(x0, x1) - labelW < 52) text(s, x0 + 6, y + 11, lbl, "lbl-strong", "start");   // no room left of a short negative bar: label it right of zero
      else text(s, Math.min(x0, x1) - 6, y + 11, lbl, "lbl-strong", "end");
      if (r.mark != null && fin(r.mark)) svg("line", { x1: sx(r.mark), x2: sx(r.mark), y1: y - 3, y2: y + 17, stroke: "var(--ink)", "stroke-width": 2 }, s);
      const hit = svg("rect", { x: 0, y: top + i * rowH, width: W, height: rowH, class: "hit", tabindex: "0", "aria-label": `${r.label}: ${lbl}` }, s);
      bindTip(hit, r.tip || (() => [[lbl, r.label]]));
    });
  }
  // vertical bars over categories; a row may carry { lo, hi } to draw a range instead of a bar
  function noData(box, msg) {
    const e = h("div", "empty");
    e.append(markEl("vmark"), h("strong", null, msg || "No data yet."), h("span", null, "The chart fills in when the daily run supplies it."));
    box.replaceChildren(e);
  }
  function barsV(box, rows, cfg = {}) {
    if (!box || !box.clientWidth || !rows.length) return;
    const vals = rows.flatMap((r) => [r.v, r.lo, r.hi]).filter(fin);
    if (!vals.length) { noData(box); return; }
    const W = boxWidth(box), Hh = cfg.height || 230, padL = cfg.padL || 44, padR = 10, top = 20, bottom = 30;
    const ticks = niceTicks(Math.min(0, ...vals), Math.max(0, ...vals, cfg.max || 0), cfg.ticks || 4), y0 = ticks[0], y1 = ticks[ticks.length - 1];
    const sy = (v) => top + (1 - (v - y0) / (y1 - y0 || 1)) * (Hh - top - bottom);
    const band = (W - padL - padR) / rows.length, bw = Math.min(54, band * 0.56);
    box.replaceChildren();
    const s = svg("svg", { viewBox: `0 0 ${W} ${Hh}`, width: W, height: Hh, role: "img", "aria-label": cfg.label || "Bar chart" }, box);
    ticks.forEach((t) => { svg("line", { x1: padL, x2: W - padR, y1: sy(t), y2: sy(t), class: t === 0 ? "baseline" : "gridline" }, s); text(s, padL - 8, sy(t) + 4, cfg.yfmt ? cfg.yfmt(t) : String(t), "ax", "end"); });
    rows.forEach((r, i) => {
      const x = padL + band * i + (band - bw) / 2;
      text(s, x + bw / 2, Hh - 9, r.label, "ax", "middle");
      let lbl;
      if (fin(r.lo) && fin(r.hi)) {
        svg("path", { d: vbar(x, bw, sy(r.lo), sy(r.hi)), fill: r.color || "var(--s1)", opacity: 0.35 }, s);
        svg("line", { x1: x, x2: x + bw, y1: sy(r.lo), y2: sy(r.lo), stroke: r.color || "var(--s1)", "stroke-width": 2 }, s);
        lbl = r.lbl || `${r.lo} to ${r.hi}`;
        text(s, x + bw / 2, sy(r.hi) - 6, lbl, "lbl-strong", "middle");
      } else if (fin(r.v)) {
        svg("path", { d: vbar(x, bw, sy(0), sy(r.v)), fill: r.color || "var(--s1)" }, s);
        lbl = r.lbl != null ? r.lbl : cfg.fmt ? cfg.fmt(r.v) : String(r.v);
        text(s, x + bw / 2, r.v >= 0 ? sy(r.v) - 6 : sy(r.v) + 14, lbl, "lbl-strong", "middle");
      }
      const hit = svg("rect", { x: padL + band * i, y: top, width: band, height: Hh - top - bottom, class: "hit", tabindex: "0", "aria-label": `${r.label}: ${lbl || "n/a"}` }, s);
      bindTip(hit, r.tip || (() => [[lbl || "n/a", r.label]]));
    });
  }

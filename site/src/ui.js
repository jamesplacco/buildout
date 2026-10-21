  /* =====================================================================================
     ui.js: DOM, SVG, tooltip, tables and the generic XY chart
     ===================================================================================== */
  const NS = "http://www.w3.org/2000/svg";
  const $ = (s, r = document) => r.querySelector(s);

  /* ---------- DOM and SVG helpers ---------- */
  function h(tag, cls, txt) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (txt != null) e.textContent = txt;
    return e;
  }
  function svg(tag, attrs, parent) {
    const e = document.createElementNS(NS, tag);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(e);
    return e;
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
    let ys = series.flatMap((s) => s.pts.map((p) => p[1])).filter(fin);
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

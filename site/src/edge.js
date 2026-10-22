  /* =====================================================================================
     edge.js (v0.15): asymmetric information. The sources worth reading and what each is uniquely good for, the
     Taleb and Damodaran lenses, and Damodaran's two calculators: the implied equity risk premium and the
     narrative-to-numbers DCF. dmErp and dmDcf mirror buildout/damodaran.py exactly (tests/test_v15.py holds them equal).
     ===================================================================================== */
  function dmErp(level, cashYield, growth, rf, years = 5) {
    const cf0 = level * cashYield;
    const pv = (r) => { let v = 0, cf = cf0; for (let t = 1; t <= years; t++) { cf *= 1 + growth; v += cf / Math.pow(1 + r, t); } return v + cf * (1 + rf) / (r - rf) / Math.pow(1 + r, years); };
    let lo = rf + 1e-6, hi = 1.0;
    if (pv(hi) > level || pv(lo) < level) return { r: null, erp: null };
    for (let i = 0; i < 200; i++) { const mid = (lo + hi) / 2; if (pv(mid) > level) lo = mid; else hi = mid; }
    const r = (lo + hi) / 2, cash_flows = [];
    for (let t = 1; t <= years; t++) cash_flows.push(cf0 * Math.pow(1 + growth, t));
    return { r, erp: r - rf, cash_flows };
  }
  function dmDcf(o) {
    const d = Object.assign({ years_to_target: 5, sales_to_capital: 1.5, tax: 0.21, wacc_start: 0.10, wacc_mature: 0.085, rf: 0.0513, g_terminal: null, p_fail: 0, distress_share: 0.5, debt: 0, cash: 0, shares: 1, years: 10 }, o);
    const gT = Math.min(d.rf, d.g_terminal == null ? d.rf : d.g_terminal);
    const rows = [];
    let rev = d.revenue, disc = 1, pv = 0;
    for (let t = 1; t <= d.years; t++) {
      const g = t <= 5 ? d.growth_high : d.growth_high - (d.growth_high - gT) * (t - 5) / 5;
      const nw = rev * (1 + g);
      const m = t >= d.years_to_target ? d.margin_target : d.margin_now + (d.margin_target - d.margin_now) * t / d.years_to_target;
      const ebit = nw * m, nopat = ebit * (1 - d.tax), reinv = (nw - rev) / d.sales_to_capital, fcff = nopat - reinv;
      const w = t <= 5 ? d.wacc_start : d.wacc_start - (d.wacc_start - d.wacc_mature) * (t - 5) / 5;
      disc /= 1 + w;
      pv += fcff * disc;
      rows.push({ year: t, growth: g, revenue: nw, margin: m, ebit, nopat, reinvestment: reinv, fcff, wacc: w, pv: fcff * disc });
      rev = nw;
    }
    const nopat11 = rev * (1 + gT) * d.margin_target * (1 - d.tax), reinv11 = d.wacc_mature > 0 ? nopat11 * (gT / d.wacc_mature) : 0;
    const tv = (nopat11 - reinv11) / (d.wacc_mature - gT), pvTv = tv * disc, ev = pv + pvTv, going = ev - d.debt + d.cash;
    const equity = (1 - d.p_fail) * going + d.p_fail * d.distress_share * Math.max(0, going);
    return { rows, pv_years: pv, terminal: tv, pv_terminal: pvTv, ev, equity, per_share: equity / d.shares, terminal_share: ev ? pvTv / ev : null, g_terminal: gT };
  }

  /* ---------- the Edge desk ---------- */
  const ED = { kind: "all" };
  const EDGE_KIND = { "es-src-bowtiedbull": "independent", "es-src-sixsigmaresearch": "independent", "es-src-taleb": "lens", "es-src-damodaran-data": "lens", "es-src-musings-on-markets": "lens",
    "es-src-berkshire-letters": "legend", "es-src-oaktree-memos": "legend", "es-src-semianalysis": "independent", "es-src-stratechery": "independent", "es-src-doomberg": "independent",
    "es-src-money-stuff": "independent", "es-src-bespoke": "independent", "mlf-source-open-source-asset-pricing": "primary" };
  const EDGE_KIND_NAME = { all: "All", independent: "Independent research", lens: "Taleb and Damodaran", legend: "Legendary investors' own words", primary: "Primary data and filings" };
  function edOk(s) { return !!(s && s.edge && Array.isArray(s.edge.edge) && s.edge.edge.length && s.damodaran && s.damodaran.dcf_story); }
  const edPct = (v, d = 1) => (fin(v) ? `${v < 0 ? MINUS : ""}${Math.abs(v * 100).toFixed(d)}%` : "n/a");
  function edLink(url, label) { const a = h("a", null, label); a.href = url; a.target = "_blank"; a.rel = "noopener"; return a; }
  function renderEdgeDesk() {
    const tiles = $("#ed-tiles");
    if (!tiles || !edOk(SNAP15)) { if (tiles && !tiles.children.length) tiles.append(h("p", "hint", "The edge snapshot is missing or malformed.")); return; }
    if (tiles.children.length) return;
    const E = EDGE_SNAP.edge, src = E.filter((x) => x.kind === "source"), D = DAM_SNAP;
    [[String(src.length), "Sources profiled", "each with its edge, its biases, cadence and cost"], [String(src.filter((x) => x.feed_url).length), "With a live feed", "RSS or Atom, confirmed to load"],
      [`${fx(D.erp.erp_oct, 2)}%`, "Damodaran's implied ERP", "October 1, 2026, over a 5.29% T-bond"], [`${fx(D.erp.er_oct, 2)}%`, "Implied expected return", "US equities, his October 8 post"],
      [`${fx(D.semis.ev_sales, 1)}x`, "Semiconductor EV/sales", "his January 2026 data, 35.3% pre-tax margin"]].forEach(([v, k, s]) => { const d = h("div", "at-kpi"); d.append(h("b", null, v), h("span", null, k), h("small", null, s)); tiles.append(d); });
    edSources();
    edEvidence();
    edErpWire();
    edDcfWire();
  }
  function edKind(x) { return EDGE_KIND[x.id] || "primary"; }
  function edSources() {
    const seg = $("#ed-seg"), box = $("#ed-src");
    const src = EDGE_SNAP.edge.filter((x) => x.kind === "source");
    const draw = () => {
      seg.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", b.dataset.k === ED.kind ? "true" : "false"));
      box.replaceChildren();
      src.filter((x) => ED.kind === "all" || edKind(x) === ED.kind).forEach((x) => {
        const c = h("article", "ed-card");
        const top = h("div", "ed-top");
        top.append(h("span", "ed-kind", EDGE_KIND_NAME[edKind(x)]), h("span", "ed-meta", [x.cadence, x.cost].filter(Boolean).join(" · ")));
        c.append(top, h("h3", null, x.title));
        if (x.edge) { const p = h("p", "ed-edge"); p.append(h("b", null, "Edge. "), x.edge); c.append(p); }
        if (x.biases) { const p = h("p", "ed-bias"); p.append(h("b", null, "Watch for. "), x.biases); c.append(p); }
        const links = h("p", "ed-links");
        links.append(edLink(x.source_url, "Open the source"));
        if (x.feed_url) { links.append(" · "); links.append(edLink(x.feed_url, "Feed")); }
        c.append(links);
        box.append(c);
      });
    };
    Object.entries(EDGE_KIND_NAME).forEach(([k, name]) => { if (k !== "all" && !src.some((x) => edKind(x) === k)) return; const b = h("button", null, name); b.type = "button"; b.dataset.k = k; b.addEventListener("click", () => { ED.kind = k; draw(); }); seg.append(b); });
    draw();
  }
  function edEvidence() {
    const box = $("#ed-ev");
    const items = EDGE_SNAP.edge.filter((x) => x.kind !== "source");
    const byLens = [["Taleb", (x) => /taleb|kappa|fragil|ruin|ergodic/i.test(x.id + x.title)], ["Damodaran", (x) => /damodaran/i.test(x.id + x.title)], ["The newsletters", (x) => /bowtied|sixsigma/i.test(x.id)],
      ["Everything else", () => true]];
    const used = new Set();
    byLens.forEach(([name, f]) => {
      const list = items.filter((x) => !used.has(x.id) && f(x));
      if (!list.length) return;
      list.forEach((x) => used.add(x.id));
      const d = h("details", "ed-lens");
      d.open = name !== "Everything else";
      d.append(h("summary", null, `${name} · ${list.length}`));
      const ul = h("ul", "ed-list");
      list.forEach((x) => { const li = h("li"); li.append(h("b", null, x.title + ". "), x.text + " ", edLink(x.source_url, x.publisher || "source")); ul.append(li); });
      d.append(ul);
      box.append(d);
    });
  }
  function edNum(id) { const v = parseFloat($("#" + id).value); return fin(v) ? v : NaN; }
  function edErpWire() {
    const D = DAM_SNAP.erp;
    $("#ed-erp-rf").value = (D.y10_now * 100).toFixed(2);
    const run = () => {
      const cy = edNum("ed-erp-cy") / 100, g = edNum("ed-erp-g") / 100, rf = edNum("ed-erp-rf") / 100, out = $("#ed-erp-out");
      if (![cy, g, rf].every(fin) || cy <= 0 || cy > 0.2 || g < -0.2 || g > 0.4 || rf < 0 || rf > 0.2) { out.textContent = "Enter a cash yield above 0 and below 20%, growth between −20% and 40%, and a risk-free rate between 0 and 20%."; return; }
      const r = dmErp(100, cy, g, rf);
      out.replaceChildren();
      if (r.r == null) { out.append(h("p", null, "No discount rate between the risk-free rate and 100% prices the index at these cash flows.")); return; }
      out.append(h("p", "ed-big", `Implied ERP ${edPct(r.erp, 2)}`), h("p", null, `The index is priced to return ${edPct(r.r, 2)} a year if cash to shareholders starts at ${edPct(cy, 1)} of the index, grows ${edPct(g, 1)} a year for five years, then at the risk-free rate of ${edPct(rf, 2)} forever.`),
        h("p", "hint", `Damodaran's own October 1 reading: ${fx(D.erp_oct, 2)}% on trailing cash flows with adjusted payout, over a ${fx(D.rf_oct, 2)}% T-bond. The calculator opens on illustrative inputs; set the cash yield and growth to the ones you believe.`));
    };
    ["ed-erp-cy", "ed-erp-g", "ed-erp-rf"].forEach((id) => $("#" + id).addEventListener("input", run));
    run();
  }
  const ED_STORIES = {
    semis: { name: "Chip designer at semiconductor averages", growth_high: 0.25, margin_now: 0.30, margin_target: 0.3531, sales_to_capital: 1.21, wacc_start: 0.1055, p_fail: 0.05 },
    software: { name: "Software at software averages", growth_high: 0.18, margin_now: 0.25, margin_target: 0.3321, sales_to_capital: 1.54, wacc_start: 0.0934, p_fail: 0.03 },
    fade: { name: "The boom fades: growth halves, margins fall back", growth_high: 0.12, margin_now: 0.30, margin_target: 0.22, sales_to_capital: 1.21, wacc_start: 0.1055, p_fail: 0.10 },
  };
  const ED_FIELDS = [["growth_high", "ed-dcf-g", 100], ["margin_now", "ed-dcf-m0", 100], ["margin_target", "ed-dcf-m1", 100], ["sales_to_capital", "ed-dcf-sc", 1], ["wacc_start", "ed-dcf-w", 100], ["p_fail", "ed-dcf-pf", 100]];
  function edDcfWire() {
    const S = DAM_SNAP.dcf_story;
    const set = (st) => ED_FIELDS.forEach(([k, id, m]) => { $("#" + id).value = +(st[k] * m).toFixed(2); });
    set(S);
    const pre = $("#ed-dcf-pre");
    Object.entries(ED_STORIES).forEach(([k, st]) => { const b = h("button", "pill", st.name); b.type = "button"; b.addEventListener("click", () => { set(st); run(); }); pre.append(b); });
    const run = () => {
      const o = { revenue: 100, years_to_target: 5, tax: 0.21, wacc_mature: S.wacc_mature, rf: S.rf, distress_share: 0.5 };
      let ok = true;
      ED_FIELDS.forEach(([k, id, m]) => { const v = edNum(id) / m; if (!fin(v)) ok = false; o[k] = v; });
      const out = $("#ed-dcf-out");
      if (!ok || o.sales_to_capital <= 0 || o.growth_high < -0.5 || o.growth_high > 1 || o.margin_target < -1 || o.margin_target > 1 || o.wacc_start <= o.rf || o.p_fail < 0 || o.p_fail > 1) {
        out.replaceChildren(h("p", "hint", "Check the inputs: sales to capital above 0, growth between −50% and 100%, margins between −100% and 100%, a cost of capital above the risk-free rate, failure odds between 0 and 100%.")); return;
      }
      const r = dmDcf(o);
      out.replaceChildren();
      out.append(h("p", "ed-big", `Value ${fx(r.equity, 0)} per 100 of revenue today (${fx(r.equity / 100, 1)}x sales)`),
        h("p", null, `${edPct(r.terminal_share, 0)} of it is the terminal value; growth fades from ${edPct(o.growth_high, 0)} to the risk-free ${edPct(r.g_terminal, 2)} in years six to ten, and the margin reaches ${edPct(o.margin_target, 1)} by year five. A ${edPct(o.p_fail, 0)} chance the story fails is valued at half of going-concern value.`),
        h("p", "hint", `Compare with what the market pays: Damodaran's January data put semiconductors at ${fx(DAM_SNAP.semis.ev_sales, 1)}x enterprise value to sales. If the price is far above this value, the price needs a bigger story than the one entered.`));
      out.append(tableBlock(["Year", "Growth", "Revenue", "Margin", "Reinvestment", "FCFF", "Cost of capital"], r.rows.map((x) => [String(x.year), edPct(x.growth, 1), fx(x.revenue, 0), edPct(x.margin, 1), fx(x.reinvestment, 1), fx(x.fcff, 1), edPct(x.wacc, 2)]), 1));
    };
    ED_FIELDS.forEach(([, id]) => $("#" + id).addEventListener("input", run));
    run();
  }

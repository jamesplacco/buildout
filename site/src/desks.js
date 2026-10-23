  /* =====================================================================================
     desks.js (v0.5): Fundamentals (10-K and 10-Q analysis), Physics (watts, not dollars)
     and Findings (original research on 156 years of public data)
     ===================================================================================== */
  const B$ = (v, d = 1) => (fin(v) ? (v < 0 ? MINUS : "") + "$" + fx(Math.abs(v), d) + "B" : "n/a");
  const pct0 = (v) => (fin(v) ? Math.round(v * 100) + "%" : "n/a");
  const sPct = (v, d = 1) => (fin(v) ? (v > 0 ? "+" : v < 0 ? MINUS : "") + fx(Math.abs(v) * 100, d) + "%" : "n/a");
  function roEl(k, v, key) { const d = h("div", "ro" + (key ? " key" : "")); d.append(h("span", "k", k), h("span", "v", v)); return d; }
  function srcLink(src) { if (!src) return null; const a = h("a", "src", src[0]); a.href = src[1]; return a; }
  const readF = () => (LIVE.research && LIVE.research.hedge && LIVE.research.panel ? LIVE.research : FINDINGS);
  const BUILDERS = ["MSFT", "GOOGL", "AMZN", "META", "ORCL", "CRWV"];
  const fundRow = (t) => FUND.rows.find((r) => r.t === t) || null;

  /* ============================== FUNDAMENTALS ============================== */
  function renderFundTable() {
    const tbl = $("#fund-table");
    if (!tbl) return;
    const thead = h("thead"), hr = h("tr"), tb = h("tbody");
    [["Company", ""], ["Revenue", "r"], ["Cash flow from operations", "r"], ["Capex", "r"], ["Free cash flow", "r"], ["Capex ÷ cash flow", "r"], ["Capex growth, last quarter", "r"], ["Pre-tax income from marks", "r"], ["Net cash", "r"], ["Coverage", ""]]
      .forEach(([t, c]) => { const th = h("th", c || null, t); th.scope = "col"; hr.append(th); });
    thead.append(hr);
    BUILDERS.map(fundRow).filter(Boolean).forEach((r) => {
      const tr = h("tr"), th = h("th");
      th.scope = "row";
      th.append(document.createTextNode(r.name));
      const sm = h("small");
      sm.append(document.createTextNode(`${r.t} · to ${isoNice(r.quarter_end)} · `));
      const a = h("a", null, "filings");
      a.href = SECL(r.cik);
      sm.append(a);
      th.append(sm);
      const td = (v, neg) => h("td", "r" + (neg ? " neg" : ""), v);
      const accel = fin(r.capex_accel) ? (r.capex_accel > 0 ? " ↑" : " ↓") : "";
      const g = h("td", "r", fin(r.capex_last_q_yoy) ? sPct(r.capex_last_q_yoy, 0) + accel : "n/a");
      if (fin(r.capex_accel)) g.title = `Growth ${r.capex_accel > 0 ? "sped up" : "slowed"} by ${fx(Math.abs(r.capex_accel) * 100, 0)} points against the prior quarter's (the second derivative)`;
      const st = h("td");
      st.append(h("span", "stage mk " + (r.stage || ""), r.coverage === "interest_uncovered" ? "Interest not covered" : r.coverage === "funding_gap" ? `Funding gap ${B$(r.funding_gap, 0)}` : r.coverage === "self_funded" ? "Self-funded" : "n/a"));
      if (r.refreshed) st.append(h("small", null, ` new filing to ${isoNice(r.quarter_end)}`));
      if (fin(r.gap_cover_years)) st.title = `Cash on hand covers ${fx(r.gap_cover_years, 1)} years of the gap at this rate; debt maturities are not modelled.`;
      tr.append(th, td(B$(r.revenue)), td(B$(r.ocf)), td(B$(r.capex)), td(B$(r.fcf), r.fcf < 0), td(pct0(r.capex_to_ocf), r.capex_to_ocf > 1), g, td(pct0(r.nonop_share), r.nonop_share > 0.3), td(B$(r.net_cash), r.net_cash < 0), st);
      tb.append(tr);
    });
    tbl.replaceChildren(thead, tb);
    const five = ["MSFT", "GOOGL", "AMZN", "META", "ORCL"].map(fundRow), cx = five.reduce((s, r) => s + r.capex, 0), ocf = five.reduce((s, r) => s + r.ocf, 0), guide = five.reduce((s, r) => s + (r.guide || 0), 0);
    const nv = fundRow("NVDA"), ts = fundRow("TSLA"), ms = fundRow("MSFT"), oc = fundRow("ORCL"), cw = fundRow("CRWV");
    const note = $("#fu-note");
    note.replaceChildren();
    note.append(document.createTextNode(`The five builders: capex ${B$(cx, 0)} against operating cash flow of ${B$(ocf, 0)} (${pct0(cx / ocf)}); next-year guidance adds up to about ${B$(guide, 0)}. Microsoft also took on ${B$(ms.leases)} of finance leases, which are capex by another name. Nvidia, the main supplier, spends ${pct0(nv.capex_to_ocf)} of its ${B$(nv.ocf, 0)} cash flow; Tesla ${pct0(ts.capex_to_ocf)}. Supplements the standard tags miss: ${oc.notes} ${cw.notes} `));
    const s = srcLink(SRC5.secapi), c = srcLink(SRC5.crwv), e = srcLink(SRC5.sec);
    [e, s, c].forEach((x, i) => { if (i) note.append(document.createTextNode(" · ")); note.append(x); });
    const newer = FUND.rows.filter((r) => r.refreshed);
    if (newer.length) note.append(document.createTextNode(` Newer filings from the daily run replace the shipped figures field by field, and every view on the page redraws from them: ${newer.map((r) => `${r.t} to ${isoNice(r.quarter_end)}, capex ${pct0(r.capex_to_ocf)} of cash flow (${COVERAGE[r.coverage] || "coverage n/a"})`).join("; ")}.`));
  }
  function renderMinsky() {
    const box = $("#fu-minsky");
    if (!box) return;
    box.replaceChildren();
    const all = FUND.rows.filter((r) => r.stage);
    [["hedge", "Cash flow covers capex", "A year of operating cash flow pays for a year of the build and the interest."],
      ["speculative", "Capex exceeds cash flow", "Interest is covered but the build needs cash on hand, asset sales, leases or new debt. A funding gap, not distress."],
      ["ponzi", "Interest not covered", "Operating income below interest, or negative cash flow. Survival leans on refinancing; maturities are not modelled here."]].forEach(([k, t, d]) => {
      const col = h("div");
      col.append(h("h3", null, t), h("p", null, d));
      const who = h("div", "who");
      all.filter((r) => r.stage === k).forEach((r) => { const sp = h("span", null, `${r.t} ${pct0(r.capex_to_ocf)}`); sp.title = `${r.name}: capex ${B$(r.capex)} against operating cash flow ${B$(r.ocf)}`; who.append(sp); });
      if (!who.childNodes.length) who.append(h("span", null, "None"));
      col.append(who);
      box.append(col);
    });
  }
  function pairBars(box, rows, cfg = {}) {
    if (!box || !box.clientWidth) return;
    const W = boxWidth(box), labelW = Math.round(Math.min(150, Math.max(84, W * 0.22))), padR = 70, rowH = 52, top = 4, bottom = 24, Hh = top + rows.length * rowH + bottom;
    const max = Math.max(...rows.flatMap((r) => [r.a, r.b]).filter(fin)), ticks = niceTicks(0, max, 4), hi = ticks[ticks.length - 1];
    const sx = (v) => labelW + (v / (hi || 1)) * (W - labelW - padR);
    box.replaceChildren();
    const s = svg("svg", { viewBox: `0 0 ${W} ${Hh}`, width: W, height: Hh, role: "img", "aria-label": cfg.label || "Paired bars" }, box);
    ticks.forEach((t) => { svg("line", { x1: sx(t), x2: sx(t), y1: top, y2: Hh - bottom, class: t === 0 ? "baseline" : "gridline" }, s); text(s, sx(t), Hh - 8, cfg.tfmt ? cfg.tfmt(t) : String(t), "ax", "middle"); });
    rows.forEach((r, i) => {
      const y = top + i * rowH + 6;
      text(s, labelW - 10, y + 20, r.label, "cat", "end");
      [[r.a, "var(--s1)", 0, r.aLbl], [r.b, "var(--s2)", 18, r.bLbl]].forEach(([v, col, dy, lbl]) => {
        if (!fin(v)) { text(s, labelW + 6, y + dy + 12, "n/a", "ax", "start"); return; }
        svg("path", { d: hbar(labelW, sx(v), y + dy, 14), fill: col }, s);
        text(s, sx(v) + 6, y + dy + 11, lbl, "lbl-strong", "start");
      });
      const hit = svg("rect", { x: 0, y: top + i * rowH, width: W, height: rowH, class: "hit", tabindex: "0", "aria-label": `${r.label}: ${r.aLbl} operating, ${r.bLbl} non-operating` }, s);
      bindTip(hit, () => [[r.aLbl, `${r.label} · operating`], [r.bLbl, `${r.label} · non-operating`]]);
    });
  }
  function renderPaper() {
    const rows = ["GOOGL", "AMZN", "MSFT"].map(fundRow).filter((r) => r && fin(r.nonop));
    pairBars($("#fu-paper"), rows.map((r) => ({ label: r.name, a: r.op_income, b: r.nonop, aLbl: B$(r.op_income), bLbl: B$(r.nonop) })), { label: "Operating and non-operating income, last twelve months", tfmt: (t) => "$" + t + "B" });
    const box = $("#fu-paper-read");
    if (!box) return;
    box.replaceChildren(h("div", "panel-head"));
    box.firstChild.append(h("span", "panel-title", "If half the marks reverse"));
    const tbl = h("table"), thead = h("thead"), tr0 = h("tr"), tb = h("tbody");
    ["Company", "Marks, share of pre-tax", "Pre-tax income falls", "P/E rises by"].forEach((t, i) => { const th = h("th", i ? "r" : null, t); th.scope = "col"; tr0.append(th); });
    thead.append(tr0);
    rows.forEach((r) => {
      const drop = 0.5 * r.nonop_share, pe = 1 / (1 - drop) - 1, tr = h("tr"), th = h("th", null, r.name);
      th.scope = "row";
      tr.append(th, h("td", "r", pct0(r.nonop_share)), h("td", "r neg", MINUS + fx(drop * 100, 0) + "%"), h("td", "r", "+" + fx(pe * 100, 0) + "%"));
      tb.append(tr);
    });
    tbl.append(thead, tb);
    const w = h("div", "tablewrap");
    w.append(tbl);
    const g = fundRow("GOOGL");
    box.append(w, h("p", "sentence warn", `Alphabet's non-operating income (${B$(g.nonop)}) was larger than its operating income (${B$(g.op_income)}) over the last twelve months. Most of it is marks on private stakes (SpaceX, Anthropic). Value it on operating income: the marks are reflexive, rising with the boom and reversing faster than the business.`));
    const p = h("p", "hint");
    p.append(document.createTextNode("Pre-tax income = operating + non-operating. A reversal of half the marks cuts pre-tax income by half the marks' share; at an unchanged price, the multiple rises by 1 ÷ (1 − cut) − 1. "));
    p.append(srcLink(SRC5.goog98));
    box.append(p);
  }

  /* ---------- the depreciation wave: fitted to reported depreciation, run forward on guidance ---------- */
  const DW = { co: "MSFT", life: 4, g: 0.15 };
  function buildDepr() {
    const sel = $("#dw-co");
    if (!sel || sel.options.length) return;
    FUND.rows.filter((r) => r.depr).forEach((r) => { const o = h("option", null, r.name); o.value = r.t; sel.append(o); });
    sel.value = DW.co;
    sel.addEventListener("change", () => { DW.co = sel.value; guard("Depreciation wave", renderDepr, $("#dw-chart")); });
    $("#dw-life").addEventListener("input", (e) => { DW.life = Number(e.target.value); guard("Depreciation wave", renderDepr, $("#dw-chart")); });
    $("#dw-g").addEventListener("input", (e) => { DW.g = Number(e.target.value); guard("Depreciation wave", renderDepr, $("#dw-chart")); });
  }
  function deprModel(r, life, g) {
    const D = r.depr, hist = Object.fromEntries(Object.entries(D.hist).map(([y, v]) => [Number(y), v]));
    hist[D.guide_year] = r.guide;
    hist[D.guide_year + 1] = r.guide * (1 + g);
    const share = fitShare(hist, D.fit_year, D.reported, D.stated_life);
    const years = [];
    for (let y = D.fit_year - 4; y <= D.guide_year + 1; y++) years.push(y);
    return { D, hist, share, years, stated: deprPath(hist, share, D.stated_life, 25, years), test: deprPath(hist, share, life, 25, years) };
  }
  function renderDepr() {
    const r = fundRow(DW.co);
    if (!r || !r.depr) return;
    $("#dw-life-o").textContent = fx(DW.life, 1) + " years";
    $("#dw-g-o").textContent = sPct(DW.g, 0);
    const M = deprModel(r, DW.life, DW.g), D = M.D, ny = D.guide_year, n2 = ny + 1;
    $("#dw-fit").textContent = `Fitted: ${pct0(M.share)} of ${r.name}'s capex is servers and network gear on a ${fx(D.stated_life, 1)}-year life; the rest (buildings, power) on 25 years. That reproduces the ${B$(D.reported)} of depreciation it reported for fiscal ${D.fit_year}. Fiscal ${ny} capex is the guidance midpoint (${B$(r.guide, 0)}); ${n2} adds the growth you choose.`;
    const extra = M.test[ny] - M.stated[ny], opInc = fin(r.op_income) ? r.op_income : NaN, grow = M.stated[ny] / M.stated[D.fit_year] - 1;
    const out = $("#dw-out");
    out.replaceChildren(roEl(`Fiscal ${ny}, at the stated ${fx(D.stated_life, 1)} years`, B$(M.stated[ny])), roEl(`At a ${fx(DW.life, 1)}-year life`, B$(M.test[ny])),
      roEl(extra >= 0 ? "Extra cost" : "Lower cost", B$(Math.abs(extra)), true), roEl("Share of operating income", fin(opInc) ? fx(Math.abs(extra) / opInc * 100, 0) + "%" : "n/a"));
    const lg = $("#dw-legend");
    lg.replaceChildren();
    [["var(--s1)", `Stated life (${fx(D.stated_life, 1)} years)`], ["var(--s2)", `${fx(DW.life, 1)}-year life`]].forEach(([c, t]) => { const sp = h("span"), i = h("i", "ln"); i.style.background = c; sp.append(i, document.createTextNode(t)); lg.append(sp); });
    $("#dw-chart-title").textContent = `${r.name}: depreciation by fiscal year, $ billions`;
    xyChart($("#dw-chart"), {
      height: 240, label: `${r.name} depreciation by year at the stated and a shorter server life`, zero: true,
      series: [{ name: `Stated ${fx(D.stated_life, 1)} years`, color: "var(--s1)", pts: M.years.map((y) => [y, M.stated[y]]), dots: true },
        { name: `${fx(DW.life, 1)} years`, color: "var(--s2)", pts: M.years.map((y) => [y, M.test[y]]), dots: true }],
      xticks: M.years.map((y) => [y, "FY" + String(y).slice(2)]), yfmt: (v) => "$" + fx(v, 0) + "B", xfmt: (x) => "fiscal " + x,
      vmarks: [{ x: D.fit_year, label: "fit" }],
    });
    $("#dw-read").textContent = `Depreciation is the bill for capex, paid later. ${r.name}'s rises ${sPct(grow, 0)} by fiscal ${ny} at its own stated life, before any change in accounting. `
      + (extra > 0 ? `If servers really last ${fx(DW.life, 1)} years, add ${B$(extra)} more in fiscal ${ny}${fin(opInc) ? `, ${fx(extra / opInc * 100, 0)}% of the last twelve months' operating income` : ""}. The income statement has not felt this yet.` : `At ${fx(DW.life, 1)} years the bill is lower than reported: lives would have to lengthen again.`);
  }
  function renderBacklog() {
    const box = $("#fu-backlog");
    if (!box) return;
    box.replaceChildren();
    const ms = fundRow("MSFT"), oc = fundRow("ORCL"), cw = fundRow("CRWV");
    const card = (tag, title, big, lines, src) => {
      const c = h("article", "card");
      c.append(h("span", "tag", tag), h("h3", null, title), h("span", "big", big));
      const dl = h("dl");
      lines.forEach(([k, v]) => dl.append(h("dt", null, k), h("dd", null, v)));
      c.append(dl);
      if (src) { const p = h("p"); p.append(srcLink(src)); c.append(p); }
      return c;
    };
    box.append(
      card("Backlog", "Microsoft", B$(ms.rpo, 0), [["Remaining performance obligations", `${isoNice(ms.rpo_date)}`], ["Years of revenue", fx(ms.rpo_years, 2)], ["Reading", "A normal multi-year cloud book."]], SRC5.sec),
      card("Backlog and leases", "Oracle", B$(oc.rpo, 0), [["Years of revenue", fx(oc.rpo_years, 2)], ["Leases signed, not yet started", B$(oc.leases_not_commenced, 0) + " (off the balance sheet)"], ["Free cash flow", B$(oc.fcf)], ["Interest covered by cash flow", fx(oc.ocf_to_interest, 1) + " times"]], SRC5.secapi),
      card("Backlog and power", "CoreWeave", B$(cw.rpo, 0), [["Years of revenue", fx(cw.rpo_years, 1)], ["Power", `${fx(cw.power_active_gw, 1)} GW active, ${fx(cw.power_contracted_gw, 1)} GW contracted`], ["Debt", `${B$(cw.debt)}, up ${pct0(cw.debt_yoy)} in a year`], ["Latest quarter", `operating loss of $${Math.round(Math.abs(cw.op_income_lq) * 1000)}M against $${Math.round(cw.interest_lq * 1000)}M of interest`]], SRC5.crwv));
  }
  const LIVES = [
    ["2021", "Alphabet", "Servers 3 to 4 years; network gear 4 to 5", "Lower depreciation (amount not restated here)", SRC5.lives],
    ["FY2023 (Jul 2022)", "Microsoft", "Servers and network gear 4 to 6 years", "About $3.7B of savings in fiscal 2023", SRC5.msftlife],
    ["2022", "Amazon", "Servers 4 to 5 years; network gear 5 to 6", "Depreciation $3.6B lower", ["Hudson Labs", "https://www.hudson-labs.com/research/amazon-server-depreciation-amzn"]],
    ["2023", "Alphabet", "Servers and network gear to 6 years", "Depreciation $3.9B lower; net income $3.0B higher", SRC5.lives],
    ["2024", "Amazon", "Servers 5 to 6 years", "Depreciation $3.2B lower; net income $2.5B higher", ["Hudson Labs", "https://www.hudson-labs.com/research/amazon-server-depreciation-amzn"]],
    ["2025", "Meta", "Servers and network gear 4 to 5 years, to 5.5", "Depreciation about $2.9B lower in 2025", ["Meta 10-K for 2024 (via MyCPE)", "https://my-cpe.com/insights/accounting-and-auditing/how-meta-turned-a-simple-accounting-tweak-into-a-2-9b-payday"]],
    ["2025", "Amazon", "A subset of servers 6 to 5 years: the first shortening", "Depreciation $1.4B higher; net income $1.0B lower", SRC5.amznlife],
  ];
  function renderLives() {
    const tbl = $("#fu-lives");
    if (!tbl) return;
    const thead = h("thead"), tr0 = h("tr"), tb = h("tbody");
    ["When", "Company", "Change", "Effect on earnings", "Source"].forEach((t) => { const th = h("th", null, t); th.scope = "col"; tr0.append(th); });
    thead.append(tr0);
    LIVES.forEach(([w, c, ch, ef, src]) => { const tr = h("tr"), td = h("td"); td.append(srcLink(src)); tr.append(h("td", null, w), h("td", null, c), h("td", null, ch), h("td", null, ef), td); tb.append(tr); });
    tbl.replaceChildren(thead, tb);
  }
  function buildFundamentals() {
    guard("Fundamentals table", renderFundTable, $("#fund-table"));
    guard("Minsky stages", renderMinsky, $("#fu-minsky"));
    guard("Backlog", renderBacklog, $("#fu-backlog"));
    guard("Useful lives", renderLives, $("#fu-lives"));
    guard("Depreciation controls", buildDepr);
  }
  function drawFundamentals() {
    guard("Paper profits", renderPaper, $("#fu-paper"));
    guard("Depreciation wave", renderDepr, $("#dw-chart"));
  }

  /* ============================== PHYSICS ============================== */
  const PH = { capex: 800, cost: 45, load: 0.8 };
  function buildPhysics() {
    const bind = (id, k) => { const el = $(id); if (!el) return; el.value = String(PH[k]); el.addEventListener("input", () => { PH[k] = Number(el.value); guard("Watts calculator", updatePhysics, $("#ph-out")); }); };
    bind("#ph-capex", "capex"); bind("#ph-cost", "cost"); bind("#ph-load", "load");
    guard("Watts calculator", updatePhysics, $("#ph-out"));
    guard("Grid tiles", renderPhysTiles, $("#ph-tiles"));
    guard("Perez markers", renderPerez, $("#ph-perez"));
    guard("Megaproject facts", renderFlyvRead, $("#ph-flyv-read"));
  }
  function updatePhysics() {
    $("#ph-capex-o").textContent = "$" + PH.capex + "B";
    $("#ph-cost-o").textContent = "$" + PH.cost + "B";
    $("#ph-load-o").textContent = Math.round(PH.load * 100) + "%";
    const gw = PH.capex / PH.cost, twh = (gw * 8760 * PH.load) / 1000, homes = (twh * 1e9) / PHYS.homeKWh, share = twh / PHYS.usTWh;
    $("#ph-out").replaceChildren(roEl("New load a year", fx(gw, 1) + " GW", true), roEl("Electricity a year", fx(twh, 0) + " TWh"), roEl("Like adding", fx(homes / 1e6, 1) + "M homes"), roEl("Share of US use", pct(share, 1, false)));
    $("#ph-read").textContent = `One year of AI capex at this pace asks for about ${fx(gw, 0)} GW of new, always-on load, ${pct(share, 1, false)} of today's US electricity. PJM, the largest US grid, came up ${fx(6.623, 1)} GW short of its reliability target for 2027/28 and has a capacity price at its cap. The money can be spent faster than the power can be connected: that is the constraint the capex guidance does not show.`;
  }
  function drawPhysics() {
    barsV($("#ph-dc"), PHYS.dcTWh.map((d) => (fin(d.v) ? { label: String(d.y), v: d.v, lbl: d.v + " TWh", color: "var(--s1)" } : { label: d.y + "e", lo: d.lo, hi: d.hi, lbl: `${d.lo} to ${d.hi}`, color: "var(--s2)" })), { label: "US data-center electricity use, TWh a year", yfmt: (t) => String(t) });
    barsV($("#ph-pjm"), PHYS.pjm.map((d, i) => ({ label: d.y, v: d.v, lbl: "$" + fx(d.v, 2), color: i >= 2 ? "var(--bad)" : "var(--s1)" })), { label: "PJM capacity price, $ per MW-day", yfmt: (t) => "$" + t });
    barsH($("#ph-booms"), PHYS.booms.map((b) => ({ label: b.n, v: b.v, lbl: fx(b.v, 1) + "%", color: b.now ? "var(--accent)" : "var(--s1)", strong: !!b.now, tip: () => [[fx(b.v, 1) + "% of GDP a year", b.n + (b.note ? ` · ${b.note}` : "")]] })), { label: "Investment during each boom, percent of GDP a year", tfmt: (t) => t + "%", labelW: Math.min(260, Math.max(140, boxWidth($("#ph-booms")) * 0.45)) });
    renderFlyv();
  }
  function renderPhysTiles() {
    const box = $("#ph-tiles");
    if (!box) return;
    const P = PHYS, gT = (src, el) => { if (src) { const a = srcLink(src); a.style.display = "block"; el.append(a); } return el; };
    box.replaceChildren(
      gT(SRC5.pjm, tile("PJM shortfall, 2027/28", "6,623 MW", "The first time the auction cleared short of the reliability requirement; price at the cap.")),
      gT(SRC5.gev, tile("GE Vernova gas-turbine backlog", `${P.gev[1].v} GW`, `Up from ${P.gev[0].v} GW a quarter earlier; slots now stretch to the end of the decade.`)),
      gT(SRC5.eia, tile("Residential power prices", sPct(P.power.yoy, 1), `A year to July 2026: Ohio ${sPct(P.power.oh, 1)}, Maryland ${sPct(P.power.md, 1)}. The PJM states lead.`)),
      gT(SRC5.lbnl, tile("Data centers' share of US power", "4.4% → 6.7–12%", "From 176 TWh in 2023 to 325 to 580 TWh by 2028 (LBNL for the DOE).")));
  }
  function renderPerez() {
    const box = $("#ph-perez");
    if (!box) return;
    const g = fundRow("GOOGL"), F = readF();
    const items = [
      ["Installation", "money pours into the new infrastructure ahead of the revenue: five builders spend about 83% of their operating cash flow on capex, and next year's guidance is larger than this year's cash flow."],
      ["Frenzy", `financial markers run ahead of the real ones: a CAPE of 40.9 (top decile since 1881, where ten-year real returns averaged ${sPct(F.cape.rows[9].f, 1)} a year); earnings padded by marks on each other (${pct0(g.nonop_share)} of Alphabet's pre-tax income); special-purpose vehicles at 90% loan to value.`],
      ["Strain", "the physical limit arrives: grid capacity at its price cap, turbine books full to 2030, household power bills up in the states that host the build."],
      ["Turning point (not yet)", "in every earlier revolution the frenzy ended in a financial crash, then a long deployment phase where users gained more than builders. Watch the credit layer: CCC spreads are the first place it shows."],
    ];
    box.replaceChildren(...items.map(([k, t]) => { const li = h("li"); li.append(h("strong", null, k + ": "), document.createTextNode(t)); return li; }));
  }
  function renderFlyv() {
    const box = $("#ph-flyv");
    if (!box || !box.clientWidth) return;
    const W = boxWidth(box), cols = 50, rows = 20, gap = 2, cell = Math.max(3, Math.floor((W - (cols - 1) * gap) / cols)), Hh = rows * (cell + gap);
    box.replaceChildren();
    const s = svg("svg", { viewBox: `0 0 ${W} ${Hh}`, width: W, height: Hh, role: "img", "aria-label": "Of 1,000 big projects, 85 finish on time and on budget, and 5 of those also deliver the promised benefits" }, box);
    for (let i = 0; i < 1000; i++) {
      const c = i % cols, r = Math.floor(i / cols);
      svg("rect", { x: c * (cell + gap), y: r * (cell + gap), width: cell, height: cell, rx: 1.5, fill: i < 5 ? "var(--good)" : i < 85 ? "var(--s1)" : "var(--grid)" }, s);
    }
    const lg = h("div", "legend");
    lg.style.marginTop = "8px";
    [["var(--good)", "5 on time, on budget and on benefits"], ["var(--s1)", "80 more on time and on budget"], ["var(--grid)", "915 late, over budget or both"]].forEach(([c, t]) => { const sp = h("span"), i = h("i"); i.style.background = c; sp.append(i, document.createTextNode(t)); lg.append(sp); });
    box.append(lg);
  }
  function renderFlyvRead() {
    const box = $("#ph-flyv-read");
    if (!box) return;
    const f = PHYS.flyv, cw = fundRow("CRWV");
    const items = [
      ["8.5%", ` of more than ${f.projects.toLocaleString("en-US")} projects came in on time and on budget; 0.5% also delivered the benefits promised.`],
      ["The fat tail", " is in cost: overruns are not normally distributed, and the worst ones are many times the median. Plan for the tail, not the average."],
      ["For the build", `: CoreWeave runs ${fx(cw.power_active_gw, 1)} GW and has contracted ${fx(cw.power_contracted_gw, 1)} GW. If its new capacity is late at the base rate, revenue arrives later than the debt service does.`],
      ["For the model", ": haircut timing in every guidance-based forecast. The desk's depreciation wave assumes guidance is spent on time; late spending moves the wave right, not away."],
    ];
    box.replaceChildren(...items.map(([b, t]) => { const li = h("li"); li.append(h("strong", null, b), document.createTextNode(t)); return li; }));
    const li = h("li");
    li.append(srcLink(SRC5.flyv));
    box.append(li);
  }

  /* ============================== FINDINGS ============================== */
  function findingCard(id, title, claim, numBig, numNote, paras, chartTitle, drawer, changes, link) {
    const art = h("article", "finding");
    art.id = id;
    const txt = h("div", "txt");
    txt.append(h("h3", null, title), h("p", "claim", claim));
    const nb = h("div");
    nb.append(h("span", "num", numBig), h("span", "hint", " " + numNote));
    txt.append(nb);
    paras.forEach(([k, v]) => { const p = h("p"); p.append(h("b", null, k + ". "), document.createTextNode(v)); txt.append(p); });
    const ch = h("p");
    ch.append(h("b", null, "What it changes. "), document.createTextNode(changes + " "));
    if (link) { const a = h("a", null, link[1] + " →"); a.href = "#" + link[0]; ch.append(a); }
    txt.append(ch);
    const fig = h("figure", "chart");
    fig.style.margin = "0";
    const head = h("div", "chart-head");
    head.append(h("span", "chart-title", chartTitle));
    const box = h("div", "svgbox");
    box.id = id + "-chart";
    fig.append(head, box);
    art.append(txt, fig);
    art._draw = () => drawer(box);
    return art;
  }
  function buildFindings() {
    const list = $("#fi-list");
    if (!list) return;
    const F = readF(), H = F.hedge, T = F.tails, R = F.roc, O = F.oil, V = F.vix, S = F.spells, G = F.gold, C = F.cape;
    const below = H.rows.filter((r) => ["Deflation", "0 to 2%", "2 to 3%"].includes(r.bucket)), above = H.rows.filter((r) => !["Deflation", "0 to 2%", "2 to 3%"].includes(r.bucket));
    const wavg = (rs) => rs.reduce((s, r) => s + r.share_hedging * r.months, 0) / rs.reduce((s, r) => s + r.months, 0);
    const cards = [
      findingCard("fi-hedge", "Above about 3% inflation, bonds have mostly stopped hedging stocks; the exact line is uncertain",
        H.split ? `Across ${F.panel.months.toLocaleString("en-US")} months since ${F.panel.start.slice(0, 4)}, the stock-bond correlation was negative (bonds hedged) in ${pct0(H.split.below)} of months when three-year inflation was below ${pctPts(H.split.cut * 100)}, and in ${pct0(H.split.above)} when it was above.`
          : `Across ${F.panel.months.toLocaleString("en-US")} months since ${F.panel.start.slice(0, 4)}, bonds hedged in ${pct0(wavg(below))} of months with three-year inflation below 3%, and ${pct0(wavg(above))} above.`,
        pctPts(H.latest.infl_avg * 100), `three-year inflation now (${monthNice(H.latest.month + "-01")}); ${fin(H.line) ? `the validated line is ${pctPts(H.line * 100)}` : `no line validated (${String(H.status || "unavailable").replace(/_/g, " ")})`}`,
        [["Method", `36-month correlation of monthly S&P 500 total returns against a constant-maturity 10-year bond, bucketed by the same 36 months' inflation. The cut is chosen only on data through ${H.trained_through || "n/a"}${H.zone ? ` (best band ${pctPts(H.zone[0] * 100)} to ${pctPts(H.zone[1] * 100)}; the policy uses the low edge)` : ""}, then tested on the untouched decade after it${H.holdout && fin(H.holdout.gap) ? `: bonds hedged ${pct0(H.holdout.gap)} more often below the line than above it` : ""}.`],
          ["Uncertainty", H.bootstrap && fin(H.bootstrap.cut_p05) ? `A block bootstrap that re-chooses the cut puts the line anywhere from ${pctPts(H.bootstrap.cut_p05 * 100)} to ${pctPts(H.bootstrap.cut_p95 * 100)}. Walk-forward: the cut chosen on the past held in ${(H.walk_forward || []).filter((w) => w.held).length} of ${(H.walk_forward || []).length} later 20-year blocks. Overlapping windows leave about ${H.bootstrap.independent_windows} independent three-year periods.` : "Overlapping windows: about 52 independent three-year periods, not 1,868."],
          ["Does it add value?", H.experiment ? `Out of sample since ${H.experiment.from.slice(0, 4)}, a 30% bond overlay gated by correlation and inflation had worst-month losses of ${sPct(H.experiment.rules.correlation_and_inflation.worst5, 2)}, against ${sPct(H.experiment.rules.correlation_only.worst5, 2)} for the correlation rule alone and ${sPct(H.experiment.rules.never.worst5, 2)} unhedged. ${H.experiment.inflation_adds_value ? "Inflation conditioning helped." : "Inflation conditioning added nothing measurable: the correlation state is the gate that matters."}` : "Not yet tested."],
          ["Today", `Correlation ${sgn2(H.latest.corr)} over 36 months. At 2% inflation from here, the average stays above 2.75% for about ${ROC_SNAP.cpi.months_to_line} months: base effects keep it there.`]],
        "Share of months bonds hedged, by three-year inflation",
        (box) => barsV(box, H.rows.map((r) => ({ label: r.bucket.replace(" to ", "–"), v: r.share_hedging * 100, lbl: pct0(r.share_hedging), color: ["3 to 4%", "4 to 6%", "Above 6%"].includes(r.bucket) ? "var(--bad)" : "var(--s1)", tip: () => [[pct0(r.share_hedging) + " of months", `${r.bucket} · ${r.months} months · mean correlation ${sgn2(r.mean_corr)}`]] })), { label: "Share of months with a negative stock-bond correlation, by inflation bucket", yfmt: (t) => t + "%", max: 70 }),
        "The TLT hedge waits for the stock-bond state; options, gold and energy carry the hedge meanwhile.", ["d-duration", "Decision 2"]),
      findingCard("fi-tails", "Crashes are thousands of times more common than a bell curve allows",
        `Monthly stock returns since 1871 had ${T.rows[3].obs} six-sigma down months; a normal distribution with the same volatility expects one every ${fx(T.rows[3].every / 1e6, 1)} million years.`,
        "α " + fx(T.alpha, 2), "tail index (Hill, worst 5% of months): moments of order α and above do not exist, so kurtosis is infinite",
        [["Method", `Log returns standardized by their full-sample mean and standard deviation (${fx(T.sigma * 100, 2)}% a month), counted beyond 3 to 6 sigma, against the normal's expected count. The tail index uses the worst 5% of months.`],
          ["Caveat", "Volatility clusters, so part of the excess is regime, not shape. That is the point: the regime is the risk."],
          ["Worst months", T.worst.map((w) => `${w.m} (${fx(w.s, 1)}σ)`).join(", ") + "."]],
        "Down months beyond k sigma, observed against normal (log scale)",
        (box) => barsH(box, T.rows.flatMap((r) => [{ label: `${r.k}σ observed`, v: r.obs, lbl: String(r.obs), color: "var(--bad)", strong: true }, { label: `${r.k}σ normal`, v: r.exp, lbl: r.exp >= 0.1 ? fx(r.exp, 1) : r.exp.toExponential(1).replace("e-", "e−"), color: "var(--muted)" }]), { log: true, label: "Observed and normal-model counts of down months beyond 3 to 6 standard deviations", rowH: 24 }),
        "Size to the stress, not the standard deviation; own convexity.", ["swans", "Swans desk"]),
      findingCard("fi-roc", "The best time to buy was when earnings growth was falling and slowing",
        `Since ${R.since}, the next 12 months' real return averaged ${sPct(R.rows[3].mean, 1)} when earnings growth was negative and decelerating, against ${sPct(R.rows[0].mean, 1)} when it was positive and accelerating.`,
        sPct(R.rows[3].mean - R.rows[0].mean, 1), "a year: the gap between the worst and best-looking states",
        [["Method", `Earnings growth over 12 months (the level) and its change over 6 months (the second derivative), four states, each followed by the next 12 months' real total return. ${R.rows.map((x) => `${x.state}: ${x.n} months`).join("; ")}.`],
          ["Why", "Markets price the rate of change before it shows: by the time growth is visibly falling and slowing, the price has already fallen. Druckenmiller's rule in numbers."],
          ["Caveat", `Earnings data end ${R.until}; Shiller's file updates slowly.`]],
        "Next 12 months' real return by the state of earnings growth",
        (box) => barsV(box, R.rows.map((r) => ({ label: r.state.replace("Growth ", "").replace(", ", " · "), v: r.mean * 100, lbl: sPct(r.mean, 1), color: r.state.startsWith("Growth down") ? "var(--good)" : "var(--s1)", tip: () => [[sPct(r.mean, 1), `${r.state} · ${r.n} months · positive ${pct0(r.up)}`]] })), { label: "Mean forward 12-month real return by earnings state", yfmt: (t) => t + "%" }),
        "Rates of change outrank levels on the Decide desk.", ["roc-title", "Rates of change"]),
      findingCard("fi-oil", "Supply oil shocks hurt stocks; demand rebounds did not",
        `Since 1989, when Brent rose 50% in a year while far above its five-year average (a supply shock), the S&P 500 returned ${sPct(O.summary.supply.mean_fwd12, 1)} on average over the next year (${O.summary.supply.n} cases, ${pct0(O.summary.supply.share_up)} up). After a rebound from a low base: ${sPct(O.summary.rebound.mean_fwd12, 1)} (${O.summary.rebound.n} cases, ${pct0(O.summary.rebound.share_up)} up).`,
        fx(ROC_SNAP.oil.vs_avg5y, 2) + "x", `Brent against its five-year average now: a supply shock by this rule`,
        [["Method", "First month of each run with Brent up more than 50% on the year; supply if price is above 1.3 times its 60-month average, rebound otherwise."],
          ["Caveat", "Nine and eight cases: direction, not law (assumption a-samples)."],
          ["2026", O.rows.filter((r) => !fin(r.fwd)).map((r) => `${monthNice(r.m + "-01")} averaged $${fx(r.brent, 1)}, ${fx(r.rel, 2)} times its five-year average`).join("; ") + ": both supply shocks by this rule."]],
        "Next 12 months' S&P 500 return after an oil spike",
        (box) => barsH(box, [{ label: `Supply shocks (${O.summary.supply.n})`, v: O.summary.supply.mean_fwd12 * 100, lbl: sPct(O.summary.supply.mean_fwd12, 1), color: "var(--bad)", tip: () => [[sPct(O.summary.supply.mean_fwd12, 1), `supply shocks · ${pct0(O.summary.supply.share_up)} up`]] },
          { label: `Rebounds (${O.summary.rebound.n})`, v: O.summary.rebound.mean_fwd12 * 100, lbl: sPct(O.summary.rebound.mean_fwd12, 1), color: "var(--good)", tip: () => [[sPct(O.summary.rebound.mean_fwd12, 1), `demand rebounds · ${pct0(O.summary.rebound.share_up)} up`]] }],
          { label: "Mean next-year S&P 500 return after supply shocks and demand rebounds", tfmt: (t) => t + "%", rowH: 40 }),
        "An energy sleeve while Brent is above the supply line.", ["d-inflation", "Decision 3"]),
      findingCard("fi-vix", "Buying the first VIX spike paid, and the bigger the spike the better",
        `After the first close above 30 in a year (${V.s30.n} cases since 1990), the S&P 500 returned ${sPct(V.s30.mean, 1)} over the next 12 months; above 40 (${V.s40.n} cases), ${sPct(V.s40.mean, 1)}, up ${pct0(V.s40.up)} of the time.`,
        fx(V.half_life, 0) + " days", "VIX half-life: spikes decay fast",
        [["Method", "First month with a VIX high above 30 (or 40) after a year without one; forward return from that month-end."],
          ["Caveat", "Survivorship of the index, small samples, and a regime where the Fed eased into most spikes. In an inflation regime it may not."],
          ["Use", "It is why the tail rule monetizes in stages: a spike is when insurance is worth the most and stocks are cheapest."]],
        "Next 12 months' S&P 500 return after the first VIX spike",
        (box) => barsV(box, [{ label: `VIX above 30 (${V.s30.n})`, v: V.s30.mean * 100, lbl: sPct(V.s30.mean, 1), color: "var(--s1)" }, { label: `VIX above 40 (${V.s40.n})`, v: V.s40.mean * 100, lbl: sPct(V.s40.mean, 1), color: "var(--good)" }], { label: "Mean next-year return after VIX spikes", yfmt: (t) => t + "%" }),
        "Monetize puts in stages into spikes; never chase protection after one.", ["d-tail", "Decision 4"]),
      findingCard("fi-spells", "Inflation above 5% took a median of 29 months to get back below 3%",
        (() => { const done = S.eps.filter((e) => fin(e.n)), longest = done.slice().sort((a, b) => b.n - a.n)[0], last = done[done.length - 1];
          return `${S.eps.length} episodes since 1913.` + (longest ? ` The longest, from ${longest.from.slice(0, 4)}, lasted ${longest.n} months; the latest, from ${last.from.slice(0, 4)}, ${last.n}.` : ""); })(),
        fx(S.median, 0) + " months", `median, from crossing 5% to below 3%; inflation is ${pctPts(S.latest * 100)} now (${monthNice(S.month + "-01")})`,
        [["Method", "Year-over-year CPI-U; an episode starts when inflation crosses above 5% and ends at the first month below 3%."],
          ["Caveat", "Wartime spells (1916, 1941, 1946) mix price controls into the record."],
          ["Use", "Base rates for the Fed path: once above 5%, plan in years, not quarters."]],
        "Months from above 5% to below 3%, each episode",
        (box) => barsH(box, S.eps.filter((e) => fin(e.n)).map((e) => ({ label: `${e.from.slice(0, 4)} (peak ${fx(e.peak * 100, 0)}%)`, v: e.n, lbl: e.n + " mo", color: e.n > S.median ? "var(--bad)" : "var(--s1)" })), { label: "Duration of each inflation episode in months", rowH: 24, tfmt: (t) => t + "" }),
        "Assume a long road back to the line.", ["d-duration", "Decision 2"]),
      findingCard("fi-gold", "Gold hedged stock drawdowns when bonds could not",
        `Since ${G.since}, in years when inflation ran above 4%, gold returned ${sPct(G.high_infl.gold, 1)} a year after inflation against ${sPct(G.high_infl.stocks, 1)} for stocks. When stocks fell more than 15% in real terms, gold returned ${sPct(G.stocks_down15.gold, 1)}, up ${pct0(G.stocks_down15.share_gold_up)} of the time.`,
        sPct(G.stocks_down15.gold, 1), "gold's real 12-month return when stocks fell 15%",
        [["Method", "Rolling 12-month real returns, monthly, split by inflation above or below 4% and by real stock returns below minus 15%."],
          ["Caveat", `${G.stocks_down15.months} overlapping months, from a handful of drawdowns.`],
          ["Low inflation", `The order flips: stocks ${sPct(G.low_infl.stocks, 1)}, gold ${sPct(G.low_infl.gold, 1)}. Gold is a regime hedge, not a permanent one.`]],
        "Real 12-month return, gold against stocks",
        (box) => barsV(box, [{ label: "Gold, high inflation", v: G.high_infl.gold * 100, lbl: sPct(G.high_infl.gold, 1), color: "var(--s2)" }, { label: "Stocks, high inflation", v: G.high_infl.stocks * 100, lbl: sPct(G.high_infl.stocks, 1), color: "var(--s1)" },
          { label: "Gold, stocks down 15%", v: G.stocks_down15.gold * 100, lbl: sPct(G.stocks_down15.gold, 1), color: "var(--s2)" }], { label: "Real returns of gold and stocks by regime", yfmt: (t) => t + "%" }),
        "Gold is half of the inflation sleeve.", ["d-inflation", "Decision 3"]),
      findingCard("fi-cape", "From today's valuation, history's ten-year returns were thin",
        `When the cyclically adjusted P/E was in its top decile (above ${fx(C.rows[9].lo, 1)}), the next ten years' real return averaged ${sPct(C.rows[9].f, 1)} a year; above 30 it averaged ${sPct(C.above30.mean, 1)} (${C.above30.months} months). The CAPE is 40.9 now.`,
        "40.9", "CAPE, Oct 20 (multpl.com); top decile since 1881",
        [["Method", "Shiller's CAPE in deciles; forward 10-year annualized real total return from each month."],
          ["Caveat", "Valuation sets the long-run return, never the timing: CAPE was above 30 for most of 1997 to 2001 and 2017 to 2021."],
          ["Range in the top decile", `${sPct(C.rows[9].w, 1)} to ${sPct(C.rows[9].b, 1)} a year. The average, ${sPct(C.rows[9].f, 1)}, is about half the ${sPct(C.rows.reduce((s, r) => s + r.f * r.n, 0) / C.rows.reduce((s, r) => s + r.n, 0), 1)} of all months.`]],
        "Next 10 years' real return a year, by starting CAPE decile",
        (box) => barsV(box, C.rows.map((r) => ({ label: "D" + r.d, v: r.f * 100, lbl: fx(r.f * 100, 1), color: r.d === 10 ? "var(--bad)" : "var(--s1)", tip: () => [[sPct(r.f, 1) + " a year", `CAPE ${fx(r.lo, 1)} to ${fx(r.hi, 1)} · ${r.n} months`]] })), { label: "Forward ten-year real return by CAPE decile", yfmt: (t) => t + "%" }),
        "Expect less from the book's beta; earn it from the hedges and the tilts.", ["lg-buffett", "Buffett's lens"]),
    ];
    list.replaceChildren(...cards);
    const read = $("#fi-read");
    read.replaceChildren();
    const p = h("p");
    p.append(h("strong", null, "Read together: "), document.createTextNode(`the regime that makes this book dangerous is the one where the textbook hedges fail. Above the inflation line bonds hedged ${pct0(H.split ? H.split.above : wavg(above))} of the time; supply oil shocks preceded falling stocks; valuations are in the top decile. What worked in that regime: gold in drawdowns, convexity bought before the spike and sold into it, and buying when earnings growth was falling and slowing. Every finding feeds a rule on the Decide desk.`));
    read.append(p);
  }
  function drawFindings() {
    document.querySelectorAll("#fi-list .finding").forEach((c) => { if (c._draw) guard("Finding " + c.id, c._draw, c.querySelector(".svgbox")); });
  }

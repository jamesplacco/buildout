  /* =====================================================================================
     ooda.js (v0.11): the harness for the decision engine. Renders ooda.json (or the engine's snapshot of it) as the
     Decision loop, the Positions desk and the Engine room; the hedge book is interactive (hedgebook.js).
     ===================================================================================== */
  const oodaOk = (o) => {
    try {
      return !!(o && o.observe && Array.isArray(o.observe.moved) && o.orient && o.orient.positions && typeof o.orient.positions === "object" && o.decide && Array.isArray(o.decide.positions) &&
        o.decide.positions.every((a) => a && typeof a.ticker === "string" && fin(a.weight) && fin(a.target) && typeof a.action === "string") && o.decide.hedges && o.decide.posterior && typeof o.decide.posterior === "object" &&
        o.act && Array.isArray(o.act.proposals) && o.valuation && o.valuation.positions && typeof o.valuation.positions === "object");
    } catch (e) { return false; }
  };
  function oodaData() { return LIVE.ooda && oodaOk(LIVE.ooda) ? LIVE.ooda : OODA_SNAP; }
  const oodaLive = () => !!(LIVE.ooda && oodaOk(LIVE.ooda));
  const VERDICT = { extreme: ["Priced for the extreme", "ev-hyp"], exuberant: ["Priced for exceptional growth", "ev-hyp"], within: ["Within the base rates", "ev-est"], pessimistic: ["Priced for decline", "ev-obs"], insufficient: ["Not enough to judge", "ev-na"] };
  const ACTION_TXT = { trim: "Trim", "hold and hedge": "Hold and hedge", hold: "Hold", add: "Add candidate", investigate: "Investigate" };
  const nodeNm = (id) => (BR_IDX[id] != null ? BR_NODES[BR_IDX[id]].n : String(id));
  const badge = (code) => { const [t, c] = VERDICT[code] || ["n/a", "ev-na"]; return h("span", "ev " + c, t); };
  const pctOrNa = (v, d = 0) => (fin(v) ? fx(v * 100, d) + "%" : "n/a");
  const bnFmt = (v) => (fin(v) ? (Math.abs(v) >= 1000 ? "$" + fx(v / 1000, 2) + "T" : "$" + fx(v, 0) + "B") : "n/a");
  const share = (p) => (!fin(p) ? "n/a" : p < 0.001 ? "< 0.1%" : p < 0.1 ? fx(p * 100, 1) + "%" : pct0(p));
  const scenIds = () => RZ_SCENARIOS.map((s) => s.id);

  /* ---------- the hedge book (interactive) ---------- */
  const HBS = (() => {
    const st = LS.get("bo-hedges", null);
    const ok = st && typeof st === "object" && st.on && typeof st.on === "object" && st.sizes && typeof st.sizes === "object";
    const sizes = {}, on = {};
    HB_HEDGES.forEach((x) => {
      const v = ok ? Number(st.sizes[x.id]) : NaN;
      sizes[x.id] = fin(v) ? clamp(v, x.range[0], x.range[1]) : x.def;
      on[x.id] = ok ? st.on[x.id] === true : false;
    });
    return { on, sizes, e: ok && fin(st.e) ? clamp(st.e, 0.2, 1.5) : 1.0, wired: false };
  })();
  const hbSave = () => LS.set("bo-hedges", { on: HBS.on, sizes: HBS.sizes, e: HBS.e });
  function hbPost() { const p = oodaData().decide.posterior, ids = scenIds(); const v = ids.map((k) => Number(p[k])); return v.every(fin) ? v : RZ_SCENARIOS.map((s) => s.prior); }
  const hbFmtSize = (x, v) => (x.unit === "x equity" ? fx(v, 2) + "x" : x.unit.startsWith("of NAV") ? fx(v * 100, 2).replace(/\.?0+$/, "") + "% of NAV" : Math.round(v * 100) + "% " + x.unit.replace(/^of /, "of "));
  function buildHedgeBook() {
    const box = $("#hb-list");
    if (!box || HBS.wired) return;
    HBS.wired = true;
    HB_HEDGES.forEach((x) => {
      const card = h("div", "hb-card"), top = h("div", "hb-top"), sw = h("button", "hb-sw");
      sw.type = "button"; sw.dataset.h = x.id;
      sw.setAttribute("role", "switch");
      sw.setAttribute("aria-label", `${x.name}: on or off`);
      sw.addEventListener("click", () => { HBS.on[x.id] = !HBS.on[x.id]; hbSave(); renderHedgeBook(); });
      top.append(sw, h("b", null, x.name));
      const f = h("div", "field"), ft = h("div", "field-top"), lab = h("label", null, "Size"), out = h("output", null, ""), inp = h("input");
      lab.htmlFor = `hb-sz-${x.id}`; inp.id = `hb-sz-${x.id}`; inp.type = "range"; inp.min = x.range[0]; inp.max = x.range[1]; inp.step = x.step; inp.value = HBS.sizes[x.id];
      out.id = `hb-sz-${x.id}-o`;
      inp.addEventListener("input", () => { HBS.sizes[x.id] = Number(inp.value); hbSave(); renderHedgeBook(); });
      ft.append(lab, out); f.append(ft, inp);
      card.append(top, f, h("p", "hint", `Protects: ${x.protects.map((k) => (RZ_SCENARIOS.find((s) => s.id === k) || { name: k }).name).join(", ")}. ${x.note}`), h("p", "hb-eff num", ""));
      card.dataset.h = x.id;
      box.append(card);
    });
    const e = $("#hb-e");
    e.value = HBS.e;
    e.addEventListener("input", () => { HBS.e = Number(e.value); hbSave(); renderHedgeBook(); });
    $("#hb-reset").addEventListener("click", () => { HB_IDS.forEach((k) => { HBS.on[k] = false; }); hbSave(); renderHedgeBook(); });
    $("#hb-copy").addEventListener("click", async () => {
      const on = HB_IDS.filter((k) => HBS.on[k]);
      const txt = `[hedges]\non = [${on.map((k) => `"${k}"`).join(", ")}]\nequity = ${fx(HBS.e, 2)}\n\n[hedges.sizes]\n${HB_IDS.map((k) => `${k} = ${HBS.sizes[k]}`).join("\n")}\n`;
      try { await navigator.clipboard.writeText(txt); $("#hb-msg").textContent = "Copied. Paste into config.toml and the daily run uses these switches."; }
      catch (err) { const ta = $("#hb-export"); ta.hidden = false; ta.value = txt; ta.select(); $("#hb-msg").textContent = "Copy was blocked here: the settings are selected below."; }
    });
  }
  function renderHedgeBook() {
    if (!$("#hb-list")) return;
    buildHedgeBook();
    const post = hbPost(), on = {};
    HB_IDS.forEach((k) => { if (HBS.on[k]) on[k] = HBS.sizes[k]; });
    $("#hb-e-o").textContent = xx(HBS.e);
    const r = hbEvaluate(on, HBS.e, post), base = r.base;
    document.querySelectorAll("#hb-list .hb-card").forEach((card) => {
      const k = card.dataset.h, x = HB_HEDGES.find((y) => y.id === k), sw = card.querySelector(".hb-sw");
      sw.setAttribute("aria-checked", HBS.on[k] ? "true" : "false");
      sw.textContent = HBS.on[k] ? "On" : "Off";
      card.classList.toggle("on", !!HBS.on[k]);
      $(`#hb-sz-${k}-o`).textContent = hbFmtSize(x, HBS.sizes[k]);
      const solo = hbEvaluate({ [k]: HBS.sizes[k] }, HBS.e, post);
      card.querySelector(".hb-eff").textContent = `Alone: worst case ${sPct(solo.worst, 1)} (book ${sPct(Math.min(...base), 1)}), expected cost ${fx(solo.cost_bp, 0)}bp a quarter`;
    });
    fillTable($("#hb-scen"), ["Scenario", `Odds (engine run, ${isoNice(oodaData().as_of)} signals)`, "Book", "With hedges"], RZ_SCENARIOS.map((s, i) => [s.name, pct0(post[i]), sPct(base[i], 1), sPct(r.rets[i], 1)]), 1);
    const nOn = Object.keys(on).length, L = RZ_DEFAULTS.max_loss;
    $("#hb-sum").textContent = `Current book (proposals are listed under Act): ${nOn} hedge${nOn === 1 ? "" : "s"} on · growth ${sPct(r.ce, 2)} a quarter · worst ${sPct(r.worst, 1)} ${r.worst >= -L - 1e-12 ? "(inside" : "(outside"} the ${Math.round(L * 100)}% loss limit) · cost ${fx(r.cost_bp, 0)}bp`;
    const sizes = Object.assign({}, HBS.sizes), adv = hbAdvisor(sizes, HBS.e, post), al = $("#hb-adv");
    al.replaceChildren();
    const show = (lab, row) => {
      if (!row) return;
      const li = h("li"), btn = h("button", "pill", "Use");
      btn.type = "button";
      btn.setAttribute("aria-label", `Use the set: ${lab}`);
      btn.addEventListener("click", () => { HB_IDS.forEach((k) => { HBS.on[k] = row.on.includes(k); }); hbSave(); renderHedgeBook(); });
      li.append(h("span", null, `${lab}: ${row.on.length ? row.on.map((k) => HB_HEDGES.find((x) => x.id === k).name).join(", ") : "no hedges"}`), h("b", "num", `worst ${sPct(row.worst, 1)} · ${fx(row.cost_bp, 0)}bp`), btn);
      al.append(li);
    };
    show("Cheapest set inside the loss limit", adv.cheapest_meeting_limit[0]);
    show("Best growth", adv.best_growth[0]);
    show("Best worst case", adv.best_worst_case[0]);
    $("#hb-adv-t").textContent = `${adv.combinations} combinations at the sizes above; ${adv.meets_limit} keep every scenario inside the ${Math.round(L * 100)}% loss limit. Cost is the expected return given up under the scenario odds, plus an assumed 5bp a quarter for each hedge run. A negative cost means the scenario odds price the hedge below its expected payoff: check that against what the options market charges.`;
    if (typeof requestAnimationFrame === "function") requestAnimationFrame(() => fixChartRoles($("#view-ooda")));
  }

  /* ---------- the decision loop ---------- */
  function renderOODA() {
    const o = oodaData(), box = $("#oo-strip");
    if (!box) return;
    $("#oo-status").textContent = `${oodaLive() ? "Engine run of " + isoNice(o.as_of) : "Engine output as of " + isoNice(o.as_of)} · fundamentals ${o.observe.inputs ? o.observe.inputs.fundamentals : "n/a"} · prices ${o.observe.inputs ? o.observe.inputs.prices : "n/a"} · model book, not personal positions`;
    // observe
    const ml = $("#oo-moved");
    ml.replaceChildren();
    o.observe.moved.forEach((m) => { const li = h("li"); li.append(h("span", null, nodeNm(m.node)), h("b", "num", sg(m.z, 2) + "σ")); ml.append(li); });
    const su = o.observe.surprise || {}, W = o.observe.world;
    if (W && Array.isArray(W.p) && Array.isArray(W.blends)) {
      barsH($("#oo-world"), W.blends.map((b, i) => ({ label: blendName(b), v: W.p[i] * 100, lbl: pct0(W.p[i]), color: W.p[i] === Math.max(...W.p) ? "var(--s1)" : "var(--s2)" })), { label: "Posterior probability of each version of the map", fmt: (v) => fx(v, 0) + "%" });
    }
    const top = o.observe.moved[0];
    $("#oo-obs-t").textContent = `${top ? `${nodeNm(top.node)} moved most (${sg(top.z, 2)}σ over three months). ` : ""}The readings ${fin(su.p) && su.p < 0.05 ? "are surprising for the map (p " + fx(su.p, 3) + "): something it does not model is moving." : `are within what the map expects (p ${fin(su.p) ? fx(su.p, 2) : "n/a"}).`} ${W && fin(W.mean_blend) ? `They fit the ${W.mean_blend < 0.5 ? "pre-2022" : "inflation-era"} relationships better (${Math.round(W.mean_blend * 100)}% of the way to the 2022-on world).` : ""}`;
    // orient
    const el = $("#oo-expl");
    el.replaceChildren();
    const ex = o.orient.explanations || [], shown = ex.reduce((a, r) => a + (fin(r.p) ? r.p : 0), 0);
    ex.forEach((r) => { const li = h("li"); li.append(h("span", null, r.cause === "noise only" ? "Nothing unusual" : nodeNm(r.cause)), h("b", "num", pct0(r.p))); el.append(li); });
    if (ex.length && shown < 0.995) { const li = h("li"); li.append(h("span", null, "Other single causes, each under the list"), h("b", "num", pct0(1 - shown))); el.append(li); }
    const kl = o.orient.key_link && o.orient.key_link.regimes, ki = kl && kl.inflation, ko = kl && kl.low_inflation;
    $("#oo-link").textContent = ki && fin(ki.ols) ? `The link the bond hedge rests on (10-year to stocks) reads ${sg(ki.ols, 2)} since 2022 with a Newey-West t of ${fx(ki.hac_t, 1)}${ki.months_to_flip ? ` and reverses on ${ki.months_to_flip} months` : ""}; ${ko && fin(ko.ols) ? `${sg(ko.ols, 2)} before 2022.` : ""} Treat its sign as a hypothesis.` : "";
    const cb = o.orient.crisis_behaviour || {}, cm = cb.in_stocks_worst_months || {};
    fillTable($("#oo-crisis"), ["Asset", "Average move, σ", "Helps a long book?"], Object.entries(cm).filter(([, v]) => fin(v)).map(([k, v]) => {
      const helps = k === "y10" ? v < -0.2 : k === "gold" ? v > 0.2 : k === "vix" ? v > 0.5 : null;
      return [k === "y10" ? "10-year yield (bonds rally when it falls)" : nodeNm(k), sg(v, 2), helps == null ? "" : helps ? "Yes" : "No"];
    }), 1);
    $("#oo-crisis-t").textContent = `Regime used: ${cb.regime === "inflation" ? "2022 on" : "1990 to 2021"}, the one today's readings fit better. ${fin(cm.y10) ? (cm.y10 < 0 ? "In this regime yields fell when stocks crashed: long bonds hedged." : "In this regime yields rose when stocks crashed: long bonds added to the loss.") : ""}`;
    const V = o.valuation.positions, P = o.orient.positions;
    fillTable($("#oo-pos"), ["Position", "Verdict", "Accounting", "Main risk", "Implied growth", "Companies this size that did it"], Object.keys(P).map((t) => {
      const p = P[t], v = V[t] || {};
      return [`${t} · ${v.name || t}`, (VERDICT[(p.verdict || {}).code] || ["n/a"])[0], p.quality || "n/a", p.why && p.why[0] ? p.why[0].driver.replace(/_/g, " ") : "", pctOrNa(p.implied_growth), share(p.p_achieve)];
    }), 4);
    const counts = {};
    Object.values(P).forEach((p) => { const c = (p.verdict || {}).code || "insufficient"; counts[c] = (counts[c] || 0) + 1; });
    $("#oo-ori-t").textContent = `${counts.extreme || 0} of ${Object.keys(P).length} positions are priced for growth fewer than 1 in 100 companies of their size achieved, ${counts.exuberant || 0} for growth fewer than 1 in 20 achieved, and ${counts.within || 0} within the base rates${counts.pessimistic ? `; ${counts.pessimistic} priced for decline` : ""}${counts.insufficient ? `; ${counts.insufficient} without enough data to judge` : ""}. ${(o.orient.explanations || [])[0] ? `The leading explanation of today's readings: ${o.orient.explanations[0].cause === "noise only" ? "nothing unusual" : nodeNm(o.orient.explanations[0].cause)}.` : ""}`;
    // decide
    const S = o.decide.solver || {}, nom = S.nominal, rob = S["robust_rho_0.05"];
    $("#oo-dec-t").textContent = nom && rob ? `The solver's choice is ${xx(nom.port[0])} equity (growth ${sPct(nom.ce, 2)} a quarter on its own odds); allowing modest doubt about those odds (KL 0.05) it chooses ${xx(rob.port[0])} equity (${sPct(rob.ce, 2)} guaranteed). The positions below come from what each price requires.` : "";
    renderHedgeBook();
    fillTable($("#oo-actions"), ["Position", "Action", "Confidence", "Kill criterion", "Weight"], o.decide.positions.map((a) => [a.ticker, ACTION_TXT[a.action] || a.action, a.confidence,
      (a.frameworks || {}).kill_criteria || "", Math.abs(a.target - a.weight) > 1e-9 ? `${pct0(a.weight)} → ${fx(a.target * 100, 1)}%` : pct0(a.weight)]), 4);
    // act
    const pl = $("#oo-props");
    pl.replaceChildren();
    o.act.proposals.forEach((p) => {
      const li = h("li");
      if (p.type === "position") li.append(h("span", null, `${ACTION_TXT[p.action] || p.action} ${p.ticker}: ${fx(p.from * 100, 1)}% → ${fx(p.to * 100, 1)}%`), h("b", "num", `${p.confidence} confidence · two-way door`));
      else li.append(h("span", null, `${p.action === "switch on" ? "Switch on" : "Switch off"} ${(HB_HEDGES.find((x) => x.id === p.hedge) || { name: p.hedge }).name}`), h("b", "num", p.why ? "advisor" : ""));
      pl.append(li);
    });
    if (!o.act.proposals.length) pl.append(h("li", "none", "No changes proposed: hold as is."));
    const wl = $("#oo-watch");
    wl.replaceChildren();
    (o.act.watch || []).forEach((w) => { const li = h("li"); li.append(h("span", null, nodeNm(w.node)), h("b", "num", fin(w.information_nats) ? fx(w.information_nats, 3) + " nats" : "")); wl.append(li); });
    $("#oo-review").textContent = `Look again by ${isoNice(o.act.review_by)}, or sooner if a watched reading moves: the loop is only as good as its tempo.`;
    const nT = o.act.proposals.filter((p) => p.type === "position").length, nH = o.act.proposals.length - nT, freed = fin(o.decide.freed_weight) ? o.decide.freed_weight : 0;
    $("#oo-act-t").textContent = `${nT} position change${nT === 1 ? "" : "s"} and ${nH} hedge switch${nH === 1 ? "" : "es"} proposed${freed > 0 ? `, freeing ${fx(freed * 100, 1)}% of NAV to cash` : ""}. Each is a two-way door; each carries the evidence that would reverse it.`;
    $("#oo-frames").textContent = Object.values(o.frameworks || {}).join(" ");
    // the strip
    box.replaceChildren();
    [["Observe", "#oo-obs-sec", $("#oo-obs-t").textContent], ["Orient", "#oo-ori-sec", $("#oo-ori-t").textContent], ["Decide", "#oo-dec-sec", $("#oo-dec-t").textContent], ["Act", "#oo-act-sec", $("#oo-act-t").textContent]].forEach(([n, href, t], i) => {
      const li = h("li", "oo-step"), a = h("a");
      a.href = href.replace("#", "#");
      a.append(h("span", "oo-n", String(i + 1)), h("b", null, n));
      li.append(a, h("p", null, t.split(". ")[0] + (t.includes(". ") ? "." : "")));
      box.append(li);
    });
  }
  function wireOODA() {
    const c = $("#oo-copy");
    if (!c || c.dataset.wired) return;
    c.dataset.wired = "1";
    c.addEventListener("click", async () => {
      const o = oodaData(), on = HB_IDS.filter((k) => HBS.on[k]);
      const rec = { recorded: new Date().toISOString(), as_of: o.as_of, source: oodaLive() ? "engine run" : "engine output as shipped", proposals: o.act.proposals, hedges_on: on, equity: HBS.e,
        positions: o.decide.positions.map((a) => ({ ticker: a.ticker, action: a.action, from: a.weight, to: a.target, confidence: a.confidence, kill: (a.frameworks || {}).kill_criteria })) };
      const txt = JSON.stringify(rec, null, 2);
      try { await navigator.clipboard.writeText(txt); $("#oo-msg").textContent = "Copied: paste it into the journal's import or keep it with the decision."; }
      catch (e) { const ta = $("#oo-export"); ta.hidden = false; ta.value = txt; ta.select(); $("#oo-msg").textContent = "Copy was blocked here: the record is selected below."; }
    });
  }

  /* ---------- the positions desk ---------- */
  const PS = { filter: "all" };
  const QUAL_ROWS = [["op_margin", "Operating margin", "pct"], ["cash_conversion", "Cash conversion (OCF / operating earnings)", "x"], ["accruals", "Accruals / assets", "pct"],
    ["sbc_to_revenue", "Stock pay / revenue", "pct"], ["owner_fcf_margin", "Free cash flow after stock pay / revenue", "pct"], ["steady_fcf_margin", "Steady-state free cash flow margin", "pct"], ["working_capital_lift", "Cash flow above operating earnings / revenue", "pct"],
    ["capex_to_da", "Capex / D&A", "x"], ["depreciation_drag", "Operating income lost if D&A caught up with capex", "pct"], ["net_debt_to_ebitda", "Net debt / EBITDA", "x"], ["interest_cover", "Interest cover", "x"], ["roic", "Return on invested capital", "pct"]];
  function baseRateMini(box, bucket, gReal) {
    const BR = oodaData().valuation.base_rates, B = BR && BR.buckets && BR.buckets[bucket];
    if (!B || !Array.isArray(B.bins) || !B.bins.every((b) => Array.isArray(b) && b.length === 3 && b.every(fin))) return;
    const W = 260, H = 70, bins = B.bins.slice(1, -1), bw = W / bins.length, mx = Math.max(...bins.map((b) => b[2]));
    const s = svg("svg", { viewBox: `0 0 ${W} ${H + 16}`, width: W, height: H + 16, role: "img", "aria-label": `Base rates for ${B.label}: share of companies by 10-year real growth; the price needs ${fx(gReal, 0)}% real` }, box);
    bins.forEach((b, i) => { const hh = (b[2] / mx) * H; svg("rect", { x: i * bw + 1, y: H - hh, width: bw - 2, height: Math.max(hh, 0.5), rx: 2, fill: "var(--s2)", opacity: 0.55 }, s); });
    const lo = bins[0][0], hi = bins[bins.length - 1][1], x = clamp(((gReal - lo) / (hi - lo)) * W, 1, W - 1);
    svg("line", { x1: x, x2: x, y1: 0, y2: H, stroke: "var(--ink)", "stroke-width": 2 }, s);
    const lx = clamp(x, 40, W - 40), off = gReal > hi ? " (off the scale)" : gReal < lo ? " (below the scale)" : "";
    const lab = `price: ${fx(gReal, 0)}%${off}`, half = lab.length * 3.1;
    if (lx - half > 28) text(s, 2, H + 13, `${lo}%`, "ax", "start");
    if (lx + half < W - 28) text(s, W - 2, H + 13, `${hi}%`, "ax", "end");
    text(s, off && gReal > hi ? W - 2 : off ? 2 : lx, H + 13, lab, "lbl-strong", off && gReal > hi ? "end" : off ? "start" : "middle");
  }
  function renderPositions() {
    const grid = $("#ps-grid");
    if (!grid) return;
    const o = oodaData(), V = o.valuation.positions, acts = Object.fromEntries(o.decide.positions.map((a) => [a.ticker, a]));
    $("#ps-status").textContent = `${oodaLive() ? "Engine run" : "Engine output as shipped"} · ${o.observe.inputs ? o.observe.inputs.fundamentals : ""} · prices ${o.observe.inputs ? o.observe.inputs.prices : ""} · 10-year yield ${fin(o.valuation.rf) ? fx(o.valuation.rf * 100, 2) + "%" : "n/a"}`;
    const fl = $("#ps-filter");
    if (!fl.dataset.wired) {
      fl.dataset.wired = "1";
      [["all", "All"], ["extreme", "Extreme"], ["exuberant", "Exceptional"], ["within", "Within base rates"], ["insufficient", "Not enough data"]].forEach(([k, n]) => {
        const b = h("button", "chip", n); b.type = "button"; b.dataset.k = k;
        b.addEventListener("click", () => { PS.filter = k; renderPositions(); });
        fl.append(b);
      });
    }
    fl.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", b.dataset.k === PS.filter ? "true" : "false"));
    grid.replaceChildren();
    Object.entries(V).forEach(([t, v]) => {
      const code = (v.verdict || {}).code || "insufficient";
      if (PS.filter !== "all" && code !== PS.filter) return;
      const card = h("article", "ps-card"), head = h("div", "ps-head");
      card.id = "ps-" + t.toLowerCase();
      head.append(h("h3", null, `${t} · ${v.name || t}`), badge(code));
      card.append(head, h("p", "ps-verdict", (v.verdict || {}).text || ""));
      const nums = h("div", "nw-nums");
      [["Market value", bnFmt(v.market_cap)], ["Implied growth", pctOrNa(v.implied_growth, 1)], ["Discount rate", pctOrNa(v.discount_rate, 1)], ["P/E", fin(v.pe) && v.pe > 0 ? fx(v.pe, 0) + "x" : fin(v.pe) ? "negative earnings" : "n/a"],
        ["EV / sales", fin(v.ev_sales) ? fx(v.ev_sales, 1) + "x" : "n/a"], ["FCF yield after stock pay", pctOrNa(v.owner_fcf_yield, 1)]].forEach(([k, val]) => { const d = h("div"); d.append(h("b", "num", val), h("small", null, k)); nums.append(d); });
      card.append(nums);
      if (fin(v.implied_real_pct) && v.base_rate_bucket) { const mini = h("div", "ps-mini"); baseRateMini(mini, v.base_rate_bucket, v.implied_real_pct); card.append(mini); }
      const lists = h("div", "ps-two");
      const mk = (title, arr, cls) => { const d = h("div"); d.append(h("h4", null, title)); const ol = h("ol", "ps-why " + cls); (arr || []).slice(0, 4).forEach((w) => { const li = h("li"); li.append(h("span", null, w.text), h("b", "num", `${fx(Math.abs(w.points), 1)} pts`)); ol.append(li); }); if (!(arr || []).length) ol.append(h("li", "none", "Nothing material.")); d.append(ol); return d; };
      if ((v.why || []).length || (v.why_right || []).length) {         // SpaceX has no filings yet, so no case either way
        lists.append(mk("Why the price could be wrong", v.why, "neg"), mk("What a buyer is betting on", v.why_right, "pos"));
        card.append(lists);
      }
      const q = v.quality || {}, rows = QUAL_ROWS.filter(([k]) => fin(q[k])).map(([k, n, f]) => [n, f === "pct" ? fx(q[k] * 100, 1) + "%" : fx(q[k], 2) + "x"]);
      const det = h("details", "tableview"), sum = h("summary", null, `The accounting (quality ${q.quality_grade || "n/a"}${(q.flags || []).length ? `; ${(q.flags || []).length} flag${q.flags.length > 1 ? "s" : ""}` : ""})`);
      det.append(sum);
      (q.flags || []).forEach((f) => det.append(h("p", "hint", `${f.grade === "red" ? "Red" : "Watch"}: ${f.text}.`)));
      det.append(tableBlock(["Measure", "Value"], rows));
      card.append(det);
      const a = acts[t];
      if (a) {
        const fr = h("details", "tableview"), s2 = h("summary", null, `Decision: ${ACTION_TXT[a.action] || a.action}${Math.abs(a.target - a.weight) > 1e-9 ? ` (${pct0(a.weight)} → ${fx(a.target * 100, 1)}%)` : ""}, ${a.confidence} confidence`);
        fr.append(s2);
        const F = a.frameworks || {}, names = { outside_view: "Outside view", inside_view: "Inside view", pre_mortem: "Pre-mortem", margin_of_safety: "Margin of safety", reversibility: "Reversibility", kill_criteria: "Kill criterion" };
        Object.entries(names).forEach(([k, n]) => { if (F[k]) { const p = h("p", "hint"); p.append(h("b", null, n + ": "), document.createTextNode(F[k])); fr.append(p); } });
        card.append(fr);
      }
      grid.append(card);
    });
    if (!grid.children.length) grid.append(h("p", "hint", "No positions with this verdict."));
  }

  /* ---------- the engine room ---------- */
  function renderEngines() {
    const t = $("#en-table");
    if (!t) return;
    const live = LIVE.engines && Array.isArray(LIVE.engines.engines) ? LIVE.engines : null;
    const str = (v) => (typeof v === "string" ? v : "");
    const list = (v) => (Array.isArray(v) ? v.filter((x) => typeof x === "string").join(", ") : "");
    const rows = (live ? live.engines : ENGINES_SNAP).filter((e) => e && typeof e === "object").map((e) => [str(e.title) || str(e.name) || "Unnamed", e.offline ? "offline" : "network or key", list(e.reads) || "sources", list(e.writes) || "n/a",
      live ? `${str(e.status) || "n/a"}${fin(e.seconds) ? ` · ${fx(e.seconds, 2)}s` : ""}` : "registered", str(e.does)]);
    fillTable(t, ["Engine", "Runs", "Reads", "Writes", "Last run", "Does"], rows, 1);
    const okN = live ? live.engines.filter((e) => e && e.status === "ok").length : 0, failN = live ? live.engines.filter((e) => e && e.status === "failed").length : 0;
    const ran = live && /^\d{4}-\d{2}-\d{2}/.test(String(live.run_at || "")) ? ` of ${isoNice(String(live.run_at).slice(0, 10))}` : "";
    const ver = live && typeof live.version === "string" && /^[\d.]+$/.test(live.version) ? `, version ${live.version}` : "";
    $("#en-t").textContent = live ? `Manifest${ran}: ${okN} engines ran, ${failN} failed${ver}. Every output is recorded with the content hashes of its inputs.` : "The registry as shipped. After a daily run, engines.json adds each engine's status, timing and input and output hashes here.";
    const fl = $("#en-flow");
    if (fl.children.length) return;
    [["Sources", "FRED, Treasury, SEC XBRL, Databento, public long-history datasets, feeds; every source registered with its licence (sources.json)."],
      ["Data engines", "macro, research, brain, book, fundamentals: dated JSON, raw data never enters the repository."],
      ["Reasoning engines", "the brain (inference, counterfactuals, structure learning, robust links), the solver (Bayes, robust to the odds), games, valuation and accounting, causal statistics, the hedge book, the shape of the market (geometry.py)."],
      ["Decision engines", "decide.py sizes the stock exposure (stacked forecasts, the neural ensemble in nn.py, regimes and changepoints in infer.py, model averaging, a risk budget, an evidence gate); portfolio.py decides stocks, Treasuries, gold and cash together; ooda.py turns both into one record per position and hedge, with frameworks and kill criteria."],
      ["Harnesses", "this page renders the files; the MCP server answers any assistant with the same engines; the journal scores the decisions."]].forEach(([k, v], i) => {
      const li = h("li"); li.append(h("span", "oo-n", String(i + 1)), h("b", null, k), h("p", null, v)); fl.append(li);
    });
  }

  /* ---------- causal statistics on the brain page ---------- */
  function renderCausalPanel() {
    const t = $("#brl-crisis");
    if (!t) return;
    const C = (LIVE.causal && LIVE.causal.regimes) ? LIVE.causal : oodaData().causal;
    if (!C || !C.regimes) return;
    const ok = (r) => (r && typeof r === "object" && r.crisis && typeof r.crisis === "object" && r.granger && typeof r.granger === "object" ? r : null);
    const lo = ok(C.regimes.low_inflation), hi = ok(C.regimes.inflation), keys = ["oil", "cpi", "y10", "vix", "gold"];
    const cm = (r, k) => (r && r.crisis[k] && fin(r.crisis[k].crisis_mean) ? sg(r.crisis[k].crisis_mean, 2) : "n/a");
    fillTable(t, ["Asset", "1990 to 2021", "2022 on"], keys.map((k) => [k === "y10" ? "10-year yield" : nodeNm(k), cm(lo, k), cm(hi, k)]), 1);
    const gl = $("#brl-granger");
    gl.replaceChildren();
    const G = lo ? Object.entries(lo.granger).filter(([, v]) => v && fin(v.p) && v.p < 0.05).sort((a, b) => a[1].p - b[1].p) : [];
    G.slice(0, 8).forEach(([k, v]) => { const [a, b] = k.split(">"); const li = h("li"); li.append(h("span", null, `${nodeNm(a)} → ${nodeNm(b)}`), h("b", "num", `p ${v.p < 0.001 ? "< 0.001" : fx(v.p, 3)}`)); gl.append(li); });
    if (!G.length) gl.append(h("li", "none", "No pair passes at 5%."));
  }

  /* =====================================================================================
     decide.js (v0.5): the brief, the system map, the decision board, rates of change,
     weighted assumptions, known knowns and the 2nd-to-4th-order chains
     ===================================================================================== */
  const LS = {                        // per-viewer conveniences only; the page works without them
    get(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* storage blocked: keep it in memory */ } },
  };
  const isoNice = (iso) => niceDate(iso) || iso || "n/a";
  const monthNice = (iso) => (isoOk(iso) ? `${MONTHS[Number(iso.slice(5, 7)) - 1]} ${iso.slice(0, 4)}` : "n/a");     // monthly data: "Sep 2026"
  const pctPts = (x, d = 2) => (fin(x) ? fx(x, d) + "%" : "n/a");
  const sBp = (x, d = 1) => (fin(x) ? (x > 0 ? "+" : x < 0 ? MINUS : "") + fx(Math.abs(x), d) : "n/a");
  const WEEKS_PER_MONTH = 52 / 12;

  /* ---------- inputs: the latest value of everything a decision reads (live where the daily run has it) ---------- */
  function liveMove(key) {
    const rows = LIVE.macro && Array.isArray(LIVE.macro.moves) ? LIVE.macro.moves : [];
    return rows.find((x) => x && x.key === key && fin(x.value) && isoOk(x.date)) || null;
  }
  function liveInflation() {
    const ms = LIVE.macro && LIVE.macro.macro_state, inf = ms && ms.inflation;
    return inf && fin(inf.avg36) && fin(inf.yoy) && isoOk(inf.date) ? inf : null;
  }
  function inputs() {
    const m = LIVE.macro, ms = m && m.macro_state, lv = m && m.rates && m.rates.levels, R = ROC_SNAP;
    // live from the daily run, else the dated static level store (data.js LEVELS), else the rate-of-change snapshot
    const lvl = (k) => (lv && lv[k] && fin(lv[k].value) && isoOk(lv[k].date) ? { v: lv[k].value, d: lv[k].date, live: true } : (typeof levelStatic === "function" ? levelStatic(k) : null));
    const li = liveInflation();
    const infl = li ? { avg36: li.avg36 * 100, yoy: li.yoy * 100, d: li.date, live: true, months: li.months_to_line_at_2pct, v3: fin(li.avg36_v3) ? li.avg36_v3 * 100 : NaN }
      : { avg36: R.cpi.avg36, yoy: R.cpi.value, d: R.cpi.date, live: false, months: R.cpi.months_to_line, v3: R.cpi.avg36_v3 };
    const HL = hedgeLineInfo(), lineAt = HL.lo * 100;          // the low edge of the uncertain band (2.75%), for distances and the sleeve
    const corr = m && m.latest && fin(m.latest.corr63) && isoOk(m.latest.as_of)
      ? { v: m.latest.corr63, d: m.latest.as_of, live: true, what: "Nasdaq-100 against the 20-year Treasury, 63-day half-life" }
      : { v: readF().hedge.latest.corr, d: readF().hedge.latest.month + "-01", live: false, what: "S&P 500 against the 10-year Treasury, 36 months (Findings)" };
    const vol = m && m.vol && m.vol.latest ? m.vol.latest : null;
    const vxn = vol && vol.ndx && fin(vol.ndx.implied) && isoOk(vol.ndx.date) ? { v: vol.ndx.implied, d: vol.ndx.date, live: true } : lvl("vxn") || { v: STATIC_VOL.vxn[0], d: "2026-10-23", live: false };
    const term = vol && vol.term && fin(vol.term.ratio) && isoOk(vol.term.date) ? { v: vol.term.ratio, d: vol.term.date, live: true }
      : { v: STATIC_VOL.term.vix / STATIC_VOL.term.vix3m, d: STATIC_VOL.term.date, live: false };     // one date for both legs
    const liq = m && m.liquidity && m.liquidity.latest;
    const funding = liq && liq.funding && fin(liq.funding.gap_5d_bp) && isoOk(liq.funding.date) ? { v: liq.funding.gap_5d_bp, d: liq.funding.date, live: true } : { v: R.funding.value, d: R.funding.date, live: false };
    const rrp = liq && liq.net && fin(liq.net.rrp) && isoOk(liq.net.date) ? { v: liq.net.rrp, d: liq.net.date, live: true } : { v: STATIC_LIQ.rrp[0], d: "2026-10-19", live: false };
    const S = LIVE.report && LIVE.report.summary;
    const gross = S && fin(S.recommended_gross) && isoOk(S.as_of) ? { v: S.recommended_gross, d: S.as_of, live: true } : null;
    const builders = FUND.rows.filter((r) => ["MSFT", "GOOGL", "AMZN", "META", "ORCL"].includes(r.t));
    const sum = (k) => builders.reduce((a, r) => a + (fin(r[k]) ? r[k] : 0), 0);
    return {
      infl, lineAt, HL, corr, vxn, term, funding, rrp, gross,
      vix: lvl("vix") || { v: R.vix.value, d: R.vix.date, live: false },
      real: lvl("real10") || { v: R.real.value, d: R.real.date, live: false },
      be: lvl("breakeven10") || { v: R.be.value, d: R.be.date, live: false },
      hy: lvl("hy_oas") || { v: R.hy.value, d: R.hy.date, live: false },
      ccc: lvl("ccc_oas") || { v: R.ccc.value, d: R.ccc.date, live: false },
      oil: lvl("brent") || { v: R.oil.value, d: R.oil.date, live: false }, oilAvg5: R.oil.avg5y,
      nfci: ms && ms.nfci && fin(ms.nfci.value) && isoOk(ms.nfci.date) ? { v: ms.nfci.value, d: ms.nfci.date, live: true } : { v: R.nfci.value, d: R.nfci.date, live: false },
      sahm: ms && ms.sahm && fin(ms.sahm.value) && isoOk(ms.sahm.date) ? { v: ms.sahm.value, d: ms.sahm.date, live: true } : { v: R.sahm.value, d: R.sahm.date, live: false },
      capexTTM: sum("capex"), ocfTTM: sum("ocf"),
    };
  }
  const liveTag = (o) => (o && o.live ? "latest available" : "as shipped with this version");

  /* ---------- assumption probabilities: the desk's, or the viewer's own ---------- */
  let asOverride = LS.get("bo-assume", {});
  if (!asOverride || typeof asOverride !== "object") asOverride = {};
  const asP = (id) => { const a = ASSUMPTIONS.find((x) => x.id === id); return a ? (fin(asOverride[id]) ? clamp(asOverride[id], 0.01, 0.99) : a.p) : NaN; };
  const decConf = (ids) => conjunction(ids.map(asP).filter(fin));

  /* ---------- the seven decisions: data, rule, action, confidence, distance to a flip ---------- */
  function decisions() {
    const I = inputs(), out = [];
    const pctOf = (x) => (fin(x) ? Math.round(x * 100) + "%" : "n/a");
    const TD = tltNow(I), hedgeOn = TD.on === true;

    // 1. gross
    const bookVol = 1.1 * I.vxn.v, byVol = Math.min(0.2 / (bookVol / 100), 1.5), g = I.gross ? I.gross.v : byVol;
    const vxnAt1 = (0.2 / 1.1) * 100;
    out.push({ id: "d-gross", n: "How big?", q: "Gross exposure for the model book", level: g < 0.75 ? 2 : g < 1 ? 1 : 0, vol: g,
      ins: [["Nasdaq-100 implied volatility (VXN)", fx(I.vxn.v, 2), `${isoNice(I.vxn.d)} · ${liveTag(I.vxn)}`],
        ["Book volatility forecast, 1.1 times VXN", fx(bookVol, 1) + "%", "assumption: the book runs hotter than the index"],
        ["Volatility target", "20%", "config.toml; gross capped at 1.5x"],
        I.gross ? ["Engine's size to run", xx(I.gross.v), `${isoNice(I.gross.d)}: ${sizeBindingTxt()}`] : ["Bond hedge available?", hedgeOn ? "Yes" : "No", "decision 2: options carry the hedge"]],
      rule: "Policy size.equity.v2: equity scale = the smallest of 20% target volatility ÷ forecast volatility, the 25% one-year drawdown cap and 1.5x. Quarter Kelly is not a size input: it reports the excess return this size would need.",
      act: govSize() ? `Governing size ${xx(govSize().x)}; volatility rule ${xx(g)}` : `Run ${xx(g)} gross`, sub: `${govNote("The volatility rule's size", g)} ${I.gross ? `From the engine's sizing stack; ${sizeBindingTxt()}.` : "The daily run adds the drawdown cap and the Kelly check."}`,
      flip: `Gross reaches 1.00x when VXN falls to <strong>${fx(vxnAt1, 1)}</strong>, ${fx(Math.max(0, I.vxn.v - vxnAt1), 1)} points below today.`, as: ["a-beta", "a-vrp", "a-hygiene"], link: "size",
      math: `<var>g</var> = min(0.20 &divide; (1.1 &times; ${fx(I.vxn.v / 100, 4)}), 1.5) = ${fx(byVol, 2)}${I.gross ? `; engine ${fx(I.gross.v, 2)}` : ""}` });

    // 2. the bond hedge: policy hedge.tlt.v2, the same function the engine backtests
    const corrGap = I.corr.v + 0.1, HL = I.HL, inflGap = fin(HL.line) ? I.infl.avg36 - HL.line * 100 : NaN;
    const b = readF().hedge.rows.find((r) => r.bucket === (I.infl.avg36 < 0 ? "Deflation" : I.infl.avg36 < 2 ? "0 to 2%" : I.infl.avg36 < 3 ? "2 to 3%" : I.infl.avg36 < 4 ? "3 to 4%" : I.infl.avg36 < 6 ? "4 to 6%" : "Above 6%"));
    const gateTxt = TD.gates.inflation.status === "ok" ? `${TD.gates.inflation.pass ? "passes" : "fails"}: ${pctPts(I.infl.avg36)} against the ${fx(HL.line * 100, 2)}% line`
      : `not applied (${TD.gates.inflation.status.replace(/_/g, " ")})`;
    out.push({ id: "d-duration", n: "Hold the TLT hedge?", q: "Long Treasuries as the book's hedge", level: TD.status !== "ok" ? 1 : hedgeOn ? 0 : 2,
      ins: [["Stock-bond state", TD.gates.state.value || "n/a", `correlation ${sgn2(I.corr.v)} · ${I.corr.what} · ${I.corr.live ? isoNice(I.corr.d) : monthNice(I.corr.d)}`],
        ["Measure in force", I.corr.live ? "Policy measure" : "Stand-in", I.corr.live ? "the policy's 63-day exponentially weighted correlation, from the daily run" : "the policy's 63-day exponentially weighted measure is not computed in this copy; the 36-month monthly correlation stands in. The Fed's one-year +0.21 (Jul 31) and Geometry's real-return figure are context"],
        ["Inflation gate", TD.gates.inflation.status === "ok" ? (TD.gates.inflation.pass ? "Passes" : "Fails") : "Not applied", `${pctPts(I.infl.avg36)} over 36 months · ${monthNice(I.infl.d)} · ${liveTag(I.infl)}`],
        ["Where the line could be", HL.band ? `${fx(HL.band[0] * 100, 2)} to ${fx(HL.band[1] * 100, 2)}%` : "n/a", `bootstrap of the threshold choice, ${HL.boot ? HL.boot.independent_windows : "n/a"} independent 3-year windows`],
        [`Since 1871 at ${b ? b.bucket : "this"} inflation, bonds hedged in`, b ? `${Math.round(b.share_hedging * 100)}% of months` : "n/a", `${b ? b.months.toLocaleString("en-US") : "n/a"} months (Findings)`]],
      rule: `Policy hedge.tlt.v2 (the engine backtests the same function): hold TLT at the minimum-variance ratio only while the stock-bond state is "hedging" (entered at a correlation of −0.10 or below, left only above 0) and, while the research has a validated line, 36-month inflation is below it (${fin(HL.line) ? fx(HL.line * 100, 2) + "%, chosen on data through " + HL.trained : "none validated today"}). A missing input makes the decision unavailable, never zero.`,
      act: TD.status !== "ok" ? "Unavailable: " + TD.blocked.join("; ") : hedgeOn ? "Hold TLT at the minimum-variance ratio" : "No TLT hedge: 0%",
      sub: hedgeOn ? "Bonds have hedged in this state." : TD.gates.state.value === "amplifying" ? "Stocks and bonds are moving together: long bonds would add to a sell-off. Options, gold and energy carry the hedge (decisions 3 to 5)." : "The correlation is between the lines; the hedge waits for a clear hedging state.",
      flip: `The hedge comes back when the correlation falls to <strong>−0.10</strong>, ${fx(Math.max(0, corrGap), 2)} below today${fin(inflGap) && inflGap >= 0 ? `, and 36-month inflation falls <strong>${fx(inflGap, 2)} points</strong> below the line` : ""}. Inflation gate today: ${gateTxt}. Out of sample since 1901, adding the inflation gate to the correlation rule did ${readF().hedge.experiment && readF().hedge.experiment.inflation_adds_value ? "improve" : "not improve"} the worst months (Findings).`,
      as: ["a-line", "a-regime", "a-fed"], link: "fi-hedge",
      math: `on &hArr; state = hedging and (&pi;<sub>36</sub> &lt; line, when validated). State: enter at &rho; &le; &minus;0.10, leave at &rho; &gt; 0. Now &rho; = ${sgn2(I.corr.v)} (${TD.gates.state.value || "n/a"}), &pi;<sub>36</sub> = ${fx(I.infl.avg36 / 100, 4)}, line = ${fin(HL.line) ? fx(HL.line, 4) : "none"} (${HL.status.replace(/_/g, " ")}).` });

    // 3. the inflation sleeve
    const oilRel = I.oil.v / I.oilAvg5, sleeve = I.infl.avg36 >= I.lineAt || oilRel >= 1.3, G = readF().gold;
    out.push({ id: "d-inflation", n: "Replace bonds with what?", q: "The inflation sleeve: gold and energy", level: sleeve ? 1 : 0,
      ins: [["Brent against its 5-year average", `$${fx(I.oil.v, 2)} = ${fx(oilRel, 2)}x`, `${isoNice(I.oil.d)}, EIA dated spot · average $${fx(I.oilAvg5, 2)}${I.oil.live ? "" : " · futures $111.95 on Oct 22, within $2 of the line"}`],
        ["Gold when stocks fell 15% (real, 12 months)", sPct(G.stocks_down15.gold, 1), `up ${fin(G.stocks_down15.share_gold_up) ? Math.round(G.stocks_down15.share_gold_up * 100) + "%" : "n/a"} of the time, since ${G.since}`],
        ["Gold in high-inflation years (real)", sPct(G.high_infl.gold, 1), `stocks ${sPct(G.high_infl.stocks, 1)}`],
        ["10-year breakeven", pctPts(I.be.v), `${isoNice(I.be.d)} · ${liveTag(I.be)}`]],
      rule: "If 36-month inflation is above 2.75% (the low edge of the band where bonds stopped hedging most of the time), or Brent is above 1.3 times its 5-year average (a supply shock), hold 8% in inflation assets: half gold, half energy. Otherwise 2%.",
      act: sleeve ? "Hold 8%: 4% gold, 4% energy" : "Hold 2%: keep the sleeve warm", sub: "Gold hedged equity drawdowns in inflationary years when bonds did not.",
      flip: `The sleeve shrinks only when Brent falls below <strong>$${fx(1.3 * I.oilAvg5, 2)}</strong> and inflation drops below the line.`, as: ["a-line", "a-oil", "a-samples"], link: "fi-gold",
      math: `on &hArr; &pi;<sub>36</sub> &ge; line or Brent &divide; avg<sub>5y</sub> &ge; 1.3. Now ${fx(oilRel, 3)}` });

    // 4. index puts, aligned with the VIX and VIX-curve signals
    const t = I.term.v, vx = I.vix.v;
    const tail = t >= 1 || vx >= 30 ? ["Monetize puts in stages", 2] : t >= 0.95 ? ["Buy put spreads before the curve inverts", 1] : vx >= 20 ? ["Hold hedges; do not chase", 1] : ["Buy 3- to 6-month put spreads: protection is cheap", 0];
    out.push({ id: "d-tail", n: "Buy insurance?", q: "Index puts and put spreads", level: tail[1],
      ins: [["VIX", fx(vx, 2), `${isoNice(I.vix.d)} · ${liveTag(I.vix)}`], ["VIX over 3-month VIX", fx(t, 3), `${isoNice(I.term.d)} · below 0.95 normal, above 1 inverted`],
        ["VXN", fx(I.vxn.v, 2), "Nasdaq-100 implied"], ["Budget", `${fx(POLICY7.limits.maxPremium * 100, 1)}% of NAV a year`, "the policy cap (limits.portfolio.v1); the Options desk prices what it buys"]],
      rule: "Buy convexity while it is cheap (VIX below 20, curve in contango). When the front of the curve flattens toward 1, buy before it inverts. Once it inverts or VIX tops 30, monetize in stages.",
      act: tail[0], sub: "Put spreads beat outright puts when skew is steep: the far tail is sold off.",
      flip: `The curve inverts at 1.00, <strong>${fx(Math.max(0, 1 - t), 3)}</strong> away; VIX reaches 30 in ${fx(Math.max(0, 30 - vx), 2)} points.`, as: ["a-vrp", "a-mech"], link: "tb-title",
      math: `contango &hArr; VIX/VIX3M &lt; 0.95; now ${fx(t, 3)}` });

    // 5. credit protection
    const cccStress = I.ccc.v >= 9, hyCalm = I.hy.v < 4.5;
    out.push({ id: "d-credit", n: "Buy credit protection?", q: "High-yield protection against an AI financing break", level: cccStress ? (hyCalm ? 1 : 2) : 0,
      ins: [["CCC spread", pctPts(I.ccc.v), `${isoNice(I.ccc.d)} · ${liveTag(I.ccc)} · 8.53% in July 2025`], ["High-yield spread", pctPts(I.hy.v), `${isoNice(I.hy.d)} · ${liveTag(I.hy)}`],
        ["CCC as a multiple of high yield", fx(I.ccc.v / I.hy.v, 2) + "x", "stress at the bottom, calm at the index"], ["Builders with capex above cash flow", "Amazon, Oracle, CoreWeave", "Fundamentals desk"]],
      rule: "When the bottom of credit cracks (CCC above 9%) while the index is calm (high yield below 4.5%), protection is cheap relative to the risk: buy it. Once high yield passes 4.5%, monetize half.",
      act: cccStress && hyCalm ? "Buy protection: HYG puts or CDX HY" : cccStress ? "Monetize half the protection" : "No protection needed", sub: "This hedges the financing branch of the AI thesis, which duration cannot.",
      flip: `Monetize at a high-yield spread of <strong>4.50%</strong>, ${fx(Math.max(0, (4.5 - I.hy.v) * 100), 0)}bp away; drop the hedge if CCC falls below 9%.`, as: ["a-credit", "a-ig"], link: "sw-credit",
      math: `buy &hArr; CCC &ge; 9% and HY &lt; 4.5%. Now ${fx(I.ccc.v, 2)}%, ${fx(I.hy.v, 2)}%` });

    // 6. which builders
    const get = (tk) => FUND.rows.find((r) => r.t === tk) || {};
    out.push({ id: "d-names", n: "Which builders?", q: "Tilts inside the AI book (model book)", level: 1,
      ins: [["Capex ÷ cash flow, inside it", `MSFT ${pctOf(get("MSFT").capex_to_ocf)} · META ${pctOf(get("META").capex_to_ocf)} · GOOGL ${pctOf(get("GOOGL").capex_to_ocf)}`, "SEC, last twelve months"],
        ["Capex ÷ cash flow, above it", `AMZN ${pctOf(get("AMZN").capex_to_ocf)} · ORCL ${pctOf(get("ORCL").capex_to_ocf)} · CRWV ${pctOf(get("CRWV").capex_to_ocf)}`, "the build needs new money"],
        ["Pre-tax income from marks", `GOOGL ${pctOf(get("GOOGL").nonop_share)} · AMZN ${pctOf(get("AMZN").nonop_share)} · MSFT ${pctOf(get("MSFT").nonop_share)}`, "non-operating share"],
        ["Debt growth, one year", `AMZN +${pctOf(get("AMZN").debt_yoy)} · CRWV +${pctOf(get("CRWV").debt_yoy)}`, "SEC balance sheets"]],
      rule: "Overweight builders in hedge finance with little paper profit; size marks-heavy names on operating income; underweight speculative finance; avoid Ponzi-edge credit.",
      act: "Favor MSFT and META; size GOOGL and AMZN on operating income; underweight ORCL; avoid CRWV credit", sub: "This call rests on four uncertain assumptions, so its confidence is the lowest on the board: tilt, do not bet.",
      flip: `Upgrade Amazon when capex falls back under cash flow (now <strong>${pctOf(get("AMZN").capex_to_ocf)}</strong>); Oracle when free cash flow turns positive (now <strong>${B$(get("ORCL").fcf)}</strong>).`,
      as: ["a-capex", "a-life", "a-marks", "a-ig"], link: "fundamentals", math: "stage = hedge if capex &le; OCF; Ponzi edge if OCF &le; 0 or operating income &lt; interest; otherwise speculative" });

    // 7. funding
    const tight = I.funding.v > 0;
    out.push({ id: "d-liquidity", n: "Can the system fund a selloff?", q: "Funding and financial conditions", level: I.funding.v >= 10 ? 2 : tight ? 1 : 0,
      ins: [["SOFR minus IORB", bp(I.funding.v), `${isoNice(I.funding.d)} · ${liveTag(I.funding)}`], ["Financial conditions (NFCI)", fx(I.nfci.v, 3), `${isoNice(I.nfci.d)} · below 0 is looser than average`],
        ["Sahm recession indicator", fx(I.sahm.v, 2), `${monthNice(I.sahm.d)} · 0.50 signals recession`], ["Reverse repo", "$" + fx(I.rrp.v * 1000, 2) + "B", `${isoNice(I.rrp.d)} · the buffer is gone`]],
      rule: "Repo above the rate on reserves means cash is scarce: cut leverage. Above +10bp, run the liquidity playbook. With the reverse repo empty, any further drain comes out of bank reserves.",
      act: tight ? "Cut leverage: funding is tight" : "No funding action", sub: "Watch month-end and the Treasury's cash balance: the reverse repo cushion is empty.",
      flip: `Funding turns tight above <strong>0bp</strong>, ${fx(Math.max(0, -I.funding.v), 0)}bp away.`, as: ["a-fed"], link: "liq-title",
      math: `tight &hArr; SOFR &minus; IORB &gt; 0. Now ${fx(I.funding.v, 1)}bp` });
    return out;
  }

  const LINK5 = { size: "Sizing lab", "fi-hedge": "Finding: the inflation line", "fi-gold": "Finding: gold", "tb-title": "Tail-hedge budget", "sw-credit": "Swan: a private-credit run", fundamentals: "Fundamentals desk", "liq-title": "Liquidity" };
  const linkLabel5 = (t) => LINK5[t] || linkLabel(t);
  const LEVEL_WORD = ["Default", "Adjusted", "Defensive"], LEVEL_CLS = ["on", "mid", "off"];
  function renderDecisions() {
    const box = $("#dec-board");
    if (!box) return;
    const ds = decisions();
    LIVE.decisions = ds;
    box.replaceChildren();
    ds.forEach((d, i) => {
      const card = h("article", "dec l" + d.level);
      card.id = d.id;
      const head = h("div", "dec-head"), t = h("div");
      t.append(h("h3", null, `${i + 1}. ${d.n}`), h("span", "q", d.q));
      head.append(t, h("span", "stance " + LEVEL_CLS[d.level], LEVEL_WORD[d.level]));
      const c1 = h("div", "col data"), c2 = h("div", "col"), c3 = h("div", "col");
      const ul = h("ul", "inputs");
      d.ins.forEach(([k, v, src]) => { const li = h("li"); li.append(h("span", null, k), h("b", null, v), h("span", "s", src)); ul.append(li); });
      c1.append(h("h4", null, "Data"), ul);
      const mth = h("div", "math");
      mth.innerHTML = `<span class="mlabel">This decision</span>${d.math}`;
      c2.append(h("h4", null, "Rule, written in advance"), h("p", "rule-box", d.rule), mth);
      const fl = h("p", "flip");
      fl.innerHTML = d.flip;
      const fr = frechet(d.as.map(asP).filter(fin)), conf = fr.indep, meter = h("div", "meter"), bar = h("div", "bar"), fill = h("i"), rng = h("i", "rng"), mk = h("div", "mk");
      fill.style.width = Math.round(conf * 100) + "%";
      rng.style.left = Math.round(fr.lo * 100) + "%"; rng.style.width = Math.max(1, Math.round((fr.hi - fr.lo) * 100)) + "%";
      bar.append(rng, fill);
      mk.append(h("span", null, Math.round(fr.lo * 100) === Math.round(fr.hi * 100) ? `All assumptions hold: ${Math.round(fr.lo * 100)}%` : `All assumptions hold: ${Math.round(fr.lo * 100)} to ${Math.round(fr.hi * 100)}%`), h("b", null, `${Math.round(conf * 100)}% if independent`));
      meter.append(bar, mk);
      meter.setAttribute("role", "img");
      meter.setAttribute("aria-label", `All ${d.as.length} assumptions hold with probability between ${Math.round(fr.lo * 100)}% and ${Math.round(fr.hi * 100)}% (bounds that need no independence assumption); ${Math.round(conf * 100)}% if they were independent`);
      c3.append(h("h4", null, "Action today"), h("p", "act", d.act), h("p", "flip", d.sub), fl, meter);
      const as = h("p", "flip");
      as.append(document.createTextNode("Rests on: "));
      d.as.forEach((id, j) => {
        const A = ASSUMPTIONS.find((x) => x.id === id) || {}, a = h("a", null, A.s || A.kind || id);
        a.href = "#as-" + id + "-row";
        a.title = A.t || "";
        if (j) as.append(document.createTextNode(", "));
        as.append(a);
      });
      c3.append(as);
      if (d.link) { const a = h("a", "src", linkLabel5(d.link) + " →"); a.href = "#" + d.link; c3.append(a); }
      card.append(head, c1, c2, c3);
      box.append(card);
    });
    const weakest = ds.slice().sort((a, b) => decConf(a.as) - decConf(b.as))[0];
    const g = ds[0], dur = ds[1], read = $("#dec-read");
    read.replaceChildren();
    const s1 = h("p");
    const G = govSize();
    s1.append(h("strong", null, G ? `Hold ${G.words}: ${G.book ? `the book's ${G.book.bindingName.replace(/^the /, "")} sets the size` : "the decision engine's gated call governs"}. ` : `${g.act}, ${dur.level === 2 ? "with no bond hedge" : "with the bond hedge on"}. `),
      document.createTextNode(`${G ? `The cards below are rule-based cross-checks: the volatility rule reads ${xx(ds[0].vol)} and the bond rule says ${dur.level === 2 ? "no bond hedge" : "bond hedge on"}. ` : ""}${ds.filter((d) => d.level === 2).length} of ${ds.length} calls are defensive and ${ds.filter((d) => d.level === 1).length} adjusted. Weakest link: `));
    const a = h("a", null, weakest.n.replace("?", ""));
    a.href = "#" + weakest.id;
    s1.append(a, document.createTextNode(`, at ${Math.round(decConf(weakest.as) * 100)}% confidence because it rests on ${weakest.as.length} uncertain assumptions at once.`));
    read.append(s1);
    const I = inputs();
    $("#dec-sub").textContent = `Inputs dated ${isoNice(I.real.d)}${I.real.live ? ", from the daily run" : " (as shipped; the daily run replaces them)"}. Each card: the data, the rule, today's action, the confidence its assumptions allow, and the distance to a flip.`;
  }

  /* ---------- rates of change ---------- */
  // risk +1: a rise is the risk; each line is [level, state above it, state below it]
  const ROC_ROWS = [
    { k: "infl36", n: "Inflation, 36-month average", unit: "pp", freq: "m", risk: 1,
      lines: [[() => hedgeLineInfo().lo * 100, "Above 2.75%: bonds hedged in a minority of months", "Below 2.75%: bonds hedged most months"], [() => (fin(hedgeLineInfo().line) ? hedgeLineInfo().line * 100 : NaN), "Above the validated line: the TLT gate fails", "Below the validated line"], ] },
    { k: "cpi", n: "Inflation, past year", unit: "pp", freq: "m", risk: 1, lines: [[3, "Above 3%", "Below 3%"], [5, "A 5% spell: median 29 months to undo", "Below 5%"]] },
    { k: "real", move: "real10", n: "10-year real yield", unit: "pp", risk: 1, lines: [[2.0, "Tight", "Easy"], [2.5, "Restrictive", "Tight"]] },
    { k: "be", move: "be10", n: "10-year breakeven", unit: "pp", risk: 1, lines: [[2.5, "Rising", "Anchored"], [3.0, "Unanchored", "Rising"]] },
    { k: "curve", move: "c2s10s", n: "2s10s curve", unit: "bp", risk: -1, lines: [[0, "Flat", "Inverted"], [25, "Positive", "Flat"]] },
    { k: "y30", move: "y30", n: "30-year Treasury (TLT's yield)", unit: "pp", risk: 1, lines: [] },
    { k: "vix", move: "vix", n: "VIX", unit: "pts", risk: 1, meanReverting: true, lines: [[20, "Elevated", "Calm"], [30, "Stress", "Elevated"]] },
    { k: "oil", move: "brent", n: "Brent crude", unit: "$", risk: 1, lines: [[85, "Elevated", "Normal"], [100, "Shock", "Elevated"], [() => 1.3 * ROC_SNAP.oil.avg5y, "Supply-shock line: sleeve to 8%", "Below the supply-shock line"]] },
    { k: "hy", move: "hy", n: "High-yield spread", unit: "pp", risk: 1, lines: [[4.5, "Stress", "Calm"], [6, "Credit event", "Stress"]] },
    { k: "ccc", move: "ccc", n: "CCC spread", unit: "pp", risk: 1, lines: [[9, "Stress", "Calm"], [14, "Distress", "Stress"]] },
    { k: "nfci", n: "Financial conditions (NFCI)", unit: "idx", risk: 1, lines: [[0, "Tighter than average", "Looser than average"]] },
  ];
  const rocLines = (row) => row.lines.map(([at, up, down]) => [typeof at === "function" ? at() : at, up, down]).filter(([at]) => fin(at));
  const fmtRocLevel = (row, v) => (!fin(v) ? "n/a" : row.unit === "bp" ? fx(v, 0) + "bp" : row.unit === "$" ? "$" + fx(v, 2) : row.unit === "idx" ? fx(v, 3) : row.unit === "pts" ? fx(v, 2) : pctPts(v));
  // velocities in level units per week (v13, v4, a13); vm: the per-month pair that monthly rows display
  // the dated static level store, when it is newer than the rate-of-change snapshot's level for this row
  function rocNewerLevel(row, S) {
    if (typeof levelStatic !== "function") return null;
    const map = { real: "real10", be: "breakeven10", vix: "vix", oil: "brent", hy: "hy_oas", ccc: "ccc_oas", y30: "y30" };
    let st = null;
    if (row.k === "curve") { const a = levelStatic("y10"), b = levelStatic("y2"); st = a && b && a.d === b.d ? { v: (a.v - b.v) * 100, d: a.d } : null; }
    else if (map[row.k]) st = levelStatic(map[row.k]);
    return st && fin(st.v) && (!S.date || st.d > S.date) ? st : null;
  }
  function rocValues(row) {
    const S = ROC_SNAP[row.k === "infl36" ? "cpi" : row.k] || {};
    const mv = row.move ? liveMove(row.move) : null;
    const nl = rocNewerLevel(row, S), paced = (how) => (nl ? `level ${isoNice(nl.d)} from the key levels; pace to ${isoNice(S.date)}, ${how}` : how);
    if (mv && fin(mv.v13)) {
      // the engine quotes rates in bp per week, VIX in points per week and prices in log percent per week
      let level = mv.value, k = 1;
      if (row.unit === "pp") k = 1 / 100;
      if (row.unit === "bp") level = mv.value * 100;
      if (row.unit === "$") k = mv.value / 100;
      return { level, date: mv.date, v13: mv.v13 * k, v4: fin(mv.v4) ? mv.v4 * k : NaN, a13: fin(mv.a13) ? mv.a13 * k : NaN, live: true, how: "13- and 4-week least-squares slopes of the daily prints" };
    }
    if (row.freq === "m") {
      const li = liveInflation(), key = row.k === "infl36" ? "avg36" : "yoy";
      const src = li && fin(li[key + "_v3"]) ? { level: li[key] * 100, v3: li[key + "_v3"] * 100, v1: li[key + "_v1"] * 100, a3: fin(li[key + "_a3"]) ? li[key + "_a3"] * 100 : NaN, date: li.date, live: true }
        : row.k === "infl36" ? { level: S.avg36, v3: S.avg36_v3, v1: S.avg36_v1, a3: S.avg36_a3, date: S.date, live: false } : { level: S.value, v3: S.v3, v1: S.v1, a3: S.a3, date: S.date, live: false };
      return { level: src.level, date: src.date, v13: src.v3 / WEEKS_PER_MONTH, v4: src.v1 / WEEKS_PER_MONTH, a13: src.a3 / WEEKS_PER_MONTH, vm: [src.v3, src.v1], live: src.live,
        how: "monthly: the least-squares slope of the last four prints (three months) and the last one-month change" };
    }
    if (row.k === "nfci") {
      const ms = LIVE.macro && LIVE.macro.macro_state, n = ms && ms.nfci;
      if (n && fin(n.v13) && isoOk(n.date)) return { level: n.value, date: n.date, v13: n.v13, v4: n.v4, a13: n.a13, live: true, how: "weekly: 13- and 4-week least-squares slopes" };
      const w = (Date.parse(S.wk_dates[1]) - Date.parse(S.wk_dates[0])) / WEEK_MS;
      return { level: S.value, date: S.date, v13: NaN, v4: (S.wk[1] - S.wk[0]) / w, a13: NaN, live: false, how: `as shipped: the change since ${isoNice(S.wk_dates[0])}` };
    }
    if (row.k === "ccc" || row.k === "hy") {
      const w = (Date.parse(S.wk_dates[1]) - Date.parse(S.wk_dates[0])) / WEEK_MS;
      const v13 = row.k === "ccc" ? (S.value - S.from) / ((Date.parse(S.date) - Date.parse(S.from_date)) / WEEK_MS) : NaN;
      return { level: nl ? nl.v : S.value, date: nl ? nl.d : S.date, v13, v4: (S.wk[1] - S.wk[0]) / w, a13: NaN, live: false, w13: row.k === "ccc" ? "since Jul 2025" : null, w4: "last week only",
        how: paced(row.k === "ccc" ? `as shipped: the average pace since ${isoNice(S.from_date)}, and the last week; the daily run replaces both with 13- and 4-week slopes` : "as shipped: the last week only; the daily run replaces it with 13- and 4-week slopes") };
    }
    const k = row.unit === "pp" ? 1 / 100 : 1;                    // snapshot slopes are in bp per week for rates
    return { level: nl ? nl.v : S.value, date: nl ? nl.d : S.date, v13: S.v13 * k, v4: S.v4 * k, a13: S.a13 * k, live: false, how: paced("as shipped: 13- and 4-week least-squares slopes, computed with the engine's code") };
  }
  // the rule line the market is heading toward at pace v, and how long it takes
  function lineAhead(row, level, v) {
    if (!fin(v) || !fin(level)) return { state: "na" };
    if (v === 0) return { state: "flat" };
    const ls = rocLines(row).filter(([at]) => (v > 0 ? at > level : at < level)).sort((a, b) => (v > 0 ? a[0] - b[0] : b[0] - a[0]));
    if (!ls.length) return { state: "none" };
    const [at, up, down] = ls[0];
    return { state: "line", at, weeks: timeToTrigger(level, v, at), esc: Math.sign(v) * row.risk > 0, label: v > 0 ? up : down };
  }
  function durTxt(weeks) {
    if (!fin(weeks)) return "n/a";
    if (weeks < 1) return "under a week";
    if (weeks < 9) return `${Math.round(weeks)} week${Math.round(weeks) === 1 ? "" : "s"}`;
    const mo = weeks / WEEKS_PER_MONTH;
    if (mo < 24) return `${Math.round(mo)} months`;
    return mo > 120 ? "over 10 years" : `${fx(mo / 12, 1)} years`;
  }
  function rocRows() {
    return ROC_ROWS.map((row) => {
      const r = rocValues(row);
      return { row, r, at13: lineAhead(row, r.level, r.v13), at4: lineAhead(row, r.level, r.v4) };
    });
  }
  function paceTxt(row, r, which) {
    const v = which === 13 ? r.v13 : r.v4;
    if (!fin(v)) return "n/a";
    if (r.vm) return `${sBp(r.vm[which === 13 ? 0 : 1] * 100)}bp/mo`;
    if (row.unit === "pp") return `${sBp(v * 100)}bp/wk`;
    if (row.unit === "bp") return `${sBp(v)}bp/wk`;
    if (row.unit === "$") return `${v >= 0 ? "+" : MINUS}$${fx(Math.abs(v), 2)}/wk`;
    return `${v >= 0 ? "+" : MINUS}${fx(Math.abs(v), row.unit === "idx" ? 3 : 2)}/wk`;
  }
  function aheadCell(row, a) {
    const td = h("td");
    if (a.state === "na") { td.append(h("span", "ttt none", "n/a")); return td; }
    if (a.state === "flat") { td.append(h("span", "ttt none", "flat")); return td; }
    if (a.state === "none") { td.append(h("span", "ttt none", row.lines.length ? "no line ahead" : "no rule")); return td; }
    const cls = !a.esc ? "relief" : a.weeks <= 8 ? "hot" : a.weeks <= 26 ? "near" : "";
    td.append(h("span", "ttt" + (cls ? " " + cls : ""), `${durTxt(a.weeks)} to ${fmtRocLevel(row, a.at)}`),
      h("small", "ttl", a.label + (row.meanReverting && a.esc ? " (VIX mean-reverts: a pace is not a forecast)" : "")));
    return td;
  }
  function renderROC() {
    const tbl = $("#roc-table");
    if (!tbl) return;
    const rows = rocRows(), thead = h("thead"), hr = h("tr"), tb = h("tbody");
    [["Signal", ""], ["Level", "r"], ["Pace, 13 weeks", "r"], ["Pace, 4 weeks", "r"], ["Speeding up?", ""], ["Heading, 4-week", ""], ["At the 13-week pace", ""], ["At the 4-week pace", ""]]
      .forEach(([t, c]) => { const th = h("th", c || null, t); th.scope = "col"; hr.append(th); });
    thead.append(hr);
    rows.forEach(({ row, r, at13, at4 }) => {
      const tr = h("tr"), th = h("th", null, row.n);
      th.scope = "row";
      th.append(h("small", null, `${row.freq === "m" ? monthNice(r.date) : isoNice(r.date)} · ${r.live ? "live" : "as shipped"}`));
      // the heading is the most recent pace (4 weeks); "speeding up" compares the two paces the row prints
      const v = fin(r.v4) ? r.v4 : r.v13, toward = fin(v) && v !== 0 ? Math.sign(v) * row.risk : 0;
      const accel = !fin(r.v4) || !fin(r.v13) ? "n/a" : Math.abs(r.v4) < 1e-9 && Math.abs(r.v13) < 1e-9 ? "steady"
        : Math.sign(r.v4) !== Math.sign(r.v13) && Math.abs(r.v13) > 1e-9 ? "reversing" : Math.abs(r.v4) > Math.abs(r.v13) * 1.1 ? "faster" : Math.abs(r.v4) < Math.abs(r.v13) * 0.9 ? "slower" : "steady";
      const paceCell = (which) => { const td = h("td", "r", paceTxt(row, r, which)), w = which === 13 ? r.w13 : r.w4; if (w && fin(which === 13 ? r.v13 : r.v4)) td.append(h("small", "ttl", w)); return td; };
      tr.append(th, h("td", "r", fmtRocLevel(row, r.level)), paceCell(13), paceCell(4), h("td", null, accel));
      const d = h("td", "dir " + (toward > 0 ? "up" : toward < 0 ? "down" : "flat"), !fin(v) || v === 0 ? "→" : v > 0 ? "↑" : "↓");
      d.setAttribute("aria-label", toward > 0 ? "moving toward risk" : toward < 0 ? "moving away from risk" : "flat");
      d.title = d.getAttribute("aria-label");
      tr.append(d, aheadCell(row, at13), aheadCell(row, at4));
      tr.title = r.how;
      tb.append(tr);
    });
    tbl.replaceChildren(thead, tb);
    const anyLive = rows.some((x) => x.r.live);
    $("#roc-note").textContent = (anyLive ? "Live rows come from the daily FRED run: 13- and 4-week least-squares slopes in the unit each market is quoted in. " : "Rows as shipped use Treasury, CBOE, EIA, BLS and ICE histories through mid-October, with slopes computed by the engine's own code; the daily run replaces them. ")
      + "Inflation is monthly, so its paces are a three-month slope and the last one-month change. Red is a rule line approaching in the risk direction, amber within six months, green is relief. Hover a row for its method.";
  }

  /* ---------- assumptions: probability, impact, fragility ---------- */
  function renderAssumptions() {
    const tbl = $("#as-table");
    if (!tbl) return;
    const rows = ASSUMPTIONS.map((a) => ({ a, p: asP(a.id) })).map((x) => ({ ...x, frag: (1 - x.p) * x.a.imp })).sort((x, y) => y.frag - x.frag);
    const DS = decisions(), names = Object.fromEntries(DS.map((d) => [d.id, d.n.replace("?", "")]));
    // the Feeds column is derived from the cards' own "rests on" lists, so the two can never disagree (audit v0.24, major 27)
    const feedsOf = (aid) => DS.filter((d) => Array.isArray(d.as) && d.as.includes(aid)).map((d) => d.id);
    const thead = h("thead"), hr = h("tr"), tb = h("tbody");
    [["Assumption", ""], ["Kind", ""], ["Probability it holds", ""], ["Impact (1 to 5)", "r"], ["Fragility", ""], ["What would falsify it", ""], ["Feeds", ""]]
      .forEach(([t, c]) => { const th = h("th", c || null, t); th.scope = "col"; hr.append(th); });
    thead.append(hr);
    rows.forEach(({ a, p, frag }) => {
      const tr = h("tr"), td = h("td", "stmt");
      tr.id = "as-" + a.id + "-row";
      td.append(document.createTextNode(a.t), h("small", null, a.ev));
      const k = h("td");
      k.append(h("span", "kind-tag", a.kind));
      const pc = h("td"), inp = h("input"), out = h("output", null, Math.round(p * 100) + "%");
      inp.type = "range"; inp.min = "0.05"; inp.max = "0.99"; inp.step = "0.01"; inp.value = String(p); inp.id = "as-" + a.id;
      inp.setAttribute("aria-label", `Probability that ${a.t}`);
      out.setAttribute("for", inp.id);
      if (fin(asOverride[a.id])) out.classList.add("mine");
      inp.addEventListener("input", () => { asOverride[a.id] = Number(inp.value); out.textContent = Math.round(Number(inp.value) * 100) + "%"; });
      inp.addEventListener("change", () => {
        LS.set("bo-assume", asOverride);
        guard("Assumptions", renderAssumptions, $("#as-table"));
        guard("Decisions", renderDecisions, $("#dec-board"));
        const back = $("#as-" + a.id);
        if (back) back.focus();
      });
      pc.append(inp, document.createTextNode(" "), out);
      const fr = h("td"), bar = h("span", "frag" + (frag >= 1.2 ? " hi" : frag < 0.5 ? " lo" : ""));
      bar.style.width = Math.max(4, Math.round(frag * 40)) + "px";
      fr.append(bar, document.createTextNode(" " + fx(frag, 2)));
      const feeds = h("td");
      const fed = feedsOf(a.id).length ? feedsOf(a.id) : a.dec;
      fed.forEach((id, i) => { const l = h("a", null, names[id] || id); l.href = "#" + id; if (i) feeds.append(document.createTextNode("; ")); feeds.append(l); });
      tr.append(td, k, pc, h("td", "r", String(a.imp)), fr, h("td", null, a.test), feeds);
      tb.append(tr);
    });
    tbl.replaceChildren(thead, tb);
    const ps = ASSUMPTIONS.map((a) => asP(a.id)), weakest = rows[0], box = $("#as-math");
    box.replaceChildren(
      tile("All of them hold", `${Math.round(frechet(ps).lo * 100)} to ${Math.round(frechet(ps).hi * 100)}%`, `Bounds that need no independence assumption; ${Math.round(conjunction(ps) * 100)}% only if all ${ps.length} were independent. Shared causes push it toward the top.`),
      tile("Expected to fail", fx(ps.reduce((s, p) => s + (1 - p), 0), 1) + " of " + ps.length, "The sum of (1 − p): how many of these the desk should expect to be wrong."),
      tile("Most fragile", weakest.a.kind, weakest.a.t));
    if (Object.keys(asOverride).length) {
      const b = h("button", "btn ghost", "Reset to the desk's probabilities");
      b.type = "button";
      b.addEventListener("click", () => { asOverride = {}; LS.set("bo-assume", {}); guard("Assumptions", renderAssumptions, $("#as-table")); guard("Decisions", renderDecisions, $("#dec-board")); });
      box.append(b);
    }
  }

  /* ---------- known knowns to unknown unknowns ---------- */
  function renderKnowns() {
    const box = $("#kk-grid");
    if (!box) return;
    box.replaceChildren();
    const cell = (k) => {
      const q = KNOWNS[k], c = h("div", "cell q-" + k);
      c.append(h("h3", null, q.h), h("span", "eyebrow", q.sub));
      const ul = h("ul");
      q.items.forEach((t) => { const li = h("li"); li.innerHTML = t; ul.append(li); });
      c.append(ul, h("p", "resp", q.resp));
      return c;
    };
    box.append(h("span", "ax"), h("span", "ax", "Known"), h("span", "ax", "Unknown"));
    box.append(h("span", "ax v", "We are aware"), cell("kk"), cell("ku"));
    box.append(h("span", "ax v", "We are not aware"), cell("uk"), cell("uu"));
  }

  /* ---------- 2nd- to 4th-order chains, each step with today's reading ---------- */
  function watchValue(w) {
    if (!w) return "";
    if (w.startsWith("text:")) return w.slice(5);
    const I = inputs();
    switch (w) {
      case "oil": return `Brent $${fx(I.oil.v, 2)} (${isoNice(I.oil.d)})`;
      case "cpi": return `CPI ${pctPts(I.infl.yoy)} a year; ${pctPts(I.infl.avg36)} over 36 months (${monthNice(I.infl.d)})`;
      case "real": return `Real 10-year ${pctPts(I.real.v)} (${isoNice(I.real.d)})`;
      case "corr": return `Stock-bond correlation ${sgn2(I.corr.v)} (${I.corr.live ? "63-day" : "36-month"})`;
      case "ccc": return `CCC ${pctPts(I.ccc.v)}, high yield ${pctPts(I.hy.v)}`;
      case "capex": return `Capex $${fx(I.capexTTM, 0)}B against operating cash flow $${fx(I.ocfTTM, 0)}B (five builders)`;
      case "y30": { const r = rocValues(ROC_ROWS.find((x) => x.k === "y30")); return `30-year ${pctPts(r.level)}, ${sBp(r.v13 * 100)}bp a week over 13 weeks`; }
      case "vix": return `VIX ${fx(I.vix.v, 2)}`;
      default: return "";
    }
  }
  const ORDER_NAME = ["Trigger", "1st order", "2nd order", "3rd order", "4th order"];
  function renderChains() {
    const box = $("#chain-list");
    if (!box) return;
    box.replaceChildren();
    CHAINS.forEach((c) => {
      const art = h("article", "cchain");
      art.id = c.id;
      const head = h("div", "cchain-head");
      head.append(h("h3", null, c.n));
      const row = h("ol", "orders");
      c.steps.forEach((s) => {
        const o = h("li", "ord");
        o.dataset.o = String(s.o);
        const w = h("p", "watch");
        w.append(document.createTextNode("Watch: "), h("b", null, watchValue(s.w)));
        o.append(h("span", "lvl", ORDER_NAME[s.o]), h("p", null, s.t), w, h("p", "do", s.do));
        row.append(o);
      });
      art.append(head, h("p", "so", c.so), row);
      box.append(art);
    });
  }

  /* ---------- the brief (Today): do, risk, watch ---------- */
  function renderBrief() {
    const box = $("#brief");
    if (!box) return;
    const ds = decisions(), g = ds[0], dur = ds[1], tail = ds.find((d) => d.id === "d-tail"), cr = ds.find((d) => d.id === "d-credit"), I = inputs();
    const b34 = readF().hedge.rows.find((r) => r.bucket === "3 to 4%");
    const near = rocRows().filter((x) => !x.row.meanReverting && x.at13.state === "line" && x.at13.esc && fin(x.at13.weeks)).sort((a, b) => a.at13.weeks - b.at13.weeks).slice(0, 2);
    box.replaceChildren();
    const cell = (k, v, n, href, label) => {
      const d = h("div");
      d.append(h("span", "bk", k), h("span", "bv", v), h("span", "bn", n));
      if (href) { const a = h("a", null, label + " →"); a.href = href; d.append(a); }
      return d;
    };
    const lower = (s) => s.charAt(0).toLowerCase() + s.slice(1);
    const above = I.infl.avg36 >= I.lineAt, TD = tltNow(I);
    box.append(
      (typeof DX19 !== "undefined" && DX19 && DX19.now
        ? (() => { const BC = typeof bookCall === "function" ? bookCall(DX19.now) : null;
            return BC ? cell("Do", `Run the book at ${xx(BC.size)}. ${dur.level === 2 ? "No bond hedge." : "Bond hedge on."}`, `${BC.keep != null ? `Or keep every name and short ${pct0(BC.keep)} of NAV in Nasdaq-100 futures. ` : ""}${tail.act}; ${lower(cr.act)}.`, "#book", "Book risk")
              : cell("Do", `Hold ${xx(DX19.now.exposure)} equity. ${dur.level === 2 ? "No bond hedge." : "Bond hedge on."}`, `The engine's gated call governs; the volatility rule's ${xx(g.vol)} is a cross-check. ${tail.act}; ${lower(cr.act)}.`, "#decide", "The seven decisions"); })()
        : cell("Do", `${g.act}. ${dur.level === 2 ? "No bond hedge." : "Bond hedge on."}`, `${tail.act}; ${lower(cr.act)}.`, "#decide", "The seven decisions")),
      cell("Risk", TD.on ? "The bond hedge is on: stocks and bonds are moving opposite." : TD.gates.state.value === "amplifying" ? `Bonds won't hedge: stocks and bonds move together (${sgn2(I.corr.v)}).` : `The bond hedge is unproven: correlation ${sgn2(I.corr.v)}.`,
        above ? `${b34 ? `Since 1871, with inflation at 3 to 4%, bonds hedged ${Math.round(b34.share_hedging * 100)}% of months. ` : ""}${fin(I.infl.months) ? `At 2% inflation from here, the 36-month average stays above 2.75% for ${I.infl.months} months.` : ""}` : "", "#fi-hedge", "The finding"),
      near.length ? cell("Watch", near.map((x) => `${x.row.n}: ${fmtRocLevel(x.row, x.at13.at)} in ${durTxt(x.at13.weeks)}`).join("; ") + ".",
        `At the 13-week pace. ${near.map((x) => `${x.row.n}: "${x.at13.label}"`).join("; ")}.`, "#roc-title", "Rates of change")
        : cell("Watch", "No rule line is approaching at the current pace.", "", "#roc-title", "Rates of change"));
  }

  /* ---------- the system map (Today) ---------- */
  function nodeState(n) {
    if (fin(n.state)) return n.state;
    const st = LIVE.sigStates || {};
    const lv = n.sig.map((id) => (st[id] && st[id].level != null ? st[id].level : null)).filter((x) => x != null);
    return lv.length ? Math.max(...lv) : null;
  }
  const STATE_WORD = ["Calm", "Watch", "Act"];
  function renderMap() {
    const box = $("#map-box");
    if (!box) return;
    const W = boxWidth(box), H = Math.round(Math.max(380, Math.min(520, W * 0.56))), nw = Math.round(Math.min(170, Math.max(124, W * 0.15))), nh = 46;
    box.replaceChildren();
    const s = svg("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: "group", "aria-label": "System map: nine parts of the financial system and the channels between them" }, box);
    const pos = {};
    MAP.nodes.forEach((n) => { pos[n.id] = { x: 12 + n.x * (W - 24 - nw) + nw / 2, y: 10 + n.y * (H - 20 - nh) + nh / 2, st: nodeState(n), n }; });
    const edges = svg("g", { "aria-hidden": "true" }, s), hits = svg("g", {}, s);
    MAP.edges.forEach(([a, b, label, wt]) => {
      const A = pos[a], B = pos[b];
      if (!A || !B) return;
      const hot = A.st === 2 && (B.st || 0) >= 1;
      const mx = (A.x + B.x) / 2 + (B.y - A.y) * 0.12, my = (A.y + B.y) / 2 - (B.x - A.x) * 0.12, d = `M${A.x},${A.y} Q${mx},${my} ${B.x},${B.y}`;
      svg("path", { d, class: "edge" + (wt >= 2 ? " strong" : "") + (hot ? " hot" : "") }, edges);
      const hit = svg("path", { d, fill: "none", stroke: "transparent", "stroke-width": 14 }, hits);
      bindTip(hit, () => [[label, `${A.n.n} → ${B.n.n}${hot ? " · carrying stress now" : ""}`]]);
    });
    const list = h("div", "sysmap-list");
    MAP.nodes.forEach((n) => {
      const P = pos[n.id], word = P.st == null ? "no signal" : STATE_WORD[P.st];
      const a = svg("a", { href: "#" + n.at, "aria-label": `${n.n}: ${word}` }, s);
      svg("rect", { x: P.x - nw / 2, y: P.y - nh / 2, width: nw, height: nh, rx: 9, class: "node-box" + (P.st == null ? "" : " l" + P.st) }, a);
      text(a, P.x, P.y - 3, n.n, "node-name", "middle");
      text(a, P.x, P.y + 13, word, "node-state", "middle");
      const row = h("a", "tchip", `${n.n}: ${word}`);
      row.href = "#" + n.at;
      list.append(row);
    });
    box.append(list);
  }

  /* ---------- connections most portfolios miss (Today) ---------- */
  function renderMiss() {
    const box = $("#miss-list");
    if (!box) return;
    const I = inputs(), F = readF(), g = fundRow("GOOGL"), O = F.oil.summary, faq = FAQ.find((f) => /inflation figures change/.test(f.q));
    const items = [
      ["The hedge and the book share a borrower.", `The five builders spend ${pct0(I.capexTTM / I.ocfTTM)} of their operating cash flow on capex, and the ones spending more than they earn borrow the gap: Amazon's debt rose ${pct0(fundRow("AMZN").debt_yoy)} in a year; Oracle owes ${B$(fundRow("ORCL").debt, 0)}. That bond supply lifts the long yields the TLT hedge depends on.`, "ch-debt", "The chain"],
      ["Bonds stay out for months, even if inflation breaks.", `Three-year inflation is ${pctPts(I.infl.avg36)}. At 2% inflation from here, base effects keep it above 2.75% for about ${I.infl.months} months, and stocks and bonds are moving together today.`, "d-duration", "Decision 2"],
      ["Earnings are partly marks on each other.", `${pct0(g.nonop_share)} of Alphabet's pre-tax income over the last twelve months was non-operating, mostly gains on private AI stakes. Those reverse faster than the business.`, "pp-title", "Paper profits"],
      ["Today's oil spike is the kind that hurt.", `Brent is ${fx(I.oil.v / I.oilAvg5, 2)} times its five-year average: a supply shock. Since 1989 those were followed by a ${sPct(O.supply.mean_fwd12, 1)} average year for stocks; demand rebounds by ${sPct(O.rebound.mean_fwd12, 1)}.`, "fi-oil", "The finding"],
      ["The build is limited by watts, not dollars.", "PJM cleared 6,623 MW short of its reliability target, at the price cap; turbine order books run toward 2030; 91.5% of megaprojects finish late, over budget or both.", "physics", "Physics"],
      ["One missing month broke the inflation math.", "BLS published no October 2025 CPI. Code that drops the month measures 13 months of inflation: August read 3.69% instead of the 3.4% BLS printed. The engine now fills the calendar.", faq ? faqId(faq) : "faq-title", "The fix"],
    ];
    box.replaceChildren(...items.map(([hd, body, at, label]) => {
      const c = h("article", "card");
      c.append(h("h3", null, hd), h("p", null, body));
      const a = h("a", "src", label + " →");
      a.href = "#" + at;
      c.append(a);
      return c;
    }));
  }

  function buildDecide() {
    guard("Connections", renderMiss, $("#miss-list"));
    guard("Decisions", renderDecisions, $("#dec-board"));
    guard("Rates of change", renderROC, $("#roc-table"));
    guard("Assumptions", renderAssumptions, $("#as-table"));
    guard("Knowns", renderKnowns, $("#kk-grid"));
    guard("Chains", renderChains, $("#chain-list"));
    guard("Brief", renderBrief, $("#brief"));
  }

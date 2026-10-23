  /* =====================================================================================
     pf.js (v0.20): the portfolio engine desk. Stocks, 10-year Treasuries, gold and cash decided together from regimes,
     a learner over whole policies, ten simulated years and eight replayed drawdowns. Every number was computed by
     buildout/portfolio.py and shipped in snap20.js.
     ===================================================================================== */
  function pfOk() { try { return typeof PF20 === "object" && PF20 && PF20.now && PF20.perf; } catch (e) { return false; } }
  const PF_COL = { stocks: "var(--s1)", bonds: "var(--s3)", gold: "var(--s4)", cash: "var(--muted)" };
  const PF_POL = { hold: "Hold stocks", sixty_forty: "60/40", risk_parity: "Risk parity", trend: "10-month trend rule", regime: "Regime allocation",
    regime_stocks: "Regime, stocks only", gated: "Regime, gated by its evidence", meta: "The learner over six policies" };
  function pfMixText(a) {
    const c = 1 - a[0] - a[1] - a[2];
    const parts = [["stocks", a[0]], ["Treasuries", a[1]], ["gold", a[2]]].filter(([, v]) => v > 1e-9).map(([k, v]) => `${Math.round(v * 100)}% ${k}`);
    if (c > 1e-9) parts.push(`${Math.round(c * 100)}% cash`); else if (c < -1e-9) parts.push(`${Math.round(-c * 100)}% borrowed`);
    return parts.join(", ");
  }
  function pfMixBar(label, a, note) {
    const row = h("div", "pf-mix");
    const head = h("div", "pf-mix-h");
    head.append(h("b", null, label), h("span", null, pfMixText(a)));
    const bar = h("div", "pf-bar"), tot = 1.5;                  // one scale for every bar: 100% sits two thirds along, borrowing runs past it
    const seg = (k, v) => { if (v <= 1e-9) return; const s = h("i"); s.style.width = (v / tot * 100).toFixed(2) + "%"; s.style.background = PF_COL[k]; s.title = `${Math.round(v * 100)}% ${k}`; bar.append(s); };
    seg("stocks", a[0]); seg("bonds", a[1]); seg("gold", a[2]); seg("cash", Math.max(0, 1 - a[0] - a[1] - a[2]));
    const wrap = h("div", "pf-barw"); wrap.append(bar, h("span", "pf-100", "100%"));
    row.append(head, wrap);
    if (note) row.append(h("small", null, note));
    return row;
  }
  function renderPortfolio() {
    const card = $("#pf-card");
    if (!card || !pfOk()) { if (card && !card.children.length) card.append(h("p", "hint", "The portfolio engine is missing from the snapshot.")); return; }
    const O = PF20, N = O.now, P = O.perf, st = N.states;
    let cur = 0; N.next.forEach((v, i) => { if (v > N.next[cur]) cur = i; });
    const sim = O.simulation;
    if (!card.children.length) {
      const gp = PF_POL[N.gate_policy] || N.gate_policy;
      $("#pf-bluf").textContent = `Recommendation: hold ${pfMixText(N.decision)}. The regime model's optimum is ${pfMixText(N.optimum)}, but timing stocks, Treasuries and gold by regime earned a Sharpe of ${fx(P.regime.sharpe, 2)} walked forward since ${O.start.slice(0, 4)}, against ${fx(P.hold.sharpe, 2)} for holding and ${fx(P.sixty_forty.sharpe, 2)} for 60/40. A learner that weights six whole policies by their record matched holding (${fx(P.meta.sharpe, 2)}) with a worst drawdown of ${pct(P.meta.maxdd, 0)} instead of ${pct(P.hold.maxdd, 0)}; diversifying across decision processes outperformed regime prediction.`;
      card.append(h("span", "dx-k", "Model-book mix"));
      card.append(pfMixBar("Decision", N.decision, `the gate moves ${pct(N.gate, 0, false)} of the way toward the best-evidenced policy, ${gp.toLowerCase()} (utility t ${fx(N.gate_t, 1)} against ${fx(N.gate_t0, 1)} from luck)`));
      card.append(pfMixBar("Regime optimum", N.optimum, `expected utility under next month's regime odds, inside a ${pct(O.es_limit, 0, false)} expected-shortfall budget`));
      card.append(pfMixBar("The learner", N.meta_mix, "exponential weights over six policies by their log growth"));
      card.append(pfMixBar("Risk parity", N.risk_parity_mix, "inverse volatility over the last three years"));
      const lg = h("div", "legend");
      [["stocks", "US stocks"], ["bonds", "10-year Treasuries"], ["gold", "Gold"], ["cash", "Cash"]].forEach(([k, n]) => { const sp = h("span"); const i = h("i"); i.style.background = PF_COL[k]; sp.append(i, document.createTextNode(n)); lg.append(sp); });
      card.append(lg, h("p", "dx-note", "The MODEL book, not personal positions. Research only: the engine never places orders."));
      const h10 = sim.hold.horizons["120"], s10 = sim.sixty_forty.horizons["120"];
      dxKpis($("#pf-tiles"), [
        [pct(N.next[cur], 0, false), st[cur].name + " regime next month", `${N.K} states of stocks, bonds and gold by BIC`],
        [(st[cur].corr_sb >= 0 ? "+" : MINUS) + Math.abs(st[cur].corr_sb).toFixed(2), "Stock-bond correlation there", "above zero, Treasuries do not hedge stocks"],
        [fx(P.meta.sharpe, 2), "The learner's Sharpe", `worst drawdown ${pct(P.meta.maxdd, 0)} against ${pct(P.hold.maxdd, 0)}`],
        [fx(h10.q50, 2) + "x", "All stocks, ten years, median", `5% to 95%: ${fx(h10.q05, 2)}x to ${fx(h10.q95, 2)}x real`],
        [fx(s10.q50, 2) + "x", "60/40, ten years, median", `5% to 95%: ${fx(s10.q05, 2)}x to ${fx(s10.q95, 2)}x real`],
        [pct(sim.hold.p_dd30, 0, false) + " / " + pct(sim.sixty_forty.p_dd30, 0, false), "Drawdown over 30% in ten years", "all stocks / 60/40, simulated"]]);
      const ann = (v) => pct(v, 1);
      fillTable($("#pf-states"), ["State", "Next month", "Stocks", "Treasuries", "Gold", "Stock vol", "Stock-bond corr", "Lasts about"], st.map((s, k) => [
        k === cur ? h("b", null, s.name) : s.name, pct(N.next[k], 0, false), ann(s.mu_shrunk[0]), ann(s.mu_shrunk[1]), ann(s.mu_shrunk[2]), pct(s.vol[0], 0, false),
        (s.corr_sb >= 0 ? "+" : MINUS) + Math.abs(s.corr_sb).toFixed(2), Math.round(s.persistence_months) + " months"]), 1);
      const order = ["hold", "sixty_forty", "risk_parity", "trend", "regime", "regime_stocks", "gated", "meta"];
      fillTable($("#pf-perf"), ["Policy", "Sharpe", "Real growth", "Worst drawdown", "Average mix", "Utility t vs holding"], order.filter((k) => P[k]).map((k) => {
        const p = P[k];
        return [k === "meta" ? h("b", null, PF_POL[k]) : PF_POL[k], fx(p.sharpe, 2), pct(p.cagr, 1), pct(p.maxdd, 0), pfMixText([p.avg.stocks, p.avg.bonds, p.avg.gold]), k === "hold" ? "" : fx(p.utility_t, 1)];
      }), 1);
      $("#pf-dsr").textContent = `Deflated for the ${O.n_tried} policies tried, the chance the best one in excess of holding (${(PF_POL[O.deflated.best] || O.deflated.best).toLowerCase()}) has a real edge is ${pct(O.deflated.dsr, 0, false)}. The learner's rate, ${fx(O.meta.eta, 3)}, is fixed in advance from the horizon and the number of policies, which bounds its shortfall against the best policy in hindsight at ${fx(O.meta.bound, 1)} in log wealth; it was not tuned on the result.`;
      const hz = ["12", "36", "60", "120"], lab = { "12": "1 year", "36": "3 years", "60": "5 years", "120": "10 years" };
      const mixes = [["hold", "All stocks"], ["sixty_forty", "60/40"], ["risk_parity", "Risk parity"], ["optimum", "Regime optimum"]];
      fillTable($("#pf-sim"), ["Mix", ...hz.map((k) => lab[k] + ", median"), "10 years, 5% to 95%", "Real loss at 5 years", "Drawdown over 30%"], mixes.map(([k, n]) => {
        const s = sim[k];
        return [n, ...hz.map((x) => fx(s.horizons[x].q50, 2) + "x"), `${fx(s.horizons["120"].q05, 2)}x to ${fx(s.horizons["120"].q95, 2)}x`, pct(s.horizons["60"].p_loss, 0, false), pct(s.p_dd30, 0, false)];
      }), 1);
      fillTable($("#pf-stress"), ["Episode", "Months", "All stocks", "60/40", "Risk parity", "Regime optimum", "Gold alone"], O.stress.map((r) => [
        `${r.name} (${r.start} to ${r.end})`, String(r.months), ...["hold", "sixty_forty", "risk_parity", "optimum"].map((k) => h("span", r.returns[k] >= 0 ? "pos" : "neg", pct(r.returns[k], 0))), h("span", r.assets.gold >= 0 ? "pos" : "neg", pct(r.assets.gold, 0))]), 1);
      fillTable($("#pf-drv"), ["If", "The optimum would be"], N.drivers.map((d) => [d.state != null ? `Certain of the ${st[d.state].name.toLowerCase()} state` : d.part, pfMixText(d.mix)]), 1);
      const ol = $("#pf-find");
      O.findings.forEach((f) => ol.append(h("li", null, f)));
    }
    pfCharts();
  }
  function pfCharts() {
    const O = PF20, N = O.now;
    const yr = (arr) => arr.map(dxYear);
    const C = O.curve, xd = yr(C.dates), l10 = (a) => a.map((v) => v / Math.LN10);
    const S = [["meta", "var(--s1)", 2.4], ["hold", "var(--muted)", 1.6], ["sixty_forty", "var(--s3)", 1.8], ["risk_parity", "var(--s4)", 1.4], ["regime", "var(--s2)", 1.4], ["trend", "var(--s5)", 1.2]];
    xyChart($("#pf-curve"), { series: S.map(([k, c, w]) => ({ name: PF_POL[k], pts: xd.map((x, i) => [x, l10(C[k])[i]]), color: c, width: w })), height: 280, yTicks: 4,
      yfmt: (v) => { const m = Math.pow(10, v); return (m >= 10 ? Math.round(m).toLocaleString("en-US") : fx(m, 1)) + "x"; }, xfmt: (v) => String(Math.floor(v)),
      xticks: dxTicks(xd[0], xd[xd.length - 1], 10), label: "Growth of one real dollar since " + O.start.slice(0, 4) });
    legendLines($("#pf-curve-leg"), S.map(([k, c]) => [c, PF_POL[k]]));
    const M = O.meta.hist, md = yr(M.dates), cols = ["var(--muted)", "var(--s3)", "var(--s4)", "var(--s5)", "var(--s2)", "var(--s1)"];
    xyChart($("#pf-meta"), { series: O.meta.names.map((k, j) => ({ name: PF_POL[k], pts: md.map((x, i) => [x, M[k][i]]), color: cols[j], width: 1.8 })), height: 200, yDomain: [0, 0.3],
      yfmt: (v) => pct(v, 0, false), xfmt: (v) => String(Math.floor(v)), xticks: dxTicks(md[0], md[md.length - 1], 10), label: "The learner's weights on each policy" });
    legendLines($("#pf-meta-leg"), O.meta.names.map((k, j) => [cols[j], PF_POL[k]]));
    const fan = O.simulation, fm = fan._meta.fan_months.map((m) => m / 12);
    const band = (k, c) => [{ pts: fm.map((x, i) => [x, Math.log10(fan[k].fan.q05[i]), Math.log10(fan[k].fan.q95[i])]), color: c, opacity: 0.1 },
      { pts: fm.map((x, i) => [x, Math.log10(fan[k].fan.q25[i]), Math.log10(fan[k].fan.q75[i])]), color: c, opacity: 0.18 }];
    xyChart($("#pf-fan"), { series: [{ name: "All stocks, median", pts: fm.map((x, i) => [x, Math.log10(fan.hold.fan.q50[i])]), color: "var(--s1)", width: 2.2 },
      { name: "60/40, median", pts: fm.map((x, i) => [x, Math.log10(fan.sixty_forty.fan.q50[i])]), color: "var(--s3)", width: 2.2 }],
    bands: [...band("hold", "var(--s1)"), ...band("sixty_forty", "var(--s3)")], height: 260, zero: true,
    yfmt: (v) => fx(Math.pow(10, v), 1) + "x", xfmt: (v) => "year " + fx(v, 1), xticks: [1, 2, 4, 6, 8, 10].map((v) => [v, "year " + v]), label: "Ten years simulated from today's regime odds" });
    legendLines($("#pf-fan-leg"), [["var(--s1)", "All stocks: median, middle half, 90% band"], ["var(--s3)", "60/40: median, middle half, 90% band"]]);
    const SP = N.stress_path;
    xyChart($("#pf-sp"), { series: [["stocks", 0], ["bonds", 1], ["gold", 2]].map(([k, j]) => ({ name: { stocks: "Stocks", bonds: "Treasuries", gold: "Gold" }[k], pts: SP.map((r) => [r.p, r.mix[j]]), color: PF_COL[k], width: 2.2, dots: true })),
      height: 220, yDomain: [0, 1.5], yfmt: (v) => fx(v, 1) + "x", xfmt: (v) => "stressed odds " + pct(v, 0, false), xticks: [0, 0.25, 0.5, 0.75, 1].map((v) => [v, pct(v, 0, false)]),
      vmarks: [{ x: N.next[N.worst], label: "today" }], label: "The optimum mix against the stressed regime's odds" });
    legendLines($("#pf-sp-leg"), [[PF_COL.stocks, "Stocks"], [PF_COL.bonds, "10-year Treasuries"], [PF_COL.gold, "Gold"]]);
    const H = N.history, hd = yr(H.dates), avg = (a, n = 8) => a.map((_, i) => { const w = a.slice(Math.max(0, i - n + 1), i + 1); return w.reduce((x, y) => x + y, 0) / w.length; });
    const sw = avg(H.p_worst), fw = avg(H.filtered);
    xyChart($("#pf-reg"), { series: [{ name: "Stressed state, smoothed", pts: hd.map((x, i) => [x, sw[i]]), color: "var(--s2)", width: 1.6, area: true },
      { name: "Stressed state, filtered", pts: hd.map((x, i) => [x, fw[i]]), color: "var(--s1)", width: 1.4 }], height: 200, yDomain: [0, 1], yfmt: (v) => pct(v, 0, false),
    xfmt: (v) => String(Math.floor(v)), xticks: dxTicks(hd[0], hd[hd.length - 1], 25), label: "Odds of the stressed state, two-year average" });
  }

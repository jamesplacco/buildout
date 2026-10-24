  /* =====================================================================================
     dx.js (v0.19): the decision engine desk. Data, features, models, inference, decision, one pipeline walked forward
     from 1940. Every number was computed by buildout/decide.py (with infer.py and nn.py) and shipped in snap19.js.
     ===================================================================================== */
  function dxOk() { try { return typeof DX19 === "object" && DX19 && DX19.now && Array.isArray(DX19.pipeline); } catch (e) { return false; } }
  const dxYear = (d) => Number(d.slice(0, 4)) + (Number(d.slice(5, 7)) - 1) / 12;
  const dxX = (v) => (fin(v) ? fx(v, 2) + "x" : "n/a");
  const dxTicks = (a, b, step) => { const o = []; for (let y = Math.ceil(a / step) * step; y <= b; y += step) o.push([y, String(y)]); return o; };
  function dxKpis(box, rows) {
    rows.forEach(([v, k, s]) => { const d = h("div", "at-kpi"); d.append(h("b", null, v), h("span", null, k), h("small", null, s)); box.append(d); });
  }
  function renderDecision() {
    const card = $("#dx-card");
    if (!card || !dxOk()) { if (card && !card.children.length) card.append(h("p", "hint", "The decision engine is missing from this build.")); return; }
    const O = DX19, N = O.now, R = N.regime, G = N.gate, Fc = N.forecasts, E = O.configs.engine, Hd = O.hold;
    if (!card.children.length) {
      const worst = R.next[R.worst];
      $("#dx-bluf").textContent = `Recommendation: hold ${dxX(N.exposure)} equity exposure. The engine's unconstrained optimum is ${dxX(N.engine_exposure)}, driven by a calm regime, but walked forward since ${O.start.slice(0, 4)} its departures from 1x left a risk-averse investor no better off than holding (Sharpe ${fx(E.perf.sharpe, 2)} against ${fx(Hd.sharpe, 2)}), so its evidence gate moves ${pct(G.value, 0, false)} of the way toward that optimum. The engine departs from the baseline only when its own record supports doing so.`;
      // the recommendation
      const big = h("div", "dx-big");
      big.append(h("span", "dx-k", "Model-book exposure"), h("b", "dx-x", dxX(N.exposure)), h("span", "dx-sub", "stocks, against a 1.00x baseline"));
      const why = h("div", "dx-why");
      [["Engine's optimum", dxX(N.engine_exposure), N.capped ? "held down by the risk budget" : "expected utility, inside the risk budget"],
        ["Evidence gate", pct(G.value, 0, false), `utility gain t ${fx(G.t, 1)} vs ${fx(G.t0, 1)} for the best of ${G.n_tried} useless strategies`],
        ["Hedge", N.hedge.name, `${N.hedge.context}; best with ${pct(Math.max(...N.hedge.p_best), 0, false)} odds (bond data to ${N.hedge.as_of})`],
        ["RL checks", `${dxX(N.rl.v16)} and ${dxX(N.rl.conservative.action)}`, `the fitted-Q agent and the conservative ensemble (${pct(N.rl.conservative.agreement, 0, false)} of its agents agree)`]]
        .forEach(([k, v, s]) => { const r = h("div", "dx-row"); r.append(h("span", "dx-rk", k), h("b", null, v), h("small", null, s)); why.append(r); });
      card.append(big, why, h("p", "dx-note", "The MODEL book, not personal positions. Research only: the engine never places orders."));
      // the pipeline
      const pipe = $("#dx-pipe");
      O.pipeline.forEach((p, i) => { const s = h("li", "dx-stage"); s.append(h("span", "dx-n", String(i + 1).padStart(2, "0")), h("b", null, p.stage), h("span", null, p.what)); pipe.append(s); });
      dxKpis($("#dx-tiles"), [
        [pct(worst, 0, false), "Stressed regime, next month", `${R.K}-state model of stock returns alone; the portfolio engine's three-asset model and the labs' two-state model put it lower`],
        [pct(N.changepoint.recent, 0, false), "New regime in the last 6 months", `changepoint odds; expected run ${Math.round(N.changepoint.expected_run)} months`],
        [pct(Fc.stacked, 1), "Stacked 12-month real return", `historical mean ${pct(Fc.now.mean, 1)}`],
        [fx(E.perf.sharpe - Hd.sharpe, 2), "Engine Sharpe minus holding", `90% range ${fx(E.sharpe_vs_hold.lo, 2)} to ${fx(E.sharpe_vs_hold.hi, 2)}, since ${O.start.slice(0, 4)}`],
        [N.evpi ? Math.round(N.evpi.ce_month * 12e4) + " bp" : "n/a", "Worth of knowing the regime", "a year, certainty-equivalent"],
        [fx(O.gamma, 2), "Risk aversion", "set on 1871 to 1939 so holding is optimal on average"]]);
      // regimes table
      const ann = (m) => pct(m * 12, 1), annSd = (s) => pct(s * Math.sqrt(12), 0, false);
      const sdMax = R.sd.indexOf(Math.max(...R.sd)), muMax = R.mu.indexOf(Math.max(...R.mu));
      const stName = (k) => (k === R.worst ? "Stressed" : k === muMax ? "Calm" : k === sdMax ? "Turbulent" : "Middle");
      fillTable($("#dx-states"), ["State", "Mean, a year", "Shrunk mean", "Volatility", "Lasts about", "Now", "Next month"], R.mu.map((m, k) => [
        stName(k), ann(m), ann(R.mu_shrunk[k]), annSd(R.sd[k]), Math.round(R.persistence_months[k]) + " months", pct(R.now[k], 0, false), pct(R.next[k], 0, false)]), 1);
      // forecasts table
      const S = O.forecast_scores;
      fillTable($("#dx-fc"), ["Model", "Skill vs mean", "Diebold-Mariano t", "Today, 12 months", "Stack weight"], ["mean", "ridge", "combo", "nn"].map((k) => [
        Fc.names[k], h("span", S[k].skill >= 0 ? "pos" : "neg", pct(S[k].skill, 1)), fx(S[k].dm.t, 1), pct(Fc.now[k], 1), pct(Fc.weights[k], 0, false)])
        .concat([[h("b", null, "Stacked"), h("span", S.stacked.skill >= 0 ? "pos" : "neg", pct(S.stacked.skill, 1)), fx(S.stacked.dm.t, 1), pct(Fc.stacked, 1), "100%"]]), 1);
      $("#dx-nn").textContent = `The neural-network ensemble (five networks of 16 and 8 units, dropout, weight decay, early stopping on the newest fifth of the data) forecasts a ${pct(Fc.now.nn, 1)} real return with a ${pct(Fc.nn_sd, 0, false)} predictive sd, of which ${pct(Fc.nn_epistemic_sd, 1, false)} is the networks' own disagreement. Out of sample its 80% bands covered ${pct(S.nn.coverage80, 0, false)} of outcomes; rescaled by its own past misses, ${pct(S.nn.coverage80_recalibrated, 0, false)}. Like every flexible model on the ML desk, it fits the past and loses to the plain mean on the future; the stack gives it ${pct(Fc.weights.nn, 0, false)} of the weight.`;
      // model averaging now
      barsH($("#dx-mw"), Object.keys(N.models.weights).map((k) => ({ label: N.models.names[k], v: N.models.weights[k] * 100, lbl: pct(N.models.weights[k], 0, false), color: "var(--s1)",
        tip: () => [[pct(N.models.weights[k], 1, false), `${N.models.names[k]}: weight from its discounted predictive log score`]] })), { fmt: (v) => Math.round(v) + "%" });
      // drivers
      fillTable($("#dx-drv"), ["Take away", "Engine's optimum without it", "Change"], N.drivers.map((d) => [d.part, dxX(d.without), h("span", d.delta > 0 ? "pos" : (d.delta < 0 ? "neg" : null), d.delta === 0 ? "none" : fx(d.delta, 2))]), 1);
      const fl = N.flip, fl2 = [];
      if (fin(fl.cut_if_below)) fl2.push(`falls if the stacked 12-month forecast drops below ${pct(fl.cut_if_below, 0, false)}`);
      if (fin(fl.raise_if_above)) fl2.push(`rises if it tops ${pct(fl.raise_if_above, 0, false)}`);
      if (fin(fl.cut_if_stress_prob_above)) fl2.push(`falls if the stressed regime's odds pass ${pct(fl.cut_if_stress_prob_above, 0, false)}`);
      $("#dx-flip").textContent = fl2.length ? `The engine's optimum ${fl2.join("; it ")}. The gate then decides how much of any change reaches the book.` : "No input in range flips the optimum.";
      // backtest table
      const nm = { engine: "The engine", gated: "The engine, gated by its own evidence", no_forecasts: "Without the forecasts", no_risk_budget: "Without the risk budget", regimes_only: "Regimes only" };
      const rows = Object.keys(nm).filter((k) => O.configs[k]).map((k) => { const c = O.configs[k]; return [nm[k], fx(c.perf.sharpe, 2), pct(c.perf.cagr, 1), pct(c.perf.maxdd, 0), dxX(c.avg_exposure), fx(c.timing_alpha.t, 1)]; });
      rows.push(["Holding 1x", fx(Hd.sharpe, 2), pct(Hd.cagr, 1), pct(Hd.maxdd, 0), "1.00x", ""], ["The 10-month trend rule", fx(O.trend.sharpe, 2), pct(O.trend.cagr, 1), pct(O.trend.maxdd, 0), "", ""],
        ["RL agent (v0.16)", fx(O.rl.v16.sharpe, 2), pct(O.rl.v16.cagr, 1), pct(O.rl.v16.maxdd, 0), "", ""], ["RL, conservative ensemble", fx(O.rl.conservative.sharpe, 2), pct(O.rl.conservative.cagr, 1), pct(O.rl.conservative.maxdd, 0), dxX(O.rl.conservative_avg_exposure), ""]);
      fillTable($("#dx-bt"), ["Strategy", "Sharpe", "Real growth", "Worst drawdown", "Average exposure", "Timing alpha t"], rows, 1);
      const HP = O.hedges.perf;
      fillTable($("#dx-hedge"), ["Hedge", "Sharpe", "Real growth", "Worst drawdown", "Chosen"], [["The selector, by regime", fx(HP.selector.sharpe, 2), pct(HP.selector.cagr, 1), pct(HP.selector.maxdd, 0), ""]]
        .concat(Object.keys(O.hedges.names).map((k) => [O.hedges.names[k], fx(HP[k].sharpe, 2), pct(HP[k].cagr, 1), pct(HP[k].maxdd, 0), pct(O.hedges.share[k], 0, false)])), 1);
      $("#dx-hedge-note").textContent = `${O.hedges.start.slice(0, 4)} to ${O.hedges.end}, where Shiller's 10-year yield ends. Every hedge's return is seen every month, so this is an experts problem, not a bandit: each context (stressed or calm, trend on or off) keeps a discounted posterior of each hedge's log growth. Today, in a ${N.hedge.context}, the odds each is best: ${N.hedge.names.map((n, i) => `${n.toLowerCase()} ${pct(N.hedge.p_best[i], 0, false)}`).join(", ")}.`;
      $("#dx-dsr").textContent = `Deflated for the ${G.n_tried} strategies tried, the chance the best configuration's timing alpha is real is ${pct(O.deflated_excess.dsr, 0, false)}; its gain in Sharpe over holding has a 90% bootstrap range of ${fx(E.sharpe_vs_hold.lo, 2)} to ${fx(E.sharpe_vs_hold.hi, 2)}. Timing alpha is what the engine's departures from 1x earned beyond carrying more or less market; a risk-averse investor also pays for the extra swings, which is what the gate measures.`;
      // v0.23: the gate in words, and the overlay study
      const gn = $("#dx-gate-note");
      if (gn) gn.textContent = `g = max(0, 2Φ(t − t0) − 1). The engine's monthly utility gain over holding since ${O.start.slice(0, 4)} has t ${fx(G.t, 1)}; the best of ${G.n_tried} useless strategies would show t ${fx(G.t0, 2)} (Φ⁻¹(1 − 1/${G.n_tried})), so the gate is ${pct(G.value, 0, false)} and the book holds ${dxX(N.exposure)} against the engine's ${dxX(N.engine_exposure)}. The gate rises toward 1 only as the record becomes conclusive; it cannot be tuned.`;
      const OV = O.overlay;
      if (OV && $("#dx-ov")) {
        const rows = OV.factors.map((f) => { const r = OV.rows[`hold:${f}`] || OV.rows[`hold:${f.toFixed(1)}`] || OV.rows[`hold:${f.toFixed(2)}`]; return r ? [fx(f, 2) + (f === OV.adopted ? " · adopted" : ""), fx(r.perf.sharpe, 2), pct(r.perf.cagr, 1), pct(r.perf.maxdd, 0),
          `${fx(r.sharpe_vs_hold.lo, 2)} to ${fx(r.sharpe_vs_hold.hi, 2)}`, `${pct(r.maxdd_vs_hold.lo, 0)} to ${pct(r.maxdd_vs_hold.hi, 0)}`, fx(r.utility_t, 2)] : null; }).filter(Boolean);
        fillTable($("#dx-ov"), ["Factor", "Sharpe", "Real growth", "Worst drawdown", "Sharpe gain over holding, 90% range", "Drawdown shallower than holding, 90% range", "Utility t vs holding"], rows, 1);
        $("#dx-ov-note").textContent = `Rule: ${OV.rule}. Factor 1.00 is holding; 0.00 is the classic trend rule (out of stocks below the average). Adopted: ${OV.adopted_reason}. Today the trend is ${OV.trend_on_now ? "on, so the overlay is armed and the book holds the gated call" : "off, so the gated call is scaled by " + fx(OV.adopted, 2)}.`;
      }
      const ol = $("#dx-find");
      O.findings.forEach((f) => ol.append(h("li", null, f)));
    }
    dxCharts();
  }
  function dxCharts() {
    const O = DX19, N = O.now, R = N.regime;
    const yr = (arr) => arr.map(dxYear);
    const rh = R.history, dts = yr(rh.dates);
    // the points are quarterly; a two-year average makes 155 years of regime odds readable
    const avg = (a, n = 8) => a.map((_, i) => { const w = a.slice(Math.max(0, i - n + 1), i + 1); return w.reduce((x, y) => x + y, 0) / w.length; });
    const sw = avg(rh.p_worst), fw = avg(rh.filtered);
    xyChart($("#dx-reg"), { series: [{ name: "Stressed regime, smoothed", pts: dts.map((x, i) => [x, sw[i]]), color: "var(--s2)", width: 1.6, area: true },
      { name: "Stressed regime, filtered (as known then)", pts: dts.map((x, i) => [x, fw[i]]), color: "var(--s1)", width: 1.4 }],
    height: 230, yDomain: [0, 1], yfmt: (v) => pct(v, 0, false), xfmt: (v) => String(Math.floor(v)), xticks: dxTicks(dts[0], dts[dts.length - 1], 25), label: "Probability of the stressed regime, 1871 to now, two-year average" });
    legendLines($("#dx-reg-leg"), [["var(--s2)", "Smoothed (uses the whole history)"], ["var(--s1)", "Filtered (only data up to each month)"]]);
    const ch = N.changepoint.history, cd = yr(ch.dates);
    xyChart($("#dx-cp"), { series: [{ name: "New regime in the last 6 months", pts: cd.map((x, i) => [x, ch.recent[i]]), color: "var(--s4)", width: 1.2, area: true }],
      hlines: [{ y: 0.5, color: "var(--muted)", label: "alarm" }],
      height: 170, yDomain: [0, 1], yfmt: (v) => pct(v, 0, false), xfmt: (v) => String(Math.floor(v)), xticks: dxTicks(cd[0], cd[cd.length - 1], 25), label: "Changepoint probability" });
    const C = O.curve, xd = yr(C.dates);
    const l10 = (a) => a.map((v) => v / Math.LN10);                     // log growth on a base-10 scale: 1x, 10x, 100x
    xyChart($("#dx-curve"), { series: [{ name: "Engine", pts: xd.map((x, i) => [x, l10(C.engine)[i]]), color: "var(--s1)", width: 2.2 }, { name: "Engine, gated", pts: xd.map((x, i) => [x, l10(C.gated)[i]]), color: "var(--s3)", width: 2 },
      { name: "Hold 1x", pts: xd.map((x, i) => [x, l10(C.hold)[i]]), color: "var(--muted)", width: 1.6 }, { name: "Trend rule", pts: xd.map((x, i) => [x, l10(C.trend)[i]]), color: "var(--s2)", width: 1.4 }],
    height: 260, yTicks: 4, yfmt: (v) => { const m = Math.pow(10, v); return (m >= 10 ? Math.round(m).toLocaleString("en-US") : fx(m, 1)) + "x"; }, xfmt: (v) => String(Math.floor(v)), xticks: dxTicks(xd[0], xd[xd.length - 1], 10), label: "Growth of one real dollar since " + O.start.slice(0, 4) });
    legendLines($("#dx-curve-leg"), [["var(--s1)", "The engine"], ["var(--s3)", "Gated by its own evidence"], ["var(--muted)", "Hold 1x"], ["var(--s2)", "10-month trend rule"]]);
    const X = O.exposure_hist;
    // the optimum flips month to month; a two-year average shows where it leaned, the gated line what reached the book
    const ma = (a, n = 4) => a.map((_, i) => { const w = a.slice(Math.max(0, i - n + 1), i + 1); return w.reduce((p, q) => p + q, 0) / w.length; });
    xyChart($("#dx-exp"), { series: [{ name: "Engine's optimum, two-year average", pts: xd.map((x, i) => [x, ma(X.x)[i]]), color: "var(--s1)", width: 1.6 },
      { name: "After the gate", pts: xd.map((x, i) => [x, X.gated[i]]), color: "var(--s3)", width: 2.2, area: true }], hlines: [{ y: 1, color: "var(--muted)" }],
      height: 170, yDomain: [0, 1.5], yfmt: (v) => fx(v, 1) + "x", xfmt: (v) => String(Math.floor(v)), xticks: dxTicks(xd[0], xd[xd.length - 1], 10), label: "Exposure through history" });
    const FL = N.flip.curve;
    xyChart($("#dx-flipc"), { series: [{ name: "Engine's optimum", pts: FL.r12.map((r, i) => [r, FL.x[i]]), color: "var(--s1)", width: 2.2, dots: true }],
      height: 210, yDomain: [0, 1.5], yfmt: (v) => fx(v, 1) + "x", xfmt: (v) => "12-month forecast " + pct(v, 0), xticks: [-0.3, -0.15, 0, 0.15, 0.3].map((v) => [v, pct(v, 0)]),
      vmarks: [{ x: N.forecasts.stacked, label: "today" }], label: "Optimum against the 12-month forecast" });
    if (N.flip.stress_curve) {
      const SC = N.flip.stress_curve;
      xyChart($("#dx-stressc"), { series: [{ name: "Engine's optimum", pts: SC.p.map((p, i) => [p, SC.x[i]]), color: "var(--s2)", width: 2.2, dots: true }],
        height: 210, yDomain: [0, 1.5], yfmt: (v) => fx(v, 1) + "x", xfmt: (v) => "stressed odds " + pct(v, 0, false), xticks: [0, 0.25, 0.5, 0.75, 1].map((v) => [v, pct(v, 0, false)]),
        vmarks: [{ x: R.next[R.worst], label: "today" }], label: "Optimum against the stressed regime's odds" });
    }
    const D = N.distribution;
    barsH($("#dx-dist"), D.hist.map((n, i) => ({ label: fx(i * 0.1, 1) + "x", v: n, lbl: pct(n / D.hist.reduce((a, b) => a + b, 0), 0, false), color: "var(--s1)",
      tip: () => [[String(n), `draws whose optimum is near ${fx(i * 0.1, 1)}x`]] })).filter((r) => r.v > 0), { fmt: (v) => String(Math.round(v)) });
    const MW = O.model_weights_hist, md = yr(MW.dates);
    xyChart($("#dx-mwh"), { series: Object.keys(N.models.names).map((k, j) => ({ name: N.models.names[k], pts: md.map((x, i) => [x, MW[k][i]]), color: ["var(--s1)", "var(--s4)", "var(--muted)", "var(--s3)"][j], width: 1.8 })),
      height: 190, yDomain: [0, 1], yfmt: (v) => pct(v, 0, false), xfmt: (v) => String(Math.floor(v)), xticks: dxTicks(md[0], md[md.length - 1], 10), label: "Model-averaging weights through history" });
    legendLines($("#dx-mwh-leg"), Object.keys(N.models.names).map((k, j) => [["var(--s1)", "var(--s4)", "var(--muted)", "var(--s3)"][j], N.models.names[k]]));
    const K0 = O.kalman, k0 = K0.dates.findIndex((d) => Number(d.slice(0, 4)) >= 1891);   // the filter's first 20 years are its burn-in
    const K = { beta: K0.beta.slice(k0), se: K0.se.slice(k0), now: K0.now, now_se: K0.now_se, as_of: K0.as_of }, kd = yr(K0.dates.slice(k0));
    xyChart($("#dx-kal"), { series: [{ name: "Stock return per point of 10-year yield", pts: kd.map((x, i) => [x, K.beta[i]]), color: "var(--s1)", width: 1.8 }],
      bands: [{ pts: kd.map((x, i) => [x, K.beta[i] - 1.645 * K.se[i], K.beta[i] + 1.645 * K.se[i]]), color: "var(--s1)" }],
      height: 220, zero: true, yfmt: (v) => pct(v, 0), xfmt: (v) => String(Math.floor(v)), xticks: dxTicks(kd[0], kd[kd.length - 1], 25), label: "Stock-bond beta, Kalman filtered" });
    $("#dx-kal-note").textContent = `Each point is the month's estimate using only data up to then: the real stock return that came with a one-point rise in the 10-year yield (to ${K.as_of}, where Shiller's long rate ends: ${pct(K.now, 1)} with a 90% band of ${pct(K.now - 1.645 * K.now_se, 1)} to ${pct(K.now + 1.645 * K.now_se, 1)}). Below zero, rising yields hurt stocks and bonds fail as a hedge; above zero, bonds hedge.`;
  }

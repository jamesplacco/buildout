  /* =====================================================================================
     landing.js (v0.23): the landing page as one screen. The call board (the engine's call in six numbers), how the
     engine thinks (six stages with today's values), the parameters strip (Theta, counted), under the hood (the
     codebase, counted) and the live counts in the fund block. Everything reads the shipped snapshots (DX19, THETA23,
     CODE_SNAP, ENGINES_SNAP, SNAP14.stats) so the landing page cannot disagree with the desks behind it.
     ===================================================================================== */
  const MCP_TOOLS = 41;          // buildout/mcp_server.py TOOLS (test_v23 checks this against the server)
  const TESTS_PASSING = 646;     // the shipped test count (the chip and the hood tile read it)
  const dxEngine = () => (typeof DX19 !== "undefined" && DX19 && DX19.now ? DX19 : null);
  const theta = () => (typeof THETA23 !== "undefined" && THETA23 && Array.isArray(THETA23.entries) ? THETA23 : null);
  const kcount = (n) => (!fin(n) ? "n/a" : n >= 1e6 ? fx(n / 1e6, 2) + "M" : n >= 1e4 ? fx(n / 1e3, 0) + "k" : n.toLocaleString());

  function regimeNow(R) {
    // the same naming as the decision desk: the worst-mean state is Stressed, the highest-mean Calm, the most volatile Turbulent
    const muMax = R.mu.indexOf(Math.max(...R.mu)), sdMax = R.sd.indexOf(Math.max(...R.sd));
    const name = (k) => (k === R.worst ? "Stressed" : k === muMax ? "Calm" : k === sdMax ? "Turbulent" : "Middle");
    const k = R.now.indexOf(Math.max(...R.now));
    return { k, name: name(k), p: R.now[k], pStressNext: R.next[R.worst] };
  }
  // the regime read that governs (the engine's K-state stocks model), its distance to the cut line, and what the other two models say
  function regimeWords(N, R, rg) {
    const line = N.flip && fin(N.flip.cut_if_stress_prob_above) ? N.flip.cut_if_stress_prob_above : null;
    let s = `Hidden Markov, ${R.K} states; stressed next month ${pct0(rg.pStressNext)}`;
    if (line != null) s += `, ${Math.abs(rg.pStressNext - line) < 0.005 ? "at" : rg.pStressNext < line ? `${fx((line - rg.pStressNext) * 100, 0)} points under` : `${fx((rg.pStressNext - line) * 100, 0)} points over`} the ${pct0(line)} cut line`;
    s += `; changepoint ${pct0(N.changepoint.recent)}.`;
    try {
      const P = typeof PF20 !== "undefined" && PF20 && PF20.now, L = typeof LB !== "undefined" && LB && LB.regimes;
      const others = [];
      if (P && Array.isArray(P.next) && fin(P.worst)) others.push(`${pct0(P.next[P.worst])} (Portfolio)`);
      if (L && Array.isArray(L.p_now) && fin(L.p_now[1])) others.push(`${pct0(L.p_now[1])} (Labs)`);
      if (others.length) s += ` Other models: ${others.join(", ")}. A jumpy read, so it enters only through the mixture and the gate.`;
    } catch (e) { /* the other models are optional here */ }
    return s;
  }
  function hedgeWords(N) {
    const c = N.hedge && N.hedge.choice;
    return c === "stocks" ? "no bond hedge" : c === "bonds" ? "a 30% Treasury hedge" : c === "cash" ? "a 30% cash sleeve" : "";
  }

  function renderHeadline(N) {
    const el = $("#desk-title");
    if (!el || !N) return;
    const ov = N.overlay, hw = hedgeWords(N);
    const none = !ov || !fin(ov.factor) || ov.factor >= 1;
    const tail = !ov ? "" : none ? "no trend overlay after it failed its walk-forward test" : (ov.trend_on ? `cut to ${xx(ov.exposure_if_off)} if the 10-month trend breaks` : `scaled by ${fx(ov.factor, 2)} while the trend is off`);
    const BC = typeof bookCall === "function" ? bookCall(N) : null;
    // v0.30: the call is about the book. The decision engine supplies the baseline; the book's own limits set the size.
    el.textContent = BC && BC.cut
      ? `Run the book at ${xx(BC.size)}${BC.keep != null ? `, or keep every name and short ${pct0(BC.keep)} of NAV in Nasdaq-100 futures` : ""}${hw ? "; " + hw : ""}.`
      : `Hold equity at ${xx(N.exposure)}${hw ? " with " + hw : ""}${tail ? "; " + tail : ""}.`;
    const eb = $("#t7-eyebrow");
    if (eb) eb.textContent = `The engine's call · model book · data to ${isoNice(latestDataDate())}`;
  }

  function renderCallBoard(N, O) {
    const box = $("#call-board");
    if (!box) return;
    box.replaceChildren();
    const I = inputs(), TD = tltNow(I), R = N.regime, rg = regimeNow(R), ov = N.overlay || {};
    const cell = (cls, k, v, n, href, label) => {
      const d = h("div", "cb " + cls);
      d.setAttribute("role", "listitem");
      d.append(h("span", "cb-k", k), h("span", "cb-v num", v), h("span", "cb-n", n));
      if (href) { const a = h("a", null, label + " →"); a.href = href; d.append(a); }
      return d;
    };
    box.append(
      (() => { const BC = typeof bookCall === "function" ? bookCall(N) : null;
        return BC ? cell(BC.cut ? "rule" : "model", "Book size", xx(BC.size), `The decision engine's baseline (${xx(N.exposure)}) cut to ${BC.bindingName}, measured on the nine names' own prices: at 1.00x the book breaks ${BC.breaches === 3 ? "all three" : `${BC.breaches} of its three`} limits.`, "#book", "Book risk")
          : cell("model", "Equity exposure", xx(N.exposure), `The gated call for the model book${N.capped ? ", capped by the risk budget" : ""}.`, "#decision", "Decision engine"); })(),
      cell("model", "Engine optimum", xx(N.engine_exposure), `Before the evidence gate; CRRA γ ${fx(O.gamma, 2)}, worst-month loss budget ${pct0(O.es_limit)}${N.engine_exposure >= 1.5 - 1e-9 ? "; the top of its 0 to 1.5x grid, so a bound, not an interior optimum" : ""}.`, "#dx-gate", "The gate"),
      cell("rule", "Evidence gate", pct0(N.gate.value), `Utility t ${fx(N.gate.t, 2)} since ${O.start.slice(0, 4)} against ${fx(N.gate.t0, 2)} needed after ${N.gate.n_tried} strategies tried.`, "#dx-gate", "Why so little"),
      cell("model", "Regime", `${rg.name} ${pct0(rg.p)}`, regimeWords(N, R, rg), "#dx-states", "The states"),
      cell(TD.on ? "on" : "off", "Bond hedge", TD.status !== "ok" ? "Unknown" : TD.on ? "On" : "Off", `${(() => { const B = typeof B30 === "function" ? B30() : null, P = B && B.hedges && B.hedges.policies; return P ? `On the book's own days a bond hedge cut its variance ${pct0(P.bond_when_it_hedges.variance_cut)} and an index short ${pct0(P.nasdaq_beta.variance_cut)}. ` : ""; })()}S&P 500 against the 10-year, 36 months of monthly returns: ${sgn2(I.corr.v)}; the selector's pick: ${N.hedge.name.toLowerCase()} (${pct0(N.hedge.p_best[Math.max(0, ["stocks", "bonds", "cash"].indexOf(N.hedge.choice))])} best).`, "#bonds", "Bonds"),
      (!fin(ov.factor) || ov.factor >= 1)
        ? cell("off", "Trend overlay", "None", `Tested, not adopted: on the full record a 0.50 scaling looked free, but re-chosen yearly on the record to date it cost expected utility. The 10-month trend is ${ov.trend_on ? "on" : "off"}; the rule stays a cross-check.`, "#dx-overlay", "The overlay study")
        : cell(ov.trend_on ? "rule" : "off", "Trend overlay", ov.trend_on ? `Armed · ${fx(ov.factor, 2)}` : `On · ${fx(ov.factor, 2)}`,
          ov.trend_on ? `Trend on. Below the 10-month average the exposure is scaled by ${fx(ov.factor, 2)}, to ${xx(ov.exposure_if_off)}.` : `Trend off: exposure scaled by ${fx(ov.factor, 2)}.`, "#dx-overlay", "The overlay study"));
  }

  function renderImplementation(N, O) {
    // per $100m of NAV: the loss budget in dollars and what the overlay cut would mean in contracts (Nasdaq-100 futures, $20 a point)
    const el = $("#t7-impl");
    if (!el) return;
    el.replaceChildren();
    const lv = (typeof LEVELS !== "undefined" ? LEVELS : []).find((x) => x.label === "Nasdaq-100");
    const ndx = lv ? Number(String(lv.value).replace(/,/g, "")) : NaN, ov = N.overlay || {};
    const nav = 100, BC = typeof bookCall === "function" ? bookCall(N) : null;
    const es = BC ? BC.B.tail.es95.governing * BC.size * nav : N.es_1x * N.exposure * nav;
    const cut = ov.trend_on && fin(ov.factor) && ov.factor < 1 && fin(ov.exposure_if_off) ? (N.exposure - ov.exposure_if_off) * nav : 0;
    const contracts = fin(ndx) && cut > 0 ? Math.round(cut * 1e6 / (20 * ndx)) : null;
    el.append(h("strong", null, "Per $100m of NAV. "), document.createTextNode(BC
      ? `The worst month in twenty at ${xx(BC.size)} costs about $${fx(es, 1)}m (the book's expected shortfall on its own prices; the budget is $${fx(O.es_limit * nav, 0)}m). Getting there from 1.00x means selling $${fx((1 - BC.size) * nav, 0)}m of the names pro rata${BC.keep != null && fin(ndx) ? `, or keeping them and selling about ${Math.round(BC.keep * nav * 1e6 / (20 * ndx)).toLocaleString()} Nasdaq-100 futures ($${fx(BC.keep * nav, 0)}m at ${lv.value})` : ""}. `
      : `The worst month in twenty at ${xx(N.exposure)} costs about $${fx(es, 1)}m (expected shortfall, the engine's budget is $${fx(O.es_limit * nav, 0)}m). `), evTag("est"));
    if (cut > 0) el.append(document.createTextNode(` If the 10-month trend breaks, the overlay cuts $${fx(cut, 0)}m of equity exposure: about ${contracts ? contracts.toLocaleString() : "n/a"} Nasdaq-100 futures at ${lv ? lv.value : "n/a"}${lv && lv.note ? ` (${lv.note.split(";")[0].replace(/\.$/, "")})` : ""}, or the same notional in the holdings, at the engine's assumed 2 bp a side plus impact. `), evTag("asm"));
    el.append(document.createTextNode(" Scale to the fund's NAV; nothing here is an order."));
  }

  // Limits and breaches: which loss limit governs the size, its horizon, today's reading and whether it is met (audit v0.24, blocker 2).
  // v0.25: the call, derived step by step with today's numbers (shown by default; the Σ button hides every formula)
  function renderCallMath(N, O) {
    const el = $("#t7-math");
    if (!el) return;
    const G = N.gate, w = N.models.weights, nm = N.models.names, F = N.forecasts || {};
    const wTxt = Object.keys(w).sort((a, b) => w[b] - w[a]).map((k) => `${fx(w[k], 3)} ${nm[k] ? nm[k].toLowerCase() : k}`).join(" + ");
    const cap = O.es_limit / N.es_1x;
    const phi = (t) => 0.5 * (1 + erfApprox(t / Math.SQRT2));
    const raw = 2 * phi(G.t - G.t0) - 1;
    el.innerHTML = `<span class="mlabel">The call, derived with today's numbers</span>`
      + `<p><b>1. Belief.</b> Next month's real return <var>R</var> ~ &Sigma;<sub>m</sub> <var>w</var><sub>m</sub> &Sigma;<sub>s</sub> &pi;<sub>m,s</sub> N(&mu;<sub>m,s</sub>, &sigma;<sub>m,s</sub><sup>2</sup>), model weights <var>w</var><sub>m</sub> &prop; exp(&Sigma;<sub>&tau;</sub> 0.98<sup>age</sup> log <var>p</var><sub>m</sub>(<var>r</var><sub>&tau;</sub>)) = ${wTxt}.${fin(F.stacked) ? ` Forecast tilt from the stacked 12-month forecast: ${sPct(F.stacked, 1)} a year.` : ""}</p>`
      + `<p><b>2. Optimum.</b> <var>x</var>* = argmax<sub><var>x</var></sub> E[<var>u</var>(1 + <var>x R</var> &minus; <var>b</var>&middot;max(<var>x</var> &minus; 1, 0))], <var>u</var>(<var>v</var>) = (<var>v</var><sup>1&minus;&gamma;</sup> &minus; 1)/(1 &minus; &gamma;), &gamma; = ${fx(O.gamma, 2)}, subject to <var>x</var>&middot;ES<sub>5%</sub>(<var>R</var>) &le; ${pct0(O.es_limit)}: ES<sub>5%</sub> = ${pctPlain(N.es_1x, 2)}, so <var>x</var> &le; ${fx(O.es_limit, 2)} &divide; ${fx(N.es_1x, 4)} = ${fx(cap, 2)}; on the grid of exposures from 0 to 1.5x (the gross cap), <var>x</var>* = ${xx(N.engine_exposure)}.</p>`
      + `<p><b>3. Gate.</b> <var>t</var><sub>0</sub> = &Phi;<sup>&minus;1</sup>(1 &minus; 1/<var>n</var>) = &Phi;<sup>&minus;1</sup>(1 &minus; 1/${G.n_tried}) = ${fx(G.t0, 2)}; <var>g</var> = max(0, 2&Phi;(<var>t</var> &minus; <var>t</var><sub>0</sub>) &minus; 1) = max(0, 2&Phi;(${fx(G.t, 2)} &minus; ${fx(G.t0, 2)}) &minus; 1) = max(0, ${fx(raw, 2)}) = ${fx(G.value, 2)}.</p>`
      + `<p><b>4. Baseline.</b> <var>x</var> = 1 + <var>g</var>(<var>x</var>* &minus; 1) = 1 + ${fx(G.value, 2)} &times; (${fx(N.engine_exposure, 2)} &minus; 1) = <b>${xx(N.exposure)}</b>; its worst-month cost: ${fx(N.exposure, 2)} &times; ${pctPlain(N.es_1x, 2)} = ${pctPlain(N.exposure * N.es_1x, 2)} of NAV on the index against the ${pct0(O.es_limit)} budget; the index is not the book, so step 5 measures the book.</p>`
      + (() => { const BC = typeof bookCall === "function" ? bookCall(N) : null; if (!BC) return ""; const B = BC.B, S = B.sizes;
          return `<p><b>5. The book's limits.</b> On the nine names' own daily prices since ${B.from.slice(0, 4)}: ES<sub>5%</sub>(book) = ${pctPlain(B.tail.es95.governing, 1)} (most cautious of three methods), so <var>x</var> &le; ${fx(O.es_limit, 2)} &divide; ${fx(B.tail.es95.governing, 4)} = ${fx(S.es_budget, 2)}; &sigma;(book) = ${pctPlain(B.risk.vol, 1)}, so <var>x</var> &le; 0.20 &divide; ${fx(B.risk.vol, 3)} = ${fx(S.vol_target, 2)}; the 95th-percentile one-year drawdown stays within 25% up to <var>x</var> = ${fx(S.drawdown_cap, 2)}. Size = min(${xx(N.exposure)}, ${fx(S.es_budget, 2)}, ${fx(S.vol_target, 2)}, ${fx(S.drawdown_cap, 2)}, ${fx(S.gross_cap, 2)}) = <b>${xx(BC.size)}</b>.</p>`; })()
      + `<p><b>6. Hedge.</b> Selector: choose argmax<sub><var>h</var></sub> P(<var>h</var> best | context), posterior from discounted outcomes in the same context (${N.hedge.context}): ${N.hedge.names.map((n, i) => `${fx(N.hedge.p_best[i], 3)} ${n.toLowerCase()}`).join(", ")} &rArr; ${N.hedge.name.toLowerCase()}.</p>`;
  }
  // erf by Abramowitz and Stegun 7.1.26 (error under 1.5e-7), for the gate's normal CDF shown in the math
  function erfApprox(x) {
    const s = Math.sign(x), a = Math.abs(x), t = 1 / (1 + 0.3275911 * a);
    const y = 1 - ((((1.061405429 * t - 1.453152027) * t + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-a * a);
    return s * y;
  }

  function renderLimits(N, O) {
    const el = $("#t7-limits");
    if (!el) return;
    el.replaceChildren();
    const rows = [];
    const esNow = N.es_1x * N.exposure, BC = typeof bookCall === "function" ? bookCall(N) : null;
    if (BC) {                                // v0.30: the book's own limits, measured on the names' prices, govern the size
      const B = BC.B, S = B.sizes, x = BC.size, st = (k) => (S[k] >= 1 - 1e-9 ? "within" : k === BC.binding ? `breached at 1.00x; binds, sets ${xx(x)}` : `breached at 1.00x; met at ${xx(x)}`);
      rows.push(["Book expected shortfall", "a hard limit on the book", "one month, mean of the worst 5%, most cautious of three methods", `${pctPlain(B.tail.es95.governing, 1)} at 1.00x, ${pctPlain(B.tail.es95.governing * x, 1)} at ${xx(x)}, against ${pctPlain(O.es_limit, 0)}`, st("es_budget"), "#book"]);
      rows.push(["Book volatility", "a hard limit on the book", "one year, factor model on the names' prices", `${pctPlain(B.risk.vol, 1)} at 1.00x, ${pctPlain(B.risk.vol * x, 1)} at ${xx(x)}, against ${pctPlain(B.limits.vol_target, 0)}`, st("vol_target"), "#book"]);
      rows.push(["Book one-year drawdown", "a hard limit on the book", "one year, 95% confidence", `${pctPlain(B.at_full.drawdown95, 0)} at 1.00x; ${xx(S.drawdown_cap)} keeps it at ${pctPlain(B.limits.max_drawdown, 0)}`, st("drawdown_cap"), "#book"]);
      rows.push(["Index expected shortfall", "information: the S&P 500 the decision engine models", "one month, mean of the worst 5%", `${pctPlain(esNow, 1)} at ${xx(N.exposure)} against ${pctPlain(O.es_limit, 0)}`, "reported", "#decision"]);
    } else {
      rows.push(["Expected shortfall budget", "governs the size", "one month, mean of the worst 5%", `${pctPlain(esNow, 1)} at ${xx(N.exposure)} against ${pctPlain(O.es_limit, 0)}`, esNow <= O.es_limit ? "within" : "breached", "#decision"]);
    }
    try {
      const R = typeof runReasoner === "function" ? (typeof RZ_LAST !== "undefined" && RZ_LAST) || runReasoner(false) : null, keep = R && R.alts && R.alts.keep;
      if (keep && fin(keep.worst)) rows.push(["Scenario loss limit", "the Solve desk, a stress test", "three months, worst of seven scenarios", `${sPct(keep.worst, 1)} for the book as it stands against a ${RZS.loss}% limit`, keep.feasible ? "within" : "breached on that desk's scenarios", "#solve"]);
    } catch (e) { /* the solver is optional here */ }
    try {                                   // v0.25: the actuarial cross-checks (crossfield.py, walked forward since 1940)
      const C = typeof SNAP25 !== "undefined" && SNAP25 && SNAP25.crossfield, tm = C && C.tail && C.tail.methods, ru = C && C.ruin && C.ruin["1.0"];
      if (tm && tm.pot && tm.pot["0.05"]) rows.push(["Tail cross-check (generalized Pareto)", "an actuary's estimate of the same 5% ES", "one month, peaks over threshold since 1871", `${pctPlain(tm.pot["0.05"].es_last, 1)} at 1x, allowing up to ${xx(tm.pot["0.05"].max_exposure_now)} within the 12% budget`, tm.pot["0.05"].es_last * N.exposure <= O.es_limit ? "within" : "breached by the cross-check", "#crossfield"]);
      if (ru) rows.push(["Ruin (a 50% fall from a peak)", "information: no limit is set on it", "ten years, block bootstrap of every month since 1871", `${pctPlain(ru.bootstrap_dd50_10y.p, 1)} at 1x; ${pctPlain(C.ruin["1.5"].bootstrap_dd50_10y.p, 1)} at the 1.5x cap`, "reported", "#crossfield"]);
    } catch (e) { /* the v0.25 snapshot is optional here */ }
    const t = h("table", "limits");
    const thead = h("thead"), hr = h("tr");
    ["Limit", "Role", "Horizon", "Reading today", "Status"].forEach((x) => { const th = h("th", null, x); th.scope = "col"; hr.append(th); });
    thead.append(hr); t.append(thead);
    const tb = h("tbody");
    rows.forEach(([name, role, hz, read, st, href]) => {
      const tr = h("tr", /breached/.test(st) ? "breach" : null);
      const a = h("a", null, name); a.href = href;
      tr.append(h("td", null, a), h("td", null, role), h("td", null, hz), h("td", "num", read), h("td", null, h("span", "lim-" + (/breached/.test(st) ? "no" : "ok"), st)));
      tb.append(tr);
    });
    t.append(tb);
    const cap = h("p", "t7-sizing");
    if (BC) {
      cap.append(h("strong", null, "Limits and breaches. "), document.createTextNode(`Measured on the nine names' own daily prices since ${BC.B.from.slice(0, 4)} (the Book risk desk), the book at 1.00x breaks ${BC.breaches === 3 ? "all three" : BC.breaches} of its limits; the tightest, ${BC.bindingName}, allows ${xx(BC.size)}, and that is the call. The decision engine finds no evidence for any size other than holding (its gate has stayed shut in every month on record), so it supplies the 1.00x baseline and the limits cut it. The index rows describe the S&P 500 the decision engine models, not the book; the stress and tail rows below are cross-checks. When the book run updates, the call follows the binding limit.`));
    } else {
      cap.append(h("strong", null, "Limits and breaches. "), document.createTextNode("The book run is not in this build, so the size is the index call; the book's own limits are not measured."));
    }
    const wrap = h("div", "tablewrap"); wrap.append(t);
    el.append(cap, wrap);
  }

  function renderFlow(N, O) {
    const ol = $("#flow");
    if (!ol) return;
    ol.replaceChildren();
    ol.className = "eflow";
    const rg = regimeNow(N.regime), F = N.forecasts, w = N.models.weights, ov = N.overlay || {};
    const src = (typeof LIVE !== "undefined" && LIVE.sources && fin(LIVE.sources.count)) ? LIVE.sources.count : 99;
    const stage = (k, v, t, href, label) => {
      const li = h("li");
      li.append(h("span", "ef-k", k), h("span", "ef-v num", v), h("span", "ef-t", t));
      const a = h("a", null, label + " →"); a.href = href; li.append(a);
      return li;
    };
    const topW = Object.entries(w).sort((a, b) => b[1] - a[1])[0];
    ol.append(
      stage("Data", `1871 to ${O.end.slice(0, 4)}`, `Shiller, FRED, SEC, Treasury: ${src} sources, every figure dated and used with a ${O.lag}-month lag; decisions judged from ${O.start.slice(0, 4)}, ${O.months.toLocaleString()} months.`, "#engines", "Engine room"),
      stage("Regimes", `${rg.name} ${pct0(rg.p)}`, `Four models averaged by discounted predictive score; ${pct0(topW[1])} of the weight sits on ${N.models.names[topW[0]].replace(/^Hidden/, "hidden")}.`, "#dx-states", "The models"),
      stage("Forecasts", `${sPct(F.stacked, 1)} real, 12 months`, `Four forecasters stacked; the restricted combination carries ${pct0(F.weights.combo)} of the weight; the network ensemble's predictive sd ${pct0(F.nn_sd)}.`, "#ml", "Machine-learning lab"),
      stage("Allocation", xx(N.engine_exposure), `CRRA utility on a 31-size grid inside a ${pct0(O.es_limit)} worst-month budget; expected shortfall at 1x ${pct0(N.es_1x)}.`, "#solve", "Sizing math"),
      stage("Gate", `${pct0(N.gate.value)} → ${xx(N.exposure)}`, `The record (t ${fx(N.gate.t, 2)}) against the best of ${N.gate.n_tried} useless strategies (t ${fx(N.gate.t0, 2)}); the baseline holds${(() => { const BC = typeof bookCall === "function" ? bookCall(N) : null; return BC && BC.cut ? `, and the book's own ${BC.bindingName.replace(/^the /, "")} cuts it to ${xx(BC.size)}` : ""; })()}.`, "#dx-gate", "The evidence gate"),
      stage("Hedge and overlay", N.hedge.name, `Selector context: ${N.hedge.context}. ${(!fin(ov.factor) || ov.factor >= 1) ? "Trend overlay tested and not adopted: it failed its walk-forward test." : `Overlay ${ov.trend_on ? "armed" : "on"} at ${fx(ov.factor, 2)}: ${ov.trend_on ? `${xx(ov.exposure_if_off)} if the trend breaks` : "in force"}.`}`, "#portfolio", "Portfolio engine"));
  }

  function renderThetaStrip() {
    const T = theta(), box = $("#theta"), lay = $("#theta-layers");
    if (!T || !box) return;
    box.replaceChildren();
    const kpi = (v, k, s) => { const d = h("div", "at-kpi"); d.append(h("b", null, v), h("span", null, k), h("small", null, s)); return d; };
    const big = T.entries.reduce((a, e) => (e.count > a.count ? e : a), T.entries[0]);
    box.append(
      kpi(String(T.entries.length), "Learned objects", `${T.layers.length} layers, from regimes to the knowledge graph`),
      kpi(T.total.toLocaleString(), "Numbers in all", `${kcount(big.count)} in the ${big.name.toLowerCase()}`),
      kpi(T.core.toLocaleString(), "Decision core", "regimes, forecasters, allocation, portfolio, learner"),
      kpi(String(T.set_by_hand.length), "Set by hand", "constants with their reasons, listed apart"),
      kpi(String(Object.keys(T.feeds).length), "Desks fed directly", "the rest read figures derived from them"));
    if (lay) {
      lay.replaceChildren();
      T.layers.forEach((L) => {
        const b = T.by_layer[L.id] || { count: 0, objects: 0 };
        const a = h("a", null, L.name + " ");
        a.append(h("b", null, kcount(b.count)));
        a.href = "#pm-layer-" + L.id;
        a.title = `${b.objects} object${b.objects === 1 ? "" : "s"}, ${b.count.toLocaleString()} numbers`;
        lay.append(a);
      });
    }
  }

  function renderHood() {
    const box = $("#hood");
    if (!box) return;
    box.replaceChildren();
    const kpi = (v, k, s, href) => {
      const d = h("div", "at-kpi");
      d.append(h("b", null, v), h("span", null, k), h("small", null, s));
      if (href) { d.style.cursor = "pointer"; d.addEventListener("click", () => { location.hash = href; }); }
      return d;
    };
    const code = typeof CODE_SNAP !== "undefined" && Array.isArray(CODE_SNAP) ? CODE_SNAP : [];
    const lines = code.reduce((a, f) => a + (f.lines || 0), 0);
    const engines = typeof ENGINES_SNAP !== "undefined" && Array.isArray(ENGINES_SNAP) ? ENGINES_SNAP.length : 0;
    const st = typeof SNAP14 !== "undefined" && SNAP14 && SNAP14.stats ? SNAP14.stats : null;
    box.append(
      kpi(String(code.length), "Source files on the source desk", `${kcount(lines)} lines of the engine's modules and scripts, each readable here; the repository also carries 37 test files`, "code"),
      kpi(String(TESTS_PASSING), "Tests passing", "parity between the engine and the page, every release", "code"),
      kpi(String(engines), "Engines", "pure functions of dated files, registered for the daily run; none has run live in this snapshot", "engines"),
      kpi(String(MCP_TOOLS), "MCP tools", "the engine as a server; none places an order", "cd-flow-t"),
      kpi(st ? st.nodes.toLocaleString() : "n/a", "Knowledge nodes", st ? `${st.edges.toLocaleString()} typed links in one graph` : "", "mind"),
      kpi(String(typeof VIEWS !== "undefined" ? VIEWS.length : 0), "Desks", "each answering one question, built with agents", "agents"));
    const ft = $("#fund-tools");
    if (ft) ft.textContent = String(MCP_TOOLS);
    const ct = $("#chip-tests");
    if (ct) ct.textContent = `Tests ${TESTS_PASSING} of ${TESTS_PASSING}`;
  }

  function renderLanding() {
    const O = dxEngine();
    if (O) {
      guard("Headline", () => renderHeadline(O.now));
      guard("Call board", () => renderCallBoard(O.now, O), $("#call-board"));
      guard("How the engine thinks", () => renderFlow(O.now, O), $("#flow"));
      guard("Implementation", () => renderImplementation(O.now, O), $("#t7-impl"));
      guard("Limits", () => renderLimits(O.now, O), $("#t7-limits"));
      guard("The call, derived", () => renderCallMath(O.now, O), $("#t7-math"));
    }
    guard("The parameters", renderThetaStrip, $("#theta"));
    guard("Under the hood", renderHood, $("#hood"));
  }

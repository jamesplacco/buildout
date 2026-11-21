  /* =====================================================================================
     explain.js (v0.24): the "How it works" desk. The plain-English account of the engine with its live numbers, and
     a replay of any half-year since 1940 from the decision engine's own shipped histories (DX19.exposure_hist,
     gate_hist, curve, model_weights_hist, forecast_weights_hist, now.regime.history). Nothing is recomputed with
     hindsight: every value shown for a past date is what the walk-forward engine produced then.
     ===================================================================================== */
  const EX = { i: null };
  const exYear = (d) => Number(d.slice(0, 4)) + (Number(d.slice(5, 7)) - 1) / 12;
  function exLatest(dates, vals, d) {
    // the last value at or before date d (the weights are kept yearly, the regime odds quarterly)
    let j = -1;
    for (let k = 0; k < dates.length; k++) { if (dates[k] <= d) j = k; else break; }
    return j < 0 ? null : vals[j];
  }
  function exTop(obj, names) {
    const e = Object.entries(obj).filter(([k]) => !/^dates$/.test(k)).sort((a, b) => b[1] - a[1])[0];
    return e ? { name: names[e[0]] || e[0], w: e[1] } : null;
  }

  function renderExplained() {
    const O = typeof DX19 !== "undefined" && DX19 && DX19.now ? DX19 : null;
    const box = $("#hw-read");
    if (!box) return;
    if (!O) { box.replaceChildren(h("p", "empty", "The decision engine's snapshot is missing from this build.")); return; }
    const N = O.now;
    // the live numbers in the paragraph
    const set = (id, v) => { const el = $(id); if (el) el.textContent = v; };
    set("#hw-es", pct0(O.es_limit));
    set("#hw-opt", xx(N.engine_exposure));
    set("#hw-gate", pct0(N.gate.value));
    set("#hw-x", xx(N.exposure));
    set("#hw-f", N.overlay && fin(N.overlay.factor) && N.overlay.factor < 1 ? `adopted at ${fx(N.overlay.factor, 2)}` : "tested and not adopted, because it failed the same walk-forward test the engine applies to itself");
    const H = O.exposure_hist, G = O.gate_hist, C = O.curve;
    const sl = $("#hw-when");
    sl.max = String(H.dates.length - 1);
    if (EX.i == null) EX.i = H.dates.length - 1;
    sl.value = String(EX.i);
    const draw = () => {
      const i = EX.i, d = H.dates[i];
      $("#hw-when-out").textContent = d;
      sl.setAttribute("aria-valuetext", d);
      const reg = N.regime.history, pStress = exLatest(reg.dates, reg.p_worst, d);
      const mw = O.model_weights_hist, fw = O.forecast_weights_hist;
      const mTop = exTop({ hmm: exLatest(mw.dates, mw.hmm, d), bocpd: exLatest(mw.dates, mw.bocpd, d), uncond: exLatest(mw.dates, mw.uncond, d), geo: exLatest(mw.dates, mw.geo, d) }, N.models.names);
      const fTop = exTop({ mean: exLatest(fw.dates, fw.mean, d), ridge: exLatest(fw.dates, fw.ridge, d), combo: exLatest(fw.dates, fw.combo, d), nn: exLatest(fw.dates, fw.nn, d) }, N.forecasts.names);
      const next = Math.min(i + 10, C.dates.length - 1);          // five years on, where the record allows
      const fwd = (k) => (next > i && fin(C[k][i]) && fin(C[k][next]) ? (1 + C[k][next]) / (1 + C[k][i]) - 1 : null);
      const cell = (k, v, n) => { const el = h("div", "cb model"); el.setAttribute("role", "listitem"); el.append(h("span", "cb-k", k), h("span", "cb-v num", v), h("span", "cb-n", n)); return el; };
      box.replaceChildren(
        cell("Stressed regime, odds", pStress == null ? "n/a" : pct0(pStress), "filtered odds for that month from the data then; Today shows next month's odds, which add the chance of a switch"),
        cell("Model with most weight", mTop ? `${pct0(mTop.w)}` : "n/a", mTop ? mTop.name : "weights kept yearly"),
        cell("Forecaster with most weight", fTop ? `${pct0(fTop.w)}` : "n/a", fTop ? fTop.name : "weights kept yearly"),
        cell("Engine optimum", xx(H.x[i]), "the exposure with the best expected outcome inside the budget"),
        cell("Gate, then the book", `${pct0(G.g[i])} → ${xx(H.gated[i])}`, "how much of the move toward the optimum reached the book"),
        cell("Next five years, gated vs holding", (fwd("gated") == null || fwd("hold") == null) ? "n/a" : `${sPct(fwd("gated"), 0)} vs ${sPct(fwd("hold"), 0)}`, next > i ? `real growth to ${C.dates[next]}` : "the record ends here"));
      const g1 = (k) => (fin(C[k][i]) ? "$" + fx(1 + C[k][i], 2) : "n/a");
      const MON = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
      const nice = (dd) => `${MON[Number(dd.slice(5, 7)) - 1]} ${dd.slice(0, 4)}`;
      $("#hw-story").textContent = `In ${nice(d)} the engine's optimum was ${xx(H.x[i])} and the gate ${pct0(G.g[i])}, so the book held ${xx(H.gated[i])}. One real dollar invested in January 1940 had grown to ${g1("gated")} by then (holding: ${g1("hold")}; the trend rule: ${g1("trend")}; the engine ungated: ${g1("engine")}).`;
      const pts = (k) => H.dates.map((dd, j) => [exYear(dd), H[k][j]]);
      const cps = (k) => C.dates.map((dd, j) => [exYear(dd), 1 + C[k][j]]);
      const xt = [1940, 1960, 1980, 2000, 2020].map((y) => [y, String(y)]);
      xyChart($("#hw-exp"), { series: [{ name: "Engine", color: "var(--s2)", pts: pts("x") }, { name: "Gated (the book)", color: "var(--s1)", pts: pts("gated") }], yfmt: (v) => fx(v, 1) + "x", xticks: xt, xfmt: (v) => String(Math.round(v)),
        vmarks: [{ x: exYear(d), label: d }], zero: true, height: 220, label: "Exposure each half-year: the engine's optimum and what the book held after the gate" });
      xyChart($("#hw-growth"), { series: [{ name: "Gated (the book)", color: "var(--s1)", pts: cps("gated") }, { name: "Holding", color: "var(--muted)", pts: cps("hold") }, { name: "Trend rule", color: "var(--s3)", pts: cps("trend") }, { name: "Engine, ungated", color: "var(--s2)", pts: cps("engine") }],
        yfmt: (v) => "$" + fx(v, 0), xticks: xt, xfmt: (v) => String(Math.round(v)), vmarks: [{ x: exYear(d), label: d }], height: 220, label: "Growth of one real dollar since 1940 under four policies, costs included" });
    };
    if (!sl.dataset.wired) {
      sl.dataset.wired = "1";
      sl.addEventListener("input", () => { EX.i = Number(sl.value); draw(); });
    }
    draw();
  }

  /* v0.49: THE BRIEF'S METHOD PAGE. The desk above explains the forecasting model, which today has no say in the
     call (its gate is at 0%). A reader with ten minutes needs the other half first: how the call is actually made.
     Six steps, with the live limits; the terms the brief uses; what the thing is not. Drawn on the short page only. */
  function renderBriefMethod() {
    const view = $("#view-explained");
    if (!view) return;
    const B = typeof B30 === "function" ? B30() : null, L = (B && B.limits) || {};
    const N = typeof DX19 !== "undefined" && DX19 && DX19.now ? DX19.now : null;
    const T = typeof T38 === "function" ? T38() : null, Lv = (T && T.live) || {};
    const lim = (v, d) => (fin(v) ? pctPlain(v, 0) : d);
    let sec = $("#hw-call-s");
    if (!sec) {
      sec = h("section", "section");
      sec.id = "hw-call-s";
      sec.setAttribute("aria-labelledby", "hw-call-title");
      const head = h("div", "section-head"), h2 = h("h2", null, "Six steps, repeated every trading day");
      h2.id = "hw-call-title";
      head.append(h("p", "eyebrow", "The steps"), h2);
      const ol = h("ol", "steps"); ol.id = "hw-call-steps";
      sec.append(head, ol);
      const first = view.querySelector(":scope > section.section");
      if (first) first.before(sec); else view.append(sec);
    }
    const gate = N && N.gate && fin(N.gate.value) ? pct0(N.gate.value) : null;
    const steps = [
      ["Measure the risk.", "Each day the nine stocks' own prices give three readings for the book held in full: how far it swings in a typical year, how much it loses in a bad month, and how far it would fall in a bad year."],
      ["Apply the limits.", `Volatility no higher than ${lim(L.vol_target, "20%")}. Loss in a bad month no higher than ${lim(L.es_budget, "12%")}. Loss in a bad year no higher than ${lim(L.max_drawdown, "25%")}. Each limit allows some share of the book, and the call is the smallest of the three.`],
      ["Offer the hedged alternative.", `The book can instead be held in full with a Nasdaq-100 futures short big enough to meet the same limits${fin(L.max_total_gross) ? `, as long as long plus short stays within ${pct0(L.max_total_gross)} of NAV` : ""}. Less of the book is a smaller bet on the market. The short is a bet that these stocks beat the index.`],
      ["Hedge with bonds only when bonds are hedging.", "Treasuries are added only while they move opposite to stocks and inflation is low enough for that to last. When they move with stocks, as in 2022, they add risk and stay out."],
      ["Let a forecast move the size only if it has earned it.", `A separate model reads 156 years of market history and proposes a size. Its proposal counts only as far as it has beaten simply holding since 1940, after a discount for every version tried.${gate ? ` Today that weight is ${gate}.` : ""}`],
      ["Record the call before it takes effect.", `Each call is written to a tamper-evident log before the session it applies to, so the record cannot be edited afterward. A paper account follows the calls${Lv.first_effective ? ` and has since ${isoNice(Lv.first_effective)}` : ""}. Mistakes found later are published, not erased.`]];
    const ol = $("#hw-call-steps");
    ol.replaceChildren(...steps.map(([k, t]) => { const li = h("li"), d = h("div"); d.append(h("strong", null, k + " "), document.createTextNode(t)); li.append(d); return li; }));
    const dl = view.querySelector(".hw-words");
    if (dl) dl.replaceChildren(...[
      ["Full size", "The model book held with 100% of NAV. The call is a share of that."],
      ["NAV", "Net asset value: what the account is worth."],
      ["Volatility", "How far returns swing in a typical year (one standard deviation)."],
      ["Loss in a bad month", "The average of the worst 5% of months. Risk managers call it expected shortfall."],
      ["Loss in a bad year", "How far the book falls from its peak in a one-in-twenty year. Also called drawdown."],
      ["Beta", "How much the book moves when the Nasdaq-100 moves 1%."],
      ["Sharpe ratio", "Return above cash for each unit of volatility. Higher is better."],
      ["Simulation (walk-forward)", "A test that, at every past date, uses only what was known on that date."]]
      .map(([k, t]) => { const d = h("div"); d.append(h("dt", null, k), h("dd", null, t)); return d; }));
    const not = view.querySelector('[aria-labelledby="hw-not-title"] .grid2');
    if (not) not.replaceChildren(...[
      ["Not a price forecast", "It does not predict where these stocks go. Its forecasting model barely beats the long-run average, and says so. The value is in the limits and in following them."],
      ["Not a trading system", "Nothing on this site places an order. A call is a proposal; a paper account follows it so the record builds in real time."],
      ["Not a long track record", `The long record is a simulation, on stocks chosen with hindsight. The live record began ${Lv.first_effective ? isoNice(Lv.first_effective) : "in November 2026"}.`],
      ["Not personal positions", "The book is a model portfolio. It is research, not investment advice."]]
      .map(([k, t]) => { const d = h("div", "panel"); d.append(h("span", "panel-title", k), h("p", "prose", t)); return d; }));
  }


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

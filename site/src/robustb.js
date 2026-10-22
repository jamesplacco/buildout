  /* =====================================================================================
     robustb.js (v0.12): how far to trust the brain (renders buildout/brain_robust.py: brain.json or ROBUST_SNAP).
     Honest error bars by adaptive conformal inference, a stacked ensemble of five world models scored out of sample,
     and the robustness value of every measured link to an unseen common cause.
     ===================================================================================== */
  const MODEL_NAME = { history: "Full history", recent: "Last 36 months", robust: "Outlier-resistant", drift: "Drifting links", none: "No link" };
  const MODEL_COL = { history: "var(--s1)", recent: "var(--s2)", robust: "var(--s3)", drift: "var(--s4)", none: "var(--s5)" };
  const EQ_NAME = { cpi: "Consumer prices", y10: "10-year yield", eq: "Stocks", vix: "Volatility", gold: "Gold" };
  function robustOk(r) {
    try {
      return !!(r && r.equations && r.equations.eq && fin(r.equations.eq.coverage.aci) && fin(r.equations.eq.coverage.gauss) && r.equations.eq.weights
        && r.confounding && r.confounding.inflation && r.confounding.inflation.links && Object.values(r.confounding.inflation.links).every((l) => l && fin(l.rv)));
    } catch (e) { return false; }
  }
  function robustData() { const b = LIVE.brain && LIVE.brain.robust_brain; return b && robustOk(b) ? b : ROBUST_SNAP; }
  const topModel = (w) => { const ks = Object.keys(w || {}).filter((k) => fin(w[k])); return ks.length ? ks.sort((a, b) => w[b] - w[a])[0] : null; };
  function renderRobustBrain() {
    const t1 = $("#brr-cov");
    if (!t1) return;
    const R = robustData(), E = R.equations;
    const keys = Object.keys(EQ_NAME).filter((k) => E[k]);
    fillTable(t1, ["Equation", "Textbook 90%", "Since 2022", "Conformal 90%", "Since 2022", "Honest width now"], keys.map((k) => {
      const c = E[k].coverage;
      return [EQ_NAME[k], pctTxt(c.gauss), pctTxt(c.gauss_recent), pctTxt(c.aci), pctTxt(c.aci_recent), fin(E[k].kappa) ? `${fx(E[k].kappa, 2)}× textbook` : "unbounded"];
    }), 1);
    const t2 = $("#brr-stack");
    fillTable(t2, ["Equation", "Trusted most, 2000 on", "Trusted most, 2022 on", "Top two today"], keys.map((k) => {
      const e = E[k], a = topModel(e.weights), b = topModel(e.weights_recent), n = topModel(e.weights_now);
      return [EQ_NAME[k], a ? `${MODEL_NAME[a]} ${pctTxt(e.weights[a])}` : "n/a", b ? `${MODEL_NAME[b]} ${pctTxt(e.weights_recent[b])}` : "n/a",
        Object.keys(MODEL_NAME).filter((m) => e.weights_now && fin(e.weights_now[m])).sort((a, b) => e.weights_now[b] - e.weights_now[a]).slice(0, 2).map((m) => `${MODEL_NAME[m]} ${pctTxt(e.weights_now[m])}`).join(", ") || "n/a"];
    }), 1);
    const eq = E.eq;
    // stacking weights for stocks over time
    const box = $("#brr-path");
    if (box && eq.path && Array.isArray(eq.path.dates)) {
      const xs = eq.path.dates.map((d) => Number(d.slice(0, 4)) + (Number(d.slice(5, 7)) - 1) / 12);
      const ser = Object.keys(MODEL_NAME).filter((m) => Array.isArray(eq.path.weights[m])).map((m) => ({ name: MODEL_NAME[m], color: MODEL_COL[m], pts: xs.map((x, i) => [x, eq.path.weights[m][i] * 100]) }));
      const x0 = xs[0], x1 = xs[xs.length - 1];
      const ticks = [];
      for (let y = Math.ceil(x0 / 5) * 5; y <= x1; y += 5) ticks.push([y, String(y)]);
      xyChart(box, { series: ser, height: 230, yfmt: (v) => v + "%", xfmt: (x) => String(Math.floor(x)), xticks: ticks, yDomain: [0, 100], label: "Stacking weight of each world model for stocks, months before each date only" });
      legendLines($("#brr-path-l"), Object.keys(MODEL_NAME).map((m) => [MODEL_COL[m], MODEL_NAME[m]]));
    }
    // did the honest band hold? the last 60 months
    const bb = $("#brr-band");
    if (bb && eq.band && Array.isArray(eq.band.dates)) {
      const B = eq.band, xs = B.dates.map((d) => Number(d.slice(0, 4)) + (Number(d.slice(5, 7)) - 1) / 12);
      const ok = B.y.every(fin) && B.mu.every(fin) && B.sd.every(fin);
      if (ok) {
        const band = xs.map((x, i) => [x, fin(B.q[i]) ? B.mu[i] - B.q[i] * B.sd[i] : NaN, fin(B.q[i]) ? B.mu[i] + B.q[i] * B.sd[i] : NaN]);
        const miss = xs.map((x, i) => [x, fin(B.q[i]) && Math.abs(B.y[i] - B.mu[i]) > B.q[i] * B.sd[i] ? B.y[i] : NaN]);
        const ticks = [];
        for (let y = Math.ceil(xs[0]); y <= xs[xs.length - 1]; y++) ticks.push([y, String(y)]);
        xyChart(bb, { series: [{ name: "Stocks, actual (z)", color: "var(--ink)", pts: xs.map((x, i) => [x, B.y[i]]), width: 1.6 }, { name: "Ensemble forecast", color: "var(--s1)", pts: xs.map((x, i) => [x, B.mu[i]]) }],
          bands: [{ pts: band, color: "var(--s1)", opacity: 0.18 }], height: 230, zero: true, xticks: ticks, xfmt: (x) => `${Math.floor(x)}-${String(Math.round((x % 1) * 12) + 1).padStart(2, "0")}`, yfmt: (v) => fx(v, 1),
          label: "Stocks' monthly move against the ensemble's forecast and its adaptive conformal 90% band, last 60 months" });
        const nm = miss.filter((p) => fin(p[1])).length;
        $("#brr-band-t").textContent = `${nm} of ${xs.length} months fell outside the band (the target is about ${Math.round(xs.length * 0.1)}).`;
      }
    }
    // confounding
    const t3 = $("#brr-conf"), C = R.confounding;
    const rows = [];
    BR_MEASURED.forEach((k) => {
      const a = C.low_inflation && C.low_inflation.links[k], b = C.inflation && C.inflation.links[k];
      if (!a || !b) return;
      const [f, to] = k.split(">");
      const cell = (l) => `${pctTxt(l.rv)}${l.rv_alpha > 0 ? ` (${pctTxt(l.rv_alpha)} to lose 5% significance)` : " (not significant at 5%)"}`;
      rows.push([`${BR_NODES[BR_IDX[f]].s} → ${BR_NODES[BR_IDX[to]].s}`, cell(a), cell(b), b.benchmark ? `${nodeNm(b.benchmark)} ${pctTxt(b.benchmark_r2)}` : "none"]);
    });
    fillTable(t3, ["Link", "1990 to 2021", "2022 on", "Strongest observed parent, 2022 on"], rows, 1);
    const lines = (R.findings && R.findings.length ? R.findings : []).slice(0, 3);
    $("#brr-sum").textContent = lines.join(" ");
  }

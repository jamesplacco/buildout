  /* =====================================================================================
     ml.js (v0.15): the machine-learning lab, judged the way a skeptical PM would judge it. Every number here was
     computed by buildout/ml.py: purged walk-forward forecasts from 1940 (each refit sees only data that would have
     been known, with a gap so overlapping 12-month outcomes cannot leak), combinatorial purged cross-validation for
     the odds that the in-sample winner misleads, split-conformal intervals, permutation importance, calibration,
     nearest analogs and how unfamiliar today is.
     ===================================================================================== */
  function mlOk(s) { return !!(s && s.return && s.return.scores && s.crash && s.crash.scores && Array.isArray(s.analogs) && s.shift); }
  const mlPct = (v, d = 1) => (fin(v) ? `${v < 0 ? MINUS : v > 0 ? "+" : ""}${Math.abs(v * 100).toFixed(d)}%` : "n/a");
  const mlX = (v) => (fin(v) ? Math.expm1(v) : v);   // the models forecast log returns; the page shows simple returns
  const mlP = (v, d = 0) => (fin(v) ? `${Math.abs(v * 100).toFixed(d)}%` : "n/a");
  function renderMlDesk() {
    const tiles = $("#ml-tiles");
    if (!tiles || !mlOk(ML_SNAP)) { if (tiles && !tiles.children.length) tiles.append(h("p", "hint", "The machine-learning data is missing or malformed.")); return; }
    const R = ML_SNAP.return, Cr = ML_SNAP.crash, sh = ML_SNAP.shift;
    if (!tiles.children.length) {
      [[mlPct(R.scores.ensemble.skill), "Ensemble skill, 12-month return", `out of sample since ${ML_SNAP.start_oos}, against the historical mean`],
        [mlP(R.cpcv.pbo), "Odds the in-sample winner misleads", `${R.cpcv.splits} combinatorial purged splits`],
        [`${mlPct(mlX(R.now.ensemble))} vs ${mlPct(mlX(R.now.benchmark))}`, "Next 12 months, real", `ensemble vs the historical mean; 80% interval ±${mlP(R.interval.halfwidth)} in log terms`],
        [`${mlP(Cr.now.ensemble)} vs ${mlP(Cr.now.benchmark)}`, `Chance of a ${mlP(-ML_SNAP.crash_threshold)} fall`, `ensemble vs the base rate; AUC ${fx(Cr.scores.ensemble.auc, 2)}`],
        [mlP(sh.novelty_pct), "Months more familiar than today", "distance to the 24 nearest months in the record"]].forEach(([v, k, s]) => { const d = h("div", "at-kpi"); d.append(h("b", null, v), h("span", null, k), h("small", null, s)); tiles.append(d); });
      $("#ml-sum").textContent = (ML_SNAP.findings || []).join(" ");
      mlTables();
    }
    mlCharts();
  }
  function mlTables() {
    const R = ML_SNAP.return, Cr = ML_SNAP.crash, eras = Object.keys(R.scores.ensemble.eras);
    fillTable($("#ml-ret"), ["Model", "Skill vs mean", "Diebold-Mariano t", "Direction right", ...eras.map((e) => `Skill ${e}`), "Forecast now"],
      Object.entries(R.scores).map(([k, s]) => [R.labels[k], mlPct(s.skill), fx(s.dm.t, 2), mlP(s.hit), ...eras.map((e) => mlPct(s.eras[e])), mlPct(mlX(R.now[k]))]), 1);
    fillTable($("#ml-crash"), ["Model", "Brier skill vs base rate", "AUC (0.5 is a coin)", "Diebold-Mariano t", "Chance now"],
      Object.entries(Cr.scores).map(([k, s]) => [Cr.labels[k], mlPct(s.skill), fx(s.auc, 2), fx(s.dm.t, 2), mlP(Cr.now[k])]), 1);
    const cp = R.cpcv;
    fillTable($("#ml-cpcv"), ["Model", "In-sample skill", "Out-of-sample skill", "Splits where it beat the mean"],
      cp.names.filter((n) => n !== "mean").map((n) => [R.labels[n] || n, mlPct(cp.in_mean[n]), mlPct(cp.oos_mean[n]), mlP(cp.share_beating_mean[n])]), 1);
    fillTable($("#ml-cal"), ["Forecast band", "Months", "Average forecast", "Realized"], Cr.calibration.map((b) => [`${mlP(b.lo)} to ${mlP(Math.min(1, b.hi))}`, String(b.n), mlP(b.forecast), mlP(b.realized)]), 1);
    fillTable($("#ml-an"), ["Month", "Distance", "CAPE", "Next 12 months, real", "Fell 15%?"],
      ML_SNAP.analogs.map((a) => [a.date, fx(a.distance, 2), fx(a.cape, 1), a.next12 == null ? "n/a" : mlPct(mlX(a.next12)), a.crash ? "yes" : "no"]), 1);
    fillTable($("#ml-shift"), ["Feature", "Today", "Percentile in the record", "z-score", "Outside every month seen?"],
      Object.entries(ML_SNAP.shift.features).map(([k, f]) => [ML_SNAP.features[k], k === "log_cape" ? `CAPE ${fx(Math.exp(f.value), 1)}` : /y10|infl|mom|gap|vol|drawdown|ecy/.test(k) ? mlPct(f.value) : fx(f.value, 3), mlP(f.pct), fx(f.z, 2), f.outside ? "yes" : "no"]), 1);
  }
  function mlCharts() {
    const R = ML_SNAP.return, s = R.series;
    xyChart($("#ml-ts"), { height: 250, label: "Out-of-sample 12-month forecasts against what happened", series: [
      { pts: s.dates.map((d, i) => [lDate(d), mlX(s.y[i])]).filter((p) => fin(p[1])), color: "var(--s1)", name: "Realized" },
      { pts: s.dates.map((d, i) => [lDate(d), mlX(s.bench[i])]), color: "var(--muted)", name: "Historical mean" },
      { pts: s.dates.map((d, i) => [lDate(d), mlX(s.ensemble[i])]), color: "var(--warn)", name: "Ensemble" }],
      xticks: [2000, 2005, 2010, 2015, 2020, 2025].map((y) => [y, String(y)]), yfmt: (v) => mlPct(v, 0), zero: true });
    legendLines($("#ml-ts-l"), [["var(--s1)", "What happened"], ["var(--muted)", "Historical mean"], ["var(--warn)", "Ensemble forecast"]]);
    const imp = R.importance.forest, total = Object.values(imp).reduce((a, b) => a + Math.max(0, b), 0) || 1;
    barsH($("#ml-imp"), Object.entries(imp).sort((a, b) => b[1] - a[1]).map(([k, v]) => ({ label: ML_SNAP.features[k], v: v / total, color: v > 0 ? "var(--s1)" : "var(--muted)", lbl: mlPct(v / total, 0) })), { fmt: (v) => mlPct(v, 0), tfmt: (v) => mlPct(v, 0) });
  }

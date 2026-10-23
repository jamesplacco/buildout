  /* =====================================================================================
     complexity.js (v0.17): why the complex models backtest better and forecast worse, on the ML lab. Every number
     was computed by buildout/complexity.py on the engine's own 155 years and on planted data.
     ===================================================================================== */
  const CX = { fam: null };
  function cxOk() { try { return typeof CX17 === "object" && CX17.sweep && CX17.information && Array.isArray(CX17.conclusions) && CX17.conclusions.length; } catch (e) { return false; } }
  function renderComplexity() {
    const tiles = $("#cmx-tiles");
    if (!tiles || !cxOk()) { if (tiles && !tiles.children.length) tiles.append(h("p", "hint", "The complexity study is missing from this build.")); return; }
    if (!tiles.children.length) {
      const I = CX17.information, st = CX17.stambaugh, E = CX17.extrapolation;
      $("#cmx-bluf").textContent = `Because the history is far shorter than it looks and the signal is far weaker than the noise. ${I.months.toLocaleString("en-US")} months of overlapping 12-month returns hold about ${Math.round(I.n_eff)} independent observations, valuation has a half-life of about ${Math.round(I.cape_half_life_months / 12)} years, and all eight predictors together explain ${pct(I.r2_in_sample_all, 1, false)} of returns in sample. A flexible model spends that thin data memorizing the past: its in-sample fit climbs toward 100% while its forecast of the years after gets worse at every step. It extrapolates relationships into ranges it never saw, and the relationships themselves drift. The models that forecast best are the ones that assume the least.`;
      [[String(Math.round(I.n_eff)), "Independent observations", `in ${I.months.toLocaleString("en-US")} overlapping months`], [pct(I.r2_in_sample_all, 1, false), "Explained in sample", "all eight predictors, ordinary least squares"],
        [pct(I.ols_cost, 1, false), "Expected cost of estimation", `${I.p} predictors on ${Math.round(I.n_eff)} observations, out of sample`],
        [fx(E.y10_coef, 1), "Weight on the 10-year, fitted before 1950", `then yields reached ${pct(E.y10_test[1], 1, false)}`],
        [`${fx(st.p_naive, 2)} to ${fx(st.p_bias_aware, 2)}`, "CAPE p-value, raw to bias-aware", "Stambaugh's small-sample bias"]].forEach(([v, k, s]) => { const d = h("div", "at-kpi"); d.append(h("b", null, v), h("span", null, k), h("small", null, s)); tiles.append(d); });
      const seg = $("#cmx-seg");
      CX.fam = Object.keys(CX17.sweep)[0];
      Object.keys(CX17.sweep).forEach((f) => { const b = h("button", null, f); b.type = "button"; b.dataset.f = f; b.addEventListener("click", () => { CX.fam = f; cxChart(); }); seg.append(b); });
      const ol = $("#cmx-list");
      CX17.conclusions.forEach((c) => { const li = h("li"); li.append(h("b", null, c.title), h("span", null, c.text)); ol.append(li); });
      const names = { linear: "Linear regression", forest: "Random forest", boost: "Boosted trees" };
      fillTable($("#cmx-exp"), ["Shape", "True R squared", ...Object.values(names)], CX17.experiment.rows.map((r) => {
        const best = Object.keys(names).reduce((a, k) => (r[k] > r[a] ? k : a), "linear");
        return [r.shape === "linear" ? "Linear" : "Threshold", pct(r.true_r2, 0, false), ...Object.keys(names).map((k) => { const s = h("span", r[k] >= 0 ? "pos" : "neg", pct(r[k])); if (k === best) s.style.fontWeight = "700"; return s; })];
      }), 2);
    }
    cxChart();
    const D = CX17.drift;
    xyChart($("#cmx-drift"), { series: [{ name: "CAPE slope", pts: D.map((r) => [Number(r.end.slice(0, 4)) + (Number(r.end.slice(5, 7)) - 1) / 12, r.slope]), color: "var(--s1)", dots: true }],
      height: 220, zero: true, yfmt: (v) => fx(v, 2), xfmt: (v) => "30 years to " + Math.floor(v), xticks: [1920, 1950, 1980, 2010].map((x) => [x, String(x)]), label: "Rolling 30-year CAPE slope" });
  }
  function cxChart() {
    const rows = CX17.sweep[CX.fam];
    $("#cmx-seg").querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", b.dataset.f === CX.fam ? "true" : "false"));
    const clip = (v) => Math.max(-1, v);
    const xt = rows.map((r, i) => [i, r.label.replace(" trees, depth ", "×d").replace("degree ", "deg ").replace("depth ", "d")]);
    xyChart($("#cmx-chart"), { series: [{ name: "In sample", pts: rows.map((r, i) => [i, r.in_sample]), color: "var(--s2)", dots: true, width: 2 },
      { name: "Out of sample", pts: rows.map((r, i) => [i, clip(r.out_of_sample)]), color: "var(--s1)", dots: true, width: 2.5 }],
    height: 260, zero: true, yDomain: [-1, 1], yfmt: (v) => pct(v, 0), xfmt: (i) => rows[Math.round(i)].label, xticks: xt, label: `${CX.fam}: in-sample and out-of-sample R squared by complexity` });
    legendLines($("#cmx-legend"), [["var(--s2)", "In sample (training years)"], ["var(--s1)", "Out of sample (the years after)"]]);
  }

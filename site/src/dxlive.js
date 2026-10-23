  /* =====================================================================================
     dxlive.js (v0.20): the decision engine's choice, recomputed in the page. The same mixture, utility, risk budget
     and gate as buildout/decide.py, so moving a slider asks the engine itself, not a picture of it (tests/test_v20.py
     checks the two agree). Pure functions first; the desk wiring after.
     ===================================================================================== */
  function dxlUtility(w, mu, sd, gamma, grid, borrow, z, wq) {
    const out = new Float64Array(grid.length);
    for (let i = 0; i < grid.length; i++) {
      const x = grid[i], lev = Math.max(x - 1, 0) * borrow;
      let tot = 0;
      for (let k = 0; k < w.length; k++) {
        let s = 0;
        for (let q = 0; q < z.length; q++) {
          const v = Math.max(1 + x * (mu[k] + sd[k] * z[q]) - lev, 0.02);
          s += wq[q] * (Math.abs(gamma - 1) < 1e-9 ? Math.log(v) : (Math.pow(v, 1 - gamma) - 1) / (1 - gamma));
        }
        tot += w[k] * s;
      }
      out[i] = tot;
    }
    return out;
  }
  function dxlCvar(w, mu, sd, alpha = 0.05, n = 1201) {
    let lo = Infinity, hi = -Infinity;
    for (let k = 0; k < w.length; k++) { lo = Math.min(lo, mu[k] - 6 * sd[k]); hi = Math.max(hi, mu[k] + 6 * sd[k]); }
    const g = new Float64Array(n), pdf = new Float64Array(n), cdf = new Float64Array(n);
    const step = (hi - lo) / (n - 1), c0 = Math.sqrt(2 * Math.PI);
    let run = 0;
    for (let i = 0; i < n; i++) {
      g[i] = lo + i * step;
      let p = 0;
      for (let k = 0; k < w.length; k++) { const zz = (g[i] - mu[k]) / sd[k]; p += w[k] * Math.exp(-0.5 * zz * zz) / (sd[k] * c0); }
      pdf[i] = p; run += p * step; cdf[i] = run;
    }
    let idx = n - 1;
    for (let i = 0; i < n; i++) if (cdf[i] / run >= alpha) { idx = i; break; }
    let num = 0, den = 0;
    for (let i = 0; i <= idx; i++) { num += g[i] * pdf[i]; den += pdf[i]; }
    return [-g[idx], den > 0 ? -num / den : -g[idx]];
  }
  function dxlChoose(w, mu, sd, gamma, esLimit, grid, borrow, z, wq) {
    const u = dxlUtility(w, mu, sd, gamma, grid, borrow, z, wq);
    let es1 = null, best = -1, bestAll = 0;
    for (let i = 1; i < u.length; i++) if (u[i] > u[bestAll]) bestAll = i;
    if (esLimit == null) return { x: grid[bestAll], i: bestAll, u, capped: false, es1 };
    es1 = dxlCvar(w, mu, sd, 0.05)[1];
    for (let i = 0; i < u.length; i++) {
      const ok = i === 0 || grid[i] * Math.max(es1, 1e-9) <= esLimit + 1e-12;
      if (ok && (best < 0 || u[i] > u[best])) best = i;
    }
    return { x: grid[best], i: best, u, capped: best !== bestAll, es1 };
  }
  const dxlCE = (u, gamma) => (Math.abs(gamma - 1) < 1e-9 ? Math.exp(u) - 1 : Math.pow(1 + (1 - gamma) * u, 1 / (1 - gamma)) - 1);
  function dxlGate(t, nTried) {                               // 2 Phi(t - t0) - 1, floored at 0; t0 the best of n useless strategies
    const t0 = dxlNormInv(1 - 1 / nTried);
    return Math.max(0, 2 * dxlNormCdf(t - t0) - 1);
  }
  function dxlNormCdf(x) {                                    // Abramowitz and Stegun 7.1.26 through erf, error under 1.5e-7
    const s = x < 0 ? -1 : 1, a = Math.abs(x) / Math.SQRT2, t = 1 / (1 + 0.3275911 * a);
    const y = 1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-a * a);
    return 0.5 * (1 + s * y);
  }
  function dxlNormInv(p) {                                    // Acklam's rational approximation, refined by one Newton step
    const a = [-39.69683028665376, 220.9460984245205, -275.9285104469687, 138.357751867269, -30.66479806614716, 2.506628277459239];
    const b = [-54.47609879822406, 161.5858368580409, -155.6989798598866, 66.80131188771972, -13.28068155288572];
    const c = [-0.007784894002430293, -0.3223964580411365, -2.400758277161838, -2.549732539343734, 4.374664141464968, 2.938163982698783];
    const d = [0.007784695709041462, 0.3224671290700398, 2.445134137142996, 3.754408661907416];
    const pl = 0.02425;
    let x;
    if (p < pl) { const q = Math.sqrt(-2 * Math.log(p)); x = (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1); }
    else if (p <= 1 - pl) { const q = p - 0.5, r = q * q; x = (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1); }
    else { const q = Math.sqrt(-2 * Math.log(1 - p)); x = -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1); }
    const e = dxlNormCdf(x) - p;
    return x - e * Math.sqrt(2 * Math.PI) * Math.exp(x * x / 2);
  }
  // the engine's mixture under a what-if: stressed odds p (the other states keep their proportions), a 12-month forecast
  function dxlMixture(N, opt) {
    const M = N.mixture, R = N.regime, names = ["hmm", "bocpd", "uncond"];
    const mw = names.map((k) => N.models.weights[k]);
    const W = [], MU = [], SD = [];
    const tilt = opt.r12 == null ? N.tilt : (opt.r12 - N.forecasts.now.mean) / 12;
    names.forEach((k, j) => {
      let cw = M[k].w.slice();
      if (k === "hmm" && opt.pStress != null) {
        const wk = R.worst, rest = 1 - cw[wk];
        cw = cw.map((v, i) => (i === wk ? opt.pStress : (rest > 1e-12 ? v / rest * (1 - opt.pStress) : (1 - opt.pStress) / (cw.length - 1))));
      }
      cw.forEach((v, i) => { W.push(mw[j] * v); MU.push(M[k].mu[i] + (opt.noTilt ? 0 : tilt)); SD.push(M[k].sd[i]); });
    });
    return { W, MU, SD, tilt };
  }
  function dxlDecide(N, opt) {
    const { W, MU, SD, tilt } = dxlMixture(N, opt);
    const gamma = opt.gamma == null ? N.gamma : opt.gamma, es = opt.es === undefined ? N.es_limit : opt.es;
    const r = dxlChoose(W, MU, SD, gamma, es, N.grid, N.borrow, N.gh.z, N.gh.w);
    const g = opt.t == null ? N.gate.value : dxlGate(opt.t, N.gate.n_tried);
    const fin = Math.round((1 + g * (r.x - 1)) / 0.05) * 0.05;
    return { ...r, gate: g, decision: fin, tilt, gamma, ce: Array.from(r.u, (u) => dxlCE(u, gamma)) };
  }

  /* ---------- the desk: what if ---------- */
  const DXL = { p: null, r12: null, gamma: null, es: null, t: null };
  function renderWhatIf() {
    const box = $("#dxw-out");
    if (!box || !dxOk() || !DX19.now.mixture) return;
    const N = DX19.now;
    if (!box.dataset.wired) {
      box.dataset.wired = "1";
      const set = (id, v) => { const e = $(id); if (e) e.value = String(v); };
      const reset = () => {
        DXL.p = N.regime.next[N.regime.worst]; DXL.r12 = N.forecasts.stacked; DXL.gamma = N.gamma; DXL.es = N.es_limit; DXL.t = N.gate.t;
        set("#dxw-p", DXL.p); set("#dxw-r", DXL.r12); set("#dxw-g", DXL.gamma); set("#dxw-es", DXL.es); set("#dxw-t", DXL.t);
        dxlUpdate();
      };
      [["#dxw-p", "p"], ["#dxw-r", "r12"], ["#dxw-g", "gamma"], ["#dxw-es", "es"], ["#dxw-t", "t"]].forEach(([id, k]) => {
        const e = $(id);
        if (e) e.addEventListener("input", () => { DXL[k] = Number(e.value); dxlUpdate(); });
      });
      const rb = $("#dxw-reset");
      if (rb) rb.addEventListener("click", reset);
      reset();
      return;
    }
    dxlUpdate();
  }
  function dxlUpdate() {
    const N = DX19.now;
    const esv = DXL.es >= 0.299 ? null : DXL.es;
    const r = dxlDecide(N, { pStress: DXL.p, r12: DXL.r12, gamma: DXL.gamma, es: esv, t: DXL.t });
    const txt = (id, s) => { const e = $(id); if (e) e.textContent = s; };
    txt("#dxw-p-v", pct(DXL.p, 0, false)); txt("#dxw-r-v", pct(DXL.r12, 1)); txt("#dxw-g-v", fx(DXL.gamma, 2));
    txt("#dxw-es-v", esv == null ? "off" : pct(esv, 0, false)); txt("#dxw-t-v", fx(DXL.t, 1));
    txt("#dxw-x", dxX(r.decision)); txt("#dxw-opt", dxX(r.x)); txt("#dxw-gate", pct(r.gate, 0, false));
    txt("#dxw-why", `The engine's optimum is ${dxX(r.x)}${r.capped ? ", held down by the risk budget" : ""}; a 1x month's expected shortfall is ${r.es1 == null ? "not limited" : pct(r.es1, 1, false)}. `
      + (r.gate > 0 ? `With evidence t ${fx(DXL.t, 1)}, the gate passes ${pct(r.gate, 0, false)} of the move away from 1x.` : `With evidence t ${fx(DXL.t, 1)}, under the ${fx(dxlNormInv(1 - 1 / N.gate.n_tried), 1)} that luck alone would give the best of ${N.gate.n_tried} strategies, the gate stays shut.`));
    const pts = N.grid.map((x, i) => [x, r.ce[i] * 12]);
    xyChart($("#dxw-chart"), { series: [{ name: "Certainty-equivalent return, a year", pts, color: "var(--s1)", width: 2.2 }], height: 220, zero: true,
      yfmt: (v) => pct(v, 0), xfmt: (v) => "exposure " + fx(v, 2) + "x", xticks: [0, 0.5, 1, 1.5].map((v) => [v, fx(v, 1) + "x"]),
      vmarks: [{ x: r.x, label: "optimum" }], label: "What each exposure is worth to this investor, in certain return" });
  }

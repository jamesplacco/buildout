  /* =====================================================================================
     geo.js (v0.22): the shape of the market. 156 years of stocks, Treasuries and gold as points on the curved space of
     covariance matrices (an era map, today's analogs and the placebo that tests them), the eigenvalues of the world's
     markets against pure noise, the topology of their correlations, the Levy area of stocks against bonds, long memory
     and the geometry of compounding. Every number was computed by buildout/geometry.py and shipped in snap22.js.
     ===================================================================================== */
  function geoOk() { try { return typeof GEO22 === "object" && GEO22 && GEO22.covariance && GEO22.tests; } catch (e) { return false; } }
  const GEO_ERAS = [["1871-1913", 1871, 1913, "var(--s4)"], ["1914-1945", 1914, 1945, "var(--s2)"], ["1946-1972", 1946, 1972, "var(--s5)"],
    ["1973-1999", 1973, 1999, "var(--s3)"], ["2000-2019", 2000, 2019, "var(--s1)"], ["2020-now", 2020, 2100, "var(--ink)"]];
  const geoEra = (y) => GEO_ERAS.find((e) => y >= e[1] && y <= e[2]) || GEO_ERAS[GEO_ERAS.length - 1];
  const geoYr = (d) => (typeof d === "number" ? d + 11 / 12 : Number(String(d).slice(0, 4)) + (Number(String(d).slice(5, 7)) - 1) / 12);
  const geoSgn = (v, d = 2) => (v >= 0 ? "+" : MINUS) + Math.abs(v).toFixed(d);
  const geoName = (k) => (GEO22.labels && GEO22.labels[k] ? GEO22.labels[k].name : k);
  function renderGeometry() {
    const top = $("#geo-tiles");
    if (!top || !geoOk()) { if (top && !top.children.length) top.append(h("p", "hint", "The geometry study is missing from the snapshot.")); return; }
    const O = GEO22, C = O.covariance, N = C.now, E = O.engine_model, PL = E.placebo, SP = O.spectrum, TP = O.topology, SC = O.scaling;
    if (!top.children.length) {
      const surv = O.tests.filter((t) => t.q <= 0.10);
      const near = Object.entries(C.eras).sort((a, b) => a[1].distance_now - b[1].distance_now)[0];
      $("#geo-bluf").textContent = `Recommendation: no change to the 1.00x exposure. Covariance structure is informative about risk but not about returns. Of ${O.tests.length} geometric hypotheses tested out of sample, ${surv.length} ${surv.length === 1 ? "survives" : "survive"} a 10% false-discovery rate. The survivor, the decision engine's new analog model, outperforms the long-run average (t ${fx(E.t, 1)}), but a placebo of randomly selected windows performs equally well (nearest versus random, t ${fx(PL.geometry_t, 1)}). The improvement comes from the fatter tails of a mixture of historical periods, not from similarity to today. The engine therefore retains the model for tail shape only, and the geometry serves as a descriptive map rather than a signal.`;
      dxKpis(top, [
        [`${surv.length} of ${O.tests.length}`, "Claims that survive", "Benjamini-Hochberg, 10% false-discovery rate"],
        [fx(E.t, 1), "Analog model over the long run", `log score +${fx(E.mean_gain, 3)} a month since 1940`],
        [fx(PL.geometry_t, 1), "Nearest over random analogs", "placebo: similarity adds no measurable value"],
        ...(SP ? [[String(SP.now.above), "Real factors in world markets", `${SP.now.N} series, eigenvalues above the noise edge of ${fx(SP.now.edges[1], 2)}`]] : []),
        [near[0].replace("-", " to "), "Today's nearest era", `distance ${fx(near[1].distance_now, 2)} to its Frechet mean`],
        [fx(SC.all, 2), "Hurst exponent of returns", `shuffled range ${fx(SC.null_q05, 2)} to ${fx(SC.null_q95, 2)}; partly an averaging artifact`]]);
      const ul = $("#geo-find");
      O.findings.forEach((f) => ul.append(h("li", null, f)));
      geoAnalogs();
      geoTests();
      geoComp();
    }
    geoMap();
    geoPlacebo();
    geoSpectrum();
    geoBarcode();
    geoLevy();
    geoHurst();
    geoSeries();
    fixChartRoles($("#view-geometry"));
  }
  /* the era map: one point per year, placed by classical multidimensional scaling of the log-Euclidean distances
     between that December's 36-month covariance matrix and every other year's */
  function geoMap() {
    const box = $("#geo-map");
    if (!box) return;
    redrawWhenSized(box, geoMap);
    const M = GEO22.covariance.map, W = Math.max(300, box.clientWidth || 0), H = Math.round(Math.min(460, Math.max(300, W * 0.6))), pad = 26;
    const xs = M.x, ys = M.y, x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
    const k = Math.min((W - 2 * pad) / (x1 - x0 || 1), (H - 2 * pad) / (y1 - y0 || 1));      // one scale for both axes: distances on the page are distances
    const ox = (W - k * (x1 - x0)) / 2, oy = (H - k * (y1 - y0)) / 2;
    const sx = (v) => ox + (v - x0) * k, sy = (v) => H - (oy + (v - y0) * k);
    box.replaceChildren();
    const s = svg("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: "img", "aria-label": "Map of 150 years of stock, bond and gold risk structure, one point per year" }, box);
    // the path through time, faint, then the points by era
    let d = "";
    M.x.forEach((_, i) => { d += (i ? "L" : "M") + sx(xs[i]).toFixed(1) + "," + sy(ys[i]).toFixed(1); });
    svg("path", { d, fill: "none", stroke: "var(--rule)", "stroke-width": 1.2, "stroke-linejoin": "round" }, s);
    const last = M.x.length - 1;
    M.x.forEach((_, i) => {
      const yv = typeof M.years[i] === "number" ? M.years[i] : Number(String(M.years[i]).slice(0, 4)), era = geoEra(yv);
      svg("circle", { cx: sx(xs[i]), cy: sy(ys[i]), r: i === last ? 7 : 3.6, fill: era[3], class: "mark-ring" }, s);
      const hit = svg("circle", { cx: sx(xs[i]), cy: sy(ys[i]), r: 9, class: "hit", tabindex: i % 5 === 0 || i === last ? "0" : "-1", "aria-label": `${M.years[i]}: stock volatility ${pct(M.vol_s[i], 0, false)}, stock-bond correlation ${geoSgn(M.corr_sb[i])}` }, s);
      bindTip(hit, () => [[String(M.years[i]), era[0].replace("-", " to ")], [pct(M.vol_s[i], 0, false), "stock volatility, 36 months"], [geoSgn(M.corr_sb[i]), "stock-bond correlation"]]);
    });
    // label the first year of each era where it lands, and today
    const seen = new Set();
    M.x.forEach((_, i) => {
      const yv = typeof M.years[i] === "number" ? M.years[i] : Number(String(M.years[i]).slice(0, 4)), era = geoEra(yv);
      if (seen.has(era[0]) || i === last) return;
      seen.add(era[0]);
      text(s, sx(xs[i]) + 7, sy(ys[i]) - 6, String(M.years[i]), "ax", "start");
    });
    const lx = sx(xs[last]), ly = sy(ys[last]);
    text(s, lx + (lx > W - 70 ? -10 : 10), ly + 4, "today", "lbl-strong", lx > W - 70 ? "end" : "start");
    const lg = $("#geo-map-leg");
    if (lg && !lg.children.length) legendLines(lg, GEO_ERAS.map((e) => [e[3], e[0].replace("-", " to ")]));
    const n = $("#geo-map-n");
    if (n) n.textContent = `Two axes carry ${pct(M.share[0] + M.share[1], 0, false)} of the structure (${pct(M.share[0], 0, false)} and ${pct(M.share[1], 0, false)}). Points close together had similar volatilities and correlations; the path joins the years in order. The long left-to-right move is gold: pegged until 1971, then free.`;
  }
  function geoAnalogs() {
    const C = GEO22.covariance, N = C.now, T = GEO22.transport;
    fillTable($("#geo-an"), ["Window ending", "Distance", "Stock vol", "Bond vol", "Gold vol", "Stock-bond corr", "Next 12 months, stocks"], N.analogs.map((a) => [
      a.date, fx(a.distance, 2), pct(a.vol[0], 0, false), pct(a.vol[1], 0, false), pct(a.vol[2], 0, false), geoSgn(a.corr_sb), a.next12_stocks == null ? "n/a" : pct(a.next12_stocks, 1)]), 1);
    const now = $("#geo-now");
    if (now) now.textContent = `Today (36 months to ${N.date}): stocks ${pct(N.vol[0], 0, false)} volatility, Treasuries ${pct(N.vol[1], 0, false)}, gold ${pct(N.vol[2], 0, false)}; stock-bond correlation ${geoSgn(N.corr[0][1])}, stock-gold ${geoSgn(N.corr[0][2])}. The eight analogs averaged ${pct(N.analog_next12, 1)} over the next year against ${pct(N.uncond_next12, 1)} for every month since 1871.`;
    const tr = $("#geo-tr");
    if (tr) fillTable(tr, ["Window ending", "Sliced Wasserstein distance", "Next 12 months, stocks"], T.now.analogs.map((a) => [a.date, fx(a.distance, 3), a.next12_stocks == null ? "n/a" : pct(a.next12_stocks, 1)]), 1);
  }
  function geoPlacebo() {
    const box = $("#geo-placebo");
    if (!box) return;
    const E = GEO22.engine_model, PL = E.placebo;
    barsH(box, [
      { label: (box.clientWidth || 600) < 420 ? "Nearest 8 (the model)" : "Nearest 8 windows (the model)", v: E.mean_gain * 1000, lbl: "+" + fx(E.mean_gain * 1000, 1), color: "var(--s1)", strong: true, tip: () => [["+" + fx(E.mean_gain, 4), "log score a month over the long-run average"], ["t " + fx(E.t, 1), "Newey-West, since 1940"]] },
      { label: (box.clientWidth || 600) < 420 ? "8 random windows" : `8 random windows (${PL.draws} draws)`, v: PL.random_gain * 1000, lbl: "+" + fx(PL.random_gain * 1000, 1), color: "var(--muted)", tip: () => [["+" + fx(PL.random_gain, 4), "the placebo"], ["t " + fx(PL.random_t, 1), "random windows help as much"]] },
      { label: "Farthest 8 windows", v: PL.farthest_gain * 1000, lbl: "+" + fx(PL.farthest_gain * 1000, 1), color: "var(--s2)", tip: () => [["+" + fx(PL.farthest_gain, 4), "the anti-model"], ["t " + fx(PL.farthest_t, 1), "unlike today still helps a little"]] }],
    { fmt: (v) => fx(v, 1), label: "Predictive log-score gain over the long-run average, thousandths per month", labelW: Math.round(Math.min(210, Math.max(120, (box.clientWidth || 300) * 0.42))) });
    const n = $("#geo-placebo-n");
    if (n) n.textContent = `Thousandths of a log point a month, walked forward over ${E.months.toLocaleString("en-US")} months. Nearest over random: ${geoSgn(PL.geometry_over_random * 1000, 1)} (t ${fx(PL.geometry_t, 1)}). Nearest over farthest: ${geoSgn(PL.nearest_over_farthest * 1000, 1)} (t ${fx(PL.nearest_far_t, 1)}).`;
  }
  /* the eigenvalues of the last ten years' correlation matrix of world markets, against the Marchenko-Pastur density
     a matrix of pure noise with the same shape would have */
  function geoSpectrum() {
    const box = $("#geo-spec"), SP = GEO22.spectrum;
    if (!box || !SP) return;
    redrawWhenSized(box, geoSpectrum);
    const Nw = SP.now, W = Math.max(300, box.clientWidth || 0), H = 220, padL = 40, padR = 16, top = 16, bottom = 30;
    const lmax = Math.max(...Nw.eigen) * 1.04, dmax = Math.max(...Nw.mp.density) * 1.1;
    const sx = (v) => padL + (v / lmax) * (W - padL - padR), sy = (v) => top + (1 - v / dmax) * (H - top - bottom);
    box.replaceChildren();
    const s = svg("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: "img", "aria-label": "Eigenvalues of world-market correlations against the noise density" }, box);
    niceTicks(0, lmax, 6).forEach((t) => { if (t > lmax) return; svg("line", { x1: sx(t), x2: sx(t), y1: top, y2: H - bottom, class: "gridline" }, s); text(s, sx(t), H - 10, String(t), "ax", "middle"); });
    svg("line", { x1: padL, x2: W - padR, y1: H - bottom, y2: H - bottom, class: "baseline" }, s);
    let d = "";
    Nw.mp.x.forEach((x, i) => { if (x > lmax) return; d += (d ? "L" : "M") + sx(x).toFixed(1) + "," + sy(Nw.mp.density[i]).toFixed(1); });
    svg("path", { d: d + `L${sx(Math.min(lmax, Nw.mp.x[Nw.mp.x.length - 1]))},${H - bottom}L${sx(Nw.mp.x[0])},${H - bottom}Z`, fill: "var(--s1)", opacity: 0.12 }, s);
    svg("path", { d, fill: "none", stroke: "var(--s1)", "stroke-width": 2 }, s);
    const edge = Nw.edges[1];
    svg("line", { x1: sx(edge), x2: sx(edge), y1: top, y2: H - bottom, stroke: "var(--ink-2)", "stroke-dasharray": "4 3", "stroke-width": 1.2 }, s);
    text(s, sx(edge) + 5, top + 10, "noise edge " + fx(edge, 2), "ax", "start");
    Nw.eigen.forEach((v, i) => {
      const above = v > edge, x = sx(v);
      svg("line", { x1: x, x2: x, y1: H - bottom, y2: H - bottom - (above ? 60 : 22), stroke: above ? "var(--s2)" : "var(--muted)", "stroke-width": above ? 3 : 1.6, "stroke-linecap": "round" }, s);
      if (above) text(s, x, H - bottom - 66, i === 0 ? "factor 1" : "factor " + (i + 1), "lbl-strong", x > W - 60 ? "end" : "middle");
      const hit = svg("rect", { x: x - 5, y: top, width: 10, height: H - top - bottom, class: "hit", tabindex: above ? "0" : "-1", "aria-label": `Eigenvalue ${i + 1}: ${fx(v, 2)}` }, s);
      bindTip(hit, () => [[fx(v, 2), `eigenvalue ${i + 1} of ${Nw.N}`], [pct(v / Nw.N, 0, false), "of the total variance"], [above ? "above the noise edge" : "inside the noise band", ""]]);
    });
    const f = $("#geo-factors");
    if (f && !f.children.length) (Nw.factors || []).forEach((fc, i) => {
      const li = h("li");
      li.append(h("b", null, `Factor ${i + 1}, ${pct(fc.share, 0, false)} of the variance: `), document.createTextNode(fc.top.map((t) => `${geoName(t.name)} ${geoSgn(t.loading)}`).join(", ")));
      f.append(li);
    });
    const n = $("#geo-spec-n");
    if (n) n.textContent = `${Nw.N} series, ${Nw.T} months (q = N/T = ${fx(Nw.q, 3)}). Pure noise would put every eigenvalue between ${fx(Nw.edges[0], 2)} and ${fx(Nw.edges[1], 2)}, the blue curve; ${Nw.above} rise above it. Absorption ratio today: ${pct(Nw.ar, 0, false)} of the variance in the top fifth of eigenvectors.`;
  }
  /* persistent homology today: how the 30 most complete series join up (H0, the spanning tree) and the loops that open
     and close (H1) as the correlation distance threshold grows */
  function geoBarcode() {
    const box = $("#geo-bars"), TP = GEO22.topology;
    if (!box || !TP) return;
    redrawWhenSized(box, geoBarcode);
    const h0 = TP.now.h0, h1 = TP.now.h1.filter((p) => p[1] != null), W = Math.max(300, box.clientWidth || 0), rows = h0.length + h1.length + 1, rh = 7, top = 8, bottom = 28, padL = 34, padR = 14;
    const H = top + rows * rh + bottom, rmax = Math.max(1.2, ...h0, ...h1.map((p) => p[1])) * 1.02;
    const sx = (v) => padL + (v / rmax) * (W - padL - padR);
    box.replaceChildren();
    const s = svg("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: "img", "aria-label": "Persistence barcode of world-market correlations" }, box);
    niceTicks(0, rmax, 5).forEach((t) => { if (t > rmax) return; svg("line", { x1: sx(t), x2: sx(t), y1: top, y2: H - bottom, class: "gridline" }, s); text(s, sx(t), H - 10, String(t), "ax", "middle"); });
    text(s, padL - 6, top + 6, "H0", "ax", "end");
    h0.forEach((v, i) => {
      const y = top + i * rh;
      svg("line", { x1: sx(0), x2: sx(v), y1: y + 3, y2: y + 3, stroke: "var(--s1)", "stroke-width": 3.5, "stroke-linecap": "round" }, s);
    });
    const y1 = top + (h0.length + 1) * rh;
    text(s, padL - 6, y1 + 6, "H1", "ax", "end");
    h1.forEach((p, i) => {
      const y = y1 + i * rh;
      svg("line", { x1: sx(p[0]), x2: sx(p[1]), y1: y + 3, y2: y + 3, stroke: "var(--s2)", "stroke-width": 3.5, "stroke-linecap": "round" }, s);
      const hit = svg("rect", { x: sx(p[0]) - 4, y, width: Math.max(8, sx(p[1]) - sx(p[0]) + 8), height: rh, class: "hit", tabindex: "0", "aria-label": `Loop born at ${fx(p[0], 2)}, dies at ${fx(p[1], 2)}` }, s);
      bindTip(hit, () => [[fx(p[1] - p[0], 3), "persistence of the loop"], [`${fx(p[0], 2)} to ${fx(p[1], 2)}`, "born and filled, correlation distance"]]);
    });
    const n = $("#geo-bars-n");
    const mst = TP.now.mst.slice().sort((a, b) => a.d - b.d).slice(0, 5).map((e) => `${geoName(e.a)} and ${geoName(e.b)} (${fx(1 - e.d * e.d / 2, 2)})`);
    if (n) n.textContent = `${h0.length + 1} series from the atlas, distance √(2(1 − ρ)). Blue: when each series joins the rest (the spanning tree); its tightest links are ${mst.join(", ")}, with correlations in brackets. Orange: ${h1.length} loop${h1.length === 1 ? "" : "s"}, groups of markets each linked to the next but not across, that close as the threshold grows.`;
  }
  /* the path of cumulative stock and bond returns over the last 36 months, the chord from start to end, and the
     signed area between them: positive when stocks moved first */
  function geoLevy() {
    const box = $("#geo-levy"), P = GEO22.paths;
    if (!box || !P) return;
    redrawWhenSized(box, geoLevy);
    const xs = P.now.path.stocks, ys = P.now.path.bonds, W = Math.max(300, box.clientWidth || 0), H = 260, pad = 34;
    const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
    const sx = (v) => pad + ((v - x0) / (x1 - x0 || 1)) * (W - 2 * pad), sy = (v) => H - pad - ((v - y0) / (y1 - y0 || 1)) * (H - 2 * pad);
    box.replaceChildren();
    const s = svg("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: "img", "aria-label": "Path of cumulative stock and bond returns over 36 months" }, box);
    let d = "";
    xs.forEach((x, i) => { d += (i ? "L" : "M") + sx(x).toFixed(1) + "," + sy(ys[i]).toFixed(1); });
    svg("path", { d: d + "Z", fill: P.now.area >= 0 ? "var(--s3)" : "var(--s2)", opacity: 0.14, stroke: "none" }, s);
    svg("line", { x1: sx(xs[0]), y1: sy(ys[0]), x2: sx(xs[xs.length - 1]), y2: sy(ys[ys.length - 1]), stroke: "var(--ink-2)", "stroke-dasharray": "4 3", "stroke-width": 1.2 }, s);
    svg("path", { d, fill: "none", stroke: "var(--s1)", "stroke-width": 2, "stroke-linejoin": "round" }, s);
    svg("circle", { cx: sx(xs[0]), cy: sy(ys[0]), r: 4, fill: "var(--muted)", class: "mark-ring" }, s);
    svg("circle", { cx: sx(xs[xs.length - 1]), cy: sy(ys[ys.length - 1]), r: 5, fill: "var(--s1)", class: "mark-ring" }, s);
    text(s, sx(xs[0]) + 7, sy(ys[0]) + 14, "36 months ago", "ax", "start");
    const ex = sx(xs[xs.length - 1]);
    text(s, ex + (ex > W - 60 ? -8 : 8), sy(ys[ys.length - 1]) - 8, "now", "lbl-strong", ex > W - 60 ? "end" : "start");
    text(s, W / 2, H - 8, "cumulative stock return →", "ax", "middle");
    text(s, 12, H / 2, "bonds →", "ax", "middle", { transform: `rotate(-90 12 ${H / 2})` });
    const n = $("#geo-levy-n");
    if (n) n.textContent = `Levy area per month today: ${geoSgn(P.now.area, 3)} (each series scaled to unit variance); stock-bond correlation over the window ${geoSgn(P.now.corr)}. Walked forward since 1874, the area says nothing about the next year's correlation beyond today's correlation (t ${fx(P.test.t, 1)}, p ${fx(P.test.p, 2)}).`;
  }
  function geoHurst() {
    const box = $("#geo-hurst"), SC = GEO22.scaling;
    if (!box || !SC) return;
    barsH(box, SC.eras.map((e) => ({ label: e.era, v: e.hurst, lbl: fx(e.hurst, 2), color: "var(--s1)", mark: 0.5,
      tip: () => [[fx(e.hurst, 2), "Hurst exponent of monthly returns"], [fx(e.hurst_abs, 2), "of their size (volatility memory)"], ["0.50", "a random walk"]] })),
    { fmt: (v) => fx(v, 2), min: 0, max: 0.8, label: "Hurst exponent of monthly real stock returns by era", labelW: 120 });
  }
  function geoComp() {
    const t = $("#geo-comp");
    if (!t) return;
    fillTable(t, ["Decade", "Arithmetic", "Geometric (what compounded)", "Gap", "σ²/2 drag", "Volatility"], GEO22.compounding.map((r) => [
      r.decade + (r.months < 120 ? ` (${r.months} months)` : ""), pct(r.arithmetic, 1), pct(r.geometric, 1), pct(r.gap, 2, false), pct(r.drag, 2, false), pct(r.vol, 0, false)]), 1);
  }
  function geoTests() {
    const t = $("#geo-tests");
    if (!t) return;
    fillTable(t, ["Claim, walked forward", "p", "q (false discovery)", "Verdict"], GEO22.tests.map((r) => [r.test, r.p < 0.001 ? "<0.001" : fx(r.p, 3), r.q < 0.001 ? "<0.001" : fx(r.q, 3),
      r.q <= 0.10 ? h("b", null, "survives") : "does not survive"]), 1);
  }
  function geoSeries() {
    const SP = GEO22.spectrum, TP = GEO22.topology, P = GEO22.paths;
    if (SP) xyChart($("#geo-ar"), { label: "Absorption ratio of world markets", series: [{ name: "Absorption ratio", pts: SP.series.dates.map((d, i) => [geoYr(d), SP.series.ar[i]]), color: "var(--s1)", width: 1.8 }],
      xticks: [1995, 2000, 2005, 2010, 2015, 2020, 2025].map((y) => [y, String(y)]), yfmt: (v) => pct(v, 0, false), xfmt: (x) => String(Math.floor(x)), height: 200 });
    if (TP) xyChart($("#geo-tda"), { label: "Total persistence of loops in world-market correlations", series: [{ name: "H1 total persistence", pts: TP.series.dates.map((d, i) => [geoYr(d), TP.series.h1[i]]), color: "var(--s2)", width: 1.8 }],
      xticks: [1995, 2000, 2005, 2010, 2015, 2020, 2025].map((y) => [y, String(y)]), yfmt: (v) => fx(v, 2), xfmt: (x) => String(Math.floor(x)), height: 200 });
    if (P) xyChart($("#geo-area"), { label: "Levy area of stocks against bonds, 36-month windows", zero: true, series: [{ name: "Levy area", pts: P.series.dates.map((d, i) => [geoYr(d), P.series.area[i]]), color: "var(--s3)", width: 1.6 }],
      xticks: [1880, 1900, 1920, 1940, 1960, 1980, 2000, 2020].map((y) => [y, String(y)]), yfmt: (v) => fx(v, 2), xfmt: (x) => String(Math.floor(x)), height: 200 });
  }

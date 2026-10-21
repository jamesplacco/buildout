  /* =====================================================================================
     brain.js (v0.6): the system as a signed, weighted graph. Shocks propagate order by order
     (x_k = W' x_k-1), so the desk can show what arrives first, second, third and fourth.
     Eleven edges are measured from monthly data in two regimes (BRAIN_SNAP, or data/brain.json);
     the rest are judged, labelled as such, and editable. Nothing here is a forecast: it is a
     consistent way to carry assumptions to their conclusions, and to see which ones carry the weight.
     ===================================================================================== */
  // ring 0 = drivers (outside), 1 = transmission, 2 = outcomes (centre); a = angle in degrees, 0 = right, clockwise
  const BR_NODES = [
    { id: "hormuz", n: "Hormuz disruption", s: "Hormuz", ring: 0, a: 205, d: "nw-oil-physical", why: "Tankers through the strait: 4 a day on Oct 4 against 85 before the war (IMF PortWatch via Straits.live)." },
    { id: "oil", n: "Oil, physical", s: "Oil", ring: 0, a: 240, m: "oil", d: "fi-oil", why: "EIA spot Brent, monthly average. Measured edges start here." },
    { id: "fed", n: "Fed policy path", s: "Fed", ring: 0, a: 274, d: "nw-fed-hike", why: "3.75 to 4.00% after the Sep 16 hike; Oct 28 decision." },
    { id: "fiscal", n: "Treasury and tech bond supply", s: "Supply", ring: 0, a: 308, d: "pp-title", why: "Deficits plus record hyperscaler bond issuance add duration the market must absorb." },
    { id: "capex", n: "AI capex", s: "AI capex", ring: 0, a: 342, d: "fund-table", why: "About $725B of 2026 guidance across four hyperscalers (April)." },
    { id: "memory", n: "Memory prices", s: "Memory", ring: 0, a: 22, d: "nw-memory", why: "DDR5 contracts +57% in Q1 and +50% in Q2 2026; HBM sold out for 2026." },
    { id: "power", n: "Grid power prices", s: "Power", ring: 0, a: 58, d: "nw-power", why: "PJM 2027/28 capacity cleared at the cap, about 6.3 GW short of the reliability target." },
    { id: "cpi", n: "Consumer prices", s: "CPI", ring: 1, a: 246, m: "cpi", d: "d-duration", why: "CPI-U: 3.7% over the year to September; 3.6% annualized over three months." },
    { id: "y10", n: "10-year yield", s: "10-year", ring: 1, a: 284, m: "y10", d: "rates-title", why: "5.15% on Oct 19 (Treasury)." },
    { id: "tp", n: "Term premium", s: "Term prem.", ring: 1, a: 318, d: "rates-title", why: "The extra yield for holding duration; supply pushes it up." },
    { id: "dep", n: "Depreciation catch-up", s: "Depreciation", ring: 1, a: 12, d: "bs-depr-title", why: "Server lives of 5 to 6 years against 2 to 3 years of frontier economic life." },
    { id: "pods", n: "Pod crowding and de-grossing", s: "Pods", ring: 1, a: 54, d: "pr-pods-title", why: "Multi-manager AUM grew 175% from 2017 to 2023; crowded longs unwind together." },
    { id: "liq", n: "Funding liquidity", s: "Liquidity", ring: 1, a: 100, d: "liq-title", why: "Reverse repo is empty ($0.33B), so drains hit bank reserves." },
    { id: "credit", n: "Credit spreads (HY and CCC)", s: "Credit", ring: 1, a: 144, d: "d-credit", why: "CCC 13.10% against high yield 3.29% on Oct 19: cracks at the bottom." },
    { id: "pcredit", n: "Private credit stress", s: "Private credit", ring: 1, a: 180, d: "nw-private-credit", why: "BCRED capped redemptions for a third straight quarter; 10 of 16 non-traded BDCs hit the cap in Q2." },
    { id: "consumer", n: "Consumer spending", s: "Consumer", ring: 1, a: 214, d: "nw-consumer", why: "UMich sentiment 46.3 (Oct preliminary), near its record low." },
    { id: "eq", n: "AI book and stocks", s: "AI book", ring: 2, a: 90, m: "eq", d: "d-gross", why: "S&P 500 in the measured edges; the AI book carries more beta." },
    { id: "vix", n: "Volatility", s: "VIX", ring: 2, a: 162, m: "vix", d: "iv-title", why: "18.44 on Oct 19." },
    { id: "gold", n: "Gold", s: "Gold", ring: 2, a: 234, m: "gold", d: "d-inflation", why: "$4,319 average in September." },
    { id: "tlt", n: "Long bonds (TLT)", s: "TLT", ring: 2, a: 306, d: "d-duration", why: "Price moves opposite the yield, about 15.5 times as much." },
    { id: "corr", n: "Stock-bond correlation", s: "Corr.", ring: 2, a: 18, d: "fi-hedge", why: "Positive means bonds fall with stocks: the hedge is broken." },
  ];
  // [from, to, judged weight, why, source]; weights are sigma of the child per sigma of the parent, per step.
  // Edges listed in BR_MEASURED take their weight from the data and ignore the judged value.
  const BR_EDGES = [
    ["hormuz", "oil", 0.60, "Lost Gulf barrels lift physical crude first", "IEA OMR, Oct 14: Dated Brent about $134 against futures about $107"],
    ["oil", "cpi", 0.5, "Fuel feeds the index within the month", "measured"],
    ["oil", "y10", 0.2, "Inflation risk premium", "measured"],
    ["cpi", "y10", 0.1, "Inflation lifts yields", "measured"],
    ["oil", "eq", 0.1, "Energy earnings against everyone else's costs", "measured"],
    ["cpi", "eq", -0.1, "Higher discount rates and squeezed margins", "measured"],
    ["y10", "eq", -0.1, "The discount rate on long-duration growth", "measured"],
    ["eq", "vix", -0.7, "Falling stocks lift implied volatility", "measured"],
    ["y10", "vix", -0.05, "Rates volatility spills into equity volatility", "measured"],
    ["oil", "gold", 0.18, "Both are inflation and geopolitics hedges", "measured"],
    ["y10", "gold", -0.25, "Gold pays nothing: higher yields raise its carrying cost", "measured"],
    ["eq", "gold", -0.05, "Flight to safety", "measured"],
    ["cpi", "fed", 0.40, "The reaction function: inflation above target means hikes", "FOMC minutes, Oct 7: most see another hike by year end"],
    ["fed", "y10", 0.25, "Policy rate expectations anchor the curve", "Judged"],
    ["fed", "eq", -0.15, "Tighter money, lower multiples", "Judged"],
    ["fed", "credit", 0.15, "Floating-rate borrowers pay more", "Judged"],
    ["fed", "liq", -0.30, "Hikes and runoff drain reserves", "Judged"],
    ["fiscal", "tp", 0.35, "More duration to absorb, more premium demanded", "Kim-Wright term premium (FRED THREEFYTP10)"],
    ["tp", "y10", 0.50, "The term premium is part of the yield", "Identity, scaled"],
    ["capex", "fiscal", 0.25, "Hyperscalers fund the build with bonds", "Morgan Stanley: about $570B of AI-related debt in 2026"],
    ["capex", "power", 0.40, "Every campus needs firm power", "PJM 2027/28 auction cleared at the cap"],
    ["capex", "memory", 0.50, "HBM and server DRAM demand", "TrendForce: DRAM revenue up 81% q/q in 1Q26 (headline)"],
    ["capex", "eq", 0.25, "Suppliers book the spend as revenue", "Judged"],
    ["capex", "dep", 0.50, "Today's capex is tomorrow's depreciation", "Fundamentals desk: Microsoft's rises 67% by fiscal 2027"],
    ["capex", "credit", 0.10, "Neoclouds borrow against GPUs", "CoreWeave debt +251% in a year (SEC)"],
    ["eq", "capex", 0.30, "Reflexivity: rising stocks fund more capex", "Soros; equity and debt issuance follow prices"],
    ["power", "capex", -0.20, "Watts cap the build", "Physics desk"],
    ["memory", "capex", -0.10, "Memory costs eat the budget", "Judged"],
    ["power", "cpi", 0.15, "Electricity is in the CPI basket", "Judged"],
    ["memory", "cpi", 0.05, "Device prices pass through", "Manual: OEM price hikes of 15 to 20%"],
    ["dep", "eq", -0.30, "Earnings catch up with cash costs", "Manual 6a: $35B a year at a 4-year life"],
    ["credit", "eq", -0.35, "Credit leads equity in a financing shock", "Judged"],
    ["eq", "credit", -0.30, "Falling equity cushions widen spreads", "Merton: equity is the cushion under debt"],
    ["pcredit", "credit", 0.30, "Private marks leak into public spreads", "BDC discounts to NAV"],
    ["credit", "pcredit", 0.30, "Wider public spreads raise private defaults", "Fitch: record 6% default rate (April)"],
    ["y10", "pcredit", 0.20, "Higher base rates push borrowers to PIK", "Manual: PIK about 11% of loans in Q2"],
    ["pcredit", "consumer", -0.10, "Middle-market lenders pull back; small firms hire less", "Judged"],
    ["liq", "eq", 0.20, "Ample cash supports risk assets", "Judged"],
    ["liq", "credit", -0.20, "Scarce cash widens spreads", "Judged"],
    ["vix", "liq", -0.20, "Margin calls drain liquidity", "Judged"],
    ["vix", "pods", 0.50, "Risk limits force de-grossing", "Aug 2007 quant quake"],
    ["pods", "eq", -0.30, "Crowded longs unwind together", "Manual: pod costs and crowding"],
    ["consumer", "eq", 0.20, "Spending is two-thirds of GDP", "Judged"],
    ["consumer", "cpi", 0.15, "Demand pulls prices", "Judged"],
    ["y10", "consumer", -0.20, "Mortgage and card rates bite", "Judged"],
    ["oil", "consumer", -0.25, "Gasoline is a tax on spending", "Judged"],
    ["cpi", "corr", 0.50, "Inflation-driven yields make bonds fall with stocks", "Findings: the 2.75% line, 1,868 months"],
    ["y10", "tlt", -0.95, "Price moves opposite the yield", "Bond math"],
  ];
  const BR_MEASURED = ["oil>cpi", "oil>y10", "cpi>y10", "oil>eq", "cpi>eq", "y10>eq", "eq>vix", "y10>vix", "oil>gold", "y10>gold", "eq>gold"];
  const BR_PRESETS = [
    { id: "hormuz", n: "Hormuz stays shut", shock: { hormuz: 1.5 } },
    { id: "reopen", n: "Hormuz reopens", shock: { hormuz: -2 } },
    { id: "pivot", n: "Fed pivots to cuts", shock: { fed: -1.5 } },
    { id: "hike", n: "Second hike", shock: { fed: 1 } },
    { id: "capex-cut", n: "Capex cut 20%", shock: { capex: -1.5 } },
    { id: "gpu-life", n: "GPU life reset", shock: { dep: 1.5 } },
    { id: "gates", n: "Private credit gates spread", shock: { pcredit: 1.5 } },
    { id: "supply", n: "Bond supply glut", shock: { fiscal: 1.5 } },
  ];
  const BR_IDX = Object.fromEntries(BR_NODES.map((n, i) => [n.id, i]));
  const BR_DRIVERS = BR_NODES.filter((n) => n.ring === 0).map((n) => n.id);
  const BR = { preset: "hormuz", shock: { hormuz: 1.5 }, target: "eq", blend: 1, K: 6, dataOnly: false, edits: LS.get("bo-brain-edits", {}) || {}, sel: null, wired: false };
  const ekey = (e) => e[0] + ">" + e[1];

  function brainData() { return LIVE.brain && LIVE.brain.regimes ? LIVE.brain : BRAIN_SNAP; }
  // the weight each edge carries under the current regime blend, mode and edits, with its uncertainty
  function brWeights(blend = BR.blend, dataOnly = BR.dataOnly) {
    const R = brainData().regimes, A = R.low_inflation.edges, B = R.inflation.edges;
    return BR_EDGES.map((e) => {
      const k = ekey(e), measured = BR_MEASURED.includes(k) && A[k] && B[k];
      let w = measured ? A[k].w * (1 - blend) + B[k].w * blend : dataOnly ? 0 : e[2];
      let sd = measured ? A[k].se * (1 - blend) + B[k].se * blend : Math.abs(e[2]) * 0.5;
      const edited = fin(BR.edits[k]);
      if (edited) { w = BR.edits[k]; sd = Math.max(0.05, Math.abs(w) * 0.5); }
      return { from: BR_IDX[e[0]], to: BR_IDX[e[1]], key: k, w, sd, measured: !!measured, edited, why: e[3], src: e[4] };
    });
  }
  // x_k = W' x_k-1, order by order; returns the per-order vectors and their sum
  function brPropagate(W, shock, K) {
    const n = BR_NODES.length;
    let x = new Float64Array(n);
    Object.entries(shock).forEach(([id, v]) => { if (BR_IDX[id] != null) x[BR_IDX[id]] = v; });
    const orders = [], total = new Float64Array(n);
    for (let k = 1; k <= K; k++) {
      const nx = new Float64Array(n);
      for (const e of W) if (e.w) nx[e.to] += e.w * x[e.from];
      orders.push(nx);
      for (let i = 0; i < n; i++) total[i] += nx[i];
      x = nx;
    }
    return { orders, total };
  }
  // spectral radius by Gelfand's formula on repeated products: above 1, a shock feeds on itself forever
  function brRadius(W) {
    const n = BR_NODES.length;
    let M = Array.from({ length: n }, (_, i) => { const r = new Float64Array(n); r[i] = 1; return r; }), logn = 0;
    const steps = 48;
    for (let s = 0; s < steps; s++) {
      const N = Array.from({ length: n }, () => new Float64Array(n));
      for (const e of W) if (e.w) for (let j = 0; j < n; j++) N[e.to][j] += e.w * M[e.from][j];
      let norm = 0;
      for (const r of N) for (const v of r) norm += v * v;
      norm = Math.sqrt(norm);
      if (!(norm > 0)) return 0;
      logn += Math.log(norm);
      M = N.map((r) => r.map((v) => v / norm));
    }
    return Math.exp(logn / steps);
  }
  // simple paths from the shocked node to the target, strongest first
  function brPaths(W, from, to, maxLen = 5, floor = 0.002) {
    const out = [], adj = BR_NODES.map(() => []);
    W.forEach((e) => { if (e.w) adj[e.from].push(e); });
    (function walk(node, prod, path, seen) {
      if (path.length > maxLen) return;
      for (const e of adj[node]) {
        if (seen.has(e.to)) continue;
        const p = prod * e.w;
        if (Math.abs(p) < floor) continue;
        const np = path.concat(e.to);
        if (e.to === to) out.push({ nodes: np, gain: p });
        else { seen.add(e.to); walk(e.to, p, np, seen); seen.delete(e.to); }
      }
    })(from, 1, [from], new Set([from]));
    return out.sort((a, b) => Math.abs(b.gain) - Math.abs(a.gain));
  }
  // feedback loops: simple cycles up to five links, each found once (from its lowest-numbered node)
  function brLoops(W, maxLen = 5) {
    const adj = BR_NODES.map(() => []), out = [];
    W.forEach((e) => { if (e.w) adj[e.from].push(e); });
    for (let s = 0; s < BR_NODES.length; s++) {
      (function walk(node, prod, path) {
        if (path.length > maxLen) return;
        for (const e of adj[node]) {
          if (e.to === s && path.length > 1) { out.push({ nodes: path.concat(s), gain: prod * e.w }); continue; }
          if (e.to <= s || path.includes(e.to)) continue;
          walk(e.to, prod * e.w, path.concat(e.to));
        }
      })(s, 1, [s]);
    }
    return out.sort((a, b) => Math.abs(b.gain) - Math.abs(a.gain));
  }
  function brNormal(rnd) { const u = Math.max(rnd(), 1e-12), v = rnd(); return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v); }
  // Monte Carlo over every edge's uncertainty: the share of worlds where the answer keeps its sign
  function brMonteCarlo(W, shock, target, K, draws = 400, seed = 11) {
    const rnd = mulberry32(seed), t = BR_IDX[target], vals = [];
    for (let d = 0; d < draws; d++) {
      const Wd = W.map((e) => (e.w ? Object.assign({}, e, { w: e.w + e.sd * brNormal(rnd) }) : e));
      vals.push(brPropagate(Wd, shock, K).total[t]);
    }
    vals.sort((a, b) => a - b);
    const q = (p) => vals[Math.min(vals.length - 1, Math.max(0, Math.round(p * (vals.length - 1))))];
    return { p10: q(0.1), p50: q(0.5), p90: q(0.9), neg: vals.filter((v) => v < 0).length / vals.length };
  }
  // which edges carry the conclusion: the change in the answer if each edge sat 2 sd from its value
  function brSensitivity(W, shock, target, K) {
    const t = BR_IDX[target], base = brPropagate(W, shock, K).total[t], out = [];
    W.forEach((e, i) => {
      if (!e.w) return;
      const Wb = W.slice(); Wb[i] = Object.assign({}, e, { w: e.w + 0.02 });
      const d = (brPropagate(Wb, shock, K).total[t] - base) / 0.02;
      if (Math.abs(d) > 1e-6) out.push({ e, d, swing: d * 2 * e.sd, flips: Math.abs(d * 2 * e.sd) > Math.abs(base) });
    });
    return out.sort((a, b) => Math.abs(b.swing) - Math.abs(a.swing));
  }
  // the inverse problem: the smallest combination of driver shocks that moves the target by y
  function brInverse(W, target, K, y = -1) {
    const t = BR_IDX[target];
    const m = BR_DRIVERS.map((id) => ({ id, m: brPropagate(W, { [id]: 1 }, K).total[t] }));
    const ss = m.reduce((a, r) => a + r.m * r.m, 0);
    return ss > 0 ? m.map((r) => ({ id: r.id, s: (y * r.m) / ss, m: r.m })).sort((a, b) => Math.abs(b.s) - Math.abs(a.s)) : [];
  }
  // where the regime turns the answer around: blend from 1990-2021 (0) to 2022 on (1)
  function brFlip(shock, target, K) {
    let prev = null, out = null;
    for (let b = 0; b <= 1.0001; b += 0.02) {
      const v = brPropagate(brWeights(b), shock, K).total[BR_IDX[target]];
      if (prev != null && Math.sign(v) !== Math.sign(prev) && Math.abs(v) > 1e-9) { out = b; break; }
      prev = v;
    }
    return out;
  }
  const brName = (i) => BR_NODES[i].s;
  const sg = (v, d = 2) => (fin(v) ? (v > 0.0049 ? "+" : v < -0.0049 ? MINUS : "") + fx(Math.abs(v), d) : "n/a");

  /* ---------- render ---------- */
  function buildBrain() {
    const shockSel = $("#br-shock"), tgtSel = $("#br-target"), edgeSel = $("#br-edge");
    if (!shockSel || BR.wired) return;
    BR_NODES.forEach((n) => { shockSel.append(new Option(n.n, n.id)); tgtSel.append(new Option(n.n, n.id)); });
    BR_EDGES.forEach((e) => edgeSel.append(new Option(`${BR_NODES[BR_IDX[e[0]]].n} → ${BR_NODES[BR_IDX[e[1]]].n}`, ekey(e))));
    const pre = $("#br-presets");
    BR_PRESETS.forEach((p) => {
      const b = h("button", null, p.n);
      b.type = "button"; b.dataset.p = p.id;
      b.addEventListener("click", () => { BR.preset = p.id; BR.shock = Object.assign({}, p.shock); syncBrainControls(); updateBrain(); });
      pre.append(b);
    });
    shockSel.addEventListener("change", () => { BR.preset = null; BR.shock = { [shockSel.value]: Number($("#br-size").value) }; updateBrain(); });
    $("#br-size").addEventListener("input", () => { const id = Object.keys(BR.shock)[0] || shockSel.value; BR.preset = null; BR.shock = { [id]: Number($("#br-size").value) }; updateBrain(); });
    tgtSel.addEventListener("change", () => { BR.target = tgtSel.value; updateBrain(); });
    $("#br-blend").addEventListener("input", () => { BR.blend = Number($("#br-blend").value) / 100; updateBrain(); });
    $("#br-K").addEventListener("input", () => { BR.K = Number($("#br-K").value); updateBrain(); });
    $("#br-mode").querySelectorAll("button").forEach((b) => b.addEventListener("click", () => { BR.dataOnly = b.dataset.v === "data"; updateBrain(); }));
    edgeSel.addEventListener("change", () => { BR.sel = edgeSel.value; syncEdgeEditor(); });
    $("#br-w").addEventListener("input", () => { if (!BR.sel) return; BR.edits[BR.sel] = Number($("#br-w").value); LS.set("bo-brain-edits", BR.edits); updateBrain(); });
    $("#br-w-reset").addEventListener("click", () => { if (BR.sel) delete BR.edits[BR.sel]; LS.set("bo-brain-edits", BR.edits); syncEdgeEditor(); updateBrain(); });
    $("#br-reset-all").addEventListener("click", () => { BR.edits = {}; LS.set("bo-brain-edits", BR.edits); syncEdgeEditor(); updateBrain(); });
    BR.wired = true;
    BR.sel = "y10>eq";
    syncBrainControls();
    syncEdgeEditor();
    updateBrain();
  }
  function syncBrainControls() {
    const id = Object.keys(BR.shock)[0];
    $("#br-shock").value = id;
    $("#br-size").value = BR.shock[id];
    $("#br-target").value = BR.target;
    $("#br-presets").querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", b.dataset.p === BR.preset ? "true" : "false"));
  }
  function syncEdgeEditor() {
    const W = brWeights(), e = W.find((x) => x.key === BR.sel);
    if (!e) return;
    $("#br-edge").value = BR.sel;
    $("#br-w").value = fx(e.w, 2).replace(MINUS, "-");
    $("#br-w-o").textContent = sg(e.w);
    const R = brainData().regimes, m = R.low_inflation.edges[e.key], n = R.inflation.edges[e.key];
    $("#br-edge-note").textContent = e.measured || (m && n)
      ? `Measured: ${sg(m.w)} (±${fx(m.se, 2)}) in ${R.low_inflation.start.slice(0, 4)} to ${R.low_inflation.end.slice(0, 4)}, ${sg(n.w)} (±${fx(n.se, 2)}) since ${R.inflation.start.slice(0, 4)}. ${e.edited ? "You have overridden it." : "Blended by the regime slider."} ${e.why}.`
      : `Judged at ${sg(BR_EDGES.find((x) => ekey(x) === e.key)[2])}, uncertainty ±${fx(e.sd, 2)}. ${e.why}. Source: ${e.src}.${e.edited ? " You have overridden it." : ""}`;
  }

  function updateBrain() {
    if (!$("#br-svg-box")) return;
    const W = brWeights(), K = BR.K, t = BR_IDX[BR.target];
    const res = brPropagate(W, BR.shock, K), rho = brRadius(W);
    const shockId = Object.keys(BR.shock)[0], sIdx = BR_IDX[shockId], size = BR.shock[shockId];
    $("#br-size-o").textContent = sg(size, 1) + "σ";
    $("#br-blend-o").textContent = BR.blend >= 0.995 ? "2022 on" : BR.blend <= 0.005 ? "1990 to 2021" : `${Math.round(BR.blend * 100)}% toward 2022 on`;
    $("#br-K-o").textContent = `${K} order${K > 1 ? "s" : ""}`;
    $("#br-mode").querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", (b.dataset.v === "data") === BR.dataOnly ? "true" : "false"));
    const tot = res.total[t] + (sIdx === t ? size : 0);
    const mc = brMonteCarlo(W, BR.shock, BR.target, K);
    const byOrder = res.orders.map((o) => o[t]);
    const absSum = byOrder.reduce((a, v) => a + Math.abs(v), 0) || 1;
    const paths = sIdx === t ? [] : brPaths(W, sIdx, t);
    const loops = brLoops(W);
    const sens = brSensitivity(W, BR.shock, BR.target, K);
    const inv = brInverse(W, BR.target, K, -1);
    const flip = brFlip(BR.shock, BR.target, K);
    const lowB = brPropagate(brWeights(0), BR.shock, K).total[t], hiB = brPropagate(brWeights(1), BR.shock, K).total[t];
    // readouts
    $("#br-total").textContent = sg(tot) + "σ";
    $("#br-total-k").textContent = `${BR_NODES[t].n} after ${K} orders`;
    const same = tot < 0 ? mc.neg : 1 - mc.neg;
    $("#br-robust").textContent = Math.round(same * 100) + "%";
    $("#br-band").textContent = `${sg(mc.p10)} to ${sg(mc.p90)}`;
    $("#br-rho").textContent = fx(rho, 2);
    const rhoNote = $("#br-rho-note");
    rhoNote.textContent = rho >= 1 ? "Above 1: some loop feeds on itself; read finite horizons only." : rho >= 0.7 ? "High: loops amplify and slow the fade." : "Below 1: shocks fade as they travel.";
    // order bars
    barsH($("#br-orders"), byOrder.map((v, i) => ({ label: i === 0 ? "1st order (direct)" : `${i + 1}${["nd", "rd"][i - 1] || "th"} order`, v, color: v < 0 ? "var(--s1)" : "var(--s2)", lbl: `${sg(v)}σ · ${Math.round((Math.abs(v) / absSum) * 100)}%` })),
      { fmt: (v) => sg(v), label: `Effect on ${BR_NODES[t].n} by order`, labelW: 140, padR: 108 });
    // conclusion
    const c = $("#br-conclusion");
    c.replaceChildren();
    const share2 = byOrder.slice(1).reduce((a, v) => a + Math.abs(v), 0) / absSum;
    const lead = h("p");
    lead.append(h("strong", null, `${sg(size, 1)}σ in ${BR_NODES[sIdx].n} moves ${BR_NODES[t].n} by ${sg(tot)}σ`),
      document.createTextNode(` over ${K} orders; ${Math.round(share2 * 100)}% of it arrives after the first link, where intuition stops looking. The answer keeps its sign in ${Math.round(same * 100)}% of 400 worlds drawn from every edge's uncertainty.`));
    c.append(lead);
    if (paths[0]) {
      const p = h("p");
      p.append(h("strong", null, "Main channel: "), document.createTextNode(paths[0].nodes.map(brName).join(" → ") + ` (${sg(paths[0].gain * size)}σ).`));
      const hidden = paths.find((x) => x.nodes.length >= 4 && Math.sign(x.gain) !== Math.sign(paths[0].gain));
      if (hidden) p.append(document.createTextNode(` A counter-channel pushes the other way: ${hidden.nodes.map(brName).join(" → ")} (${sg(hidden.gain * size)}σ).`));
      c.append(p);
    }
    const reg = h("p");
    reg.append(h("strong", null, "Regime: "), document.createTextNode(`with 1990 to 2021 weights the same shock gives ${sg(lowB)}σ; with 2022-on weights, ${sg(hiB)}σ.` +
      (flip != null ? ` The sign turns ${Math.round(flip * 100)}% of the way from the old regime to the new one.` : Math.abs(hiB) > Math.abs(lowB) * 1.5 && Math.abs(lowB) > 0.01 ? ` The new regime makes it ${fx(hiB / lowB, 1)} times as large.` : "")));
    c.append(reg);
    if (sens[0]) {
      const s0 = sens[0], p = h("p");
      p.append(h("strong", null, "Load-bearing assumption: "), document.createTextNode(`${BR_NODES[s0.e.from].n} → ${BR_NODES[s0.e.to].n} at ${sg(s0.e.w)} (${s0.e.measured ? "measured" : s0.e.edited ? "your override" : "judged"}). Two standard deviations of doubt on it move the answer by ${sg(s0.swing)}σ${s0.flips ? ", enough to flip its sign" : ""}.`));
      c.append(p);
    }
    // lists
    const pl = $("#br-paths");
    pl.replaceChildren();
    (paths.length ? paths.slice(0, 6) : []).forEach((p) => { const li = h("li"); li.append(h("span", null, p.nodes.map(brName).join(" → ")), h("b", "num", sg(p.gain * size) + "σ")); pl.append(li); });
    if (!paths.length) pl.append(h("li", "none", sIdx === t ? "The shock and the target are the same node." : "No path above 0.002σ links these two nodes."));
    const ll = $("#br-loops");
    ll.replaceChildren();
    loops.slice(0, 6).forEach((L) => { const li = h("li"); li.append(h("span", null, L.nodes.map(brName).join(" → ")), h("b", "num " + (L.gain > 0 ? "warm" : "cool"), (L.gain > 0 ? "Reinforcing " : "Balancing ") + sg(L.gain, 3))); ll.append(li); });
    const sl = $("#br-sens");
    sl.replaceChildren();
    sens.slice(0, 5).forEach((s) => { const li = h("li"); li.append(h("span", null, `${BR_NODES[s.e.from].s} → ${BR_NODES[s.e.to].s}${s.e.measured ? " (measured)" : ""}`), h("b", "num", `±${fx(Math.abs(s.swing), 2)}σ${s.flips ? " · can flip" : ""}`)); sl.append(li); });
    const il = $("#br-inverse");
    il.replaceChildren();
    inv.slice(0, 4).forEach((r) => { const li = h("li"); li.append(h("span", null, BR_NODES[BR_IDX[r.id]].n), h("b", "num", sg(r.s, 2) + "σ")); il.append(li); });
    $("#br-inverse-t").textContent = BR_NODES[t].n;
    // table view
    fillTable($("#br-table"), ["Node", "Response, σ", "Now, 3-month z", "Kind"], BR_NODES.map((n, i) => {
      const st = n.m && brainData().state && brainData().state[n.m];
      return [n.n, sg(res.total[i] + (i === sIdx ? size : 0)), st ? sg(st.z3m, 1) : "n/a", n.m ? "Measured" : "Judged"];
    }), 1);
    drawBrain(W, res, sIdx, t, size);
    syncEdgeEditor();
  }

  function drawBrain(W, res, sIdx, t, size) {
    const box = $("#br-svg-box");
    if (!box || !box.clientWidth) return;
    const narrow = Wd0() < 560;
    function Wd0() { return boxWidth(box); }
    const Wd = boxWidth(box), Hd = narrow ? Math.round(Wd * 1.18) : Math.round(Math.min(680, Math.max(420, Wd * 0.72))), cx = Wd / 2, cy = Hd / 2, R = Math.min(Wd, Hd) / 2 - (narrow ? 30 : 46);
    const radii = [R, R * 0.64, R * 0.27];
    const pos = BR_NODES.map((n) => { const a = (n.a * Math.PI) / 180, r = radii[n.ring]; return [cx + r * Math.cos(a), cy + r * Math.sin(a)]; });
    const resp = BR_NODES.map((_, i) => res.total[i] + (i === sIdx ? size : 0));
    box.replaceChildren();
    const s = svg("svg", { viewBox: `0 0 ${Wd} ${Hd}`, width: Wd, height: Hd, role: "group", "aria-label": "The brain: nodes are parts of the system, lines are signed links; glow shows each node's response to the shock" }, box);
    const defs = svg("defs", {}, s);
    const rg = svg("radialGradient", { id: "br-bg", cx: "50%", cy: "50%", r: "65%" }, defs);
    svg("stop", { offset: "0%", "stop-color": "#1b1640" }, rg); svg("stop", { offset: "55%", "stop-color": "#0d0b22" }, rg); svg("stop", { offset: "100%", "stop-color": "#05050d" }, rg);
    const fl = svg("filter", { id: "br-glow", x: "-80%", y: "-80%", width: "260%", height: "260%" }, defs);
    svg("feGaussianBlur", { stdDeviation: "7" }, fl);
    svg("rect", { x: 0, y: 0, width: Wd, height: Hd, rx: 16, fill: "url(#br-bg)" }, s);
    radii.forEach((r, i) => svg("circle", { cx, cy, r, fill: "none", stroke: "#3b3670", "stroke-opacity": 0.55 - i * 0.12, "stroke-dasharray": i === 1 ? "2 6" : "none" }, s));
    // flows: each edge carries |w * x(from)| summed over orders
    const flow = W.map((e) => res.orders.reduce((a, o, k) => a + Math.abs(e.w * (k === 0 ? (e.from === sIdx ? size : 0) : res.orders[k - 1][e.from])), 0));
    const maxF = Math.max(1e-9, ...flow);
    const gE = svg("g", {}, s);
    W.forEach((e, i) => {
      if (!e.w) return;
      const [x1, y1] = pos[e.from], [x2, y2] = pos[e.to];
      const mx = (x1 + x2) / 2, my = (y1 + y2) / 2, pull = 0.35;
      const qx = mx + (cx - mx) * pull, qy = my + (cy - my) * pull;
      const d = `M${x1.toFixed(1)},${y1.toFixed(1)} Q${qx.toFixed(1)},${qy.toFixed(1)} ${x2.toFixed(1)},${y2.toFixed(1)}`;
      const f = flow[i] / maxF, active = f > 0.04;
      const col = e.w > 0 ? "#ff9e5e" : "#5ec8ff";
      const p = svg("path", { d, fill: "none", stroke: col, "stroke-width": (0.6 + 3.2 * Math.min(1, Math.abs(e.w))).toFixed(2), "stroke-opacity": (active ? 0.35 + 0.6 * f : 0.16).toFixed(2), class: "br-edge" + (active ? " flow" : "") + (e.key === BR.sel ? " sel" : "") + (e.measured ? "" : " judged") }, gE);
      if (active) p.style.animationDuration = (2.6 - 1.9 * f).toFixed(2) + "s";
      const hit = svg("path", { d, fill: "none", stroke: "transparent", "stroke-width": 12, class: "br-hit", tabindex: "-1", "aria-label": `${BR_NODES[e.from].n} to ${BR_NODES[e.to].n}: ${sg(e.w)}` }, gE);
      hit.addEventListener("click", () => { BR.sel = e.key; syncEdgeEditor(); updateBrain(); $("#br-w").focus(); });
      bindTip(hit, () => [[sg(e.w) + (e.measured ? " measured" : e.edited ? " your override" : " judged"), `${BR_NODES[e.from].n} → ${BR_NODES[e.to].n}: ${e.why}`]]);
    });
    const maxR = Math.max(0.05, ...resp.map(Math.abs));
    BR_NODES.forEach((n, i) => {
      const [x, y] = pos[i], v = resp[i], m = Math.abs(v) / maxR;
      const g = svg("g", { class: "br-node", tabindex: "0", role: "button", "aria-label": `${n.n}: response ${sg(v)} sigma. Enter shocks it; T makes it the target.` }, s);
      const warm = v > 0, hue = warm ? "#ff7a59" : "#45b8ff";
      if (m > 0.02) {
        const halo = svg("circle", { cx: x, cy: y, r: (14 + 30 * m).toFixed(1), fill: hue, opacity: (0.25 + 0.5 * m).toFixed(2), filter: "url(#br-glow)", class: "br-halo" }, g);
        halo.style.animationDuration = (3.2 - 1.6 * m).toFixed(2) + "s";
      }
      const core = n.ring === 2 ? 13 : 11;
      svg("circle", { cx: x, cy: y, r: core, fill: "#151233", stroke: i === sIdx ? "#ffd166" : i === t ? "#ffffff" : n.m ? "#9fe3c9" : "#8f88c9", "stroke-width": i === sIdx || i === t ? 2.6 : 1.4, "stroke-dasharray": i === t && i !== sIdx ? "3 2" : "none" }, g);
      svg("circle", { cx: x, cy: y, r: Math.max(2.5, core * 0.45 * Math.min(1, m + 0.2)), fill: m > 0.02 ? hue : "#5b5591" }, g);
      const right = Math.cos((n.a * Math.PI) / 180) >= -0.2, below = narrow || n.ring === 2;
      const lx = below ? Math.min(Wd - 34, Math.max(34, x)) : x + (right ? core + 6 : -core - 6), ly = below ? y + core + 12 : y + 4;
      const anchor = below ? "middle" : right ? "start" : "end";
      const lab = text(g, lx, ly, n.s, "br-label" + (narrow ? " small" : ""), anchor);
      if (m > 0.02 && (!narrow || m > 0.3 || i === sIdx || i === t)) text(g, lx, ly + (narrow ? 11 : 13), sg(v) + "σ", "br-val" + (warm ? " warm" : " cool") + (narrow ? " small" : ""), anchor);
      lab.setAttribute("font-weight", i === sIdx || i === t ? "700" : "500");
      const pick = (asTarget) => { if (asTarget) BR.target = n.id; else { BR.preset = null; BR.shock = { [n.id]: Number($("#br-size").value) || 1 }; } syncBrainControls(); updateBrain(); };
      g.addEventListener("click", (ev) => pick(ev.shiftKey || ev.altKey));
      g.addEventListener("keydown", (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); pick(false); } else if (ev.key === "t" || ev.key === "T") { ev.preventDefault(); pick(true); } });
      bindTip(g, () => [[`${sg(v)}σ`, `${n.n}${n.m ? " · measured node" : ""}. ${n.why}`]]);
    });
    text(s, 14, Hd - 12, narrow ? "Tap a node to shock it · tap a line to edit it" : "Click a node to shock it · shift-click to make it the target · click a line to edit it", "br-hintline", "start");
  }
  function renderBrainMeasured() {
    const t = $("#br-meas");
    if (!t) return;
    const D = brainData(), R = D.regimes, A = R.low_inflation, B = R.inflation;
    fillTable(t, ["Link", `${A.start.slice(0, 4)} to ${A.end.slice(0, 4)}`, `Since ${B.start.slice(0, 4)}`, "Change"], BR_MEASURED.map((k) => {
      const [f, to] = k.split(">"), a = A.edges[k], b = B.edges[k];
      return [`${BR_NODES[BR_IDX[f]].s} → ${BR_NODES[BR_IDX[to]].s}`, `${sg(a.w)} (t ${sg(a.w / a.se, 1)})`, `${sg(b.w)} (t ${sg(b.w / b.se, 1)})`, sg(b.w - a.w)];
    }), 1);
    const c = D.corr || D.y10_eq_corr || {};
    $("#br-meas-note").textContent = `Standardized monthly changes, ${A.months} and ${B.months} months. The monthly correlation of 10-year yield changes with stock returns went from ${sg(c.low_inflation)} to ${sg(c.inflation)}: rising yields used to mean good growth news; now they mean inflation, and stocks fall. The second regime is short, so its standard errors are about three times wider.`;
  }

  /* =====================================================================================
     brain.js (v0.6, v0.8): the system as a signed, weighted graph, and (v0.8) a reasoner over it. Shocks propagate order by order
     (x_k = W' x_k-1), so the desk can show what arrives first, second, third and fourth.
     Eleven edges are measured from monthly data in two regimes (BRAIN_SNAP, or data/brain.json);
     the rest are judged, labelled as such, and editable. Nothing here is a forecast: it is a
     consistent way to carry assumptions to their conclusions, and to see which ones carry the weight.
     ===================================================================================== */
  // ring 0 = drivers (outside), 1 = transmission, 2 = markets, 3 = holdings, 4 = the book (centre); a = angle in degrees, 0 = right, clockwise
  const BR_NODES = [
    { id: "hormuz", n: "Hormuz disruption", s: "Hormuz", ring: 0, a: 205, d: "nw-oil-physical", why: "Tankers through the strait: 4 a day on Oct 4 against 85 before the war (IMF PortWatch via Straits.live)." },
    { id: "oil", n: "Oil, physical", s: "Oil", ring: 0, a: 240, m: "oil", d: "fi-oil", why: "EIA spot Brent, monthly average. Measured edges start here." },
    { id: "fed", n: "Fed policy path", s: "Fed", ring: 0, a: 274, d: "nw-fed-hike", why: "3.75 to 4.00% after the Sep 16 hike; Oct 28 decision." },
    { id: "fiscal", n: "Treasury and tech bond supply", s: "Supply", ring: 0, a: 308, d: "pp-title", why: "Deficits plus record hyperscaler bond issuance add duration the market must absorb." },
    { id: "capex", n: "AI capex", s: "AI capex", ring: 0, a: 342, d: "fund-table", why: "About $725B of 2026 guidance across four hyperscalers (April)." },
    { id: "memory", n: "Memory prices", s: "Memory", ring: 0, a: 22, d: "nw-memory", why: "DDR5 contracts +57% in Q1 and +50% in Q2 2026; HBM sold out for 2026." },
    { id: "power", n: "Grid power prices", s: "Power", ring: 0, a: 58, d: "nw-power", why: "PJM 2027/28 capacity cleared at the cap, about 6.6 GW (6,623 MW) short of the reliability target." },
    { id: "aidemand", n: "AI end demand", s: "AI demand", ring: 0, a: 118, d: "nw-saas", why: "Paid use of AI by businesses and consumers: the revenue that has to justify the build." },
    { id: "cpi", n: "Consumer prices", s: "CPI", ring: 1, a: 246, m: "cpi", d: "d-duration", why: "CPI-U: 3.7% over the year to September; 3.6% annualized over three months." },
    { id: "y10", n: "10-year yield", s: "10-year", ring: 1, a: 284, m: "y10", d: "rates-title", why: "5.15% on Oct 19 (Treasury)." },
    { id: "tp", n: "Term premium", s: "Term prem.", ring: 1, a: 318, d: "rates-title", why: "The extra yield for holding duration; supply pushes it up." },
    { id: "dep", n: "Depreciation catch-up", s: "Depreciation", ring: 1, a: 12, d: "bs-depr-title", why: "Server lives of 5 to 6 years against 2 to 3 years of frontier economic life." },
    { id: "pods", n: "Pod crowding and de-grossing", s: "Pods", ring: 1, a: 54, d: "pr-pods-title", why: "Multi-manager AUM grew 175% from 2017 to 2023 (per the field manual); crowded longs unwind together." },
    { id: "liq", n: "Funding liquidity", s: "Liquidity", ring: 1, a: 100, d: "liq-title", why: "Reverse repo is empty ($0.33B), so drains hit bank reserves." },
    { id: "credit", n: "Credit spreads (HY and CCC)", s: "Credit", ring: 1, a: 144, d: "d-credit", why: "CCC 13.10% against high yield 3.29% on Oct 19: cracks at the bottom." },
    { id: "pcredit", n: "Private credit stress", s: "Private credit", ring: 1, a: 180, d: "nw-private-credit", why: "BCRED capped redemptions for a third straight quarter; 10 of 16 non-traded BDCs hit the cap in Q2." },
    { id: "consumer", n: "Consumer spending", s: "Consumer", ring: 1, a: 214, d: "nw-consumer", why: "UMich sentiment 46.3 (Oct preliminary), near its record low." },
    { id: "dollar", n: "The dollar", s: "Dollar", ring: 1, a: 344, d: "rates-title", why: "Tighter Fed policy lifts the dollar; a strong dollar weighs on gold and on multinational earnings." },
    { id: "earn", n: "AI earnings revisions", s: "Earnings", ring: 1, a: 77, d: "fund-table", why: "Analysts' estimates for the builders and their suppliers: where demand, capex and depreciation meet the P&L." },
    { id: "eq", n: "AI book and stocks", s: "AI book", ring: 2, a: 90, m: "eq", d: "d-gross", why: "S&P 500 in the measured edges; the AI book carries more beta." },
    { id: "vix", n: "Volatility", s: "VIX", ring: 2, a: 162, m: "vix", d: "iv-title", why: "18.44 on Oct 19." },
    { id: "gold", n: "Gold", s: "Gold", ring: 2, a: 234, m: "gold", d: "d-inflation", why: "$4,319 average in September." },
    { id: "tlt", n: "Long bonds (TLT)", s: "TLT", ring: 2, a: 306, d: "d-duration", why: "Price moves opposite the yield, about 15.5 times as much." },
    { id: "corr", n: "Stock-bond correlation", s: "Corr.", ring: 2, a: 18, d: "fi-hedge", why: "Positive means bonds fall with stocks: the hedge is broken." },
    { id: "NVDA", n: "Nvidia", s: "NVDA", ring: 3, a: 270, h: 0.14, d: "fund-table", why: "Sells the GPUs: revenue rises with capex." },
    { id: "AVGO", n: "Broadcom", s: "AVGO", ring: 3, a: 310, h: 0.08, d: "fund-table", why: "Custom accelerators and networking: capex is revenue." },
    { id: "MSFT", n: "Microsoft", s: "MSFT", ring: 3, a: 350, h: 0.14, d: "fund-table", why: "Spends on the build; earns from cloud and software." },
    { id: "GOOGL", n: "Alphabet", s: "GOOGL", ring: 3, a: 30, h: 0.14, d: "fund-table", why: "Spends on the build; marks private AI stakes through income." },
    { id: "AMZN", n: "Amazon", s: "AMZN", ring: 3, a: 70, h: 0.14, d: "fund-table", why: "Largest spender; capex above operating cash flow." },
    { id: "META", n: "Meta", s: "META", ring: 3, a: 110, h: 0.12, d: "fund-table", why: "Spends on the build, earns from ads: consumer and capex at once." },
    { id: "ORCL", n: "Oracle", s: "ORCL", ring: 3, a: 150, h: 0.06, d: "fund-table", why: "Debt-funded build against a large backlog: credit matters most here." },
    { id: "TSLA", n: "Tesla", s: "TSLA", ring: 3, a: 190, h: 0.10, d: "fund-table", why: "Long-duration growth: rates and the consumer." },
    { id: "SPCX", n: "SpaceX", s: "SPCX", ring: 3, a: 230, h: 0.08, d: "fund-table", why: "Listed June 2026: liquidity and rates set its multiple." },
    { id: "book", n: "Your model book", s: "Book", ring: 4, a: 90, d: "d-gross", why: "The model book's weights times each holding's response (an approximation in σ units: it ignores diversification)." },
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
    ["cpi", "corr", 0.50, "Inflation-driven yields make bonds fall with stocks", "Findings: inflation band 2.75 to 4.25%, 1,833 windows"],
    ["y10", "tlt", -0.95, "Price moves opposite the yield", "Bond math"],
    // v0.8: demand, the dollar, earnings, and the holdings (all judged; the book weights are config.toml)
    ["aidemand", "capex", 0.45, "Demand pulls the build", "Judged"],
    ["aidemand", "earn", 0.45, "Paid use becomes revenue", "Judged"],
    ["aidemand", "eq", 0.15, "Growth narratives lift the market", "Judged"],
    ["capex", "earn", 0.25, "Suppliers book the spend as revenue", "Fundamentals desk"],
    ["dep", "earn", -0.35, "Depreciation catches up with the spenders' earnings", "Buyside 2026, depreciation table"],
    ["consumer", "earn", 0.15, "Ads, devices and retail", "Judged"],
    ["fed", "dollar", 0.35, "Higher rates attract capital", "Judged"],
    ["dollar", "gold", -0.30, "Gold is priced in dollars", "Judged"],
    ["dollar", "eq", -0.10, "Overseas earnings translate into fewer dollars", "Judged"],
    ["eq", "NVDA", 0.55, "Market beta", "Judged; exposures desk"], ["eq", "AVGO", 0.55, "Market beta", "Judged; exposures desk"],
    ["eq", "MSFT", 0.60, "Market beta", "Judged; exposures desk"], ["eq", "GOOGL", 0.60, "Market beta", "Judged; exposures desk"],
    ["eq", "AMZN", 0.60, "Market beta", "Judged; exposures desk"], ["eq", "META", 0.55, "Market beta", "Judged; exposures desk"],
    ["eq", "ORCL", 0.45, "Market beta", "Judged; exposures desk"], ["eq", "TSLA", 0.45, "Market beta", "Judged; exposures desk"],
    ["eq", "SPCX", 0.35, "Market beta (short history, shrunk toward TSLA)", "Judged; exposures desk"],
    ["earn", "NVDA", 0.35, "Supplier revenue", "Judged"], ["earn", "AVGO", 0.30, "Supplier revenue", "Judged"],
    ["earn", "MSFT", 0.25, "Cloud revenue against depreciation", "Judged"], ["earn", "GOOGL", 0.25, "Cloud and search", "Judged"],
    ["earn", "AMZN", 0.20, "AWS", "Judged"], ["earn", "META", 0.25, "Ads efficiency", "Judged"], ["earn", "ORCL", 0.20, "Backlog conversion", "Judged"],
    ["earn", "TSLA", 0.10, "Autonomy optionality", "Judged"],
    ["capex", "NVDA", 0.35, "The build is Nvidia's revenue", "Fundamentals desk"], ["capex", "AVGO", 0.30, "Custom chips and networking", "Judged"],
    ["capex", "ORCL", 0.15, "Capacity to fill the backlog", "Judged"],
    ["dep", "MSFT", -0.12, "Depreciation catch-up", "Buyside 2026"], ["dep", "GOOGL", -0.12, "Depreciation catch-up", "Buyside 2026"],
    ["dep", "AMZN", -0.12, "Depreciation catch-up", "Buyside 2026"], ["dep", "META", -0.15, "Depreciation catch-up", "Buyside 2026"],
    ["dep", "ORCL", -0.15, "Depreciation catch-up", "Buyside 2026"],
    ["power", "ORCL", -0.12, "Campuses wait for power", "Judged"], ["power", "MSFT", -0.05, "Power costs", "Judged"], ["power", "AMZN", -0.05, "Power costs", "Judged"],
    ["memory", "NVDA", -0.08, "HBM costs squeeze margins", "Judged"], ["memory", "META", -0.05, "Server costs", "Judged"],
    ["credit", "ORCL", -0.25, "Debt-funded build: credit spreads set its cost", "Fundamentals desk: Oracle's net debt"],
    ["credit", "TSLA", -0.08, "Auto credit", "Judged"], ["credit", "SPCX", -0.15, "Risk appetite for new issues", "Judged"],
    ["y10", "TSLA", -0.15, "Long-duration growth", "Judged"], ["y10", "SPCX", -0.12, "Long-duration growth", "Judged"], ["y10", "NVDA", -0.05, "Discount rate", "Judged"],
    ["consumer", "TSLA", 0.20, "Car buyers", "Judged"], ["consumer", "AMZN", 0.12, "Retail", "Judged"], ["consumer", "META", 0.10, "Ad budgets", "Judged"],
    ["liq", "SPCX", 0.20, "New listings need liquidity", "Judged"],
    ["pods", "NVDA", -0.15, "The most crowded long", "Judged"], ["pods", "META", -0.10, "Crowded long", "Judged"],
    ["NVDA", "book", 0.14, "Book weight", "config.toml"], ["AVGO", "book", 0.08, "Book weight", "config.toml"], ["MSFT", "book", 0.14, "Book weight", "config.toml"],
    ["GOOGL", "book", 0.14, "Book weight", "config.toml"], ["AMZN", "book", 0.14, "Book weight", "config.toml"], ["META", "book", 0.12, "Book weight", "config.toml"],
    ["ORCL", "book", 0.06, "Book weight", "config.toml"], ["TSLA", "book", 0.10, "Book weight", "config.toml"], ["SPCX", "book", 0.08, "Book weight", "config.toml"],
    ["tlt", "book", 0.0, "Your TLT hedge (off today: edit it to add one)", "Policy hedge.tlt.v2"],
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
    { id: "demand-stall", n: "AI demand stalls", shock: { aidemand: -1.5 } },
    { id: "demand-surprise", n: "AI demand surprise", shock: { aidemand: 1.5 } },
  ];
  const BR_IDX = Object.fromEntries(BR_NODES.map((n, i) => [n.id, i]));
  const BR_DRIVERS = BR_NODES.filter((n) => n.ring === 0).map((n) => n.id);
  const BR_ROOTS = BR_NODES.filter((n) => n.ring === 0 || n.id === "pods" || n.id === "pcredit").map((n) => n.id);
  const BR_HOLD = BR_NODES.filter((n) => n.ring === 3).map((n) => n.id);
  const BR = { preset: "hormuz", shock: { hormuz: 1.5 }, target: "book", blend: 1, K: 6, dataOnly: false, edits: LS.get("bo-brain-edits", {}) || {}, sel: null, wired: false,
    view: "shock", obs: LS.get("bo-brain-obs", {}) || {}, focus: null, thought: null, step: -1, timer: null };
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
  /* ---------- v0.8: the reasoner (mirrors buildout/thinking.py) ---------- */
  // T = sum_{k=0..K} (W')^k: the effect on every node of a unit shock at every node within K links
  function brTotal(W, K) {
    const n = BR_NODES.length;
    let P = Array.from({ length: n }, (_, i) => { const r = new Float64Array(n); r[i] = 1; return r; });
    const T = P.map((r) => Float64Array.from(r));
    for (let k = 0; k < K; k++) {
      const N = Array.from({ length: n }, () => new Float64Array(n));
      for (const e of W) if (e.w) { const src = P[e.from], dst = N[e.to]; for (let j = 0; j < n; j++) dst[j] += e.w * src[j]; }
      P = N;
      for (let i = 0; i < n; i++) for (let j = 0; j < n; j++) T[i][j] += P[i][j];
    }
    return T;
  }
  function matInv(M) {
    const n = M.length, A = M.map((r, i) => r.map(Number).concat(Array.from({ length: n }, (_, j) => (i === j ? 1 : 0))));
    for (let c = 0; c < n; c++) {
      let p = c;
      for (let r = c + 1; r < n; r++) if (Math.abs(A[r][c]) > Math.abs(A[p][c])) p = r;
      if (Math.abs(A[p][c]) < 1e-14) throw new Error("singular");
      [A[c], A[p]] = [A[p], A[c]];
      const pv = A[c][c];
      for (let k = 0; k < 2 * n; k++) A[c][k] /= pv;
      for (let r = 0; r < n; r++) if (r !== c && A[r][c] !== 0) { const f = A[r][c]; for (let k = 0; k < 2 * n; k++) A[r][k] -= f * A[c][k]; }
    }
    return A.map((r) => r.slice(n));
  }
  // the root shocks that best explain what was observed (ridge MAP), with their uncertainty
  function brAbduce(T, observed, roots, obsSd = 0.5, priorSd = 1.0) {
    const obs = Object.keys(observed).map(Number).sort((a, b) => a - b), y = obs.map((i) => observed[i]);
    const A = obs.map((i) => roots.map((r) => T[i][r])), lam = (obsSd / priorSd) ** 2, m = roots.length;
    const M = Array.from({ length: m }, (_, a) => Array.from({ length: m }, (__, b) => A.reduce((acc, row) => acc + row[a] * row[b], 0) + (a === b ? lam : 0)));
    const Minv = matInv(M), Aty = roots.map((_, a) => A.reduce((acc, row, i) => acc + row[a] * y[i], 0));
    const sv = Minv.map((row) => row.reduce((acc, v, b) => acc + v * Aty[b], 0));
    const cov = Minv.map((row) => row.map((v) => v * obsSd * obsSd));
    const fit = A.map((row) => row.reduce((acc, v, b) => acc + v * sv[b], 0));
    const ssy = y.reduce((a, v) => a + v * v, 0), ssr = y.reduce((a, v, i) => a + (v - fit[i]) ** 2, 0);
    return { obs, y, roots: roots.slice(), s: sv, sd: cov.map((r, i) => Math.sqrt(r[i])), cov, fit, explained: ssy > 0 ? 1 - ssr / ssy : 0 };
  }
  function brPredict(T, ab) {
    const n = T.length, mean = [], sd = [];
    for (let i = 0; i < n; i++) {
      const t = ab.roots.map((r) => T[i][r]);
      mean.push(t.reduce((a, v, j) => a + v * ab.s[j], 0));
      let v2 = 0;
      for (let a = 0; a < t.length; a++) for (let b = 0; b < t.length; b++) v2 += t[a] * ab.cov[a][b] * t[b];
      sd.push(Math.sqrt(Math.max(v2, 0)));
    }
    return { mean, sd };
  }
  // what the map cannot explain, and the link whose change would cut the misfit fastest
  function brCriticize(W, K, ab, obsSd = 0.5, hstep = 1e-4) {
    const sv = ab.s;
    const misfit = (Wx) => { const T = brTotal(Wx, K); return ab.obs.reduce((a, o, i) => { const f = ab.roots.reduce((acc, r, j) => acc + T[o][r] * sv[j], 0); return a + (ab.y[i] - f) ** 2; }, 0); };
    const base = misfit(W);
    const grad = W.map((e, i) => { if (!e.w) return 0; const W2 = W.slice(); W2[i] = Object.assign({}, e, { w: e.w + hstep }); return (misfit(W2) - base) / hstep; });
    return { resid: ab.y.map((v, i) => (v - ab.fit[i]) / obsSd), misfit: base, grad };
  }
  function logEvidence(y, a, obsSd, priorSd) {
    const n = y.length, s2 = obsSd * obsSd, yy = y.reduce((acc, v) => acc + v * v, 0);
    if (!a) return -0.5 * (n * Math.log(2 * Math.PI * s2) + yy / s2);
    const aa = a.reduce((acc, v) => acc + v * v, 0), ay = a.reduce((acc, v, i) => acc + v * y[i], 0), c = s2 + priorSd * priorSd * aa;
    const q = (yy - (priorSd * priorSd * ay * ay) / c) / s2;
    return -0.5 * (n * Math.log(2 * Math.PI) + (n - 1) * Math.log(s2) + Math.log(c) + q);
  }
  // single-cause hypotheses ranked by exact Bayesian evidence, with "nothing happened" as a contender
  function brExplanations(T, observed, roots, obsSd = 0.5, priorSd = 1.0) {
    const obs = Object.keys(observed).map(Number).sort((a, b) => a - b), y = obs.map((i) => observed[i]);
    const rows = [{ root: null, logev: logEvidence(y, null, obsSd, priorSd), s: 0, s_sd: 0 }];
    roots.forEach((r) => {
      const a = obs.map((i) => T[i][r]), aa = a.reduce((acc, v) => acc + v * v, 0), ay = a.reduce((acc, v, i) => acc + v * y[i], 0);
      const pv = 1 / (aa / (obsSd * obsSd) + 1 / (priorSd * priorSd));
      rows.push({ root: r, logev: logEvidence(y, a, obsSd, priorSd), s: (pv * ay) / (obsSd * obsSd), s_sd: Math.sqrt(pv) });
    });
    const m = Math.max(...rows.map((r) => r.logev)), z = rows.reduce((acc, r) => acc + Math.exp(r.logev - m), 0);
    rows.forEach((r) => { r.p = Math.exp(r.logev - m) / z; });
    return rows.sort((a, b) => b.p - a.p);
  }
  function mixtureEntropy(ws, mus, sds, grid = 801) {
    const lo = Math.min(...mus.map((m, i) => m - 7 * sds[i])), hi = Math.max(...mus.map((m, i) => m + 7 * sds[i])), dx = (hi - lo) / (grid - 1);
    let tot = 0;
    for (let g = 0; g < grid; g++) {
      const x = lo + g * dx;
      let d = 0;
      for (let k = 0; k < ws.length; k++) d += ws[k] * Math.exp(-0.5 * ((x - mus[k]) / sds[k]) ** 2) / (sds[k] * Math.sqrt(2 * Math.PI));
      if (d > 0) tot += -d * Math.log(d);
    }
    return tot * dx;
  }
  // which unobserved node would best tell the explanations apart (mutual information, nats)
  function brNextObservation(T, hyps, candidates, obsSd = 0.5, top = 6) {
    const hs = hyps.filter((r) => r.p > 1e-6).slice(0, top), tot = hs.reduce((a, r) => a + r.p, 0), ws = hs.map((r) => r.p / tot);
    return candidates.map((u) => {
      const mus = [], sds = [];
      hs.forEach((r) => {
        if (r.root == null) { mus.push(0); sds.push(obsSd); return; }
        const g = T[u][r.root];
        mus.push(g * r.s); sds.push(Math.sqrt(g * g * r.s_sd * r.s_sd + obsSd * obsSd));
      });
      const cond = ws.reduce((a, w, k) => a + w * 0.5 * Math.log(2 * Math.PI * Math.E * sds[k] * sds[k]), 0);
      return { node: u, info: Math.max(0, mixtureEntropy(ws, mus, sds) - cond), means: mus };
    }).sort((a, b) => b.info - a.info);
  }
  // do(node = v): cut the node's incoming links, then propagate
  function brIntervene(W, K, node, v) {
    const T = brTotal(W.filter((e) => e.to !== node), K);
    return T.map((row) => row[node] * v);
  }
  function brShared(T, holdings, roots) {
    const V = holdings.map((hh) => roots.map((r) => T[hh][r])), nr = V.map((r) => Math.sqrt(r.reduce((a, v) => a + v * v, 0)) || 1);
    return { sens: V, cos: V.map((a, i) => V.map((b, j) => a.reduce((acc, v, k) => acc + v * b[k], 0) / (nr[i] * nr[j]))) };
  }
  function brThink(W, K, observed, rootIds = BR_ROOTS, holdIds = BR_HOLD, obsSd = 0.5, priorSd = 1.0) {
    const T = brTotal(W, K), roots = rootIds.map((id) => BR_IDX[id]), holds = holdIds.map((id) => BR_IDX[id]);
    const ab = brAbduce(T, observed, roots, obsSd, priorSd), pr = brPredict(T, ab), cr = brCriticize(W, K, ab, obsSd);
    const ex = brExplanations(T, observed, roots, obsSd, priorSd);
    const cand = BR_NODES.map((_, i) => i).filter((i) => !(i in observed));
    return { T, abduce: ab, predict: pr, criticize: cr, explanations: ex, next: brNextObservation(T, ex, cand, obsSd), shared: brShared(T, holds, roots) };
  }

  const brName = (i) => BR_NODES[i].s;
  const sg = (v, d = 2) => (fin(v) ? (v > 0.0049 ? "+" : v < -0.0049 ? MINUS : "") + fx(Math.abs(v), d) : "n/a");

  /* ---------- v0.8: what the brain observes, and how it reasons about it ---------- */
  // measured nodes start from their latest 3-month change in standard deviations; the reader can add, change or drop any
  function brObserved() {
    const st = brainData().state || {}, out = {}, src = {};
    BR_NODES.forEach((n, i) => { if (n.m && st[n.m] && fin(st[n.m].z3m)) { out[i] = st[n.m].z3m; src[i] = `data, 3 months to ${st[n.m].month}`; } });
    Object.entries(BR.obs || {}).forEach(([id, v]) => {
      const i = BR_IDX[id];
      if (i == null) return;
      if (v === "off") { delete out[i]; delete src[i]; } else if (fin(v)) { out[i] = clamp(v, -4, 4); src[i] = "your observation"; }
    });
    return { values: out, src };
  }
  function brTrace(th, ob, W) {
    const steps = [], ex = th.explanations, ab = th.abduce, pr = th.predict, cr = th.criticize, obsIdx = ab.obs;
    const name = (i) => BR_NODES[i].n, hyp = (r) => (r.root == null ? "nothing unusual (noise)" : name(r.root));
    steps.push({ k: "obs", h: "Observe", nodes: obsIdx, t: `${obsIdx.length} readings: ${obsIdx.map((i, j) => `${BR_NODES[i].s} ${sg(ab.y[j], 2)}σ`).join(", ")}. Measured nodes come from the data; your own observations count the same way.` });
    const top = ex.slice(0, 3);
    steps.push({ k: "hyp", h: "Explain", nodes: top.filter((r) => r.root != null).map((r) => r.root), t: `Competing single causes, ranked by how well each explains every reading at once: ${top.map((r) => `${hyp(r)} ${pct0(r.p)}${r.root != null ? ` (${sg(r.s, 1)}σ)` : ""}`).join("; ")}.${top.length > 1 && Math.abs(top[0].p - top[1].p) < 0.05 ? ` The readings cannot tell the first two apart: ${hyp(top[0])} and ${hyp(top[1])} leave the same footprint on what is observed.` : ""}` });
    const strong = ab.roots.map((r, j) => ({ r, s: ab.s[j], sd: ab.sd[j] })).filter((x) => Math.abs(x.s) >= 0.2).sort((a, b) => Math.abs(b.s) - Math.abs(a.s)).slice(0, 4);
    steps.push({ k: "est", h: "Infer", nodes: strong.map((x) => x.r), t: strong.length ? `Allowing several causes at once, the readings are best explained by ${strong.map((x) => `${name(x.r)} ${sg(x.s, 2)}σ (±${fx(x.sd, 2)})`).join(", ")}. Together they account for ${pct0(Math.max(0, ab.explained))} of the readings.` : `No cause stands out: the readings sit within noise of zero, and the brain says so rather than inventing one.` });
    const exclude = new Set(obsIdx.concat(ab.roots));
    const preds = pr.mean.map((m, i) => ({ i, m, sd: pr.sd[i], z: pr.sd[i] > 0 ? Math.abs(m) / pr.sd[i] : 0 })).filter((x) => !exclude.has(x.i) && Math.abs(x.m) > 0.05).sort((a, b) => b.z - a.z).slice(0, 4);
    steps.push({ k: "est", h: "Deduce", nodes: preds.map((x) => x.i), t: preds.length ? `If that is right, these should also be true now: ${preds.map((x) => `${name(x.i)} ${sg(x.m, 2)}σ (±${fx(x.sd, 2)})`).join(", ")}. Each is a prediction the data can check.` : "The inference implies nothing notable elsewhere." });
    const rmax = cr.resid.map((r, j) => ({ r, i: obsIdx[j] })).sort((a, b) => Math.abs(b.r) - Math.abs(a.r))[0];
    const gi = cr.grad.map((g, j) => ({ g: Math.abs(g), e: W[j] })).filter((x) => x.e.w && x.g > 0).sort((a, b) => b.g - a.g)[0];
    steps.push({ k: "hyp", h: "Doubt", nodes: [rmax ? rmax.i : null, gi ? gi.e.from : null, gi ? gi.e.to : null].filter((x) => x != null),
      t: `${rmax && Math.abs(rmax.r) >= 1 ? `The map cannot explain ${name(rmax.i)}: it reads ${fx(Math.abs(rmax.r), 1)} noise units ${rmax.r > 0 ? "above" : "below"} what the inferred causes imply.` : "Every reading sits within one noise unit of the inference."}${gi ? ` The link most likely wrong: ${name(gi.e.from)} → ${name(gi.e.to)} (${gi.e.measured ? "measured" : "judged"} ${sg(gi.e.w)}); changing it would cut the misfit fastest.` : ""}` });
    const b = BR_IDX.book, bs = ab.roots.map((r, j) => ({ r, c: th.T[b][r] * ab.s[j] })).sort((x, y) => Math.abs(y.c) - Math.abs(x.c));
    const cos = th.shared.cos, pairs = [];
    BR_HOLD.forEach((a, i) => BR_HOLD.forEach((c, j) => { if (j > i) pairs.push({ a, c, v: cos[i][j] }); }));
    pairs.sort((x, y) => y.v - x.v);
    steps.push({ k: "est", h: "Apply to the book", nodes: [b, BR_IDX[pairs[0].a], BR_IDX[pairs[0].c]].concat(bs[0] ? [bs[0].r] : []),
      t: `The book's implied move is ${sg(pr.mean[b], 2)}σ (±${fx(pr.sd[b], 2)}), mostly through ${bs[0] ? name(bs[0].r) : "n/a"}. ${pairs[0].a} and ${pairs[0].c} repeat the same bet: their sensitivities to the root causes point the same way (cosine ${fx(pairs[0].v, 2)}).` });
    const nx = th.next[0];
    if (nx && top.length >= 2 && nx.info > 1e-4) {
      const hs = ex.filter((r) => r.p > 1e-6).slice(0, 6), i0 = 0, i1 = 1, mid = (nx.means[i0] + nx.means[i1]) / 2;
      steps.push({ k: "hyp", h: "Look next", nodes: [nx.node], t: `To tell "${hyp(hs[i0])}" from "${hyp(hs[i1])}", watch ${name(nx.node)}: the first implies ${sg(nx.means[i0], 2)}σ, the second ${sg(nx.means[i1], 2)}σ. It carries ${fx(nx.info, 3)} nats about which explanation is right, the most of any unobserved node.` });
      steps.push({ k: "hyp", h: "Change my mind", nodes: [nx.node], t: `A reading of ${name(nx.node)} ${nx.means[i1] > nx.means[i0] ? "above" : "below"} ${sg(mid, 2)}σ would favour "${hyp(hs[i1])}" over the current leader. Add it as an observation above and the brain re-reasons.` });
    }
    return steps;
  }
  function brRunThink(W) {
    const ob = brObserved();
    if (Object.keys(ob.values).length < 1) { BR.thought = null; return null; }
    try { BR.thought = brThink(W, BR.K, ob.values); BR.thought.src = ob.src; BR.thought.steps = brTrace(BR.thought, ob, W); } catch (e) { BR.thought = null; }
    if (BR.thought) try { brTraceFrontier(BR.thought, W); } catch (e) { /* the core trace stands on its own */ }
    return BR.thought;
  }
  function renderThink(W) {
    const box = $("#br-steps");
    if (!box) return;
    const th = BR.thought;
    box.replaceChildren();
    if (!th) { box.append(h("li", "none", "Add at least one observation for the brain to reason about.")); return; }
    th.steps.forEach((st, i) => {
      const li = h("li", "br-step" + (i === BR.step ? " active" : ""));
      li.tabIndex = 0;
      const head = h("div", "br-step-h");
      head.append(h("b", null, st.h), evTag(st.k));
      li.append(head, h("p", null, st.t));
      const pick = () => { BR.step = i; BR.focus = st.nodes; stopThinking(); renderThinkFocus(); };
      li.addEventListener("click", pick);
      li.addEventListener("focus", pick);
      box.append(li);
    });
    // observations
    const ob = brObserved(), ot = $("#br-obs tbody");
    ot.replaceChildren();
    Object.keys(ob.values).map(Number).sort((a, b) => a - b).forEach((i) => {
      const tr = h("tr"), del = h("button", "pill", "Drop");
      del.type = "button";
      del.setAttribute("aria-label", `Drop the ${BR_NODES[i].n} observation`);
      del.addEventListener("click", () => { BR.obs[BR_NODES[i].id] = "off"; LS.set("bo-brain-obs", BR.obs); updateBrain(); });
      const td = h("td"); td.append(del);
      tr.append(h("td", null, BR_NODES[i].n), h("td", "r num", sg(ob.values[i], 2) + "σ"), h("td", "cat", ob.src[i]), td);
      ot.append(tr);
    });
    // explanations
    barsH($("#br-expl"), th.explanations.slice(0, 7).map((r) => ({ label: r.root == null ? "Nothing unusual" : BR_NODES[r.root].n, v: r.p * 100, lbl: pct0(r.p),
      color: r.root == null ? "var(--muted)" : "var(--s1)", tip: () => [[pct0(r.p), "posterior"], [r.root == null ? "noise only" : `${sg(r.s, 2)}σ ± ${fx(r.s_sd, 2)}`, "implied size of the cause"]] })),
      { label: "Posterior probability of each single-cause explanation", fmt: (v) => fx(v, 0) + "%", labelW: 190 });
    // predictions for what was not observed
    const pt = $("#br-pred tbody");
    pt.replaceChildren();
    const obsSet = new Set(th.abduce.obs);
    th.predict.mean.map((m, i) => ({ m, i, sd: th.predict.sd[i] })).filter((x) => !obsSet.has(x.i)).sort((a, b) => Math.abs(b.m) - Math.abs(a.m)).slice(0, 10).forEach((x) => {
      const tr = h("tr"), root = th.abduce.roots.includes(x.i);
      tr.append(h("td", null, BR_NODES[x.i].n), h("td", "r num", sg(x.m, 2) + "σ"), h("td", "r num", "±" + fx(x.sd, 2)), h("td", "cat", root ? "inferred cause" : BR_NODES[x.i].ring === 3 ? "holding" : x.i === BR_IDX.book ? "the book" : "implied"));
      pt.append(tr);
    });
    // next observations
    const nl = $("#br-next");
    nl.replaceChildren();
    th.next.slice(0, 5).forEach((r) => { const li = h("li"); li.append(h("span", null, BR_NODES[r.node].n), h("b", "num", fx(r.info, 3) + " nats")); nl.append(li); });
    // shared exposure
    const sh = $("#br-shared");
    sh.replaceChildren();
    const thead = h("thead"), hr = h("tr");
    hr.append(h("th", null, ""));
    BR_HOLD.forEach((id) => hr.append(h("th", "r", id)));
    thead.append(hr);
    const tb = h("tbody");
    BR_HOLD.forEach((id, i) => {
      const tr = h("tr");
      tr.append(h("th", null, id));
      th.shared.cos[i].forEach((v, j) => { const td = h("td", "r num heat", i === j ? "1" : fx(v, 2)); td.style.background = `color-mix(in srgb, var(--s2) ${Math.round(Math.max(0, v) ** 3 * 45)}%, transparent)`; tr.append(td); });
      tb.append(tr);
    });
    sh.append(thead, tb);
    const b = BR_IDX.book;
    barsH($("#br-booksens"), BR_ROOTS.map((id) => ({ label: BR_NODES[BR_IDX[id]].n, v: th.T[b][BR_IDX[id]] })).sort((x, y) => Math.abs(y.v) - Math.abs(x.v)).slice(0, 8)
      .map((r) => Object.assign(r, { color: r.v < 0 ? "var(--s1)" : "var(--s2)", lbl: sg(r.v, 2) })), { label: "The book's move per 1σ of each root cause", fmt: (v) => sg(v, 2), labelW: 190 });
    // seeing against doing
    const sId = Object.keys(BR.shock)[0], sIdx = BR_IDX[sId], size = BR.shock[sId], t = BR_IDX[BR.target];
    const doing = brIntervene(W, BR.K, sIdx, size)[t];
    let seeing = NaN;
    try { const T = th.T, roots = BR_ROOTS.map((id) => BR_IDX[id]); const ab = brAbduce(T, { [sIdx]: size }, roots); seeing = brPredict(T, ab).mean[t]; } catch (e) { seeing = NaN; }
    $("#br-sd").textContent = `Doing: if ${BR_NODES[sIdx].n} is set to ${sg(size, 1)}σ from outside (its own causes cut), ${BR_NODES[t].n} moves ${sg(doing, 2)}σ. Seeing: if ${BR_NODES[sIdx].n} is merely observed at ${sg(size, 1)}σ, the brain first asks what caused it, and that inference implies ${sg(seeing, 2)}σ. ${fin(seeing) && Math.abs(seeing - doing) > 0.1 ? "The gap is what the observation signals about its causes: a move you cause and a move you see are not the same news." : "Here the two agree: the move carries little news about its causes."}`;
    const ex = th.steps.find((x) => x.h === "Explain");
    $("#br-think-sum").textContent = ex ? ex.t : "";
  }
  function renderThinkFocus() {
    document.querySelectorAll("#br-steps .br-step").forEach((li, i) => li.classList.toggle("active", i === BR.step));
    drawBrain(BR.lastW, BR.lastRes, BR.lastS, BR.lastT, BR.lastSize);
  }
  function stopThinking() { if (BR.timer) { clearInterval(BR.timer); BR.timer = null; } const b = $("#br-think-go"); if (b) b.textContent = "Think it through"; }
  function startThinking() {
    stopThinking();
    if (!BR.thought) return;
    const motion = !(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
    BR.view = "think";
    syncViewButtons();
    if (!motion) { BR.step = -1; BR.focus = null; renderThinkFocus(); return; }
    BR.step = 0; BR.focus = BR.thought.steps[0].nodes; renderThinkFocus();
    const b = $("#br-think-go"); if (b) b.textContent = "Stop";
    BR.timer = setInterval(() => {
      BR.step += 1;
      if (!BR.thought || BR.step >= BR.thought.steps.length) { stopThinking(); BR.step = -1; BR.focus = null; renderThinkFocus(); return; }
      BR.focus = BR.thought.steps[BR.step].nodes; renderThinkFocus();
    }, 1600);
  }
  function syncViewButtons() { const v = $("#br-view"); if (v) v.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", b.dataset.v === BR.view ? "true" : "false")); }

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
    const vw = $("#br-view");
    if (vw) vw.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => { BR.view = b.dataset.v; BR.focus = null; BR.step = -1; stopThinking(); syncViewButtons(); updateBrain(); }));
    const go = $("#br-think-go");
    if (go) go.addEventListener("click", () => { if (BR.timer) { stopThinking(); BR.focus = null; BR.step = -1; renderThinkFocus(); } else startThinking(); });
    const on = $("#br-obs-node");
    if (on) {
      BR_NODES.forEach((n) => on.append(new Option(n.n, n.id)));
      on.value = "credit";
      $("#br-obs-v").addEventListener("input", () => { $("#br-obs-v-o").textContent = sg(Number($("#br-obs-v").value), 2) + "σ"; });
      $("#br-obs-v-o").textContent = sg(Number($("#br-obs-v").value), 2) + "σ";
      $("#br-obs-add").addEventListener("click", () => { BR.obs[on.value] = Number($("#br-obs-v").value); LS.set("bo-brain-obs", BR.obs); BR.view = "think"; syncViewButtons(); updateBrain(); });
      $("#br-obs-reset").addEventListener("click", () => { BR.obs = {}; LS.set("bo-brain-obs", BR.obs); updateBrain(); });
    }
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
    const note = $("#br-edge-note"), measured = e.measured || (m && n);
    const txt = measured
      ? `Measured: ${sg(m.w)} (±${fx(m.se, 2)}) in ${R.low_inflation.start.slice(0, 4)} to ${R.low_inflation.end.slice(0, 4)}, ${sg(n.w)} (±${fx(n.se, 2)}) since ${R.inflation.start.slice(0, 4)}. ${e.edited ? "You have overridden it." : "Blended by the regime slider."} ${e.why}. Falsified if the next 24 months estimate the opposite sign with |t| ≥ 2; identification rests on the stated ordering, not on causality.`
      : `Judged at ${sg(BR_EDGES.find((x) => ekey(x) === e.key)[2])}, uncertainty ±${fx(e.sd, 2)}. ${e.why}. Source: ${e.src}.${e.edited ? " You have overridden it." : ""} Test: the link is rejected if, once data exists for both ends, their co-movement over two years has the opposite sign; until then it is a hypothesis, not a measurement.`;
    note.replaceChildren(evTag(e.edited ? "asm" : measured ? "est" : "hyp"), document.createTextNode(" " + txt));
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
      p.append(h("strong", null, "The assumption the answer rests on: "), document.createTextNode(`${BR_NODES[s0.e.from].n} → ${BR_NODES[s0.e.to].n} at ${sg(s0.e.w)} (${s0.e.measured ? "measured" : s0.e.edited ? "your override" : "judged"}). Two standard deviations of doubt on it move the answer by ${sg(s0.swing)}σ${s0.flips ? ", enough to flip its sign" : ""}.`));
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
    brRunThink(W);
    Object.assign(BR, { lastW: W, lastRes: res, lastS: sIdx, lastT: t, lastSize: size });
    guard("The brain's reasoning", () => renderThink(W), $("#br-steps"));
    guard("Frontier reasoning", () => { wireFrontier(); renderFrontier(W); }, $("#brf-regime"));
    syncViewButtons();
    drawBrain(W, res, sIdx, t, size);
    syncEdgeEditor();
  }

  // the Buildout mark: the lotus (the same symbol as the header logo)
  function logoMark(parent, x, y, size, attrs = {}) {
    const g = svg("g", Object.assign({ transform: `translate(${(x - size / 2).toFixed(1)},${(y - size / 2).toFixed(1)})`, class: "logo-mark" }, attrs), parent);
    svg("circle", { cx: size / 2, cy: size / 2, r: size / 2, fill: "var(--surface)" }, g);
    const u = svg("use", { href: "#lotus", width: size, height: size }, g);
    u.style.color = "var(--accent)";
    return g;
  }
  function drawBrain(W, res, sIdx, t, size) {
    const box = $("#br-svg-box");
    if (!box || !box.clientWidth || !W) return;
    const Wd = boxWidth(box), narrow = Wd < 560;
    const Hd = narrow ? Math.round(Wd * 1.2) : Math.round(Math.min(760, Math.max(460, Wd * 0.8))), cx = Wd / 2, cy = Hd / 2, R = Math.min(Wd, Hd) / 2 - (narrow ? 30 : 46);
    const radii = [R, R * 0.77, R * 0.55, R * 0.33, 0];
    const pos = BR_NODES.map((n) => { const a = (n.a * Math.PI) / 180, r = radii[n.ring]; return [cx + r * Math.cos(a), cy + r * Math.sin(a)]; });
    const th = BR.thought, think = BR.view === "think" && th;
    const obsSet = think ? new Set(th.abduce.obs) : new Set(), rootS = think ? Object.fromEntries(th.abduce.roots.map((r, j) => [r, th.abduce.s[j]])) : {};
    const resp = think ? th.predict.mean.slice() : BR_NODES.map((_, i) => res.total[i] + (i === sIdx ? size : 0));
    if (think) th.abduce.obs.forEach((o, j) => { resp[o] = th.abduce.y[j]; });
    const focus = BR.focus && BR.focus.length ? new Set(BR.focus) : null;
    box.replaceChildren();
    const s = svg("svg", { viewBox: `0 0 ${Wd} ${Hd}`, width: Wd, height: Hd, role: "group", "aria-label": think ? "The brain's inference: observed nodes are ringed, inferred causes glow, every other node shows what the inference implies" : "The brain: nodes are parts of the system, lines are signed links; glow shows each node's response to the shock" }, box);
    const defs = svg("defs", {}, s);
    const rg = svg("radialGradient", { id: "br-bg", cx: "50%", cy: "50%", r: "65%" }, defs);
    svg("stop", { offset: "0%", "stop-color": "#1b1640" }, rg); svg("stop", { offset: "55%", "stop-color": "#0d0b22" }, rg); svg("stop", { offset: "100%", "stop-color": "#05050d" }, rg);
    const fl = svg("filter", { id: "br-glow", x: "-80%", y: "-80%", width: "260%", height: "260%" }, defs);
    svg("feGaussianBlur", { stdDeviation: "7" }, fl);
    svg("rect", { x: 0, y: 0, width: Wd, height: Hd, rx: 16, fill: "url(#br-bg)" }, s);
    radii.slice(0, 4).forEach((r, i) => svg("circle", { cx, cy, r, fill: "none", stroke: "#3b3670", "stroke-opacity": 0.55 - i * 0.1, "stroke-dasharray": i % 2 ? "2 6" : "none" }, s));
    // flows: in the shock view, |w x(from)| summed over orders; in the inference view, |w x(from)| at the inferred state
    const flow = W.map((e) => (think ? Math.abs(e.w * resp[e.from]) : res.orders.reduce((a, o, k) => a + Math.abs(e.w * (k === 0 ? (e.from === sIdx ? size : 0) : res.orders[k - 1][e.from])), 0)));
    const maxF = Math.max(1e-9, ...flow);
    const gE = svg("g", {}, s);
    W.forEach((e, i) => {
      if (!e.w) return;
      const [x1, y1] = pos[e.from], [x2, y2] = pos[e.to];
      const mx = (x1 + x2) / 2, my = (y1 + y2) / 2, pull = 0.3;
      const qx = mx + (cx - mx) * pull, qy = my + (cy - my) * pull;
      const d = `M${x1.toFixed(1)},${y1.toFixed(1)} Q${qx.toFixed(1)},${qy.toFixed(1)} ${x2.toFixed(1)},${y2.toFixed(1)}`;
      const f = flow[i] / maxF, active = f > 0.04, dim = focus && !(focus.has(e.from) && focus.has(e.to));
      const col = e.w > 0 ? "#ff9e5e" : "#5ec8ff";
      const p = svg("path", { d, fill: "none", stroke: col, "stroke-width": (0.5 + 3 * Math.min(1, Math.abs(e.w))).toFixed(2), "stroke-opacity": (dim ? 0.06 : active ? 0.32 + 0.6 * f : 0.13).toFixed(2), class: "br-edge" + (active && !dim ? " flow" : "") + (e.key === BR.sel ? " sel" : "") + (e.measured ? "" : " judged") }, gE);
      if (active) p.style.animationDuration = (2.6 - 1.9 * f).toFixed(2) + "s";
      const hit = svg("path", { d, fill: "none", stroke: "transparent", "stroke-width": 12, class: "br-hit", tabindex: "-1", "aria-label": `${BR_NODES[e.from].n} to ${BR_NODES[e.to].n}: ${sg(e.w)}` }, gE);
      hit.addEventListener("click", () => { BR.sel = e.key; syncEdgeEditor(); updateBrain(); $("#br-w").focus(); });
      bindTip(hit, () => [[sg(e.w) + (e.measured ? " measured" : e.edited ? " your override" : " judged"), `${BR_NODES[e.from].n} → ${BR_NODES[e.to].n}: ${e.why}`]]);
    });
    const maxR = Math.max(0.05, ...resp.map(Math.abs));
    BR_NODES.forEach((n, i) => {
      const [x, y] = pos[i], v = resp[i], m = Math.abs(v) / maxR, dim = focus && !focus.has(i);
      const g = svg("g", { class: "br-node" + (dim ? " dim" : "") + (focus && focus.has(i) ? " focus" : ""), tabindex: "0", role: "button",
        "aria-label": `${n.n}: ${think ? (obsSet.has(i) ? "observed" : i in rootS ? "inferred cause" : "implied") : "response"} ${sg(v)} sigma. Enter shocks it; T makes it the target.` }, s);
      const warm = v > 0, hue = warm ? "#ff7a59" : "#45b8ff";
      if (m > 0.02) {
        const halo = svg("circle", { cx: x, cy: y, r: ((n.ring === 4 ? 26 : n.ring === 3 ? 9 : 14) + (n.ring === 3 ? 18 : 30) * m).toFixed(1), fill: hue, opacity: (0.22 + 0.5 * m).toFixed(2), filter: "url(#br-glow)", class: "br-halo" }, g);
        halo.style.animationDuration = (3.2 - 1.6 * m).toFixed(2) + "s";
      }
      if (n.ring === 4) {
        const L = narrow ? 34 : 46;
        svg("circle", { cx: x, cy: y, r: L * 0.78, fill: "#151233", stroke: i === t ? "#ffffff" : "#8f88c9", "stroke-width": i === t ? 2.4 : 1.2, "stroke-dasharray": i === t ? "3 2" : "none" }, g);
        logoMark(g, x, y, L * 0.82);
        text(g, x, y + L * 0.78 + 13, `${n.s} ${sg(v)}σ`, "br-label" + (narrow ? " small" : ""), "middle").setAttribute("font-weight", "700");
      } else {
        const core = n.ring === 2 ? 12 : n.ring === 3 ? 8 : 10;
        if (think && obsSet.has(i)) svg("circle", { cx: x, cy: y, r: core + 5, fill: "none", stroke: "#ffffff", "stroke-width": 1.4, "stroke-opacity": 0.9 }, g);
        if (think && i in rootS && Math.abs(rootS[i]) >= 0.2) svg("circle", { cx: x, cy: y, r: core + 9, fill: "none", stroke: "#ffd166", "stroke-width": 1.6, "stroke-dasharray": "2 3", class: "br-root" }, g);
        svg("circle", { cx: x, cy: y, r: core, fill: "#151233", stroke: !think && i === sIdx ? "#ffd166" : i === t ? "#ffffff" : n.m ? "#9fe3c9" : n.ring === 3 ? "#c9c3ff" : "#8f88c9", "stroke-width": (!think && i === sIdx) || i === t ? 2.6 : 1.4, "stroke-dasharray": i === t && i !== sIdx ? "3 2" : "none" }, g);
        svg("circle", { cx: x, cy: y, r: Math.max(2, core * 0.45 * Math.min(1, m + 0.2)), fill: m > 0.02 ? hue : "#5b5591" }, g);
        const right = Math.cos((n.a * Math.PI) / 180) >= -0.2, below = narrow || n.ring >= 2;
        const lx = below ? Math.min(Wd - 34, Math.max(34, x)) : x + (right ? core + 6 : -core - 6), ly = below ? y + core + 12 : y + 4;
        const anchor = below ? "middle" : right ? "start" : "end";
        const lab = text(g, lx, ly, n.s, "br-label" + (narrow || n.ring === 3 ? " small" : ""), anchor);
        if (m > 0.02 && (!narrow || m > 0.3 || i === sIdx || i === t) && (n.ring !== 3 || m > 0.25)) text(g, lx, ly + (narrow || n.ring === 3 ? 11 : 13), sg(v) + "σ", "br-val" + (warm ? " warm" : " cool") + (narrow || n.ring === 3 ? " small" : ""), anchor);
        lab.setAttribute("font-weight", i === sIdx || i === t ? "700" : "500");
      }
      const pick = (asTarget) => { if (asTarget) BR.target = n.id; else { BR.preset = null; BR.view = "shock"; BR.shock = { [n.id]: Number($("#br-size").value) || 1 }; } syncBrainControls(); updateBrain(); };
      g.addEventListener("click", (ev) => pick(ev.shiftKey || ev.altKey));
      g.addEventListener("keydown", (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); pick(false); } else if (ev.key === "t" || ev.key === "T") { ev.preventDefault(); pick(true); } });
      bindTip(g, () => [[`${sg(v)}σ`, `${n.n}${think ? (obsSet.has(i) ? " · observed" : i in rootS ? " · inferred cause" : " · implied by the inference") : n.m ? " · measured node" : ""}. ${n.why}`]]);
    });
    const step = think && BR.step >= 0 && th.steps[BR.step];
    text(s, 14, Hd - 12, step ? `${BR.step + 1}. ${step.h}` : think ? (narrow ? "Inference: ringed = observed, dashed gold = inferred cause" : "Inference view: ringed nodes are observed, dashed gold rings are inferred causes, everything else is implied") : narrow ? "Tap a node to shock it · tap a line to edit it" : "Click a node to shock it · shift-click to make it the target · click a line to edit it", "br-hintline", "start");
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

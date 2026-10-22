  /* =====================================================================================
     hedgebook.js (v0.11): prebuilt hedges, each switchable and sized, run through the solver's seven scenarios.
     Mirrors buildout/hedgebook.py (tests/test_v11.py checks they agree).
     ===================================================================================== */
  const HB_HEDGES = [
    { id: "tlt", name: "Long Treasuries (TLT)", param: "ratio", def: 0.3, range: [0, 1], step: 0.05, unit: "x equity", protects: ["soft", "digest"], nodes: ["y10", "tlt"], note: "Fails when stocks and bonds fall together (2022, term-premium shocks)." },
    { id: "put_spread", name: "Index put spread 95/85", param: "premium", def: 0.01, range: [0, 0.03], step: 0.0025, unit: "of NAV", protects: ["termprem", "digest", "stagfl", "crash"], nodes: ["eq", "vix"], note: "Pays between 5% and 15% falls; nothing beyond." },
    { id: "collar", name: "Collar 90/110", param: "share", def: 0.5, range: [0, 1], step: 0.05, unit: "of equity", protects: ["digest", "stagfl", "crash"], nodes: ["eq"], note: "Close to free; gives up gains above 10% in a melt-up." },
    { id: "gold", name: "Gold sleeve", param: "weight", def: 0.05, range: [0, 0.2], step: 0.01, unit: "of NAV", protects: ["termprem", "stagfl"], nodes: ["gold", "dollar"], note: "Hedges inflation and policy shocks; can fall in a liquidity crash." },
    { id: "vix_calls", name: "VIX call spread 25/40", param: "premium", def: 0.005, range: [0, 0.02], step: 0.0025, unit: "of NAV", protects: ["crash", "digest"], nodes: ["vix"], note: "Convex in a crash; decays in calm quarters." },
    { id: "beta_short", name: "Short index futures", param: "share", def: 0.25, range: [0, 1], step: 0.05, unit: "of market beta", protects: ["termprem", "digest", "stagfl", "crash"], nodes: ["eq"], note: "Linear: costs upside one for one; keeps the AI bet." },
    { id: "ai_pair", name: "Short semiconductor basket", param: "weight", def: 0.15, range: [0, 0.5], step: 0.05, unit: "of NAV", protects: ["digest", "termprem"], nodes: ["aidemand", "capex", "NVDA", "AVGO"], note: "Hedges an AI-capex digestion; basis risk if the book's names diverge from the basket." },
    { id: "trend", name: "Trend cut", param: "cut", def: 0.5, range: [0, 1], step: 0.05, unit: "of equity", protects: ["digest", "stagfl", "crash"], nodes: ["eq"], note: "Cuts after an 8% fall and avoids about 60% of the rest; false signals cost about 1% a quarter (Assumed)." },
    { id: "degross", name: "Run less equity", param: "cut", def: 0.2, range: [0, 0.8], step: 0.05, unit: "of equity", protects: ["termprem", "digest", "stagfl", "crash"], nodes: ["eq"], note: "The simplest hedge: less of everything, cash earns the rate." },
  ];
  const HB_IDS = HB_HEDGES.map((x) => x.id);
  const HB_RUNNING_BP = 5.0;
  const HB_A = { smh_beta_market: 1.3, smh_beta_ai: 1.5, vix0: 18.0, vix_vol: 1.0, vix_term: 1.5, vix_per_market: 90.0, trend_trigger: -0.08, trend_whipsaw: 0.01, trend_capture: 0.6, call_skew: -2.0, put_skew: 3.0 };
  const hbP = (P) => Object.assign({}, RZ_DEFAULTS, P || {});
  const hbVixEnd = (s, vix0) => Math.max(9, vix0 - HB_A.vix_per_market * s.market);
  function hbCosts(P) {
    const v = P.vix / 100, T = P.horizon, pv = v + HB_A.put_skew / 100;
    const put95 = bs(1, 0.95, T, 0, 0, pv, "put").price, put85 = bs(1, 0.85, T, 0, 0, pv, "put").price, put90 = bs(1, 0.90, T, 0, 0, pv, "put").price;
    const call110 = bs(1, 1.10, T, 0, 0, Math.max(0.05, v + HB_A.call_skew / 100), "call").price, F = P.vix + HB_A.vix_term;
    const vc = bs(F, 25, T, 0, 0, HB_A.vix_vol, "call").price - bs(F, 40, T, 0, 0, HB_A.vix_vol, "call").price;
    return { put_spread: put95 - put85, collar_net: put90 - call110, vix_spread: vc };
  }
  function hbPnl(hid, x, e, s, P, c) {
    const m = 1 + s.market, cash = P.rf * P.horizon, stock = P.beta_market * s.market + P.beta_ai * s.ai;
    switch (hid) {
      case "tlt": return e * x * (rzBond(s.dy, P) - cash);
      case "put_spread": { const pay = Math.max(0, 0.95 - m) - Math.max(0, 0.85 - m); return c.put_spread > 0 ? (x / c.put_spread) * pay - x : 0; }
      case "collar": return x * e * (Math.max(0, 0.90 - m) - Math.max(0, m - 1.10) - c.collar_net);
      case "gold": return x * (s.gold - cash);
      case "vix_calls": { const pay = Math.min(Math.max(hbVixEnd(s, P.vix) - 25, 0), 15); return c.vix_spread > 0 ? (x / c.vix_spread) * pay - x : 0; }
      case "beta_short": return -x * e * P.beta_market * s.market;
      case "ai_pair": return -x * (HB_A.smh_beta_market * s.market + HB_A.smh_beta_ai * s.ai);
      case "trend": {
        if (s.market >= HB_A.trend_trigger) return -x * e * HB_A.trend_whipsaw;
        const frac = (s.market - HB_A.trend_trigger) / s.market;
        return -x * e * (stock * frac * HB_A.trend_capture - cash * 0.5) - x * e * HB_A.trend_whipsaw;
      }
      case "degross": return -x * e * (stock - cash);
      default: throw new Error(hid);
    }
  }
  function hbBook(e, s, P) {
    const stock = P.beta_market * s.market + P.beta_ai * s.ai, cash = 1 - e;
    return e * stock + cash * (P.rf + (cash < 0 ? P.borrow_spread : 0)) * P.horizon;
  }
  function hbEvaluate(on, e, post, P0 = null, scen = RZ_SCENARIOS) {
    const P = hbP(P0), c = hbCosts(P), base = scen.map((s) => hbBook(e, s, P)), parts = {};
    Object.entries(on).forEach(([hid, x]) => { if (x) parts[hid] = scen.map((s) => hbPnl(hid, x, e, s, P, c)); });
    const rets = base.map((b, i) => b + Object.values(parts).reduce((a, p) => a + p[i], 0));
    const elog = rets.reduce((a, r, i) => a + post[i] * Math.log1p(Math.max(r, -0.999999)), 0), mean = rets.reduce((a, r, i) => a + post[i] * r, 0), bm = base.reduce((a, r, i) => a + post[i] * r, 0);
    const wi = base.indexOf(Math.min(...base)), contrib = {};
    Object.entries(parts).forEach(([hid, p]) => { contrib[hid] = { mean_bp: p.reduce((a, r, i) => a + post[i] * r, 0) * 1e4, worst_scenario: p[wi] }; });
    return { rets, base, parts, ce: Math.expm1(elog), elog, mean, worst: Math.min(...rets), cost_bp: (bm - mean) * 1e4, worst_gain: Math.min(...rets) - Math.min(...base), contrib };
  }
  function hbAdvisor(sizes, e, post, P0 = null, maxLoss = null, allowed = null, top = 5) {
    const P = hbP(P0), L = maxLoss == null ? P.max_loss : maxLoss, ids = (allowed || HB_IDS).filter((h) => sizes[h]), rows = [];
    const n = ids.length;
    for (let k = 0; k < (1 << n); k++) {
      // the same order as Python's itertools.product((0, 1), repeat=n): the first id is the slowest bit
      const on = {};
      ids.forEach((hid, j) => { if ((k >> (n - 1 - j)) & 1) on[hid] = sizes[hid]; });
      const r = hbEvaluate(on, e, post, P);
      rows.push({ on: Object.keys(on).sort(), ce: r.ce, worst: r.worst, cost_bp: r.cost_bp, meets: r.worst >= -L - 1e-12, all_in_bp: r.cost_bp + HB_RUNNING_BP * Object.keys(on).length });
    }
    const key = (r) => r.on.join(",");
    const cmpOn = (a, b) => (a.on.length - b.on.length) || (key(a) < key(b) ? -1 : key(a) > key(b) ? 1 : 0);
    const meets = rows.filter((r) => r.meets);
    const cheapest = meets.slice().sort((a, b) => (a.all_in_bp - b.all_in_bp) || (b.ce - a.ce) || cmpOn(a, b)).slice(0, top);
    const growth = rows.slice().sort((a, b) => (b.ce - a.ce) || cmpOn(a, b)).slice(0, top);
    const safest = rows.slice().sort((a, b) => (b.worst - a.worst) || (b.ce - a.ce) || cmpOn(a, b)).slice(0, top);
    return { combinations: rows.length, meets_limit: meets.length, loss_limit: L, cheapest_meeting_limit: cheapest, best_growth: growth, best_worst_case: safest };
  }

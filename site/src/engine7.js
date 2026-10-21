  /* =====================================================================================
     engine7.js (v0.7): the page's reasoning engine. Pure functions, no DOM.
     Mirrors buildout/policy.py, reasoner.py, games.py, microstructure.py (fill quality) and analytics/risk.py
     (diversification); tests/test_v07.py runs both languages on the same cases.
     ===================================================================================== */

  /* ---------- policies: one specification for the recommendation, its text and the backtest ---------- */
  const POLICY7 = {
    hedge: { id: "hedge.tlt.v2", enter: -0.10, exit: 0.0, maxRatio: 1.0 },
    size: { id: "size.equity.v2" }, limits: { id: "limits.portfolio.v1", maxTotalGross: 2.0, maxPremium: 0.02 },
  };
  function stockBondState(corrs, prev = "neutral", enter = -0.10, exit = 0.0) {
    const out = []; let st = prev;
    for (const c of corrs) {
      if (!fin(c)) { out.push(null); continue; }
      if (st === "hedging" && c > exit) st = "neutral";
      else if (st === "amplifying" && c < -exit) st = "neutral";
      if (st === "neutral") { if (c <= enter) st = "hedging"; else if (c >= -enter) st = "amplifying"; }
      out.push(st);
    }
    return out;
  }
  function tltDecision(state, infl36, line, lineStatus = "ok", mvRatio = null, maxRatio = 1.0) {
    const gates = { state: { value: state, pass: state === "hedging" } }, blocked = [];
    if (state == null) blocked.push("stock-bond correlation unavailable");
    if (lineStatus !== "ok" || !fin(line)) gates.inflation = { value: fin(infl36) ? infl36 : null, line: null, pass: null, status: lineStatus !== "ok" ? lineStatus : "unavailable" };
    else if (!fin(infl36)) { gates.inflation = { value: null, line, pass: null, status: "input_unavailable" }; blocked.push("36-month inflation unavailable"); }
    else gates.inflation = { value: infl36, line, pass: infl36 < line, status: "ok" };
    if (blocked.length) return { policy: POLICY7.hedge.id, status: "unavailable", on: null, ratio: null, gates, blocked };
    const on = gates.state.pass && gates.inflation.pass !== false;
    const ratio = on && fin(mvRatio) ? Math.min(Math.max(mvRatio, 0), maxRatio) : on ? null : 0;
    return { policy: POLICY7.hedge.id, status: "ok", on, ratio, gates, blocked: [] };
  }
  function sizingDecision(volScale, ddCap, maxGross, kellyLev = null, longRunVol = null, kellyFraction = 0.25) {
    const cands = { vol_target: volScale, drawdown_cap: ddCap, max_gross: maxGross };
    const missing = Object.keys(cands).filter((k) => !fin(cands[k]));
    if (missing.length) return { policy: POLICY7.size.id, status: "unavailable", scale: null, binding: null, candidates: cands, blocked: missing.map((k) => k + " unavailable") };
    const binding = Object.keys(cands).reduce((a, k) => (cands[k] < cands[a] ? k : a), "vol_target");
    const scale = cands[binding];
    const check = fin(longRunVol) && longRunVol > 0 ? { kelly_leverage: kellyLev, excess_return_needed: scale * longRunVol * longRunVol / kellyFraction, kelly_supports_size: fin(kellyLev) && kellyLev >= scale } : null;
    return { policy: POLICY7.size.id, status: "ok", scale, binding, candidates: cands, kelly_check: check, blocked: [] };
  }
  function portfolioLimits(equity, hedgeRatio, premium = 0, maxTotalGross = 2.0, maxPremium = 0.02) {
    const bond = equity * hedgeRatio, gross = equity + bond, k = gross > 0 ? Math.min(1, maxTotalGross / gross) : 1;
    const binding = [];
    if (k < 1) binding.push("max_total_gross");
    if (premium > maxPremium) binding.push("max_premium");
    return { policy: POLICY7.limits.id, equity: equity * k, bond: bond * k, total_gross: gross * k, net_long: (equity + bond) * k, premium: Math.min(premium, maxPremium), scaled_by: k, binding };
  }
  // the joint probability of several assumptions without assuming independence (Frechet bounds); independence gives the product
  const frechet = (ps) => ({ lo: Math.max(0, ps.reduce((a, p) => a + p, 0) - (ps.length - 1)), hi: ps.length ? Math.min(...ps) : 1, indep: ps.reduce((a, p) => a * p, 1) });

  /* ---------- fundamentals: one effective dataset, newest validated filing wins field by field ---------- */
  const COVERAGE = { self_funded: "Cash flow covers capex", funding_gap: "Capex exceeds cash flow; interest covered", interest_uncovered: "Operating income below interest, or negative cash flow" };
  function coverageOf(m) {
    const ocf = m.ocf, capex = m.capex;
    if (!fin(ocf) || !fin(capex)) return null;
    const op = fin(m.op_income_lq) ? m.op_income_lq : m.op_income, it = fin(m.interest_lq) ? m.interest_lq : m.interest;
    if (ocf <= 0 || (fin(op) && fin(it) && it > 0 && op < it)) return "interest_uncovered";
    return capex <= ocf ? "self_funded" : "funding_gap";
  }
  const FUND_FIELDS = ["revenue", "ocf", "capex", "da", "op_income", "nonop", "net_income", "interest", "debt", "cash", "rpo", "capex_last_q", "capex_last_q_yoy", "revenue_growth", "debt_yoy"];
  function effectiveFund(rows, live) {
    return rows.map((r0) => {
      const r = Object.assign({}, r0), m = live && live[r0.t], src = {};
      FUND_FIELDS.forEach((f) => { if (fin(r0[f])) src[f] = "snapshot " + r0.quarter_end; });
      if (m && typeof m === "object" && isoOk(m.quarter_end) && m.quarter_end > r0.quarter_end) {
        FUND_FIELDS.forEach((f) => { if (fin(m[f])) { r[f] = m[f]; src[f] = "filing " + m.quarter_end; } });
        r.quarter_end = m.quarter_end; r.refreshed = true;
      }
      const div = (a, b) => (fin(a) && fin(b) && b !== 0 ? a / b : null);
      r.fcf = fin(r.ocf) && fin(r.capex) ? r.ocf - r.capex : null;
      r.capex_to_ocf = div(r.capex, r.ocf);
      r.net_cash = fin(r.cash) && fin(r.debt) ? r.cash - r.debt : null;
      r.coverage = coverageOf(r);
      r.stage = r.coverage ? { self_funded: "hedge", funding_gap: "speculative", interest_uncovered: "ponzi" }[r.coverage] : null;
      const gap = fin(r.capex) && fin(r.ocf) ? r.capex - r.ocf : null;
      r.funding_gap = gap == null ? null : Math.max(gap, 0);
      r.gap_cover_years = gap > 0 && fin(r.cash) ? r.cash / gap : null;
      r.src = src;
      return r;
    });
  }

  /* ---------- diversification: concentration by position versus independent drivers ---------- */
  function jacobiEigen(S) {
    const n = S.length, A = S.map((r) => r.slice()), V = S.map((_, i) => S.map((__, j) => (i === j ? 1 : 0)));
    for (let sweep = 0; sweep < 100; sweep++) {
      let off = 0;
      for (let i = 0; i < n; i++) for (let j = i + 1; j < n; j++) off += A[i][j] * A[i][j];
      if (off < 1e-22) break;
      for (let p = 0; p < n; p++) for (let q = p + 1; q < n; q++) {
        if (Math.abs(A[p][q]) < 1e-300) continue;
        const th = (A[q][q] - A[p][p]) / (2 * A[p][q]), t = Math.sign(th || 1) / (Math.abs(th) + Math.sqrt(th * th + 1));
        const c = 1 / Math.sqrt(t * t + 1), s = t * c;
        for (let k = 0; k < n; k++) { const akp = A[k][p], akq = A[k][q]; A[k][p] = c * akp - s * akq; A[k][q] = s * akp + c * akq; }
        for (let k = 0; k < n; k++) { const apk = A[p][k], aqk = A[q][k]; A[p][k] = c * apk - s * aqk; A[q][k] = s * apk + c * aqk; }
        for (let k = 0; k < n; k++) { const vkp = V[k][p], vkq = V[k][q]; V[k][p] = c * vkp - s * vkq; V[k][q] = s * vkp + c * vkq; }
      }
    }
    return { values: A.map((r, i) => r[i]), vectors: V };
  }
  function effIndependentBets(w, S) {
    const { values, vectors } = jacobiEigen(S), n = w.length;
    const v = values.map((lam, k) => { let d = 0; for (let i = 0; i < n; i++) d += w[i] * vectors[i][k]; return d * d * Math.max(lam, 0); });
    const tot = v.reduce((a, b) => a + b, 0);
    if (!(tot > 0)) return NaN;
    return Math.exp(-v.filter((x) => x > tot * 1e-12).map((x) => x / tot).reduce((a, p) => a + p * Math.log(p), 0));
  }
  function diversificationRatio(w, S) {
    let port = 0, avg = 0;
    for (let i = 0; i < w.length; i++) { avg += Math.abs(w[i]) * Math.sqrt(S[i][i]); for (let j = 0; j < w.length; j++) port += w[i] * S[i][j] * w[j]; }
    return port > 0 ? avg / Math.sqrt(port) : NaN;
  }

  /* ---------- the reasoner ---------- */
  const RZ_FACTORS = ["market", "ai", "dy", "oil", "gold"];
  const RZ_SCENARIOS = [
    { id: "base", name: "Grind higher (base case)", market: 0.06, ai: 0.02, dy: 0.0010, oil: 0.00, gold: 0.01, prior: 0.52 },
    { id: "soft", name: "Soft landing, cuts", market: 0.07, ai: 0.03, dy: -0.0050, oil: -0.05, gold: 0.02, prior: 0.12 },
    { id: "melt", name: "AI melt-up, yields up", market: 0.12, ai: 0.10, dy: 0.0040, oil: 0.05, gold: 0.00, prior: 0.10 },
    { id: "termprem", name: "AI financing / term-premium shock", market: -0.08, ai: -0.06, dy: 0.0075, oil: 0.00, gold: 0.03, prior: 0.09 },
    { id: "digest", name: "AI capex digestion (growth scare)", market: -0.12, ai: -0.12, dy: -0.0060, oil: -0.10, gold: 0.04, prior: 0.07 },
    { id: "stagfl", name: "Inflation + hikes (2022 replay)", market: -0.15, ai: -0.06, dy: 0.0100, oil: 0.25, gold: 0.06, prior: 0.06 },
    { id: "crash", name: "Liquidity crash, everything sells", market: -0.22, ai: -0.08, dy: 0.0025, oil: -0.20, gold: -0.04, prior: 0.04 },
  ];
  const RZ_SIGNALS = [
    { id: "infl", name: "36-month inflation at or above 2.75%", cluster: "inflation", lik: [0.40, 0.30, 0.50, 0.60, 0.30, 0.90, 0.40] },
    { id: "corr", name: "Stocks and bonds moving together (correlation above 0)", cluster: "inflation", lik: [0.40, 0.35, 0.55, 0.70, 0.25, 0.85, 0.50] },
    { id: "oil", name: "Brent at or above 1.3x its 5-year average", cluster: "oil", lik: [0.15, 0.15, 0.25, 0.20, 0.15, 0.70, 0.20] },
    { id: "vix", name: "VIX at or above 20", cluster: "stress", lik: [0.20, 0.20, 0.25, 0.50, 0.60, 0.55, 0.80] },
    { id: "hy", name: "High-yield spread at or above 4.5%", cluster: "credit", lik: [0.15, 0.15, 0.10, 0.40, 0.50, 0.45, 0.70] },
    { id: "capex", name: "Builders' capex above 80% of operating cash flow", cluster: "ai", lik: [0.50, 0.40, 0.60, 0.70, 0.70, 0.50, 0.50] },
    { id: "curve", name: "2s10s curve inverted", cluster: "growth", lik: [0.25, 0.35, 0.20, 0.20, 0.55, 0.45, 0.50] },
  ];
  const RZ_DEFAULTS = { beta_market: 1.15, beta_ai: 1.0, tlt_duration: 16.5, tlt_convexity: 360.0, y30: 0.0485, rf: 0.042, borrow_spread: 0.01,
    vix: 18.0, skew_pts: 3.0, horizon: 0.25, max_loss: 0.15, max_equity: 1.5, max_gross: 2.0, max_premium: 0.02 };

  function rzPosterior(priors, signals, observed) {
    const tot = priors.reduce((a, b) => a + b, 0), p = priors.map((x) => x / tot);
    let logp = p.map(Math.log);
    const groups = {};
    signals.forEach((s) => {
      const o = observed[s.id];
      if (o == null) return;
      (groups[s.cluster] = groups[s.cluster] || []).push(s.lik.map((l) => Math.log(o ? l : 1 - l)));
    });
    const contrib = {};
    // keys in insertion order, as Python dicts keep them
    Object.keys(groups).forEach((c) => {
      const rows = groups[c], v = rows[0].map((_, j) => rows.reduce((a, r) => a + r[j], 0) / rows.length);
      contrib[c] = v; logp = logp.map((x, j) => x + v[j]);
    });
    const mx = Math.max(...logp), e = logp.map((x) => Math.exp(x - mx)), se = e.reduce((a, b) => a + b, 0);
    return { prior: p, posterior: e.map((x) => x / se), log_contrib: contrib };
  }
  function rzPutCost(vix, horizon = 0.25, upper = 0.95, lower = 0.85, skew = 3.0) {
    const v = (vix + skew) / 100;
    return bs(1, upper, horizon, 0, 0, v, "put").price - bs(1, lower, horizon, 0, 0, v, "put").price;
  }
  const rzBond = (dy, P) => P.y30 * P.horizon - P.tlt_duration * dy + 0.5 * P.tlt_convexity * dy * dy;
  function rzReturns(port, scen, P, cost) {
    const [e, h, prem, g] = port;
    return scen.map((s) => {
      const stock = P.beta_market * s.market + P.beta_ai * s.ai, bond = rzBond(s.dy, P) - P.rf * P.horizon, m = 1 + s.market;
      const payoff = Math.max(0, 0.95 - m) - Math.max(0, 0.85 - m), puts = cost > 0 ? (prem / cost) * payoff - prem : 0;
      const cash = 1 - e - g - prem, carry = cash * (P.rf + (cash < 0 ? P.borrow_spread : 0)) * P.horizon;
      return e * stock + e * h * bond + puts + g * s.gold + carry;
    });
  }
  const rzFeasible = (port, rets, P) => Math.min(...rets) >= -P.max_loss - 1e-12 && port[0] <= P.max_equity + 1e-12 && port[0] * (1 + port[1]) + port[3] <= P.max_gross + 1e-12 && port[2] <= P.max_premium + 1e-12;
  const rzElog = (rets, w) => rets.reduce((a, r, i) => a + w[i] * Math.log1p(Math.max(r, -0.999999)), 0);
  const r20 = (x) => Math.floor(Math.min(Math.max(x, 0), 1.5) * 20 + 0.5);
  function rzSolve(post, scen, P, fixEquity = null, allow = "ehpg", lossLimit = true) {
    const cost = rzPutCost(P.vix, P.horizon, 0.95, 0.85, P.skew_pts), PP = lossLimit ? P : Object.assign({}, P, { max_loss: 10 });
    let best = null;
    for (let i = 0; i < 31; i++) {
      const e = i / 20;
      if (fixEquity != null && Math.abs(e - fixEquity) > 1e-9) continue;
      for (let j = 0; j < 11; j++) for (let k = 0; k < 9; k++) for (let l = 0; l < 6; l++) {
        const port = [e, j / 10, k / 400, l / 50];
        if ((!allow.includes("h") && port[1]) || (!allow.includes("p") && port[2]) || (!allow.includes("g") && port[3])) continue;
        const rets = rzReturns(port, scen, P, cost);
        if (!rzFeasible(port, rets, PP)) continue;
        const u = rzElog(rets, post);
        if (!best || u > best.elog + 1e-12) best = { port, elog: u, rets };
      }
    }
    return best;
  }
  /* ---------- v0.10: robust to being wrong about the odds (mirrors reasoner.solve_robust) ---------- */
  const DRO_GOLD = (Math.sqrt(5) - 1) / 2, DRO_ITERS = 80, DRO_T = [-12.0, 8.0];
  function droG(t, u, p, umin, rho) {
    const lam = Math.exp(t);
    let s = 0;
    for (let i = 0; i < u.length; i++) s += p[i] * Math.exp(-(u[i] - umin) / lam);
    return umin - lam * rho - lam * Math.log(s);
  }
  function klWorst(u, p, rho) {
    if (!(rho > 0)) return { value: u.reduce((a, v, i) => a + v * p[i], 0), lam: null, q: p.slice() };
    let umin = Infinity;
    for (let i = 0; i < u.length; i++) if (p[i] > 0 && u[i] < umin) umin = u[i];
    let a = DRO_T[0], b = DRO_T[1], c = b - DRO_GOLD * (b - a), d = a + DRO_GOLD * (b - a), fc = droG(c, u, p, umin, rho), fd = droG(d, u, p, umin, rho);
    for (let it = 0; it < DRO_ITERS; it++) {
      if (fc > fd) { b = d; d = c; fd = fc; c = b - DRO_GOLD * (b - a); fc = droG(c, u, p, umin, rho); }
      else { a = c; c = d; fc = fd; d = a + DRO_GOLD * (b - a); fd = droG(d, u, p, umin, rho); }
    }
    const tm = (a + b) / 2, val = Math.max(droG(tm, u, p, umin, rho), umin), lam = Math.exp(tm);
    const w = u.map((v, i) => p[i] * Math.exp(-(v - umin) / lam)), z = w.reduce((x, y) => x + y, 0);
    return { value: val, lam, q: w.map((v) => v / z) };
  }
  function rzFeasibleGrid(scen, P) {
    const cost = rzPutCost(P.vix, P.horizon, 0.95, 0.85, P.skew_pts), ports = [], R = [];
    for (let i = 0; i < 31; i++) for (let j = 0; j < 11; j++) for (let k = 0; k < 9; k++) for (let l = 0; l < 6; l++) {
      const port = [i / 20, j / 10, k / 400, l / 50], rets = rzReturns(port, scen, P, cost);
      if (rzFeasible(port, rets, P)) { ports.push(port); R.push(rets); }
    }
    return { ports, R };
  }
  function rzSolveRobust(post, scen, P, rho, cache = null) {
    const { ports, R } = cache || rzFeasibleGrid(scen, P);
    if (!ports.length) return null;
    const U = R.map((r) => r.map((x) => Math.log1p(Math.max(x, -0.999999))));
    const vals = U.map((u) => (rho > 0 ? klWorst(u, post, rho).value : u.reduce((a, v, i) => a + v * post[i], 0)));
    let i = 0;
    for (let k = 1; k < ports.length; k++) if (vals[k] > vals[i] + 1e-12) i = k;
    const w = klWorst(U[i], post, rho);
    return { port: ports[i].slice(), value: vals[i], ce: Math.expm1(vals[i]), nominal_elog: U[i].reduce((a, v, j) => a + v * post[j], 0), rets: R[i].slice(), q_worst: w.q, rho };
  }
  function maxScenarioOdds(p, rho) {
    if (!(rho > 0) || p >= 1) return p;
    const kl = (q) => q * Math.log(q / p) + (1 - q) * Math.log((1 - q) / (1 - p));
    let lo = p, hi = 1 - 1e-12;
    if (kl(hi) <= rho) return hi;
    for (let i = 0; i < 200; i++) { const mid = (lo + hi) / 2; if (kl(mid) <= rho) lo = mid; else hi = mid; }
    return lo;
  }
  const RHO_SWEEP = [0.0, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1.0];
  function rzRobustSweep(post, scen, P, rhos = RHO_SWEEP) {
    const cache = rzFeasibleGrid(scen, P), nominal = rzSolveRobust(post, scen, P, 0, cache);
    const rows = rhos.map((r) => { const sr = rzSolveRobust(post, scen, P, r, cache);
      return { rho: r, port: sr.port, worst_case_ce: sr.ce, nominal_ce: Math.expm1(sr.nominal_elog), price_bp: (nominal.nominal_elog - sr.nominal_elog) * 1e4, q_worst: sr.q_worst }; });
    const ch = rows.findIndex((r, i) => i > 0 && r.port.join() !== rows[i - 1].port.join());
    return { rows, first_change_rho: ch > 0 ? rows[ch].rho : null };
  }
  function rzEvaluate(port, post, scen, P) {
    const cost = rzPutCost(P.vix, P.horizon, 0.95, 0.85, P.skew_pts), rets = rzReturns(port, scen, P, cost), u = rzElog(rets, post);
    return { port: port.slice(), rets, elog: u, ce: Math.expm1(u), worst: Math.min(...rets), mean: rets.reduce((a, r, i) => a + post[i] * r, 0), feasible: rzFeasible(port, rets, P) };
  }
  function rzAlternatives(post, scen, P, current) {
    const keep = rzEvaluate(current, post, scen, P), cost = rzPutCost(P.vix, P.horizon, 0.95, 0.85, P.skew_pts);
    let red = null;
    for (let i = r20(current[0]); i >= 0; i--) {
      const port = [i / 20, 0, 0, 0];
      if (rzFeasible(port, rzReturns(port, scen, P, cost), P)) { red = rzEvaluate(port, post, scen, P); break; }
    }
    const e0 = r20(current[0]) / 20;
    const hed = rzSolve(post, scen, P, e0) || rzSolve(post, scen, P, e0, "ehpg", false);
    const opt = rzSolve(post, scen, P);
    const out = { keep, reduce: red, hedge: hed ? rzEvaluate(hed.port, post, scen, P) : null, optimal: opt ? rzEvaluate(opt.port, post, scen, P) : null };
    const names = ["keep", "reduce", "hedge", "optimal"].filter((k) => out[k]);
    const R = names.map((k) => out[k].rets), colMax = R[0].map((_, j) => Math.max(...R.map((r) => r[j])));
    const maxReg = R.map((r) => Math.max(...r.map((x, j) => colMax[j] - x)));
    names.forEach((k, i) => { out[k].max_regret = maxReg[i]; });
    out.minimax_regret = names[maxReg.indexOf(Math.min(...maxReg))];
    return out;
  }
  // max c.x s.t. A x <= b, x >= 0 (b >= 0): dense tableau, Bland's rule. Returns [x, optimum, dual prices].
  function simplexMax(c, A, b) {
    const m = A.length, n = c.length;
    const T = A.map((row, i) => row.map(Number).concat(Array.from({ length: m }, (_, j) => (j === i ? 1 : 0)), [Number(b[i])]));
    let z = c.map((x) => -x).concat(new Array(m).fill(0), [0]);
    const basis = Array.from({ length: m }, (_, i) => n + i);
    for (let it = 0; it < 500; it++) {
      let col = -1;
      for (let j = 0; j < n + m; j++) if (z[j] < -1e-12) { col = j; break; }
      if (col < 0) break;
      let r = -1, best = null;
      for (let i = 0; i < m; i++) if (T[i][col] > 1e-12) {
        const ratio = T[i][T[i].length - 1] / T[i][col];
        if (best === null || ratio < best[0] || (ratio === best[0] && basis[i] < best[1])) { best = [ratio, basis[i]]; r = i; }
      }
      if (r < 0) throw new Error("unbounded");
      const pv = T[r][col];
      T[r] = T[r].map((x) => x / pv);
      for (let i = 0; i < m; i++) if (i !== r && Math.abs(T[i][col]) > 0) { const f = T[i][col]; T[i] = T[i].map((a, k) => a - f * T[r][k]); }
      const f = z[col]; z = z.map((a, k) => a - f * T[r][k]);
      basis[r] = col;
    }
    const x = new Array(n + m).fill(0);
    basis.forEach((bi, i) => { x[bi] = T[i][T[i].length - 1]; });
    return [x.slice(0, n), z[z.length - 1], z.slice(n, n + m)];
  }
  function zeroSum(M) {
    const lo = Math.min(...M.map((r) => Math.min(...r))), k = 1 - lo, B = M.map((r) => r.map((v) => v + k));
    const [w, , dual] = simplexMax(new Array(B[0].length).fill(1), B, new Array(B.length).fill(1));
    const sw = w.reduce((a, b) => a + b, 0), sd = dual.reduce((a, b) => a + b, 0);
    return { row: dual.map((d) => d / sd), col: w.map((x) => x / sw), value: 1 / sw - k };
  }
  function rzRobust(alts) {
    const names = ["keep", "reduce", "hedge", "optimal"].filter((k) => alts[k]);
    const g = zeroSum(names.map((k) => alts[k].rets));
    return { names, mix: g.row, nature: g.col, value: g.value, mixed_port: [0, 1, 2, 3].map((i) => names.reduce((a, k, j) => a + g.row[j] * alts[k].port[i], 0)) };
  }
  function rzVOI(priors, signals, observed, scen, P) {
    const base = rzPosterior(priors, signals, observed).posterior, best = rzSolve(base, scen, P);
    const perScen = scen.map((_, i) => rzSolve(scen.map((__, j) => (j === i ? 1 : 0)), scen, P));
    const evpi = base.reduce((a, pi, i) => a + pi * perScen[i].elog, 0) - best.elog;
    const rows = signals.map((s) => {
      const rest = Object.assign({}, observed); delete rest[s.id];
      const post0 = rzPosterior(priors, signals, rest).posterior, pOn = post0.reduce((a, p, j) => a + p * s.lik[j], 0);
      const u0 = rzSolve(post0, scen, P).elog;
      let pre = 0; const choice = {};
      [[true, pOn], [false, 1 - pOn]].forEach(([o, po]) => {
        const b = rzSolve(rzPosterior(priors, signals, Object.assign({}, rest, { [s.id]: o })).posterior, scen, P);
        pre += po * b.elog; choice[o] = b.port;
      });
      const cur = observed[s.id], same = (a, b) => a.every((x, i) => x === b[i]);
      return { id: s.id, name: s.name, p_on: pOn, evsi_bp: (pre - u0) * 1e4, observed: cur == null ? null : cur,
        flip_changes_choice: cur == null ? null : !same(choice[!cur], choice[cur]), choice_if_on: choice[true], choice_if_off: choice[false] };
    });
    rows.sort((a, b) => b.evsi_bp - a.evsi_bp);
    return { evpi_bp: evpi * 1e4, signals: rows };
  }
  const rzExposure = (port, P) => [port[0] * P.beta_market, port[0] * P.beta_ai, -port[0] * port[1] * P.tlt_duration, 0, port[3]];
  function reverseStress(b, cov, loss) {
    const n = b.length, Sb = cov.map((row) => row.reduce((a, v, j) => a + v * b[j], 0)), q = b.reduce((a, v, i) => a + v * Sb[i], 0);
    if (!(q > 0)) return { shock: new Array(n).fill(0), sigmas: Infinity, p_normal: 0 };
    const d = loss / Math.sqrt(q);
    return { shock: Sb.map((x) => -loss * x / q), sigmas: d, p_normal: ncdf(-d), port_sd: Math.sqrt(q) };
  }

  // v0.8: the decision boundary. Tilt the odds of the four downside scenarios by f (renormalized) and move the loss
  // limit; at every pair, the grid's optimal equity. Where the colour changes is where the preferred action changes.
  const RZ_DOWN = ["termprem", "digest", "stagfl", "crash"];
  function rzTilt(post, f) {
    const w = post.map((p, i) => p * (RZ_DOWN.includes(RZ_SCENARIOS[i].id) ? f : 1)), z = w.reduce((a, b) => a + b, 0);
    return w.map((x) => x / z);
  }
  function rzBoundary(post, scen, P, tilts, losses) {
    return losses.map((L) => tilts.map((f) => {
      const b = rzSolve(rzTilt(post, f), scen, Object.assign({}, P, { max_loss: L }));
      return b ? { port: b.port, elog: b.elog } : null;
    }));
  }
  // leave one evidence family (driver) out at a time: does the choice survive without it?
  function rzLeaveOneOut(priors, signals, observed, scen, P) {
    const fams = [...new Set(signals.map((s) => s.cluster))], base = rzSolve(rzPosterior(priors, signals, observed).posterior, scen, P);
    return fams.map((fam) => {
      const obs = Object.assign({}, observed);
      signals.filter((s) => s.cluster === fam).forEach((s) => { delete obs[s.id]; });
      const b = rzSolve(rzPosterior(priors, signals, obs).posterior, scen, P);
      return { family: fam, port: b ? b.port : null, same: !!(b && base && b.port.every((x, i) => x === base.port[i])), used: signals.some((s) => s.cluster === fam && observed[s.id] != null) };
    });
  }

  /* ---------- game theory ---------- */
  function solveLinear(M, v) {
    const n = v.length, A = M.map((r, i) => r.map(Number).concat([Number(v[i])]));
    for (let c = 0; c < n; c++) {
      let p = c;
      for (let r = c + 1; r < n; r++) if (Math.abs(A[r][c]) > Math.abs(A[p][c])) p = r;
      if (Math.abs(A[p][c]) < 1e-12) return null;
      [A[c], A[p]] = [A[p], A[c]];
      for (let r = 0; r < n; r++) if (r !== c) { const f = A[r][c] / A[c][c]; A[r] = A[r].map((a, k) => a - f * A[c][k]); }
    }
    return A.map((r, i) => r[n] / r[i]);
  }
  function combos(n, k) {
    const out = [], cur = [];
    (function rec(s) { if (cur.length === k) { out.push(cur.slice()); return; } for (let i = s; i < n; i++) { cur.push(i); rec(i + 1); cur.pop(); } })(0);
    return out;
  }
  function nashAll(A, B, tol = 1e-9) {
    const m = A.length, n = A[0].length, eqs = [];
    const close = (a, b) => a.every((x, i) => Math.abs(x - b[i]) <= 1e-7);
    const add = (x, y) => {
      if (eqs.some((e) => close(e.x, x) && close(e.y, y))) return;
      let ur = 0, uc = 0;
      for (let i = 0; i < m; i++) for (let j = 0; j < n; j++) { ur += x[i] * A[i][j] * y[j]; uc += x[i] * B[i][j] * y[j]; }
      eqs.push({ x, y, u_row: ur, u_col: uc, pure: Math.max(...x) > 1 - 1e-9 && Math.max(...y) > 1 - 1e-9 });
    };
    const unit = (k, i) => Array.from({ length: k }, (_, j) => (j === i ? 1 : 0));
    for (let i = 0; i < m; i++) for (let j = 0; j < n; j++) {
      const colMax = Math.max(...A.map((r) => r[j])), rowMax = Math.max(...B[i]);
      if (A[i][j] >= colMax - tol && B[i][j] >= rowMax - tol) add(unit(m, i), unit(n, j));
    }
    for (let k = 2; k <= Math.min(m, n); k++) for (const I of combos(m, k)) for (const J of combos(n, k)) {
      const My = I.map((i) => J.map((j) => A[i][j]).concat([-1])).concat([new Array(k).fill(1).concat([0])]);
      const sy = solveLinear(My, new Array(k).fill(0).concat([1]));
      const Mx = J.map((j) => I.map((i) => B[i][j]).concat([-1])).concat([new Array(k).fill(1).concat([0])]);
      const sx = solveLinear(Mx, new Array(k).fill(0).concat([1]));
      if (!sy || !sx) continue;
      const y = new Array(n).fill(0), x = new Array(m).fill(0);
      J.forEach((j, t) => { y[j] = sy[t]; }); I.forEach((i, t) => { x[i] = sx[t]; });
      if (y.some((v) => v < -tol) || x.some((v) => v < -tol)) continue;
      const Ay = A.map((r) => r.reduce((a, v, j) => a + v * y[j], 0)), xB = B[0].map((_, j) => B.reduce((a, r, i) => a + x[i] * r[j], 0));
      if (Math.max(...Ay) > sy[k] + 1e-7 || Math.max(...xB) > sx[k] + 1e-7) continue;
      add(x.map((v) => clamp(v, 0, 1)), y.map((v) => clamp(v, 0, 1)));
    }
    const domRow = [], domCol = [];
    for (let i = 0; i < m; i++) if (A.some((r, k) => k !== i && r.every((v, j) => v > A[i][j] + tol))) domRow.push(i);
    for (let j = 0; j < n; j++) { let d = false; for (let k = 0; k < n; k++) if (k !== j && B.every((r) => r[k] > r[j] + tol)) d = true; if (d) domCol.push(j); }
    const pareto = [];
    for (let i = 0; i < m; i++) for (let j = 0; j < n; j++) {
      let dom = false;
      for (let a = 0; a < m; a++) for (let b = 0; b < n; b++) if (A[a][b] >= A[i][j] && B[a][b] >= B[i][j] && (A[a][b] > A[i][j] || B[a][b] > B[i][j])) dom = true;
      if (!dom) pareto.push([i, j]);
    }
    let best = -Infinity; for (let i = 0; i < m; i++) for (let j = 0; j < n; j++) best = Math.max(best, A[i][j] + B[i][j]);
    const worstEq = eqs.length ? Math.min(...eqs.map((e) => e.u_row + e.u_col)) : NaN;
    return { equilibria: eqs, dominated_rows: domRow, dominated_cols: domCol, pareto, welfare_best: best, welfare_worst_eq: worstEq,
      price_of_anarchy: worstEq > 0 ? best / worstEq : null };
  }
  function cournot(a, b, costs) {
    let active = costs.map((_, i) => i), q = {};
    for (;;) {
      const n = active.length, cs = active.reduce((s, i) => s + costs[i], 0);
      q = {}; active.forEach((i) => { q[i] = (a - (n + 1) * costs[i] + cs) / (b * (n + 1)); });
      const out = active.filter((i) => q[i] <= 0);
      if (!out.length || !n) break;
      active = active.filter((i) => !out.includes(i));
    }
    const Q = active.reduce((s, i) => s + q[i], 0), P = a - b * Q, qs = costs.map((_, i) => Math.max(q[i] || 0, 0));
    return { q: qs, Q, P, profit: qs.map((x, i) => (P - costs[i]) * x), active };
  }
  function cournotCalibrate(qObs, costs, pObs) {
    const n = qObs.length, Q = qObs.reduce((s, x) => s + x, 0), cbar = costs.reduce((s, x) => s + x, 0) / costs.length;
    const a = cbar + (n + 1) * (pObs - cbar);
    return { a, b: (a - pObs) / Q, Q_obs: Q, p_obs: pObs };
  }
  function capexGame(qObs, costs, pObs) {
    const cal = cournotCalibrate(qObs, costs, pObs), { a, b } = cal, eq = cournot(a, b, costs), n = costs.length, cmin = Math.min(...costs);
    const Qm = (a - cmin) / (2 * b), Pm = a - b * Qm, joint = (Pm - cmin) * Qm, mean = costs.reduce((s, x) => s + x, 0) / n;
    const ent = cournot(a, b, costs.concat([mean])), sumP = eq.profit.reduce((s, x) => s + x, 0);
    return { calibration: cal, nash: eq, collusive_Q: Qm, collusive_P: Pm, joint_profit_max: joint, overbuild: eq.Q / Qm,
      profit_share_kept: joint > 0 ? sumP / joint : null, with_entrant: ent,
      entrant_cut: sumP > 0 ? ent.profit.slice(0, n).reduce((s, x) => s + x, 0) / sumP - 1 : null,
      symmetric_overbuild: 2 * n / (n + 1), symmetric_profit_share: 4 * n / ((n + 1) * (n + 1)) };
  }
  function capexDilemma(a, b, c, n = 5) {
    const q = { restrain: (a - c) / (2 * b) / n, race: (a - c) / (b * (n + 1)) }, names = ["restrain", "race"];
    const pay = (mine, theirs) => (a - b * (q[mine] + (n - 1) * q[theirs]) - c) * q[mine];
    const A = names.map((me) => names.map((them) => pay(me, them)));
    const q2 = { restrain: (a - c) / (4 * b), race: (a - c) / (3 * b) };
    const A2 = names.map((me) => names.map((them) => (a - b * (q2[me] + q2[them]) - c) * q2[me])), B2 = [[A2[0][0], A2[1][0]], [A2[0][1], A2[1][1]]];
    return { names, n, q, A, race_dominant: A[1][0] > A[0][0] && A[1][1] > A[0][1], everyone_restrains: A[0][0], everyone_races: A[1][1],
      cost_of_racing: 1 - A[1][1] / A[0][0], temptation: A[1][0] / A[0][0] - 1, duopoly: { A: A2, B: B2, analysis: nashAll(A2, B2) } };
  }
  function crowdedExit(lam, cost, y, sdPub, sdPriv, theta = null) {
    const al = 1 / (sdPub * sdPub), be = 1 / (sdPriv * sdPriv), s = Math.sqrt(1 + be / (al + be));
    const mu = (x) => (al * y + be * x) / (al + be);
    const F = (x) => mu(x) - lam * ncdf(Math.sqrt(be) * (x - mu(x)) / s) + cost;
    const dF = (x) => be / (al + be) - lam * npdf(Math.sqrt(be) * (x - mu(x)) / s) * Math.sqrt(be) * (al / (al + be)) / s;
    let lo = y - 20 * (sdPub + sdPriv) - lam, hi = y + 20 * (sdPub + sdPriv) + lam;
    for (let i = 0; i < 200; i++) { const mid = (lo + hi) / 2; if (F(mid) > 0) hi = mid; else lo = mid; }
    const xs = (lo + hi) / 2;
    let unique = true;
    const g0 = y - 6 * sdPub - lam, g1 = y + 6 * sdPub + lam;
    for (let i = 0; i <= 800; i++) if (!(dF(g0 + (g1 - g0) * i / 800) > 0)) { unique = false; break; }
    const th = theta == null ? y : theta, share = ncdf(Math.sqrt(be) * (xs - th));
    return { x_star: xs, theta_star: xs, unique, share_exiting: share, theta: th, stay_payoff: th - lam * share, laplace_limit: lam / 2 - cost, p_fundamental_below: ncdf((xs - y) / sdPub) };
  }
  const kyleEq = (sv, su) => ({ lambda: sv / (2 * su), beta: su / sv, insider_profit: su * sv / 2, post_var_share: 0.5, cost_of_noise_flow: su * sv / 2 });
  const kalshiFee = (p, contracts = 1, rate = 0.07) => Math.ceil(rate * contracts * p * (1 - p) * 100 - 1e-9) / 100;
  function ladderCheck(rows0, contracts = 100) {
    const r = rows0.slice().sort((a, b) => a.k - b.k), mids = r.map((x) => (x.bid + x.ask) / 2), viol = [], arbs = [];
    for (let i = 0; i < r.length; i++) for (let j = i + 1; j < r.length; j++) {
      if (mids[j] > mids[i] + 1e-12) viol.push({ lo: r[i].k, hi: r[j].k, gap: mids[j] - mids[i] });
      const edge = r[j].bid - r[i].ask, fees = (kalshiFee(r[i].ask, contracts) + kalshiFee(r[j].bid, contracts)) / contracts;
      if (edge - fees > 0) arbs.push({ buy: r[i].k, sell: r[j].k, edge, fees, net: edge - fees, per_100: (edge - fees) * 100 });
    }
    const mono = [];
    mids.forEach((v) => { mono.push([v, 1]); while (mono.length > 1 && mono[mono.length - 2][0] < mono[mono.length - 1][0]) { const [v2, w2] = mono.pop(), [v1, w1] = mono.pop(); mono.push([(v1 * w1 + v2 * w2) / (w1 + w2), w1 + w2]); } });
    const fit = []; mono.forEach(([v, w]) => { for (let t = 0; t < w; t++) fit.push(v); });
    const bins = [{ lo: null, hi: r[0].k, p: 1 - fit[0] }];
    for (let i = 0; i < r.length - 1; i++) bins.push({ lo: r[i].k, hi: r[i + 1].k, p: fit[i] - fit[i + 1] });
    bins.push({ lo: r[r.length - 1].k, hi: null, p: fit[fit.length - 1] });
    return { mids, coherent_fit: fit, violations: viol, arbitrage: arbs, pmf: bins };
  }

  /* ---------- v0.8: field research, comparing explanations (mirrors buildout/field.py) ---------- */
  function fieldPosterior(prior, lik, seen) {
    let p = prior.map(Number);
    Object.entries(seen).forEach(([e, v]) => { if (v == null || !(e in lik)) return; p = p.map((pi, i) => pi * (v ? lik[e][i] : 1 - lik[e][i])); });
    const z = p.reduce((a, b) => a + b, 0);
    return z > 0 ? p.map((x) => x / z) : p.map(() => 1 / p.length);
  }
  const entropy2 = (p) => -p.reduce((a, x) => a + (x > 0 ? x * Math.log2(x) : 0), 0);
  function fieldNext(prior, lik, seen) {
    const post = fieldPosterior(prior, lik, seen), h0 = entropy2(post), out = [];
    Object.entries(lik).forEach(([e, ls]) => {
      if (seen[e] != null) return;
      const pYes = post.reduce((a, p, i) => a + p * ls[i], 0);
      const hy = pYes > 0 ? entropy2(fieldPosterior(post, { [e]: ls }, { [e]: true })) : 0, hn = pYes < 1 ? entropy2(fieldPosterior(post, { [e]: ls }, { [e]: false })) : 0;
      out.push({ evidence: e, p_yes: pYes, info_bits: h0 - pYes * hy - (1 - pYes) * hn });
    });
    return out.sort((a, b) => b.info_bits - a.info_bits);
  }

  /* ---------- fill quality (review sections 20 and 21) ---------- */
  function bookState(bid, ask, qb, qa) {
    const tot = qb + qa;
    return { mid: (bid + ask) / 2, spread: ask - bid, imbalance: tot > 0 ? (qb - qa) / tot : 0, weighted_mid: tot > 0 ? (ask * qb + bid * qa) / tot : (bid + ask) / 2 };
  }
  const markoutOf = (side, price, midNow, midLater) => ({ markout: side * (midNow - price) + side * (midLater - midNow), edge: side * (midNow - price), move: side * (midLater - midNow) });
  const postValue = (pFill, mFill, cFill, cMiss) => pFill * (mFill - cFill) - (1 - pFill) * cMiss;

  /* ---------- the calculator: a small, exact-as-doubles expression language (no eval) ---------- */
  function ninv(p) {                                        // Acklam's rational approximation, then one Newton step
    if (!(p > 0 && p < 1)) return p === 0 ? -Infinity : p === 1 ? Infinity : NaN;
    const a = [-39.69683028665376, 220.9460984245205, -275.9285104469687, 138.357751867269, -30.66479806614716, 2.506628277459239];
    const b = [-54.47609879822406, 161.5858368580409, -155.6989798598866, 66.80131188771972, -13.28068155288572];
    const c = [-0.007784894002430293, -0.3223964580411365, -2.400758277161838, -2.549732539343734, 4.374664141464968, 2.938163982698783];
    const d = [0.007784695709041462, 0.3224671290700398, 2.445134137142996, 3.754408661907416];
    let x;
    if (p < 0.02425) { const q = Math.sqrt(-2 * Math.log(p)); x = (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1); }
    else if (p > 1 - 0.02425) { const q = Math.sqrt(-2 * Math.log(1 - p)); x = -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1); }
    else { const q = p - 0.5, r = q * q; x = (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1); }
    const e = ncdf(x) - p, u = e * Math.sqrt(2 * Math.PI) * Math.exp(x * x / 2);
    return x - u / (1 + x * u / 2);
  }
  function irr(cfs) {
    const npv = (r) => cfs.reduce((a, c, t) => a + c / Math.pow(1 + r, t), 0);
    let lo = -0.99, hi = 10;
    if (npv(lo) * npv(hi) > 0) return NaN;
    for (let i = 0; i < 200; i++) { const mid = (lo + hi) / 2; if (npv(lo) * npv(mid) <= 0) hi = mid; else lo = mid; }
    return (lo + hi) / 2;
  }
  const CALC_FN = {
    sqrt: [1, 1, Math.sqrt], ln: [1, 1, Math.log], log: [1, 1, Math.log10], exp: [1, 1, Math.exp], abs: [1, 1, Math.abs],
    floor: [1, 1, Math.floor], ceil: [1, 1, Math.ceil], round: [1, 2, (x, d = 0) => Math.round(x * Math.pow(10, d)) / Math.pow(10, d)],
    min: [1, 99, Math.min], max: [1, 99, Math.max], sum: [1, 99, (...x) => x.reduce((a, b) => a + b, 0)],
    mean: [1, 99, (...x) => x.reduce((a, b) => a + b, 0) / x.length],
    sd: [2, 99, (...x) => { const m = x.reduce((a, b) => a + b, 0) / x.length; return Math.sqrt(x.reduce((a, b) => a + (b - m) * (b - m), 0) / (x.length - 1)); }],
    ncdf: [1, 1, ncdf], npdf: [1, 1, npdf], ninv: [1, 1, ninv],
    bscall: [4, 6, (S, K, T, v, r = 0, q = 0) => bs(S, K, T, r, q, v, "call").price], bsput: [4, 6, (S, K, T, v, r = 0, q = 0) => bs(S, K, T, r, q, v, "put").price],
    delta: [4, 6, (S, K, T, v, r = 0, q = 0) => bs(S, K, T, r, q, v, "call").delta],
    kelly: [2, 2, (p, b) => kelly(p, b)], growth: [3, 3, (f, p, b) => logGrowth(f, p, b)],
    pv: [3, 3, (r, n, cf) => cf / Math.pow(1 + r, n)], fv: [3, 3, (r, n, x) => x * Math.pow(1 + r, n)],
    annuity: [3, 3, (r, n, pmt) => (r === 0 ? pmt * n : pmt * (1 - Math.pow(1 + r, -n)) / r)],
    npv: [2, 99, (r, ...cf) => cf.reduce((a, c, t) => a + c / Math.pow(1 + r, t), 0)], irr: [2, 99, (...cf) => irr(cf)],
    cagr: [3, 3, (a, b, yrs) => Math.pow(b / a, 1 / yrs) - 1], dv01: [2, 2, (price, dur) => price * dur * 1e-4],
    bondret: [2, 3, (dur, dy, cvx = 0) => -dur * dy + 0.5 * cvx * dy * dy], impact: [3, 4, (Q, adv, sig, Y = 0.8) => Y * sig * Math.sqrt(Q / adv)],
    kyle: [2, 2, (sv, su) => sv / (2 * su)], tstat: [2, 2, (sr, yrs) => sr * Math.sqrt(yrs)], breakeven: [2, 2, (vol, days) => vol * Math.sqrt(days / 252)],
  };
  const CALC_CONST = { pi: Math.PI, e: Math.E };
  const SUFFIX = { k: 1e3, m: 1e6, mm: 1e6, bn: 1e9, b: 1e9, t: 1e12, tn: 1e12, bp: 1e-4, bps: 1e-4 };
  function calcTokens(src) {
    const s = String(src).replace(/[×✕]/g, "*").replace(/÷/g, "/").replace(/[−–]/g, "-"), out = [];
    let i = 0;
    while (i < s.length) {
      const ch = s[i];
      if (/\s/.test(ch)) { i++; continue; }
      const num = /^(\d[\d_]*\.?\d*|\.\d+)(e[+-]?\d+)?/i.exec(s.slice(i));
      if (num) {
        let v = Number(num[0].replace(/_/g, "")); i += num[0].length;
        const suf = /^(bps|bp|bn|mm|tn|k|m|b|t)(?![a-z_])/i.exec(s.slice(i));
        if (suf) { v *= SUFFIX[suf[1].toLowerCase()]; i += suf[1].length; }
        out.push({ t: "num", v }); continue;
      }
      const id = /^\$?[a-z_][a-z0-9_]*/i.exec(s.slice(i));
      if (id) { out.push({ t: "id", v: id[0].toLowerCase() }); i += id[0].length; continue; }
      if ("+-*/^(),%!=".includes(ch)) { out.push({ t: ch }); i++; continue; }
      throw new Error(`unexpected "${ch}"`);
    }
    return out;
  }
  function calcEval(src, env = {}, vars = {}) {
    const tk = calcTokens(src);
    let p = 0;
    const peek = () => tk[p] || { t: "end" }, take = (t) => { if (peek().t !== t) throw new Error(`expected "${t}"`); return tk[p++]; };
    let target = null;
    if (tk.length > 2 && tk[0].t === "id" && tk[1].t === "=" && !tk[0].v.startsWith("$")) { target = tk[0].v; p = 2; }
    function sum() { let v = prod(); while (peek().t === "+" || peek().t === "-") { const o = tk[p++].t, r = prod(); v = o === "+" ? v + r : v - r; } return v; }
    function prod() {
      let v = unary();
      for (;;) {
        const t = peek().t;
        if (t === "*" || t === "/") { p++; const r = unary(); v = t === "*" ? v * r : v / r; }
        else if (t === "num" || t === "id" || t === "(") v *= unary();          // implicit multiplication: 2pi, 3(4)
        else return v;
      }
    }
    function unary() { if (peek().t === "-") { p++; return -unary(); } if (peek().t === "+") { p++; return unary(); } return power(); }
    function power() { const b = postfix(); if (peek().t === "^") { p++; return Math.pow(b, unary()); } return b; }
    function postfix() {
      let v = primary();
      for (;;) {
        if (peek().t === "%") { p++; v /= 100; }
        else if (peek().t === "!") { p++; if (!(v >= 0 && v <= 170 && Number.isInteger(v))) throw new Error("factorial needs a whole number up to 170"); let f = 1; for (let k = 2; k <= v; k++) f *= k; v = f; }
        else return v;
      }
    }
    function primary() {
      const t = peek();
      if (t.t === "num") { p++; return t.v; }
      if (t.t === "(") { p++; const v = sum(); take(")"); return v; }
      if (t.t === "id") {
        p++;
        if (peek().t === "(") {
          const f = CALC_FN[t.v];
          if (!f) throw new Error(`unknown function ${t.v}`);
          p++; const args = [];
          if (peek().t !== ")") { args.push(sum()); while (peek().t === ",") { p++; args.push(sum()); } }
          take(")");
          if (args.length < f[0] || args.length > f[1]) throw new Error(`${t.v} takes ${f[0] === f[1] ? f[0] : f[0] + " to " + f[1]} numbers`);
          return f[2](...args);
        }
        if (t.v in vars) return vars[t.v];
        if (t.v in env) { if (!fin(env[t.v])) throw new Error(`${t.v} is unavailable`); return env[t.v]; }
        if (t.v in CALC_CONST) return CALC_CONST[t.v];
        throw new Error(`unknown name ${t.v}`);
      }
      throw new Error(t.t === "end" ? "the expression ends early" : `unexpected "${t.t}"`);
    }
    if (!tk.length) throw new Error("type an expression");
    const v = sum();
    if (p !== tk.length) throw new Error(`unexpected "${peek().t === "id" || peek().t === "num" ? peek().v : peek().t}"`);
    if (target) vars[target] = v;
    return { value: v, assigned: target };
  }
  function calcFormat(v) {
    if (!Number.isFinite(v)) return Number.isNaN(v) ? "not a number" : v > 0 ? "infinity" : MINUS + "infinity";
    if (v === 0) return "0";
    const a = Math.abs(v);
    const s = a >= 1e15 || a < 1e-6 ? v.toExponential(9).replace(/\.?0+e/, "e") : String(Number(v.toPrecision(12)));
    return s.replace(/^-/, MINUS);
  }

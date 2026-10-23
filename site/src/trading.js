  /* =====================================================================================
     trading.js (v0.6): the Prop and Market making desks. Closed forms mirror
     buildout/microstructure.py; tests/test_page.py checks them against the engine.
     ===================================================================================== */
  // ---------- closed forms (engine parity) ----------
  function asQuotes(mid, q, gamma, sigma, tau, k) {
    const r = mid - q * gamma * sigma * sigma * tau, spread = gamma * sigma * sigma * tau + (2 / gamma) * Math.log(1 + gamma / k);
    return { reservation: r, spread, bid: r - spread / 2, ask: r + spread / 2 };
  }
  const gmSpread = (mu, vh, vl) => mu * (vh - vl);
  const sqrtImpact = (qty, adv, sigmaD, Y = 0.7) => (adv > 0 && qty > 0 ? Y * sigmaD * Math.sqrt(qty / adv) : 0);
  function acTrajectory(X, T, N, sigma, eta, lam) {
    const tau = T / N, out = [];
    if (!(lam > 0)) { for (let j = 0; j <= N; j++) out.push(X * (1 - j / N)); return out; }
    const kappa = Math.acosh(1 + (lam * sigma * sigma * tau * tau) / (2 * eta)) / tau;
    for (let j = 0; j <= N; j++) out.push((X * Math.sinh(kappa * (T - j * tau))) / Math.sinh(kappa * T));
    return out;
  }
  function acCost(traj, T, sigma, eta) {
    const N = traj.length - 1, tau = T / N;
    let e = 0, v = 0;
    for (let j = 1; j <= N; j++) { const n = traj[j - 1] - traj[j]; e += (eta / tau) * n * n; v += traj[j] * traj[j]; }
    return { expected: e, sd: Math.sqrt(sigma * sigma * tau * v) };
  }
  // edge arithmetic for a trader who wins b R with probability p and loses 1 R otherwise, paying c R a trade
  function edgeStats(p, b, c) {
    const E = p * b - (1 - p) - c, m = p * b - (1 - p);
    const sd = Math.sqrt(Math.max(1e-12, p * b * b + (1 - p) - m * m));
    return { E, sd, breakeven: (1 + c) / (1 + b), kelly: p - (1 - p) / b, tradesToProve: E > 0 ? Math.pow((2 * sd) / E, 2) : Infinity };
  }
  // log growth per trade risking fraction r of the account
  const growthPerTrade = (p, b, c, r) => (r * (1 + c) >= 1 ? -Infinity : p * Math.log(1 + r * (b - c)) + (1 - p) * Math.log(1 - r * (1 + c)));

  /* ---------- PROP: edge calculator ---------- */
  function readRange(id) { const el = $(id); return el ? Number(el.value) : NaN; }
  function updateEdge() {
    const p = readRange("#pe-p") / 100, b = readRange("#pe-b"), c = readRange("#pe-c"), r = readRange("#pe-r") / 100, n = readRange("#pe-n");
    $("#pe-p-o").textContent = fx(p * 100, 0) + "%"; $("#pe-b-o").textContent = fx(b, 2) + " R"; $("#pe-c-o").textContent = fx(c, 2) + " R";
    $("#pe-r-o").textContent = fx(r * 100, 2) + "%"; $("#pe-n-o").textContent = n + " a day";
    const s = edgeStats(p, b, c), yearTrades = n * 252;
    const sharpe = s.E / s.sd * Math.sqrt(yearTrades);
    $("#pe-E").textContent = sg(s.E, 3) + " R";
    $("#pe-be").textContent = fx(s.breakeven * 100, 1) + "%";
    $("#pe-sr").textContent = fin(sharpe) ? fx(sharpe, 2) : "n/a";
    $("#pe-days").textContent = s.E > 0 ? Math.ceil(s.tradesToProve / n).toLocaleString("en-US") + " days" : "never";
    const out = $("#pe-out"), kel = Math.max(0, s.kelly);
    out.className = "sentence " + (s.E > 0 ? "ok" : "warn");
    out.textContent = s.E > 0
      ? `Each trade earns ${sg(s.E, 3)} R after costs. A ${fx(p * 100, 0)}% win rate needs ${fx(s.breakeven * 100, 1)}% to break even at this payoff, so the margin of error is ${fx((p - s.breakeven) * 100, 1)} points. Proving the edge at t = 2 takes about ${Math.ceil(s.tradesToProve).toLocaleString("en-US")} trades. Full Kelly risks ${fx(kel * 100, 1)}% a trade; the setting risks ${fx(r * 100, 2)}%${r > kel ? ", above Kelly: more risk now buys less growth" : r > kel / 2 ? ", between half and full Kelly" : ", at or below half Kelly"}.`
      : `No edge after costs: a ${fx(p * 100, 0)}% win rate needs a payoff above ${fx((1 - p + c) / p, 2)} R. Every trade loses ${fx(-s.E, 3)} R on average; more size only loses faster.`;
    const box = $("#pe-chart");
    if (box && box.clientWidth) {
      const top = Math.max(0.02, Math.min(0.5, Math.max(kel * 2.4, r * 1.6, 0.05)));
      const pts = [];
      for (let i = 0; i <= 80; i++) { const x = (top * i) / 80, g = growthPerTrade(p, b, c, x) * yearTrades; pts.push([x, fin(g) ? Math.max(-2, g) : NaN]); }
      const marks = [{ x: r, label: "You" }];
      if (kel > 0 && kel < top) marks.push({ x: kel, label: "Kelly" });
      xyChart(box, { series: [{ name: "Growth a year (log)", color: "var(--s1)", pts, area: true }], zero: true, yfmt: (v) => fx(v, 1), xfmt: (x) => "risk " + fx(x * 100, 2) + "% a trade",
        xticks: niceTicks(0, top, 5).filter((x) => x <= top).map((x) => [x, fx(x * 100, x < 0.02 ? 1 : 0) + "%"]), vmarks: marks, label: "Long-run growth by risk per trade", height: 230 });
    }
  }

  /* ---------- PROP: challenge simulator ---------- */
  function simChallenge(o, risk, paths, seed = 5) {
    const rnd = mulberry32(seed);
    let pass = 0, breach = 0, daysPass = [];
    for (let k = 0; k < paths; k++) {
      let eq = 1, done = false;
      for (let d = 1; d <= o.days && !done; d++) {
        const start = eq;
        for (let t = 0; t < o.n; t++) {
          eq += rnd() < o.p ? risk * (o.b - o.c) : -risk * (1 + o.c);
          if (eq <= 1 - o.maxLoss || eq - start <= -o.daily) { breach++; done = true; break; }
          if (eq >= 1 + o.target) { pass++; daysPass.push(d); done = true; break; }
        }
      }
    }
    daysPass.sort((a, b) => a - b);
    return { pass: pass / paths, breach: breach / paths, timeout: 1 - (pass + breach) / paths, medDays: daysPass.length ? daysPass[Math.floor(daysPass.length / 2)] : null };
  }
  let chalTimer = 0;
  function chalState() {
    return { p: readRange("#pc-p") / 100, b: readRange("#pc-b"), c: 0.02, n: readRange("#pc-n"), target: readRange("#pc-t") / 100, maxLoss: readRange("#pc-ml") / 100,
      daily: readRange("#pc-dl") / 100, days: readRange("#pc-days"), fee: readRange("#pc-fee"), risk: readRange("#pc-r") / 100 };
  }
  function labelsChallenge(o) {
    $("#pc-p-o").textContent = fx(o.p * 100, 0) + "%"; $("#pc-b-o").textContent = fx(o.b, 2) + " R"; $("#pc-n-o").textContent = o.n + " a day";
    $("#pc-t-o").textContent = fx(o.target * 100, 0) + "%"; $("#pc-ml-o").textContent = fx(o.maxLoss * 100, 0) + "%"; $("#pc-dl-o").textContent = fx(o.daily * 100, 1) + "%";
    $("#pc-days-o").textContent = o.days + " days"; $("#pc-fee-o").textContent = money(o.fee); $("#pc-r-o").textContent = fx(o.risk * 100, 2) + "%";
  }
  function updateChallenge() {
    const o = chalState();
    labelsChallenge(o);
    const me = simChallenge(o, o.risk, 3000);
    const grid = [];
    for (let r = 0.0025; r <= 0.0301; r += 0.0025) grid.push(r);
    const curve = grid.map((r) => ({ r, ...simChallenge(o, r, 1500, 9) }));
    const best = curve.reduce((a, x) => (x.pass > a.pass ? x : a));
    const kink = o.daily / (o.n * (1 + o.c));     // risk at which a day of all losses hits the daily limit
    $("#pc-pass").textContent = fx(me.pass * 100, 1) + "%";
    $("#pc-breach").textContent = fx(me.breach * 100, 1) + "%";
    $("#pc-cost").textContent = me.pass > 0 ? money(o.fee / me.pass) : "n/a";
    $("#pc-best").textContent = fx(best.r * 100, 2) + "%";
    const out = $("#pc-out");
    out.className = "sentence " + (me.pass >= 0.3 ? "ok" : "warn");
    out.textContent = `At ${fx(o.risk * 100, 2)}% a trade, ${fx(me.pass * 100, 0)}% of 3,000 simulated attempts pass, ${fx(me.breach * 100, 0)}% breach a loss limit and ${fx(me.timeout * 100, 0)}% run out of days${me.medDays ? `; passes take a median ${me.medDays} days` : ""}. The risk that maximizes the pass rate is ${fx(best.r * 100, 2)}% (${fx(best.pass * 100, 0)}%): a barrier problem, not a growth problem, so Kelly does not apply. Each funded account costs about ${me.pass > 0 ? money(o.fee / me.pass) : "everything"} in fees. The curve steps rather than slopes: above ${fx(kink * 100, 2)}% a trade, ${o.n} losses in one day breach the ${fx(o.daily * 100, 1)}% daily limit, and the number of wins needed to reach the target falls in whole trades.`;
    const box = $("#pc-chart");
    if (box && box.clientWidth) {
      xyChart(box, { series: [{ name: "Pass", color: "var(--s3)", pts: curve.map((x) => [x.r, x.pass]), width: 2.5, dots: true }, { name: "Breach", color: "var(--red)", pts: curve.map((x) => [x.r, x.breach]) }],
        yDomain: [0, 1], yfmt: (v) => fx(v * 100, 0) + "%", xfmt: (x) => "risk " + fx(x * 100, 2) + "%", xticks: [0.005, 0.01, 0.015, 0.02, 0.025, 0.03].map((x) => [x, fx(x * 100, 1) + "%"]),
        vmarks: [{ x: o.risk, label: "You" }], snapXs: grid, label: "Pass and breach probability by risk per trade", height: 240 });
    }
  }
  const scheduleChallenge = () => { labelsChallenge(chalState()); clearTimeout(chalTimer); chalTimer = setTimeout(() => guard("Challenge simulator", updateChallenge, $("#pc-chart")), 80); };

  /* ---------- PROP: pod economics ---------- */
  function podNet(gross, pass, mgmt, perf) {
    const afterPass = gross - pass - mgmt;
    const fee = afterPass > 0 ? afterPass * perf : 0;
    return { afterPass, fee, net: afterPass - fee };
  }
  function updatePods() {
    const g = readRange("#pp-g") / 100, pt = readRange("#pp-pt") / 100, mg = readRange("#pp-mg") / 100, pf = readRange("#pp-pf") / 100, vol = readRange("#pp-vol") / 100;
    $("#pp-g-o").textContent = fx(g * 100, 1) + "%"; $("#pp-pt-o").textContent = fx(pt * 100, 1) + "%"; $("#pp-mg-o").textContent = fx(mg * 100, 1) + "%";
    $("#pp-pf-o").textContent = fx(pf * 100, 0) + "%"; $("#pp-vol-o").textContent = fx(vol * 100, 1) + "%";
    const r = podNet(g, pt, mg, pf), cash = 0.0427;
    $("#pp-net").textContent = sPct(r.net, 1);
    $("#pp-keep").textContent = g > 0 ? fx(Math.max(0, r.net / g) * 100, 0) + "%" : "n/a";
    $("#pp-sr").textContent = vol > 0 ? `${fx((g - cash) / vol, 2)} → ${fx((r.net - cash) / vol, 2)}` : "n/a";
    const need = cash / (1 - pf) + pt + mg;   // gross that leaves the LP exactly the cash rate
    $("#pp-out").textContent = `Of ${sPct(g, 1)} gross, pass-through costs take ${fx(pt * 100, 1)} points, the management fee ${fx(mg * 100, 1)}, the performance fee ${fx(r.fee * 100, 1)}: the LP keeps ${sPct(r.net, 1)}. Just matching cash (4.27%) takes ${fx(need * 100, 1)}% gross. Balyasny's 2023, from the field manual: 15.2% gross became 2.8% net after $768M of pass-throughs.`;
    barsH($("#pp-chart"), [{ label: "Gross return", v: g * 100, color: "var(--s1)" }, { label: "Pass-through", v: -pt * 100, color: "var(--red)" }, { label: "Management fee", v: -mg * 100, color: "var(--red)" },
      { label: "Performance fee", v: -r.fee * 100, color: "var(--red)" }, { label: "Net to the LP", v: r.net * 100, color: "var(--s3)", strong: true }], { fmt: (v) => sg(v, 1) + "%", label: "From gross to net", labelW: 130 });
  }

  /* ---------- MARKET MAKING: Avellaneda-Stoikov ---------- */
  function simAS(o, symmetric, seed) {
    const rnd = mulberry32(seed), dt = o.T / o.steps, sq = Math.sqrt(dt), pnl = new Float64Array(o.paths), inv = new Float64Array(o.paths);
    let fills = 0;
    const sample = [];
    for (let k = 0; k < o.paths; k++) {
      let s = 100, q = 0, cash = 0;
      for (let i = 0; i < o.steps; i++) {
        const tau = o.T - i * dt, spread = o.gamma * o.sigma * o.sigma * tau + (2 / o.gamma) * Math.log(1 + o.gamma / o.k);
        const r = symmetric ? s : s - q * o.gamma * o.sigma * o.sigma * tau, bid = r - spread / 2, ask = r + spread / 2;
        if (rnd() < o.A * Math.exp(-o.k * (s - bid)) * dt) { q += 1; cash -= bid; fills++; }
        if (rnd() < o.A * Math.exp(-o.k * (ask - s)) * dt) { q -= 1; cash += ask; fills++; }
        s += o.sigma * sq * (rnd() < 0.5 ? -1 : 1);
        if (k === 0) sample.push(q);
      }
      pnl[k] = cash + q * s; inv[k] = q;
    }
    const m = pnl.reduce((a, x) => a + x, 0) / o.paths, sd = Math.sqrt(pnl.reduce((a, x) => a + (x - m) * (x - m), 0) / (o.paths - 1));
    const qm = inv.reduce((a, x) => a + x, 0) / o.paths, qsd = Math.sqrt(inv.reduce((a, x) => a + (x - qm) * (x - qm), 0) / (o.paths - 1));
    return { pnl: Array.from(pnl), mean: m, sd, invSd: qsd, fills: fills / o.paths, sample };
  }
  function asState() { return { sigma: readRange("#as-sig"), gamma: readRange("#as-g"), k: readRange("#as-k"), A: readRange("#as-A"), T: 1, steps: 200, paths: 600 }; }
  function updateAS() {
    const o = asState();
    $("#as-sig-o").textContent = fx(o.sigma, 1); $("#as-g-o").textContent = fx(o.gamma, 2); $("#as-k-o").textContent = fx(o.k, 1); $("#as-A-o").textContent = String(o.A);
    const a = simAS(o, false, 21), s = simAS(o, true, 21);
    $("#as-mean").textContent = `${fx(a.mean, 1)} vs ${fx(s.mean, 1)}`;
    $("#as-sd").textContent = `${fx(a.sd, 1)} vs ${fx(s.sd, 1)}`;
    $("#as-ratio").textContent = `${fx(a.mean / a.sd, 2)} vs ${fx(s.mean / s.sd, 2)}`;
    $("#as-inv").textContent = `${fx(a.invSd, 1)} vs ${fx(s.invSd, 1)}`;
    const q0 = asQuotes(100, 0, o.gamma, o.sigma, 1, o.k), q5 = asQuotes(100, 5, o.gamma, o.sigma, 1, o.k);
    $("#as-out").textContent = `Quoted spread at the start: ${fx(q0.spread, 2)}. Long 5 units, the desk shades its reservation price down by ${fx(100 - q5.reservation, 2)} so its bid gets hit less and its ask lifted more. Skewing for inventory cuts the spread of outcomes from ${fx(s.sd, 1)} to ${fx(a.sd, 1)} and inventory swings from ${fx(s.invSd, 1)} to ${fx(a.invSd, 1)} units, for ${fx(s.mean - a.mean, 1)} less average P&L: the market maker sells immediacy and refuses to warehouse risk.`;
    const box = $("#as-chart");
    if (box && box.clientWidth) {
      const lo = Math.min(...a.pnl, ...s.pnl), hi = Math.max(...a.pnl, ...s.pnl), bins = 24, w = (hi - lo) / bins || 1;
      const hist = (arr) => { const c = new Array(bins).fill(0); arr.forEach((x) => { c[Math.min(bins - 1, Math.floor((x - lo) / w))]++; }); return c.map((v, i) => [lo + (i + 0.5) * w, v / arr.length]); };
      xyChart(box, { series: [{ name: "Inventory-skewed", color: "var(--s1)", pts: hist(a.pnl), width: 2.5 }, { name: "Symmetric", color: "var(--s2)", pts: hist(s.pnl) }], yfmt: (v) => fx(v * 100, 0) + "%",
        xfmt: (x) => "P&L " + fx(x, 0), xticks: niceTicks(lo, hi, 5).map((x) => [x, fx(x, 0)]), label: "Distribution of end-of-day P&L, 600 days each", height: 230 });
    }
    const ib = $("#as-inv-chart");
    if (ib && ib.clientWidth) xyChart(ib, { series: [{ name: "Skewed", color: "var(--s1)", pts: a.sample.map((q, i) => [i, q]) }, { name: "Symmetric", color: "var(--s2)", pts: s.sample.map((q, i) => [i, q]) }],
      zero: true, yfmt: (v) => fx(v, 0), xfmt: (x) => "step " + x, xticks: [[0, "open"], [100, "midday"], [199, "close"]], label: "Inventory through one simulated day", height: 200 });
  }

  /* ---------- MARKET MAKING: adverse selection ---------- */
  function updateGM() {
    const mu = readRange("#gm-mu") / 100, info = readRange("#gm-info"), spread = readRange("#gm-s");
    $("#gm-mu-o").textContent = fx(mu * 100, 0) + "%"; $("#gm-info-o").textContent = fx(info, 0) + " bp"; $("#gm-s-o").textContent = fx(spread, 1) + " bp";
    const fair = gmSpread(mu, info / 2, -info / 2), edge = spread / 2 - fair / 2;
    $("#gm-fair").textContent = fx(fair, 1) + " bp";
    $("#gm-edge").textContent = sg(edge, 2) + " bp";
    const out = $("#gm-out");
    out.className = "sentence " + (edge >= 0 ? "ok" : "warn");
    out.textContent = `With ${fx(mu * 100, 0)}% of orders informed about a ${fx(info, 0)} bp move, the break-even spread is ${fx(fair, 1)} bp. Quoting ${fx(spread, 1)} bp ${edge >= 0 ? `earns ${fx(edge, 2)} bp a trade` : `loses ${fx(-edge, 2)} bp a trade to better-informed traders`}. This is why wholesalers pay for retail order flow: at a few percent informed, a tight spread still makes money, and about half of US share volume (50.6% in September) now trades off exchange.`;
    const box = $("#gm-chart");
    if (box && box.clientWidth) {
      const pts = []; for (let i = 0; i <= 50; i++) { const m = i / 100; pts.push([m, gmSpread(m, info / 2, -info / 2)]); }
      xyChart(box, { series: [{ name: "Break-even spread", color: "var(--s1)", pts, width: 2.5 }], hlines: [{ y: spread, label: `Your spread ${fx(spread, 1)} bp`, color: "var(--s2)" }],
        vmarks: [{ x: mu, label: "Now" }], yfmt: (v) => fx(v, 0) + " bp", xfmt: (x) => fx(x * 100, 0) + "% informed", xticks: [0, 0.1, 0.2, 0.3, 0.4, 0.5].map((x) => [x, fx(x * 100, 0) + "%"]), label: "Break-even spread by share of informed flow", height: 220 });
    }
  }

  /* ---------- MARKET MAKING: execution ---------- */
  function exState() { return { qty: readRange("#ex-q") / 100, sigma: readRange("#ex-sig") / 100, spread: readRange("#ex-sp"), days: readRange("#ex-T"), lam: readRange("#ex-l"), Y: readRange("#ex-Y") }; }
  function updateExec() {
    const o = exState();
    $("#ex-q-o").textContent = fx(o.qty * 100, 1) + "% of ADV"; $("#ex-sig-o").textContent = fx(o.sigma * 100, 1) + "%"; $("#ex-sp-o").textContent = fx(o.spread, 1) + " bp";
    $("#ex-T-o").textContent = o.days + (o.days === 1 ? " day" : " days"); $("#ex-l-o").textContent = o.lam === 0 ? "0 (even pace)" : String(o.lam); $("#ex-Y-o").textContent = fx(o.Y, 2);
    const X = o.qty, N = Math.max(4, o.days * 4), I = sqrtImpact(X, 1, o.sigma, o.Y), eta = I / (X / o.days || 1);
    const lamScale = (lam) => (lam * eta) / (o.sigma * o.sigma || 1e-9);
    const twap = acTrajectory(X, o.days, N, o.sigma, eta, 0), mine = acTrajectory(X, o.days, N, o.sigma, eta, lamScale(o.lam)), fast = acTrajectory(X, o.days, N, o.sigma, eta, lamScale(Math.max(10, o.lam * 4)));
    const cost = (tr) => { const c = acCost(tr, o.days, o.sigma, eta); return { e: (c.expected / X) * 1e4, sd: (c.sd / X) * 1e4 }; };
    const cT = cost(twap), cM = cost(mine);
    $("#ex-imp").textContent = fx(I * 1e4, 1) + " bp";
    $("#ex-tot").textContent = fx(I * 1e4 + o.spread / 2, 1) + " bp";
    $("#ex-cost").textContent = `${fx(cM.e, 1)} ± ${fx(cM.sd, 1)} bp`;
    $("#ex-out").textContent = `Trading ${fx(o.qty * 100, 1)}% of a day's volume costs about ${fx(I * 1e4, 1)} bp of impact by the square-root law (Y = ${fx(o.Y, 2)}), plus ${fx(o.spread / 2, 1)} bp of half-spread. Four times the size costs only twice the impact per share. Spreading it over ${o.days} ${o.days === 1 ? "day" : "days"}: the even pace expects ${fx(cT.e, 1)} bp with ${fx(cT.sd, 1)} bp of timing risk; the chosen urgency trades ${fx(cM.e - cT.e, 1)} bp more expected cost for ${fx(cT.sd - cM.sd, 1)} bp less risk.`;
    const box = $("#ex-chart");
    if (box && box.clientWidth) {
      const t = (tr) => tr.map((x, j) => [(j / N) * o.days, (x / X) * 100]);
      xyChart(box, { series: [{ name: "Even pace", color: "var(--muted)", pts: t(twap) }, { name: "Your urgency", color: "var(--s1)", pts: t(mine), width: 2.5 }, { name: "High urgency", color: "var(--s2)", pts: t(fast) }],
        yDomain: [0, 100], yfmt: (v) => fx(v, 0) + "%", xfmt: (x) => "day " + fx(x, 2), xticks: Array.from({ length: o.days + 1 }, (_, d) => [d, "day " + d]), label: "Share of the order still to trade (Almgren-Chriss)", height: 220 });
    }
    const fb = $("#ex-frontier");
    if (fb && fb.clientWidth) {
      const pts = [0, 0.25, 0.5, 1, 2, 4, 8, 16, 32, 64].map((l) => { const c = cost(acTrajectory(X, o.days, N, o.sigma, eta, lamScale(l))); return [c.sd, c.e]; });
      xyChart(fb, { series: [{ name: "Efficient frontier", color: "var(--s1)", pts, dots: true, width: 2 }], yfmt: (v) => fx(v, 1) + " bp", xfmt: (x) => "risk " + fx(x, 1) + " bp",
        xticks: niceTicks(Math.min(...pts.map((p) => p[0])), Math.max(...pts.map((p) => p[0])), 4).map((x) => [x, fx(x, 0)]), snapXs: pts.map((p) => p[0]), label: "Expected cost against timing risk", height: 200 });
    }
  }

  /* ---------- the book's own liquidity, after the Databento run ---------- */
  function renderTape() {
    const box = $("#mm-tape");
    if (!box) return;
    const r = LIVE.report && LIVE.report.roll_spread_bps;
    if (!r || typeof r !== "object" || !Object.values(r).some(fin)) {
      const e = h("div", "empty");
      e.append(h("strong", null, "Live panel: fills from the book run."), h("span", null, "With the Databento key in place, the engine estimates each name's effective spread from its daily closes (Roll) and adds it here."));
      box.replaceChildren(e);
      return;
    }
    box.replaceChildren(tableBlock(["Ticker", "Roll spread, bp"], Object.entries(r).filter(([, v]) => fin(v)).sort((a, b) => b[1] - a[1]).map(([t, v]) => [t, fx(v, 1)])));
  }

  function buildTrading() {
    [[["#pe-p", "#pe-b", "#pe-c", "#pe-r", "#pe-n"], updateEdge, "Edge calculator"], [["#pp-g", "#pp-pt", "#pp-mg", "#pp-pf", "#pp-vol"], updatePods, "Pod economics"],
     [["#gm-mu", "#gm-info", "#gm-s"], updateGM, "Adverse selection"], [["#ex-q", "#ex-sig", "#ex-sp", "#ex-T", "#ex-l", "#ex-Y"], updateExec, "Execution"]].forEach(([ids, fn, name]) =>
      ids.forEach((id) => { const el = $(id); if (el) el.addEventListener("input", () => guard(name, fn)); }));
    ["#pc-p", "#pc-b", "#pc-n", "#pc-t", "#pc-ml", "#pc-dl", "#pc-days", "#pc-fee", "#pc-r"].forEach((id) => { const el = $(id); if (el) el.addEventListener("input", scheduleChallenge); });
    let asTimer = 0;
    ["#as-sig", "#as-g", "#as-k", "#as-A"].forEach((id) => { const el = $(id); if (el) el.addEventListener("input", () => { clearTimeout(asTimer); asTimer = setTimeout(() => guard("Market maker", updateAS, $("#as-chart")), 60); }); });
  }

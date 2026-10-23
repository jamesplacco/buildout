  /* =====================================================================================
     labs.js (v0.14): the labs (every trader's claim, tested on the longest data the engine reads) and the card room
     (poker, haggling, private markets and the theory of storage). The calculators mirror buildout/games2.py exactly
     (tests/test_v14.py holds them equal); the lab results are the engine's (buildout/labs.py), shipped as derived
     numbers only.
     ===================================================================================== */
  const LB = LABS_SNAP;
  const G_RANKS = "23456789TJQKA", G_SUITS = "cdhs";
  const G_CATS = ["High card", "Pair", "Two pair", "Three of a kind", "Straight", "Flush", "Full house", "Four of a kind", "Straight flush"];
  function gCard(s) {
    const t = String(s || "").trim();
    if (t.length !== 2) return null;
    const r = G_RANKS.indexOf(t[0].toUpperCase()), u = G_SUITS.indexOf(t[1].toLowerCase());
    return r < 0 || u < 0 ? null : r * 4 + u;
  }
  function gStraightTop(mask) {
    for (let top = 12; top > 3; top--) if (((mask >> (top - 4)) & 0b11111) === 0b11111) return top;
    if ((mask & 0b1000000001111) === 0b1000000001111) return 3;
    return -1;
  }
  function gEval7(cards) {
    const counts = new Array(13).fill(0), suits = [0, 0, 0, 0], smask = [0, 0, 0, 0];
    for (const c of cards) { const r = Math.floor(c / 4), s = c % 4; counts[r]++; suits[s]++; smask[s] |= 1 << r; }
    const pack = (cat, ks) => { let v = cat; const k5 = ks.concat([0, 0, 0, 0, 0]).slice(0, 5); for (const k of k5) v = v * 13 + k; return v; };
    for (let s = 0; s < 4; s++) if (suits[s] >= 5) { const top = gStraightTop(smask[s]); if (top >= 0) return pack(8, [top]); }
    const desc = [12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1, 0];
    const quads = desc.filter((r) => counts[r] === 4), trips = desc.filter((r) => counts[r] === 3), pairs = desc.filter((r) => counts[r] === 2);
    if (quads.length) { const q = quads[0]; return pack(7, [q, Math.max(...desc.filter((r) => counts[r] && r !== q))]); }
    if (trips.length && (trips.length > 1 || pairs.length)) return pack(6, [trips[0], Math.max(...trips.slice(1).concat(pairs))]);
    for (let s = 0; s < 4; s++) if (suits[s] >= 5) return pack(5, desc.filter((r) => (smask[s] >> r) & 1).slice(0, 5));
    let mask = 0;
    for (let r = 0; r < 13; r++) if (counts[r]) mask |= 1 << r;
    const top = gStraightTop(mask);
    if (top >= 0) return pack(4, [top]);
    const singles = desc.filter((r) => counts[r] === 1);
    if (trips.length) return pack(3, [trips[0]].concat(singles.slice(0, 2)));
    if (pairs.length >= 2) { const rest = singles.concat(pairs.slice(2)).sort((a, b) => b - a); return pack(2, pairs.slice(0, 2).concat(rest.slice(0, 1))); }
    if (pairs.length) return pack(1, [pairs[0]].concat(singles.slice(0, 3)));
    return pack(0, singles.slice(0, 5));
  }
  const gCategory = (v) => G_CATS[Math.floor(v / 13 ** 5)];
  function gEquity(hero, board = [], opponents = 1, trials = 4000, seed = 7) {
    const rnd = mulberry32(seed), dead = new Set(hero.concat(board)), deck = [];
    for (let c = 0; c < 52; c++) if (!dead.has(c)) deck.push(c);
    let win = 0, tie = 0;
    for (let t = 0; t < trials; t++) {
      const d = deck.slice(), need = 2 * opponents + (5 - board.length);
      for (let i = 0; i < need; i++) { const j = i + Math.floor(rnd() * (d.length - i)); const x = d[i]; d[i] = d[j]; d[j] = x; }
      const opp = []; for (let k = 0; k < opponents; k++) opp.push(d.slice(2 * k, 2 * k + 2));
      const full = board.concat(d.slice(2 * opponents, need));
      const hv = gEval7(hero.concat(full));
      let best = -1; for (const o of opp) best = Math.max(best, gEval7(o.concat(full)));
      if (hv > best) win += 1;
      else if (hv === best) { let n = 1; for (const o of opp) if (gEval7(o.concat(full)) === hv) n++; tie += 1 / n; }
    }
    return { equity: (win + tie) / trials, win: win / trials, tie: tie / trials, trials };
  }
  const gPotOdds = (pot, call) => call / (pot + call);
  const gCallEv = (eq, pot, call) => eq * (pot + call) - call;
  const gKelly = (p, b) => Math.max(0, p - (1 - p) / b);
  const gRuin = (mu, sigma, bank) => (mu <= 0 ? 1 : Math.exp(-2 * mu * bank / sigma ** 2));
  const gBankrollFor = (mu, sigma, ruin) => -Math.log(ruin) * sigma ** 2 / (2 * mu);
  function gRubinstein(d1, d2) { const x = (1 - d2) / (1 - d1 * d2); return { first: x, second: 1 - x }; }
  function gNash(pie, d1, d2, power = 0.5) { const s = pie - d1 - d2; return s <= 0 ? { deal: false, x1: null, x2: null, surplus: s } : { deal: true, x1: d1 + power * s, x2: d2 + (1 - power) * s, surplus: s }; }
  function gBestOffer(cost, lo, hi) {
    if (!(hi > lo)) return null;
    const p = Math.min(hi, Math.max(lo, (hi + cost) / 2)), acc = (hi - p) / (hi - lo);
    return { price: p, accept: acc, expected: Math.max(0, (p - cost) * acc), zopa: Math.max(0, hi - Math.max(cost, lo)) };
  }
  const gNpv = (rate, flows, times) => flows.reduce((a, f, i) => a + f / (1 + rate) ** (times ? times[i] : i), 0);
  function gIrr(flows, times) {
    let lo = -0.99, hi = 10, flo = gNpv(lo, flows, times), fhi = gNpv(hi, flows, times);
    if (flo * fhi > 0) return null;
    for (let k = 0; k < 300; k++) {
      const mid = (lo + hi) / 2, fm = gNpv(mid, flows, times);
      if (fm === 0 || hi - lo < 1e-13) return mid;
      if (flo * fm < 0) { hi = mid; fhi = fm; } else { lo = mid; flo = fm; }
    }
    return (lo + hi) / 2;
  }
  function gMultiples(calls, dists, nav) { const paid = calls.reduce((a, b) => a + b, 0), d = dists.reduce((a, b) => a + b, 0); return { tvpi: (d + nav) / paid, dpi: d / paid, rvpi: nav / paid }; }
  function gPme(calls, dists, nav, index) {
    const end = index[index.length - 1];
    const fd = dists.reduce((a, x, i) => a + x * end / index[i], 0) + nav, fc = calls.reduce((a, x, i) => a + x * end / index[i], 0);
    return fd / fc;
  }
  function gYale(commit = 100, years = 12, rc = [0.25, 0.333, 0.5, 0.5, 0.5, 0.5], growth = 0.1, bow = 2.5, yld = 0, life = 12) {
    let paid = 0, nav = 0;
    const rows = [];
    for (let t = 1; t <= years; t++) {
      const r = t - 1 < rc.length ? rc[t - 1] : rc[rc.length - 1], c = r * (commit - paid);
      paid += c;
      const rd = Math.max(yld, (t / life) ** bow), d = Math.min(1, rd) * nav * (1 + growth);
      nav = nav * (1 + growth) + c - d;
      rows.push({ year: t, call: c, dist: d, nav, paid });
    }
    let cum = 0;
    rows.forEach((row) => { cum += row.dist - row.call; row.net_cum = cum; });
    const flows = rows.map((r) => -r.call + r.dist);
    flows[flows.length - 1] += rows[rows.length - 1].nav;
    const trough = rows.reduce((a, r) => (r.net_cum < a.net_cum ? r : a), rows[0]);
    const be = rows.find((r) => r.net_cum >= 0);
    return { rows, irr: gIrr(flows, rows.map((r) => r.year)), trough: trough.net_cum, trough_year: trough.year, breakeven_year: be ? be.year : null,
      tvpi: (rows.reduce((a, r) => a + r.dist, 0) + rows[rows.length - 1].nav) / rows[rows.length - 1].paid };
  }
  const gCarry = (spot, r, u, y, T) => spot * Math.exp((r + u - y) * T);
  const gConv = (spot, fut, r, u, T) => r + u - Math.log(fut / spot) / T;
  const gRoll = (near, far, months) => Math.log(near / far) * 12 / months;

  /* ---------- the labs desk ---------- */
  const lPct = (v, d = 0) => (fin(v) ? `${v < 0 ? MINUS : ""}${Math.abs(v * 100).toFixed(d)}%` : "n/a");
  const lNum = (v, d = 2) => fx(v, d);
  const lDate = (s) => { const t = String(s || ""); const y = +t.slice(0, 4), m = +t.slice(5, 7) || 1, d = +t.slice(8, 10) || 15; return y + (m - 1) / 12 + (d - 1) / 365; };
  function labsOk(L) {
    try { return !!(L && L.trend && L.trend.full && L.valuation && L.valuation.cape && L.readings && L.multiple_testing && Array.isArray(L.multiple_testing.rows)); } catch (e) { return false; }
  }
  function renderLabsDesk() {
    if (!$("#lb-tiles") || !labsOk(LB)) { const b = $("#lb-tiles"); if (b && !b.children.length) b.append(h("p", "hint", "The labs data is missing or malformed.")); return; }
    const tiles = $("#lb-tiles");
    const T = LB.trend, V = LB.valuation, R = LB.readings, MT = LB.multiple_testing;
    if (!tiles.children.length) {
      [[`${lNum(T.full.rule.sharpe)} vs ${lNum(T.full.hold.sharpe)}`, "10-month rule vs holding", `Sharpe on ${Math.round(T.years)} years, acting a month late`],
        [`${lPct(T.full.rule.maxdd)} vs ${lPct(T.full.hold.maxdd)}`, "Worst drawdown", "the rule's real gift"],
        [`${(T.spa_p * 100).toFixed(1)}%`, "Luck explains the best length", "on return, across 22 lengths"],
        [fx(V.cape.now, 1), "CAPE", `${lPct(V.cape.percentile)} of months were cheaper; source ${V.cape.now_source === "research" ? "multpl (secondary)" : "computed"}`],
        [lPct(V.cape.implied_10y_real, 1), "Implied ten-year real return", `80% range ${lPct(V.cape.range80[0])} to ${lPct(V.cape.range80[1])}`],
        [lPct(LB.regimes.p_now[1]), "Chance of the turbulent regime", "Hamilton Markov switching"],
        [`${MT.bh_5pct} of ${MT.n}`, "Tests that survive", `after the false discovery rate; ${MT.holm_5pct} after Holm`]].forEach(([v, k, s]) => { const d = h("div", "at-kpi"); d.append(h("b", null, v), h("span", null, k), h("small", null, s)); tiles.append(d); });
      $("#lb-sum").textContent = (LB.findings || []).join(" ");
      lReadings();
      lTables();
      wireCardRoom();
    }
    lCharts();
  }
  function lReadings() {
    const box = $("#lb-read");
    const R = LB.readings, sp = R.sp500;
    const card = (title, rows, note) => { const d = h("div", "panel lb-read"); d.append(h("span", "panel-title", title)); const dl = h("dl", "lb-dl"); rows.forEach(([k, v]) => { dl.append(h("dt", null, k), h("dd", null, v)); }); d.append(dl); if (note) d.append(h("p", "hint", note)); return d; };
    if (sp) box.append(card(`${sp.name} · ${sp.date}`, [["vs 10-month average", lPct(sp.vs_ma, 1)], ["RSI(14), monthly", fx(sp.rsi14, 0)], ["12-1 momentum", lPct(sp.mom12_1, 1)], ["From its peak", lPct(sp.dd, 1)]],
      sp.vs_ma > 0 ? "Above the 10-month average: the trend rule stays invested." : "Below the 10-month average: the trend rule steps aside."));
    ["brent", "wti", "gas", "vix"].forEach((k) => {
      const r = R[k];
      if (!r) return;
      box.append(card(`${r.name} · ${r.date}`, [["vs 200-day average", lPct(r.vs_ma200, 1)], ["50-day vs 200-day", r.golden ? "above (golden cross)" : "below"], ["RSI(14)", fx(r.rsi14, 0)],
        ["MACD vs signal", r.macd > r.macd_signal ? "above" : "below"], ["Bollinger %b", fx(r.pct_b, 2)], ["One-year volatility", lPct(r.vol1y)]], null));
    });
  }
  function lTables() {
    fillTable($("#lb-osc"), ["Signal", "Market", "Horizon", "Months or days on", "Edge per period", "t (Newey-West)", "p"],
      LB.oscillators.map((o) => [o.name, o.asset, o.per_year === 12 ? `${o.h} month` : `${o.h} days`, `${o.n_on.toLocaleString()} of ${(o.n_on + o.n_off).toLocaleString()}`, lPct(o.diff, 2), fx(o.t, 2), fx(o.p, 3)]), 2);
    fillTable($("#lb-mt"), ["Test", "p", "Holm", "BH (false discovery rate)", "Survives?"],
      LB.multiple_testing.rows.slice().sort((a, b) => a.p - b.p).map((r) => [r.test, fx(r.p, 4), fx(r.holm, 4), fx(r.bh, 4), r.holm < 0.05 ? "Holm and BH" : r.bh < 0.05 ? "BH only" : r.p < 0.05 ? "raw only" : "no"]), 1);
    fillTable($("#lb-garch"), ["Market", "α (shock)", "β (memory)", "Persistence", "Half-life (days)", "Now, annual", "Long run, annual", "Kurtosis"],
      ["brent", "wti", "gas"].filter((k) => LB.volatility[k]).map((k) => { const g = LB.volatility[k]; return [g.name, fx(g.alpha, 3), fx(g.beta, 3), fx(g.persistence, 4), g.half_life ? fx(g.half_life, 0) : "integrated", lPct(g.annual_current), g.annual_long ? lPct(g.annual_long) : "none (integrated)", fx(g.tails.kurtosis, 0)]; }), 1);
    fillTable($("#lb-vr"), ["Series", "q", "Variance ratio", "Null", "z", "p"], LB.randomness.map((v) => [v.series, String(v.q), fx(v.vr, 2), fx(v.null, 2), fx(v.z, 2), fx(v.p, 3)]), 1);
    const cal = LB.calendar, rows = [];
    ["since 1871", "since 1950"].forEach((k) => { const c = cal[k]; if (c) rows.push([`Sell in May, ${k}`, lPct(c.winter.mean, 2), lPct(c.summer.mean, 2), lPct(c.diff.est, 2), fx(c.diff.t, 2), fx(c.diff.p, 3)]); });
    fillTable($("#lb-cal"), ["Test", "Nov to Apr, per month", "May to Oct, per month", "Gap", "t", "p"], rows, 1);
    const bw = LB.spreads.brent_wti, go = LB.spreads.gold_oil;
    fillTable($("#lb-spr"), ["Spread", "Now", "Long-run", "Evidence", "Half-life"], [["Brent minus WTI", `$${fx(bw.spread_now, 2)} (z ${fx(bw.z_now, 1)})`, `$${fx(bw.spread_mean, 2)}`, `cointegrated, ADF t ${fx(bw.adf_t, 1)}, p ${fx(bw.p, 3)}`, `${fx(bw.half_life, 0)} days`],
      go ? ["Gold / Brent (barrels per ounce)", fx(go.now, 1), `median ${fx(go.median, 1)}`, `more than ${lPct(go.percentile)} of months since ${String(go.from || "").slice(0, 4)}`, "slow"] : null].filter(Boolean), 1);
    const vs = LB.valuation.signals;
    fillTable($("#lb-val"), ["Valuation measure", "Slope, 10-year", "t", "In-sample R²", "Out-of-sample R², 10-year", "Out-of-sample R², 1-year"],
      Object.entries(vs).map(([k, v]) => [k, fx(v["10y"].slope, 3), fx(v["10y"].t, 1), fx(v["10y"].r2, 2), fx(v["10y"].oos_r2, 2), fx(v["1y"].oos_r2, 3)]), 1);
  }
  function lCharts() {
    const T = LB.trend, c = T.curve;
    xyChart($("#lb-curve"), { height: 240, label: "Log wealth: holding against the 10-month rule", series: [
      { pts: c.dates.map((d, i) => [lDate(d), c.hold[i]]), color: "var(--s1)", name: "Hold" }, { pts: c.dates.map((d, i) => [lDate(d), c.rule[i]]), color: "var(--good)", name: "10-month rule" }],
      xticks: [1880, 1920, 1960, 2000, 2020].map((y) => [y, String(y)]), yfmt: (v) => fx(v, 0) });
    const lens = Object.entries(T.lengths).map(([n, s]) => ({ label: `${n}`, v: s, color: +n === T.best ? "var(--warn)" : +n === 10 ? "var(--good)" : "var(--s1)", lbl: +n === T.best || +n === 10 ? fx(s, 2) : "" }));
    barsV($("#lb-lens"), lens, { fmt: (v) => fx(v, 2), height: 200, label: "Sharpe ratio by moving-average length in months" });
    lScatter($("#lb-cape"));
    const rg = LB.regimes.path;
    xyChart($("#lb-reg"), { height: 200, label: "Chance of the turbulent regime", series: [{ pts: rg.dates.map((d, i) => [lDate(d), rg.p_turbulent[i]]), color: "var(--bad)", name: "P(turbulent)" }],
      xticks: [1930, 1960, 1990, 2020].map((y) => [y, String(y)]), yfmt: (v) => lPct(v), yDomain: [0, 1] });
    const b = LB.readings.brent;
    if (b && b.derived) {
      const dv = b.derived;
      xyChart($("#lb-brent"), { height: 200, label: "Brent against its 200-day average", series: [{ pts: dv.dates.map((d, i) => [lDate(d), dv.vs_ma200[i]]).filter((p) => fin(p[1])), color: "var(--accent)", name: "Brent vs 200-day" }],
        xticks: [2025, 2026].map((y) => [y, String(y)]), yfmt: (v) => lPct(v), zero: true });
      xyChart($("#lb-rsi"), { height: 160, label: "Brent RSI(14)", series: [{ pts: dv.dates.map((d, i) => [lDate(d), dv.rsi[i]]).filter((p) => fin(p[1])), color: "var(--good)", name: "RSI(14)" }],
        hlines: [{ y: 70, label: "70" }, { y: 30, label: "30", color: "var(--good)" }], xticks: [2025, 2026].map((y) => [y, String(y)]), yDomain: [0, 100] });
    }
    const sp = LB.spreads.brent_wti.spread;
    if (sp && sp.dates) xyChart($("#lb-bw"), { height: 180, label: "Brent minus WTI, monthly", series: [{ pts: sp.dates.map((d, i) => [lDate(d), sp.usd[i]]).filter((p) => fin(p[1])), color: "var(--warn)", name: "Spread, $/bbl" }],
      xticks: [2000, 2010, 2020].map((y) => [y, String(y)]), yfmt: (v) => "$" + fx(v, 0), zero: true });
    const gs = LB.calendar.gas_seasonal || [];
    if (gs.length) barsV($("#lb-gas"), gs.map((m) => ({ label: ["J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"][m.month - 1], v: m.mean, color: m.p < 0.05 ? "var(--warn)" : "var(--s1)" })), { fmt: (v) => lPct(v, 1), yfmt: (v) => lPct(v, 0), height: 200, label: "Henry Hub gas, average return by calendar month" });
    drawYale();
  }

  function lScatter(box) {
    if (!box || !box.clientWidth) return;
    const c = LB.valuation.cape, sc = c.scatter, fit = c.fit;
    if (!sc || !sc.x.length) { noData(box); return; }
    const W = boxWidth(box), H = 270, padL = 50, padR = 16, top = 14, bottom = 30;
    const x0 = 4, x1 = Math.max(45, c.now + 2), ys = sc.y.concat([c.implied_10y_real]), ylo = Math.min(...ys, -0.06), yhi = Math.max(...ys, 0.18);
    const ticks = niceTicks(ylo, yhi, 5), y0 = ticks[0], y1 = ticks[ticks.length - 1];
    const sx = (x) => padL + ((x - x0) / (x1 - x0)) * (W - padL - padR), sy = (y) => top + (1 - (y - y0) / (y1 - y0)) * (H - top - bottom);
    box.replaceChildren();
    const s = svg("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: "img", "aria-label": `CAPE against the next ten years' real return; today ${fx(c.now, 1)} implies ${lPct(c.implied_10y_real, 1)} a year` }, box);
    ticks.forEach((t) => { svg("line", { x1: padL, x2: W - padR, y1: sy(t), y2: sy(t), class: t === 0 ? "baseline" : "gridline" }, s); text(s, padL - 8, sy(t) + 4, lPct(t), "ax", "end"); });
    [10, 20, 30, 40].forEach((x) => text(s, sx(x), H - 9, String(x), "ax", "middle"));
    sc.x.forEach((x, i) => svg("circle", { cx: sx(x), cy: sy(sc.y[i]), r: 2.2, fill: "var(--s1)", opacity: 0.55 }, s));
    let d = "";
    for (let k = 0; k <= 50; k++) { const x = x0 + 1 + (x1 - x0 - 1) * k / 50; d += (k ? "L" : "M") + sx(x).toFixed(1) + "," + sy(fit[0] * Math.log(x) + fit[1]).toFixed(1); }
    svg("path", { d, fill: "none", stroke: "var(--bad)", "stroke-width": 2 }, s);
    svg("line", { x1: sx(c.now), x2: sx(c.now), y1: sy(c.range80[0]), y2: sy(c.range80[1]), stroke: "var(--warn)", "stroke-width": 3, opacity: 0.6 }, s);
    svg("circle", { cx: sx(c.now), cy: sy(c.implied_10y_real), r: 6, fill: "var(--warn)", class: "mark-ring" }, s);
    text(s, sx(c.now) - 10, sy(c.implied_10y_real) - 10, `today ${fx(c.now, 1)}`, "lbl-strong", "end");
  }

  /* ---------- the card room ---------- */
  function wireCardRoom() {
    const num = (id) => parseFloat(($("#" + id) || {}).value);
    const cards = (id) => String(($("#" + id) || {}).value || "").trim().split(/[\s,]+/).filter(Boolean).map(gCard);
    const eqGo = () => {
      const hero = cards("cr-hand"), board = cards("cr-board"), n = Math.round(clamp(num("cr-opp") || 1, 1, 8)), out = $("#cr-eq-out");
      if (hero.length !== 2 || hero.concat(board).some((c) => c == null) || board.length > 5 || board.length === 1 || board.length === 2 || new Set(hero.concat(board)).size !== hero.length + board.length) {
        out.textContent = "Enter two cards for the hand (like As Kd) and 0, 3, 4 or 5 board cards, all different. Ranks 2-9, T, J, Q, K, A; suits c, d, h, s."; return;
      }
      const e = gEquity(hero, board, n, 4000, 7);
      const pot = num("cr-pot"), call = num("cr-call"), need = fin(pot) && fin(call) && call > 0 ? gPotOdds(pot, call) : null;
      let txt = `Equity ${lPct(e.equity, 1)} against ${n} random hand${n > 1 ? "s" : ""} (${e.trials.toLocaleString()} deals; win ${lPct(e.win, 1)}, split ${lPct(e.tie, 1)}).`;
      if (board.length >= 3) txt += ` Made hand now: ${gCategory(gEval7(hero.concat(board)))}.`;
      if (need != null) { const ev = gCallEv(e.equity, pot, call); txt += ` The call needs ${lPct(need, 1)}; calling is worth ${ev >= 0 ? "+" : MINUS}${fx(Math.abs(ev), 2)} per call in chips, so ${ev >= 0 ? "call" : "fold"} (ignoring later betting).`; }
      out.textContent = txt;
    };
    $("#cr-eq-go").addEventListener("click", eqGo);
    const kGo = () => {
      const p = num("cr-p"), b = num("cr-b"), out = $("#cr-k-out");
      if (!(p > 0 && p < 1 && b > 0)) { out.textContent = "Win probability between 0 and 1, and odds above 0."; return; }
      const f = gKelly(p, b), mu = p * b - (1 - p), sd = Math.sqrt(p * (b - mu) ** 2 + (1 - p) * (-1 - mu) ** 2);
      const units = Math.max(1, num("cr-bank") || 50);
      out.textContent = `Kelly stakes ${lPct(f, 1)} of the bankroll (half Kelly ${lPct(f / 2, 1)}: about three quarters of the growth for half the swings). Edge ${fx(mu, 3)} and spread ${fx(sd, 2)} per unit bet: with ${units} betting units the chance of ever going broke is about ${gRuin(mu, sd, units) < 1e-4 ? "under 0.01%" : lPct(gRuin(mu, sd, units), 2)}; 1% needs ${mu > 0 ? fx(gBankrollFor(mu, sd, 0.01), 0) : "infinitely many"} units.`;
    };
    $("#cr-k-go").addEventListener("click", kGo);
    const bGo = () => {
      const d1 = num("cr-d1"), d2 = num("cr-d2"), cost = num("cr-cost"), lo = num("cr-lo"), hi = num("cr-hi"), out = $("#cr-b-out");
      const parts = [];
      if (d1 > 0 && d1 < 1 && d2 > 0 && d2 < 1) { const r = gRubinstein(d1, d2); parts.push(`Alternating offers (Rubinstein): the side that opens gets ${lPct(r.first, 1)} of the pie; patience is power.`); }
      const bo = gBestOffer(cost, lo, hi);
      if (bo) parts.push(`Haggling: with your walk-away at ${fx(cost, 2)} and theirs somewhere between ${fx(lo, 2)} and ${fx(hi, 2)}, ask ${fx(bo.price, 2)}. They accept ${lPct(bo.accept)} of the time and you expect ${fx(bo.expected, 2)} of surplus; asking more raises the price and lowers the odds.`);
      out.textContent = parts.join(" ") || "Fill in the patience (0 to 1) and the walk-away prices.";
    };
    $("#cr-b-go").addEventListener("click", bGo);
    const cGo = () => {
      const S = num("cr-spot"), F = num("cr-fut"), r = num("cr-r") / 100, u = num("cr-u") / 100, T = num("cr-t") / 12, out = $("#cr-c-out");
      if (!(S > 0 && F > 0 && T > 0)) { out.textContent = "Spot, future and months to expiry must be positive."; return; }
      const y = gConv(S, F, r, u, T), roll = gRoll(S, F, num("cr-t"));
      out.textContent = `The curve implies a convenience yield of ${lPct(y, 1)} a year: that is what holders pay to have barrels now. Rolling a long from spot-month into this contract earns about ${lPct(roll, 1)} a year if the curve holds still (${roll > 0 ? "backwardation pays the long" : "contango costs the long"}). At zero convenience yield the fair future would be ${fx(gCarry(S, r, u, 0, T), 2)}.`;
    };
    $("#cr-c-go").addEventListener("click", cGo);
    ["cr-y-g", "cr-y-b", "cr-y-life"].forEach((id) => $("#" + id).addEventListener("input", drawYale));
    eqGo(); kGo(); bGo(); cGo();
  }
  function drawYale() {
    const g = parseFloat(($("#cr-y-g") || {}).value), bow = parseFloat(($("#cr-y-b") || {}).value), life = parseFloat(($("#cr-y-life") || {}).value);
    if (!$("#cr-yale")) return;
    const Y = gYale(100, 12, [0.25, 0.333, 0.5, 0.5, 0.5, 0.5], fin(g) ? g / 100 : 0.1, fin(bow) ? bow : 2.5, 0, fin(life) ? life : 12);
    xyChart($("#cr-yale"), { height: 220, label: "Cumulative net cash flow of a 100 commitment", series: [{ pts: Y.rows.map((r) => [r.year, r.net_cum]), color: "var(--accent)", name: "Net cash to the investor" },
      { pts: Y.rows.map((r) => [r.year, r.nav]), color: "var(--good)", name: "NAV" }], xticks: Y.rows.filter((r) => r.year % 2 === 0).map((r) => [r.year, `yr ${r.year}`]), yfmt: (v) => fx(v, 0), zero: true });
    $("#cr-y-out").textContent = `The J-curve bottoms at ${fx(Y.trough, 1)} in year ${Y.trough_year} and ${Y.breakeven_year ? `breaks even in year ${Y.breakeven_year}` : "has not broken even by year 12"}; IRR ${Y.irr == null ? "n/a" : lPct(Y.irr, 1)}, TVPI ${fx(Y.tvpi, 2)}x (Takahashi and Alexander 2002).`;
  }

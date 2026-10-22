  /* =====================================================================================
     reality.js (v0.15): where the models meet the real world. Every model the engine runs, the assumption it rests
     on, a live test of that assumption, the breakpoint at which its conclusion flips, and the PM's triage of a
     quant's backtest. rtTriage mirrors buildout/assumptions.py's triage exactly (tests/test_v15.py holds them equal).
     ===================================================================================== */
  const RT_EULER = 0.5772156649015329, RT_DECAY_OOS = 0.26, RT_DECAY_PUB = 0.58;
  const rtEmaxZ = (n) => (n <= 1 ? 0 : (1 - RT_EULER) * ninv(1 - 1 / n) + RT_EULER * ninv(1 - 1 / (n * Math.E)));
  function rtTriage(sharpe, years, trials = 1, periods = 12, skew = 0, kurt = 3, published = false, costBps = 0, turns = 0, vol = 0.15, trialSd = null) {
    const n = Math.max(2, Math.round(years * periods));
    if (trialSd == null) trialSd = 1 / Math.sqrt(Math.max(years, 1e-9));
    const drag = vol > 0 ? costBps / 1e4 * turns / vol : 0;
    const net = sharpe - drag, decay = published ? RT_DECAY_PUB : RT_DECAY_OOS, live = net * (1 - decay);
    const srp = net / Math.sqrt(periods), den = Math.sqrt(Math.max(1 - skew * srp + (kurt - 1) / 4 * srp * srp, 1e-12));
    const psr = ncdf(srp * Math.sqrt(n - 1) / den), emax = trialSd / Math.sqrt(periods) * rtEmaxZ(trials);
    const dsr = ncdf((srp - emax) * Math.sqrt(n - 1) / den);
    const minbtl = trials > 1 && sharpe > 0 ? Math.pow(rtEmaxZ(trials) / sharpe, 2) : 0;
    const verdict = dsr >= 0.95 && years >= minbtl && live > 0.3 ? "credible" : dsr >= 0.5 && live > 0 ? "doubtful" : "likely noise";
    return { sharpe, cost_drag: drag, net, decay, live, psr, dsr, emax_annual: emax * Math.sqrt(periods), minbtl_years: minbtl, enough_data: years >= minbtl, n, trial_sd: trialSd, verdict };
  }
  function rtOk(s) { return !!(s && s.checks && s.checks.tails_month && Array.isArray(s.map) && s.map.length); }
  const rtPct = (v, d = 0) => (fin(v) ? `${v < 0 ? MINUS : ""}${Math.abs(v * 100).toFixed(d)}%` : "n/a");
  const RT_STATUS = { holds: "Holds", strained: "Strained", broken: "Broken", untested: "Untested" };
  function rtBadge(st) { return h("span", "rt-badge rt-" + st, RT_STATUS[st] || st); }
  function renderRealityDesk() {
    const tiles = $("#rt-tiles");
    if (!tiles || !rtOk(REAL_SNAP)) { if (tiles && !tiles.children.length) tiles.append(h("p", "hint", "The reality-check snapshot is missing or malformed.")); return; }
    const C = REAL_SNAP.checks;
    if (!tiles.children.length) {
      const broken = REAL_SNAP.map.filter((m) => m.verdict === "broken").length;
      [[`${broken} of ${REAL_SNAP.map.length}`, "Models with a broken assumption", "today, on the engine's own data"],
        [`${C.tails_month.observed_beyond} vs ${fx(C.tails_month.gaussian_expects, 0)}`, "3σ months: seen vs bell curve", `S&P 500 since 1871; normal VaR ${rtPct(C.tails_month.var_understatement)} too small`],
        [fx(C.kappa.series["S&P 500, monthly"].n_equivalent_30, 0), "Months to learn what 30 normal ones teach", `Taleb's kappa ${fx(C.kappa.series["S&P 500, monthly"].kappa, 2)}`],
        [`${fx(C.hedge.rho_star, 2)} vs ${C.hedge.now >= 0 ? "+" : ""}${fx(C.hedge.now, 2)}`, "TLT hedge breakpoint vs now", "stock-bond correlation above the line adds risk"],
        [`${fx(C.trend.breakeven_cost * 1e4, 0)}bp`, "Trend rule's break-even cost", "a switch; the gain is gone by a 4-month delay"],
        [`${rtPct(C.worlds.all.mix_sharpe)} → ${rtPct(C.worlds.inflation.mix_sharpe)}`, "60/40 beats stocks on Sharpe", "all resampled worlds, then inflationary ones"]].forEach(([v, k, s]) => { const d = h("div", "at-kpi"); d.append(h("b", null, v), h("span", null, k), h("small", null, s)); tiles.append(d); });
      $("#rt-sum").textContent = (REAL_SNAP.findings || []).slice(0, 3).join(" ");
      rtMap();
      rtTriageWire();
      rtTables();
      rtHaircuts();
      rtHedgeWire();
    }
    rtCharts();
  }
  function rtMap() {
    const box = $("#rt-map");
    box.replaceChildren();
    REAL_SNAP.map.forEach((m) => {
      const c = h("article", "rt-card rt-c-" + m.verdict);
      const top = h("div", "rt-top"); top.append(h("h3", null, m.model), rtBadge(m.verdict));
      const p = h("p", "rt-where", m.where);
      const ul = h("ul", "rt-asm");
      m.assumes.forEach((a, i) => { const li = h("li"); li.append(rtBadge(m.statuses[i] || "untested"), " ", a); ul.append(li); });
      c.append(top, p, ul, h("p", "rt-cons", m.consequence));
      box.append(c);
    });
  }
  function rtTriageWire() {
    const ids = ["rt-sr", "rt-yrs", "rt-n", "rt-cost", "rt-turn", "rt-vol"];
    const run = () => {
      const [sr, yrs, n, cost, turn, vol] = ids.map((id) => parseFloat($("#" + id).value));
      const pub = $("#rt-pub").checked, out = $("#rt-out");
      if (![sr, yrs, n, cost, turn, vol].every(fin) || yrs <= 0 || yrs > 200 || n < 1 || vol <= 0 || cost < 0 || turn < 0 || sr <= -5 || sr >= 10) {
        out.replaceChildren(h("p", "hint", "Enter a Sharpe between −5 and 10, years between 0 and 200, at least one variant, and non-negative costs and turnover.")); return;
      }
      const t = rtTriage(sr, yrs, Math.round(n), 12, 0, 3, pub, cost, turn, vol / 100);
      out.replaceChildren();
      const v = h("p", "rt-verdict rt-v-" + t.verdict.replace(" ", "-"), { credible: "Credible", doubtful: "Doubtful", "likely noise": "Likely noise" }[t.verdict]);
      const steps = h("ol", "rt-steps");
      [[`Claimed Sharpe`, fx(t.sharpe, 2)], [`After ${fx(cost, 1)}bp × ${fx(turn, 0)} trades a year`, fx(t.net, 2)], [`After the ${rtPct(t.decay)} ${pub ? "post-publication" : "out-of-sample"} decay McLean and Pontiff measured`, fx(t.live, 2)]]
        .forEach(([k, x]) => { const li = h("li"); li.append(h("span", null, k), h("b", null, x)); steps.append(li); });
      out.append(v, steps,
        h("p", null, `Chance the true Sharpe is above zero: ${rtPct(t.psr)}. Above the best of ${Math.round(n)} skill-less tries (${fx(t.emax_annual, 2)} by luck alone over ${fx(yrs, 0)} years): ${rtPct(t.dsr)}. That second number is the deflated Sharpe ratio.`),
        h("p", null, t.minbtl_years > 0 ? `${Math.round(n)} tries need at least ${fx(t.minbtl_years, 1)} years of data before a Sharpe of ${fx(sr, 2)} means anything (minimum backtest length); ${t.enough_data ? "this backtest has enough." : "this backtest is too short."}` : "With one try there is no selection to correct for; costs and decay still apply."));
    };
    ids.concat(["rt-pub"]).forEach((id) => $("#" + id).addEventListener("input", run));
    run();
  }
  function rtHedgeWire() {
    const H = REAL_SNAP.checks.hedge, sl = $("#rt-rho");
    sl.value = H.now;
    const run = () => {
      const rho = parseFloat(sl.value), w = H.weight, se = H.sigma_book, sb = H.sigma_bond;
      const v0 = se, v1 = Math.sqrt(se * se + w * w * sb * sb + 2 * w * rho * se * sb);
      $("#rt-rho-v").textContent = (rho >= 0 ? "+" : "") + rho.toFixed(2);
      $("#rt-rho-out").textContent = `At a stock-bond correlation of ${(rho >= 0 ? "+" : "") + rho.toFixed(2)}, adding a ${rtPct(w)} TLT sleeve on top of the book moves its volatility from ${rtPct(v0, 1)} to ${rtPct(v1, 1)}: it ${v1 < v0 - 1e-9 ? "lowers" : v1 > v0 + 1e-9 ? "raises" : "leaves"} risk. The line is ${fx(H.rho_star, 2)}; the latest 36-month reading is ${(H.now >= 0 ? "+" : "") + fx(H.now, 2)}.`;
    };
    sl.addEventListener("input", run);
    run();
  }
  function rtTables() {
    const C = REAL_SNAP.checks;
    const t = [C.tails_month, C.tails_day].filter(Boolean);
    fillTable($("#rt-tails"), ["Series", "Kurtosis (3 normal)", "Tail index", "Beyond", "Seen", "Normal expects", "Normal VaR too small by"],
      t.map((x) => [x.series, fx(x.kurtosis, 1), fx(x.hill_alpha, 2), `${fx(x.threshold_sd, 0)}σ`, String(x.observed_beyond), x.gaussian_expects < 0.1 ? x.gaussian_expects.toExponential(1) : fx(x.gaussian_expects, 1), rtPct(x.var_understatement)]), 1);
    const K = C.kappa.series;
    fillTable($("#rt-kappa"), ["Series", "κ (0 normal, 1 fattest)", "Observations to match 30 normal ones"], Object.entries(K).map(([k, v]) => [k, fx(v.kappa, 3), fx(v.n_equivalent_30, 0)]), 1);
    const F = C.fragility.structures, FN = { unhedged: "Book, unhedged", put_spread: "With a put spread", collar: "With a collar", vix_calls: "With VIX calls", levered_1_5x: "Levered 1.5x", short_put: "Short puts (selling insurance)" };
    fillTable($("#rt-frag"), ["Structure", "Worst convexity H", "At a fall of", "Verdict"], Object.entries(F).map(([k, v]) => [FN[k] || k, fx(v.H_min, 4), Math.abs(v.H_min) < 1e-4 ? "nowhere" : rtPct(+v.at), v.verdict]), 1);
    const W = C.worlds, rw = (k, lab) => [lab, rtPct(W.all[k]), rtPct(W.inflation[k])];
    fillTable($("#rt-worlds"), ["In resampled 50-year histories", `All months (${W.n})`, `Inflationary months only`],
      [rw("trend_sharpe", "Trend rule beats holding on Sharpe"), rw("trend_dd", "Trend rule has the smaller worst drawdown"), rw("mix_sharpe", "60/40 beats all stocks on Sharpe"), rw("mix_dd", "60/40 has the smaller worst drawdown"),
        ["Median stock-bond correlation", fx(W.all.corr_median, 2), fx(W.inflation.corr_median, 2)]], 1);
    const CC = C.crisis ? C.crisis.series : {}, CN = { oil: "Oil", cpi: "Inflation", y10: "10-year yield", vix: "VIX", gold: "Gold" };
    fillTable($("#rt-crisis"), ["Correlation with stocks", "All months", "Worst months for stocks", "Shift"], Object.entries(CC).map(([k, v]) => [CN[k] || k, fx(v.all, 2), fx(v.worst, 2), (v.worst - v.all >= 0 ? "+" : MINUS) + fx(Math.abs(v.worst - v.all), 2)]), 1);
    const D = C.dependence, S = C.stability, R = C.correlation, KL = C.kelly;
    fillTable($("#rt-tests"), ["Assumption", "Test", "Result", "Status"], [
      ["Months are independent", "Ljung-Box, 12 lags, on returns and squared returns", `first autocorrelation ${fx(D.returns.rho1, 2)} (Working's averaging alone gives ${fx(D.working_rho1, 2)}); squared returns p ${D.squared.p < 0.001 ? "< 0.001" : fx(D.squared.p, 3)}: volatility clusters`, RT_STATUS[D.status]],
      ["The return process is stable", "sup-F break test; 30-year rolling Sharpe and 10-year volatility", `strongest break ${S.break_date} (p ${fx(S.sup_f.p, 2)}); Sharpe ${fx(S.sharpe30_min, 2)} to ${fx(S.sharpe30_max, 2)}; volatility ${rtPct(S.vol10_min)} to ${rtPct(S.vol10_max)}`, RT_STATUS[S.status]],
      ["Bonds hedge stocks", "stock-bond correlation by inflation regime", `${fx(R.low_inflation, 2)} when inflation is low, ${fx(R.high_inflation, 2)} when high; ${rtPct(R.share_windows_positive)} of 36-month windows positive`, RT_STATUS[R.status]],
      ["The edge is known well enough for Kelly", "Kelly fraction across every 30-year window", `${fx(KL.min, 1)}x to ${fx(KL.max, 1)}x capital; latest ${fx(KL.last_window, 1)}x`, RT_STATUS[KL.status]],
      ["The models have seen days like today", "distance to the 24 nearest historical months", C.ml ? `today is further out than ${rtPct(C.ml.novelty_pct)} of months` : "n/a", RT_STATUS[C.ml ? (C.ml.novelty_pct > 0.9 ? "broken" : C.ml.novelty_pct > 0.75 ? "strained" : "holds") : "untested"]],
    ], 4);
  }
  function rtHaircuts() {
    const box = $("#rt-hc");
    const items = EDGE_SNAP.model_risk;
    const groups = [["What backtests lose live", /mclean|hlz|harvey|bailey|wiecki|novy|hxz|jkp|arnott|ldp/], ["When models met the world", /khandani|ltcm|knight|xiv|viniar|dowd|sigma|longin|ang-chen/], ["How a firm challenges a model", /sr117|derman|box/]];
    const used = new Set();
    groups.concat([["More", /./]]).forEach(([name, rx]) => {
      const list = items.filter((x) => !used.has(x.id) && rx.test(x.id));
      if (!list.length) return;
      list.forEach((x) => used.add(x.id));
      const d = h("details", "ed-lens"); d.open = name !== "More";
      d.append(h("summary", null, `${name} · ${list.length}`));
      const ul = h("ul", "ed-list");
      list.forEach((x) => { const li = h("li"); const a = h("a", null, x.publisher || "source"); a.href = x.source_url; a.target = "_blank"; a.rel = "noopener"; li.append(h("b", null, x.title + ". "), x.text + " ", a); ul.append(li); });
      d.append(ul); box.append(d);
    });
  }
  function rtCharts() {
    const C = REAL_SNAP.checks, T = C.trend.sharpe_gain_by_delay;
    barsV($("#rt-delay"), Object.entries(T).map(([k, v]) => ({ label: `${k} mo`, v, color: v > 0 ? "var(--good)" : "var(--bad)", lbl: fx(v, 2) })), { fmt: (v) => fx(v, 2), height: 200, label: "Trend rule Sharpe gain over holding, by how late it acts" });
    const F = C.fragility, g = F.grid, cols = { unhedged: "var(--s1)", collar: "var(--good)", levered_1_5x: "var(--warn)", short_put: "var(--bad)" };
    xyChart($("#rt-frag-c"), { height: 240, label: "Book payoff across market moves, by structure", series: Object.entries(cols).filter(([k]) => F.structures[k]).map(([k, c]) => ({ pts: g.map((x, i) => [x * 100, F.structures[k].curve[i]]), color: c, name: k.replace("_", " ") })),
      xticks: [-40, -30, -20, -10, 0, 10, 20].map((x) => [x, `${x}%`]), yfmt: (v) => rtPct(v), zero: true });
    legendLines($("#rt-frag-l"), [["var(--s1)", "Unhedged"], ["var(--good)", "Collar"], ["var(--warn)", "Levered 1.5x"], ["var(--bad)", "Short puts"]]);
  }

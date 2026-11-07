  /* deeprl.js (v0.41): the Deep RL desk. Reads SNAP38.deeprl (buildout/deeprl.py) and the track's call_rl policy. */
  function renderDeepRl() {
    const T = typeof T38 === "function" ? T38() : null, R = T && T.deeprl;
    if (!R) { $("#dr-sum").textContent = "The deep RL study is not in this build."; return; }
    const V = R.variants, P = V.policy, Q = V.plan, H = R.hold, TR = R.trend, TB = R.tabular, best = V[R.best], W = R.world_model, G = R.agent;
    const drP = (v, d = 0) => (fin(v) ? `${(v * 100).toFixed(d)}%` : "n/a"), drS = (v, d = 0) => (fin(v) ? `${v < 0 ? MINUS : "+"}${Math.abs(v * 100).toFixed(d)}%` : "n/a");
    rsKpi($("#dr-tiles"), [
      [fx(best.perf.sharpe, 2), `Sharpe, ${R.best === "plan" ? "with planning" : "the policy"}`, `holding ${fx(H.sharpe, 2)}, trend rule ${fx(TR.sharpe, 2)}, tabular agent ${fx(TB.sharpe, 2)}`],
      [drP(best.perf.maxdd), "Worst drawdown", `holding ${drP(H.maxdd)}; 2008 ${drS(best.perf.y2008)} against ${drS(H.y2008)}`],
      [drP(R.deflated_excess.dsr), "Chance the edge over holding is real", `deflated for the ${R.n_tried} variants tried; 90% range ${sgn2(best.sharpe_vs_hold.lo)} to ${sgn2(best.sharpe_vs_hold.hi)} Sharpe`],
      [`${(G.sim_months_total / 1e6).toFixed(0)}M`, "Simulated months trained on", `${G.refits} yearly refits, ${G.params.toLocaleString()} weights, ${Math.round(G.seconds / 60)} minutes on two CPU cores`]]);
    $("#dr-sum").textContent = R.findings.join(" ");
    // the recipe
    const gc = R.gradcheck, ov = R.overfit, bl = R.blocks || [];
    $("#dr-rec-p").textContent = "Karpathy's 2019 recipe says most neural-network failures are silent, so each step is a check that must pass before the next. The table is that checklist, with the numbers this build produced. Steps that could be gamed by looking at the test months were not: the held-out tenth is always the newest tenth of the training window, never a month the agent is later judged on.";
    fillTable($("#dr-rec"), ["Step", "What it demands", "Done here", "Measured"], [
      ["1. Become one with the data", "Know the record before modelling it", `${R.months} months judged from ${R.start}; ${R.features.length} state features knowable at each month's start (trend a month late for Shiller's averaging, trailing volatility, last month and last year's return, CAPE, drawdown, the 10-year yield), plus the agent's last action`, `${R.data ? `${R.data.months} months from ${R.data.from}: mean ${drS(R.data.mean, 2)} a month, sd ${drP(R.data.sd, 1)}, skew ${fx(R.data.skew, 2)}, worst ${drS(R.data.worst, 0)}, best ${drS(R.data.best, 0)}` : ""}`],
      ["2. Set baselines first", "Simple models that must be beaten", "Holding, the 10-month trend rule, the tabular agent (rl.py); for the world model, one Gaussian and a volatility-scaled Gaussian", `Sharpe: hold ${fx(H.sharpe, 2)}, trend ${fx(TR.sharpe, 2)}, tabular ${fx(TB.sharpe, 2)}`],
      ["3. Initialize well", "Start the output at the data's statistics", "The mixture's means and spreads start at the training months' mean and spread in volatility units; without this the first fit lost to a plain Gaussian by 8 nats", `held-out NLL now ${fx(W.nll_heldout.mdn, 3)} against ${fx(W.nll_heldout.vol_gaussian, 3)} for the baseline`],
      ["4. Verify the gradients", "Analytic against finite differences", "Both backward passes (PPO loss, mixture likelihood) checked at 40 random weights", `max relative error ${gc.agent_max_rel_err.toExponential(1)} (agent), ${gc.world_max_rel_err.toExponential(1)} (world model)`],
      ["5. Overfit one batch", "A tiny fixed batch the model must learn perfectly", "64 states: the value head fits random targets, the policy learns to choose given actions", `value error ${fx(ov.value_mse_before, 2)} to ${ov.value_mse_after.toExponential(1)}; probability of the chosen action ${drP(ov.p_chosen_before)} to ${drP(ov.p_chosen_after)} in ${ov.steps} steps`],
      ["6. Regularize", "Early stopping, weight decay, entropy", `The world model stops at the step with the best held-out likelihood (median ${bl.length ? fx(bl.map((b) => b.steps).sort((a, b) => a - b)[Math.floor(bl.length / 2)], 0) : "n/a"} of 1,500 steps); weight decay on both nets; an entropy bonus keeps the policy from collapsing early`, `policy entropy at the last refit ${fx(G.entropy_last, 2)} nats (1.39 is uniform over 4 actions)`],
      ["7. Scale", "Train on more than the record holds", `${PPO_ENVS(R)} episodes of ${R.horizon} months per iteration, ${R.iters.first} iterations for the first fit and ${R.iters.warm} per yearly refit, warm-started`, `${(G.sim_months_total / 1e6).toFixed(1)} million simulated months against ${R.data ? R.data.months.toLocaleString() : "about 1,700"} real ones`],
      ["8. Judge out of sample", "Never tune on the test", "Retrained each January on earlier months only; the walk-forward is the only test; the deflated Sharpe counts every variant tried", `${R.n_tried} variants (policy, planner); deflated chance ${drP(R.deflated_excess.dsr)}`]], 4);
    // the world model
    const nl = W.nll_heldout, tc = W.tail_check;
    $("#dr-wm-p").textContent = `A mixture density network (Bishop 1994) with three Gaussian components, two hidden layers of 16, predicting next month's real return in units of trailing volatility. It beat both baselines on held-out months in ${W.refits_mdn_best} of ${W.refits} refits. The gain is small (${fx(nl.vol_gaussian - nl.mdn, 3)} nats a month over the volatility-scaled Gaussian) and that is the honest finding: beyond volatility clustering and fat tails there is little in monthly returns to learn. The slow variables the agent also sees (the price trend, CAPE, the 10-year yield) move by simple fitted rules, marked Assumed in the code.`;
    fillTable($("#dr-wm"), ["Model", "Held-out NLL per month", "Against the mixture"], [
      ["Mixture density network (this)", fx(nl.mdn, 3), ""], ["Volatility-scaled Gaussian", fx(nl.vol_gaussian, 3), sgn2(nl.vol_gaussian - nl.mdn)], ["One Gaussian for every month", fx(nl.gaussian, 3), sgn2(nl.gaussian - nl.mdn)]], 1);
    fillTable($("#dr-tail"), ["", "Imagined", "Real"], [
      ["Months below -10%", drP(tc.sim_below_10, 1), drP(tc.real_below_10, 1)], ["Standard deviation", drP(tc.sim_sd, 1), drP(tc.real_sd, 1)], ["Skew", fx(tc.sim_skew, 2), fx(tc.real_skew, 2)]], 1);
    // the record
    $("#dr-rec2-p").textContent = `From ${R.start}: the policy alone earned a Sharpe of ${fx(P.sharpe_vs_hold.est + H.sharpe, 2)}; with planning (each action tried in ${R.plan.rollouts} imagined futures of ${R.plan.horizon} months, the value network scoring the end) ${Q ? fx(Q.perf.sharpe, 2) : "n/a"}. The tabular agent, on the same reward with a six-cell state, earned ${fx(TB.sharpe, 2)}. ${best.sharpe_vs_hold.lo > 0 ? "The best variant's edge over holding is above zero across the 90% bootstrap range" : "The best variant's edge over holding is not distinguishable from zero at 90%"}; deflated for the variants tried, the chance it is real is ${drP(R.deflated_excess.dsr)}.`;
    const cv = R.curve, lD = (s) => { const t = String(s); return +t.slice(0, 4) + (+t.slice(5, 7) - 1) / 12; };
    const ser = [["hold", "var(--s1)", "Hold"], ["trend", "var(--good)", "Trend rule"], ["tabular", "var(--muted)", "Tabular agent"], ["policy", "var(--s4)", "Deep agent, policy"], ["plan", "var(--s2)", "Deep agent, planning"]].filter(([k]) => cv[k]);
    xyChart($("#dr-curve"), { height: 260, label: "Log real wealth since 1940", series: ser.map(([k, c, n]) => ({ pts: cv.dates.map((d, i) => [lD(d), cv[k][i]]), color: c, name: `${n} (ends ${fx(cv[k][cv[k].length - 1], 2)})` })),
      xticks: [1950, 1970, 1990, 2010].map((y) => [y, String(y)]), yfmt: (v) => fx(v, 1) });
    const row = (name, p, extra) => [name, fx(p.sharpe, 2), drS(p.cagr, 1), drP(p.maxdd), drS(p.y1974), drS(p.y2008), drS(p.y2022), ...extra];
    fillTable($("#dr-pol"), ["Policy", "Sharpe", "Real growth a year", "Worst drawdown", "1974", "2008", "2022", "Average exposure", "Months out", "Months levered", "Switches a year"], [
      row("Deep agent, policy", P.perf, [fx(P.avg_exposure, 2) + "x", drP(P.time_out), drP(P.time_levered), fx(P.switches_per_year, 1)]),
      ...(Q ? [row("Deep agent, planning", Q.perf, [fx(Q.avg_exposure, 2) + "x", drP(Q.time_out), drP(Q.time_levered), fx(Q.switches_per_year, 1)])] : []),
      row("Tabular agent (rl.py, pooled state)", TB, ["", "", "", ""]), row("10-month trend rule", TR, ["", "", "", ""]), row("Hold", H, ["1.00x", "0%", "0%", ""])], 1);
    $("#dr-pol-n").textContent = `Real returns after a 10 bp cost per unit traded and 2% a year to borrow above 1.0x, the tabular agent's terms. The reward penalizes squared losses (the risk_averse setting), so the agent is not trying to maximize growth.`;
    const ex = R.exposure;
    xyChart($("#dr-expo"), { height: 160, label: "Exposure chosen, quarterly samples", series: [{ pts: ex.dates.map((d, i) => [lD(d), ex.policy[i]]), color: "var(--s4)", name: "Policy" }].concat(ex.plan ? [{ pts: ex.dates.map((d, i) => [lD(d), ex.plan[i]]), color: "var(--s2)", name: "Planning" }] : []),
      xticks: [1950, 1970, 1990, 2010].map((y) => [y, String(y)]), yfmt: (v) => fx(v, 1) + "x" });
    // what it learned
    const pm = R.policy_map || [];
    $("#dr-map-p").textContent = `The final policy (trained through ${R.now.model_trained_through}) read on every state in the record, from a 1.0x position: its mean exposure by whether the trend is on, the volatility tercile and the drawdown bucket. A policy that only followed the trend would show one number per row pair; this one changes with volatility and drawdown as well.`;
    const vl = ["low", "mid", "high"], dl = ["under 10%", "10 to 25%", "over 25%"];
    fillTable($("#dr-map"), ["Trend", "Volatility", "Drawdown", "Months", "Mean exposure"], pm.map((r) => [r.trend_on ? "on" : "off", vl[r.vol], dl[r.dd], String(r.months), fx(r.exposure, 2) + "x"]), 3);
    const N = R.now;
    fillTable($("#dr-now"), ["", "Value"], [["Data through", N.date], ["Trend (log price over 10-month average)", sgn2(N.state.trend)], ["12-month volatility", drP(N.state.vol, 1)], ["CAPE", fx(Math.exp(N.state.lcape), 1)], ["Drawdown", drP(N.state.dd, 1)], ["10-year yield", drP(N.state.y10, 2)],
      ["Policy: probabilities over 0, 0.5, 1.0, 1.5x", N.probs.map((p) => drP(p)).join(", ")], ["Policy's action", fx(N.action, 1) + "x"], ["Planner's scores (discounted reward, 12 months)", N.plan_scores.map((v) => fx(v, 3)).join(", ")], ["Planner's action", fx(N.plan_action, 1) + "x"]], 1);
    $("#dr-now-n").textContent = "The S&P 500's state, not the book's: this agent sizes the market. Its reading of the book is the next section.";
    // the book
    const PP = T.pit && T.pit.policies, B = T.deeprl_book, rl = PP && PP.call_rl;
    if (rl && B) {
      const c = PP.call, hd = PP.hold, cs = PP.call_short;
      $("#dr-book-p").textContent = `The policy trained through each prior year read the book's own state (its trend, volatility, drawdown and returns, with the market's CAPE and yield) at ${B.months} month-ends and chose an exposure, cut to 1.0x because the record holds no leverage; for ${B.fallbacks} early months the book had less than a year of history and the call stood in. It spent ${drP(B.time_out)} of months out of the book entirely. The result, net of the same costs as every other row: a Sharpe of ${fx(rl.net.sharpe, 2)} against ${fx(c.net.sharpe, 2)} for the call and ${fx(hd.net.sharpe, 2)} for holding, a worst drawdown of ${drP(rl.net.maxdd)} against ${drP(c.net.maxdd)} and ${drP(hd.net.maxdd)}. ${rl.net.sharpe > c.net.sharpe ? "A sizer trained on the whole market's record did better than the rule built for this book, on the book's own years." : `The rule built for this book did better than a sizer trained on the whole market's record. The reason is visible in the exposure path: the book's volatility (${drP(hd.net.vol)} a year) is about two and a half times the market's, so on features standardized to the market the book reads as a permanent crisis; the sizer sat out half the months and was whipsawed (turnover ${fx(rl.net.turnover_yr || 0, 1)}x a year against ${fx(c.net.turnover_yr || 0, 1)}x for the call). A sizer for the book would need its features scaled to the book, or training on books like it. That is the next experiment, logged on the Memos desk, not a result of this one.`}`;
      const r2 = (name, p) => [name, fx(p.net.sharpe, 2), drS(p.net.cagr, 1), drP(p.net.maxdd), drS(p.net.y2022), fx(p.net.turnover_yr || 0, 1) + "x"];
      fillTable($("#dr-book"), ["Policy, 2018 to now", "Sharpe", "CAGR net", "Worst drawdown", "2022", "Turnover a year"], [r2("Deep RL sizer, unhedged", rl), r2("The call (the live rule)", c), r2("Full size with the call's short", cs), r2("Holding at 1.00x", hd)], 1);
      $("#dr-book-n").textContent = `Point-in-time universe, daily returns, costs as on the Track record desk. The sizer's exposure path is on that desk's policy table as "${T.policy_name.call_rl}".`;
    } else {
      $("#dr-book-p").textContent = "The book test is not in this build.";
    }
    const lim = [
      "One asset, four actions, monthly: the agent sizes the S&P 500 (and, by transfer, the book). It does not pick names or hedge.",
      "The world model is fit to the same months the agent is later judged against only through earlier years: each refit sees nothing after its January. But the model's structure (three Gaussians in volatility units, simple rules for CAPE and yields) was chosen by the author with the whole record in view.",
      `Two variants were tried (policy, planner) and both are shown; the deflated Sharpe counts them. Seeds were not searched: one seed, ${R.gamma} discount, the tabular agent's penalty.`,
      "The imagined months are slightly thinner-tailed than the record (the table above); an agent trained in them is a little braver than it should be.",
      "On the book the sizer sees a year of the book's own history at most times and the market's CAPE and yield; it was never trained on the book, which is the point of that test and also why it should not be expected to beat a rule built for the book.",
      "Research, not advice. The record is 86 years and about 1,040 monthly decisions; a Sharpe difference of 0.1 is within what luck produces over such spans, which is what the bootstrap range and the deflated chance measure."];
    const ul = $("#dr-lim"); ul.textContent = ""; lim.forEach((t) => ul.append(h("li", null, t)));
  }
  const PPO_ENVS = (R) => (R.ppo && R.ppo.envs ? R.ppo.envs.toLocaleString() : "4,096");

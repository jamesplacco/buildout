  /* =====================================================================================
     solve.js (v0.7): the Solve desk. Evidence in, a constrained choice out, with the reasoning shown:
     a calculator, the evidence ledger, the posterior, four alternatives, the game against Nature,
     the value of information and the most plausible way to breach the loss limit.
     ===================================================================================== */
  const EV_KINDS = { obs: "Observed", est: "Estimated", asm: "Assumed", hist: "Historical pattern", hyp: "Hypothesis", na: "Unavailable" };
  function evTag(kind, title) {
    const s = h("span", "ev ev-" + kind, EV_KINDS[kind] || kind);
    if (title) s.title = title;
    return s;
  }
  const latestTag = (o) => (o && o.live ? "latest available" : "snapshot");

  /* ---------- what the reasoner observes: every signal from the same inputs the decisions read ---------- */
  function observeSignals() {
    const I = inputs(), ratio = I.ocfTTM > 0 ? I.capexTTM / I.ocfTTM : NaN;
    let curve = null;
    try { const c = rocRows().find((x) => x.row.k === "curve"); if (c && fin(c.r.level)) curve = { v: c.r.level, d: c.r.date, live: !!c.r.live }; } catch (e) { curve = null; }
    const row = (id, v, d, live, on, show) => ({ id, v, d, live, on: fin(v) ? on : null, show });
    return [
      row("infl", I.infl.avg36, I.infl.d, I.infl.live, I.infl.avg36 >= 2.75, `${fx(I.infl.avg36, 2)}%`),
      row("corr", I.corr.v, I.corr.d, I.corr.live, I.corr.v > 0, sgn2(I.corr.v)),
      row("oil", I.oil.v / I.oilAvg5, I.oil.d, I.oil.live, I.oil.v >= 1.3 * I.oilAvg5, `$${fx(I.oil.v, 2)} (${fx(I.oil.v / I.oilAvg5, 2)}x)`),
      row("vix", I.vix.v, I.vix.d, I.vix.live, I.vix.v >= 20, fx(I.vix.v, 2)),
      row("hy", I.hy.v, I.hy.d, I.hy.live, I.hy.v >= 4.5, `${fx(I.hy.v, 2)}%`),
      row("capex", ratio, null, false, ratio > 0.8, `${pct0(ratio)} of cash flow`),
      row("curve", curve ? curve.v : NaN, curve ? curve.d : null, curve ? curve.live : false, curve ? curve.v < 0 : false, curve ? `${sBp(curve.v, 0)}bp` : "n/a"),
    ];
  }

  /* ---------- state: overrides and parameters live in this browser only ---------- */
  const RZS = { over: LS.get("bo-rz-over", {}), loss: 15, prem: 0.5, eq: null, h: null, regime: "inflation", busy: false };   // prem: per three months; 0.50 is the policy's 2% a year
  if (!RZS.over || typeof RZS.over !== "object") RZS.over = {};
  function rzParams() {
    const I = inputs();
    return Object.assign({}, RZ_DEFAULTS, { vix: fin(I.vix.v) ? I.vix.v : RZ_DEFAULTS.vix, rf: RZ_DEFAULTS.rf, max_loss: RZS.loss / 100, max_premium: RZS.prem / 100 });
  }
  function rzCurrent() {
    const S = LIVE.report && LIVE.report.summary;
    const eq = RZS.eq != null ? RZS.eq : S && fin(S.recommended_gross) ? S.recommended_gross : 1.0;
    const hr = RZS.h != null ? RZS.h : S && fin(S.hedge_ratio_now) ? S.hedge_ratio_now : 0;
    return [Math.min(1.5, Math.max(0, eq)), Math.min(1, Math.max(0, hr)), 0, 0];
  }
  function rzObserved() {
    const out = {};
    observeSignals().forEach((s) => { out[s.id] = s.id in RZS.over ? RZS.over[s.id] : s.on; });
    return out;
  }
  const portTxt = (p) => {
    const parts = [`${xx(p[0])} equity`];
    if (p[1] > 0) parts.push(`TLT at ${fx(p[1], 1)}x of it`);
    if (p[2] > 0) parts.push(`${fx(p[2] * 100, 2)}% of NAV in 3-month 95/85 put spreads`);
    if (p[3] > 0) parts.push(`${fx(p[3] * 100, 0)}% gold`);
    return parts.join(", ");
  };
  const shortPort = (p) => [`${xx(p[0])} equity`, p[1] > 0 ? `TLT ${fx(p[1], 1)}x` : null, p[2] > 0 ? `${fx(p[2] * 100, 2)}% puts` : null, p[3] > 0 ? `${fx(p[3] * 100, 0)}% gold` : null].filter(Boolean).join(", ");
  // a live covariance file must be two regimes of 5 x 5 finite matrices with positive variances, or the snapshot stays
  const covOk = (c) => { try { return ["low_inflation", "inflation"].every((k) => { const m = c.regimes[k].cov; return m.length === 5 && m.every((r, i) => r.length === 5 && r.every(fin) && r[i] > 0) && fin(c.regimes[k].months); }); } catch (e) { return false; } };
  let RZ_LAST = null;
  function runReasoner(withVoi = true) {
    const P = rzParams(), pri = RZ_SCENARIOS.map((s) => s.prior), obs = rzObserved(), cur = rzCurrent();
    const post = rzPosterior(pri, RZ_SIGNALS, obs);
    const alts = rzAlternatives(post.posterior, RZ_SCENARIOS, P, cur);
    const robust = rzRobust(alts);
    const voi = withVoi ? rzVOI(pri, RZ_SIGNALS, obs, RZ_SCENARIOS, P) : null;
    const cov = covOk(LIVE.brain && LIVE.brain.factor_cov) ? LIVE.brain.factor_cov : REASON_SNAP;
    const rev = {};
    Object.keys(cov.regimes).forEach((k) => { rev[k] = reverseStress(rzExposure(cur, P), cov.regimes[k].cov, P.max_loss); });
    RZ_LAST = { P, pri, obs, cur, post, alts, robust, voi, rev, cov, at: Date.now() };
    return RZ_LAST;
  }

  /* ---------- the calculator ---------- */
  const CALC_VARS = {};
  function calcEnv() {
    const I = inputs(), lv = (k) => { const m = LIVE.macro && LIVE.macro.rates && LIVE.macro.rates.levels; return m && m[k] && fin(m[k].value) ? m[k].value : NaN; };
    const y10 = fin(lv("y10")) ? lv("y10") : ROC_SNAP.y10.value, y30 = fin(lv("y30")) ? lv("y30") : ROC_SNAP.y30.value;
    return { $vix: I.vix.v, $vxn: I.vxn.v, $brent: I.oil.v, $infl36: I.infl.avg36 / 100, $cpi: I.infl.yoy / 100, $corr: I.corr.v, $hy: I.hy.v / 100,
      $y10: y10 / 100, $y30: y30 / 100, $real: I.real.v / 100, $rf: RZ_DEFAULTS.rf, $gross: I.gross ? I.gross.v : NaN };
  }
  const CALC_EXAMPLES = ["bsput(100, 95, 0.25, ($vix + 3)%)", "kelly(0.55, 1.2)", "impact(2bn, 15bn, 2.2%)", "16.5 * 25bp", "irr(-100, 30, 40, 50)", "ninv(0.99) * 16% / sqrt(12)"];
  function wireCalc(input, out, hist) {
    if (!input || input.dataset.wired) return;
    input.dataset.wired = "1";
    const run = (expr, record) => {
      if (!expr.trim()) { out.replaceChildren(h("span", "calc-hint", "Type an expression: numbers, + − × ÷ ^ %, functions and live values such as $vix.")); return; }
      try {
        const r = calcEval(expr.replace(/^=\s*/, ""), calcEnv(), CALC_VARS);
        out.replaceChildren(h("span", "calc-eq", "="), h("strong", "calc-v num", calcFormat(r.value)));
        if (r.assigned) out.append(h("span", "calc-hint", ` saved as ${r.assigned}`));
        if (record && hist) {
          const li = h("li"), b = h("button", "calc-h", expr);
          b.type = "button";
          b.addEventListener("click", () => { input.value = expr; run(expr, false); input.focus(); });
          li.append(b, h("span", "num", calcFormat(r.value)));
          hist.prepend(li);
          while (hist.children.length > 8) hist.lastChild.remove();
        }
      } catch (e) { out.replaceChildren(h("span", "calc-err", `Can't read that: ${e.message}.`)); }
    };
    input.addEventListener("input", () => run(input.value, false));
    input.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); run(input.value, true); } });
    const ex = $("#calc-ex");
    if (ex) CALC_EXAMPLES.forEach((x) => { const b = h("button", "pill", x); b.type = "button"; b.addEventListener("click", () => { input.value = x; run(x, true); }); ex.append(b); });
    const vars = $("#calc-vars");
    if (vars) { const env = calcEnv(); vars.textContent = Object.keys(env).map((k) => `${k} ${fin(env[k]) ? calcFormat(Number(env[k].toPrecision(4))) : "n/a"}`).join(" · "); }
    run(input.value, false);
  }

  /* ---------- rendering ---------- */
  const SCEN_SHORT = { base: "Base", soft: "Soft landing", melt: "Melt-up", termprem: "Term premium", digest: "Capex digestion", stagfl: "Stagflation", crash: "Crash" };
  function heatCell(v, scale = 0.25) {
    const td = h("td", "r num heat", sPct(v, 1));
    const a = Math.min(1, Math.abs(v) / scale);
    td.style.background = `color-mix(in srgb, ${v >= 0 ? "var(--good)" : "var(--bad)"} ${Math.round(a * 38)}%, transparent)`;
    return td;
  }
  function renderSolve(full = true) {
    if (!$("#rz-ledger")) return;
    const R = runReasoner(full), sig = observeSignals(), opt = R.alts.optimal, keep = R.alts.keep;
    // 1. the answer
    const top = R.post.posterior.map((p, i) => [p, i]).sort((a, b) => b[0] - a[0]);
    $("#rz-answer").textContent = opt
      ? `Hold ${portTxt(opt.port)}. Expected log growth over three months ${sPct(opt.ce, 1)}; worst scenario ${sPct(opt.worst, 1)} against a ${RZS.loss}% limit. The book as it stands (${portTxt(R.cur)}) ${keep.feasible ? "meets" : "breaks"} this desk's ${RZS.loss}% three-month scenario limit: worst case ${sPct(keep.worst, 1)}. ${govNote("The solver's allocation", opt.port[0])}`
      : "No portfolio on the grid meets the loss limit; loosen the limit or the premium budget.";
    $("#rz-top").textContent = `${RZ_SCENARIOS[top[0][1]].name} ${pct0(top[0][0])} · ${RZ_SCENARIOS[top[1][1]].name} ${pct0(top[1][0])}`;
    // 2. the evidence ledger
    const tb = $("#rz-ledger tbody");
    tb.replaceChildren();
    sig.forEach((s) => {
      const def = RZ_SIGNALS.find((x) => x.id === s.id), state = R.obs[s.id], over = s.id in RZS.over, tr = h("tr");
      const lr = def.lik.map((l, j) => Math.log(state ? l / (1 - l) : (1 - l) / l));
      const lean = lr.indexOf(Math.max(...lr));
      const b = h("button", "pill" + (state ? " strong" : ""), state == null ? "unknown" : state ? "on" : "off");
      b.type = "button";
      b.setAttribute("aria-label", `${def.name}: ${state ? "on" : "off"}${over ? " (your what-if)" : ""}. Toggle.`);
      b.addEventListener("click", () => {
        const nxt = !(state === true);
        if (nxt === s.on) delete RZS.over[s.id]; else RZS.over[s.id] = nxt;
        LS.set("bo-rz-over", RZS.over); renderSolve(true);
      });
      const tdS = h("td"); tdS.append(b); if (over) tdS.append(h("span", "whatif", "what-if"));
      const tdE = h("td"); tdE.append(over ? evTag("asm", "Your override") : s.on == null ? evTag("na") : evTag("obs", latestTag(s)));
      tr.append(h("td", null, def.name), h("td", "r num", s.show), h("td", "r", s.d ? isoNice(s.d) : s.id === "capex" ? FUND.as_of.replace("SEC filings through ", "") : "n/a"), tdS, tdE,
        h("td", null, state == null ? "n/a" : SCEN_SHORT[RZ_SCENARIOS[lean].id]), h("td", "cat", def.cluster));
      tb.append(tr);
    });
    // 3. posterior against prior
    barsH($("#rz-post"), RZ_SCENARIOS.map((s, i) => ({ label: s.name, v: R.post.posterior[i] * 100, mark: R.post.prior[i] * 100, lbl: pct0(R.post.posterior[i]),
      color: i === top[0][1] ? "var(--s1)" : "var(--s2)", tip: () => [[pct0(R.post.posterior[i]), "posterior"], [pct0(R.post.prior[i]), "prior (tick)"], [s.name, `market ${sPct(s.market, 0)}, AI ${sPct(s.ai, 0)}, long yield ${sBp(s.dy * 1e4, 0)}bp`]] })),
      { label: "Posterior probability of each 3-month scenario, with the prior as a tick", fmt: (v) => fx(v, 0) + "%", labelW: 210 });
    // 4. alternatives
    const names = { keep: "Keep the exposure", reduce: "Reduce until the limit holds", hedge: "Same equity, best hedge", optimal: "Optimal on the grid" };
    const at = $("#rz-alts tbody");
    at.replaceChildren();
    ["keep", "reduce", "hedge", "optimal"].forEach((k) => {
      const a = R.alts[k], tr = h("tr");
      if (!a) { tr.append(h("td", null, names[k]), h("td", "r", "none feasible")); at.append(tr); return; }
      const first = h("td"); first.append(h("strong", null, names[k])); if (k === R.alts.minimax_regret) first.append(h("span", "flag", "minimax regret"));
      tr.append(first, h("td", "r num", xx(a.port[0])), h("td", "r num", fx(a.port[1], 1) + "x"), h("td", "r num", fx(a.port[2] * 100, 2) + "%"), h("td", "r num", fx(a.port[3] * 100, 0) + "%"),
        h("td", "r num", sPct(a.mean, 1)), h("td", "r num", sPct(a.ce, 1)), h("td", "r num", sPct(a.worst, 1)), h("td", "r num", fx(a.max_regret * 100, 1) + " pts"),
        h("td", "r", a.feasible ? "yes" : "no"));
      at.append(tr);
    });
    // 5. payoff by scenario
    const ht = $("#rz-heat");
    ht.replaceChildren();
    const thead = h("thead"), hr = h("tr");
    hr.append(h("th", null, "Choice"));
    RZ_SCENARIOS.forEach((s, i) => { const th = h("th", "r", SCEN_SHORT[s.id]); th.title = `${s.name}: posterior ${pct0(R.post.posterior[i])}`; hr.append(th); });
    thead.append(hr);
    const hb = h("tbody");
    ["keep", "reduce", "hedge", "optimal"].forEach((k) => { if (!R.alts[k]) return; const tr = h("tr"); tr.append(h("td", null, names[k])); R.alts[k].rets.forEach((v) => tr.append(heatCell(v))); hb.append(tr); });
    const pr = h("tr", "post-row"); pr.append(h("td", null, "Posterior")); R.post.posterior.forEach((p) => pr.append(h("td", "r num", pct0(p)))); hb.append(pr);
    ht.append(thead, hb);
    // 6. the game against Nature
    const rb = R.robust, natTop = rb.nature.map((p, i) => [p, i]).filter((x) => x[0] > 0.005).sort((a, b) => b[0] - a[0]);
    $("#rz-nature").textContent = `If Nature picks the scenario that hurts most, the best that can be guaranteed is ${sPct(rb.value, 1)} over three months, with ${rb.names.map((n, i) => (rb.mix[i] > 0.995 ? `"${names[n]}"` : rb.mix[i] > 0.005 ? `${pct0(rb.mix[i])} in "${names[n]}"` : null)).filter(Boolean).join(" and ")}. Nature's equilibrium attack: ${natTop.map(([p, i]) => `${RZ_SCENARIOS[i].name} ${pct0(p)}`).join(", ")}. That blend, not the posterior, is what the book is most exposed to.`;
    // 7. value of information
    if (R.voi) {
      const vt = $("#rz-voi tbody");
      vt.replaceChildren();
      R.voi.signals.forEach((r) => {
        const tr = h("tr");
        tr.append(h("td", null, r.name), h("td", "r num", fx(r.evsi_bp, 1)), h("td", "r num", pct0(r.p_on)),
          h("td", "r", r.flip_changes_choice == null ? "n/a" : r.flip_changes_choice ? "yes" : "no"),
          h("td", null, r.choice_if_on.join(" / ") === r.choice_if_off.join(" / ") ? "same choice either way" : `on: ${shortPort(r.choice_if_on)} · off: ${shortPort(r.choice_if_off)}`));
        vt.append(tr);
      });
      $("#rz-evpi").textContent = `Perfect foresight of the scenario would be worth ${fx(R.voi.evpi_bp, 0)}bp of certainty-equivalent return over three months (the ceiling on any research). The table ranks what each signal is worth to learn.`;
    }
    // 8. reverse stress
    const rv = R.rev[RZS.regime] || R.rev.inflation, months = R.cov.regimes[RZS.regime] ? R.cov.regimes[RZS.regime].months : null;
    const units = [(v) => sPct(v, 1), (v) => sPct(v, 1), (v) => `${sBp(v * 1e4, 0)}bp`, (v) => sPct(v, 1), (v) => sPct(v, 1)];
    const rt = $("#rz-rev tbody");
    rt.replaceChildren();
    ["Stock market (S&P 500)", "AI factor (excess)", "10-year yield", "Brent", "Gold"].forEach((n, i) => {
      const tr = h("tr"); tr.append(h("td", null, n), h("td", "r num", units[i](rv.shock[i]))); rt.append(tr);
    });
    $("#rz-rev-out").textContent = fin(rv.sigmas)
      ? `For the book as it stands, the most plausible way to lose ${RZS.loss}% in three months is the move above: ${fx(rv.sigmas, 2)} standard deviations of the joint factor distribution, measured over ${months || "n/a"} months of the ${RZS.regime === "inflation" ? "2022-on inflation" : "1990 to 2021 low-inflation"} regime. Under a normal model that is a ${pct0(rv.p_normal)} chance a quarter; fat tails make it likelier.`
      : "The book has no exposure to these factors.";
    fixChartRoles($("#view-solve"));
  }
  /* ---------- v0.8: the boundary of the decision, its robustness, and five kinds of uncertainty ---------- */
  const BND_TILTS = [0.25, 0.5, 0.75, 1, 1.25, 1.5, 2, 2.5, 3], BND_LOSSES = [0.05, 0.08, 0.10, 0.12, 0.15, 0.18, 0.20, 0.25, 0.30, 0.35];
  function renderBoundary() {
    const box = $("#rz-bnd");
    if (!box || !RZ_LAST) return;
    redrawWhenSized(box, renderBoundary);
    const R = RZ_LAST, grid = rzBoundary(R.post.posterior, RZ_SCENARIOS, R.P, BND_TILTS, BND_LOSSES), opt = R.alts.optimal;
    let agree = 0, tot = 0;
    grid.forEach((row) => row.forEach((c) => { if (c) { tot += 1; if (opt && Math.abs(c.port[0] - opt.port[0]) <= 0.1 + 1e-9) agree += 1; } }));
    const W = boxWidth(box), padL = 54, padB = 40, padT = 10, cw = (W - padL - 10) / BND_TILTS.length, chh = 26, Hh = padT + chh * BND_LOSSES.length + padB;
    box.replaceChildren();
    const sv = svg("svg", { viewBox: `0 0 ${W} ${Hh}`, width: W, height: Hh, role: "img", "aria-label": `Decision boundary: optimal equity by downside odds and loss limit. The current choice holds in ${tot ? Math.round((agree / tot) * 100) : 0}% of the grid.` }, box);
    const col = (e) => `color-mix(in srgb, var(--q5) ${Math.round((e / 1.5) * 100)}%, var(--q1))`;
    BND_LOSSES.forEach((L, i) => {
      const y = padT + (BND_LOSSES.length - 1 - i) * chh;
      text(sv, padL - 8, y + chh / 2 + 4, `${Math.round(L * 100)}%`, "ax", "end");
      BND_TILTS.forEach((f, j) => {
        const c = grid[i][j], x = padL + j * cw;
        const r = svg("rect", { x: x + 1, y: y + 1, width: cw - 2, height: chh - 2, rx: 4, fill: c ? col(c.port[0]) : "var(--grid)" }, sv);
        if (c) text(sv, x + cw / 2, y + chh / 2 + 4, `${fx(c.port[0], 2)}${c.port[2] > 0 ? "·p" : ""}`, c.port[0] > 0.8 ? "bnd-l dark" : "bnd-l", "middle");
        const here = Math.abs(f - 1) < 1e-9 && Math.abs(L - R.P.max_loss) < 1e-9;
        if (here) svg("rect", { x: x + 1, y: y + 1, width: cw - 2, height: chh - 2, rx: 4, fill: "none", stroke: "var(--ink)", "stroke-width": 2.2 }, sv);
        bindTip(r, () => [[c ? `${xx(c.port[0])} equity` : "nothing feasible", `downside odds ×${f}, loss limit ${Math.round(L * 100)}%`], [c ? `TLT ${fx(c.port[1], 1)}x · puts ${fx(c.port[2] * 100, 2)}% · gold ${fx(c.port[3] * 100, 0)}%` : "", "rest of the portfolio"]]);
      });
    });
    BND_TILTS.forEach((f, j) => text(sv, padL + j * cw + cw / 2, Hh - padB + 16, `×${f}`, "ax", "middle"));
    text(sv, padL + (W - padL) / 2, Hh - 6, "Odds on the four downside scenarios, times today's posterior", "ax", "middle");
    $("#rz-bnd-out").textContent = `The current choice (${opt ? xx(opt.port[0]) : "n/a"} equity, within 0.10x) is optimal in ${tot ? Math.round((agree / tot) * 100) : 0}% of the ${tot} assumption pairs tested. That is scenario robustness across stated assumptions, not a probability. "·p" marks cells that buy put spreads. Your current limit and today's odds are outlined.`;
    RZ_LAST.robust_share = tot ? agree / tot : NaN;
    renderUncertainty();
  }
  function renderUncertainty() {
    const box = $("#rz-unc");
    if (!box || !RZ_LAST) return;
    const R = RZ_LAST, sig = observeSignals(), live = sig.filter((x) => x.live).length, known = sig.filter((x) => x.on != null).length;
    const H = -R.post.posterior.reduce((a, p) => a + (p > 0 ? p * Math.log(p) : 0), 0) / Math.log(R.post.posterior.length);
    const opt = R.alts.optimal, spread = opt ? Math.max(...opt.rets) - Math.min(...opt.rets) : NaN;
    const mm = R.alts.minimax_regret, robustPick = R.robust.names[R.robust.mix.indexOf(Math.max(...R.robust.mix))];
    const loo = rzLeaveOneOut(R.pri, RZ_SIGNALS, R.obs, RZ_SCENARIOS, R.P), flipsFam = loo.filter((x) => x.used && !x.same);
    const flipSig = R.voi ? R.voi.signals.filter((x) => x.flip_changes_choice) : [];
    const months = R.cov.regimes.inflation ? R.cov.regimes.inflation.months : null;
    const grade = (bad, mid) => (bad ? ["High", "bad"] : mid ? ["Medium", "warn"] : ["Low", "good"]);
    const rows = [
      ["Data quality", grade(known < 5, live < known), `${known} of ${sig.length} signals observed, ${live} from the latest daily files; the rest from the dated snapshot.`],
      ["Forecast uncertainty", grade(H > 0.85, H > 0.6), `Posterior entropy ${fx(H, 2)} of its maximum; the chosen portfolio's 3-month outcomes span ${fx(spread * 100, 1)} points across scenarios.`],
      ["Model disagreement", grade(mm !== "optimal" && robustPick !== "optimal", mm !== "optimal" || robustPick !== "optimal"), `Growth-optimal picks "optimal"; minimax regret picks "${mm}"; the game against Nature leans to "${robustPick}".`],
      ["Assumption sensitivity", grade(flipSig.length >= 3 || (fin(R.robust_share) && R.robust_share < 0.3), flipSig.length >= 1 || flipsFam.length >= 1), `${flipSig.length} signal${flipSig.length === 1 ? "" : "s"} would flip the choice; dropping ${flipsFam.length ? flipsFam.map((x) => `the ${x.family} family`).join(" or ") : "no single evidence family"} changes it${fin(R.robust_share) ? `; robust in ${pct0(R.robust_share)} of the boundary grid` : ""}.`],
      ["Applicability", grade(months != null && months < 36, months != null && months < 120), `Covariances for the current regime rest on ${months || "n/a"} months; scenarios and likelihoods are assumptions, not fitted to these conditions.`],
    ];
    box.replaceChildren(tableBlock(["Dimension", "Level", "Why"], rows.map(([k, [lvl], why]) => [k, lvl, why])));
    box.querySelectorAll("tbody tr").forEach((tr, i) => { const td = tr.children[1]; td.className = "lvl-" + rows[i][1][1]; });
    const lt = $("#rz-loo");
    if (lt) lt.replaceChildren(tableBlock(["Evidence family left out", "Used today", "Choice without it", "Same choice?"], loo.map((x) => [x.family, x.used ? "yes" : "no", x.port ? shortPort(x.port) : "nothing feasible", x.same ? "yes" : "no"])));
  }
  let solveTimer = null;
  function scheduleSolve() {
    renderSolve(false);                                   // instant: posterior and choices
    clearTimeout(solveTimer);
    solveTimer = setTimeout(() => { guard("Value of information", () => renderSolve(true), $("#rz-voi")); guard("Decision boundary", renderBoundary, $("#rz-bnd")); guard("Robust solver", renderDRO, $("#rz-dro")); }, 180);
  }
  function buildSolve() {
    if (!$("#rz-ledger")) return;
    const bind = (id, key, fmt) => {
      const el = $(id), o = $(id + "-o");
      if (!el || el.dataset.wired) return;
      el.dataset.wired = "1";
      const upd = () => { RZS[key] = Number(el.value); if (o) o.textContent = fmt(RZS[key]); };
      el.addEventListener("input", () => { upd(); scheduleSolve(); });
      upd();
    };
    const cur = rzCurrent();
    if ($("#rz-eq") && !$("#rz-eq").dataset.wired) $("#rz-eq").value = String(cur[0]);
    if ($("#rz-h") && !$("#rz-h").dataset.wired) $("#rz-h").value = String(cur[1]);
    bind("#rz-loss", "loss", (v) => `${v}%`);
    bind("#rz-prem", "prem", (v) => `${fx(v, 2)}%`);
    bind("#rz-eq", "eq", (v) => xx(v));
    bind("#rz-h", "h", (v) => `${fx(v, 1)}x`);
    const sel = $("#rz-regime");
    if (sel && !sel.dataset.wired) { sel.dataset.wired = "1"; sel.value = RZS.regime; sel.addEventListener("change", () => { RZS.regime = sel.value; renderSolve(false); }); }
    const reset = $("#rz-reset");
    if (reset && !reset.dataset.wired) { reset.dataset.wired = "1"; reset.addEventListener("click", () => { RZS.over = {}; LS.set("bo-rz-over", {}); renderSolve(true); }); }
    wireCalc($("#calc-in"), $("#calc-out"), $("#calc-hist"));
    const rec = $("#rz-record");
    if (rec && !rec.dataset.wired) {
      rec.dataset.wired = "1";
      rec.addEventListener("click", async () => {
        rec.disabled = true;
        const msg = $("#rz-record-msg");
        try {
          const R = RZ_LAST || runReasoner(true), saved = await recordSolverDecision(R, observeSignals());
          if (saved) { msg.replaceChildren(document.createTextNode(`Recorded with hash ${saved.hash}. `)); const a = h("a", null, "Open it in the journal →"); a.href = "#journal"; a.addEventListener("click", () => { JR.sel = saved.id; JR.draft = Object.assign({}, saved); JR.showEx = false; }); msg.append(a); if (typeof renderJournal === "function") renderJournal(); }
          else msg.textContent = "Could not save here; export from the journal to keep it.";
        } catch (e) { msg.textContent = "Could not record: " + (e && e.message ? e.message : e); }
        rec.disabled = false;
      });
    }
    if (current === "solve") renderSolve(true);          // the full solve (about a second) runs when the desk opens, not at page load
    guard("Decision boundary", renderBoundary, $("#rz-bnd"));
    guard("Robust solver", renderDRO, $("#rz-dro"));
  }

  /* ---------- v0.10: robust to being wrong about the odds ---------- */
  const DRO = { idx: 4, key: null, sweep: null, timer: null };
  function renderDRO() {
    const t = $("#rz-dro");
    if (!t || !RZ_LAST) return;
    const R = RZ_LAST, post = R.post.posterior, key = post.map((p) => p.toFixed(6)).join() + JSON.stringify(R.P);
    if (DRO.key !== key) {
      DRO.key = key; DRO.sweep = null;
      $("#rz-dro-out").textContent = "Solving under doubt…";
      clearTimeout(DRO.timer);
      DRO.timer = setTimeout(() => { try { DRO.sweep = rzRobustSweep(post, RZ_SCENARIOS, R.P); } catch (e) { DRO.sweep = null; } guard("Robust solver", drawDRO, $("#rz-dro")); }, 60);
      return;
    }
    drawDRO();
  }
  const portShort = (p) => `${xx(p[0])} equity${p[1] ? ` · TLT ${fx(p[1], 1)}x` : ""}${p[2] ? ` · puts ${fx(p[2] * 100, 2)}%` : ""}${p[3] ? ` · gold ${fx(p[3] * 100, 0)}%` : ""}`;
  function drawDRO() {
    const S = DRO.sweep, t = $("#rz-dro");
    if (!S || !t) return;
    fillTable(t, ["Doubt", "Choice", "Guaranteed growth", "Nominal growth", "Price"], S.rows.map((r) => [r.rho === 0 ? "none" : fx(r.rho, 2), portShort(r.port), sPct(r.worst_case_ce, 2), sPct(r.nominal_ce, 2), r.rho === 0 ? "" : `${fx(r.price_bp, 0)}bp`]), 2);
    const post = RZ_LAST.post.posterior, crash = RZ_SCENARIOS.findIndex((s) => s.id === "crash"), r1 = S.rows.find((r) => r.rho === S.first_change_rho) || S.rows[1];
    const p1 = (v) => (v < 0.1 ? fx(v * 100, 1) + "%" : pct0(v));
    $("#rz-dro-out").textContent = S.first_change_rho == null
      ? "The choice holds at every level of doubt tested: it does not depend on the odds being exactly right."
      : `The choice changes at a doubt of ${fx(S.first_change_rho, 2)}, enough to let the liquidity-crash scenario's odds rise from ${p1(post[crash])} to ${p1(maxScenarioOdds(post[crash], S.first_change_rho))}. ${S.first_change_rho <= 0.02 ? "That is a small doubt: the nominal choice leans on the exact odds and is not robust." : "The nominal choice survives modest doubt about the odds."} At that level the robust choice is ${portShort(r1.port)}, giving up ${fx(r1.price_bp, 0)}bp of nominal growth.`;
    const sl = $("#rz-dro-rho");
    if (sl && !sl.dataset.wired) { sl.dataset.wired = "1"; sl.max = String(S.rows.length - 1); sl.addEventListener("input", () => { DRO.idx = Number(sl.value); drawDROq(); }); }
    drawDROq();
  }
  function drawDROq() {
    const S = DRO.sweep;
    if (!S) return;
    const r = S.rows[Math.min(DRO.idx, S.rows.length - 1)], post = RZ_LAST.post.posterior;
    $("#rz-dro-rho-o").textContent = r.rho === 0 ? "none" : fx(r.rho, 2);
    barsH($("#rz-dro-q"), RZ_SCENARIOS.map((s, i) => ({ label: s.name, v: (r.q_worst[i] - post[i]) * 100, lbl: `${pct0(post[i])} → ${pct0(r.q_worst[i])}`, color: r.q_worst[i] > post[i] ? "var(--s2)" : "var(--s1)" })),
      { label: "Worst-case odds against the posterior, by scenario", fmt: (v) => sg(v, 0) + " pts", padR: 96 });
    const up = RZ_SCENARIOS.map((s, i) => ({ n: s.name, d: r.q_worst[i] - post[i] })).sort((a, b) => b.d - a.d)[0];
    $("#rz-dro-q-t").textContent = r.rho === 0 ? "No doubt: the posterior odds as they are." : `At this doubt the odds that hurt the robust choice most put ${up.n} up ${fx(up.d * 100, 0)} points. Its guaranteed growth is ${sPct(r.worst_case_ce, 2)} a quarter whatever odds within that distance turn out to be true.`;
  }

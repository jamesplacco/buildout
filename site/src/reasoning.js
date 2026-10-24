  /* =====================================================================================
     v0.25: REASONING (deduction, induction, abduction, invention), BORROWED MT_METHODS, THE MT_METHODS REGISTRY
     Reads SNAP25 (scripts/snapshot_v25.py) and, for live numbers, DX19 and PF20. Nothing is recomputed.
     ===================================================================================== */
  const R25 = () => (typeof SNAP25 !== "undefined" && SNAP25) || null;
  const rsF = (v, d = 2) => (fin(v) ? fx(v, d) : "n/a");
  const rsT = (v) => (fin(v) ? (v >= 0 ? "+" : "−") + fx(Math.abs(v), 2) : "n/a");
  const rsPP = (v, d = 1) => (fin(v) ? (v >= 0 ? "+" : "−") + fx(Math.abs(v) * 100, d) + " pts" : "n/a");
  const RS_VAR = { cape_pct: "CAPE percentile", log_cape: "log CAPE", ecy: "excess CAPE yield", y10: "10-year yield", dy12: "12-month change in the 10-year yield",
    infl12: "12-month inflation", infl36: "36-month inflation", mom12_1: "12-1 month momentum", trend_gap: "distance from the 10-month average", vol12: "12-month volatility",
    drawdown: "distance below the peak", corr36: "36-month stock-bond correlation", earn_g12: "12-month real earnings growth", earn_accel: "change in earnings growth" };
  const RS_OUT = { ret12: "next 12 months' real return", ret1: "next month's real return", crash12: "chance of a 15% fall within 12 months", vol_next12: "next 12 months' volatility",
    maxdd12: "worst drawdown in the next 12 months", bond_hedge12: "chance bonds hedge stocks over the next 36 months" };
  const rsCond = (c) => `${RS_VAR[c[0]] || c[0]} ${c[1].replace("<=", "≤").replace(">=", "≥")} ${Math.abs(c[2]) < 1 && !["cape_pct", "log_cape"].includes(c[0]) ? fx(c[2] * 100, Math.abs(c[2]) < 0.01 ? 2 : 1) + "%" : fx(c[2], 2)}`;
  const rsKpi = (box, rows) => { box.replaceChildren(); rows.forEach(([v, k, s]) => { const d = h("div", "at-kpi"); d.append(h("b", null, v), h("span", null, k), h("small", null, s)); box.append(d); }); };

  function renderReasoning() {
    const S = R25(), O = S && S.reason;
    const tiles = $("#rs-tiles");
    if (!tiles) return;
    if (!O) { tiles.replaceChildren(h("p", "empty", "The reasoning run is not in this build.")); return; }
    const D = O.discover, DE = O.deduce, rules = (O.rules || []).filter((r) => r.source !== "built-in example");
    const sup = rules.filter((r) => r.verdict === "supported"), one = rules.filter((r) => r.verdict === "one era only"), rev = rules.filter((r) => r.verdict === "reversed");
    rsKpi(tiles, [[DE.derived.toLocaleString("en-US"), "Facts deduced", `from ${DE.given.toLocaleString("en-US")} typed links, ${DE.contradictions_n} contradictions`],
      [`${D.survivors.length} of ${D.tested}`, "Induced rules that survived", `found before 1961, tested after; ${D.n_candidates.toLocaleString("en-US")} conditions tried`],
      [`${sup.length} of ${rules.length}`, "Legendary rules supported", `in both halves of the record; ${one.length} in one era only, ${rev.length} reversed`],
      [`${O.invent.predicates.survivors.length} of ${O.invent.predicates.candidates}`, "Invented predicates that survived", `and ${O.invent.k} invented regimes that do not beat the mean`]]);
    // 1. deduction: the decision as a proof
    const P = O.decision, box = $("#rs-proof");
    const node = (t, depth = 0) => {
      const li = h("li", t.given ? "rs-leaf" : null);
      if (t.given) li.append(h("span", "rs-fact", t.fact.replace(/_/g, " ")), h("small", null, " given"));
      else { li.append(h("span", "rs-concl", t.conclusion), h("small", "rs-rule", ` by ${t.rule}`)); const ul = h("ul"); (t.premises || []).forEach((p) => ul.append(node(p, depth + 1))); li.append(ul); }
      return li;
    };
    const ul = h("ul", "rs-tree"); ul.append(node(P.proof)); box.replaceChildren(ul);
    const cf = (P.counterfactuals || []).filter((c) => c.flips_up || c.flips_down || c.why_not || c.changes);
    fillTable($("#rs-cf"), ["Premise", "Today", "What flips, and where"], cf.map((c) => {
      const f = c.flips_down || c.flips_up;
      const what = f ? `at ${fin(f.at) ? fx(f.at, Math.abs(f.at) < 1 ? 3 : 2) : f.at}: hedge ${f.bond_hedge}, ${fx(f.exposure, 2)}x, overlay ${f.overlay}` : c.why_not ? c.why_not : c.if !== undefined ? `if ${c.if}: ${c.changes ? (c.hedge_name ? c.hedge_name.toLowerCase() : `hedge ${c.bond_hedge}, ${fx(c.exposure, 2)}x`) : "no change"}` : "";
      return [c.premise.replace(/_/g, " "), typeof c.now === "number" ? fx(c.now, Math.abs(c.now) < 1 ? 3 : 2) : String(c.now), what];
    }), 1);
    const PR = (P.rules || []).map((r) => `<b>${r.name}</b>: ${r.text}`).join("<br>");
    $("#rs-proof-math").innerHTML = `<span class="mlabel">The rules, as written (Horn clauses; the proof applies them in order)</span>${PR}`;
    $("#rs-ded").textContent = `From ${DE.given.toLocaleString("en-US")} typed facts in the mind (is a, part of, causes up, causes down, measures, uses, opposes, hedges), forward chaining derived ${DE.derived.toLocaleString("en-US")} more in ${DE.steps} rounds and reached a fixpoint: ${DE.counts["part_of.transitive"]} by the transitivity of part of, ${DE.counts["is_a.transitive"]} by the transitivity of is a, ${DE.causal_derived} causal chains of up to ${DE.max_len} links with signs multiplied, and ${DE.counts["opposes.symmetric"]} by symmetry. It found ${DE.sign_contradictions} pairs derived with both signs above a confidence of ${fx(DE.floor, 1)} and ${DE.contradictions_n} contradictions in all. It never deduces a hedge from causal signs alone: two things moved by the same driver in opposite directions need not offset in a crash. Examples:`;
    fillTable($("#rs-chains"), ["Derived", "Rule", "Confidence", "Chain"], (DE.examples || []).filter((e) => /causal/.test(e.rule)).slice(0, 10).map((e) => [`${e.fact[0]} ${e.fact[1] === "causes+" ? "raises" : e.fact[1] === "causes-" ? "lowers" : e.fact[1]} ${e.fact[2]}`, e.rule, fx(e.conf, 2), e.chain.map((c) => `${c[0]} ${c[1] === "causes+" ? "↑" : "↓"} ${c[2]}`).join("; ")]), 1);
    // 2. induction
    const pc = D.per_outcome.ret12;
    $("#rs-ind-p").textContent = `Every feature at its quintile edges (known at the cutoff), alone and in pairs, against each of six outcomes: ${D.n_candidates.toLocaleString("en-US")} candidate rules scored on ${pc.disc_from.slice(0, 4)} to ${pc.disc_to.slice(0, 4)}. The best ${D.tested} were carried untouched into ${D.start_test.slice(0, 4)} to 2026 and kept only if their effect held with Benjamini-Hochberg control across the ${D.tested}. ${D.bh_significant.toLocaleString("en-US")} passed the discovery screen, a count inflated by conditions that last for years; the later period is the real test.`;
    const steps = [[D.n_candidates, "conditions tried"], [D.bh_significant, "pass discovery (inflated)"], [D.tested, "carried forward"], [D.testable, "testable after 1961"], [D.kept_sign, "kept their sign"], [D.survivors.length, "survived"]];
    const fun = $("#rs-funnel"); fun.replaceChildren();
    steps.forEach(([n, k], i) => { const d = h("div", "rs-step"); d.style.setProperty("--w", `${Math.max(8, 100 * Math.log10(n + 1) / Math.log10(D.n_candidates + 1))}%`); d.append(h("b", "num", n.toLocaleString("en-US")), h("span", null, k)); fun.append(d); });
    $("#rs-ind-math").innerHTML = `<span class="mlabel">The test for each rule</span>effect &Delta; = &#563;<sub>in</sub> &minus; &#563;<sub>out</sub>; <var>t</var> = &Delta; / SE<sub>NW</sub>(&Delta;) with Newey-West lags equal to the outcome's horizon (12 months; 36 for the bond hedge), because overlapping 12-month outcomes are not independent; BH: reject <var>p</var><sub>(k)</sub> &le; <var>k q</var>/<var>m</var>, <var>q</var> = 10%. Posterior that the sign is right: &Phi;(&Delta;&#770;/&radic;(SE<sup>2</sup> + &tau;<sup>2</sup>) &middot; &tau;/SE) under a skeptical prior N(0, &tau;<sup>2</sup>), &tau; = half the outcome's spread, computed on the out-of-sample estimate.`;
    const byId = Object.fromEntries((D.rules || []).map((r) => [r.id, r]));
    const surv = (D.survivors || []).map((x) => byId[x] || x).filter((r) => r && r.if);
    fillTable($("#rs-surv"), ["Rule found before 1961", "Outcome", "Effect before", "Effect after 1961", "t after", "Months inside", "P(sign right)"],
      surv.map((r) => [r.if.map(rsCond).join(" and "), RS_OUT[r.outcome] || r.outcome, r.outcome === "crash12" || r.outcome === "bond_hedge12" ? rsPP(r.disc.effect) : rsPP(r.disc.effect), rsPP(r.oos.effect), rsT(r.oos.t), String(r.oos.n_in), pct0(r.p_bayes_sign)]), 2);
    const RO = O.rolling || {};
    $("#rs-roll").textContent = "Rediscovered every ten years on the data to date and tested on the next ten: " + Object.entries(RO).map(([k, v]) => `${RS_OUT[k] || k}, ${v.testable ? `${pct0(v.share_held)} of ${v.testable} testable decades` : "never testable (each decade's best rule hardly recurred)"}`).join("; ") + ". A rule that holds in a decade it was not found in is rare; that is the lesson.";
    // 3. legends on trial
    const RM = S.rules_meta || {};
    $("#rs-leg-p").textContent = `${rules.length} principles from Taleb, Spitznagel, Livermore, Soros, Druckenmiller, Tudor Jones, Templeton, Baruch, Rogers, Robertson, Kovner, the Turtles, Dalio and the actuarial literature, each translated by a research agent into a condition and an outcome, checked against its source by a second agent, and run on every month since 1871. Supported means significant after Benjamini-Hochberg across all of them and the same sign before and after 1950. ${sup.length} are supported, ${one.length} hold in one era only, ${rev.length} reversed and ${rules.length - sup.length - one.length - rev.length} show no evidence.`;
    const LS = { v: "all" };
    const draw = () => {
      const pick = rules.filter((r) => LS.v === "all" || r.verdict === LS.v).sort((a, b) => (a.q || 1) - (b.q || 1));
      fillTable($("#rs-legends"), ["Who", "Principle (our words)", "Test", "Effect", "t", "Before / after 1950", "Verdict"], pick.map((r) => {
        const who = h("span"); const m = RM[r.id];
        if (m && m.source_url) { const a = h("a", null, r.person); a.href = m.source_url; a.target = "_blank"; a.rel = "noopener"; who.append(a); } else who.textContent = r.person;
        const isProb = ["crash12", "bond_hedge12"].includes(r.outcome);
        const eff = r.full && fin(r.full.effect) ? (isProb || r.outcome === "maxdd12" || r.outcome === "vol_next12" ? rsPP(r.full.effect) : rsPP(r.full.effect)) : "n/a";
        const halves = r.pre && r.post && fin(r.pre.effect) && fin(r.post.effect) ? `${rsPP(r.pre.effect)} / ${rsPP(r.post.effect)}` : "n/a";
        const v = h("span", "rs-v rs-v-" + (r.verdict || "").replace(/\s+/g, "-"), r.verdict);
        const dirW = r.outcome === "maxdd12" ? (r.direction > 0 ? "shallower" : "deeper") : (r.direction > 0 ? "higher" : "lower");
        return [who, r.principle, `If ${r.if.map(rsCond).join(" and ")}, the ${RS_OUT[r.outcome] || r.outcome} is ${dirW}`, eff, rsT(r.full && r.full.t), halves, v];
      }), 1);
    };
    const fb = $("#rs-leg-filter"); fb.replaceChildren();
    const seg = h("div", "seg");
    [["all", `All (${rules.length})`], ["supported", `Supported (${sup.length})`], ["one era only", `One era only (${one.length})`], ["reversed", `Reversed (${rev.length})`], ["no evidence", `No evidence (${rules.filter((r) => r.verdict === "no evidence").length})`]].forEach(([k, n]) => {
      const b = h("button", null, n); b.type = "button"; b.setAttribute("aria-pressed", LS.v === k ? "true" : "false");
      b.addEventListener("click", () => { LS.v = k; seg.querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", x === b ? "true" : "false")); draw(); });
      seg.append(b);
    });
    fb.append(seg); draw();
    $("#rs-leg-math").innerHTML = `<span class="mlabel">How a principle becomes a test</span>condition <var>C</var> on variables knowable at the start of the month; outcome <var>Y</var>; effect &Delta; = E[<var>Y</var> | <var>C</var>] &minus; E[<var>Y</var> | not <var>C</var>] with a Newey-West <var>t</var>; supported &hArr; BH <var>q</var> &le; 10% across all ${rules.length}, sign as claimed, and sign(&Delta;<sub>&lt;1950</sub>) = sign(&Delta;<sub>&ge;1950</sub>). Thresholds come from the principle or a round number, never fitted.`;
    // 4. abduction
    const AB = O.abduce || {};
    const abt = (key, tbl, title) => {
      const A = AB[key];
      if (!A) return;
      $(title).textContent = `${$(title).textContent} (base rate ${pct0(A.base_rate)} of ${A.months.toLocaleString("en-US")} months)`;
      fillTable($(tbl), ["Explanation", "Outcome followed it", "Otherwise", "Likelihood ratio", "Months"], (A.explanations || []).map((e) => [e.kind === "condition" ? e.text.replace(/\s*\(its [^)]*\)/, "") : `Regime: ${e.text || e.name}`, pct0(e.p_obs_given_h), pct0(e.p_obs_given_not), fx(e.lr, 2), String(e.months)]), 1);
    };
    abt("crash12=1", "#rs-abd1", "#rs-abd1-t"); abt("bond_hedge12=0", "#rs-abd2", "#rs-abd2-t");
    $("#rs-abd-math").innerHTML = `<span class="mlabel">Ranking explanations</span>LR(<var>h</var>) = P(obs | <var>h</var>) / P(obs | not <var>h</var>), each with Laplace smoothing (<var>k</var> + 1)/(<var>n</var> + 2); ranked by the support P(<var>h</var> | obs) &minus; P(<var>h</var>), so a condition true in most months cannot win by being common.`;
    // 5. invention
    const IV = O.invent;
    if (IV) {
      const oo = IV.oos || {}, r12 = oo.ret12, c12 = oo.crash12;
      $("#rs-inv-p").textContent = `A Gaussian mixture fit on the ${IV.features.length} standardized features to ${IV.cutoff.slice(0, 4)} chose ${IV.k} regimes by BIC and named each by its most distinctive features. Months after ${IV.cutoff.slice(0, 4)} were assigned by the fitted model only. ${r12 ? `Out of sample, knowing the regime gave an MSE skill of ${fx(r12.mse_skill * 100, 1)}% for the 12-month return (Diebold-Mariano t ${fx(r12.dm.t, 1)})` : ""}${c12 ? ` and a log-score gain of ${fx(c12.log_score_gain.mean_gain, 3)} nats a month for crashes (t ${fx(c12.log_score_gain.t, 1)})` : ""}: the invented regimes describe the past well and forecast no better than the long-run average. Of ${IV.predicates ? IV.predicates.candidates : "n/a"} invented predicates (products and differences of feature pairs), ${IV.predicates ? IV.predicates.screened : "n/a"} passed the discovery screen and ${IV.predicates ? IV.predicates.survivors.length : "n/a"} survived.`;
      fillTable($("#rs-inv"), ["Invented regime", "Months before 1961", "After", "12-month return, all months", "Chance of a 15% fall"], IV.clusters.map((c) => [c.name, String(c.months_pre), String(c.months_post), sPct(c.ret12_all, 1), pct0(c.crash12_all)]), 1);
      $("#rs-inv-math").innerHTML = `<span class="mlabel">The invention and its test</span><var>z</var> = standardized features; <var>p</var>(<var>z</var>) = &Sigma;<sub>k</sub> &pi;<sub>k</sub> N(<var>z</var>; &mu;<sub>k</sub>, &Sigma;<sub>k</sub>), <var>K</var> = argmin BIC = &minus;2 log <var>L</var> + <var>p</var> log <var>n</var> (chosen: ${IV.k}); name = the features with the largest |&mu;<sub>k,j</sub>|; test: MSE skill = 1 &minus; MSE<sub>regime means</sub>/MSE<sub>${IV.cutoff.slice(0, 4)} mean</sub> after ${IV.cutoff.slice(0, 4)}.`;
    }
    // 6. today
    const TD = O.today;
    if (TD) {
      const fires = TD.fires || [];
      const good = fires.filter((f) => f.survives || f.verdict === "supported");
      $("#rs-now").textContent = `${TD.date}: the invented regime today is "${TD.regime}". ${fires.length} rules fire, ${good.length} of them survivors or supported${good.length ? "" : ", so the reasoner adds nothing to the decision today and the engine's call stands as derived above"}. Five valuation and earnings features are carried from ${(TD.notes && TD.notes.carried && TD.notes.carried.cape_pct) || "2023-11"}, where Shiller's earnings stop. The reasoner's 36-month correlation (${fx(TD.row.corr36, 2)}) uses the engine's real 10-year bond returns, one month later than the Findings measure in force (${fx(P.facts.corr36, 2)}); both are above the +0.10 line.`;
      fillTable($("#rs-fire"), ["Rule that fires today", "Outcome", "Inside the condition", "All months", "Status"], fires.slice(0, 18).map((f) => [f.text ? f.text.replace(/\s*\(its [^)]*\)/g, "") : f.principle, RS_OUT[f.outcome] || f.outcome, fin(f.in) ? (["crash12", "bond_hedge12"].includes(f.outcome) ? pct0(f.in) : sPct(f.in, 1)) : "n/a", fin(f.base) ? (["crash12", "bond_hedge12"].includes(f.outcome) ? pct0(f.base) : sPct(f.base, 1)) : "n/a", f.survives ? "survivor" : f.verdict || "did not survive"]), 1);
    }
  }

  /* ---------- borrowed methods: actuarial, weather, big data ---------- */
  const CF_OVERLAP = [
    ["Score forecasts with proper rules", "Experience studies: actual against expected", "Brier, CRPS and log scores; skill against climatology", "Held-out leaderboards; log loss", "Log score and CRPS of the monthly mixture since 1950; skill against history"],
    ["Calibrate first, then sharpen", "A reserve that is right on average and in the tail", "Reliability diagrams and PIT histograms; EMOS", "Platt and isotonic calibration", "PIT and 90% coverage verified; EMOS tried and rejected"],
    ["Shrink small samples toward the pool", "Buhlmann credibility, Z = n/(n + k)", "Model output statistics against climatology", "Empirical Bayes and regularization", "Regime means shrunk with 120 pseudo-months; credibility tried and the 120 kept"],
    ["Model the tail on its own terms", "Generalized Pareto above a threshold; the 1-in-200 standard", "Extreme events verified separately", "Anomaly detection", "The 12% loss budget backtested against five tail estimators"],
    ["Combine many models, weight by record", "Blending chain ladder with a prior (Bornhuetter-Ferguson)", "Ensembles and Bayesian model averaging", "Stacking and boosting", "Dynamic model averaging by log score; BMA tried, not adopted"],
    ["Never let the test leak into the fit", "Reserves set before the claims develop", "Hindcasts on unseen seasons", "Leakage audits; a reused holdout counted", "Walk-forward with a two-month lag; every strategy tried discounted by the gate"],
  ];
  function renderCrossfield() {
    const S = R25(), C = S && S.crossfield;
    const tiles = $("#cf-tiles");
    if (!tiles) return;
    if (!C) { tiles.replaceChildren(h("p", "empty", "The verification run is not in this build.")); return; }
    const A = C.variants.as_is, TR = S.trials || [], M = S.methods || [], RU = C.ruin || {};
    rsKpi(tiles, [[`${TR.length}`, "Upgrades tried on the core", `${TR.filter((t) => t.adopted).length} adopted; each counted by the gate`],
      [pct0(A.coverage90 ? A.coverage90.coverage : NaN), "90% intervals that covered", `${A.coverage90 ? A.coverage90.n : ""} months since 1950; calibrated is 90%`],
      [RU["1.0"] ? pct(RU["1.0"].bootstrap_dd50_10y.p, 1, false) : "n/a", "Chance of a 50% fall within 10 years", "at 1x, by bootstrap of every month since 1871"],
      [String(M.length), "Method cards", "actuarial, weather and big data, each with a test"]]);
    fillTable($("#cf-overlap"), ["Shared idea", "Actuarial science", "Weather forecasting", "Big data and ML", "In the engine"], CF_OVERLAP, 1);
    // verification
    const pit = A.pit;
    $("#cf-verif-p").textContent = `From ${C.eval_start} to ${C.end} (${C.months_eval} months), the engine's predictive mixture scored a mean log score of ${fx(A.log_score, 3)} and a CRPS of ${fx(A.crps, 4)}. Its 90% intervals covered ${pct(A.coverage90.coverage, 1, false)} of months. The PIT histogram is nearly flat: the body is slightly too wide (PIT sd ${fx(pit.pit_sd, 3)} against ${fx(pit.pit_sd_uniform, 3)}), and consecutive PITs are correlated (+${fx(pit.z_acf1, 2)}) because Shiller's prices are monthly averages and the engine acts two months late. The one real failure is the far tail: at 1% the mixture is breached more often and by more than it predicts.`;
    barsV($("#cf-pit"), pit.counts.map((c, i) => ({ label: `${i * 10}–${(i + 1) * 10}%`, v: c, lbl: String(c), color: "var(--s1)", tip: () => [[String(c) + " months", `PIT in ${i * 10}% to ${(i + 1) * 10}%; flat is ${fx(pit.n / pit.bins, 0)}`]] })), { label: "Months by PIT decile" });
    $("#cf-pit-n").textContent = `Flat would be ${fx(pit.n / pit.bins, 0)} months a bar. Chi-square p ${fx(pit.chi2_p_neff, 2)} allowing for serial dependence; Kolmogorov-Smirnov p ${fx(pit.ks_p_neff, 2)}.`;
    const B = C.benchmarks || {}, BR = C.brier_down_month || {}, SS = C.spread_skill || {};
    const cl = (B.climatology || {}).crps || {}, cll = (B.climatology || {}).log_score || {}, un = (B.uncond_model || {}).crps || {}, pe = (B.persistence || {}).crps || {};
    fillTable($("#cf-score"), ["Measure", "Engine", "Reading"], [
      ["Mean log score", fx(A.log_score, 3), `higher is better; against history t ${rsT(cll.t)}`],
      ["CRPS", fx(A.crps, 4), "lower is better; in units of monthly return"],
      ["90% interval coverage", pct(A.coverage90.coverage, 1, false), `Kupiec p ${fx(A.coverage90.kupiec_p, 2)}`],
      ["CRPS skill against history (climatology)", sPct(cl.skill, 2), `t ${rsT(cl.t)}: no better than the expanding record`],
      ["CRPS skill against its own long-run model", sPct(un.skill, 1), `t ${rsT(un.t)}: the regimes and analogs add something`],
      ["CRPS skill against persistence", sPct(pe.skill, 0), `t ${rsT(pe.t)}`],
      ["Brier, chance of a down month", fx(BR.bs, 4), `reliability ${fx(BR.reliability, 4)}, resolution ${fx(BR.resolution, 4)}, skill ${sPct(BR.bss_vs_base_rate, 1)}`],
      ["Spread and skill", fx(SS.corr, 2), `p ${fx(SS.corr_p, 5)}: a wider forecast does mean a larger miss`],
    ], 1);
    $("#cf-verif-math").innerHTML = `<span class="mlabel">The scores</span>CRPS(<var>F</var>, <var>y</var>) = &int; (<var>F</var>(<var>x</var>) &minus; 1{<var>y</var> &le; <var>x</var>})<sup>2</sup> <var>dx</var>; for a mixture &Sigma;<var>w</var><sub>i</sub>N(&mu;<sub>i</sub>, &sigma;<sub>i</sub><sup>2</sup>): &Sigma;<sub>i</sub><var>w</var><sub>i</sub>A(<var>y</var> &minus; &mu;<sub>i</sub>, &sigma;<sub>i</sub><sup>2</sup>) &minus; &frac12;&Sigma;<sub>i,j</sub><var>w</var><sub>i</sub><var>w</var><sub>j</sub>A(&mu;<sub>i</sub> &minus; &mu;<sub>j</sub>, &sigma;<sub>i</sub><sup>2</sup> + &sigma;<sub>j</sub><sup>2</sup>), A(&mu;, &sigma;<sup>2</sup>) = 2&sigma;&phi;(&mu;/&sigma;) + &mu;(2&Phi;(&mu;/&sigma;) &minus; 1) (Grimit et al. 2006). PIT <var>u</var><sub>t</sub> = <var>F</var><sub>t</sub>(<var>y</var><sub>t</sub>) ~ U(0, 1) if calibrated. Brier = reliability &minus; resolution + uncertainty (Murphy 1973).`;
    // trials
    const metricTxt = (t) => {
      if (fin(t.log_t)) return [`log score / CRPS / tail (FZ0 at 1%)`, `t ${rsT(t.log_t)} / ${rsT(t.crps_t)} / ${rsT(t.fz0_t_01)}`];
      if (fin(t.utility_t)) return ["CRRA utility, raw / gated", `t ${rsT(t.utility_t)} / ${rsT(t.gated_utility_t)}`];
      const pctm = /skill|Brier|certainty/i.test(t.metric || "");
      return [t.metric || "", `${pctm ? sPct(t.before, 1) : rsF(t.before)} \u2192 ${pctm ? sPct(t.after, 1) : rsF(t.after)}${fin(t.t) ? `, t ${rsT(t.t)}` : ""}`];
    };
    const trs = TR.slice().sort((a, b) => (b.adopted ? 1 : 0) - (a.adopted ? 1 : 0));
    fillTable($("#cf-trials"), ["Upgrade", "From", "Measured by", "Result", "Verdict", "Why"], trs.map((t) => { const m = metricTxt(t); return [t.name, t.field, m[0], m[1], h("span", "rs-v rs-v-" + (t.adopted ? "supported" : "no-evidence"), t.adopted ? "adopted" : "not adopted"), t.why || ""]; }), 2);
    const ad = TR.filter((t) => t.adopted);
    $("#cf-trials-p").textContent = `${TR.length} upgrades were tried, each against a rule written before its result: a forecast upgrade must beat the old one out of sample (Diebold-Mariano t above 1.5 to 2) without worsening calibration; a sizing upgrade must raise both Sharpe and a cautious investor's utility with 90% ranges that exclude zero. ${ad.length} passed: ${ad.map((t) => t.name).join("; ")}. None of the borrowed upgrades to the decision core's predictive passed cleanly, so the core keeps it as is. Every sizing variant counts among the strategies the evidence gate discounts, which raised the bar the engine's own record must clear to t\u2080 ${(() => { try { return fx(DX19.now.gate.t0, 2); } catch (e) { return "n/a"; } })()}.`;
    // tail
    const T = C.tail || {}, res = T.methods || {};
    const name = { normal: "Normal", historical: "Historical", pot: "Peaks over threshold (GPD)", filtered_pot: "GPD on volatility-filtered losses", engine: "The engine's mixture" };
    const cell = (m, p) => { const x = (res[m] || {})[p]; return x ? `${pct(x.kupiec.rate, 1, false)} (Kupiec ${fx(x.kupiec.p, 2)}, Z2 ${fx(x.z2.p, 2)}, independence ${fx(x.christoffersen.p_ind, 2)})` : "n/a"; };
    fillTable($("#cf-tail"), ["Estimator", "Breaches at 5% (tests' p)", "Breaches at 1% (tests' p)"], Object.keys(res).map((m) => [name[m] || m, cell(m, "0.05"), cell(m, "0.01")]), 1);
    $("#cf-tail-p").textContent = `Each month since 1940, every estimator predicted the 5% and 1% value at risk and expected shortfall from the data known two months earlier. At 5% the engine's mixture is calibrated in frequency and size. At 1% it is breached 1.7% of the time against 1% and by more than it predicts; only the peaks-over-threshold model passes all three tests there. Paired by the joint VaR-ES score, no estimator beats the engine with t above 2.`;
    fillTable($("#cf-budget"), ["Estimator", "5% ES now", "Most exposure the 12% budget allows"], ["engine", "pot", "filtered_pot"].filter((m) => res[m] && res[m]["0.05"]).map((m) => [name[m], pct(res[m]["0.05"].es_last, 1, false), fx(res[m]["0.05"].max_exposure_now, 2) + "x"]), 1);
    fillTable($("#cf-ruin"), ["Exposure", "Bootstrap, from a peak (95% interval)", "Lundberg bound, from the start"], Object.entries(RU).map(([k, v]) => [fx(Number(k), 2) + "x", `${pct(v.bootstrap_dd50_10y.p, 1, false)} (${pct(v.bootstrap_dd50_10y.lo, 1, false)} to ${pct(v.bootstrap_dd50_10y.hi, 1, false)})`, pct(v.cramer_lundberg.lundberg_bound, 1, false)]), 1);
    $("#cf-tail-math").innerHTML = `<span class="mlabel">The actuarial formulas</span>Excesses over <var>u</var> ~ GPD(&xi;, &beta;): VaR<sub><var>p</var></sub> = <var>u</var> + &beta;/&xi; [(<var>n p</var>/<var>n</var><sub><var>u</var></sub>)<sup>&minus;&xi;</sup> &minus; 1], ES<sub><var>p</var></sub> = VaR<sub><var>p</var></sub>/(1 &minus; &xi;) + (&beta; &minus; &xi;<var>u</var>)/(1 &minus; &xi;) (McNeil, Frey and Embrechts). Kupiec: LR = &minus;2 log[(1 &minus; <var>p</var>)<sup><var>n</var>&minus;<var>x</var></sup><var>p</var><sup><var>x</var></sup>] + 2 log[(1 &minus; <var>x</var>/<var>n</var>)<sup><var>n</var>&minus;<var>x</var></sup>(<var>x</var>/<var>n</var>)<sup><var>x</var></sup>] ~ &chi;<sup>2</sup><sub>1</sub>. Lundberg: P(ruin) &le; e<sup>&minus;R<var>u</var></sup>, R = 2&mu;/&sigma;<sup>2</sup> for a Brownian surplus. Buhlmann: Z = <var>n</var>/(<var>n</var> + <var>k</var>), <var>k</var> = EPV/VHM; estimated <var>k</var> &asymp; 4 months against the engine's 120.`;
    // method cards
    const CS = { f: "all" };
    const fields = [...new Set(M.map((m) => m.field || m.domain))];
    const drawCards = () => {
      const box = $("#cf-cards"); box.replaceChildren();
      M.filter((m) => CS.f === "all" || (m.field || m.domain) === CS.f).forEach((m) => {
        const art = h("article", "mt-card");
        const top = h("div", "mt-top"); top.append(h("span", "mt-field", m.field || m.domain), h("h3", null, m.method));
        art.append(top, h("p", null, m["what it does in its home field"] || m.what || ""));
        if (m.formula && m.formula !== "n/a") { const f = h("div", "math"); f.innerHTML = `<span class="mlabel">Formula</span>`; f.append(document.createTextNode(m.formula)); art.append(f); }
        const dl = h("dl", "mt-dl");
        [["Market analog", m["market analog"]], ["How the engine could use it", m["how the engine could use it"]], ["Test that would show it helps", m["test that would show it helps"]]].forEach(([k, v]) => { if (v) { dl.append(h("dt", null, k), h("dd", null, v)); } });
        art.append(dl);
        if (m.source_url) { const a = h("a", "src", m.source_title || "Source"); a.href = m.source_url; a.target = "_blank"; a.rel = "noopener"; art.append(a); }
        box.append(art);
      });
    };
    const fb = $("#cf-cards-filter"); fb.replaceChildren();
    const seg = h("div", "seg");
    [["all", `All (${M.length})`], ...fields.map((f) => [f, `${f} (${M.filter((m) => (m.field || m.domain) === f).length})`])].forEach(([k, n]) => {
      const b = h("button", null, n); b.type = "button"; b.setAttribute("aria-pressed", CS.f === k ? "true" : "false");
      b.addEventListener("click", () => { CS.f = k; seg.querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", x === b ? "true" : "false")); drawCards(); });
      seg.append(b);
    });
    fb.append(seg); drawCards();
  }

  /* ---------- the methods registry: every method, its formula with today's numbers, its origin and its test ---------- */
  function mtNow() {
    const D = typeof DX19 !== "undefined" ? DX19 : null, N = D && D.now;
    return { D, N, G: N && N.gate, R: N && N.regime };
  }
  const MT_METHODS = [
    { f: "Statistics", n: "Hidden Markov regimes", o: "Baum and Welch (1970); Hamilton (1989) for markets; speech recognition", where: "infer.py, decide.py",
      m: "<var>s</var><sub>t</sub> ~ Markov(<var>A</var>), <var>r</var><sub>t</sub> | <var>s</var><sub>t</sub> = <var>k</var> ~ N(&mu;<sub>k</sub>, &sigma;<sub>k</sub><sup>2</sup>); fit by expectation-maximization; filter &alpha;<sub>t</sub> &prop; (&alpha;<sub>t&minus;1</sub><var>A</var>) &odot; <var>p</var>(<var>r</var><sub>t</sub> | <var>s</var>)",
      now: (X) => X.R ? `today: ${X.R.K} states, stressed next month ${pct0(X.R.next[X.R.worst])}` : "", ev: "Carries 87% of the model-averaging weight by its log-score record; its stress odds swing, so it enters only through the mixture and the gate." },
    { f: "Statistics", n: "Bayesian online changepoint detection", o: "Adams and MacKay (2007)", where: "infer.py",
      m: "P(<var>r</var><sub>t</sub> = <var>r</var>&prime; | data) by the run-length recursion with hazard 1/120", now: (X) => X.N ? `today: changepoint odds ${pct0(X.N.changepoint.recent)}, expected run ${fx(X.N.changepoint.expected_run, 0)} months` : "", ev: "Alarms in 1929, 1987, 2008 and 2020; almost no weight in the mixture because its log score is weaker." },
    { f: "Weather forecasting", n: "Dynamic model averaging by log score", o: "Raftery, Karny and Ettler (2010); ensemble forecasting", where: "decide.py",
      m: "<var>w</var><sub>m,t</sub> &prop; exp(&Sigma;<sub>&tau; &le; t&minus;2</sub> 0.98<sup>t&minus;2&minus;&tau;</sup> log <var>p</var><sub>m</sub>(<var>r</var><sub>&tau;</sub>))",
      now: (X) => X.N ? "today: " + Object.entries(X.N.models.weights).map(([k, v]) => `${k} ${fx(v, 2)}`).join(", ") : "", ev: "BMA by EM was tried in its place in v0.25 and did not beat it out of sample (log score t −0.79)." },
    { f: "Machine learning", n: "Stacked forecasts", o: "Wolpert (1992); Breiman (1996)", where: "decide.py, ml.py",
      m: "<var>v</var> = argmin &Sigma; (<var>y</var> &minus; &Sigma;<sub>j</sub> <var>v</var><sub>j</sub><var>f</var><sub>j</sub>)<sup>2</sup>, <var>v</var> &ge; 0, &Sigma;<var>v</var> = 1, on forecasts whose outcomes were known",
      now: (X) => X.N && X.N.forecasts ? `today: stacked 12-month forecast ${sPct(X.N.forecasts.stacked, 1)}` : "", ev: "The restricted combination is the only forecaster with positive skill (+2.7%, t 1.5); the stack leans on it. In the ML lab, v0.25 floors each member at zero and shrinks the average toward the mean with a walked-forward weight: skill -6.0% to +4.0% (t 1.66, best of 11)." },
    { f: "Decision theory", n: "CRRA expected utility with a loss budget", o: "Arrow (1965), Pratt (1964); expected shortfall, Acerbi and Tasche (2002)", where: "decide.py",
      m: "<var>x</var>* = argmax E[(<var>v</var><sup>1&minus;&gamma;</sup> &minus; 1)/(1 &minus; &gamma;)] s.t. <var>x</var>&middot;ES<sub>5%</sub> &le; 12%",
      now: (X) => X.N ? `today: &gamma; ${fx(X.N.gamma, 2)}, ES at 1x ${pct(X.N.es_1x, 2, false)}, optimum ${fx(X.N.engine_exposure, 2)}x` : "", ev: "The 5% ES of the mixture is calibrated since 1940 (Kupiec p 0.68)." },
    { f: "Statistics", n: "The evidence gate (multiple-testing discount)", o: "Bailey and Lopez de Prado (2014); Harvey and Liu (2015)", where: "decide.py",
      m: "<var>g</var> = max(0, 2&Phi;(<var>t</var> &minus; <var>t</var><sub>0</sub>) &minus; 1), <var>t</var><sub>0</sub> = &Phi;<sup>&minus;1</sup>(1 &minus; 1/<var>n</var>)",
      now: (X) => X.G ? `today: t ${fx(X.G.t, 2)} against t<sub>0</sub> ${fx(X.G.t0, 2)} (n = ${X.G.n_tried}), g = ${fx(X.G.value, 2)}` : "", ev: "Keeps the book at 1.00x while the engine's record is inconclusive." },
    { f: "Control engineering", n: "Kalman filter", o: "Kalman (1960); navigation and guidance", where: "infer.py",
      m: "&beta;<sub>t</sub> = &beta;<sub>t&minus;1</sub> + &eta;<sub>t</sub>; <var>K</var><sub>t</sub> = <var>P</var><sub>t|t&minus;1</sub><var>x</var><sub>t</sub>/(<var>x</var><sub>t</sub><sup>2</sup><var>P</var><sub>t|t&minus;1</sub> + <var>R</var>); &beta;<sub>t|t</sub> = &beta;<sub>t|t&minus;1</sub> + <var>K</var><sub>t</sub>(<var>r</var><sub>t</sub> &minus; <var>x</var><sub>t</sub>&beta;<sub>t|t&minus;1</sub>)",
      now: (X) => X.D && X.D.kalman ? `latest stock-yield beta ${pct(X.D.kalman.now, 1)} per point` : "", ev: "The band includes zero today: the record cannot say whether bonds hedge stocks unconditionally." },
    { f: "Statistics", n: "Thompson sampling hedge selector", o: "Thompson (1933)", where: "decide.py",
      m: "P(<var>h</var> best | context) by draws from discounted outcome posteriors (forgetting 0.995)", now: (X) => X.N ? `today: ${X.N.hedge.names.map((n, i) => `${fx(X.N.hedge.p_best[i], 2)}`).join(" / ")} for all stocks / Treasuries / cash` : "", ev: "Chooses all stocks in a calm regime with the trend on." },
    { f: "Machine learning", n: "Fitted Q iteration (reinforcement learning)", o: "Ernst, Geurts and Wehenkel (2005)", where: "rl.py, decide.py",
      m: "<var>Q</var><sub>k+1</sub>(<var>s</var>, <var>a</var>) &larr; <var>r</var> + &gamma; max<sub><var>a</var>&prime;</sub> <var>Q</var><sub>k</sub>(<var>s</var>&prime;, <var>a</var>&prime;), with a penalty toward holding", now: () => "", ev: "v0.25 pools the states (trend by drawdown): Sharpe 0.74 against 0.64 for holding, 90% range of the gain +0.02 to +0.17, but a cautious investor's utility is slightly below holding's, so it stays in the learning lab and does not size the book." },
    { f: "Statistics", n: "Conformal prediction intervals", o: "Vovk, Gammerman and Shafer (2005)", where: "ml.py",
      m: "interval = <var>f</var> &plusmn; <var>q</var><sub>0.8</sub>(|<var>y</var> &minus; <var>f</var>| on the last 360 known errors)", now: () => "", ev: "Past 80% intervals covered 81% of years." },
    { f: "Statistics", n: "Diebold-Mariano test", o: "Diebold and Mariano (1995)", where: "ml.py, crossfield.py",
      m: "<var>t</var> = <span style='text-decoration:overline'><var>d</var></span> / &radic;(LRV(<var>d</var>)/<var>n</var>), <var>d</var> = loss<sub>model</sub> &minus; loss<sub>benchmark</sub>", now: () => "", ev: "The test every forecaster and every v0.25 upgrade had to pass." },
    { f: "Statistics", n: "Benjamini-Hochberg false discovery rate", o: "Benjamini and Hochberg (1995)", where: "labs.py, reason.py",
      m: "reject <var>H</var><sub>(k)</sub> for <var>k</var> &le; max{<var>k</var>: <var>p</var><sub>(k)</sub> &le; <var>k q</var>/<var>m</var>}", now: () => "", ev: "Applied across 34 chart signals, 43 legendary and 6 textbook rules, and the induced rules." },
    { f: "Statistics", n: "Stationary bootstrap", o: "Politis and Romano (1994)", where: "labs.py", m: "resample blocks of geometric length (mean 12 months) to keep serial dependence", now: () => "", ev: "Every 90% range on the site." },
    { f: "Weather forecasting", n: "Forecast verification: CRPS, PIT, coverage", o: "Matheson and Winkler (1976); Dawid (1984); Gneiting and Raftery (2007)", where: "crossfield.py",
      m: "CRPS = &int;(<var>F</var> &minus; 1{<var>y</var> &le; <var>x</var>})<sup>2</sup><var>dx</var>; PIT <var>u</var> = <var>F</var>(<var>y</var>)", now: () => (R25() && R25().crossfield ? `since 1950: CRPS ${fx(R25().crossfield.variants.as_is.crps, 4)}, 90% coverage ${pct(R25().crossfield.variants.as_is.coverage90.coverage, 1, false)}` : ""), ev: "The forecast is calibrated except in the far tail." },
    { f: "Weather forecasting", n: "EMOS recalibration", o: "Gneiting, Raftery, Westveld and Goldman (2005)", where: "crossfield.py", m: "<var>Y</var> ~ N(<var>a</var> + <var>b</var>&mu;, <var>c</var> + <var>d</var>&sigma;<sup>2</sup>), fit by minimum CRPS on past outcomes", now: () => "", ev: "Tried on the decision core; it narrowed the forecast and worsened the tail. Not adopted." },
    { f: "Actuarial science", n: "Peaks over threshold (generalized Pareto)", o: "Pickands (1975); Balkema and de Haan (1974); McNeil and Frey (2000)", where: "crossfield.py",
      m: "<var>P</var>(<var>X</var> &minus; <var>u</var> &gt; <var>y</var> | <var>X</var> &gt; <var>u</var>) = (1 + &xi;<var>y</var>/&beta;)<sup>&minus;1/&xi;</sup>", now: () => "today: tail shape &xi; about 0.15 to 0.24; 5% ES 9.2%", ev: "The only estimator calibrated at 1% since 1940; as a floor on the loss budget it cut exposure without raising utility, so it stays a cross-check." },
    { f: "Actuarial science", n: "Buhlmann credibility", o: "Buhlmann (1967); Buhlmann and Straub (1970)", where: "crossfield.py, decide.py", m: "&mu;&#770; = <var>Z</var>&#563;<sub>group</sub> + (1 &minus; <var>Z</var>)&mu;<sub>pool</sub>, <var>Z</var> = <var>n</var>/(<var>n</var> + <var>k</var>), <var>k</var> = EPV/VHM", now: () => "estimated k about 4 months; the engine keeps 120", ev: "The estimate is biased toward too little shrinkage when states are fit to the same data; the hand-set 120 wins out of sample (log score t 2.09)." },
    { f: "Actuarial science", n: "Ruin probability", o: "Lundberg (1903); Cramer (1930s)", where: "crossfield.py", m: "P(ruin) &le; e<sup>&minus;R<var>u</var></sup>, R = 2&mu;/&sigma;<sup>2</sup>; bootstrap of 10-year paths", now: () => "a 50% fall from a peak within 10 years: 12.2% at 1x, 40.7% at 1.5x", ev: "At 1.5x the chance of halving within a decade is about 41%: the gross cap is already aggressive, and the loss budget is a hard limit, not a trade-off." },
    { f: "Taleb", n: "Kappa and the equivalent sample", o: "Taleb (2019), arXiv 1802.05495", where: "reality desk", m: "&kappa;(<var>n</var><sub>0</sub>, <var>n</var>) = 2 &minus; (log <var>n</var> &minus; log <var>n</var><sub>0</sub>)/log(<var>M</var>(<var>n</var>)/<var>M</var>(<var>n</var><sub>0</sub>))", now: () => "monthly stocks: &kappa; 0.13; 30 normal months of information take about 39", ev: "Why the engine's record needs decades before the gate opens." },
    { f: "Taleb", n: "Fragility heuristic", o: "Taleb, Canetti et al. (IMF 2012)", where: "concepts", m: "<var>H</var> = [<var>f</var>(<var>x</var> + &Delta;) + <var>f</var>(<var>x</var> &minus; &Delta;)]/2 &minus; <var>f</var>(<var>x</var>); <var>H</var> &lt; 0 is fragile", now: () => "", ev: "A concave payoff loses more from a shock than it gains from the opposite one; the loss budget is the engine's answer." },
    { f: "Physics", n: "Random matrix theory", o: "Marchenko and Pastur (1967)", where: "geometry.py", m: "&lambda;<sub>&plusmn;</sub> = &sigma;<sup>2</sup>(1 &plusmn; &radic;(<var>N</var>/<var>T</var>))<sup>2</sup>", now: () => "2 eigenvalues above the noise edge across 27 world markets", ev: "Two real factors: the dollar, then oil and rates." },
    { f: "Geometry", n: "Affine-invariant distance between covariance matrices", o: "Pennec, Fillard and Ayache (2006); Forstner", where: "geometry.py", m: "<var>d</var>(<var>A</var>, <var>B</var>) = &#8214;log(<var>A</var><sup>&minus;&frac12;</sup><var>B A</var><sup>&minus;&frac12;</sup>)&#8214;<sub>F</sub>", now: () => "", ev: "Analogs beat the mean through fatter tails, not resemblance (the placebo shows it)." },
    { f: "Logic", n: "Forward-chaining deduction with proofs", o: "Horn (1951); Datalog semi-naive evaluation", where: "reason.py", m: "repeat: derive every <var>head</var> whose <var>body</var> holds in the known facts, keeping the proof, until no new fact", now: () => (R25() && R25().reason ? `${R25().reason.deduce.derived} facts derived, 0 contradictions` : ""), ev: "The decision itself is derived as a proof with its flip points." },
    { f: "Logic", n: "Rule induction, walked forward", o: "Inductive logic programming; Holte (1993); Benjamini and Hochberg", where: "reason.py", m: "find rules on data to 1960, test on 1961 onward with Newey-West <var>t</var> and BH", now: () => (R25() && R25().reason ? `${R25().reason.discover.survivors.length} of ${R25().reason.discover.tested} survived` : ""), ev: "Little survives; what does is reported with its out-of-sample effect." },
    { f: "Logic", n: "Abduction (inference to the best explanation)", o: "Peirce (1903)", where: "reason.py", m: "rank <var>h</var> by P(<var>h</var> | obs) &minus; P(<var>h</var>), with LR = P(obs | <var>h</var>)/P(obs | not <var>h</var>)", now: () => "", ev: "Retrospective only; never fed to the size." },
  ];
  function renderMethods() {
    const tiles = $("#mt-tiles");
    if (!tiles) return;
    const X = mtNow(), fields = [...new Set(MT_METHODS.map((m) => m.f))];
    rsKpi(tiles, [[String(MT_METHODS.length), "Methods in the engine", "each with its formula and its test"], [String(fields.length), "Fields they come from", fields.slice(0, 4).join(", ") + "..."],
      [R25() ? String((R25().trials || []).length) : "n/a", "Upgrades tried in v0.25", R25() ? `${(R25().trials || []).filter((t) => t.adopted).length} adopted (in the ML and learning labs); none of the borrowed upgrades to the decision core` : ""], ["On", "The math", "shown by default; the Σ button hides it"]]);
    const st = { f: "all" };
    const draw = () => {
      const box = $("#mt-list"); box.replaceChildren();
      MT_METHODS.filter((m) => st.f === "all" || m.f === st.f).forEach((m) => {
        const art = h("article", "mt-card");
        const top = h("div", "mt-top"); top.append(h("span", "mt-field", m.f), h("h3", null, m.n));
        art.append(top, h("p", "mt-o", m.o));
        const f = h("div", "math"); let now = ""; try { now = m.now(X) || ""; } catch (e) { now = ""; }
        f.innerHTML = `<span class="mlabel">${m.where}</span>${m.m}${now ? `<br><span class="mt-now">${now}</span>` : ""}`;
        art.append(f, h("p", "mt-ev", m.ev));
        box.append(art);
      });
    };
    const fb = $("#mt-filter"); fb.replaceChildren();
    const seg = h("div", "seg");
    [["all", `All (${MT_METHODS.length})`], ...fields.map((x) => [x, `${x} (${MT_METHODS.filter((m) => m.f === x).length})`])].forEach(([k, n]) => {
      const b = h("button", null, n); b.type = "button"; b.setAttribute("aria-pressed", st.f === k ? "true" : "false");
      b.addEventListener("click", () => { st.f = k; seg.querySelectorAll("button").forEach((y) => y.setAttribute("aria-pressed", y === b ? "true" : "false")); draw(); });
      seg.append(b);
    });
    fb.append(seg); draw();
  }

  /* =====================================================================================
     v0.26: THE EDGE LAB. A hypothesis factory over ordinary and unusual data across world markets, and the
     gauntlet that kills most of its ideas. Reads SNAP26 (scripts/snapshot_v26.py); nothing is recomputed here.
     After the independent audit: p-values calibrated on nulls for every rule kind (fake markets and fake signals),
     composites must beat their parents, an edge counts as tested only when most of its markets trade in the test,
     and the out-of-sample case is the early-split replication (chosen with data through 2010, tested 2011 to 2017).
     ===================================================================================== */
  const E26 = () => (typeof SNAP26 !== "undefined" && SNAP26 && SNAP26.discovery) || null;
  const e26N = (v) => (fin(v) ? v.toLocaleString("en-US") : "n/a");
  const e26S = (v, d = 2) => (fin(v) ? (v >= 0 ? "" : "−") + fx(Math.abs(v), d) : "n/a");
  const e26T = (v) => (fin(v) ? (v >= 0 ? "+" : "−") + fx(Math.abs(v), 1) : "n/a");
  const e26Pct = (v, d = 1) => (fin(v) ? (v < 0 ? "−" : "") + pct(Math.abs(v), d, false) : "n/a");
  const e26Share = (v) => (!fin(v) ? "n/a" : v === 0 ? "0%" : v >= 0.1 ? (100 * v).toFixed(1) + "%" : Number((100 * v).toPrecision(2)).toString() + "%");
  const e26Luck = (s, nullN, realN) => {                        // expected false count, or the 95% bound when the null had none
    if (!s) return "n/a";
    if (s.placebo === 0 && fin(nullN) && nullN > 0) return `under ${fx(3 / nullN * realN, 1)}`;
    return fin(s.expected_false_real) ? (s.expected_false_real < 10 ? fx(s.expected_false_real, 1) : e26N(Math.round(s.expected_false_real))) : "n/a";
  };
  const e26Tested = (e) => !!(e && e.test && e.test.tested);
  const e26Partial = (e) => !!(e && e.test && e.test.net && (e.test.net.n || 0) >= 12 && !e.test.tested);

  function renderEdges() {
    const O = E26(), tiles = $("#ed2-tiles");
    if (!tiles) return;
    if (!O) { tiles.replaceChildren(h("p", "empty", "The edge lab's run is not in this build.")); return; }
    const F = O.funnel, by = Object.fromEntries(F.map((s) => [s.key, s])), U = O.universe, PL = O.placebo, NL = PL.null || {}, CAL = PL.calibration || {};
    const EA = O.early || null, EF = EA ? Object.fromEntries(EA.funnel.map((s) => [s.key, s])) : {}, EB = EA && EA.book && EA.book.test, ENL = EA ? (EA.placebo.null || {}) : {};
    const nullN = NL.hypotheses || by.tried.placebo;
    rsKpi(tiles, [[e26N(U.hypotheses), "Candidate edges invented", `${e26N(U.market_level_tests)} market-level tests over ${U.targets} markets; ${e26N(nullN)} fake-market hypotheses run beside them`],
      [`${by.distinct.real} vs ${e26Luck(by.distinct, nullN, by.tried.real)}`, "Distinct survivors against luck", `the fake markets produced ${by.distinct.placebo}; p-values calibrated on them`],
      EA ? [`${EF.test_positive.real} of ${EF.test_data.real}`, "Made money in the replay's test", `chosen with data through ${EA.calendar.validation_to}, tested ${EA.calendar.test} (the main search's validation years); ${EF.test_t2.real} with t of 2 or more`] : ["n/a", "Out-of-sample test", "no early-split run"],
      EB ? [e26S(EB.sharpe), "Replay book Sharpe, held-out years", `after costs, t ${e26S(EB.t, 1)}; about ${fx((EA.book.test_concentration || {}).independent_bets_test, 1)} independent bets on spot research prices`] : ["n/a", "Out-of-sample book", "no tested edges"]]);
    // 1. the funnel
    const lo = CAL.own || {}, ls = CAL.signal || {};
    $("#ed2-funnel-p").textContent = `Every stage runs identically on the real candidates and on two kinds of fake with no edge by construction: the whole rule library on ${NL.replicates || 3} copies of the markets with their returns shuffled in time (in two-month blocks, within each period, the same shuffle for every market, so they keep their volatility, fat tails and co-movement), and ${e26N(PL.signals)} fake signals. The fakes showed that the textbook p-values were too small: at the 0.1% tail their |t| was ${e26S(lo.q_abs_t)} for rules on a market's own data and ${e26S(ls.q_abs_t)} for rules on a common signal, not 3.29. So every p-value is calibrated first, and because one calibration point cannot fit every tail, the cut is also held where the fake markets' own false share is at most 5% (at the plain BH cut it was ${e26Pct(PL.null_fdr_at_bh_cut, 0)}; at the cut used, ${e26Pct(PL.null_fdr_at_cut, 0)}). Together they move the cut from ${fx(PL.bh_p_threshold_uncalibrated, 5)} to ${O.bh_p_threshold.toExponential(1)}. Composites must also add timing beyond the two rules they are built from, and an edge counts as tested only if most of its markets trade in the test years.`;
    fillTable($("#ed2-funnel"), ["Stage", "Real", "Share of real", "Fake markets", "Share of fake markets", "Real count expected by luck", "Fake signals"],
      F.map((s) => [s.stage, e26N(s.real), e26Share(s.real_rate), e26N(s.placebo), e26Share(s.placebo_rate), e26Luck(s, nullN, by.tried.real), fin(s.placebo_signals) ? e26N(s.placebo_signals) : "n/a"]), 1);
    $("#ed2-funnel-math").innerHTML = `<span class="mlabel">The gauntlet</span>edge statistic: <var>s</var><sub>t</sub> = mean<sub><var>i</var>&isin;family</sub> <var>w</var><sub><var>i</var>,<var>t</var>&minus;2</sub> &middot; <var>r</var><sub><var>i</var>,<var>t</var></sub>/&sigma;&#770;<sub><var>i</var>,<var>t</var>&minus;2</sub>, with a Newey-West <var>t</var>; calibration: &lambda; = (<var>q</var><sub>fake</sub>(|<var>t</var>|, 99.9%) / 3.29)<sup>2</sup> = ${e26S(lo.lambda)} (own data) and ${e26S(ls.lambda)} (common signals), <var>p</var> = 2&Phi;(&minus;|<var>t</var>|/&radic;&lambda;); BH: reject <var>p</var><sub>(<var>k</var>)</sub> &le; <var>k</var>&middot;${O.fdr_q}/<var>m</var>, and the largest cut <var>c</var> with <var>m</var>&middot;share<sub>fake</sub>(<var>p</var> &le; <var>c</var>) &le; 0.05&middot;#{real <var>p</var> &le; <var>c</var>}; here <var>p</var> &le; ${O.bh_p_threshold.toExponential(1)} over <var>m</var> = ${e26N(PL.valid_hypotheses || U.hypotheses)} hypotheses with enough data; timing: &alpha; in <var>s</var><sub>t</sub> = &alpha; + &beta;&middot;<var>drift</var><sub>t</sub> (+ &gamma;&middot;<var>parents</var><sub>t</sub> for composites) + &epsilon;, <var>t</var><sub>&alpha;</sub> &ge; 1.96; with no fake survivor in <var>n</var> fake tries the 95% bound on the false-pass rate is 3/<var>n</var>.`;
    // 1b. what the audit changed
    const PA = (typeof SNAP26 !== "undefined" && SNAP26.preaudit) || null;
    if (PA) {
      $("#ed2-audit-p").textContent = "Before publishing, an independent auditor reran the engine and tried to break it. It found no look-ahead in the code's timing, but one look-ahead in the data and four other faults in the evidence. The data look-ahead: Shiller interpolates the early long rate and dividends from annual values, which inflated the long US block. The other four: the test years did not test most edges (their markets had stopped trading); the fake signals gave no test of chance for own-history rules or composites; the p-values were too optimistic; and one oil-shock month carried the book. Each was fixed in the engine, not in the wording. A second pass then found the calibrated cut still too loose where it is used, and the replay's test years overlapping the main search's validation years. Both are now handled or stated. The headline shrank.";
      const ac = (EA && EA.edges) || [];
      fillTable($("#ed2-audit"), ["Measure", "Before the audit", "After"], [
        ["Cut on p (Benjamini-Hochberg, then the fake-market false share)", fx(PA.bh_cut, 5), O.bh_p_threshold.toExponential(1)],
        ["Passed BH", e26N(PA.bh), e26N(by.bh.real)],
        ["Distinct survivors (main calendar)", e26N(PA.distinct), e26N(by.distinct.real)],
        ["Expected by luck among them", fin(PA.null_distinct_expected) ? fx(PA.null_distinct_expected, 1) + " (fake signals only)" : "n/a", e26Luck(by.distinct, nullN, by.tried.real) + " (every rule kind)"],
        ["Composite survivors", e26N(PA.composite_edges), e26N(O.edges.filter((e) => e.kind === "compositions").length)],
        ["Long US block survivors", e26N(PA.long_edges), e26N(O.edges.filter((e) => e.block === "long").length)],
        ["Edges counted as tested after 2017", e26N(PA.test_data), e26N(by.test_data.real)],
        ["Main-calendar book Sharpe after 2017", PA.book_sharpe != null ? `${e26S(PA.book_sharpe)} (t ${e26S(PA.book_t, 1)}, volatility ${e26Pct(PA.book_vol, 0)})` : "n/a", O.book.test ? e26S(O.book.test.sharpe) : "no tested edges"],
        ["Early-split survivors, tested 2011 to 2017", e26N(PA.early_distinct), e26N(ac.length)],
        ["Early-split book Sharpe", e26S(PA.early_book_sharpe), EB ? `${e26S(EB.sharpe)} (volatility ${e26Pct(EB.vol_annual, 0)})` : "n/a"],
        ["False share at the BH stage, measured on fake markets", "not measured", e26Pct(PL.null_fdr_at_cut, 0)]], 1);
    }
    // 2. the ledger
    const tested = ((EA && EA.edges) || []).map((e) => ({ ...e, _cal: "early" })).concat(O.edges.filter(e26Tested));
    const main = O.edges.filter((e) => !e26Tested(e));
    $("#ed2-edges-p").textContent = `${tested.length} edges were tested on years their own search did not use: ${EA ? `the ${EA.edges.length} survivors of the search replayed with data through ${EA.calendar.validation_to}, tested ${EA.calendar.test}` : "none"}. Then the ${main.length} survivors of the main search (data through 2009, validated 2010 to 2017), which cannot be tested after 2017 because their IMF markets stop in June 2017; ${main.filter(e26Partial).length} can be followed on the few markets still trading, as partial evidence only. "Faded" means the edge trades against the signal; "followed" means with it.`;
    const box = $("#ed2-edges"); box.replaceChildren();
    const ST = { all: false };
    const card = (e) => {
      const art = h("article", "mt-card");
      const top = h("div", "mt-top");
      top.append(h("span", "mt-field", `${e._cal === "early" ? "tested 2011 to 2017" : e26Tested(e) ? "tested" : e26Partial(e) ? "partial evidence" : "not testable"} · ${e.group} · ${e.kind}`), h("h3", null, e.name));
      art.append(top);
      const T = e.test && e.test.net, D = e.discovery, V = e.validation && e.validation.net;
      const f = h("div", "math");
      const tline = T && fin(T.t)
        ? `${e26Tested(e) ? "<b>" : ""}test ${e.test.period}: Sharpe ${e26S(T.sharpe)}, <var>t</var> ${e26T(T.t)}, ${T.n} months on ${e.test.markets_with_test_data} of ${e.group_markets} markets${e26Tested(e) ? "</b>" : " (partial: not counted)"}`
        : "no test-period data";
      f.innerHTML = `<span class="mlabel">The record</span>discovery (${D.period}): Sharpe ${e26S(D.sharpe)}, <var>t</var> ${e26T(Math.abs(D.t))}; validation ${e.validation ? e.validation.period : ""}: Sharpe ${e26S(V && V.sharpe)} after costs; ${tline}; breadth ${e.breadth.agree} of ${e.breadth.n} ${e.breadth.units || "markets"} agree`
        + (fin(e.sharpe_kept) ? `; the test kept ${pct(e.sharpe_kept, 0, false)} of the discovery Sharpe.` : ".");
      art.append(f);
      const dl = h("dl", "mt-dl");
      const mech = e.mechanism || {};
      dl.append(h("dt", null, "Mechanism"), h("dd", null, `${(mech.concepts || []).map((c) => c.name).join(", ") || "no known mechanism"}. ${mech.status ? mech.status.charAt(0).toUpperCase() + mech.status.slice(1) + "." : ""}`));
      if (e.eom) dl.append(h("dt", null, "The averaging trap"), h("dd", null, e.eom.status + (fin(e.eom.t_after_discovery) ? ` (end-of-month closes after discovery: t ${e26T(e.eom.t_after_discovery)})` : "")));
      if (e.costs) dl.append(h("dt", null, "Costs"), h("dd", null, `about ${fx(e.costs.round_trip_bp_mean, 0)} bp a round trip, a median ${pct(e.costs.turnover_share_per_month, 0, false)} of the position turned over a month: ${pct(e.costs.cost_annual_at_10pct_vol, 1, false)} a year at 10% volatility`));
      if (e.today && e.today.positions && e.today.positions.length) dl.append(h("dt", null, `Signal for ${e.today.as_of} (data through ${e.today.data_through || "the last month"}; research only)`), h("dd", null, e.today.positions.map((p) => `${p.side} ${p.name}`).join(", ")));
      if (e.test && e.test.note) dl.append(h("dt", null, "Test"), h("dd", null, e.test.note));
      if (e.caveats && e.caveats.length) dl.append(h("dt", null, "Caveats"), h("dd", null, e.caveats.join(" ")));
      art.append(dl);
      return art;
    };
    const ordered = tested.slice().sort((a, b) => (b.test.net.t || 0) - (a.test.net.t || 0)).concat(main.slice().sort((a, b) => (e26Partial(b) - e26Partial(a)) || ((b.validation.net.t || 0) - (a.validation.net.t || 0))));
    const drawCards = () => { box.replaceChildren(); (ST.all ? ordered : ordered.slice(0, 12)).forEach((e) => box.append(card(e))); if (!ST.all && ordered.length > 12) { const b = h("button", "pill m-more", `Show all ${ordered.length}`); b.type = "button"; b.addEventListener("click", () => { ST.all = true; drawCards(); }); box.append(b); } };
    drawCards();
    // 3. the out-of-sample test: the early split
    if (EA && EB) {
      const BK = EA.book, NV = BK.naive && BK.naive.test, conc = BK.test_concentration || {}, LM = EB.largest_month || {}, WO = EB.without_largest_month || {};
      $("#ed2-book-p").textContent = `The IMF commodity prices end in June 2017, so the engine replayed the whole search on an earlier calendar: discovery to ${EA.calendar.discovery_to}, validation to ${EA.calendar.validation_to}, and ${EA.calendar.test} held out, with its own fake markets and its own calibrated cut over ${e26N(EA.hypotheses)} candidates. It is a replay, not an independent test: those test years are the main search's validation years, and the replay's results were in view when the audit changed the method. ${EF.distinct.real} distinct edges survived; its ${e26N(ENL.hypotheses)} fake-market hypotheses produced ${EF.distinct.placebo}. In the test years all ${EF.test_positive.real} of ${EF.test_data.real} made money after costs. Combined at equal risk, refit each January and scaled from an exponentially weighted volatility, the book earned a Sharpe of ${e26S(EB.sharpe)} (t ${e26S(EB.t, 1)}, bootstrap range ${e26S(EB.sharpe_boot.p05)} to ${e26S(EB.sharpe_boot.p95)}) at ${e26Pct(EB.vol_annual, 1)} volatility against a 10% aim, with a worst drawdown of ${e26Pct(EB.max_drawdown, 1)}; without its largest month (${LM.date}, ${e26Pct(LM.r, 1)}) the Sharpe is ${e26S(WO.sharpe)}, so no single month carries it. Three more cautions: the ${BK.edges} edges are about ${fx(conc.independent_bets_test, 1)} independent bets (average correlation ${e26S(conc.mean_pairwise_corr)}); they trade IMF spot research prices, not futures with roll, so they are information rather than trades; and the naive book of all ${BK.naive ? BK.naive.edges : "n/a"} tested discovery survivors earned ${NV ? e26S(NV.sharpe) : "n/a"}, so in this window the later stages cost return.`;
      fillTable($("#ed2-early"), ["Stage", "Real", "Fake markets", "Real count expected by luck"], EA.funnel.map((s) => [s.stage, e26N(s.real), e26N(s.placebo), e26Luck(s, ENL.hypotheses, EA.funnel[0].real)]), 1);
      try {
        const M = BK.monthly_test, pts = []; let w = 0;
        M.dates.forEach((d, i) => { w += Math.log(1 + (M.r[i] || 0)); pts.push([Number(d.slice(0, 4)) + (Number(d.slice(5, 7)) - 0.5) / 12, Math.exp(w)]); });
        const y0 = Number(M.dates[0].slice(0, 4)), y1 = Number(M.dates[M.dates.length - 1].slice(0, 4));
        const ticks = []; for (let y = y0; y <= y1 + 1; y += 2) ticks.push([y, String(y)]);
        $("#ed2-curve-t").textContent = `Growth of $1 in the out-of-sample book, ${EA.calendar.test}, after costs`;
        xyChart($("#ed2-curve"), { series: [{ pts, color: "var(--s1)", name: "Out-of-sample edge book, after costs", width: 2 }], height: 220, yfmt: (v) => "$" + fx(v, 2), xfmt: (v) => String(Math.floor(v)), xticks: ticks, label: "Growth of $1 in the out-of-sample edge book" });
      } catch (e) { /* the curve is optional */ }
      const row = (k, x) => (x && fin(x.sharpe) ? [k, x.from + " to " + x.to, e26S(x.sharpe), e26S(x.t, 1), x.without_largest_month ? e26S(x.without_largest_month.sharpe) : "n/a", e26Pct(x.return_annual, 1), e26Pct(x.vol_annual, 1), e26Pct(x.max_drawdown, 1)] : [k, "n/a", "n/a", "n/a", "n/a", "n/a", "n/a", "n/a"]);
      fillTable($("#ed2-book"), ["Book", "Years", "Sharpe", "t", "Sharpe without largest month", "Return a year", "Volatility", "Worst drawdown"], [
        row(`The ${BK.edges} edges, held-out test`, EB), row("Same book, validation years (in sample)", BK.validation_in_sample),
        row(`Best single family, chosen in validation (${BK.best_family ? BK.best_family.family : "none"})`, BK.best_family && BK.best_family.test),
        row(`Naive: all ${BK.naive ? BK.naive.edges : ""} tested discovery survivors, no later stages`, NV),
        row(BK.null_book ? `The fake markets' own book (${BK.null_book.edges} false edges)` : "The fake markets' own book: no false edge survived to build one", BK.null_book && BK.null_book.test)], 1);
      $("#ed2-book-math").innerHTML = `<span class="mlabel">The book</span>weights <var>w</var><sub><var>k</var></sub> &prop; 1/&sigma;&#770;<sub><var>k</var></sub> (24 months), capped at 3/<var>K</var>, refit each January on data through November; scale = 10% / max(&sigma;&#770;<sub>EWMA, half-life 12</sub>, 0.75&middot;&sigma;&#770;<sub>long run</sub>), from data through <var>t</var> &minus; 2; costs = &Sigma; |&Delta;<var>w</var>| &times; half the round trip. Independent bets = (&Sigma;&lambda;<sub><var>i</var></sub>)<sup>2</sup>/&Sigma;&lambda;<sub><var>i</var></sub><sup>2</sup> over the eigenvalues of the edges' correlation matrix = ${fx(conc.independent_bets_test, 1)}. Deflated Sharpe for ${e26N(EB.deflated.n_trials)} trials: ${e26Pct(EB.deflated.dsr, 0)} (luck threshold ${e26S(EB.deflated.sr0_annual)}); it treats every candidate as an independent trial on the test years, which overstates luck for a book fixed before them.`;
    } else {
      $("#ed2-book-p").textContent = "No out-of-sample test is in this build.";
    }
    // 4. families
    const fam = O.families.slice().sort((a, b) => (b.distinct || 0) - (a.distinct || 0) || b.tried - a.tried);
    fillTable($("#ed2-fam"), ["Family of idea", "Tried", "Pass BH", "Pass validation", "Distinct survivors", "Distinct expected from fake markets", "Verdict"],
      fam.map((f) => [f.family, e26N(f.tried), e26N(f.bh), e26N(f.validation), e26N(f.distinct), fin(f.expected_false_distinct) ? (f.null && f.null.distinct === 0 ? `under ${fx(3 / f.null.tried * f.tried, 2)}` : fx(f.expected_false_distinct, 2)) : "n/a",
        h("span", "rs-v rs-v-" + (f.beats_placebo ? "supported" : "no-evidence"), f.beats_placebo ? "beats chance" : "no better than chance")]), 1);
    // 5. now
    const now = tested.concat(main).filter((e) => e.today && e.today.positions && e.today.positions.length);
    fillTable($("#ed2-now"), ["Edge", "Evidence", "Signal (research only)"], now.map((e) => [e.name, e._cal === "early" ? `tested 2011 to 2017: Sharpe ${e26S(e.test.net.sharpe)}` : e26Partial(e) ? `partial, ${e.test.markets_with_test_data} markets: Sharpe ${e26S(e.test.net.sharpe)}` : "validated, not testable", e.today.positions.map((p) => `${p.side} ${p.name}`).join(", ")]), 1);
    // 6. data
    const UM = (typeof SNAP26 !== "undefined" && SNAP26.unusual) || {}, DN = O.data_notes || {};
    const ub = Object.values(UM).reduce((a, m) => { a[m.family] = (a[m.family] || 0) + 1; return a; }, {});
    const LMK = DN.long_block_masks || {};
    $("#ed2-data-p").textContent = `${Object.keys(UM).length} unusual series in ${Object.keys(ub).length} families (${Object.entries(ub).sort((a, b) => b[1] - a[1]).map(([k, v]) => `${k} ${v}`).join(", ")}), each moved forward by the months it takes to be published, so a value enters only when it was knowable. Annual series act as slow conditioning signals. The traps: ${DN.averaging || ""} Measured here, one-month momentum without the skip month has t ${(DN.own_one_month_signal_by_skip || []).map((g) => `${fx(g.t_lag1, 1)} in ${g.group.toLowerCase()}`).join(", ")}; with it, under 2 in every class. ${LMK.why || ""} The data mirrors carry today's revised values, not the first print, so revision look-ahead is not removed.`;
    fillTable($("#ed2-data"), ["Series", "Family", "Frequency", "Knowable after", "Source"], Object.entries(UM).sort((a, b) => (a[1].family || "").localeCompare(b[1].family || "")).map(([k, m]) => {
      const src = m.url ? (() => { const a = h("a", null, m.computed ? "computed" : (m.url.match(/github(?:usercontent)?\.com\/([^/]+\/[^/]+)/) || [null, "GitHub mirror"])[1]); a.href = m.url.startsWith("http") ? m.url : "#"; a.target = "_blank"; a.rel = "noopener"; return a; })() : "computed";
      return [m.name || k, m.family || "", m.frequency || "", m.computed ? "same month" : `${m.lag_months} month${m.lag_months === 1 ? "" : "s"}${m.live === false ? " (feed no longer updated)" : ""}`, src];
    }), 1);
    const sub = $("#ed2-sub");
    if (sub) sub.title = (SNAP26.summary || []).join(" ");
  }

  // Today: the edge lab in one paragraph, linked to the desk
  function renderEdgesToday() {
    const el = $("#t7-edges"), O = E26();
    if (!el || !O) return;
    const by = Object.fromEntries(O.funnel.map((s) => [s.key, s])), EA = O.early, EB = EA && EA.book && EA.book.test;
    const EF = EA ? Object.fromEntries(EA.funnel.map((s) => [s.key, s])) : null, nullN = (O.placebo.null || {}).hypotheses;
    const tilt = {};
    (EA ? EA.edges : []).concat(O.edges).filter((e) => e.today && e.today.positions && e.today.positions.length && e.test.tested).forEach((e) => e.today.positions.forEach((p) => { tilt[p.name] = (tilt[p.name] || 0) + (p.side === "long" ? 1 : -1); }));
    el.replaceChildren();
    const a = h("a", null, "The edge lab →"); a.href = "#edges";
    const lean = Object.entries(tilt).filter(([, v]) => v).map(([k, v]) => `${v > 0 ? "long" : "short"} ${k}`).join(", "), any = Object.keys(tilt).length > 0;
    el.append(h("strong", null, "From the edge lab. "), document.createTextNode(`Of ${e26N(O.universe.hypotheses)} candidate edges invented from market data and unusual data (climate, oceans, the sun, storms, shipping, the calendar), ${by.distinct.real} survived a gauntlet calibrated on ${e26N(nullN)} fake-market hypotheses, against ${e26Luck(by.distinct, nullN, by.tried.real)} expected by luck. `
      + (EA && EB ? `Replayed with data through ${EA.calendar.validation_to}, ${EF.test_positive.real} of ${EF.test_data.real} survivors made money on ${EA.calendar.test} (years the main search had used for validation, so a replay, not an independent test), and their book earned a Sharpe of ${e26S(EB.sharpe)} after costs; but they are about ${fx((EA.book.test_concentration || {}).independent_bets_test, 1)} independent bets on spot commodity research prices, not tradeable futures. ` : "")
      + `${lean ? `The tested edges that still trade lean ${lean}: a` : any ? "The tested edges that still trade point opposite ways today and cancel out; the lab is in any case a" : "No tested edge trades today, and the lab is in any case a"} research signal, never the call. `), a);
  }

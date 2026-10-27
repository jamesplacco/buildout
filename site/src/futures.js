  /* =====================================================================================
     v0.29: THE FUTURES ENGINE. Carry, trend, basis momentum and hedgers' positioning across liquid CME futures, tested
     after costs across markets and over time; the book's Treasury hedge read from the same data. Reads SNAP29
     (scripts/snapshot_v29.py): the long run on pysystemtrade's published prices (to March 2024) and, when it exists,
     the Databento run (2010 to now).
     ===================================================================================== */
  const F29 = () => (typeof SNAP29 !== "undefined" && SNAP29 && SNAP29.futures) || null;
  const f29S = (v, d = 2) => (fin(v) ? (v < 0 ? "−" : "") + fx(Math.abs(v), d) : "n/a");
  const f29P = (p) => (!fin(p) ? "n/a" : p < 0.001 ? "under 0.001" : fx(p, 3));
  const f29Pct = (v, d = 0) => (fin(v) ? (v < 0 ? "−" : "") + pct(Math.abs(v), d, false) : "n/a");
  const F29_VCLASS = { supported: "supported", faded: "one-era", class_tilt: "one-era", beta_only: "one-era", one_era: "one-era", reversed: "no-evidence", chance: "no-evidence", untested: "no-evidence" };
  const F29_DES = { xs: "across markets", ts: "over time" };
  const f29Date = (s) => { const t = String(s || ""); return +t.slice(0, 4) + ((+t.slice(5, 7) || 1) - 1) / 12; };

  function f29Rows(R, A, VD) {
    return R.tests.slice().sort((a, b) => a.p - b.p).map((t) => [
      SIGNALS29[t.signal] || t.name.split(":")[0], F29_DES[t.design] || t.design, f29S(t.sharpe_gross), f29S(t.sharpe_net), f29P(t.p), f29S(t.alpha_sharpe),
      `${f29S(t.halves.first && t.halves.first.sharpe)} / ${f29S(t.halves.second && t.halves.second.sharpe)} (split ${t.halves.split || ""})`,
      t.within_class ? f29S(t.within_class.sharpe_net) : "",
      `${f29S(t.since_publication.sharpe)} (${t.since_publication.months || 0} mo)`,
      h("span", "rs-v rs-v-" + (F29_VCLASS[t.verdict] || "no-evidence"), VD[t.verdict] || t.verdict)]);
  }
  const F29_HEAD = ["Signal", "Portfolio", "Sharpe before costs", "Sharpe after costs", "p (one-sided)", "Beyond holding long", "Halves (first / second)", "Within asset classes", "Since publication", "Verdict"];

  function renderFutures() {
    const O = F29(), tiles = $("#ft-tiles");
    if (!tiles) return;
    if (!O) { tiles.replaceChildren(h("p", "empty", "The futures engine is not in this build.")); return; }
    const runs = O.runs || {}, L = runs.pysystemtrade, D = runs.databento, V = O.validation || {}, A = O.assumptions || {}, VD = O.verdicts || {};
    const C = (O.calibration || {}).pooled || {};
    const R = L || D;
    const T = R ? R.tests : [], sup = T.filter((t) => t.supported), pass = T.filter((t) => t.pass_bh);
    rsKpi(tiles, R ? [
      [String(R.universe.markets), "Futures markets", `${R.universe.from} to ${R.universe.to}; equity indexes, Treasuries, rates, currencies, metals, energy, grains, livestock`],
      [`${sup.length} of ${R.n_hypotheses}`, "Still work", `${pass.length} passed the multiple-testing cut; still works also needs: beyond holding long, both halves, within classes, and a Sharpe of ${A.faded_sharpe} since publication`],
      [f29Pct(R.fakes.share_p_below_05, 0), "Random signals below p 0.05", "on the real returns, each market's average removed; about 5% is honest"],
      [D ? "Live" : "Pending", "Databento run, 2010 to now", D ? `last run ${String(D.built || "").slice(0, 10)}` : "needs your DATABENTO_API_KEY, on your computer or in GitHub"]] : [
      [String((O.markets || []).length), "Futures markets", "ready to test"], ["Pending", "First run", ""], ["", "", ""], ["", "", ""]]);
    // status
    $("#ft-status-p").textContent = (L ? `The long record ran here on pysystemtrade's published prices (Rob Carver's open-source project): ${L.universe.markets} markets, ${L.universe.from} to ${L.universe.to}, each day's held contract and the next one. ` : "")
      + (D ? `The Databento run covers ${D.universe.from} to ${D.universe.to} (last run ${String(D.built || "").slice(0, 10)}), with hedgers' positions from the CFTC for ${D.universe.with_positioning} markets. `
        : `The Databento run (2010 to now, with hedgers' positions from the CFTC) needs your key, so it runs where the key is: on your computer, ${O.how_to_run.laptop}; or in GitHub, ${O.how_to_run.github}. Until then the desk shows the long record, which ends in March 2024. `)
      + "The two are run separately, not spliced: they hold different contracts (pysystemtrade its own roll calendar, Databento the most traded contract), so they are two records of the same markets.";
    // results
    if (L) {
      const U = (L.untested || []).map((u) => u.name.split(":")[0].toLowerCase());
      $("#ft-res-p").textContent = `${L.universe.from} to ${L.universe.to}, ${L.n_hypotheses} tests (${Object.keys(SNAP29.futures.designs || {}).length ? "each signal as a portfolio across markets and one over time" : ""}), net of trading and roll costs${U.length ? `; not testable here: ${[...new Set(U)].join(", ")} (needs the CFTC's site)` : ""}. ${sup.length ? `Still working on every check: ${sup.map((t) => `${(SIGNALS29[t.signal] || t.name.split(":")[0]).toLowerCase()} ${F29_DES[t.design]}`).join("; ")}.` : "None holds on every check."} Read the halves and the column since publication together: most of these premia were larger before they were published.`;
      fillTable($("#ft-res"), F29_HEAD, f29Rows(L, A, VD), 2);
      // the chart: growth of a dollar, each strategy scaled to 10% volatility, plus holding long
      const pick = ["carry:xs", "trend_12:ts", "basis_mom:xs"], colors = ["var(--s1)", "var(--s3)", "var(--s4)"];
      const series = [], legend = [];
      const scaled = (c) => { const r = c.net, m = r.reduce((a, b) => a + b, 0) / r.length, sd = Math.sqrt(r.reduce((a, b) => a + (b - m) ** 2, 0) / (r.length - 1)) * Math.sqrt(12); let g = 0; return c.months.map((d, i) => [f29Date(d), (g += Math.log1p(r[i] * 0.10 / (sd || 1)))]); };
      pick.forEach((k, i) => {
        const t = L.tests.find((x) => `${x.signal}:${x.design}` === k);
        if (!t) return;
        const nm = `${SIGNALS29[t.signal] || t.name.split(":")[0]} ${F29_DES[t.design]}`;
        series.push({ pts: scaled(t.curve), color: colors[i], name: nm });
        legend.push([colors[i], nm]);
      });
      if (L.benchmark && L.benchmark.curve) { series.push({ pts: scaled(L.benchmark.curve), color: "var(--s2)", name: "Holding every market long" }); legend.push(["var(--s2)", "Holding every market long, equal risk"]); }
      const y0 = Math.floor(f29Date(L.universe.from) / 5) * 5;
      xyChart($("#ft-chart"), { height: 260, label: "Growth of one dollar after costs at 10% volatility, log scale", series,
        xticks: Array.from({ length: 8 }, (_, i) => y0 + 5 * i).map((y) => [y, String(y)]), yfmt: (v) => "$" + fx(Math.exp(v), Math.exp(v) < 10 ? 1 : 0), padL: 52 });
      legendLines($("#ft-chart-leg"), legend);
    } else {
      $("#ft-res-p").textContent = "Waiting for the first run.";
      fillTable($("#ft-res"), ["Signal"], O.signals.map((s) => [s.name]), 1);
    }
    $("#ft-math").innerHTML = `<span class="mlabel">The test</span>each month <var>t</var>, from each market's last close: across markets, weights from the signal's centred rank (long side and short side one each), every market sized to equal risk (divided by its ${A.vol_com_days}-day exponentially weighted volatility), at least ${A.min_markets_xs} markets; over time, each market long or short by the signal's sign, sized to equal risk, at least ${A.min_markets_ts} markets; the return over month <var>t</var>+1 of the contract held, a roll taken from the new contract's own previous close (a roll day without one is left out); costs per market in basis points of notional per round trip, half on each change in weight and a full round trip per roll; <var>p</var> one-sided in the published direction, from the monthly returns by the equal-weighted cosine test (Lazarus, Lewis, Stock and Watson 2018), at least ${A.min_months} months (after costs a strategy with no edge loses a little, and a two-sided test would count that as a discovery; a significant loss shows as "reversed"); Benjamini-Hochberg at <var>q</var> = ${A.fdr_q}; "beyond holding long": the returns less their beta to a passive long portfolio of all the markets at equal risk; "still works" needs the cut, the published sign, beyond holding long at <var>p</var> 0.05, the same sign in both halves (each record split at its middle month), across markets a positive Sharpe within asset classes, and a Sharpe of ${A.faded_sharpe} or more since publication (with three years or more of it; below that the premium counts as faded, a judgment, since over five to eleven years a Sharpe ratio's standard error is 0.3 to 0.45).`;
    // the recent record
    if (D) {
      $("#ft-live-p").textContent = `${D.universe.from} to ${D.universe.to} from Databento, ${D.universe.markets} markets, hedgers' positions for ${D.universe.with_positioning}. ${(D.findings || []).slice(0, 2).join(" ")}`;
      fillTable($("#ft-live"), F29_HEAD, f29Rows(D, A, VD), 2);
    } else {
      $("#ft-live-p").textContent = `Pending your Databento key. The run pulls about fifteen years of daily bars for the two most traded contracts of each market, with their contract definitions, and refuses any pull estimated above $5; then it adds hedgers' positions from the CFTC, which the build workspace cannot reach. On your computer, ${O.how_to_run.laptop}.`;
      fillTable($("#ft-live"), ["Signal", "Status"], O.signals.map((s) => [s.name.split(":")[0], "pending the Databento run"]), 1);
    }
    // the book
    const B = (D || L || {}).book || {};
    const TD = B.today || [];
    $("#ft-book-p").textContent = TD.length ? `As of ${B.as_of}${D ? "" : " (the long record's last month; the Databento run brings it to today)"}: carry is what holding the future earns a year if prices stand still (negative means the further contract is dearer, so holding it costs); the percentile places the value in that market's own history since 1990 (100 is the highest). A reading, not a forecast: only signals marked "still works" above carry evidence. Research only.` : "";
    fillTable($("#ft-book"), ["Future", "Carry, a year", "Carry percentile", "Past 12 months", "Trend percentile", "Past 3 months", "Volatility"], TD.map((x) => [x.name,
      f29Pct(x.carry, 1), fin(x.carry_pct) ? fx(100 * x.carry_pct, 0) : "n/a", f29Pct(x.trend_12, 1), fin(x.trend_12_pct) ? fx(100 * x.trend_12_pct, 0) : "n/a", f29Pct(x.trend_3, 1), f29Pct(x.vol, 0)]), 1);
    const SL = B.selloffs || [], CO = B.correlation || [];
    const decades = [...new Set(CO.flatMap((c) => Object.keys(c.by_decade || {})))].sort();
    $("#ft-sell-p").textContent = SL.length ? `In the S&P 500 future's worst months (its worst 5%), how each Treasury future did, and its correlation with the S&P 500 future by decade. A hedge earns its keep in exactly those months, and the correlation's sign has not been constant: it was positive through much of the 1990s and again since 2022, when stocks and bonds fell together.` : "";
    fillTable($("#ft-sell"), ["Treasury future", "Worst months for stocks", "Stocks, average", "Treasury, average", "Treasury up in"].concat(decades.map((d) => `Correlation, ${d}`)).concat(["Last 36 months"]),
      SL.map((s) => { const c = CO.find((x) => x.market === s.market) || {}; return [s.name, String(s.worst_es_months), f29Pct(s.es_mean, 1), f29Pct(s.treasury_mean, 1), f29Pct(s.treasury_up_share, 0)]
        .concat(decades.map((d) => f29S((c.by_decade || {})[d]))).concat([f29S(c.last_36m)]); }), 1);
    // signals and markets
    $("#ft-sig-p").textContent = "Each signal comes from published research, with the direction that research found. The markets are today's liquid CME futures, which flatters any signal that is long what survived; the costs are the engine's own estimates.";
    fillTable($("#ft-sig"), ["Signal", "Published by", "Year", "Predicted"], O.signals.map((s) => [s.name, s.reference, String(s.published), s.direction > 0 ? "higher, better" : "higher, worse"]), 1);
    const BM = (R && R.universe && R.universe.by_market) || {};
    fillTable($("#ft-mk"), ["Market", "Code", "Class", "Long record", "Cost, bp a round trip", "CFTC code"], (O.markets || []).map((m) => [m.name, m.code, m.class,
      BM[m.code] ? `${BM[m.code].from} to ${BM[m.code].to}` : "not in the long record", fx(m.cost_bp, 1), m.cftc_code]), 1);
    // validation and calibration
    const P = V.planted || {}, cx = P["carry:xs"] || {}, ct = P["carry:ts"] || {};
    $("#ft-val-p").textContent = `On ${((V.design || {}).markets) || ""} synthetic markets in pysystemtrade's layout, with market and sector factors and half of each month's carry earned the next month, the engine found the planted carry edge across markets (Sharpe ${f29S(cx.sharpe_net)} after costs, p ${f29P(cx.p)}${cx.supported ? ", holding on every check" : ""}); over time the same edge gave Sharpe ${f29S(ct.sharpe_net)} (p ${f29P(ct.p)}${ct.pass_bh ? "" : ", short of the multiple-testing cut"}). ${C.worlds ? `In ${C.worlds} more synthetic worlds with no edge at all, ${f29Pct(C.tests_p_below_05, 1)} of ${C.tests} signal tests fell below p 0.05 and ${C.tests_passing_cut} passed the cut; of ${C.fake_runs} random-signal runs across ${C.fake_worlds || C.worlds} worlds, ${f29Pct(C.fakes_p_below_05, 1)}. About 5% is honest; after costs a strategy with no edge loses a little, which is why the signal tests come in under it.` : ""}`;
    fillTable($("#ft-val"), ["Synthetic test", "Sharpe after costs", "p", "Passed the cut"], [["Carry across markets (planted)", f29S(cx.sharpe_net), f29P(cx.p), cx.pass_bh ? "yes" : "no"], ["Carry over time (planted)", f29S(ct.sharpe_net), f29P(ct.p), ct.pass_bh ? "yes" : "no"]]
      .concat((V.others || []).map((t) => [`${(SIGNALS29[t.signal] || t.signal)} ${F29_DES[t.design] || t.design} (no edge)`, f29S(t.sharpe_net), f29P(t.p), t.pass_bh ? "yes" : "no"])), 1);
    const ul = $("#ft-limits"); ul.replaceChildren(); (O.limitations || []).forEach((l) => ul.append(h("li", null, l)));
    const sub = $("#ft-sub"); if (sub && R) sub.title = (R.findings || []).join(" ");
  }
  const SIGNALS29 = { trend_1: "Trend, 1 month", trend_3: "Trend, 3 months", trend_12: "Trend, 12 months", basis_mom: "Basis momentum", hedging_pressure: "Hedging pressure", carry: "Carry" };

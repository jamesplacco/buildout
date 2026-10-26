  /* =====================================================================================
     v0.28: THE FILINGS ENGINE. SEC insider data sets and XBRL company facts across every stock that has been in the
     S&P 500, each value used only once it could have been traded. Reads SNAP28 (scripts/snapshot_v28.py). Before the
     first real run the desk shows the design, the engine's validation on synthetic data and its calibration; after
     it, the results.
     ===================================================================================== */
  const F28 = () => (typeof SNAP28 !== "undefined" && SNAP28 && SNAP28.filings) || null;
  const f28S = (v, d = 3) => (fin(v) ? (v < 0 ? "−" : "") + fx(Math.abs(v), d) : "n/a");
  const f28P = (p) => (!fin(p) ? "n/a" : p < 0.001 ? "under 0.001" : fx(p, 3));
  const f28Pct = (v, d = 0) => (fin(v) ? (v < 0 ? "−" : "") + pct(Math.abs(v), d, false) : "n/a");
  const F28_FAM = { insiders: "Insider trades (Forms 4 and 5)", fundamentals: "Financial statements (XBRL)", text: "10-K text" };
  const F28_VCLASS = { supported: "supported", reversed: "one-era", cut_only: "one-era", chance: "no-evidence", opposite: "no-evidence", untested: "no-evidence" };

  function renderFilings() {
    const O = F28(), tiles = $("#fl-tiles");
    if (!tiles) return;
    if (!O) { tiles.replaceChildren(h("p", "empty", "The filings engine is not in this build.")); return; }
    const R = O.run, V = O.validation || {}, A = O.assumptions || {}, VD = O.verdicts || {}, C = (O.calibration || {}).pooled || {};
    const T = R ? R.tests : [], sup = T.filter((t) => t.supported), pass = T.filter((t) => t.pass_bh);
    rsKpi(tiles, R ? [
      [(R.universe.tickers_ever || 0).toLocaleString("en-US"), "Tickers ever in the S&P 500", `tested ${R.universe.from} to ${R.universe.to}, about ${fx(R.coverage.companies_mean, 0)} companies a month`],
      [(R.universe.insider_transactions || 0).toLocaleString("en-US"), "Insider trades read", `and the filings of ${(R.universe.companies_with_facts || 0).toLocaleString("en-US")} companies`],
      [`${sup.length} of ${R.n_hypotheses}`, "Signals that still work", `${pass.length} passed the multiple-testing cut; still works also needs the published direction, both halves and the controls`],
      [f28Pct(R.fakes.share_p_below_05, 0), "Random noise below p 0.05", "persistent random signals on the real data; about 5% is the honest rate"]] : [
      [String(O.signals.length), "Signals ready to test", "insider trades, financial statements and, optionally, 10-K text"],
      ["≈500", "Stocks a month", "every S&P 500 member since 2009, including those that later left"],
      [f28Pct(C.tests_p_below_05, 0), "False alarms with no edge", `signal tests below p 0.05 across ${C.worlds || "several"} synthetic worlds; about 5% is honest`],
      ["Pending", "First real run", "needs the SEC's site, so it runs on your computer or in GitHub"]]);
    // status
    $("#fl-status-p").textContent = R
      ? `Last run ${String(R.built || "").slice(0, 10)}: ${R.coverage.months} months, ${f28Pct(R.coverage.with_return_share)} of member companies with a return (free price sources often lack delisted companies, which biases toward survivors); membership known through ${R.coverage.membership_through}. ${(R.findings || []).slice(0, 2).join(" ")}`
      : `Built, audited and validated, not yet run on real data. This workspace cannot reach the SEC, so the first run happens where it can: on your computer (${O.how_to_run.laptop}), or in GitHub (${O.how_to_run.github}). The first run downloads about eighty quarters of the SEC's insider data sets and the filings of every company in the index since 2007 (cached), then tests every signal below. This desk fills in from that run.`;
    fillTable($("#fl-run"), ["Step", "Source", "Used from"], [
      ["Universe", "S&P 500 membership at each month end (GitHub: hanshof/sp500_constituents); tests from 2009 to the file's last change", "the month it applies to"],
      ["Insider trades", "SEC Insider Transactions Data Sets, Forms 4 and 5, quarterly since 2006", "filed before the month's last trading day"],
      ["Financial statements", "SEC XBRL company facts (data.sec.gov), each value as first filed", "filed before the month's last trading day"],
      ["Prices", "Yahoo (with split events), then Stooq, by each company's current ticker; adjusted for splits and dividends", "month-end closes"]], 1);
    // signals
    $("#fl-sig-p").textContent = `Each signal comes from published research, with the direction that research found. Most were published before the sample begins, so the question is whether they still work after years of being known: McLean and Pontiff (2016) found published anomalies lose about half their return after publication.`;
    fillTable($("#fl-sig"), ["Signal", "Data", "Published by", "Year", "Predicted"], O.signals.map((s) => [s.name, F28_FAM[s.family] || s.family, s.reference, String(s.published), s.direction > 0 ? "higher, better" : "higher, worse"]), 1);
    // results
    $("#fl-math").innerHTML = `<span class="mlabel">The test</span>each month <var>t</var>: rank IC<sub><var>t</var></sub> = corr(rank <var>s</var><sub><var>i</var>,<var>t</var></sub>, rank <var>r</var><sub><var>i</var>,<var>t</var>+1..<var>t</var>+<var>h</var></sub>) over the S&amp;P 500 companies with both (at least ${A.min_stocks}; a flag or count needs ${A.min_group} or more off its commonest value); <var>p</var> from the monthly IC series itself by the equal-weighted cosine test (Lazarus, Lewis, Stock and Watson 2018): the long-run variance from the first &nu; = 0.4&thinsp;<var>T</var><sup>2/3</sup> cosine projections, <var>t</var> referred to Student's <var>t</var> with &nu; degrees of freedom, at least ${A.min_months} months; it carries the month-to-month swings of a signal tied to industries or factors and keeps its size in short, autocorrelated and overlapping series; controlled IC: the signal's rank residualized on the ranks of size, momentum (months <var>t</var>&minus;11 to <var>t</var>&minus;1) and book to market; Benjamini-Hochberg at <var>q</var> = ${A.fdr_q}; "still works" also needs the published direction, the same sign in both halves (split ${String(A.split || "").slice(0, 4)}) and a controlled IC with <var>p</var> of 0.05 or less; portfolio: always the published direction, top minus bottom quintile (or flagged against unflagged), equal weight, ${A.cost_bp_round_trip} bp a round trip on turnover.`;
    if (R) {
      const U = R.untested || [];
      $("#fl-res-p").textContent = `${R.n_hypotheses} hypotheses tested (each signal at one and three months ahead)${U.length ? `; ${U.length} could not be tested, too few months with enough stocks: ${[...new Set(U.map((u) => u.name.toLowerCase()))].join("; ")}` : ""}. ${sup.length ? `${sup.length} hold up: ${sup.map((t) => t.name.toLowerCase()).join("; ")}.` : "None holds up on every check."} The table lists them all, best p first; the reassignment p is shown for comparison only: it ignores factors, so it runs too low on signals tied to them.`;
      fillTable($("#fl-res"), ["Signal", "Months ahead", "Mean rank IC", "t", "Controlled IC", "p", "Reassignment p", "Both halves", "Long-short Sharpe", "Verdict"],
        T.slice().sort((a, b) => (a.p || 1) - (b.p || 1)).map((t) => [t.name, String(t.horizon), f28S(t.mean_ic), f28S(t.t_nw, 1), f28S(t.mean_ic_controlled), f28P(t.p), f28P(t.p_reassign), t.same_sign_both_halves ? "same sign" : "differ",
          t.portfolio ? f28S(t.portfolio.sharpe, 2) : "",
          h("span", "rs-v rs-v-" + (F28_VCLASS[t.verdict] || "no-evidence"), VD[t.verdict] || t.verdict)]), 1);
    } else {
      $("#fl-res-p").textContent = "Waiting for the first real run. The table will list every signal at one and three months ahead with its rank IC, controlled IC, p, both halves, the long-short portfolio in the published direction after costs and a verdict.";
      fillTable($("#fl-res"), ["Signal", "Months ahead", "Mean rank IC", "p", "Verdict"], O.signals.filter((s) => s.family !== "text").map((s) => [s.name, "1 and 3", "pending", "pending", "pending"]), 1);
    }
    // validation
    const P = V.planted || {}, K = V.checks || {}, nz = V.noise || [];
    $("#fl-val-p").textContent = `Before the engine is trusted with real data it must find an edge that is known to be there, and nothing else. On 160 synthetic companies in the SEC's own data layouts, twelve years of daily prices that move with a market factor and an industry-like factor, random insider trades, two share classes of one company, a 2-for-1 split, companies joining and leaving the index, and one planted edge (higher gross profitability, a higher next return; a rank IC about 0.04, at the strong end of what published anomalies show in large stocks), it ${P.pass_bh ? "found the edge" : "did not find the edge"}: mean rank IC ${f28S(P.mean_ic)}, p ${f28P(P.p)}, ${P.supported ? "holding on every check" : "not holding on every check"}, long-short Sharpe ${f28S(P.sharpe, 2)}. ${(() => { const k = nz.filter((n) => n.pass_bh).length; return k ? `${k} of ${nz.length} tests of signals with no planted edge passed the cut, which a 5% false-discovery rate allows.` : `None of the ${nz.length} tests of signals with no planted edge passed the cut.`; })()} The two share classes were merged into one company, and the split read as ${f28S(K.split_issuance_with_splits, 3)} share issuance (without the split events, ${f28S(K.split_issuance_without, 3)}).`;
    fillTable($("#fl-val"), ["Signal", "Months ahead", "Planted?", "Mean rank IC", "p", "Reassignment p", "Passed"], [["Gross profitability", "1", "yes", f28S(P.mean_ic), f28P(P.p), f28P(P.p_reassign), P.pass_bh ? "yes" : "no"]].concat(nz.map((n) => [n.signal.replace(/_/g, " "), String(n.horizon), "no", f28S(n.mean_ic), f28P(n.p), f28P(n.p_reassign), n.pass_bh ? "yes" : "no"])), 1);
    // calibration
    const SP = (O.calibration || {}).sparse || [];
    $("#fl-cal-p").textContent = C.worlds ? `Calibration: ${C.worlds} more synthetic worlds with no edge at all, ${C.tests} signal tests and ${C.random_signals} random signals. An honest test puts about 5% below p 0.05. The usual shortcut, reassigning each company's signal to another company, keeps a signal's persistence but forgets that stocks share factors, so on signals tilted toward a factor it calls noise significant far too often. Tilts in one world share its few factors, so they are fewer independent draws than they look (about ${fx(C.factor_tilt_effective_n_per_world || 0, 1)} per world of 10); on real data they can also carry real factor premia, so on the real run they are a reading, not the calibration.` : "";
    fillTable($("#fl-cal"), ["Signals with no edge", "This engine's test", "Reassignment test"], C.worlds ? [
      ["The ten signals, every horizon", f28Pct(C.tests_p_below_05, 1), f28Pct(C.tests_reassign_p_below_05, 1)],
      ["The ten signals, passing the multiple-testing cut", `${C.tests_passing_cut} of ${C.tests}`, ""],
      ["Random tilts toward a factor", f28Pct(C.factor_tilt_p_below_05, 1), f28Pct(C.factor_tilt_reassign_p_below_05, 1)],
      ["Random persistent noise", f28Pct(C.persistent_noise_p_below_05, 1), ""]].concat(SP.map((x) => [`Random flags on ${fx(100 * x.flag_rate, 0)}% of stocks` + (x.tested != null && x.tested < x.sims ? ` (${x.tested} of ${x.sims} testable)` : ""), x.tested === 0 ? "too rare to test" : f28Pct(x.share_p_below_05, 1), ""])) : [], 1);
    // the book
    if (R && R.today && R.today.length) {
      const sigs = Object.keys(R.today[0].percentile || {});
      const carried = R.today.some((x) => x.membership_carried);
      $("#fl-book-p").textContent = `Each holding's percentile among the ${R.today[0].month} S&P 500 members on each signal (100 is the highest value), and its insiders' open-market trades over the last 90 days.${carried ? ` The membership file ends ${R.coverage.membership_through}, so this month's universe is that list carried forward.` : ""} A percentile is a reading, not a forecast: only signals marked "still works" above carry evidence. Research only.`;
      fillTable($("#fl-book"), ["Company", "Insider buyers / sellers, 90 days"].concat(sigs.map((s) => s.replace(/_/g, " "))), R.today.map((x) => [x.ticker, `${x.insiders_90d.buyers} / ${x.insiders_90d.sellers}`].concat(sigs.map((s) => (fin(x.percentile[s]) ? fx(100 * x.percentile[s], 0) : "n/a")))), 1);
    } else {
      $("#fl-book-p").textContent = "After the first run: each holding's percentile among the S&P 500 on every signal, and its insiders' open-market purchases and sales over the last 90 days.";
      fillTable($("#fl-book"), ["Company", "Readings"], ["MSFT", "AMZN", "GOOGL", "META", "NVDA", "AVGO", "TSLA", "ORCL"].map((t) => [t, "pending the first run"]), 1);
    }
    const ul = $("#fl-limits"); ul.replaceChildren(); (O.limitations || []).forEach((l) => ul.append(h("li", null, l)));
    const sub = $("#fl-sub"); if (sub) sub.title = ((R && R.findings) || (V.findings || [])).join(" ");
  }

  /* =====================================================================================
     today7.js (v0.7): the first screen answers five questions (what changed, why it matters to the book,
     what the choices are, what would reverse the call, and whether to trust it), plus the shared helpers
     for the hedge policy and the one effective fundamentals dataset.
     ===================================================================================== */
  function hedgeLineInfo() {
    const H = readF().hedge || {}, status = H.status || (fin(H.line) ? "ok" : "unavailable");
    const boot = H.bootstrap || null;
    const band = boot && fin(boot.cut_p05) && fin(boot.cut_p95) ? [boot.cut_p05, boot.cut_p95] : H.zone_full || H.zone || null;
    return { line: status === "ok" && fin(H.line) ? H.line : null, status, band, lo: band ? band[0] : 0.0275, boot, trained: H.trained_through || null, holdout: H.holdout || null };
  }
  // the stock-bond state: the engine's own label (it has the history the hysteresis needs), else the snapshot reading
  function hedgeStateNow(I) {
    const lab = LIVE.macro && LIVE.macro.latest && LIVE.macro.latest.regime;
    if (I.corr.live && ["hedging", "neutral", "amplifying"].includes(lab)) return lab;
    return stockBondState([I.corr.v], "neutral")[0];
  }
  function tltNow(I) {
    const HL = I.HL || hedgeLineInfo(), S = LIVE.report && LIVE.report.summary;
    return tltDecision(hedgeStateNow(I), fin(I.infl.avg36) ? I.infl.avg36 / 100 : null, HL.line, HL.status, S && fin(S.hedge_ratio_now) && S.hedge_ratio_now > 0 ? S.hedge_ratio_now : null, POLICY7.hedge.maxRatio);
  }
  function sizeBindingTxt() {
    const d = LIVE.report && LIVE.report.decision && LIVE.report.decision.size;
    const names = { vol_target: "the volatility target binds", drawdown_cap: "the drawdown cap binds", max_gross: "the 1.5x gross cap binds" };
    return d && d.binding ? names[d.binding] || d.binding : "the smallest of the volatility target and the drawdown cap; Kelly checks the edge";
  }

  /* ---------- one effective fundamentals dataset ---------- */
  const FUND_BASE = FUND.rows.map((r) => Object.assign({}, r));
  function applyEffectiveFund() {
    FUND.rows = effectiveFund(FUND_BASE, LIVE.capexTTM || null);
    const n = FUND.rows.filter((r) => r.refreshed).length;
    FUND.note = n ? `${n} compan${n > 1 ? "ies" : "y"} updated from newer SEC filings` : "";
    return n;
  }

  /* ---------- the first screen ---------- */
  function latestDataDate() {
    const ds = [];
    const I = inputs();
    [I.vix, I.corr, I.hy, I.oil, I.real].forEach((o) => { if (o && o.live && isoOk(o.d)) ds.push(o.d); });
    return ds.length ? ds.sort().slice(-1)[0] : "2026-10-23";
  }
  function todayChanges(I, TD) {
    const HL = I.HL, out = [];
    const st = TD.gates.state.value;
    out.push({ id: "corr", k: "obs", what: `Stocks and bonds ${st === "amplifying" ? "are moving together" : st === "hedging" ? "are moving opposite" : "have no clear relationship"}`,
      v: `correlation ${sgn2(I.corr.v)}`, d: I.corr.live ? isoNice(I.corr.d) : monthNice(I.corr.d), live: I.corr.live,
      why: `TLT hedge: ${TD.status !== "ok" ? "unavailable" : TD.on ? "on" : "off"} under policy hedge.tlt.v2. It returns at −0.10 (${fx(Math.max(0, I.corr.v + 0.1), 2)} away).`, href: "#d-duration" });
    const inBand = HL.band && I.infl.avg36 / 100 >= HL.band[0] && I.infl.avg36 / 100 <= HL.band[1];
    out.push({ id: "infl", k: inBand ? "est" : "obs", what: inBand ? "Inflation sits inside the band where 156 years of data cannot pin the line" : I.infl.avg36 / 100 < HL.lo ? "Inflation is below the band: bonds hedged most months at this level" : "Inflation is above the band",
      v: `${pctPts(I.infl.avg36)} over 36 months${HL.band ? `; band ${fx(HL.band[0] * 100, 2)} to ${fx(HL.band[1] * 100, 2)}%` : ""}`, d: monthNice(I.infl.d), live: I.infl.live,
      why: `Inflation sleeve: ${I.infl.avg36 >= I.lineAt ? "8%, half gold, half energy" : "2%"}. TLT inflation gate ${TD.gates.inflation.status === "ok" ? (TD.gates.inflation.pass ? "passes" : "fails") : "not applied"}.`, href: "#fi-hedge" });
    let third = null;
    try {
      const near = rocRows().filter((x) => !x.row.meanReverting && x.at13.state === "line" && x.at13.esc && fin(x.at13.weeks)).sort((a, b) => a.at13.weeks - b.at13.weeks)[0];
      if (near && near.at13.weeks <= 26) third = { id: "roc", k: "est", what: `${near.row.n} is heading for a rule line`, v: `${fmtRocLevel(near.row, near.at13.at)} in ${durTxt(near.at13.weeks)} at the 13-week pace`, d: isoNice(near.r.date), live: !!near.r.live,
        why: `Crossing it reads "${near.at13.label}". A straight-line projection, not a forecast of the date.`, href: "#roc-title" };
    } catch (e) { third = null; }
    if (!third) {
      const ratio = I.capexTTM / I.ocfTTM, fresh = FUND.rows.filter((r) => r.refreshed).length;
      third = { id: "capex", k: "obs", what: fresh ? "New filings changed the builders' cash coverage" : "The five builders spend most of their cash flow on capex",
        v: `${pct0(ratio)} of operating cash flow`, d: FUND.as_of.replace("SEC filings through ", ""), live: fresh > 0,
        why: "AI equity scenarios: the capex-digestion signal is on above 80%; the reasoner weighs it.", href: "#fu-t-title" };
    }
    out.push(third);
    return out;
  }
  // previous values: what each headline read at the last data date this browser saw, so a change shows its "was"
  function todayCompare(items, asof) {
    let hist = LS.get("bo-today-hist", []);
    if (!Array.isArray(hist)) hist = [];
    hist = hist.filter((e) => e && isoOk(e.asof) && e.vals && typeof e.vals === "object");
    const vals = {};
    items.forEach((c) => { if (c.id) vals[c.id] = c.v; });
    const prev = hist.filter((e) => e.asof < asof).sort((a, b) => b.asof.localeCompare(a.asof))[0] || null;
    hist = hist.filter((e) => e.asof !== asof).concat([{ asof, vals }]).sort((a, b) => a.asof.localeCompare(b.asof)).slice(-12);
    LS.set("bo-today-hist", hist);
    if (!prev) return { prev: null, note: `First look at data through ${isoNice(asof)} in this browser. Next time, each line shows what it read before.` };
    const moved = Object.keys(vals).filter((k) => prev.vals[k] != null && prev.vals[k] !== vals[k]).length;
    return { prev, note: moved ? `${moved} of ${Object.keys(vals).length} headlines moved since ${isoNice(prev.asof)}.` : `Quiet: nothing on this screen moved since ${isoNice(prev.asof)}. No action is a decision too; the policies above still hold.` };
  }
  function renderToday7() {
    const box = $("#today7");
    if (!box) return;
    const I = inputs(), TD = tltNow(I), HL = I.HL;
    // the answer to the headline question
    const st = TD.gates.state.value, ans = $("#t7-answer");
    ans.replaceChildren();
    const lead = TD.status !== "ok" ? "Would bonds hedge the book? Unknown today." : TD.on ? "Would bonds hedge the book? Reliable enough to hold." : st === "amplifying" ? "Would bonds hedge the book? Not in this regime." : "Would bonds hedge the book? Unproven.";
    const H = readF().hedge || {}, gateAdds = H.experiment ? H.experiment.inflation_adds_value === true : null;
    ans.append(h("strong", null, lead + " "),
      document.createTextNode(st === "amplifying" ? `Stocks and bonds are moving together (S&P 500 against the 10-year, 36 months of monthly returns: ${sgn2(I.corr.v)}), so long bonds would add to a sell-off `
        : st === "hedging" ? `Stocks and bonds are moving opposite (S&P 500 against the 10-year, 36 months of monthly returns: ${sgn2(I.corr.v)}) ` : `The S&P 500's 36-month correlation with the 10-year (${sgn2(I.corr.v)}) sits between the lines `),
      evTag("obs"), document.createTextNode(`. The correlation state alone decides this: three-year inflation of ${pctPts(I.infl.avg36)} is ${fin(HL.line) ? (I.infl.avg36 / 100 < HL.line ? "below" : "above") + ` the validated ${fx(HL.line * 100, 2)}% line` : "unlined"}, and the engine's out-of-sample test ${gateAdds === false ? "cannot tell the inflation gate from the correlation rule (the difference is a few percent of the test's own noise), so it is kept as a guard, not dropped" : gateAdds ? "finds the inflation gate adds a little" : "has not tested the inflation gate"} `), evTag("est"), document.createTextNode("."));
    try {                                    // v0.30: the same question on the book's own days
      const B = typeof B30 === "function" ? B30() : null, P = B && B.hedges && B.hedges.policies, C = B && B.correlation;
      if (P && C) ans.append(document.createTextNode(` On the book's own days since ${B.hedges.from.slice(0, 4)}, the long bond held only when its correlation said it hedged cut the book's variance ${pct0(P.bond_when_it_hedges.variance_cut)} and lost ${pctPlain(-P.bond_when_it_hedges.y2022 + P.none.y2022, 0)} more in 2022; a Nasdaq-100 short cut it ${pct0(P.nasdaq_beta.variance_cut)}. The book's 63-day correlation with a 20-year bond is ${sgn2(C.book_63d)}. `), evTag("obs"));
    } catch (e) { /* the book run is optional here */ }
    // the latest day's tape, where it bears on the call: a growth scare is the one selloff long bonds do cushion
    try {
      const T = (typeof TAPE17 !== "undefined" && Array.isArray(TAPE17)) ? Object.fromEntries(TAPE17.map((x) => [x.id, x])) : {};
      const tl = T["tp-tlt-1022"], qq = T["tp-qqq-1022"];
      if (st === "amplifying" && tl && qq && fin(tl.value) && fin(qq.value) && tl.value > 0 && qq.value < 0) {
        ans.append(document.createTextNode(` The regime describes the average month, not every day: on Oct 22, a growth and earnings scare, TLT rose ${fx(tl.value, 2)}% while QQQ fell ${fx(Math.abs(qq.value), 2)}%. `), evTag("obs"));
      }
    } catch (e) { /* the tape is optional */ }
    $("#t7-status").textContent = `Model book, not personal positions · Data to ${isoNice(latestDataDate())}, tape to Oct 23 · Policies: TLT hedge v2, equity sizing v2${LIVE.status && Array.isArray(LIVE.status.checks) ? ` · ${LIVE.status.checks.filter((c) => c.ok).length} of ${LIVE.status.checks.length} data checks pass` : ""}`;
    // one governing size, and the other rules named as cross-checks so the desks cannot seem to disagree
    const sz = $("#t7-sizing");
    if (sz) {
      sz.replaceChildren();
      try {
        const N = typeof DX19 !== "undefined" && DX19 && DX19.now ? DX19.now : null;
        const R0 = RZ_LAST || runReasoner(false), opt = R0 && R0.alts && R0.alts.optimal;
        const byVol = Math.min(0.2 / ((1.1 * I.vxn.v) / 100), 1.5);
        const BC = N && typeof bookCall === "function" ? bookCall(N) : null;
        if (BC) {
          const S = BC.B.sizes;
          sz.append(h("strong", null, `One call: ${xx(BC.size)}. `), document.createTextNode(`The decision engine holds the ${xx(N.exposure)} baseline (no evidence for any other size); the book's own limits, measured on its names' prices, allow ${xx(S.es_budget)} (expected shortfall), ${xx(S.vol_target)} (volatility) and ${xx(S.drawdown_cap)} (drawdown), and the smallest is the size. ${BC.keep != null ? `To keep every name at full size instead, short ${pct0(BC.keep)} of NAV in Nasdaq-100 futures. ` : ""}`));
          const cross = [];
          if (opt) cross.push(`scenario solver ${xx(opt.port[0])}${fin(R0.robust_share) ? ` (optimal in ${pct0(R0.robust_share)} of assumption pairs)` : ""}`);
          if (N.hedge && /trend (on|off)/.test(N.hedge.context)) cross.push(`10-month trend rule ${/trend on/.test(N.hedge.context) ? "on" : "off"}`);
          if (cross.length) sz.append(document.createTextNode(`Cross-checks: ${cross.join("; ")}. `));
          sz.append(evTag("obs"));
        } else if (N) {
          const cross = [`volatility rule ${xx(byVol)}`];
          if (opt) cross.push(`scenario solver ${xx(opt.port[0])}${fin(R0.robust_share) ? ` (optimal in ${pct0(R0.robust_share)} of assumption pairs)` : ""}`);
          if (N.hedge && /trend (on|off)/.test(N.hedge.context)) cross.push(`10-month trend rule ${/trend on/.test(N.hedge.context) ? "on" : "off"}`);
          const bb = typeof bookBeta === "function" ? bookBeta() : NaN;
          sz.append(h("strong", null, "Cross-checks, not the call: "), document.createTextNode(cross.join("; ") + `. The call is the decision engine's gated output; the other rules are shown so no desk can seem to disagree with it.`));
          if (fin(bb)) sz.append(document.createTextNode(` In book terms: the engine sizes the index, and the model book's weighted beta is about ${fx(bb, 2)} on measured betas, so ${xx(N.exposure)} of the book is about ${fx(bb * N.exposure, 1)}x market beta plus an unsized AI factor (the Fundamentals desk measures the factor betas when the book run has data). `), evTag("est"));
        }
      } catch (e) { /* the sizing line is optional */ }
    }
    // what changed and why it matters
    const ch = $("#t7-changes"), items = todayChanges(I, TD), cmp = todayCompare(items, latestDataDate());
    ch.replaceChildren();
    items.forEach((c) => {
      const li = h("li"), top = h("div", "t7-what");
      top.append(h("strong", null, c.what), evTag(c.k, c.live ? "latest available" : "as shipped with this version"));
      const a = h("a", null, "Details →"); a.href = c.href;
      const v = h("span", "t7-v num", `${c.v} · ${c.d}`), was = cmp.prev && cmp.prev.vals[c.id];
      if (was && was !== c.v) v.append(h("span", "t7-was", ` · was ${was} on ${isoNice(cmp.prev.asof)}`));
      li.append(top, v, h("span", "t7-why", c.why), a);
      ch.append(li);
    });
    const q = $("#t7-quiet");
    if (q) q.textContent = cmp.note;
    const R = RZ_LAST || runReasoner(false);
    // what would reverse it
    const rv = $("#t7-reverse");
    rv.replaceChildren();
    const rows = [[`TLT hedge back on`, `correlation at −0.10 or below (now ${sgn2(I.corr.v)})${fin(HL.line) ? ` and 36-month inflation below ${fx(HL.line * 100, 2)}%` : ""}`],
      ["Inflation sleeve back to 2%", `36-month inflation below 2.75% (now ${pctPts(I.infl.avg36)}) and Brent below $${fx(1.3 * I.oilAvg5, 0)}`]];
    const top = R.voi && R.voi.signals[0];
    if (top && top.evsi_bp > 1) rows.push(["Most worth learning", `${top.name}: ${fx(top.evsi_bp, 0)}bp of certainty-equivalent return over three months`]);
    rows.forEach(([k, v]) => { const li = h("li"); li.append(h("b", null, k), h("span", null, v)); rv.append(li); });
    // can I trust it
    const tr = $("#t7-trust");
    tr.replaceChildren();
    const fresh = [["Market data", I.vix.live ? isoNice(I.vix.d) : "as of Oct 23, 2026"], ["Research", `${readF().panel.end}, line ${HL.status.replace(/_/g, " ")}`],
      ["Filings", FUND.note || FUND.as_of], ["Book", LIVE.report && LIVE.report.summary ? `engine run ${isoNice(LIVE.report.summary.as_of)}${adjTxt(LIVE.report.summary.adjustments)}` : "model book, as shipped"]];
    fresh.forEach(([k, v]) => { const li = h("li"); li.append(h("b", null, k), h("span", null, v)); tr.append(li); });
    if (typeof renderLanding === "function") renderLanding();   // the call board, the stages and the counts read the same inputs
  }

  // how corporate actions were handled: the vendor's factors, or the free public table with estimated bond income
  function adjTxt(a) {
    if (!a || typeof a !== "object" || typeof a.source !== "string") return "";
    if (a.source === "databento") return "; splits and dividends from Databento";
    if (a.source === "public") return "; splits from the public table, stock dividends left out, bond-fund income estimated";
    return "";
  }
  function renderPolicyLive() {
    const box = $("#pol-live");
    if (!box) return;
    const r = LIVE.report, d = r && r.decision, S = r && r.summary;
    if (!d || !S) { box.replaceChildren(h("p", null, "The engine's decision record (inputs with dates, policy outputs, binding constraints and anything blocked) appears here after a book run. The model book needs the Databento key; until then the page applies the same policies to its snapshot.")); return; }
    const hd = d.hedge || {}, sz = d.size || {}, lim = d.limits || {};
    box.replaceChildren(h("p", null, `Engine run of ${isoNice(d.as_of)} (${S.data}): TLT ${hd.status !== "ok" ? "unavailable" : hd.on ? `on at ${fx(hd.ratio, 2)}x` : "off"}, stock-bond state ${(hd.gates && hd.gates.state && hd.gates.state.value) || "n/a"}; equity scale ${xx(sz.scale)} with ${(sz.binding || "n/a").replace(/_/g, " ")} binding; total gross ${xx(lim.total_gross)}${(lim.binding || []).length ? ` (capped by ${lim.binding.join(", ").replace(/_/g, " ")})` : ""}. Effective risk contributors ${fx(S.effective_risk_contributors, 1)}; effective independent bets ${fx(S.effective_independent_bets, 2)}. ${d.blocked && d.blocked.length ? "Blocked: " + d.blocked.join("; ") + "." : "Nothing blocked."} Trials counted for the deflated Sharpe: ${S.trials_counted || "n/a"}.${adjTxt(S.adjustments) ? ` Prices: ${adjTxt(S.adjustments).slice(2)}.` : ""}`));
  }

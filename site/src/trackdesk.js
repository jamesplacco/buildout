  /* =====================================================================================
     v0.38: THE TRACK RECORD, THE HEDGE TEST, AND THE FRONT DOOR. Reads SNAP38 (scripts/snapshot_v38.py from
     buildout/track.py and the ledger). Three records, never on one chart: the backtest (in-sample), the walk-forward
     (out-of-sample, costs charged, universe chosen point in time) and the live paper record (the hash-chained
     ledger). Then sizing as the product, the named weeks replayed, the bond hedge tested by regime against its
     alternatives, and the home page a reader can take in within a minute.
     ===================================================================================== */
  const T38 = () => (typeof SNAP38 !== "undefined" && SNAP38 && SNAP38.pit ? SNAP38 : null);
  const tP = (v, d = 1) => (fin(v) ? pctPlain(v, d) : "n/a");
  const tS = (v, d = 1) => (fin(v) ? pct(v, d) : "n/a");
  const T_ORDER = ["call", "call_short", "product", "vm_rule", "bond30", "hold"];
  const CONTACT = { name: "James Placco", links: [["LinkedIn", "https://www.linkedin.com/in/james-placco/"]] };     // set in one place

  function trackCurve(box, W, keys, title, height = 260) {
    const col = { call: "var(--accent)", call_short: "var(--s2)", product: "var(--s3)", vm_rule: "var(--s4)", bond30: "var(--s5)", hold: "var(--muted)", qqq: "var(--warn)" };
    const series = keys.filter((k) => W.curve[k]).map((k) => ({ name: k === "qqq" ? "Nasdaq-100 (QQQ)" : SNAP38.policy_name[k], color: col[k], width: k === "call" ? 2.5 : 1.5, pts: W.curve[k].map(([d, v]) => [Date.parse(d), v]) }));
    const p0 = series[0].pts;
    xyChart(box, { series, yfmt: (v) => "$" + fx(v, 2), xfmt: dateLabel, xticks: yearTicks(p0[0][0], p0[p0.length - 1][0]), label: title, height, snapXs: p0.map((p) => p[0]) });
  }

  function policyTable(table, W, which) {
    fillTable(table, ["Policy", "CAGR, net of costs", "CAGR before costs", "Volatility", "Sharpe", "Max drawdown", "Months up", "Turnover a year", "Market beta", "Rates beta", "2022"],
      T_ORDER.map((k) => { const p = W.policies[k], n = p[which], g = p.gross, ex = n.exposure || {};
        return [SNAP38.policy_name[k], tS(n.cagr), tS(g.cagr), tP(n.vol), fx(n.sharpe, 2), tP(n.maxdd, 0), tP(n.hit_month, 0), fin(n.turnover_yr) ? fx(n.turnover_yr, 1) + "x" : "n/a", fx(ex.market, 2), fx(ex.rates, 2), tS(n.y2022, 0)]; })
        .concat([["Nasdaq-100 (QQQ), for reference", tS(W.bench.cagr), tS(W.bench.cagr), tP(W.bench.vol), fx(W.bench.sharpe, 2), tP(W.bench.maxdd, 0), tP(W.bench.hit_month, 0), "", "1.00", "", tS(W.bench.y2022, 0)]]), 1);
  }

  async function saveTearsheet(btn, note) {
    const T = T38();
    if (!T || !T.tearsheet_pdf_b64) return;
    try {
      const dl = window.claude && typeof window.claude.use === "function" ? await window.claude.use("downloads") : null;
      const bytes = Uint8Array.from(atob(T.tearsheet_pdf_b64), (c) => c.charCodeAt(0));
      if (dl) { await dl.save({ filename: `buildout-tearsheet-${T.asof}.pdf`, data: new Blob([bytes]) }); note.textContent = "Saved."; return; }
      const a = h("a", null, "Open the tear sheet (PDF)"); a.href = "tearsheet.pdf"; a.target = "_blank"; a.rel = "noopener";
      note.replaceChildren(a);
    } catch (e) {
      note.textContent = e && e.code === "declined" ? "Not saved." : "The download could not start here; the PDF is in the repository as site/tearsheet.pdf.";
    }
  }

  function renderTrack() {
    const T = T38(), tiles = $("#tr-tiles");
    if (!tiles) return;
    if (!T) { tiles.replaceChildren(h("p", "empty", "The track record is not in this build.")); return; }
    const W = T.pit, C = W.policies.call, CS = W.policies.call_short, Hd = W.policies.hold, L = T.live, V = T.ledger && T.ledger.verify;
    rsKpi(tiles, [
      [String(L.calls || 0), "Calls in the ledger", V && V.ok ? `hash chain verified; the first governs from ${isoNice((T.ledger.entries[0] || {}).effective_from)}` : "ledger does not verify"],
      [fx(C.net.sharpe, 2), "Walk-forward Sharpe, the call", `${isoNice(C.net.from)} to ${isoNice(C.net.to)}, net of costs; holding: ${fx(Hd.net.sharpe, 2)}`],
      [tP(C.net.maxdd, 0), "Worst drawdown, the call", `holding the book: ${tP(Hd.net.maxdd, 0)}; the Nasdaq-100: ${tP(W.bench.maxdd, 0)}`],
      [tS(C.net.y2022, 0), "2022, the call", `holding: ${tS(Hd.net.y2022, 0)}; with the Nasdaq-100 short: ${tS(CS.net.y2022, 0)}`]]);
    // the three records
    const bt = T.backtest;
    fillTable($("#tr-three"), ["Record", "What it is", "Span", "Reading", "Can it have been fitted?"], [
      ["1. Backtest", `The full-history size (${xx(bt.size)}, ${bt.binding.replace(/_/g, " ")} binding) applied to the same history, on today's nine names`, `${isoNice(bt.stats.from)} to ${isoNice(bt.stats.to)}`, `CAGR ${tS(bt.stats.cagr)}, volatility ${tP(bt.stats.vol)}, worst drawdown ${tP(bt.stats.maxdd, 0)}`, "Yes: the names and the size were both chosen knowing the history"],
      ["2. Walk-forward", "Size and hedge recomputed at every month-end from data to that close, held the next month, costs charged, universe chosen point in time", `${isoNice(C.net.from)} to ${isoNice(C.net.to)}`, `CAGR ${tS(C.net.cagr)}, volatility ${tP(C.net.vol)}, worst drawdown ${tP(C.net.maxdd, 0)}, Sharpe ${fx(C.net.sharpe, 2)}`, "Only through the design: the rules and the limits were set in 2026"],
      ["3. Live paper", "The calls written to the hash-chained ledger before the next bar, marked as prices arrive", (L.first_effective || L.first_call) ? `from ${isoNice((L.first_effective || L.first_call).slice(0, 10))}` : "starts Nov 4, 2026", L.marked_days ? `${L.marked_days} trading day${L.marked_days === 1 ? "" : "s"} marked to ${isoNice(L.last_mark || T.asof)}: ${tS(L.total, 1)}${L.stats ? `, ${tS(L.stats.cagr)} annualized` : " (too short to annualize)"}` : "No day of marks yet: the record starts now", "No: every call is timestamped before its first day"]], 1);
    $("#tr-three-p").textContent = `A portfolio manager judges an analyst by calls made in advance, sized sensibly, and honest when wrong. These are three different records and they never share a chart. The backtest shows the rule with hindsight; the walk-forward record is the honest estimate; the live record is the only one that cannot have been fitted, and it starts today.`;
    // the walk-forward record
    trackCurve($("#tr-curve"), W, ["call", "call_short", "hold", "qqq"], "Walk-forward growth of $1, net of costs, point-in-time universe");
    policyTable($("#tr-pol"), W, "net");
    $("#tr-pol-p").textContent = `Each policy is decided at a month-end close from data to that close, frozen, and held through the next month. ${W.policies.call.meta ? `The call averaged ${xx(W.policies.call.meta.avg_gross)}; the hedged variant shorted ${tP(W.policies.call_short.meta.avg_short, 0)} of NAV on average.` : ""} Costs: stocks ${SNAP38.cost.stock_bp} bp per dollar traded, futures ${SNAP38.cost.fut_bp} bp a trade plus ${SNAP38.cost.roll_bp_q} bp a quarter to roll, borrowing above 1.00x at cash plus ${fx(SNAP38.cost.borrow_spread * 1e4, 0)} bp. The "before costs" column shows what they take.`;
    // survivorship
    const sv = T.survivorship, mem = T.members, yrs = Object.keys(mem).sort();
    const gapPts = sv.gap_cagr * 100, Hh = T.hindsight.policies.hold.net, Hp = W.policies.hold.net;
    $("#tr-surv-p").textContent = `Today's nine names were not the obvious nine in 2018. The walk-forward record holds, each January, the nine names with the largest trailing-year dollar volume among sixteen AI buildout candidates, using only data before that January. Holding today's nine with hindsight grew ${tS(sv.hindsight_hold_cagr)} a year; the point-in-time nine grew ${tS(sv.pit_hold_cagr)}. ${Math.abs(gapPts) < 1 ? `The return gap is ${fx(Math.abs(gapPts), 1)} points a year, close to nothing: the rule kept picking the same leaders (Nvidia, Microsoft, Amazon, Meta, Alphabet and Tesla are in every year), and the semiconductor names it held instead of today's later arrivals (Intel, Micron, AMD) roughly offset each other. Hindsight here flatters the risk more than the return: the point-in-time book fell ${tP(Hp.maxdd, 0)} at worst against ${tP(Hh.maxdd, 0)}, and ${tS(Hp.y2022, 0)} in 2022 against ${tS(Hh.y2022, 0)}.` : `A gap of ${fx(gapPts, 1)} points a year that a backtest on today's names would have claimed as skill.`} The candidate list itself was chosen in 2026, so a company that failed and left the data cannot appear: that residual bias remains, and it points the same way.`;
    fillTable($("#tr-mem"), ["Year", "The nine names held, chosen the January before"], yrs.map((y) => [y, mem[y].join(", ")]), 2);
    const H2 = T.hindsight;
    fillTable($("#tr-hind"), ["Policy, on today's nine (hindsight)", "CAGR, net", "Sharpe", "Max drawdown", "2022"], T_ORDER.map((k) => { const n = H2.policies[k].net; return [SNAP38.policy_name[k], tS(n.cagr), fx(n.sharpe, 2), tP(n.maxdd, 0), tS(n.y2022, 0)]; }), 1);
    // sizing as the product
    const SP = T.sizing_path;
    if (SP && SP.length) {
      const pts = (k) => SP.map((r) => [Date.parse(r.date), r[k]]);
      xyChart($("#tr-lev"), { series: [{ name: "Realized volatility (annual)", color: "var(--bad)", width: 1.5, pts: pts("sigma") }, { name: "Vol target size", color: "var(--s2)", width: 1.5, pts: pts("vol_target") },
        { name: "Quarter-Kelly size", color: "var(--s3)", width: 1.2, pts: pts("kelly") }, { name: "The product (smaller of the two)", color: "var(--accent)", width: 2.5, pts: pts("product") }, { name: "The limits' size", color: "var(--muted)", width: 1.2, pts: pts("size") }],
        yfmt: (v) => fx(v, 2), xfmt: dateLabel, xticks: yearTicks(pts("sigma")[0][0], pts("sigma")[SP.length - 1][0]), label: "Leverage against realized volatility, month by month", height: 260, zero: true });
      const P = W.policies.product;
      $("#tr-lev-p").textContent = `The sizing rule a fund would run: target ${tP(0.20, 0)} volatility (size = 20% divided by realized volatility), capped by a quarter of the Kelly bet at the engine's assumed drift (cash plus 5% a year per unit of beta), with a hard stop: from a ${tP(0.15, 0)} drawdown the size is halved until the drawdown is back inside ${tP(0.10, 0)}. When volatility rises, both the vol target and the Kelly size fall with it, the first as one over volatility and the second as one over its square; the chart shows the leverage coming down in 2020 and 2022 as volatility rose. Walked forward with costs: CAGR ${tS(P.net.cagr)}, Sharpe ${fx(P.net.sharpe, 2)}, worst drawdown ${tP(P.net.maxdd, 0)}, 2022 ${tS(P.net.y2022, 0)}. The honest reading: the product is too small to be the book. It averaged ${xx(P.meta.avg_gross)} gross because a quarter of Kelly at a 5% premium is tiny when volatility is near 30% (full Kelly is the premium over the variance, about 0.5x; a quarter is about 0.13x before the beta scaling), so Kelly, not the vol target, binds almost every month. Its Sharpe (${fx(P.net.sharpe, 2)}) is close to the call's (${fx(W.policies.call.net.sharpe, 2)}): it is the same bet, smaller. What it shows is the shape (size falls as volatility rises, and the stop cuts in a drawdown); the fraction was set from the rule of thumb before the test and was not tuned to it.`;
    }
    // the weeks
    const wk = $("#tr-weeks"); wk.replaceChildren();
    (T.weeks || []).forEach((w) => {
      const keys = ["call", "call_short", "product", "bond30", "hold", "qqq"];
      const t = h("table", "rs-table");
      const box = h("div", "tablewrap"); box.append(t);
      const sec = h("div", "tr-week"); sec.append(h("h3", null, `${w.week}: ${isoNice(w.from)} to ${isoNice(w.to)}`), box);
      wk.append(sec);
      fillTable(t, ["Policy"].concat(w.days.map((d) => d.slice(5))).concat(["The week"]), keys.filter((k) => w.policies[k]).map((k) => [k === "qqq" ? "Nasdaq-100 (QQQ)" : SNAP38.policy_name[k]].concat(w.policies[k].daily.map((v) => tS(v, 1))).concat([tS(w.policies[k].week, 1)])), 1);
    });
    // the ledger
    const E = (T.ledger && T.ledger.entries) || [];
    fillTable($("#tr-ledger"), ["#", "Written (UTC)", "Data through", "Governs from", "Size", "Binding limit", "Menu", "Hash"], E.map((e) => [String(e.seq), e.ts_utc.replace("T", " ").replace("Z", ""), isoNice(e.data_asof), isoNice(e.effective_from), xx(e.call.size), e.call.binding.replace(/_/g, " "),
      e.call.menu_low && e.call.menu_high ? `${xx(e.call.menu_low.gross)} unhedged to ${xx(e.call.menu_high.gross)} with ${tP(e.call.menu_high.short, 0)} short` : "", e.hash.slice(0, 12)]), 3);
    $("#tr-ledger-p").textContent = `Every call the engine makes is appended to ledger/calls.jsonl before the next bar and committed by the daily run, so git's history timestamps it twice. Each entry's SHA-256 hash covers its content and the previous entry's hash: editing or deleting any past line breaks every hash after it, and python -m buildout ledger verify says so. A call governs from the first trading day after it is written, never earlier. ${V ? (V.ok ? `Chain verified: ${V.entries} ${V.entries === 1 ? "entry" : "entries"}, head ${String(V.head).slice(0, 12)}.` : "The chain does not verify.") : ""}`;
    const btn = $("#tr-pdf"), note = $("#tr-pdf-note");
    if (btn && !btn._bound) { btn._bound = true; btn.addEventListener("click", () => saveTearsheet(btn, note)); }
  }

  function renderHedgeTest() {
    const T = T38(), tiles = $("#ht-tiles");
    if (!tiles) return;
    if (!T || !T.regimes) { tiles.replaceChildren(h("p", "empty", "The hedge study is not in this build" + (T && T.hedge_study_error ? `: ${T.hedge_study_error}` : "") + ".")); return; }
    const R = T.regimes.rows, find = (n) => R.find((r) => r.regime === n) || {};
    const A = T.alternatives, RW = T.regime_walk, BH = T.book_hedges;
    const cut = (v) => (fin(v) ? (v < 0 ? `added ${tP(-v, 0)} to` : `cut ${tP(v, 0)} of`) : "n/a");
    const lo = find("Inflation below 3%"), hi = find("Inflation above 3%"), e2 = find("2000 to 2020"), r22 = R.find((r) => /^2021 to/.test(r.regime)) || {};
    rsKpi(tiles, [
      [sgn2(lo.corr), "Stock-bond correlation, inflation below 3%", `${lo.months} months since ${T.regimes.from.slice(0, 4)}; a 30% bond ${cut(lo.var_cut_30)} stock variance`],
      [sgn2(hi.corr), "Stock-bond correlation, inflation above 3%", `${hi.months} months; the 30% bond ${cut(hi.var_cut_30)} stock variance: the hedge fails here`],
      [sgn2(r22.corr), r22.regime || "Since 2021", `${r22.months} months, two thirds of them with inflation above 3%: the 30% bond ${cut(r22.var_cut_30)} stock variance${fin(r22.var_cut_minvar) ? `; the best weight ${cut(r22.var_cut_minvar)} it` : ""}`],
      RW && RW.summary ? [tS(RW.summary.regime_switching.y2022, 0), "2022, regime-switching bond hedge", `book unhedged ${tS(RW.summary.book.y2022, 0)}; static 30% bond ${tS(RW.summary.static30.y2022, 0)}`] : ["n/a", "Regime hedge", ""]]);
    const regRead = `Read it plainly: the bond hedged stocks from 2000 to 2020 (correlation ${sgn2(e2.corr)}) and whenever inflation was below 3%; it failed from 1962 to 1999 and whenever inflation was above 3% (${sgn2(hi.corr)}), where a 30% bond added risk. Since 2021 the correlation has been ${sgn2(r22.corr)}${r22.corr > 0 ? ", bonds falling with stocks," : ", but the bond has been volatile enough that"} and a 30% position ${cut(r22.var_cut_30)} stock variance${fin(r22.bond_in_selloffs) ? `; in the ${r22.selloffs} months the S&P fell more than 5% the bond returned ${tS(r22.bond_in_selloffs, 1)} on average` : ""}. TLT loses in the regime the book has been in.`;
    fillTable($("#ht-reg"), ["Regime", "Months", "Correlation", "Variance cut, 30% bond", "Variance cut, best bond weight", "Best weight", "Bond return in stock selloffs", "Selloff months"],
      R.map((r) => [r.regime, String(r.months), sgn2(r.corr), tS(r.var_cut_30, 0), tS(r.var_cut_minvar, 0), fx(Math.max(r.minvar_weight, 0), 2), tS(r.bond_in_selloffs, 1), String(r.selloffs)]), 1);
    $("#ht-reg-p").textContent = `Monthly, ${T.regimes.from} to ${T.regimes.to}: Shiller's S&P Composite with dividends against a 10-year Treasury (carry plus the price change of a par bond). Inflation direction compares CPI inflation with a year earlier; policy direction is the six-month change in the 3-month rate expected by the rate futures (since 1984), a proxy for whether the Fed is tightening or easing. A "selloff" is a month the S&P fell more than 5%. The 30% column is the old TLT rule: where it is negative, the hedge added risk. ${regRead}`;
    if (A) {
      const ks = Object.keys(A.labels);
      fillTable($("#ht-alt"), ["Regime", "Months", "Down months"].concat(ks.map((k) => A.labels[k])), A.rows.map((r) => [r.regime, String(r.months), String(r.down_months)].concat(ks.map((k) => { const x = r.h[k]; return k === "cash" ? "0.0%" : x && fin(x.down) ? `${tS(x.down, 1)} (cuts ${tP(Math.max(x.var_cut, 0), 0)})` : "n/a"; }))), 3);
      $("#ht-alt-p").textContent = `Monthly, ${A.from} to ${A.to}, on the futures record: each hedge's average return in the months the Nasdaq-100 future fell more than 3%, and in brackets the share of the Nasdaq-100's variance it removes at its best weight in that regime. The put is modelled (one month, 90% strike, priced at the VIX times 1.25), not traded; cash is cutting size, which removes risk one for one and pays nothing in a selloff. ${BH ? `On the book's own months (${BH.from} to ${BH.to}), a short basket of the three weakest AI names returned ${tS(BH.short_weak.down, 1)} in the book's ${BH.down_months} months down more than 5% (correlation with the book ${sgn2(BH.short_weak.corr)}), against ${tS(BH.long_bond.down, 1)} for the long bond; but the basket costs ${tS(BH.short_weak.mean_ann, 0)} a year to hold, because the weak names rose too.` : ""} ${(() => { const y = A.rows.find((r) => r.regime === "2022"), t = A.rows.find((r) => r.regime === "Policy tightening"), e = A.rows.find((r) => r.regime === "Policy easing"); if (!y || !t || !e) return ""; return `Where TLT loses: in tightening the long bond averaged ${tS(t.h.long_bond.down, 1)} in the Nasdaq-100's down months, against ${tS(e.h.long_bond.down, 1)} in easing, and in 2022 ${tS(y.h.long_bond.down, 1)}; the modelled put was ${tS(y.h.put.down, 1)} in 2022 and cut ${tP(Math.min(...A.rows.map((r) => r.h.put.var_cut)), 0)} to ${tP(Math.max(...A.rows.map((r) => r.h.put.var_cut)), 0)} of variance in every regime, at a premium. The 2-year note helped only in easing (it cut ${tP(e.h.ZT.var_cut, 0)} of variance there, ${tP(Math.max(t.h.ZT.var_cut, 0), 0)} in tightening); gold's down-month returns were small and it removed ${tP(Math.max(...A.rows.map((r) => r.h.GC.var_cut || 0)), 0)} of variance at most.`; })()}`;
    }
    if (RW && RW.summary) {
      const S = RW.summary;
      fillTable($("#ht-walk"), ["Policy, walked forward on the book's months", "Volatility", "Worst month", "Worst drawdown", "2022"], [["Book, unhedged", S.book], ["Static 30% long bond", S.static30], ["Bond weight chosen by regime", S.regime_switching]].map(([n, s]) => [n, tP(s.vol), tS(s.worst, 1), tP(s.maxdd, 0), tS(s.y2022, 0)]), 1);
      $("#ht-walk-p").textContent = `Each month-end the regime is read (inflation direction, policy direction) and the bond weight is set to the best weight in past months of the same regime only, from the long record before the decision, floored at zero. On average the weight was ${fx(RW.avg_weight, 2)} and it was zero in ${tP(RW.share_off, 0)} of months: the rule turns the bond hedge off in the regimes where it failed. ${S.regime_switching.y2022 > S.static30.y2022 ? `In 2022 it beat the static rule (${tS(S.regime_switching.y2022, 0)} against ${tS(S.static30.y2022, 0)}), ${Math.abs(S.regime_switching.y2022 - S.book.y2022) < 0.01 ? "but only by switching itself off: it matched the unhedged book" : "and the unhedged book"}.` : "In 2022 it did not beat the static rule."} Over the whole span its volatility (${tP(S.regime_switching.vol)}) and worst drawdown (${tP(S.regime_switching.maxdd, 0)}) were ${S.regime_switching.vol <= S.book.vol ? "slightly better than" : "no better than"} the unhedged book's (${tP(S.book.vol)}, ${tP(S.book.maxdd, 0)}): a regime rule avoids the bond's damage, it does not add protection. The Nasdaq-100 short still removes far more of this book's risk than any bond weight; the regime rule decides whether the bond belongs beside it.`;
    }
  }

  function renderHome() {
    const T = T38(), box = $("#hm-perf");
    if (!box) return;
    const N = typeof DX19 !== "undefined" && DX19 && DX19.now ? DX19.now : null, BC = N && typeof bookCall === "function" ? bookCall(N) : null;
    $("#hm-call").textContent = BC && BC.menu ? `Hold ${xx(BC.menu.lo.gross)} of the book, or ${xx(BC.menu.hi.gross)} with ${pct0(BC.menu.hi.short)} of NAV short Nasdaq-100 futures. No bond hedge.` : "The call is on the Desk.";
    $("#hm-why").textContent = BC ? `${(BC.bindingName || "the binding limit").replace(/^the /, "The ")} sets the size, measured on the nine names' own risk; the forecast has not earned the right to move it. Long bonds stay off while stocks and bonds fall together.` : "";
    const wh = $("#hm-when"), B = typeof B30 === "function" ? B30() : null;
    if (wh && B) {
      const E0 = (T38() && T38().ledger && T38().ledger.entries) || [], ent = E0.filter((e) => e.data_asof === B.asof).pop();
      const bd = (a, b) => { let n = 0; const d = new Date(a + "T12:00:00Z"), e = new Date(b + "T12:00:00Z"); while (d < e) { d.setUTCDate(d.getUTCDate() + 1); if (d.getUTCDay() % 6) n++; } return n; };
      const age = bd(B.asof, new Date().toISOString().slice(0, 10));
      wh.textContent = `On prices through ${isoNice(B.asof)}${ent ? `; logged in the ledger, in force from ${isoNice(ent.effective_from)}` : ""}.${age > 3 ? ` This build's call is ${age} business days old: the Track record and the published site carry newer ones.` : ""}`;
      wh.classList.toggle("hm-stale", age > 3);
    }
    const ct = $("#hm-contact");
    ct.replaceChildren();
    CONTACT.links.forEach(([k, u]) => { const a = h("a", null, k); a.href = u; a.target = "_blank"; a.rel = "noopener"; ct.append(a); });
    const btn = $("#hm-pdf"), note = $("#hm-pdf-note");
    if (btn && !btn._bound) { btn._bound = true; btn.addEventListener("click", () => saveTearsheet(btn, note)); }
    if (!T) { box.replaceChildren(h("p", "empty", "The track record is not in this build.")); return; }
    const W = T.pit, C = W.policies.call, Hd = W.policies.hold.net, Q = W.bench, L = T.live, E = (T.ledger && T.ledger.entries) || [];
    $("#hm-asof").textContent = "Data through " + isoNice(T.asof);
    const fig = (v, k, note) => { const d = h("div"); d.append(h("dt", null, k), h("dd", null, v), h("p", null, note)); return d; };
    box.replaceChildren(
      fig(fx(C.net.sharpe, 2), "Sharpe ratio", `Nasdaq-100 ${fx(Q.sharpe, 2)}; holding the book ${fx(Hd.sharpe, 2)}`),
      fig(tP(C.net.maxdd, 0), "Worst drawdown", `holding the book ${tP(Hd.maxdd, 0)}; Nasdaq-100 ${tP(Q.maxdd, 0)}`),
      fig(tS(C.net.y2022, 0), "In 2022", `holding the book ${tS(Hd.y2022, 0)}; Nasdaq-100 ${tS(Q.y2022, 0)}`),
      fig(tS(C.net.cagr, 1), "A year, compounded", `at ${xx(C.meta.avg_gross)} average exposure`),
      fig(String(L.calls || E.length || 0), "Live calls logged", E.length ? `hash-chained; the first governs from ${isoNice(E[0].effective_from)}` : "hash-chained; the record starts now"));
    $("#hm-figs-note").textContent = `Walk-forward, ${isoNice(C.net.from)} to ${isoNice(C.net.to)}: each month sized from data to that close and held the next month, costs charged, the nine names chosen point in time each January. The results of a model, not of an account. The backtest, with hindsight, is reported separately on the Track record.`;
    const cv = $("#hm-curve");
    if (cv && !cv.childElementCount) trackCurve(cv, W, ["call", "hold", "qqq"], "Walk-forward growth of $1, net of costs: the call, the book held at 1.00x, the Nasdaq-100", 230);
    const R = (T.regimes && T.regimes.rows) || [], r21 = R.find((r) => /^2021 to/.test(r.regime)) || {}, hi = R.find((r) => r.regime === "Inflation above 3%") || {};
    const A = T.alternatives, puts = A ? A.rows.map((r) => r.h.put && r.h.put.var_cut).filter(fin) : [];
    const items = [
      [sgn2(r21.corr), "Long Treasuries have stopped hedging", `Since 2021 stocks and bonds have moved together; a 30% bond position ${fin(r21.var_cut_30) && r21.var_cut_30 < 0 ? `added ${tP(-r21.var_cut_30, 0)} to` : "barely changed"} stock variance. Since 1962 bonds hedged below 3% inflation and failed above it (correlation ${sgn2(hi.corr)}).`, "#hedgetest", "Hedge test"],
      [`${tP(Hd.maxdd, 0)} to ${tP(C.net.maxdd, 0)}`, "Limits, not forecasts, made the record", `A Sharpe ratio of ${fx(C.net.sharpe, 2)} against ${fx(Hd.sharpe, 2)} for holding the book, with the worst drawdown cut by more than half: size falls when the book's own risk rises, before the loss, not after.`, "#track", "Track record"],
      [puts.length ? `${tP(Math.min(...puts), 0)} to ${tP(Math.max(...puts), 0)}` : "n/a", "Puts held up in every regime", `A modelled one-month, 90% put on the Nasdaq-100 removed that share of its variance in every inflation and policy regime since 2000, and, of the overlays that add to the book (bonds, 2-year notes, gold, puts), was the only one that paid in 2022; the call's own hedge, a Nasdaq-100 short, did more. It costs a premium; the bond's failure costs more.`, "#hedgetest", "Hedge test"]];
    const ol = $("#hm-find"); ol.replaceChildren();
    items.forEach(([big, t, p, href, lab]) => { const li = h("li"), a = h("a", null, lab); a.href = href; li.append(h("span", "hm-big", big), h("h3", null, t), h("p", null, p), a); ol.append(li); });
  }


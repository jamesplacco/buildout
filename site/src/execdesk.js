  /* execdesk.js (v0.39): the VIX as a hedge (on the Hedge test desk) and the Execution desk: the call as a ticket for a
     Robinhood Agentic account. The targets here follow buildout/execution.py's target() line for line. */
  const EX_DEFAULT = { vix_share: 0.05, max_gross: 0.98, vix_symbol: "VIXY", short_symbol: "PSQ" };

  function exTarget(call, variant, P = EX_DEFAULT) {
    let vix = Math.max(0, P.vix_share);
    const room = P.max_gross - vix;
    const ok = (call.frontier || []).filter((r) => r.meets !== false && r.short != null && r.gross != null);   // rows that meet every limit only
    const fr = (ok.length ? ok : [{ gross: call.size, short: 0 }]).slice().sort((a, b) => a.gross - b.gross);
    let g = fr[0].gross, s = fr[0].short || 0;
    if (variant === "hedged") {
      for (let i = 0; i + 1 < fr.length; i++) {
        const a = fr[i], b = fr[i + 1];
        if (b.gross + b.short <= room) { g = b.gross; s = b.short; continue; }
        const da = a.gross + a.short, db = b.gross + b.short;
        if (da <= room && room < db) { const t = (room - da) / (db - da); g = a.gross + t * (b.gross - a.gross); s = a.short + t * (b.short - a.short); }
        break;
      }
    }
    if (g > room) vix = Math.max(0, P.max_gross - g);
    if (g + s + vix > P.max_gross) g = Math.max(0, P.max_gross - s - vix);     // clipped to what a cash account can hold, as in execution.target()
    return { gross: g, short: s, vix };
  }

  function renderExecution() {
    const call = typeof B30 === "function" ? B30() : null;
    const W = (call && call.weights) || {};
    const U = call ? exTarget(call, "unhedged") : null, Hd = call ? exTarget(call, "hedged") : null;
    rsKpi($("#ex-tiles"), [
      [U ? xx(U.gross) : "n/a", "The book, unhedged", call ? `the call's size on data through ${isoNice(call.asof)}` : ""],
      [Hd ? xx(Hd.gross) : "n/a", "The book, hedged", Hd ? `with ${pct0(Hd.short)} in PSQ, the most a cash account allows` : ""],
      [pct0(EX_DEFAULT.vix_share), "VIX sleeve (VIXY)", "of the account, on by default; 0 turns it off"],
      ["0", "Orders Buildout can place", "Robinhood's MCP places them, after approval"]]);
    $("#ex-map-p").textContent = "Robinhood's Agentic account (support pages read Nov 5, 2026) allows long stocks and ETFs, single-leg long options, and market, limit and stop orders. It does not allow margin borrowing, short selling, futures or multi-leg options. So the call's Nasdaq-100 futures short becomes a long position in an inverse ETF, and everything long stays under the account's equity.";
    fillTable($("#ex-map"), ["The call says", "In the Agentic account", "The difference"], [
      ["Hold the nine names at the call's size", "The nine names, long, at that share of equity", "None, at sizes up to 0.98x"],
      ["Short Nasdaq-100 futures (hedged)", "PSQ, long (ProShares Short QQQ, -1x daily)", "Daily reset and a 0.95% fee; the book plus PSQ must fit in the cash"],
      ["Hold the VIX sleeve", "VIXY, long (short-term VIX futures)", "The futures roll cost studied on the Hedge test desk"],
      ["Above 1.00x (the call's full-size menu)", "Not possible", "No margin borrowing for agents"],
      ["Index puts, VIX calls", "Allowed by Robinhood, not automated here", "The planner trades shares only"]], 3);
    const syms = Object.keys(W);
    const rows = syms.map((k) => [k, pctPlain(U.gross * W[k], 1), pctPlain(Hd.gross * W[k], 1)]);
    if (U) {
      rows.push(["PSQ (index short)", pctPlain(U.short, 1), pctPlain(Hd.short, 1)], ["VIXY (VIX sleeve)", pctPlain(U.vix, 1), pctPlain(Hd.vix, 1)], ["Cash", pctPlain(1 - U.gross - U.short - U.vix, 1), pctPlain(1 - Hd.gross - Hd.short - Hd.vix, 1)]);
      fillTable($("#ex-tgt"), ["Holding", "Unhedged (default)", "Hedged"], rows, 1);
      const TT = typeof T38 === "function" ? T38() : null, PP = TT && TT.pit && TT.pit.policies;
      const rec = PP && PP.call && PP.call_short ? ` Which variant? The walk-forward record favours the hedge: full size with the call's short earned a Sharpe of ${fx(PP.call_short.net.sharpe, 2)} against ${fx(PP.call.net.sharpe, 2)} for the call as sized. A cash account can hold only part of that hedge, so the hedged variant here is a partial version of it.` : "";
      $("#ex-tgt-p").textContent = `From the call on data through ${isoNice(call.asof)}: the unhedged variant holds the book at ${xx(U.gross)}, the smallest size every limit allows. The hedged variant walks the call's menu (more book, more index short) until the book, PSQ and the VIX sleeve fill 98% of the account: ${xx(Hd.gross)} of book with ${pct0(Hd.short)} in PSQ. Whole shares and limit orders, so the account will sit a little under these.${rec}`;
    }
    fillTable($("#ex-chk"), ["Check", "Default", "Why"], [
      ["Not halted", "private/HALT or BUILDOUT_TRADING_HALT", "one switch stops every ticket"],
      ["Agentic account only", "account type must say Agentic", "Robinhood lets agents trade nothing else; the planner refuses too"],
      ["The call's data is fresh", "at most 3 business days old", "no trading on a stale call"],
      ["The call is in the ledger", "the verified ledger holds this data date", "every position change is logged before it trades"],
      ["Allowlist", "the nine names, PSQ, VIXY", "an unknown holding blocks the ticket rather than being traded around"],
      ["Quotes and spreads", "every symbol quoted; spreads under 1%", "limit prices from live quotes, 10 bp through the touch"],
      ["No short sale", "a sale at most what is held", "the account cannot be short"],
      ["No borrowing", "everything long at most 98% of equity; cash at least 2%", "no margin in the Agentic account"],
      ["Order size", "each order at most 25% of equity and $25,000", "a fat-finger cap"],
      ["Turnover", "at most 60% of equity (100% for a first build)", "a rebalance, not a rebuild"],
      ["Once a day", "one executed ticket a day", "no loops"],
      ["Expiry and approval", "15 minutes; the person approves the ticket id", "the quotes and the person both have to be current"]], 3);
  }

  function renderTrader() {
    fillTable($("#ex-modes"), ["Mode", "What happens to a ticket that passes every check", "Who decides"], [
      ["manual (default)", "Staged. It executes on a later pass only after the person approves its id (approve_ticket or trader --approve), within the approval's life.", "The person, every time"],
      ["supervised", "Staged. It executes once approved, or at once under a standing approval the person gave for a window (trader --standing 120).", "The person, in advance"],
      ["autonomous", "Executes without asking, if the mandate is armed. The person reads the digest and the journal; the HALT file stops it.", "The mandate"]], 3);
    fillTable($("#ex-routes"), ["Route", "Who places the orders", "Credential", "Status"], [
      ["paper", "The paper broker fills at the quote plus the collar in a model account.", "None", "Running: the public paper bot below, and private rehearsals"],
      ["assistant", "The assistant holding Robinhood's Trading MCP (Claude with the Robinhood connector) places what the trader hands it and reports fills through record_fills.", "Robinhood's OAuth, held by the assistant", "Works today; every order is one the trader wrote"],
      ["robinhood_mcp", "Buildout's own JSON-RPC client on Robinhood's Trading MCP, with OAuth in the standard library.", "Robinhood's OAuth, tokens in private/", "Built; the tool names Robinhood has not published are filled in from `broker probe`; untested against the live endpoint"]], 4);
    $("#ex-tr-n").textContent = "The evidence gate (v0.42.4, in code): a live broker trades in manual mode, whatever the mandate says, until the paper bot has held a position for 60 trading days and 5 live tickets have filled after an approval of their own id. Robinhood's own terms (support pages read Nov 8, 2026): an external agent trades only in the Agentic account; it can act without confirmation if the person has asked it to; and the person is responsible for the trades it places. The trader's modes sit inside those terms: manual and supervised keep the confirmation on Buildout's side, autonomous removes it under the mandate.";
    fillTable($("#ex-mandate"), ["Term", "Default", "What it does"], [
      ["mode", "manual", "manual, supervised or autonomous"], ["armed", "false", "a live broker sends nothing until true, in every mode, over signed_by and signed_on"], ["broker", "paper", "paper, assistant or robinhood_mcp"],
      ["max_order_usd / max_order_pct", "$10,000 / 25%", "one order at most this much"], ["max_day_turnover_pct", "60%", "one day's notional (a first build is exempt)"],
      ["max_gross / cash_floor", "98% / 2%", "everything long at most 98% of equity; no borrowing"], ["max_equity_usd", "$250,000", "above this the trader refuses: the mandate was written for less"],
      ["halt_drawdown / halt_day_loss", "20% / 5%", "from the account's recorded peak, or from the previous day: the trader stops"],
      ["min_days_between_tickets", "1", "a rebalance, not a loop"], ["approval_ttl_min", "240", "how long an approval stays good"], ["window", "09:45 to 15:45 New York, weekdays", "when a pass may act"],
      ["quiet_days", "none", "dates to sit out"], ["notes", "", "required for an armed autonomous mandate: why unattended trading is wanted"]], 3);
    const T = typeof T38 === "function" ? T38() : null, Pp = T && T.paper;
    const has = !!(Pp && Array.isArray(Pp.equity_history) && Pp.equity_history.length);
    $("#ex-pb-grid").hidden = !has; $("#ex-pb-jp").hidden = !has;
    if (!has) {
      $("#ex-pb-p").textContent = "The paper bot starts with the first weekday run after v0.42 ships: each morning before the open the daily workflow runs one pass of the trader against a $100,000 model account, unhedged and without the VIX sleeve (PSQ and VIXY are not in the price mirror), filled at the prior close plus a 5 bp half-spread and the 10 bp collar. Its state is committed in paper/ and summarized to data/paper.json, which this section reads.";
      rsKpi($("#ex-pb-tiles"), [["$100,000", "Opening cash", "the model account"], ["0", "Tickets filled", "none yet"], ["autonomous", "Mode", "paper broker, under a wide mandate"], ["weekdays", "Cadence", "one pass a day, 6:17 New York"]]);
      $("#ex-pb-n").textContent = "Not a personal account; nothing here is advice.";
      return;
    }
    const eq = Pp.equity_history, first = eq[0][1], last = eq[eq.length - 1][1], ret = last / Pp.start_cash - 1;
    rsKpi($("#ex-pb-tiles"), [[`$${Math.round(last).toLocaleString()}`, "Equity", `${ret >= 0 ? "+" : MINUS}${Math.abs(ret * 100).toFixed(2)}% since ${isoNice(Pp.opened)}`],
      [String(Pp.tickets_filled), "Tickets filled", `${Pp.passes} passes; fills chain ${Pp.fills_chain && Pp.fills_chain.ok ? "verified" : "BROKEN"}`],
      [`${Math.round((1 - Pp.cash / last) * 100)}%`, "Invested", `cash $${Math.round(Pp.cash).toLocaleString()}`],
      [isoNice(Pp.marks_asof), "Marked at the close of", Pp.last ? `last pass: ${Pp.last.outcome || Pp.last.event}` : ""]]);
    $("#ex-pb-p").textContent = `${Pp.note} ${Pp.mode}.`;
    const lD = (s) => { const d = new Date(s + "T00:00:00Z"); return d.getUTCFullYear() + (d.getUTCMonth() + (d.getUTCDate() - 1) / 31) / 12; };
    xyChart($("#ex-pb-curve"), { height: 180, label: "Equity, $", series: [{ pts: eq.map(([d, v]) => [lD(d), v]), color: "var(--s1)", name: "Paper account" }],
      xticks: eq.length > 1 ? [[lD(eq[0][0]), isoNice(eq[0][0]).replace(/, \d{4}$/, "")], [lD(eq[eq.length - 1][0]), isoNice(eq[eq.length - 1][0]).replace(/, \d{4}$/, "")]] : [[lD(eq[0][0]), isoNice(eq[0][0])]],
      yfmt: (v) => `$${Math.round(v / 1000)}k` });
    fillTable($("#ex-pb-pos"), ["Symbol", "Shares"], (Pp.positions || []).map((p) => [p.symbol, String(p.quantity)]), 1);
    fillTable($("#ex-pb-j"), ["When (UTC)", "Event", "Outcome", "Ticket", "Fills"], (Pp.recent || []).map((r) => [r.ts_utc, r.event, r.outcome || r.status || "", r.ticket || "", r.fills != null ? String(r.fills) : ""]), 4);
    $("#ex-pb-n").textContent = "Not a personal account; nothing here is advice. The account is marked at the last close in the price mirror.";
  }

  function renderVix() {
    const T = typeof T38 === "function" ? T38() : null, V = T && T.vix;
    if (!V) { $("#vx-p").textContent = "The VIX study is not in this build."; return; }
    const R = V.regimes, all = R[0], yr = (y) => R.find((r) => r.regime === y);
    const B = V.book.rows, row = (h, s) => B.find((r) => r.hedge === h && Math.abs(r.share - s) < 1e-9) || {};
    const none = row("none", 0), f10 = row("vix_fut", 0.1), f05 = row("vix_fut", 0.05), s25 = row("nq_short", 0.25);
    rsKpi($("#vx-tiles"), [
      [sgn2(all.h.vix_fut.corr), "VIX futures against the Nasdaq-100", `monthly, ${V.from} to ${V.to}; they cut ${tP(all.h.vix_fut.var_cut, 0)} of its variance at the best weight`],
      [tS(V.carry.ann_all, 0), "What holding them costs, a year", `on average; they lost money in ${tP(V.carry.share_months_negative, 0)} of months`],
      [`${tS(none.y2020q1, 0)} to ${tS(f10.y2020q1, 0)}`, "The book, Feb 19 to Mar 23, 2020", `with 10% of its value in VIX futures; ${f10.cagr_cost > 0 ? `${tP(f10.cagr_cost, 1)} a year of growth given up` : `growth ${tS(-f10.cagr_cost, 1)} a year higher on these days, a window that holds the Feb 2018 and Mar 2020 spikes`}`],
      [`${tS(none.y2022, 0)} to ${tS(f10.y2022, 0)}`, "The book in 2022, the same hedge", `the slow bear: a 25% index short took it to ${tS(s25.y2022, 0)}`]]);
    $("#vx-p").textContent = `The VIX rises when stocks fall, so owning it looks like the natural hedge for an AI book. The record says it is a crash hedge, not a bear-market hedge. VIX futures (what VIXY holds) paid in the fast falls (2008, March 2020) and cost about ${tP(-V.carry.ann_all, 0)} a year on average the rest of the time, because the futures sit above the spot VIX in calm markets and drift down to it. In 2022 the VIX never spiked, the futures barely moved, and the hedge did almost nothing. ${f05.cagr_cost > 0 ? `Per point of one-month tail cut, VIX futures were the cheapest hedge on the book (${fx(f05.es_cut_per_cost, 1)} points of tail per point of growth at 5% of the book, against ${fx(s25.es_cut_per_cost, 1)} for a 25% index short)` : `On the book's days from ${isoNice(V.book.from)} to ${isoNice(V.book.to)}, a 5% VIX sleeve cut the one-month tail from ${tP(none.es21, 1)} to ${tP(f05.es21, 1)} and cost nothing, because those days hold two VIX spikes; that is the window's luck, not the hedge's carry, which over the longer monthly record ran near ${tS(V.carry.ann_all, 0)} a year`}, but only the index short cut the worst drawdown and 2022. The two do different jobs: the default execution keeps a 5% VIX sleeve for the crash and leaves the bear market to the call's size.`;
    const lab = { none: "No hedge", vix_fut: "VIX futures", vix_call: "VIX calls, 125% strike (modelled)", nq_put: "Nasdaq-100 puts, 90% strike (modelled)", nq_short: "Nasdaq-100 futures short" };
    fillTable($("#vx-book"), ["Hedge", "Share of the book", "One-month tail (ES 95%)", "Worst drawdown", "Feb 19 to Mar 23, 2020", "2022", "CAGR", "Tail cut per point of growth given up"],
      B.map((r) => [lab[r.hedge] || r.hedge, r.hedge === "none" ? "" : pct0(r.share), tP(r.es21, 1), tP(r.maxdd, 0), tS(r.y2020q1, 0), tS(r.y2022, 0), tS(r.cagr, 1), fin(r.es_cut_per_cost) ? fx(r.es_cut_per_cost, 2) : ""]), 2);
    $("#vx-book-n").textContent = `The point-in-time book at 1.00x, ${isoNice(V.book.from)} to ${isoNice(V.book.to)} (the VIX futures record ends in March 2024), with each hedge rebalanced monthly and marked every day. Options are priced, not traded: VIX calls by Black-76 at a volatility of volatility of 100% (at 80% they cost ${tS(V.call_vov["0.8"].ann, 0)} a year per $1 of notional, at 120% ${tS(V.call_vov["1.2"].ann, 0)}), Nasdaq-100 puts at the VIX times 1.25; half a 3% spread is paid on each side.`;
    fillTable($("#vx-reg"), ["Regime", "Months", "Down months", "VIX futures: correlation", "in down months", "variance cut", "a year", "VIX calls: in down months", "a year", "VIX index: in down months"],
      R.map((r) => [r.regime, String(r.months), String(r.down_months), sgn2(r.h.vix_fut.corr), tS(r.h.vix_fut.down, 1), tP(r.h.vix_fut.var_cut, 0), tS(r.h.vix_fut.ann, 0),
                    tS(r.h.vix_call.down, 1), tS(r.h.vix_call.ann, 0), tS(r.h.vix_index.down, 1)]), 1);
    fillTable($("#vx-wk"), ["Week", "VIX before", "VIX at the end", "High"], (V.weeks || []).map((w) => [w.week, fx(w.start, 1), fx(w.end, 1), fx(w.high, 1)]), 1);
    $("#vx-n").textContent = `The VIX index cannot be bought; its column is the ceiling a hedge could reach, not a return anyone earned. The free VIX record this build reads ends on ${isoNice(V.vix_now.date)}, when the VIX closed at ${fx(V.vix_now.level, 1)}, above ${tP(V.vix_now.pct_since_1990, 0)} of days since 1990. On Robinhood, agents cannot trade VIX futures; VIXY trades as shares, and VIX index options are listed (single-leg long options are open to agents, index options through the agent are not confirmed).`;
  }

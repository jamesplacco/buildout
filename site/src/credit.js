  /* =====================================================================================
     v0.34: THE PRIVATE CREDIT LENS, Blue Owl at the centre (buildout/private_credit.py, snapshot in snappc.js).
     Three places where stress shows before a mark moves: the repurchase queue of a non-traded fund (the 5% cap
     divided by requests is the fill rate), the listed BDC's discount to NAV (an asset markdown once the leverage is
     taken out), and the share of income paid in kind. Then the sector's default rate and its mix, how the stress
     reaches the book's names, the scorecard, what would flip the lens, and the catalysts. Every figure dated and
     sourced; nothing here is a position.
     ===================================================================================== */
  const PC = () => (typeof SNAPPC !== "undefined" && SNAPPC && SNAPPC.credit && SNAPPC.credit.scorecard) ? SNAPPC.credit : null;
  const pcP = (v, d = 1) => (fin(v) ? pctPlain(v, d) : "n/a");
  const pcUsd = (v) => (!fin(v) ? "n/a" : Math.abs(v) >= 1e9 ? "$" + fx(v / 1e9, Math.abs(v) >= 1e10 || Math.abs(Math.round(v / 1e8) % 10) === 0 ? 0 : 1) + "B" : "$" + fx(v / 1e6, 0) + "M");
  const PC_GRADE = { green: ["good", "within"], amber: ["warn", "watch"], red: ["bad", "breached"] };
  const pcPill = (g) => { const s = h("span", "verdict " + PC_GRADE[g][0], PC_GRADE[g][1]); return s; };
  const pcVal = (r) => (r.unit === "pct" ? pcP(r.value, r.value < 0.02 ? 1 : 1) : r.unit === "x" ? fx(r.value, 2) + "x" : fx(r.value, 2));

  function renderCredit() {
    const C = PC(), tiles = $("#pc-tiles");
    if (!tiles) return;
    if (!C) { tiles.replaceChildren(h("p", "empty", "The private credit lens is not in this build.")); return; }
    const S = C.stack, ow = S.manager, ob = S.listed_bdc, oc = S.flagship_fund, ot = S.technology_fund, fi = S.sector, hy = S.template_deal;
    const L = C.liquidity, M = C.marks.obdc, I = C.income, G = C.loss_gap, src = C.sources;
    const srcA = (k) => { const a = h("a", null, src[k] ? src[k].title : k); if (src[k]) { a.href = src[k].url; a.target = "_blank"; a.rel = "noopener"; } return a; };
    rsKpi(tiles, [
      [pcP(oc.requests_share, 1), "OCIC holders asking out, share of shares", `a quarter; ${pcP(L.ocic.fill, 1)} of requests filled (the 5% cap divided by the queue); OTIC ${pcP(ot.requests_share, 0)}, filled ${pcP(L.otic.fill, 1)}`],
      [pcP(M.price_to_nav, 0) + " of NAV", "OBDC, the listed fund, on its own June buybacks", `an asset markdown near ${pcP(M.implied_asset_markdown, 0)} after ${fx(M.debt_to_equity, 2)}x leverage; it books ${pcP(ob.non_accrual_fv, 1)} on non-accrual at fair value`],
      [pcP(fi.pcdr, 1), "Fitch private credit default rate", `a record, trailing twelve months to ${isoNice(fi.asof)}; ${pcP(fi.soft_share, 0)} of the events are soft (PIK, deferral, extension)`],
      [pcUsd(ow.fre_q), "Blue Owl fee-related earnings, Q3", `up ${pcP(ow.fre_q / ow.fre_q_prior_year - 1, 0)} on a year earlier; AUM ${pcUsd(ow.aum)}; the manager earns while its holders queue`]]);
    $("#pc-sub").textContent = `Private credit matters to an AI equity book for one reason: it is the marginal source of the equity and debt that build the campuses the nine names lease, and it is marked by models. Stress shows in three places before it shows in a mark. This desk reads them from Blue Owl's filings, as of ${isoNice(C.latest_observation)}, and computes what they imply.`;
    $("#pc-call").textContent = C.headline;
    // the stack
    fillTable($("#pc-stack"), ["Entity", "What it is", "Size", "The reading", "As of", "Source"], [
      [ow.name, "the manager: fees on other people's capital", pcUsd(ow.aum) + " AUM", `FRE ${pcUsd(ow.fre_q)} a quarter (${pcP(ow.fre_margin, 0)} margin), ${pcUsd(ow.raised_ttm)} raised in twelve months, realized losses in direct lending ${fx(ow.direct_lending_realized_loss_ann * 1e4, 0)} bp a year`, isoNice(ow.asof), "8-K, 10-Q, call"],
      [ob.name, "the listed BDC: the only one with a market price", pcUsd(ob.portfolio_fv) + " of loans, " + ob.companies + " companies", `NAV $${fx(ob.nav_ps, 2)} (${pcP(I.nav_change_since_2024, 1)} since end-2024); dividend cut from $${fx(ob.dividend_base_prior, 2)} to $${fx(ob.dividend_base, 2)}; non-accruals ${pcP(ob.non_accrual_cost, 1)} at cost, ${pcP(ob.non_accrual_fv, 1)} at fair value; software about ${pcP(ob.software_share_mgmt, 0)}`, isoNice(ob.asof), "8-K, 10-Q"],
      [oc.name, "the flagship non-traded fund (wealth channel)", pcUsd(oc.investments_fv) + " of loans, " + oc.companies + " companies", `${pcP(oc.requests_share, 1)} of shares asked out (from ${pcP(oc.requests_share_prior, 1)}); ${pcP(oc.fill_reported, 1)} filled; paid ${pcUsd(oc.paid_usd)} in ${oc.paid_with}; a third party offers $${fx(oc.third_party_tender_price, 2)} against $${fx(oc.nav_ps, 2)} NAV`, isoNice(oc.asof), "fund 8-Ks"],
      [ot.name, "the technology fund (software borrowers)", pcUsd(ot.portfolio_fv) + " of loans", `${pcP(ot.requests_share, 0)} of shares asked out (from ${pcP(ot.requests_share_prior, 1)}); ${pcP(ot.fill_reported, 1)} filled; NAV $${fx(ot.nav_ps, 2)}, ${pcP(C.marks.otic_nav_change_ytd, 1)} this year`, isoNice(ot.asof), "fund 8-Ks"],
      [hy.name, "the template: an off-balance-sheet campus the book's names lease", pcUsd(hy.debt_usd) + " of debt on a ~" + pcUsd(hy.asset_usd) + " asset", `Blue Owl funds own ${pcP(hy.blue_owl_share, 0)}; ${pcP(hy.ltv, 0)} loan to value, debt service covered ${fx(hy.dscr, 2)} times; Meta guarantees the residual value for ${hy.residual_guarantee_years} years`, isoNice(hy.asof), "deal reporting"],
      [fi.name, "the sector", `${fi.unique_defaulters_ttm} unique defaulters`, `${pcP(fi.pcdr, 1)} (from ${pcP(fi.pcdr_prior_q, 1)}); ${fi.events_q} events in the quarter against ${fi.events_prior_q}; software ${pcP(fi.sector["Technology software"], 1)}, industrials ${pcP(fi.sector["Industrials and manufacturing"], 1)}`, isoNice(fi.asof), "Fitch 3Q26 monitor"]], 2);
    // gauge 1: liquidity
    const q = (f, o) => [o.name.replace(/ \(.*$/, ""), pcP(o.requests_share, 1), pcP(f.cap, 0), pcP(f.fill, 1), pcP(f.fill_reported, 1), f.model_matches ? "yes" : "no", fx(f.quarters_to_90pct_exit, 1) + " quarters (" + fx(f.years_to_90pct_exit, 1) + " years)", pcP(f.left_after_4_quarters, 0)];
    fillTable($("#pc-queue"), ["Fund", "Asked out, share of shares", "Cap, a quarter", "Fill the model predicts", "Fill reported", "Match", "Time to get 90% out if the queue stays", "Still in after a year"], [q(L.ocic, oc), q(L.otic, ot)], 1);
    $("#pc-queue-p").textContent = `A non-traded BDC repurchases at most ${pcP(L.cap, 0)} of its shares a quarter, pro rata. The fill rate is the cap divided by the requests, and the model reproduces both funds' reported fills to the tenth of a point, which is the check that this is the mechanism. A holder who keeps asking exits geometrically: after n quarters (1 minus fill)^n remains. At OTIC that is ${fx(L.otic.quarters_to_90pct_exit, 0)} quarters to get nine tenths out; a third party's offer to buy OCIC shares at $${fx(oc.third_party_tender_price, 2)} prices that wait at a ${pcP(L.third_party_tender_discount, 0)} discount to NAV. Requests have fallen two quarters at OCIC and risen at OTIC, where the borrowers are software companies.`;
    // gauge 2: marks
    fillTable($("#pc-marks"), ["Measure", "Value", "How"], [
      ["OBDC price to NAV", pcP(M.price_to_nav, 1), `$${fx(M.price, 2)} (${M.basis})`],
      ["Equity discount", pcP(M.equity_discount, 1), "1 minus price to NAV"],
      ["Debt to equity", fx(M.debt_to_equity, 2) + "x", "net, June 30"],
      ["Implied asset markdown", pcP(M.implied_asset_markdown, 1), "discount divided by (1 + debt to equity): if the debt is whole, the equity discount is a markdown on all the assets"],
      ["Non-accruals the fund books", pcP(ob.non_accrual_fv, 1) + " at fair value, " + pcP(ob.non_accrual_cost, 1) + " at cost", `${ob.non_accrual_count} companies; the market's markdown is ${fx(M.multiple_of_non_accruals_fv, 0)} times the fair-value figure`],
      ["Largest non-accruals", ob.largest_non_accruals.map((x) => `${x[0]} (${x[1]}) ${pcUsd(x[2])} at cost, ${pcUsd(x[3])} marked`).join("; "), "three of the four are not software"],
      ["NAV per share", ob.nav_history.map((x) => `${x[0].slice(0, 7)}: $${fx(x[1], 2)}`).join(" · "), `${pcP(I.nav_change_since_2024, 1)} since end-2024`]], 3);
    // gauge 3: income
    fillTable($("#pc-income"), ["Measure", "Value", "How"], [
      ["Net investment income a share", "$" + fx(I.nii_ps, 2), "GAAP, Q2 2026; adjusted $" + fx(ob.nii_ps_adjusted, 2)],
      ["Dividend declared", "$" + fx(I.dividend, 2), `base $${fx(ob.dividend_base, 2)} (cut ${pcP(-I.dividend_cut, 0)} from $${fx(ob.dividend_base_prior, 2)}) plus $${fx(ob.dividend_supplemental, 2)} supplemental`],
      ["NII cover of the dividend", fx(I.cover, 2) + "x", "NII divided by the dividend"],
      ["PIK share of income", pcP(I.pik_share_income, 1), `Q2 MD&A; ${pcP(ob.pik_share_income_h1, 1)} for the half; ${pcUsd(ob.pik_usd_q)} of interest paid as more loan`],
      ["Cash cover, estimate", fx(I.cash_cover_est, 2) + "x", `NII less PIK, over the dividend; shares estimated at ${fx(I.shares_est / 1e6, 0)}M from portfolio less debt over NAV (the 10-Q's count would replace it)`]], 3);
    $("#pc-income-p").textContent = `Payment-in-kind interest is income that arrives as more loan. With it, NII covers the dividend ${fx(I.cover, 2)} times; without it the estimated cash cover is ${fx(I.cash_cover_est, 2)}. Fitch counts PIK introductions and interest deferrals as half of all default events: the ${pcP(I.pik_share_income, 1)} is where the sector's "soft" defaults live inside one fund's income statement.`;
    // the sector
    drawPcSectors(fi);
    fillTable($("#pc-mix"), ["Kind of default event", "Share of events, twelve months"], Object.entries(fi.mix).map(([k, v]) => [{ pik_or_deferral: "PIK introduced or interest deferred", maturity_extension: "Maturity extended under stress", payment_default: "Uncured payment default", bankruptcy_or_restructuring: "Bankruptcy, liquidation or out-of-court restructuring" }[k] || k, pcP(v, 0)]), 1);
    $("#pc-gap").textContent = `Both numbers are true. Blue Owl reports realized losses of ${fx(G.realized_loss_manager * 1e4, 0)} bp a year in direct lending; Fitch reports a record ${pcP(G.pcdr, 1)} default rate in the same market. The hard defaults (payment defaults and bankruptcies) are ${pcP(1 - G.soft_share, 0)} of Fitch's events, ${pcP(G.hard_default_rate, 2)} of issuers; at a ${pcP(G.severity, 0)} loss severity they cost about ${fx(G.hard_loss_at_severity * 1e4, 0)} bp a year. The other ${pcP(G.soft_share, 0)} produce no realized loss until they do. The page's unlevered direct-lending fund earns ${pcP(C.net_yield.net, 1)} net at the sector's default rate, ${pcP(-C.net_yield.over_treasury, 1)} below Treasuries: the illiquidity premium is gone at this default rate, which is why the holders queue.`;
    // the book
    const B = (typeof SNAP30 !== "undefined" && SNAP30 && SNAP30.book) ? SNAP30.book : null;
    const scn = B && (B.scenarios || []).find((s) => /financing/i.test(s.scenario));
    fillTable($("#pc-book"), ["Name", "Channel", "Exposure", "What to watch"], C.transmission.map((t) => [t.name, t.channel, t.exposure, t.watch]), 4);
    const chain = $("#pc-chain"); chain.replaceChildren(); C.chain.forEach((x) => chain.append(h("li", null, x)));
    $("#pc-book-p").textContent = scn
      ? `The book's own measurement of this lane is the engine's "${scn.scenario}" scenario (Nasdaq-100 ${pctPlain(scn.nasdaq, 0)}, semis ${pctPlain(scn.semis_vs_nasdaq, 0)} more, yields ${scn.dy_bp > 0 ? "up" : "down"} ${Math.abs(scn.dy_bp)} bp): ${pct(scn.book, 1)} for the book at 1.00x through its measured betas, ${pct(scn.with_nasdaq_hedge, 1)} with the Nasdaq-100 short that keeps every name, and ${pct(scn.with_bond_30, 1)} with the 30% bond hedge, because in this lane the bond falls with the stocks. The worst name in it is ${scn.worst_name} (${pct(scn.worst_name_move, 0)}). That is the number this lens guards.`
      : "The book engine's financing-shock scenario is not in this build.";
    // the scorecard
    const sc = $("#pc-score"); sc.replaceChildren();
    const thead = h("thead"), tr = h("tr"); ["Gauge", "Reading", "Green", "Red", "Status", "Why the thresholds"].forEach((x, i) => tr.append(h("th", i >= 1 && i <= 3 ? "r" : null, x))); thead.append(tr); sc.append(thead);
    const tb = h("tbody");
    C.scorecard.forEach((r) => {
      const row = h("tr"), f = (v) => (r.unit === "pct" ? pcP(v, r.id === "software" ? 1 : 0) : r.unit === "x" ? fx(v, 2) + "x" : fx(v, 2));
      row.append(h("td", null, r.label), h("td", "r", pcVal(r)), h("td", "r", (r.direction === "low" ? "at or below " : "at or above ") + f(r.green)), h("td", "r", (r.direction === "low" ? "at or above " : "at or below ") + f(r.red)));
      const td = h("td"); td.append(pcPill(r.grade)); row.append(td, h("td", null, r.note));
      tb.append(row);
    });
    sc.append(tb);
    $("#pc-score-p").textContent = `${C.reds} of ${C.scorecard.length} gauges are red. The thresholds are the desk's rules: the Buyside manual's "above 15% of shares asked out, widen the haircut on every private mark", the thesis's kill condition of a default rate below 3%, and cover below 1.0 meaning a second dividend cut. The one green gauge is the surprise: Fitch's software default rate is the lowest sector at ${pcP(fi.sector["Technology software"], 1)}, down from ${pcP(fi.sector_prior["Technology software"], 1)}, while the market's fear and the lawsuits are about software. The defaults are in dental labs, films and outdoor goods.`;
    // flips and catalysts
    fillTable($("#pc-flips"), ["Direction", "Trigger", "Where it stands"], C.flips.map((f) => [f.direction === "worse" ? "Lens darkens" : "Lens lifts", f.trigger, f.now]), 3);
    fillTable($("#pc-cat"), ["Date", "Event", "Where"], C.catalysts.map((c) => [isoNice(c.date), c.event, c.source]), 3);
    // sources and limits
    const su = $("#pc-sources"); su.replaceChildren();
    Object.keys(src).forEach((k) => { const li = h("li"); li.append(srcA(k)); su.append(li); });
    const lu = $("#pc-limits"); lu.replaceChildren(); C.limitations.forEach((x) => lu.append(h("li", null, x)));
    const mg = C.manager, tp = C.template;
    $("#pc-manager").textContent = `The manager's own arithmetic: ${pcUsd(ow.aum_not_yet_fee_paying)} of AUM is not yet paying fees, which management expects to add about ${pcUsd(mg.fees_from_undeployed)} a year (${pcP(mg.implied_fee_rate, 1)} of it), ${pcP(mg.uplift, 0)} on a run-rate FRE of ${pcUsd(mg.fre_run_rate)}. Credit raised ${pcUsd(ow.credit_raised_q)} in the quarter (${pcUsd(ow.credit_raised_split.investment_grade)} investment grade, ${pcUsd(ow.credit_raised_split.direct_lending)} direct lending); wealth equity ${pcUsd(ow.wealth_equity_raised_ttm)} over twelve months against ${pcUsd(ow.raised_ttm)} in total, so the queue is in the channel that supplies about a fifth of new money. In data centers: ${ow.data_centers} operational or under construction, about ${ow.gw_leased_or_owned} GW leased or owned, a ${ow.gw_pipeline} GW pipeline, a ${pcUsd(ow.next_digital_fund_target)} next fund; chip financings for ${ow.chip_financing.join(" and ")}. The template deal's cushions: a ${pcP(tp.equity_cushion, 0)} fall in the asset's value exhausts the equity, a ${pcP(tp.rent_cushion, 0)} fall in rent breaks debt service.`;
    const qs = $("#pc-quotes"); qs.replaceChildren(); ow.quotes.forEach(([who, what]) => { const b = h("blockquote", "pc-quote"); b.append(h("p", null, "“" + what + "”"), h("footer", null, who + ", Blue Owl, Oct 29, 2026")); qs.append(b); });
  }

  // a single-hue bar chart: Fitch's default rate by sector, software marked as the lowest
  function drawPcSectors(fi) {
    const box = $("#pc-sectors");
    if (!box) return;
    box.replaceChildren();
    const rows = Object.entries(fi.sector).sort((a, b) => b[1] - a[1]).concat([["All private credit (PCDR)", fi.pcdr]]);
    const W = boxWidth(box), rowH = 34, padL = 230, padR = 64, top = 10, Hh = top + rows.length * rowH + 10;
    const s = svg("svg", { viewBox: `0 0 ${W} ${Hh}`, role: "group", "aria-label": "Fitch private credit default rate by sector, trailing twelve months to September 2026" }, box);
    const xmax = Math.max(...rows.map((r) => r[1])) * 1.15, x = (v) => padL + (v / xmax) * (W - padL - padR);
    rows.forEach(([name, v], i) => {
      const y = top + i * rowH, all = /PCDR/.test(name), soft = /software/i.test(name);
      svg("text", { x: padL - 10, y: y + rowH / 2 + 4, "text-anchor": "end", class: "lbl", fill: "var(--ink-2)", "font-size": 12 }, s).textContent = name;
      const bar = svg("rect", { x: padL, y: y + 8, width: Math.max(2, x(v) - padL), height: rowH - 16, rx: 3, fill: all ? "var(--ink-2)" : soft ? "var(--accent)" : "color-mix(in srgb, var(--accent) 45%, var(--surface))", tabindex: 0, "aria-label": `${name}: ${pctPlain(v, 1)}` }, s);
      bindTip(bar, () => [[pctPlain(v, 1), name], [fi.sector_prior && fi.sector_prior[name] != null ? "from " + pctPlain(fi.sector_prior[name], 1) + " the quarter before" : all ? "from " + pctPlain(fi.pcdr_prior_q, 1) + " the quarter before" : "twelve months to " + isoNice(fi.asof), "Fitch"]]);
      svg("text", { x: x(v) + 6, y: y + rowH / 2 + 4, class: "lbl", fill: "var(--ink)", "font-size": 12, "font-weight": 600 }, s).textContent = pctPlain(v, 1);
    });
    redrawWhenSized(box, () => drawPcSectors(fi));
  }

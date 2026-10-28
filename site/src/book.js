  /* =====================================================================================
     v0.30: THE BOOK, SIZED AND MEASURED. The nine names on their own daily prices (buildout/book.py): factor
     exposures to external factors, ex-ante risk and its split, one-month expected shortfall three ways, the size each
     limit allows and the binding one, the Nasdaq-100 hedge that keeps every name, hedges tested out of sample on the
     book's own days, stress, correlation under one definition, liquidity. Reads SNAP30 (scripts/snapshot_v30.py).
     bookCall() is the one size the Desk shows: the decision engine's baseline, cut to the binding book limit.
     ===================================================================================== */
  const B30 = () => (typeof SNAP30 !== "undefined" && SNAP30 && SNAP30.book && SNAP30.book.sizes) ? SNAP30.book : null;
  const b30P = (v, d = 1) => (fin(v) ? pctPlain(v, d) : "n/a");
  const b30S = (v, d = 1) => (fin(v) ? pct(v, d) : "n/a");
  const B30_LIMIT = { es_budget: "Expected-shortfall budget", vol_target: "Volatility target", drawdown_cap: "One-year drawdown cap", gross_cap: "Gross cap" };
  const B30_LIMIT_LC = { es_budget: "the expected-shortfall budget", vol_target: "the volatility target", drawdown_cap: "the drawdown cap", gross_cap: "the gross cap" };
  const B30_POLICY = { none: "No hedge", nasdaq_beta: "Short Nasdaq-100 at the measured beta", nasdaq_and_semis: "Short Nasdaq-100 and semis at the measured betas",
    bond_when_it_hedges: "Long 20-year bond, only when its correlation says it hedges", bond_static_30: "Long 20-year bond, 30% always (the TLT 0.3x rule)" };

  // the one call: the decision engine's size (its baseline while the gate is shut), cut to the tightest book limit
  function bookCall(N) {
    const B = B30();
    if (!B || !N || !fin(N.exposure)) return null;
    const size = Math.min(N.exposure, B.size);
    const k = B.keep_names_hedge || {};
    return { B, size, engine: N.exposure, cut: size < N.exposure - 1e-9, binding: B.binding, bindingName: B30_LIMIT_LC[B.binding] || B.binding,
      breaches: ["es_budget", "vol_target", "drawdown_cap"].filter((x) => B.sizes[x] < 1 - 1e-9).length,
      keep: k.meets_all && fin(k.short_nasdaq_frac) ? k.short_nasdaq_frac : null };
  }

  function renderBookRisk() {
    const B = B30(), tiles = $("#bk-tiles");
    if (!tiles) return;
    if (!B) { tiles.replaceChildren(h("p", "empty", "The book engine is not in this build.")); return; }
    const t = B.tail, e95 = t.es95, e975 = t["es97.5"], S = B.sizes, L = B.limits, K = B.keep_names_hedge || {}, R = B.risk, X = B.exposure;
    rsKpi(tiles, [
      [xx(B.size), "The size the limits allow", `${B30_LIMIT_LC[B.binding]} binds; ${K.meets_all ? `or keep every name and short ${b30P(K.short_nasdaq_frac, 0)} of NAV in Nasdaq-100 futures` : "no index hedge alone fits every limit"}`],
      [b30P(e95.governing, 1), "Worst month in twenty at 1.00x", `one-month 95% expected shortfall, most cautious of three methods; the budget is ${b30P(L.es_budget, 0)}`],
      [b30P(R.vol, 0), "Volatility at 1.00x", `factor model; the names' own covariance says ${b30P(R.vol_names_cov, 0)}; the target is ${b30P(L.vol_target, 0)}`],
      [fx(R.effective_bets, 1), "Independent bets, of nine", `${b30P(R.variance_share.market, 0)} of the variance is one factor, the Nasdaq-100`]]);
    const F = (B.findings || []).map((x) => x.replace(/(^|[\s(])-(\d)/g, "$1\u2212$2"));
    $("#bk-sub").textContent = `Every other desk sizes the S&P 500 or the Nasdaq-100. This one measures the book that is held: the nine names' own daily prices from ${isoNice(B.from)} to ${isoNice(B.asof)}, each name's betas to three outside factors (the Nasdaq-100, semiconductors net of the market, a 20-year Treasury bond), and the book's risk against its own limits.`;
    // the size
    $("#bk-size-p").textContent = `${F[1] || ""} The decision engine supplies the baseline (it finds no evidence for any size but holding, so it holds 1.00x), and the tightest of the book's limits sets the size. Readings at 1.00x and at the size, on the same methods:`;
    const at = (x, k) => (k === "es_budget" ? e95.governing * x : k === "vol_target" ? R.vol * x : null);
    fillTable($("#bk-size"), ["Limit", "Measure", "At 1.00x", "Limit", "Size it allows", `At ${xx(B.size)}`, "Status at 1.00x"], [
      ["Expected-shortfall budget", "one month, mean of the worst 5%, most cautious of three methods", b30P(e95.governing), b30P(L.es_budget, 0), xx(S.es_budget), b30P(at(B.size, "es_budget")), S.es_budget < 1 ? "breached" : "within"],
      ["Volatility target", "annual, factor model at today's factor volatility", b30P(R.vol, 1), b30P(L.vol_target, 0), xx(S.vol_target), b30P(at(B.size, "vol_target")), S.vol_target < 1 ? "breached" : "within"],
      ["One-year drawdown cap", `95th percentile, constant-volatility simulation, drift ${b30P(L.drawdown_drift, 1)}`, b30P(B.at_full.drawdown95, 0), b30P(L.max_drawdown, 0), xx(S.drawdown_cap), "at the cap", S.drawdown_cap < 1 ? "breached" : "within"],
      ["Gross cap", "gross exposure", "1.00x", xx(L.max_gross), xx(S.gross_cap), xx(B.size), "within"]], 2);
    $("#bk-keep-p").textContent = K.meets_all
      ? `Keeping every name at full size takes a Nasdaq-100 futures short of ${b30P(K.short_nasdaq_frac, 0)} of NAV ($${fx(K.notional_usd_per_100m / 1e6, 0)}m per $100m), which leaves a Nasdaq-100 beta of ${fx(K.market_beta_left, 2)}, ${b30P(K.vol, 0)} volatility, a ${b30P(K.es95, 1)} worst month in twenty and a ${b30P(K.drawdown95, 0)} one-year drawdown; ${B30_LIMIT_LC[K.binding_after]} still binds. The choice between cutting gross and shorting the index is the PM's: the short keeps the stock-specific bets and the semis tilt, cutting gross keeps the market bet smaller and simpler. Both carry the same limits.`
      : `No Nasdaq-100 short alone brings the full-size book inside every limit (the best, ${b30P(K.best_short, 0)} of NAV, leaves ${b30P(K.drawdown95, 0)} of one-year drawdown): cut gross to ${xx(B.size)}.`;
    $("#bk-math").innerHTML = `<span class="mlabel">The method</span>daily total returns <var>r</var><sub>i,t</sub> = (<var>P</var><sub>t</sub> + <var>D</var><sub>t</sub>) / <var>P</var><sub>t&minus;1</sub> &minus; 1 (prices split-adjusted, dividends on their ex-dates); the book <var>r</var><sub>B,t</sub> = &Sigma; <var>w</var><sub>i</sub><var>r</var><sub>i,t</sub> at today's weights, a name without a price that day handing its weight to the others pro rata; factors: <var>m</var> = QQQ, <var>s</var> = SOXX &minus; &beta;<sub>t&minus;1</sub>QQQ (semis net of the market, the beta through the day before), <var>y</var> = a 20-year par bond repriced daily from the Treasury's par yields; betas by exponentially weighted least squares (half-life ${126} days; SPCX shrunk toward TSLA, weight <var>n</var>/(<var>n</var> + 126) on its own); &Sigma; = <var>B</var>&Phi;<var>B</var>&prime; + <var>D</var> with &Phi; the factors' 63-day exponentially weighted covariance; ES<sub>&alpha;</sub> one month by historical simulation of 21-day compounded returns, filtered historical simulation (standardized by RiskMetrics &lambda; 0.94 volatility, rescaled to today's) and a Student-t (&nu; 5) at the factor-model volatility; the governing ES is the largest of the three; sizes: ${b30P(L.es_budget, 0)} &divide; ES<sub>5%</sub>, ${b30P(L.vol_target, 0)} &divide; &sigma;, the largest leverage whose 95th-percentile one-year drawdown stays within ${b30P(L.max_drawdown, 0)}; the call is the smallest.`;
    // exposures
    const rc = Object.fromEntries((R.contributions || []).map((c) => [c.name, c]));
    $("#bk-exp-p").textContent = `${F[2] || ""} ${X.semis < -0.1 ? "The semis column is the surprise: net of the market the book is short semiconductors, because the buyers of AI capacity (Microsoft, Amazon, Alphabet, Meta) lag on days the sellers (Nvidia, Broadcom) beat the market. " : ""}Rates betas are on the 20-year bond's return, so a negative beta means the name falls when bonds rally.`;
    fillTable($("#bk-exp"), ["Name", "Weight", "Nasdaq-100 beta", "Semis net of market", "20-year bond", "Stock-specific volatility", "Share of risk", "Days of history"],
      (B.betas || []).map((b) => [b.name + (b.prior ? ` (leans on ${b.prior})` : ""), b30P(B.weights[b.name], 0), fx(b.market, 2), fx(b.semis, 2), fx(b.rates, 2), b30P(b.specific_vol, 0), b30P(rc[b.name] && rc[b.name].share, 0), String(b.days)])
        .concat([["The book", "100%", fx(X.market, 2), fx(X.semis, 2), fx(X.rates, 2), "", "100%", ""]]), 1);
    // tail
    const VB = B.var_backtest || {};
    $("#bk-tail-p").textContent = `One-month expected shortfall, three ways, at 95% (the budget's definition) and 97.5% (the Basel standard). The record holds ${B.days.toLocaleString()} days; overlapping 21-day windows give ${t.months.toLocaleString()} months. ${F[5] || ""} A normal model at today's volatility understates this book's daily tail; history's own shapes do not, which is why the size uses the most cautious method.`;
    fillTable($("#bk-tail"), ["Measure", "Historical", "Filtered historical", "Student-t", "Governing"], [
      ["One month, 95% ES", b30P(e95.historical), b30P(e95.filtered), b30P(e95.student_t), b30P(e95.governing)],
      ["One month, 97.5% ES", b30P(e975.historical), b30P(e975.filtered), b30P(e975.student_t), b30P(e975.governing)],
      ["One day, 99% VaR", b30P(t.day.var99_hist, 2), "", "", `${b30P(t.day.var99_now, 2)} at today's volatility (normal)`],
      ["One day, 99% ES", b30P(t.day.es99_hist, 2), "", "", ""]], 1);
    fillTable($("#bk-var"), ["VaR model, one day 99%", "Days", "Breaches", "Expected", "Proportion test p", "Average loss when breached", "Average VaR on those days"],
      ["normal", "filtered"].filter((k) => VB[k]).map((k) => [VB[k].model, VB[k].days.toLocaleString(), String(VB[k].breaches), fx(VB[k].expected, 0), VB[k].p < 0.001 ? "under 0.001" : fx(VB[k].p, 3), b30P(VB[k].avg_loss_given_breach, 2), b30P(VB[k].avg_var_on_breach, 2)]), 1);
    // hedges
    const H = B.hedges || {}, P = H.policies || {};
    $("#bk-hedge-p").textContent = `${F[3] || ""} Every ratio is known at the close before the day it is used, and every hedge leg is measured as a future (its return less cash), ${isoNice(H.from)} to ${isoNice(H.to)}. The index short buys its protection with the index's return: it gave up ${b30P(-(P.nasdaq_beta || {}).leg_mean_ann, 0)} a year in a decade when the Nasdaq-100 compounded, which is the price of the insurance, not a flaw in it. The bond did not hedge this book in either form.`;
    fillTable($("#bk-hedge"), ["Policy", "Volatility", "Variance cut", "Average year", "Worst 5% of days", "Worst 10% of months", "One-month 95% ES", "Worst drawdown", "2022", "Sharpe"],
      Object.keys(B30_POLICY).filter((k) => P[k]).map((k) => { const p = P[k]; return [B30_POLICY[k], b30P(p.vol, 0), k === "none" ? "" : b30P(p.variance_cut, 0), b30S(p.mean_ann, 0), b30S(p.worst_5pct_days, 2), b30S(p.worst_10pct_months, 1), b30P(p.es95_month, 1), b30P(p.max_drawdown, 0), b30S(p.y2022, 0), fx(p.sharpe, 2)]; }), 1);
    // stress
    $("#bk-ep-p").textContent = "The engine's episodes replayed on the names' own returns (SPCX had not listed; its weight goes to the others). The worst point is the deepest the book fell inside the window.";
    fillTable($("#bk-ep"), ["Episode", "Window", "Book", "Worst point", "Nasdaq-100", "Semis (SOXX)", "20-year bond", "Worst name"],
      (B.episodes || []).map((x) => [x.episode, `${isoNice(x.from)} to ${isoNice(x.to)}`, b30S(x.book, 1), b30S(x.worst_point, 1), b30S(x.nasdaq, 1), b30S(x.semis_etf, 1), b30S(x.bond20, 1), `${x.worst_name} ${b30S(x.worst_name_return, 0)}`]), 2);
    $("#bk-sc-p").textContent = `The engine's scenarios through the measured betas (assumptions, not forecasts; the scenarios' AI move beyond the Nasdaq-100 is carried by the semis factor). The bond is the 20-year par bond repriced for the yield move. The last column holds the names and shorts ${b30P(K.best_short, 0)} of NAV in Nasdaq-100 futures.`;
    fillTable($("#bk-sc"), ["Scenario", "Nasdaq-100", "Semis net", "Long yield", "Book", "Book plus 30% bond", "Book plus index short", "Worst name"],
      (B.scenarios || []).map((x) => [x.scenario, b30S(x.nasdaq, 0), b30S(x.semis_vs_nasdaq, 0), bp(x.dy_bp), b30S(x.book, 1), b30S(x.with_bond_30, 1), b30S(x.with_nasdaq_hedge, 1), `${x.worst_name} ${b30S(x.worst_name_move, 0)}`]), 1);
    fillTable($("#bk-wd"), ["Worst days", "Book", "Nasdaq-100", "Semis (SOXX)", "20-year bond"],
      (B.worst_days || []).map((x) => [isoNice(x.date), b30S(x.book, 1), b30S(x.nasdaq, 1), b30S(x.semis_etf, 1), b30S(x.bond20, 1)]), 1);
    // correlation
    const C = B.correlation || {};
    $("#bk-corr-p").textContent = `One definition: ${C.definition}, with the engine's hysteresis (enter a state at 0.10, leave it at 0). Today ${sgn2(C.book_63d)}, ${C.state}${C.state_since ? ` since ${isoNice(C.state_since)}` : ""}; the Nasdaq-100 on the same definition ${sgn2(C.nasdaq_63d)}; the book's 36-month correlation of monthly returns ${sgn2(C.book_36m_monthly)}. Other desks quote other definitions (the Desk's 36-month S&P 500 against the 10-year, the Futures desk's S&P 500 future against Treasury futures); they are labelled where they appear and are not interchangeable.`;
    fillTable($("#bk-corr"), ["On the book's worst 5% of days", "Days", "Book, average", "Bond, average", "Bond up on", "Bond offset per dollar"],
      (C.shock || []).map((g) => [g.group, String(g.days), b30S(g.avg_equity, 1), b30S(g.avg_bond, 2), b30P(g.bond_up_share, 0), b30P(g.offset, 0)]), 1);
    // growth chart
    const D = B.drawdowns || {}, M = D.monthly || {};
    if (Array.isArray(M.months) && M.months.length > 2) {
      const yr = (s) => +s.slice(0, 4) + (+s.slice(5, 7) - 1) / 12;
      xyChart($("#bk-chart"), { height: 250, label: "Growth of one dollar, the book at today's weights against the Nasdaq-100, log scale", padL: 52,
        series: [{ pts: M.months.map((m, i) => [yr(m), Math.log(M.book[i])]), color: "var(--s1)", name: "The book" },
                 { pts: M.months.map((m, i) => [yr(m), Math.log(M.nasdaq[i])]), color: "var(--s2)", name: "Nasdaq-100 (QQQ)" }],
        xticks: [2017, 2019, 2021, 2023, 2025].map((y) => [y, String(y)]), yfmt: (v) => "$" + fx(Math.exp(v), Math.exp(v) < 10 ? 1 : 0) });
      legendLines($("#bk-chart-leg"), [["var(--s1)", `The book: ${b30P(D.cagr, 0)} a year, worst drawdown ${b30P(D.max, 0)} (${isoNice(D.peak)} to ${isoNice(D.trough)}), ${b30P(D.now, 0)} below its peak now`],
        ["var(--s2)", `Nasdaq-100: ${b30P(D.nasdaq_cagr, 0)} a year, worst drawdown ${b30P(D.nasdaq_max, 0)}`]]);
    }
    // liquidity
    const LQ = B.liquidity || [];
    $("#bk-liq-p").textContent = `Days to sell each position at ${b30P(0.2, 0)} of its 20-day average dollar volume. At $100m of NAV nothing takes as long as a day; the column at $1bn shows where size starts to matter.`;
    fillTable($("#bk-liq"), ["Name", "Average daily volume", "Position at $100m", "Days at $100m", "Days at $1bn"],
      LQ.map((x) => [x.name, `$${fx(x.adv_usd / 1e9, 1)}bn`, `$${fx(x.position_usd / 1e6, 0)}m`, fx(x.days_100m, 3), fx(x.days_1bn, 2)]), 1);
    // validation and limits
    const V = B.validation || {};
    $("#bk-val-p").textContent = V.mean_abs_beta_error != null ? `On a synthetic world with planted betas (nine names, a fat-tailed market, a semis factor, a bond from simulated yields, the last name listing ninety days before the end), the engine recovered the betas with a mean error of ${fx(V.mean_abs_beta_error, 2)} (largest ${fx(V.max_abs_beta_error, 2)}) and the book's Nasdaq-100 exposure as ${fx(V.book_exposure.market, 2)} against ${fx(V.planted_exposure.market, 2)} planted; the short-history name leans on the others' average as designed.` : "";
    const ul = $("#bk-limits"); ul.replaceChildren(); (B.limitations || []).forEach((l) => ul.append(h("li", null, l)));
  }

  /* v0.30: THE RESEARCH INVENTORY. Every edge or rule the engine has tested, one row each, joined from the desks' own
     shipped results (scripts/snapshot_v30.py inventory()); nothing is re-run here. */
  const invMinus = (x) => String(x || "").replace(/(^|[\s(;])-(\d)/g, "$1\u2212$2").replace(/\u22120\.00\b/g, "0.00").replace(/\u22120\.0%/g, "0.0%");
  const INV_ORDER = ["works", "promising", "faded", "in sample only", "failed", "untested"];
  const INV_CLASS = { works: "supported", promising: "one-era", faded: "one-era", "in sample only": "one-era", failed: "no-evidence", untested: "no-evidence" };
  function renderInventory() {
    const I = (typeof SNAP30 !== "undefined" && SNAP30 && SNAP30.inventory) || null, tiles = $("#inv-tiles");
    if (!tiles) return;
    if (!I || !Array.isArray(I.rows)) { tiles.replaceChildren(h("p", "empty", "The inventory is not in this build.")); return; }
    const c = I.counts || {}, n = I.rows.length;
    rsKpi(tiles, [[String(n), "Edges and rules tested", `across ${new Set(I.rows.map((r) => r.desk)).size} desks`],
      [String(c.works || 0), "Work", "passed every test their desk sets, out of sample"],
      [String((c.faded || 0) + (c.promising || 0) + (c["in sample only"] || 0)), "Faded, promising or in sample only", "real once, not yet proven, or never tested out of sample"],
      [String(c.failed || 0), "Failed", `${c.untested || 0} more wait for data`]]);
    $("#inv-p").textContent = `What survives an honest test is short. ${(I.notes || []).map((x) => x.replace(/^[a-z ]+: /, (m) => m.charAt(0).toUpperCase() + m.slice(1))).join(". ")}. Each row links to the desk that ran it; the verdict is that desk's own, in one vocabulary.`;
    const sel = $("#inv-filter");
    if (sel && !sel.options.length) {
      [["all", "Every verdict"]].concat(INV_ORDER.map((v) => [v, v.charAt(0).toUpperCase() + v.slice(1)])).forEach(([v, t]) => { const o = document.createElement("option"); o.value = v; o.textContent = t; sel.append(o); });
      sel.addEventListener("change", () => renderInventory());
    }
    const want = sel ? sel.value : "all";
    const rows = I.rows.filter((r) => want === "all" || r.verdict === want).slice().sort((a, b) => INV_ORDER.indexOf(a.verdict) - INV_ORDER.indexOf(b.verdict) || a.desk.localeCompare(b.desk));
    const t = $("#inv-table");
    fillTable(t, ["Verdict", "Desk", "Family", "What was tested", "How", "Result", "p", "Record to"], rows.map((r) => {
      const a = h("a", null, r.desk); a.href = r.href;
      return [h("span", "rs-v rs-v-" + (INV_CLASS[r.verdict] || "no-evidence"), r.verdict), a, r.family, r.test, r.method, invMinus(r.stat), fin(r.p) ? (r.p < 0.001 ? "under 0.001" : fx(r.p, 3)) : "", String(r.through || "")];
    }), 6);
    const ul = $("#inv-key"); if (ul) { ul.replaceChildren(); INV_ORDER.forEach((v) => ul.append(h("li", null, `${v}: ${(I.verdicts || {})[v] || ""}`))); }
  }

  /* v0.31: THE LIBRARY. The desks moved off the main path, one index away, grouped by what they are for. */
  const LIBRARY = [
    ["Decision tools", "Other ways to reach and stress the call", ["portfolio", "decide", "solve", "noteworthy"]],
    ["Models and maps", "How the parts of the system connect, and whether the models' assumptions hold", ["mind", "brain", "atlas", "geometry", "matrix", "reality"]],
    ["Research", "Signals, data and tests behind the desk's views", ["analysis", "labs", "ml", "edge", "physics", "buyside", "field"]],
    ["Markets reference", "What each security carries, and who funds the long end", ["securities", "insurers"]],
    ["Workshop", "Games, market making, prop economics, the math lab, and the investors whose rules the engine borrows", ["games", "cardroom", "making", "prop", "lab", "legends", "lenses"]],
    ["Methods and reference", "How it runs each day, borrowed methods, definitions", ["crossfield", "engine", "engines", "appendix"]],
  ];
  function renderLibrary() {
    const box = $("#lib-grid");
    if (!box || box.childElementCount) return;
    LIBRARY.forEach(([name, sub, views]) => {
      const sec = h("section", "lib-sec");
      sec.append(h("h2", null, name), h("p", "lib-sub", sub));
      const ul = h("ul", "lib-list");
      views.filter((v) => document.getElementById("view-" + v)).forEach((v) => {
        const li = h("li"), a = h("a", null, TAB_NAME[v] || v);
        a.href = "#" + v;
        li.append(a, h("span", null, (typeof DESK_GUIDE === "object" && DESK_GUIDE[v] && DESK_GUIDE[v].q) || ""));
        ul.append(li);
      });
      sec.append(ul);
      box.append(sec);
    });
  }

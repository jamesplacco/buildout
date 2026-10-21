  /* =====================================================================================
     buyside6.js (v0.6): the Buyside desk, built from the 2026 field manual. Calculators mirror
     buildout/accounting.py and buildout/buyside.py exactly (tests/test_page.py checks them).
     ===================================================================================== */
  // ---------- engine parity ----------
  const depreciationTable = (cohort, lives = [6, 5, 4, 3, 2], book = 6) => lives.map((L) => ({ life: L, annual: cohort / L, gap: cohort / L - cohort / book }));
  const ddbFirstYear = (cohort, life) => cohort * Math.min(1, 2 / life);
  const cashEps = (ni, dE, dB, sbc, dSw, dDef, sh) => (sh > 0 ? (ni - (dE - dB) - sbc - dSw + dDef) / sh : NaN);
  function dcfValue(f0, g, r, tg, years = 10) {
    if (r <= tg) return Infinity;
    let pv = 0, f = f0;
    for (let t = 1; t <= years; t++) { f *= 1 + g; pv += f / Math.pow(1 + r, t); }
    return pv + (f * (1 + tg)) / (r - tg) / Math.pow(1 + r, years);
  }
  function reverseDcf(mv, f0, r, tg = 0.03, years = 10) {
    if (!(f0 > 0) || !(mv > 0) || r <= tg) return NaN;
    let lo = -0.5, hi = 1.5;
    if (dcfValue(f0, hi, r, tg, years) < mv) return Infinity;
    if (dcfValue(f0, lo, r, tg, years) > mv) return lo;
    for (let i = 0; i < 200; i++) { const mid = (lo + hi) / 2; if (dcfValue(f0, mid, r, tg, years) > mv) hi = mid; else lo = mid; }
    return (lo + hi) / 2;
  }
  function creditStress(base, spread, dr, rec, mgmt = 0.0125, inc = 0.125, tsy = 0.052) {
    const gross = base + spread, loss = dr * (1 - rec), pre = gross - loss - mgmt, net = pre > 0 ? pre * (1 - inc) : pre;
    return { gross, loss, net, over: net - tsy };
  }
  const RED_TESTS = [["capex_to_dep", "Capex / depreciation", 1.5, 2.5, "lt", "Depreciation catch-up will hit margins later"], ["fcf_to_ni", "Free cash flow / net income", 0.9, 0.6, "gt", "Earnings not converting to cash"],
    ["sbc_to_rev", "Stock compensation / revenue", 0.05, 0.12, "lt", "A real cost hidden in adjusted metrics"], ["recv_minus_rev", "Receivables minus revenue growth", 0.05, 0.10, "lt", "Pulled-forward or vendor-financed sales"],
    ["top3_customers", "Top three customers / revenue", 0.30, 0.50, "lt", "One capex cut hits the whole P&L"]];
  function gradeFlag(v, healthy, red, dir) {
    if (!fin(v)) return "n/a";
    return dir === "lt" ? (v < healthy ? "healthy" : v > red ? "red" : "watch") : v > healthy ? "healthy" : v < red ? "red" : "watch";
  }
  function grossScaler(fed, real10) {
    if (fed > 0 && real10 > 1.5) return [0.60, 0.75, "Hiking with real yields above 1.5%"];
    if (fed > 0) return [0.75, 0.85, "Hiking with real yields below 1.5%"];
    if (fed < 0) return [1.00, 1.20, "Easing"];
    return [0.85, 0.85, "On hold"];
  }
  function regimeLabel(cpi3m, real10, fed, brentRatio) {
    const hot = cpi3m >= 3 || brentRatio >= 1.3, supply = brentRatio >= 1.3;
    if (hot && fed > 0) return supply ? "Supply-shock stagflation scare" : "Tightening into inflation";
    if (hot && fed === 0) return "Sticky inflation, Fed on hold";
    if (hot) return "Easing into inflation";
    return fed < 0 ? "Easing, disinflation" : fed > 0 ? "Late-cycle tightening" : "Neutral";
  }
  function buyData() { return LIVE.buyside && LIVE.buyside.latest ? LIVE.buyside : BUY_SNAP; }

  /* ---------- regime and gross ---------- */
  function renderBsRegime() {
    const B = buyData(), L = B.latest, inp = inputs();
    const real10 = signalNow("real") ?? 2.74;
    const fut = 107 / (84.54 || 1);
    const label = regimeLabel(L.cpi_3m_ann * 100, real10, 1, L.brent_vs_5y);
    const [lo, hi, why] = grossScaler(1, real10);
    const maxG = 1.5, volG = inp.gross && fin(inp.gross.v) ? inp.gross.v : Math.min(0.2 / (1.1 * inp.vxn.v / 100), maxG);
    const tiles = $("#bs-reg-tiles");
    tiles.replaceChildren(
      tile("Regime", label, `Inflation ${fx(L.cpi_3m_ann * 100, 2)}% annualized over three months (${monthNice(L.month + "-01")}); Brent ${fx(L.brent_vs_5y, 2)}x its five-year average; Fed hiking.`),
      tile("Rule 7a.1 gross", `${fx(lo * maxG, 2)}x to ${fx(hi * maxG, 2)}x`, `${why}: ${Math.round(lo * 100)} to ${Math.round(hi * 100)}% of the ${fx(maxG, 1)}x maximum.`),
      tile("Volatility rule gross", xx(volG), "Decision 1: 20% target over 1.1 times VXN."),
      tile("Binding constraint", volG <= lo * maxG ? "Volatility" : "Regime", volG <= lo * maxG ? `The volatility rule (${xx(volG)}) is already below the regime band: it binds.` : "The regime band is tighter than the volatility rule: cut to its top."),
      (() => { const T = tltNow(inputs()); return tile("Long bonds in the stack?", T.status !== "ok" ? "Unavailable" : T.on ? "Yes" : "No", `Policy hedge.tlt.v2, the same rule as Decision 2: the stock-bond state is ${T.gates.state.value || "n/a"}; inflation gate ${T.gates.inflation.status === "ok" ? (T.gates.inflation.pass ? "passes" : "fails") : "not applied"}.`); })(),
      tile("Oil rule on futures", `${fx(fut, 2)}x`, `Spot reads ${fx(L.brent_vs_5y, 2)}x; front futures (about $107, IEA Oct 14) read ${fx(fut, 2)}x, under the 1.3x supply line. The inflation leg keeps the sleeve.`));
  }
  function signalNow(id) {
    const s = LIVE.sigStates && LIVE.sigStates[id];
    if (s && fin(s.v)) return s.v;
    const sg0 = SIGNALS.find((x) => x.id === id);
    return sg0 && sg0.snap && fin(sg0.snap.v) ? sg0.snap.v : null;
  }

  /* ---------- hedge selector, tails, replays ---------- */
  function renderBsSelector() {
    const B = buyData(), S = B.selector || {}, box = $("#bs-sel");
    if (!box) return;
    box.replaceChildren();
    [["above_line", "Inflation above 2.75% (historical split)"], ["below_line", "Inflation below 2.75%"]].forEach(([k, title]) => {
      const reg = S[k];
      if (!reg) return;
      const p = h("div", "panel");
      p.append(h("span", "panel-title", `${title}: ${reg.periods} months since ${B.selector_since || "1990-02"}`));
      const bx = h("div", "svgbox");
      bx.id = "bs-sel-" + k;
      p.append(bx, tableBlock(["Hedge", "On the worst 5%", "Shortfall removed", "Carry a year", "Paid"], reg.rows.map((r) => [r.hedge, sPct(r.on_worst, 1), sg(r.es_removed * 100, 2) + " pts", sPct(r.carry, 1), Math.round(r.hit * 100) + "%"])));
      box.append(p);
    });
    drawBsSelector();
  }
  function drawBsSelector() {
    const S = buyData().selector || {};
    ["above_line", "below_line"].forEach((k) => {
      const box = $("#bs-sel-" + k), reg = S[k];
      if (!box || !reg) return;
      barsH(box, reg.rows.map((r) => ({ label: r.hedge, v: r.es_removed * 100, color: r.es_removed > 0 ? "var(--s3)" : "var(--red)" })), { fmt: (v) => sg(v, 2) + " pts", label: "Shortfall removed by a 30% hedge, percentage points", labelW: 130 });
    });
  }
  function renderBsTails() {
    const T = buyData().tail;
    if (!T) return;
    $("#bs-tail-note").textContent = `Monthly S&P 500 total returns, ${T.months.toLocaleString("en-US")} months since 1871. A Student-t fitted by maximum likelihood has ${fx(T.nu, 1)} degrees of freedom: finite variance, infinite kurtosis. The normal model understates the average loss in the worst 2.5% of months by ${Math.round((1 - T.normal / T.historical) * 100)}%; even the Student-t understates it by ${Math.round((1 - T.student_t / T.historical) * 100)}%.`;
    barsH($("#bs-tail"), [{ label: "Normal model", v: T.normal * 100, color: "var(--muted)" }, { label: "Student-t", v: T.student_t * 100, color: "var(--s1)" }, { label: "History", v: T.historical * 100, color: "var(--red)", strong: true }],
      { fmt: (v) => fx(v, 1) + "%", label: "Average loss in the worst 2.5% of months", labelW: 110 });
  }
  function renderBsReplays() {
    const R = buyData().replays || [];
    fillTable($("#bs-replay"), ["Episode", "Months", "Book (S&P 500)", "10-year Treasury", "Gold", "Brent", "Put spread", "Book + 30% bonds", "Book + hedge stack"],
      R.map((r) => [r.name, `${monthNice(r.from + "-01")} to ${monthNice(r.to + "-01")}`, sPct(r.book, 1), sPct(r.bond10, 1), sPct(r.gold, 1), sPct(r.brent, 1), sPct(r.put_spread, 1), sPct(r.book_plus_bonds, 1), sPct(r.book_plus_stack, 1)]), 2);
    const box = $("#bs-replay-chart");
    if (box && box.clientWidth && R.length) {
      const W = boxWidth(box), Hh = 250, padL = 44, top = 16, bottom = 40, band = (W - padL - 8) / R.length, bw = Math.min(18, (band - 16) / 3);
      const vals = R.flatMap((r) => [r.book, r.book_plus_bonds, r.book_plus_stack]), ticks = niceTicks(Math.min(0, ...vals), Math.max(0, ...vals), 4), y0 = ticks[0], y1 = ticks[ticks.length - 1];
      const sy = (v) => top + (1 - (v - y0) / (y1 - y0 || 1)) * (Hh - top - bottom);
      box.replaceChildren();
      const s = svg("svg", { viewBox: `0 0 ${W} ${Hh}`, width: W, height: Hh, role: "img", "aria-label": "Episode returns: book alone, with bonds, with the hedge stack" }, box);
      ticks.forEach((t) => { svg("line", { x1: padL, x2: W - 8, y1: sy(t), y2: sy(t), class: t === 0 ? "baseline" : "gridline" }, s); text(s, padL - 6, sy(t) + 4, pct(t, 0), "ax", "end"); });
      R.forEach((r, i) => {
        const cx = padL + band * (i + 0.5);
        text(s, cx, Hh - 22, r.from.slice(0, 4), "ax", "middle");
        text(s, cx, Hh - 9, r.key.split("-")[0], "ax", "middle");
        [["book", "var(--muted)", "Book"], ["book_plus_bonds", "var(--s2)", "With bonds"], ["book_plus_stack", "var(--s1)", "With the stack"]].forEach(([k, col, lab], j) => {
          const x = cx - 1.5 * bw - 2 + j * (bw + 2), v = r[k];
          svg("path", { d: vbar(x, bw, sy(0), sy(v), 3), fill: col }, s);
          const hit = svg("rect", { x: x - 1, y: Math.min(sy(0), sy(v)) - 2, width: bw + 2, height: Math.max(6, Math.abs(sy(v) - sy(0)) + 4), class: "hit", tabindex: "0", "aria-label": `${r.name}, ${lab}: ${pct(v, 1)}` }, s);
          bindTip(hit, () => [[pct(v, 1), `${lab} · ${r.name}`]]);
        });
      });
    }
  }

  /* ---------- accounting calculators ---------- */
  function updateDeprCalc() {
    const cohort = readRange("#bd-c"), life = readRange("#bd-l");
    $("#bd-c-o").textContent = "$" + fx(cohort, 0) + "B"; $("#bd-l-o").textContent = fx(life, 1) + " years";
    const rows = depreciationTable(cohort, [6, 5, 4, 3, 2]);
    const mine = cohort / life, gap = mine - cohort / 6, ddb = ddbFirstYear(cohort, 6);
    $("#bd-annual").textContent = "$" + fx(mine, 1) + "B"; $("#bd-gap").textContent = (gap > 0.05 ? "+" : gap < -0.05 ? MINUS : "") + "$" + fx(Math.abs(gap), 1) + "B";
    $("#bd-ddb").textContent = "$" + fx(ddb, 1) + "B";
    $("#bd-out").textContent = `On a $${fx(cohort, 0)}B server cohort, a ${fx(life, 1)}-year life books $${fx(mine, 1)}B a year against $${fx(cohort / 6, 1)}B at the 6-year book life: ${gap >= 0 ? "$" + fx(gap, 1) + "B more expense" : "$" + fx(-gap, 1) + "B less"}. A front-loaded (double-declining) 6-year schedule books $${fx(ddb, 1)}B in year one, close to a 3-year straight line: the realistic middle the manual describes.`;
    barsH($("#bd-chart"), rows.map((r) => ({ label: `${r.life}-year life`, v: r.annual, color: r.life === 6 ? "var(--muted)" : "var(--s1)", strong: Math.abs(r.life - life) < 0.01 })), { fmt: (v) => "$" + fx(v, 0) + "B", label: "Annual depreciation by assumed life", labelW: 100 });
  }
  function updateCashEps() {
    const v = (id) => readNum($(id), -1e6, 1e6, 0);
    const ni = v("#ce-ni"), dE = v("#ce-de"), dB = v("#ce-db"), sbc = v("#ce-sbc"), sw = v("#ce-sw"), dr = v("#ce-dr"), sh = readNum($("#ce-sh"), 0.001, 1e6, 7.4);
    const rep = ni / sh, cash = cashEps(ni, dE, dB, sbc, sw, dr, sh);
    $("#ce-rep").textContent = money(rep, 2); $("#ce-cash").textContent = money(cash, 2); $("#ce-gap").textContent = fin(cash) && rep ? sPct(cash / rep - 1, 0) : "n/a";
    $("#ce-out").textContent = fin(cash) ? `Reported EPS ${money(rep, 2)} becomes ${money(cash, 2)} of cash EPS once depreciation is set to economic life, stock pay counts as pay, capitalized software is expensed and deferred revenue is credited. Underwrite the second number; decide how much optimism to pay for the first.` : "Enter a share count above zero.";
  }
  function updateRevDcf() {
    const mv = readNum($("#rd-mv"), 1, 1e5, 3800), f0 = readNum($("#rd-f"), -1e4, 1e4, 67), rf = readRange("#rd-rf") / 100, erp = readRange("#rd-erp") / 100, g3 = readRange("#rd-g3") / 100, tg = 0.03;
    $("#rd-rf-o").textContent = fx(rf * 100, 2) + "%"; $("#rd-erp-o").textContent = fx(erp * 100, 1) + "%"; $("#rd-g3-o").textContent = fx(g3 * 100, 0) + "% a year";
    const g = reverseDcf(mv, f0, rf + erp, tg);
    $("#rd-g").textContent = fin(g) ? sPct(g, 1) + " a year" : g === Infinity ? "above 150%" : "n/a";
    const moon = fin(g) && g > 2 * g3;
    const out = $("#rd-out");
    out.className = "sentence " + (moon ? "warn" : "ok");
    out.textContent = !fin(g) && g !== Infinity ? "Free cash flow must be positive for a reverse DCF." : `At a ${fx((rf + erp) * 100, 1)}% discount rate (${fx(rf * 100, 2)}% risk-free plus ${fx(erp * 100, 1)}% equity premium) and 3% terminal growth, a $${Math.round(mv).toLocaleString("en-US")}B value needs free cash flow to grow ${fin(g) ? sPct(g, 1) : "above 150%"} a year for ten years. ${moon ? `That is more than twice the last three years' ${fx(g3 * 100, 0)}%: the price already assumes the moonshot.` : `That is within twice the last three years' ${fx(g3 * 100, 0)}%: the price does not need a moonshot.`}`;
  }
  const CS_PRESETS = [["Pre-2025 normal", 0.02, 0.6], ["Today (Fitch record 6%)", 0.06, 0.5], ["UBS worst case", 0.14, 0.4]];
  function updateCredit() {
    const base = readRange("#cs-b") / 100, sp = readRange("#cs-s") / 100, dr = readRange("#cs-d") / 100, rec = readRange("#cs-r") / 100, mg = readRange("#cs-m") / 100;
    $("#cs-b-o").textContent = fx(base * 100, 2) + "%"; $("#cs-s-o").textContent = fx(sp * 100, 2) + "%"; $("#cs-d-o").textContent = fx(dr * 100, 1) + "%"; $("#cs-r-o").textContent = fx(rec * 100, 0) + "%"; $("#cs-m-o").textContent = fx(mg * 100, 2) + "%";
    const r = creditStress(base, sp, dr, rec, mg);
    $("#cs-net").textContent = sPct(r.net, 2); $("#cs-over").textContent = sg(r.over * 100, 1) + " pts"; $("#cs-loss").textContent = fx(r.loss * 100, 2) + "%";
    const out = $("#cs-out");
    out.className = "sentence " + (r.over > 0.01 ? "ok" : "warn");
    out.textContent = `Gross yield ${fx(r.gross * 100, 1)}%, credit losses ${fx(r.loss * 100, 2)}% a year, fees ${fx(mg * 100, 2)}% plus 12.5% of what is left: the investor nets ${sPct(r.net, 2)}, ${r.over >= 0 ? fx(r.over * 100, 1) + " points over" : fx(-r.over * 100, 1) + " points under"} the 5.2% 10-year. ${r.over <= 0.005 ? "The illiquidity premium is gone: the investor is paid for credit risk it is not receiving." : "There is still a premium for locking the money up."}`;
    $("#cs-presets").querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", Math.abs(Number(b.dataset.d) - dr) < 1e-9 && Math.abs(Number(b.dataset.r) - rec) < 1e-9 ? "true" : "false"));
  }
  function renderRedFlags() {
    const rows = FUND.rows.map((r) => {
      const LIVEm = LIVE.capexTTM && LIVE.capexTTM[r.t];
      const m = { capex_to_dep: r.capex_to_da, fcf_to_ni: r.net_income > 0 && fin(r.fcf) ? r.fcf / r.net_income : null, sbc_to_rev: LIVEm ? LIVEm.sbc_to_rev : null, recv_minus_rev: LIVEm ? LIVEm.recv_minus_rev : null };
      return [r.name || r.t, ...RED_TESTS.slice(0, 4).map(([k, , hh, rr, d]) => { const v = m[k], g = gradeFlag(v, hh, rr, d); return fin(v) ? `${k === "capex_to_dep" ? fx(v, 1) + "x" : fx(v * 100, 0) + "%"} · ${g}` : "after the daily run"; })];
    });
    fillTable($("#bs-flags"), ["Company", "Capex / depreciation", "FCF / net income", "Stock pay / revenue", "Receivables minus revenue growth"], rows, 1);
    $("#bs-flags").querySelectorAll("td").forEach((td) => { const t = td.textContent; td.className = (td.className ? td.className + " " : "") + (t.endsWith("red") ? "flag-red" : t.endsWith("watch") ? "flag-watch" : t.endsWith("healthy") ? "flag-ok" : ""); });
  }
  function updateMoonbag() {
    const entry = readNum($("#mb-e"), 0.01, 1e6, 100), now = readNum($("#mb-p"), 0.01, 1e6, 210), sh = readNum($("#mb-s"), 1, 1e9, 100), atr = readRange("#mb-atr") / 100;
    $("#mb-atr-o").textContent = fx(atr * 100, 1) + "% a day";
    const mult = now / entry, sell = mult >= 2 ? Math.ceil((sh * entry) / now) : 0, keep = sh - sell, stop = now * (1 - 3 * atr);
    $("#mb-mult").textContent = fx(mult, 2) + "x";
    $("#mb-sell").textContent = sell ? sell.toLocaleString("en-US") + " shares" : "Not yet";
    $("#mb-keep").textContent = keep.toLocaleString("en-US") + " shares";
    $("#mb-stop").textContent = money(stop, 2);
    $("#mb-out").textContent = mult >= 2
      ? `At ${fx(mult, 2)}x, selling ${sell.toLocaleString("en-US")} shares (${money(sell * now)}) recovers the original ${money(sh * entry)}. The remaining ${keep.toLocaleString("en-US")} shares ride with a zero cost basis and no stop: the worst case is breakeven, the best case keeps the whole right tail. Growth-tier positions below 2x carry a volatility stop at 3 times the daily range: ${money(stop, 2)} now.`
      : `Below 2x (now ${fx(mult, 2)}x), the position is a growth-tier holding with a volatility-scaled trailing stop at 3 times the 20-day range: ${money(stop, 2)}. The moonbag rule triggers at ${money(entry * 2, 2)}.`;
  }

  /* ---------- the manual's ten signals, read against the desk's own data ---------- */
  function renderManualBoard() {
    const B = buyData(), L = B.latest, y10 = curveYield("10Y") * 100;
    const rows = [
      ["10-year Treasury", fx(y10, 2) + "% (" + curveNowSet().label + ")", "Above 5.5%", "Below 4.5%", y10 > 5.5 ? "Risk-off" : y10 < 4.5 ? "Risk-on" : "Between", "Cut gross 10 to 15 points above 5.5%; add 2-year, not 30-year, duration", "warn"],
      ["Stock-bond correlation", `${sgn2(L.corr36)} (36 months, engine); +0.21 (Fed, 1 year)`, "Stays above 0", "Below −0.2", "Risk-off", "TLT stays out of the hedge stack", "bad"],
      ["CPI, 3 months annualized", fx(L.cpi_3m_ann * 100, 2) + "% (" + monthNice(L.month + "-01") + ")", "Above 4%", "Below 2.5%", "Between", "Below 2.5%: raise gross toward 100% and extend duration", "warn"],
      ["Fed decision", "3.75 to 4.00%; Oct 28", "Second hike", "First cut", "Pending", "Apply the rule 7a.1 gross scaler", "warn"],
      ["Brent crude", "$126.55 spot (EIA, Oct 14); about $107 futures (IEA)", "Above $110", "Below $80", "Risk-off on spot", "Add energy call spreads; take hedge profits below $80", "bad"],
      ["Sentiment and real spending", "UMich 46.3 (Oct prelim); real PCE from the daily run", "Real PCE down 2 months", "Sentiment above 55", "Watch", "Cut discretionary; favor staples and trade-down retailers", "warn"],
      ["Useful-life disclosures", "No reset yet", "Any shortening or SEC letter", "Capex up with FCF rising", "Calm", "Hedge neoclouds and GPU lenders; trim second-derivative suppliers", "good"],
      ["Memory contract prices", "Rising every quarter of 2026", "First sequential decline", "Continued rises", "Risk-on", "On the first decline, exit memory trades", "good"],
      ["BDC redemption queue", "BCRED about 10% vs 5% cap; Blue Owl tech fund 38%", "Above 15% across the cohort", "Below 5%", "Watch", "Above 15%: widen the haircut on all private marks", "warn"],
      ["Amended PIK and non-accruals", "PIK about 11% of loans (Q2)", "Amended PIK up 2 quarters", "Falling", "Watch", "Underweight high-PIK lenders; buy discounted secondaries", "warn"],
    ];
    const box = $("#bs-board");
    box.replaceChildren();
    rows.forEach(([n, latest, off, on, state, act, lvl]) => {
      const c = h("article", "sig l" + (lvl === "bad" ? 2 : lvl === "warn" ? 1 : 0));
      const top = h("div", "sig-top");
      top.append(h("span", "sig-name", n), h("span", "sig-state", state));
      c.append(top, h("span", "sig-val text", latest), h("span", "sig-rule", `Risk-off: ${off}. Risk-on: ${on}.`), h("span", "sig-act", act));
      box.append(c);
    });
  }
  function buildBuyside() {
    ["#bd-c", "#bd-l"].forEach((id) => $(id) && $(id).addEventListener("input", () => guard("Depreciation calculator", updateDeprCalc, $("#bd-chart"))));
    ["#ce-ni", "#ce-de", "#ce-db", "#ce-sbc", "#ce-sw", "#ce-dr", "#ce-sh"].forEach((id) => $(id) && $(id).addEventListener("input", () => guard("Cash earnings bridge", updateCashEps)));
    ["#rd-mv", "#rd-f", "#rd-rf", "#rd-erp", "#rd-g3"].forEach((id) => $(id) && $(id).addEventListener("input", () => guard("Reverse DCF", updateRevDcf)));
    ["#cs-b", "#cs-s", "#cs-d", "#cs-r", "#cs-m"].forEach((id) => $(id) && $(id).addEventListener("input", () => guard("Credit stress", updateCredit)));
    ["#mb-e", "#mb-p", "#mb-s", "#mb-atr"].forEach((id) => $(id) && $(id).addEventListener("input", () => guard("Moonbag", updateMoonbag)));
    const pre = $("#cs-presets");
    CS_PRESETS.forEach(([n, d, r]) => {
      const b = h("button", null, n);
      b.type = "button"; b.dataset.d = d; b.dataset.r = r;
      b.addEventListener("click", () => { $("#cs-d").value = d * 100; $("#cs-r").value = r * 100; guard("Credit stress", updateCredit); });
      pre.append(b);
    });
    guard("Regime and gross", renderBsRegime, $("#bs-reg-tiles"));
    guard("Hedge selector", renderBsSelector, $("#bs-sel"));
    guard("Manual board", renderManualBoard, $("#bs-board"));
    guard("Red flags", renderRedFlags, $("#bs-flags"));
    guard("Replays", renderBsReplays, $("#bs-replay"));
    guard("Cash earnings bridge", updateCashEps);
    guard("Reverse DCF", updateRevDcf);
    guard("Credit stress", updateCredit);
    guard("Moonbag", updateMoonbag);
  }
  function drawBuyside() {
    guard("Depreciation calculator", updateDeprCalc, $("#bd-chart"));
    guard("Hedge selector", drawBsSelector);
    guard("Fat tails", renderBsTails, $("#bs-tail"));
    guard("Replays", renderBsReplays, $("#bs-replay-chart"));
  }

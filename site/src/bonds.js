  /* =====================================================================================
     bonds.js (v0.17): the "Bonds, simply" desk. Two sliders set the 10-year and 30-year yields; every Treasury ETF is
     repriced on today's curve by bondlab.js (the mirror of buildout/bondlab.py). Today's tape, the model's check
     against it, the stock read-through by inflation band and the four things a bond is.
     ===================================================================================== */
  const BD_ORDER = ["SHY", "IEI", "IEF", "TLH", "TLT", "EDV", "ZROZ"];
  const BD = { y10: null, y30: null, front: "parallel", lock: true, funds: null, ready: false };
  function bdOk() {
    try { return typeof BONDS17 === "object" && BONDS17.curve && fin(BONDS17.curve["10y"]) && fin(BONDS17.curve["30y"]) && BONDS17.funds && BONDS17.funds.TLT && fin(BONDS17.funds.TLT.coupon); } catch (e) { return false; }
  }
  const bdP = (y) => (y * 100).toFixed(2) + "%";
  const bdUsd = (v) => (fin(v) ? "$" + v.toFixed(2) : "");
  const bdBp = (v) => bp(v * 1e4);
  function bdFunds() {
    if (BD.funds) return BD.funds;
    const out = {};
    BD_ORDER.forEach((t) => { const f = BONDS17.funds[t]; if (f) out[t] = Object.assign({}, f, { mats: blLadder(f) }); });
    BD.funds = out;
    return out;
  }
  function renderBonds() {
    const tiles = $("#bd-tiles");
    if (!tiles || !bdOk()) { if (tiles && !tiles.children.length) tiles.append(h("p", "hint", "The bond snapshot is missing or malformed.")); return; }
    if (BD.ready) { bdUpdate(); return; }
    BD.ready = true;
    const C = BONDS17.curve, cs = BONDS17.cases, T = (k) => cs[k].funds.TLT, tlt = BONDS17.funds.TLT, fa = (BONDS17.facts || {}).TLT || {};
    $("#bd-lede").textContent = `If the 10-year and 30-year both go to 4%, TLT is worth about ${bdUsd(T("both_4").price)} (${pct(T("both_4").change)}) from ${bdUsd(tlt.price)}; at 6%, about ${bdUsd(T("both_6").price)} (${pct(T("both_6").change)}). `
      + `The latest closing curve (${BONDS17.curve_meta ? BONDS17.curve_meta.as_of : ""}) has the 10-year at ${bdP(C["10y"])} and the 30-year at ${bdP(C["30y"])}. A Treasury ETF never matures, so it trades like a stock whose price is the yield moves times its duration, with convexity on top; set the yields below and every fund reprices bond by bond.`;
    [[bdUsd(T("both_4").price), "TLT if both go to 4%", pct(T("both_4").change) + " now, " + pct(T("both_4").total) + " over 12 months with income"],
      [bdUsd(T("both_6").price), "TLT if both go to 6%", pct(T("both_6").change) + " now, " + pct(T("both_6").total) + " over 12 months with income"],
      [fx((fa.duration || tlt.duration), 2) + " yrs", "TLT duration", `reported by iShares (${fa.duration_as_of || "model"}); 1bp is about ${fx((fa.duration || tlt.duration) * (tlt.price || 0) / 1e4, 3)} dollars a share`],
      [Math.round(BONDS17.breakeven.TLT * 1e4) + " bp", "TLT break-even", "the yield rise a year of income covers"]].forEach(([v, k, s]) => { const d = h("div", "at-kpi"); d.append(h("b", null, v), h("span", null, k), h("small", null, s)); tiles.append(d); });
    const y10 = $("#bd-y10"), y30 = $("#bd-y30");
    BD.y10 = C["10y"]; BD.y30 = C["30y"];
    y10.value = (BD.y10 * 100).toFixed(2); y30.value = (BD.y30 * 100).toFixed(2);
    const onSlide = (which) => {
      const a = Number(y10.value) / 100, b = Number(y30.value) / 100;
      if (BD.lock) {
        const d = which === "10" ? a - BD.y10 : b - BD.y30;
        BD.y10 = Math.max(0.025, Math.min(0.08, BD.y10 + d)); BD.y30 = Math.max(0.025, Math.min(0.08, BD.y30 + d));
        y10.value = (BD.y10 * 100).toFixed(2); y30.value = (BD.y30 * 100).toFixed(2);
      } else { BD.y10 = a; BD.y30 = b; }
      bdUpdate();
    };
    y10.addEventListener("input", () => onSlide("10"));
    y30.addEventListener("input", () => onSlide("30"));
    $("#bd-lock").addEventListener("change", (e) => { BD.lock = e.target.checked; });
    const pre = $("#bd-pre"), tape = (BONDS17.today || {});
    const presets = [["Today", C["10y"], C["30y"]], ["Both 4%", 0.04, 0.04], ["Both 5%", 0.05, 0.05], ["Both 6%", 0.06, 0.06], [MINUS + "100bp", C["10y"] - 0.01, C["30y"] - 0.01], ["+100bp", C["10y"] + 0.01, C["30y"] + 0.01]];
    if (fin(tape.d10)) presets.splice(1, 0, ["Oct 22 midday", C["10y"] + tape.d10, C["30y"] + tape.d30]);
    presets.forEach(([lab, a, b]) => {
      const bt = h("button", null, lab); bt.type = "button";
      bt.addEventListener("click", () => { bdSet(a, b); });
      pre.append(bt);
    });
    $("#bd-front").querySelectorAll("button").forEach((bt) => bt.addEventListener("click", () => {
      BD.front = bt.dataset.f;
      $("#bd-front").querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", x === bt ? "true" : "false"));
      bdHeat(); bdUpdate();
    }));
    bdHeat();
    bdUpdate();
    bdTape();
    bdEquity();
    bdFour();
    const src = h("span");
    src.append("Curve: ", bdLink("US Treasury daily par yield curve", "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/TextView?type=daily_treasury_par_yield_curve&field_tdr_date_value_month=202610"),
      ". Fund durations, maturities, yields and prices: the issuers' fund pages (iShares, Vanguard), each checked by a second agent. Stock read-through: Shiller's monthly data since 1871. Tape: the sources linked in the table. The model book shown elsewhere is a model, not personal positions.");
    $("#bd-src").replaceChildren(src);
  }
  function bdLink(t, u) { const a = h("a", null, t); a.href = u; a.target = "_blank"; a.rel = "noopener"; return a; }
  function bdSet(a, b) {
    BD.y10 = Math.round(a * 1e4) / 1e4; BD.y30 = Math.round(b * 1e4) / 1e4;
    $("#bd-y10").value = (BD.y10 * 100).toFixed(2); $("#bd-y30").value = (BD.y30 * 100).toFixed(2);
    bdUpdate();
  }
  function bdUpdate() {
    if (!BD.ready) return;
    const C = BONDS17.curve, F = bdFunds(), sc = blScenario(C, F, BD.y10, BD.y30, BD.front);
    $("#bd-y10-v").textContent = `${bdP(BD.y10)} (${bdBp(BD.y10 - C["10y"])})`;
    $("#bd-y30-v").textContent = `${bdP(BD.y30)} (${bdBp(BD.y30 - C["30y"])})`;
    const t = sc.TLT, f = F.TLT, hero = $("#bd-hero");
    hero.replaceChildren();
    const big = h("div", "bd-big");
    big.append(h("span", "eyebrow", "TLT at these yields"), h("b", null, bdUsd(t.price) || pct(t.change)), h("span", t.change >= 0 ? "pos" : "neg", `${pct(t.change)} now · ${pct(t.total)} over 12 months with income`));
    const avg = f.mats.reduce((s, T) => s + blShift(T, BD.y10 - C["10y"], BD.y30 - C["30y"], BD.front), 0) / f.mats.length;
    const rule = -f.duration * avg;
    const why = h("p", "prose", `TLT's bonds mature in ${fx(f.a == null ? f.lo : f.a, 0)} to ${fx(f.b == null ? f.hi : f.b, 0)} years, so their yields move about ${bdBp(avg)} on average. Duration alone says ${pct(rule)}; repricing every bond says ${pct(t.change)}. The difference, ${pct(t.change - rule)}, is convexity. `
      + (t.total > t.change ? `Holding a year adds ${pct(t.total - t.change)} of coupons and roll.` : `Holding a year: ${pct(t.total)} in all.`));
    hero.append(big, why);
    const rows = Object.keys(F).map((k) => {
      const ff = F[k], s = sc[k], fa = (BONDS17.facts || {})[k] || {};
      const chg = h("span", s.change >= 0 ? "pos" : "neg", pct(s.change)), tot = h("span", s.total >= 0 ? "pos" : "neg", pct(s.total));
      return [k, `${fx(ff.lo, 0)} to ${fx(ff.hi, 0)}${ff.zero ? " (zeros)" : ""}`, fx(fa.duration || ff.duration, 2) + (fa.duration ? "" : "*"), fa.ytm ? bdP(fa.ytm) : bdP(ff.ytm) + "*", bdUsd(ff.price) || "n/a", bdUsd(s.price) || "n/a", chg, tot, bdBp(blBreakeven(ff))];
    });
    fillTable($("#bd-table"), ["Fund", "Maturities, years", "Duration", "Yield", "Price now", "At these yields", "Change", "12 months, with income", "Break-even rise"], rows, 2);
    $("#bd-table-note").textContent = "Duration and yield as reported by the issuer; * where the issuer's figure was not available here, the model's (ZROZ from its index range). Prices are Oct 21 closes or NAVs. The 12-month return assumes the move happens now and yields then hold: coupons are earned and each bond rolls down the curve. Break-even is yield divided by duration: how far yields can rise in a year before the income is gone.";
    bdPxChart();
    bdCurveChart();
    bdHeatMark();
  }
  function bdPxChart() {
    const C = BONDS17.curve, F = bdFunds(), f = F.TLT, base = f.price || 100, pts = [], lin = [];
    const lv = (C["10y"] + C["30y"]) / 2;
    for (let y = 0.03; y <= 0.0701; y += 0.0025) {
      const d10 = y - C["10y"], d30 = y - C["30y"];
      const v = blValue(C, f.mats, f.coupon, y, y, BD.front) / blValue(C, f.mats, f.coupon) - 1;
      pts.push([Math.round(y * 1e4) / 100, base * (1 + v)]);
      const avg = f.mats.reduce((s, T) => s + blShift(T, d10, d30, BD.front), 0) / f.mats.length;
      lin.push([Math.round(y * 1e4) / 100, base * (1 - f.duration * avg)]);
    }
    const cur = (BD.y10 + BD.y30) / 2;
    xyChart($("#bd-px-chart"), { series: [{ name: "TLT, every bond repriced", pts, color: "var(--s1)", width: 2.5 }, { name: "Duration rule", pts: lin, color: "var(--muted)", width: 1.5 }],
      height: 250, yfmt: (v) => "$" + v.toFixed(0), xfmt: (v) => v.toFixed(2) + "% both", xticks: [3, 4, 5, 6, 7].map((x) => [x, x + "%"]),
      vmarks: [{ x: Math.round(lv * 1e4) / 100, label: "today" }].concat(Math.abs(cur - lv) > 0.0005 ? [{ x: Math.round(cur * 1e4) / 100, label: "set" }] : []), label: "TLT price against the level of the 10-year and 30-year yields" });
    legendLines($("#bd-px-legend"), [["var(--s1)", "Every bond repriced"], ["var(--muted)", "Duration rule"]]);
  }
  function bdCurveChart() {
    const C = BONDS17.curve, t0 = [], t1 = [];
    BL_KEYS.forEach((k, i) => {
      const T = BL_TENORS[i];
      if (C[k] == null || T < 1) return;
      t0.push([T, C[k] * 100]);
      t1.push([T, blMoved(C, T, BD.y10, BD.y30, BD.front) * 100]);
    });
    xyChart($("#bd-cv-chart"), { series: [{ name: "Today", pts: t0, color: "var(--muted)", width: 1.5, dots: true }, { name: "Set", pts: t1, color: "var(--s1)", width: 2.5, dots: true }],
      height: 250, yfmt: (v) => v.toFixed(2) + "%", xfmt: (v) => v + " years", xticks: [[1, "1y"], [2, "2y"], [5, "5y"], [10, "10y"], [20, "20y"], [30, "30y"]], snapXs: t0.map((p) => p[0]), label: "Par yield curve today and after the move" });
    legendLines($("#bd-cv-legend"), [["var(--muted)", "Today"], ["var(--s1)", "After your move"]]);
    $("#bd-cv-note").textContent = `Today's 20-year (${bdP(C["20y"])}) sits above the 30-year (${bdP(C["30y"])}); the move keeps that hump. The 2-year is ${bdP(C["2y"])}: ${BD.front === "anchored" ? "with the front end anchored, short yields barely move, so SHY and IEI change little." : "with the front end moving like the 10-year, the whole curve shifts."}`;
  }
  function bdHeat() {
    const C = BONDS17.curve, F = bdFunds(), g = blGrid(C, F.TLT, 0.03, 0.07, 0.005, BD.front), tb = $("#bd-heat");
    tb.replaceChildren();
    const hd = h("tr"); hd.append(h("th", null, "10y \\ 30y"));
    const lab = (y) => (y * 100).toFixed(1) + "%";
    g.y.forEach((y) => hd.append(h("th", "r", lab(y))));
    const th = h("thead"); th.append(hd); tb.append(th);
    const body = h("tbody");
    g.y.forEach((a, i) => {
      const tr = h("tr"); tr.append(h("th", null, lab(a)));
      g.y.forEach((b, j) => {
        const v = g.change[i][j], td = h("td", "r bd-cell", pct(v, 0));
        const w = Math.min(100, Math.abs(v) * 220);
        td.style.background = `color-mix(in srgb, ${v >= 0 ? "var(--grid-pos)" : "var(--grid-neg)"} ${w}%, transparent)`;
        td.dataset.a = a; td.dataset.b = b; td.tabIndex = 0;
        td.title = `10-year ${bdP(a)}, 30-year ${bdP(b)}: TLT ${pct(v)}`;
        const go = () => bdSet(a, b);
        td.addEventListener("click", go);
        td.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); } });
        tr.append(td);
      });
      body.append(tr);
    });
    tb.append(body);
  }
  function bdHeatMark() {
    $("#bd-heat").querySelectorAll(".bd-cell").forEach((td) => td.classList.toggle("on", Math.abs(Number(td.dataset.a) - BD.y10) < 0.0025 && Math.abs(Number(td.dataset.b) - BD.y30) < 0.0025));
  }
  function bdTape() {
    const T = (typeof TAPE17 !== "undefined" ? TAPE17 : []) || [], by = {};
    T.forEach((x) => { by[x.id] = x; });
    const want = [["tp-qqq-1022", "QQQ (Nasdaq-100 fund)"], ["tp-nasdaq-1022", "Nasdaq Composite"], ["tp-sp500-1022", "S&P 500"], ["tp-meta-1022", "Meta"], ["tp-avgo-1022", "Broadcom"],
      ["tp-nvda-1022", "Nvidia"], ["tp-orcl-1022", "Oracle"], ["tp-msft-1022", "Microsoft"], ["tp-tsla-1022", "Tesla"], ["tp-lrcx-1022", "Lam Research"], ["tp-tlt-1022", "TLT (20+ year Treasuries)"],
      ["tp-10y-1022", "10-year yield"], ["tp-30y-1022", "30-year yield"], ["tp-brent-1022", "Brent crude"], ["tp-vix-1022", "VIX"]];
    const rows = [];
    want.forEach(([id, name]) => {
      const x = by[id];
      if (!x) return;
      const tm = (x.text.match(/(\d{1,2}:\d{2} [ap]\.m\. ET)/) || [])[1] || (x.text.includes("early") ? "early" : "");
      const v = x.unit === "percent" && /yield/.test(name) ? (x.value).toFixed(2) + "%" : x.unit === "percent" ? pct(x.value / 100, 2) : fx(x.value, 2);
      const lv = /yield/.test(name) ? (x.text.match(/(fell|rose) (\d+) basis points/) || [])[0] || "" : (x.text.match(/\$[\d,]+\.\d+/) || [])[0] || "";
      rows.push([name, h("span", /yield/.test(name) ? "" : x.value >= 0 ? "pos" : "neg", v), lv, tm, x.source_url ? bdLink(x.publisher || "source", x.source_url) : ""]);
    });
    fillTable($("#bd-tape"), ["", "Move", "Level", "Time", "Source"], rows, 1);
    const why = ["tp-why-ai", "tp-why-yields"].map((k) => by[k]).filter(Boolean);
    const eq = BONDS17.equity || {}, now = eq.now, r = now && eq[now.regime];
    $("#bd-tape-read").textContent = (why.length ? why.map((x) => x.text).join(" ") + " " : "")
      + (r ? `Read through the history: with inflation at ${pct(now.infl36, 1, false)} a year over three years, the middle band, stocks have tended to fall when yields rise (${pct(r.per_point)} per point). Today ran the other way: yields fell while stocks fell, the pattern of a growth or earnings scare with a flight to safety, when long bonds do hedge. On the reported reasons, the selloff moved rates rather than rates moving stocks.` : "");
    const ck = BONDS17.today, box = $("#bd-check");
    box.replaceChildren();
    if (ck) {
      box.append(h("p", "prose", `At ${ck.yield_time}, the 10-year was ${bdBp(ck.d10)} and the 30-year ${bdBp(ck.d30)} on the day. Repricing TLT's ladder for that move gives ${pct(ck.model_tlt, 2)}; TLT was ${pct(ck.actual_tlt, 2)} at ${ck.tlt_time}, by which time the 10-year had fallen further (4.97% on a later quote). The model and the market agree to within the drift in yields between the two times.`));
      const bt = h("button", "btn", "Set the sliders to the midday move"); bt.type = "button";
      bt.addEventListener("click", () => bdSet(BONDS17.curve["10y"] + ck.d10, BONDS17.curve["30y"] + ck.d30));
      box.append(bt);
    } else box.append(h("p", "hint", "No intraday check is available."));
  }
  function bdEquity() {
    const eq = BONDS17.equity;
    if (!eq) return;
    const names = { all: "All months since 1871", low_inflation: "Inflation below 2.75%", middle_inflation: "Inflation 2.75% to 4.25%", high_inflation: "Inflation above 4.25%", since_2000: "Since 2000" };
    const now = eq.now ? eq.now.regime : null;
    const rows = Object.keys(names).filter((k) => eq[k]).map((k) => [names[k] + (k === now ? " (now)" : ""), h("span", eq[k].per_point >= 0 ? "pos" : "neg", pct(eq[k].per_point)), fx(eq[k].t, 1), String(eq[k].n), pct(eq[k].r2, 1, false)]);
    fillTable($("#bd-eq"), ["Sample", "S&P 500 real return per point of 10-year rise", "t", "Months", "R squared"], rows, 1);
    if (eq.now) $("#bd-eq-note").textContent = `Inflation over the three years to ${eq.now.as_of}: ${pct(eq.now.infl36, 1, false)} a year on Shiller's consumer price series (3.06% on the BLS figure the Today desk uses); either way, the middle band. In that band a one-point rise in the 10-year has come with about ${pct(eq[eq.now.regime].per_point)} on stocks the same month, so a move to 6% is a stock problem as well as a bond one, and a move to 4% helps both. The fit explains only a few percent of monthly moves: earnings and risk appetite do most of the work.`;
  }
  function bdFour() {
    const f = BONDS17.funds.TLT, C = BONDS17.curve;
    const items = [["A bond is a list of promised payments.", `A coupon every six months and the face value at the end. Its price is those payments discounted at a yield. Nothing else goes into it.`],
      ["Yield and price move opposite, by duration.", `Duration is the price change for a one-point move in yield. TLT's ${fx(f.duration, 1)} years means a one-point rise costs about ${fx(f.duration, 0)}%, a one-point fall earns about the same.`],
      ["Convexity makes the trade lopsided.", `Prices bend with yields: a one-point fall in TLT's yields earns ${pct(BONDS17.cases.down_100.funds.TLT.change)}, a one-point rise costs ${pct(BONDS17.cases.up_100.funds.TLT.change)}. Longer bonds and zero-coupon STRIPS (EDV, ZROZ) bend most.`],
      ["An ETF never matures, so it trades like a stock.", `A single bond pulls back to par as it ages. A fund sells bonds as they leave its range and buys new ones, holding its duration steady, so its price shows the capital gain or loss from every move in yields: ${bdP(C["10y"])} and ${bdP(C["30y"])} today against 4% or 6% is the whole trade.`]];
    const ol = $("#bd-four");
    ol.replaceChildren();
    items.forEach(([t, d]) => { const li = h("li"); li.append(h("b", null, t), h("span", null, " " + d)); ol.append(li); });
  }

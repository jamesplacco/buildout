  /* =====================================================================================
     analysis.js (v0.16): technical and fundamental analysis, the data connections, your broker export read in the
     browser, the reinforcement-learning agent on the ML lab, and the distribution scorecard on the Edge desk.
     brokerWeights mirrors buildout/datahub.py's import_positions (tests/test_v16.py holds them equal).
     ===================================================================================== */
  const AN = { asset: null, co: null };
  const anPct = (v, d = 1) => (fin(v) ? `${v < 0 ? MINUS : v > 0 ? "+" : ""}${Math.abs(v * 100).toFixed(d)}%` : "n/a");
  const anP = (v, d = 0) => (fin(v) ? `${(v * 100).toFixed(d)}%` : "n/a");
  const anX = (v, d = 1) => (fin(v) ? `${v.toFixed(d)}x` : "n/a");
  const AN_SIG = { trend_200: "Above the 200-day average", golden_cross: "50-day above 200-day", macd: "MACD above signal", rsi_extreme: "RSI below 30 / above 70 (fade)",
    bollinger: "Outside a Bollinger band (fade)", momentum_12m: "12-month momentum", breakout_55: "55-day breakout", supertrend: "Supertrend", adx_trend: "ADX trend",
    stochastic: "Stochastic extremes (fade)", cloud: "Ichimoku cloud", obv_trend: "OBV trend", mfi_extreme: "Money-flow extremes (fade)" };
  function anOk() { return typeof SNAP16 === "object" && SNAP16 && TA_SNAP && TA_SNAP.assets && FA_SNAP && FA_SNAP.companies; }
  function renderAnalysisDesk() {
    const tiles = $("#an-tiles");
    if (!tiles || !anOk()) { if (tiles && !tiles.children.length) tiles.append(h("p", "hint", "The analysis data is missing or malformed.")); return; }
    if (tiles.children.length) return;
    const A = TA_SNAP.assets, keys = Object.keys(A);
    const sig = keys.reduce((n, k) => n + Object.values(A[k].studies).filter((s) => s.t != null && s.bh < 0.05).length, 0);
    const tests = keys.reduce((n, k) => n + Object.values(A[k].studies).filter((s) => s.t != null).length, 0);
    const conn = CONN_SNAP.filter((r) => r.ok).length;
    [[String(keys.length), "Series analyzed here", "every holding in the daily run"], [`${sig} of ${tests}`, "Signals that survive", "Benjamini-Hochberg at 5%, on each asset's own history"],
      [String(Object.values(FA_SNAP.companies).filter((c) => c.ok).length), "Companies from filings", "ratios, Piotroski, Altman, Beneish"],
      [`${conn} of ${CONN_SNAP.length}`, "Data sources reachable", "from the build workspace; the daily run checks with the configured keys"]].forEach(([v, k, s]) => { const d = h("div", "at-kpi"); d.append(h("b", null, v), h("span", null, k), h("small", null, s)); tiles.append(d); });
    anAssetSeg();
    anCompanySeg();
    anConnections();
    anBrokerWire();
  }
  function anAssetSeg() {
    const seg = $("#an-seg"), keys = Object.keys(TA_SNAP.assets);
    AN.asset = AN.asset || keys[0];
    keys.forEach((k) => { const b = h("button", null, TA_SNAP.assets[k].name.split(" (")[0]); b.type = "button"; b.dataset.k = k; b.addEventListener("click", () => { AN.asset = k; anAsset(); }); seg.append(b); });
    anAsset();
  }
  function anAsset() {
    const a = TA_SNAP.assets[AN.asset], r = a.readings, st = a.structure;
    $("#an-seg").querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", b.dataset.k === AN.asset ? "true" : "false"));
    const box = $("#an-read");
    box.replaceChildren();
    const card = (title, rows) => { const d = h("div", "panel lb-read"); d.append(h("span", "panel-title", title)); const dl = h("dl", "lb-dl"); rows.forEach(([k, v]) => dl.append(h("dt", null, k), h("dd", null, v))); d.append(dl); return d; };
    const rel = (x) => (fin(x) ? anPct(r.close / x - 1) : "n/a");
    box.append(card(`${a.name} · ${a.date}`, [["vs 50-day average", rel(r.sma50)], ["vs 200-day average", rel(r.sma200)], ["RSI(14)", fx(r.rsi14, 0)], ["MACD minus signal", fx(r.macd - r.macd_signal, 2)],
      ["Bollinger %b", fx(r.bb_pctb, 2)], ["One-month volatility, annual", anP(r.vol21)]]),
      card("Structure", [["From the 52-week high", anPct(st.range_52w.from_high)], ["Above the 52-week low", anPct(st.range_52w.from_low)],
        ["Trend template", st.trend_template ? `${st.trend_template.passed} of ${st.trend_template.of}` : "n/a"], ["RSI divergence", st.rsi_divergence || "none"],
        ["Nearest support", st.levels.support[0] ? `${fx(st.levels.support[0].level, 2)} (${anPct(st.levels.support[0].distance)})` : "none in a year"],
        ["Nearest resistance", st.levels.resistance[0] ? `${fx(st.levels.resistance[0].level, 2)} (${anPct(st.levels.resistance[0].distance)})` : "none in a year"]]),
      card("Composite", [["Evidence-weighted", fx(a.composite, 2)], ["Equal vote", fx(a.naive_vote, 2)], ["Out-of-sample t (second half)", fx(a.composite_oos.t, 2)],
        ["Hit rate out of sample", anP(a.composite_oos.hit)], ["Bars", a.bars.toLocaleString()], ["Source", a.source || ""]]));
    $("#an-text").replaceChildren(...(a.text || []).map((t) => h("li", null, t)));
    const rows = Object.entries(a.studies).filter(([, s]) => s.t != null).sort((x, y) => (x[1].bh || 1) - (y[1].bh || 1));
    fillTable($("#an-ev"), ["Signal", "Now", "Daily edge", "t (Newey-West)", "BH-adjusted p", "In / out of sample t", "Weight"],
      rows.map(([k, s]) => [AN_SIG[k] || k, a.signals_now[k] == null ? "n/a" : a.signals_now[k] > 0 ? "bullish" : a.signals_now[k] < 0 ? "bearish" : "neutral",
        `${fx(s.daily_edge * 1e4, 1)}bp`, fx(s.t, 2), fx(s.bh, 3), `${fx(a.split[k].t_in, 1)} / ${fx(a.split[k].t_out, 1)}`, fx(a.weights[k], 2)]), 1);
    const fib = st.fibonacci;
    fillTable($("#an-fib"), ["Level", "Price"], [["High", fx(fib.high, 2)], ...Object.entries(fib.levels).map(([k, v]) => [`${(Number(k) * 100).toFixed(1)}% retracement`, fx(v, 2)]), ["Low", fx(fib.low, 2)]], 1);
  }
  function anCompanySeg() {
    const seg = $("#an-co-seg"), C = FA_SNAP.companies, keys = Object.keys(C).filter((k) => C[k].ok);
    AN.co = AN.co || keys[0];
    keys.forEach((k) => { const b = h("button", null, k); b.type = "button"; b.dataset.k = k; b.addEventListener("click", () => { AN.co = k; anCompany(); }); seg.append(b); });
    anCompany();
    const last = (c) => c.ratios[c.ratios.length - 1];
    fillTable($("#an-co-all"), ["Company", "Fiscal year", "Revenue growth", "Operating margin", "FCF margin", "Cash conversion", "Capex / D&A", "Rule of 40"],
      keys.map((k) => { const r = last(C[k]); return [k, C[k].fiscal_year_end, anPct(r.revenue_growth), anPct(r.op_margin), anPct(r.fcf_margin), fx(r.cash_conversion, 2), anX(r.capex_to_da), anPct(r.rule_of_40)]; }), 1);
  }
  function anCompany() {
    const c = FA_SNAP.companies[AN.co];
    $("#an-co-seg").querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", b.dataset.k === AN.co ? "true" : "false"));
    fillTable($("#an-co"), ["Fiscal year end", "Revenue ($bn)", "Growth", "Op. margin", "FCF ($bn)", "FCF margin", "Capex / revenue", "Capex / D&A", "Cash conversion"],
      c.ratios.map((r) => [r.end, fin(r.revenue) ? fx(r.revenue / 1e9, 1) : "n/a", anPct(r.revenue_growth), anPct(r.op_margin), fin(r.fcf) ? fx(r.fcf / 1e9, 1) : "n/a", anPct(r.fcf_margin),
        anPct(r.capex_intensity), anX(r.capex_to_da), fx(r.cash_conversion, 2)]), 1);
    const p = c.piotroski;
    const sc = h("div", "an-scores");
    const tile = (k, v, s) => { const d = h("div", "at-kpi"); d.append(h("b", null, v), h("span", null, k), h("small", null, s)); return d; };
    sc.append(tile("Piotroski F", `${p.score} of ${p.known}`, p.known < 9 ? `${9 - p.known} tests need tags the shipped filing extract lacks` : "all nine tests run"),
      tile("Altman Z''", c.altman_z2 ? fx(c.altman_z2.z, 2) : "n/a", c.altman_z2 ? c.altman_z2.zone : "needs current assets and liabilities"),
      tile("Beneish M", c.beneish && c.beneish.m != null ? fx(c.beneish.m, 2) : "n/a", !c.beneish ? "needs two years of revenue" : c.beneish.m == null ? `${c.beneish.neutral_filled.length} of 8 inputs missing; not scored` : c.beneish.neutral_filled.length ? `${c.beneish.neutral_filled.length} of 8 inputs neutral-filled` : "all inputs filed"));
    $("#an-co-scores").replaceChildren(sc);
    $("#an-co-flags").replaceChildren(...c.flags.map((f) => h("li", null, f)));
    $("#an-co-tags").textContent = `Tags used: ${Object.entries(c.tags).map(([k, v]) => `${k} = ${v}`).join("; ")}.`;
  }
  function anConnections() {
    fillTable($("#an-conn"), ["Source", "What", "Cost", "Key", "Reachable from the build workspace", "Note"],
      CONN_SNAP.map((r) => {
        // the build workspace reaches only package registries; an exception's name is for the log, not the reader
        const raw = String(r.note || ""), clean = raw.replace(/;?\s*[A-Za-z]*(?:Error|Exception)\b.*$/, "").trim();
        const note = h("span", "hint", clean || (r.reachable ? "" : "Not reachable from the build workspace; the daily run reaches it"));
        if (raw && raw !== clean) note.title = raw;
        return [r.source, r.what, r.cost, r.credential == null ? "none needed" : r.credential ? "set" : "not set", r.reachable ? `yes (${r.ms} ms)` : "no", note];
      }), 2);
  }
  /* ---------- your broker's export, read in this browser only ---------- */
  function brokerCsv(text) {
    const rows = [];
    let cur = [], f = "", q = false;
    for (let i = 0; i < text.length; i++) {
      const ch = text[i];
      if (q) { if (ch === '"' && text[i + 1] === '"') { f += '"'; i++; } else if (ch === '"') q = false; else f += ch; }
      else if (ch === '"') q = true;
      else if (ch === ",") { cur.push(f); f = ""; }
      else if (ch === "\n" || ch === "\r") { if (ch === "\r" && text[i + 1] === "\n") i++; cur.push(f); rows.push(cur); cur = []; f = ""; }
      else f += ch;
    }
    if (f !== "" || cur.length) { cur.push(f); rows.push(cur); }
    return rows.filter((r) => r.some((c) => c.trim() !== ""));
  }
  function brokerWeights(text) {
    const rows = brokerCsv(String(text).replace(/^﻿/, ""));
    if (rows.length < 2) throw new Error("empty file");
    const head = rows[0].map((c) => c.toLowerCase().trim());
    const pick = (...names) => { for (const n of names) { const i = head.indexOf(n); if (i >= 0) return i; } return -1; };
    const sym = pick("symbol", "ticker", "instrument"), val = pick("market value", "equity", "value", "current value", "market_value"),
      qty = pick("quantity", "shares", "qty"), px = pick("price", "last price", "average cost", "current price"), wt = pick("weight", "% of account", "percent of account");
    if (sym < 0) throw new Error("no symbol column");
    const num = (s) => parseFloat(String(s == null ? "" : s).replace(/[$,%]/g, "").trim() || "0") || 0;
    const pos = {};
    rows.slice(1).forEach((r) => {
      const s = String(r[sym] || "").trim().toUpperCase();
      if (!s || ["CASH", "TOTAL", "ACCOUNT TOTAL"].includes(s) || !/^[A-Z0-9]+$/.test(s.replace(/[.-]/g, ""))) return;
      let v;
      if (val >= 0) v = num(r[val]); else if (qty >= 0 && px >= 0) v = num(r[qty]) * num(r[px]); else if (wt >= 0) v = num(r[wt]); else throw new Error("need a value, quantity and price, or weight column");
      pos[s] = (pos[s] || 0) + v;
    });
    const tot = Object.values(pos).filter((v) => v > 0).reduce((a, b) => a + b, 0);
    const weights = {};
    if (tot > 0) Object.entries(pos).sort((a, b) => b[1] - a[1] || (a[0] < b[0] ? -1 : 1)).forEach(([k, v]) => { weights[k] = v / tot; });
    return { weights, total: tot, n: Object.keys(pos).length };
  }
  function anBrokerWire() {
    const inp = $("#an-file"), out = $("#an-broker");
    const show = (text) => {
      try {
        const r = brokerWeights(text), book = BOOK;
        const names = [...new Set([...Object.keys(r.weights), ...Object.keys(book)])].sort((a, b) => (r.weights[b] || 0) - (r.weights[a] || 0));
        out.replaceChildren(h("p", null, `${r.n} positions read in this browser; nothing was uploaded or stored.`),
          tableBlock(["Symbol", "Your weight", "Model book", "Gap"], names.slice(0, 40).map((k) => [k, anP(r.weights[k] || 0, 1), anP(book[k] || 0, 1), anPct((r.weights[k] || 0) - (book[k] || 0), 1)]), 1),
          h("p", "hint", "To run them through the engine's lenses, pass the same weights to the MCP tool analyze_positions, or locally: python -m buildout positions export.csv."));
      } catch (e) { out.replaceChildren(h("p", "hint", `Could not read that file: ${e.message}. It needs a symbol column and a market value, quantity and price, or weight column.`)); }
    };
    inp.addEventListener("change", () => { const f = inp.files && inp.files[0]; if (!f) return; const rd = new FileReader(); rd.onload = () => show(rd.result); rd.readAsText(f); });
    $("#an-paste").addEventListener("input", () => { const t = $("#an-paste").value; if (t.trim().length > 10) show(t); });
  }

  /* ---------- the reinforcement-learning agent, on the ML lab ---------- */
  function renderRlBlock() {
    const box = $("#rl-tiles");
    if (!box || !RL_SNAP || !RL_SNAP.configs || box.children.length) return;
    const b = RL_SNAP.configs[RL_SNAP.best], H = RL_SNAP.hold, T = RL_SNAP.trend;
    [[`${fx(b.perf.sharpe, 2)}`, "Agent's Sharpe", `holding ${fx(H.sharpe, 2)}, trend rule ${fx(T.sharpe, 2)}`], [anP(b.perf.maxdd), "Agent's worst drawdown", `holding ${anP(H.maxdd)}, trend ${anP(T.maxdd)}`],
      [anP(RL_SNAP.deflated_excess.dsr), "Chance its edge is real", `deflated for ${Object.keys(RL_SNAP.configs).length} configurations`], [`${fx(RL_SNAP.now.action, 1)}x`, "Today's exposure", `state as of ${RL_SNAP.now.date}`]]
      .forEach(([v, k, s]) => { const d = h("div", "at-kpi"); d.append(h("b", null, v), h("span", null, k), h("small", null, s)); box.append(d); });
    $("#rl-sum").textContent = RL_SNAP.findings.join(" ");
    fillTable($("#rl-cfg"), ["Configuration", "Sharpe", "Real growth", "Worst drawdown", "Average exposure", "Months out", "Months levered"],
      Object.entries(RL_SNAP.configs).map(([k, c]) => [k.replace(/_/g, " "), fx(c.perf.sharpe, 2), anPct(c.perf.cagr), anP(c.perf.maxdd), anX(c.avg_exposure, 2), anP(c.time_out), anP(c.time_levered)]), 1);
    const cv = RL_SNAP.curve;
    xyChart($("#rlx-curve"), { height: 240, label: "Log real wealth since 1940: the agent, holding and the trend rule", series: [
      { pts: cv.dates.map((d, i) => [lDate(d), cv.hold[i]]), color: "var(--s1)", name: "Hold" }, { pts: cv.dates.map((d, i) => [lDate(d), cv.trend[i]]), color: "var(--good)", name: "Trend rule" },
      { pts: cv.dates.map((d, i) => [lDate(d), cv.agent[i]]), color: "var(--warn)", name: "Agent" }], xticks: [1950, 1970, 1990, 2010].map((y) => [y, String(y)]), yfmt: (v) => fx(v, 1) });
    legendLines($("#rlx-curve-l"), [["var(--s1)", "Hold"], ["var(--good)", "10-month trend rule"], ["var(--warn)", "RL agent"]]);
  }

  /* ---------- distribution, on the Edge desk ---------- */
  function renderDistribution() {
    const box = $("#ed-dist");
    if (!box || !Array.isArray(DIST_SNAP) || box.children.length) return;
    const by = {};
    DIST_SNAP.filter((x) => x.ticker || /spacex/.test(x.id)).forEach((x) => { const k = x.ticker || "SpaceX"; (by[k] = by[k] || []).push(x); });
    Object.entries(by).forEach(([k, xs]) => {
      const c = h("article", "ed-card");
      c.append(h("span", "ed-kind", k));
      const ul = h("ul", "ed-list");
      xs.forEach((x) => { const li = h("li"); const a = h("a", null, x.publisher || "source"); a.href = x.source_url; a.target = "_blank"; a.rel = "noopener"; li.append(h("b", null, x.title + ". "), `${x.text} `, a); ul.append(li); });
      c.append(ul);
      box.append(c);
    });
    const idea = DIST_SNAP.filter((x) => !x.ticker && !/spacex/.test(x.id));
    const ul = h("ul", "ed-list");
    idea.forEach((x) => { const li = h("li"); const a = h("a", null, x.publisher || "source"); a.href = x.source_url; a.target = "_blank"; a.rel = "noopener"; li.append(h("b", null, x.title + ". "), `${x.text} `, a); ul.append(li); });
    $("#ed-dist-idea").replaceChildren(ul);
  }

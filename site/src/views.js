  /* =====================================================================================
     DESK
     ===================================================================================== */
  const cssVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

  // The one governing size: the decision engine's gated equity exposure (snap19). Every other size on the site is a
  // cross-check and says so beside this number (audit v0.24, blocker 1).
  function govSize() {
    try {
      const D = typeof DX19 !== "undefined" ? DX19 : null, N = D && D.now;
      if (!N || !fin(N.exposure)) return null;
      const hedge = N.hedge && N.hedge.choice === "bonds" ? "with a 30% Treasury sleeve" : N.hedge && N.hedge.choice === "cash" ? "with a 30% cash sleeve" : "with no bond sleeve";
      return { x: N.exposure, max: 1.5, date: N.date, hedge, words: `${xx(N.exposure)} equity ${hedge}` };
    } catch (e) { return null; }
  }
  // "Governing size 1.00x equity (decision engine, gated). <what> is a cross-check, not the call."
  function govNote(what, x) {
    const G = govSize();
    if (!G) return "";
    const same = fin(x) && Math.abs(x - G.x) < 0.005;
    return `Governing size: ${G.words}, the decision engine's gated call (${typeof monthNice === "function" ? monthNice(G.date + "-01") : G.date} data). ${what} is a cross-check, not the call${same ? "" : fin(x) ? `; it differs from the governing size by ${(x - G.x) >= 0 ? "+" : ""}${fx(x - G.x, 2)}x` : ""}.`;
  }

  // Guilloche rosette: overlapping hypotrochoids, the engraving pattern on a bond certificate.
  let rosetteDrawn = false, rosetteAnimating = false;
  function drawRosette(animate) {
    const c = $("#rosette");
    if (!c || !c.clientWidth) return;
    const dpr = window.devicePixelRatio || 1, size = c.clientWidth;
    c.width = Math.round(size * dpr); c.height = Math.round(size * dpr);
    const ctx = c.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const cx = size / 2, cy = size / 2, scale = size / 330;
    const ink = cssVar("--accent") || "#1d5b49", ink2 = cssVar("--muted") || "#6f7c76";
    const curves = [];
    const R = 120 * scale, r = 45 * scale;
    for (let k = 0; k < 18; k++) curves.push({ R, r, d: (36 + k * 2.2) * scale, rot: (k * Math.PI) / 54, color: ink, alpha: 0.5 });
    for (let k = 0; k < 10; k++) curves.push({ R: 140 * scale, r: 10 * scale, d: (6 + k * 0.6) * scale, rot: k * 0.05, color: ink2, alpha: 0.35, outer: true });
    function path(cv, frac) {
      const turns = cv.outer ? 1 : 3, steps = cv.outer ? 900 : 1400, end = Math.floor(steps * frac);
      ctx.beginPath();
      for (let i = 0; i <= end; i++) {
        const t = (i / steps) * Math.PI * 2 * turns, k = (cv.R - cv.r) / cv.r;
        let x = (cv.R - cv.r) * Math.cos(t) + cv.d * Math.cos(k * t);
        let y = (cv.R - cv.r) * Math.sin(t) - cv.d * Math.sin(k * t);
        if (cv.outer) { x = (cv.R + cv.r) * Math.cos(t) - cv.d * Math.cos(((cv.R + cv.r) / cv.r) * t); y = (cv.R + cv.r) * Math.sin(t) - cv.d * Math.sin(((cv.R + cv.r) / cv.r) * t); }
        const xr = x * Math.cos(cv.rot) - y * Math.sin(cv.rot), yr = x * Math.sin(cv.rot) + y * Math.cos(cv.rot);
        if (i === 0) ctx.moveTo(cx + xr, cy + yr); else ctx.lineTo(cx + xr, cy + yr);
      }
      ctx.strokeStyle = cv.color; ctx.globalAlpha = cv.alpha; ctx.lineWidth = 0.6; ctx.stroke(); ctx.globalAlpha = 1;
    }
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (rosetteAnimating) return;
    if (!animate || reduce || rosetteDrawn) { ctx.clearRect(0, 0, size, size); curves.forEach((cv) => path(cv, 1)); rosetteDrawn = true; return; }
    rosetteAnimating = true;
    const t0 = performance.now(), dur = 1400;
    (function frame(now) {
      const f = Math.min(1, Math.max(0, (now - t0) / dur)), e = 1 - Math.pow(1 - f, 3);
      ctx.clearRect(0, 0, size, size);
      curves.forEach((cv) => path(cv, e));
      if (f < 1) requestAnimationFrame(frame); else { rosetteDrawn = true; rosetteAnimating = false; }
    })(t0);
  }

  const EXTRA_NOTE = { vix: "S&P 500 implied volatility, 30 days.", hy_oas: "ICE BofA US High Yield, option-adjusted.", ig_oas: "ICE BofA US Corporate, option-adjusted.",
    term_premium10: "Kim-Wright model, 10-year zero.", dollar_broad: "Fed nominal broad index.", fwd5y5y: "Inflation expected for the five years starting five years out." };
  const LEVEL_NOTE = { real10: "10-year TIPS yield.", breakeven10: "10-year nominal minus TIPS.", brent: "Europe Brent spot, per barrel.", vix: "S&P 500 implied volatility, 30 days.",
    vxn: "Nasdaq-100 implied volatility, 30 days.", hy_oas: "ICE BofA US High Yield, option-adjusted.", ccc_oas: "ICE BofA CCC and lower, option-adjusted.",
    usdjpy: "Yen per dollar.", bitcoin: "Coinbase, daily." };
  // a "Live" badge that turns into "Stale" once data is more than STALE_AFTER weekdays old
  const STALE_AFTER = 3;
  // series that publish with a lag (EIA oil, the Kim-Wright model, the Fed's weekly balance sheet) get a longer leash
  const STALE_DAYS = { brent: 8, wti: 8, oil: 8, term_premium10: 8, weekly: 8 };
  function liveBadge(iso, maxAge = STALE_AFTER) {
    const old = weekdaysSince(iso) > maxAge;
    const b = h("span", "badge" + (old ? " stale" : ""), (old ? "Stale · " : "Live · ") + (niceDate(iso) || iso || "n/a"));
    if (old) b.title = `Last daily run data is from ${niceDate(iso)}; check System status on the Engine desk.`;
    return b;
  }
  function srcNode(src) {
    const el = h("span", "src");
    const list = Array.isArray(src && src[0]) ? src : src ? [src] : [];
    list.forEach(([label, url], i) => { if (i) el.append(document.createTextNode(" · ")); const a = h("a", null, label); a.href = url; el.append(a); });
    return el;
  }
  const LIVE_FMT = { "%": (v) => fx(v, 2) + "%", "$": (v) => "$" + fx(v, 2), "$0": (v) => "$" + Math.round(v).toLocaleString("en-US"), n0: (v) => Math.round(v).toLocaleString("en-US"), n2: (v) => fx(v, 2) };
  function renderLevels(live) {
    const box = $("#levels");
    box.replaceChildren();
    const lv = live && live.rates ? live.rates : null, lat = live && live.latest ? live.latest : null;
    const curveMap = {}, soyMap = {};
    const pts = (c) => (c && Array.isArray(c.points) ? c.points : []);
    if (lv && lv.curves) {
      pts(lv.curves.latest).forEach((p) => { curveMap[p.tenor] = p.yield; });
      pts(lv.curves.start_of_year).forEach((p) => { soyMap[p.tenor] = p.yield; });
    }
    LEVELS.forEach((L) => {
      let value = L.value, note = L.note, liveDate = null;
      if (L.live) {
        const [kind, k, f] = L.live, fmt = LIVE_FMT[f || "%"];
        if (kind === "curve" && fin(curveMap[k])) {
          value = fmt(curveMap[k]); liveDate = lv.curves.latest.date;
          note = fin(soyMap[k]) ? `${bp((curveMap[k] - soyMap[k]) * 100)} since ${niceDate(lv.curves.start_of_year.date)}.` : "Treasury constant maturity.";
        } else if (kind === "level" && lv && lv.levels && lv.levels[k] && fin(lv.levels[k].value)) {
          value = fmt(lv.levels[k].value); liveDate = lv.levels[k].date;
          note = LEVEL_NOTE[k] || "";
        } else if (kind === "latest" && lat && fin(lat[k])) {
          value = fmt(lat[k]); liveDate = lat[k + "_date"] || lat.as_of; note = "Daily close.";
        }
      }
      const t = h("article", "tile" + (liveDate ? " live" : ""));
      if (liveDate) t.append(liveBadge(liveDate, STALE_DAYS[L.live[1]] || STALE_AFTER));
      t.append(h("span", "label", L.label), h("span", "value", value), h("span", "note", note));
      t.append(liveDate ? srcNode(L.fid ? F(L.fid) : ["FRED", "https://fred.stlouisfed.org/"]) : srcNode(L.src));
      box.append(t);
    });
    if (lv && lv.levels) {
      LIVE_EXTRA.forEach(([k, label, fmt, fid]) => {
        const o = lv.levels[k];
        if (!o || !fin(o.value)) return;
        const t = h("article", "tile live");
        t.append(liveBadge(o.date, STALE_DAYS[k] || STALE_AFTER), h("span", "label", label), h("span", "value", fmt(o.value)), h("span", "note", EXTRA_NOTE[k] || ""), srcNode(F(fid)));
        box.append(t);
      });
      $("#levels-sub").textContent = "Live tiles come from the engine's daily FRED run; the rest are a dated snapshot from official and market sources.";
    }
  }

  function renderGauge() {
    const box = $("#gauge");
    if (!box || !box.clientWidth) return;
    const W = boxWidth(box), Hh = 112, pad = 6, y = 58, lo = -0.8, hi = 0.8;
    const sx = (v) => pad + ((v - lo) / (hi - lo)) * (W - 2 * pad);
    box.replaceChildren();
    const s = svg("svg", { viewBox: `0 0 ${W} ${Hh}`, width: W, height: Hh }, box);
    svg("rect", { x: sx(lo), y: y - 9, width: sx(0) - sx(lo), height: 18, rx: 4, fill: "var(--zone-good)" }, s);
    svg("rect", { x: sx(0), y: y - 9, width: sx(hi) - sx(0), height: 18, rx: 4, fill: "var(--zone-bad)" }, s);
    svg("line", { x1: sx(0), x2: sx(0), y1: y - 13, y2: y + 13, class: "baseline" }, s);
    [-0.8, -0.4, 0, 0.4, 0.8].forEach((v) => {
      svg("line", { x1: sx(v), x2: sx(v), y1: y + 9, y2: y + 13, class: "baseline" }, s);
      text(s, sx(v), y + 27, v === 0 ? "0" : (v < 0 ? MINUS : "+") + Math.abs(v).toFixed(1), "ax", v === lo ? "start" : v === hi ? "end" : "middle");
    });
    text(s, sx(lo), Hh - 4, "Bonds rise when stocks fall", "ax", "start");
    text(s, sx(hi), Hh - 4, "Bonds fall with stocks", "ax", "end");
    const narrow = W < 520;
    [{ v: -0.6, label: "2020", sub: narrow ? "−0.6" : "about −0.6", anchor: "middle", dx: 0 },
     { v: 0.05, label: narrow ? "2022–26 avg" : "2022–26 average", sub: narrow ? "+0.05" : "about +0.05", anchor: "end", dx: -7 },
     { v: 0.21, label: "Jul 31, 2026", sub: "+0.21", anchor: "start", dx: 7, key: true }].forEach((m) => {
      const x = sx(m.v);
      text(s, x + m.dx, y - 30, m.label, m.key ? "lbl-strong" : "lbl", m.anchor);
      text(s, x + m.dx, y - 16, m.sub, "ax", m.anchor);
      const c = svg("circle", { cx: x, cy: y, r: m.key ? 6 : 4.5, class: "mark-ring", fill: m.key ? "var(--bad)" : "var(--ink-2)", tabindex: "0", "aria-label": `${m.label}: ${m.sub}` }, s);
      bindTip(c, () => [[m.sub, m.label]]);
    });
  }

  /* ---------- live readout (data/macro.json and data/report.json) ---------- */
  const LIVE = { macro: null, report: null, btSeries: null, capex: null, capexPick: null, status: null, problems: [] };
  // fetch with a timeout; a missing, slow or malformed file yields null and a note, never an exception
  async function loadJSON(path, ms = 10000) {
    const ctl = typeof AbortController === "function" ? new AbortController() : null;
    const timer = ctl ? setTimeout(() => ctl.abort(), ms) : 0;
    try {
      const res = await fetch(path, { cache: "no-store", signal: ctl ? ctl.signal : undefined });
      if (!res.ok) return null;
      const text = await res.text();
      try { return JSON.parse(text); } catch (e) { LIVE.problems.push(`${path} is not valid JSON`); return null; }
    } catch (e) { return null; } finally { clearTimeout(timer); }
  }
  const SCHEMA_MAX = 2;
  const getPath = (o, path) => path.split(".").reduce((x, k) => (x == null ? undefined : x[k]), o);
  // returns the list of required paths that are missing or of the wrong kind
  function missingFields(o, spec) {
    return Object.entries(spec).filter(([path, kind]) => {
      const v = getPath(o, path);
      if (kind === "num") return !(typeof v === "number" && fin(v));
      if (kind === "arr") return !Array.isArray(v);
      if (kind === "series") return !(v && Array.isArray(v.dates) && Array.isArray(v.values));
      return v == null || v === "";
    }).map(([path]) => path);
  }
  function errorState(box, title, detail) {
    if (!box) return;
    const e = h("div", "empty error");
    e.append(markEl("vmark"), h("strong", null, title), h("span", null, detail));
    box.replaceChildren(e);
  }
  // error boundary: one failing panel shows a contained message; the rest of the page keeps working
  let rolesQueued = false;
  const scheduleRoles = () => {
    if (rolesQueued || typeof requestAnimationFrame !== "function") return;
    rolesQueued = true;
    requestAnimationFrame(() => { rolesQueued = false; fixChartRoles(); });
  };
  function guard(name, fn, box) {
    try { const out = fn(); scheduleRoles(); return out; } catch (e) {
      console.error("[buildout] " + name, e);
      LIVE.problems.push(`${name}: ${e && e.message ? e.message : e}`);
      errorState(box, `${name} could not render.`, "The rest of the page is unaffected. Details are in the browser console.");
      return null;
    }
  }
  function regimeNode(r) { return h("span", "regime " + (r || "neutral"), r ? r.charAt(0).toUpperCase() + r.slice(1) : "n/a"); }
  function tile(label, value, note) {
    const t = h("article", "tile");
    t.append(h("span", "label", label));
    if (typeof value === "string") t.append(h("span", "value", value)); else { value.classList.add("value"); t.append(value); }
    if (note) t.append(typeof note === "string" ? h("span", "note", note) : note);
    return t;
  }
  function figureBlock(title, legend, id) {
    const f = h("figure", "chart"), head = h("div", "chart-head");
    head.append(h("span", "chart-title", title));
    if (legend && legend.length) {
      const lg = h("span", "legend");
      legend.forEach(([color, label, line]) => { const sp = h("span"); const i = h("i", line ? "ln" : null); i.style.background = color; sp.append(i, document.createTextNode(label)); lg.append(sp); });
      head.append(lg);
    }
    const box = h("div", "svgbox");
    box.id = id;
    f.append(head, box);
    return f;
  }
  function yearlyChart(box, rows) {
    if (!box || !rows.length || !box.clientWidth) return;
    const W = boxWidth(box), Hh = 230, padL = 40, padR = 8, top = 16, bottom = 26;
    const m = Math.max(0.2, ...rows.map((r) => Math.abs(r.corr)));
    const ticks = niceTicks(-m, m, 4), lo = ticks[0], hi = ticks[ticks.length - 1];
    const sy = (v) => top + (1 - (v - lo) / (hi - lo)) * (Hh - top - bottom);
    const band = (W - padL - padR) / rows.length, bw = Math.max(2, Math.min(24, band - 2));
    box.replaceChildren();
    const s = svg("svg", { viewBox: `0 0 ${W} ${Hh}`, width: W, height: Hh, role: "img", "aria-label": "Correlation of Nasdaq-100 and long Treasury daily returns by year" }, box);
    ticks.forEach((t) => {
      svg("line", { x1: padL, x2: W - padR, y1: sy(t), y2: sy(t), class: t === 0 ? "baseline" : "gridline" }, s);
      text(s, padL - 6, sy(t) + 4, t === 0 ? "0" : sgn2(t), "ax", "end");
    });
    const every = band < 14 ? 8 : 4;
    rows.forEach((r, i) => {
      const x = padL + band * i + (band - bw) / 2;
      svg("path", { d: vbar(x, bw, sy(0), sy(r.corr), Math.min(4, bw / 2)), fill: r.corr < 0 ? "var(--s1)" : "var(--red)" }, s);
      if ((r.year - rows[0].year) % every === 0) text(s, x + bw / 2, Hh - 8, String(r.year), "ax", "middle");
      const hit = svg("rect", { x: padL + band * i, y: top, width: band, height: Hh - top - bottom, class: "hit", tabindex: "0", "aria-label": `${r.year}: ${sgn2(r.corr)}` }, s);
      bindTip(hit, () => [[sgn2(r.corr), `${r.year} · ${r.days} trading days`]]);
    });
    const last = rows[rows.length - 1], lx = padL + band * (rows.length - 1) + band / 2;
    text(s, lx, last.corr >= 0 ? sy(last.corr) - 6 : sy(last.corr) + 14, sgn2(last.corr), "lbl-strong", lx > W - 30 ? "end" : "middle");
  }
  const POLICY = { none: "No hedge", static: "Fixed 30%", min_var_long_only: "Min-variance", regime_gated: "Regime-gated" };
  const MACRO_SPEC = { "latest.as_of": "str", "latest.corr63": "num", "latest.corr252": "num", "latest.regime": "str",
    "latest.hedge_ratio_gated": "num", "latest.hedge_ratio_minvar": "num", yearly: "arr", corr63: "series", start: "str" };
  function asOfLine(iso, source) {
    const old = weekdaysSince(iso) > STALE_AFTER;
    return `As of ${niceDate(iso) || iso}${old ? " · stale" : ""} · ${source}`;
  }
  function renderMacro(m) {
    const L = m.latest, body = $("#macro-body");
    $("#macro-asof").textContent = asOfLine(L.as_of, `FRED, daily since ${String(m.start).slice(0, 4)}`);
    body.replaceChildren();
    if (m.schema > SCHEMA_MAX) body.append(h("p", "hint", "This data was written by a newer engine than this page expects; reassemble the page."));
    const tiles = h("div", "tiles compact");
    const note1 = h("span", "note");
    note1.append(regimeNode(L.regime), document.createTextNode(` since ${niceDate(L.regime_since)}`));
    tiles.append(
      tile("Correlation, 63-day half-life", sgn2(L.corr63), note1),
      tile("One-year correlation", sgn2(L.corr252), "Below zero means long bonds rose when the Nasdaq fell."),
      tile("Long-bond hedge ratio", Math.round(L.hedge_ratio_gated * 100) + "%", `What the regime rule holds per $1 of Nasdaq-100, in 20-year bond notional. Min-variance alone: ${Math.round(L.hedge_ratio_minvar * 100)}%.`),
      tile("30-year minus 3-month", (L.curve_30y_3m > 0 ? "+" : "") + num(L.curve_30y_3m, 2, " pts"), `30y ${num(L.DGS30, 2, "%")} · 10y breakeven ${num(L.T10YIE, 2, "%")} · VIX ${num(L.VIXCLS, 1)}`)
    );
    const two = h("div", "grid2");
    two.append(figureBlock("Correlation of daily returns, by year", [["var(--s1)", "Bonds hedged"], ["var(--red)", "Bonds amplified"]], "yearly-chart"),
      figureBlock("Correlation with a 63-day half-life, weekly", null, "corr-chart"));
    const era = (m.shock_by_era || []).map((r) => [r.group, String(r.days), pct(r.avg_equity, 2), pct(r.avg_bond, 2), Math.round(r.bond_up_share * 100) + "%"]);
    const eraFig = h("figure", "chart");
    eraFig.append(h("span", "chart-title", "Nasdaq-100's worst 5% of days: what the long bond did"), tableBlock(["Era", "Days", "Nasdaq-100, avg", "Long bond, avg", "Bond rose"], era));
    const pol = (m.policies_since_2022 || []).filter((r) => r.index !== "none").map((r) => [POLICY[r.index] || r.index, pct(r.variance_reduction, 1), pct(r.worst_days_saved, 2), pct(r.ann_return_drag, 1)]);
    const polFig = h("figure", "chart");
    polFig.append(h("span", "chart-title", "Hedge policies since 2022, judged out of sample"), tableBlock(["Policy", "Variance cut", "Worst-day saving", "Return per year"], pol));
    const two2 = h("div", "grid2");
    two2.append(eraFig, polFig);
    body.append(tiles, two, two2, h("p", "hint", m.source + ". Correlations use simple daily returns; hedge ratios are long-only and applied the next day."));
    const gl = $("#gauge-live");
    gl.hidden = false;
    gl.className = "sentence" + (L.regime === "hedging" ? " ok" : L.regime === "amplifying" ? " warn" : "");
    gl.textContent = `Engine, ${niceDate(L.as_of)}: Nasdaq-100 against the 20-year Treasury, correlation ${sgn2(L.corr63)} (63-day half-life) and ${sgn2(L.corr252)} over one year. Regime: ${L.regime}${L.regime === "hedging" ? ", so the rule holds the bond hedge." : ", so the rule holds no bond hedge."}`;
    drawMacroCharts();
  }
  function drawMacroCharts() {
    const m = LIVE.macro;
    if (!m) return;
    yearlyChart($("#yearly-chart"), m.yearly || []);
    const box = $("#corr-chart");
    if (box && box.clientWidth) {
      const pts = seriesPts(m.corr63);
      xyChart(box, { series: [{ name: "Correlation", color: "var(--s1)", pts, endLabel: sgn2(pts[pts.length - 1][1]) }], zero: true, yfmt: (v) => sgn2(v),
        xticks: yearTicks(pts[0][0], pts[pts.length - 1][0]), xfmt: dateLabel, label: "Correlation of Nasdaq-100 and long Treasury returns, 63-day half-life", height: 230 });
    }
  }
  const BOOK_SPEC = { "summary.as_of": "str", "summary.recommended_gross": "num", "summary.hedge_ratio_now": "num",
    "summary.var99_fhs": "num", "backtest.curves": "str", "backtest.stats": "str", exposures: "arr", "hedge.policies": "arr" };
  function renderBook(r) {
    const S = r.summary, body = $("#book-body");
    $("#book-asof").textContent = asOfLine(S.as_of, "Databento");
    body.replaceChildren();
    const tiles = h("div", "tiles compact");
    tiles.append(
      tile("Book vs TLT regime", regimeNode(S.regime_now), `Correlation ${sgn2(S.stock_bond_corr_now)}, 63-day half-life.`),
      tile("TLT hedge now", Math.round(S.hedge_ratio_now * 100) + "% of book", "Regime-gated minimum-variance ratio."),
      tile("Size to run", xx(S.recommended_gross), `Vol target ${xx(S.vol_target_scale)} · drawdown cap ${xx(S.drawdown_leverage_cap)}`),
      tile("1-day VaR, 99%", pctPlain(S.var99_fhs, 1), `Filtered historical simulation; expected shortfall ${pctPlain(S.cvar99_fhs, 1)}.`)
    );
    const labels = Object.keys(r.backtest.curves), colors = ["var(--s1)", "var(--s2)", "var(--s3)", "var(--s4)"];
    const fig = figureBlock("Growth of $1 under four hedge and sizing policies", labels.map((l, i) => [colors[i], l, true]), "bt-chart");
    const stats = labels.map((l) => { const s = r.backtest.stats[l]; return [l, pct(s.cagr, 1), pctPlain(s.vol, 1), fx(s.sharpe, 2), pctPlain(Math.abs(s.max_drawdown), 1), s.dsr.toFixed(2)]; });
    const statFig = h("figure", "chart");
    statFig.append(tableBlock(["Policy", "CAGR", "Volatility", "Sharpe", "Max drawdown", "Deflated Sharpe"], stats),
      h("p", "hint", "Deflated Sharpe is the probability the true Sharpe beats what the best of every variant, policy and hedge tried would show by luck. Above 0.95 is the bar."));
    const exp = (r.exposures || []).map((e) => [e.index, fx(e.market, 2), fx(e.ai, 2), fx(e.rates, 2), String(Math.round(e.n_obs))]);
    const expFig = h("figure", "chart");
    expFig.append(h("span", "chart-title", "Factor betas (market = QQQ, AI = basket minus QQQ, rates = TLT)"), tableBlock(["Ticker", "Market", "AI", "Rates", "Days of history"], exp));
    const pol = (r.hedge.policies || []).filter((p) => p.index !== "none").map((p) => [POLICY[p.index] || p.index, pct(p.variance_reduction, 1), pct(p.worst_days_saved, 2), pct(p.ann_return_drag, 1)]);
    const polFig = h("figure", "chart");
    polFig.append(h("span", "chart-title", "TLT hedge policies on the book"), tableBlock(["Policy", "Variance cut", "Worst-day saving", "Return per year"], pol));
    const two = h("div", "grid2");
    two.append(expFig, polFig);
    body.append(tiles, fig, statFig, two);
    const rb = robustnessFigure(r.robustness, r.data_quality);
    if (rb) body.append(rb);
    LIVE.btSeries = labels.map((l, i) => ({ name: l, color: colors[i], pts: seriesPts(r.backtest.curves[l]) }));
    drawBookCharts();
  }
  // v0.10: would the backtest survive another history, and is the hedge rule a peak or a plateau?
  function robustnessFigure(R, dq) {
    if (!R || typeof R !== "object" || !R.bootstrap || !R.bootstrap.variants || typeof R.bootstrap.variants !== "object") return null;
    const fig = h("figure", "chart"), V = R.bootstrap.variants;
    fig.append(h("span", "chart-title", `How robust is the backtest? ${fin(R.bootstrap.draws) ? R.bootstrap.draws : "n/a"} resampled histories (blocks of about ${fin(R.bootstrap.mean_block_days) ? Math.round(R.bootstrap.mean_block_days) : "n/a"} days)`));
    const q = (a, f) => (Array.isArray(a) && a.length === 3 && a.every(fin) ? `${f(a[0])} to ${f(a[2])}` : "n/a");
    fig.append(tableBlock(["Policy", "Sharpe, 90% range", "CAGR, 90% range", "Max drawdown, 90% range", "Beats unhedged"],
      Object.entries(V).filter(([, v]) => v && typeof v === "object").map(([k, v]) => [k, q(v.sharpe, (x) => fx(x, 2)), q(v.cagr, (x) => pct(x, 1)), q(Array.isArray(v.max_drawdown) ? v.max_drawdown.slice().reverse() : v.max_drawdown, (x) => pctPlain(Math.abs(x), 1)), fin(v.p_beats_base) ? pct0(v.p_beats_base) : ""])));
    const P = R.pbo || {}, L = R.plateau || {};
    const lines = [];
    if (fin(P.pbo)) lines.push(`Probability of backtest overfitting across ${P.rules} neighbouring hedge rules and ${P.splits} splits of the history: ${pct0(P.pbo)}. ${P.pbo >= 0.4 ? "Picking the best backtested rule is close to picking at random: the rule should be justified by economics, not by its backtest." : P.pbo <= 0.15 ? "The best rule in one half of history tends to stay good in the other." : "Selection explains part of the best rule's edge."}`);
    if (fin(L.chosen_sharpe) && fin(L.rank)) lines.push(`The chosen rule (enter at −0.10, leave at 0) ranks ${L.rank} of ${L.of} on Sharpe (${fx(L.chosen_sharpe, 2)}; neighbours ${fx(L.neighbour_min, 2)} to ${fx(L.neighbour_max, 2)}). ${fin(L.spread) && L.spread < 0.15 ? "A plateau: nearby rules perform about the same." : "Performance varies across nearby rules: treat the exact thresholds as fragile."}`);
    if (dq && fin(dq.flagged)) lines.push(dq.flagged ? `The price screen flagged ${dq.flagged} symbol${dq.flagged > 1 ? "s" : ""} (bad prints, frozen prices or gaps); see the run status.` : "The price screen found no bad prints, frozen prices or gaps.");
    lines.forEach((t) => fig.append(h("p", "hint", t)));
    return fig;
  }
  function drawBookCharts() {
    const box = $("#bt-chart");
    if (!LIVE.btSeries || !box || !box.clientWidth) return;
    const pts = LIVE.btSeries[0].pts;
    xyChart(box, { series: LIVE.btSeries, yfmt: (v) => "$" + v.toFixed(2), xticks: yearTicks(pts[0][0], pts[pts.length - 1][0]), xfmt: dateLabel, label: "Growth of one dollar under four policies", height: 260 });
  }

  /* =====================================================================================
     RATES
     ===================================================================================== */
  const QCOL = ["var(--q1)", "var(--q2)", "var(--q3)", "var(--q4)", "var(--q5)"];
  function renderCurve() {
    const box = $("#curve-chart");
    if (!box || !box.clientWidth) return;
    const series = CURVES.dates.map((d, i) => ({ name: d.label, color: QCOL[i], width: i === CURVES.dates.length - 1 ? 2.75 : 1.5,
      dots: i === CURVES.dates.length - 1, pts: d.y.map((y, j) => [j, y]) }));
    xyChart(box, { series, xticks: CURVES.tenors.map((t, j) => [j, t]), xfmt: (j) => CURVES.tenors[j], yfmt: (v) => fx(v, 2) + "%",
      label: "Treasury par yield curve on seven dates in 2026", height: 280, yTicks: 5, snapXs: CURVES.tenors.map((_, j) => j) });
  }
  function buildRatesStatic() {
    legendLines($("#curve-legend"), CURVES.dates.map((d, i) => [QCOL[i], d.label]));
    const first = CURVES.dates[0].y, last = CURVES.dates[CURVES.dates.length - 1].y;
    fillTable($("#curve-table"), ["Tenor", ...CURVES.dates.map((d) => d.label), "Change since Jan 2"],
      CURVES.tenors.map((t, j) => [t, ...CURVES.dates.map((d) => d.y[j].toFixed(2) + "%"), bp(Math.round((last[j] - first[j]) * 100))]));
    const ix = (t) => CURVES.tenors.indexOf(t);
    const spreads = [["2s10s", "10Y", "2Y"], ["3m10y", "10Y", "3M"], ["10s30s", "30Y", "10Y"], ["20s30s", "30Y", "20Y"]];
    const st = $("#spread-tiles");
    st.replaceChildren();
    spreads.forEach(([name, a, b]) => {
      const now = Math.round((last[ix(a)] - last[ix(b)]) * 100), then = Math.round((first[ix(a)] - first[ix(b)]) * 100);
      st.append(tile(name, bp(now), `Jan 2: ${bp(then)} · change ${bp(now - then)}`));
    });
    // nominal = real (TIPS) + breakeven, on two sourced dates, drawn to one scale
    const d = $("#decomp"), DEC = [["Sep 17, TIPS auction", 2.653, 2.30, 4.95], ["Oct 7", 2.91, 2.36, 5.27]], scale = 5.5;
    d.replaceChildren();
    DEC.forEach(([when, real, be, nom]) => {
      const row = h("div", "decomp-row"), bar = h("div", "decomp-bar");
      const a = h("span", null, `Real ${real.toFixed(2)}%`), b = h("span", null, `Inflation ${be.toFixed(2)}%`);
      a.style.width = (real / scale * 100) + "%"; a.style.background = "var(--decomp-real)";
      b.style.width = (be / scale * 100) + "%"; b.style.background = "var(--decomp-infl)";
      bar.append(a, b);
      const head = h("div", "decomp-head");
      head.append(h("span", null, when), h("strong", null, `10-year ${nom.toFixed(2)}%`));
      row.append(head, bar);
      d.append(row);
    });
    d.append(h("p", "hint", "In three weeks the 10-year rose 32bp: 26bp from the real yield and 6bp from inflation expectations. The breakeven was 2.46% on Apr 29."));
    // duration menu at the latest shipped curve
    const rows = [
      ["3-month bill", "SGOV, BIL", 0.25, last[ix("3M")], "Safe leg; collateral"],
      ["2-year note", "SHY, ZT", 2, last[ix("2Y")], "Fed-path exposure"],
      ["5-year note", "IEI, ZF", 5, last[ix("5Y")], "Belly of the curve"],
      ["10-year note", "IEF, ZN, TN", 10, last[ix("10Y")], "Benchmark duration"],
      ["30-year par bond", "ZB, UB; TLT holds 20 to 30 years (duration 14.85)", 30, last[ix("30Y")], "Growth-scare hedge"],
    ];
    const out = rows.map(([n, tick, mat, y, role]) => {
      // a bill has one cash flow: duration is maturity over (1 + y·t); coupon bonds are repriced on the grid
      const dur = mat < 0.5 ? mat / (1 + (y / 100) * mat) : durCvx(y / 100, mat, y / 100).dur;
      return [n, tick, y.toFixed(2) + "%", dur.toFixed(2), money(dur * 100000 * 1e-4, 2), role];
    });
    out.push(["Long zero-coupon", "ZROZ, EDV", "near the 30-year", "about 25", "about $250", "Most duration per dollar"]);
    out.push(["10-year TIPS", "Direct; TIP and SCHP run shorter", "2.66% real (Oct 23)", "about 9", "about $90", "Real-return anchor"]);
    fillTable($("#duration-table"), ["Instrument", "Access", "Yield", "Duration", "DV01 per $100k", "Role"], out, 2);
    $("#duration-table").querySelectorAll("tr").forEach((tr) => { tr.lastChild.className = ""; });
  }
  function buildRatesLive(m) {
    const r = m.rates;
    if (!r || !r.curves || !r.curves.latest) return;
    const wrap = $("#rates-live");
    wrap.replaceChildren();
    const tiles = h("div", "tiles compact"), L = r.levels || {}, S0 = r.spreads_bp || {}, HIST = r.history || {};
    const lastOf = (o) => (o && o.values && o.values.length ? o.values[o.values.length - 1] : null);
    ["2s10s", "3m10y"].forEach((k) => {
      const v = lastOf(S0[k]), y = yearAgo(S0[k]);
      if (v != null) tiles.append(tile(k, bp(Math.round(v)), y != null ? `${bp(Math.round(v - y))} over the past year.` : "From the FRED curve."));
    });
    [["real10", "10-year real yield"], ["breakeven10", "10-year breakeven"], ["term_premium10", "10-year term premium"], ["hy_oas", "High-yield spread"]].forEach(([k, label]) => {
      if (!L[k]) return;
      const y = yearAgo(HIST[k]);
      tiles.append(tile(label, fx(L[k].value, 2) + "%", y != null ? `${bp(Math.round((L[k].value - y) * 100))} over the past year.` : niceDate(L[k].date)));
    });
    const s2 = S0["2s10s"], since = s2 && s2.dates && s2.dates.length ? s2.dates[0].slice(0, 4) : "";
    const grid = h("div", "grid2");
    grid.append(figureBlock(`FRED curve on ${niceDate(r.curves.latest.date)} vs a year earlier`, [["var(--q2)", r.curves.year_ago ? niceDate(r.curves.year_ago.date) : "", true], ["var(--q5)", niceDate(r.curves.latest.date), true]], "rl-curve"),
      figureBlock(`2s10s and 3m10y since ${since}, bp`, [["var(--s1)", "2s10s", true], ["var(--s2)", "3m10y", true]], "rl-spreads"));
    const grid2 = h("div", "grid2");
    grid2.append(figureBlock("10-year real yield and breakeven, %", [["var(--s1)", "Real (TIPS)", true], ["var(--s2)", "Breakeven", true]], "rl-real"),
      figureBlock("Credit spreads, %", [["var(--s1)", "High yield", true], ["var(--s2)", "Investment grade", true]], "rl-credit"));
    const p1 = h("div", "panel"), p2 = h("div", "panel");
    p1.append(grid); p2.append(grid2);
    wrap.append(tiles, p1, p2, h("p", "hint", "Source: FRED series DGS1MO to DGS30, DFII10, T10YIE, THREEFYTP10, BAMLH0A0HYM2 and BAMLC0A0CM, pulled by the daily run."));
    wrap.style.display = "grid";
    wrap.style.gap = "16px";
    drawRatesLive();
  }
  function drawRatesLive() {
    const m = LIVE.macro;
    if (!m || !m.rates || !m.rates.curves) return;
    const r = m.rates;
    const cb = $("#rl-curve");
    if (cb && cb.clientWidth && r.curves.latest) {
      const tenors = r.curves.latest.points.map((p) => p.tenor);
      const mk = (c) => c ? c.points.map((p) => [tenors.indexOf(p.tenor), p.yield]).filter((p) => p[0] >= 0) : [];
      xyChart(cb, { series: [{ name: r.curves.year_ago ? niceDate(r.curves.year_ago.date) : "Year ago", color: "var(--q2)", width: 1.5, pts: mk(r.curves.year_ago) },
        { name: niceDate(r.curves.latest.date), color: "var(--q5)", width: 2.5, dots: true, pts: mk(r.curves.latest) }],
        xticks: tenors.map((t, j) => [j, t]), xfmt: (j) => tenors[j], yfmt: (v) => fx(v, 2) + "%", snapXs: tenors.map((_, j) => j), label: "FRED Treasury curve, now vs a year ago", height: 240 });
    }
    const draw = (id, defs, fmt, zero, label) => {
      const box = $(id);
      const ser = defs.filter(([o]) => o && o.dates && o.dates.length);
      if (!box || !box.clientWidth || !ser.length) return;
      const series = ser.map(([o, name, color]) => ({ name, color, pts: seriesPts(o) }));
      const p0 = series[0].pts;
      xyChart(box, { series, zero, yfmt: fmt, xticks: yearTicks(p0[0][0], p0[p0.length - 1][0]), xfmt: dateLabel, height: 230, label });
    };
    const H = r.history || {}, S = r.spreads_bp || {};
    draw("#rl-spreads", [[S["2s10s"], "2s10s", "var(--s1)"], [S["3m10y"], "3m10y", "var(--s2)"]], (v) => (v < 0 ? MINUS : "") + Math.abs(Math.round(v)), true, "2s10s and 3m10y Treasury spreads in basis points");
    draw("#rl-real", [[H.real10, "Real (TIPS)", "var(--s1)"], [H.breakeven10, "Breakeven", "var(--s2)"]], (v) => fx(v, 2) + "%", true, "10-year real yield and breakeven inflation");
    draw("#rl-credit", [[H.hy_oas, "High yield", "var(--s1)"], [H.ig_oas, "Investment grade", "var(--s2)"]], (v) => fx(v, 2) + "%", true, "High-yield and investment-grade credit spreads");
  }

  /* ---------- bond calculator ---------- */
  function updateBond() {
    const cpn = readNum($("#bc-cpn"), 0, 30, 5.15) / 100, y = readNum($("#bc-yld"), -5, 30, 5.15) / 100;
    const mat = readNum($("#bc-mat"), 0.5, 50, 10), face = readNum($("#bc-face"), 1000, 1e10, 100000), shock = Number($("#bc-shock").value);
    $("#bc-shock-o").textContent = bp(shock);
    const dc = durCvx(y, mat, cpn), mac = dc.dur * (1 + y / 2);
    const dv01 = dc.price / 100 * face * dc.dur * 1e-4;
    const pShock = bondPrice(y + shock / 1e4, mat, cpn), chg = pShock / dc.price - 1;
    const approx = -dc.dur * shock / 1e4 + 0.5 * dc.cvx * Math.pow(shock / 1e4, 2);
    $("#bc-price").textContent = fx(dc.price, 3);
    $("#bc-dur").textContent = fx(dc.dur, 2) + " yrs";
    $("#bc-cvx").textContent = fx(dc.cvx, 1);
    $("#bc-dv01").textContent = money(dv01, 2);
    $("#bc-out").textContent = `A ${bp(shock)} move takes the price to ${fx(pShock, 3)}, a ${pct(chg, 2)} change, or ${signedMoney(chg * dc.price / 100 * face)} on this face. Duration plus convexity estimates ${pct(approx, 2)}. Macaulay duration is ${fx(mac, 2)} years.`;
  }

  /* ---------- curve trade ---------- */
  const CT_PRESETS = [["Bull steepener", -50, -20], ["Bear steepener", 10, 40], ["Bull flattener", -10, -40], ["Bear flattener", 50, 20], ["Parallel +50", 50, 50]];
  function updateCurveTrade() {
    const dv = Number($("#ct-dv01").value), d2 = Number($("#ct-d2").value), d10 = Number($("#ct-d10").value);
    const last = CURVES.dates[CURVES.dates.length - 1].y, y2 = last[4] / 100, y10 = last[8] / 100;
    $("#ct-dv01-o").textContent = money(dv) + "/bp";
    $("#ct-d2-o").textContent = bp(d2);
    $("#ct-d10-o").textContent = bp(d10);
    const D2 = durCvx(y2, 2, y2).dur, D10 = durCvx(y10, 10, y10).dur;
    const n2 = dv / (D2 * 1e-4), n10 = dv / (D10 * 1e-4);
    const pnl2 = n2 * (bondPrice(y2 + d2 / 1e4, 2, y2) / 100 - 1), pnl10 = -n10 * (bondPrice(y10 + d10 / 1e4, 10, y10) / 100 - 1);
    const pnl = pnl2 + pnl10, ds = d10 - d2;
    $("#ct-n2").textContent = money(n2);
    $("#ct-n10").textContent = money(n10);
    $("#ct-ds").textContent = bp(ds);
    $("#ct-pnl").textContent = signedMoney(pnl);
    const out = $("#ct-out");
    out.className = "sentence " + (pnl >= 0 ? "ok" : "warn");
    out.textContent = `The 2-year leg makes ${signedMoney(pnl2)} and the 10-year leg ${signedMoney(pnl10)}. A steepener earns about the risk times the spread change (${money(dv)} × ${bp(ds)} ≈ ${signedMoney(dv * ds)}); convexity explains the rest. Starting curve: 2-year ${last[4].toFixed(2)}%, 10-year ${last[8].toFixed(2)}% (${CURVES.dates[CURVES.dates.length - 1].label}).`;
    $("#ct-presets").querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", Number(b.dataset.d2) === d2 && Number(b.dataset.d10) === d10 ? "true" : "false"));
  }
  function buildCurveTrade() {
    const wrap = $("#ct-presets");
    CT_PRESETS.forEach(([name, d2, d10]) => {
      const b = h("button", null, name);
      b.type = "button"; b.dataset.d2 = d2; b.dataset.d10 = d10;
      b.addEventListener("click", () => { $("#ct-d2").value = d2; $("#ct-d10").value = d10; updateCurveTrade(); });
      wrap.append(b);
    });
  }

  /* =====================================================================================
     OPTIONS
     ===================================================================================== */
  let bsType = "put";
  function updateBS() {
    const S = readNum($("#bs-S"), 0.01, 1e7, 100), K = readNum($("#bs-K"), 0.01, 1e7, 90), days = Number($("#bs-T").value);
    const v = Number($("#bs-v").value) / 100, r = readNum($("#bs-r"), -5, 30, 4.25) / 100, q = readNum($("#bs-q"), 0, 30, 0.6) / 100;
    $("#bs-T-o").textContent = days + " days";
    $("#bs-v-o").textContent = fx(v * 100, 1) + "%";
    const o = bs(S, K, days / 365, r, q, v, bsType);
    const mk = $("#bs-mkt"), ivBox = $("#bs-iv"), raw = mk.value.trim();
    if (raw === "") { ivBox.hidden = true; mk.setAttribute("aria-invalid", "false"); }
    else {
      const px = Number(raw), iv = fin(px) ? impliedVol(px, S, K, days / 365, r, q, bsType) : NaN;
      ivBox.hidden = false;
      mk.setAttribute("aria-invalid", fin(iv) ? "false" : "true");
      ivBox.className = "sentence " + (fin(iv) ? "ok" : "warn");
      ivBox.textContent = fin(iv)
        ? `A ${fx(px, 2)} price implies ${fx(iv * 100, 1)}% volatility, ${iv >= v ? "above" : "below"} the ${fx(v * 100, 1)}% input by ${fx(Math.abs(iv - v) * 100, 1)} points.`
        : `No volatility produces a ${fx(px, 2)} price: it sits below the option's discounted intrinsic value or above its no-arbitrage ceiling.`;
    }
    $("#bs-px").textContent = fx(o.price, 2);
    $("#bs-pct").textContent = pctPlain(o.price / S, 2);
    $("#bs-delta").textContent = fx(o.delta, 3);
    $("#bs-pitm").textContent = pctPlain(o.pitm, 1);
    $("#bs-gamma").textContent = fx(o.gamma, 4);
    $("#bs-vega").textContent = fx(o.vega, 3);
    $("#bs-theta").textContent = fx(o.theta, 3);
    const be = bsType === "put" ? K - o.price : K + o.price;
    $("#bs-be").textContent = fx(be, 2);
    const move = be / S - 1;
    $("#bs-out").textContent = bsType === "put"
      ? `This put costs ${pctPlain(o.price / S, 2)} of spot for ${days} days. It pays off at expiry only below ${fx(be, 2)}, a ${pct(move, 1)} move. Annualized, rolling it would cost about ${pctPlain(o.price / S * 365 / days, 1)} a year at this volatility.`
      : `This call costs ${pctPlain(o.price / S, 2)} of spot for ${days} days and pays off above ${fx(be, 2)}, a ${pct(move, 1)} move. Ten percent of a portfolio in calls like this is the convex side of a barbell.`;
  }

  const STRATS = [
    { k: "put", n: "Protective put", d: "Own the book and one 90%-strike put per unit. Floor below a 10% drop, full upside minus the premium.", book: 1, legs: [["put", 0.90, 1]] },
    { k: "spread", n: "Put spread", d: "Long a 95% put, short an 80% put. Cheaper insurance that pays between a 5% and a 20% drop.", book: 1, legs: [["put", 0.95, 1], ["put", 0.80, -1]] },
    { k: "collar", n: "Collar", d: "Long a 90% put, short a 110% call. Near-zero cost; protection below 90%, gains capped above 110%.", book: 1, legs: [["put", 0.90, 1], ["call", 1.10, -1]] },
    { k: "covered", n: "Covered call", d: "Short a 105% call against the book. Income in flat markets, no crash protection.", book: 1, legs: [["call", 1.05, -1]] },
    { k: "barbell", n: "Barbell", d: "Taleb's shape: 90% of NAV in T-bills, 10% in 105%-strike calls. The most that can be lost by expiry is the premium less the bill interest; the upside stays open.", book: 0, legs: [["call", 1.05, "budget10"]] },
  ];
  let stratKey = "put";
  function updatePayoff() {
    const v = Number($("#po-v").value) / 100, days = Number($("#po-T").value), T = days / 365, r = 0.0427, q = 0.006;
    $("#po-v-o").textContent = (v * 100).toFixed(1) + "%";
    $("#po-T-o").textContent = days + " days";
    const st = STRATS.find((s) => s.k === stratKey);
    $("#po-desc").textContent = st.d;
    $("#po-strat").querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", b.dataset.k === stratKey ? "true" : "false"));
    const legs = st.legs.map(([type, k, qty]) => {
      const prem = bs(100, 100 * k, T, r, q, v, type).price;
      const n = qty === "budget10" ? 10 / prem : qty;
      return { type, K: 100 * k, prem, n };
    });
    const cost = legs.reduce((a, L) => a + L.n * L.prem, 0) / 100;
    const bill = st.book === 0 ? 0.9 * (Math.exp(r * T) - 1) : 0;
    const pay = (m) => {
      const S = 100 * (1 + m);
      const opt = legs.reduce((a, L) => a + L.n * ((L.type === "put" ? Math.max(L.K - S, 0) : Math.max(S - L.K, 0)) - L.prem), 0) / 100;
      return st.book * m + opt + bill;
    };
    const moves = [];
    for (let m = -0.5; m <= 0.5001; m += 0.01) moves.push(Number(m.toFixed(2)));
    $("#po-cost").textContent = pctPlain(Math.abs(cost), 2) + (cost < 0 ? " credit" : "");
    $("#po-m20").textContent = pct(pay(-0.2), 1);
    $("#po-m35").textContent = pct(pay(-0.35), 1);
    $("#po-p20").textContent = pct(pay(0.2), 1);
    const box = $("#po-chart");
    if (box && box.clientWidth) {
      xyChart(box, { series: [{ name: "Book alone", color: "var(--muted)", pts: moves.map((m) => [m, m]) }, { name: "Book with hedge", color: "var(--s2)", width: 2.5, pts: moves.map((m) => [m, pay(m)]) }],
        zero: true, yfmt: (y) => pct(y, 0), xfmt: (x) => "underlying " + pct(x, 0), xticks: [-0.5, -0.25, 0, 0.25, 0.5].map((x) => [x, pct(x, 0).replace("+0%", "0%")]),
        vmarks: [{ x: 0, label: "Today" }], label: "Payoff at expiry", height: 260 });
    }
    const rows = legs.map((L) => [`${L.n > 0 ? "Long" : "Short"} ${Math.abs(L.n).toFixed(st.book === 0 ? 2 : 0)} × ${L.type} @ ${L.K.toFixed(0)}`, L.prem.toFixed(2), pctPlain(Math.abs(L.n * L.prem) / 100, 2)]);
    if (st.book === 0) rows.unshift(["90% of NAV in T-bills at 4.25%", "", pct(bill, 2)]);
    const t = $("#po-table");
    fillTable(t, ["Leg", "Premium per 100", "Share of NAV"], rows);
    const tb = h("tbody"), hr = h("tr");
    hr.append(h("th", null, "Underlying at expiry"), h("th", "r", "Book alone"), h("th", "r", "With hedge"));
    tb.append(hr);
    [-0.35, -0.2, -0.1, 0, 0.1, 0.2, 0.35].forEach((m) => { const tr = h("tr"); tr.append(h("td", null, pct(m, 0)), h("td", "r", pct(m, 1)), h("td", "r", pct(pay(m), 1))); tb.append(tr); });
    t.append(tb);
    updateGrid(st, legs, v, T, r, q);
  }
  // instant revaluation of the payoff builder's position across spot and volatility shocks
  function updateGrid(st, legs, v, T, r, q) {
    const table = $("#sv-grid"), spots = [-0.3, -0.2, -0.1, -0.05, 0, 0.05, 0.1, 0.2], vols = [-10, -5, 0, 5, 10, 20];
    const value = (S, vol) => legs.reduce((a, L) => a + L.n * bs(S, L.K, T, r, q, vol, L.type).price, 0);
    const base = value(100, v);
    const cells = spots.map((m) => vols.map((dv) => st.book * m + (value(100 * (1 + m), Math.max(0.01, v + dv / 100)) - base) / 100));
    const maxAbs = Math.max(1e-9, ...cells.flat().map(Math.abs));
    table.replaceChildren();
    const thead = h("thead"), hr = h("tr");
    hr.append(h("th", null, "Underlying"));
    vols.forEach((dv) => hr.append(h("th", null, dv === 0 ? "Vol unchanged" : `Vol ${dv > 0 ? "+" : MINUS}${Math.abs(dv)} pts`)));
    thead.append(hr);
    const tb = h("tbody");
    spots.forEach((m, i) => {
      const tr = h("tr");
      tr.append(h("th", null, pct(m, 0)));
      vols.forEach((dv, j) => {
        const x = cells[i][j], td = h("td", m === 0 && dv === 0 ? "zero" : null, pct(x, 1)), w = Math.round(Math.min(1, Math.abs(x) / maxAbs) * 100);
        td.style.background = `color-mix(in srgb, ${x >= 0 ? "var(--grid-pos)" : "var(--grid-neg)"} ${w}%, transparent)`;
        tr.append(td);
      });
      tb.append(tr);
    });
    table.append(thead, tb);
    const S0 = STRATS.find((x) => x.k === stratKey);
    $("#grid-cap").textContent = `Instant P&L, % of NAV: ${S0.n.toLowerCase()} at ${fx(v * 100, 1)}% volatility, ${Math.round(T * 365)} days`;
  }
  function buildPayoff() {
    const wrap = $("#po-strat");
    STRATS.forEach((s) => {
      const b = h("button", null, s.n);
      b.type = "button"; b.dataset.k = s.k;
      b.addEventListener("click", () => { stratKey = s.k; updatePayoff(); });
      wrap.append(b);
    });
  }

  function updateTail() {
    const k = Number($("#tb-k").value) / 100, days = Number($("#tb-T").value), v = Number($("#tb-v").value) / 100, n = Number($("#tb-n").value) / 100;
    $("#tb-k-o").textContent = Math.round(k * 100) + "%";
    $("#tb-T-o").textContent = days + " days";
    $("#tb-v-o").textContent = (v * 100).toFixed(1) + "%";
    $("#tb-n-o").textContent = Math.round(n * 100) + "%";
    const prem = bs(100, 100 * k, days / 365, 0.0427, 0.006, v, "put").price / 100;
    const rolls = 365 / days, yearly = prem * rolls * n;
    const crashes = [-0.1, -0.2, -0.3, -0.35, -0.4];
    const payoff = (c) => n * Math.max(k - (1 + c), 0);
    $("#tb-roll").textContent = pctPlain(prem * n, 2);
    $("#tb-rolls").textContent = rolls.toFixed(1);
    $("#tb-year").textContent = pctPlain(yearly, 2);
    $("#tb-pay").textContent = pctPlain(payoff(-0.35), 1);
    const rows = crashes.map((c) => ({ c, un: c, he: c + payoff(c) - yearly }));
    const mild = rows[0], big = rows.find((r) => r.c === -0.35);
    const mult = (x) => (yearly > 1e-6 ? `${fx(x / yearly, 1)}x` : "n/a");
    const cap = POLICY7.limits.maxPremium, fitN = yearly > 1e-6 ? n * cap / yearly : NaN;
    $("#tb-out").textContent = (yearly > 1e-6
      ? `A year of puts costs ${pctPlain(yearly, 2)} of NAV${yearly > cap + 1e-9 ? `, above the policy cap of ${pctPlain(cap, 0)} a year: at this strike and tenor the cap fits about ${Math.round(fitN * 100)}% of the book` : `, within the policy cap of ${pctPlain(cap, 0)} a year`}. One −35% quarter pays ${pctPlain(payoff(-0.35), 1)}, ${fx(payoff(-0.35) / yearly, 1)} times that, and leaves the book at ${pct(big.he, 1)} net instead of −35%. `
      : `At this strike and volatility the puts cost almost nothing, and pay ${pctPlain(payoff(-0.35), 1)} in a −35% quarter. `) +
      (payoff(mild.c) > 0 ? `Even a −${pctPlain(-mild.c, 0)} quarter pays ${pctPlain(payoff(mild.c), 1)}.` : `A −${pctPlain(-mild.c, 0)} quarter pays nothing, and the book ends at ${pct(mild.he, 1)} after a year of premium: the price of the tail.`);
    fillTable($("#tb-table"), ["Quarter's move", "Unhedged", "Hedged, net of a year's premium", "Payout ÷ yearly budget"],
      rows.map((r) => [pct(r.c, 0), pct(r.un, 1), pct(r.he, 1), mult(payoff(r.c))]));
    const box = $("#tb-chart");
    if (!box || !box.clientWidth) return;
    const W = boxWidth(box), Hh = 250, padL = 44, padR = 10, top = 22, bottom = 30;
    const vals = rows.flatMap((r) => [r.un, r.he]);
    const ticks = niceTicks(Math.min(0, ...vals) * 1.15, Math.max(0, ...vals) * 1.15, 4), y0 = ticks[0], y1 = ticks[ticks.length - 1];
    const sy = (y) => top + (1 - (y - y0) / (y1 - y0 || 1)) * (Hh - top - bottom);
    const band = (W - padL - padR) / rows.length, bw = Math.min(26, (band - 18) / 2), both = band >= 84;
    box.replaceChildren();
    const s = svg("svg", { viewBox: `0 0 ${W} ${Hh}`, width: W, height: Hh, role: "img", "aria-label": "Quarterly drawdown with and without the tail hedge" }, box);
    ticks.forEach((t) => {
      svg("line", { x1: padL, x2: W - padR, y1: sy(t), y2: sy(t), class: t === 0 ? "baseline" : "gridline" }, s);
      text(s, padL - 6, sy(t) + 4, pct(t, 0), "ax", "end");
    });
    rows.forEach((r, i) => {
      const cx = padL + band * (i + 0.5);
      text(s, cx, Hh - 9, (W >= 560 ? "Market " : "") + pct(r.c, 0), "ax", "middle");
      [["un", "var(--s1)", "Unhedged"], ["he", "var(--s2)", "Hedged"]].forEach(([key, color, label], j) => {
        const x = j ? cx + 5 : cx - 5 - bw, val = r[key], neg = val < 0;
        svg("path", { d: vbar(x, bw, sy(0), sy(val)), fill: color }, s);
        if (j || both) text(s, x + bw / 2, neg ? sy(val) + 13 : sy(val) - 5, pct(val, 0), j ? "lbl-strong" : "lbl", "middle");
        const hit = svg("rect", { x: x - 2, y: Math.min(sy(0), sy(val)) - 2, width: bw + 4, height: Math.max(6, Math.abs(sy(val) - sy(0)) + 4), class: "hit", tabindex: "0", "aria-label": `${label} when the market moves ${pct(r.c, 0)}: ${pct(val, 1)}` }, s);
        bindTip(hit, () => [[pct(val, 1), `${label} · market ${pct(r.c, 0)} in a quarter`]]);
      });
    });
  }

  /* =====================================================================================
     HEDGES: matrix, hedge lab, sizing lab
     ===================================================================================== */
  const GLYPH = { 2: ["Strong", "g2", "Strong"], 1: ["Partial", "g1", "Partial"], 0: ["None", "g0", "Little or none"], "-1": ["Hurts", "gx", "Tends to hurt"] };
  function buildMatrix() {
    const t = $("#matrix"), thead = h("thead"), hr = h("tr");
    hr.append(h("th", null, "Hedge"));
    SCEN_MX.forEach((sc) => { const th = h("th"); th.append(document.createTextNode(sc.name), h("span", null, sc.sub)); hr.append(th); });
    thead.append(hr);
    const tb = h("tbody");
    MATRIX.forEach((row) => {
      const tr = h("tr"), th = h("th");
      th.scope = "row";
      th.append(document.createTextNode(row.h), h("span", null, row.sub));
      tr.append(th);
      row.g.forEach((g, j) => {
        const [glyph, cls, word] = GLYPH[String(g)];
        const td = h("td"), b = h("button", "grade " + cls, glyph);
        b.type = "button";
        b.setAttribute("aria-pressed", "false");
        b.setAttribute("aria-label", `${row.h} in ${SCEN_MX[j].name}: ${word}`);
        b.addEventListener("click", () => {
          t.querySelectorAll(".grade[aria-pressed='true']").forEach((x) => x.setAttribute("aria-pressed", "false"));
          b.setAttribute("aria-pressed", "true");
          $("#matrix-detail").textContent = `${row.h}, ${SCEN_MX[j].name.toLowerCase()}: ${word.toLowerCase()}. ${row.note}`;
        });
        bindTip(b, () => [[`${word} in a ${SCEN_MX[j].name.toLowerCase()}`, `${row.h}: ${row.note}`]]);
        td.append(b);
        tr.append(td);
      });
      tb.append(tr);
    });
    t.replaceChildren(thead, tb);
    buildMatrixPhone();
  }
  // phones: one scenario at a time, hedges ranked best first, reasoning inline
  let mScen = 0;
  function buildMatrixPhone() {
    const box = $("#matrix-m");
    box.replaceChildren();
    const seg = h("div", "seg");
    seg.setAttribute("role", "group");
    seg.setAttribute("aria-label", "Scenario");
    SCEN_MX.forEach((sc, j) => {
      const b = h("button", null, sc.name);
      b.type = "button";
      b.setAttribute("aria-pressed", j === mScen ? "true" : "false");
      b.addEventListener("click", () => { mScen = j; buildMatrixPhone(); });
      seg.append(b);
    });
    const list = h("div");
    MATRIX.map((row, i) => ({ row, g: row.g[mScen], i })).sort((a, b) => b.g - a.g || a.i - b.i).forEach(({ row, g }) => {
      const [glyph, cls, word] = GLYPH[String(g)];
      const b = h("button", "mrow"), gl = h("span", "grade " + cls, glyph);
      b.type = "button";
      b.setAttribute("aria-expanded", "false");
      gl.setAttribute("aria-hidden", "true");
      b.append(gl, h("strong", null, row.h), h("small", null, `${word} · ${row.sub}`), h("span", "why", row.note));
      b.addEventListener("click", () => b.setAttribute("aria-expanded", b.getAttribute("aria-expanded") === "true" ? "false" : "true"));
      list.append(b);
    });
    box.append(seg, h("p", "hint", `${SCEN_MX[mScen].sub}. Best hedges first; tap a row for the reasoning.`), list);
  }

  const SCEN = [
    { key: "growth", name: "Growth scare", long: "AI capex digestion (growth scare)", m: -0.30, dy: -75 },
    { key: "financing", name: "Financing shock", long: "AI financing / term-premium shock", m: -0.20, dy: 75 },
    { key: "inflation", name: "Oil and inflation", long: "Oil-led inflation with hikes", m: -0.30, dy: 125 },
    { key: "meltup", name: "Melt-up, yields up", long: "AI melt-up with rising yields", m: 0.20, dy: 50 },
    { key: "soft", name: "Soft landing", long: "Soft landing and cuts", m: 0.10, dy: -50 },
  ];
  let currentScen = "growth";
  const HL = { move: $("#h-move"), dy: $("#h-dy"), ratio: $("#h-ratio"), gross: $("#h-gross"), y0: $("#h-y0"), dur: $("#h-dur") };
  function buildHedgeLab() {
    const segWrap = $("#scen-buttons");
    [...SCEN, { key: "custom", name: "Custom" }].forEach((s) => {
      const b = h("button", null, s.name);
      b.type = "button"; b.dataset.key = s.key;
      b.addEventListener("click", () => { if (s.key !== "custom") { HL.move.value = Math.round(s.m * 100); HL.dy.value = s.dy; } updateHedge(); });
      segWrap.append(b);
    });
    Object.values(HL).forEach((inp) => inp.addEventListener("input", updateHedge));
  }
  const hedgeState = () => ({ m: Number(HL.move.value) / 100, dy: Number(HL.dy.value), h: Number(HL.ratio.value) / 100, g: Number(HL.gross.value), y0: Number(HL.y0.value) / 100, D: Number(HL.dur.value) });
  function updateHedge() {
    const st = hedgeState();
    const match = SCEN.find((s) => Math.round(s.m * 100) === Math.round(st.m * 100) && s.dy === st.dy);
    currentScen = match ? match.key : "custom";
    $("#scen-buttons").querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", b.dataset.key === currentScen ? "true" : "false"));
    $("#h-move-o").textContent = pct(st.m, 0);
    $("#h-dy-o").textContent = bp(st.dy);
    $("#h-ratio-o").textContent = Math.round(st.h * 100) + "%";
    $("#h-gross-o").textContent = xx(st.g);
    $("#h-y0-o").textContent = (st.y0 * 100).toFixed(2) + "%";
    $("#h-dur-o").textContent = st.D.toFixed(1);
    const b = longBondReturn(st.y0, st.dy, st.D), book = st.g * st.m, hedge = st.g * st.h * b, net = book + hedge;
    $("#r-book").textContent = pct(book);
    $("#r-hedge").textContent = pct(hedge);
    $("#r-bond").textContent = pct(b);
    $("#r-net").textContent = pct(net);
    const off = $("#r-offset");
    off.className = "sentence";
    if (st.m < 0 && b > 0) {
      off.textContent = `Full offset would take TLT at ${Math.round(-st.m / b * 100)}% of the book. At ${Math.round(st.h * 100)}% the hedge recovers ${Math.round(st.h * b / -st.m * 100)}% of the loss.`;
      off.classList.add("ok");
    } else if (st.m < 0) {
      off.textContent = `TLT falls ${pctPlain(-b)} in this scenario, so the hedge adds ${pctPlain(-hedge)} of NAV to the loss.`;
      off.classList.add("warn");
    } else if (b < 0) off.textContent = `The book gains and TLT falls ${pctPlain(-b)}: the hedge costs ${pctPlain(-hedge)} of NAV.`;
    else off.textContent = "Book and TLT both gain in this scenario.";
    $("#lg-hedged").textContent = `With TLT hedge (${Math.round(st.h * 100)}%)`;
    renderScenarioChart(st);
  }
  function renderScenarioChart(st) {
    const box = $("#scen-chart");
    if (!box || !box.clientWidth) return;
    const W = boxWidth(box), narrow = W < 560;
    const rows = SCEN.map((s) => { const b = longBondReturn(st.y0, s.dy, st.D); return { s, b, un: st.g * s.m, he: st.g * (s.m + st.h * b) }; });
    const vals = rows.flatMap((r) => [r.un, r.he, 0]);
    const ticks = niceTicks(Math.min(...vals), Math.max(...vals), narrow ? 4 : 6);
    const labelW = narrow ? 0 : 168, padL = 54, padR = 54, top = 6, rowH = narrow ? 62 : 46, barH = 12, gap = 3;
    const Hh = top + rows.length * rowH + 26, x0 = labelW + padL, x1 = W - padR;
    const sx = (v) => x0 + ((v - ticks[0]) / (ticks[ticks.length - 1] - ticks[0])) * (x1 - x0);
    box.replaceChildren();
    const s = svg("svg", { viewBox: `0 0 ${W} ${Hh}`, width: W, height: Hh, role: "img", "aria-label": "Net P&L by scenario, unhedged and with the TLT hedge" }, box);
    ticks.forEach((t) => { svg("line", { x1: sx(t), x2: sx(t), y1: top, y2: Hh - 22, class: "gridline" }, s); text(s, sx(t), Hh - 6, pct(t, 0).replace("+0%", "0%"), "ax", "middle"); });
    rows.forEach((r, i) => {
      const yRow = top + i * rowH;
      if (r.s.key === currentScen) svg("rect", { x: 0, y: yRow, width: W, height: rowH - 4, rx: 6, class: "rowwash" }, s);
      const yb = narrow ? yRow + 22 : yRow + (rowH - 4 - (2 * barH + gap)) / 2;
      if (narrow) text(s, 6, yRow + 15, r.s.name, "cat", "start"); else text(s, 10, yb + barH + 2, r.s.name, "cat", "start");
      [["un", "var(--s1)", "Unhedged"], ["he", "var(--s2)", "With TLT hedge"]].forEach(([k, color, label], j) => {
        const v = r[k], y = yb + j * (barH + gap);
        svg("path", { d: hbar(sx(0), sx(v), y, barH), fill: color }, s);
        text(s, v >= 0 ? sx(v) + 6 : sx(v) - 6, y + barH - 2, pct(v, 1), j ? "lbl-strong" : "lbl", v >= 0 ? "start" : "end");
        const hit = svg("rect", { x: Math.min(sx(0), sx(v)) - 4, y: y - 2, width: Math.abs(sx(v) - sx(0)) + 8, height: barH + 4, class: "hit", tabindex: "0", "aria-label": `${r.s.long}, ${label}: ${pct(v)}` }, s);
        bindTip(hit, () => [[pct(v), `${label} · ${r.s.long}`], [pct(r.b), `TLT move, 30y ${bp(r.s.dy)}`]]);
      });
    });
    svg("line", { x1: sx(0), x2: sx(0), y1: top, y2: Hh - 22, class: "baseline" }, s);
    fillTable($("#scen-table"), ["Scenario", "AI book", "30y yield", "TLT", "Unhedged", "With hedge"], rows.map((r) => [r.s.long, pct(r.s.m, 0), bp(r.s.dy), pct(r.b), pct(r.un), pct(r.he)]));
  }

  // sizing lab: Monte Carlo drawdown with common random numbers
  const P = 2000, NS_STEPS = 252, Z = new Float64Array(P * NS_STEPS);
  (function fillNormals() {
    let a = 7 >>> 0;
    const rnd = () => { a = (a + 0x6D2B79F5) >>> 0; let t = a; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
    for (let i = 0; i < Z.length; i += 2) {
      const u = Math.max(rnd(), 1e-12), v = rnd(), rr = Math.sqrt(-2 * Math.log(u));
      Z[i] = rr * Math.cos(2 * Math.PI * v);
      if (i + 1 < Z.length) Z[i + 1] = rr * Math.sin(2 * Math.PI * v);
    }
  })();
  const ddBuf = new Float64Array(P);
  function ddQuantile(mu, sig, L, q, r, spread) {
    if (L <= 0) return 0;
    const annMu = L * mu + (1 - L) * r - Math.max(L - 1, 0) * spread, annSig = L * sig, dt = 1 / 252;
    const drift = (annMu - 0.5 * annSig * annSig) * dt, vol = annSig * Math.sqrt(dt);
    for (let p = 0; p < P; p++) {
      let x = 0, peak = 0, mdd = 0;
      const off = p * NS_STEPS;
      for (let k = 0; k < NS_STEPS; k++) { x += drift + vol * Z[off + k]; if (x > peak) peak = x; else if (peak - x > mdd) mdd = peak - x; }
      ddBuf[p] = 1 - Math.exp(-mdd);
    }
    const sorted = Array.from(ddBuf).sort((x, y) => x - y);
    return sorted[Math.min(P - 1, Math.round(q * (P - 1)))];
  }
  function ddCap(mu, sig, limit, q, r, spread, hi = 3) {
    if (ddQuantile(mu, sig, hi, q, r, spread) <= limit) return hi;
    let lo = 0;
    for (let i = 0; i < 26; i++) { const mid = (lo + hi) / 2; if (ddQuantile(mu, sig, mid, q, r, spread) <= limit) lo = mid; else hi = mid; }
    return lo;
  }
  const GROSS_LIMIT = 1.5;   // the engine's max_gross (config.py RiskParams)
  const SZ = { mu: $("#s-mu"), sig: $("#s-sig"), tv: $("#s-tv"), dd: $("#s-dd"), conf: $("#s-conf"), kf: $("#s-kf"), r: $("#s-r"), sp: $("#s-sp") };
  let sizeTimer = 0, lastCurve = null, sizeReady = false;
  const sizeState = () => ({ mu: Number(SZ.mu.value) / 100, sig: Number(SZ.sig.value) / 100, tv: Number(SZ.tv.value) / 100, dd: Number(SZ.dd.value) / 100, q: Number(SZ.conf.value), f: Number(SZ.kf.value), r: Number(SZ.r.value) / 100, sp: Number(SZ.sp.value) / 100 });
  function labelsSize(st) {
    $("#s-mu-o").textContent = pctPlain(st.mu, 1); $("#s-sig-o").textContent = pctPlain(st.sig, 1); $("#s-tv-o").textContent = pctPlain(st.tv, 1);
    $("#s-dd-o").textContent = pctPlain(st.dd, 0); $("#s-r-o").textContent = pctPlain(st.r, 2); $("#s-sp-o").textContent = pctPlain(st.sp, 2);
  }
  function updateSize() {
    const st = sizeState();
    labelsSize(st);
    const vt = st.tv / st.sig, kelly = Math.max(0, st.f * (st.mu - st.r) / (st.sig * st.sig));
    const cap = ddCap(st.mu, st.sig, st.dd, st.q, st.r, st.sp), run = Math.min(vt, cap, GROSS_LIMIT);
    const need = run * st.sig * st.sig / st.f, have = st.mu - st.r;
    $("#z-vt").textContent = xx(vt); $("#z-dd").textContent = cap >= 3 ? "3.00x+" : xx(cap); $("#z-k").textContent = xx(kelly); $("#z-run").textContent = xx(run);
    const fname = st.f === 1 ? "full" : st.f === 0.5 ? "half" : "quarter", e = $("#z-edge");
    e.className = "sentence " + (need > have ? "warn" : "ok");
    e.textContent = `Running ${xx(run)} at ${fname} Kelly assumes about ${pctPlain(need, 1)} a year over cash. Your inputs give ${pctPlain(Math.max(have, 0), 1)}. ` +
      (need > have ? `At this Kelly fraction the return assumption supports ${xx(kelly)}. Size above that rests on the risk limits alone.` : "The return assumption supports this size.") +
      (govNote("This lab's size", run) ? " " + govNote("This lab's size", run) : "");
    $("#dd-title").textContent = `One-year max drawdown at ${Math.round(st.q * 100)}% confidence, by gross exposure`;
    const xs = Array.from({ length: 21 }, (_, i) => i * 0.1), ys = xs.map((L) => ddQuantile(st.mu, st.sig, L, st.q, st.r, st.sp));
    lastCurve = { xs, ys, st, cap, run };
    sizeReady = true;
    renderDD();
    fillTable($("#dd-table"), ["Gross exposure", "Max drawdown"], xs.filter((_, i) => i % 2 === 0).map((L) => [xx(L), pctPlain(ys[Math.round(L * 10)], 1)]));
  }
  function renderDD() {
    const box = $("#dd-chart");
    if (!lastCurve || !box || !box.clientWidth) return;
    const { xs, ys, st, cap } = lastCurve;
    xyChart(box, { series: [{ name: "Max drawdown", color: "var(--s1)", area: true, pts: xs.map((L, i) => [L, ys[i]]) }],
      hlines: [{ y: st.dd, label: `Limit ${pctPlain(st.dd, 0)}`, color: "var(--bad)" }],
      vmarks: [...(cap <= 2 ? [{ x: cap, label: `Cap ${xx(cap)}` }] : []), ...(Math.abs(cap - GROSS_LIMIT) > 0.25 ? [{ x: GROSS_LIMIT, label: "Gross limit" }] : [])],
      yfmt: (v) => pctPlain(v, 0), xfmt: (x) => xx(x) + " gross", xticks: [0, 0.5, 1, 1.5, 2].map((x) => [x, x.toFixed(1) + "x"]), yDomain: [0, Math.max(...ys, st.dd) * 1.05], label: "Drawdown by gross exposure", height: 250 });
  }
  function scheduleSize() { clearTimeout(sizeTimer); labelsSize(sizeState()); sizeTimer = setTimeout(updateSize, 90); }
  Object.values(SZ).forEach((inp) => inp.addEventListener(inp.tagName === "SELECT" ? "change" : "input", scheduleSize));

  /* =====================================================================================
     SECURITIES, THESES, LENSES
     ===================================================================================== */
  let secFilter = "All";
  function buildSecurities() {
    const f = $("#sec-filters");
    f.append(h("span", "flabel", "Risk driver"));
    ["All", ...DRIVERS].forEach((d) => {
      const b = h("button", null, d);
      b.type = "button"; b.dataset.d = d;
      b.addEventListener("click", () => { secFilter = d; renderSecurities(); });
      f.append(b);
    });
    f.classList.add("seg");
    renderSecurities();
  }
  function renderSecurities() {
    $("#sec-filters").querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", b.dataset.d === secFilter ? "true" : "false"));
    const g = $("#sec-grid");
    g.replaceChildren();
    const list = SECS.filter((s) => secFilter === "All" || s.d.includes(secFilter));
    list.forEach((s) => {
      const c = h("article", "sec");
      c.id = "sec-" + slug(s.n);
      c.append(h("span", "fam", s.f), h("h3", null, s.n), h("p", null, s.w));
      const dr = h("div", "drivers");
      s.d.forEach((d) => dr.append(h("span", "drv", d)));
      const dl = h("dl");
      [["Now", s.now], ["Access", s.acc], ["Role", s.role]].forEach(([k, v]) => dl.append(h("dt", null, k), h("dd", null, v)));
      c.append(dr, dl);
      g.append(c);
    });
    renderDrivers();
    $("#sec-count").textContent = secFilter === "All" ? `${SECS.length} securities across rates, credit, structured, equity-linked, real assets, digital and currencies.` : `${list.length} of ${SECS.length} carry ${secFilter.toLowerCase()} risk.`;
  }
  function renderDrivers() {
    const box = $("#drv-chart");
    if (!box || !box.clientWidth) return;
    const counts = DRIVERS.map((d) => ({ d, n: SECS.filter((x) => x.d.includes(d)).length })).sort((a, b) => b.n - a.n);
    const W = boxWidth(box), rowH = 30, top = 2, Hh = top + counts.length * rowH + 2, labelW = 86, padR = 36;
    const max = Math.max(...counts.map((c) => c.n)), sx = (v) => labelW + (v / max) * (W - labelW - padR);
    box.replaceChildren();
    const s = svg("svg", { viewBox: `0 0 ${W} ${Hh}`, width: W, height: Hh, role: "img", "aria-label": "Number of catalog securities carrying each risk driver" }, box);
    counts.forEach((c, i) => {
      const y = top + i * rowH + 7, on = secFilter === c.d;
      text(s, 0, y + 12, c.d, on ? "lbl-strong" : "cat", "start");
      svg("path", { d: hbar(sx(0), sx(c.n), y, 16), fill: on ? "var(--accent)" : "var(--s1)" }, s);
      text(s, sx(c.n) + 6, y + 12, String(c.n), "lbl-strong", "start");
      const hit = svg("rect", { x: 0, y: y - 7, width: W, height: rowH, class: "hit", tabindex: "0", role: "button", "aria-label": `Filter the catalog to ${c.d}: ${c.n} securities` }, s);
      hit.style.cursor = "pointer";
      const go = () => { secFilter = secFilter === c.d ? "All" : c.d; renderSecurities(); $("#sec-filters").scrollIntoView({ block: "start", behavior: "smooth" }); };
      hit.addEventListener("click", go);
      hit.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); } });
      bindTip(hit, () => [[`${c.n} of ${SECS.length}`, `carry ${c.d.toLowerCase()} risk`]]);
    });
  }

  /* ---------- live capex from SEC filings (data/capex.json) ---------- */
  function renderCapex(cx) {
    const cos = cx && cx.companies ? Object.entries(cx.companies).filter(([, rows]) => rows && rows.length) : [];
    if (!cos.length) return;
    const latest = cos.map(([t, rows]) => {
      const ok = rows.filter((r) => r.ocf != null && r.capex != null);
      const r = ok[ok.length - 1] || rows[rows.length - 1];
      const ttm = ok.slice(-4);
      const sum = (k) => ttm.reduce((a, x) => a + (x[k] || 0), 0);
      return { t, r, rows: ok, ratio: r.ocf ? r.capex / r.ocf : null, ttmRatio: ttm.length === 4 && sum("ocf") > 0 ? sum("capex") / sum("ocf") : null,
        ttmCapex: ttm.length === 4 ? sum("capex") : null, ttmOcf: ttm.length === 4 ? sum("ocf") : null };
    }).sort((a, b) => (b.ratio ?? -1) - (a.ratio ?? -1));
    LIVE.capex = latest;
    const wrap = $("#capex-live");
    wrap.replaceChildren();
    const grid = h("div", "capex-grid");
    const f1 = figureBlock("Capex as a share of operating cash flow, latest quarter", [["var(--s1)", "Funded by cash flow"], ["var(--red)", "Capex above cash flow"]], "cx-chart");
    const f2 = figureBlock("Capex and operating cash flow by quarter, $bn", [["var(--s1)", "Capex", true], ["var(--s2)", "Operating cash flow", true]], "cx-lines");
    const pick = h("div", "seg"), order = cos.map(([t]) => t), first = order.includes("GOOGL") ? "GOOGL" : order[0];
    pick.setAttribute("role", "group");
    pick.setAttribute("aria-label", "Company");
    order.map((t) => latest.find((c) => c.t === t)).forEach((c) => {
      const b = h("button", null, c.t);
      b.type = "button";
      b.dataset.t = c.t;
      b.setAttribute("aria-pressed", c.t === first ? "true" : "false");
      b.addEventListener("click", () => { LIVE.capexPick = c.t; pick.querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", x === b ? "true" : "false")); drawCapex(); });
      pick.append(b);
    });
    f2.insertBefore(pick, f2.querySelector(".svgbox"));
    LIVE.capexPick = first;
    const p1 = h("div", "panel"), p2 = h("div", "panel");
    p1.append(f1);
    p2.append(f2);
    grid.append(p1, p2);
    const rows = latest.map((c) => [c.t, niceDate(c.r.quarter_end), num(c.r.ocf, 1), num(c.r.capex, 1), fx(c.r.fcf, 1), c.ratio == null ? "n/a" : pctPlain(c.ratio, 0), c.ttmRatio == null ? "n/a" : pctPlain(c.ttmRatio, 0), num(c.r.long_term_debt, 1), num(c.r.cash, 1)]);
    const tb = tableBlock(["Ticker", "Quarter ended", "Operating cash flow", "Capex", "Free cash flow", "Capex ÷ cash flow", "Last four quarters", "Long-term debt", "Cash"], rows, 1);
    const p3 = h("div", "panel");
    p3.append(tb, h("p", "hint", "USD billions. SEC EDGAR XBRL company facts; year-to-date cash flows are converted to single quarters. Debt and cash are period-end balances as filed."));
    wrap.append(grid, p3);
    wrap.style.display = "grid";
    wrap.style.gap = "16px";
    drawCapex();
  }
  function drawCapex() {
    const latest = LIVE.capex;
    if (!latest) return;
    const box = $("#cx-chart");
    if (box && box.clientWidth) {
      const W = boxWidth(box), rowH = 34, top = 20, labelW = 58, padR = 52;
      const list = latest.filter((c) => c.ratio != null), Hh = top + list.length * rowH + 26;
      const hi = Math.max(1.2, ...list.map((c) => c.ratio)) * 1.05, ticks = niceTicks(0, hi, 4), x1 = ticks[ticks.length - 1];
      const sx = (v) => labelW + (Math.max(0, v) / x1) * (W - labelW - padR);
      box.replaceChildren();
      const s = svg("svg", { viewBox: `0 0 ${W} ${Hh}`, width: W, height: Hh, role: "img", "aria-label": "Capex as a share of operating cash flow by company, latest quarter" }, box);
      ticks.forEach((t) => { svg("line", { x1: sx(t), x2: sx(t), y1: top, y2: Hh - 22, class: t === 0 ? "baseline" : "gridline" }, s); text(s, sx(t), Hh - 6, pctPlain(t, 0), "ax", "middle"); });
      list.forEach((c, i) => {
        const y = top + i * rowH + 8;
        text(s, 0, y + 13, c.t, "cat", "start");
        svg("path", { d: hbar(sx(0), sx(c.ratio), y, 18), fill: c.ratio > 1 ? "var(--red)" : "var(--s1)" }, s);
        text(s, sx(c.ratio) + 6, y + 13, pctPlain(c.ratio, 0), "lbl-strong", "start");
        const hit = svg("rect", { x: 0, y: y - 6, width: W, height: rowH, class: "hit", tabindex: "0", "aria-label": `${c.t}: capex ${pctPlain(c.ratio, 0)} of operating cash flow in the quarter ending ${c.r.quarter_end}` }, s);
        bindTip(hit, () => [[pctPlain(c.ratio, 0) + " of cash flow", `${c.t} · quarter ending ${c.r.quarter_end} · capex $${num(c.r.capex, 1)}B, cash flow $${num(c.r.ocf, 1)}B`]]);
      });
      svg("line", { x1: sx(1), x2: sx(1), y1: top, y2: Hh - 22, stroke: "var(--ink-2)", "stroke-width": 1.5, "stroke-dasharray": "4 3" }, s);
      text(s, sx(1), top - 7, "Capex = cash flow", "ax", "middle");
    }
    const lb = $("#cx-lines"), pick = latest.find((c) => c.t === LIVE.capexPick) || latest[0];
    if (lb && lb.clientWidth && pick && pick.rows.length) {
      const pts = (k) => pick.rows.map((r) => [Date.parse(r.quarter_end), r[k]]);
      const p0 = pts("capex");
      xyChart(lb, { series: [{ name: "Capex", color: "var(--s1)", width: 2.5, dots: true, pts: p0 }, { name: "Operating cash flow", color: "var(--s2)", width: 2, pts: pts("ocf") }],
        zero: true, yfmt: (v) => "$" + fx(v, 0), xfmt: dateLabel, xticks: yearTicks(p0[0][0], p0[p0.length - 1][0]), label: `${pick.t} capex and operating cash flow by quarter`, height: 240, snapXs: p0.map((p) => p[0]) });
    }
  }

  function buildTheses() {
    const g = $("#thesis-grid");
    THESES.forEach((t) => {
      const c = h("article", "thesis");
      c.id = t.id;
      const head = h("div", "thesis-head");
      const label = t.st === "active" ? "Active" : t.st === "watch" ? "Watch" : "Risk";
      head.append(h("h3", null, t.t), h("span", "status " + t.st, label));
      const left = h("div", "col"), right = h("div", "col");
      const sec = (title, node) => { const d = h("div"); d.append(h("h4", null, title), node); return d; };
      const ul = (items) => { const u = h("ul"); items.forEach((x) => u.append(h("li", null, x))); return u; };
      left.append(h("p", "stance", t.stance), sec("Evidence", ul(t.ev)));
      // v0.24: this week's checked items that bear on the thesis, from the research digest, each linked to its source
      const wk = (typeof DIGEST24 !== "undefined" && DIGEST24 && Array.isArray(DIGEST24.items) && Array.isArray(t.wk)) ? t.wk.map((id) => dgFind(DIGEST24, id)).filter(Boolean) : [];
      if (wk.length) {
        const u = h("ul", "thesis-wk");
        wk.forEach((x) => { const li = h("li"); const a = h("a", "src", `${x.publisher || "Source"}, ${isoNice(x.as_of)}`); a.href = x.source_url; a.target = "_blank"; a.rel = "noopener"; li.append(document.createTextNode(x.text + " "), a); u.append(li); });
        left.append(sec("This week's evidence", u));
      }
      if (BEAR[t.id]) left.append(sec("Strongest case against", h("p", "prose", BEAR[t.id])));
      right.append(sec("Expression", h("p", "prose", t.ex)), sec("Hedge", h("p", "prose", t.hd)), sec("What would change the desk's mind", ul(t.kill)), sec("Data the engine tracks", ul(t.data)));
      c.append(head, left, right);
      g.append(c);
    });
  }
  function buildLenses() {
    const g = $("#lens-grid");
    LENSES.forEach((L) => {
      const c = h("article", "lens");
      c.id = "lens-" + slug(L.n);
      c.append(h("h3", null, L.n), h("p", "idea", L.idea));
      const rule = h("p", "rule");
      rule.append(h("b", null, "How the desk uses it"), document.createTextNode(L.rule));
      c.append(rule, h("p", "read", L.read));
      if (L.link) { const a = h("a", "src", L.link[0]); a.href = L.link[1]; c.append(a); }
      g.append(c);
    });
  }

  /* ---------- capex charts ---------- */
  const GOOG = [{ q: "Q4 2025", capex: 27.9, fcf: 24.6 }, { q: "Q1 2026", capex: 35.7, fcf: 10.1 }, { q: "Q2 2026", capex: 44.9, fcf: -5.9 }];
  function renderGoog() {
    const box = $("#goog-chart");
    if (!box || !box.clientWidth) return;
    const W = boxWidth(box), Hh = 240, padL = 36, padR = 8, top = 18, bottom = 28;
    const ticks = niceTicks(-10, 50, 6), lo = ticks[0], hi = ticks[ticks.length - 1];
    const sy = (v) => top + (1 - (v - lo) / (hi - lo)) * (Hh - top - bottom);
    const band = (W - padL - padR) / GOOG.length, bw = Math.min(24, band / 4);
    box.replaceChildren();
    const s = svg("svg", { viewBox: `0 0 ${W} ${Hh}`, width: W, height: Hh, role: "img", "aria-label": "Alphabet capex rose from 27.9 to 44.9 billion dollars while free cash flow fell from 24.6 to minus 5.9" }, box);
    ticks.forEach((t) => { svg("line", { x1: padL, x2: W - padR, y1: sy(t), y2: sy(t), class: t === 0 ? "baseline" : "gridline" }, s); text(s, padL - 6, sy(t) + 4, t < 0 ? MINUS + Math.abs(t) : String(t), "ax", "end"); });
    GOOG.forEach((d, i) => {
      const cx = padL + band * (i + 0.5);
      text(s, cx, Hh - 8, d.q, "ax", "middle");
      [["capex", "var(--s1)", "Capex"], ["fcf", "var(--s2)", "Free cash flow"]].forEach(([k, color, label], j) => {
        const x = j ? cx + 2 : cx - 2 - bw, v = d[k];
        svg("path", { d: vbar(x, bw, sy(0), sy(v)), fill: color }, s);
        text(s, x + bw / 2, v >= 0 ? sy(v) - 5 : sy(v) + 13, (v < 0 ? MINUS : "") + Math.abs(v).toFixed(1), j ? "lbl-strong" : "lbl", "middle");
        const hit = svg("rect", { x: x - 3, y: Math.min(sy(0), sy(v)) - 3, width: bw + 6, height: Math.abs(sy(v) - sy(0)) + 6, class: "hit", tabindex: "0", "aria-label": `${d.q} ${label}: ${v} billion dollars` }, s);
        bindTip(hit, () => [[(v < 0 ? MINUS : "") + "$" + Math.abs(v).toFixed(1) + "B", `${label} · ${d.q}`]]);
      });
    });
    fillTable($("#goog-table"), ["Quarter", "Capex, $bn", "Free cash flow, $bn", "Operating cash flow, $bn"], GOOG.map((d) => [d.q, d.capex.toFixed(1), (d.fcf < 0 ? MINUS : "") + Math.abs(d.fcf).toFixed(1), (d.capex + d.fcf).toFixed(1)]));
  }
  const GUIDE = [{ co: "Amazon", lo: 220, hi: 220, label: "220" }, { co: "Alphabet", lo: 195, hi: 205, label: "195–205" }, { co: "Microsoft", lo: 175, hi: 175, label: "≈175" }, { co: "Meta", lo: 130, hi: 145, label: "130–145" }];
  function renderGuide() {
    const box = $("#guide-chart");
    if (!box || !box.clientWidth) return;
    const W = boxWidth(box), rowH = 46, top = 4, Hh = top + GUIDE.length * rowH + 22, labelW = 78, padR = 74;
    const ticks = niceTicks(0, 250, 5), hi = ticks[ticks.length - 1], sx = (v) => labelW + (v / hi) * (W - labelW - padR);
    box.replaceChildren();
    const s = svg("svg", { viewBox: `0 0 ${W} ${Hh}`, width: W, height: Hh, role: "img", "aria-label": "2026 capex guidance by company" }, box);
    ticks.forEach((t) => { svg("line", { x1: sx(t), x2: sx(t), y1: top, y2: Hh - 20, class: t === 0 ? "baseline" : "gridline" }, s); text(s, sx(t), Hh - 5, String(t), "ax", "middle"); });
    GUIDE.forEach((d, i) => {
      const y = top + i * rowH + (rowH - 18) / 2, mid = (d.lo + d.hi) / 2;
      text(s, 0, y + 13, d.co, "cat", "start");
      svg("path", { d: hbar(sx(0), sx(mid), y, 18), fill: "var(--s1)" }, s);
      if (d.hi > d.lo) {
        svg("line", { x1: sx(d.lo), x2: sx(d.hi), y1: y + 9, y2: y + 9, stroke: "var(--ink)", "stroke-width": 1.5 }, s);
        [d.lo, d.hi].forEach((v) => svg("line", { x1: sx(v), x2: sx(v), y1: y + 4, y2: y + 14, stroke: "var(--ink)", "stroke-width": 1.5 }, s));
      }
      const money$ = (d.label.startsWith("≈") ? "≈$" + d.label.slice(1) : "$" + d.label) + "B";
      text(s, sx(d.hi) + 8, y + 13, money$, "lbl-strong", "start");
      const hit = svg("rect", { x: sx(0), y: y - 4, width: sx(d.hi) - sx(0) + 6, height: 26, class: "hit", tabindex: "0", "aria-label": `${d.co}: ${d.label} billion dollars` }, s);
      bindTip(hit, () => [[money$, `${d.co} · 2026 capex guidance`]]);
    });
    fillTable($("#guide-table"), ["Company", "2026 capex guidance, $bn"], GUIDE.map((d) => [d.co, d.label]));
  }

  /* =====================================================================================
     SHARED HELPERS
     ===================================================================================== */
  const slug = (x) => String(x).toLowerCase().normalize("NFKD").replace(/[^\w\s-]/g, "").trim().replace(/[\s_]+/g, "-").replace(/-+/g, "-");
  // read a number input; out-of-range values are clamped and flagged, blanks fall back
  function readNum(el, lo, hi, fallback) {
    const raw = String(el.value).trim(), v = Number(raw);
    const ok = raw !== "" && fin(v) && v >= lo && v <= hi;
    el.setAttribute("aria-invalid", ok ? "false" : "true");
    el.title = ok ? "" : `Enter a number from ${lo.toLocaleString("en-US")} to ${hi.toLocaleString("en-US")}`;
    return ok ? v : raw !== "" && fin(v) ? clamp(v, lo, hi) : fallback;
  }
  const TAB_NAME = { nowcast: "Nowcast", edges: "Edge lab", reasoning: "Reasoning", methods: "Every method", crossfield: "Borrowed methods", explained: "How it works", parameters: "Parameters", digest: "Digest", desk: "Desk", rates: "Rates", options: "Options", hedges: "Hedges", securities: "Securities", insurers: "Insurers", theses: "Theses", lenses: "Lenses", engine: "Engine", appendix: "Appendix",
    decide: "Decide", journal: "Journal", swans: "Swans", fundamentals: "Fundamentals", physics: "Physics", findings: "Findings", legends: "Legends", lab: "Math lab",
    noteworthy: "Noteworthy", brain: "The brain", prop: "Prop", making: "Market making", buyside: "Buyside 2026", solve: "Solve", games: "Games", field: "Field", ooda: "Decision loop", decision: "Decision engine", portfolio: "Portfolio", matrix: "The shortcut", geometry: "Geometry", positions: "Positions", engines: "Engine room", atlas: "Atlas", mind: "The mind", labs: "Labs", analysis: "Analysis", bonds: "Bonds", ml: "ML lab", reality: "Reality check", edge: "Edge", cardroom: "Card room", code: "Under the hood", agents: "Agents" };
  const LINK_NAME = { "fw-title": "Carry and roll-down", "tb-title": "Tail-hedge budget", "hedge": "Hedge lab", "size": "Sizing lab", "iv-title": "Insurance price", "liq-title": "Liquidity",
    "lg-griffin": "Griffin's lens", "regime-title": "The regime", "roc-title": "Rates of change" };
  function linkLabel(target) {
    if (/^pb-/.test(target)) { const p = PLAYBOOKS.find((x) => x.id === target); return p ? `Playbook: ${p.t}` : "Playbook"; }
    if (/^t\d$/.test(target)) return `Thesis ${target.slice(1)}`;
    return LINK_NAME[target] || "Details";
  }

  /* =====================================================================================
     WHAT MOVED, THE PRICE OF INSURANCE, AND THE PLUMBING: three reads from the daily FRED run
     ===================================================================================== */
  const ord = (n) => { const x = ["th", "st", "nd", "rd"], v = n % 100; return n + (x[(v - 20) % 10] || x[v] || x[0]); };
  const rankTxt = (r) => (fin(r) ? `${ord(Math.round(r * 100))} percentile of ten years` : "");
  const moveChange = (kind, a, b) => (kind === "pct" ? b / a - 1 : kind === "bp" ? (b - a) * 100 : b - a);
  const fmtMove = (kind, v) => (!fin(v) ? "n/a" : kind === "pct" ? pct(v, 1) : kind === "bp" ? bp(v) : (Math.abs(v) < 0.005 ? "0.00" : (v > 0 ? "+" : MINUS) + fx(Math.abs(v), 2)));
  const MOVE_PREFIX = { brent: "$", btc: "$", DCOILBRENTEU: "$", CBBTCUSD: "$" };
  function fmtLevel(key, kind, v) {
    if (!fin(v)) return "n/a";
    if (key === "c2s10s") return bp(v * 100);
    if (kind === "bp") return fx(v, 2) + "%";
    if (kind === "pts") return fx(v, 2);
    return (MOVE_PREFIX[key] || "") + (Math.abs(v) >= 1000 ? Math.round(v).toLocaleString("en-US") : fx(v, 2));
  }
  const okMove = (r) => r && typeof r.label === "string" && ["bp", "pts", "pct"].includes(r.kind) && fin(r.value) && isoOk(r.date);
  const zOk = (z) => (fin(z) && Math.abs(z) < 50 ? z : null);      // a 50σ week is a data error, not news
  const liveMoves = () => (LIVE.macro && Array.isArray(LIVE.macro.moves) ? LIVE.macro.moves.filter(okMove) : []);
  function weekMoves() {
    const live = liveMoves();
    if (live.length) return { live: true, rows: live.map((r) => ({ key: r.key, label: r.label, kind: r.kind, w1: fin(r.w1) ? r.w1 : null, z: zOk(r.z_w1) })) };
    return { live: false, rows: STATIC_MOVES.rows.map(([label, kind, a, b, date, fid, lead]) => ({ key: fid, label, kind, w1: moveChange(kind, a, b), lead: !!lead })) };
  }
  function weekLine() {
    const { live, rows } = weekMoves();
    const pick = live ? rows.filter((r) => r.z != null && r.w1 != null).sort((a, b) => Math.abs(b.z) - Math.abs(a.z)).slice(0, 4) : rows.filter((r) => r.lead);
    if (!pick.length) return "";
    const eq = rows.find((r) => r.key === "ndx" || r.key === "NASDAQ100");
    const bond = rows.find((r) => r.key === "y30" || r.key === "DGS30") || rows.find((r) => r.key === "y10" || r.key === "DGS10");
    let tail = "";
    if (eq && bond && fin(eq.w1) && fin(bond.w1) && eq.w1 < -0.01) {
      tail = bond.w1 <= -2 ? " Long yields fell as stocks did: bonds hedged this week." : bond.w1 >= 2 ? " Long yields rose as stocks fell: bonds amplified this week." : " Long yields barely moved as stocks fell.";
    }
    const lead = live ? "Largest moves this week, against three years of weekly moves: " : `Since the ${STATIC_MOVES.from} close: `;
    return lead + pick.map((r) => `${r.label} ${fmtMove(r.kind, r.w1)}${live && r.z != null ? ` (${fx(r.z, 1)}σ)` : ""}`).join(", ") + "." + tail;
  }
  function spark(o, w = 84, hgt = 22) {
    const pts = seriesPts(o), s = svg("svg", { viewBox: `0 0 ${w} ${hgt}`, width: w, height: hgt, class: "spark", "aria-hidden": "true" });
    if (pts.length < 2) return s;
    const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
    const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
    const sx = (x) => 1 + ((x - x0) / (x1 - x0 || 1)) * (w - 4), sy = (y) => hgt - 3 - ((y - y0) / (y1 - y0 || 1)) * (hgt - 6);
    svg("path", { d: pts.map((p, i) => (i ? "L" : "M") + sx(p[0]).toFixed(1) + " " + sy(p[1]).toFixed(1)).join(" "), fill: "none", stroke: "var(--s1)", "stroke-width": 1.25, "stroke-linejoin": "round" }, s);
    const last = pts[pts.length - 1];
    svg("circle", { cx: sx(last[0]), cy: sy(last[1]), r: 2.25, fill: "var(--s1)" }, s);
    return s;
  }
  function renderMoves() {
    const tbl = $("#mv-table");
    if (!tbl) return;
    const live = liveMoves(), thead = h("thead"), hr = h("tr"), tb = h("tbody");
    const cols = live.length
      ? [["Market", ""], ["Level", "r"], ["1 day", "r opt"], ["1 week", "r"], ["1 month", "r opt"], ["Year to date", "r"], ["1 year", "r opt"], ["Unusual", "r"], ["Past year", "opt"]]
      : [["Market", ""], ["Level", "r"], [`Since ${STATIC_MOVES.from}`, "r"], ["As of", "r"]];
    cols.forEach(([t, c]) => { const th = h("th", c || null, t); th.scope = "col"; hr.append(th); });
    thead.append(hr);
    if (live.length) {
      live.forEach((r) => {
        const tr = h("tr"), z = zOk(r.z_w1), th = h("th", null, r.label);
        th.scope = "row";
        if (z != null && Math.abs(Number(z.toFixed(1))) >= 2) tr.className = "hot";   // same rounding as the cell shows
        tr.append(th, h("td", "r", fmtLevel(r.key, r.kind, r.value)));
        [["d1", "r opt"], ["w1", "r"], ["m1", "r opt"], ["ytd", "r"], ["y1", "r opt"]].forEach(([k, c]) => tr.append(h("td", c, fmtMove(r.kind, r[k]))));
        tr.append(h("td", "r", z == null ? "n/a" : `${fx(z, 1)}σ`));
        const sp = h("td", "opt");
        sp.append(spark(r.spark));
        tr.append(sp);
        tb.append(tr);
      });
      const last = live.map((r) => r.date).sort().pop();
      $("#mv-note").textContent = `FRED, latest prints through ${niceDate(last)}. Unusual is this week's change in standard deviations of every seven-day change over the past three years; rows at 2σ or more are highlighted. Yields and spreads move in basis points, volatility in points, prices in percent.`;
    } else {
      STATIC_MOVES.rows.forEach(([label, kind, a, b, date, fid]) => {
        const tr = h("tr"), th = h("th", null, label);
        th.scope = "row";
        tr.append(th, h("td", "r", fmtLevel(fid, kind, b)), h("td", "r", fmtMove(kind, moveChange(kind, a, b))), h("td", "r", date));
        tb.append(tr);
      });
      $("#mv-note").textContent = `FRED, as shipped: the ${STATIC_MOVES.from} close against each series' latest close. The daily run replaces it with day, month, year-to-date and one-year changes and flags unusual moves.`;
    }
    tbl.replaceChildren(thead, tb);
  }

  function tileLive(label, value, note, date, maxAge) { const t = tile(label, value, note); t.classList.add("live"); t.prepend(liveBadge(date, maxAge)); return t; }
  function renderInsurance() {
    const tiles = $("#iv-tiles"), read = $("#iv-read");
    if (!tiles || !read) return;
    const v = LIVE.macro && LIVE.macro.vol && LIVE.macro.vol.latest ? LIVE.macro.vol.latest : null;
    const okVol = (x) => x && fin(x.implied) && fin(x.realized) && fin(x.vrp) && isoOk(x.date);
    const ndx = v && okVol(v.ndx) ? v.ndx : null, spx = v && okVol(v.spx) ? v.spx : null, term = v && v.term && fin(v.term.ratio) && isoOk(v.term.date) ? v.term : null;
    const S = STATIC_VOL, signed = (x) => (x >= 0 ? "+" : MINUS) + fx(Math.abs(x), 1);
    tiles.replaceChildren();
    if (ndx) {
      tiles.append(tileLive("VXN, Nasdaq-100 implied", fx(ndx.implied, 1), rankTxt(ndx.implied_rank10y) || "Points of annualized volatility.", ndx.date),
        tileLive("Realized, 21 trading days", fx(ndx.realized, 1), "Nasdaq-100, close to close, annualized.", ndx.date),
        tileLive("Premium: implied minus realized", signed(ndx.vrp), fin(ndx.vrp_median10y) ? `Ten-year median ${signed(ndx.vrp_median10y)} points.` : "", ndx.date));
      if (spx) tiles.append(tileLive("VIX against S&P 500 realized", `${fx(spx.implied, 1)} vs ${fx(spx.realized, 1)}`, fin(spx.earned_mean5y) ? `Over five years, VIX averaged ${signed(spx.earned_mean5y)} points above what the next month delivered.` : "", spx.date));
    } else {
      tiles.append(tile("VXN, Nasdaq-100 implied", fx(S.vxn[0], 2), `${S.vxn[1]} close.`), tile("VIX, S&P 500 implied", fx(S.vix[0], 2), `${S.vix[1]} close.`),
        tile("Realized and the premium", "Daily run", "Realized volatility needs price history; it fills in from the daily run."));
    }
    const ratio = term ? term.ratio : S.vix[0] / S.vix3m[0];
    tiles.append(term ? tileLive("VIX over 3-month VIX", fx(ratio, 2), `${fin(term.days_inverted_1y) ? term.days_inverted_1y : "n/a"} inverted days in the past year.`, term.date)
      : tile("VIX over 3-month VIX", fx(ratio, 2), `${fx(S.vix[0], 2)} against ${fx(S.vix3m[0], 2)}, ${S.vix3m[1]}.`));
    const rank = ndx && fin(ndx.implied_rank10y) ? ndx.implied_rank10y : null, flat = ratio >= 0.95 ? " The VIX curve is flattening: near-term fear is building." : "";
    let cls = "", msg;
    if (ratio >= 1) { cls = "warn"; msg = `Stress is priced now: the VIX curve is inverted at ${fx(ratio, 2)}. Monetize puts in stages; any new protection should be spreads.`; }
    else if (ndx && rank != null && rank <= 1 / 3 && (!fin(ndx.vrp_median10y) || ndx.vrp <= ndx.vrp_median10y + 2)) { cls = "ok"; msg = `Insurance is cheap: VXN sits at the ${rankTxt(rank)} and only ${signed(ndx.vrp)} points over realized. Buy convexity: puts and put spreads, at longer tenors.${flat}`; }
    else if (ndx && rank != null && rank >= 0.8) { cls = "warn"; msg = `Insurance is expensive: VXN sits at the ${rankTxt(rank)}. Prefer put spreads and collars to outright puts, and size from the budget, not from fear.${flat}`; }
    else if (ndx) { msg = `Fairly priced: VXN at the ${rankTxt(rank) || "middle of its range"}, ${signed(ndx.vrp)} points over realized${fin(ndx.vrp_median10y) ? ` against a ten-year median of ${signed(ndx.vrp_median10y)}` : ""}.${flat}`; }
    else { msg = (ratio >= 0.95 ? `The VIX curve is nearly flat at ${fx(ratio, 2)}: near-term fear is building, so protection is not cheap.` : `The VIX curve is in normal contango at ${fx(ratio, 2)}.`) + " Realized volatility and the premium fill in after the first daily run."; }
    read.className = "sentence" + (cls ? " " + cls : "");
    read.textContent = msg;
    const H = LIVE.macro && LIVE.macro.vol && LIVE.macro.vol.history;
    $("#iv-charts").hidden = !(H && ((H.ndx && hasSeries(H.ndx.implied)) || hasSeries(H.term)));
    drawInsurance();
  }
  function drawInsurance() {
    const H = LIVE.macro && LIVE.macro.vol && LIVE.macro.vol.history;
    if (!H) return;
    const box = $("#iv-chart");
    if (box && box.clientWidth && H.ndx && hasSeries(H.ndx.implied)) {
      const imp = seriesPts(H.ndx.implied), rea = seriesPts(H.ndx.realized);
      legendLines($("#iv-legend"), [["var(--s1)", "Implied (VXN)"], ["var(--s2)", "Realized, 21 days"]]);
      xyChart(box, { series: [{ name: "Implied (VXN)", color: "var(--s1)", pts: imp }, { name: "Realized", color: "var(--s2)", pts: rea, width: 1.5 }], yfmt: (x) => fx(x, 0),
        xticks: yearTicks(imp[0][0], imp[imp.length - 1][0]), xfmt: dateLabel, height: 230, label: "Nasdaq-100 implied and realized volatility, weekly" });
    }
    const tb = $("#iv-term");
    if (tb && tb.clientWidth && hasSeries(H.term)) {
      const pts = seriesPts(H.term);
      xyChart(tb, { series: [{ name: "VIX over 3-month VIX", color: "var(--s1)", pts }], hlines: [{ y: 1, color: "var(--bad)", label: "Inverted above 1" }], yfmt: (x) => fx(x, 2),
        xticks: yearTicks(pts[0][0], pts[pts.length - 1][0]), xfmt: dateLabel, height: 230, label: "VIX over 3-month VIX, weekly" });
    }
  }

  function renderLiquidity() {
    const tiles = $("#liq-tiles"), read = $("#liq-read");
    if (!tiles || !read) return;
    const L = LIVE.macro && LIVE.macro.liquidity && LIVE.macro.liquidity.latest ? LIVE.macro.liquidity.latest : null;
    const net = L && L.net && fin(L.net.value) && fin(L.net.fed_assets) && fin(L.net.tga) && fin(L.net.rrp) && isoOk(L.net.date) ? L.net : null;
    const res = L && L.reserves && fin(L.reserves.value) && isoOk(L.reserves.date) ? L.reserves : null;
    const fund = L && L.funding && fin(L.funding.gap_bp) && fin(L.funding.gap_5d_bp) && isoOk(L.funding.date) ? L.funding : null;
    const S = STATIC_LIQ, T = (x) => "$" + fx(x, 2) + "T", B = (t) => "$" + fx(t * 1000, t < 0.01 ? 2 : 0) + "B";
    const chg = (x, w) => (fin(x) ? `${x >= 0 ? "+" : MINUS}$${fx(Math.abs(x), 2)}T over ${w} weeks.` : "");
    tiles.replaceChildren();
    const wk = STALE_DAYS.weekly;
    if (net) tiles.append(tileLive("Net liquidity", T(net.value), chg(net.chg_13w, 13), net.date, wk), tileLive("Fed assets", T(net.fed_assets), "Wednesday level.", net.date, wk),
      tileLive("Treasury cash (TGA)", T(net.tga), "Week average.", net.date, wk), tileLive("Reverse repo", B(net.rrp), "Overnight facility, on the same Wednesday.", net.date, wk));
    else tiles.append(tile("Net liquidity", T(S.assets[0] - S.tga[0] - S.rrp[0]), `${S.assets[1]}: Fed assets minus Treasury cash minus reverse repo.`), tile("Fed assets", T(S.assets[0]), `${S.assets[1]}, Wednesday level.`),
      tile("Treasury cash (TGA)", T(S.tga[0]), `${S.tga[1]}, week average.`), tile("Reverse repo", B(S.rrp[0]), `${S.rrp[1]}: the facility is all but empty.`));
    tiles.append(res ? tileLive("Bank reserves", T(res.value), chg(res.chg_13w, 13), res.date, wk) : tile("Bank reserves", T(S.reserves[0]), `${S.reserves[1]}, week average.`));
    const gap = fund ? fund.gap_5d_bp : (S.sofr[0] - S.iorb[0]) * 100;
    tiles.append(fund ? tileLive("SOFR minus IORB", bp(fund.gap_bp), `5-day average ${bp(fund.gap_5d_bp)}; 3-month high ${bp(fund.gap_max_3m_bp)}.`, fund.date)
      : tile("SOFR minus IORB", bp(gap), `SOFR ${fx(S.sofr[0], 2)}% against IORB ${fx(S.iorb[0], 2)}%, ${S.sofr[1]}.`));
    const rrp = net ? net.rrp : S.rrp[0], state = gap >= 10 ? "Stress" : gap > 0 ? "Tight" : "Ample";
    read.className = "sentence " + (gap > 0 ? "warn" : "ok");
    read.textContent = `${state}: repo trades ${gap > 0 ? "above" : "below"} the rate the Fed pays on reserves, ${bp(gap)}${fund ? " over five days" : ""}. `
      + (rrp < 0.05 ? "The reverse repo facility is all but empty, so any further drain (a larger Treasury cash balance or a smaller Fed) comes out of bank reserves." : `Reverse repo still holds ${B(rrp)} that can drain before reserves do.`)
      + (net && fin(net.chg_13w) ? ` Net liquidity ${net.chg_13w >= 0 ? "rose" : "fell"} ${T(Math.abs(net.chg_13w))} over 13 weeks.` : "");
    const H = LIVE.macro && LIVE.macro.liquidity && LIVE.macro.liquidity.history;
    $("#liq-charts").hidden = !(H && (hasSeries(H.net) || hasSeries(H.funding_gap_bp)));
    drawLiquidity();
  }
  function drawLiquidity() {
    const H = LIVE.macro && LIVE.macro.liquidity && LIVE.macro.liquidity.history;
    if (!H) return;
    const nb = $("#liq-net");
    if (nb && nb.clientWidth && hasSeries(H.net)) {
      const pts = seriesPts(H.net);
      xyChart(nb, { series: [{ name: "Net liquidity", color: "var(--s1)", pts, endLabel: "$" + fx(pts[pts.length - 1][1], 2) + "T" }], yfmt: (x) => "$" + fx(x, 1) + "T",
        xticks: yearTicks(pts[0][0], pts[pts.length - 1][0]), xfmt: dateLabel, height: 230, label: "Net liquidity in trillions of dollars, weekly" });
    }
    const gb = $("#liq-gap");
    if (gb && gb.clientWidth && hasSeries(H.funding_gap_bp)) {
      const pts = seriesPts(H.funding_gap_bp);
      xyChart(gb, { series: [{ name: "SOFR minus IORB", color: "var(--s2)", pts, width: 1.25 }], zero: true, yfmt: (x) => fx(x, 0),
        xticks: yearTicks(pts[0][0], pts[pts.length - 1][0]), xfmt: dateLabel, height: 230, label: "SOFR minus IORB in basis points, daily" });
    }
  }

  // one sentence for the whole board: what is red, which playbook the signals argue for, and what this week did
  const SIG_SHORT = { corr: "stock-bond correlation", real: "real yields", be: "breakevens", curve: "2s10s", hy: "high yield", ccc: "CCC credit", vix: "VIX",
    vts: "VIX curve", oil: "Brent", capex: "capex funding", funding: "repo funding", fed: "Fed" };
  function renderDeskRead(states) {
    const box = $("#desk-read");
    if (!box) return;
    box.replaceChildren();
    const red = states.filter((x) => x.level === 2), amber = states.filter((x) => x.level === 1), score = {};
    states.forEach(({ sg, level }) => {
      const pb = level != null && sg.pb ? sg.pb[level] : null;
      if (pb) score[pb] = (score[pb] || 0) + (level === 2 ? 2 : 1);
    });
    const ranked = Object.entries(score).sort((a, b) => b[1] - a[1]);
    const list = (xs) => xs.map(({ sg, level }) => `${SIG_SHORT[sg.id] || sg.name} (${sg.labels[level].toLowerCase()})`).join(", ");
    const p1 = h("p");
    p1.append(h("strong", null, `Desk read: ${red.length} red, ${amber.length} amber of ${states.length} signals. `));
    if (red.length) p1.append(document.createTextNode(`Red: ${list(red)}. `));
    if (amber.length) p1.append(document.createTextNode(`Amber: ${list(amber)}.`));
    const p2 = h("p"), top = ranked[0], pb = top && PLAYBOOKS.find((x) => x.id === top[0]);
    if (pb && top[1] >= 3) {
      const a = h("a", null, `${pb.t} →`);
      a.href = "#" + pb.id;
      p2.append(h("strong", null, "Closest playbook: "), a, document.createTextNode(` (${pb.tag.toLowerCase()}).`));
      const nx = ranked[1] && PLAYBOOKS.find((x) => x.id === ranked[1][0]);
      if (nx && ranked[1][1] >= 2) p2.append(document.createTextNode(` Next: ${nx.t.toLowerCase()}.`));
    } else p2.append(document.createTextNode("No playbook has enough signals behind it: run the base book with its standing hedges."));
    box.append(p1, p2);
    const wk = weekLine();
    if (wk) box.append(h("p", "wk", wk));
  }

  /* =====================================================================================
     SIGNALS BOARD
     ===================================================================================== */
  function curveNow() {
    const c = LIVE.macro && LIVE.macro.rates && LIVE.macro.rates.curves && LIVE.macro.rates.curves.latest;
    if (!c || !Array.isArray(c.points)) return null;
    const by = {};
    c.points.forEach((p) => { if (fin(p.yield)) by[p.tenor] = p.yield; });
    return { by, date: c.date };
  }
  function signalLive(sg) {
    const m = LIVE.macro, lat = m && m.latest, lv = m && m.rates && m.rates.levels;
    const L = (k) => (lv && lv[k] && fin(lv[k].value) ? { v: lv[k].value, date: lv[k].date } : null);
    switch (sg.id) {
      case "corr": return lat && fin(lat.corr63) ? { v: lat.corr63, date: lat.as_of, note: "Nasdaq-100 vs 20-year bond, 63-day half-life" } : null;
      case "real": return L("real10");
      case "be": return L("breakeven10");
      case "hy": return L("hy_oas");
      case "ccc": return L("ccc_oas");
      case "vts": {
        const t = m && m.vol && m.vol.latest && m.vol.latest.term;
        return t && fin(t.ratio) && isoOk(t.date) ? { v: t.ratio, date: t.date, note: fin(t.vix) && fin(t.vix3m) ? `VIX ${fx(t.vix, 2)} against 3-month VIX ${fx(t.vix3m, 2)}` : null } : null;
      }
      case "funding": {
        const f = m && m.liquidity && m.liquidity.latest && m.liquidity.latest.funding;
        return f && fin(f.gap_5d_bp) && isoOk(f.date) ? { v: f.gap_5d_bp, date: f.date, note: fin(f.sofr) && fin(f.iorb) ? `5-day average; SOFR ${fx(f.sofr, 2)}% against IORB ${fx(f.iorb, 2)}%` : "5-day average" } : null;
      }
      case "vix": return L("vix");
      case "oil": return L("brent");
      case "curve": { const c = curveNow(); return c && fin(c.by["10Y"]) && fin(c.by["2Y"]) ? { v: (c.by["10Y"] - c.by["2Y"]) * 100, date: c.date } : null; }
      case "capex": {
        // the builders as one balance sheet, trailing twelve months, the same figure the Fundamentals desk prints
        const rows = (LIVE.capex || []).filter((x) => fin(x.ttmCapex) && fin(x.ttmOcf) && x.ttmOcf > 0);
        if (!rows.length) return null;
        const capex = rows.reduce((a, x) => a + x.ttmCapex, 0), ocf = rows.reduce((a, x) => a + x.ttmOcf, 0);
        return { v: capex / ocf, date: rows.map((x) => x.r.quarter_end).sort().pop(), note: `${rows.length} builders, trailing twelve months: capex $${fx(capex, 0)}B against operating cash flow of $${fx(ocf, 0)}B` };
      }
      default: return null;
    }
  }
  function fmtSignal(sg, v) {
    if (sg.unit === "corr") return sgn2(v);
    if (sg.unit === "%") return fx(v, 2) + "%";
    if (sg.unit === "bp") return bp(v);
    if (sg.unit === "$") return "$" + fx(v, 2);
    if (sg.unit === "ratio") return pctPlain(v, 0) + " of cash flow";
    if (sg.unit === "x") return fx(v, 2);
    return fx(v, 2);
  }
  function renderSignals() {
    const box = $("#signals-grid");
    box.replaceChildren();
    let nLive = 0;
    const states = [];
    SIGNALS.forEach((sg) => {
      const lv = signalLive(sg), use = lv || sg.snap;
      let level = null, val = "Waiting for the daily run";
      if (sg.unit === "text") { if (use) { level = use.lvl; val = use.text; } }
      else if (use && fin(use.v)) { level = sg.level(use.v); val = fmtSignal(sg, use.v); }
      if (lv) nLive++;
      states.push({ sg, level, live: !!lv, v: use && fin(use.v) ? use.v : null });
      const card = h("article", "sig " + (level == null ? "lx" : "l" + level));
      card.id = "sig-" + sg.id;
      const top = h("div", "sig-top");
      top.append(h("span", "sig-name", sg.name), h("span", "sig-state", level == null ? "No data" : sg.labels[level]));
      card.append(top, h("span", "sig-val" + (sg.unit === "text" ? " text" : ""), val));
      if (use && use.note) card.append(h("span", "sig-rule", use.note));
      card.append(h("span", "sig-rule", sg.rule));
      if (level != null) card.append(h("span", "sig-act", sg.act[level]));
      const foot = h("div", "sig-foot");
      if (lv && sg.id === "capex") foot.append(h("span", "src", `SEC filings · quarter ended ${niceDate(lv.date)}`));
      else if (lv) foot.append(liveBadge(lv.date, STALE_DAYS[sg.id] || STALE_AFTER));
      else if (use && use.src) { const sp = h("span", "src"); sp.append(document.createTextNode("As of " + use.date + " · ")); const a = h("a", null, use.src[0]); a.href = use.src[1]; sp.append(a); foot.append(sp); }
      else foot.append(h("span", "src", "Live only: fills in after the first daily run"));
      if (sg.link) { const a = h("a", null, linkLabel(sg.link) + " →"); a.href = "#" + sg.link; a.className = "src"; foot.append(a); }
      card.append(foot);
      box.append(card);
    });
    $("#sig-sub").textContent = nLive
      ? `${nLive} of ${SIGNALS.length} signals read live from the daily run; the rest show the dated snapshot. Each has a rule and an action.`
      : `${SIGNALS.length} signals, each with a rule and an action. Live values replace the dated snapshot after each daily run.`;
    LIVE.sigStates = Object.fromEntries(states.map((x) => [x.sg.id, x]));
    guard("Desk read", () => renderDeskRead(states), $("#desk-read"));
  }

  /* =====================================================================================
     RATES: zero curve, forwards, carry and roll-down
     ===================================================================================== */
  let fwPick = null;
  function curveSets() {
    const sets = CURVES.dates.map((d) => ({ label: d.label, years: CURVES.years, y: d.y.map((v) => v / 100) }));
    const c = LIVE.macro && LIVE.macro.rates && LIVE.macro.rates.curves && LIVE.macro.rates.curves.latest;
    if (c && Array.isArray(c.points)) {
      const pts = c.points.filter((p) => fin(p.yield) && fin(p.years)).sort((a, b) => a.years - b.years);
      const years = pts.map((p) => p.years), y = pts.map((p) => p.yield / 100);
      // a live curve joins only if it bootstraps to positive discount factors all the way out
      if (pts.length >= 8 && years[years.length - 1] >= 20 && bootstrap(years, y).ok) sets.push({ label: "FRED " + niceDate(c.date), years, y, live: true });
    }
    return sets;
  }
  function buildForwardDates() {
    const wrap = $("#fw-dates");
    wrap.replaceChildren();
    const sets = curveSets();
    if (!fwPick || !sets.some((x) => x.label === fwPick)) fwPick = (sets.find((x) => x.live) || sets.find((x) => x.label === "Oct 23") || sets[sets.length - 1]).label;
    sets.forEach((x) => {
      const b = h("button", null, x.label);
      b.type = "button";
      b.setAttribute("aria-pressed", x.label === fwPick ? "true" : "false");
      b.addEventListener("click", () => { fwPick = x.label; buildForwardDates(); renderForward(); });
      wrap.append(b);
    });
  }
  const KEY_FWD = [["1y1y", 1, 2, "The 1-year rate one year out: where the market sees the Fed"], ["2y1y", 2, 3, "The 1-year rate two years out"],
    ["5y5y", 5, 10, "Long-run rate expectations plus term premium; the Fed watches it"], ["10y10y", 10, 20, "Distant forward: mostly term premium"], ["20y10y", 20, 30, "Falls below 10y10y when the 20-year kinks above the 30-year"]];
  function renderForward() {
    const sets = curveSets(), set = sets.find((x) => x.label === fwPick) || sets[sets.length - 1];
    const zc = bootstrap(set.years, set.y), box = $("#fw-chart");
    $("#fw-chart-title").textContent = `Par, zero and 6-month forward curves, ${set.label}`;
    legendLines($("#fw-legend"), [["var(--s1)", "Par"], ["var(--s3)", "Zero"], ["var(--s2)", "6-month forward"]]);
    if (box && box.clientWidth) {
      xyChart(box, { series: [
        { name: "Par", color: "var(--s1)", width: 2.5, pts: zc.grid.map((t) => [t, parAt(set.years, set.y, t) * 100]) },
        { name: "Zero", color: "var(--s3)", width: 1.75, pts: zc.grid.map((t, i) => [t, zc.zero[i] * 100]) },
        { name: "6-month forward", color: "var(--s2)", width: 1.75, pts: zc.grid.map((t) => [t, forwardRate(zc, t - 0.5, t) * 100]) },
      ], xticks: [[0.5, "6M"], [2, "2Y"], [5, "5Y"], [10, "10Y"], [20, "20Y"], [30, "30Y"]], xfmt: (t) => `${t} years`, yfmt: (v) => fx(v, 2) + "%",
        snapXs: zc.grid, label: `Par, zero and forward Treasury curves, ${set.label}`, height: 280 });
    }
    fillTable($("#fw-table"), ["Forward", "Rate", "Compare with", "What it says"],
      KEY_FWD.map(([n, a, b, say]) => [n, fx(forwardRate(zc, a, b) * 100, 2) + "%", `${b}-year par ${fx(parAt(set.years, set.y, b) * 100, 2)}%`, say]), 1);
    $("#fw-table").querySelectorAll("tr").forEach((tr) => { tr.lastChild.className = ""; });
    const repo = parAt(set.years, set.y, 0.25), rows = [2, 3, 5, 7, 10, 20, 30].map((M) => carryRoll(set.years, set.y, M, repo));
    fillTable($("#cr-table"), ["Tenor", "Yield", "Carry", "Roll-down", "One year", "Duration", "Breakeven"],
      rows.map((r) => [r.M + "Y", fx(r.coupon * 100, 2) + "%", pct(r.carry, 2), pct(r.roll, 2), pct(r.total, 2), fx(r.durH, 1), bp(r.breakevenBp)]));
    renderBreakevenBars(rows);
    const best = rows.reduce((a, b) => (b.breakevenBp > a.breakevenBp ? b : a)), lng = rows[rows.length - 1], neg = rows.filter((r) => r.breakevenBp < 0);
    $("#cr-out").textContent = `On the ${set.label} curve a financed ${best.M}-year earns ${pct(best.total, 2)} over a year and can absorb a ${Math.round(best.breakevenBp)}bp rise; the 30-year earns ${pct(lng.total, 2)} and absorbs ${Math.round(lng.breakevenBp)}bp. `
      + (neg.length ? `Negative breakevens (${neg.map((r) => r.M + "Y").join(", ")}) lose money even if yields do not move: the bill pays more than the coupon.` : "Per unit of risk, carry is richest where the breakeven is largest.");
  }
  function renderBreakevenBars(rows) {
    const box = $("#cr-chart");
    if (!box || !box.clientWidth) return;
    const W = boxWidth(box), rowH = 30, top = 6, labelW = 40, padR = 54, Hh = top + rows.length * rowH + 22;
    const vals = rows.map((r) => r.breakevenBp), ticks = niceTicks(Math.min(0, ...vals), Math.max(0, ...vals), 4), x0 = ticks[0], x1 = ticks[ticks.length - 1];
    const sx = (v) => labelW + ((v - x0) / (x1 - x0 || 1)) * (W - labelW - padR);
    box.replaceChildren();
    const s = svg("svg", { viewBox: `0 0 ${W} ${Hh}`, width: W, height: Hh, role: "img", "aria-label": "Yield rise each tenor can absorb in a year, in basis points" }, box);
    ticks.forEach((t) => { svg("line", { x1: sx(t), x2: sx(t), y1: top, y2: Hh - 20, class: t === 0 ? "baseline" : "gridline" }, s); text(s, sx(t), Hh - 5, fx(t, 0), "ax", "middle"); });
    rows.forEach((r, i) => {
      const y = top + i * rowH + 6, v = r.breakevenBp;
      text(s, 0, y + 12, r.M + "Y", "cat", "start");
      svg("path", { d: hbar(sx(0), sx(v), y, 16), fill: v >= 0 ? "var(--s1)" : "var(--red)" }, s);
      text(s, v >= 0 ? sx(v) + 6 : sx(v) - 6, y + 12, `${Math.round(v)}bp`, "lbl-strong", v >= 0 ? "start" : "end");
      const hit = svg("rect", { x: 0, y: y - 6, width: W, height: rowH, class: "hit", tabindex: "0", "aria-label": `${r.M}-year: absorbs ${Math.round(v)} basis points` }, s);
      bindTip(hit, () => [[`${Math.round(v)}bp`, `${r.M}-year · carry ${pct(r.carry, 2)}, roll-down ${pct(r.roll, 2)}, duration ${fx(r.durH, 1)}`]]);
    });
  }

  /* =====================================================================================
     HEDGES: playbooks and the futures calculator
     ===================================================================================== */
  function buildPlaybooks() {
    const g = $("#pb-grid");
    PLAYBOOKS.forEach((p) => {
      const c = h("article", "pb");
      c.id = p.id;
      const sec = (title, node) => { const d = h("div"); d.append(h("h4", null, title), node); return d; };
      const ul = (xs) => { const u = h("ul"); xs.forEach((x) => u.append(h("li", null, x))); return u; };
      c.append(h("span", "tagline", p.tag), h("h3", null, p.t), sec("Early signals", ul(p.sig)), sec("What usually moves", h("p", null, p.moves)),
        sec("First moves", ul(p.first)), sec("Avoid", h("p", null, p.avoid)), sec("All-clear", h("p", null, p.clear)));
      const eps = h("div", "eps");
      p.ep.forEach((k) => { const e = EPISODES.find((x) => x.key === k); if (!e) return; const a = h("a", null, e.name); a.href = "#ep-" + k; eps.append(a); });
      c.append(sec("Built from", eps));
      g.append(c);
    });
  }
  let fuEq = "MNQ", fuRt = "UB", fuTouched = { ndx: false, beta: false };
  const EQ_MULT = { NQ: 20, MNQ: 2 };
  function buildFutures() {
    const seg = $("#fu-rt");
    Object.keys(FUT).forEach((k) => {
      const b = h("button", null, FUT[k].name);
      b.type = "button"; b.dataset.v = k;
      b.addEventListener("click", () => { fuRt = k; updateFutures(); });
      seg.append(b);
    });
    $("#fu-eq").querySelectorAll("button").forEach((b) => b.addEventListener("click", () => { fuEq = b.dataset.v; updateFutures(); }));
    ["#fu-book", "#fu-beta", "#fu-ndx", "#fu-share", "#fu-tlt"].forEach((id) => $(id).addEventListener("input", () => { if (id === "#fu-ndx") fuTouched.ndx = true; if (id === "#fu-beta") fuTouched.beta = true; updateFutures(); }));
  }
  function futuresDefaults() {
    const lat = LIVE.macro && LIVE.macro.latest;
    if (!fuTouched.ndx && lat && fin(lat.NASDAQ100)) $("#fu-ndx").value = Math.round(lat.NASDAQ100);
    const ex = LIVE.report && Array.isArray(LIVE.report.exposures) ? LIVE.report.exposures : null;
    if (!fuTouched.beta && ex) {
      let w = 0, b = 0;
      ex.forEach((e) => { if (BOOK[e.index] && fin(e.market)) { w += BOOK[e.index]; b += BOOK[e.index] * e.market; } });
      if (w > 0.5) $("#fu-beta").value = (b / w).toFixed(2);
    }
  }
  function updateFutures() {
    const book = readNum($("#fu-book"), 1e4, 1e10, 1e6), beta = readNum($("#fu-beta"), 0, 3, 1.25), ndx = readNum($("#fu-ndx"), 1000, 2e5, 28959);
    const share = Number($("#fu-share").value) / 100, tlt = Number($("#fu-tlt").value) / 100;
    $("#fu-share-o").textContent = Math.round(share * 100) + "%";
    $("#fu-tlt-o").textContent = Math.round(tlt * 100) + "%";
    $("#fu-eq").querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", b.dataset.v === fuEq ? "true" : "false"));
    $("#fu-rt").querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", b.dataset.v === fuRt ? "true" : "false"));
    const sets = curveSets(), set = sets.find((x) => x.live) || sets.find((x) => x.label === "Oct 23");
    const betaUsd = book * beta * share, perContract = ndx * EQ_MULT[fuEq], nEq = betaUsd / perContract;
    const notional = book * tlt, dv = notional * TLT_DUR * 1e-4, all = Object.keys(FUT).map((k) => futuresDV01(set.years, set.y, k)), f = all.find((x) => x.key === fuRt), nRt = dv / f.dv01;
    $("#fu-bd").textContent = money(betaUsd);
    $("#fu-n-eq").textContent = `${Math.round(nEq).toLocaleString("en-US")} ${fuEq}`;
    $("#fu-dv").textContent = money(dv) + "/bp";
    $("#fu-n-rt").textContent = `${Math.round(nRt).toLocaleString("en-US")} ${fuRt}`;
    const eqRes = betaUsd - Math.round(nEq) * perContract, rtRes = dv - Math.round(nRt) * f.dv01;
    const resTxt = Math.abs(eqRes) < 1 ? "exactly" : eqRes > 0 ? `leaving ${money(eqRes)} of beta unhedged from rounding` : `over-hedging by ${money(-eqRes)} from rounding`;
    $("#fu-out").textContent = `Selling ${Math.round(nEq)} ${fuEq} at ${money(perContract)} of notional each takes ${Math.round(share * 100)}% of the book's beta off, ${resTxt}. `
      + (tlt > 0 ? `Buying ${Math.round(nRt)} ${fuRt} at about ${money(f.dv01)} per basis point matches the ${money(dv)} DV01 of ${money(notional)} in TLT to within ${money(Math.abs(rtRes))}.` : "No rates hedge selected.")
      + (nEq > 0 && nEq < 0.5 ? " The hedge is smaller than one contract: use MNQ or skip it." : "");
    fillTable($("#fu-table"), ["Contract", "Cheapest to deliver", "Conversion factor", "DV01 per contract", "Contracts for this hedge"],
      all.map((x) => [x.name, `${fx(x.ctdYears, 1)} years, ${fx(x.coupon * 100, 2)}% coupon`, fx(x.cf, 4), money(x.dv01, 2), fx(dv / x.dv01, 1)]), 2);
    const lat = LIVE.macro && LIVE.macro.latest;
    $("#fu-src").textContent = `Index level: ${lat && fin(lat.NASDAQ100) && !fuTouched.ndx ? "FRED, " + niceDate(lat.NASDAQ100_date || lat.as_of) : "Oct 19 close (FRED) or your input"}. Beta: ${LIVE.report && !fuTouched.beta ? "the engine's weighted market betas" : "an assumption until the engine's betas arrive"}. Futures DV01 from the ${set.label} curve: CTD DV01 over the conversion factor, assuming the shortest deliverable. Approximate; check the exchange's figure before trading.`;
  }

  /* =====================================================================================
     APPENDIX
     ===================================================================================== */
  function buildGlossary() {
    const isLetter = (g) => /^[A-Za-z]/.test(g.term);
    const list = GLOSSARY.slice().sort((a, b) => (isLetter(a) - isLetter(b)) || a.term.localeCompare(b.term, "en", { sensitivity: "base" }));
    const box = $("#gloss"), az = $("#gl-az");
    let letter = "";
    list.forEach((g) => {
      const first = g.term[0].toUpperCase(), L0 = /[A-Z]/.test(first) ? first : "#";
      if (L0 !== letter) {
        letter = L0;
        const lh = h("h3", "letter", L0 === "#" ? "Symbols and numbers" : L0);
        lh.id = "gl-" + (L0 === "#" ? "sym" : L0.toLowerCase());
        box.append(lh);
        const a = h("a", null, L0);
        a.href = "#" + lh.id;
        az.append(a);
      }
      const dl = h("dl", "entry");
      dl.id = "g-" + g.id;
      const dt = h("dt", null, g.term);
      if (g.alt && g.alt.length) dt.append(h("span", "alt", g.alt.join(", ")));
      const dd = h("dd", null, g.def);
      if (g.why) dd.append(h("span", "why", g.why));
      if (g.at && document.getElementById(g.at)) { const a = h("a", "used", "Where it is used →"); a.href = "#" + g.at; dd.append(document.createTextNode(" "), a); }
      dl.append(dt, dd);
      box.append(dl);
    });
    $("#gl-sub").textContent = `${GLOSSARY.length} terms. Terms with a dotted underline anywhere on the site open their entry here.`;
  }
  function buildMethods() {
    const box = $("#methods");
    METHODS.forEach((g) => {
      const grp = h("div", "mgroup");
      grp.append(h("h3", null, g.group.replace(/\s*\(v\d+\.\d+\)\s*$/, "")));
      g.items.forEach((m) => {
        const row = h("div", "method"), f = h("div", "formula"), say = h("p", "say");
        f.innerHTML = m.f;          // static, authored markup from reference.js
        say.innerHTML = m.say;
        row.append(h("span", "mname", m.name), f, say, h("span", "where", m.where));
        grp.append(row);
      });
      box.append(grp);
    });
  }
  // stable deep links: a question's id comes from its words, so adding questions never renumbers old links
  const faqId = (f) => "faq-" + slug(f.q).slice(0, 60).replace(/-+$/, "");
  function buildFAQ() {
    const box = $("#faq");
    [...new Set(FAQ.map((f) => f.g))].forEach((g) => {
      box.append(h("h3", null, g));
      FAQ.filter((f) => f.g === g).forEach((f) => {
        const d = h("details");
        d.id = faqId(f);
        d.append(h("summary", null, f.q), h("p", null, f.a));
        box.append(d);
      });
    });
    $("#faq-title").parentElement.querySelector(".prose").textContent = `${FAQ.length} questions, from plain English for a newcomer to the ones a portfolio manager, a risk officer or an interviewer would ask, answered straight.`;
  }
  function buildModelRisk() {
    fillTable($("#mr-table"), ["Model", "Assumes", "Breaks when", "What the desk does"], MODEL_RISK, 4);
  }
  function buildDict() {
    const cov = LIVE.macro && LIVE.macro.coverage ? LIVE.macro.coverage : null;
    const covText = (id) => {
      const key = id.split(/[\s,…]+/)[0], c = cov && cov[key];
      return c ? `${niceDate(c.first)} to ${niceDate(c.last)}` : cov ? "not in the last run" : "after the first run";
    };
    // the coverage column exists only once a daily run has reported it
    if (cov) fillTable($("#dict-fred"), ["Series", "What it is", "Used for", "Coverage in the last run"], FRED_DICT.map((r) => [...r, covText(r[0])]), 4);
    else fillTable($("#dict-fred"), ["Series", "What it is", "Used for"], FRED_DICT.map((r) => r.slice(0, 3)), 3);
    fillTable($("#dict-other"), ["Source", "What the engine reads", "Used for"], OTHER_DICT, 3);
    fillTable($("#dict-json"), ["File", "Fields the page reads"], JSON_DICT, 2);
  }
  let epKind = "All";
  function buildEpisodes() {
    const f = $("#ep-filters");
    f.replaceChildren();
    ["All", ...new Set(EPISODES.map((e) => e.kind))].forEach((k) => {
      const b = h("button", null, k);
      b.type = "button";
      b.setAttribute("aria-pressed", k === epKind ? "true" : "false");
      b.addEventListener("click", () => { epKind = k; buildEpisodes(); });
      f.append(b);
    });
    const g = $("#ep-grid");
    g.replaceChildren();
    const okEp = (e) => e && typeof e.key === "string" && fin(e.equity_return) && isoOk(e.peak) && isoOk(e.trough) && fin(e.days);
    const live = LIVE.macro && Array.isArray(LIVE.macro.episodes) ? Object.fromEntries(LIVE.macro.episodes.filter(okEp).map((e) => [e.key, e])) : {};
    if (live.current && epKind === "All") g.append(episodeCard({ key: "current", name: "The drawdown in progress", when: `${niceDate(live.current.peak)} to ${niceDate(live.current.trough)}`, kind: "Open", eq: "Nasdaq-100 from its one-year high", bonds: "See the live figures below", worked: "Read the signals board", lesson: "History rhymes; the atlas shows which episodes this one resembles." }, live.current));
    EPISODES.filter((e) => epKind === "All" || e.kind === epKind).forEach((e) => g.append(episodeCard(e, live[e.key])));
  }
  function episodeCard(e, lv) {
    const c = h("article", "ep");
    c.id = "ep-" + e.key;
    c.dataset.key = e.key;
    c.append(h("span", "kind", e.kind), h("h3", null, e.name), h("span", "when", e.when));
    const dl = h("dl");
    [["Stocks", e.eq], ["Bonds", e.bonds], ["What worked", e.worked]].forEach(([k, v]) => dl.append(h("dt", null, k), h("dd", null, v)));
    c.append(dl, h("p", "lesson", e.lesson));
    if (e.src) c.append(srcNode(e.src));
    if (lv) {
      const box = h("div", "livestats");
      const stat = (label, val) => { const d = h("div"); d.append(h("b", null, val), h("span", null, label)); box.append(d); };
      stat("Nasdaq-100", pct(lv.equity_return, 1));
      stat(lv.bond_series === "DGS30" ? "30-year bond" : "20-year bond", lv.bond_return == null ? "n/a" : pct(lv.bond_return, 1));
      stat("10-year yield", lv.d10_bp == null ? "n/a" : bp(lv.d10_bp));
      stat("VIX peak", lv.vix_max == null ? "n/a" : fx(lv.vix_max, 1));
      stat("Oil", lv.oil_return == null ? "n/a" : pct(lv.oil_return, 0));
      stat("Stock-bond corr", lv.corr == null ? "n/a" : sgn2(lv.corr));
      const cap = h("span", "src", `FRED, ${niceDate(lv.peak)} to ${niceDate(lv.trough)}, ${lv.days} days`);
      cap.style.gridColumn = "1 / -1";
      box.append(cap);
      c.append(box);
    }
    return c;
  }
  function buildReading() {
    const box = $("#reading");
    READING.forEach((g) => {
      const d = h("div"), ul = h("ul");
      d.append(h("h3", null, g.g));
      g.items.forEach(([title, url, why]) => {
        const li = h("li");
        if (url) { const a = h("a", null, title); a.href = url; li.append(a); } else li.append(document.createTextNode(title));
        li.append(h("span", null, why));
        ul.append(li);
      });
      d.append(ul);
      box.append(d);
    });
  }
  function buildChecklists() {
    const box = $("#checklists");
    CHECKLISTS.forEach((c) => {
      const card = h("article", "ck"), ol = h("ol");
      c.items.forEach((x) => ol.append(h("li", null, x)));
      card.append(h("h3", null, c.t), ol);
      box.append(card);
    });
  }
  function buildChangelog() { fillTable($("#changelog"), ["Version", "Date", "What changed"], CHANGELOG, 3); }

  /* ---------- numbers to know and worked examples: the page's own math, shown step by step ---------- */
  function vixNow() {
    const lv = LIVE.macro && LIVE.macro.rates && LIVE.macro.rates.levels && LIVE.macro.rates.levels.vix;
    return lv && fin(lv.value) && isoOk(lv.date) ? { v: lv.value, date: niceDate(lv.date) } : { v: STATIC_VOL.vix[0], date: STATIC_VOL.vix[1] };
  }
  function curveNowSet() { const sets = curveSets(); return sets.find((x) => x.live) || sets.find((x) => x.label === "Oct 23") || sets[sets.length - 1]; }
  function curveYield(tenor) { const set = curveNowSet(); return parAt(set.years, set.y, { "3M": 0.25, "2Y": 2, "10Y": 10, "30Y": 30 }[tenor]); }
  function examples() {
    const set = curveNowSet(), on = set.label, y = (t) => parAt(set.years, set.y, t), repo = y(0.25), out = [];
    const vxl = LIVE.macro && LIVE.macro.vol && LIVE.macro.vol.latest && LIVE.macro.vol.latest.ndx;
    const vxn = vxl && fin(vxl.implied) && isoOk(vxl.date) ? { v: vxl.implied, d: niceDate(vxl.date) } : { v: STATIC_VOL.vxn[0], d: STATIC_VOL.vxn[1] };
    const lat = LIVE.macro && LIVE.macro.latest;
    const ndx = lat && fin(lat.NASDAQ100) ? { v: lat.NASDAQ100, d: niceDate(lat.NASDAQ100_date || lat.as_of) } : { v: 28958.69, d: "Oct 22" };
    {
      const yy = y(10), dc = durCvx(yy, 10, yy), dv = dc.dur * 1e6 * 1e-4;
      out.push({ id: "dv01", q: "What is a basis point worth on $1 million of 10-year notes?", link: ["bc-title", "Bond calculator"],
        steps: [[`10-year par yield, ${on}`, fx(yy * 100, 2) + "%"], ["Modified duration of a par bond", fx(dc.dur, 2) + " years"], ["DV01 = duration × $1,000,000 × 0.0001", money(dv, 0)]],
        a: `About ${money(dv, 0)} per basis point, so a 10bp move is about ${money(Math.round(dv) * 10, 0)}.` });
    }
    {
      const yy = y(30), up = longBondReturn(yy, 100, TLT_DUR), dn = longBondReturn(yy, -100, TLT_DUR);
      out.push({ id: "tlt100", q: "What does a 100bp rise in long yields do to TLT?", link: ["hedge", "Hedge lab"],
        steps: [[`Duration alone: −${TLT_DUR} × 1%`, pct(-TLT_DUR / 100, 1)], [`Exact repricing of a TLT-like bond from ${fx(yy * 100, 2)}%`, pct(up, 2)], ["The same bond after a 100bp fall", pct(dn, 2)]],
        a: `About ${pct(up, 1)}. Convexity makes the loss smaller than duration alone says and the gain larger: ${pct(dn, 1)} for a 100bp fall.` });
    }
    {
      const f = futuresDV01(set.years, set.y, "ZN"), dv = 1e6 * TLT_DUR * 1e-4, n = dv / f.dv01;
      out.push({ id: "zn", q: "How many 10-year futures replace $1 million of TLT?", link: ["fut-title", "Futures hedge"],
        steps: [[`TLT DV01 = $1,000,000 × ${TLT_DUR} × 0.0001`, money(dv, 0)], [`ZN: cheapest to deliver ${fx(f.ctdYears, 1)} years, conversion factor ${fx(f.cf, 4)}`, money(f.dv01, 2) + " a contract"], ["Contracts = TLT DV01 ÷ ZN DV01", fx(n, 1)]],
        a: `About ${Math.round(n)} ZN contracts carry the rate risk of $1 million of TLT, for margin instead of cash.` });
    }
    {
      const usd = 1e6 * 1.15 * 0.5, per = ndx.v * 2, n = usd / per;
      out.push({ id: "mnq", q: "How many micro Nasdaq futures take half the beta off a $1 million book?", link: ["fut-title", "Futures hedge"],
        steps: [["Beta dollars = $1,000,000 × 1.15 beta × 50%", money(usd, 0)], [`One MNQ = Nasdaq-100 at ${Math.round(ndx.v).toLocaleString("en-US")} (${ndx.d}) × $2`, money(per, 0)], ["Contracts = beta dollars ÷ notional per contract", fx(n, 1)]],
        a: `Sell about ${Math.round(n)} MNQ; one NQ equals ten. Re-size when beta or the index moves.` });
    }
    {
      const v = (vxn.v + 3) / 100, T = 91 / 365, o = bs(100, 90, T, repo, 0.006, v, "put"), cost = o.price / 100;
      out.push({ id: "put90", q: "What does a 3-month 90% put on the Nasdaq-100 cost?", link: ["bs-title", "Option pricer"],
        steps: [[`VXN ${fx(vxn.v, 2)} (${vxn.d}) plus about 3 points of skew at a 10% out-of-the-money strike`, fx(v * 100, 1) + "%"], [`Black-Scholes, 91 days, rate ${fx(repo * 100, 2)}%, dividend yield 0.6%`, pctPlain(cost, 2) + " of spot"], ["Rolled four times a year", pctPlain(cost * 365 / 91, 1) + " a year"]],
        a: `About ${pctPlain(cost, 2)} of the position for three months, ${pctPlain(cost * 365 / 91, 1)} a year if rolled: why the desk reaches for put spreads when implied volatility is high.` });
    }
    {
      const c = carryRoll(set.years, set.y, 10, repo);
      out.push({ id: "carry10", q: "What does a financed 10-year earn in a year if the curve does not move?", link: ["fw-title", "Carry and roll-down"],
        steps: [[`Carry: ${fx(c.coupon * 100, 2)}% coupon minus the ${fx(repo * 100, 2)}% 3-month bill`, pct(c.carry, 2)], ["Roll-down as it ages into a 9-year", pct(c.roll, 2)], ["One year in total", pct(c.total, 2)], ["Yield rise that uses it up", bp(c.breakevenBp)]],
        a: `${pct(c.total, 2)} over the year, and the position survives a ${Math.round(c.breakevenBp)}bp rise in the 10-year yield.` });
    }
    {
      const c = carryRoll(set.years, set.y, 30, repo);
      out.push({ id: "carry30", q: "How far can the 30-year yield rise before a year of carry is gone?", link: ["fw-title", "Carry and roll-down"],
        steps: [[`Carry: ${fx(c.coupon * 100, 2)}% coupon minus ${fx(repo * 100, 2)}% financing`, pct(c.carry, 2)], ["Roll-down into the 29-year point", pct(c.roll, 2)], ["Duration after a year", fx(c.durH, 1) + " years"], ["Breakeven: the rise that zeroes the year, solved exactly", bp(c.breakevenBp)]],
        a: `Only about ${Math.round(c.breakevenBp)}bp: the long end carries little cushion for its risk${c.roll < 0 ? ", because the 20-year kink makes it roll up the curve instead of down" : ""}.` });
    }
    {
      const sig = 0.32, L = 1.5, need = L * sig * sig;
      out.push({ id: "kelly", q: "What edge would justify running a 32%-volatility book at 1.5x?", link: ["size", "Sizing lab"],
        steps: [["Kelly leverage = edge ÷ variance, so full Kelly needs edge = 1.5 × 0.32²", pctPlain(need, 1) + " a year"], ["Half Kelly needs twice that", pctPlain(need * 2, 1) + " a year"], ["Quarter Kelly needs four times", pctPlain(need * 4, 1) + " a year"]],
        a: `About ${pctPlain(need * 4, 0)} a year over cash at quarter Kelly. No forecast with a tested record clears that, so the risk limits, not the forecast, set the size.` });
    }
    return out;
  }
  function buildExamples() {
    const box = $("#examples"), list = examples();
    box.replaceChildren();
    list.forEach((x) => {
      const c = h("article", "wx"), ol = h("ol", "wx-steps"), a = h("a", "src", x.link[1] + " →");
      c.id = "wx-" + x.id;
      x.steps.forEach(([k, v]) => { const li = h("li"); li.append(h("span", null, k), h("b", null, v)); ol.append(li); });
      a.href = "#" + x.link[0];
      c.append(h("h3", null, x.q), ol, h("p", "wx-ans", x.a), a);
      box.append(c);
    });
    $("#wx-sub").textContent = `${list.length} questions the tools answer, worked step by step with the page's own math on the ${curveNowSet().label} curve.`;
  }
  function buildRules() {
    const box = $("#rules");
    box.replaceChildren();
    RULES.forEach((r) => {
      const c = h("article", "nk");
      c.id = "nk-" + slug(r.t);
      c.append(h("h3", null, r.t), h("p", null, r.r));
      let now = "";
      try { now = r.v ? r.v() : ""; } catch (e) { now = ""; }
      if (now) c.append(h("p", "nk-now", now));
      if (r.at) { const a = h("a", "src", "Where it is used →"); a.href = "#" + r.at; c.append(a); }
      box.append(c);
    });
  }

  /* =====================================================================================
     ENGINE: system status from data/status.json
     ===================================================================================== */
  function renderStatus(st) {
    const box = $("#status-body");
    const miss = missingFields(st, { generated_utc: "str", checks: "arr", files: "str" });
    if (miss.length) { errorState(box, "The status file is incomplete.", "Missing: " + miss.join(", ") + "."); return; }
    box.replaceChildren();
    const passed = st.checks.filter((c) => c.ok).length, when = String(st.generated_utc);
    const tiles = h("div", "tiles compact");
    tiles.append(tile("Last run", `${niceDate(when.slice(0, 10))}, ${when.slice(11, 16)} UTC`, st.commit ? `Commit ${st.commit}` : "Local run"),
      tile("Checks passed", `${passed} of ${st.checks.length}`, st.ok ? "Every check passed." : "Failures are listed below."));
    Object.entries(st.files).forEach(([name, f]) => {
      const age = f && f.cadence === "quarterly" ? "Quarterly SEC filings" : f && fin(f.weekdays_old) ? `${f.weekdays_old} weekday${f.weekdays_old === 1 ? "" : "s"} old` : "";
      tiles.append(tile(name, !f || !f.present ? "Missing" : f.valid === false ? "Invalid" : (niceDate(f.as_of) || "Present"), !f || !f.present ? "Not written by the last run." : f.valid === false ? String(f.error || "") : age));
    });
    const ul = h("ul", "checks");
    st.checks.forEach((c) => { const li = h("li", c.ok ? null : "fail"); li.append(document.createTextNode(c.name)); if (c.detail) li.append(h("span", null, String(c.detail))); ul.append(li); });
    box.append(tiles, ul);
    const chip = $("#chip-run");
    chip.querySelector(".dot").className = "dot " + (st.ok ? "good" : "warn");
    chip.lastElementChild.textContent = st.ok ? `Daily run ${st.checks.length} of ${st.checks.length} checks` : `Daily run ${passed} of ${st.checks.length} checks`;
  }

  /* =====================================================================================
     NAVIGATION: contents, glossary links, search, shortcuts, print
     ===================================================================================== */
  function buildTOCs() {
    VIEWS.forEach((v) => {
      const view = $("#view-" + v), heads = [...view.querySelectorAll(":scope > .section > .section-head h2[id]")];
      if (heads.length < 3 || view.querySelector(":scope > .toc")) return;
      const nav = h("nav", "toc");
      nav.setAttribute("aria-label", "On this desk");
      nav.append(h("span", "flabel", "On this desk"));
      heads.forEach((h2) => { const a = h("a", null, h2.textContent); a.href = "#" + h2.id; nav.append(a); });
      const after = view.querySelector(":scope > .start") || view.querySelector(":scope > .vhead, :scope > .hero");
      if (after) after.after(nav);
    });
  }
  const NO_LINK = "a, button, label, h1, h2, h3, h4, h5, h6, summary, svg, script, style, input, select, textarea, code, kbd, var, table, dt, .src, .eyebrow, .badge, .tip, .gloss, .methods, .term, .signals, #levels, .chart-title, .panel-title, .flabel, .tagline, .kind, .sig-state, .toc, .chips, .tchips, .sec, .readouts, .sentence";
  const LINKED = new Set();
  function linkTerms(only) {
    const entries = [];
    GLOSSARY.forEach((g) => [g.term, ...(g.alt || [])].forEach((t) => entries.push({ t, id: g.id, cs: (t.match(/[A-Z0-9]/g) || []).length >= 2 && t === t.toUpperCase() || /^[A-Z][a-z]?[A-Z]/.test(t) })));
    entries.sort((a, b) => b.t.length - a.t.length);
    const esc = (x) => x.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const mk = (list, flags) => (list.length ? new RegExp(`(^|[^\\w-])(${list.map((e) => esc(e.t)).join("|")})(?![\\w-])`, flags) : null);
    const reCS = mk(entries.filter((e) => e.cs), "g"), reCI = mk(entries.filter((e) => !e.cs), "gi");
    const byCS = new Map(entries.filter((e) => e.cs).map((e) => [e.t, e.id])), byCI = new Map(entries.filter((e) => !e.cs).map((e) => [e.t.toLowerCase(), e.id]));
    const defs = Object.fromEntries(GLOSSARY.map((g) => [g.id, g]));
    let made = 0;
    (only || VIEWS).forEach((v) => {
      if (LINKED.has(v)) return;
      LINKED.add(v);
      const root = $("#view-" + v), used = new Set();
      const flowing = (el) => { const d = getComputedStyle(el).display; return !/flex|grid/.test(d); };
      const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, { acceptNode: (n) => (n.nodeValue.trim().length > 2 && !n.parentElement.closest(NO_LINK) && flowing(n.parentElement) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT) });
      const queue = [];
      while (walker.nextNode()) queue.push(walker.currentNode);
      const next = (text) => {
        let best = null;
        [[reCS, byCS, false], [reCI, byCI, true]].forEach(([re, map, lower]) => {
          if (!re) return;
          re.lastIndex = 0;
          let m;
          while ((m = re.exec(text))) {
            const word = m[2], id = map.get(lower ? word.toLowerCase() : word), pos = m.index + m[1].length;
            if (id && !used.has(id)) { if (!best || pos < best.pos) best = { id, pos, word }; break; }
            re.lastIndex = pos + word.length;
          }
        });
        return best;
      };
      while (queue.length) {
        const node = queue.shift(), hit = next(node.nodeValue);
        if (!hit) continue;
        const mid = node.splitText(hit.pos), tail = mid.splitText(hit.word.length);
        const a = h("a", "term", hit.word);
        a.href = "#g-" + hit.id;
        bindTip(a, () => [[defs[hit.id].term, defs[hit.id].def]]);
        mid.replaceWith(a);
        used.add(hit.id);
        made++;
        queue.unshift(tail);
      }
    });
    return made;
  }

  const INDEX = [];
  function buildIndex() {
    const add = (title, sub, kind, target, keys = "") => INDEX.push({ title, sub, kind, target, t: title.toLowerCase(), hay: `${title} ${sub} ${keys}`.toLowerCase() });
    VIEWS.forEach((v) => { const h1 = $("#view-" + v).querySelector("h1"); add(TAB_NAME[v], h1 ? h1.textContent : "", "Desk", v); });
    document.querySelectorAll(".view .section-head h2[id]").forEach((h2) => {
      const view = h2.closest(".view").id.slice(5), head = h2.parentElement, eb = head.querySelector(".eyebrow");
      const isTool = eb && /tool/i.test(eb.textContent);
      add(h2.textContent, TAB_NAME[view] + (eb ? " · " + eb.textContent : ""), isTool ? "Tool" : "Section", h2.id, head.textContent);
    });
    GLOSSARY.forEach((g) => add(g.term, g.def, "Term", "g-" + g.id, (g.alt || []).join(" ")));
    SECS.forEach((x) => add(x.n, x.w, "Security", "sec-" + slug(x.n), `${x.acc} ${x.f} ${x.d.join(" ")} ${x.role}`));
    THESES.forEach((t) => add(t.t, t.stance, "Thesis", t.id, t.ex));
    LENSES.forEach((L) => add(L.n, L.idea, "Lens", "lens-" + slug(L.n), L.read));
    EPISODES.forEach((e) => add(e.name, `${e.when} · ${e.lesson}`, "Episode", "ep-" + e.key, `${e.kind} ${e.worked}`));
    PLAYBOOKS.forEach((p) => add(`${p.t} playbook`, p.moves, "Playbook", p.id, p.sig.join(" ")));
    FAQ.forEach((f) => add(f.q, f.a, "Question", faqId(f), f.g));
    RULES.forEach((r) => add(r.t, r.r, "Rule", "nk-" + slug(r.t)));
    examples().forEach((x) => add(x.q, x.a, "Example", "wx-" + x.id));
    MATRIX.forEach((m) => add(`${m.h} as a hedge`, m.note, "Hedge", "mx-title", m.sub));
    SIGNALS.forEach((sg) => add(`${sg.name} signal`, sg.rule, "Signal", "sig-" + sg.id));
  }
  const KIND_RANK = { Desk: 9, Tool: 8, Term: 7, Signal: 6, Playbook: 6, Section: 5, Thesis: 5, Rule: 5, Example: 5, Hedge: 4, Security: 4, Episode: 3, Question: 3, Lens: 2 };
  function searchIndex(q) {
    const terms = q.toLowerCase().split(/\s+/).filter(Boolean);
    if (!terms.length) return INDEX.filter((x) => x.kind === "Desk" || x.kind === "Tool");
    return INDEX.map((x) => {
      let sc = 0;
      for (const t of terms) { if (x.t.startsWith(t)) sc += 6; else if (new RegExp(`\\b${t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`).test(x.t)) sc += 5; else if (x.t.includes(t)) sc += 3; else if (x.hay.includes(t)) sc += 1; else return null; }
      return { x, sc: sc + (KIND_RANK[x.kind] || 0) * 0.05 };
    }).filter(Boolean).sort((a, b) => b.sc - a.sc).slice(0, 15).map((r) => r.x);
  }
  let palSel = 0, palItems = [], palReturn = null;
  function renderPalette() {
    const list = $("#palette-list"), q = $("#palette-q").value;
    palItems = searchIndex(q);
    // a query that reads as arithmetic is answered first, by the calculator
    const expr = q.trim().replace(/^=\s*/, "");
    if (expr && (/^=/.test(q.trim()) || (/[\d)]\s*[-+*/^×÷%]|^[a-z]+\(|^\$/i.test(expr) && /\d|\$/.test(expr)))) {
      try { const r = calcEval(expr, calcEnv(), {}); palItems.unshift({ title: `= ${calcFormat(r.value)}`, sub: `${expr} · open it in the calculator`, kind: "Math", target: "calc", expr }); } catch (e) { /* not arithmetic: search only */ }
    }
    palSel = Math.min(palSel, Math.max(0, palItems.length - 1));
    list.replaceChildren();
    if (!palItems.length) { list.append(h("li", "none", `Nothing matches "${q}". Try a ticker, a term like DV01, or a desk name.`)); $("#palette-q").removeAttribute("aria-activedescendant"); return; }
    palItems.forEach((x, i) => {
      const li = h("li");
      li.id = "pal-" + i;
      li.setAttribute("role", "option");
      li.setAttribute("aria-selected", i === palSel ? "true" : "false");
      li.append(h("b", null, x.title), h("small", null, x.sub.length > 110 ? x.sub.slice(0, 108) + "…" : x.sub), h("em", null, x.kind));
      li.addEventListener("mousemove", () => { if (palSel !== i) { palSel = i; mark(); } });
      li.addEventListener("click", () => go(x.target, x.expr));
      list.append(li);
    });
    mark();
  }
  function mark() {
    $("#palette-list").querySelectorAll("li[role=option]").forEach((li, i) => li.setAttribute("aria-selected", i === palSel ? "true" : "false"));
    const sel = $("#pal-" + palSel);
    if (sel) { sel.scrollIntoView({ block: "nearest" }); $("#palette-q").setAttribute("aria-activedescendant", sel.id); }
  }
  function openPalette() {
    if (!$("#keys").hidden) closeDialog($("#keys"));
    palReturn = document.activeElement;
    $("#palette").hidden = false;
    const q = $("#palette-q");
    q.value = "";
    palSel = 0;
    renderPalette();
    q.focus();
  }
  function closeDialog(el) {
    el.hidden = true;
    if (palReturn && document.contains(palReturn)) palReturn.focus();
    palReturn = null;
  }
  function go(target, expr) {
    closeDialog($("#palette"));
    if (target === "calc" && expr && $("#calc-in")) { $("#calc-in").value = expr; $("#calc-in").dispatchEvent(new Event("input")); }
    if (location.hash === "#" + target) show(target, true); else location.hash = target;
  }
  function wireNavigation() {
    $("#search-open").addEventListener("click", openPalette);
    $("#palette-q").addEventListener("input", () => { palSel = 0; renderPalette(); });
    $("#palette-q").addEventListener("keydown", (e) => {
      if (e.key === "ArrowDown") { e.preventDefault(); palSel = Math.min(palItems.length - 1, palSel + 1); mark(); }
      else if (e.key === "ArrowUp") { e.preventDefault(); palSel = Math.max(0, palSel - 1); mark(); }
      else if (e.key === "Enter") { e.preventDefault(); if (palItems[palSel]) go(palItems[palSel].target, palItems[palSel].expr); }
      else if (e.key === "Escape") { e.preventDefault(); closeDialog($("#palette")); }
      else if (e.key === "Tab") e.preventDefault();
    });
    ["#palette", "#keys"].forEach((id) => $(id).addEventListener("mousedown", (e) => { if (e.target === $(id)) closeDialog($(id)); }));
    $("#keys-close").addEventListener("click", () => closeDialog($("#keys")));
    $("#keys-open").addEventListener("click", () => { palReturn = document.activeElement; $("#keys").hidden = false; $("#keys-close").focus(); });
    $("#print-all").addEventListener("click", () => window.print());
    if (window.claude) $("#print-all").hidden = true;          // the artifact viewer cannot open a print dialog
    $("#skip").addEventListener("click", (e) => { e.preventDefault(); const t = $("#view-" + current + " h1") || $("#main"); t.setAttribute("tabindex", "-1"); t.focus(); });
    document.addEventListener("keydown", (e) => {
      const typing = e.target.closest && e.target.closest("input, textarea, select, [contenteditable]");
      if (e.key === "Escape") { if (!$("#palette").hidden) closeDialog($("#palette")); if (!$("#keys").hidden) closeDialog($("#keys")); return; }
      if ((e.key === "k" || e.key === "K") && (e.metaKey || e.ctrlKey)) { e.preventDefault(); openPalette(); return; }
      if (typing || e.metaKey || e.ctrlKey || e.altKey || !$("#palette").hidden) return;
      if (e.key === "/") { e.preventDefault(); openPalette(); }
      else if (e.key === "?") { e.preventDefault(); palReturn = document.activeElement; $("#keys").hidden = false; $("#keys-close").focus(); }
      else if (/^[1-6]$/.test(e.key) && $("#keys").hidden) goGroup(GROUP_ORDER[Number(e.key) - 1]);
      else if ((e.key === "m" || e.key === "M") && $("#keys").hidden) toggleMath();
    });
    $("#keys").addEventListener("keydown", (e) => { if (e.key === "Tab") { e.preventDefault(); $("#keys-close").focus(); } });
    // print every desk with every hard question answered, then put the page back exactly as it was
    let printState = null;
    window.addEventListener("beforeprint", () => {
      if (printState) return;
      lazyFlushAll();
      const shut = [...document.querySelectorAll(".faq details:not([open])")];
      printState = { hidden: VIEWS.map((v) => $("#view-" + v).hidden), shut };
      document.body.classList.add("printing");
      shut.forEach((d) => { d.open = true; });
      VIEWS.forEach((v) => { $("#view-" + v).hidden = false; });
      VIEWS.forEach((v) => guard("Print " + v, RENDER[v]));
    });
    window.addEventListener("afterprint", () => {
      document.body.classList.remove("printing");
      if (printState) {
        VIEWS.forEach((v, i) => { $("#view-" + v).hidden = printState.hidden[i]; });
        printState.shut.forEach((d) => { d.open = false; });
      }
      printState = null;
      if (current) guard(TAB_NAME[current], RENDER[current]);
    });
  }

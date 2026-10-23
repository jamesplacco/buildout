  /* =====================================================================================
     wisdom.js (v0.5): Swans (fat tails, the atlas, Taleb's toolkit, the compound-growth test)
     and Legends (twenty lenses on today's data, and what most desks skip)
     ===================================================================================== */

  /* ============================== SWANS ============================== */
  function tailRows(T) {
    return T.rows.flatMap((r) => [
      { label: `${r.k}σ, observed`, v: r.obs, lbl: String(r.obs), color: "var(--bad)", strong: true, tip: () => [[`${r.obs} months`, `down ${r.k} sigma or more since 1871`]] },
      { label: `${r.k}σ, normal model`, v: r.exp, lbl: r.exp >= 0.1 ? fx(r.exp, 1) : r.exp.toExponential(1).replace("e-", "e−"), color: "var(--muted)", tip: () => [[r.exp >= 0.1 ? fx(r.exp, 1) : r.exp.toExponential(2), `expected by a normal model: once every ${r.every >= 1e6 ? fx(r.every / 1e6, 1) + " million" : Math.round(r.every).toLocaleString("en-US")} years`]] }]);
  }
  function renderTailsDesk() {
    const F = readF(), T = F.tails;
    barsH($("#sw-tails"), tailRows(T), { log: true, rowH: 24, label: "Down months beyond 3 to 6 standard deviations: observed against a normal model" });
  }
  let tailWired = false;
  function buildSwans() {
    renderSwansStatic();
    if (!tailWired) {
      tailWired = true;
      ["#th-p", "#th-crash", "#th-norm", "#th-cost", "#th-mult"].forEach((id) => { const el = $(id); if (el) el.addEventListener("input", () => guard("Tail-hedge lab", updateTailLab, $("#th-chart"))); });
    }
    guard("Tail-hedge lab", () => updateTailLab(true), $("#th-chart"));
  }
  function renderSwansStatic() {
    const F = readF(), T = F.tails, six = T.rows.find((r) => r.k === 6), tiles = $("#sw-tail-tiles");
    if (tiles) tiles.replaceChildren(
      tile("Six-sigma down months", String(six.obs), `A normal model expects one every ${fx(six.every / 1e6, 1)} million years.`),
      tile("Tail index (Hill)", fx(T.alpha, 2), "Hill estimate on the largest 5% of all months. Moments of order α and above do not exist: at 2.15 the variance barely does. The labs use the largest 5% of losses only and get about 3.8; both say kurtosis is unreliable. A normal curve has no limit."),
      tile("Monthly volatility", fx(T.sigma * 100, 2) + "%", `${T.months.toLocaleString("en-US")} months since 1871.`));
    const w = $("#sw-worst");
    if (w) {
      const ul = h("ul", "facts");
      T.worst.forEach((x) => { const li = h("li"); li.append(h("strong", null, x.m), document.createTextNode(`: ${sPct(Math.expm1(x.r), 1)} in a month, ${fx(x.s, 1)} sigma.`)); ul.append(li); });
      w.replaceChildren(h("p", "panel-title", "The five worst months"), ul);
    }
    const g = $("#sw-grid");
    if (g) {
      g.replaceChildren(...SWANS.map((s) => {
        const c = h("article", "card");
        c.id = s.id;
        c.append(h("span", "tag", s.kind), h("h3", null, s.n));
        const p = h("p", null, s.ev + " ");
        if (s.src) p.append(srcLink(s.src));
        const dl = h("dl");
        [["First hit", s.hit], ["Pays", s.pays], ["Fails", s.fails], ["Cost to carry", s.cost]].forEach(([k, v]) => dl.append(h("dt", null, k), h("dd", null, v)));
        c.append(p, dl);
        return c;
      }));
    }
    const tg = $("#taleb-grid");
    if (tg) tg.replaceChildren(...TALEB.map((t) => { const c = h("article", "card"); c.append(h("h3", null, t.n), h("p", null, t.t)); const r = h("p"); r.append(h("strong", null, "Rule: "), document.createTextNode(t.rule)); c.append(r); return c; }));
  }
  function tailState() {
    const n = (id) => Number($(id).value);
    return { p: n("#th-p"), crash: n("#th-crash"), norm: n("#th-norm"), cost: n("#th-cost"), mult: n("#th-mult") };
  }
  function tailNumbers(st, cost) {
    const scen = [[st.p, st.crash], [1 - st.p, st.norm]];
    const un = hedgeCagr(scen, 0, {}), wi = hedgeCagr(scen, cost, { 0: st.mult * cost });
    const meanUn = st.p * st.crash + (1 - st.p) * st.norm, meanWi = meanUn - cost + st.p * st.mult * cost;
    return { un, wi, meanUn, meanWi };
  }
  function updateTailLab(noDraw) {
    const st = tailState();
    $("#th-p-o").textContent = pct(st.p, 0, false);
    $("#th-crash-o").textContent = pct(st.crash, 0);
    $("#th-norm-o").textContent = pct(st.norm, 1);
    $("#th-cost-o").textContent = pct(st.cost, 2, false);
    $("#th-mult-o").textContent = fx(st.mult, 1) + "x";
    const N = tailNumbers(st, st.cost);
    // the payoff multiple at which the hedge stops raising compound growth
    let lo = 0, hi = 200;
    for (let i = 0; i < 60; i++) { const mid = (lo + hi) / 2; if (tailNumbers({ ...st, mult: mid }, st.cost).wi > N.un) hi = mid; else lo = mid; }
    const be = st.cost > 0 ? hi : NaN;
    $("#th-out").replaceChildren(roEl("Compound growth, unhedged", sPct(N.un, 2)), roEl("Compound growth, hedged", sPct(N.wi, 2), true), roEl("Average return, unhedged", sPct(N.meanUn, 2)), roEl("Average return, hedged", sPct(N.meanWi, 2)));
    const read = $("#th-read"), gain = N.wi - N.un;
    read.className = "sentence " + (gain > 0 ? "ok" : "warn");
    read.textContent = gain > 0
      ? `The hedge raises compound growth by ${fx(gain * 100, 2)} points a year${N.meanWi < N.meanUn ? `, even though it lowers the average return by ${fx((N.meanUn - N.meanWi) * 100, 2)}: it shrinks the losses compounding punishes most` : ""}. It keeps paying for itself while the crash payoff is above ${fx(be, 1)} times its cost.`
      : `This hedge lowers compound growth by ${fx(-gain * 100, 2)} points a year: at ${fx(st.mult, 1)} times its cost it does not pay enough in the crash. It needs about ${fin(be) ? fx(be, 1) : "n/a"} times to break even.`;
    if (noDraw !== true || $("#th-chart").clientWidth) drawTailLab(st);
  }
  function drawTailLab(st) {
    const box = $("#th-chart");
    if (!box || !box.clientWidth) return;
    const costs = Array.from({ length: 41 }, (_, i) => i * 0.00125), base = tailNumbers(st, 0).un;
    xyChart(box, {
      height: 220, label: "Compound growth against the yearly hedge budget",
      series: [{ name: "Hedged", color: "var(--s1)", pts: costs.map((c) => [c, tailNumbers(st, c).wi * 100]) }, { name: "Unhedged", color: "var(--muted)", pts: costs.map((c) => [c, base * 100]) }],
      xticks: [0, 0.01, 0.02, 0.03, 0.04, 0.05].map((c) => [c, pct(c, 0, false)]), yfmt: (v) => fx(v, 1) + "%", xfmt: (x) => "budget " + pct(x, 2, false),
      vmarks: [{ x: st.cost, label: "yours" }],
    });
  }

  /* ============================== LEGENDS ============================== */
  let lgGroup = "All";
  function trendRead() {
    const mv = liveMove("ndx");
    const pts = mv && mv.spark ? seriesPts(mv.spark) : [];
    if (pts.length < 200) return null;
    const last = pts[pts.length - 1][1], avg = pts.slice(-200).reduce((s, p) => s + p[1], 0) / 200;
    return { last, avg, above: last > avg, date: dateLabel(pts[pts.length - 1][0]) };
  }
  function lensRead(lens) {
    const I = inputs(), F = readF(), cape = 40.9;
    const stages = FUND.rows.filter((r) => ["MSFT", "GOOGL", "AMZN", "META", "ORCL"].includes(r.t));
    const spec = stages.filter((r) => r.stage !== "hedge").map((r) => r.t), g = fundRow("GOOGL");
    switch (lens) {
      case "liquidity": return I.real.v >= 2.5 || I.funding.v > 0 ? ["off", `Real yields at ${pctPts(I.real.v)} are restrictive and the Fed is hiking: liquidity is a headwind. His rule: cut gross and wait for the turn.`] : ["on", "Liquidity is easing: the setup he sizes up for."];
      case "valuation": return ["off", `A CAPE of ${fx(cape, 1)} is in the top decile, where ten-year real returns averaged ${sPct(F.cape.rows[9].f, 1)} a year. The margin of safety is thin.`];
      case "invert": return ["mid", "Invert: the book dies if inflation stays above the line while AI financing cracks. Every hedge on the board answers that pre-mortem."];
      case "funding": return I.funding.v > 0 ? ["off", `Repo trades ${bp(I.funding.v)} over reserves: funding is tight. Match every hedge's liquidity to its capital.`] : ["mid", `Funding is ample (SOFR ${bp(I.funding.v)} against reserves), but the reverse repo buffer is gone: the next drain hits reserves.`];
      case "regime": return I.infl.avg36 >= I.lineAt ? ["off", "Rising inflation with steady growth: commodities, gold and inflation-linked bonds work; nominal bonds and long-duration equity suffer."] : ["mid", "Inflation is below the line: the balanced mix works again."];
      case "reflexivity": return ["mid", `The loop still runs upward: marks are ${pct0(g.nonop_share)} of Alphabet's pre-tax income and the build eats ${pct0(I.capexTTM / I.ocfTTM)} of cash flow. Reflexive loops reverse harder than they rise.`];
      case "pendulum": return I.hy.v < 4 && I.vix.v < 20 ? ["off", `High-yield spreads at ${pctPts(I.hy.v)} and a VIX of ${fx(I.vix.v, 1)}: the pendulum sits on the greed side, while CCC at ${pctPts(I.ccc.v)} says the bottom is already cracking.`] : ["mid", "Fear is in the price: the pendulum is swinging back."];
      case "trend": { const t = trendRead(); return t ? (t.above ? ["on", `The Nasdaq-100 (${fx(t.last, 0)}) is above its 200-day average (${fx(t.avg, 0)}): the trend says stay in.`] : ["off", `The Nasdaq-100 (${fx(t.last, 0)}) is below its 200-day average (${fx(t.avg, 0)}): play defense.`]) : ["mid", "The 200-day average comes with the daily run; the snapshot has no index history."]; }
      case "edge": return ["mid", "The engine's backtest Sharpe ratios are deflated for the number of trials; nothing here trades on an edge that has not survived walk-forward testing."];
      case "kelly": return ["mid", "Size at a quarter of Kelly on shrunk return estimates. The Journal's calculator flags any bet above it, and refuses a bet with negative expectancy."];
      case "fragility": return ["off", `Fat tails (tail index ${fx(F.tails.alpha, 2)}), a positive stock-bond correlation and a debt-funded build: fragile. Own convexity; never size for ruin.`];
      case "haven": return I.vix.v < 20 ? ["mid", `VIX at ${fx(I.vix.v, 1)}: protection is still affordable. The Swans lab shows when a hedge raises compound growth.`] : ["off", "Protection is expensive now: it should already be owned."];
      case "sitting": return ["mid", "Let the winners run inside their trim bands; the hedges, not the trading, carry the defense."];
      case "cycle": return ["off", `Euphoria markers: a CAPE of ${fx(cape, 1)}, earnings padded by marks, special-purpose vehicles at 90% loan to value.`];
      case "lender": return I.funding.v <= 0 ? ["on", "Funding is ample: a selloff today would not start as a funding crisis."] : ["off", "Funding is tight: Bagehot's panic needs a lender of last resort."];
      case "minsky": return [spec.length >= 2 ? "off" : "mid", `${spec.length} of 5 builders (${spec.join(", ")}) are past hedge finance, and CoreWeave sits at the Ponzi edge: the drift Minsky described.`];
      case "beauty": return ["mid", "Price what others will be forced to do, not what they think: the fourth-order chains on the Decide desk."];
      case "herd": return ["off", "The AI trade is the index. When everyone owns it, the exit is narrow."];
      case "calibration": return ["mid", "Score forecasts: the Journal's Brier score and calibration chart."];
      case "ooda": return ["mid", "Signals observe, the system map orients, Decide decides, the Journal reviews. The loop is the edge."];
      default: return ["mid", ""];
    }
  }
  const STANCE_WORD = { on: "Supportive", mid: "Neutral", off: "Defensive" };
  function buildLegends() {
    const f = $("#lg-filter");
    if (f && !f.childNodes.length) {
      f.classList.add("seg");
      f.append(h("span", "flabel", "Show"));
      ["All", "Investors", "Thinkers", "Risk and tails"].forEach((g) => {
        const b = h("button", null, g);
        b.type = "button"; b.dataset.g = g;
        b.addEventListener("click", () => { lgGroup = g; renderLegends(); });
        f.append(b);
      });
    }
    renderLegends();
    const ov = $("#ov-grid");
    if (ov) ov.replaceChildren(...OVERLOOKED.map((o) => { const c = h("article", "card"); c.append(h("h3", null, o.n), h("p", null, o.t)); const a = h("a", "src", "Open " + (TAB_NAME[o.at] || linkLabel5(o.at) || "the desk") + " →"); a.href = "#" + o.at; c.append(a); return c; }));
  }
  function renderLegends() {
    const reads = LEGENDS.map((l) => ({ l, r: lensRead(l.lens) }));
    const n = { on: 0, mid: 0, off: 0 };
    reads.forEach(({ r }) => { n[r[0]]++; });
    const tally = $("#lg-tally");
    if (tally) {
      tally.replaceChildren();
      ["off", "mid", "on"].forEach((k) => { if (!n[k]) return; const s = h("span", k, `${n[k]} ${STANCE_WORD[k].toLowerCase()}`); s.style.flex = String(n[k]); tally.append(s); });
      tally.setAttribute("aria-label", `Council vote: ${n.off} defensive, ${n.mid} neutral, ${n.on} supportive`);
    }
    const sub = $("#cv-sub");
    if (sub) sub.textContent = `${n.off} of ${LEGENDS.length} lenses read today's data as defensive, ${n.mid} neutral and ${n.on} supportive. The vote is not a signal on its own: it shows where the desk's rules come from.`;
    $("#lg-filter").querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", b.dataset.g === lgGroup ? "true" : "false"));
    const grid = $("#lg-grid");
    grid.replaceChildren(...reads.filter(({ l }) => lgGroup === "All" || l.g === lgGroup).map(({ l, r }) => {
      const c = h("article", "card");
      c.id = l.id;
      c.append(h("span", "tag", l.g), h("h3", null, l.n), h("span", "jr-note", l.who), h("p", null, l.idea));
      if (l.quote) { const q = h("blockquote", "lg-quote", "“" + l.quote + "”"); c.append(q); }
      const rule = h("p");
      rule.append(h("strong", null, "Rule on this desk: "), document.createTextNode(l.rule));
      const now = h("p");
      now.append(h("span", "stance " + r[0], STANCE_WORD[r[0]]), document.createTextNode(" " + r[1]));
      c.append(rule, now);
      const src = h("p", "jr-note");
      if (l.srcUrl) { const a = h("a", null, l.src); a.href = l.srcUrl; src.append(a); } else src.textContent = l.src;
      c.append(src);
      return c;
    }));
  }

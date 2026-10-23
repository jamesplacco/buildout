  /* =====================================================================================
     games.js (v0.7): the Games desk (who else is choosing, and what their best response does to the book)
     and the fill-quality lab on the market-making desk.
     ===================================================================================== */
  const GM = { p: 40, wacc: 9, orcl: 2, entrant: false,
    crowd: 400, adv: 150, vol: 2.2, Y: 0.8, cost: 30, edge: 1.0, sdPub: 2.0, sdPriv: 1.0,
    sv: 8, su: 600, order: 250, preset: "capex", custom: null, ladder: null };
  const CAPEX_SEATS = [["MSFT", 6.0], ["GOOGL", 6.0], ["AMZN", 5.0], ["META", 5.5], ["ORCL", 5.0]];
  function capexInputs() {
    const rows = CAPEX_SEATS.map(([t, life]) => {
      const r = FUND.rows.find((x) => x.t === t) || {};
      const lifeUsed = r.depr && fin(r.depr.stated_life) ? r.depr.stated_life : life;
      const wacc = GM.wacc / 100 + (t === "ORCL" ? GM.orcl / 100 : 0);
      return { t, name: r.name || t, capex: r.capex, life: lifeUsed, cost: 1 / lifeUsed + wacc, q_end: r.quarter_end, refreshed: !!r.refreshed };
    });
    return rows.every((r) => fin(r.capex)) ? rows : null;
  }
  function renderCapexGame() {
    const box = $("#gt-capex-table");
    if (!box) return;
    const rows = capexInputs();
    if (!rows) { box.replaceChildren(h("p", "hint", "Capex filings are unavailable; the game needs all five builders.")); return; }
    const g = capexGame(rows.map((r) => r.capex), rows.map((r) => r.cost), GM.p / 100);
    const d = capexDilemma(g.calibration.a, g.calibration.b, rows.reduce((s, r) => s + r.cost, 0) / rows.length, rows.length);
    const ent = g.with_entrant;
    box.replaceChildren(tableBlock(["Builder", "Capex, last 12 months", "Cost of $1 of capacity a year", "Model capex at equilibrium", GM.entrant ? "With a sixth builder" : "Model profit a year"],
      rows.map((r, i) => [`${r.name}${r.refreshed ? " (new filing)" : ""}`, B$(r.capex), `${pct0(r.cost)} (1/${fx(r.life, 1)} + ${fx((r.cost - 1 / r.life) * 100, 1)}%)`, B$(g.nash.q[i]),
        GM.entrant ? B$(ent.q[i]) : B$(g.nash.profit[i])])));
    $("#gt-over").textContent = xx(g.overbuild);
    $("#gt-kept").textContent = pct0(g.profit_share_kept);
    $("#gt-ent").textContent = sPct(g.entrant_cut, 0);
    $("#gt-price").textContent = `${pct0(g.nash.P)} vs ${pct0(g.collusive_P)}`;
    const A = d.A, mt = $("#gt-dilemma");
    mt.replaceChildren();
    const hd = h("thead"), hr = h("tr");
    hr.append(h("th", null, "Your seat ↓ / everyone else →"), h("th", "r", "Everyone restrains"), h("th", "r", "Everyone races"));
    hd.append(hr);
    const tb = h("tbody");
    ["Restrain", "Race"].forEach((n, i) => {
      const tr = h("tr"); tr.append(h("th", null, n));
      A[i].forEach((v, j) => { const td = h("td", "r num" + (i === 1 && j === 1 ? " eq" : ""), B$(v, 1)); if (i === 1 && j === 1) td.title = "The Nash equilibrium: racing is dominant"; tr.append(td); });
      tb.append(tr);
    });
    mt.append(hd, tb);
    $("#gt-capex-out").textContent = `Racing pays more whatever the others do (${B$(A[1][0], 1)} against ${B$(A[0][0], 1)} if they restrain; ${B$(A[1][1], 1)} against ${B$(A[0][1], 1)} if they race), so every seat races, and each earns ${pct0(d.cost_of_racing)} less than if all had restrained. The calibrated market clears at a ${pct0(g.nash.P)} gross return on capacity; one buyer setting the build would choose ${B$(g.collusive_Q, 0)} instead of ${B$(g.nash.Q, 0)}. A sixth builder at the average cost cuts the five incumbents' profit by ${pct0(-g.entrant_cut)}.`;
  }
  function renderExit() {
    if (!$("#gt-exit-chart")) return;
    const lam = GM.Y * (GM.vol / 100) * Math.sqrt(GM.crowd / GM.adv), cost = GM.cost / 1e4, y = GM.edge / 100, sp = GM.sdPub / 100, sv = GM.sdPriv / 100;
    const r = crowdedExit(lam, cost, y, sp, sv);
    $("#gt-lam").textContent = sPct(-lam, 2);
    $("#gt-x").textContent = sPct(r.x_star, 2);
    $("#gt-share").textContent = pct0(r.share_exiting);
    $("#gt-uniq").textContent = r.unique ? "Unique" : "Multiple";
    $("#gt-exit-out").textContent = `Unwinding the whole crowd would cost stayers about ${fx(lam * 100, 2)}% (square-root impact: ${fx(GM.crowd, 0)} billion against ${fx(GM.adv, 0)} billion a day at ${fx(GM.vol, 1)}% daily volatility). A pod exits when its own read of the trade's edge falls below ${sPct(r.x_star, 2)}, so at today's expected edge of ${sPct(y, 2)} about ${pct0(r.share_exiting)} of the crowd heads for the door. ${r.unique ? "Private views are precise enough relative to public news that the run threshold is unique: the outcome follows fundamentals." : "Public news is precise relative to private views, so several equilibria exist: a headline can coordinate a run that fundamentals do not justify."}`;
    const pts = [];
    for (let i = 0; i <= 80; i++) { const th = y - 4 * sp + (8 * sp) * i / 80; pts.push([th * 100, ncdf(Math.sqrt(1 / (sv * sv)) * (r.x_star - th)) * 100]); }
    xyChart($("#gt-exit-chart"), { series: [{ name: "Share exiting", pts, color: "var(--s1)" }], xfmt: (v) => fx(v, 1) + "%", yfmt: (v) => fx(v, 0) + "%",
      label: "Share of the crowd exiting by the true edge of the trade", xticks: niceTicks(pts[0][0], pts[pts.length - 1][0], 6).map((t) => [t, fx(t, 1) + "%"]), vmarks: [{ x: y * 100, label: "expected edge" }], zero: true });
  }
  function renderKyle() {
    if (!$("#gt-kyle-out")) return;
    const sv = GM.sv / 100, su = GM.su, k = kyleEq(sv, su);
    const moveYour = k.lambda * GM.order;
    $("#gt-klam").textContent = `${fx(k.lambda * 1e4 * 100, 2)}bp per $100M`;
    $("#gt-kmove").textContent = sPct(moveYour, 2);
    $("#gt-kprof").textContent = `$${fx(k.insider_profit, 1)}M`;
    $("#gt-kyle-out").textContent = `With fundamental uncertainty of ${fx(GM.sv, 1)}% and ${fx(GM.su, 0)} million dollars of uninformed flow, a market maker who knows someone informed is trading moves the price ${fx(k.lambda * 1e4 * 100, 2)}bp per $100 million of net buying. Your ${fx(GM.order, 0)} million order would move it ${sPct(moveYour, 2)}. The informed trader reveals half of what she knows, and more noise flow both hides her and pays her.`;
  }
  /* ---------- the matrix lab ---------- */
  const GAME_PRESETS = {
    capex: { name: "Capex race (two builders)", rows: ["Restrain", "Race"], cols: ["Restrain", "Race"], A: [[9, 7.5], [10, 8]], B: [[9, 10], [7.5, 8]],
      note: "Payoffs are profits in the textbook duopoly (a = 1, b = 1, c = 0, times 72): racing is dominant and both earn less." },
    chicken: { name: "Who de-grosses first", rows: ["Hold", "Sell first"], cols: ["Hold", "Sell first"], A: [[0, 7], [2, 6]], B: [[0, 2], [7, 6]],
      note: "Two pods in one crowded trade. Both holding through a drawdown is the worst cell; selling first is safe but leaves money behind." },
    stag: { name: "Hedge together or alone", rows: ["Coordinate", "Go alone"], cols: ["Coordinate", "Go alone"], A: [[4, 0], [3, 3]], B: [[4, 3], [0, 3]],
      note: "A stag hunt: the joint hedge pays most but only if both commit; going alone is safe. Two pure equilibria, and a mixed one." },
    pennies: { name: "Market maker against an informed trader", rows: ["Quote wide", "Quote tight"], cols: ["Trade", "Wait"], A: [[1, -1], [-1, 1]], B: [[-1, 1], [1, -1]],
      note: "Zero-sum: any predictable quoting is exploited, so the equilibrium is mixed (the logic behind randomized order placement)." },
    rps: { name: "Sector rotation", rows: ["Growth", "Value", "Defensives"], cols: ["Growth", "Value", "Defensives"], A: [[0, -1, 1], [1, 0, -1], [-1, 1, 0]], B: [[0, 1, -1], [-1, 0, 1], [1, -1, 0]],
      note: "Rock, paper, scissors: no pure equilibrium; the only equilibrium mixes all three evenly." },
  };
  function gameNow() { return GM.custom || GAME_PRESETS[GM.preset]; }
  function renderGameMatrix() {
    const box = $("#gt-matrix");
    if (!box) return;
    const g = gameNow(), m = g.rows.length, n = g.cols.length;
    box.replaceChildren();
    const t = h("table", "payoff"), hd = h("thead"), hr = h("tr");
    hr.append(h("th", null, "Row ↓ / Column →"));
    g.cols.forEach((c) => hr.append(h("th", "r", c)));
    hd.append(hr);
    const tb = h("tbody");
    for (let i = 0; i < m; i++) {
      const tr = h("tr"); tr.append(h("th", null, g.rows[i]));
      for (let j = 0; j < n; j++) {
        const td = h("td", "r cellpair");
        [["A", "row"], ["B", "column"]].forEach(([k, who]) => {
          const inp = h("input", "pay " + k);
          inp.type = "number"; inp.step = "any"; inp.value = String(g[k][i][j]);
          inp.setAttribute("aria-label", `${who} payoff when row plays ${g.rows[i]} and column plays ${g.cols[j]}`);
          inp.addEventListener("change", () => {
            const v = Number(inp.value);
            if (!Number.isFinite(v)) { inp.value = String(gameNow()[k][i][j]); return; }
            const c = JSON.parse(JSON.stringify(gameNow())); c[k][i][j] = v; c.name = "Your game"; GM.custom = c; renderMatrixResult();
          });
          td.append(inp);
        });
        tr.append(td);
      }
      tb.append(tr);
    }
    t.append(hd, tb);
    const w = h("div", "tablewrap"); w.append(t);
    box.append(w);
    $("#gt-note").textContent = g.note || "Your own payoffs: row player first, column player second.";
    renderMatrixResult();
  }
  function renderMatrixResult() {
    const g = gameNow(), r = nashAll(g.A, g.B), out = $("#gt-eq");
    if (!out) return;
    out.replaceChildren();
    const mix = (v, names) => v.map((p, i) => (p > 1e-9 ? `${names[i]} ${pct0(p)}` : null)).filter(Boolean).join(", ");
    r.equilibria.forEach((e, k) => {
      const li = h("li");
      li.append(h("strong", null, e.pure ? `Pure equilibrium ${k + 1}` : `Mixed equilibrium ${k + 1}`),
        h("span", null, `Row: ${mix(e.x, g.rows)}. Column: ${mix(e.y, g.cols)}. Payoffs ${fx(e.u_row, 2)} and ${fx(e.u_col, 2)}.`));
      out.append(li);
    });
    if (!r.equilibria.length) out.append(h("li", null, "No equilibrium found on equal-size supports: the game is degenerate; nudge a payoff by a small amount."));
    const facts = [];
    if (r.dominated_rows.length) facts.push(`Row never plays ${r.dominated_rows.map((i) => g.rows[i]).join(", ")} (strictly dominated).`);
    if (r.dominated_cols.length) facts.push(`Column never plays ${r.dominated_cols.map((j) => g.cols[j]).join(", ")} (strictly dominated).`);
    facts.push(`Pareto-efficient cells: ${r.pareto.map(([i, j]) => `${g.rows[i]} / ${g.cols[j]}`).join("; ")}.`);
    if (r.price_of_anarchy) facts.push(`Price of anarchy: the best cell's total payoff is ${fx(r.price_of_anarchy, 3)} times the worst equilibrium's.`);
    $("#gt-facts").textContent = facts.join(" ");
  }
  /* ---------- the prediction-market ladder ---------- */
  const LADDER_DEFAULT = [{ k: 3.0, bid: 0.86, ask: 0.88 }, { k: 3.25, bid: 0.62, ask: 0.65 }, { k: 3.5, bid: 0.41, ask: 0.44 }, { k: 3.75, bid: 0.46, ask: 0.48 }, { k: 4.0, bid: 0.09, ask: 0.11 }];
  function renderLadder() {
    const box = $("#gt-ladder");
    if (!box) return;
    if (!GM.ladder) GM.ladder = LADDER_DEFAULT.map((r) => Object.assign({}, r));
    box.replaceChildren();
    const t = h("table", "pm-ladder"), hd = h("thead"), hr = h("tr");
    ["Above", "Yes bid", "Yes ask"].forEach((c, i) => hr.append(h("th", i ? "r" : null, c)));
    hd.append(hr);
    const tb = h("tbody");
    GM.ladder.forEach((r, i) => {
      const tr = h("tr");
      ["k", "bid", "ask"].forEach((f) => {
        const td = h("td", f === "k" ? null : "r"), inp = h("input", "pay");
        inp.type = "number"; inp.step = f === "k" ? "0.05" : "0.01"; inp.min = "0"; inp.value = String(r[f]);
        inp.setAttribute("aria-label", `${f === "k" ? "Threshold" : f === "bid" ? "Yes bid" : "Yes ask"}, row ${i + 1}`);
        inp.addEventListener("change", () => { const v = Number(inp.value); if (Number.isFinite(v) && (f === "k" || (v >= 0 && v <= 1))) { GM.ladder[i][f] = v; renderLadderResult(); } else inp.value = String(GM.ladder[i][f]); });
        td.append(inp); tr.append(td);
      });
      tb.append(tr);
    });
    t.append(hd, tb);
    const w = h("div", "tablewrap"); w.append(t); box.append(w);
    renderLadderResult();
  }
  function renderLadderResult() {
    const rows = GM.ladder.filter((r) => fin(r.k) && fin(r.bid) && fin(r.ask) && r.bid <= r.ask);
    if (rows.length < 2) { $("#gt-ladder-out").textContent = "Enter at least two thresholds with a bid at or below the ask."; return; }
    const L = ladderCheck(rows, 100);
    const lab = (b) => (b.lo == null ? `≤ ${b.hi}` : b.hi == null ? `> ${b.lo}` : `${b.lo} to ${b.hi}`);
    barsV($("#gt-pmf"), L.pmf.map((b) => ({ label: lab(b), v: b.p * 100, lbl: pct0(b.p) })), { label: "Implied probability of each range, after the coherence fix", yfmt: (v) => fx(v, 0) + "%", height: 200 });
    const parts = [];
    parts.push(L.violations.length ? `${L.violations.length} incoherent pair${L.violations.length > 1 ? "s" : ""}: the market prices "above ${L.violations[0].hi}" ${fx(L.violations[0].gap * 100, 1)} cents richer than "above ${L.violations[0].lo}", which cannot be.` : "The ladder is coherent: the chance of clearing each threshold falls as the threshold rises.");
    parts.push(L.arbitrage.length ? `Executable after fees: buy "above ${L.arbitrage[0].buy}" at the ask and sell "above ${L.arbitrage[0].sell}" at the bid for ${fx(L.arbitrage[0].net * 100, 1)} cents a pair that cannot lose (fees ${fx(L.arbitrage[0].fees * 100, 1)} cents, 100 contracts).` : "No pair is executable for a riskless profit once fees and the spread are paid.");
    $("#gt-ladder-out").textContent = parts.join(" ");
  }
  /* ---------- the fill-quality lab (market making desk) ---------- */
  const FQ = { bid: 100.00, ask: 100.02, qb: 900, qa: 100, later: 99.99, pf: 60, cf: 0.1, miss: 0.8 };
  function renderFill() {
    if (!$("#fq-out")) return;
    const b = bookState(FQ.bid, FQ.ask, FQ.qb, FQ.qa), passive = markoutOf(1, FQ.bid, b.mid, FQ.later), cross = markoutOf(1, FQ.ask, b.mid, FQ.later);
    const vPost = postValue(FQ.pf / 100, passive.markout * 100, FQ.cf, FQ.miss), vCross = cross.markout * 100 - FQ.cf;
    $("#fq-mid").textContent = fx(b.mid, 3);
    $("#fq-imb").textContent = fx(b.imbalance, 2);
    $("#fq-wm").textContent = fx(b.weighted_mid, 3);
    $("#fq-mk").textContent = `${sBp(passive.markout * 100, 1)}¢`;
    $("#fq-out").textContent = `Buying on the bid at ${fx(FQ.bid, 2)} starts ${fx(passive.edge * 100, 1)}¢ ahead of the midpoint; the midpoint then moves ${sBp(passive.move * 100, 1)}¢, so the markout is ${sBp(passive.markout * 100, 1)}¢ a share. Posting is worth ${sBp(vPost, 2)}¢ a share after a ${fx(FQ.pf, 0)}% fill chance and the cost of missing; crossing is worth ${sBp(vCross, 2)}¢. ${vPost >= vCross ? "Post." : "Cross: the queue is not worth waiting in."} With imbalance ${fx(b.imbalance, 2)}, the size-weighted midpoint (${fx(b.weighted_mid, 3)}) already leans ${b.weighted_mid > b.mid ? "up" : "down"}: a heuristic, not a forecast.`;
  }
  function buildGames() {
    const bind = (id, obj, key, fmt, after) => {
      const el = $(id), o = $(id + "-o");
      if (!el || el.dataset.wired) return;
      el.dataset.wired = "1";
      const upd = () => { obj[key] = el.type === "checkbox" ? el.checked : Number(el.value); if (o) o.textContent = fmt(obj[key]); };
      el.addEventListener("input", () => { upd(); guard("Games", after); });
      upd();
    };
    bind("#gt-p", GM, "p", (v) => `${v}%`, renderCapexGame);
    bind("#gt-wacc", GM, "wacc", (v) => `${fx(v, 1)}%`, renderCapexGame);
    bind("#gt-orcl", GM, "orcl", (v) => `+${fx(v, 1)}%`, renderCapexGame);
    bind("#gt-ent-t", GM, "entrant", (v) => (v ? "shown" : "hidden"), renderCapexGame);
    [["#gt-crowd", "crowd", (v) => `$${v}B`], ["#gt-adv", "adv", (v) => `$${v}B`], ["#gt-vol", "vol", (v) => `${fx(v, 1)}%`], ["#gt-cost", "cost", (v) => `${v}bp`],
      ["#gt-edge", "edge", (v) => `${fx(v, 2)}%`], ["#gt-sdpub", "sdPub", (v) => `${fx(v, 2)}%`], ["#gt-sdpriv", "sdPriv", (v) => `${fx(v, 2)}%`]].forEach(([id, k, f]) => bind(id, GM, k, f, renderExit));
    [["#gt-sv", "sv", (v) => `${fx(v, 1)}%`], ["#gt-su", "su", (v) => `$${v}M`], ["#gt-order", "order", (v) => `$${v}M`]].forEach(([id, k, f]) => bind(id, GM, k, f, renderKyle));
    [["#fq-qb", "qb", (v) => String(v)], ["#fq-qa", "qa", (v) => String(v)], ["#fq-later", "later", (v) => fx(v, 3)], ["#fq-pf", "pf", (v) => `${v}%`], ["#fq-cf", "cf", (v) => `${fx(v, 2)}¢`], ["#fq-miss", "miss", (v) => `${fx(v, 2)}¢`]].forEach(([id, k, f]) => bind(id, FQ, k, f, renderFill));
    const sel = $("#gt-preset");
    if (sel && !sel.dataset.wired) {
      sel.dataset.wired = "1";
      Object.entries(GAME_PRESETS).forEach(([k, g]) => { const o = h("option", null, g.name); o.value = k; sel.append(o); });
      sel.value = GM.preset;
      sel.addEventListener("change", () => { GM.preset = sel.value; GM.custom = null; renderGameMatrix(); });
    }
    const lr = $("#gt-ladder-reset");
    if (lr && !lr.dataset.wired) { lr.dataset.wired = "1"; lr.addEventListener("click", () => { GM.ladder = null; renderLadder(); }); }
    renderCapexGame(); renderKyle(); renderGameMatrix(); renderLadder(); renderFill();
  }
  function drawGames() { guard("Crowded exit", renderExit, $("#gt-exit-chart")); guard("Ladder", renderLadderResult, $("#gt-pmf")); fixChartRoles($("#view-games")); }

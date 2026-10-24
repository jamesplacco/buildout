  /* =====================================================================================
     boot.js (v0.6, regrouped in v0.18 and v0.23): six groups, their desks, the math toggle, deep links, live data, boot
     ===================================================================================== */
  const GROUPS = {   // v0.23: six groups. Today is one screen; the Engine group is the system itself, its parameters first; Workshop holds the games and toys
    today: { name: "Today", views: ["desk", "decision", "portfolio", "ooda", "decide", "solve", "journal", "noteworthy"] },
    engine: { name: "Engine", views: ["explained", "parameters", "mind", "brain", "atlas", "geometry", "matrix", "code", "agents"] },
    markets: { name: "Markets", views: ["bonds", "rates", "hedges", "options", "securities", "insurers", "positions", "swans"] },
    research: { name: "Research", views: ["digest", "findings", "fundamentals", "analysis", "theses", "edge", "physics", "buyside", "labs", "ml", "reality", "field"] },
    workshop: { name: "Workshop", views: ["games", "cardroom", "making", "prop", "lab", "legends", "lenses"] },
    reference: { name: "Methods", views: ["engine", "engines", "appendix"] },
  };
  const GROUP_ORDER = ["today", "engine", "markets", "research", "workshop", "reference"];
  const VIEWS = GROUP_ORDER.flatMap((g) => GROUPS[g].views);
  const groupOf = (v) => GROUP_ORDER.find((g) => GROUPS[g].views.includes(v)) || "today";
  const lastInGroup = {};
  function goGroup(g) {
    if (!GROUPS[g]) return;
    const v = lastInGroup[g] || GROUPS[g].views[0];
    if (location.hash === "#" + v) show(v, true); else location.hash = v;
  }
  const RENDER = {
    atlas: () => guard("The atlas", renderAtlasDesk, $("#atv-tiles")),
    mind: () => { guard("The mind", renderMindDesk, $("#md-tiles")); guard("Which brain", wireHeroWhich, $("#hero")); },
    labs: () => guard("The labs", renderLabsDesk, $("#lb-tiles")),
    analysis: () => guard("Technicals and fundamentals", renderAnalysisDesk, $("#an-tiles")),
    ml: () => { guard("The machine-learning lab", renderMlDesk, $("#ml-tiles")); guard("Complexity", renderComplexity, $("#cmx-tiles")); guard("The RL agent", renderRlBlock, $("#rl-tiles")); },
    reality: () => guard("The reality check", renderRealityDesk, $("#rt-tiles")),
    edge: () => { guard("The information edge", renderEdgeDesk, $("#ed-tiles")); guard("Distribution", renderDistribution, $("#ed-dist")); },
    cardroom: () => { guard("The labs", renderLabsDesk, $("#lb-tiles")); guard("The card room", drawYale, $("#cr-yale")); },
    code: () => guard("Under the hood", renderCodeDesk, $("#cd-list")),
    agents: () => {},
    desk: () => { guard("Today", renderToday7, $("#today7")); guard("Landing", renderLanding, $("#call-board")); guard("Rosette", () => drawRosette(true)); },
    parameters: () => guard("The parameters", renderParameters, $("#pm-tiles")),
    explained: () => guard("How it works", renderExplained, $("#hw-read")),
    digest: () => guard("Research digest", renderDigest, $("#dg-tiles")),
    bonds: () => guard("Bonds, simply", renderBonds, $("#bd-tiles")),
    decision: () => { guard("Decision engine", renderDecision, $("#dx-card")); guard("What if", renderWhatIf, $("#dxw-out")); },
    portfolio: () => guard("Portfolio engine", renderPortfolio, $("#pf-card")),
    matrix: () => guard("The shortcut", renderMatrix, $("#mx-tiles")),
    geometry: () => guard("The shape of the market", renderGeometry, $("#geo-tiles")),
    rates: () => { guard("Curve chart", renderCurve, $("#curve-chart")); guard("Forward curve", renderForward, $("#fw-chart")); guard("Live rates", drawRatesLive); guard("Liquidity charts", drawLiquidity); },
    options: () => { guard("Payoff builder", updatePayoff, $("#po-chart")); guard("Tail budget", updateTail, $("#tb-chart")); guard("Insurance charts", drawInsurance); },
    hedges: () => { guard("Hedge lab", () => renderScenarioChart(hedgeState()), $("#scen-chart")); guard("Sizing lab", () => (sizeReady ? renderDD() : updateSize()), $("#dd-chart")); guard("Futures hedge", updateFutures); },
    securities: () => guard("Risk drivers", renderDrivers, $("#drv-chart")),
    insurers: () => {}, lenses: () => {}, engine: () => {}, appendix: () => {}, decide: () => {}, legends: () => guard("Voices", wireVoices, $("#voices")),
    theses: () => { guard("Alphabet chart", renderGoog, $("#goog-chart")); guard("Guidance chart", renderGuide, $("#guide-chart")); guard("Capex panel", drawCapex); },
    journal: () => guard("Calibration", () => renderCal(scorecard(allRecs())), $("#jrs-cal")),
    swans: () => { guard("Fat tails", renderTailsDesk, $("#sw-tails")); guard("Tail-hedge lab", () => drawTailLab(tailState()), $("#th-chart")); },
    fundamentals: drawFundamentals, physics: drawPhysics, findings: drawFindings, lab: drawLab,
    noteworthy: () => {}, buyside: drawBuyside, solve: () => {
      guard("The solver", () => renderSolve(!RZ_LAST || !RZ_LAST.voi), $("#rz-ledger"));
      // the boundary sweep (90 solves) and the robust sweep follow once the desk is on screen, so opening it never stalls
      idle(() => { guard("Decision boundary", renderBoundary, $("#rz-bnd")); guard("Robust solver", renderDRO, $("#rz-dro")); });
    }, games: drawGames,
    brain: () => { guard("System map", renderMap, $("#map-box")); guard("The brain", updateBrain, $("#br-svg-box")); guard("Learning from the data", renderLearned, $("#brl-order")); guard("Ask the brain", wireAsk, $("#bra-form")); guard("Causal statistics", renderCausalPanel, $("#brl-crisis")); guard("Brain self-checks", renderRobustBrain, $("#brr-cov")); },
    field: () => guard("Field compare", renderFieldCompare, $("#fd-ev")),
    ooda: () => { guard("Decision loop", renderOODA, $("#oo-strip")); guard("Decision record", wireOODA); guard("Correlation gauge", renderGauge, $("#gauge")); },
    positions: () => guard("Positions", renderPositions, $("#ps-grid")),
    engines: () => { guard("Engine room", renderEngines, $("#en-table")); guard("Market charts", drawMacroCharts, $("#corr-chart")); guard("Book charts", drawBookCharts, $("#bt-chart")); },
    prop: () => { guard("Edge calculator", updateEdge, $("#pe-chart")); guard("Challenge simulator", updateChallenge, $("#pc-chart")); guard("Pod economics", updatePods, $("#pp-chart")); },
    making: () => { guard("Fill quality", renderFill, $("#fq-out")); guard("Market maker", updateAS, $("#as-chart")); guard("Adverse selection", updateGM, $("#gm-chart")); guard("Execution", updateExec, $("#ex-chart")); guard("Tape", renderTape, $("#mm-tape")); },
  };
  let current = null;
  // any element id is a deep link: the view that contains it opens and the element scrolls into view
  function resolve(token) {
    if (!token) return { view: "desk", el: null };
    if (VIEWS.includes(token)) return { view: token, el: null };
    if (GROUPS[token]) return { view: lastInGroup[token] || GROUPS[token].views[0], el: null };
    let el = document.getElementById(token);
    if (!el && /^sec-/.test(token) && secFilter !== "All") { secFilter = "All"; renderSecurities(); el = document.getElementById(token); }
    if (!el && /^ep-/.test(token) && epKind !== "All") { epKind = "All"; buildEpisodes(); el = document.getElementById(token); }
    if (!el && /^lg-/.test(token) && lgGroup !== "All") { lgGroup = "All"; renderLegends(); el = document.getElementById(token); }
    if (!el && LAZY.pending) { lazyFlushAll(); el = document.getElementById(token); }      // a deep link into a desk not built yet
    const v = el && el.closest(".view");
    return v ? { view: v.id.slice(5), el } : { view: "desk", el: null };
  }
  function renderSubtabs(view) {
    const g = groupOf(view), nav = $("#subtabs");
    document.querySelectorAll(".tabs a[data-group]").forEach((a) => {
      if (a.dataset.group === g) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
      const v = lastInGroup[a.dataset.group] || GROUPS[a.dataset.group].views[0];
      a.href = "#" + v;
    });
    if (!nav) return;
    nav.replaceChildren();
    if (GROUPS[g].views.length < 2) return;
    nav.append(h("span", "sub-label", GROUPS[g].name));
    GROUPS[g].views.forEach((v) => {
      const a = h("a", null, TAB_NAME[v]);
      a.href = "#" + v;
      if (v === view) a.setAttribute("aria-current", "page");
      if (typeof DESK_GUIDE === "object" && DESK_GUIDE[v]) a.title = DESK_GUIDE[v].q;
      nav.append(a);
    });
    const here = h("span", "sub-here");
    here.id = "sub-here"; here.hidden = true;
    nav.append(here);
  }
  // a view change cross-fades where the browser supports view transitions and the reader allows motion
  const calm = () => !window.matchMedia || window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  function show(token, scroll) {
    let t = token;
    try { t = decodeURIComponent(token); } catch (e) { t = ""; }
    const { view } = resolve(t);
    if (scroll && current && view !== current && typeof document.startViewTransition === "function" && !calm() && !document.body.classList.contains("printing")) {
      try { document.startViewTransition(() => showNow(token, scroll)); return; } catch (e) { /* fall through */ }
    }
    showNow(token, scroll);
  }
  function showNow(token, scroll) {
    let t = token;
    try { t = decodeURIComponent(token); } catch (e) { t = ""; }
    const { view, el } = resolve(t);
    lazyFlush(view);
    VIEWS.forEach((v) => { $("#view-" + v).hidden = v !== view; });
    current = view;
    lastInGroup[groupOf(view)] = view;
    renderSubtabs(view);
    guard("Guide", () => guideOnShow(view));
    document.title = (view === "desk" ? "" : TAB_NAME[view] + " · ") + "Buildout Risk Engine";
    guard(TAB_NAME[view], RENDER[view]);
    hideTip();
    if (el) {
      if (el.tagName === "DETAILS") el.open = true;
      const d = el.parentElement && el.parentElement.closest("details");
      if (d) d.open = true;
      el.scrollIntoView({ block: "start" });
    } else if (scroll) window.scrollTo(0, 0);
  }

  /* ---------- show the math ---------- */
  function setMath(on) {
    document.documentElement.classList.toggle("math-on", on);
    const b = $("#math-toggle");
    if (b) { b.setAttribute("aria-pressed", on ? "true" : "false"); b.title = on ? "Hide the formulas" : "Show every formula on the page"; }
    LS.set("bo-math", on);
  }
  const toggleMath = () => setMath(!document.documentElement.classList.contains("math-on"));
  function wireMath() {
    const b = $("#math-toggle");
    if (b) b.addEventListener("click", toggleMath);
    setMath(LS.get("bo-math", false) === true);
  }

  /* ---------- search: the v0.5 desks join the index ---------- */
  function buildIndex5() {
    const add = (title, sub, kind, target, keys = "") => INDEX.push({ title, sub, kind, target, t: title.toLowerCase(), hay: `${title} ${sub} ${keys}`.toLowerCase() });
    (LIVE.decisions || decisions()).forEach((d, i) => add(`Decision ${i + 1}: ${d.n}`, d.act, "Decision", d.id, `${d.q} ${d.rule}`));
    ASSUMPTIONS.forEach((a) => add(a.t, `${a.kind} assumption · ${Math.round(a.p * 100)}% · ${a.ev}`, "Assumption", "as-" + a.id + "-row", a.test));
    CHAINS.forEach((c) => add(c.n, c.so, "Chain", c.id, c.steps.map((s) => s.t + " " + s.do).join(" ")));
    SWANS.forEach((s) => add(s.n, `${s.kind} · ${s.hit}`, "Swan", s.id, `${s.ev} ${s.pays} ${s.fails}`));
    LEGENDS.forEach((l) => add(l.n, l.idea, "Legend", l.id, `${l.who} ${l.rule} ${l.g}`));
    TALEB.forEach((t) => add(t.n, t.t, "Principle", "tal-title", t.rule));
    OVERLOOKED.forEach((o) => add(o.n, o.t, "Overlooked", o.at));
    TOYS.forEach((t) => add(t.title, t.intro, "Tool", t.id));
    document.querySelectorAll("#fi-list .finding").forEach((f) => { const h3 = f.querySelector("h3"), c = f.querySelector(".claim"); if (h3) add(h3.textContent, c ? c.textContent : "", "Finding", f.id); });
    NW.forEach((t) => add(t.n, t.bluf, "Trend", "nw-" + t.id, t.watch.map((w) => w.join(" ")).join(" ")));
    BR_NODES.forEach((n) => add(`${n.n} in the brain`, n.why, "Node", "brain", n.s));
    BR_PRESETS.forEach((p) => add(`Brain scenario: ${p.n}`, "Shock the system map and read the fourth-order effects", "Tool", "brain"));
    FUND.rows.forEach((r) => add(`${r.name} fundamentals`, `${r.t}: capex ${B$(r.capex)} against cash flow ${B$(r.ocf)} · ${COVERAGE[r.coverage] || "coverage n/a"}`, "Company", "fu-t-title", r.t));
    add("Voices: extreme bear to extreme bull", "Verbatim, sourced quotes from legendary and current investors on any question", "Tool", "voices", "quotes investors buffett munger dalio druckenmiller bitcoin gold ai bubble bonds");
    add("The atlas", "The whole brain: every series, every learned link, communities, connectedness", "Tool", "atlas", "network graph lasso stability selection var lingam connectedness spillover diebold yilmaz pagerank");
    add("The brain, live", "Watch a shock travel the system order by order, with the math", "Tool", "hero", "animation propagation neumann leontief matrix monte carlo");
    add("How far to trust the brain", "Conformal error bars, stacked world models, robustness to hidden causes", "Tool", "brr-title", "conformal stacking robustness value confounding");
    add("Calculator", "Exact arithmetic with Black-Scholes, Kelly, NPV, IRR and live values; type = in search", "Tool", "calc", "math compute formula expression");
    add("The solver", "Evidence ledger, posterior, constrained choice, game against Nature, value of information", "Tool", "solve", "bayes optimize reason");
    add("Reverse stress test", "The most plausible way to breach the loss limit", "Tool", "rzr-title", "mahalanobis breach");
    add("Value of information", "Which signal is worth learning next", "Tool", "rzv-title", "research priority evsi evpi");
    add("Capex race (game theory)", "Cournot prisoner's dilemma calibrated to the builders' filings", "Tool", "gtc-title", "nash cournot hyperscaler");
    add("Crowded exit (global game)", "When a crowded trade runs: the Morris-Shin threshold", "Tool", "gtx-title", "pods de-grossing run");
    add("Kyle's lambda", "What your order tells the market", "Tool", "gtk-title", "informed trader impact");
    add("Game solver", "Every Nash equilibrium of a two-player game", "Tool", "gtm-title", "nash equilibrium matrix");
    add("Prediction-market ladder", "Coherence, arbitrage after fees, implied distribution", "Tool", "gtl-title", "kalshi polymarket");
    add("Fill quality", "Markouts, queue imbalance and the posting decision", "Tool", "fq-title", "execution markout microprice");
    Object.assign(KIND_RANK, { Decision: 8, Finding: 7, Trend: 6, Chain: 5, Swan: 5, Company: 5, Node: 4, Legend: 4, Assumption: 4, Principle: 3, Overlooked: 3 });
  }

  /* ---------- boot ----------
     v0.18: the desk being opened is built first and painted; every other desk's builders wait in a queue that runs in
     idle time, one desk at a time, or at once when that desk is opened, a deep link needs its content, or the page is
     printed. A builder belongs to the desk that contains its target element; builders without one run at once. */
  const LAZY = { byView: {}, pending: 0 };
  const lazyView = (box) => { const el = box ? $(box) : null, v = el && el.closest(".view"); return v ? v.id.slice(5) : null; };
  function lazyFlush(v) {
    const q = LAZY.byView[v];
    if (q) { delete LAZY.byView[v]; LAZY.pending -= q.length; q.forEach(([n, f, b]) => guard(n, f, b ? $(b) : null)); }
    guard("Glossary links", () => linkTerms([v]));
  }
  function lazyFlushAll() { VIEWS.forEach((v) => lazyFlush(v)); }
  const idle = (fn) => (typeof requestIdleCallback === "function" ? requestIdleCallback(fn, { timeout: 1500 }) : setTimeout(fn, 40));
  const LAZY_ON_OPEN = new Set(["solve"]);   // heavy desks (the solver searches thousands of portfolios) build only when opened
  // build the unopened desks one piece at a time while the browser is idle, yielding whenever a frame is due, so a
  // click or a scroll during the background build is answered at once instead of after a whole desk
  function lazyDrain(deadline) {
    const left = () => (deadline && typeof deadline.timeRemaining === "function" ? deadline.timeRemaining() : 8);
    do {
      const v = Object.keys(LAZY.byView).find((k) => !LAZY_ON_OPEN.has(k));
      if (!v) { idle(() => guard("Glossary links", () => linkTerms())); return; }
      const q = LAZY.byView[v];
      const [n, f, b] = q.shift();
      LAZY.pending--;
      guard(n, f, b ? $(b) : null);
      if (!q.length) { delete LAZY.byView[v]; guard("Glossary links", () => linkTerms([v])); }
    } while (left() > 6);
    idle(lazyDrain);
  }
  const BOOT_VIEW = (() => { try { return resolve(decodeURIComponent(location.hash.slice(1))).view; } catch (e) { return "desk"; } })();
  [["The mark", placeMarks], ["Effective fundamentals", applyEffectiveFund], ["Key levels", () => renderLevels(null), "#levels"], ["What moved", renderMoves, "#mv-table"], ["Signals", renderSignals, "#signals-grid"], ["Insurance", renderInsurance, "#iv-tiles"], ["Liquidity", renderLiquidity, "#liq-tiles"], ["Rates tables", buildRatesStatic],
   ["Forward dates", buildForwardDates], ["Curve trade", buildCurveTrade], ["Payoff builder", buildPayoff], ["Hedge matrix", buildMatrix, "#matrix-m"], ["Playbooks", buildPlaybooks, "#pb-grid"],
   ["Hedge lab", buildHedgeLab], ["Futures", buildFutures], ["Securities", buildSecurities, "#sec-grid"], ["Theses", buildTheses, "#thesis-grid"], ["Lenses", buildLenses, "#lens-grid"],
   ["Decide", buildDecide], ["Fundamentals", buildFundamentals], ["Physics", buildPhysics], ["Findings", buildFindings, "#fi-list"], ["Swans", buildSwans, "#sw-grid"], ["Legends", buildLegends, "#lg-grid"], ["Math lab", buildLab, "#lab-list"],
   ["Noteworthy", buildNoteworthy, "#nw-grid"], ["Brain", buildBrain, "#br-svg-box"], ["Trading", buildTrading], ["Buyside", buildBuyside, "#bs-sel"], ["Brain links", renderBrainMeasured, "#br-meas"], ["Pulse", buildPulse, "#pulse"],
   ["Episode atlas", buildEpisodes, "#ep-grid"], ["Glossary", buildGlossary, "#gloss"], ["Methods", buildMethods, "#methods"], ["Numbers to know", buildRules, "#rules"], ["Worked examples", buildExamples, "#examples"], ["Hard questions", buildFAQ, "#faq"], ["Model risk", buildModelRisk],
   ["Solver", buildSolve, "#rz-ledger"], ["Policy record", renderPolicyLive, "#pol-live"], ["Games", buildGames, "#gt-matrix"], ["Field", buildField, "#fd-ev"], ["Today", renderToday7, "#today7"],
   ["Data dictionary", buildDict], ["Reading list", buildReading, "#reading"], ["Checklists", buildChecklists, "#checklists"], ["Changelog", buildChangelog],
   ["Contents", buildTOCs], ["Guide", wireGuide], ["Glossary links", () => linkTerms([BOOT_VIEW])], ["Search", buildIndex], ["Search, v0.5", buildIndex5], ["Navigation", wireNavigation], ["Vim and Emacs keys", wireKeys], ["Show the math", wireMath], ["Journal", wireJournal, "#jr-list"]].forEach(([name, fn, box]) => {
    const v = box && name !== "Journal" ? lazyView(box) : null;
    if (!v || v === BOOT_VIEW) { guard(name, fn, box ? $(box) : null); return; }
    (LAZY.byView[v] = LAZY.byView[v] || []).push([name, fn, box]);
    LAZY.pending++;
  });

  ["#bc-cpn", "#bc-yld", "#bc-mat", "#bc-face", "#bc-shock"].forEach((id) => $(id).addEventListener("input", () => guard("Bond calculator", updateBond)));
  ["#ct-dv01", "#ct-d2", "#ct-d10"].forEach((id) => $(id).addEventListener("input", () => guard("Curve trade", updateCurveTrade)));
  ["#bs-S", "#bs-K", "#bs-T", "#bs-v", "#bs-r", "#bs-q", "#bs-mkt"].forEach((id) => $(id).addEventListener("input", () => guard("Option pricer", updateBS)));
  $("#bs-type").querySelectorAll("button").forEach((b) => b.addEventListener("click", () => {
    bsType = b.dataset.v;
    $("#bs-type").querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", x === b ? "true" : "false"));
    guard("Option pricer", updateBS);
  }));
  ["#po-v", "#po-T"].forEach((id) => $(id).addEventListener("input", () => guard("Payoff builder", updatePayoff)));
  ["#tb-k", "#tb-T", "#tb-v", "#tb-n"].forEach((id) => $(id).addEventListener("input", () => guard("Tail budget", updateTail)));
  document.querySelectorAll("form").forEach((f) => f.addEventListener("submit", (e) => e.preventDefault()));
  [["Bond calculator", updateBond], ["Curve trade", updateCurveTrade], ["Option pricer", updateBS], ["Hedge lab", updateHedge], ["Sizing lab", () => labelsSize(sizeState())], ["Futures hedge", updateFutures], ["Payoff builder", updatePayoff]]
    .forEach(([name, fn]) => guard(name, fn));
  show(location.hash.slice(1), false);
  window.addEventListener("hashchange", () => show(location.hash.slice(1), true));
  idle(lazyDrain);

  let raf = 0, lastW = 0;
  if (typeof ResizeObserver === "function") {
    new ResizeObserver(() => {
      const w = document.body.clientWidth;
      if (w === lastW) return;
      lastW = w;
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => { if (current) guard(TAB_NAME[current], RENDER[current]); });
    }).observe(document.body);
  }
  const redrawTheme = () => { if (current === "desk") guard("Rosette", () => drawRosette(false)); };
  const mq = window.matchMedia("(prefers-color-scheme: dark)");
  if (mq.addEventListener) mq.addEventListener("change", redrawTheme);
  new MutationObserver(redrawTheme).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });

  // the long-history research file must look like the snapshot it replaces, or the snapshot stays
  function researchOk(r) {
    try {
      return !!(r && r.panel && r.panel.months >= 1500 && isoOk(r.panel.end + "-01") && Array.isArray(r.hedge.rows) && r.hedge.rows.length >= 5 && (r.hedge.status ? ["ok", "no_reliable_threshold", "insufficient_evidence", "unavailable"].includes(r.hedge.status) && (r.hedge.status !== "ok" || fin(r.hedge.line)) && (r.hedge.status === "ok" || r.hedge.line == null) : fin(r.hedge.line)) && r.hedge.latest && fin(r.hedge.latest.corr)
        && r.tails && Array.isArray(r.tails.rows) && r.tails.rows.length === 4 && r.roc && r.roc.rows.length === 4 && r.oil && r.oil.summary && r.vix && r.vix.s30 && r.spells && r.gold && r.cape && r.cape.rows.length === 10 && r.panel.end >= FINDINGS.panel.end);
    } catch (e) { return false; }
  }
  // v0.6 files must look like their snapshots, or the snapshot stays
  const brainOk = (b) => { try { return ["low_inflation", "inflation"].every((k) => b.regimes[k] && BR_MEASURED.every((e) => b.regimes[k].edges[e] && fin(b.regimes[k].edges[e].w) && Math.abs(b.regimes[k].edges[e].w) < 1.5 && fin(b.regimes[k].edges[e].se))); } catch (e) { return false; } };
  const buyOk = (b) => { try { return !!(b.latest && fin(b.latest.cpi_3m_ann) && fin(b.latest.corr36) && fin(b.latest.brent_vs_5y) && b.selector && b.tail && fin(b.tail.student_t) && Array.isArray(b.replays)); } catch (e) { return false; } };
  const feedsOk = (f) => !!(f && Array.isArray(f.themes) && Array.isArray(f.items) && typeof f.bluf === "string");
  Promise.all(["brain", "buyside", "feeds", "sources"].map((n) => loadJSON(`data/${n}.json`))).then(([b, bs, fd, so]) => {
    if (b && brainOk(b)) { LIVE.brain = b; guard("Brain links", renderBrainMeasured, $("#br-meas")); guard("The brain", updateBrain, $("#br-svg-box")); } else if (b) LIVE.problems.push("brain.json did not match the expected shape; the page keeps its snapshot");
    if (bs && buyOk(bs)) { LIVE.buyside = bs; guard("Buyside", buildBuyside, $("#bs-sel")); if (current === "buyside") guard("Buyside", drawBuyside); } else if (bs) LIVE.problems.push("buyside.json did not match the expected shape");
    if (fd && feedsOk(fd)) { LIVE.feeds = fd; guard("Noteworthy", buildNoteworthy, $("#nw-grid")); } else if (fd) LIVE.problems.push("feeds.json did not match the expected shape");
    if (so && fin(so.count)) { LIVE.sources = so; const c = $("#chip-sources"); if (c) c.textContent = `${so.count} sources`; }
  });
  loadJSON("data/atlas.json").then((at) => {
    if (at && atlasOk(at)) { LIVE.atlas = at; AT_M = null; if (current === "atlas") guard("The atlas", renderAtlasDesk, $("#atv-tiles")); }
    else if (at) LIVE.problems.push("atlas.json did not match the expected shape; the page keeps the atlas snapshot");
  });
  Promise.all(["ooda", "causal", "engines"].map((n) => loadJSON(`data/${n}.json`))).then(([oo, ca, en]) => {
    if (oo && oodaOk(oo)) { LIVE.ooda = oo; if (current && ["ooda", "positions"].includes(current)) guard(TAB_NAME[current], RENDER[current]); } else if (oo) LIVE.problems.push("ooda.json did not match the expected shape; the page keeps the engine snapshot");
    if (ca && ca.regimes && ca.regimes.low_inflation && ca.regimes.low_inflation.crisis) LIVE.causal = ca;
    if (en && Array.isArray(en.engines)) LIVE.engines = en;
  });
  Promise.all(["macro", "report", "capex", "status", "research"].map((n) => loadJSON(`data/${n}.json`))).then(([m, r, cx, st, rs]) => {
    if (cx) {
      guard("Capex panel", () => renderCapex(cx), $("#capex-live"));
      if (cx.ttm && typeof cx.ttm === "object") {
        LIVE.capexTTM = cx.ttm;
        // one effective dataset: newer filings replace snapshot fields, and every dependent view redraws from it
        if (guard("Effective fundamentals", () => { applyEffectiveFund(); return true; })) {
          [["Fundamentals table", renderFundTable, "#fund-table"], ["Fundamentals", buildFundamentals], ["Decide", buildDecide], ["Games", renderCapexGame, "#gt-capex-table"], ["Today", renderToday7, "#today7"]]
            .forEach(([n, fn, b]) => guard(n, fn, b ? $(b) : null));
          if (current && RENDER[current]) guard(TAB_NAME[current], RENDER[current]);
        }
      }
    }
    if (rs && researchOk(rs)) {
      LIVE.research = rs;
      guard("Findings", buildFindings, $("#fi-list"));
      guard("Swans", renderSwansStatic, $("#sw-grid"));
    } else if (rs) LIVE.problems.push("research.json did not match the expected shape; the page keeps its snapshot");
    if (m && m.latest) {
      const miss = missingFields(m, MACRO_SPEC);
      if (miss.length) errorState($("#macro-body"), "The market file is incomplete.", `Missing or malformed: ${miss.join(", ")}. The rest of the page uses the dated figures shipped with it.`);
      else {
        LIVE.macro = m;
        guard("Engine readout", () => renderMacro(m), $("#macro-body"));
        guard("Key levels", () => renderLevels(m), $("#levels"));
        guard("Live rates", () => buildRatesLive(m), $("#rates-live"));
        guard("What moved", renderMoves, $("#mv-table"));
        guard("Insurance", renderInsurance, $("#iv-tiles"));
        guard("Liquidity", renderLiquidity, $("#liq-tiles"));
        guard("Numbers to know", buildRules, $("#rules"));
        guard("Worked examples", buildExamples, $("#examples"));
        guard("Forward dates", buildForwardDates);
        guard("Data dictionary", buildDict);
        guard("Episode atlas", buildEpisodes, $("#ep-grid"));
      }
    } else if (m) errorState($("#macro-body"), "The market file is incomplete.", "It has no latest block. The rest of the page uses the dated figures shipped with it.");
    if (r && r.summary && r.summary.data && r.summary.data !== "synthetic") {
      const miss = missingFields(r, BOOK_SPEC);
      if (miss.length) errorState($("#book-body"), "The book file is incomplete.", `Missing or malformed: ${miss.join(", ")}.`);
      else { LIVE.report = r; guard("Model book", () => renderBook(r), $("#book-body")); guard("Policy record", renderPolicyLive, $("#pol-live")); guard("Today", renderToday7, $("#today7")); }
    }
    if (st) { LIVE.status = st; guard("System status", () => renderStatus(st), $("#status-body")); }
    guard("Signals", renderSignals, $("#signals-grid"));
    guard("Futures defaults", futuresDefaults);
    if (LIVE.macro || LIVE.report || LIVE.research) { guard("Decide", buildDecide); guard("Legends", renderLegends, $("#lg-grid")); guard("Pulse", buildPulse, $("#pulse")); guard("Buyside", buildBuyside, $("#bs-sel")); }
    if (current) guard(TAB_NAME[current], RENDER[current]);
  });

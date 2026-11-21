  /* =====================================================================================
     boot.js (v0.6, regrouped in v0.18, v0.23, v0.31 and v0.45): five groups, their desks, the math toggle, deep links, live data, boot
     ===================================================================================== */
  // v0.45: one menu on both pages. Four groups carry the call (the same fifteen desks, under the same names, on the
  // core page and on the full one); the fifth, the Library, holds every other desk on seven shelves by what it is for.
  // Before this the full page kept the v0.31 groups (Today, Evidence, Markets, Engine, Library), so a reader who
  // followed the Library link met a second menu with the same desks filed differently.
  const CORE_GROUPS = {
    today: { name: "Call", views: ["home", "desk", "book", "decision", "hedgetest"] },
    record: { name: "Record", views: ["track", "execution"] },
    evidence: { name: "Evidence", views: ["inventory", "memos", "fundamentals"] },
    engine: { name: "Method", views: ["explained", "parameters", "engines", "engine", "appendix"] },
  };
  // the shelves: [key, name, what it is for, desks]. Every desk outside the four groups is on exactly one.
  const SHELVES = [
    ["markets", "Markets and hedges", "The instruments: what each pays, what it costs and what it protects against", ["hedges", "options", "rates", "bonds", "credit", "swans", "positions", "securities", "insurers"]],
    ["live", "Live research", "Read and scored as new data arrives", ["digest", "theses", "reading", "noteworthy", "nowcast", "filings", "futures", "physics"]],
    ["studies", "Studies and tests", "Rules and signals people repeat, put to an honest test", ["findings", "labs", "analysis", "ml", "deeprl", "edge", "field", "buyside", "levers"]],
    ["tools", "Decision tools", "Other ways to reach and stress the call", ["ooda", "decide", "portfolio", "solve", "journal"]],
    ["models", "Models and maps", "How the parts of the system connect, and whether the models' assumptions hold", ["mind", "brain", "atlas", "geometry", "matrix", "reality"]],
    ["internals", "Engine internals", "How the engine finds, tests and runs its methods, and how it was built", ["edges", "reasoning", "methods", "crossfield", "code", "agents"]],
    ["workshop", "Workshop", "The mathematics behind the rules, and the people they were borrowed from", ["lab", "games", "cardroom", "making", "prop", "legends", "lenses"]],
  ];
  const shelfOf = (v) => SHELVES.find((s) => s[3].includes(v)) || null;
  // v0.43: the same sources build two pages; the assembler sets BUILD_CORE for the short one.
  // v0.49: the short page is the brief: five desks, one each in the menu, written for a reader who knows finance
  // and has ten minutes. The call, the book, the record and the method are each one page there; the other ten
  // desks that carried the call (the decision engine, the hedge test, execution, the evidence, the method's
  // internals) are in the library with everything else, under the four groups they always had.
  const CORE = typeof BUILD_CORE !== "undefined" && BUILD_CORE === true;
  if (CORE) document.documentElement.classList.add("is-brief");
  const LIBRARY_HREF = typeof BUILD_LIBRARY_HREF === "string" ? BUILD_LIBRARY_HREF : "page.html";
  const BRIEF_VIEWS = ["home", "desk", "book", "track", "explained"];
  const FULL_GROUPS = Object.assign({}, CORE_GROUPS, { library: { name: "Library", views: ["library"].concat(SHELVES.flatMap((s) => s[3])) } });
  const FULL_ORDER = ["today", "record", "evidence", "engine", "library"];
  const ALL_VIEWS = FULL_ORDER.flatMap((g) => FULL_GROUPS[g].views);
  // on the brief each desk is its own menu entry (a group of one, keyed by the desk), so there is no second row
  const GROUPS = CORE ? Object.fromEntries(BRIEF_VIEWS.map((v) => [v, { name: null, views: [v] }])) : FULL_GROUPS;
  const GROUP_ORDER = CORE ? BRIEF_VIEWS.slice() : FULL_ORDER;
  // the page a reader lands on with no link: Home on the core page, the index on the library
  const FRONT = CORE ? "home" : "library";
  // links written for the menu before v0.45 still land somewhere sensible
  const OLD_GROUPS = Object.assign({ markets: "hedges", research: "digest", reference: "appendix" }, CORE ? { today: "home", record: "track", evidence: "inventory", engine: "explained" } : {});
  const VIEWS = GROUP_ORDER.flatMap((g) => GROUPS[g].views);
  const inLibrary = (v) => CORE && ALL_VIEWS.includes(v) && !VIEWS.includes(v);
  // v0.44: one navigation per link. A link is resolved twice on its way to the screen (once to pick the view, once to
  // show it), and a second assignment to location.href cancels the first request and starts the library again.
  let leavingFor = null;
  // v0.44.1: replace, not assign. The link that brought the reader here has already put this page at #<desk> in the
  // history; assigning left that entry behind, so Back from the library landed on it and was sent forward again.
  const toLibrary = (v) => { if (leavingFor === v) return; leavingFor = v; location.replace(LIBRARY_HREF + "#" + v); };
  window.addEventListener("pageshow", () => { leavingFor = null; });          // back from the library: its links work again
  const groupOf = (v) => GROUP_ORDER.find((g) => GROUPS[g].views.includes(v)) || GROUP_ORDER[0];
  const lastInGroup = {};
  function goGroup(g) {
    if (!GROUPS[g]) return;
    const v = g === "library" ? "library" : lastInGroup[g] || GROUPS[g].views[0];
    if (location.hash === "#" + v) show(v, true); else location.hash = v;
  }
  // v0.37: a desk opens with its first screen; the rest of its sections fold under one line, each still reachable by link.
  // FOLD lists the sections (by aria-labelledby) that stay visible; everything after the first kept section folds.
  const FOLD = {
    book: ["bk-size-t", "bk-front-t", "bk-sens-t", "bk-hedge-t"],
    track: ["tr-three-t", "tr-wf-t", "tr-surv-t", "tr-lev-t"],
    decision: ["dx-inf-title", "dx-dec-title", "dx-ov-title"],
    ooda: ["oo-obs-title", "oo-ori-title", "oo-dec-title", "oo-act-title"],
    futures: ["ft-status-t", "ft-res-t", "ft-book-t"],
    nowcast: ["nc-next-t", "nc-acc-t"],
    filings: ["fl-status-t", "fl-res-t", "fl-book-t"],
    fundamentals: ["rq-title", "fu-t-title", "mi-title"],
    credit: ["pc-call-t", "pc-queue-t", "pc-marks-t", "pc-income-t", "pc-sector-t", "pc-cohort-t", "pc-score-t"],
    edges: ["ed2-funnel-t", "ed2-fam-t", "ed2-now-t"],
    reasoning: ["rs-proof-t", "rs-now-t"],
    parameters: ["pm-flow-title", "pm-read-title"],
    swans: ["tails-title", "atlas-title", "tl-title"],
    insurers: ["how-title", "chainf-title", "pc-title"],
  };
  function foldDesk(view) {
    const keep = FOLD[view], root = $("#view-" + view);
    if (CORE || !keep || !root || root.dataset.folded) return;          // v0.49: the brief cuts (briefDesk), it does not fold
    const secs = [...root.children].filter((e) => e.matches("section.section"));
    const rest = secs.filter((s) => !keep.includes(s.getAttribute("aria-labelledby")));
    if (!rest.length || rest.reduce((a, s) => a + s.innerText.length, 0) < 2500) { root.dataset.folded = "1"; return; }
    const det = h("details", "desk-more"), sm = h("summary");
    const titles = rest.map((s) => { const t = s.querySelector("h2"); return t ? t.textContent.replace(/[.:].*$/, "").trim() : "section"; });
    sm.append(document.createTextNode(rest.length === 1 ? "More on this desk" : `More on this desk (${rest.length} sections)`), h("small", null, titles.join(" · ")));
    det.append(sm);
    rest[0].before(det);
    rest.forEach((s) => det.append(s));
    root.dataset.folded = "1";
  }
  // v0.49: THE BRIEF. On the short page a desk is one page: the sections named here, in order, and nothing else.
  // What is left out is hidden, not deleted (the modules that draw it still run, and the library shows all of it);
  // a link into a hidden part opens the library there. BRIEF_KEEP lists sections by aria-labelledby; BRIEF_HIDE
  // lists anything else on the desk that the short page drops.
  const BRIEF_KEEP = {
    book: ["bk-size-t", "bk-front-t"],
    track: ["tr-three-t", "tr-wf-t", "tr-surv-t"],
    explained: ["hw-call-title", "hw-words-title", "hw-not-title"],
    desk: [],
  };
  const BRIEF_HIDE = {
    desk: ["#brief", "#call-board", "#t7-sizing", ".rosette-end"],
    book: [],
    track: ["#tr-restate-p", "#tr-restate-w", "#tr-hind"],
    explained: [],
    home: ['[aria-labelledby="hm-how-t"]'],
  };
  const BRIEF_WORDS = {
    "bk-title": "How risky the book is, and how much of it the limits allow",
    "bk-size-t": "Three limits, and the one that decides",
    "bk-front-t": "Every mix of size and hedge that meets the limits",
    "tr-title": "The track record: what the rule would have done, and what it has done live",
    "tr-three-t": "Three records, from least to most trustworthy",
    "tr-wf-t": "The simulation: smaller losses, at a cost",
    "tr-surv-t": "The catch: the stocks were picked with hindsight",
    "hw-title": "How the call is made",
    "hw-words-title": "Eight terms, one line each",
    "hw-not-title": "What this is not",
  };
  // the short label over each heading (the rail beside the page lists these)
  const BRIEF_LABEL = { "bk-size-t": "The size", "bk-front-t": "The choices", "tr-three-t": "Three records", "tr-wf-t": "The simulation", "tr-surv-t": "The catch", "hw-words-title": "The terms", "hw-not-title": "What it is not" };
  const BRIEF_LEDE = {
    track: "A rule earns trust from calls made in advance. This page shows what is simulated, what is live, and where the simulation flatters itself.",
    explained: "The call comes from risk limits, not from a view on prices. Six steps, the terms they use, and what this is not.",
  };
  // the desks in the library that a reader of this page is most likely to want next
  const BRIEF_NEXT = {
    desk: [["hedgetest", "Why not bonds: the hedge test"], ["decision", "The forecasting model and its gate"]],
    book: [["hedgetest", "Which hedge protected this book"], ["execution", "How a call becomes orders"]],
    track: [["memos", "The failure log: every mistake found so far"], ["execution", "The paper account"]],
    explained: [["parameters", "Every value set by hand"], ["engines", "Where each number comes from"]],
  };
  const briefCut = (el) => { if (el) { el.hidden = true; el.dataset.briefCut = "1"; } };
  function briefDesk(view) {
    const root = $("#view-" + view);
    if (!CORE || !root || root.dataset.brief) return;
    const keep = BRIEF_KEEP[view];
    if (keep) [...root.children].filter((e) => e.matches("section.section") && !keep.includes(e.getAttribute("aria-labelledby"))).forEach(briefCut);
    (BRIEF_HIDE[view] || []).forEach((sel) => root.querySelectorAll(sel).forEach(briefCut));
    root.querySelectorAll(":scope > .toc, :scope > .dguide").forEach(briefCut);
    Object.entries(BRIEF_WORDS).forEach(([id, txt]) => { const el = root.querySelector("#" + id); if (el) el.textContent = txt; });
    Object.entries(BRIEF_LABEL).forEach(([id, txt]) => { const el = root.querySelector("#" + id), eb = el && el.parentElement.querySelector(":scope > .eyebrow"); if (eb) eb.textContent = txt; });
    const lede = root.querySelector(":scope > .vhead > .lede");
    if (lede && BRIEF_LEDE[view]) lede.textContent = BRIEF_LEDE[view];
    if (view !== "home") {
      const p = h("p", "brief-more"), a = h("a", null, `${TAB_NAME[view]} in full`);
      a.href = LIBRARY_HREF + "#" + view;
      p.append(h("span", "brief-more-k", "In the library: "), a);
      (BRIEF_NEXT[view] || []).forEach(([v, txt]) => { const x = h("a", null, txt); x.href = LIBRARY_HREF + "#" + v; p.append(document.createTextNode(" · "), x); });
      const nx = root.querySelector(":scope > .dnext");
      if (nx) nx.before(p); else root.append(p);
    }
    root.dataset.brief = "1";
  }
  const RENDER = {
    atlas: () => guard("The atlas", renderAtlasDesk, $("#atv-tiles")),
    mind: () => { guard("The mind", renderMindDesk, $("#md-tiles")); guard("Which brain", wireHeroWhich, $("#hero")); },
    labs: () => guard("The labs", renderLabsDesk, $("#lb-tiles")),
    analysis: () => guard("Technicals and fundamentals", renderAnalysisDesk, $("#an-tiles")),
    ml: () => { guard("The machine-learning lab", renderMlDesk, $("#ml-tiles")); guard("Complexity", renderComplexity, $("#cmx-tiles")); guard("The RL agent", renderRlBlock, $("#rl-tiles")); },
    deeprl: () => guard("Deep RL", renderDeepRl, $("#dr-tiles")),
    reality: () => guard("The reality check", renderRealityDesk, $("#rt-tiles")),
    edge: () => { guard("The information edge", renderEdgeDesk, $("#ed-tiles")); guard("Distribution", renderDistribution, $("#ed-dist")); },
    cardroom: () => { guard("The labs", renderLabsDesk, $("#lb-tiles")); guard("The card room", drawYale, $("#cr-yale")); },
    code: () => guard("Under the hood", renderCodeDesk, $("#cd-list")),
    agents: () => {},
    desk: () => { guard("Today", renderToday7, $("#today7")); guard("Landing", renderLanding, $("#call-board")); guard("Nowcast today", renderNowcastToday, $("#t7-nowcast")); guard("Edge lab today", renderEdgesToday, $("#t7-edges")); guard("Rosette", () => drawRosette(true)); },
    parameters: () => guard("The parameters", renderParameters, $("#pm-tiles")),
    explained: () => { guard("How it works", renderExplained, $("#hw-read")); if (CORE) guard("How the call is made", renderBriefMethod, $("#hw-read")); },
    digest: () => guard("Research digest", renderDigest, $("#dg-tiles")),
    reasoning: () => guard("Reasoning", renderReasoning, $("#rs-tiles")),
    filings: () => guard("Filings", renderFilings, $("#fl-tiles")),
    futures: () => guard("Futures", renderFutures, $("#ft-tiles")),
    nowcast: () => guard("Nowcast", renderNowcast, $("#nc-tiles")),
    edges: () => guard("Edge lab", renderEdges, $("#ed2-tiles")),
    methods: () => guard("Methods", renderMethods, $("#mt-tiles")),
    crossfield: () => guard("Borrowed methods", renderCrossfield, $("#cf-tiles")),
    bonds: () => guard("Bonds, simply", renderBonds, $("#bd-tiles")),
    decision: () => { guard("Decision engine", renderDecision, $("#dx-card")); guard("What if", renderWhatIf, $("#dxw-out")); },
    portfolio: () => guard("Portfolio engine", renderPortfolio, $("#pf-card")),
    matrix: () => guard("The shortcut", renderMatrix, $("#mx-tiles")),
    geometry: () => guard("The shape of the market", renderGeometry, $("#geo-tiles")),
    rates: () => { guard("Curve chart", renderCurve, $("#curve-chart")); guard("Forward curve", renderForward, $("#fw-chart")); guard("Live rates", drawRatesLive); guard("Liquidity charts", drawLiquidity); },
    options: () => { guard("Payoff builder", updatePayoff, $("#po-chart")); guard("Tail budget", updateTail, $("#tb-chart")); guard("Insurance charts", drawInsurance); },
    hedges: () => { guard("Hedge lab", () => renderScenarioChart(hedgeState()), $("#scen-chart")); guard("Sizing lab", () => (sizeReady ? renderDD() : updateSize()), $("#dd-chart")); guard("Futures hedge", updateFutures); },
    securities: () => guard("Risk drivers", renderDrivers, $("#drv-chart")),
    insurers: () => {}, lenses: () => {}, engine: () => guard("Test count", renderTestCount), appendix: () => {}, decide: () => {}, legends: () => guard("Voices", wireVoices, $("#voices")),
    theses: () => { guard("Alphabet chart", renderGoog, $("#goog-chart")); guard("Guidance chart", renderGuide, $("#guide-chart")); guard("Capex panel", drawCapex); },
    journal: () => guard("Calibration", () => renderCal(scorecard(allRecs())), $("#jrs-cal")),
    swans: () => { guard("Fat tails", renderTailsDesk, $("#sw-tails")); guard("Tail-hedge lab", () => drawTailLab(tailState()), $("#th-chart")); },
    fundamentals: () => { drawFundamentals(); guard("Railway test", bindRailway, $("#rq-tiles")); }, physics: drawPhysics, findings: drawFindings, lab: drawLab,
    noteworthy: () => {}, buyside: drawBuyside, solve: () => {
      guard("The solver", () => renderSolve(!RZ_LAST || !RZ_LAST.voi), $("#rz-ledger"));
      // the boundary sweep (90 solves) and the robust sweep follow once the desk is on screen, so opening it never stalls
      idle(() => { guard("Decision boundary", renderBoundary, $("#rz-bnd")); guard("Robust solver", renderDRO, $("#rz-dro")); });
    }, games: drawGames,
    brain: () => { guard("System map", renderMap, $("#map-box")); guard("The brain", updateBrain, $("#br-svg-box")); guard("Learning from the data", renderLearned, $("#brl-order")); guard("Ask the brain", wireAsk, $("#bra-form")); guard("Causal statistics", renderCausalPanel, $("#brl-crisis")); guard("Brain self-checks", renderRobustBrain, $("#brr-cov")); },
    field: () => guard("Field compare", renderFieldCompare, $("#fd-ev")),
    ooda: () => { guard("Decision loop", renderOODA, $("#oo-strip")); guard("Decision record", wireOODA); guard("Correlation gauge", renderGauge, $("#gauge")); },
    positions: () => guard("Positions", renderPositions, $("#ps-grid")),
    book: () => guard("Book risk", renderBookRisk, $("#bk-tiles")),
    credit: () => guard("Private credit", renderCredit, $("#pc-tiles")),
    reading: () => guard("Reading room", renderReading, $("#rr-list")),
    home: () => guard("Home", renderHome, $("#hm-perf")),
    track: () => guard("Track record", renderTrack, $("#tr-tiles")),
    hedgetest: () => { guard("Hedge test", renderHedgeTest, $("#ht-tiles")); guard("VIX hedge", renderVix, $("#vx-tiles")); },
    execution: () => { guard("Execution", renderExecution, $("#ex-tiles")); guard("The trader", renderTrader, $("#ex-modes")); },
    memos: () => guard("Memos", renderMemos, $("#mm-list")),
    levers: () => guard("Value creation", renderLevers, $("#lv-tiles")),
    library: () => guard("Library", renderLibrary, $("#lib-grid")),
    inventory: () => guard("Inventory", renderInventory, $("#inv-tiles")),
    engines: () => { guard("Engine room", renderEngines, $("#en-table")); guard("Market charts", drawMacroCharts, $("#corr-chart")); guard("Book charts", drawBookCharts, $("#bt-chart")); },
    prop: () => { guard("Edge calculator", updateEdge, $("#pe-chart")); guard("Challenge simulator", updateChallenge, $("#pc-chart")); guard("Pod economics", updatePods, $("#pp-chart")); },
    making: () => { guard("Fill quality", renderFill, $("#fq-out")); guard("Market maker", updateAS, $("#as-chart")); guard("Adverse selection", updateGM, $("#gm-chart")); guard("Execution", updateExec, $("#ex-chart")); guard("Tape", renderTape, $("#mm-tape")); },
  };
  let current = null;
  // any element id is a deep link: the view that contains it opens and the element scrolls into view
  function resolve(token) {
    if (!token) return { view: FRONT, el: null };          // v0.38: the front door; v0.45: the library opens at its index
    if (VIEWS.includes(token)) return { view: token, el: null };
    if (inLibrary(token)) { toLibrary(token); return { view: current || "home", el: null }; }      // v0.43: a desk the core page does not carry
    if (GROUPS[token]) return { view: lastInGroup[token] || GROUPS[token].views[0], el: null };
    if (OLD_GROUPS[token]) return resolve(OLD_GROUPS[token]);
    let el = document.getElementById(token);
    if (!el && /^sec-/.test(token) && secFilter !== "All") { secFilter = "All"; renderSecurities(); el = document.getElementById(token); }
    if (!el && /^ep-/.test(token) && epKind !== "All") { epKind = "All"; buildEpisodes(); el = document.getElementById(token); }
    if (!el && /^lg-/.test(token) && lgGroup !== "All") { lgGroup = "All"; renderLegends(); el = document.getElementById(token); }
    if (!el && LAZY.pending) { lazyFlushAll(); el = document.getElementById(token); }      // a deep link into a desk not built yet
    // v0.44.1: a link to a security, an episode or a legend is a link into the library when this page does not carry
    // that desk. In v0.43 it threw (the filter it resets was a constant stand-in) and the core page stayed blank.
    // v0.47: any id this page does not carry is a link into the library, which has every desk. Before, only the three
    // families above were sent on and every other one (a finding, a decision, a tool) opened Home without a word.
    if (!el && CORE && /^[A-Za-z][\w-]*$/.test(token)) { toLibrary(token); return { view: current || "home", el: null }; }
    if (el && CORE && el.closest("[data-brief-cut]")) { toLibrary(token); return { view: current || "home", el: null }; }      // v0.49: hidden on the brief
    const v = el && el.closest(".view");
    return v ? { view: v.id.slice(5), el } : { view: FRONT, el: null };      // v0.38: an unknown link opens the front page (v0.45: the library's is its index)
  }
  function renderSubtabs(view) {
    const g = groupOf(view), nav = $("#subtabs");
    document.querySelectorAll(".tabs a[data-group]").forEach((a) => {
      if (a.dataset.group === g) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
      // v0.45: the Library tab always opens the index; the other groups reopen the desk last read there
      const v = a.dataset.group === "library" ? "library" : lastInGroup[a.dataset.group] || GROUPS[a.dataset.group].views[0];
      a.href = "#" + v;
    });
    if (!nav) return;
    nav.replaceChildren();
    if (GROUPS[g].views.length < 2) return;
    // v0.45: a library desk shows its shelf: the index, then the desks filed beside it
    const shelf = g === "library" ? shelfOf(view) : null;
    if (g !== "library" || shelf) nav.append(h("span", shelf ? "sub-label sub-shelf" : "sub-label", shelf ? shelf[1] : GROUPS[g].name));
    const row = g === "library" ? ["library"].concat(shelf ? shelf[3].filter((v) => document.getElementById("view-" + v)) : []) : GROUPS[g].views;
    if (row.length > 1) row.forEach((v) => {
      const a = h("a", null, g === "library" && v === "library" ? "Index" : TAB_NAME[v]);
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
    const R0v = resolve(t), view = R0v.view; let el = R0v.el;
    lazyFlush(view);
    VIEWS.forEach((v) => { $("#view-" + v).hidden = v !== view; });
    current = view;
    lastInGroup[groupOf(view)] = view;
    renderSubtabs(view);
    guard("Guide", () => guideOnShow(view));
    document.title = (view === "desk" ? "" : TAB_NAME[view] + " · ") + "Buildout Risk Engine";
    guard(TAB_NAME[view], RENDER[view]);
    guard("Snapshot badge", () => snapBadge(view));
    guard("Fold", () => foldDesk(view));
    guard("Brief", () => briefDesk(view));
    guard("Rail", () => { railFor(view); guideHere(); });          // v0.46: the desk's sections, beside it
    hideTip();
    if (el && el.id && !el.isConnected) el = document.getElementById(el.id) || el;     // v0.31: the desk re-rendered after the link resolved
    if (el) {
      if (el.tagName === "DETAILS") el.open = true;
      for (let d = el.parentElement && el.parentElement.closest("details"); d; d = d.parentElement && d.parentElement.closest("details")) d.open = true;
      el.scrollIntoView({ block: "start" });
    } else if (scroll) window.scrollTo(0, 0);
  }

  /* ---------- show the math ---------- */
  function setMath(on) {
    document.documentElement.classList.toggle("math-on", on);
    document.documentElement.classList.toggle("math-off", !on);
    const b = $("#math-toggle");
    if (b) { b.setAttribute("aria-pressed", on ? "true" : "false"); b.title = on ? "Hide the formulas" : "Show every formula on the page"; const l = b.querySelector(".lab-t"); if (l) l.textContent = on ? "Hide the math" : "Show the math"; }
    LS.set(CORE ? "bo-math49" : "bo-math25", on);
  }
  const toggleMath = () => setMath(!document.documentElement.classList.contains("math-on"));
  function wireMath() {
    const b = $("#math-toggle");
    if (b) b.addEventListener("click", toggleMath);
    // v0.25: the math shows by default; the button hides it. v0.49: on the brief it is hidden until asked for.
    setMath(CORE ? LS.get("bo-math49", false) === true : LS.get("bo-math25", true) !== false);
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

  // v0.43: wiring for inputs that only some builds carry (the core page has no bond or option calculators)
  const onInput = (ids, name, fn) => ids.forEach((id) => { const e = $(id); if (e) e.addEventListener("input", () => guard(name, fn)); });
  onInput(["#bc-cpn", "#bc-yld", "#bc-mat", "#bc-face", "#bc-shock"], "Bond calculator", updateBond);
  onInput(["#ct-dv01", "#ct-d2", "#ct-d10"], "Curve trade", updateCurveTrade);
  onInput(["#bs-S", "#bs-K", "#bs-T", "#bs-v", "#bs-r", "#bs-q", "#bs-mkt"], "Option pricer", updateBS);
  if ($("#bs-type")) $("#bs-type").querySelectorAll("button").forEach((b) => b.addEventListener("click", () => {
    bsType = b.dataset.v;
    $("#bs-type").querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", x === b ? "true" : "false"));
    guard("Option pricer", updateBS);
  }));
  onInput(["#po-v", "#po-T"], "Payoff builder", updatePayoff);
  onInput(["#tb-k", "#tb-T", "#tb-v", "#tb-n"], "Tail budget", updateTail);
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
  // v0.39.1: the day's call and the ledger, when the published site carries newer ones than this build's snapshot
  const bookOk = (b) => !!(b && typeof b.asof === "string" && fin(b.size) && b.sizes && b.tail && Array.isArray(b.frontier) && b.weights && b.keep_names_hedge);
  // v0.42.5: the decision engine's package is loaded too. Before, the Decision desk read only the embedded DX19 while
  // a revised data/decision.json sat beside it (same month, different inputs: stress next month 20% embedded, 24.5%
  // published). The published package replaces the embedded one, in place, when its content hash differs and it was
  // not computed earlier; the comparison is on content, because both carried the same month.
  const decOk = (d) => !!(d && typeof d.end === "string" && d.now && fin(d.now.exposure) && d.now.gate && fin(d.now.es_1x) && d.gate_hist && Array.isArray(d.gate_hist.dates) && d.curve && Array.isArray(d.curve.dates) && d.forecast_scores && Array.isArray(d.pipeline));
  // v0.47: the walk-forward record. The daily run now rebuilds it (data/track.json) and the tear sheet. When that file
  // is newer than the record built into the page, it replaces the parts the daily run computes: the point-in-time
  // record policy by policy, the hindsight record, the backtest, survivorship, the weeks, the sizing path, the
  // members, the regime table. What only a release computes stays from the snapshot and is labeled with the
  // snapshot's date wherever it is drawn (SNAP38.kept): the deep RL sizer's row, the universe checks, the deep RL
  // study, the VIX study, the alternatives, the regime walk, the restatement. The live record still comes from
  // data/live.json. Before this the record was fixed at each release ("record through Nov 5" on Nov 18).
  const trackOk = (k) => { try { const P = k.pit.policies; return isoOk(k.asof) && ["call", "hold", "call_short"].every((x) => P[x] && P[x].net && fin(P[x].net.sharpe) && fin(P[x].net.maxdd) && fin(P[x].net.cagr) && isoOk(P[x].net.to) && P[x].meta && fin(P[x].meta.avg_gross))
    && fin(k.pit.bench.sharpe) && Array.isArray(k.pit.curve.call) && k.pit.curve.call.length > 100 && fin(k.backtest.size) && k.backtest.stats && fin(k.survivorship.pit_hold_cagr) && k.members && k.hindsight.policies.hold.net && k.policy_name && Array.isArray(k.weeks) && Array.isArray(k.sizing_path); } catch (e) { return false; } };
  Promise.all([loadJSON("data/book.json"), loadJSON("data/calls.json"), loadJSON("data/live.json"), loadJSON("data/paper.json"), loadJSON("data/decision.json"),
    // the record is asked for only when this deployment lists it (data/manifest.json, written by scripts/build_site.py), so a site built before the first daily record logs no failed request
    loadJSON("data/manifest.json").then((mf) => (mf && mf.data && mf.data["track.json"] ? loadJSON("data/track.json") : null)),
    loadJSON("data/manifest.json").then((mf) => (mf && mf.data && mf.data["restatement.json"] ? loadJSON("data/restatement.json") : null))]).then(([bkj, cl, lv, pp, dj, tk, rs]) => {
    let changed = false;
    const PK = LIVE.pkg = {};
    if (typeof DX19 !== "undefined" && DX19) {
      const newer = dj && decOk(dj) && dj.end >= DX19.end && dj.content_sha256 && dj.content_sha256 !== DX19.content_sha256 && String(dj.computed_utc || "") >= String(DX19.computed_utc || "");
      if (newer) { const keep = DX19.v30_patch; Object.keys(DX19).forEach((k) => { delete DX19[k]; }); Object.assign(DX19, dj); if (keep) DX19.v30_patch = keep; LIVE.decision = dj; changed = true; }
      else if (dj && !decOk(dj)) LIVE.problems.push("decision.json did not match the expected shape; the page keeps the decision in its snapshot");
      PK.decision = { showing: newer ? "published" : "embedded", same: !!(dj && dj.content_sha256 === DX19.content_sha256), id: DX19.content_sha256 || null, through: DX19.end, computed: DX19.computed_utc || null, fetch: LIVE.fetch["data/decision.json"] };
    }
    if (bkj && bookOk(bkj) && typeof SNAP30 !== "undefined" && SNAP30 && SNAP30.book && bkj.asof > SNAP30.book.asof) {
      // v0.44: a published book from a run that predates the sensitivity block keeps the embedded one, which says
      // which book and date it was computed on; the next daily run writes its own.
      if (!(bkj.sensitivity && bkj.sensitivity.models) && SNAP30.book.sensitivity) bkj.sensitivity = SNAP30.book.sensitivity;
      // v0.47: two more blocks the daily run cannot rebuild (it has no futures record and plants no test world) stay
      // from the snapshot: the volatility rule's long record, and the planted-beta self-test. Without them the Book
      // risk desk lost its only "supported" row and its validation paragraph the day the first daily file loaded.
      const SB = SNAP30.book;
      if (bkj.vol_rule && !bkj.vol_rule.long_record && SB.vol_rule && SB.vol_rule.long_record) bkj.vol_rule.long_record = SB.vol_rule.long_record;
      if (!bkj.selftest) bkj.selftest = SB.selftest || (SB.validation && SB.validation.mean_abs_beta_error != null ? SB.validation : null);
      SNAP30.book = bkj; LIVE.book = bkj; changed = true;
    }
    else if (bkj && !bookOk(bkj)) LIVE.problems.push("book.json did not match the expected shape; the page keeps the call in its snapshot");
    const T = typeof SNAP38 !== "undefined" ? SNAP38 : null;
    if (tk && trackOk(tk) && T && T.pit && T.pit.policies && isoOk(T.asof) && tk.asof > T.asof) {
      const was = T.asof, keptPol = Object.keys(T.pit.policies).filter((k) => !tk.pit.policies[k]);
      const pit = Object.assign({}, tk.pit, { policies: Object.assign({}, tk.pit.policies), curve: Object.assign({}, tk.pit.curve) });
      keptPol.forEach((k) => { pit.policies[k] = T.pit.policies[k]; if (T.pit.curve && T.pit.curve[k] && !pit.curve[k]) pit.curve[k] = T.pit.curve[k]; });
      ["hindsight", "backtest", "survivorship", "weeks", "sizing_path", "live_rule", "members", "regimes", "book_hedges", "cost"].forEach((k) => { if (tk[k] != null) T[k] = tk[k]; });
      T.policy_name = Object.assign({}, T.policy_name, tk.policy_name);
      T.pit = pit; T.asof = tk.asof;
      T.kept = { asof: was, policies: keptPol, blocks: ["universe", "deeprl", "deeprl_book", "vix", "alternatives", "restated", "regime_walk"].filter((k) => T[k] != null) };
      LIVE.track = tk; changed = true;
    } else if (tk && !trackOk(tk)) LIVE.problems.push("track.json did not match the expected shape; the page keeps the record in its snapshot");
    // v0.48: the before and after of the v0.48 correction, computed once by the daily run on the same prices
    // (scripts/restate.py). Until that file exists the restatement panel says nothing about v0.48.
    if (rs && T && T.restated && rs.policies && rs.policies.call && Array.isArray(rs.policies.call.sharpe)) { T.restated.revised2 = rs; changed = true; }
    if (cl && T && cl.verify && cl.verify.ok && Array.isArray(cl.entries) && cl.entries.length > ((T.ledger && T.ledger.entries) || []).length) {
      T.ledger = { verify: cl.verify, entries: cl.entries };
      T.live = { ...(T.live || {}), calls: cl.entries.length, first_effective: governsFrom(cl.entries[0]) || cl.entries[0].effective_from };
      changed = true;
    }
    if (lv && T && Number.isFinite(lv.marked_days) && lv.calls >= ((T.live && T.live.calls) || 0) && (lv.last_mark || "") >= ((T.live && T.live.last_mark) || "")) { T.live = lv; changed = true; }   // v0.40: the daily marks
    if (pp && T && Number.isFinite(pp.equity) && Array.isArray(pp.equity_history) && Array.isArray(pp.positions)) { T.paper = pp; changed = true; }   // v0.42: the paper bot's account
    const B0 = typeof SNAP30 !== "undefined" && SNAP30 && SNAP30.book ? SNAP30.book : null;
    PK.book = { showing: LIVE.book ? "published" : "embedded", through: B0 ? B0.asof : null, fetch: LIVE.fetch["data/book.json"] };
    const E0 = T && T.ledger ? T.ledger.entries || [] : [], head = (a) => (a.length ? a[a.length - 1].hash : "");
    PK.calls = { showing: cl && E0 === cl.entries ? "published" : "embedded", same: !!(cl && Array.isArray(cl.entries) && cl.entries.length === E0.length && head(cl.entries) === head(E0)), n: E0.length, fetch: LIVE.fetch["data/calls.json"] };
    PK.live = { showing: T && T.live === lv ? "published" : "embedded", through: T && T.live ? T.live.last_mark || null : null, fetch: LIVE.fetch["data/live.json"] };
    PK.paper = { showing: T && T.paper === pp ? "published" : "embedded", through: T && T.paper ? T.paper.marks_asof || null : null, fetch: LIVE.fetch["data/paper.json"] };
    PK.record = { showing: LIVE.track ? "daily" : "embedded", through: T ? T.asof : null, fetch: LIVE.track ? LIVE.fetch["data/track.json"] : (LIVE.fetch["data/track.json"] && LIVE.fetch["data/track.json"] !== "loaded" ? `${LIVE.fetch["data/track.json"]}; built into the page` : "built into the page"), kept: T && T.kept ? T.kept.asof : null };
    guard("Data packages", renderPackages, $("#pkg-body"));
    if (LIVE.decision) guard("Decision engine", () => { if (typeof dxRebuild === "function") dxRebuild(); });
    if (changed) guard("Search", reindexDesk);
    if (changed && current && RENDER[current]) guard(TAB_NAME[current], RENDER[current]);
    if (changed && typeof renderBrief === "function" && $("#brief")) guard("Brief", renderBrief, $("#brief"));   // v0.47: the Do card cited the snapshot's decision
    if (current) guard("Snapshot badge", () => snapBadge(current));
  });
  // v0.47: two library desks said things the daily files contradict (the filings engine "awaiting first run", one of
  // eight data sources reachable). Both files are published every day; the library now reads them.
  const filingsOk = (f) => !!(f && typeof f.built === "string" && Array.isArray(f.tests) && f.tests.length && f.universe && fin(f.universe.tickers_ever) && f.coverage && fin(f.coverage.months) && f.fakes && fin(f.n_hypotheses));
  const connOk = (c) => !!(c && Array.isArray(c.sources) && c.sources.length && c.sources.every((r) => r && typeof r.source === "string" && typeof r.ok === "boolean"));
  if (!CORE) Promise.all([loadJSON("data/filings.json"), loadJSON("data/connections.json"), loadJSON("data/hedges.json")]).then(([fl, cn, hj]) => {
    if (hj && hj.inputs && typeof hj.inputs === "object") { LIVE.hedges = hj; guard("Hedge inputs", renderHedgeInputs, $("#hb-inputs")); }
    if (fl && filingsOk(fl) && typeof SNAP28 !== "undefined" && SNAP28 && SNAP28.filings && typeof SNAP28.filings === "object") {
      SNAP28.filings.run = fl; SNAP28.filings.status = "run"; LIVE.filings = fl;
      if (current === "filings") guard("Filings", renderFilings, $("#fl-tiles"));
    } else if (fl) LIVE.problems.push("filings.json did not match the expected shape; the page keeps the filings snapshot");
    if (cn && connOk(cn)) {
      LIVE.connections = cn;
      const t = $("#an-tiles"); if (t) t.replaceChildren();
      if (current === "analysis") guard("Technicals and fundamentals", renderAnalysisDesk, $("#an-tiles"));
    } else if (cn) LIVE.problems.push("connections.json did not match the expected shape; the page keeps the connection snapshot");
    if (current) guard("Snapshot badge", () => snapBadge(current));
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

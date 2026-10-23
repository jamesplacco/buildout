  /* =====================================================================================
     guide.js (v0.18): how to find your way. Every desk opens with what it answers, when to open it and how to read
     it, and ends with the next desk in reading order; a map lays out every desk by group; the band shows how far
     down the desk you are and which section you are in. Sections are numbered so a desk reads in order.
     ===================================================================================== */
  const GUIDE_GROUPS = {"today": "The daily read: what changed, what it means, and what to watch.", "decide": "Turn evidence into sized, written-down decisions, and score them afterward.", "markets": "How bonds, rates, options and hedges work, with tools to price them.", "research": "Tests, filings and findings behind the desk's views, plus thinkers and theses.", "reference": "How the engine runs, its code, how it was built, and definitions."};
  const DESK_GUIDE = {"geometry": {"q": "Does the shape of the market (its risk structure, its factors, its topology) say anything about what comes next?","use": "When someone says today looks like a past year, or reaches for an exotic signal, and you want the honest test.","read": "Start with the era map and today's analogs, then the placebo: random pasts help as much as similar ones. The test table is the verdict.","level": "deep"},"matrix": {"q": "How does the engine run on matrix multiplication, and what does it buy?","use": "When you want to see why the engine is fast, what the mind computes when it thinks, or what Pearl's matrix-multiplication mining means for the buildout.","read": "Start with the tiles, then run the whole board in your browser. The table compares each step-by-step method with its matrix version; the heatmap is every shock against every holding.","level": "deep"},"portfolio": {"q": "What mix of stocks, Treasuries, gold and cash should the model book hold, and which way of deciding has earned trust?","use": "Open after the Decision engine when the question is the whole mix, the hedge, or how the next ten years could go.","read": "Start with the mix bars, then the regimes and their stock-bond correlation. The policy table and the learner say which process the record supports; the fan and stress tables show the range.","level": "core"},"decision": {"q": "Given everything the engine knows, what exposure should the model book hold, and how far should it trust itself?","use": "Open after the Desk for the single sized call, the regime, the models behind it and their record since 1940.","read": "Read the big number first, then the gate: it says how much of the engine's own optimum reaches the book. Then the drivers and what would flip the call.","level": "start"},"desk": {"q": "How reliable is my bond hedge in this regime, and what changed?","use": "Open first each day to see what changed and what it means for the book.","read": "Start with the answer under the headline and the evidence labels. The correlation gauge shows whether bonds rose when stocks fell; negative means they hedged.","level": "start"},"mind": {"q": "What does the system know about this, and how sure is it?","use": "When you have a question in words and want to see the evidence behind the answer.","read": "Ask a question, then read the evidence on each side with its weight and source, and how fragile the verdict is.","level": "core"},"atlas": {"q": "Which economic series actually drive each other, according to the data?","use": "When you want the links learned from data rather than judged by hand.","read": "Start with the map: each line is a link that survived repeated half-sample tests. Then see what changed in 2022 and what forecasts.","level": "deep"},"ooda": {"q": "Given today's data, what should I do with the book?","use": "Open after the Desk for proposals, the hedges, and when to look again.","read": "Read the four steps in order: what the data says, what it means, the choice, then proposals. Nothing here is an order.","level": "start"},"noteworthy": {"q": "What trends are moving before they become consensus?","use": "When you want early stories to track, with sources to follow live.","read": "Start with the bottom line, then the curve chart: each story's position runs from niche to consensus. Each card lists what to monitor.","level": "core"},"solve": {"q": "Given the evidence and my loss limit, how should I size?","use": "When you want a sized portfolio choice that respects your own loss limit.","read": "Set your limits in the calculator, then read what the evidence supports. Check where the answer changes and how wide the safe region is.","level": "core"},"positions": {"q": "Is the market pricing each holding rationally, and if not, why?","use": "Open before adding to or trimming a name, to see the growth its price requires.","read": "Look at required growth from the reverse DCF, then how often companies that size have achieved it. Bull and bear cases are in points.","level": "core"},"decide": {"q": "Which decisions fire today, and how close is each to flipping?","use": "Open to see each of seven decisions traced from data to rule to trade.","read": "Each card shows dated inputs, the rule, today's action and confidence. Then check how far the data is from flipping the call.","level": "start"},"games": {"q": "How do other players' choices change what happens to my book?","use": "When a crowded trade, capex race or market maker could move against you.","read": "Each section solves one game exactly: why every builder overbuilds, when a crowded trade runs, and what your order tells the market.","level": "deep"},"cardroom": {"q": "What decision math does trading borrow from poker and bargaining?","use": "When you want to practice pot odds, Kelly sizing or bargaining math by hand.","read": "Each calculator runs the engine's own functions. Start with poker equity and pot odds, then Kelly sizing and the risk of ruin.","level": "deep"},"brain": {"q": "If one thing shocks, where does it travel in the system?","use": "When something moved and you want its knock-on effects through to your book.","read": "Start with the map: 34 parts joined by 110 signed links, eleven measured, the rest judged. Shock a node and follow it.","level": "core"},"journal": {"q": "Did my past decisions show skill or just luck?","use": "Log a forecast before the trade, then score it when it closes.","read": "Start with the scorecard. On the calibration chart, points on the diagonal mean your stated odds matched results; below it means overconfident.","level": "core"},"swans": {"q": "How exposed am I to rare crashes, and is protection worth it?","use": "When sizing for tail risk or judging whether a tail hedge pays for itself.","read": "Start with how fat the tails are versus a normal model, then the compound-growth test of whether the hedge pays.","level": "core"},"bonds": {"q": "If the 10-year and 30-year yields move, what happens to bond ETFs?","use": "Start here to learn how bond prices respond to yields, before the Rates desk.","read": "Move the two yield sliders and watch every Treasury ETF reprice. In the TLT grid, blue is a gain, red a loss, against today.","level": "start"},"rates": {"q": "What is the Treasury curve paying, and who sets its price?","use": "When deciding whether and how to own duration in the current curve.","read": "Start with the curve chart and the carry section. Rising real yields with slipping breakevens is the regime where long bonds stop hedging stocks.","level": "core"},"options": {"q": "What does protection cost, and what does it pay?","use": "When pricing a put or setting a yearly budget for tail insurance.","read": "Build the payoff against the book first. Then check if insurance is cheap: implied volatility above realized is the premium you pay for protection.","level": "core"},"hedges": {"q": "Which hedge protects against which kind of selloff?","use": "Open when choosing a hedge for a specific risk, such as an inflation shock.","read": "Start with the matrix: fifteen hedges graded against six scenarios; select any cell for the reasoning. Then size it in the sizing lab.","level": "start"},"making": {"q": "How do market makers earn the spread without holding risk?","use": "When you want to understand trading costs, spreads and the price of liquidity.","read": "Each section is a working model: quoting, adverse selection, square-root execution costs, then a check on whether a passive fill was good.","level": "deep"},"prop": {"q": "Does my trading edge survive costs, and how much should I risk?","use": "When testing a strategy's edge or a funded-account challenge before risking money.","read": "Start with the edge calculator: earnings per trade after costs and trades needed to prove it. Then the challenge simulator and pod shop net returns.","level": "deep"},"securities": {"q": "Which risks does each security carry, and who gets paid first?","use": "Check a security's risks and its job in the book before sizing it.","read": "Start with who gets paid first in the capital structure, then the thirty security cards and their risk drivers.","level": "core"},"insurers": {"q": "Why do insurers matter for AI financing and long bonds?","use": "When tracking long-end bond demand or private credit risk tied to data centers.","read": "Read how an insurer makes money, then the data-center financing chain. Private credit is where stress shows first; six balance sheets come last.","level": "core"},"analysis": {"q": "Which chart signals have actually worked, and what do the filings say?","use": "When checking a technical signal or a company's ratios before acting on either.","read": "Each signal is scored on the asset's own history; the composite weights only signals that worked. Ratios and Piotroski, Altman, Beneish scores come from filings.","level": "core"},"labs": {"q": "Do the trading rules people repeat hold up on 156 years?","use": "When someone cites a moving average, RSI, P/E or seasonal rule as an edge.","read": "Start with today's readings, then each test. The final table lists every p-value, corrected for the many variants tried.","level": "deep"},"ml": {"q": "Can machine learning forecast next year's stock market return?","use": "When a model claims to forecast returns and you want the honest benchmark.","read": "The scoreboard shows each model out of sample: flexible models lose to the plain average; only the simple ensemble edges it, not yet significantly.","level": "deep"},"reality": {"q": "Do the models' assumptions hold today, and when do conclusions flip?","use": "Open before trusting any model or backtest on the site.","read": "Start with the table of each model's assumptions and whether they hold today. Then see how wrong each can be before the answer changes.","level": "deep"},"edge": {"q": "Where does information edge come from, and what does each source miss?","use": "When choosing which primary sources to read and what to watch in each.","read": "Start with the sources: what each is good for and gets wrong. Then the implied equity risk premium and the story the price needs.","level": "core"},"fundamentals": {"q": "Can the AI builders' cash flow pay for their capex?","use": "When judging whether the buildout is self-funded or depends on outside money.","read": "Key number: $586B of capex against $707B of operating cash flow over twelve months. Then the depreciation wave and backlog from the filings.","level": "core"},"findings": {"q": "What does long-run data show that most portfolios ignore?","use": "Start here for the eight research findings that shape the desk's rules.","read": "Each finding gives the claim, the numbers, the method and the caveat, and what it changes. Small samples point a direction; they are not law.","level": "start"},"buyside": {"q": "What did my Oct 21 field manual change on the desk?","use": "When checking the manual's rules, signals and tests against the desk's data.","read": "Start with what the engine changed because of the manual, then where the manual and the data disagree; both figures are shown with the reason.","level": "core"},"physics": {"q": "Is the AI buildout limited by power and construction, not money?","use": "When testing capex plans against grid, turbine and build-time limits.","read": "Start with capex converted to watts, then demand against buildable supply. Megaproject history shows big builds usually run late and over budget.","level": "core"},"theses": {"q": "What are the desk's working theses, and what would prove them wrong?","use": "When you want each research position with its evidence, hedge and disconfirming data.","read": "Each thesis lists evidence, an expression, a hedge and the data that would change the desk's mind. These are research positions, not recommendations.","level": "core"},"legends": {"q": "What would great investors make of today's data?","use": "When you want each legend's core rule and their read on today.","read": "Start with what the council says today, then each legend's idea in plain words and the rule it adds to the engine.","level": "deep"},"lenses": {"q": "Which outside thinkers shaped the engine's rules?","use": "When you want to trace a rule back to the thinker behind it.","read": "Each lens is one paraphrased line mapped to the rule or view where the engine uses it. A short reference list.","level": "deep"},"field": {"q": "How should a real-world anecdote be tested before it moves the book?","use": "When a supplier, lender or job-site observation seems to signal something early.","read": "Each observation is dated, sourced, and registered before testing, with rival explanations. Nothing here is validated yet; this desk is the method.","level": "deep"},"lab": {"q": "Why does the desk size and hedge the way it does?","use": "When a formula on another desk needs intuition; move the inputs and watch.","read": "Seven interactive toys, each a formula the engine uses. Start with the coin game: it shows leverage, Kelly sizing and ruin in one picture.","level": "deep"},"engine": {"q": "How does the engine run, and what does each number mean?","use": "When you need the daily run's stages, conventions, system status or roadmap.","read": "Reference. Key rule: a value at date t uses data through t's close, and a decision at t earns returns from t+1.","level": "deep"},"engines": {"q": "What runs each day, and what does each engine read and write?","use": "When tracing a number on the site back to the engine and files behind it.","read": "Reference. Each engine is a pure function of dated files, run daily and isolated, recorded with content hashes. Start with the sources-to-decisions flow.","level": "deep"},"code": {"q": "What does the engine's code look like, and who approves trades?","use": "When you want to read a module or the path from question to order.","read": "Appendix. Start with the path from data to a decision a person approves, then read any module. Nothing here places a trade.","level": "deep"},"agents": {"q": "How was the engine built with Claude and its subagents?","use": "When you want to know how the system was built and where that method falls short.","read": "Appendix. Start with the lead, researcher and checker roles, then the release numbers and the agents the page can call.","level": "deep"},"appendix": {"q": "What does this term, formula or data source mean?","use": "When a word, number or source on any desk needs a definition.","read": "Reference. Use the glossary and methods first; the model risk register and hard questions say where each model can break.","level": "deep"}};
  const GUIDE_LEVEL = { start: "Start here", core: "Core desk", deep: "Deep dive" };
  function guideNext(v) {
    const i = VIEWS.indexOf(v);
    return i >= 0 && i < VIEWS.length - 1 ? VIEWS[i + 1] : null;
  }
  function guideLink(v, cls) {
    const a = h("a", cls, TAB_NAME[v] || v);
    a.href = "#" + v;
    return a;
  }
  // the card under each desk's headline, and the way on at the bottom of the desk
  function buildGuides() {
    VIEWS.forEach((v) => {
      const view = $("#view-" + v), g = DESK_GUIDE[v];
      if (!view || !g || view.querySelector(":scope > .dguide")) return;
      const card = h("aside", "dguide");
      card.setAttribute("aria-label", "About this desk");
      const top = h("div", "dguide-top");
      top.append(h("span", "dguide-lvl lvl-" + g.level, GUIDE_LEVEL[g.level] || g.level), h("span", "dguide-grp", `${GROUPS[groupOf(v)].name} · ${GROUPS[groupOf(v)].views.indexOf(v) + 1} of ${GROUPS[groupOf(v)].views.length}`));
      const mapb = h("button", "dguide-map", "All desks");
      mapb.type = "button";
      mapb.addEventListener("click", () => openMap(v));
      top.append(mapb);
      const grid = h("dl", "dguide-grid");
      [["It answers", g.q], ["Open it when", g.use], ["How to read it", g.read]].forEach(([k, t]) => { const d = h("div"); d.append(h("dt", null, k), h("dd", null, t)); grid.append(d); });
      card.append(top, grid);
      const head = view.querySelector(":scope > .vhead, :scope > .t7 > .t7-head, :scope > .hero");
      if (head) head.after(card); else view.prepend(card);
      const nx = guideNext(v);
      if (nx && !view.querySelector(":scope > .dnext")) {
        const foot = h("nav", "dnext");
        foot.setAttribute("aria-label", "Next desk");
        const a = h("a", "dnext-a");
        a.href = "#" + nx;
        a.append(h("span", "dnext-k", groupOf(nx) === groupOf(v) ? `Next in ${GROUPS[groupOf(v)].name}` : `Next: ${GROUPS[groupOf(nx)].name}`), h("b", null, TAB_NAME[nx] || nx), h("span", "dnext-q", (DESK_GUIDE[nx] || {}).q || ""));
        foot.append(a);
        view.append(foot);
      }
    });
  }
  // the map: every desk, by group, with the question it answers
  function buildMap() {
    if ($("#sitemap")) return;
    const dlg = h("div", "sitemap");
    dlg.id = "sitemap"; dlg.hidden = true;
    dlg.setAttribute("role", "dialog"); dlg.setAttribute("aria-modal", "true"); dlg.setAttribute("aria-labelledby", "sitemap-t");
    const box = h("div", "sitemap-box");
    const head = h("div", "sitemap-head");
    head.append(h("p", "eyebrow", "The desk map"), h("h2", null, "Every desk, by the question it answers"));
    head.lastChild.id = "sitemap-t";
    const close = h("button", "btn sitemap-x", "Close");
    close.type = "button";
    close.addEventListener("click", closeMap);
    head.append(close);
    const start = h("div", "sitemap-start");
    start.append(h("span", "flabel", "New here? Read in this order"));
    const ol = h("ol");
    VIEWS.filter((v) => DESK_GUIDE[v] && DESK_GUIDE[v].level === "start").forEach((v) => { const li = h("li"); li.append(guideLink(v), h("span", null, " " + DESK_GUIDE[v].q)); ol.append(li); });
    start.append(ol);
    const cols = h("div", "sitemap-cols");
    GROUP_ORDER.forEach((gk, gi) => {
      const col = h("section", "sitemap-col");
      col.append(h("h3", null, `${gi + 1} · ${GROUPS[gk].name}`), h("p", "hint", GUIDE_GROUPS[gk] || ""));
      const ul = h("ul");
      GROUPS[gk].views.forEach((v) => {
        const li = h("li", "lvl-" + ((DESK_GUIDE[v] || {}).level || "core"));
        li.append(guideLink(v), h("span", null, (DESK_GUIDE[v] || {}).q || ""));
        ul.append(li);
      });
      col.append(ul);
      cols.append(col);
    });
    box.append(head, start, cols, h("p", "hint", "Keys: 0 opens this map, 1 to 5 open a group, / searches, ? lists every shortcut."));
    dlg.append(box);
    dlg.addEventListener("click", (e) => { if (e.target === dlg || (e.target.closest && e.target.closest("a"))) closeMap(); });
    dlg.addEventListener("keydown", (e) => { if (e.key === "Escape") { e.preventDefault(); closeMap(); } });
    document.body.append(dlg);
    const btn = $("#map-open");
    if (btn) btn.addEventListener("click", () => openMap(current));
  }
  let mapReturn = null;
  function openMap(v) {
    buildMap();
    const d = $("#sitemap");
    mapReturn = document.activeElement;
    d.querySelectorAll("a").forEach((a) => a.toggleAttribute("aria-current", a.getAttribute("href") === "#" + v));
    d.hidden = false;
    document.documentElement.classList.add("map-open");
    const here = d.querySelector('a[aria-current]') || d.querySelector("a");
    if (here) here.focus();
  }
  function closeMap() {
    const d = $("#sitemap");
    if (!d || d.hidden) return;
    d.hidden = true;
    document.documentElement.classList.remove("map-open");
    if (mapReturn && mapReturn.focus) mapReturn.focus();
  }
  // where you are inside a desk: a thin progress line under the band and the current section's name
  const GPOS = { heads: [], raf: 0 };
  function guideOnShow(v) {
    const view = $("#view-" + v), here = $("#sub-here");
    GPOS.heads = view ? [...view.querySelectorAll(":scope > .section > .section-head h2, :scope > section > .section-head h2")] : [];
    if (here) here.textContent = "";
    guideProgress();
    deskbarFor(v);
  }
  function guideHere() {
    const here = $("#sub-here");
    if (!here) return;
    let cur = null;
    for (const x of GPOS.heads) if (x.getBoundingClientRect().top < 140) cur = x;
    here.textContent = cur ? cur.textContent : "";
    here.hidden = !cur;
  }
  function guideProgress() {
    cancelAnimationFrame(GPOS.raf);
    GPOS.raf = requestAnimationFrame(() => {
      const bar = $("#readbar");
      if (!bar) return;
      const max = document.documentElement.scrollHeight - innerHeight;
      bar.style.transform = `scaleX(${max > 0 ? Math.min(1, Math.max(0, scrollY / max)) : 0})`;
      guideHere();
      deskbarScroll();
    });
  }
  function wireGuide() {
    buildGuides();
    buildMap();
    buildDeskbar();
    addEventListener("scroll", guideProgress, { passive: true });
    addEventListener("keydown", (e) => {
      if (e.key !== "0" || e.metaKey || e.ctrlKey || e.altKey) return;
      const t = e.target;
      if (t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName))) return;
      if (!$("#keys").hidden || (typeof KY === "object" && KY && KY.mode && KY.mode !== "default")) return;
      e.preventDefault();
      const d = $("#sitemap");
      if (d && !d.hidden) closeMap(); else openMap(current);
    });
  }
  // the floating desk bar: the way back, where you are, the map and the way on, following the reader down the desk
  function buildDeskbar() {
    if ($("#deskbar")) return;
    const bar = h("nav", "deskbar");
    bar.id = "deskbar";
    bar.setAttribute("aria-label", "Desk navigation");
    const prev = h("a", "db-prev"), here = h("button", "db-here"), map = h("button", "db-map"), next = h("a", "db-next");
    here.type = "button"; map.type = "button";
    here.title = "Back to the top of this desk";
    here.addEventListener("click", () => scrollTo({ top: 0, behavior: calmMotion() ? "auto" : "smooth" }));
    map.addEventListener("click", () => openMap(current));
    const ic = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    ic.setAttribute("viewBox", "0 0 16 16"); ic.setAttribute("width", "17"); ic.setAttribute("height", "17"); ic.setAttribute("aria-hidden", "true");
    ic.innerHTML = '<path d="M1.5 3.5l4-1.5 5 1.5 4-1.5v10.5l-4 1.5-5-1.5-4 1.5z M5.5 2v10.5 M10.5 3.5V14" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"></path>';
    map.append(ic, h("span", "db-map-l", "All desks"));
    map.setAttribute("aria-label", "All desks");
    bar.append(prev, h("span", "db-sep"), here, h("span", "db-sep"), map, next);
    document.body.append(bar);
  }
  const calmMotion = () => !window.matchMedia || window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  function deskbarFor(v) {
    buildDeskbar();
    const bar = $("#deskbar"), i = VIEWS.indexOf(v), pv = i > 0 ? VIEWS[i - 1] : null, nx = guideNext(v);
    const prev = bar.querySelector(".db-prev"), next = bar.querySelector(".db-next"), here = bar.querySelector(".db-here");
    prev.replaceChildren(h("span", null, "←"), h("span", "db-label", pv ? TAB_NAME[pv] : ""));
    prev.href = pv ? "#" + pv : "#desk";
    prev.hidden = !pv;
    prev.setAttribute("aria-label", pv ? `Previous desk: ${TAB_NAME[pv]}` : "");
    next.replaceChildren(h("span", "db-label", nx ? TAB_NAME[nx] : ""), h("span", null, "→"));
    next.href = nx ? "#" + nx : "#desk";
    next.hidden = !nx;
    next.setAttribute("aria-label", nx ? `Next desk: ${TAB_NAME[nx]}` : "");
    here.replaceChildren(h("b", null, TAB_NAME[v] || v), h("small", null, ""));
    deskbarScroll();
  }
  function deskbarScroll() {
    const bar = $("#deskbar");
    if (!bar) return;
    // shown past the hero while reading back up or resting; tucked away while scrolling down, so it never sits on content
    const y = scrollY, down = y > (deskbarScroll.lastY || 0) + 4, up = y < (deskbarScroll.lastY || 0) - 4;
    if (down) deskbarScroll.tucked = true; else if (up) deskbarScroll.tucked = false;
    deskbarScroll.lastY = y;
    const nearEnd = y + innerHeight > document.documentElement.scrollHeight - 240;
    const show = y > 420 && (!deskbarScroll.tucked || nearEnd) && !document.body.classList.contains("printing");
    bar.classList.toggle("show", show);
    bar.setAttribute("aria-hidden", show ? "false" : "true");
    bar.querySelectorAll("a, button").forEach((x) => { x.tabIndex = show ? 0 : -1; });
    const sm = bar.querySelector(".db-here small"), here = $("#sub-here");
    if (sm) sm.textContent = here && here.textContent ? here.textContent : (DESK_GUIDE[current] || {}).q || "";
  }

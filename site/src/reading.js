  /* =====================================================================================
     v0.36: THE READING ROOM. Every outside source the desk reads, chosen for range the way a senior reading list is:
     research and policy, data that sees the buildout before earnings, books, history and podcasts, and the other side.
     Each entry is checked, dated, mapped to the theses and desks it bears on, and says what it changes. Reads SOURCES
     (scripts/snapshot_sources.py from buildout/assets/sources/*.json).
     ===================================================================================== */
  const RR = () => (typeof SOURCES !== "undefined" && SOURCES && Array.isArray(SOURCES.rows) ? SOURCES : null);
  const RR_TYPE = { paper: "Paper", policy: "Policy", data: "Data", book: "Book", history: "History", longform: "Long read", podcast: "Podcast", practitioner: "Practitioner", skeptic: "Skeptic" };
  const RR_STATE = { lane: "all", thesis: "all", all: false };
  const RR_PAGE = 24;
  // the five that change the engine most: picked by hand, each with the rule it adds
  const RR_PICKS = [
    ["hallucinations.pdf", "Back out the revenue that capex and prices imply, and compare it with the usage trend every quarter."],
    ["abstract_id=2460551", "Deflate every backtest's Sharpe ratio by the number of variants tried; the decision engine already does, every new desk must."],
    ["gfsr/2026", "Stress the hyperscalers' earnings at a three-year GPU life, not the six they book."],
    ["credit-market-lens", "Track BDC marks against broadly syndicated loan prices: a widening gap is a stale mark."],
    ["lrb.co.uk/the-paper/v39", "Size the oil-shock hedge by OPEC+ spare capacity, not by the price alone."]];

  function renderReading() {
    const S = RR(), box = $("#rr-list");
    if (!box) return;
    if (!S) { box.replaceChildren(h("p", "empty", "The Reading room is not in this build.")); return; }
    const counts = {}; S.rows.forEach((r) => { counts[r.lane] = (counts[r.lane] || 0) + 1; });
    rsKpi($("#rr-tiles"), Object.keys(S.lanes).map((l) => [String(counts[l] || 0), S.lanes[l], { research: "papers, central banks, the IMF and BIS", data: "trackers that move before earnings", books: "and the history of other buildouts", dissent: "the best case against each thesis" }[l]]));
    // the picks
    const pk = $("#rr-picks"); pk.replaceChildren();
    RR_PICKS.forEach(([key, rule]) => {
      const r = S.rows.find((x) => x.url.toLowerCase().includes(key.toLowerCase()));
      if (!r) return;
      const li = h("li"); const a = h("a", null, r.title); a.href = r.url; a.target = "_blank"; a.rel = "noopener";
      li.append(a, document.createTextNode(` (${r.who}, ${r.date.slice(0, 4)}). `), h("strong", null, "The rule: "), document.createTextNode(rule));
      pk.append(li);
    });
    // filters
    const fl = $("#rr-filters"); fl.replaceChildren();
    const chip = (label, on, fn) => { const b = h("button", "pill" + (on ? " strong" : ""), label); b.type = "button"; b.setAttribute("aria-pressed", on ? "true" : "false"); b.addEventListener("click", fn); return b; };
    const r1 = h("div", "rr-row"); r1.append(h("span", "flabel", "Kind"));
    [["all", "All"]].concat(Object.entries(S.lanes)).forEach(([k, v]) => r1.append(chip(v, RR_STATE.lane === k, () => { RR_STATE.lane = k; renderReading(); })));
    const r2 = h("div", "rr-row"); r2.append(h("span", "flabel", "Thesis"));
    [["all", "All"]].concat(THESES.map((t) => [t.id, t.id.toUpperCase()])).forEach(([k, v]) => {
      const b = chip(v, RR_STATE.thesis === k, () => { RR_STATE.thesis = k; renderReading(); });
      if (k !== "all") b.title = (THESES.find((t) => t.id === k) || {}).t || "";
      r2.append(b);
    });
    fl.append(r1, r2);
    // the list
    const rows = S.rows.filter((r) => (RR_STATE.lane === "all" || r.lane === RR_STATE.lane) && (RR_STATE.thesis === "all" || r.bears_on.includes(RR_STATE.thesis)));
    const th = RR_STATE.thesis !== "all" ? THESES.find((t) => t.id === RR_STATE.thesis) : null;
    const shown = RR_STATE.all || rows.length <= RR_PAGE ? rows : rows.slice(0, RR_PAGE);
    $("#rr-count").textContent = `${rows.length} of ${S.rows.length} sources${th ? ` on ${th.id.toUpperCase()}: ${th.t}` : ""}${shown.length < rows.length ? `; showing the first ${shown.length}` : ""}.`;
    box.replaceChildren();
    shown.forEach((r) => {
      const c = h("article", "rr-card" + (r.lane === "dissent" ? " against" : ""));
      const top = h("div", "rr-top"); top.append(h("span", "rr-type", RR_TYPE[r.type] || r.type), h("span", "rr-date", r.date.length > 4 ? isoNice(r.date) : r.date));
      const t = h("h3"); const a = h("a", null, r.title); a.href = r.url; a.target = "_blank"; a.rel = "noopener"; t.append(a);
      const tags = h("p", "rr-tags");
      r.bears_on.forEach((b) => { const x = h("a", "rr-tag", /^t\d/.test(b) ? b.toUpperCase() : (TAB_NAME[b] || b)); x.href = "#" + b; tags.append(x); });
      const ch = h("p", "rr-changes"); ch.append(h("strong", null, r.lane === "dissent" ? "What would make the desk agree: " : "What it changes: "), document.createTextNode(r.changes));
      c.append(top, t, h("p", "rr-who", r.who), h("p", "rr-claim", r.claim), ch, tags);
      box.append(c);
    });
    const more = $("#rr-more"); more.replaceChildren();
    if (shown.length < rows.length) { const b = h("button", "pill strong", `Show all ${rows.length}`); b.type = "button"; b.addEventListener("click", () => { RR_STATE.all = true; renderReading(); }); more.append(b); }
    else if (RR_STATE.all && rows.length > RR_PAGE) { const b = h("button", "pill", `Show the first ${RR_PAGE}`); b.type = "button"; b.addEventListener("click", () => { RR_STATE.all = false; renderReading(); }); more.append(b); }
  }

  /* v0.36: the railway test on the Fundamentals desk (buildout/accounting.py required_revenue; tests check parity) */
  const RQ_CLOUD_RUN = (46.0 + 30.7 + 63.9) * 4;   // $B a year: Q3 2026 AWS, Google Cloud, Microsoft Cloud, annualized
  function requiredRevenue(capex, life, r, m) { const op = capex * (1 / life + r); return { op, rev: op / m }; }
  function renderRailway() {
    const c = readRange("#rq-c"), L = readRange("#rq-l"), r = readRange("#rq-r"), m = readRange("#rq-m");
    if (!fin(c)) return;
    $("#rq-c-v").textContent = "$" + fx(c, 0) + "B"; $("#rq-l-v").textContent = fx(L, 1) + " years"; $("#rq-r-v").textContent = pctPlain(r, 1); $("#rq-m-v").textContent = pctPlain(m, 0);
    const q = requiredRevenue(c, L, r, m), ratio = q.rev / RQ_CLOUD_RUN;
    rsKpi($("#rq-tiles"), [["$" + fx(q.rev, 0) + "B", "Revenue a year this vintage needs", `operating profit of $${fx(q.op, 0)}B at a ${pctPlain(m, 0)} margin`],
      ["$" + fx(RQ_CLOUD_RUN, 0) + "B", "What the three clouds bill a year", "Q3 2026, annualized; includes non-AI work"],
      [fx(ratio, 2) + "x", "Needed over billed", "the 1840s railway mania stood near 4x"]]);
    const out = $("#rq-out");
    out.className = "sentence " + (ratio > 1 ? "warn" : "ok");
    out.textContent = `At a ${fx(L, 1)}-year life and a ${pctPlain(r, 1)} cost of capital, one year of capex ($${fx(c, 0)}B) needs about $${fx(q.rev, 0)}B of revenue a year, ${ratio >= 1 ? `${fx(ratio, 2)} times` : `${pctPlain(ratio, 0)} of`} everything the three clouds now bill, before the 2024 and 2025 spending earns anything. ${ratio < 2 ? "That is a stretch, not a mania: the railway test's 4x is far away." : "That is mania territory by the railway test."}`;
    $("#rq-presets").querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", Number(b.dataset.l) === L && Math.abs(Number(b.dataset.m) - m) < 1e-9 ? "true" : "false"));
  }
  function bindRailway() {
    const f = $("#rq-c");
    if (!f || f._bound) return;
    f._bound = true;
    ["#rq-c", "#rq-l", "#rq-r", "#rq-m"].forEach((id) => $(id).addEventListener("input", renderRailway));
    $("#rq-presets").querySelectorAll("button").forEach((b) => b.addEventListener("click", () => { $("#rq-l").value = b.dataset.l; $("#rq-m").value = b.dataset.m; renderRailway(); }));
    renderRailway();
  }

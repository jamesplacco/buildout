  /* =====================================================================================
     digest.js (v0.24): the Research digest desk. Every checked knowledge item dated in the last fortnight (DIGEST24,
     scripts/snapshot_v24.py), grouped by the question it bears on, each with its date, publisher and source. The
     "read" under each group is the desk's reading as shipped with this version; the items are the evidence.
     ===================================================================================== */
  const DG = { cluster: "All" };
  const DG_GROUPS = [
    ["capex_earnings", "The builders' results and capex", "Does the buildout still outrun its cash flow? What the latest quarters and guidance say.", ["fundamentals", "theses", "positions"]],
    ["ai_credit", "How the buildout is financed", "Who is lending, at what price, and where the stress shows first.", ["insurers", "theses", "securities"]],
    ["fed_inflation", "The Fed, inflation and the Treasury market", "What the rate path and the term premium do to the bond hedge.", ["rates", "bonds", "theses"]],
    ["bonds", "Yields and bond-market levels", "The curve the bond lab and the decision engine read.", ["bonds", "rates"]],
    ["tape", "The tape", "What moved, by how much, and whether bonds cushioned stocks when it mattered.", ["desk", "decide", "analysis"]],
    ["power", "Power and physical limits", "Whether megawatts, turbines and construction, not dollars, set the pace.", ["physics", "theses"]],
    ["distribution", "AI adoption and distribution", "Whether the spend is finding paying users.", ["noteworthy", "theses"]],
    ["private_markets", "Private markets", "Venture, private equity and private credit flows into AI.", ["insurers", "edge"]],
    ["commodities", "Oil, gold and commodities", "The energy tail and the inflation sleeve.", ["theses", "hedges"]],
    ["edge_sources", "Sources", "What each source is good for and what it misses.", ["edge"]],
  ];
  // the desk's read of each group, written for this version from the items below it; the items are the evidence, the read is judgment
  const DIGEST_READS = {
    tape: "The week answered the hedge question for one kind of selloff. On Oct 22 the Nasdaq-100 fell 2.86% (QQQ) on an AI growth scare and TLT rose 1.87%; the 10-year par yield fell 17 basis points to 4.96%. On a growth scare, long bonds cushioned stocks. On Oct 23 oil rose and the pair reversed. The 36-month correlation that governs the engine's hedge call is still positive, so one day does not change the regime; it is the counter-evidence Today names. Volatility rose (VIX 19.45, VXN 28.30) but stayed under the 20 line the Decide desk watches. Goldman's prime desk saw three hedge-fund strategies each lose more than 1% on Oct 22 and crowded AI trades cut; BofA's survey had short Treasuries as the second most crowded trade, which is the squeeze that played out.",
    fed_inflation: "Inflation is 3.7% headline and 2.6% core (September CPI), with energy up 20% on the year, and the Cleveland Fed nowcasts 3.75% for October. The Fed hiked to 3.75 to 4.00% on Sep 16, most participants expected another increase by year end, and the market prices about 91% odds of a hold on Oct 28 with a December hike around 76%. Fiscal 2026 net interest ($1.05 trillion) exceeded defense. The Kim-Wright term premium near one point says a fifth of the 5% yield is compensation for duration. A Fed staff note dated Oct 16 finds the stock-bond relationship since 2021 unlike 2000 to 2021 and says the hedging property depends on the inflation environment; that is the engine's position, with the bond hedge off until inflation returns to the band.",
    ai_credit: "The buildout's financing has moved from cash flow to credit. Four hyperscalers issued over $228bn of bonds by Oct 13 (LSEG), hyperscalers are near 10% of investment-grade issuance (IMF), and 78 of 91 of their 2026 bonds trade wider than issue (Reuters). The IMF counts 14 circular deals with about $650bn of debt behind $1.4trn of revenue commitments. Stress shows at the fringe first: CoreWeave's five-year CDS at 1,115 basis points and its 2031 bond at 15.76% on Oct 22, CCC spreads at 13.40% while the broad high-yield index sits at 3.40%. Insurers hold about $1.2trn of private credit (NAIC). The book's hedge for this lane is credit protection and index puts, not long Treasuries.",
    power: "Megawatts, turbines and construction set the pace, not dollars. GE Vernova has 116 GW of gas equipment backlog and slot reservations with about 10 GW of slots left for 2029 and 2030; transformer lead times passed 160 weeks; PJM's 2028 to 2029 auction cleared at its $325 per MW-day cap, 6,831 MW short of the reliability requirement, and would have cleared near $555 uncapped. Nearly 40% of 2026 US data-center projects risk slipping more than three months (SynMax), ERCOT has about 474 GW of large loads asking for interconnection against 9.5 GW approved to energize, and a greenfield build now costs $17.6m per MW before chips. TSMC held 2026 capex at $60bn to $64bn with demand far above supply. For the book this is the thesis that the binding constraint is physical, which favours the bottleneck suppliers over the balance sheets that must borrow to build.",
    capex_earnings: "The quarter's results set the capex ratio the engine watches. See each company's items for the figures the desk reads; the Fundamentals desk carries the trailing twelve months from the filings.",
    distribution: "Adoption items the Noteworthy desk tracks; the question is whether the spend is finding paying users.",
    private_markets: "Flows into AI through venture and private credit; read with the AI credit group.",
    commodities: "Oil is the inflation sleeve's driver and the tail the bond hedge cannot cover; read with the Fed group.",
  };
  const dgDate = (iso) => (typeof isoNice === "function" ? isoNice(iso) : iso);
  const dgFind = (D, id) => (D.items.find((x) => x.id === id) || (Array.isArray(D.older) ? D.older.find((x) => x.id === id) : null) || null);
  function dgValue(v, unit) {
    const u = String(unit);
    if (/^usd$/i.test(u) && Math.abs(v) >= 1e9) return `$${fx(v / 1e9, 2)} bn`;
    if (/^usd$/i.test(u) && Math.abs(v) >= 1e6) return `$${fx(v / 1e6, 1)} m`;
    if (/^usd bn$/i.test(u)) return `$${fx(v, Number.isInteger(v) ? 0 : 1)} bn`;
    if (/^usd m$/i.test(u)) return `$${fx(v, Number.isInteger(v) ? 0 : 1)} m`;
    if (/^percent$/i.test(u)) return `${fx(v, Number.isInteger(v) ? 0 : 2)}%`;
    if (/^basis points$|^bp$/i.test(u)) return `${fx(v, 0)} bp`;
    return `${typeof v === "number" ? v.toLocaleString(undefined, { maximumFractionDigits: 3 }) : v} ${u}`;
  }

  function renderDigest() {
    const D = typeof DIGEST24 !== "undefined" && DIGEST24 && Array.isArray(DIGEST24.items) ? DIGEST24 : null;
    const tiles = $("#dg-tiles");
    if (!tiles) return;
    if (!D || !D.items.length) { tiles.replaceChildren(h("p", "empty", "No research items dated in the last fortnight are in this build.")); return; }
    tiles.replaceChildren();
    const conf = D.items.filter((x) => /^confirmed/.test(x.checked || "")).length, corr = D.items.filter((x) => /^corrected/.test(x.checked || "")).length;
    const dates = D.items.map((x) => x.as_of).sort();
    [[String(D.n), "Checked items", `dated ${dgDate(dates[0])} to ${dgDate(dates[dates.length - 1])}`], [String(D.publishers.length), "Publishers", "primary where the issuer or the agency publishes the figure"],
      [String(Object.keys(D.by_cluster).length), "Questions", "each with the desks that read it"], [`${conf} + ${corr}`, "Confirmed + corrected", "by a second checker who did not see the first agent's notes"]]
      .forEach(([v, k, s]) => { const d = h("div", "at-kpi"); d.append(h("b", null, v), h("span", null, k), h("small", null, s)); tiles.append(d); });
    const sub = $("#dg-sub");
    if (sub) sub.textContent = `${D.n} items since ${dgDate(D.since)}, from ${D.publishers.length} publishers. Each was found on its source page by a research agent and re-checked on the same page by an independent checker; the ones corrected say so.`;
    dgFilter(D);
    dgList(D);
  }

  function dgFilter(D) {
    const box = $("#dg-filter");
    if (!box) return;
    box.replaceChildren();
    const seg = h("div", "seg");
    [["All", `All (${D.n})`]].concat(DG_GROUPS.filter((g) => D.by_cluster[g[0]]).map((g) => [g[0], `${g[1]} (${D.by_cluster[g[0]]})`])).forEach(([id, name]) => {
      const b = h("button", null, name);
      b.type = "button";
      b.setAttribute("aria-pressed", DG.cluster === id ? "true" : "false");
      b.addEventListener("click", () => { DG.cluster = id; dgFilter(D); dgList(D); });
      seg.append(b);
    });
    box.append(seg);
  }

  function dgList(D) {
    const box = $("#dg-list");
    if (!box) return;
    box.replaceChildren();
    const groups = DG_GROUPS.filter((g) => D.by_cluster[g[0]] && (DG.cluster === "All" || DG.cluster === g[0]));
    const reads = typeof DIGEST_READS === "object" ? DIGEST_READS : {};
    groups.forEach(([id, name, q, desks]) => {
      const sec = h("section", "dg-group");
      sec.id = "dg-" + id.replace(/_/g, "-");
      sec.setAttribute("aria-labelledby", sec.id + "-t");
      const head = h("div", "section-head");
      const h2 = h("h2", null, q); h2.id = sec.id + "-t";
      head.append(h("p", "eyebrow", name), h2);
      const links = h("p", "dg-desks");
      links.append(document.createTextNode("Read by: "));
      desks.forEach((d, i) => { const a = h("a", null, (typeof TAB_NAME !== "undefined" && TAB_NAME[d]) || d); a.href = "#" + d; links.append(a); if (i < desks.length - 1) links.append(document.createTextNode(" · ")); });
      head.append(links);
      sec.append(head);
      if (reads[id]) { const p = h("p", "dg-read"); p.append(h("b", null, "The desk's read. "), document.createTextNode(reads[id])); sec.append(p); }
      const ul = h("div", "dg-items");
      // v0.31: the three newest items show; the rest fold under one line, so a question reads in a glance
      const all = D.items.filter((x) => x.cluster === id).slice().sort((a, b) => String(b.as_of).localeCompare(String(a.as_of)));
      const rest = h("div", "dg-items");
      all.forEach((x, i) => {
        const art = h("article", "dg-item");
        art.id = "dg-" + x.id;
        const top = h("div", "dg-top");
        top.append(h("span", "dg-date num", dgDate(x.as_of)), h("span", "dg-pub", x.publisher || ""));
        if (x.ticker) top.append(h("span", "dg-tk", x.ticker));
        if (/^corrected/.test(x.checked || "")) { const c = h("span", "dg-chk", "corrected on check"); c.title = x.checked; top.append(c); }
        const t = h("h3", null, x.title);
        const txt = h("p", "dg-text", x.text);
        const foot = h("div", "dg-foot");
        if (fin(x.value) && x.unit) foot.append(h("span", "dg-val num", dgValue(x.value, x.unit)));
        const a = h("a", "src", x.source_title ? x.source_title.slice(0, 80) : "Source"); a.href = x.source_url; a.target = "_blank"; a.rel = "noopener";
        foot.append(a);
        if (Array.isArray(x.concepts) && x.concepts.length) foot.append(h("span", "dg-tags", x.concepts.slice(0, 4).join(" · ")));
        art.append(top, t, txt, foot);
        (i < 3 ? ul : rest).append(art);
      });
      sec.append(ul);
      if (all.length > 3) {
        const more = h("details", "dg-more"), sm = h("summary", null, `${all.length - 3} more items on this question`);
        more.append(sm, rest);
        sec.append(more);
      }
      box.append(sec);
    });
  }

  /* ---------- the Fundamentals desk's latest-quarter panel: fixed items from the digest, one card each ---------- */
  const FU_LATEST = ["cx-meta-q3-capex-ocf-261021", "cx-meta-2026-capex-guide-261021", "cx-meta-debt-9m-261021", "cx-tsla-q3-cash-261021", "cx-tsla-capex-cut-ap-261021",
    "cx-spcx-q3-capex-261020", "cx-spcx-balance-261020", "cx-orcl-q1fy27-cash-260911", "cx-orcl-rpo-debt-260831", "cx-msft-cy26-capex-175-260729", "cx-googl-equity-debt-raise-260722",
    "cx-amzn-q2-cash-260730", "cx-nvda-q2fy27-cash-260826", "cx-crwv-q2-results-260811", "cx-msft-next-report-261028", "cx-amzn-next-report-261029"];
  function renderFundLatest() {
    const box = $("#fu-latest");
    if (!box) return;
    const D = typeof DIGEST24 !== "undefined" && DIGEST24 && Array.isArray(DIGEST24.items) ? DIGEST24 : null;
    const items = D ? FU_LATEST.map((id) => dgFind(D, id)).filter(Boolean) : [];
    box.replaceChildren();
    if (!items.length) { box.append(h("p", "empty", "The latest releases are not in this build's research digest.")); return; }
    items.forEach((x) => {
      const art = h("article", "dg-item");
      const top = h("div", "dg-top");
      top.append(h("span", "dg-tk", x.ticker || ""), h("span", "dg-date num", dgDate(x.as_of)), h("span", "dg-pub", x.publisher || ""));
      const foot = h("div", "dg-foot");
      const a = h("a", "src", x.source_title ? x.source_title.slice(0, 80) : "Source"); a.href = x.source_url; a.target = "_blank"; a.rel = "noopener";
      foot.append(a);
      art.append(top, h("h3", null, x.title), h("p", "dg-text", x.text), foot);
      box.append(art);
    });
  }

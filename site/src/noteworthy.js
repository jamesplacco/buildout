  /* =====================================================================================
     noteworthy.js (v0.6): what is moving before it is obvious. Curated cards (the desk's read,
     dated and sourced) carry the analysis; the feed scraper (data/feeds.json) adds live heat,
     asymmetry and the latest items from X, Telegram, Substack, Reddit, Hacker News and the wires.
     Item text from feeds is untrusted: it is set with textContent and links must be http(s).
     ===================================================================================== */
  const NW_AS_OF = "Oct 21, 2026";
  const NW_STAGES = ["Niche", "Specialist", "Mainstream", "Consensus"];
  const NW_BLUF = "Physical oil is far tighter than the futures price says, the Fed meets Oct 28 with most officials expecting another hike by year end, and liquidity strain is spreading from private-credit gates toward public spreads. Track the Dated-futures oil gap, the Oct 28 statement and Q3 hyperscaler capex this month.";
  const NW = [
    { id: "oil-physical", n: "Physical oil premium", stage: 1, link: "d-inflation",
      bluf: "Dated Brent, the physical barrel, traded about $27 over futures in mid-October while 2028 to 2030 contracts sit near $63 to $70. The curve prices a temporary shock; consumer prices follow the physical barrel. The desk's oil rule reads 1.50x its five-year average on spot and 1.27x on futures, so the inflation sleeve rests on the inflation leg, not on oil alone.",
      nums: [["Dated Brent vs futures", "$134 vs $107", "IEA, Oct 14", "https://www.vantagemarkets.com/market-news/brent-crude-oil-price-iea-futures-107-dated-134-october-19-2026/"],
        ["Hormuz transits", "4 a day vs 85", "Oct 4, IMF PortWatch", "https://straits.live/briefs/2026-10-09"],
        ["2028 to 2030 Brent futures", "$63 to $70", "early Oct", "https://fxnx.com/en/blog/oil-backwardation-2026-why-brent-s-6-month-spread-topped-20"]],
      watch: [["Dated minus futures", "above $20 stress; below $5 normal"], ["Hormuz transits", "above 40 a day: the premium bleeds out"], ["EIA Short-Term Energy Outlook", "Nov 10"]],
      q: "\"dated brent\" OR hormuz tankers" },
    { id: "fed-hike", n: "Fed second hike", stage: 3, link: "d-gross",
      bluf: "Markets priced a 16 to 18% chance of an October hike on Oct 9 and 75 to 85% by year end; the minutes say most officials see another hike by December. September CPI then printed 3.7%. This is consensus, so the edge is not in the call but in sizing: gross stays under the hiking-regime cap.",
      nums: [["Fed funds", "3.75 to 4.00%", "since Sep 16", "https://political.org/2026/10/12/fed-officials-hope-to-skip-an-october-rate-hike-but-this-weeks-inflation-report-could-upend-that-plan/"],
        ["Hike by year end", "75 to 85%", "market odds, Oct 9", "https://political.org/2026/10/12/fed-officials-hope-to-skip-an-october-rate-hike-but-this-weeks-inflation-report-could-upend-that-plan/"],
        ["CPI, past year", "3.7%", "September, BLS", "https://www.bls.gov/news.release/CPI.htm"]],
      watch: [["FOMC statement", "Oct 28, 2:00 pm ET"], ["GDP and PCE", "Oct 29"], ["October CPI", "Nov 10"]],
      q: "FOMC hike Waller Williams" },
    { id: "private-credit", n: "Private credit gates", stage: 1, link: "d-credit",
      bluf: "BCRED capped redemptions at 5% for a third straight quarter with about $4.3B requested, and 10 of 16 non-traded BDCs hit their caps in Q2. Gated money cannot chase the best vintage, banks cut back-leverage, and the marks are the last thing to move. Public BDC discounts to NAV are the honest price.",
      nums: [["BCRED Q3 requests", "$4.3B, about 10%", "capped at 5%", "https://angelinvestorsnetwork.com/alternative-investments/blackstone-bcred-redemption-cap-q3-2026"],
        ["Non-traded BDCs at the cap", "10 of 16", "Q2 2026, Fitch", "https://angelinvestorsnetwork.com/alternative-investments/blackstone-bcred-redemption-cap-q3-2026"],
        ["Private credit default rate", "6.0%", "record, April (Fitch)", "https://news.bloomberglaw.com/financial-accounting/us-private-credit-defaults-hit-new-record-of-6-in-april-fitch"]],
      watch: [["Requests across the cohort", "above 15% of NAV: widen every private mark"], ["Amended PIK", "rising two quarters running"], ["Q3 10-Q filings", "early November"]],
      q: "BDC redemptions gate PIK" },
    { id: "memory", n: "Memory supercycle", stage: 2, link: "pp-title",
      bluf: "Server DDR5 contracts rose 57% in Q1 and 50% in Q2, and HBM is sold out for 2026; TrendForce expects HBM contract prices to rise steeply again in 2027. Memory is the most cyclical part of semiconductors: own it as a trade with a stop, and treat the first sequential price decline as the exit.",
      nums: [["Server DDR5 contracts", "+57% Q1, +50% Q2", "2026", "https://blog.findchips.com/dram-memory-shortage-2026-pricing-lead-times-where-to-buy/"],
        ["HBM share of DRAM wafers", "22% → 30%", "end-2026 to end-2027", "https://www.trendforce.com/presscenter/news/20260602-13074.html"],
        ["HBM supply", "Sold out for 2026", "Micron", "https://www.poems.com.sg/stock-research/MU/micron-technology-inc-dram-shortage-fuels-pricing-upside"]],
      watch: [["Contract prices", "first sequential decline: exit"], ["Supplier capex", "a jump in new fabs ends cycles"], ["Hyperscaler Q3 capex", "late October"]],
      q: "HBM DRAM contract prices" },
    { id: "power", n: "Grid power ceiling", stage: 1, link: "physics",
      bluf: "PJM's 2027/28 capacity auction cleared at its cap for the second year running, about 6.6 GW (6,623 MW) short of its reliability requirement. The scarce input earns the rent: firm power, turbines and grid equipment collect; merchant data-center developers without secured power pay.",
      nums: [["PJM 2027/28 capacity", "about $333/MW-day", "at the cap", "https://www.voltus.co/blog/pjm-capacity-auction-results-2027-2028"],
        ["Shortfall vs requirement", "6,623 MW (6.6 GW)", "PJM", "https://www.voltus.co/blog/pjm-capacity-auction-results-2027-2028"],
        ["Data centers' share of US power", "4.4% → 6.7 to 12%", "2023 to 2028, LBNL", "https://www.industrialinfo.com/iirenergy/industry-news/article/doe-report-us-data-center-power-demand-could-triple-by-2028--337583"]],
      watch: [["State price caps", "regulatory risk to the long"], ["Interconnection queue", "time to power"], ["Next PJM base auction", "results set 2028/29 prices"]],
      q: "PJM capacity data center power" },
    { id: "depreciation", n: "GPU useful-life reset", stage: 0, link: "bs-depr-title",
      bluf: "Hyperscalers depreciate servers over 5 to 6 years while frontier GPUs earn their keep for 2 to 3. On a $425B 2026 server cohort, a 3-year life adds about $71B a year of expense. Few people model it; one disclosure or SEC comment letter would make it everyone's model.",
      nums: [["2026 server cohort", "$425B", "manual", "https://www.datagravity.dev/p/how-long-does-a-gpu-last"],
        ["3-year life vs 6", "+$71B a year", "computed", "#bs-depr-title"],
        ["Meta's 4 to 5.5-year change", "−$2.9B of 2025 depreciation", "MyCPE", "https://my-cpe.com/insights/accounting-and-auditing/how-meta-turned-a-simple-accounting-tweak-into-a-2-9b-payday"]],
      watch: [["Useful-life notes in 10-Qs", "any shortening"], ["Impairments", "prior-generation GPUs"], ["SEC comment letters", "on server lives"]],
      q: "GPU useful life depreciation hyperscaler" },
    { id: "market-structure", n: "Market structure shift", stage: 1, link: "making",
      bluf: "Half of US share volume now trades off exchange (50.6% in September) and same-day options are two thirds of S&P 500 option volume (66.2% in July, a record). Liquidity has moved to whoever internalizes order flow; the firms that do are posting record revenue.",
      nums: [["Off-exchange share", "50.6%", "September, Cboe", "https://www.cboe.com/insights/posts/market-metrics-that-matter-u-s-cash-equities-september-volume-briefing"],
        ["0DTE share of SPX volume", "66.2%", "July, record", "https://tradeinformer.com/institutional-trading/cboe-reports-july-options-and-fx-growth-as-0dte-reaches-66-2-of-spx-volume"],
        ["Jane Street trading revenue", "$16.1B in Q1", "record (Reuters)", "https://uk.marketscreener.com/news/jane-street-rakes-in-record-first-quarter-trading-haul-of-16-1-billion-sources-say-ce7f5bdbdf8af521"]],
      watch: [["Cboe monthly briefing", "mid-November"], ["0DTE share", "above 70%: gamma-driven intraday moves"], ["Retail activity", "falling since the May-June peak"]],
      q: "0DTE off-exchange market maker" },
    { id: "pods", n: "Pod shop costs and crowding", stage: 1, link: "prop",
      bluf: "Citadel's flagship ran about $4.5B of operating costs in 2025 while net income fell 22%, and pass-through fees take 3 to 10% of NAV a year. High fixed costs force tight stops and crowding in the same factor-neutral longs: the August 2007 setup. Smaller specialists beat the big multistrats in H1 2026.",
      nums: [["Citadel flagship costs", "about $4.5B", "2025", "https://www.hedgeweek.com/?p=100485"],
        ["Pass-through fees", "3 to 10% of NAV", "a year", "https://meanmatch.beehiiv.com/p/the-evolution-of-hedge-fund-fees-from-2-and-20-to-pass-through-models"],
        ["Balyasny 2023", "15.2% gross → 2.8% net", "after $768M of pass-throughs", "https://farview.substack.com/p/the-evolution-of-multi-manager-and"]],
      watch: [["Most-held pod longs", "avoid them into year end"], ["Short interest in crowded names", "rising: unwind risk"], ["Year-end results", "capital rotation"]],
      q: "multistrategy pass-through fees crowding" },
    { id: "consumer", n: "Consumer strain", stage: 2, link: "d-names",
      bluf: "Sentiment printed 46.3 in October's preliminary read against 47.8 expected, near May's record low, while spending has held up. Sentiment has diverged from spending for three years: it matters only when real spending rolls over with it.",
      nums: [["UMich sentiment", "46.3", "October preliminary", "https://investinglive.com/news/us-october-umich-prelim-consumer-sentiment-vs-47-8-expected/"],
        ["Record low", "44.8", "May 2026", "https://www.advisorperspectives.com/dshort/updates/2026/10/09/consumer-sentiment-falls-again-in-october"]],
      watch: [["Final October sentiment", "Oct 23"], ["Real PCE", "two negative months in a row: cut discretionary"], ["Card delinquencies", "rising with rates"]],
      q: "consumer sentiment delinquencies spending" },
    { id: "saas", n: "Agents eat seat-based software", stage: 1, link: "bs-credit-title",
      bluf: "Software loans are about a fifth of direct lending, and a $500B-plus SaaS loan book has 30% maturing by 2028. If AI agents cut seats, net revenue retention falls first, then sponsor equity, then the loans. Public software multiples already fell about 30% from October 2025 to February 2026; private marks have not.",
      nums: [["Software share of direct lending", "about 19%", "BIS", "https://www.bis.org/publ/qtrpdf/r_qt2603v.htm"],
        ["SaaS loans maturing by 2028", "30% of $500B+", "Franklin Templeton", "https://www.franklintempleton.com/articles/2026/institute/software-as-a-service-selloff-and-the-implications-for-private-markets"]],
      watch: [["Net revenue retention", "disclosures in Q3 reports"], ["Software loan marks", "in BDC 10-Qs"], ["Public vs private software marks", "gap above 20 points"]],
      q: "SaaS AI agents seats loans" },
  ];
  // where the scraper looks (mirrors feeds.toml); every link opens the source itself
  const NW_SOURCES = [
    ["x", "The Kobeissi Letter", "KobeissiLetter", "mainstream"], ["x", "Six Sigma Capital", "SixSigmaCapital", "specialist"], ["x", "BowTiedBull", "BowTiedBull", "specialist"],
    ["x", "Nick Timiraos (WSJ, the Fed)", "NickTimiraos", "mainstream"], ["x", "Jim Bianco", "biancoresearch", "specialist"], ["x", "SemiAnalysis", "SemiAnalysis_", "specialist"],
    ["telegram", "Walter Bloomberg", "WalterBloomberg", "mainstream"],
    ["substack", "Bouchaud (microstructure)", "https://bouchaud.substack.com", "niche"], ["substack", "Farview (multi-managers)", "https://farview.substack.com", "niche"],
    ["substack", "EventHorizonIQ (BDCs)", "https://eventhorizoniq.substack.com", "niche"], ["substack", "Data Gravity (GPU economics)", "https://www.datagravity.dev", "niche"],
    ["substack", "Doomberg (energy)", "https://doomberg.substack.com", "specialist"], ["substack", "Apricitas Economics", "https://www.apricitas.io", "specialist"],
    ["substack", "Net Interest", "https://www.netinterest.co", "specialist"], ["substack", "The Diff", "https://www.thediff.co", "specialist"],
    ["official", "Federal Reserve", "https://www.federalreserve.gov/newsevents/pressreleases.htm", "official"], ["official", "BLS", "https://www.bls.gov/bls/newsrels.htm", "official"],
    ["official", "EIA", "https://www.eia.gov/todayinenergy/", "official"], ["official", "SEC", "https://www.sec.gov/newsroom/press-releases", "official"],
    ["reddit", "r/quant", "https://www.reddit.com/r/quant/", "niche"], ["reddit", "r/investing", "https://www.reddit.com/r/investing/", "mainstream"],
    ["hn", "Hacker News", "https://news.ycombinator.com/", "specialist"],
  ];
  const nwX = (q) => "https://x.com/search?" + new URLSearchParams({ q, f: "live" }).toString();
  const nwSub = (q) => "https://substack.com/search/" + encodeURIComponent(q) + "?searching=all_posts";
  const nwNews = (q) => "https://news.google.com/search?" + new URLSearchParams({ q }).toString();
  const nwTg = "https://t.me/s/WalterBloomberg";
  const safeUrl = (u) => (typeof u === "string" && /^https?:\/\//.test(u) ? u : u && u[0] === "#" ? u : null);
  function nwLive(id) { const f = LIVE.feeds; return f && Array.isArray(f.themes) ? f.themes.find((t) => t && t.id === id) : null; }
  function stageMeter(stage) {
    const m = h("div", "stage");
    m.setAttribute("role", "img");
    m.setAttribute("aria-label", `Diffusion: ${NW_STAGES[stage]}`);
    NW_STAGES.forEach((s, i) => { const seg = h("span", i <= stage ? "on" : null); seg.title = s; m.append(seg); });
    m.append(h("small", null, NW_STAGES[stage] + (stage <= 1 ? " · asymmetric" : stage === 3 ? " · priced" : "")));
    return m;
  }
  function liveSpark(series) {
    const vals = (series || []).filter(fin);
    if (vals.length < 2) return null;
    return spark({ dates: vals.map((_, i) => new Date(Date.UTC(2026, 0, 1 + i)).toISOString().slice(0, 10)), values: vals }, 96, 24);
  }
  function nwCard(t) {
    const c = h("article", "nw");
    c.id = "nw-" + t.id;
    const top = h("div", "nw-top");
    top.append(h("h3", null, t.n), stageMeter(t.stage));
    c.append(top, h("p", "nw-bluf", t.bluf));
    const dl = h("div", "nw-nums");
    t.nums.forEach(([k, v, when, url]) => {
      const d = h("div");
      const a = safeUrl(url);
      const val = h("b", null, v);
      d.append(val, h("span", null, k), (() => { const s = h("small"); if (a) { const l = h("a", null, when); l.href = a; s.append(l); } else s.textContent = when; return s; })());
      dl.append(d);
    });
    c.append(dl);
    const lv = nwLive(t.id);
    const live = h("div", "nw-live");
    if (lv && fin(lv.heat)) {
      live.append(h("span", "badge", "Live"), h("span", null, `${lv.count24 || 0} mentions in 24h · heat ${sg(lv.heat, 1)}σ · niche skew ${sg((lv.asymmetry || 0) * 100, 0)} pts · ${lv.breadth || 0} platforms` + (fin(lv.lead_days) ? ` · niche leads by ${lv.lead_days}d` : "")));
      const sp = liveSpark(lv.series);
      if (sp) live.append(sp);
      if (lv.noteworthy) c.classList.add("hot");
    } else live.append(h("span", null, "Heat, niche skew and lead time fill in after the first feeds run."));
    c.append(live);
    const w = h("ul", "nw-watch");
    t.watch.forEach(([k, v]) => { const li = h("li"); li.append(h("b", null, k), document.createTextNode(" · " + v)); w.append(li); });
    c.append(h("h4", null, "Monitor"), w);
    const links = h("div", "nw-links");
    [["X, live", nwX(t.q)], ["Substack", nwSub(t.q)], ["News", nwNews(t.q)], ["Telegram wire", nwTg]].forEach(([l, u]) => { const a = h("a", "pill", l); a.href = u; a.rel = "noopener"; links.append(a); });
    const go = h("a", "pill strong", "Where the desk uses it →");
    go.href = "#" + t.link;
    links.append(go);
    c.append(links);
    if (lv && Array.isArray(lv.top) && lv.top.length) {
      const ul = h("ul", "nw-items");
      lv.top.slice(0, 3).forEach((it) => {
        const u = safeUrl(it.url);
        const li = h("li");
        if (u) { const a = h("a", null, String(it.title || "").slice(0, 160)); a.href = u; a.rel = "noopener nofollow"; li.append(a); } else li.append(document.createTextNode(String(it.title || "").slice(0, 160)));
        li.append(h("small", null, ` ${String(it.source || "")} · ${String(it.tier || "")}`));
        ul.append(li);
      });
      c.append(ul);
    }
    return c;
  }
  function buildNoteworthy() {
    const g = $("#nw-grid");
    if (!g) return;
    g.replaceChildren();
    const order = NW.slice().sort((a, b) => {
      const la = nwLive(a.id), lb = nwLive(b.id);
      const sa = (la && la.noteworthy ? 10 : 0) + (la && fin(la.heat) ? la.heat : 0) - a.stage * 0.5, sb = (lb && lb.noteworthy ? 10 : 0) + (lb && fin(lb.heat) ? lb.heat : 0) - b.stage * 0.5;
      return sb - sa;
    });
    order.forEach((t) => g.append(nwCard(t)));
    const f = LIVE.feeds;
    const b = $("#nw-bluf");
    b.replaceChildren(h("strong", null, "BLUF. "), document.createTextNode(NW_BLUF));
    if (f && typeof f.bluf === "string") b.append(h("span", "nw-livebluf", " Scraper, " + (niceDate(String(f.generated_utc || "").slice(0, 10)) || "latest run") + ": " + f.bluf.slice(0, 400)));
    $("#nw-asof").textContent = f ? `Desk read ${NW_AS_OF}; live scores from the feeds run of ${niceDate(String(f.generated_utc || "").slice(0, 10)) || "n/a"} (${(f.sources && f.sources.read) || 0} items read).` : `Desk read ${NW_AS_OF}. Live heat, skew and items appear after the daily feeds run.`;
    // stage map: every trend on the diffusion curve
    const map = $("#nw-map");
    if (map) {
      map.replaceChildren();
      NW_STAGES.forEach((s, i) => {
        const col = h("div", "nw-col");
        col.append(h("span", "eyebrow", s));
        NW.filter((t) => t.stage === i).forEach((t) => { const a = h("a", null, t.n); a.href = "#nw-" + t.id; col.append(a); });
        map.append(col);
      });
    }
    // sources
    const src = $("#nw-sources");
    if (src) {
      src.replaceChildren();
      NW_SOURCES.forEach(([kind, name, ref, tier]) => {
        const u = kind === "x" ? "https://x.com/" + ref : kind === "telegram" ? "https://t.me/s/" + ref : ref;
        const a = h("a", "src-chip " + kind, name);
        a.href = u; a.rel = "noopener";
        a.append(h("small", null, ` ${kind === "x" ? "X" : kind === "hn" ? "HN" : kind[0].toUpperCase() + kind.slice(1)} · ${tier}`));
        src.append(a);
      });
    }
    // latest feed items, newest first
    const box = $("#nw-feed");
    if (box) {
      box.replaceChildren();
      const items = f && Array.isArray(f.items) ? f.items.slice(0, 30) : [];
      if (!items.length) { const e = h("div", "empty"); e.append(h("strong", null, "Live panel: no feed items in this copy."), h("span", null, "The daily run reads every source in feeds.toml and writes data/feeds.json; X needs the X_BEARER_TOKEN secret.")); box.append(e); }
      items.forEach((it) => {
        const row = h("div", "nw-row"), u = safeUrl(it.url);
        const title = u ? Object.assign(h("a", null, String(it.title || "").slice(0, 180)), { href: u, rel: "noopener nofollow" }) : h("span", null, String(it.title || "").slice(0, 180));
        row.append(h("span", "nw-plat " + String(it.platform || "").replace(/[^a-z]/g, ""), String(it.platform || "")), title, h("small", null, `${String(it.source || "")} · ${(it.themes || []).join(", ")}`));
        box.append(row);
      });
    }
  }

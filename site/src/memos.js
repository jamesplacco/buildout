  /* =====================================================================================
     v0.38: MODEL MEMOS AND THE FAILURE LOG. Each model gets one page in the format of an equity pitch: the thesis,
     the variant perception (where it differs from the consensus way of doing it), the evidence, what would prove it
     wrong, and what changed and why. The failure log lists the engine's misses in the order they were found, each
     with what it cost and what changed. Nothing here is computed; every figure is the desk's own, linked.
     ===================================================================================== */
  const MEMOS = [
    { id: "m-vix", n: "The VIX sleeve: insurance for the crash, not the bear market", desk: "hedgetest", since: "v0.39, Nov 5, 2026",
      thesis: "A small long position in VIX futures (VIXY on Robinhood) pays when the AI book crashes and costs a known amount the rest of the time. At 5% of the account it is the cheapest cut to the one-month tail of any hedge tested; it is not a substitute for the call's size.",
      variant: "Most retail VIX hedging is either avoided (the decay is notorious) or sized to feel safe. Here it is sized from the book's own daily record: tail cut per point of growth given up, against puts and the index short on the same days.",
      evidence: "Monthly since 2006, VIX futures moved -0.62 with the Nasdaq-100 and cut 38% of its variance at the best weight, but lost about 20% a year on average and lost money in about two months in three. On the book from 2017 to March 2024, 10% of its value in VIX futures cut the Feb 19 to Mar 23, 2020 loss from 29% to 18% for 1.5 points a year of growth, and moved 2022 from -46% to -45%: only the index short helped there.",
      wrong: "The sleeve fails to gain in the next fast fall of 10% or more in the Nasdaq-100, or its cost over a year exceeds 1.5% of the account; either turns it off (vix_share = 0).",
      changed: "Nov 5: added to the execution defaults at 5% of the account, studied on the Hedge test desk." },
    { id: "m-exec", n: "Execution: a ticket a person approves, placed by the broker's own agent", desk: "execution", since: "v0.39, Nov 5, 2026",
      thesis: "The model should trade only what it can defend line by line. Buildout writes a hashed, checked ticket from the logged call; Robinhood's Trading MCP places it in a separate Agentic account after a person approves the ticket id.",
      variant: "Agentic trading usually hands an assistant a brokerage connection and a goal. Here the assistant gets a ticket it may not alter, a list of checks it cannot skip, and no credential: the broker's agent places orders, the engine never does.",
      evidence: "Robinhood's Agentic account (support pages, Nov 5, 2026) allows long stocks and ETFs and single-leg long options, with no margin, shorting or futures for agents. Every mapping, check and limit is tested (tests/test_v39.py): a halted switch, a non-Agentic account, a stale call, an unlogged call, a missing quote, an unknown holding, too much turnover and an oversized order each block the ticket.",
      wrong: "A ticket is placed that failed a check or was not approved, a fill lands through its limit, or paper tickets drift from what the call says; any of these halts trading until the cause is fixed and logged here.",
      changed: "Nov 5: built in paper mode; live mode is switched on only in the private config." },
    { id: "m-book", n: "Book sizing: the limits set the size", desk: "book", since: "v0.30, Oct 27, 2026",
      thesis: "Size the book from its own names' risk against three hard limits (a 12% worst month in twenty, 20% volatility, a 25% one-year drawdown at 95%), not from a forecast. Today the drawdown cap binds at about 0.59x, or full size with an 85% Nasdaq-100 short.",
      variant: "The usual practice sizes a concentrated tech book by conviction, or by the index's volatility. The nine names carry about 2.7 times the index's one-month tail; a book sized on the index is oversized by the same factor.",
      evidence: "On the names' own prices since 2017, the book at 1.00x breaks all three limits. The walk-forward record recomputes the size every month from data up to that month and charges costs: see the Track record desk for its Sharpe, drawdown and 2022 against holding.",
      wrong: "Walked forward, the limit-sized book earns less per unit of risk than holding and does not cut the drawdown: then the limits cost more than they save. Or the limits keep binding in calm years, which would mean they are set too tight for this book.",
      changed: "Oct 27: the call moved from 1.00x to 0.59x when the book was measured on its own names instead of the S&P 500 (nothing in the market changed; the measurement did). Oct 30: the call became a menu, from 0.59x unhedged to 1.00x with an 85% short, because the choice between them is a judgment about the names, not about risk." },
    { id: "m-bond", n: "The bond hedge selector: off until bonds hedge again", desk: "hedges", since: "v0.2, Oct 2026",
      thesis: "A long Treasury hedge earns its place only when stocks and bonds move apart. Since 2022 they have moved together, so the hedge is off and the Nasdaq-100 short does the work.",
      variant: "The 60/40 habit treats long bonds as the default hedge for an equity book. The record since 1962 says the bond hedged when inflation was below 3% (correlation about -0.17) and added risk above it (about +0.25); since 2021 the correlation has been about +0.35. 2022 was the regime, not an accident.",
      evidence: "On the book's own days since 2017 a bond hedge cut its variance about 3%, against about 90% for a Nasdaq-100 short. The regime study on the Track record desk splits the stock-bond correlation by inflation and policy direction since 1962 and walks a regime-switching hedge ratio forward.",
      wrong: "The 36-month stock-bond correlation falls below -0.10 with inflation easing (the selector's own re-entry rule), or the Fed's October 2026 note is right that the safe-haven property returns once inflation is back near 2%: then the bond is the cheaper hedge and the desk should switch.",
      changed: "Nov 3: the hedge is tested against the alternatives (2-year note, gold, index puts, cash, a short basket of weak AI names) by regime, instead of being assumed. The modelled put was the only hedge that paid in 2022 and cut a quarter to a third of the Nasdaq-100's variance in every regime; a regime-switching bond rule matched the unhedged book rather than improving on it." },
    { id: "m-decision", n: "The decision engine: a forecast with a gate", desk: "decision", since: "v0.19, Oct 22, 2026",
      thesis: "A model forecasts the market's next year from regimes and valuation, and sizes from it, but only as far as its own walked-forward record since 1940 has earned. Today that record earns nothing, so the engine holds the index at 1.00x.",
      variant: "Most allocation models act on their forecast. This one has to beat plain holding out of sample, deflated for the 28 strategies it tried, before it may move the size at all.",
      evidence: "Its edge over holding scores t = 0.35 on monthly data since 1940 against 1.80 needed; the gate has stayed shut in every month on record. A trend overlay that looked free on the full record cost expected utility when re-chosen each year on the record to date, and was rejected.",
      wrong: "The gate opens out of sample (the t crosses the bar on data the engine had not seen), or a simpler rule beats it on the same test. Then the engine's size, not the limits, should set the book.",
      changed: "Oct 24: the trend overlay was dropped after failing its own walk-forward. Oct 27: the engine stopped being the call and became its baseline, cut by the book's limits." },
    { id: "m-vol", n: "Volatility-managed sizing", desk: "book", since: "v0.32, Oct 30, 2026",
      thesis: "Cutting exposure when last month's variance is high (Moreira and Muir, 2017) improves the utility of holding the Nasdaq-100.",
      variant: "The published result is on the market portfolio and has been disputed out of sample (Cederburg and co-authors). The desk tests it as one of twelve variants, deflated for the count.",
      evidence: "On the Nasdaq-100 future since 1999 the headline rule's utility t is 1.76 against a bar of 1.66; from 2003 on it is 0.89. The gain comes from two crashes, 2000 and 2008: a thin record. Today it reads about 1.01x, so it does not change the call.",
      wrong: "The t falls below the bar as new data arrive, or the gain disappears at realistic costs. Two crashes are not a law.",
      changed: "Oct 30: a timing bug was found (exposure changed inside the month instead of at month-end); fixed, the verdict moved from chance to supported, which is why the rule is labelled a reading, not the call." },
    { id: "m-credit", n: "Private credit: the financing lens", desk: "credit", since: "v0.34, Nov 1, 2026",
      thesis: "Private credit is where the AI cycle's losses surface first. Repurchase queues, listed-fund discounts and paid-in-kind income move before marks do.",
      variant: "The consensus reads the record default rate as a credit story. The desk reads it as a financing story for the book: a gated wealth channel raises the price of the next campus.",
      evidence: "Blue Owl's OCIC had 16.8% and OTIC 39% of shares asked out in Q3; the 5% cap divided by the queue reproduces both funds' reported fills. Fitch's record 6.3% default rate is 88% soft restructurings. Peers' queues run 10% to 15%.",
      wrong: "Queues fall back under the 5% cap and listed discounts close to within 5% of NAV, or Fitch's rate falls below 3%. Or the AI tenants keep financing campuses on their own balance sheets at no higher cost.",
      changed: "Nov 2: the lens was extended to the cohort, which showed Blue Owl is the outlier on the queue but the sector on marks. The accuracy pass corrected the Oracle and Hyperion claims." },
    { id: "m-nowcast", n: "The nowcast: early data against the next report", desk: "nowcast", since: "v0.27, Oct 24, 2026",
      thesis: "Facts published early (TSMC's monthly revenue, peers that report first, hyperscaler capex) forecast the book's next quarterly revenue better than persistence.",
      variant: "Sell-side models extrapolate the last quarter. The nowcast reads what is already public and dates every input to when it was knowable.",
      evidence: "The best of 15 walked-forward models cuts the persistence forecast's squared error by 19% (t 2.8), but does not pass the multiple-testing cut. Of 51 hypotheses about whether the market had already priced it, none passed; nor did any of 240 random signals.",
      wrong: "Already partly true: the forecasting gain is not significant after correction, and no pricing edge was found. The memo keeps it as a monitoring tool, not a signal.",
      changed: "Oct 24: published with its null result rather than tuned until something passed." },
    { id: "m-edges", n: "The edge lab: a hypothesis factory with a placebo", desk: "edges", since: "v0.26, Oct 24, 2026",
      thesis: "A machine can propose tens of thousands of candidate edges and an honest gauntlet will keep only the ones that are not luck.",
      variant: "Data mining is usually reported without its denominator. The lab runs the same search on block-shuffled fake markets beside the real ones and calibrates every p-value to the null.",
      evidence: "43,247 candidate edges, 197,337 market-level tests: 12 passed the false-discovery cut, 5 survived every stage, against fewer than 1 expected by luck. None can be tested after 2017.",
      wrong: "The five survivors fail on data after 2017 as it becomes available, or the fake markets start producing survivors at the same rate.",
      changed: "Oct 24: an independent audit changed the null calibration before publication; composites were made to beat their own parts, which removed all five that had passed." },
    { id: "m-futures", n: "Carry and trend in futures", desk: "futures", since: "v0.29, Oct 26, 2026",
      thesis: "Carry and trend across 37 futures markets still pay after costs and beyond simply holding the markets.",
      variant: "Both are well known and often called arbitraged away. The test asks whether they survived publication, within asset classes and in both halves of the record.",
      evidence: "On pysystemtrade's published prices, 1990 to March 2024: 8 of 10 tests pass the false-discovery cut; 3 also beat a passive long, held in both halves, within classes and since publication (12-month trend over time and across markets, cross-sectional carry). Carry over time has faded since 2018.",
      wrong: "The surviving signals lose money for several years after March 2024 on Databento's data, net of costs.",
      changed: "Oct 26: reported with the faded carry signal named, not dropped." },
    { id: "m-railway", n: "The railway test: what one year of capex must earn", desk: "fundamentals", since: "v0.36, Nov 2, 2026",
      thesis: "The AI buildout is a stretch, not a mania: one year of the four hyperscalers' capex needs about 93% of what the three clouds bill (1.5x at a three-year GPU life), where the 1840s railway mania priced in about 4x.",
      variant: "The bubble debate argues from valuations. Odlyzko's test argues from the revenue the spending must earn, against what is already billed.",
      evidence: "About $730B of 2026 capex at a six-year life, a 9% cost of capital and Google Cloud's 36% margin needs about $520B a year; AWS, Google Cloud and Microsoft Cloud bill about $562B annualized. It covers one vintage only.",
      wrong: "Cloud revenue stalls while capex keeps rising, pushing the ratio above 2x, or depreciation lives are cut toward three years. Either moves it toward the railway mania's ratio.",
      changed: "Nov 2: built from the Reading room's sources." },
  ];

  const FAILURES = [
    { d: "2026-10-21", v: "v0.5", what: "A missing October 2025 CPI print (the government shutdown) turned recent 12-month inflation into 13 months, and Shiller's preliminary CPI overrode the official series.", cost: "The inflation line that gates the bond hedge was misread for every month after the gap.", fix: "Official series take precedence; a missing month is a gap, never an interpolation." },
    { d: "2026-10-24", v: "v0.24", what: "The trend overlay, chosen on the full record, looked free; walked forward it cost expected utility (t negative).", cost: "Had it shipped, the call would have rested on a rule fitted with hindsight.", fix: "Every rule is now re-chosen each year on the record to date before it may enter." },
    { d: "2026-10-27", v: "v0.30", what: "The Desk sized the S&P 500, which the decision engine models, while the book is nine AI names. Measured on its own names, the book at 1.00x broke all three of its limits.", cost: "For a week the headline call was 1.00x when the book's own risk allowed 0.59x.", fix: "The book is measured on its names' own prices; the index row is information only." },
    { d: "2026-10-27", v: "v0.30", what: "The deflated Sharpe ratio returned no number (not-a-number); betas went blank on short histories; an AI factor had been built from the book itself.", cost: "A circular factor flattered the book's exposures.", fix: "External factors only (Nasdaq-100, semis net of the market, a 20-year bond)." },
    { d: "2026-10-29", v: "v0.31", what: "The tests failed on GitHub: pytest 9.2 rejected an approximate comparison of nested lists.", cost: "The CI badge was red for a day.", fix: "Comparison flattened; CI is reproduced on the latest packages before release." },
    { d: "2026-10-30", v: "v0.32", what: "The volatility rule changed exposure inside the month (calendar month-end timestamps), a timing leak.", cost: "The verdict moved from chance to supported once fixed: the leak had hidden a real result, not invented one, but it could have gone the other way.", fix: "Exposure is set at the last close of a month and held; a test fixes March's exposure at February's close." },
    { d: "2026-11-01", v: "v0.33", what: "The scheduled daily runs after Oct 30 committed only their status file: a data step hung on a blocked site until the job's time limit and every later step was skipped. Nobody was told.", cost: "Three days of runs produced nothing, silently.", fix: "A per-site circuit breaker, a time limit on every step, and (v0.38) a failing run now fails the job and opens a GitHub issue." },
    { d: "2026-11-02", v: "v0.35.1", what: "Apollo's xAI chip financing was shown as $35B; it was $3.5B, a headline that dropped the decimal.", cost: "A tenfold error on two desks for a week.", fix: "Three independent checkers verified about 250 claims; figures now cite the primary release." },
    { d: "2026-11-02", v: "v0.35.1", what: "The private credit desk said Oracle's campuses were financed by other lenders; Blue Owl co-owns the Abilene campus Oracle leases. It also stated Hyperion's loan to value and debt cover as disclosed; they were a discussant's estimate.", cost: "The transmission table understated Oracle's exposure.", fix: "Corrected; estimates are labelled with whose they are." },
    { d: "2026-11-02", v: "v0.36", what: "Thesis cards showed the last scorecard in the list as the latest, and new entries had been added at the front: t1 and t6 displayed their Oct 27 verdicts after newer ones existed.", cost: "Two theses read a week stale.", fix: "Scorecards sort by date; a test checks it." },
    { d: "2026-11-02", v: "v0.36", what: "Thesis t9 said AI financing had rotated from bonds; LSEG counted record hyperscaler bond issuance, more than double 2025. Thesis t11 said compute prices were deflating; H100 rents rose about 40% from October to March.", cost: "Two theses overstated their case.", fix: "t9 retitled widened, not rotated; t11 restated per token, not per GPU-hour; each thesis now carries its strongest dissent." },
    { d: "2026-11-03", v: "v0.38", what: "The first entry of the new call ledger claimed the call took effect the day after its data (Oct 26) although it was written on Nov 3: a backdated call.", cost: "Caught before it was committed.", fix: "A call now governs from the first trading day after it is written; the ledger's verify step rejects any entry effective on or before the day it was written." },
    { d: "2026-11-03", v: "v0.38", what: "The sizing limits passed an annual volatility into a monthly expected-shortfall formula, so every walk-forward size came out about 3.5 times too small.", cost: "Caught in the first walk-forward run, before any figure was published.", fix: "The volatility is converted to monthly before the formula; a synthetic test checks that size falls after a volatility jump and never uses tomorrow's data." },
    { d: "2026-11-03", v: "v0.38", what: "Shiller's monthly file pads its last three years with zeros for the dividend, CPI and bond yield. The zero yield read as a 33% one-month bond gain in October 2023, inside a stock selloff, and the regime study ended there.", cost: "Caught while reading the hedge study's numbers: the bond looked like a hedge since 2021 on one fictitious month.", fix: "Zeros are treated as missing, CPI and the 10-year yield are filled from their own series to September 2026, and the price validator rejects non-positive values." },
    { d: "2026-11-03", v: "v0.38", what: "The value-creation plan's figures were checked against sources: Rhode Island has no Clean Heat Standard law (the bill was held for study), the federal service-disabled veteran set-aside goal is 5%, not 3%, and a 10% EBITDA move at 90% debt swings equity about 100% at close, not 30%.", cost: "The lever page would have priced heat-pump demand and a set-aside on the wrong rules.", fix: "The page shows each claim with its verdict and source, and the calculator defaults to the corrected figures (exit near 6x, not 7 to 8x)." },
  ];

  function renderMemos() {
    const box = $("#mm-list");
    if (!box || box.childElementCount) return;
    MEMOS.forEach((m) => {
      const c = h("article", "memo"); c.id = m.id;
      const head = h("div", "memo-head"); const a = h("a", "src", "Open the desk"); a.href = "#" + m.desk;
      head.append(h("h3", null, m.n), h("span", "memo-since", m.since), a);
      const row = (k, v) => { const d = h("div", "memo-row"); d.append(h("h4", null, k), h("p", null, v)); return d; };
      c.append(head, row("Thesis", m.thesis), row("Variant perception", m.variant), row("Evidence", m.evidence), row("What would prove it wrong", m.wrong), row("What changed, and why", m.changed));
      box.append(c);
    });
    fillTable($("#mm-fail"), ["Found", "Release", "What went wrong", "What it cost", "What changed"], FAILURES.slice().reverse().map((f) => [isoNice(f.d), f.v, f.what, f.cost, f.fix]), 3);
    $("#mm-fail-n").textContent = `${FAILURES.length} misses logged since Oct 21, 2026, newest first. A miss is anything the desk said or did that was wrong, found by its own tests, its own audits or a reader.`;
  }

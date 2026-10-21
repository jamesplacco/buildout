  /* =====================================================================================
     DATA: dated snapshot (every figure carries its source) and the desk's content
     ===================================================================================== */
  const SRC = {
    treasury: ["US Treasury", "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/2026/all?type=daily_treasury_yield_curve"],
    macroradar: ["FRED via MacroRadar", "https://www.macroradar.io/as-of/2026-10-07"],
    fxstreet: ["UOB via FXStreet", "https://www.fxstreet.com/news/federal-reserve-more-hikes-ahead-after-october-pause-uob-202610081303"],
    mof: ["Ministry of Finance, Japan", "https://www.mof.go.jp/english/policy/jgbs/auction/calendar/eresul/eresul20261008.htm"],
    fortune: ["Fortune", "https://fortune.com/article/current-price-of-gold-10-13-2026/"],
    rio: ["Rio Times", "https://www.riotimesonline.com/crypto-markets-bitcoin-majors-friday-october-16-2026/"],
    tipswatch: ["Tipswatch", "https://tipswatch.com/2026/09/17/10-year-tips-reopening-gets-real-yield-of-2-653-highest-in-nearly-18-years/"],
    roic: ["ROIC (Reuters)", "https://www.roic.ai/news/wall-streets-fear-gauge-spikes-vix-jumps-to-four-month-high-as-inflation-fears-and-ai-debt-worries-rattle-markets-10-16-2026"],
    fred: ["FRED", "https://fred.stlouisfed.org/series/NASDAQ100"],
  };

  const CURVES = {
    tenors: ["1M", "3M", "6M", "1Y", "2Y", "3Y", "5Y", "7Y", "10Y", "20Y", "30Y"],
    years: [1 / 12, 0.25, 0.5, 1, 2, 3, 5, 7, 10, 20, 30],
    dates: [
      { label: "Jan 2", y: [3.72, 3.65, 3.58, 3.47, 3.47, 3.55, 3.74, 3.95, 4.19, 4.81, 4.86] },
      { label: "Apr 1", y: [3.74, 3.70, 3.72, 3.68, 3.81, 3.84, 3.97, 4.15, 4.33, 4.91, 4.91] },
      { label: "Jul 1", y: [3.67, 3.85, 4.00, 4.00, 4.17, 4.19, 4.24, 4.35, 4.48, 4.97, 4.97] },
      { label: "Oct 1", y: [4.06, 4.17, 4.27, 4.44, 4.78, 4.91, 5.01, 5.12, 5.24, 5.64, 5.61] },
      { label: "Oct 19", y: [4.11, 4.27, 4.37, 4.50, 4.77, 4.85, 4.94, 5.04, 5.15, 5.53, 5.48] },
    ],
  };

  const LEVELS = [
    { label: "Fed funds target", value: "3.75–4.00%", note: "Hiked 25bp on Sep 16. October hike odds about 33% on Oct 16, up from 19% on Oct 8.", src: [SRC.fxstreet, SRC.roic] },
    { label: "Nasdaq-100", value: "29,529", note: "Oct 19 close.", src: SRC.fred, live: ["latest", "NASDAQ100", "n0"] },
    { label: "VIX", value: "21.41", note: "Oct 16; up from 16.44, a four-month high.", src: SRC.roic, live: ["level", "vix", "n2"] },
    { label: "3-month bill", value: "4.27%", note: "Oct 19 close.", src: SRC.treasury, live: ["curve", "3M"] },
    { label: "2-year Treasury", value: "4.77%", note: "Oct 19; up 130bp since Jan 2.", src: SRC.treasury, live: ["curve", "2Y"] },
    { label: "10-year Treasury", value: "5.15%", note: "Oct 19; up 96bp since Jan 2.", src: SRC.treasury, live: ["curve", "10Y"] },
    { label: "30-year Treasury", value: "5.48%", note: "Oct 19; 5.66% on Oct 5.", src: SRC.treasury, live: ["curve", "30Y"] },
    { label: "10-year real yield", value: "2.91%", note: "TIPS, Oct 7. Near an 18-year high.", src: SRC.macroradar, live: ["level", "real10"] },
    { label: "10-year breakeven", value: "2.36%", note: "Oct 7. Little changed since spring.", src: SRC.macroradar, live: ["level", "breakeven10"] },
    { label: "Japan 30-year", value: "4.11%", note: "Oct 8 auction average yield.", src: SRC.mof },
    { label: "Brent crude", value: "$125.44", note: "Oct 7; WTI $96.24. Iran war since Feb 28.", src: SRC.macroradar, live: ["level", "brent", "$"] },
    { label: "Gold", value: "$4,182", note: "Oct 13; up 2.6% from a year earlier.", src: SRC.fortune },
    { label: "Bitcoin", value: "$82,046", note: "Oct 16; down 0.6% on the week.", src: SRC.rio },
    { label: "USD/JPY", value: "157.81", note: "Oct 5.", src: SRC.macroradar },
  ];
  const LIVE_EXTRA = [
    ["hy_oas", "High-yield spread", (v) => fx(v, 2) + "%"],
    ["ig_oas", "Investment-grade spread", (v) => fx(v, 2) + "%"], ["term_premium10", "10-year term premium", (v) => fx(v, 2) + "%"],
    ["dollar_broad", "Broad dollar index", (v) => fx(v, 1)],
  ];

  // the model book (config.toml), used to weight the engine's betas in the futures calculator
  const BOOK = { MSFT: 0.14, AMZN: 0.14, GOOGL: 0.14, NVDA: 0.14, META: 0.12, TSLA: 0.10, AVGO: 0.08, SPCX: 0.08, ORCL: 0.06 };

  const SCEN_MX = [
    { name: "Growth scare", sub: "Demand doubts; yields fall" },
    { name: "Credit event", sub: "AI or private-credit losses" },
    { name: "Inflation shock", sub: "Oil up, Fed hikes" },
    { name: "Liquidity crash", sub: "Forced selling" },
    { name: "Slow bleed", sub: "Grinding, low-vol decline" },
    { name: "Debasement", sub: "Fiscal stress, weak dollar" },
  ];
  // grades: 2 strong, 1 partial, 0 little or none, -1 tends to hurt
  const MATRIX = [
    { h: "T-bills and cash", sub: "SGOV, BIL", g: [1, 1, 1, 1, 1, -1], note: "Holds its value in every crash scenario and pays 4.27% (3-month, Oct 19). It protects by not falling, not by rising. Loses real value under debasement. The safe side of a barbell." },
    { h: "Long Treasuries", sub: "TLT, ZB, UB", g: [2, 1, -1, 1, 1, -1], note: "Rallies when growth fears pull yields down, as on Oct 8. Falls with stocks when inflation, oil or bond supply push yields up, as in March 2026. Mixed in March 2020's dash for cash." },
    { h: "Intermediate Treasuries", sub: "IEF, ZN", g: [1, 1, 0, 1, 1, -1], note: "About half of TLT's duration: a smaller hedge in a growth scare and smaller damage in an inflation shock." },
    { h: "TIPS", sub: "TIP, SCHP", g: [1, 0, 1, 0, 0, 1], note: "Protect against inflation surprises but lose when real yields jump, as in 2022 and 2026. At a real yield near 2.9%, they lock in a positive real return if held." },
    { h: "Index puts", sub: "QQQ, SPX", g: [2, 2, 2, 2, 0, 0], note: "Pay in any fast equity decline, whatever the cause. The cost is the premium, which bleeds away in calm or slowly falling markets." },
    { h: "Put spreads", sub: "Long put, short lower put", g: [1, 1, 1, 1, 0, 0], note: "Cheaper puts with a capped payout. Good for moderate drawdowns; they give back the deep tail." },
    { h: "Collars", sub: "Long put, short call", g: [1, 1, 1, 1, 1, 0], note: "Fund the put by selling upside. Near-zero cost, so they protect in slow declines too, at the price of capping gains." },
    { h: "VIX calls", sub: "VIX options", g: [1, 1, 1, 2, -1, 0], note: "Explode in panics when volatility spikes. Decay quickly in calm markets, and a slow decline may never lift VIX enough to pay." },
    { h: "Credit protection", sub: "HYG puts, CDX HY", g: [1, 2, 1, 2, 0, 0], note: "Pays when spreads blow out: the direct hedge for an AI or private-credit financing shock. CoreWeave's CDS traded at distress levels on Oct 15." },
    { h: "Trend-following", sub: "DBMF, KMLM", g: [1, 1, 2, 0, 2, 1], note: "Profits from persistent moves in rates, currencies and commodities, as in 2022. Can whipsaw in sudden reversals and V-shaped crashes." },
    { h: "Gold", sub: "GLD, IAU", g: [1, 1, 1, 0, 0, 2], note: "Hedges debasement and geopolitics. Often sold for cash in liquidity crunches, and it struggles when real yields rise: up only 2.6% in the year to Oct 13, 2026, despite a war." },
    { h: "US dollar", sub: "UUP, DX futures", g: [1, 1, 1, 2, 0, -1], note: "The world's funding currency usually rallies in a crisis. Fails when the shock is fiscal or US-specific." },
    { h: "Bitcoin", sub: "IBIT, spot", g: [-1, -1, -1, -1, 0, 2], note: "Trades as high-beta liquidity in drawdowns. A debasement sleeve sized small, not a crash hedge." },
    { h: "Energy", sub: "XLE, Brent futures", g: [-1, 0, 2, -1, 0, 1], note: "The one exposure that rises in an oil-led inflation shock, the scenario where stocks and bonds fall together. Brent went from $73 to $118 between February and April 2026." },
    { h: "Lower gross, vol targeting", sub: "Engine rule", g: [1, 1, 1, 1, 1, 1], note: "Cuts exposure as volatility rises. Always helps, always a little late in a gap." },
  ];

  const SECS = [
    { n: "Treasury bills", f: "Rates", d: ["Rates", "Liquidity"], w: "Government debt maturing within a year, sold at a discount.", now: "4.27% (3-month, Oct 19)", acc: "SGOV, BIL, TreasuryDirect", role: "Safe leg of a barbell; collateral." },
    { n: "Treasury notes and bonds", f: "Rates", d: ["Rates"], w: "Coupon-paying government debt from 2 to 30 years.", now: "10-year 5.15%, 30-year 5.48% (Oct 19)", acc: "IEF, TLT, direct", role: "Duration; hedges growth scares only." },
    { n: "TIPS", f: "Rates", d: ["Rates", "Inflation"], w: "Treasuries whose principal adjusts with CPI.", now: "10-year real yield 2.91% (Oct 7)", acc: "TIP, SCHP, direct", role: "Real-return anchor; inflation hedge." },
    { n: "STRIPS and zero-coupon funds", f: "Rates", d: ["Rates", "Volatility"], w: "Treasury cash flows sold separately, paying everything at maturity.", now: "Duration roughly equal to maturity", acc: "ZROZ, EDV", role: "Most duration and convexity per dollar." },
    { n: "Treasury futures", f: "Rates", d: ["Rates", "Liquidity"], w: "Exchange-traded contracts on 2- to 30-year Treasuries.", now: "Margin, not full cash outlay", acc: "ZT, ZF, ZN, TN, ZB, UB", role: "Hedge DV01 without selling stock." },
    { n: "Interest-rate swaps", f: "Rates", d: ["Rates", "Credit"], w: "Exchange fixed for floating payments on a notional amount.", now: "Institutional", acc: "Dealers, cleared swaps", role: "How banks and insurers hedge duration." },
    { n: "Investment-grade corporates", f: "Credit", d: ["Credit", "Rates"], w: "Bonds of companies rated BBB- or better.", now: "Home of the hyperscalers' record bond deals", acc: "LQD, VCIT", role: "Income; AI financing lives here." },
    { n: "High-yield bonds", f: "Credit", d: ["Credit", "Equity"], w: "Bonds rated below investment grade.", now: "Spread tracked daily by the engine", acc: "HYG, JNK", role: "Income; puts on HYG hedge a credit event." },
    { n: "Leveraged loans", f: "Credit", d: ["Credit", "Liquidity"], w: "Floating-rate senior secured loans to leveraged companies.", now: "Floating coupons rise with the Fed", acc: "BKLN, SRLN", role: "Senior credit with little duration." },
    { n: "Private credit", f: "Credit", d: ["Credit", "Liquidity"], w: "Loans made by funds and insurers instead of banks.", now: "Default rate a record 6.0% (April 2026, Fitch)", acc: "BDCs (ARCC, OBDC), interval funds", role: "Watch, not own: where stress shows first." },
    { n: "Municipal bonds", f: "Credit", d: ["Credit", "Rates"], w: "State and local government debt, often tax-exempt.", now: "Tax-advantaged yield", acc: "MUB", role: "After-tax income for taxable accounts." },
    { n: "CLOs", f: "Structured", d: ["Credit", "Liquidity"], w: "Pools of leveraged loans sliced into tranches from AAA to equity.", now: "AAA tranches float above bills", acc: "JAAA", role: "Floating-rate senior structured credit." },
    { n: "Credit default swaps", f: "Credit", d: ["Credit", "Volatility"], w: "Insurance on a borrower's default, paid as an annual spread.", now: "CoreWeave CDS at distress levels (Oct 15)", acc: "CDX indices; institutional", role: "Direct hedge for a financing shock." },
    { n: "Agency mortgage-backed securities", f: "Structured", d: ["Rates", "Volatility"], w: "Pools of home loans guaranteed by Fannie, Freddie or Ginnie.", now: "Negative convexity from prepayments", acc: "MBB, VMBS", role: "Extra yield for selling rate volatility." },
    { n: "Catastrophe bonds", f: "Insurance-linked", d: ["Credit", "Liquidity"], w: "Bonds that lose principal if a defined disaster happens.", now: "Record $17.3B issued in H1 2026", acc: "Specialist interval and UCITS funds", role: "Returns mostly unrelated to markets." },
    { n: "Common stock", f: "Equity", d: ["Equity"], w: "The residual claim on a company.", now: "The concentrated AI sleeve", acc: "Direct, ETFs", role: "The return engine the desk protects." },
    { n: "Preferred stock", f: "Equity-linked", d: ["Equity", "Credit", "Rates"], w: "Fixed or variable dividends paid ahead of common holders.", now: "STRC 12.00% variable, semi-monthly", acc: "STRC, PFF", role: "High income with equity-like tail risk." },
    { n: "Convertible bonds", f: "Equity-linked", d: ["Credit", "Equity", "Volatility"], w: "Bonds convertible into shares at a set price.", now: "A favorite funding tool of AI and bitcoin treasury companies", acc: "CWB", role: "Upside with a bond floor, if the issuer is sound." },
    { n: "Listed options", f: "Derivatives", d: ["Volatility", "Equity"], w: "Rights to buy or sell at a set price by a set date.", now: "See the option pricer", acc: "QQQ, SPX, single stocks", role: "Contractual convexity: the cleanest hedge." },
    { n: "Warrants", f: "Derivatives", d: ["Volatility", "Equity"], w: "Long-dated call options issued by the company itself.", now: "Common in SPACs and rescue financings", acc: "Exchange-listed warrants", role: "Cheap long-dated convexity, with dilution." },
    { n: "Gold", f: "Real assets", d: ["Inflation", "Currency"], w: "The oldest monetary hedge, with no yield.", now: "$4,182/oz (Oct 13)", acc: "GLD, IAU, futures", role: "Debasement sleeve; weak against high real yields." },
    { n: "Oil and energy", f: "Real assets", d: ["Inflation", "Equity"], w: "Crude futures, producers and service companies.", now: "Brent $125.44 (Oct 7)", acc: "XLE, Brent and WTI futures", role: "Hedge for the oil-shock lane." },
    { n: "REITs and data centers", f: "Real assets", d: ["Equity", "Rates", "Credit"], w: "Listed owners of property, including data centers.", now: "Rate-sensitive; AI-linked demand", acc: "VNQ, EQIX, DLR", role: "AI infrastructure with a rates hit." },
    { n: "Managed futures", f: "Strategies", d: ["Rates", "Currency", "Inflation"], w: "Rules-based trend following across futures markets.", now: "Built for persistent moves like 2022's", acc: "DBMF, KMLM", role: "Crisis alpha in slow, persistent declines." },
    { n: "Bitcoin", f: "Digital", d: ["Liquidity", "Volatility", "Currency"], w: "A fixed-supply digital bearer asset.", now: "$82,046 (Oct 16)", acc: "IBIT, spot", role: "Debasement sleeve, sized for its volatility." },
    { n: "Bitcoin treasury companies", f: "Digital", d: ["Equity", "Credit", "Volatility"], w: "Operating companies that hold bitcoin funded by stock, converts and preferreds.", now: "Strategy's preferreds raised $7B in 2025", acc: "MSTR and its preferreds", role: "Leveraged bitcoin with a capital stack to read." },
    { n: "US dollar", f: "Currency", d: ["Currency", "Liquidity"], w: "The world's funding and reserve currency.", now: "Broad dollar index 121.38 (Oct 5)", acc: "UUP, DX futures", role: "Crisis hedge in most crashes." },
    { n: "Japanese yen", f: "Currency", d: ["Currency", "Rates"], w: "Funding currency for global carry trades.", now: "USD/JPY 157.81 (Oct 5)", acc: "FXY, futures", role: "Carry-unwind hedge, as in August 2024." },
    { n: "Prediction markets", f: "Event contracts", d: ["Volatility", "Liquidity"], w: "Contracts that pay $1 if an event happens.", now: "Fed path, CPI and election odds", acc: "Kalshi, Polymarket", role: "Market-implied probabilities as regime inputs." },
    { n: "Annuities", f: "Insurance-linked", d: ["Credit", "Rates", "Liquidity"], w: "Insurance contracts that pay income for a term or for life.", now: "Funded largely by private credit at PE-affiliated insurers", acc: "Insurers", role: "Know who sits on the other side." },
  ];
  const DRIVERS = ["Rates", "Credit", "Equity", "Inflation", "Volatility", "Liquidity", "Currency"];

  const THESES = [
    { id: "t1", t: "The AI buildout is outrunning its cash flow", st: "active", stance: "Constructive on the buildout, cautious on how it is financed.",
      ev: ["Alphabet posted negative free cash flow of $5.9B in Q2 2026, its first since the 2004 IPO, and raised 2026 capex guidance to $195–205B.", "Meta's Q2 free cash flow fell to $0.8B from $8.6B a year earlier; it reports Oct 21.", "Morgan Stanley expects about $570B of AI-related debt issuance in 2026.", "Michael Burry estimates depreciation will be understated by $176B over 2026–28 as server lives are stretched."],
      ex: "Own the bottleneck suppliers (compute, networking, power) ahead of balance sheets that must borrow to keep up.", hd: "Credit protection and index put spreads; not long Treasuries.",
      kill: ["Hyperscaler free cash flow turns back up while capex holds.", "A hyperscaler cuts quarterly capex by 20% or more (bear trigger)."], data: ["SEC capex and cash flow (engine capex command)", "High-yield spread (FRED)", "Book vs TLT regime"] },
    { id: "t2", t: "Real rates, not inflation expectations, are doing the tightening", st: "active", stance: "Long nominal duration is a growth-scare hedge only.",
      ev: ["Since April the 10-year is up about 80bp while the 10-year breakeven slipped about 10bp.", "The Sep 17 10-year TIPS auction cleared at 2.653%, the highest real yield in nearly 18 years.", "The Fed hiked to 3.75–4.00% on Sep 16; UOB expects 4.50% by early 2027.", "Japan's 30-year cleared at 4.11% on Oct 8."],
      ex: "Hold the safe leg in bills (4.27%) and TIPS (about 2.9% real) instead of long nominals.", hd: "Options for the tail; duration only when the engine's correlation turns negative.",
      kill: ["Breakevens fall sharply alongside a growth scare.", "The engine's stock-bond correlation (63-day half-life) drops below −0.10."], data: ["TIPS real yield and breakeven (FRED)", "Nasdaq-100 vs long-bond correlation (engine)"] },
    { id: "t3", t: "Energy security is the tail risk you cannot diversify away", st: "active", stance: "Carry explicit oil-shock protection.",
      ev: ["The Iran war began Feb 28, 2026 and closed the Strait of Hormuz, which carries about 20% of global oil and LNG.", "Brent peaked at $118 in April, fell to $78 by late June on a ceasefire framework, and traded at $125 on Oct 7.", "US CPI hit 4.2% year over year in May, with gasoline up 40.5%."],
      ex: "Energy producers or Brent exposure sized to offset the book's loss in an oil shock.", hd: "This is itself the hedge for the lane where stocks and bonds fall together.",
      kill: ["A durable ceasefire with Brent back below $80.", "Breakevens and oil decouple for a full quarter."], data: ["Brent and WTI daily (FRED)", "10-year breakeven (FRED)"] },
    { id: "t4", t: "Power is the AI bottleneck", st: "watch", stance: "Firm power and the nuclear supply chain win whichever chip wins.",
      ev: ["Four hyperscalers guide about $725B of 2026 capex, and every campus needs firm power; Meta's Hyperion in Louisiana is about a $27B project.", "Meta guarantees the Hyperion campus's residual value for 16 years, a sign of how long it expects to need the capacity."],
      ex: "Research list: CEG, CCJ, BWXT and grid equipment.", hd: "Rates exposure: utilities and infrastructure suffer when real yields rise.",
      kill: ["Hyperscaler capex cuts.", "Power purchase prices for data centers fall."], data: ["SEC capex (engine)", "10-year real yield (FRED)"] },
    { id: "t5", t: "Re-armament is a multi-year budget cycle", st: "watch", stance: "Defense demand outlasts any single conflict.",
      ev: ["NATO allies agreed in June 2025 to raise defense and security spending toward 5% of GDP by 2035.", "The US-Iran conflict, under way since late February 2026, keeps defense demand front and center."],
      ex: "Research list: PLTR, LMT, BWXT and defense tech suppliers.", hd: "Budget-fight risk around the Nov 3 midterms.",
      kill: ["Ceasefire plus procurement cuts in budget negotiations."], data: ["Backlog and book-to-bill from filings (engine roadmap)"] },
    { id: "t6", t: "Private credit is where the AI cycle's losses surface first", st: "risk", stance: "A risk to monitor and hedge, not a yield to chase.",
      ev: ["Fitch's US private credit default rate hit a record 6.0% in April 2026.", "Insurers provide about 23% of private credit capital, $0.9–1.1T; US life insurers hold about 10% of assets in it, above 15% at some PE-affiliated insurers.", "Meta's Hyperion debt was sold to PIMCO and other bond investors; Apollo was reported near a $35B loan for Nvidia chips leased to xAI."],
      ex: "Prefer insurers with low private-credit concentration over PE-affiliated annuity writers (research pair).", hd: "High-yield credit protection.",
      kill: ["Default rates fall back below 3%.", "Private loan marks hold through a growth scare."], data: ["High-yield spread (FRED)", "BDC discounts to book (roadmap)"] },
    { id: "t7", t: "Hard-money hedges hedge debasement, not tightening", st: "active", stance: "Keep gold and bitcoin as small sleeves; do not count on them in a real-rate squeeze.",
      ev: ["Gold was $4,182 on Oct 13, up only 2.6% from a year earlier despite a war and an inflation spike.", "Bitcoin was $82,046 on Oct 16.", "Real yields near 3% raise the cost of holding assets that pay nothing."],
      ex: "A sized debasement sleeve rebalanced on rules.", hd: "T-bills and TIPS as the true safe leg.",
      kill: ["Real yields fall and the Fed turns to cuts: the sleeve should then lead."], data: ["10-year real yield (FRED)", "Broad dollar index (FRED)"] },
    { id: "t8", t: "Volatility is the cheapest honest hedge", st: "active", stance: "Run a standing tail budget instead of a bond hedge whose correlation can flip.",
      ev: ["Cboe flagged volatility and convexity premia at their lowest of the year in mid-August, before October's AI selloff.", "The Fed's own data show stocks and bonds falling together through July 2026.", "A put's payoff is contractual; a bond hedge's is statistical."],
      ex: "1–2% of NAV a year in rolled index put spreads; bills and TIPS as the safe leg.", hd: "This is the hedge.",
      kill: ["Implied volatility stays rich to realized for a full quarter: cut the budget and lean on size and trend instead."], data: ["VIX (FRED)", "Realized volatility of the book (engine)"] },
  ];

  const LENSES = [
    { n: "Nassim Taleb", idea: "Fat tails decide outcomes. Avoid ruin first, then seek exposures that gain from disorder: a barbell of very safe and very convex.", rule: "Drawdown cap before return; standing tail budget; bills and TIPS as the safe leg; prefer contracts to correlations.", read: "Fooled by Randomness · The Black Swan · Antifragile · Skin in the Game · Statistical Consequences of Fat Tails", link: ["@nntaleb", "https://x.com/nntaleb"] },
    { n: "Ray Dalio", idea: "Assets respond to surprises in growth and inflation. Balance risk across all four environments, and know where you are in the debt cycle.", rule: "The regime map on the Desk and the scenario columns of the hedge matrix.", read: "Principles · Big Debt Crises · The Changing World Order · How Countries Go Broke", link: ["@RayDalio", "https://x.com/RayDalio"] },
    { n: "Howard Marks", idea: "You cannot predict, but you can prepare. Know where the cycle is by watching how freely credit is offered.", rule: "Credit spreads, issuance and private-credit defaults tracked as cycle gauges.", read: "The Most Important Thing · Mastering the Market Cycle · Oaktree memos", link: ["Oaktree memos", "https://www.oaktreecapital.com/insights/memos"] },
    { n: "Stanley Druckenmiller", idea: "Liquidity and central banks move markets more than earnings. Bet big when the odds are clear, and cut fast when wrong.", rule: "Fed path, real yields and the balance sheet sit at the top of the Desk; sizing scales with conviction inside hard limits.", read: "Interviews and talks", link: null },
    { n: "George Soros", idea: "Reflexivity: prices change the fundamentals they are supposed to reflect.", rule: "The AI funding loop: rising stocks fund capex through equity and debt, which funds revenue for the suppliers. The engine watches the loop's financing leg.", read: "The Alchemy of Finance", link: null },
    { n: "Michael Burry", idea: "Read the cash flow statement and the footnotes; accounting choices can flatter earnings.", rule: "The engine pulls capex and operating cash flow straight from SEC filings; depreciation lives on the watchlist.", read: "Scion letters and public posts", link: null },
    { n: "Warren Buffett and Charlie Munger", idea: "Float is cheap capital, margin of safety is the job, and inversion finds what kills you.", rule: "The Insurers desk; stress tests ask what kills the book before asking what it earns.", read: "Berkshire shareholder letters · Poor Charlie's Almanack", link: ["Berkshire letters", "https://www.berkshirehathaway.com/letters/letters.html"] },
    { n: "BowTiedBull", idea: "Own assets instead of renting your time; build an internet business; learn crypto and markets in plain language.", rule: "This site is the asset: a body of work that compounds. Crypto enters the desk as a sized debasement sleeve (thesis 7), never as the core.", read: "BowTiedBull newsletter and the BowTied network", link: ["@BowTiedBull", "https://x.com/BowTiedBull"] },
    { n: "The Kobeissi Letter", idea: "Fast cross-asset commentary on equities, commodities, oil, gold, Treasuries and currencies.", rule: "The Desk's key levels cover the same cross-asset set, each with a source and a date.", read: "The Kobeissi Letter and its posts on X", link: ["@KobeissiLetter", "https://x.com/KobeissiLetter"] },
    { n: "Six Sigma Research", idea: "Market and investing research, posted on X as Six Sigma Capital; one of the feeds the desk reads.", rule: "Ideas from the feed get tested in the engine before they get capital.", read: "Posts on X", link: ["@SixSigmaCapital", "https://x.com/SixSigmaCapital"] },
    { n: "Billy Walters", idea: "Edge, bankroll management and information advantage decide who survives in betting and markets.", rule: "The Kelly fraction in the Sizing lab: size to edge, and never bet the bankroll.", read: "Gambler: Secrets from a Life at Risk", link: null },
  ];

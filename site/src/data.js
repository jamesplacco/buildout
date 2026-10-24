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
    fedpolicy: ["Federal Reserve", "https://federalreserve.gov/monetarypolicy/policy-normalization.htm"],
    macrotrends: ["Macrotrends", "https://www.macrotrends.net/3094/ccc-lower-high-yield-spread"],
    fomc_sep: ["Federal Reserve, Sep 16, 2026 statement", "https://www.federalreserve.gov/newsevents/pressreleases/monetary20260916a.htm"],
    te_odds: ["Trading Economics, Oct 23, 2026", "https://tradingeconomics.com/united-states/government-bond-yield/news/594660"],
    treasury_real: ["US Treasury, real yield curve", "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/TextView?type=daily_treasury_real_yield_curve&field_tdr_date_value_month=202610"],
    stockanalysis: ["StockAnalysis", "https://stockanalysis.com/etf/tlt/history/"],
    investing: ["Investing.com", "https://www.investing.com/indices/volatility-s-p-500-historical-data"],
    investing_vxn: ["Investing.com", "https://www.investing.com/indices/cboe-nasdaq-100-voltility-historical-data"],
    investing_brent: ["Investing.com", "https://www.investing.com/commodities/brent-oil-historical-data"],
    investing_gold: ["Investing.com", "https://www.investing.com/commodities/gold-historical-data"],
    investing_btc: ["Investing.com", "https://www.investing.com/crypto/bitcoin/historical-data"],
    investing_dxy: ["Investing.com", "https://www.investing.com/indices/usdollar-historical-data"],
  };
  const F = (id) => ["FRED", "https://fred.stlouisfed.org/series/" + id];

  const CURVES = {
    tenors: ["1M", "3M", "6M", "1Y", "2Y", "3Y", "5Y", "7Y", "10Y", "20Y", "30Y"],
    years: [1 / 12, 0.25, 0.5, 1, 2, 3, 5, 7, 10, 20, 30],
    dates: [
      { label: "Jan 2", y: [3.72, 3.65, 3.58, 3.47, 3.47, 3.55, 3.74, 3.95, 4.19, 4.81, 4.86] },
      { label: "Apr 1", y: [3.74, 3.70, 3.72, 3.68, 3.81, 3.84, 3.97, 4.15, 4.33, 4.91, 4.91] },
      { label: "Jul 1", y: [3.67, 3.85, 4.00, 4.00, 4.17, 4.19, 4.24, 4.35, 4.48, 4.97, 4.97] },
      { label: "Oct 1", y: [4.06, 4.17, 4.27, 4.44, 4.78, 4.91, 5.01, 5.12, 5.24, 5.64, 5.61] },
      { label: "Oct 21", y: [4.09, 4.25, 4.35, 4.52, 4.81, 4.89, 4.95, 5.03, 5.13, 5.47, 5.42] },
      { label: "Oct 22", y: [4.11, 4.22, 4.29, 4.41, 4.65, 4.72, 4.78, 4.86, 4.96, 5.32, 5.29] },
      { label: "Oct 23", y: [4.11, 4.22, 4.30, 4.44, 4.69, 4.75, 4.82, 4.89, 5.00, 5.37, 5.33] },
    ],
  };

  const LEVELS = [
    { label: "Fed funds target", value: "3.75–4.00%", note: "Hiked 25bp on Sep 16, 12 to 0. Oct 23: about 91% odds of a hold on Oct 28, a December hike around 76%.", src: [SRC.fomc_sep, SRC.te_odds] },
    { label: "Nasdaq-100", key: "ndx", date: "2026-10-22", value: "28,959", note: "Oct 22 close; 29,823 on Oct 21 and 30,569 on Oct 13.", src: SRC.fred, live: ["latest", "NASDAQ100", "n0"], fid: "NASDAQ100" },
    { label: "VIX", key: "vix", date: "2026-10-23", value: "19.45", note: "Oct 23 close; 19.03 on Oct 22, 16.68 on Oct 21, 19.99 on Oct 16 (a four-month high).", src: [SRC.investing, F("VIXCLS")], live: ["level", "vix", "n2"], fid: "VIXCLS" },
    { label: "Nasdaq-100 volatility", key: "vxn", date: "2026-10-23", value: "28.30", note: "VXN, Oct 23 close; 28.72 on Oct 22, 25.56 on Oct 19.", src: [SRC.investing_vxn, F("VXNCLS")], live: ["level", "vxn", "n2"], fid: "VXNCLS" },
    { label: "3-month bill", key: "bill3m", date: "2026-10-23", value: "4.22%", note: "Oct 23 close; 4.25% on Oct 21.", src: SRC.treasury, live: ["curve", "3M"] },
    { label: "2-year Treasury", key: "y2", date: "2026-10-23", value: "4.69%", note: "Oct 23; 4.81% on Oct 21, up 122bp since Jan 2.", src: SRC.treasury, live: ["curve", "2Y"] },
    { label: "10-year Treasury", key: "y10", date: "2026-10-23", value: "5.00%", note: "Oct 23 par yield; 4.96% on Oct 22 after 5.13% on Oct 21 (a 17bp fall on the AI growth scare); up 81bp since Jan 2.", src: SRC.treasury, live: ["curve", "10Y"] },
    { label: "30-year Treasury", key: "y30", date: "2026-10-23", value: "5.33%", note: "Oct 23; 5.42% on Oct 21, 5.66% on Oct 5.", src: SRC.treasury, live: ["curve", "30Y"] },
    { label: "10-year real yield", key: "real10", date: "2026-10-23", value: "2.66%", note: "TIPS par real yield, Oct 23; 2.76% on Oct 21, 2.91% on Oct 7, near an 18-year high.", src: [SRC.treasury_real, F("DFII10")], live: ["level", "real10"], fid: "DFII10" },
    { label: "10-year breakeven", key: "breakeven10", date: "2026-10-23", value: "2.34%", note: "Oct 23, nominal par 5.00% minus real par 2.66%; 2.46% on Apr 29.", src: [SRC.treasury_real, F("T10YIE")], live: ["level", "breakeven10"], fid: "T10YIE" },
    { label: "High-yield spread", key: "hy_oas", date: "2026-10-22", value: "3.40%", note: "Oct 22, the widest of the month; 3.11% on Oct 9.", src: F("BAMLH0A0HYM2"), live: ["level", "hy_oas"], fid: "BAMLH0A0HYM2" },
    { label: "CCC spread", key: "ccc_oas", date: "2026-10-22", value: "13.40%", note: "Oct 22; 12.53% on Oct 9, 8.53% in July 2025. The weakest borrowers first.", src: [F("BAMLH0A3HYC"), SRC.macrotrends], live: ["level", "ccc_oas"], fid: "BAMLH0A3HYC" },
    { label: "Japan 30-year", value: "4.11%", note: "Oct 8 auction average yield.", src: SRC.mof },
    { label: "Brent crude", key: "brent", date: "2026-10-23", value: "$116.93", note: "Dec 2026 futures, Oct 23 close, the highest since June 2022; $113.17 on Oct 22. EIA spot $126.55 on Oct 14; WTI $103.44 on Oct 23. Iran war since Feb 28.", src: [SRC.investing_brent, F("DCOILBRENTEU")], live: ["level", "brent", "$"], fid: "DCOILBRENTEU" },
    { label: "Gold", key: "gold", date: "2026-10-23", value: "$4,010", note: "Dec 2026 futures, Oct 23 close; $4,060 on Oct 22, $4,182 spot on Oct 13.", src: [SRC.investing_gold, SRC.fortune] },
    { label: "Bitcoin", value: "$81,698", note: "Oct 23; $81,409 on Oct 22.", src: [SRC.investing_btc, F("CBBTCUSD")], live: ["level", "bitcoin", "$0"], fid: "CBBTCUSD" },
    { label: "Dollar index", value: "101.80", note: "DXY, Oct 23; 101.61 on Oct 22.", src: SRC.investing_dxy },
    { label: "USD/JPY", value: "158.00", note: "Oct 16; yen per dollar.", src: F("DEXJPUS"), live: ["level", "usdjpy", "n2"], fid: "DEXJPUS" },
  ];
  // the static level by key, as a number with its ISO date (the one dated store every rule falls back to when the daily run is absent)
  function levelStatic(key) {
    const r = LEVELS.find((x) => x.key === key);
    if (!r) return null;
    const v = Number(String(r.value).replace(/[$,%]/g, "").replace(/,/g, ""));
    return fin(v) ? { v, d: r.date, live: false, label: r.label, note: r.note } : null;
  }
  const LIVE_EXTRA = [
    ["ig_oas", "Investment-grade spread", (v) => fx(v, 2) + "%", "BAMLC0A0CM"], ["term_premium10", "10-year term premium", (v) => fx(v, 2) + "%", "THREEFYTP10"],
    ["fwd5y5y", "5y5y inflation expectation", (v) => fx(v, 2) + "%", "T5YIFR"], ["dollar_broad", "Broad dollar index", (v) => fx(v, 1), "DTWEXBGS"],
  ];

  // What moved this week, from FRED: the Oct 13 close against each series' latest close (dates per row).
  // [label, kind, from, to, to-date, FRED id, lead]; the daily run replaces it with day to one-year changes and z-scores.
  const STATIC_MOVES = { from: "Oct 13", rows: [
    ["Nasdaq-100", "pct", 30569.48, 28958.69, "Oct 22", "NASDAQ100", true],
    ["S&P 500", "pct", 7805.45, 7690.73, "Oct 19", "SP500"],
    ["2-year Treasury", "bp", 4.79, 4.69, "Oct 23", "DGS2"],
    ["10-year Treasury", "bp", 5.21, 5.00, "Oct 23", "DGS10", true],
    ["30-year Treasury", "bp", 5.56, 5.33, "Oct 23", "DGS30", true],
    ["10-year real yield", "bp", 2.88, 2.66, "Oct 23", "DFII10"],
    ["10-year breakeven", "bp", 2.33, 2.34, "Oct 23", "T10YIE"],
    ["Investment-grade spread", "bp", 0.83, 0.87, "Oct 19", "BAMLC0A0CM"],
    ["High-yield spread", "bp", 3.16, 3.40, "Oct 22", "BAMLH0A0HYM2"],
    ["CCC spread", "bp", 12.67, 13.40, "Oct 22", "BAMLH0A3HYC", true],
    ["VIX", "pts", 15.27, 19.45, "Oct 23", "VIXCLS", true],
    ["Nasdaq-100 volatility (VXN)", "pts", 21.14, 28.30, "Oct 23", "VXNCLS"],
    ["Brent crude", "pct", 125.78, 126.55, "Oct 14", "DCOILBRENTEU"],
    ["Broad dollar", "pct", 121.4433, 121.4048, "Oct 16", "DTWEXBGS"],
    ["Yen per dollar", "pct", 158.36, 158.0, "Oct 16", "DEXJPUS"],
  ] };
  // insurance and plumbing snapshot, from FRED (values in index points, percent, and $ trillions)
  const TLT_DUR = 14.85;                 // TLT effective duration, iShares, Oct 20, 2026 (knowledge item bd-tlt-duration)
  const STATIC_VOL = { vxn: [28.30, "Oct 23"], vix: [19.45, "Oct 23"], vix3m: [20.5, "Oct 16"], term: { vix: 19.99, vix3m: 20.5, date: "2026-10-16" } };   // term: both legs on one date
  const STATIC_LIQ = { assets: [6.755639, "Oct 14"], tga: [0.883373, "Oct 14"], rrp: [0.00033, "Oct 19"], reserves: [3.02214, "Oct 14"], sofr: [3.88, "Oct 16"], iorb: [3.9, "Oct 16"] };

  // the model book (config.toml), used to weight the engine's betas in the futures calculator
  const BOOK = { MSFT: 0.14, AMZN: 0.14, GOOGL: 0.14, NVDA: 0.14, META: 0.12, TSLA: 0.10, AVGO: 0.08, SPCX: 0.08, ORCL: 0.06 };
  // assumed five-year betas to the S&P 500 (buildout/assets/positions.json); the book run replaces them with measured betas
  const BOOK_BETAS = { NVDA: 1.7, MSFT: 1.05, GOOGL: 1.1, AMZN: 1.2, META: 1.25, AVGO: 1.5, TSLA: 2.0, ORCL: 1.4, SPCX: 1.6 };
  const bookBeta = () => Object.keys(BOOK).reduce((a, k) => a + BOOK[k] * (BOOK_BETAS[k] || 1), 0) / Object.values(BOOK).reduce((a, w) => a + w, 0);

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
    { h: "T-bills and cash", sub: "SGOV, BIL", g: [1, 1, 1, 1, 1, -1], note: "Holds its value in every crash scenario and pays 4.25% (3-month, Oct 21). It protects by not falling, not by rising. Loses real value under debasement. The safe side of a barbell." },
    { h: "Long Treasuries", sub: "TLT, ZB, UB", g: [2, 1, -1, 1, 1, -1], note: "Rallies when growth fears pull yields down, as on Oct 8. Falls with stocks when inflation, oil or bond supply push yields up, as in March 2026. Mixed in March 2020's dash for cash." },
    { h: "Intermediate Treasuries", sub: "IEF, ZN", g: [1, 1, 0, 1, 1, -1], note: "About half of TLT's duration: a smaller hedge in a growth scare and smaller damage in an inflation shock." },
    { h: "TIPS", sub: "TIP, SCHP", g: [1, 0, 1, 0, 0, 1], note: "Protect against inflation surprises but lose when real yields jump, as in 2022 and 2026. At a real yield near 2.75%, they lock in a positive real return if held." },
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
    { n: "Treasury bills", f: "Rates", d: ["Rates", "Liquidity"], w: "Government debt maturing within a year, sold at a discount.", now: "4.22% (3-month, Oct 23)", acc: "SGOV, BIL, TreasuryDirect", role: "Safe leg of a barbell; collateral." },
    { n: "Treasury notes and bonds", f: "Rates", d: ["Rates"], w: "Coupon-paying government debt from 2 to 30 years.", now: "10-year 5.13%, 30-year 5.42% (Oct 21)", acc: "IEF, TLT, direct", role: "Duration; hedges growth scares only." },
    { n: "TIPS", f: "Rates", d: ["Rates", "Inflation"], w: "Treasuries whose principal adjusts with CPI.", now: "10-year real yield 2.66% (Oct 23)", acc: "TIP, SCHP, direct", role: "Real-return anchor; inflation hedge." },
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
    { n: "Oil and energy", f: "Real assets", d: ["Inflation", "Equity"], w: "Crude futures, producers and service companies.", now: "Brent $126.55 (Oct 14, EIA spot)", acc: "XLE, Brent and WTI futures", role: "Hedge for the oil-shock lane." },
    { n: "REITs and data centers", f: "Real assets", d: ["Equity", "Rates", "Credit"], w: "Listed owners of property, including data centers.", now: "Rate-sensitive; AI-linked demand", acc: "VNQ, EQIX, DLR", role: "AI infrastructure with a rates hit." },
    { n: "Managed futures", f: "Strategies", d: ["Rates", "Currency", "Inflation"], w: "Rules-based trend following across futures markets.", now: "Built for persistent moves like 2022's", acc: "DBMF, KMLM", role: "Crisis alpha in slow, persistent declines." },
    { n: "Bitcoin", f: "Digital", d: ["Liquidity", "Volatility", "Currency"], w: "A fixed-supply digital bearer asset.", now: "$81,804 (Oct 19)", acc: "IBIT, spot", role: "Debasement sleeve, sized for its volatility." },
    { n: "Bitcoin treasury companies", f: "Digital", d: ["Equity", "Credit", "Volatility"], w: "Operating companies that hold bitcoin funded by stock, converts and preferreds.", now: "Preferreds such as STRC fund the buying (see its 8-K)", acc: "MSTR and its preferreds", role: "Leveraged bitcoin with a capital stack to read." },
    { n: "US dollar", f: "Currency", d: ["Currency", "Liquidity"], w: "The world's funding and reserve currency.", now: "Broad dollar index 121.40 (Oct 16)", acc: "UUP, DX futures", role: "Crisis hedge in most crashes." },
    { n: "Japanese yen", f: "Currency", d: ["Currency", "Rates"], w: "Funding currency for global carry trades.", now: "USD/JPY 158.00 (Oct 16)", acc: "FXY, futures", role: "Carry-unwind hedge, as in August 2024." },
    { n: "Prediction markets", f: "Event contracts", d: ["Volatility", "Liquidity"], w: "Contracts that pay $1 if an event happens.", now: "Fed path, CPI and election odds", acc: "Kalshi, Polymarket", role: "Market-implied probabilities as regime inputs." },
    { n: "Annuities", f: "Insurance-linked", d: ["Credit", "Rates", "Liquidity"], w: "Insurance contracts that pay income for a term or for life.", now: "Funded largely by private credit at PE-affiliated insurers", acc: "Insurers", role: "Know who sits on the other side." },
  ];
  const DRIVERS = ["Rates", "Credit", "Equity", "Inflation", "Volatility", "Liquidity", "Currency"];

  const THESES = [
    { id: "t1", t: "The AI buildout is outrunning its cash flow", st: "active", wk: ["cr-hyperscaler-issuance-228bn-261013", "cr-imf-circular-financing-261013", "tp-meta-q3-figures-1021", "tp-script-flipped-1023"], stance: "Constructive on the buildout, cautious on how it is financed.",
      ev: ["Alphabet posted negative free cash flow of $5.9B in Q2 2026, its first since the 2004 IPO, and raised 2026 capex guidance to $195–205B.", "Meta's Q3 2026 free cash flow was negative $2.1B: capex including finance leases of $34.9B against $32.8B of operating cash flow; 2026 capex guidance narrowed to $135B to $145B (Oct 21).", "Morgan Stanley expects about $570B of AI-related debt issuance in 2026.", "Michael Burry estimates depreciation will be understated by $176B over 2026–28 as server lives are stretched."],
      ex: "Own the bottleneck suppliers (compute, networking, power) ahead of balance sheets that must borrow to keep up.", hd: "Credit protection and index put spreads; not long Treasuries.",
      kill: ["Hyperscaler free cash flow turns back up while capex holds.", "A hyperscaler cuts quarterly capex by 20% or more (bear trigger)."], data: ["SEC capex and cash flow (engine capex command)", "High-yield spread (FRED)", "Book vs TLT regime"] },
    { id: "t2", t: "Real rates, not inflation expectations, are doing the tightening", st: "active", wk: ["bd-par-close-1023", "bd-real-breakeven-1022-23", "fd-term-premium-kw10-261016", "fd-fedsnote-safe-haven-261016", "fd-fomc-oct28-odds-te-261023"], stance: "Long nominal duration is a growth-scare hedge only.",
      ev: ["Since April the 10-year is up about 80bp while the 10-year breakeven slipped about 10bp.", "The Sep 17 10-year TIPS auction cleared at 2.653%, the highest real yield in nearly 18 years.", "The Fed hiked to 3.75–4.00% on Sep 16; UOB expects 4.50% by early 2027.", "Japan's 30-year cleared at 4.11% on Oct 8."],
      ex: "Hold the safe leg in bills (4.22%) and TIPS (about 2.66% real) instead of long nominals.", hd: "Options for the tail; duration only when the engine's correlation turns negative.",
      kill: ["Breakevens fall sharply alongside a growth scare.", "The engine's stock-bond correlation (63-day half-life) drops below −0.10."], data: ["TIPS real yield and breakeven (FRED)", "Nasdaq-100 vs long-bond correlation (engine)"] },
    { id: "t3", t: "Energy security is the tail risk that cannot be diversified away", st: "active", wk: ["tp-brent-close-1022-23", "fd-cpi-sep26-shelter-energy-261014", "tp-indexes-ap-1023"], stance: "Carry explicit oil-shock protection.",
      ev: ["The Iran war began Feb 28, 2026 and closed the Strait of Hormuz, which carries about 20% of global oil and LNG.", "Brent averaged $118 in April (its daily high was about $138), fell to $78 by late June on a ceasefire framework, and traded at $125 on Oct 7.", "US CPI hit 4.2% year over year in May, with gasoline up 40.5%."],
      ex: "Energy producers or Brent exposure sized to offset the book's loss in an oil shock.", hd: "This is itself the hedge for the lane where stocks and bonds fall together.",
      kill: ["A durable ceasefire with Brent back below $80.", "Breakevens and oil decouple for a full quarter."], data: ["Brent and WTI daily (FRED)", "10-year breakeven (FRED)"] },
    { id: "t4", t: "Power is the AI bottleneck", st: "watch", wk: ["pw-gev-gas-116gw-260722", "pw-pjm-bra-2028-325-260714", "pw-synmax-delays-40pct-261005", "pw-modo-ercot-92gw-cost-261021", "pw-epoch-frontier-dc-14gw-261020"], stance: "Firm power and the nuclear supply chain win whichever chip wins.",
      ev: ["Four hyperscalers guide about $725B of 2026 capex, and every campus needs firm power; Meta's Hyperion in Louisiana is about a $27B project.", "Meta guarantees the Hyperion campus's residual value for 16 years, a sign of how long it expects to need the capacity."],
      ex: "Research list: CEG, CCJ, BWXT and grid equipment.", hd: "Rates exposure: utilities and infrastructure suffer when real yields rise.",
      kill: ["Hyperscaler capex cuts.", "Power purchase prices for data centers fall."], data: ["SEC capex (engine)", "10-year real yield (FRED)"] },
    { id: "t5", t: "Re-armament is a multi-year budget cycle", st: "watch", stance: "Defense demand outlasts any single conflict.",
      ev: ["NATO allies agreed in June 2025 to raise defense and security spending toward 5% of GDP by 2035.", "The US-Iran conflict, under way since late February 2026, keeps defense demand front and center."],
      ex: "Research list: PLTR, LMT, BWXT and defense tech suppliers.", hd: "Budget-fight risk around the Nov 3 midterms.",
      kill: ["Ceasefire plus procurement cuts in budget negotiations."], data: ["Backlog and book-to-bill from filings (engine roadmap)"] },
    { id: "t6", t: "Private credit is where the AI cycle's losses surface first", st: "risk", wk: ["cr-coreweave-cds-1115bp-261022", "cr-ccc-oas-261022", "cr-imf-bank-stress-261013", "cr-feds-note-private-credit-holders-261016", "tp-hedge-funds-goldman-1023"], stance: "A risk to monitor and hedge, not a yield to chase.",
      ev: ["Fitch's US private credit default rate hit a record 6.0% in April 2026.", "Insurers provide about 23% of private credit capital, $0.9–1.1T; US life insurers hold about 10% of assets in it, above 15% at some PE-affiliated insurers.", "Meta's Hyperion debt was sold to PIMCO and other bond investors; Apollo was reported near a $35B loan for Nvidia chips leased to xAI."],
      ex: "Prefer insurers with low private-credit concentration over PE-affiliated annuity writers (research pair).", hd: "High-yield credit protection.",
      kill: ["Default rates fall back below 3%.", "Private loan marks hold through a growth scare."], data: ["High-yield spread (FRED)", "BDC discounts to book (roadmap)"] },
    { id: "t7", t: "Hard-money hedges hedge debasement, not tightening", st: "active", wk: ["tp-gold-close-1022-23", "tp-btc-close-1022-23", "tp-dxy-close-1022-23"], stance: "Keep gold and bitcoin as small sleeves; do not count on them in a real-rate squeeze.",
      ev: ["Gold was $4,182 on Oct 13, up only 2.6% from a year earlier despite a war and an inflation spike.", "Bitcoin was $81,804 on Oct 19.", "Real yields near 3% raise the cost of holding assets that pay nothing."],
      ex: "A sized debasement sleeve rebalanced on rules.", hd: "T-bills and TIPS as the true safe leg.",
      kill: ["Real yields fall and the Fed turns to cuts: the sleeve should then lead."], data: ["10-year real yield (FRED)", "Broad dollar index (FRED)"] },
    { id: "t8", t: "Volatility is the cheapest contractual hedge", st: "active", wk: ["tp-vix-close-1022-23", "tp-vxn-close-1022-23", "tp-stock-bond-1022"], stance: "Run a standing tail budget instead of a bond hedge whose correlation can flip.",
      ev: ["Cboe flagged volatility and convexity premia at their lowest of the year in mid-August, before October's AI selloff.", "The Fed's own data show stocks and bonds falling together through July 2026.", "A put's payoff is contractual; a bond hedge's is statistical."],
      ex: "Up to 2% of NAV a year (the policy cap) in rolled index put spreads; bills and TIPS as the safe leg.", hd: "This is the hedge.",
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

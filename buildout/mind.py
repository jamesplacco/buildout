"""The mind: the brain and the engine as one graph, and a reasoning loop that runs on it.

One graph holds everything the engine knows and everything it does:
  concepts    about 600 ideas an investor needs (ontology.py), each with a plain definition, a formula where there is
              one, and typed relations (is_a, part_of, measures, causes+, causes-, uses, opposes, hedges, ...)
  markets     the atlas's 100 nodes: 72 measured monthly series and 28 judged drivers and holdings, with the links the
              atlas learned from data (graphical lasso, LiNGAM, structural VAR) as directed, signed causal edges
  evidence    about 400 sourced facts and papers (assets/knowledge.json, each checked on its page by a second agent) and
              the signals the engine derives from them and from its own tests (labs, atlas, research, ML, assumptions)
  voices      18 topics, 60 investors and 267 verified quotes
  engine      every Python module (its imports are edges), the methods, the MCP tools, the ML models and the tested
              assumptions, each linked to the concepts it implements
  sources     the information sources the engine profiles (newsletters, Taleb, Damodaran, primary data), linked to the
              concepts they inform
  world       213 economies, the S&P 500 companies with their sectors and industries, and the model book's positions
Clusters are hub nodes so a question about "commodities" can reach every commodity idea.

The reasoning loop (think) is the same in Python and on the page (site/src/mind.js; tests/test_v15.py holds them equal):
  1 read      the question is normalized and tokenized exactly as the voices library does (stems, synonyms, phrases)
  2 recall    BM25 over every node's name, aliases and text (damped for long kinds such as quotes), plus exact alias
              hits, picks up to 12 seed nodes scoring at least 30% of the best
  3 spread    personalized PageRank (spreading activation) from the seeds over the weighted, typed graph: 40 steps,
              continue probability 0.75, so what is two or three links away lights up in proportion to how connected it
              is to what was asked
  4 frame     the claim is the axis (an investor-voices topic, or "does this method give an edge?") whose evidence lit up
              most, framed bull or bear by the question's own wording
  5 weigh     each signal on that axis adds sign x strength x reliability x relevance to the log-odds of the bull case;
              within a source family the k-th strongest reading counts 1/sqrt(k), so ten readings of one fact count about
              five times one reading, not ten; investor opinion is one more, low-reliability signal; the belief network
              adds one capped row, the pull of connected claims
  6 test      leave-one-family-out gives the range of the verdict; the single signal whose removal moves it most is the
              hinge; each counting signal states what reading would flip it
  7 trace     the strongest causal chains from what lit up to the book run over the atlas's own learned links
  8 decide    the verdict meets the book: hold, or review a named hedge in the hedge book, written as an MCP proposal for
              a person to approve; nothing here executes

The belief network: thirteen claims are linked by the atlas's 12-month responses between each claim's representative
series; each claim's own evidence sets its base log-odds and mean-field propagation lets connected claims pull on one
another. "What if X, what happens to Y?" fixes X's claim at 90% (or 10%) and reads how Y, and the model book, re-settle.
"What is X?" returns X's definition beside the weighing.
"""
from __future__ import annotations

import ast
import heapq
import json
import math
import re
from pathlib import Path

from . import ontology, voices
from .core import cache

ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / "assets"

ALPHA = 0.75          # continue probability of the walk
STEPS = 40
SEEDS = 12
SEED_FLOOR = 0.3      # seeds keep at least this share of the best seed score
W_BM, W_ALIAS = 0.6, 1.0
DOC_W = (3, 2, 1)     # name, aliases, text repeats in a node's document
KIND_RECALL = {"month": 0.4, "year": 0.7, "finding": 0.8, "quote": 0.55, "signal": 0.8, "investor": 0.8, "country": 0.7, "company": 0.85, "industry": 0.85}   # long documents match everything; damp them as seeds
QSTOP = ["useful", "work", "works", "working", "good", "now", "keep", "still", "go", "away", "think", "thing", "make", "use", "need", "right",
         "time", "best", "way", "say", "tell", "explain", "mean", "meaning", "happen", "happens", "happened", "change", "changes"]
AXIS_TOPIC_BOOST = 1.5
EXPLAIN_RATIO = 0.12  # below this share of the top activation, the mind explains instead of weighing a claim

EDGE_W = {"is_a": 0.9, "part_of": 0.8, "measures": 0.8, "implemented_by": 0.6, "uses": 0.7, "related": 0.6, "opposes": 0.6,
          "causes+": 0.8, "causes-": 0.8, "example_of": 0.7, "hedges": 0.7, "priced_by": 0.6, "member": 0.35, "about": 0.6,
          "said_by": 0.8, "evidence": 0.7, "currency": 0.8, "exports": 0.6, "imports": 0.5, "code": 0.5, "method_of": 0.8,
          "tool": 0.7, "signal": 0.9, "cites": 0.6, "topic_of": 0.7, "analog": 0.5, "holds": 0.7, "routes": 0.6, "similar": 0.35}
TYPES = list(EDGE_W) + ["learned", "judged"]

GROUP_NAMES = {**{k: v for k, v in ontology.CLUSTERS.items()}, "markets": "Markets (atlas series)", "chronicle": "Market history, month by month", "core": "Core drivers and the book",
               "voices": "Investor voices", "engine": "The engine room", "world": "The world economy", "evidence": "Signals",
               "companies": "S&P 500 companies"}

FACT_CLUSTER = {"bonds": "rates", "tape": "macro", "distribution": "ai", "edge_sources": "edge", "model_risk": "reality", "ml_finance": "ml", "private_markets": "private", "asset_management": "assetmgmt", "indicators_valuation": "valuation", "commodities": "commodities",
                "games_negotiation_stats": "games", "trading_structure": "structure"}

# ---------------------------------------------------------------- axes: the claims the mind can weigh
EDGE_AXES = {
    "edge:trend": {"title": "Trend rules (the 200-day or 10-month average)", "bull": "Trend rules give an edge worth having", "bear": "Trend rules do not beat holding",
                   "node": "c:ma10m", "terms": ["c:ma200", "c:trend-following", "c:moving-average", "c:momentum"]},
    "edge:oscillators": {"title": "Oscillators (RSI, MACD, Bollinger)", "bull": "Overbought and oversold signals predict returns", "bear": "They are mostly noise after testing",
                         "node": "c:rsi", "terms": ["c:macd", "c:bollinger", "c:overbought", "c:golden-cross"]},
    "edge:valuation_timing": {"title": "Timing the market with valuation", "bull": "Valuation tells you future returns", "bear": "Valuation does not time the market",
                              "node": "c:cape", "terms": ["c:pe", "c:dividend-yield", "c:excess-cape-yield", "c:oos-r2"]},
    "edge:active": {"title": "Active management", "bull": "Active managers can beat the index", "bear": "Most cannot, after fees",
                    "node": "c:active-management", "terms": ["c:alpha", "c:skill-vs-luck", "c:fees", "c:passive-investing"]},
    "edge:seasonality": {"title": "Calendar effects (Sell in May)", "bull": "The calendar gives an edge", "bear": "Calendar effects are data mining",
                         "node": "c:seasonality", "terms": ["c:multiple-testing", "c:data-snooping"]},
    "edge:first_offer": {"title": "Haggling: who should open", "bull": "Make the first offer, and make it bold", "bear": "Let the other side open first",
                         "node": "c:first-offer", "terms": ["c:anchoring", "c:haggling", "c:negotiation-anchor", "c:zopa", "c:batna", "c:reservation-price"]},
    "edge:models": {"title": "Quant models in the real world", "bull": "The quant models hold up in the real world", "bear": "Their assumptions break; haircut every model",
                    "node": "c:model-risk", "terms": ["c:assumption-testing", "c:breakpoint", "c:fat-tails", "c:publication-decay", "c:sharpe-haircut", "c:backtest-live-gap"]},
    "edge:ml": {"title": "Machine learning for returns", "bull": "Machine learning predicts market returns", "bear": "Out of sample it mostly fits noise",
                "node": "c:machine-learning", "terms": ["c:random-forest", "c:gradient-boosting", "c:purged-cv", "c:cpcv", "c:covariate-shift"]},
    "edge:sizing": {"title": "Bet sizing and leverage", "bull": "Bet big and lever up when you have an edge", "bear": "Size small: ruin is permanent",
                    "node": "c:kelly", "terms": ["c:risk-of-ruin", "c:bankroll", "c:position-sizing", "c:leverage"]},
}
BOOK_SIGN = {"ai_boom": 1, "semis_nvidia": 1, "megacap_concentration": 1, "market_valuation": 1, "timing_crashes": 1, "speculation_manias": 1,
             "recession_economy": 1, "inflation_fed": 1, "bonds_rates": 1, "oil_energy": -1, "private_credit": 1, "value_growth": 1}
HEDGE_FOR = {"ai_boom": "ai_pair", "semis_nvidia": "ai_pair", "megacap_concentration": "degross", "market_valuation": "put_spread",
             "timing_crashes": "trend", "speculation_manias": "vix_calls", "recession_economy": "put_spread", "inflation_fed": "gold",
             "bonds_rates": "put_spread", "oil_energy": "gold", "private_credit": "beta_short", "value_growth": "degross"}
HEDGE_NAMES = {"tlt": "Long Treasuries (TLT)", "put_spread": "Index put spread 95/85", "collar": "Collar 90/110", "gold": "Gold sleeve",
               "vix_calls": "VIX call spread 25/40", "beta_short": "Short index futures", "ai_pair": "Short semiconductor basket", "trend": "Trend cut",
               "degross": "Run less equity"}

# ---------------------------------------------------------------- the world: economies, currencies and exports
# (iso3, name, atlas currency id or None, exports as atlas or concept ids, note)
COUNTRIES = [
    ("USA", "United States", "dollar", ["a:natgas", "a:wti", "a:soybeans", "a:maize", "c:lng"], "Issuer of the reserve currency; home of the AI buildout."),
    ("CHN", "China", "a:cny", ["c:china-demand"], "Buys about half the world's metals; its credit cycle drives the metals cycle."),
    ("JPN", "Japan", "a:jpy", ["c:carry-trade"], "Imports almost all its energy; the yen funds the world's carry trades."),
    ("DEU", "Germany", "a:eur", [], "Europe's industrial core."), ("IND", "India", "a:inr", [], "A large oil importer."),
    ("GBR", "United Kingdom", "a:gbp", [], "A global financial centre."), ("FRA", "France", "a:eur", [], "Euro area."),
    ("ITA", "Italy", "a:eur", ["a:olive"], "Euro area."), ("CAN", "Canada", "a:cad", ["a:wti", "a:natgas", "a:uranium"], "Oil, gas and uranium exporter."),
    ("BRA", "Brazil", "a:brl", ["a:soybeans", "a:ironore", "a:arabica", "a:sugar", "a:beef"], "The largest exporter of soybeans, coffee and sugar."),
    ("RUS", "Russia", None, ["a:brent", "a:gas_eu", "a:wheat", "a:nickel", "a:aluminum"], "Oil, gas, wheat and metals under sanctions."),
    ("KOR", "South Korea", "a:krw", ["c:hbm"], "Makes most of the world's high-bandwidth memory."),
    ("AUS", "Australia", "a:aud", ["a:ironore", "a:coal", "a:gold", "c:lng", "a:wool"], "Iron ore, coal, gold and LNG."),
    ("MEX", "Mexico", "a:mxn", ["a:wti"], "Tied to US manufacturing."), ("ESP", "Spain", "a:eur", ["a:olive"], "Euro area."),
    ("IDN", "Indonesia", None, ["a:palmoil", "a:coal", "a:nickel", "a:rubber", "a:tin"], "Palm oil, coal and nickel."),
    ("NLD", "Netherlands", "a:eur", ["a:gas_eu"], "Home of the TTF gas hub."), ("SAU", "Saudi Arabia", None, ["a:brent", "c:opec", "c:hormuz-strait", "c:spare-capacity"], "OPEC's swing producer."),
    ("TUR", "Turkey", None, [], "Straddles Europe's energy routes."), ("CHE", "Switzerland", "a:chf", ["a:gold"], "Gold refining; a haven currency."),
    ("TWN", "Taiwan", "a:twd", ["c:gpu", "c:custom-silicon"], "Makes most of the world's advanced chips."),
    ("POL", "Poland", None, [], "Fast-growing EU economy."), ("ARG", "Argentina", None, ["a:soybeans", "a:maize", "a:beef"], "Grain and soy exporter."),
    ("SWE", "Sweden", "a:sek", [], "Small open economy."), ("NOR", "Norway", "a:nok", ["a:brent", "a:gas_eu", "a:salmon"], "Oil, gas and salmon."),
    ("BEL", "Belgium", "a:eur", [], "Euro area."), ("IRN", "Iran", None, ["a:brent", "c:hormuz-strait"], "On the Strait of Hormuz."),
    ("ARE", "United Arab Emirates", None, ["a:brent", "c:hormuz-strait"], "Left OPEC and OPEC+ on May 1, 2026."),
    ("ISR", "Israel", None, [], "Technology exporter."), ("THA", "Thailand", "a:thb", ["a:rice", "a:rubber", "a:sugar"], "Rice, rubber and sugar."),
    ("SGP", "Singapore", "a:sgd", [], "Asia's trading and refining hub."), ("MYS", "Malaysia", "a:myr", ["a:palmoil", "a:rubber", "a:tin"], "Palm oil and tin."),
    ("ZAF", "South Africa", "a:zar", ["a:gold", "a:coal"], "Gold, platinum and coal."), ("NGA", "Nigeria", None, ["a:brent"], "Africa's large oil producer."),
    ("EGY", "Egypt", None, ["c:lng"], "Controls the Suez Canal; a large wheat importer."), ("PHL", "Philippines", None, [], "Remittances and services."),
    ("VNM", "Viet Nam", None, ["a:robusta", "a:rice", "a:shrimp"], "Robusta coffee and rice."), ("CHL", "Chile", None, ["a:copper"], "The largest copper producer."),
    ("PER", "Peru", None, ["a:copper", "a:gold", "a:zinc", "a:fishmeal"], "Copper, gold and fishmeal."), ("COL", "Colombia", None, ["a:arabica", "a:coal", "a:brent"], "Coffee, coal and oil."),
    ("NZL", "New Zealand", "a:nzd", ["a:lamb", "a:wool"], "Dairy, lamb and wool."), ("QAT", "Qatar", None, ["c:lng", "c:hormuz-strait"], "A top LNG exporter; Ras Laffan was damaged in 2026."),
    ("KWT", "Kuwait", None, ["a:brent", "c:hormuz-strait"], "Exports through Hormuz."), ("IRQ", "Iraq", None, ["a:brent", "c:hormuz-strait"], "Exports through Hormuz."),
    ("CIV", "Cote d'Ivoire", None, ["a:cocoa"], "The largest cocoa grower."), ("GHA", "Ghana", None, ["a:cocoa", "a:gold"], "Cocoa and gold."),
    ("KAZ", "Kazakhstan", None, ["a:uranium", "a:brent"], "The largest uranium miner."), ("UKR", "Ukraine", None, ["a:wheat", "a:maize", "a:sunflower"], "Wheat, maize and sunflower oil."),
]

TOOL_MODULES = {"get_research_snapshot": ["research"], "get_portfolio_risk": ["pipeline"], "analyze_positions": ["valuation", "pipeline"],
                "decision_loop": ["ooda"], "position_valuation": ["valuation"], "hedge_book": ["hedgebook"], "investor_voices": ["voices"],
                "atlas_trace": ["atlas"], "brain_selfcheck": ["brain_robust"], "run_hedge_scenario": ["policy"], "evaluate_trade": ["reasoner"],
                "create_order_proposal": ["mcp_server"], "review_decision": ["decisions"], "compare_explanations": ["field"],
                "learned_structure": ["discovery"], "trace_exposure": ["thinking"], "reason": ["mind"], "labs_lookup": ["labs"],
                "game_math": ["games2"]}

METHODS = {"labs-trend": ("Trend lab", "The 10-month and 22 other moving-average rules on 156 years, with a stationary bootstrap, an SPA-style max test and a deflated Sharpe."),
           "labs-oscillators": ("Oscillator lab", "RSI, MACD, Bollinger, golden cross and 52-week-high signals tested against forward returns with Newey-West errors."),
           "labs-indicators": ("Indicator kernel", "SMA, EMA, Wilder RSI, MACD, Bollinger bands and drawdown, the same arithmetic on the page."),
           "labs-valuation": ("Valuation lab", "CAPE, trailing P/E, dividend yield and the excess CAPE yield against 1- and 10-year real returns, with out-of-sample R squared."),
           "labs-regimes": ("Regime lab", "Hamilton's two-state Markov switching model of monthly S&P 500 returns by EM, with the Kim smoother."),
           "labs-volatility": ("Volatility lab", "GARCH(1,1) by quasi maximum likelihood for Brent, WTI and gas, with tail indexes."),
           "labs-spreads": ("Spread lab", "Engle-Granger cointegration of Brent and WTI with simulated p-values, the spread's half-life and z-score; gold/oil."),
           "labs-randomness": ("Randomness lab", "Lo-MacKinlay variance ratios against a random walk and against Working's averaging null."),
           "labs-calendar": ("Calendar lab", "Sell in May since 1871 and since 1950, and natural gas seasonality."),
           "labs": ("Multiple testing", "Every p-value from the labs in one table with Holm and Benjamini-Hochberg corrections."),
           "ml-walkforward": ("Purged walk-forward", "Expanding-window refits that only train on rows whose 12-month outcome had ended, plus an embargo.", "ml"),
           "ml-cpcv": ("Combinatorial purged CV", "28 purged splits of 8 time blocks and the probability that the in-sample winner misleads.", "ml"),
           "ml-conformal": ("Conformal intervals", "Forecast intervals from the models' own past errors, with their realised coverage.", "ml"),
           "ml-analogs": ("Historical analogs", "The months most like today and what followed.", "ml"),
           "ml-novelty": ("Novelty detection", "How far today sits from its nearest historical neighbours.", "ml"),
           "as-tests": ("Assumption tests", "Fat tails, dependence, stability and correlation, each tested on the data.", "assumptions"),
           "as-breakpoints": ("Breakpoints", "The cost, delay, edge error or correlation at which each model's conclusion flips.", "assumptions"),
           "as-worlds": ("Stressed worlds", "400 block-bootstrapped histories in which each decision is re-run.", "assumptions"),
           "as-kappa": ("Taleb's kappa", "Fat-tailedness in sample-size terms, for stocks, oil, gas and the VIX.", "assumptions"),
           "as-fragility": ("Fragility heuristic", "Whether the book's losses accelerate in the tail, with and without each hedge.", "assumptions"),
           "dm-erp": ("Implied equity risk premium", "The discount rate that equates the index with its expected cash flows.", "damodaran"),
           "dm-dcf": ("Narrative-to-numbers DCF", "A story turned into growth, margin, reinvestment, cost of capital and failure risk.", "damodaran"),
           "ta-indicators": ("Indicator library", "Moving averages, RSI, MACD, Bollinger, ATR, ADX, stochastic, Ichimoku, Supertrend, SAR, OBV, money flow.", "technicals"),
           "ta-event": ("Signal event study", "Each signal's edge on the asset's own history, Newey-West t and false-discovery control; weights shrink with evidence.", "technicals"),
           "fa-statements": ("Statements from filings", "Annual statements from XBRL company facts, latest filing wins, tags recorded.", "statements"),
           "fa-scores": ("Piotroski, Altman and Beneish", "The three classic accounting scores, with unknown inputs marked unknown.", "statements"),
           "rl-fqi": ("Fitted Q iteration sizing", "Offline reinforcement learning over trend, volatility, valuation and drawdown, walk-forward from 1940.", "rl"),
           "dh-check": ("Data connection check", "Credentials and reachability for every data source, with fallbacks per ticker.", "datahub")}
INDUSTRY_CONCEPTS = {"Semiconductors": ["c:gpu", "c:semis-cycle", "c:custom-silicon"], "Semiconductor Materials & Equipment": ["c:semis-cycle", "c:capex"],
                     "Systems Software": ["c:cloud", "c:hyperscaler"], "Application Software": ["c:cloud", "c:ai-revenue"], "Interactive Media & Services": ["c:hyperscaler", "c:ai-capex"],
                     "Broadline Retail": ["c:cloud"], "Internet Services & Infrastructure": ["c:data-center", "c:neocloud"], "Data Center REITs": ["c:data-center", "c:leases"],
                     "Electric Utilities": ["c:power-demand"], "Independent Power Producers & Energy Traders": ["c:power-demand", "c:spark-spread"], "Multi-Utilities": ["c:power-demand"],
                     "Heavy Electrical Equipment": ["c:power-demand", "c:energy-transition"], "Electrical Components & Equipment": ["c:power-demand", "c:data-center"],
                     "Technology Hardware, Storage & Peripherals": ["c:hbm", "c:data-center"], "Communications Equipment": ["c:data-center"], "Electronic Components": ["c:data-center"],
                     "Integrated Oil & Gas": ["c:brent", "c:oil-shock"], "Oil & Gas Exploration & Production": ["c:wti", "c:brent"], "Oil & Gas Refining & Marketing": ["c:crack-spread"],
                     "Oil & Gas Storage & Transportation": ["c:natural-gas", "c:lng"], "Oil & Gas Equipment & Services": ["c:capex", "c:brent"], "Gold": ["c:gold"], "Copper": ["c:copper"],
                     "Steel": ["c:iron-ore"], "Fertilizers & Agricultural Chemicals": ["c:grains"], "Agricultural Products & Services": ["c:grains", "c:softs"],
                     "Asset Management & Custody Banks": ["c:aum", "c:private-credit", "c:private-equity"], "Investment Banking & Brokerage": ["c:market-maker", "c:ipo"],
                     "Financial Exchanges & Data": ["c:market-liquidity", "c:zero-dte"], "Diversified Banks": ["c:credit-spread", "c:reserves"], "Regional Banks": ["c:svb-2023", "c:duration"],
                     "Consumer Finance": ["c:credit-spread"], "Transaction & Payment Processing Services": ["c:stablecoin"], "Automobile Manufacturers": ["c:tariffs"],
                     "Homebuilding": ["c:ten-year-yield"], "Passenger Airlines": ["c:oil-shock"], "Multi-Sector Holdings": ["c:value-investing"]}
SECTOR_CONCEPTS = {"Information Technology": "x:ai", "Communication Services": "x:ai", "Energy": "x:commodities", "Materials": "x:commodities", "Financials": "x:assetmgmt",
                   "Utilities": "c:power-demand", "Real Estate": "c:ten-year-yield", "Consumer Discretionary": "c:gdp", "Consumer Staples": "c:inflation",
                   "Health Care": "c:gdp", "Industrials": "c:capex"}
# Each axis's representative node in the atlas, and the sign that links the axis's bull statement to that node rising.
AXIS_REP = {"oil_energy": ("brent", 1), "inflation_fed": ("cpi", -1), "bonds_rates": ("y10", -1), "market_valuation": ("sp500", 1), "timing_crashes": ("vix", -1),
            "speculation_manias": ("liq", 1), "recession_economy": ("consumer", 1), "ai_boom": ("aidemand", 1), "semis_nvidia": ("NVDA", 1), "megacap_concentration": ("book", 1),
            "gold": ("gold", 1), "dollar_debt": ("dollar", 1), "private_credit": ("pcredit", -1), "china_em": ("cny", 1)}
NET_GAMMA = 0.6      # one unit of a certain parent belief moves a child's log-odds by gamma x the link weight
NET_CAP = 0.3        # the network row in a verdict is capped: connected claims inform a claim, they never decide it
NET_MIN = 0.15       # links weaker than this share of the strongest are dropped
NET_ITERS = 60
WHATIF_UP = ["rise", "rises", "rising", "up", "higher", "surge", "surges", "spike", "spikes", "jump", "jumps", "soar", "soars", "double", "doubles", "climb",
             "climbs", "rally", "rallies", "boom", "booms", "accelerate", "accelerates", "goes", "hits", "reaches", "stays", "strengthens", "hike", "hikes", "widen", "widens"]
WHATIF_DOWN = ["fall", "falls", "drop", "drops", "crash", "crashes", "slow", "slows", "slump", "slumps", "plunge", "plunges", "collapse", "collapses", "lower",
               "down", "cut", "cuts", "decline", "declines", "halve", "halves", "weaken", "weakens", "ease", "eases", "narrow", "narrows", "fades", "fade"]
WHATIF_SPLIT = [",", " then ", " what ", " how ", " does ", " do ", " will ", " should ", " is ", " are ", " would "]
RX_WHATIF = r"^\s*(?:what\s+if|if|suppose|assume|assuming|imagine)\s+(.+)$"
RX_BOOK = r"\b(?:the|my|our|this)\s+(?:model\s+)?(?:book|portfolio|positions?|holdings)\b"
RX_MONTH = r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(18[7-9]\d|19\d\d|20[0-2]\d)\b"
RX_YEAR = r"\b(18[7-9]\d|19\d\d|20[0-2]\d)\b"
RX_NOW = r"\b(?:months? like (?:now|today)|like today|historical analogs?|analog months?|now in history|history rhymes?)\b"
RX_HIST = r"\b(?:what happened|happened in|in history|history of|remember|back in|like in|episode|crash of|panic of)\b"
MON3 = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
RX_DECIDE = (r"\b(?:what should (?:i|we|the (?:model )?book) (?:do|hold|own|buy)|how much (?:in )?(?:stocks?|equit(?:y|ies))|(?:stock|equity|market) exposure|"
             r"allocat(?:e|ion)|position siz(?:e|ing)|decision engine|(?:what|which) regime|regime (?:are we|now|today)|risk[- ]on|risk[- ]off|stay invested|de-?risk)\b")
RX_PSTRESS = (r"(?:stress(?:ed)?|bear|crash|recession|risk[- ]off)\s*(?:regime\s*)?(?:odds|probability|chance|risk)?\s*(?:of|at|to|is|are|were|was|be|hits?|reach(?:es)?|rises? to|rose to|=)?\s*(\d{1,3}(?:\.\d+)?)\s*%"
              r"|(\d{1,3}(?:\.\d+)?)\s*%\s*(?:odds|chance|probability)\s*(?:of\s*)?(?:a\s*|the\s*)?(?:stress(?:ed)?|bear|crash|recession|risk[- ]off)")
RX_R12 = r"(?:forecast|expected (?:real )?return|returns? next year|next year's return)\s*(?:of|at|is|to|=)?\s*([+\-\u2212]?\d{1,2}(?:\.\d+)?)\s*%"
RX_GAMMA = r"risk aversion\s*(?:of|at|is|to|=)?\s*(\d{1,2}(?:\.\d+)?)"
RX_EXPLAIN = r"^\s*(?:what\s+is|what's|whats|what\s+are|define|explain|meaning\s+of|tell\s+me\s+about)\b"
ENGINE_ALIAS = {"book": "pipeline", "brain-robust": "brain_robust", "causal": "causal_stats", "robust-bt": "analytics.robust_bt",
                "options": "analytics.options", "trading": "microstructure", "reason": "reasoner"}


def norm(text: str) -> str:
    """Lower case, every run of non-alphanumerics to one space, padded: ' p e ratio '."""
    return " " + re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip() + " "


def slug(name: str) -> str:
    n = re.sub(r"\(.*?\)", "", name)
    words = [w for w in re.split(r"[^A-Za-z]+", n) if len(w) > 1]
    return "-".join(w.lower() for w in words)


def _engine_modules() -> list[dict]:
    """Every engine module, its first docstring paragraph, its internal imports and size; cached by the files' contents."""
    files = sorted(ROOT.glob("*.py")) + sorted((ROOT / "analytics").glob("*.py")) + sorted((ROOT / "data").glob("*.py")) + sorted((ROOT / "core").glob("*.py"))
    return _engine_modules_of(tuple((str(f), f.read_bytes()) for f in files))


@cache.memo("mind.engine_modules")
def _engine_modules_of(srcs: tuple) -> list[dict]:
    out = []
    files = [Path(p) for p, _ in srcs]
    for f in files:
        if f.name in ("__init__.py", "__main__.py"):
            continue
        mod = f.stem if f.parent == ROOT else f.parent.name + "." + f.stem
        src = f.read_text()
        tree = ast.parse(src)
        doc = (ast.get_docstring(tree) or "").strip()
        first = doc.split("\n\n")[0].replace("\n", " ").strip()
        imps = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level >= 1:
                base = (node.module or "")
                if f.parent != ROOT and node.level == 1:
                    pref = f.parent.name + "."
                    if base:
                        imps.add(pref + base)
                    else:
                        imps.update(pref + a.name for a in node.names)
                    continue
                if f.parent != ROOT and node.level == 2:
                    if base:
                        imps.add(base)
                    else:
                        imps.update(a.name for a in node.names)
                    continue
                if base:
                    imps.add(base)
                else:
                    imps.update(a.name for a in node.names)
        out.append({"module": mod, "doc": first[:420], "imports": sorted(imps), "lines": src.count("\n") + 1})
    names = {m["module"] for m in out}
    for m in out:
        m["imports"] = [i for i in m["imports"] if i in names and i != m["module"]]
    return out


def load_knowledge(path: Path | None = None) -> list[dict]:
    p = path or (ASSETS / "knowledge.json")
    if not p.exists():
        return []
    d = json.loads(p.read_text())
    return d["items"] if isinstance(d, dict) else d


def load_companies(path: Path | None = None) -> list[dict]:
    p = path or (ASSETS / "companies.json")
    return json.loads(p.read_text())["companies"] if p.exists() else []


def load_positions(snap11: Path | None = None) -> dict:
    """Each holding's reverse-DCF read from the decision loop's snapshot (site/src/snap11.js) or a daily ooda.json."""
    p = snap11 or (ROOT.parent / "site" / "src" / "snap11.js")
    try:
        if p.suffix == ".json":
            o = json.loads(p.read_text())
        else:
            s = p.read_text()
            i = s.index("const OODA_SNAP = ") + len("const OODA_SNAP = ")
            o, _ = json.JSONDecoder().raw_decode(s[i:])
        return o["orient"]["positions"]
    except (OSError, ValueError, KeyError):
        return {}


def load_countries(path: Path | None = None) -> dict:
    p = path or (ASSETS / "world.json")
    if not p.exists():
        return {}
    return json.loads(p.read_text())["countries"]


def _fmt(x, d=1):
    return f"{x:,.{d}f}"


# ---------------------------------------------------------------- signals: evidence with a direction
def signals(K: dict, L: dict | None, research_latest: dict | None, cape_pct: float | None) -> list[dict]:
    """Every signal the mind weighs. Values come from the verified knowledge items (K, by id), the labs (L) and the
    research run, so a correction to a source flows through. Each: axis, sign (+1 supports the axis's bull statement),
    strength (log-odds units when fully relevant and fully reliable), reliability (how well this kind of evidence has
    predicted out of sample or how certain the fact is), group (signals in one group share a dependence discount),
    refs (nodes it rests on), flip (the reading that would reverse it)."""
    S = []

    def v(kid):
        it = K.get(kid)
        return None if it is None else it.get("value")

    def add(sid, axis, sign, s, rel, group, text, refs, flip, targets=()):
        refs = [r for r in refs if r.startswith(("e:", "m:", "a:", "c:")) or r[2:] in K]
        if any(r.startswith("k:") and r[2:] not in K for r in refs):
            return
        S.append({"id": "s:" + sid, "axis": axis, "sign": sign, "s": s, "rel": rel, "group": group, "text": text, "refs": refs, "flip": flip,
                  "targets": list(targets)})

    # valuation of the market
    cape = v("val-cape-2026-10-20")
    if cape is not None:
        pct = f", above {cape_pct:.0%} of months since 1881" if cape_pct is not None else ""
        imp = ""
        if L and L["valuation"]["cape"].get("now_source") == "research":
            c = L["valuation"]["cape"]
            imp = f" History implies {c['implied_10y_real']:.1%} a year after inflation for ten years (80% range {c['range80'][0]:.0%} to {c['range80'][1]:.0%})."
        add("cape", "market_valuation", -1, 1.0, 0.6, "valuation", f"Shiller CAPE is {cape:.1f} (Oct 20, secondary source){pct}.{imp}",
            ["k:val-cape-2026-10-20", "m:labs-valuation", "c:cape"], "CAPE back under about 25, or earnings catching up with price.", ["c:cape", "c:valuation-level"])
    tpe = v("val-spx-trailing-pe-2026-10-16")
    if tpe is not None:
        add("tpe", "market_valuation", -1, 0.4, 0.5, "valuation", f"Trailing P/E is {tpe:.1f} against a 10-year average of 23.6.",
            ["k:val-spx-trailing-pe-2026-10-16", "c:pe"], "Trailing P/E back to its 10-year average.", ["c:pe"])
    fpe = v("val-spx-forward-pe-2026-10-16")
    if fpe is not None:
        add("fpe", "market_valuation", 1, 0.35, 0.4, "valuation", f"Forward P/E is {fpe:.1f}, at its 10-year average of 19.1, because earnings are expected to grow fast.",
            ["k:val-spx-forward-pe-2026-10-16", "c:forward-pe"], "Estimates cut: forward P/E rises without the price rising.", ["c:forward-pe"])
    bi = v("val-buffett-indicator-2026-10-20")
    if bi is not None:
        add("buffett", "market_valuation", -1, 0.5, 0.35, "valuation", f"Market value is {bi:.0f}% of GDP (Buffett indicator), far above any earlier peak.",
            ["k:val-buffett-indicator-2026-10-20", "c:buffett-indicator"], "Market cap to GDP back toward 150%.", ["c:buffett-indicator"])
    erp = v("val-erp-damodaran-2026-10-01")
    if erp is not None:
        add("erp", "market_valuation", 1, 0.25, 0.45, "rates_val", f"Damodaran's implied equity risk premium is {erp:.2f}%, near its own long-run range, so stocks are not priced for zero premium.",
            ["k:val-erp-damodaran-2026-10-01", "c:equity-risk-premium"], "An implied premium under 3%.", ["c:equity-risk-premium"])
    g26 = v("val-spx-cy2026-eps-growth")
    if g26 is not None:
        add("eps", "market_valuation", 1, 0.7, 0.55, "earnings", f"Analysts expect 2026 S&P 500 earnings growth of {g26:.1f}%; Q3 is tracking 29% with 84% of reporters beating.",
            ["k:val-spx-cy2026-eps-growth", "k:val-spx-q3-2026-eps-growth", "c:earnings-growth"], "A season of misses and falling 2027 estimates.", ["c:earnings-growth", "c:eps"])
        add("eps2", "recession_economy", 1, 0.45, 0.5, "earnings", f"Expected 2026 earnings growth of {g26:.1f}% is not what a recession looks like.",
            ["k:val-spx-cy2026-eps-growth", "c:earnings-growth"], "Estimates falling for two months in a row.", ["c:earnings-growth", "c:recession"])
    if L:
        tr = L["trend"]
        now = tr["now"]
        add("trend_now", "timing_crashes", 1 if now["above"] else -1, 0.4, 0.4, "trend",
            f"The S&P 500 is {now['gap']:+.1%} from its 10-month average ({now['date']}), so the trend rule says stay invested." if now["above"] else
            f"The S&P 500 is {now['gap']:+.1%} below its 10-month average ({now['date']}), so the trend rule says step aside.",
            ["m:labs-trend", "c:ma10m", "a:sp500"], "A month-end close below the 10-month average.", ["c:ma10m", "c:ma200"])
        add("trend_now_v", "market_valuation", 1 if now["above"] else -1, 0.25, 0.35, "trend", f"Price trend is {'up' if now['above'] else 'down'}: {now['gap']:+.1%} versus the 10-month average.",
            ["m:labs-trend", "c:momentum"], "A break below the 10-month average.", ["c:momentum"])
        sd = tr["sharpe_diff"]
        add("trend_sharpe", "edge:trend", 1, 0.35, 0.5, "trend_test", f"On 156 years, acting a month late, the 10-month rule's Sharpe is {tr['full']['rule']['sharpe']:.2f} against {tr['full']['hold']['sharpe']:.2f} for holding (90% range of the gain {sd['lo']:+.2f} to {sd['hi']:+.2f}).",
            ["m:labs-trend", "c:sharpe-ratio", "c:stationary-bootstrap"], "A bootstrap range of the gain that sits below zero.", ["c:ma10m"])
        add("trend_dd", "edge:trend", 1, 0.6, 0.7, "trend_test", f"Its worst drawdown is {tr['full']['rule'].get('maxdd', -0.48):.0%} against {tr['full']['hold'].get('maxdd', -0.77):.0%}; the cut in drawdown is clearly above zero.",
            ["m:labs-trend", "c:drawdown", "c:max-drawdown"], "A sample in which the rule's drawdown is no better.", ["c:drawdown"])
        add("trend_spa", "edge:trend", -1, 0.6, 0.7, "trend_test", f"On return alone, the best of 22 lengths is what luck produces {tr['spa_p']:.0%} of the time: no return edge after testing them all.",
            ["m:labs-trend", "c:data-snooping", "c:multiple-testing"], "A length that survives the max test.", ["c:data-snooping"])
        add("trend_dsr", "edge:trend", -1, 0.4, 0.6, "trend_test", f"The deflated excess Sharpe over holding is {tr['deflated']['excess_sharpe_annual']:+.2f} a year.",
            ["m:labs-trend", "c:deflated-sharpe"], "A positive deflated excess Sharpe.", ["c:deflated-sharpe"])
        add("trend_naive", "edge:trend", -1, 0.3, 0.8, "trend_test", f"Acting on the same month inflates the Sharpe to {tr['full']['naive']['sharpe']:.2f}: monthly averaging (Working 1960) flatters trend rules on averaged data.",
            ["m:labs-trend", "c:time-averaging"], "Daily data that show the same gain.", ["c:time-averaging"])
        add("trend_dd2", "risk_leverage_hedging", -1, 0.35, 0.6, "trend_test", "A trend rule cut the worst drawdown from -77% to -48% at a cost of about 1.4 points of return a year: protection that works, at a price.",
            ["m:labs-trend", "c:drawdown"], "A rule that costs more than it saves.", ["c:drawdown", "c:hedge"])
        add("timing_ret", "timing_crashes", 1, 0.5, 0.6, "trend_test", "Timing rules lowered risk but not return in 156 years: holding compounded faster (7.1% against 5.7% real).",
            ["m:labs-trend", "c:ma10m"], "A timing rule that beats holding on return after costs.", ["c:ma10m", "c:crash"])
        osc = L.get("oscillators") or []
        mt = {r["test"]: r for r in L["multiple_testing"]["rows"]}
        n_osc = sum(1 for o in osc if (o["name"] + " / " + o["asset"]) in mt)
        n_pass = sum(1 for o in osc if (o["name"] + " / " + o["asset"]) in mt and mt[o["name"] + " / " + o["asset"]]["bh"] < 0.05)
        if osc:
            share = n_pass / max(1, n_osc) if n_osc else sum(1 for o in osc if o["p"] < 0.05) / len(osc)
            label = f"{n_pass} of {n_osc}" if n_osc else f"{sum(1 for o in osc if o['p'] < 0.05)} of {len(osc)}"
            add("osc", "edge:oscillators", 1 if share > 0.5 else -1, 0.6, 0.65, "osc_test", f"Of the oscillator signals the labs tested, {label} pass at 5% after the false discovery rate correction.",
                ["m:labs-oscillators", "c:rsi", "c:fdr"], "Most of them passing on new data.", ["c:rsi", "c:macd"])
        r = L["readings"]["sp500"]
        add("rsi_now", "timing_crashes", -1 if r["rsi14"] > 70 else 1, 0.15, 0.2, "osc_now", f"Monthly RSI of the S&P 500 is {r['rsi14']:.0f}{' (overbought by the textbook)' if r['rsi14'] > 70 else ''}; the labs find such readings weak on their own.",
            ["m:labs-oscillators", "c:rsi", "a:sp500"], "RSI back in the middle of its range.", ["c:rsi", "c:overbought"])
        va = L["valuation"]["signals"]
        c10 = va["CAPE"]["10y"]
        c1 = va["CAPE"]["1y"]
        add("val10", "edge:valuation_timing", 1, 0.6, 0.6, "val_test", f"CAPE explains a share of ten-year real returns out of sample (OOS R squared {c10.get('oos_r2', 0):.2f}); the excess CAPE yield does better ({va['Excess CAPE yield']['10y'].get('oos_r2', 0):.2f}).",
            ["m:labs-valuation", "c:oos-r2", "c:cape"], "A negative out-of-sample R squared at ten years.", ["c:cape", "c:oos-r2"])
        add("val1", "edge:valuation_timing", -1, 0.7, 0.6, "val_test", f"Over one year it explains almost nothing (OOS R squared {c1.get('oos_r2', 0):.2f}): valuation is a decade tool, not a timing tool.",
            ["m:labs-valuation", "c:oos-r2"], "A one-year OOS R squared above 0.05.", ["c:cape"])
        add("val_crash", "timing_crashes", -1, 0.2, 0.3, "val_test", "High valuations lower ten-year returns but say little about the next year.",
            ["m:labs-valuation", "c:cape"], "Valuations back near average.", ["c:cape"])
        reg = L["regimes"]
        add("regime", "timing_crashes", 1 if reg["p_now"][1] < 0.5 else -1, 0.3, 0.4, "regime", f"Markov switching puts today's chance of the turbulent regime at {reg['p_now'][1]:.0%} (calm regimes last about {reg['duration'][0]:.0f} months on average).",
            ["m:labs-regimes", "c:markov-switching", "c:regime"], "The turbulent-regime probability above 50%.", ["c:regime", "c:markov-switching"])
        add("regime2", "speculation_manias", 1, 0.25, 0.35, "regime", f"Calm regime ({reg['p_now'][0]:.0%} probability): manias tend to run while volatility is low.",
            ["m:labs-regimes", "c:regime"], "Volatility regime turning turbulent.", ["c:regime"])
        cal = L["calendar"]
        add("may50", "edge:seasonality", 1, 0.45, 0.4, "cal_test", f"Since 1950, November to April beat May to October (p = {cal['since 1950']['diff']['p']:.3f}).",
            ["m:labs-calendar", "c:seasonality"], "The gap vanishing in the next decade.", ["c:seasonality", "c:sell-in-may"])
        add("may1871", "edge:seasonality", -1, 0.4, 0.6, "cal_test", f"On the full sample since 1871 it is weaker (p = {cal['since 1871']['diff']['p']:.3f}), and the 1950 start is a choice made after seeing the data.",
            ["m:labs-calendar", "c:data-snooping"], "Significance on the full sample.", ["c:data-snooping"])
        tails = L["volatility"]["sp500_monthly_tails"]
        add("tails", "risk_leverage_hedging", -1, 0.35, 0.6, "tails", f"Monthly S&P 500 returns have kurtosis {tails['kurtosis']:.0f} (3 for a bell curve) and a tail index near {tails['hill_alpha']:.1f}: crashes are far more common than a normal model says.",
            ["m:labs-volatility", "c:fat-tails", "c:hill-estimator"], "Thin tails, which no long sample has shown.", ["c:fat-tails"])
        b = L["readings"]["brent"]
        add("brent_trend", "oil_energy", 1 if b["vs_ma200"] > 0 else -1, 0.3, 0.35, "oil_trend", f"Brent ${b['price']:.2f} ({b['date']}) is {b['vs_ma200']:+.0%} from its 200-day average of ${b['ma200']:.1f}{'; the 50-day is above the 200-day' if b['golden'] else ''}.",
            ["m:labs-indicators", "c:ma200", "a:brent"], "Brent back under its 200-day average.", ["c:ma200", "c:brent"])
        vb = L["volatility"]["brent"]
        add("brent_vol", "risk_leverage_hedging", -1, 0.2, 0.5, "vol", f"Brent's GARCH volatility is {vb['annual_current']:.0%} a year against a long-run {vb['annual_long']:.0%}.",
            ["m:labs-volatility", "c:garch", "a:brent"], "Volatility back to its long-run level.", ["c:garch", "c:volatility"])
        sp = L["spreads"]["brent_wti"]
        add("bw", "oil_energy", -1, 0.15, 0.3, "oil_spread", f"Brent-WTI is ${sp['spread_now']:.2f}, {sp['z_now']:.1f} standard deviations wide; the pair is cointegrated with a half-life near {sp['half_life']:.0f} days, so the gap tends to close from the Brent side when the shock fades.",
            ["m:labs-spreads", "c:brent-wti", "c:cointegration"], "The spread widening further.", ["c:brent-wti"])
        go = L["spreads"]["gold_oil"]
        add("gold_oil", "gold", -1, 0.15, 0.25, "gold_val", f"An ounce of gold buys {go['now']:.0f} barrels of Brent ({go['date']}), more than in {go['percentile']:.0%} of months since {go.get('from', '1987')[:4]}: gold is dear against oil.",
            ["m:labs-spreads", "c:gold"], "The ratio back near its median of 19.", ["c:gold"])
    # rates and bonds
    y10 = v("val-ust10y-2026-10-21")
    if y10 is not None:
        add("y10", "bonds_rates", 1, 0.4, 0.4, "rates", f"The 10-year Treasury yields {y10:.2f}% (Oct 21), high enough to pay for holding duration.",
            ["k:val-ust10y-2026-10-21", "c:ten-year-yield", "a:y10"], "Yields falling back under 4%.", ["c:ten-year-yield"])
        add("y10i", "inflation_fed", -1, 0.35, 0.4, "rates", f"A {y10:.2f}% 10-year yield says the bond market does not think inflation is beaten.",
            ["k:val-ust10y-2026-10-21", "c:ten-year-yield"], "The 10-year back under 4.5%.", ["c:ten-year-yield", "c:inflation"])
        add("y10g", "gold", -1, 0.35, 0.4, "rates", f"With the 10-year at {y10:.2f}%, holding gold costs a high yield given up.",
            ["k:val-ust10y-2026-10-21", "c:real-yield"], "Yields falling.", ["c:real-yield"])
        add("y10d", "dollar_debt", -1, 0.3, 0.35, "rates", f"A {y10:.2f}% 10-year raises the interest bill on a large federal debt.",
            ["k:val-ust10y-2026-10-21", "c:government-debt"], "Yields falling with deficits.", ["c:government-debt"])
    if research_latest:
        c = research_latest.get("corr")
        if c is not None:
            add("sbcorr", "bonds_rates", -1 if c > 0 else 1, 0.5, 0.55, "corr", f"The 36-month stock-bond correlation is {c:+.2f} ({research_latest.get('month')}): {'bonds have been falling with stocks, a weak hedge' if c > 0 else 'bonds have been rising when stocks fall'}.",
                ["e:research", "c:stock-bond-correlation", "a:corr"], "A correlation that turns negative.", ["c:stock-bond-correlation", "c:tlt"])
    fms6 = v("am-bofa-fms-2026-10-yield-trigger")
    if fms6 is not None:
        add("fms6", "bonds_rates", 1, 0.2, 0.25, "sentiment", f"{fms6:.0f}% of fund managers say they would move into bonds at a 6% 10-year (BofA, October; secondary report).",
            ["k:am-bofa-fms-2026-10-yield-trigger"], "Buyers stepping back at 6%.", ["c:fund-manager-survey"])
    # oil
    inv = v("oil-iea-omr-inventories-sep2026")
    if inv is not None:
        add("oil_inv", "oil_energy", 1, 0.5, 0.6, "oil_supply", f"Global observed oil stocks are {abs(inv):.0f} million barrels below end-February (IEA).",
            ["k:oil-iea-omr-inventories-sep2026", "c:inventories"], "Stocks rebuilding for three months.", ["c:inventories", "c:storage-theory"])
    fb = v("oil-iea-omr-brent-dated-oct2026")
    if fb is not None:
        add("oil_curve", "oil_energy", 1, 0.45, 0.5, "oil_supply", f"Dated (physical) Brent near $134 against futures near ${fb:.0f}: steep backwardation means barrels are short now.",
            ["k:oil-iea-omr-brent-dated-oct2026", "c:backwardation"], "The curve flattening into contango.", ["c:backwardation", "c:convenience-yield"])
    hz = v("oil-iea-omr-hormuz-flows-sep2026")
    if hz is not None:
        add("oil_hormuz", "oil_energy", -1, 0.6, 0.6, "oil_supply", f"Oil through the Strait of Hormuz recovered to {hz:.1f} mb/d in September (IEA monthly estimate; daily tanker counts in early October were still far below pre-war): supply is coming back.",
            ["k:oil-iea-omr-hormuz-flows-sep2026", "c:hormuz-strait", "a:hormuz"], "Flows falling again.", ["c:hormuz-strait", "c:oil-shock"])
    dem = v("oil-iea-omr-demand-2026")
    if dem is not None:
        add("oil_dem", "oil_energy", -1, 0.5, 0.6, "oil_demand", f"The IEA has world oil demand falling {abs(dem):.1f} mb/d in 2026: high prices are destroying demand.",
            ["k:oil-iea-omr-demand-2026", "c:oil-shock"], "Demand revised up.", ["c:brent"])
        add("oil_dem2", "recession_economy", -1, 0.35, 0.45, "oil_demand", f"Oil demand falling {abs(dem):.1f} mb/d is a sign of strain on the world economy.",
            ["k:oil-iea-omr-demand-2026", "c:recession"], "Demand stabilizing.", ["c:recession"])
    eia = v("oil-eia-steo-brent-forecast-oct2026")
    if eia is not None:
        add("oil_eia", "oil_energy", -1, 0.5, 0.4, "oil_forecast", f"The EIA expects Brent near ${eia:.0f} in Q4 2026 and $84 for 2027, well under spot.",
            ["k:oil-eia-steo-brent-forecast-oct2026", "c:brent"], "Forecasts revised up toward spot.", ["c:brent"])
        add("oil_eia_inf", "inflation_fed", 1, 0.35, 0.35, "oil_forecast", f"If Brent falls toward the EIA's ${eia:.0f} for Q4 and $84 for 2027, energy inflation reverses.",
            ["k:oil-eia-steo-brent-forecast-oct2026", "c:inflation"], "Oil holding above $110.", ["c:inflation"])
    spot = v("oil-eia-spot-brent-wti-20261014")
    if spot is not None:
        add("oil_spot_inf", "inflation_fed", -1, 0.6, 0.5, "oil_level", f"Brent at ${spot:.2f} (Oct 14) keeps headline inflation up; the Fed hiked 25bp on September 16.",
            ["k:oil-eia-spot-brent-wti-20261014", "c:oil-shock", "a:fed"], "Brent back under $90.", ["c:oil-shock", "c:policy-rate"])
        add("oil_spot_rec", "recession_economy", -1, 0.4, 0.45, "oil_level", f"Brent at ${spot:.2f} is an oil shock; most past shocks of this size came before a slowdown.",
            ["k:oil-eia-spot-brent-wti-20261014", "c:oil-shock"], "Oil back under $90.", ["c:oil-shock"])
    if K.get("oil-uae-exits-opec-2026"):
        add("uae", "oil_energy", -1, 0.25, 0.35, "oil_supply2", "The UAE left OPEC and OPEC+ on May 1: one big producer no longer bound by quotas (secondary report).",
            ["k:oil-uae-exits-opec-2026", "c:opec"], "OPEC+ cuts that hold.", ["c:opec"])
    mm = v("cot-wti-managed-money-20261013")
    if mm is not None:
        add("cot_wti", "oil_energy", 1, 0.1, 0.25, "positioning", f"Managed money is net long only {mm:,.0f} WTI contracts (CFTC, Oct 13): speculators are not crowded in oil.",
            ["k:cot-wti-managed-money-20261013", "c:cot"], "A jump in speculative length.", ["c:cot"])
    # gold
    cb = v("gold-wgc-fy2025-demand")
    if cb is not None:
        add("cbgold", "gold", 1, 0.5, 0.5, "gold_flow", f"Central banks bought {cb:.0f} tonnes of gold in 2025 and {v('gold-wgc-q2-2026-demand') or 0:.0f} in Q2 2026 (World Gold Council).",
            ["k:gold-wgc-fy2025-demand", "k:gold-wgc-q2-2026-demand", "c:central-bank-gold"], "Central banks turning sellers.", ["c:central-bank-gold"])
        add("cbgold2", "dollar_debt", -1, 0.3, 0.4, "gold_flow", "Central banks keep buying gold, a slow move away from dollar reserves.",
            ["k:gold-wgc-fy2025-demand", "c:dedollarization"], "Reserve buying of gold stopping.", ["c:central-bank-gold"])
    gp, gh = v("gold-wgc-sep2026-price"), v("gold-wgc-record-jan2026")
    if gp is not None and gh is not None:
        add("goldtrend", "gold", -1, 0.35, 0.35, "gold_trend", f"Gold was ${gp:,.0f} at end-September, {gp / gh - 1:.0%} from its ${gh:,.0f} record in January.",
            ["k:gold-wgc-sep2026-price", "k:gold-wgc-record-jan2026", "c:gold"], "A new high.", ["c:gold"])
    # AI, semis, concentration, speculation
    m7 = v("val-mag7-q3-2026-eps-growth")
    if m7 is not None:
        add("mag7", "ai_boom", 1, 0.6, 0.6, "ai_earn", f"Magnificent 7 earnings are growing {m7:.1f}% in Q3 against 27.7% for the other 493 (FactSet): the spend is showing up in profits.",
            ["k:val-mag7-q3-2026-eps-growth", "c:hyperscaler"], "Hyperscaler earnings growth below the rest of the index.", ["c:ai-revenue", "c:hyperscaler"])
        add("mag7b", "megacap_concentration", 1, 0.5, 0.55, "ai_earn", f"The biggest companies are out-earning the rest ({m7:.1f}% against 27.7%): their weight is earned, for now.",
            ["k:val-mag7-q3-2026-eps-growth", "c:concentration"], "Their earnings growth falling to the index's.", ["c:concentration"])
        add("mag7c", "semis_nvidia", 1, 0.45, 0.5, "ai_earn", f"Mag 7 earnings growth of {m7:.1f}% funds chip orders.",
            ["k:val-mag7-q3-2026-eps-growth", "c:gpu"], "Capex guidance cut.", ["c:gpu"])
        add("mag7d", "value_growth", 1, 0.35, 0.45, "ai_earn", f"The growth leaders are delivering growth: Mag 7 earnings +{m7:.1f}%.",
            ["k:val-mag7-q3-2026-eps-growth", "c:growth-investing"], "Growth leaders missing.", ["c:growth-investing"])
    ai = v("vc-us-ai-share-2026ytd-q3")
    if ai is not None:
        add("vcai", "ai_boom", -1, 0.4, 0.35, "ai_capital", f"AI took {ai:.1f}% of US venture dollars through Q3 2026 (PitchBook-NVCA): capital this concentrated in one theme has preceded busts before.",
            ["k:vc-us-ai-share-2026ytd-q3", "c:ai-funding", "c:dot-com"], "AI's share falling while revenue keeps rising.", ["c:ai-funding", "c:venture-capital"])
    dpi = v("vc-carta-dpi-2026q1")
    if dpi is not None:
        add("vcdpi", "ai_boom", -1, 0.2, 0.3, "ai_capital", f"Venture funds from 2017 have returned only {dpi:.2f}x their money in cash (median DPI, Carta): private marks are not yet cash.",
            ["k:vc-carta-dpi-2026q1", "c:dpi"], "Distributions picking up.", ["c:dpi"])
    crowd = v("am-bofa-fms-2026-07-crowded")
    if crowd is not None:
        add("semis_crowd", "semis_nvidia", -1, 0.35, 0.3, "sentiment", f"{crowd:.0f}% of fund managers named long semiconductors the most crowded trade in July (BofA; secondary report).",
            ["k:am-bofa-fms-2026-07-crowded", "c:crowding"], "The trade falling down the crowded list.", ["c:crowding"])
        add("semis_crowd2", "ai_boom", -1, 0.25, 0.3, "sentiment", "Long semiconductors is the most crowded trade in the BofA survey.",
            ["k:am-bofa-fms-2026-07-crowded", "c:crowding"], "Positioning unwinding without a fall in price.", ["c:crowding"])
    top10 = v("ts-sp500-top10-weight-2026-06")
    if top10 is not None:
        add("top10", "megacap_concentration", -1, 0.55, 0.5, "concentration", f"The ten largest stocks are {top10:.1f}% of the S&P 500 (June 30): an index fund is a concentrated bet.",
            ["k:ts-sp500-top10-weight-2026-06", "c:concentration"], "Concentration falling as the rest catches up.", ["c:concentration"])
        add("top10b", "diversification_indexing", -1, 0.3, 0.4, "concentration", f"With the top ten at {top10:.1f}% of the index, even indexers are concentrated; diversify beyond the cap-weighted index.",
            ["k:ts-sp500-top10-weight-2026-06", "c:diversification"], "Weights spreading out.", ["c:diversification"])
    md = v("ts-margin-debt-2026-09")
    if md is not None:
        add("margin", "speculation_manias", -1, 0.55, 0.45, "leverage", f"Margin debt is ${md / 1000:.2f} trillion (FINRA, September), near June's record, after a 15.9% jump in two months.",
            ["k:ts-margin-debt-2026-09", "k:ts-margin-debt-surge-2026-04-05", "c:margin", "c:leverage"], "Margin debt falling while prices hold.", ["c:margin", "c:leverage"])
        add("margin2", "market_valuation", -1, 0.3, 0.35, "leverage", f"Borrowed money in stocks is near a record (${md / 1000:.2f} trillion).",
            ["k:ts-margin-debt-2026-09", "c:leverage"], "Deleveraging without a crash.", ["c:leverage"])
        add("margin3", "risk_leverage_hedging", -1, 0.25, 0.4, "leverage", "Margin debt near a record means forced selling if prices drop.",
            ["k:ts-margin-debt-2026-09", "c:margin-call"], "Lower margin balances.", ["c:margin-call"])
    z = v("ts-spx-0dte-share-2026-07")
    if z is not None:
        add("zdte", "speculation_manias", -1, 0.3, 0.3, "derivs", f"Same-day (0DTE) options were a record {z:.1f}% of S&P 500 options volume in July (Cboe).",
            ["k:ts-spx-0dte-share-2026-07", "c:zero-dte"], "That share falling.", ["c:zero-dte"])
    rt = v("ts-us-retail-share-2025")
    if rt is not None:
        add("retail", "speculation_manias", -1, 0.15, 0.25, "retail", f"Retail investors were about {rt:.0f}% of US stock volume in 2025 (secondary report).",
            ["k:ts-us-retail-share-2025", "c:retail-trading"], "Retail share falling.", ["c:retail-trading"])
    ins = v("am-insider-selling-2026h1")
    if ins is not None:
        add("insider", "market_valuation", -1, 0.2, 0.25, "insider", f"Corporate insiders sold ${ins:.1f} billion of stock in the first half of 2026 (secondary report).",
            ["k:am-insider-selling-2026h1", "c:signaling"], "Insider buying picking up.", ["c:signaling"])
    cash = v("am-bofa-fms-2026-09-cash")
    if cash is not None:
        add("fmscash", "timing_crashes", -1, 0.25, 0.25, "sentiment", f"Fund managers held {cash:.1f}% cash in September (BofA; secondary report); low cash is the survey's own contrarian warning.",
            ["k:am-bofa-fms-2026-09-cash", "c:fund-manager-survey", "c:sentiment"], "Cash back above 4.5%.", ["c:fund-manager-survey"])
    br = v("ind-breadth-above-200d-2026-10-21")
    if br is not None:
        add("breadth", "market_valuation", 1 if br >= 50 else -1, 0.1, 0.25, "breadth", f"{br:.0f}% of S&P 500 members are above their 200-day average (secondary): participation is middling.",
            ["k:ind-breadth-above-200d-2026-10-21", "c:breadth", "c:pct-above-200"], "Breadth under 40%.", ["c:breadth"])
    # private markets
    lp = v("secondaries-lp-pricing-h1-2026")
    if lp is not None:
        add("lp", "private_credit", -1, 0.45, 0.55, "private_marks", f"Buyers of fund stakes paid on average {lp:.0f}% of NAV in H1 2026, venture 79% and real estate 68% (Jefferies): private marks are above what cash buyers pay.",
            ["k:secondaries-lp-pricing-h1-2026", "k:secondaries-pricing-by-strategy-h1-2026", "c:secondaries", "c:valuation-marks"], "Secondary prices at or above NAV.", ["c:secondaries", "c:nav"])
    dist = v("pe-distributions-nav-2025")
    if dist is not None:
        add("pedist", "private_credit", -1, 0.35, 0.5, "private_cash", f"Buyout distributions were {dist:.0f}% of NAV (Bain), well below the long-run pace: money is stuck in funds.",
            ["k:pe-distributions-nav-2025", "c:distribution", "c:dpi"], "Distributions back above 25% of NAV.", ["c:distribution"])
    cv = v("secondaries-cv-share-h1-2026-jefferies")
    if cv is not None:
        add("cvs", "private_credit", -1, 0.25, 0.4, "private_cash", f"Continuation vehicles are {cv:.0f}% of GP-led secondaries: managers selling assets to themselves.",
            ["k:secondaries-cv-share-h1-2026-jefferies", "c:continuation-vehicle"], "More exits to outside buyers.", ["c:continuation-vehicle"])
    nav = v("pe-nav-loans-market-2026")
    if nav is not None:
        add("navloan", "private_credit", -1, 0.25, 0.35, "private_lev", f"NAV loans are about ${nav:.0f} billion and growing: borrowing against fund portfolios, sometimes to pay distributions.",
            ["k:pe-nav-loans-market-2026", "c:nav-loan"], "NAV lending shrinking.", ["c:nav-loan"])
    ex = v("pe-us-exit-value-2026q2")
    if ex is not None:
        add("peexit", "private_credit", 1, 0.3, 0.4, "private_exit", f"US PE exits were ${ex:.1f} billion in Q2 2026 (PitchBook), with IPOs reopening: the exit window is open.",
            ["k:pe-us-exit-value-2026q2", "c:exits"], "IPO window shutting.", ["c:exits"])
    sv = v("secondaries-volume-h1-2026-jefferies")
    if sv is not None:
        add("secvol", "private_credit", 1, 0.2, 0.35, "private_exit", f"Secondary volume hit ${sv:.0f} billion in H1 2026 (Jefferies): a deep market to sell into exists.",
            ["k:secondaries-volume-h1-2026-jefferies", "c:secondaries"], "Volume drying up.", ["c:secondaries"])
    # active versus passive
    sr = v("am-morningstar-barometer-2026h1")
    if sr is not None:
        add("active", "edge:active", -1, 0.8, 0.7, "active", f"Only {sr:.0f}% of US active funds beat their passive peers over ten years (Morningstar, mid-2026).",
            ["k:am-morningstar-barometer-2026h1", "c:active-management"], "A success rate above 50%.", ["c:active-management", "c:skill-vs-luck"])
        add("active2", "diversification_indexing", -1, 0.5, 0.55, "active", f"{100 - sr:.0f}% of active funds trailed passive peers over ten years.",
            ["k:am-morningstar-barometer-2026h1", "c:passive-investing"], "Active success above 50%.", ["c:passive-investing"])
    fee = v("am-morningstar-fee-active-passive-2025")
    if fee is not None:
        add("fees", "edge:active", -1, 0.4, 0.85, "fees", f"Active funds charge {fee:.2f}% on average against 0.10% for passive (Morningstar 2025): a certain drag.",
            ["k:am-morningstar-fee-active-passive-2025", "c:fees"], "Fees converging.", ["c:fees"])
    for pid, axis, sign, s, rel, txt in (
            ("am-paper-sharpe-1991", "edge:active", -1, 0.5, 0.9, "Sharpe (1991): before costs, active investors as a group earn the market return, so after costs they must trail it."),
            ("am-paper-fama-french-2010", "edge:active", -1, 0.4, 0.6, "Fama and French (2010): few fund managers show skill beyond what luck would produce."),
            ("am-paper-carhart-1997", "edge:active", -1, 0.3, 0.6, "Carhart (1997): fund performance persistence is mostly momentum and fees."),
            ("am-paper-berk-green-2004", "edge:active", 1, 0.2, 0.4, "Berk and Green (2004): skilled managers exist, but money chases them until their edge is spent."),
            ("ind-paper-hurst-ooi-pedersen-2017", "edge:trend", 1, 0.5, 0.5, "Hurst, Ooi and Pedersen (2017): trend following made money across markets since 1880, notably in crises."),
            ("ind-paper-moskowitz-ooi-pedersen-2012", "edge:trend", 1, 0.4, 0.5, "Moskowitz, Ooi and Pedersen (2012): an asset's past year return predicts its next month across 58 futures."),
            ("ind-paper-sullivan-timmermann-white-1999", "edge:trend", -1, 0.45, 0.6, "Sullivan, Timmermann and White (1999): after correcting for the thousands of rules tried, the best rule's edge disappears out of sample."),
            ("ind-paper-faber-2007", "edge:trend", 1, 0.3, 0.4, "Faber (2007): the 10-month rule kept equity-like returns with bond-like volatility in his sample."),
            ("ind-paper-park-irwin-2007", "edge:oscillators", 1, 0.25, 0.3, "Park and Irwin (2007): 56 of 95 modern studies found technical trading profits, with worries about snooping."),
            ("ind-paper-lo-mamaysky-wang-2000", "edge:oscillators", 1, 0.2, 0.4, "Lo, Mamaysky and Wang (2000): some chart patterns carry a little information."),
            ("val-paper-goyal-welch-2008", "edge:valuation_timing", -1, 0.5, 0.6, "Goyal and Welch (2008): popular predictors, valuation included, fail out of sample."),
            ("val-paper-campbell-thompson-2008", "edge:valuation_timing", 1, 0.3, 0.5, "Campbell and Thompson (2008): with sensible limits, valuation predicts a little out of sample, enough to matter."),
            ("val-paper-campbell-shiller-1998", "market_valuation", -1, 0.3, 0.5, "Campbell and Shiller (1998): high P/E and low dividend yields have been followed by poor long-run returns."),
            ("stats-harvey-liu-zhu-2016", "edge:oscillators", -1, 0.35, 0.7, "Harvey, Liu and Zhu (2016): with hundreds of factors tried, a new finding needs a t-statistic above 3."),
            ("negot-galinsky-mussweiler-2001", "edge:first_offer", 1, 0.6, 0.6, "Galinsky and Mussweiler (2001): whoever made the first offer, buyer or seller, got the better deal; the anchor pulls the final price toward it."),
            ("negot-tversky-kahneman-1974", "edge:first_offer", 1, 0.3, 0.7, "Tversky and Kahneman (1974): people adjust too little from a starting number, which is why anchors work."),
            ("negot-ayres-siegelman-1995", "edge:first_offer", 1, 0.2, 0.5, "Ayres and Siegelman (1995): car dealers opened higher with some buyers than others; whoever lets the seller anchor pays for it."),
            ("negot-castillo-taxi-2013", "edge:first_offer", 1, 0.15, 0.5, "Castillo and coauthors (2013): Lima taxi drivers opened higher to passengers they judged would pay more."),
            ("negot-keim-madhavan-1996", "edge:first_offer", -1, 0.2, 0.5, "Keim and Madhavan (1996): prices move against a block before it prints; revealing your hand early can cost you."),
            ("negot-raiffa-1982", "edge:first_offer", -1, 0.15, 0.4, "Raiffa (1982): when you know little about the other side's walk-away price, an extreme opening can end the talks."),
            ("games-fractional-kelly-overbetting", "edge:sizing", -1, 0.6, 0.85, "Betting twice the Kelly fraction gives zero long-run growth; half Kelly keeps 75% of the growth with far less risk (Thorp)."),
            ("games-thorp-partnership-kelly", "edge:sizing", 1, 0.4, 0.5, "Thorp's partnership compounded about 20% a year with Kelly-style sizing, but only on measured edges."),
            ("games-kelly-1956", "edge:sizing", 1, 0.3, 0.8, "Kelly (1956): with a real edge, betting a fixed fraction maximizes long-run growth."),
            ("ts-paper-barber-odean-2000", "speculation_manias", -1, 0.25, 0.6, "Barber and Odean (2000): the most active retail traders earned the least."),
            ("ts-paper-shleifer-vishny-1997", "speculation_manias", 1, 0.2, 0.5, "Shleifer and Vishny (1997): mispricing can run far because arbitrage needs capital that leaves when it hurts."),
            ("paper-gorton-rouwenhorst-2006", "oil_energy", 1, 0.15, 0.4, "Gorton and Rouwenhorst (2006): commodity futures earned an equity-like premium and rose with unexpected inflation."),
            ("paper-kilian-2009", "oil_energy", -1, 0.2, 0.5, "Kilian (2009): supply-driven oil spikes fade faster than demand-driven ones."),
            ("paper-kaplan-schoar-2005", "private_credit", -1, 0.2, 0.5, "Kaplan and Schoar (2005): average private equity returns net of fees were roughly the S&P 500's."),
            ("paper-hjk-2014", "private_credit", 1, 0.2, 0.5, "Harris, Jenkinson and Kaplan (2014): buyout funds beat public markets in most vintages."),
    ):
        if pid in K:
            add("p-" + pid, axis, sign, s, rel, "paper:" + axis, txt, ["k:" + pid], "New evidence on a longer sample.", [])
    if K.get("games-fractional-kelly-overbetting"):
        add("kelly_risk", "risk_leverage_hedging", -1, 0.4, 0.8, "math", "Ruin is permanent: past twice the Kelly fraction, expected growth turns negative however good the edge.",
            ["k:games-fractional-kelly-overbetting", "c:kelly", "c:risk-of-ruin", "e:games2"], "None: this is arithmetic.", ["c:kelly", "c:risk-of-ruin"])
    return S


def v16_signals(K: dict, rlo: dict | None, tech: dict | None) -> list[dict]:
    """v0.16: the reinforcement-learning agent's record, each series' evidence-weighted technical composite, and the
    distribution metrics the companies disclose."""
    S = []

    def add(sid, axis, sign, s, rel, group, text, refs, flip, targets=()):
        refs = [r for r in refs if not r.startswith("k:") or r[2:] in K]
        S.append({"id": "s:" + sid, "axis": axis, "sign": sign, "s": s, "rel": rel, "group": group, "text": text, "refs": refs, "flip": flip, "targets": list(targets)})
    if rlo:
        b = rlo["configs"][rlo["best"]]
        add("rl-agent", "edge:ml", 1 if b["sharpe_vs_hold"]["est"] > 0 and rlo["deflated_excess"]["dsr"] > 0.5 else -1, 0.5, 0.7, "rl",
            f"A reinforcement-learning sizing agent retrained yearly since {rlo['start'][:4]} reached a Sharpe of {b['perf']['sharpe']:.2f} against {rlo['hold']['sharpe']:.2f} for holding and {rlo['trend']['sharpe']:.2f} for the trend rule.",
            ["e:rl", "c:reinforcement-learning"], "The agent beating the trend rule out of sample.", ["c:reinforcement-learning"])
        add("rl-trend", "edge:trend", 1 if rlo["trend"]["sharpe"] > rlo["hold"]["sharpe"] else -1, 0.3, 0.6, "rl",
            f"On the same months the simple 10-month rule beat both holding and the learning agent on Sharpe ({rlo['trend']['sharpe']:.2f}).", ["e:rl", "c:ma10m"], "Holding beating the rule.", [])
    for key, axis, nm in (("brent", "oil_energy", "Brent"), ("gas", "oil_energy", "Henry Hub gas")):
        a = (tech or {}).get(key)
        if a and abs(a["composite"]) > 1e-9:
            add(f"ta-{key}", axis, 1 if a["composite"] > 0 else -1, round(min(0.4, abs(a["composite"])), 6), 0.25, "technicals",
                f"{nm}'s technical signals, each weighted by how it worked on {nm}'s own history, net to {a['composite']:+.2f} on a -1 to +1 scale.",
                ["e:technicals", "c:technical-analysis"], "The weighted signals turning.", ["c:technical-analysis"])
    dist = [k for k in K.values() if k.get("cluster") == "distribution" and k.get("kind") == "stat" and k.get("ticker") in ("MSFT", "GOOGL", "META")]
    if dist:
        pick = {"dm-msft-m365-copilot-seats", "dm-googl-gemini-app-mau", "dm-meta-family-dap"}
        chosen = [k for k in dist if k["id"] in pick] or dist[:3]
        add("dist-ai", "ai_boom", 1, 0.4, 0.5, "distribution", "Distribution is reaching AI users at scale: " + "; ".join(k["title"] for k in chosen[:3]) + ".",
            ["k:" + k["id"] for k in chosen[:3]] + ["c:distribution-moat"], "User growth stalling or paid conversion falling.", ["c:distribution-moat"])
    return S


ETF_LINKS = ["c:duration", "c:convexity", "c:yield-curve", "c:bond-etf", "c:yield-to-maturity", "c:tlt"]
DESKS = [   # where on the site: the mind routes a question to the desk that answers it
    ("portfolio", "Portfolio engine", "Stocks, 10-year Treasuries, gold and cash decided together: regimes with their stock-bond correlation, eight policies since 1940, a learner over them, ten simulated years and eight replayed drawdowns.",
     ["c:strategic-asset-allocation", "c:tactical-asset-allocation", "c:risk-parity", "c:sixty-forty", "c:stock-bond-correlation", "c:monte-carlo", "c:gold"]),
    ("decision", "Decision engine", "Stocks, Treasuries and gold decided together from regimes, a learner over whole policies, ten years simulated, and one pipeline from 156 years of data to today's sized exposure and hedge: stacked forecasts with a neural-network ensemble, hidden Markov regimes, changepoints, model averaging, a risk budget and an evidence gate, walked forward from 1940.",
     ["c:hidden-markov-model", "c:bayesian-model-averaging", "c:neural-network", "c:crra-utility", "c:expected-shortfall", "c:reinforcement-learning", "c:kalman", "c:stacking"]),
    ("bonds", "Bonds, simply", "Set the 10-year and 30-year yields and see every Treasury ETF repriced bond by bond: price, 12-month return, break-even and what it means for stocks.", ["c:duration", "c:convexity", "c:tlt", "c:bond-etf", "c:yield-curve"]),
    ("rates", "Rates and curves", "The Treasury curve through 2026, spreads, the forward curve and liquidity.", ["c:yield-curve", "c:term-premium", "c:bear-steepening"]),
    ("ml", "The machine-learning lab", "Purged walk-forward forecasts, the combination forecast, CPCV and the overfitting probability, and why complex models backtest better than they forecast.", ["c:machine-learning", "c:overfitting", "c:data-snooping"]),
    ("mind", "The mind", "Ask anything: recall, spreading activation, weighing and the belief network.", []),
    ("labs", "The labs", "The trend lab, valuation lab and the long-history tests on 155 years.", ["c:cape", "c:ma10m"]),
    ("analysis", "Technicals and fundamentals", "Every chart signal judged on its own asset, every ratio read from the filing.", ["c:technical-analysis"]),
    ("hedges", "The hedge lab", "Scenario losses for the model book with and without each hedge.", ["c:tlt", "c:hedging"]),
]
EPISODE_TERMS = {"crash-1929": ["1929", "great-depression"], "dotcom": ["dot-com", "dotcom", "2000-bubble"], "gfc": ["2008", "financial-crisis", "lehman", "subprime"],
                 "volcker": ["volcker"], "great-inflation": ["great-inflation", "stagflation"], "bear-1973": ["1973", "nifty"], "crash-1987": ["1987", "portfolio-insurance"],
                 "ltcm-1998": ["ltcm", "1998"], "taper-2013": ["taper"], "covid": ["covid", "2020"], "inflation-2022": ["2022"], "ai-buildout": ["ai-capex", "hyperscaler", "ai-bubble"],
                 "panic-1907": ["1907"], "bond-1994": ["1994"], "euro-2011": ["euro-crisis", "2011"], "ww2": ["world-war"], "roaring-twenties": ["roaring", "1920s"],
                 "bull-1982": ["1982"], "panic-1873": ["1873"], "panic-1893": ["1893"]}


@cache.memo("mind.similar_concepts")
def similar_concepts(concepts: list[dict], k: int = 4, floor: float = 0.22) -> list[tuple[str, str, float]]:
    """v0.17: each concept linked to the few whose definitions read most alike (TF-IDF cosine on name, aliases and
    definition), so thinking about one idea also recalls its neighbours even where no writer typed the relation."""
    try:
        import numpy as np
        from sklearn.feature_extraction.text import TfidfVectorizer
    except ImportError:
        return []
    docs = [f"{c['name']} {c['name']} {' '.join(c['aliases'])} {c['text']}" for c in concepts]
    X = TfidfVectorizer(sublinear_tf=True, stop_words="english", min_df=2, ngram_range=(1, 2), max_features=60000).fit_transform(docs)
    out = []
    for s0 in range(0, X.shape[0], 1000):
        S = (X[s0:s0 + 1000] @ X.T).toarray()
        for r in range(S.shape[0]):
            i = s0 + r
            S[r, i] = 0.0
            top = np.argsort(-S[r], kind="stable")[:k]
            for j in top:
                if S[r, j] >= floor:
                    out.append((concepts[i]["id"], concepts[int(j)]["id"], round(0.2 + 0.4 * float(S[r, j]), 4)))
    return out


def v17_nodes(node, edge, nodes, idx, chron, bonds, cx) -> None:
    """v0.17: the chronicle (every month since 1871, years, episodes, analogs), the Treasury ETFs with their measured
    facts and repricing, the complexity study's findings, and the site's desks as routing nodes."""
    concept_ids = [n["id"] for n in nodes if n["k"] == "concept"]
    if chron:
        for n in chron["nodes"]:
            extra = {k: n[k] for k in ("ret_next", "start", "end", "dd", "yr", "mo") if n.get(k) is not None}
            node(n["id"], n["k"], n["n"], n["g"], n["t"], n["a"], **extra)
        for a, b, typ, w in chron["edges"]:
            edge(a, b, typ, w)
        for eid, terms in EPISODE_TERMS.items():
            for cid in concept_ids:
                if any(t in cid for t in terms):
                    edge("h:" + eid, cid, "related", 0.6)
        edge("m:now", "c:cape", "related", 0.5)
        edge("m:now", "x:history", "related", 0.5)
        for eid in EPISODE_TERMS:
            edge("h:" + eid, "x:history", "part_of", 0.4)
    if bonds:
        for t, f in bonds["funds"].items():
            c = bonds["cases"]
            fa = bonds.get("facts", {}).get(t, {})
            txt = (f"{f['name']}: a {f['lo']:g} to {f['hi']:g}-year Treasury ladder" + (" of zero-coupon STRIPS" if f["zero"] else "") +
                   (f", reported duration {fa['duration']:.2f} years ({fa.get('duration_as_of')})" if fa.get("duration") else f", modelled duration {f['duration']:.1f} years") +
                   (f", yield to maturity {fa['ytm']:.2%}" if fa.get("ytm") else "") + (f", price ${fa['price']:.2f} ({fa.get('as_of')})" if fa.get("price") else "") +
                   f". If the 10-year and 30-year both go to 4%, it moves {c['both_4']['funds'][t]['change']:+.1%}; both to 6%, {c['both_6']['funds'][t]['change']:+.1%}; "
                   f"yields can rise {bonds['breakeven'][t] * 1e4:.0f}bp in a year before its income is gone.")
            node("etf:" + t.lower(), "etf", t, "rates", txt, [t.lower(), f["name"].lower()], duration=round(f["duration"], 3))
            for cid in ETF_LINKS:
                edge("etf:" + t.lower(), cid, "related", 0.7)
            edge("etf:" + t.lower(), "e:bondlab", "implemented_by", 0.7)
        edge("etf:tlt", "a:tlt", "measures", 0.9)
        for a, b in (("shy", "iei"), ("iei", "ief"), ("ief", "tlh"), ("tlh", "tlt"), ("tlt", "edv"), ("edv", "zroz")):
            edge("etf:" + a, "etf:" + b, "related", 0.5)
    if cx:
        for i, c in enumerate(cx["conclusions"]):
            node(f"cx:{i}", "finding", c["title"], "ml", c["text"], [])
            edge(f"cx:{i}", "e:complexity", "implemented_by", 0.7)
            for cid in ("c:overfitting", "c:machine-learning", "c:data-snooping", "c:effective-sample-size", "c:stambaugh-bias", "c:extrapolation", "c:curse-of-dimensionality"):
                edge(f"cx:{i}", cid, "related", 0.6)
    for d, title, text, links in DESKS:
        node("d:" + d, "desk", title, "core", f"On the site: {title}. {text}", [title.lower(), d + " desk"], desk=d)
        for cid in links:
            edge("d:" + d, cid, "routes", 0.6)
    if bonds:
        for t in bonds["funds"]:
            edge("d:bonds", "etf:" + t.lower(), "routes", 0.6)
    if cx:
        for i in range(len(cx["conclusions"])):
            edge("d:ml", f"cx:{i}", "routes", 0.6)


DX_CONCEPTS = ("c:hidden-markov-model", "c:markov-switching", "c:regime", "c:bayesian-model-averaging", "c:neural-network", "c:deep-learning", "c:dropout", "c:ensemble",
               "c:stacking", "c:crra-utility", "c:risk-aversion", "c:expected-shortfall", "c:mean-cvar-optimization", "c:kalman", "c:thompson-sampling", "c:contextual-bandit",
               "c:reinforcement-learning", "c:offline-reinforcement-learning", "c:conformal", "c:robust-decision", "c:decision-quality")


def v19_nodes(node, edge, dec) -> None:
    """v0.19: the decision engine's stages, today's decision and its findings."""
    if not dec:
        return
    n = dec["now"]
    node("x:decision", "model", "Today's decision (model book)", "core",
         f"Model-book exposure {n['exposure']:.2f}x stocks; the engine's own optimum {n['engine_exposure']:.2f}x, scaled by an evidence gate of {n['gate']['value']:.0%} "
         f"(its departures from 1x improved utility with t {n['gate']['t']:.1f} since {dec['start'][:4]}). Hedge: {n['hedge']['name'].lower()} in a {n['hedge']['context']}. "
         f"Stressed regime next month {n['regime']['next'][n['regime']['worst']]:.0%}; changepoint odds {n['changepoint']['recent']:.0%}. Research only; never an order.",
         ["decision engine", "today's decision", "what should the book do", "exposure", "model book exposure"], exposure=n["exposure"])
    edge("x:decision", "e:decide", "implemented_by", 0.9)
    edge("d:decision", "x:decision", "routes", 0.8)
    for i, st in enumerate(dec["pipeline"]):
        node(f"dx:stage:{i}", "method", f"Decision engine, {st['stage'].lower()}", "core", st["what"], [st["stage"].lower() + " stage"])
        edge(f"dx:stage:{i}", "x:decision", "part_of", 0.7)
        if i:
            edge(f"dx:stage:{i - 1}", f"dx:stage:{i}", "routes", 0.6)
    for k, mod in (("dx:stage:2", "e:nn"), ("dx:stage:3", "e:infer"), ("dx:stage:4", "e:decide"), ("dx:stage:1", "e:ml")):
        edge(k, mod, "implemented_by", 0.7)
    for i, f in enumerate(dec["findings"]):
        node(f"dx:{i}", "finding", f[:80], "core", f, [])
        edge(f"dx:{i}", "x:decision", "related", 0.7)
    for cid in DX_CONCEPTS:
        edge("x:decision", cid, "related", 0.5)


def v20_nodes(node, edge, pf) -> None:
    """v0.20: the portfolio engine's regimes, policies, simulation and today's mix."""
    if not pf:
        return
    n = pf["now"]
    mix = lambda a: ", ".join(f"{v:.0%} {k}" for k, v in zip(("stocks", "Treasuries", "gold"), a) if v > 1e-9) or "all cash"
    node("x:portfolio", "model", "Today's portfolio decision (model book)", "core",
         f"Stocks, 10-year Treasuries, gold and cash decided together: {mix(n['decision'])}. The regime optimum is {mix(n['optimum'])}; the gate moves {n['gate']:.0%} of the way "
         f"toward the best-evidenced policy ({n['gate_policy'].replace('_', ' ')}). Research only; never an order.",
         ["portfolio decision", "asset allocation", "allocation", "stocks bonds gold", "what mix"])
    edge("x:portfolio", "e:portfolio", "implemented_by", 0.9)
    edge("x:portfolio", "x:decision", "related", 0.8)
    edge("d:decision", "x:portfolio", "routes", 0.8)
    for k, st in enumerate(n["states"]):
        node(f"pf:state:{k}", "model", f"Regime: {st['name'].lower()}", "core",
             f"A state of stocks, Treasuries and gold together (hidden Markov model, 1871 to {pf['end']}): stocks {st['mu'][0]:+.1%} a year real with {st['vol'][0]:.0%} volatility, "
             f"Treasuries {st['mu'][1]:+.1%}, gold {st['mu'][2]:+.1%}; stock-bond correlation {st['corr_sb']:+.2f}; it lasts about {st['persistence_months']:.0f} months. "
             f"Odds for next month: {n['next'][k]:.0%}.", [st["name"].lower() + " regime"])
        edge(f"pf:state:{k}", "x:portfolio", "part_of", 0.7)
        edge(f"pf:state:{k}", "c:hidden-markov-model", "is_a", 0.6)
        edge(f"pf:state:{k}", "c:stock-bond-correlation", "related", 0.6)
    for i, f in enumerate(pf["findings"]):
        node(f"pf:{i}", "finding", f[:80], "core", f, [])
        edge(f"pf:{i}", "x:portfolio", "related", 0.7)
    for cid in ("c:strategic-asset-allocation", "c:tactical-asset-allocation", "c:risk-parity", "c:sixty-forty", "c:gold", "c:stock-bond-correlation", "c:monte-carlo",
                "c:minimax-regret", "c:diversification", "c:model-stress-test"):
        edge("x:portfolio", cid, "related", 0.5)


def v20_signals(K: dict, pf: dict | None) -> list[dict]:
    if not pf:
        return []
    n, P = pf["now"], pf["perf"]
    cur = max(range(len(n["next"])), key=lambda i: n["next"][i])
    st = n["states"][cur]
    S = [{"id": "s:pf-corr", "axis": "bonds_rates", "sign": 1 if st["corr_sb"] < 0 else -1, "s": round(min(0.4, abs(st["corr_sb"])), 6), "rel": 0.6, "group": "portfolio",
          "text": f"The portfolio engine's regime model puts next month in its {st['name'].lower()} state ({n['next'][cur]:.0%}), where stocks and 10-year Treasuries have moved with a "
                  f"correlation of {st['corr_sb']:+.2f}: " + ("bonds have hedged stocks there." if st["corr_sb"] < 0 else "bonds have not hedged stocks there."),
          "refs": ["e:portfolio", "x:portfolio"], "flip": "A shift into a state where the stock-bond correlation is negative.", "targets": ["c:stock-bond-correlation"]},
         {"id": "s:pf-learner", "axis": "edge:ml", "sign": 1 if P["regime"]["sharpe"] > P["hold"]["sharpe"] else -1, "s": 0.5, "rel": 0.8, "group": "portfolio",
          "text": f"Timing stocks, Treasuries and gold by regime, walked forward since {pf['start'][:4]}, earned a Sharpe of {P['regime']['sharpe']:.2f} against {P['hold']['sharpe']:.2f} for holding "
                  f"stocks and {P['sixty_forty']['sharpe']:.2f} for 60/40; a learner that weights six whole policies by their record reached {P['meta']['sharpe']:.2f} with a worst drawdown of "
                  f"{P['meta']['maxdd']:.0%} against {P['hold']['maxdd']:.0%}. Diversifying across policies did better than predicting regimes.",
          "refs": ["e:portfolio", "x:portfolio"], "flip": "Regime timing beating 60/40 out of sample.", "targets": ["c:tactical-asset-allocation"]}]
    return S


def v19_signals(K: dict, dec: dict | None) -> list[dict]:
    """v0.19: the decision engine's regime read, its forecasts and its own record."""
    if not dec:
        return []
    n = dec["now"]
    S = []
    w = n["regime"]["next"][n["regime"]["worst"]]
    S.append({"id": "s:dx-regime", "axis": "market_valuation", "sign": 1 if w < 0.3 else -1, "s": round(0.3 * abs(0.3 - w) / 0.3, 6), "rel": 0.4, "group": "decision",
              "text": f"The hidden Markov model ({n['regime']['K']} states, filtered) puts next month's odds of the stressed regime at {w:.0%}; the chance a new regime began in the last six months is {n['changepoint']['recent']:.0%}.",
              "refs": ["e:infer", "x:decision"], "flip": "The stressed regime's odds rising past " + (f"{n['flip']['cut_if_stress_prob_above']:.0%}." if n["flip"].get("cut_if_stress_prob_above") is not None else "half."),
              "targets": ["c:hidden-markov-model"]})
    fs = dec["forecast_scores"]["nn"]
    S.append({"id": "s:dx-nn", "axis": "edge:ml", "sign": 1 if fs["skill"] > 0 else -1, "s": 0.4, "rel": 0.7, "group": "decision",
              "text": f"A deep ensemble of small neural networks, walked forward since {dec['start'][:4]}, forecasts 12-month returns with skill {fs['skill']:+.1%} against the historical mean (Diebold-Mariano t {fs['dm']['t']:.1f}); the stack gives it {n['forecasts']['weights']['nn']:.0%} of the weight.",
              "refs": ["e:nn", "e:decide"], "flip": "The ensemble beating the mean out of sample.", "targets": ["c:neural-network"]})
    g = n["gate"]
    S.append({"id": "s:dx-gate", "axis": "edge:ml", "sign": 1 if g["value"] > 0 else -1, "s": 0.5, "rel": 0.8, "group": "decision",
              "text": f"The decision engine's departures from holding improved a risk-averse investor's utility with t {g['t']:.1f} since {dec['start'][:4]}, under the {g['t0']:.1f} expected from the best of {g['n_tried']} useless strategies, so it moves the book {g['value']:.0%} of the way toward its {n['engine_exposure']:.2f}x optimum.",
              "refs": ["e:decide", "x:decision"], "flip": "The engine's utility gain clearing the bar.", "targets": ["c:robust-decision"]})
    return S


def v17_signals(K: dict, bonds: dict | None, cx: dict | None) -> list[dict]:
    """v0.17: what the bond repricing, the stock read-through, today's tape and the complexity study say."""
    S = []

    def add(sid, axis, sign, s, rel, group, text, refs, flip, targets=()):
        refs = [r for r in refs if not r.startswith("k:") or r[2:] in K]
        S.append({"id": "s:" + sid, "axis": axis, "sign": sign, "s": s, "rel": rel, "group": group, "text": text, "refs": refs, "flip": flip, "targets": list(targets)})
    if bonds:
        c, be = bonds["cases"], bonds["breakeven"]["TLT"]
        dn, up = c["down_100"]["funds"]["TLT"]["change"], c["up_100"]["funds"]["TLT"]["change"]
        add("bonds-convexity", "bonds_rates", 1, 0.3, 0.6, "bonds",
            f"Repriced bond by bond, TLT gains {dn:+.1%} if yields fall 1 point and loses {up:+.1%} if they rise 1 point, and its income covers a {be * 1e4:.0f}bp rise in a year: at these yields the long bond's payoff is skewed toward the holder.",
            ["e:bondlab", "c:convexity", "etf:tlt"], "Yields rising more than the break-even in a year.", ["c:convexity"])
        eq = bonds.get("equity") or {}
        now = eq.get("now")
        if now and now["regime"] in eq:
            r = eq[now["regime"]]
            band = {"low_inflation": "below 2.75%", "middle_inflation": "between 2.75% and 4.25%", "high_inflation": "above 4.25%"}[now["regime"]]
            add("bonds-regime", "bonds_rates", 1 if r["per_point"] > 0 else -1, round(min(0.4, 0.1 * abs(r["t"])), 6), 0.5, "bonds",
                f"With inflation {band} (now {now['infl36']:.1%} a year over three years), the S&P 500 has moved {r['per_point']:+.1%} per point of rise in the 10-year since 1871 (t {r['t']:.1f}): "
                + ("stocks and bonds have tended to fall together, so long bonds hedge less." if r["per_point"] < 0 else "yields have risen with stocks, so long bonds have hedged."),
                ["e:bondlab", "c:stock-bond-correlation"], "Inflation crossing into another band.", ["c:stock-bond-correlation"])
        tl, qq = K.get("tp-tlt-1022"), K.get("tp-qqq-1022")
        if tl and qq and tl.get("value") is not None and qq.get("value") is not None:
            add("bonds-tape", "bonds_rates", 1 if tl["value"] > 0 > qq["value"] else -1, 0.2, 0.4, "bonds",
                f"On Oct 22, 2026, TLT was {tl['value']:+.2f}% while QQQ was {qq['value']:+.2f}% as AI stocks sold off on earnings and debt worries: the hedge worked on the day.",
                ["k:tp-tlt-1022", "k:tp-qqq-1022", "etf:tlt"], "Stocks and long bonds falling on the same day.", [])
    if cx:
        sw = cx["sweep"]
        worst = min(r["out_of_sample"] for rows in sw.values() for r in rows[-1:])
        add("cx-complexity", "edge:ml", -1, 0.5, 0.8, "complexity",
            f"On 155 years of data, every model family fits the training years better as it grows more complex and forecasts the years after worse, down to {'below -100%' if worst < -1 else format(worst, '+.0%')} out of sample; about {cx['information']['n_eff']:.0f} independent 12-month observations cannot pay for flexible models.",
            ["e:complexity", "c:overfitting"], "A flexible model beating the historical mean out of sample.", ["c:overfitting"])
        st = cx["stambaugh"]
        add("cx-stambaugh", "market_valuation", -1, 0.25, 0.5, "complexity",
            f"Corrected for Stambaugh's small-sample bias, the CAPE slope shrinks from {st['slope']:+.3f} to {st['slope_corrected']:+.3f} a year per log point, and its p-value rises from {st['p_naive']:.2f} to {st['p_bias_aware']:.2f}: valuation still points down, more weakly.",
            ["e:complexity", "c:stambaugh-bias", "c:cape"], "The bias-corrected slope losing its sign.", ["c:cape"])
    return S


def decision_compact(dec: dict, pf: dict | None) -> dict:
    """What the mind needs to answer decision questions and recompute them: the engine's mixture, weights, grid and gate
    (the shape of decision.json's "now", which the page's dxlive.js reads too) and the portfolio engine's call."""
    n = dec["now"]
    keep = ("mixture", "tilt", "gamma", "es_limit", "grid", "borrow", "gh", "exposure", "engine_exposure", "capped")
    out = {k: n[k] for k in keep if k in n}
    out["models"] = {"weights": n["models"]["weights"]}
    out["regime"] = {k: n["regime"][k] for k in ("K", "worst", "next", "now")}
    out["forecasts"] = {"now": {"mean": n["forecasts"]["now"]["mean"]}, "stacked": n["forecasts"]["stacked"]}
    out["gate"] = {k: n["gate"][k] for k in ("value", "t", "n_tried")}
    out["hedge"] = {"name": n["hedge"]["name"], "context": n["hedge"]["context"]}
    out["changepoint"] = {"recent": n["changepoint"]["recent"]}
    if pf:
        p = pf["now"]
        out["portfolio"] = {"decision": p["decision"], "optimum": p["optimum"], "gate": p["gate"], "gate_policy": p["gate_policy"], "next": p["next"],
                            "states": [{"name": s["name"], "corr_sb": s["corr_sb"]} for s in p["states"]], "meta_mix": p["meta_mix"]}
    return out


def bonds_compact(b: dict) -> dict:
    keep = ("name", "lo", "hi", "a", "b", "zero", "coupon", "duration", "convexity", "ytm", "price", "price_as_of", "reported_duration", "wam", "ytm_reported")
    return {"curve": b["curve"], "funds": {t: {k: f[k] for k in keep if f.get(k) is not None} for t, f in b["funds"].items()}, "equity": b.get("equity")}


def more_signals(K: dict, mlo: dict | None, aso: dict | None, positions: dict | None) -> list[dict]:
    """v0.15: evidence from the machine-learning engine, the reality check (assumptions), each holding's reverse DCF and
    the model-risk and machine-learning literature."""
    S = []

    def v(kid):
        it = K.get(kid)
        return None if it is None else it.get("value")

    def add(sid, axis, sign, s, rel, group, text, refs, flip, targets=()):
        refs = [r for r in refs if not r.startswith("k:") or r[2:] in K]
        S.append({"id": "s:" + sid, "axis": axis, "sign": sign, "s": s, "rel": rel, "group": group, "text": text, "refs": refs, "flip": flip, "targets": list(targets)})
    if mlo:
        r, c = mlo["return"], mlo["crash"]
        sk, pbo = r["scores"]["ensemble"]["skill"], r["cpcv"]["pbo"]
        ens, mean = math.expm1(r["now"]["ensemble"]), math.expm1(r["now"]["benchmark"])
        rel_r = max(0.03, min(0.5, sk * 5))                       # reliability follows out-of-sample skill; negative skill earns almost none
        add("ml-forecast", "market_valuation", 1 if ens > mean else -1, 0.5, rel_r, "ml", f"The machine-learning ensemble expects {ens:+.1%} real over the next year against a historical {mean:+.1%}; its out-of-sample skill is {sk:+.1%}, so it counts for little.",
            ["e:ml", "m:ml-walkforward", "c:machine-learning"], "Out-of-sample skill turning positive.", ["c:machine-learning"])
        cp, cb = c["now"]["ensemble"], c["now"]["benchmark"]
        csk = c["scores"]["ensemble"]["skill"]
        add("ml-crash", "timing_crashes", 1 if cp < cb else -1, 0.4, max(0.03, min(0.5, csk * 5)), "ml", f"Models put a 15% fall within a year at {cp:.0%} against a base rate of {cb:.0%}; their Brier skill out of sample is {csk:+.1%}.",
            ["e:ml", "c:brier-score"], "Skill turning positive with the probability still above base.", ["c:crash"])
        bestk = max((k for k in r["scores"] if k not in ("ensemble", "dmspe")), key=lambda k: r["scores"][k]["skill"])
        add("ml-skill", "edge:ml", 1 if sk > 0 else -1, 0.8, 0.75, "ml_test", f"Purged walk-forward since {mlo['start_oos']}: the ensemble's skill at forecasting 12-month returns is {sk:+.1%} against the historical mean; the best single model, {r['labels'][bestk].lower()}, is {r['scores'][bestk]['skill']:+.1%}.",
            ["e:ml", "m:ml-walkforward", "c:purged-cv"], "Positive skill on the next decade of data.", ["c:machine-learning", "c:walk-forward"])
        if "combo" in r["scores"]:
            cs = r["scores"]["combo"]
            add("ml-combo", "edge:ml", 1 if cs["skill"] > 0 else -1, 0.5, 0.6, "ml_combo", f"The one model that beats the mean: averaging eight one-variable forecasts with Campbell and Thompson's sign restrictions earns {cs['skill']:+.1%} skill (Diebold-Mariano t {cs['dm']['t']:.1f}), small and not yet significant, as Rapach, Strauss and Zhou found.",
                ["e:ml", "m:ml-walkforward", "c:forecast-combination"], "The combination's skill turning negative.", ["c:forecast-combination"])
        add("ml-pbo", "edge:ml", -1 if pbo > 0.5 else 1, 0.6, 0.7, "ml_test", f"Across {r['cpcv']['splits']} combinatorial purged splits, the configuration that looked best in sample landed below the median out of sample {pbo:.0%} of the time.",
            ["e:ml", "m:ml-cpcv", "c:pbo"], "A probability of overfitting below 20%.", ["c:cpcv", "c:pbo"])
        add("ml-pbo2", "edge:models", -1 if pbo > 0.5 else 1, 0.4, 0.7, "ml_test", f"Picking the in-sample winner misleads {pbo:.0%} of the time on this data.",
            ["e:ml", "m:ml-cpcv"], "Lower overfitting probability.", ["c:pbo"])
        nov = mlo["shift"]["novelty_pct"]
        add("ml-novelty", "edge:models", -1 if nov > 0.9 else 1, 0.3, 0.6, "ml_novelty", f"Today's market sits further from its nearest historical months than {nov:.0%} of months do: " + ("the models are extrapolating." if nov > 0.9 else "the models have seen conditions like these before."),
            ["e:ml", "m:ml-novelty", "c:covariate-shift"], "Novelty above the 90th percentile.", ["c:novelty-detection"])
        an = [a for a in mlo["analogs"] if a["next12"] is not None]
        if an:
            down = sum(1 for a in an if a["next12"] < 0)
            add("ml-analogs", "market_valuation", -1 if down > len(an) / 2 else 1, 0.3, 0.3, "ml_analogs", f"Of the {len(an)} months most like today ({', '.join(a['date'][:4] for a in an[:4])}…), {down} were followed by a real loss over the next year.",
                ["e:ml", "m:ml-analogs", "c:knn-analogs"], "Analogs dominated by gains.", ["c:knn-analogs"])
    for pid, sign, s_, rel, txt in (("mr-mclean-pontiff-postpub-decay", -1, 0.6, 0.8, "Published anomalies earn about 58% less after publication and 26% less out of sample (McLean and Pontiff 2016)."),
                                   ("mr-wiecki-r2", -1, 0.6, 0.7, "Across 888 algorithms, backtest Sharpe ratios explained under 2.5% of live performance (Wiecki et al. 2016)."),
                                   ("mr-hxz-65pct-fail", -1, 0.4, 0.6, "65% of 452 published anomalies fail a t of 1.96 when replicated (Hou, Xue and Zhang 2020)."),
                                   ("mr-jkp-replication-counterpoint", 1, 0.3, 0.6, "Counterpoint: Jensen, Kelly and Pedersen find most factors do replicate across 93 countries."),
                                   ("mr-novy-marx-velikov-high-turnover", -1, 0.4, 0.7, "None of the six high-turnover anomalies Novy-Marx and Velikov studied survives trading costs in basic form."),
                                   ("mr-khandani-lo-daily-losses", -1, 0.3, 0.6, "In August 2007 a standard quant strategy lost 6.85% in three days unlevered, about a quarter of capital at 8 to 1 (Khandani and Lo).")):
        if pid in K:
            add("p-" + pid, "edge:models", sign, s_, rel, "literature", txt, ["k:" + pid, "c:model-risk"], "New evidence on live performance.", [])
    for pid, sign, s_, rel, txt in (("mr-ldp-10-reasons-2018", -1, 0.3, 0.6, "Lopez de Prado (2018): most machine-learning funds fail through leakage, overfitting and non-stationary data, not weak algorithms."),
                                   ("mr-bailey-7-trials", -1, 0.4, 0.8, "On two years of data, seven tries are enough for a strategy with no edge to show an in-sample Sharpe of 1 (Bailey et al.)."),):
        if pid in K:
            add("p-" + pid, "edge:ml", sign, s_, rel, "literature_ml", txt, ["k:" + pid, "c:overfitting"], "New evidence.", [])
    if aso:
        c = aso["checks"]
        t = c["tails_month"]
        add("as-tails", "edge:models", -1, 0.6, 0.85, "assumptions", f"Monthly stocks had {t['observed_beyond']} moves beyond 3 standard deviations where a bell curve expects {t['gaussian_expects']:.0f}; a normal 1-in-100 month understates the real one by {abs(t['var_understatement']):.0%}.",
            ["e:assumptions", "m:as-tests", "c:fat-tails"], "None: 155 years of data.", ["c:fat-tails", "c:var"])
        add("as-tails2", "risk_leverage_hedging", -1, 0.3, 0.8, "assumptions", f"A normal model understates the worst month in a hundred by {abs(t['var_understatement']):.0%}; size for the fat tail.",
            ["e:assumptions", "c:var"], "None.", ["c:var"])
        ks = c["kappa"]["series"]
        if "Henry Hub gas, daily" in ks:
            add("as-kappa", "risk_leverage_hedging", -1, 0.3, 0.7, "kappa", f"Taleb's kappa: {ks['S&P 500, monthly']['kappa']:.2f} for monthly stocks and {ks['Henry Hub gas, daily']['kappa']:.2f} for daily gas; gas needs about {ks['Henry Hub gas, daily']['n_equivalent_30']:.0f} observations to learn what 30 Gaussian ones would.",
                ["e:assumptions", "m:as-kappa", "c:kappa-metric"], "None.", ["c:kappa-metric"])
        h = c["hedge"]
        if h.get("now") is not None:
            add("as-tlt", "bonds_rates", -1 if h["now"] > h["rho_star"] else 1, 0.7, 0.7, "hedge_break", f"A {h['weight']:.0%} TLT sleeve only lowers the book's risk while the stock-bond correlation is below {h['rho_star']:+.2f}; the latest 36-month reading is {h['now']:+.2f}.",
                ["e:assumptions", "m:as-breakpoints", "c:stock-bond-correlation", "a:tlt"], f"The correlation falling below {h['rho_star']:+.2f}.", ["c:tlt", "c:breakpoint"])
            add("as-tlt2", "edge:models", -1 if h["now"] > h["rho_star"] else 1, 0.4, 0.7, "hedge_break", "The classic bond hedge assumes a negative stock-bond correlation; the data now break that assumption.",
                ["e:assumptions", "m:as-breakpoints"], "A negative correlation for a year.", [])
        w = c["worlds"]
        if "inflation" in w:
            add("as-worlds", "bonds_rates", -1, 0.5, 0.6, "worlds", f"In histories resampled from inflationary months a 60/40 mix beat all stocks on Sharpe in {w['inflation']['mix_sharpe']:.0%} of worlds, against {w['all']['mix_sharpe']:.0%} in all months.",
                ["e:assumptions", "m:as-worlds", "c:stressed-worlds", "c:sixty-forty"], "Inflation falling below 2.75% for a year.", ["c:stressed-worlds"])
            add("as-worlds2", "edge:trend", 1, 0.3, 0.6, "worlds", f"The trend rule cut the worst drawdown in {w['all']['trend_dd']:.0%} of resampled histories, but beat holding on Sharpe in only {w['all']['trend_sharpe']:.0%}.",
                ["e:assumptions", "m:as-worlds"], "Worlds where it fails to cut drawdowns.", [])
        tr = c["trend"]
        add("as-trend-cost", "edge:trend", 1 if tr["breakeven_cost"] > 0.002 else -1, 0.3, 0.7, "breakpoints", f"The trend rule's Sharpe gain survives costs up to {tr['breakeven_cost'] * 1e4:.0f} basis points a switch (about {tr['switches_per_year']:.1f} switches a year) but not a four-month delay.",
            ["e:assumptions", "m:as-breakpoints", "c:transaction-cost"], "Costs above the breakeven.", ["c:breakpoint"])
        k = c["kelly"]
        add("as-kelly", "edge:sizing", -1, 0.6, 0.8, "breakpoints", f"From any 30-year backtest, the Kelly fraction for stocks ranged from {k['min']:.1f} to {k['max']:.1f} times capital: the edge is too uncertain for full Kelly.",
            ["e:assumptions", "c:kelly", "c:position-sizing"], "None.", ["c:kelly"])
        fr = c["fragility"]["structures"]
        if "put_spread" in fr:
            add("as-frag", "risk_leverage_hedging", -1, 0.3, 0.6, "fragility", f"The 95/85 put spread helps until the index is down about {float(fr['put_spread']['at']) * 100:.0f}% and then stops: losses accelerate again below it (Taleb-Douady test). Selling puts is fragile throughout.",
                ["e:assumptions", "m:as-fragility", "c:fragility-heuristic", "c:put-spread"], "None.", ["c:fragility-heuristic"])
        broken = [m for m in aso["map"] if m["verdict"] == "broken"]
        add("as-map", "edge:models", -1 if len(broken) >= 3 else 1, 0.5, 0.75, "assumptions", f"Of {len(aso['map'])} engine models, {len(broken)} rest on an assumption the data break today: {', '.join(m['model'].lower() for m in broken[:4])}.",
            ["e:assumptions", "c:assumption-testing"], "Fewer broken assumptions.", ["c:assumption-testing"])
    if positions:
        for tk, p in sorted(positions.items()):
            if not isinstance(p, dict) or p.get("p_achieve") is None or p.get("implied_growth") is None:
                continue
            axis = "semis_nvidia" if tk in ("NVDA", "AVGO") else ("ai_boom" if tk in ("MSFT", "GOOGL", "AMZN", "META", "ORCL") else "megacap_concentration")
            pa = p["p_achieve"]
            add(f"rdcf-{tk}", axis, -1 if pa < 0.05 else 1, 0.35, 0.45, "reverse_dcf", f"{tk}'s price needs about {p['implied_growth']:.0%} a year of revenue growth for ten years; {pa:.1%} of companies that size ever managed it.",
                ["e:valuation", "c:reverse-dcf", "c:base-rates", "a:" + tk], "Faster growth or a lower price.", ["c:implied-growth"])
    return S


# ---------------------------------------------------------------- the belief network: claims that move together
def combine(rows: list[dict]) -> dict:
    """The weighing rule shared by every verdict: each row has sig and relevance; within a family the k-th strongest
    reading counts 1/sqrt(k); returns the log-odds, the leave-one-family-out range and the hinge."""
    groups: dict[str, list] = {}
    for x in rows:
        s = x["sig"]
        x["raw"] = s["sign"] * s["s"] * s["rel"] * x["relevance"]
        groups.setdefault(s["group"], []).append(x)
    for g in groups.values():
        g.sort(key=lambda x: (-abs(x["raw"]), x["sig"]["id"]))
        for k, x in enumerate(g):
            x["dep"] = 1 / math.sqrt(k + 1)
            x["c"] = x["raw"] * x["dep"]
    L = 0.0
    for x in rows:
        L += x["c"]
    p = 1 / (1 + math.exp(-L))
    ps = []
    for g in sorted(groups):
        Lg = L - sum(x["c"] for x in rows if x["sig"]["group"] == g)
        ps.append(1 / (1 + math.exp(-Lg)))
    hinge = max(rows, key=lambda x: (abs(x["c"]), x["sig"]["id"])) if rows else None
    return {"L": L, "p": p, "lo": min(ps + [p]), "hi": max(ps + [p]), "hinge": hinge, "groups": len(groups)}


def network(atlas: dict, sigs: list[dict]) -> dict:
    """Links between claims, learned by the atlas: shock each axis's representative series by one standard deviation
    and read the cumulative 12-month response of every other axis's series (sign-adjusted so 'bull' means bull on
    both). Weights are scaled so the strongest is 1; weak ones are dropped. Each axis also gets its base log-odds from
    all of its evidence at full relevance."""
    from . import atlas as AT
    axes = [a for a in AXIS_REP if any(s["axis"] == a for s in sigs)]
    M = AT.matrices(atlas)
    raw = {}
    for a in axes:
        node_a, sa = AXIS_REP[a]
        if node_a not in M["ix"]:
            continue
        R = AT.respond(atlas, {node_a: 1.0}, 12, M).sum(axis=0)
        for b in axes:
            node_b, sb = AXIS_REP[b]
            if b == a or node_b not in M["ix"]:
                continue
            raw[(a, b)] = sa * sb * float(R[M["ix"][node_b]])
    mx = max((abs(v) for v in raw.values()), default=1.0) or 1.0
    links = [[axes.index(a), axes.index(b), round(v / mx, 4)] for (a, b), v in sorted(raw.items()) if abs(v / mx) >= NET_MIN]
    base = []
    for a in axes:
        rows = [{"sig": s, "relevance": 1.0} for s in sigs if s["axis"] == a]
        base.append(round(combine(rows)["L"], 6))
    out = {"axes": axes, "links": links, "base": base, "gamma": NET_GAMMA, "iters": NET_ITERS, "reps": {a: AXIS_REP[a] for a in axes}}
    out["p"] = [round(x, 6) for x in propagate(out)]
    return out


def propagate(net: dict, fixed: dict | None = None) -> list[float]:
    """Mean-field belief propagation: m = 2p - 1; each step, every free axis's log-odds is its own evidence plus gamma
    times the weighted beliefs of the axes that drive it; half-step damping; fixed axes (interventions) keep their
    value and ignore their parents."""
    fixed = fixed or {}
    n = len(net["axes"])
    m = []
    for i, a in enumerate(net["axes"]):
        m.append(2 * fixed[a] - 1 if a in fixed else 2 / (1 + math.exp(-net["base"][i])) - 1)
    for _ in range(net["iters"]):
        pull = [0.0] * n
        for i, j, w in net["links"]:
            pull[j] += w * m[i]
        new = []
        for k, a in enumerate(net["axes"]):
            if a in fixed:
                new.append(m[k])
            else:
                L = net["base"][k] + net["gamma"] * pull[k]
                new.append(0.5 * m[k] + 0.5 * (2 / (1 + math.exp(-L)) - 1))
        m = new
    return [(x + 1) / 2 for x in m]


# ---------------------------------------------------------------- the graph
def build(atlas: dict, quotes: list[dict], know: list[dict], world: dict | None = None, labs_L: dict | None = None,
          research_latest: dict | None = None, layout: bool = True, mlo: dict | None = None, aso: dict | None = None,
          positions: dict | None = None, companies: list[dict] | None = None, rlo: dict | None = None, tech: dict | None = None,
          chron: dict | None = None, bonds: dict | None = None, cx: dict | None = None, dec: dict | None = None, pf: dict | None = None) -> dict:
    nodes: list[dict] = []
    idx: dict[str, int] = {}
    edges: dict[tuple, list] = {}

    def node(nid, kind, name, group, text="", aliases=(), **extra):
        if nid in idx:
            return idx[nid]
        idx[nid] = len(nodes)
        nodes.append({"id": nid, "k": kind, "n": name, "g": group, "t": text, "a": [a for a in aliases if a], **extra})
        return idx[nid]

    def edge(a, b, typ, w=None):
        if a not in idx or b not in idx or a == b:
            return
        i, j = idx[a], idx[b]
        key = (min(i, j), max(i, j))
        ww = round(EDGE_W.get(typ, 0.5) if w is None else w, 4)
        if key in edges:
            if ww > edges[key][2]:
                edges[key] = [i, j, ww, TYPES.index(typ)]
            return
        edges[key] = [i, j, ww, TYPES.index(typ)]

    concepts = ontology.concepts()
    for cl, title in ontology.CLUSTERS.items():
        node("x:" + cl, "cluster", title, cl, f"Everything the mind knows about {title.lower()}.", [title])
    for c in concepts:
        node(c["id"], "concept", c["name"], c["cluster"], c["text"], c["aliases"], f=c["formula"])
    for a, b, w in similar_concepts(concepts):
        edge(a, b, "similar", w)
    # atlas
    for n in atlas["nodes"]:
        kind = "series" if n["measured"] else ("holding" if n["family"] == "Book" else "driver")
        grp = "markets" if n["measured"] else "core"
        node("a:" + n["id"], kind, n["name"], grp, f"{n['family']}. {n.get('source', '')}".strip(), [n.get("short", ""), n["id"]] if len(n["id"]) > 2 else [n.get("short", "")])
    causal = []
    for l in list(atlas["links"]) + [dict(x, judged=True) for x in atlas.get("judged", [])]:
        if l.get("self"):
            continue
        a, b = "a:" + l["from"], "a:" + l["to"]
        if l.get("judged"):
            edge(a, b, "judged", 0.3 + 0.5 * min(1.0, abs(l["w"])))
        else:
            edge(a, b, "learned", 0.3 + 0.5 * min(1.0, abs(l.get("t", 2)) / 8))
        if a in idx and b in idx:
            causal.append([idx[a], idx[b], round(float(l["w"]), 5)])
    # topics, investors, quotes
    for k, t in voices.TOPICS.items():
        node("t:" + k, "topic", t["title"], "voices", f"Bull case: {t['bull']}. Bear case: {t['bear']}.", [t["title"]])
    for k, ax in EDGE_AXES.items():
        pass
    for q in quotes:
        sp = q["speaker"]
        pid = "p:" + slug(sp)
        node(pid, "investor", re.sub(r"\s*\(.*?\)", "", sp).replace("Jerome H. Powell", "Jerome Powell"), "voices", q.get("role", ""), [])
        node("q:" + q["id"], "quote", f"{nodes[idx[pid]]['n']}, {q['date'][:4]}", "voices",
             f"{q['text']} {q.get('gist', '')} {' '.join(q.get('tags') or [])}", [], st=q["stance"])
        edge("q:" + q["id"], "t:" + q["topic"], "about")
        edge("q:" + q["id"], pid, "said_by")
    # engine
    mods = _engine_modules()
    for m in mods:
        node("e:" + m["module"], "engine", m["module"].replace("analytics.", "analytics/").replace("data.", "data/") + ".py", "engine", m["doc"], [m["module"]], lines=m["lines"])
    for m in mods:
        for i in m["imports"]:
            edge("e:" + m["module"], "e:" + i, "code")
    for mid, spec in METHODS.items():
        node("m:" + mid, "method", spec[0], "engine", spec[1], [])
        edge("m:" + mid, "e:" + (spec[2] if len(spec) > 2 else "labs"), "method_of")
    try:
        from . import mcp_server
        tools = {n: d for n, (_, d, _, _) in mcp_server.TOOLS.items()}
    except Exception:  # pragma: no cover
        tools = {}
    tools.setdefault("reason", "Ask the mind a question: what lit up, the verdict on the claim with its range, the arguments for and against, the causal chains to the book and a proposed action. Research only.")
    tools.setdefault("labs_lookup", "The labs' tested claims: trend rules, oscillators, valuation, regimes, volatility, spreads, calendar and the multiple-testing table.")
    tools.setdefault("game_math", "Poker equity, pot odds, Kelly, risk of ruin, Rubinstein and Nash bargaining, the best haggling offer, IRR, TVPI, PME and the J-curve.")
    for tn, d in tools.items():
        node("o:" + tn, "tool", tn, "engine", d[:400], [tn.replace("_", " ")])
        edge("o:" + tn, "e:mcp_server", "tool")
        for mm in TOOL_MODULES.get(tn, []):
            edge("o:" + tn, "e:" + mm, "tool")

    def resolve(ref):
        kind, _, rest = ref.partition(":")
        if kind in ("s", "j"):
            return "a:" + rest
        if kind == "e":
            if rest.startswith("labs-") or rest == "labs":
                return "m:" + rest if rest != "labs" else "e:labs"
            return "e:" + ENGINE_ALIAS.get(rest, rest)
        return ref
    for c in concepts:
        node_id = c["id"]
        edge(node_id, "x:" + c["cluster"], "member")
        for kind, tgt in c["rel"]:
            edge(node_id, resolve(tgt if ":" in tgt else "c:" + tgt), kind)
    # topic terms to concepts
    alias_index: dict[str, list[str]] = {}
    for c in concepts:
        for a in [c["name"], *c["aliases"], c["id"][2:].replace("-", " ")]:
            alias_index.setdefault(norm(a).strip(), []).append(c["id"])
    for k, t in voices.TOPICS.items():
        for term in t["terms"].split():
            for cid in alias_index.get(term.replace("_", " "), [])[:1]:
                edge("t:" + k, cid, "topic_of")
    for k, ax in EDGE_AXES.items():
        for cid in ax["terms"]:
            edge(ax["node"], cid, "related")
    # facts
    tok_concepts = [(c["id"], set(voices.tokens(" ".join([c["name"], *c["aliases"]]), expand=False))) for c in concepts]
    atlas_alias = {}
    for n in atlas["nodes"]:
        for a in (n["name"], n.get("short", ""), n["id"]):
            if a and len(a) > 2:
                atlas_alias[norm(a).strip()] = "a:" + n["id"]

    def match(phrase):
        p = norm(phrase).strip()
        if p in alias_index:
            return alias_index[p][:1]
        if p in atlas_alias:
            return [atlas_alias[p]]
        if p.endswith("s") and p[:-1] in alias_index:
            return alias_index[p[:-1]][:1]
        qt = set(voices.tokens(phrase, expand=False))
        if not qt:
            return []
        best, bid = 0.0, None
        for cid, ts in tok_concepts:
            if qt <= ts:
                sc = len(qt) / len(ts)
                if sc > best:
                    best, bid = sc, cid
        return [bid] if bid else []
    for it in know:
        grp = FACT_CLUSTER.get(it.get("cluster"), "valuation")
        fid = "k:" + it["id"]
        kind = {"paper": "paper", "source": "source", "quote": "fact"}.get(it["kind"], "fact")
        node(fid, kind, it["title"], grp, it["text"], [it["title"]] if kind == "source" else [],
             **{k2: it.get(k2) for k2 in ("value", "unit", "as_of", "source_url", "source_title", "publisher", "primary", "verification", "authors", "checked",
                                           "feed_url", "edge", "biases", "cadence", "cost", "speaker")})
        if kind == "source":
            edge(fid, "c:information-edge", "related")
        edge(fid, "x:" + grp, "member", 0.3)
        for c in it.get("concepts") or []:
            for m in match(c):
                edge(fid, m, "evidence")
    # world
    world = world or {}
    for iso, name, cur, exports, note in COUNTRIES:
        w = world.get(iso, {})
        bits = [note]
        if w.get("gdp"):
            bits.append(f"GDP ${w['gdp'] / 1e12:.2f} trillion ({w['gdp_year']}, World Bank)")
        if w.get("inflation") is not None:
            bits.append(f"inflation {w['inflation']:.1f}% ({w['inflation_year']})")
        if w.get("pop"):
            bits.append(f"population {w['pop'] / 1e6:.0f} million")
        node("g:" + iso, "country", name, "world", "; ".join(bits) + ".", [name], gdp=w.get("gdp"))
        if cur:
            edge("g:" + iso, cur if ":" in cur else "c:" + cur, "currency")
        for ex in exports:
            edge("g:" + iso, ex, "exports")
    curated = {c[0] for c in COUNTRIES}
    for iso, w in sorted(world.items()):
        if iso in curated or not w.get("gdp") or not w.get("name"):
            continue
        bits = [f"GDP ${w['gdp'] / 1e9:,.0f} billion ({w['gdp_year']}, World Bank)"]
        if w.get("pop"):
            bits.append(f"population {w['pop'] / 1e6:,.1f} million")
        node("g:" + iso, "country", w["name"], "world", "; ".join(bits) + ".", [w["name"]], gdp=w["gdp"])
        if w.get("region") and "g:" + w["region"] in idx:
            edge("g:" + iso, "g:" + w["region"], "related", 0.3)
    big = sorted([n for n in nodes if n["k"] == "country" and n.get("gdp")], key=lambda n: -n["gdp"])
    for n in big:                                                   # every economy hangs off the world-economy concept
        edge(n["id"], "c:gdp", "related", 0.25 + 0.35 * min(1.0, (n["gdp"] / big[0]["gdp"]) ** 0.5))
    # S&P 500 companies, sub-industries and sectors
    for co in companies or []:
        sec, ind = "sec:" + slug(co["sector"]), "ind:" + slug(co["industry"])
        node(sec, "sector", co["sector"], "companies", f"GICS sector: {co['sector']}.", [co["sector"]])
        node(ind, "industry", co["industry"], "companies", f"GICS sub-industry in {co['sector']}.", [co["industry"]])
        edge(ind, sec, "part_of")
        node("co:" + co["symbol"], "company", co["name"], "companies", f"{co['symbol']}: {co['industry']} ({co['sector']}); headquarters {co.get('hq', '')}; in the S&P 500 since {co.get('added', '')}.",
             [co["symbol"], co["name"]])
        edge("co:" + co["symbol"], ind, "part_of", 0.6)
        if "a:" + co["symbol"] in idx:
            edge("co:" + co["symbol"], "a:" + co["symbol"], "is_a", 0.95)
    for ind_name, cids in INDUSTRY_CONCEPTS.items():
        for cid in cids:
            edge("ind:" + slug(ind_name), cid, "related", 0.6)
    for sec_name, cid in SECTOR_CONCEPTS.items():
        edge("sec:" + slug(sec_name), cid, "related", 0.5)
    # machine-learning models and the assumption map, as nodes the mind can reach
    if mlo:
        for task in ("return", "crash"):
            for k, lab in mlo[task]["labels"].items():
                sk = mlo[task]["scores"][k]["skill"]
                node(f"ml:{task}:{k}", "model", f"{lab} ({'12-month return' if task == 'return' else '15% fall within a year'})", "ml",
                     f"Out-of-sample skill against the {'historical mean' if task == 'return' else 'base rate'} since {mlo['start_oos']}: {sk:+.1%}. Today's forecast: "
                     + (f"{math.expm1(mlo[task]['now'][k]):+.1%} real." if task == "return" else f"{mlo[task]['now'][k]:.0%} chance."), [lab])
                edge(f"ml:{task}:{k}", "e:ml", "uses", 0.6)
                edge(f"ml:{task}:{k}", "c:machine-learning", "is_a", 0.7)
    if aso:
        for i, m in enumerate(aso["map"]):
            node(f"as:{i}", "assumption", m["model"], "reality", f"Assumes {', '.join(m['assumes'])}. Verdict on the data: {m['verdict']}. {m['consequence']}", [], verdict=m["verdict"])
            edge(f"as:{i}", "e:assumptions", "uses", 0.6)
            edge(f"as:{i}", "c:assumption-testing", "is_a", 0.7)
            for mod in re.findall(r"([a-z_/]+)\.py", m["where"]):
                edge(f"as:{i}", "e:" + mod.replace("/", "."), "related", 0.6)
    v17_nodes(node, edge, nodes, idx, chron, bonds, cx)
    v19_nodes(node, edge, dec)
    v20_nodes(node, edge, pf)
    # signals
    K = {it["id"]: it for it in know}
    cape_pct = None
    if labs_L and labs_L["valuation"]["cape"].get("now_source") == "research":
        cape_pct = labs_L["valuation"]["cape"]["percentile"]
    sigs = signals(K, labs_L, research_latest, cape_pct) + more_signals(K, mlo, aso, positions) + v16_signals(K, rlo, tech) + v17_signals(K, bonds, cx) + v19_signals(K, dec) + v20_signals(K, pf)
    for s in sigs:
        ax = s["axis"]
        title = voices.TOPICS[ax]["title"] if ax in voices.TOPICS else EDGE_AXES[ax]["title"]
        node(s["id"], "signal", s["text"][:90], "evidence", s["text"], [], axis=ax, sign=s["sign"])
        edge(s["id"], "t:" + ax if ax in voices.TOPICS else EDGE_AXES[ax]["node"], "signal")
        for r in s["refs"] + s["targets"]:
            edge(s["id"], resolve(r) if r.startswith(("e:", "s:", "j:")) else r, "cites")
        del title
    E = sorted(edges.values(), key=lambda e: (e[0], e[1]))
    G = {"nodes": nodes, "edges": E, "causal": causal, "signals": sigs, "axes": axes_meta(), "types": TYPES,
         "groups": GROUP_NAMES, "params": params(), "net": network(atlas, sigs)}
    if bonds:
        G["bonds"] = bonds_compact(bonds)
    if dec and dec.get("now", {}).get("mixture"):
        G["decision"] = decision_compact(dec, pf)
    if layout:
        place(G)
    return G


def axes_meta() -> dict:
    out = {k: {"title": t["title"], "bull": t["bull"], "bear": t["bear"], "node": "t:" + k, "book": BOOK_SIGN.get(k, 0), "hedge": HEDGE_FOR.get(k)} for k, t in voices.TOPICS.items()}
    for k, a in EDGE_AXES.items():
        out[k] = {"title": a["title"], "bull": a["bull"], "bear": a["bear"], "node": a["node"], "book": 0, "hedge": None}
    return out


def params() -> dict:
    return {"alpha": ALPHA, "steps": STEPS, "seeds": SEEDS, "seed_floor": SEED_FLOOR, "w_bm": W_BM, "w_alias": W_ALIAS, "doc_w": list(DOC_W), "kind_recall": KIND_RECALL, "qstop": QSTOP,
            "axis_topic_boost": AXIS_TOPIC_BOOST, "explain_ratio": EXPLAIN_RATIO, "hedges": HEDGE_NAMES, "whatif_up": WHATIF_UP, "whatif_down": WHATIF_DOWN,
            "whatif_split": WHATIF_SPLIT, "rx_whatif": RX_WHATIF, "rx_explain": RX_EXPLAIN, "rx_book": RX_BOOK, "net_cap": NET_CAP,
            "rx_month": RX_MONTH, "rx_year": RX_YEAR, "rx_now": RX_NOW, "rx_hist": RX_HIST, "rx_decide": RX_DECIDE, "rx_pstress": RX_PSTRESS, "rx_r12": RX_R12,
            "rx_gamma": RX_GAMMA}


@cache.memo("mind.group_layout", deps=("buildout.atlas",))
def _group_layout(A, seed: int, iters: int):
    """One galaxy's force layout; cached by its adjacency, so an unchanged group is never laid out twice."""
    from .atlas import layout as fr_layout
    return fr_layout(A, [0] * len(A), seed=seed, iters=iters, spread=True)


def place(G: dict) -> None:
    """Galaxy layout: each group is laid out on its own (atlas.layout, force-directed then spread to an even disc whose
    radius grows with the square root of its size); the discs are then placed by a force layout of the groups, pulled
    together by the share of links between them (normalized, so a large graph cannot collapse the discs onto each
    other) and kept apart by their radii. Deterministic."""
    import numpy as np
    nodes = G["nodes"]
    gs = sorted({n["g"] for n in nodes})
    gi = {g: i for i, g in enumerate(gs)}
    p = len(nodes)
    members = {g: [i for i, n in enumerate(nodes) if n["g"] == g] for g in gs}
    pos = {}
    gid = np.array([gi[n["g"]] for n in nodes])
    local = np.zeros(p, dtype=int)
    for g in gs:
        local[members[g]] = np.arange(len(members[g]))
    E = np.array([[i, j, w] for i, j, w, _ in G["edges"]], dtype=float).reshape(-1, 3)
    ei, ej = E[:, 0].astype(int), E[:, 1].astype(int)
    for g in gs:
        idx = members[g]
        if g == "chronicle":
            from .chronicle import spiral
            pos[g] = spiral([nodes[i] for i in idx])
            continue
        A = np.zeros((len(idx), len(idx)))
        m = (gid[ei] == gi[g]) & (gid[ej] == gi[g])                # edges inside this group, without a Python scan per group
        A[local[ei[m]], local[ej[m]]] = E[m, 2]
        A[local[ej[m]], local[ei[m]]] = E[m, 2]
        pos[g] = _group_layout(A, 11 + gi[g], 300 if len(idx) < 800 else 150) if len(idx) > 1 else np.zeros((1, 2))
    Gn = len(gs)
    Cw = np.zeros((Gn, Gn))
    for i, j, w, _ in G["edges"]:
        a, b = gi[nodes[i]["g"]], gi[nodes[j]["g"]]
        if a != b:
            Cw[a, b] += w
            Cw[b, a] += w
    Cw = Cw / (Cw.max() or 1.0)
    R = np.array([0.16 * math.sqrt(len(members[g])) for g in gs])
    order = sorted(range(Gn), key=lambda k: -R[k])
    C = np.zeros((Gn, 2))
    for rank, k in enumerate(order):
        a = 2.399963 * rank                                   # golden-angle spiral start
        C[k] = [math.cos(a) * 0.4 * math.sqrt(rank + 1), math.sin(a) * 0.4 * math.sqrt(rank + 1)]
    need = R[:, None] + R[None, :] + 0.08
    off = ~np.eye(Gn, dtype=bool)
    for it in range(900):                                     # vectorized over all pairs of groups
        d = C[:, None, :] - C[None, :, :]
        dist = np.sqrt((d ** 2).sum(-1)) + 1e-9
        push = np.where((dist < need) & off, (need - dist) * 0.5, 0.0)
        pull = np.where(off, 0.03 * Cw * np.minimum(1.0, dist), 0.0)
        F = ((push - pull) / dist)[:, :, None] * d
        F = F.sum(axis=1) - 0.01 * C
        C += F * (1 - it / 1000)
    X = np.zeros((p, 2))
    for g in gs:
        k = gi[g]
        X[members[g]] = C[k] + pos[g] * R[k]
    X -= (X.max(axis=0) + X.min(axis=0)) / 2
    X /= (np.abs(X).max() or 1.0) / 0.97
    for n, (x, y) in zip(nodes, X):
        n["x"], n["y"] = round(float(x), 4), round(float(y), 4)


# ---------------------------------------------------------------- thinking
class Mind:
    def __init__(self, G: dict, lib: voices.Library | None = None):
        self.G = G
        self.nodes = G["nodes"]
        self.N = len(self.nodes)
        self.idx = {n["id"]: i for i, n in enumerate(self.nodes)}
        self.edges = G["edges"]
        self.deg = [0.0] * self.N
        for i, j, w, _ in self.edges:
            self.deg[i] += w
            self.deg[j] += w
        docs = []
        dw = G["params"]["doc_w"]
        for n in self.nodes:
            d = voices.tokens(n["n"]) * dw[0] + voices.tokens(" ".join(n["a"])) * dw[1] + voices.tokens(n["t"] or "") * dw[2]
            docs.append(d)
        self.index = voices.Index(docs)
        self.alias = []
        for i, n in enumerate(self.nodes):
            if n["k"] in ("concept", "series", "driver", "holding", "topic", "country", "investor", "cluster", "tool", "month", "year", "episode", "etf", "desk"):
                for a in [n["n"], *n["a"]]:
                    s = norm(a)
                    if len(s.strip()) >= 2:
                        self.alias.append((s, i, min(1.0, 0.6 + 0.1 * len(s.split()))))
        self.sigs = G["signals"]
        self.sig_node = [self.idx[s["id"]] for s in self.sigs]
        self.lib = lib

    # 2 recall
    def recall(self, text: str) -> list[tuple[int, float]]:
        qs = set(voices.stem(w) for w in QSTOP)
        q = [w for w in voices.tokens(text) if w not in qs]
        bm = self.index.score(q) if q else [0.0] * self.N
        bm = [b * KIND_RECALL.get(self.nodes[i]["k"], 1.0) for i, b in enumerate(bm)]
        mx = max(bm) if bm else 0.0
        score = [W_BM * (b / mx) if mx > 0 else 0.0 for b in bm]
        t = norm(text)
        hit = [0.0] * self.N
        for s, i, w in self.alias:
            if s in t and w > hit[i]:
                hit[i] = w
        for i in range(self.N):
            score[i] += W_ALIAS * hit[i]
        best = max(score) if score else 0.0
        if best <= 0:
            return []
        cand = sorted(range(self.N), key=lambda i: (-score[i], i))[:SEEDS]
        return [(i, score[i]) for i in cand if score[i] >= SEED_FLOOR * best]

    # 3 spread
    def _ppr(self):
        """The walk's arrays, built once: each edge's weight over its endpoint's degree, both directions."""
        if getattr(self, "_walk", None) is None:
            import numpy as np
            E = np.asarray([e[:3] for e in self.edges], dtype=float).reshape(-1, 3)
            I, J, W = E[:, 0].astype(np.int64), E[:, 1].astype(np.int64), E[:, 2]
            deg = np.asarray(self.deg)
            self._walk = (I, J, W / np.where(deg[I] > 0, deg[I], 1), W / np.where(deg[J] > 0, deg[J], 1), np.flatnonzero(deg == 0))
        return self._walk

    def spread(self, seeds: list[tuple[int, float]]) -> list[float]:
        """Personalized PageRank from the seeds: STEPS iterations, restart probability 1 - ALPHA, dangling mass back to
        the seeds. Vectorized (numpy); site/src/mind.js runs the same walk and agrees to 1e-12."""
        import numpy as np
        I, J, WI, WJ, dang = self._ppr()
        tot = sum(s for _, s in seeds)
        s0 = np.zeros(self.N)
        for i, s in seeds:
            s0[i] = s / tot
        r = s0.copy()
        for _ in range(STEPS):
            nr = (1 - ALPHA) * s0 + ALPHA * (np.bincount(J, WI * r[I], self.N) + np.bincount(I, WJ * r[J], self.N))
            dangling = float(r[dang].sum()) if len(dang) else 0.0
            if dangling:
                nr += ALPHA * dangling * s0
            r = nr
        return r.tolist()

    def chains(self, r: list[float], k: int = 3, prefer: list[int] | None = None) -> list[dict]:
        """Strongest directed paths over the atlas's causal links from the most activated market nodes to the book."""
        adj: dict[int, list] = {}
        for a, b, w in self.G["causal"]:
            adj.setdefault(a, []).append((b, w))
        book = self.idx.get("a:book")
        if book is None:
            return []
        rmax = max(r) or 1.0
        ranked = [i for i in sorted(range(self.N), key=lambda i: (-r[i], i)) if self.nodes[i]["id"].startswith("a:") and i != book and r[i] >= 0.02 * rmax]
        src = []
        for i in (prefer or []) + ranked:
            if i not in src and i != book:
                src.append(i)
        src = src[:k]
        out = []
        for s in src:
            dist = {s: 0.0}
            prev = {}
            pq = [(0.0, s)]
            done = set()
            while pq:
                d, u = heapq.heappop(pq)
                if u in done:
                    continue
                done.add(u)
                if u == book:
                    break
                for vtx, w in adj.get(u, []):
                    st = min(0.95, max(0.05, abs(w)))
                    nd = d - math.log(st)
                    if nd < dist.get(vtx, math.inf) - 1e-15:
                        dist[vtx] = nd
                        prev[vtx] = (u, w)
                        heapq.heappush(pq, (nd, vtx))
            if book not in dist:
                continue
            path, signs, u = [book], 1, book
            while u != s:
                pu, w = prev[u]
                signs *= 1 if w >= 0 else -1
                path.append(pu)
                u = pu
            path.reverse()
            out.append({"from": self.nodes[s]["id"], "path": [self.nodes[i]["id"] for i in path], "names": [self.nodes[i]["n"] for i in path],
                        "sign": signs, "strength": round(math.exp(-dist[book]), 6)})
        return out

    def net_pull(self, axis: str) -> tuple[float, list[dict]]:
        """What the connected claims, at their network beliefs, add to this axis's log-odds."""
        net = self.G.get("net")
        if not net or axis not in net["axes"]:
            return 0.0, []
        k = net["axes"].index(axis)
        pull, parents = 0.0, []
        for i, j, w in net["links"]:
            if j != k:
                continue
            m = 2 * net["p"][i] - 1
            pull += net["gamma"] * w * m
            parents.append({"axis": net["axes"][i], "w": w, "p": net["p"][i], "contrib": net["gamma"] * w * m})
        parents.sort(key=lambda x: (-abs(x["contrib"]), x["axis"]))
        return pull, parents

    def weigh(self, axis: str, r: list[float], text: str) -> dict:
        rows = []
        for si, s in enumerate(self.sigs):
            if s["axis"] != axis:
                continue
            rows.append({"sig": s, "act": r[self.sig_node[si]]})
        if axis in voices.TOPICS and self.lib is not None:
            res = self.lib.search(text, topic=axis)
            if res.get("lean") is not None:
                lean = res["lean"]
                n_q = sum(res["counts"].values())
                rows.append({"sig": {"id": "s:voices:" + axis, "axis": axis, "sign": 1 if lean > 0 else -1 if lean < 0 else 0, "s": round(0.3 * abs(lean), 6), "rel": 0.3,
                                     "group": "opinion", "text": f"Investor opinion in the library leans {lean:+.2f} on a -2 to +2 scale across {n_q} quotes.", "refs": ["t:" + axis],
                                     "flip": "Opinion swinging the other way.", "targets": []},
                             "act": r[self.idx["t:" + axis]]})
        pull, parents = self.net_pull(axis)
        if abs(pull) > 1e-9:
            axes = self.G["axes"]
            txt = "; ".join(f"{axes[x['axis']]['title']} (bull case {x['p']:.0%}) {'supports' if x['contrib'] > 0 else 'weighs against'} it through a {x['w']:+.2f} link the atlas learned"
                            for x in parents[:2])
            rows.append({"sig": {"id": "s:network:" + axis, "axis": axis, "sign": 1 if pull > 0 else -1, "s": round(min(abs(pull), NET_CAP), 6), "rel": 1.0, "group": "network",
                                 "text": f"Connected claims: {txt}.", "refs": [axes[x["axis"]]["node"] for x in parents[:3]], "flip": "The connected claims turning.", "targets": []},
                         "act": None})
        if not rows:
            return {"axis": axis, "logodds": 0.0, "p_bull": 0.5, "rows": [], "lo": 0.5, "hi": 0.5, "hinge": None, "groups": 0}
        acts = [x["act"] for x in rows if x["act"] is not None]
        amax = (max(acts) if acts else 1.0) or 1.0
        for x in rows:
            x["relevance"] = 1.0 if x["act"] is None else 0.5 + 0.5 * math.sqrt(x["act"] / amax)
        C = combine(rows)
        hinge = C["hinge"]
        p_wo = 1 / (1 + math.exp(-(C["L"] - hinge["c"])))
        rows.sort(key=lambda x: (-abs(x["c"]), x["sig"]["id"]))
        return {"axis": axis, "logodds": C["L"], "p_bull": C["p"], "lo": C["lo"], "hi": C["hi"], "rows": rows, "groups": C["groups"],
                "hinge": {"id": hinge["sig"]["id"], "text": hinge["sig"]["text"], "p_without": p_wo}}

    def frame(self, r: list[float], topic: str | None) -> tuple[list[str], dict]:
        axes = self.G["axes"]
        score = {}
        for si, s in enumerate(self.sigs):
            a = s["axis"]
            v = r[self.sig_node[si]]
            if v > score.get(a, 0.0):
                score[a] = v
        for a in list(score):
            node_act = r[self.idx[axes[a]["node"]]]
            score[a] = (0.5 * score[a] + node_act) * (AXIS_TOPIC_BOOST if a == topic else 1.0)
        return sorted(score, key=lambda a: (-score[a], a)), score

    def whatif(self, cond: str, target: dict | None) -> dict:
        """Intervene on the belief network: the condition's claim is set to 90% (or 10%) and every connected claim
        re-settles. Direction from the condition's own verbs (rise, cut, slow...) and the claim's link to its series."""
        net = self.G.get("net")
        seeds = self.recall(cond)
        if not net or not seeds:
            return {"cond": cond, "found": False}
        r = self.spread(seeds)
        topic = self.lib.search(cond).get("topic") if self.lib is not None else None
        ranked, _ = self.frame(r, topic)
        cand = [a for a in ranked if a in net["axes"]]
        if not cand:
            return {"cond": cond, "found": False}
        axis = cand[0]
        words = voices.raw_tokens(cond)
        up = sum(1 for w in words if w in WHATIF_UP)
        down = sum(1 for w in words if w in WHATIF_DOWN)
        d = 1 if up >= down else -1
        B = self.G.get("bonds")
        if B:                                                   # "the 10-year goes to 4.5%": the direction is the target against today
            from . import bondlab
            q = bondlab.parse(cond, B["curve"])
            if q and abs(q["y10"] - B["curve"]["10y"]) > 1e-9:
                d = 1 if q["y10"] > B["curve"]["10y"] else -1
        bull = d * net["reps"][axis][1] > 0
        pf = 0.9 if bull else 0.1
        after = propagate(net, {axis: pf})
        axes = self.G["axes"]
        eff = []
        for k, a in enumerate(net["axes"]):
            if a == axis:
                continue
            eff.append({"axis": a, "title": axes[a]["title"], "p0": round(net["p"][k], 6), "p1": round(after[k], 6), "d": round(after[k] - net["p"][k], 6)})
        eff.sort(key=lambda x: (-abs(x["d"]), x["axis"]))
        tgt = None
        if target == "book":
            rows, l0, l1 = [], 0.0, 0.0
            for k, a in enumerate(net["axes"]):
                b = axes[a]["book"]
                if b:
                    l0 += b * (2 * net["p"][k] - 1)
                    l1 += b * (2 * after[k] - 1)
                    rows.append({"axis": a, "title": axes[a]["title"], "sign": b, "d": round(b * (after[k] - net["p"][k]), 6)})
            nb = max(1, len(rows))
            rows.sort(key=lambda x: (-abs(x["d"]), x["axis"]))
            tgt = {"axis": "book", "title": "The model book", "lean0": round(l0 / nb, 6), "lean1": round(l1 / nb, 6), "rows": rows[:6]}
            target = None
        if target and target.get("found"):
            reps = {"a:" + v[0]: a for a, v in net["reps"].items()}
            hit = next((reps[s["id"]] for s in target["seeds"] if s["id"] in reps and reps[s["id"]] != axis), None)
            ta = hit or target.get("axis")
        else:
            ta = None
        if ta in net["axes"]:
            k = net["axes"].index(ta)
            tgt = {"axis": ta, "title": axes[ta]["title"], "p0": round(net["p"][k], 6), "p1": round(after[k], 6)}
        side = "bull" if bull else "bear"
        return {"cond": cond, "found": True, "axis": axis, "title": axes[axis]["title"], "side": side, "claim": axes[axis][side], "p_fixed": pf,
                "effects": eff[:8], "target": tgt}

    def bonds(self, text: str) -> dict | None:
        """A yield question ("if the 10-year and 30-year both go to 4%, what is TLT?") answered by repricing every
        Treasury ETF on today's curve (buildout/bondlab.py), with the stock read-through for today's inflation band."""
        from . import bondlab
        B = self.G.get("bonds")
        if not B:
            return None
        q = bondlab.parse(text, B["curve"])
        if not q:
            return None
        funds = {t: {**f, "mats": bondlab.ladder(f)} for t, f in B["funds"].items()}
        sc = bondlab.scenario(B["curve"], funds, q["y10"], q["y30"])
        rows = [{"t": t, "duration": round(f["duration"], 4), "change": round(sc[t]["change"], 6), "total": round(sc[t]["total"], 6),
                 "price0": f.get("price"), "price": None if sc[t]["price"] is None else round(sc[t]["price"], 4)} for t, f in funds.items()]
        out = {"y10": q["y10"], "y30": q["y30"], "d10": round(q["y10"] - B["curve"]["10y"], 6), "d30": round(q["y30"] - B["curve"]["30y"], 6), "rows": rows}
        eq = B.get("equity") or {}
        now = eq.get("now")
        if now and now["regime"] in eq:
            r = eq[now["regime"]]
            out["stocks"] = {"regime": now["regime"], "infl36": now["infl36"], "per_point": r["per_point"], "t": r["t"], "move": round(r["per_point"] * out["d10"] * 100, 6)}
        return out

    def decision(self, text: str) -> dict | None:
        """A question about what the book should do, the regime, or a what-if on the decision engine's inputs ("what if
        the odds of a stressed regime were 50%?", "with a forecast of -5%?", "at a risk aversion of 5?"): today's call and,
        when an input is named, the call recomputed with it (decide.what_if; dxlive.js in the page)."""
        from . import decide
        D = self.G.get("decision")
        if not D:
            return None
        low = text.lower()
        ps = re.search(RX_PSTRESS, low)
        r12 = re.search(RX_R12, low)
        ga = re.search(RX_GAMMA, low)
        if not (re.search(RX_DECIDE, low) or ps or ga or (r12 and re.search(r"\b(?:stocks?|exposure|book|decision|engine)\b", low))):
            return None
        kw: dict = {}
        if ps:
            kw["p_stress"] = min(1.0, float(ps.group(1) or ps.group(2)) / 100)
        if r12:
            kw["r12"] = float(r12.group(1).replace("\u2212", "-")) / 100
        if ga:
            kw["gamma"] = max(0.5, min(30.0, float(ga.group(1))))
        base = decide.what_if(D)
        out = {"exposure": D["exposure"], "optimum": base["optimum"], "gate": D["gate"]["value"], "t": D["gate"]["t"], "n_tried": D["gate"]["n_tried"],
               "p_stress": D["regime"]["next"][D["regime"]["worst"]], "changepoint": D["changepoint"]["recent"], "hedge": D["hedge"], "stacked": D["forecasts"]["stacked"]}
        if kw:
            w = decide.what_if(D, **kw)
            out["whatif"] = {**{k: round(v, 6) for k, v in kw.items()}, "optimum": w["optimum"], "decision": w["decision"], "capped": w["capped"]}
        if D.get("portfolio"):
            p = D["portfolio"]
            cur = max(range(len(p["next"])), key=lambda i: p["next"][i])
            out["portfolio"] = {"decision": p["decision"], "optimum": p["optimum"], "gate_policy": p["gate_policy"], "state": p["states"][cur]["name"],
                                "p_state": p["next"][cur], "corr_sb": p["states"][cur]["corr_sb"]}
        return out

    def history(self, text: str) -> dict | None:
        """A question about a month, a year, an episode or 'months like now': the chronicle node and what it links to
        (the episodes a year sits in, a month's analogs and what followed them)."""
        t = text.lower()
        nid = None
        m = re.search(RX_MONTH, t)
        if m and f"m:{m.group(2)}-{MON3.index(m.group(1)) + 1:02d}" in self.idx:
            nid = f"m:{m.group(2)}-{MON3.index(m.group(1)) + 1:02d}"
        if nid is None and re.search(RX_NOW, t) and "m:now" in self.idx:
            nid = "m:now"
        if nid is None:
            nt = norm(text)
            best = None
            for a, i, _w in self.alias:
                n = self.nodes[i]
                if n["k"] == "episode" and a in nt and (best is None or len(a) > best[0]):
                    best = (len(a), n["id"])
            if best:
                nid = best[1]
        if nid is None:
            y = re.search(RX_YEAR, t)
            if y and f"y:{y.group(1)}" in self.idx and (re.search(RX_HIST, t) or len(t.split()) <= 4):
                nid = f"y:{y.group(1)}"
        if nid is None:
            return None
        i = self.idx[nid]
        if not hasattr(self, "_adj"):
            self._adj = [[] for _ in range(self.N)]
            for a, b, w, ty in self.edges:
                self._adj[a].append((b, w, ty))
                self._adj[b].append((a, w, ty))
        kinds = {"month": 0, "year": 1, "episode": 2}
        nb = sorted(((self.nodes[j], w, self.G["types"][ty]) for j, w, ty in self._adj[i] if self.nodes[j]["k"] in kinds),
                    key=lambda x: (kinds[x[0]["k"]] if self.nodes[i]["k"] != "year" else -kinds[x[0]["k"]], -x[1], x[0]["id"]))
        rel = [{"id": n["id"], "name": n["n"], "kind": n["k"], "type": typ, "text": n["t"], "ret_next": n.get("ret_next")} for n, w, typ in nb[:12]]
        n = self.nodes[i]
        return {"id": nid, "name": n["n"], "kind": n["k"], "text": n["t"], "related": rel}

    def think(self, text: str) -> dict:
        h = None if re.match(RX_WHATIF, text.strip(), re.I) else self.history(text)
        if h:
            res = {"query": text, "found": False, "mode": "history", "history": h, "note": ""}
        else:
            res = self._think_all(text)
        b = self.bonds(text)
        if b:
            res["bonds"] = b
        d = self.decision(text)
        if d:
            res["engine"] = d
        return res

    def _think_all(self, text: str) -> dict:
        t = text.strip()
        m = re.match(RX_WHATIF, t, re.I)
        if m:
            body = m.group(1)
            low = body.lower()
            cuts = [low.find(sp) for sp in WHATIF_SPLIT if low.find(sp) > 0]
            cut = min(cuts) if cuts else -1
            cond = body[:cut] if cut > 0 else body
            rest = re.sub(r"^[\s,]*(?:then\s+)?", "", body[cut:], flags=re.I).strip() if cut > 0 else ""
            to_book = bool(rest) and re.search(RX_BOOK, rest, re.I) is not None
            res = self._think(rest if rest and not to_book else cond)
            res["whatif"] = self.whatif(cond, "book" if to_book else (res if rest else None))
            if res.get("found"):
                res["mode"] = "whatif"
            return res
        res = self._think(t)
        if res.get("found") and re.match(RX_EXPLAIN, t, re.I):
            res["mode"] = "explain"
            pick = next((s for s in res["seeds"] if s["kind"] not in ("fact", "paper", "signal", "quote")), res["seeds"][0])
            n = self.nodes[self.idx[pick["id"]]]
            res["define"] = {"id": n["id"], "name": n["n"], "text": n["t"], "formula": n.get("f"), "kind": n["k"]}
        return res

    def _think(self, text: str) -> dict:
        seeds = self.recall(text)
        if not seeds:
            return {"query": text, "found": False, "note": "Nothing in the mind matches. Name an asset, an indicator, a market or an idea."}
        r = self.spread(seeds)
        rmax = max(r)
        topic = None
        pol = {"side": "neither", "score": 0, "question": True}
        if self.lib is not None:
            vs = self.lib.search(text)
            topic = vs.get("topic")
            pol = vs["polarity"]
        axes = self.G["axes"]
        ranked, score = self.frame(r, topic)
        if not ranked:
            return {"query": text, "found": False, "note": "The question lit up nodes with no evidence attached."}
        main = ranked[0]
        mode = "weigh" if score[main] >= EXPLAIN_RATIO * rmax else "explain"
        verdicts = [self.weigh(a, r, text) for a in ranked[:3]]
        V = verdicts[0]
        side = pol["side"] if pol["side"] in ("bull", "bear") else "bull"
        claim = axes[main][side]
        p_claim = V["p_bull"] if side == "bull" else 1 - V["p_bull"]
        lo, hi = (V["lo"], V["hi"]) if side == "bull" else (1 - V["hi"], 1 - V["lo"])
        pros = [x for x in V["rows"] if (x["c"] > 0) == (side == "bull") and x["c"] != 0]
        cons = [x for x in V["rows"] if (x["c"] > 0) != (side == "bull") and x["c"] != 0]
        used = {x["sig"]["id"] for x in V["rows"]}
        lit = sorted(range(self.N), key=lambda i: (-r[i], i))
        concepts = [i for i in lit if self.nodes[i]["k"] == "concept"][:8]
        facts = [i for i in lit if self.nodes[i]["k"] in ("fact", "paper")][:6]
        engines = [i for i in lit if self.nodes[i]["k"] in ("engine", "method", "tool")][:5]
        countries = [i for i in lit if self.nodes[i]["k"] == "country"][:3]
        cited = set()
        for x in V["rows"]:
            cited.update(x["sig"]["refs"] + x["sig"]["targets"])
        unknown = [self.nodes[i]["id"] for i in concepts if self.nodes[i]["id"] not in cited][:4]
        book = axes[main]["book"]
        tilt = book * (V["p_bull"] - 0.5) * 2
        if book == 0 or abs(tilt) < 0.15:
            act = {"action": "hold", "text": "Hold. The evidence on this claim is balanced or does not touch the book; no change, and look again when the hinge moves."}
        elif tilt > 0:
            act = {"action": "hold", "text": "Hold the book. The evidence leans the way the book is already positioned; do not add, because the position is already concentrated."}
        else:
            h = axes[main]["hedge"]
            act = {"action": "review_hedge", "hedge": h, "text": f"Review protection: the evidence leans against the book on this claim. The hedge book's {HEDGE_NAMES.get(h, h)} is the matching hedge; size it there and write a proposal for a person to approve.",
                   "mcp": [{"tool": "hedge_book", "args": {"on": [h]}}, {"tool": "create_order_proposal", "args": {"rationale": claim, "kill": V["hinge"]["text"] if V["hinge"] else ""}}]}
        act["executed"] = False

        def nd(i):
            n = self.nodes[i]
            return {"id": n["id"], "name": n["n"], "kind": n["k"], "act": round(r[i] / rmax, 6)}

        def row(x):
            s = x["sig"]
            return {"id": s["id"], "text": s["text"], "c": round(x["c"], 6), "relevance": round(x["relevance"], 6), "rel": s["rel"], "group": s["group"],
                    "refs": s["refs"], "flip": s["flip"]}
        return {"query": text, "found": True, "mode": mode, "axis_score": round(score[main] / rmax, 6), "seeds": [nd(i) for i, _ in seeds], "polarity": pol, "topic": topic,
                "axis": main, "axis_title": axes[main]["title"], "side": side, "claim": claim, "p": round(p_claim, 6), "range": [round(lo, 6), round(hi, 6)],
                "logodds": round(V["logodds"], 6), "pros": [row(x) for x in pros[:6]], "cons": [row(x) for x in cons[:6]], "n_signals": len(V["rows"]), "groups": V["groups"],
                "hinge": V["hinge"], "flip": [x["sig"]["flip"] for x in (pros[:3])], "others": [{"axis": v["axis"], "title": axes[v["axis"]]["title"], "p_bull": round(v["p_bull"], 6),
                                                                                                 "n": len(v["rows"])} for v in verdicts[1:]],
                "concepts": [nd(i) for i in concepts], "facts": [nd(i) for i in facts], "engines": [nd(i) for i in engines], "countries": [nd(i) for i in countries],
                "unknowns": unknown, "chains": self.chains(r, prefer=[self.idx[c] for x in V["rows"] for c in x["sig"]["refs"] + x["sig"]["targets"] if c.startswith("a:") and c in self.idx][:3]), "decision": act, "used": sorted(used),
                "trace": [{"step": "read", "out": len(voices.tokens(text))}, {"step": "recall", "out": len(seeds)},
                          {"step": "spread", "out": sum(1 for x in r if x > 1e-4)}, {"step": "frame", "out": len(score)},
                          {"step": "weigh", "out": len(V["rows"])}, {"step": "test", "out": len({x['sig']['group'] for x in V['rows']})},
                          {"step": "trace", "out": 0}, {"step": "decide", "out": 1}]}


def stats(G: dict) -> dict:
    from collections import Counter
    return {"nodes": len(G["nodes"]), "edges": len(G["edges"]), "causal": len(G["causal"]), "signals": len(G["signals"]),
            "kinds": dict(Counter(n["k"] for n in G["nodes"])), "groups": dict(Counter(n["g"] for n in G["nodes"]))}


def compact(G: dict) -> dict:
    """The page's copy: short keys, no layout precision beyond 4 decimals."""
    keep = ("f", "st", "value", "unit", "as_of", "source_url", "source_title", "publisher", "primary", "verification", "authors", "checked", "lines", "axis", "sign", "gdp",
            "feed_url", "edge", "biases", "cadence", "cost", "speaker", "verdict", "ret_next", "start", "end", "dd", "desk", "duration")
    nodes = []
    for n in G["nodes"]:
        d = {"id": n["id"], "k": n["k"], "n": n["n"], "g": n["g"], "t": n["t"], "a": n["a"], "x": n.get("x", 0), "y": n.get("y", 0)}
        for k in keep:
            if n.get(k) is not None:
                d[k] = n[k]
        nodes.append(d)
    return {"nodes": nodes, "edges": G["edges"], "causal": G["causal"], "signals": G["signals"], "axes": G["axes"], "types": G["types"],
            "groups": G["groups"], "params": G["params"], "net": G["net"], **({"bonds": G["bonds"]} if G.get("bonds") else {}),
            **({"decision": G["decision"]} if G.get("decision") else {})}


def build_from_dir(out: Path | str) -> dict:
    """The daily run's mind: the atlas and labs from the data folder when they exist, else the shipped atlas and no labs
    signals; knowledge, voices and the world from the assets."""
    out = Path(out)
    atlas = json.loads((out / "atlas.json").read_text()) if (out / "atlas.json").exists() else json.loads((ASSETS / "atlas.json").read_text())
    L = json.loads((out / "labs.json").read_text()) if (out / "labs.json").exists() else None
    rl = None
    if (out / "research.json").exists():
        try:
            rl = json.loads((out / "research.json").read_text()).get("hedge", {}).get("latest")
        except (ValueError, AttributeError):
            rl = None
    rd = lambda n: json.loads((out / n).read_text()) if (out / n).exists() else None
    tech = {k.lower(): v for k, v in ((rd("technicals.json") or {}).get("assets") or {}).items()}
    G = build(atlas, voices.load(), load_knowledge(), load_countries(), L, rl, mlo=rd("ml.json"), aso=rd("reality.json"), positions=load_positions(),
              companies=load_companies(), rlo=rd("rl.json"), tech=tech)
    return compact(G)

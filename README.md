# Buildout

Regime-aware risk, hedge and sizing engine for a concentrated AI-buildout equity book
(hyperscalers, NVDA/AVGO, TSLA, SPCX) with long Treasuries as the candidate hedge.

Version 0.14 makes the brain and the engine one mind, an order of magnitude larger, and gives it a reasoning loop.
`mind.py` joins, in one typed graph of about 1,500 nodes and 3,800 links: 547 concepts with definitions, formulas and
relations (`ontology.py`), the atlas's 100 market nodes and their learned causal links, 268 facts and papers checked
twice on their sources (`assets/knowledge.json`), 267 verified quotes from 60 investors, every Python module with its
imports as links, the lab methods and the MCP tools, 48 economies with their currencies and exports, and 107 signals
(evidence with a direction, a strength and a reliability). Asked a question, it recalls by BM25 and exact names,
spreads activation by personalized PageRank, frames the claim, weighs the evidence in log-odds with a family discount,
gives a leave-one-family-out range and the hinge, traces causal chains to the book over the atlas's links and proposes
an action it never executes; the page runs the same code (`site/src/mind.js`), held equal by tests. `labs.py` tests
trading claims on 156 years (the 10-month and 200-day rule with a bootstrap, a max test and a deflated Sharpe,
corrected for monthly averaging; RSI, MACD, Bollinger, golden cross; CAPE and P/E out of sample; Markov regimes;
GARCH; cointegration; variance ratios; Sell in May; Holm and Benjamini-Hochberg). `games2.py` holds the card room's
exact math: a seven-card evaluator and seeded equity, pot odds, Kelly and ruin, Rubinstein and Nash bargaining, the
best haggling ask, IRR, TVPI, PME, the Takahashi-Alexander J-curve and the theory of storage. The page adds the Mind,
Labs, Card room, Under the hood (the engine's source) and Agents desks, and 31 plain-English hard questions.

Version 0.13 grows the brain by an order of magnitude in what it measures. `atlas.py` reads every monthly series it can
reach (the GitHub mirrors of the public datasets everywhere; FRED as well in the daily Action), learns the structure
with the graphical lasso (extended BIC) and stability selection (with a bound on false links), orients each link by
its non-Gaussian signature (pairwise LiNGAM), fits a structural VAR pruned by its own t-statistics, and computes
impulse responses, Diebold-Yilmaz connectedness (and a rolling index), communities, PageRank and total effects, regime
flips and an out-of-sample test. The core map's judged concepts and holdings join it, so one brain carries both: 100
nodes in the snapshot (72 series), about 130 in the daily run. The landing page shows the whole brain month by month;
the Atlas desk explores it.

Version 0.12 put the brain on the landing page and made it check itself. The landing desk animates a shock
travelling the 35-node graph one order at a time, x_k = W'x_(k-1), with the arithmetic beside it: the largest flows of
each step, the running sum converging on the Leontief limit at the rate of the spectral radius, and 300 Monte Carlo
worlds. `brain_robust.py` scores five rival world models for every measured equation out of sample from 2000, stacks
them (Yao, Vehtari, Simpson and Gelman 2018), puts adaptive conformal error bars on the result (Gibbs and Candes 2021),
and gives each measured link its robustness value to an unseen common cause (Cinelli and Hazlett 2020). `voices.py`
answers a question or claim with verbatim, dated, sourced quotes from legendary and current investors, arranged from
extreme bear to extreme bull; the page runs the same retrieval, held equal by tests, and never writes a quote.

Version 0.11 made the engine decide, and the page its harness. `ooda.py` runs Observe, Orient, Decide, Act into one
record (`ooda.json`): what moved and which world it fits; the explanations and what each asset did in stocks' worst
months; the solver with and without doubt; a hedge book of nine prebuilt hedges you can switch on or off, with an
advisor that enumerates every combination (`hedgebook.py`); an action per position run through outside view, inside
view, pre-mortem, margin of safety, reversibility and kill criteria; and proposals with a date to look again.
`valuation.py` reads each price as a requirement: accounting quality, the 10-year growth a reverse DCF needs, and how
often companies of that size ever achieved it (the Base Rate Book), with the case the price is right and wrong in
points of required growth. `causal_stats.py` adds Granger tests, partial correlations, tail dependence and crisis
behaviour. `engine.py` registers every engine and runs the offline ones into `engines.json` with input and output
hashes; the page's Engine room renders it.

Version 0.10 made the engine robust. Every measured link is re-estimated with Huber regression and Newey-West
errors, with each month's exact influence and the number of the most influential months whose removal reverses its
sign (`robust.py`): the 2022-on 10-year-to-stocks link the hedge rests on reverses on three. The solver gains a
distributionally robust mode, the best worst case over every set of scenario odds within a KL radius, with the price
of that protection (`reasoner.solve_robust`). Each book run adds block-bootstrapped intervals, the probability of
backtest overfitting across 30 neighbouring hedge rules, a plateau check on the chosen thresholds
(`analytics/robust_bt.py`), and a price screen for bad prints, frozen feeds and gaps (`data/quality.py`).

Version 0.9 made the brain check itself and answer questions. It asks which world the readings come from (Bayesian
model comparison across the two regimes), how surprised it should be (Mahalanobis distance, exact leave-one-out),
what would have happened otherwise (counterfactuals that keep today's evidence, and but-for shares that add up), which
channels carry each cause to the book (every walk, summing exactly), and how a bad quarter most plausibly happens
(reverse stress on the graph). It also learns from the data instead of assuming: DirectLiNGAM tests the causal order
(`discovery.py`) and a Kalman smoother tracks every measured link month by month. On today's data both say the 2022
stock-bond break may be fading. "Ask the brain" lets Claude answer questions in words using only numbers from the
page's own functions, each call listed.

Version 0.8 answered the fifth project review and made the brain think. The brain now reasons from what moved to
why (`thinking.py`): abduction finds the root shocks that best explain every reading at once, single-cause
explanations are ranked by exact Bayesian evidence against "noise only", predictions carry standard deviations,
criticism names the reading the map cannot explain and the link most to blame, the next observation is the one with
the most mutual information, and doing (cut the node's causes) is kept apart from seeing. It has 34 parts and about
110 links, down to each holding and the book. A Field desk (`field.py`) turns anecdotes into dated, sourced
observations on three clocks, compares competing explanations and ranks the evidence that separates them, registers
ten unusual indicators before testing them, and watches expected events without reading silence as news. Today shows
what each headline read before, and says so when nothing moved. The engine is also an MCP server
(`mcp_server.py`): sixteen research and proposal tools for any assistant, none of which can place an order. Without
Databento's paid adjustment factors, the book run falls back to a public split table and estimated bond-fund income.

Version 0.7 answered the third project review. It fixes the accounting (one NAV and return convention, costs in
the first return, Sharpe over accrued cash, next-session fills, every variant on the same dates beside a cash-only
baseline), puts every decision under a versioned policy shared by the recommendation and the backtest
(`policy.py`), makes the hedge line earn its place out of sample or come back as "no reliable threshold", builds
one effective fundamentals dataset, and adds an engine that reasons: tempered Bayes over seven scenarios, a
constrained growth search, a zero-sum game against Nature, value of information and reverse stress
(`reasoner.py`), and game theory for the capex race, crowded exits, informed trading and prediction-market
ladders (`games.py`). The page leads with "How reliable is your bond hedge in this regime?" and labels every
number Observed, Estimated, Assumed, Historical pattern, Hypothesis or Unavailable.

Version 0.6 added the brain (a signed network of the financial system that carries any shock or assumption to
its fourth-order effects, with eleven links measured in two regimes), Noteworthy (an asymmetric-information feed
scraper over Substack, Telegram, X, Reddit, Hacker News and the wires), prop trading and market making desks, and
the 2026 buyside field manual as engine modules. Version 0.5 added the decision layer: every reading becomes a
written rule, a sized action, a confidence and a distance to a flip, and every decision can be logged and scored.

It answers three questions every day, with the data behind each answer:

1. **How big?** Volatility targeting and a drawdown-constrained leverage cap set the size. Fractional Kelly
   is the edge check: it reports the excess return you would need to believe to justify that size.
2. **How much hedge?** Minimum-variance hedge ratios, judged out of sample, gated by regime.
3. **When does the hedge stop working?** The stock-bond correlation regime, and what long bonds actually
   did on the book's worst days in each regime.

## Daily run (GitHub Actions)

`.github/workflows/daily.yml` runs at 11:17 UTC, Tuesday to Saturday, so each run sees the prior US
session's close. It can also be started by hand from the Actions tab (Run workflow).

| Step | Needs | Writes |
|---|---|---|
| Tests | nothing | |
| Market regime: Nasdaq-100 vs the long Treasury | nothing (FRED is free) | `site/data/macro.json` |
| Book run: exposures, regime, hedge, sizing, stress, backtest | secret `DATABENTO_API_KEY` | `site/data/report.json` |
| Fundamentals: capex, cash flow, debt from SEC filings; last-twelve-month analysis and Minsky stages | variable `SEC_USER_AGENT` | `site/data/capex.json` |
| Long-history research: 155 years of public data (Shiller, BLS, Treasury, EIA, CBOE, gold) | nothing | `site/data/research.json` |
| Brain links by regime; the field manual's regime, hedge selector, fat tails and replays | nothing | `brain.json`, `buyside.json` |
| Noteworthy feeds: RSS and Substack, Telegram previews, Reddit, Hacker News, Google News; X with a token | optional secret `X_BEARER_TOKEN` | `feeds.json`, `feeds_history.json` |
| Source registry | nothing | `sources.json` |
| Status: which files exist, how fresh each is, sanity checks (always runs, even after a failure) | nothing | `site/data/status.json` |

Steps without their secret or variable skip themselves with a notice. Results are committed back to `main`
by `github-actions[bot]`. Only derived analytics are committed; raw market data never enters git.

### One-time setup

1. **Databento key.** Settings > Secrets and variables > Actions > New repository secret:
   name `DATABENTO_API_KEY`, value `db-...`. The next run prices the pull (`buildout cost`), refuses it above
   `max_cost_usd` in `config.toml` ($5 by default), and then runs the book. Split and dividend adjustment factors
   are Databento reference data, sold as a separate plan. With `adjustments = "auto"` (the default) the run uses
   them when the account has them and otherwise falls back to the public split table in
   `buildout/data/corporate_actions.py`, with TLT and IEF income estimated from Treasury yields and stock dividends
   left out. The report and the page say which applied. A split missing from the table stops the run by name:
   add the row on the ex-date (Meta announced a 2-for-1 through Class C shares on Oct 21, 2026; dates pending).
2. **X (optional).** Secret `X_BEARER_TOKEN` (X API v2) adds the X accounts in `feeds.toml` to Noteworthy.
   Without it they are skipped with a note; X is never scraped.
3. **SEC contact (optional).** Same page, Variables tab: `SEC_USER_AGENT` = `Your Name you@example.com`.
   The SEC requires a real contact on every request.
4. **Public page (optional).** Check the ICE BofA license before redistributing the credit spreads. Make the repository public, set Settings > Pages > Source to
   "GitHub Actions", and add the variable `PUBLISH_PAGES` = `true`. `pages.yml` then redeploys the page
   after every daily run.

## The page

`site/page.html` is one self-contained page with twenty-three desks in seven sections (Today, Decide, Markets,
Trading, Research, Wisdom, Reference). Market figures carry a source and a date;
tiles marked Live are replaced by the daily run's numbers, and a Stale badge appears when a file is more
than three weekdays old. The bond, curve, option, hedge and sizing tools run in the browser with the same
formulas as the engine (`analytics/bonds.py`, `curve.py`, `options.py`), checked against it to 1e-9.

| Desk | What it holds |
|---|---|
| Today | Risk rings, what changed since your last visit, a morning check-in with a streak, early trends, a three-line brief (do, risk, watch), twelve signals each with a rule and an action, the system map (nine parts of the financial system and the channels between them, red where stress is flowing), what moved, key levels, regime map, engine readout, calendar |
| Noteworthy | Ten trends placed on the curve from niche to consensus, each with a bottom line, sourced numbers, a watch list and live links to X, Substack and Telegram; the feed's latest items; heat, niche skew and lead time per theme |
| The brain | Thirty-four parts and about 110 signed links (eleven measured by regime, the rest judged and editable): propagation by order, strongest channels, feedback loops, the links the answer rests on, Monte Carlo robustness, the spectral radius, the inverse problem, PM and quant modes |
| Prop | Industry economics (Jane Street, Citadel Securities, Virtu, retail challenges), the edge calculator and Kelly hill, a funded-challenge simulator, pod-shop economics from gross to net |
| Market making | Market structure in 2026, an Avellaneda-Stoikov simulator, Glosten-Milgrom adverse selection, square-root impact with Almgren-Chriss schedules and the execution frontier, the book's own liquidity |
| Buyside 2026 | The field manual as tools: regime and gross, the hedge selector, Student-t shortfall, five replays, server-life depreciation, cash earnings, reverse DCF, red flags, private credit stress, position tiers and the moonbag rule, the manual's ten signals, and where the manual and the data disagree |
| Decide | Seven decisions traced from data to rule to action, each with a confidence (the product of its assumptions) and the distance to a flip; rates of change (velocity, acceleration, time to each rule's line) for eleven signals; fifteen weighted assumptions with sliders; known knowns to unknown unknowns; five shocks run to the fourth order |
| Journal | A private decision tracker: hypothesis, evidence, weighted assumptions, kill line, pre-mortem, Kelly sizing; the forecast locks when logged; after-action reviews; Brier score, calibration, alpha after beta, a luck test and a process-against-outcome grid |
| Swans | Fat tails since 1871, twelve named swans with the hedge that pays and the one that fails, Taleb's toolkit as rules, Spitznagel's compound-growth test |
| Fundamentals | From 10-K and 10-Q facts: last-twelve-month capex against cash flow, Minsky stages, paper profits, the depreciation wave (fitted to reported depreciation), backlog and leases, every server-life change |
| Physics | Capex in gigawatts, terawatt-hours and homes; data-center demand; PJM capacity prices; booms as a share of GDP; Perez's cycle; megaproject base rates |
| Findings | Eight original results on 155 years of data, each with method, caveat and the rule it changes |
| Legends | Twenty lenses (Druckenmiller, Buffett, Munger, Griffin, Dalio, Soros, Marks, Simons, Thorp, Taleb, Spitznagel, Minsky, Keynes and more), each read against today's data, and what most desks skip |
| Math lab | Seven toys: the ergodicity coin game, the Kelly hill, volatility drag, conjunction, Bayes, luck against skill, diversification |
| Rates | 2026 Treasury curves, spreads, forward curve with one-year carry and roll-down, real yield vs breakeven, bond calculator, DV01-neutral curve trade |
| Options | Black-Scholes pricer with Greeks and an implied-volatility solver, hedge payoff builder, spot-vol revaluation grid, tail-hedge budget |
| Hedges | Fifteen hedges graded across six scenarios, six scenario playbooks, the two kinds of AI selloff, TLT hedge lab, futures hedge calculator (NQ/MNQ against ZN/TN/ZB/UB), Monte Carlo sizing lab |
| Securities | Capital structure, seven risk drivers, thirty security cards |
| Insurers | Float and duration matching, the Hyperion financing chain, private credit exposure, six balance sheets |
| Theses | Eight theses with evidence, expression, hedge, kill criteria and the strongest case against each; live SEC capex vs cash flow |
| Lenses | Taleb, Dalio, Marks, Druckenmiller, Soros, Burry, Buffett and Munger, BowTiedBull, Kobeissi, Six Sigma, Walters |
| Engine | Pipeline, system status from the daily run, self-tests, model book, data plan, roadmap |
| Appendix | Glossary (126 terms, linked from the text), methods and formulas, 48 hard questions, model risk register, data dictionary, episode atlas (15 stresses since 1987), reading list, checklists, changelog |

Navigation: `/` or Ctrl/Cmd+K searches every desk, term, security, thesis, episode and question; `?` lists
the shortcuts; digits 1 to 7 open the sections (each reopens the desk last read in it); M shows every formula;
any element id is a deep link (`#g-dv01`, `#d-duration`, `#fi-hedge`, `#sw-credit`). Print all (Appendix)
prints every desk with every question answered (outside the artifact viewer, which cannot print).

The journal stores entries in the viewer's private space when the page runs as a published artifact
(`db` and `user` capabilities: nobody else can read them, the owner included), in browser storage
anywhere else, and exports JSON that `python -m buildout journal decisions.json` scores.

### Editing the page

The page is assembled from `site/src/` (`head.html`, `body.html`, and `math.js`, `ui.js`, `data.js`,
`reference.js`, `research.js`, `views.js`, `decide.js`, `journal.js`, `desks.js`, `wisdom.js`, `lab.js`,
`snap6.js`, `brain.js`, `noteworthy.js`, `trading.js`, `buyside6.js`, `pulse.js`, `boot.js` inside one strict-mode script). Edit the parts, then:

```bash
python scripts/assemble_page.py           # writes site/page.html; --check fails CI if it is stale
python site/tests/stress.py               # browser suite (needs: pip install playwright; playwright install chromium)
python scripts/snapshot_fundamentals.py   # regenerate the Fundamentals snapshot from the SEC facts in tests/fixtures
python scripts/snapshot_v06.py <dir>      # regenerate snap6.js from brain, buyside and sources output in <dir>
```

The browser suite builds the site from engine-generated fixtures and feeds it hostile files (wrong shapes,
truncated JSON, stale dates, absurd yields), extreme tool inputs, keyboard-only use, deep links, the journal
end to end (log, lock, unlock, close, score, export, import hostile files, delete, reload), live research,
320 to 1920px widths and print. It fails on any script error, any NaN, undefined, Infinity or null on screen,
any duplicate id, any sideways scroll, any panel that did not render, and (with poppler's `pdftotext`) any
text printed over text. With `AXE_JS` pointing at axe-core's `axe.min.js` it also fails on any serious or
critical accessibility violation.

## Local use

```bash
pip install -e ".[databento,dev]"
pytest                                    # 253 tests, no data needed
python -m buildout demo                   # full run on a synthetic market with planted answers
python -m buildout macro --out out        # free FRED regime monitor

export DATABENTO_API_KEY=db-...           # never commit it
python -m buildout cost --config config.toml   # price the pull before paying for it
python -m buildout run  --config config.toml --out out
python -m buildout capex GOOGL MSFT AMZN META ORCL TSLA --ua "Your Name you@example.com"
python -m buildout research --out out     # 155 years of public data: the hedge line, fat tails, base rates
python -m buildout journal decisions.json # score an exported journal: Brier, calibration, alpha, luck
python -m buildout brain --out out        # measured links between oil, CPI, yields, stocks, VIX and gold, by regime
python -m buildout reason --out out       # tempered Bayes, the constrained choice, the game against Nature, value of information, games
python -m buildout buyside --out out      # regime and gross, hedge selector, Student-t shortfall, replays
python -m buildout feeds --out out        # Noteworthy: reads feeds.toml (add any Substack, Telegram channel or RSS)
python -m buildout sources --out out      # every source the engine reads
python -m buildout kalshi KXFED           # prediction-market Fed path (series names change; check Kalshi)
python -m buildout mcp --data out         # MCP server on stdio (see below)
python -m buildout engine --out out       # the offline engines (valuation, causal, hedges, decision loop) and engines.json
python -m buildout engine --list          # the registry
python scripts/snapshot_v11.py            # refresh the page's engine snapshot (decision loop, valuation, causal)
python scripts/snapshot_v12.py            # refresh the brain's self-checks and the voices library in the page
python -m buildout atlas --out out        # the atlas: every series, learned structure (FRED and GitHub mirrors)
python -m buildout labs --out out         # the labs: trend rules, oscillators, valuation, regimes, GARCH, spreads, calendar
python -m buildout mind --out out         # the mind: one graph of the brain and the engine
python -m buildout think "Is AI a bubble?" # ask the mind from the command line
python scripts/snapshot_v13.py            # refresh the page's atlas snapshot
python scripts/snapshot_v14.py            # refresh the labs, the mind and the code appendix in the page
python scripts/build_knowledge.py K V     # merge research items (K) with the checkers' verdicts (V) into knowledge.json
python scripts/export_graph.py            # after editing the brain or field cases on the page (needs node)
python scripts/snapshot_v09.py path/to/csvs  # refresh the page's monthly series for structure learning
```

`config.toml` is the model book the page shows. Keep real positions in `config.private.toml` (git-ignored)
and run with `--config config.private.toml`.

## MCP server

`python -m buildout mcp --data out` (or `python -m buildout.mcp_server`) speaks the Model Context Protocol over stdio,
standard library only. Register it with any MCP client, for example:

```bash
pip install -e .                                   # once, so the module resolves from any folder
claude mcp add buildout -- /path/to/venv/bin/python -m buildout mcp --data /path/to/buildout/site/data   # Claude Code
```

Claude Desktop: add to `claude_desktop_config.json` (absolute paths; the app does not start in the repo):

```json
{"mcpServers": {"buildout": {"command": "/path/to/venv/bin/python", "args": ["-m", "buildout", "mcp", "--data", "/path/to/buildout/site/data"]}}}
```

| Tool | Answers |
|---|---|
| `get_research_snapshot` | The out-of-sample hedge line and band, the stock-bond regime, data checks, scenario probabilities, brain readings, with dates |
| `get_portfolio_risk` | The model book, its limits, the engine's risk summary, which holdings are the same bet, the book's sensitivity to each root cause |
| `analyze_positions` | YOUR holdings, passed in for one call (for example from Robinhood's MCP): weights, limit checks, same-bet pairs, root-cause sensitivity, gap to the model book. Nothing stored |
| `decision_loop` | The engine's whole decision record: observe, orient, decide, act |
| `position_valuation` | One holding's accounting, implied growth against the base rates, and the two-sided why; override price or beta |
| `hedge_book` | Switch prebuilt hedges on or off at chosen sizes: the book in every scenario, cost, and the advisor |
| `reason` | Ask the mind: the claim it weighed, the probability and its range, evidence for and against with sources, the hinge, chains to the book, a proposed action (never executed) |
| `labs_lookup` | The labs' tested trading claims, by part |
| `game_math` | Poker equity and pot odds, Kelly, ruin, bargaining, the best haggling ask, IRR, multiples, PME, the J-curve, the convenience yield |
| `investor_voices` | Verbatim, sourced quotes on a question, extreme bear to extreme bull; never generates a quote |
| `atlas_trace` | The whole brain: trace any shock month by month to any node, or read a node's links, importance and regime changes |
| `brain_selfcheck` | Conformal coverage, stacking weights and robustness values: how far to trust the brain |
| `run_hedge_scenario` | hedge.tlt.v2 on any correlation path and inflation reading, every gate visible |
| `evaluate_trade` | A portfolio on the seven scenarios: growth, worst case, loss limit, regret, the best portfolio on the grid; with `ambiguity`, its worst case over doubtful odds and the robust choice |
| `create_order_proposal` | A hashed proposal checked against gross, single-name and universe limits. Never executed |
| `review_decision` | Process score and luck quadrant for one decision, or the full journal scorecard |
| `compare_explanations` | Bayes over competing explanations and the evidence worth checking next, in bits |
| `trace_exposure` | The brain's reasoning: causes, implications for each holding, the link most to blame, what to observe next, doing vs seeing, which world fits, surprise, but-for shares, channels, a bad-quarter story, counterfactuals |
| `learned_structure` | The causal order learned from the data against the assumed one, each measured link's path over time, and how fragile each link is |

Every tool is read-only research or a proposal. The server refuses `config.private.toml`, never reads a brokerage
account and has no order, routing or cancel tool; tests check all three. It reasons on `buildout/assets/brain_graph.json`,
exported from the page by `scripts/export_graph.py`; a test fails if the export and the page drift apart.

**With Robinhood.** Add Robinhood's official MCP (`https://agent.robinhood.com/mcp/trading`) to the same Claude
client. Claude reads your holdings there, passes them to `analyze_positions` and `evaluate_trade` here, and drafts a
proposal; any order goes through Robinhood's dedicated Agentic account with trade approvals on. Buildout never sees
credentials, and the holdings it is shown are not stored.

## Data

| Source | What | Cost |
|---|---|---|
| Databento | Daily (and minute) bars for equities and ETFs, CME Treasury futures (ZN, UB); split and dividend adjustment factors if the plan includes reference data (else the free fallback) | Pay-as-you-go historical; reference data is a separate plan |
| FRED | Nasdaq-100, the Treasury curve from 1 month to 30 years, TIPS real yields, breakevens, term premium, IG, HY and CCC spreads, VIX and VXN, broad dollar, Brent and WTI, the Fed's balance sheet and repo rates, CPI, unemployment, Sahm, NFCI, claims | Free |
| SEC EDGAR | Revenue, operating cash flow, capex, leases, depreciation, operating and non-operating income, interest, debt, cash and backlog from XBRL filings | Free (contact required) |
| GitHub datasets | Shiller's S&P 500 since 1871, BLS CPI-U, the 10-year Treasury, EIA Brent, CBOE VIX, monthly gold | Free |
| Kalshi | Prediction-market probabilities (Fed path, CPI, recession) | Free public endpoints |
| Feeds | Substack and RSS, Telegram public previews, X API v2, Reddit, Hacker News, Google News (`feeds.toml`) | Free; X needs an API token |

91 sources in all (`python -m buildout sources`).

## Modules

| Layer | Module | Does |
|---|---|---|
| Data | `data/databento_source.py` | Adjusted closes (applied, default-option, primary-listing factors); roll-adjusted futures returns; explicit end dates |
| | `data/fred_source.py`, `edgar_source.py`, `kalshi_source.py` | Macro, fundamentals (YTD facts de-cumulated to quarters), prediction markets |
| | `data/synthetic.py` | Regime-switching market with known betas and regimes, for testing |
| Monitor | `macro.py` | Free daily regime read: Nasdaq-100 vs a 20-year par bond rebuilt from DGS20, back to 1993; curves, spreads, levels; episode atlas; per-series failures reported, not fatal |
| | `status.py` | Run status: files present, valid and fresh; sanity checks on correlations, hedge ratios, yields, gross and VaR |
| | `marketstate.py`, `roc.py` | What moved, insurance and liquidity reads; inflation against the hedge line; velocity, acceleration and time to trigger |
| Decisions | `decisions.py` | Kelly (bets and positions), Brier, calibration, binomial luck test, alpha after beta, conjunction, Bayes, the compound-growth hedge test, journal scorecard |
| Research | `research.py`, `fundamentals.py` | 155 years of public data (hedge line, fat tails, earnings rate of change, oil shocks, VIX spikes, inflation spells, gold, CAPE); last-twelve-month SEC analysis, Minsky stages, depreciation vintages |
| v0.14 | `mind.py` | One graph of the brain and the engine; recall (BM25, aliases), spreading activation (personalized PageRank), claim framing, log-odds weighing with a family discount, leave-one-family-out range, hinge, causal chains, decision |
| | `ontology.py` | 547 concepts in 18 clusters with definitions, formulas, aliases and typed relations to concepts, series, engine modules and voices topics |
| | `labs.py` | Indicators (SMA, EMA, RSI, MACD, Bollinger), the trend lab, oscillator tests, valuation out of sample, Markov switching, GARCH, Hill tails, Engle-Granger, variance ratios, calendar, Holm and BH |
| | `games2.py` | Seven-card evaluator, seeded equity, pot odds, Kelly, risk of ruin, Rubinstein, Nash, best offer, IRR, multiples, PME, Takahashi-Alexander, cost of carry |
| v0.13 | `atlas.py` | Every monthly series: graphical lasso with EBIC, stability selection, pairwise LiNGAM, pruned structural VAR, connectedness, communities, layout |
| v0.12 | `brain_robust.py` | Five rival world models per equation scored one step ahead from 2000, stacking, adaptive conformal intervals, robustness values |
| | `voices.py` | Verified investor quotes (assets/voices.json), BM25 retrieval with concepts and synonyms, the bear-to-bull spectrum, polarity |
| v0.11 | `valuation.py` | Accounting quality (core earnings, cash conversion, accruals, stock pay, steady-state FCF, depreciation catch-up, leverage, returns), reverse DCF implied growth, Base Rate Book probabilities, verdicts, two-sided why |
| | `hedgebook.py` | Nine prebuilt hedges priced and run through the scenarios; exhaustive advisor |
| | `causal_stats.py` | Granger, partial correlations, crisis behaviour, tail dependence, lead-lag by regime |
| | `ooda.py` | The decision loop and the position rules with decision frameworks; `ooda.json` |
| | `engine.py` | Engine registry, isolated runs, manifest with content hashes (`engines.json`) |
| v0.10 | `robust.py` | Huber IRLS, Newey-West HAC, exact leave-one-out influence, verified months-to-flip for every measured link and regime |
| | `reasoner.py` (robust) | KL-ball worst case by its convex dual, robust grid search, doubt sweep, worst-case odds |
| | `analytics/robust_bt.py` | Stationary block bootstrap, paired win rates, CSCV probability of backtest overfitting, rule family, plateau |
| | `data/quality.py` | Bad-print, frozen-feed and gap screen; flags only |
| v0.9 | `thinking.py` (frontier) | Marginal density by Woodbury, regime posterior, surprise and exact leave-one-out, counterfactuals, but-for shares, exact path attribution, loss stories |
| | `discovery.py` | DirectLiNGAM (pairwise likelihood ratio) with seeded bootstrap; Kalman time-varying links with drift by maximum likelihood; sign changes |
| v0.8 | `thinking.py` | The brain's reasoning: total effects within K links, ridge abduction of root shocks with posterior covariance, predictions with sd, residuals and misfit gradients per link, single-cause evidence by Sherman-Morrison, mutual information for the next observation, do-interventions, shared exposure |
| | `field.py` | Discrete Bayes over competing explanations and expected information (bits) of each unchecked piece of evidence |
| | `mcp_server.py` | MCP over stdio: sixteen research and proposal tools; never executes |
| | `data/corporate_actions.py` | Free fallback for Databento's paid adjustment factors: public split table, bond-fund income from Treasury yields |
| v0.7 | `policy.py` | hedge.tlt.v2, size.equity.v2, limits.portfolio.v1: one function each for recommendation, text and backtest; unavailable inputs block, never default; decision snapshot |
| | `reasoner.py` | Tempered Bayes posterior, scenario returns (duration, convexity, Black-Scholes put spreads, financing), exact grid search with a loss limit, alternatives with regret, simplex game against Nature, EVPI and EVSI, reverse stress from measured covariances; `python -m buildout reason` writes reason.json |
| | `games.py` | Nash equilibria (pure and support enumeration), asymmetric Cournot calibrated to filings, the capex dilemma, Morris-Shin crowded exit, Kyle, prediction-ladder coherence and fee-aware arbitrage |
| | `analytics/risk.py`, `research.py` | Effective risk contributors vs effective independent bets, diversification ratio; hedge line chosen in training only, walk-forward, block bootstrap, holdout, null results, the hedge experiment |
| v0.6 | `brain.py` | Recursive regressions on standardized monthly changes by regime; propagation, Leontief total, spectral radius |
| | `buyside.py`, `accounting.py` | Regime label and gross scaler, hedge selector by shortfall per carry, Student-t shortfall, replays; depreciation, cash EPS, reverse DCF, credit stress, red flags |
| | `microstructure.py` | Avellaneda-Stoikov quotes and simulation, Glosten-Milgrom, square-root impact, Almgren-Chriss, Roll, Amihud, Kyle |
| | `feeds.py`, `sources.py` | Feed fetchers and parsers, theme tagging, heat, niche skew, novelty and lead time; the source registry |
| Exposure | `analytics/exposures.py` | Recursive exponentially weighted betas to market, AI and rates factors; IPO shrinkage |
| Regime | `analytics/regime.py` | Stock-bond correlation with hysteresis; worst-day shock table |
| Hedge | `analytics/hedge.py` | Min-variance ratios, four policies judged out of sample, DV01 futures sizing |
| Rates | `analytics/bonds.py`, `curve.py` | Price, yield, duration, convexity; monotone cubic par curve, bootstrap, forwards, carry and roll-down, futures DV01 via CTD and conversion factor |
| Options | `analytics/options.py` | Black-Scholes with dividends, Greeks, implied volatility with no-arbitrage bounds |
| Risk | `analytics/vol.py`, `risk.py` | EWMA, GARCH(1,1), HAR-RV; factor-model covariance, risk shares, historical and filtered-HS VaR |
| Sizing | `analytics/sizing.py` | Vol targeting, shrunk fractional Kelly, equal risk contribution, drawdown-capped leverage, trim bands |
| Stress | `analytics/stress.py` | Historical episodes (2020, 2022, 2024, 2025, 2026) and hypothetical factor shocks |
| Proof | `analytics/backtest.py`, `metrics.py`, `signals.py` | Dollar-exact backtester, deflated Sharpe, purged walk-forward model judged on calibration |
| Page | `site/src/`, `scripts/assemble_page.py`, `scripts/build_site.py` | Twenty-four-desk research site assembled into `site/page.html` (reads `site/data/*.json`); `build_site.py` wraps it for GitHub Pages |

## What the tests prove

- Betas planted in the synthetic market are recovered; a 90-day IPO is shrunk toward its prior.
- The regime detector tracks the planted regimes; the gated hedge beats a static hedge; bonds rally on
  worst days only in the hedging regime. The FRED monitor reads the same planted regimes.
- **Look-ahead canary:** a signal known at today's close earns nothing on a random walk, while a signal that
  peeks one day ahead posts a Sharpe above 10. The backtester cannot hide a timing leak.
- Costs, financing on leverage and compounding are exact to machine precision.
- The forecasting model finds no edge where none exists, and finds an edge that was planted.
- Split factors remove split jumps; futures rolls do not create fake returns; restated SEC filings win.
- The page's bond, curve and option math matches the engine on a grid of inputs (Node evaluates `math.js`).
- Missing FRED series, truncated files and stale data are reported in `status.json`, never fatal.
- A missing month (BLS published no October 2025 CPI) never shortens a window: 12 months stays 12.
- The research recovers an inflation threshold planted in synthetic data, and invents none when none is planted.
- The depreciation model reproduces each company's reported depreciation in its fit year; the Fundamentals
  snapshot on the page is regenerated from the SEC facts and checked number for number.
- Kelly's closed form for a position matches a numerical maximization of log growth.
- The page's rates of change, decision math, journal scorecard, depreciation model and ergodicity game
  match the engine; every link the decision layer draws lands on something.
- The brain recovers planted links and a planted sign flip by regime; the page's propagation matches the engine
  and converges to the Leontief inverse.
- Market-making quotes, impact and Almgren-Chriss schedules match the engine exactly; inventory skew cuts
  inventory risk in simulation; Roll's estimator recovers a planted bid-ask bounce.
- The field manual's depreciation and private-credit tables are reproduced to the rounding shown.
- v0.7 regression cases from the review: 101 flat dates alternating 100% and cash at 2bp end at NAV 0.9799987 and the
  returns say the same; two perfectly correlated 50% positions are 2 effective risk contributors and 1 independent bet.
- The hedge policy agrees in Python and JavaScript at the boundaries (-0.10 enters, 0 stays, 0.01 leaves), through
  the hysteresis and with missing inputs; the backtest series equals the decision day by day.
- A null research result rejects the threshold, prints, and switches the inflation gate to unavailable.
- A newer filing that reverses Oracle's cash coverage updates its row, its coverage label, its date and the capex
  game together.
- The solver's choice, the game against Nature, the value of information and the reverse stress match between
  languages; the zero-sum solver gets matching pennies, rock-paper-scissors and a dominance game exactly; the capex
  game reproduces the textbook 4/9 cost of racing and 9/8 price of anarchy; the crowded exit hits the Laplace limit.
- The calculator is exact against SciPy and refuses what it cannot read.
- v0.8: abduction recovers a planted cause; "noise only" wins when nothing moved; the next observation is the one
  that separates two causes with the same footprint elsewhere; doing and seeing differ upstream of a node; criticism
  blames the link that was planted wrong; Python and the page agree on the page's own graph to 1e-9.
- The field desk's Bayes and information ranking match between languages; evidence equally likely under every story
  is worth zero bits; milestones read upcoming, due, inside the reporting lag and overdue at the right dates.
- v0.14: forty steps of spreading activation sit within 2 x 0.75^40 of the closed-form personalized PageRank; the
  page's mind equals Python's on fifteen questions (seeds, claim, side, probability, range, pros and cons, hinge,
  chains and decision); each family's k-th reading counts 1/sqrt(k); every typed reference in the ontology resolves;
  every signal quotes the checked number it rests on; the hand evaluator ranks every category and pocket aces win
  85% against a random hand; bargaining, Kelly, ruin, IRR, PME and storage match their closed forms and the page;
  GARCH, two Markov regimes and a cointegrated pair are recovered on planted data.
- v0.13: on a planted graph with missing spans the atlas finds every causal link, keeps at least 80% real ones after
  pruning the co-parent links a graphical model adds, and points at least three quarters the right way; the
  pairwise-complete correlations equal pandas; responses equal matrix powers and the page's equal Python's; the
  connectedness decomposition is exact and the rolling index has no look-ahead; communities recover a planted
  partition; a gap in the data is not a move and a weaker currency reads negative.
- v0.12: robustness values match Cinelli and Hazlett's published example; stacking recovers a true model and a true
  mixture; adaptive conformal intervals keep 90% coverage on Gaussian and fat-tailed data; no forecast changes when a
  later month does (no look-ahead); the landing brain's Leontief limit equals the series summed to convergence; the
  page's voices retrieval equals Python's token for token on 22 queries; every quote has an https source, at most 45
  words, no banned text; the MCP tool returns only library quotes.
- v0.11: the reverse DCF solves PV = EV exactly and moves the right way with price and rates; base rates match the
  book's exhibit and invert; quality reads planted accounts flag by flag, and cash lifted by prepayments does not raise the steady-state margin; switching every hedge off is the book, each
  hedge pays in the scenarios it claims (the test caught TLT wrongly claiming the liquidity crash), and hedges add
  linearly (property-based); the advisor's sets match between Python and the page; Granger finds a planted lag in the
  right direction and partial correlation a planted conditional independence; since 2022 the 10-year yield rose in
  stocks' worst months, before it fell; the position rules do exactly what the docstring says; an engine that fails on
  purpose is isolated in the manifest.
- v0.10: leave-one-out influence equals refitting to 1e-12; Huber resists planted bad prints and equals least squares
  as c grows; Newey-West widens under autocorrelation; months-to-flip is verified by refit and one fewer does not
  flip; the KL worst case matches a brute-force optimizer and is bounded and monotone (property-based); the robust
  solver reduces to the nominal one at zero doubt and never raises nominal growth; PBO is near 50% among equal rules
  and below 10% when one has a real edge; the price screen flags a bad print, a frozen feed and a gap but not a real
  crash; channel sums, Gaussian densities and risk shares hold on random inputs (property-based); Python and the page
  agree on all of it.
- v0.9: the readings' density, surprise and leave-one-out z-scores match brute-force Gaussian conditioning to 1e-10;
  model comparison finds a planted world; channels and but-for shares add up exactly; the forward loss story is the
  minimum-norm one; counterfactuals leave non-descendants alone; DirectLiNGAM recovers a planted, shuffled five-variable
  order; the Kalman smoother finds a planted sign flip and chooses a smaller drift for a link that never moved; Python
  and the page agree on all of it on the page's own graph and series, with shared seeded resamples.
- The MCP server completes the handshake over stdio, answers every tool in agreement with the engine, rejects bad
  input as tool errors, has no execution tool, marks every proposal unexecuted and refuses the private config.
- The feed scraper survives dead sources and a missing X token, finds a planted lead time, and its text cannot
  inject markup or script into the page.

## Principles

- Decisions at the close of t earn returns from t+1. Nothing else is allowed.
- Predict risk before return. Volatility and correlation forecasts are where the signal is.
- A hedge removes at most rho squared of variance. At a -0.3 correlation that is 9%. Long bonds are a
  scenario hedge (growth scares), not a variance hedge; size them to the scenario.
- Every backtest result carries a deflated Sharpe that charges for the number of variants tried.
- Rates of change outrank levels; a rule's line and the time to reach it beat a forecast.
- A decision's confidence is the product of its assumptions. Write them down, weight them, and test them.
- Write the forecast down before the outcome, and score process separately from outcome.

Research tool, not investment advice.

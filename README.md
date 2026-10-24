# Buildout

Regime-aware risk, hedge and sizing engine for a concentrated AI-buildout equity book
(hyperscalers, NVDA/AVGO, TSLA, SPCX) with long Treasuries as the candidate hedge.

Version 0.26 adds an edge lab (`buildout/discovery.py` part two, `buildout/unusual.py`, an Edge lab desk, MCP tool
`edge_lab`, `python -m buildout edges`): a hypothesis factory in the spirit of "weird edges all over the world, from
unusual data". It invents 43,247 candidate edges from 70 world markets, their own histories, every other market and 89
unusual and computed series (climate, oceans, the sun, storms, shipping, the calendar), each lagged to when it was
knowable. Then it tries to kill them. Each candidate is run beside 129,741 hypotheses on fake markets (the whole rule
library on block-shuffled returns) and 300 fake signals. Its p-values are calibrated on those fakes before
Benjamini-Hochberg, and composites must beat their own parts. It must also pass breadth, validation and costs, and an
edge counts as tested only if most of its markets trade in the test years. 5 distinct edges survive, against fewer
than 1 expected by luck. None can be tested after 2017 because their IMF markets end then. The search replayed with
data through 2010 gives 6 survivors, and all 6 made money in 2011 to mid-2017: book Sharpe 1.61 after costs, about 3
independent bets, on spot research prices rather than tradeable futures. That is a replay, not an independent test,
because those years were the main search's validation years. An independent audit and a second pass before release
cut the first run's 65 survivors (and its 0.59 book Sharpe) to these numbers, and the desk shows the before and after.

Version 0.25 makes the engine reason and lets other fields grade it. `buildout/reason.py` deduces with proofs over the
mind's typed links and over the decision policy (today's call is derived with every flip point), induces rules on data
before 1961 and tests them after (4 of 30 survive), abduces, and invents regimes and predicates (none beat the mean out
of sample). Five research agents read Taleb's works, the legendary traders, actuarial science, weather forecasting and
big data; five checkers verified 532 entries; 43 principles became tests and 2 hold in both halves of the record.
`buildout/crossfield.py` scores the monthly forecast like a weather service (CRPS, PIT, coverage, skill) and backtests
the tail like an actuary (generalized Pareto, Kupiec, Christoffersen, Acerbi-Szekely, ruin); five borrowed upgrades to
the core were tried and none adopted. The ML ensemble's skill moves from -6.0% to +4.0% and the RL lab's pooled agent
to Sharpe 0.74; every sizing variant counts in the gate (28 strategies). The math shows by default.

Version 0.24 deepens the research, explains the engine simply and answers an audit. Five research agents gathered
175 dated, linked items (the tape, capex and earnings, AI credit, the Fed and inflation, power) and a sixth 35 verbatim
quotes; independent checkers reopened every source (20 corrected, 1 failed and dropped); the store holds 780 items and
302 quotes (`scripts/snapshot_v24.py` writes the Digest desk). A How it works desk explains the engine with live numbers
and a replay since 1940. An auditor agent read every desk as a PM would and returned 70 findings. The first was the
engine's own: the trend overlay's factor was chosen on the full record. `decide.overlay_study` now walks the choice
forward (10-year burn-in, re-chosen every 12 months); walked forward it cost expected utility (t -2.29), so no overlay
is adopted and its four scalings count in `N_TRIED` (12). Every desk now shows the one governing size beside its own,
Today lists limits and breaches, one correlation measure is named as in force, and the level store is dated.

Version 0.23 names the system and counts what it has learned. The mind, the brain, the atlas and the decision and
portfolio engines are layers of one engine whose product is its parameters, Theta: every matrix, vector and scalar an
algorithm shaped by optimising a stated objective on stated data. `buildout/parameters.py` inventories them from the
engines' own outputs (desk "Parameters", `python -m buildout parameters`, MCP tool `parameter_inventory`, a daily
`parameters` engine): 22 objects and about 598,000 numbers, each with its shape, optimiser, objective, data, refit
schedule and the desks it feeds; the decision core (regimes, forecasters, allocation, portfolio, learner) is 2,850
numbers and the rest is the knowledge graph's 64-eigenvector spectral map. The eleven constants set by hand are listed
apart with their reasons. The trend rule, which beat holding on Sharpe and drawdown while the gate benchmarked against
holding, is resolved on the record (`decide.overlay_study`): of five scalings of exposure below the 10-month average,
0.50 is the deepest drawdown cut that keeps holding's expected utility (worst drawdown 36% against 52%, Sharpe gain 90%
range +0.02 to +0.17), adopted as an overlay on the gated call; the trend is on today, so the call stays at 1.00x and
would fall to 0.50x if it broke. The landing page is one screen: the sized call as the headline, a six-number call
board, the engine's six stages with today's values, the parameters and the codebase counted, and where the engine plugs
into a fund; its other sections moved to the desks that own them. Navigation is six groups (Today, Engine, Markets,
Research, Workshop, Methods), and the mind carries a node for every parameter object (8,728 nodes).

Version 0.22 asks whether the shape of the market says anything (`geometry.py`, desk "Geometry", `python -m buildout
geometry`, MCP tool `geometry_engine`). Every 36 months of stocks, 10-year Treasuries and gold is a covariance matrix, a
point on the curved space of positive-definite matrices: rolling covariances for all windows at once from cumulative
sums of outer products, matrix logarithms through batched eigendecompositions, every pairwise log-Euclidean distance from
one Gram matrix, affine-invariant distances (which ignore units and mixing of the assets) from batched eigenvalues, a
classical multidimensional-scaling map of 150 years, and Frechet means by era. Random matrix theory on the atlas's 27
world-market series finds 2 eigenvalues above the Marchenko-Pastur noise edge (the dollar, then oil and rates);
persistent homology of their correlation geometry (H0 from the minimum spanning tree, H1 by reducing the Vietoris-Rips
boundary matrix over the two-element field) and the absorption ratio are tested as warnings of 10% falls; sliced
Wasserstein distances compare whole distributions; the Levy area of the stock-bond path measures who moved first;
detrended fluctuation analysis gives the Hurst exponent by era; and the volatility drag is measured decade by decade.
Every claim is walked forward and its p-value corrected with the others (Benjamini-Hochberg). The decision engine gains
a fourth return-density model, geometric analogs (`decide.geo_walk`), and its bonds now run to 2026 with the GS10
splice. Results: of 8 claims, 1 survives a 10% false-discovery rate: the analog model beats the long-run average's
predictive log score (t 4.0) and model averaging gives it 12% of the weight, but a placebo of 8 windows drawn at random
does as well (geometry over random t -0.2): the gain is the fatter tails of a mixture, not the resemblance, so analog
point forecasts (skill -15% for returns, -26% by whole distributions) are not used. The book stays at 1.00x. Also in
this version: a Games desk bug fixed (two top-level functions shared a name; the assembler now refuses that), stale
counts and dates refreshed across the page, the code viewer and background desk building made incremental, and dead
code and CSS removed. A second, independent review (60 findings) then drove a register and consistency pass: one
governing equity size on Today with the other rules as cross-checks, the capex signal on the five builders' trailing
ratio, the rate-of-change and bond-tape column bugs fixed, every static level on the Oct 21 close, evidence grades as
quiet dot marks rather than pills, and a standards-mode skeleton on the raw page.

Version 0.21 rebuilds the heaviest parts of the engine around matrix multiplication, the operation AI hardware is built
for (prompted by DeFi Education's note on Pearl, a blockchain whose proof of work is that same math). The regime filter,
which carried odds forward one month at a time, is now a scan of matrix products (`infer._scan`, `forward_backward`):
because the forward recursion is a product of matrices and products are associative, every month's odds come out of
log2(T) rounds of batched multiplication, the backward pass is the same scan over suffixes, and every random start of a
fit runs in the same batch. The five-network ensemble trains its members side by side (`nn.DeepEnsemble(batched=True)`,
written by a subagent, identical to sequential training bit for bit). Measured on the build machine: the decision
engine rebuilds in 33 seconds instead of 93 and the portfolio engine in 9 instead of 24, with the same findings to the
last digit; the forward-backward pass is about 3x faster and agrees with the loop to about 1e-14. The mind's graph is
one sparse 9,426 by 9,426 matrix (`Mind.walk_matrix`); many questions think at once as one product with a matrix of
questions (`spread_many`, `think_many`), which gives the board: the mind's verdict on all 27 claims it weighs in one
pass (`python -m buildout board`, MCP tool `mind_board`, and live in the page). A 64-eigenvector map of the graph is
about 9x faster per question but changes half of the top twenty answers, so it is used only to find related ideas
(`Mind.related`, `python -m buildout related c:kalman`). A new desk, The shortcut, explains and measures each of these,
shows the brain's every-shock-against-every-holding matrix, and covers Pearl with facts from Alea Research and Bankless.
`python -m buildout bench` now includes the matrix benchmarks.

Version 0.20 widens the decision from a stock weight to a portfolio and adds a layer that chooses between whole
decision processes (`portfolio.py`, desk "Portfolio", `python -m buildout portfolio`, MCP tool `portfolio_engine`). Real
monthly returns on stocks, 10-year Treasuries (Shiller's long rate spliced with the GS10 series to 2026) and gold feed a
hidden Markov model of all three together (`infer.mvhmm_*`: full covariance, warm-started refits, states by BIC), so each
regime carries its own stock-bond correlation. Mixes on a grid are chosen by expected CRRA utility, integrated exactly on
343 Gauss-Hermite nodes per state, inside the 12% expected-shortfall budget. Eight policies are walked forward since 1940
with costs (hold, 60/40, risk parity, the trend rule, the regime allocation, its stock-only twin, the gated engine and a
Hedge learner over six of them with a learning rate fixed in advance). Results: timing the three assets by regime earned a
Sharpe of 0.50 (worst drawdown 62%) against 0.64 for holding stocks (52%) and 0.65 for 60/40 (37%); the learner reached
0.66 with a worst drawdown of 41%. Deflated for the nine policies tried, the chance the best has a real edge over holding
is 1%, so the decision stays at all stocks. Next month is most likely the calm-bull state (94%), where stocks and
Treasuries have moved together (correlation +0.15). A regime-switching bootstrap simulates ten years 5,000 times from
today's odds with real historical months: all stocks reach a median 2.12x real (5% to 95%: 0.93x to 4.60x) with a 38%
chance of a drawdown deeper than 30%; 60/40 1.75x (1.05x to 2.90x) with 8%. Today's mixes are replayed through eight
drawdowns since 1929. The decision engine also runs in the page (`site/src/dxlive.js`, checked against
`decide.what_if` to 1e-12): sliders for the stressed regime's odds, the 12-month forecast, risk aversion, the risk budget
and the evidence behind the gate. The mind answers "what should the book do", "what regime are we in" and what-ifs on
them in Python and in the page. Under the hood is now a code reader (taller, wrapped, highlighted, a definition jump
list, copy, full screen), and a reviewer agent's 25 findings across all 41 desks were worked through.

Version 0.19 turns the harness into a decision engine: one pipeline from data to a sized, explained decision, walked
forward from 1940 (`decide.py`, desk "Decision engine", `python -m buildout decide`, MCP tool `decision_engine`).
Data: 1,868 months of US stocks with the 10-year yield and a 10-year bond's return built from it. Features: the ML lab's
eight. Models: the historical mean, ridge, the restricted combination and a deep ensemble of five small neural networks
(`nn.py`: numpy only, backpropagation checked against finite differences to about 1e-7, dropout, weight decay, Adam,
early stopping on the newest fifth of the data, quantile and logistic losses, a purged walk-forward), stacked with
non-negative weights fit only on forecasts whose outcome was known. Inference (`infer.py`): a Gaussian hidden Markov
model of regimes (Baum-Welch with several starts, states by BIC, refit every five years, filtered so no decision sees
the future, means shrunk toward the long-run mean), Bayesian online changepoint detection, a Kalman filter on the
stock-bond beta, and dynamic model averaging of the return models by their discounted predictive log score. Decision:
the exposure from 0 to 1.5x that maximizes expected CRRA utility of next month's wealth under the averaged mixture, with
risk aversion set once on 1871 to 1939 data so holding is optimal in an average month, inside a 12% monthly expected-
shortfall budget; then an evidence gate scales the move away from 1x by the engine's own walked-forward utility gain
over holding, deflated for the strategies tried. Today the engine's optimum is 1.5x (a calm regime, 79% likely next
month) and the decision is 1.0x: since 1940 its departures from holding earned a timing alpha of about 1.5% a year
(t 1.8) but did not make a risk-averse investor better off (utility t 0.4 against the 1.1 the best of seven useless
strategies would show; Sharpe 0.64 against 0.64). The desk shows each input's weight, what drives the optimum (leave
one out), what would flip it, its distribution over 2,000 draws of regime, model and forecast, the value of knowing the
regime, a Bayesian hedge selector by regime and trend, and a conservative reinforcement-learning check (a bootstrapped
ensemble of fitted-Q agents acting on the lower confidence bound: Sharpe 0.65 with a worst drawdown of 31% against 52%,
at about half the exposure). The neural networks lose to the mean out of sample (skill -37%, Diebold-Mariano t -2.6),
like every flexible model before them; the stack gives them 11%. Seventeen planted-answer tests cover the new parts.

Version 0.18 makes the engine stronger and the page easier to read. The mark is the Today desk's rosette, the green lotus, drawn from the same curves (`scripts/make_logo.py` writes it as an SVG symbol and the page icon). The layout follows the firm and product sites: a centred navigation band, 44-pixel pill buttons, and a floating desk bar with the way back, the map and the way on. The engine gains a framework in `buildout/core/`:
a content-addressed cache (`cache.py`: results keyed by the source of the code and a canonical hash of the data, written
atomically with a checksum, corrupted entries dropped and recomputed, network inputs served from the last good copy when
a source fails), a parallel runner (`runner.py`: engines ordered by the files they read and write, each in its own
process with a time limit, retries with backoff, output contracts from `contracts.py` and the previous good files
restored when an engine fails, hangs or writes a bad file), structured logs (`log.py`), a health check
(`python -m buildout doctor`) and a benchmark (`python -m buildout bench`). Measured on this machine: the mind rebuilds in
1.6 seconds instead of 12 with a warm cache; a question takes about 0.05 seconds in Python instead of 0.4 (vectorized
recall and spreading activation); the offline engines run in about 5 seconds instead of 19; the page does about half the
main-thread work at load (2.3 seconds instead of 4.5) because it builds the desk you open first and the rest in idle
time. The page is set in EB Garamond, inlined under the SIL Open Font License; every desk opens with what it answers,
when to open it and how to read it, ends with the next desk, and numbers its sections; a map (press 0) lists every desk
by the question it answers; the desks are reordered so each group reads from the answer to the method. The Vim and
Emacs clients are rewritten (asynchronous jobs, a results buffer, commands for every engine; see Editors). A real bug
in the X feed reader (an import that shadowed `urllib`) was found by the new lint pass and fixed.

Version 0.17 does two things. First, bonds broken down to what they are: `bondlab.py` reprices every Treasury ETF
(SHY, IEI, IEF, TLH, TLT, EDV, ZROZ) bond by bond at any 10-year and 30-year yield on today's Treasury par curve. Each
fund is an equal-face ladder centred on the issuer's reported average maturity, with one coupon calibrated so the
ladder's duration equals the reported duration; the curve moves so the 10-year and 30-year land exactly where you set
them and today's hump is kept. If both go to 4%, TLT goes from $80.24 to about $99 (+23.5%); at 6%, about $73
(-8.8%); the duration rule alone would miss about 3 points of convexity. It reports the 12-month return with coupons
and roll, the break-even yield rise, a heatmap of every pair of yields, today's tape against the model (TLT +1.53%
predicted for the midday move, +1.73% reported), and how stocks have moved per point of yield by inflation band since
1871: in the middle band, where inflation now sits, stocks fall about 2.7% per point of yield rise (t -2.4).
`python -m buildout bonds --y10 4 --y30 4`, the MCP tool `bond_scenario`, and the mind all answer "if the 10-year and
30-year go to 4%, what is TLT?". Second, why the complex models backtested better and forecast worse, measured by
`complexity.py`: in-sample R squared rises toward 100% with complexity in every family while out-of-sample skill
falls; 1,710 overlapping months hold about 142 independent observations; all eight predictors explain
10.5% in sample while ordinary least squares with eight predictors costs about 5.6% out of
sample; a regression fitted before 1950 put a weight of -20.8 on a 10-year yield that later tripled; the CAPE slope
drifts; Stambaugh's bias moves its p-value from 0.03 to 0.12; and on planted data complexity pays only when the signal
is strong and genuinely nonlinear. The mind grows to 8,598 nodes and about 34,700 links: 4,295 concepts (eight writer
agents, a ninth fact-checking 958 entries), every month since 1871 with its eight nearest analogs and what followed
(`chronicle.py`), 25 named episodes, the Treasury ETFs, the desks, and similarity links between concepts; it answers
history questions ("what happened in 1974", "months like now") directly. `python -m buildout history "black monday"`
and the MCP tool `market_history` do the same.

Version 0.16 makes data the focus. `datahub.py` reads Databento (split-adjusted daily OHLCV and futures), Yahoo's
chart API, Stooq, the SEC's XBRL company facts, the Treasury's par curve, the CFTC's traders-in-financial-futures and
FRED behind one interface, tried in priority order per ticker with the answering source recorded, plus a connection
check (`python -m buildout connect`). `technicals.py` is a tested technical-analysis library (moving averages, RSI,
MACD, Bollinger, ATR, ADX, stochastic, Williams %R, CCI, TSI, Ichimoku, Supertrend, parabolic SAR, Keltner, Donchian,
OBV, money flow, Chaikin money flow, VWAP, swing levels, Fibonacci, pivots, divergences, the trend template and
relative strength) with an event study of thirteen signals on each asset's own history (Newey-West t, Benjamini-
Hochberg) and a composite that weights each signal by its evidence. `statements.py` turns company facts into annual
statements and computes margins, ROIC, cash conversion, accruals, capex against depreciation, growth and its
acceleration, the Rule of 40, Piotroski F, Altman Z'' and Beneish M, marking unknown what the filings do not carry.
`rl.py` is a reinforcement-learning sizing agent (fitted Q iteration over trend, volatility, valuation and drawdown,
walk-forward from 1940): it does not beat holding, and the 10-month trend rule beats both. `ml.py` adds the Rapach-
Strauss-Zhou combination with Campbell-Thompson restrictions, the first model to beat the historical mean out of
sample (+2.5% skill, t 1.45), and an accuracy-weighted ensemble. The Edge desk adds a distribution scorecard of each
holding's own disclosures. The page adds a Technicals and fundamentals desk with a broker-CSV reader that runs in the
browser (Robinhood, Schwab, Fidelity exports); `python -m buildout positions export.csv` does the same locally.
The mind's layout is three times faster and the page no longer runs the solver at load (about 5.4s to 1.6s).

Version 0.15 asks how far to trust any model, including its own. `ml.py` scores six machine-learning models (CAPE
regression, ridge, random forest, gradient boosting, nearest analogs, an ensemble) on forecasting 12-month real returns
and 15% falls every month since 1940 with purged walk-forward refits, against the historical mean with Diebold-Mariano
tests, plus combinatorial purged cross-validation and the probability of backtest overfitting, conformal intervals with
measured coverage, calibration, permutation importance, analogs and novelty. None beats the mean; the page says so.
`assumptions.py` answers a PM's complaint that quants' assumptions break in the real world: it registers what each
engine model assumes, tests it on the data (fat tails, dependence, structural breaks, the stock-bond correlation by
inflation regime, crisis correlations), finds the breakpoint at which each conclusion flips (the TLT hedge's
correlation line, the trend rule's cost and delay, Kelly across windows), measures Taleb's kappa and the Taleb-Douady
fragility of each hedge structure, reruns decisions in 400 block-bootstrapped worlds, and triages any backtest Sharpe
for costs, published-anomaly decay, the variants tried (deflated Sharpe) and the minimum backtest length.
`damodaran.py` holds the implied equity risk premium and the narrative-to-numbers DCF. The mind grows to 2,614 nodes
and about 5,600 links (606 concepts, 418 checked items including 23 profiled information sources, 213 economies, the
S&P 500 companies, ML models and tested assumptions) and gains a belief network over thirteen claims for what-if
questions. The page adds the ML lab, Reality check and Edge desks, Vim and Emacs key modes with a command line;
`editors/buildout.vim` and `editors/buildout.el` ask the engine from either editor.

Version 0.14 makes the brain and the engine one mind, an order of magnitude larger, and gives it a reasoning loop.
`mind.py` joins, in one typed graph of about 1,500 nodes and 3,800 links: 547 concepts with definitions, formulas and
relations (`ontology.py`), the atlas's 100 market nodes and their learned causal links, 268 facts and papers checked
twice on their sources (`assets/knowledge.json`), 371 verified quotes, every Python module with its
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
travelling the 34-node graph one order at a time, x_k = W'x_(k-1), with the arithmetic beside it: the largest flows of
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
| ML lab | Six models scored out of sample since 1940 against the historical mean; overfitting odds by CPCV; calibration; conformal intervals; importance; analogs and novelty |
| Reality check | Every model's assumptions with a live test and a verdict; the PM's triage of a quant backtest and seven questions for any pitch; breakpoints; kappa; fragility; stressed worlds; the literature on what backtests lose |
| Edge | 23 information sources with their edge, biases, cadence, cost and feeds; Damodaran's implied ERP and narrative DCF; the Taleb and Damodaran lenses, sourced |
| Keys | Press ? for Default, Vim (j k, gg G, ]] [[, gt gT, yy) or Emacs (C-n C-p, C-v M-v, C-s, M-x, C-x o) and a command line (: or M-x) taking think, whatif, go, triage, erp, set keys |
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
pytest                                    # about 400 tests, no data needed
python -m buildout doctor                 # health check: environment, secrets, knowledge, bond ladders, engine graph, page, cache
python -m buildout bench                  # time the mind, the bond lab, the engines and the page's mind
python -m buildout cache info             # the result cache (also: prune, clear); BUILDOUT_NO_CACHE=1 turns it off
python -m buildout engine --out out --jobs 4   # engines in parallel, isolated, contract-checked; --serial to debug; --graph
python -m buildout bonds --y10 4 --y30 4  # every Treasury ETF at those yields
python -m buildout history "black monday" # the chronicle: a month, a year, an episode or "months like now"
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

## Editors

`editors/buildout.vim` (Vim 8.1 or Neovim) and `editors/buildout.el` (Emacs 25.1 or later) run
`python -m buildout` from inside the editor, with nothing to install beyond the file itself. Commands run in the
background, so the editor never freezes. Every result lands in one read-only buffer (`buildout://out` in Vim,
`*buildout*` in Emacs) that shows the command, the folder and interpreter it ran with, the elapsed time and the
output. A missing interpreter, a wrong repository folder or a non-zero exit is reported in that same buffer. Plus
signs and positive numbers are green, minus signs and negative numbers red, headings and percentages stand out.

Install. Vim: copy `buildout.vim` to `~/.vim/plugin/` (Neovim: `~/.config/nvim/plugin/`). Emacs: put `buildout.el`
on your `load-path`, then `(require 'buildout)` and `(buildout-mode 1)`, or bind the prefix map yourself with
`(global-set-key (kbd "C-c b") 'buildout-command-map)`.

| Command (Vim / Emacs) | Key | Does |
|---|---|---|
| `:Buildout {sub} [args]` / `buildout-run` | `g` | Any subcommand; Tab (Vim) or completion (Emacs) offers the names, Vim also their flags |
| `:BuildoutThink [question]` / `buildout-think` | `t` | Ask the mind; prompts when empty; uses the Visual selection or the active region |
| `buildout-think-at-point` | `w` | Ask about the word under the cursor (Emacs: `C-u` for the line) |
| `buildout-think-line` | `l` | Ask about the current line, without its indent, comment leader or bullet |
| `:BuildoutWhatIf [condition]` / `buildout-what-if` | `i` | A what-if over the belief network; the selection or region works too |
| `:BuildoutBonds [y10 [y30 [front]]]` / `buildout-bonds` | `b` | Prompts for the 10-year and 30-year yields in percent; an empty 30-year moves with the 10-year |
| `:BuildoutHistory [query]` / `buildout-history` | `h` | A month, a year, an episode or `now` from the chronicle |
| `:BuildoutTA [ticker]` / `buildout-ta` | `a` | Technicals for the ticker under the cursor (`$nvda,` reads as NVDA) |
| `:BuildoutFA [ticker]` / `buildout-fa` | `f` | Fundamentals for the ticker under the cursor |
| `:BuildoutEngine [dir]` / `buildout-engine` | `e` | Run the offline engines into `out` (or the folder given) |
| `:BuildoutEngineList` / `buildout-engine-list` | `E` (Emacs) | The engine registry |
| `:BuildoutDoctor` / `buildout-doctor` | `d` | Check the setup |
| `:BuildoutBench` / `buildout-bench` | `m` | Time the engine |
| `:BuildoutRerun` / `buildout-rerun` | `r` | Run the last command again, from the same folder |
| `:BuildoutLog` / `buildout-log` | `L` | Recent commands; pick one to run it again (`:BuildoutLog!` clears the Vim log) |
| `:BuildoutStop` / `buildout-stop` | `s` | Stop the running command |
| `:BuildoutOpen` / `buildout-show` | `o` | Show the results buffer again |

The keys sit under a prefix: `<Leader>b` in Vim (so `<Leader>bt` asks the mind) and `C-c b` in Emacs with
`buildout-mode` on. Vim also keeps `:BuildoutTriage`, `:BuildoutERP`, `:BuildoutDCF`, `:BuildoutML` and
`:BuildoutReality`; Emacs has them on `T`, `P`, `D`, `M` and `R`. Every Vim key is also a `<Plug>(buildout-...)`
map for your own bindings. In the results buffer, `q` closes it, `r` reruns, `y` copies the output (Vim: to the
unnamed register; Emacs: to the kill ring), `n` and `p` jump to the next and previous section and `s` stops.

| Vim option | Emacs option | Default |
|---|---|---|
| `g:buildout_python` | `buildout-python` | `python3` |
| `g:buildout_root` | `buildout-root` | The nearest folder above the current file holding `pyproject.toml` and `buildout/`, else the folder above the plugin |
| `g:buildout_prefix`, `g:buildout_no_mappings` | bind `buildout-command-map` yourself | `<Leader>b`, mappings on |
| `g:buildout_focus` | `buildout-select-window` | Move to the results window |
| `g:buildout_engine_out` | `buildout-engine-out` | `out` |
| `g:buildout_log_size` | `buildout-log-size` | 50 |
| `g:buildout_height` | | 15 lines |
| `g:buildout_sync` | | Off; on runs commands with `system()` and waits (the tests use it) |
| `g:buildout_history` | `buildout-run-log`, `buildout-query-history` | The query log, newest first, and the minibuffer history |

`tests/test_editors.py` runs the Vim plugin headless against stub engines (one that exits 0, one that exits 2) and
checks the Emacs file's parentheses and names; `editors/buildout-test.el` holds ERT tests for Emacs
(`emacs -Q --batch -L editors -l editors/buildout-test.el -f ert-run-tests-batch-and-exit`).

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
| Research | `research.py`, `fundamentals.py` | 156 years of public data (hedge line, fat tails, earnings rate of change, oil shocks, VIX spikes, inflation spells, gold, CAPE); last-twelve-month SEC analysis, Minsky stages, depreciation vintages |
| v0.18 | `core/cache.py` | Content-addressed result cache; last-good fetch for network inputs; prune and info |
| | `core/runner.py` | Parallel dependency-graph runner: process isolation, timeouts, retries, contracts, last-good fallback, provenance |
| | `core/contracts.py` | What each output file must contain (fields, finite numbers, ranges) before anything reads it |
| | `core/doctor.py`, `core/bench.py`, `core/log.py` | Health check, benchmarks, structured logs and timing spans |
| v0.17 | `bondlab.py` | Treasury ETFs as calibrated ladders; the curve moved to any 10-year and 30-year yield; price, 12-month return with roll, break-even, grid; stocks per point of yield by inflation band; reading yield questions |
| | `complexity.py` | Complexity sweep, effective sample, cost of estimation, extrapolation, drift, Stambaugh bias, planted-signal experiment, written conclusions |
| | `chronicle.py` | Every month since 1871, years and named episodes, analogs on six standardized features, the spiral layout |
| v0.16 | `datahub.py` | Databento, Yahoo, Stooq, SEC company facts, Treasury curve, CFTC positioning, FRED; per-ticker fallbacks; connection check; broker CSV import; the market run |
| | `technicals.py` | Indicator library, signals, chart structure, event study with Newey-West and BH, evidence-weighted composite judged out of sample |
| | `statements.py` | Annual statements from XBRL company facts; ratios; Piotroski F, Altman Z'', Beneish M; valuation multiples with a price |
| | `rl.py` | Fitted Q iteration sizing agent over 54 market states and the last action, walk-forward, bootstrap and deflated Sharpe |
| | `nn.py` | Multi-layer perceptrons and deep ensembles in numpy: gradient-checked backpropagation, dropout, weight decay, Adam, early stopping on the newest data, mse, pinball and logistic losses, purged walk-forward |
| | `infer.py` | Hidden Markov models (one asset or several, full covariance) fit by EM with the forward-backward pass as a scan of matrix products and every start batched; Bayesian online changepoints; Kalman regression; stacking; mixture risk; exponential weights |
| | `decide.py` | The decision engine: walked-forward regimes, changepoints and geometric analogs, forecasts, dynamic model averaging, utility-optimal exposure in a risk budget, the evidence gate, the hedge selector, conservative RL, drivers, flip points and the value of information |
| | `geometry.py` | The shape of the market: covariance matrices on a curved space (affine-invariant analogs, an MDS era map, Frechet means), random matrix theory, persistent homology, optimal transport, the Levy area, DFA and volatility drag, every claim walked forward with a placebo and a false-discovery correction |
| | `parameters.py` | Theta: the inventory of every matrix, vector and scalar the engine learns, read from the engines' outputs (shape, count, optimiser, objective, data, refit schedule, desks fed); the constants set by hand with their reasons |
| | `portfolio.py` | The portfolio engine: three-asset regimes, utility-optimal mixes in a risk budget, eight policies walked forward, the Hedge learner, a regime-switching bootstrap and stress replays |
| v0.15 | `ml.py` | Purged walk-forward forecasts since 1940, Diebold-Mariano, CPCV and PBO, split-conformal intervals, calibration, permutation importance, analogs, novelty |
| | `assumptions.py` | Model register and assumption tests, breakpoints, Taleb's kappa, fragility heuristic, stressed worlds, backtest triage (deflated Sharpe, minimum backtest length, decay, costs) |
| | `damodaran.py` | Implied equity risk premium; narrative-to-numbers DCF with fading growth, target margin, sales-to-capital reinvestment and failure odds |
| | `editors/` | `buildout.vim` and `buildout.el`: every subcommand from inside Vim or Emacs, run in the background into one results buffer (see Editors) |
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
- v0.18: the cache hits on equal data and misses on different data, hashes canonically (dict order, DataFrames,
  dtypes), drops a truncated entry and recomputes, survives an unwritable folder, bypasses calls that would fetch their
  own data, and serves the last good copy when a source fails; the runner orders by files read and written, runs
  independent engines in parallel, stops a hung engine, isolates one that crashes the interpreter, retries a flaky
  one, restores the last good files after a failure or a NaN, flags dependents that read last-good inputs and refuses
  a cycle; doctor finds nothing broken; bond prices fall and bend upward in yield for any yield (property tests), a
  bond at its own coupon prices at par, and reading a yield question never throws on arbitrary text.
- v0.17: a zero-coupon ladder's duration equals its price-weighted maturity over one plus half the yield; the
  calibrated ladders hit the reported duration and centre on the reported maturity; the curve move lands exactly on
  the 10-year and 30-year and keeps the hump; par bonds on a flat curve lose what duration and convexity say and gain
  more on a fall than they lose on a rise; unchanged yields earn the yield; Python and the page agree on every fund,
  scenario, grid and parsed question to 1e-12; the complexity study's overlap, persistence and drift recover planted
  values and linear regression wins at a low planted signal.
- v0.16: indicators match their definitions (SMA, true range, Wilder ATR, OBV, WMA, Fibonacci) and stay in range;
  signals never change when only the future changes; the event study finds planted momentum and noise earns little
  weight; a planted company passes all nine Piotroski tests and its Altman Z'' and ratios match by hand; Beneish is
  neutral when nothing changes; Yahoo and Stooq parsers adjust and clean; the hub falls back in order; broker exports
  parse the same in Python and on the page; the connection check never prints a secret; the RL agent learns a planted
  policy and its states use only earlier data; the combination obeys its restrictions; accuracy weights use only
  known outcomes; the layout is fast and deterministic.
- v0.15: walk-forward finds a planted predictor (skill above 0.3, DM t above 2) and not a fake one, and never trains
  on an outcome that overlaps the forecast; CPCV gives low overfitting odds to a real linear signal and high odds to a
  memorizing model; conformal intervals cover 80% of iid errors; kappa reads 0 for a bell curve and positive for
  Student-t(3); sup-F finds a planted break; the hedge breakpoint is where the sleeve stops reducing variance; short
  puts read fragile and the collar does not; the triage reproduces Bailey's 45 tries in five years; the implied ERP
  reduces to Gordon and the DCF to a perpetuity; belief propagation returns each claim's own evidence without links;
  the page's what-if, explain, network, triage and Damodaran code equal Python's.
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

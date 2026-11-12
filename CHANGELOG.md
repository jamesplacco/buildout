# Changelog

Release notes, newest first. The page's Appendix desk carries the same history with dates; the failure log
(Memos desk) carries every number that turned out wrong.

Version 0.43: the core page. "Reduce what is unnecessary." The site's front page now carries fifteen desks in four
groups (Call, Record, Evidence, Method) and the library carries all sixty-six; both are built from the same sources.

- **What a reader meets.** Four groups and fifteen desks in place of five groups and sixty-six. The Desk on the core
  page ends at what would reverse the call; how the call is derived lives under Method.
- **What the browser loads.** The core page leaves out the other desks' markup, the mind's graph (4.3 MB), the
  embedded source (2.4 MB) and every snapshot and module only the library uses.
- **How the cut is decided.** `scripts/prune_core.py` replaces a file with inert stand-ins, opens the page in a
  browser, visits and uses every core desk, and leaves the file out only if no text, table or chart mark changes and
  nothing errors. A module of code is tried only if no core module names anything it declares.
- **How the cut is held.** `tests/test_v43.py` compares every core desk on the two pages in a browser; the stress
  suite serves the site as published and follows a link from the core page into the library and back.
- **Nothing was deleted.** `site/page.html` is unchanged in content and is published as `library.html`.

Version 0.42.6 adds the universe checks (`track.universe_checks`, the Track record desk): how much of the record is
owed to a candidate list written in 2026. The same sizing rule, costs and dates are run on the candidates frozen at
the end of 2017 (14 names; Palantir and SpaceX listed later and never enter), on that list without the name whose
removal costs most (AMD), and on three funds that existed before 2018 and whose members someone else chose (QQQ, SOXX,
ROBO). Findings, through Nov 5, 2026:

- **The level is the list.** Holding the nine grew 29.7% a year; the baskets 17.3%, 24.9% and 5.2%. That gap, 5 to 24
  points a year, is selection.
- **The rule's claim holds off the list.** The call cut the worst fall on all six universes (QQQ 35% to 25%, SOXX 46%
  to 20%, ROBO 44% to 31%) and gave up Sharpe ratio on all six.
- **The short's claim does not.** Full size with the Nasdaq-100 short earned 0.93 on the nine because they beat the
  index by 8.1% a year (t 2.2). SOXX beat it by 4.6% (t 0.8) and ROBO lagged it by 9.1%. The page said the hedge was
  the better way to take the limits; it now says the edge was the names (failure log).
- **No single pick carries it.** Leaving any one name out of the frozen list moves holding's growth by -0.1 to +4.1
  points a year.

Still not done: a universe with the companies that failed. No source this build can reach carries delisted names.

Also fixed: a v0.42.5 test required the embedded and the published decision to carry the same computed time, which
the first daily run changed; the suite fails against that run's commit (failure log).

Version 0.42.5 answers an outside buyside audit (Nov 11, 2026): thirteen findings, each reproduced before anything
was changed. Fixed, with a test for each:

- **The gate could undo the risk budget.** The engine found the largest exposure inside the budget, then the evidence
  gate blended the answer back toward 1.00x without checking 1.00x against the budget (budget 3%, gate shut: optimum
  0.45x, final 1.00x, shortfall 6.6%). The final size is now capped at the largest exposure inside the budget, in the
  engine, the walk-forward path and the page. The live call was not affected.
- **The track record now pays for its rebalancing.** The equal-weight book is restored to its weights daily; only
  each January's change of names was charged. Turnover for holding goes from 0.19x to 3.58x a year. Restated on the
  same prices (through Nov 5, 2026): the call's Sharpe 0.775 to 0.767, holding 0.883 to 0.878, full size with the
  call's short 0.950 to 0.926 (this one also now shorts what the ledger logs, in 5% steps). Before and after are on
  the Track record desk.
- **The modelled put is bought before the month it protects.** It was priced at the month's first close and paid on
  the whole month. Bought at the prior month-end close, its variance cut by regime moves from 26% to 38% to 28% to
  39%; the conclusion stands.
- **Paper orders fill after they are written.** The first nine fills used the previous day's close. An order now
  rests until the close of the first exchange session that ends after it was written and fills there; decision,
  order, pricing close and fill each carry a time. The nine fills are kept and marked.
- **One decision on every surface.** Home showed an 84% short, the ledger 85%, search 86%. Every surface now quotes
  the ledger's entry by its id; the exact minimum is a detail beside it.
- **Limits mean limits.** The frontier's 0.5% tolerance is gone (a 25.09% drawdown had passed a 25% cap).
- **An exchange calendar** (`buildout/sessions.py`, standard library, checked against the NYSE's published dates for
  2026 to 2028) for the ledger's effective date, the staleness check and the trader's window.
- **The page loads the published decision** (`data/decision.json`) and prefers it when its content hash differs; the
  Status desk lists which copy of each package is on screen and how its fetch ended.
- **Words.** Expected shortfall is the average loss across the worst 5% of months, not "the worst month in twenty".
  The Execution desk says which system can send an order, to which account, on whose approval.
- **One document.** The published page had two nested document skeletons; it now has one.

Not changed, and open: the candidate universe is still chosen with hindsight (now labelled as such everywhere, and
measured in v0.42.6); the
drawdown cap still comes from a constant-volatility simulation; cash is still proxied by the two-year yield; the
PSQ and VIXY version of the call has no record of its own; prices are still last trade before midnight UTC, not the
official close. The audit's redesign items (five destinations, a smaller payload, typography) are not started.

Version 0.42.4: the trader acts on the call in force today (the newest ledger entry whose effective date has come);
it had taken the newest call, which takes effect tomorrow, so the paper bot was refused on every pass and never
traded. A live broker needs `armed = true` in every mode, and trades in manual mode until the evidence gate opens
(60 paper days with a position, 5 live tickets filled under per-ticket approval; constants in `buildout/trader.py`).
MIT license. Feature freeze: the daily run, the paper bot and fixes continue.

Version 0.42.3 answers an outside review (Nov 11, 2026). The site builds with no packages installed (the Pages job
installs none, and the ledger had imported pandas, so the public site stopped updating at v0.39.1), with a manifest of
what each deployment serves. A refused paper order no longer changes the account. The direct Robinhood route writes
each order to a journal before sending it and never re-sends one whose outcome is unknown: it reconciles by client id
or waits for the person (`broker resolve`). The buys are sent only if the sells raised the cash. The README is a front
page; this file holds the history.

Version 0.42.2 cleans the Databento pull: a ticker has a first date (SPCX and META named other funds earlier), Meta's
FB years are joined on, and the weekend bars that the feed's UTC day boundary creates are dropped.

Version 0.42 adds the trader (`python -m buildout trader`): the model's recommendation turned into orders under a
mandate you write and sign, in manual, supervised or autonomous mode, through a paper account, through Claude holding
Robinhood's Trading MCP, or through Buildout's own client on that MCP. A public paper bot runs it every weekday. See
docs/TRADING.md.

Version 0.41 adds deep reinforcement learning inside a learned market model (`buildout/deeprl.py`, `python -m buildout
deeprl`): a mixture density network as the world model, a policy-value network trained by PPO on 175 million simulated
months, a planner at decision time, all in numpy with hand-written and gradient-checked backward passes. Judged
walk-forward since 1940 it beats holding, the trend rule and the tabular agent (Sharpe 0.88 with planning against
0.64, 0.75 and 0.73); on the nine-name book it never saw, it loses to the call (0.49 against 0.78), and that is on the
page too.

Version 0.40.1 closes v0.40's open items: no heading skips on any desk, a 9 KB favicon and a
logo a quarter of its old size (the page is 200 KB lighter), spacing for the folded sections, and Treasury
yields through Nov 6 in the track build.

Version 0.40 walks the call forward with the live sizing rule itself (`track.live_rule_path`) and marks the ledger's
calls every trading day (`python -m buildout live`, `site/data/live.json`).

Version 0.39.1 is an audit release: two independent reviews of the page and the engine, every finding fixed and pinned in
`tests/test_v39_1.py`; the track build runs in under a minute.

Version 0.39 adds the VIX as a hedge (`buildout/vixhedge.py`: VIX futures, modelled VIX calls and Nasdaq-100 puts,
marked daily on the book) and execution through Robinhood (`buildout/execution.py`, `docs/TRADING.md`): the logged call
becomes a hashed, risk-checked ticket for a Robinhood Agentic account; Robinhood's own Trading MCP places the orders after
a person approves the ticket id (`/rebalance` in Claude Code; `.mcp.json` connects both servers). Buildout holds no
brokerage credential and places nothing. Paper mode by default; `python -m buildout trade status`.

Version 0.38 turns the model into a dated, auditable track record. `buildout/track.py` walks the call forward month by
month with costs and a point-in-time universe, keeps the backtest, the walk-forward and live paper apart, replays named
weeks, and tests the long bond by inflation and policy regime against puts, short Treasuries, gold, cash and a short
basket of weak AI names. `buildout/ledger.py` is an append-only, hash-chained ledger of calls (`ledger/calls.jsonl`;
`python -m buildout ledger verify`), each governing from the next trading day after it is written; `python -m buildout
reproduce --date YYYY-MM-DD` recomputes a day's call and checks it against the ledger. `scripts/snapshot_v38.py` writes
the monthly tear sheet (`site/tearsheet.pdf`). `buildout/levers.py` is the value-creation model behind the Value creation
desk. Every price pull is validated (`buildout/data/validate.py`, `python -m buildout validate`); dependencies are pinned
in `requirements.lock`; a failed daily step opens an issue.

Version 0.36 adds the Reading room (`buildout/assets/sources/*.json`, `scripts/snapshot_sources.py`): about 130 checked
sources in four kinds, each mapped to the theses and desks it bears on and to what it changes; the railway test
(`accounting.required_revenue`) on the Fundamentals desk; a rewritten Desk narrative; and a second accuracy pass.

Version 0.35 adds the cohort to that lens: Apollo, HPS, Ares, Blackstone, Goldman and Golub through the same queue model
(with the inversion checked on two funds that reported both the fill and the requests), and the listed peers ARCC and
BXSL through the same marks and cover. Blue Owl is the outlier on the queue and the sector on marks; OBDC is the only listed fund in the cohort to have cut its dividend.

Version 0.34 adds the private credit lens (`buildout/private_credit.py`, `python -m buildout credit`, MCP tool
`private_credit`): Blue Owl's manager, listed BDC, non-traded funds and campus vehicles read from filings, with three
gauges (the repurchase queue, where 5% divided by requests reproduces the reported fills; the listed fund's discount as an
asset markdown; the dividend's cash cover without PIK), Fitch's sector default rates, a scorecard, the transmission to
the book's names, and what would flip the lens. Nothing in it is a position.

Version 0.33 makes the daily run reliable: a per-site circuit breaker in the downloader, a time limit on every data
step, FRED's official API when `FRED_API_KEY` is set, and plain errors from the filings engine.

Version 0.32 turns the call into a menu (every size-and-hedge mix that meets the book's limits, with its record,
on the Book risk desk) and tests a volatility-managed sizing rule (`buildout/sizing_rules.py`, Moreira and Muir 2017)
the way the engine tests every rule: against the best of twelve variants, on the Nasdaq-100 future since 1999, on QQQ
since 2017 and on the book's own days. It passed on the long record, with the gain in the two long crashes, and is
adopted as a reading beside the limits, not as the size.

Version 0.31 is the PM edition: five navigation groups (Today, Evidence, Markets, Engine, and a Library index for the
other 30 desks), a Desk that leads with the call and its reason, and folded detail on the longest desks (the Digest, the
theses, the release history). Nothing was deleted; deep links open folded sections.

Version 0.30 sizes the book that is held, not an index (`buildout/book.py`, a Book risk desk second in Today, MCP tool
`book_risk`, `python -m buildout book`). Five independent reviews of the whole system found the same gap: the Desk's call
sized the S&P 500 while the book is nine AI names, and no risk number about those names came from their prices. The book
engine runs the nine names' own daily total returns since 2017 (a public GitHub mirror, split-adjusted, dividends on their
ex-dates) against three outside factors: the Nasdaq-100 (QQQ), semiconductors net of the market (SOXX less its
walked-forward beta), and a 20-year par bond rebuilt from the Treasury's daily par yields (downloaded and cached, never
committed). It reports exposures (exponentially weighted betas; SPCX shrinks toward TSLA), ex-ante volatility and its split,
effective independent bets, one-month expected shortfall three ways (historical, filtered historical simulation,
Student-t), a VaR backtest, the size each limit allows (shortfall budget, volatility target, drawdown cap) and the
binding one, the Nasdaq-100 short that would keep every name inside every limit, hedges tested out of sample on the
book's own days, the engine's episodes and scenarios, worst days, the stock-bond correlation under one stated definition,
and liquidity. The Desk's call is now the decision engine's baseline cut to the binding book limit. The same audit fixed
the decision engine's deflated Sharpe (it printed "nan%"), its stress flip point (20% shown, 33% by the page's own
slider), its timing-alpha t (Newey-West, 1.51 to 1.07), Nasdaq-100 puts priced off the VIX instead of the VXN, a filtered
VaR that zero-filled a name before its listing, betas that went silently NaN on short histories, and an AI factor built
from the book itself. The theses carry dated scorecards, three candidate theses join them, and assumed betas give way to
measured ones.

Version 0.29 adds the futures engine (`buildout/futures.py`, a Futures desk in Markets, MCP tool `futures_engine`,
`python -m buildout futures`, and a weekly `futures-run` workflow). It tests the best known futures premia across 39 liquid
CME futures (equity indexes, Treasuries, short rates, currencies, metals, energy, grains, livestock): carry, trend over 1, 3
and 12 months, basis momentum and, where the CFTC is reachable, hedgers' positioning. Each signal is a portfolio across
markets and one over time, net of trading and roll costs, with a roll never treated as a jump. A signal "still works" only
if it passes Benjamini-Hochberg on the equal-weighted cosine test, beats a passive long portfolio of the same markets,
holds in both halves of the record, holds within asset classes (for the across-markets portfolios) and has paid since it
was published. The long record runs on pysystemtrade's published multiple prices (to March 2024, reachable from the
build workspace); Databento's CME Globex bars with contract definitions bring it to now (`DATABENTO_API_KEY`; the pull
refuses any estimate above $5). The two are run separately, not spliced. The desk also reads the book's hedge: what the
Treasury futures pay to hold today and how they did in the S&P 500's worst months, with their correlation by decade.

Version 0.28 adds the filings engine (`buildout/filings.py`, a Filings desk in Research, MCP tool `filings_engine`,
`python -m buildout filings`, and a weekly `filings-run` workflow). It goes for breadth: every stock in the S&P 500 at
each month end from 2009, about five hundred a month, including those that later left the index (two share classes of
one company count once). Signals come from the SEC's own time-stamped data: insiders' open-market purchases and sales
(the Insider Transactions Data Sets, Forms 4 and 5, since 2006), and accruals, gross profitability, asset growth, share
issuance net of splits, earnings surprise and revenue acceleration from XBRL company facts, each value as first filed.
10-K text similarity is opt-in. A value is used in a month only if it was filed before that month's last trading day.
Each signal is tested by its monthly rank IC against the next one and three months' returns. Its p-value comes from the
monthly IC series by the equal-weighted cosine test, which holds its size in short and autocorrelated series, because
stocks share industries and factors. Then come the IC controlled for size, momentum and value, both halves of the record, a long-short portfolio in
the published direction after costs, Benjamini-Hochberg, random signals (persistent noise and factor tilts) and an
insider-purchase event study. An independent audit found that the first design's reassignment permutation called noise
significant on factor-tilted signals, along with a dual-class crash, a weekend month-end look-ahead and split errors. A
second audit of the fixes found an oversized p in short series, an event-study t that ran too large and a crash with no
insider data; all are fixed, and `scripts/calibrate_filings.py` measures the result across synthetic worlds with no edge. The SEC is not
reachable from the build workspace, so the first real run happens on a laptop or in the workflow (`SEC_USER_AGENT` must
be set). Until then the desk shows the design, the validation and the calibration.

Version 0.27 adds a nowcast (`buildout/nowcast.py`, a Nowcast desk beside the call, MCP tool `nowcast`,
`python -m buildout nowcast`). It goes where edges are usually found: facts published before the reports they predict,
aimed at the book. Inputs are TSMC's monthly revenue (153 months read from TSMC's site, each checked against TSMC's printed
growth), the hyperscalers' capital spending, and peers' reports. The tests cover 552 company quarters of the book and the AI
supply chain since 2017, each dated by its earnings release (599 releases: SEC Form 8-K Item 2.02 dates plus 100 read from
the companies' releases, a sample of 36 confirmed independently). Revenue nowcasts are walked forward against persistence.
Permutation tests then ask whether the market had priced each signal by report day, within seasons (under three ways of
drawing a season) and across quarters, with 240 placebo signals beside them. Nothing passes the multiple-testing cut
across 51 hypotheses. The best lead: peers' recent reports cut the error of forecasting chip makers' revenue by 19% (t 2.4
clustered by quarter). TSMC and capital spending add nothing beyond persistence, and the tests could only see
correlations of about 0.2 or more. So the desk forecasts each holding's next report and does not call it a trade. Two
independent audits reshaped it before release: they replaced volume-based report dating with the actual release dates,
and showed that two strong-looking chip results depended on how a season was drawn.

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
one sparse 9,429 by 9,429 matrix (`Mind.walk_matrix`); many questions think at once as one product with a matrix of
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

# Buildout

**A risk, hedge and sizing engine for a concentrated AI-infrastructure equity book, built to make one decision a
day and show its work.** Nine names (MSFT, AMZN, GOOGL, META, NVDA, AVGO, TSLA, SPCX, ORCL), a model book, not
personal positions.

[Live site](https://jamesplacco.github.io/buildout/) · [Changelog](CHANGELOG.md) · [Trading and the mandate](docs/TRADING.md)

## The decision

After each exchange session (the run is at 11:17 UTC, Tuesday to Saturday), the daily run answers three questions on
data through that session's close; the answer takes effect on the first session after the day it is written:

1. **How big?** Volatility targeting and a drawdown-constrained leverage cap set the size; fractional Kelly reports
   the excess return you would need to believe to justify it.
2. **How much hedge?** Minimum-variance hedge ratios judged out of sample, gated by the stock-bond correlation regime.
3. **When does the hedge stop working?** What long bonds and Nasdaq-100 shorts actually did on the book's worst days
   in each regime.

The answer is written to a hash-chained ledger (`ledger/calls.jsonl`) before it takes effect on the next trading
day, and marked to market every day after (`site/data/live.json`).

## What the record says (and where it disappoints)

- Walked forward from 2018 with the live rule itself, after costs: the call earns a Sharpe of 0.77 with a 23% worst
  drawdown; holding the nine names earns 0.88 with 52%; full size with the call's Nasdaq-100 short earns 0.93 with
  24%. Sizing down protects, at a cost in Sharpe ratio, and that held on index baskets other people chose before
  2018 (the Nasdaq-100, a semiconductor fund, the first AI theme fund). The 0.93 did not carry over: it is the nine
  names beating the index by about 8% a year, which a candidate list written in 2026 knew (the universe checks on
  the Track record desk, v0.42.6). (Restated in v0.42.5 after an outside audit: the daily
  trades that hold the weights are now charged. Before and after are on the Track record desk. The names come from
  a candidate list chosen in 2026, so this is a walk-forward rule on a retrospectively selected universe.)
- How sure is the size (v0.44, the Book risk desk). The size is 0.53x because a modelled one-year drawdown cap of
  25% binds, and that number came from one model. With fat-tailed shocks, or the book's own days redrawn in runs,
  the cap allows the same 0.53x. With volatility that moves, a bad year at 0.53x is 29% down and the cap allows
  0.45x; with no assumed equity premium, 0.50x; at the worst year's volatility, 0.36x. The random draws alone move
  the answer by about 0.01x. Walked forward, the call's worst one-year window on the nine names was 23.3%, inside
  the cap in all 93 windows; on the Nasdaq-100 it was 25.3% (11 windows, one stretch) and on the first AI theme fund
  27.1% (4 windows, one stretch). Nine years cannot confirm a 1-in-20 number. The call is unchanged.
- A deep RL sizer trained inside a learned market model beats holding, the trend rule and a tabular agent on the
  S&P 500 since 1940 (Sharpe 0.88 against 0.64), and loses on this book (0.49 against 0.77). Both are published.
- Every number that turned out wrong is in the failure log on the Memos desk, with its cost and fix.

## Run it

```bash
pip install -e ".[dev]"
pytest -q                                  # about 830 tests, no data or keys needed
python -m buildout demo                    # the full engine on a synthetic market with planted answers
python scripts/build_site.py site _site    # the site, standard library only; open _site/index.html
```

With a Databento key (`DATABENTO_API_KEY`) and a free FRED key (`FRED_API_KEY`), `python -m buildout run --config
config.toml --out out` runs on real data; see "Local use" below.

## Limits

- One book, one decision a day, long only plus index shorts and a VIX sleeve. It does not pick stocks.
- Backtests start in 2018; the live record starts Nov 4, 2026 and is days old.
- The drawdown cap is a modelled 95th percentile, not a stop. Under a model where volatility moves, the same size
  has a bad year of 29%, not 25% (`buildout/sensitivity.py`).
- The Databento daily close is the last trade before midnight UTC, not the official close (stated in every report).
- The trader can act for a person under a signed mandate (docs/TRADING.md). Paper is the default. A live broker
  trades only on per-ticket approval until the paper bot has held a position for 60 trading days and 5 live tickets
  have filled under approval; that gate is in code. The direct Robinhood route is untested against the live endpoint.

## License

MIT. See [LICENSE](LICENSE). Research and tooling, not investment advice.


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

Two pages are built from the same sources in `site/src/` (v0.43):

- **`site/core.html`, the site's front page.** Fifteen desks in four groups, and nothing the call does not depend
  on: **Call** (Home, Desk, Book risk, Decision engine, Hedge test), **Record** (Track record, Execution),
  **Evidence** (Inventory, Memos and the failure log, Fundamentals), **Method** (How it works, Parameters, Data
  lineage, Architecture and status, Appendix). About a third of the full page's size.
- **`site/page.html`, the library.** All sixty-six desks: the core fifteen and every research desk built along the
  way. Published as `library.html`; a link on the core page to a desk it does not carry opens the library there.

What the core page leaves out is decided by rendering, not by hand. `scripts/prune_core.py` replaces a file with
inert stand-ins, opens the page in a browser, uses every core desk, and leaves the file out only if nothing a reader
sees or does changes; `tests/test_v43.py` holds every core desk to the same text, tables and charts on both pages.
The list is `scripts/core_stubs.json`.

The table below describes the library's older desks. Market figures carry a source and a date;
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
python scripts/assemble_page.py           # writes site/page.html and site/core.html; --check fails CI if either is stale
python scripts/prune_core.py --code       # only when a core desk starts using something new: re-decides what the core page leaves out
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
| | `sensitivity.py` | How sure is the size (v0.44): the one-year drawdown quantile and the size inside the cap under fat tails, a stationary bootstrap of the book's own days, moving volatility, no premium and other volatility levels; the size with one setting changed at a time; the spread from the random draws. `track.window_drawdowns` counts what the walk-forward did against the cap. Never changes the call |
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

- v0.44: the sensitivity block sizes the same book as the call (the engine's row is the engine's own function);
  this module's simulator with normal shocks agrees with the engine to sampling error; a looser limit never shrinks
  the book; a failure in the block is recorded and never touches the call; one fall fills a year of overlapping
  windows and is counted as one stretch; the page's readings are asserted against the published numbers.
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

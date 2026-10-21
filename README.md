# Buildout

Regime-aware risk, hedge and sizing engine for a concentrated AI-buildout equity book
(hyperscalers, NVDA/AVGO, TSLA, SPCX) with long Treasuries as the candidate hedge.

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
| Fundamentals: capex, cash flow, debt from SEC filings | variable `SEC_USER_AGENT` | `site/data/capex.json` |
| Status: which files exist, how fresh each is, sanity checks (always runs, even after a failure) | nothing | `site/data/status.json` |

Steps without their secret or variable skip themselves with a notice. Results are committed back to `main`
by `github-actions[bot]`. Only derived analytics are committed; raw market data never enters git.

### One-time setup

1. **Databento key.** Settings > Secrets and variables > Actions > New repository secret:
   name `DATABENTO_API_KEY`, value `db-...`. The next run prices the pull (`buildout cost`) and then runs the book.
2. **SEC contact (optional).** Same page, Variables tab: `SEC_USER_AGENT` = `Your Name you@example.com`.
   The SEC requires a real contact on every request.
3. **Public page (optional).** Make the repository public, set Settings > Pages > Source to
   "GitHub Actions", and add the variable `PUBLISH_PAGES` = `true`. `pages.yml` then redeploys the page
   after every daily run.

## The page

`site/page.html` is one self-contained page with ten desks. Market figures carry a source and a date;
tiles marked Live are replaced by the daily run's numbers, and a Stale badge appears when a file is more
than three weekdays old. The bond, curve, option, hedge and sizing tools run in the browser with the same
formulas as the engine (`analytics/bonds.py`, `curve.py`, `options.py`), checked against it to 1e-9.

| Desk | What it holds |
|---|---|
| Desk | Start-here cards, signals board (nine signals, each with a rule and an action), key levels, Dalio regime map, stock-bond correlation gauge, engine readout, calendar |
| Rates | 2026 Treasury curves, spreads, forward curve with one-year carry and roll-down, real yield vs breakeven, bond calculator, DV01-neutral curve trade |
| Options | Black-Scholes pricer with Greeks and an implied-volatility solver, hedge payoff builder, spot-vol revaluation grid, tail-hedge budget |
| Hedges | Fifteen hedges graded across six scenarios, six scenario playbooks, the two kinds of AI selloff, TLT hedge lab, futures hedge calculator (NQ/MNQ against ZN/TN/ZB/UB), Monte Carlo sizing lab |
| Securities | Capital structure, seven risk drivers, thirty security cards |
| Insurers | Float and duration matching, the Hyperion financing chain, private credit exposure, six balance sheets |
| Theses | Eight theses with evidence, expression, hedge, kill criteria and the strongest case against each; live SEC capex vs cash flow |
| Lenses | Taleb, Dalio, Marks, Druckenmiller, Soros, Burry, Buffett and Munger, BowTiedBull, Kobeissi, Six Sigma, Walters |
| Engine | Pipeline, system status from the daily run, self-tests, model book, data plan, roadmap |
| Appendix | Glossary (86 terms, linked from the text), methods and formulas, 30 hard questions, model risk register, data dictionary, episode atlas (15 stresses since 1987), reading list, checklists, changelog |

Navigation: `/` or Ctrl/Cmd+K searches every desk, term, security, thesis, episode and question; `?` lists
the shortcuts; digits 1 to 0 open the desks; any element id is a deep link (`#g-dv01`, `#ep-covid-2020`,
`#faq-12`). Print all (Appendix) prints every desk with every question answered.

### Editing the page

The page is assembled from `site/src/` (`head.html`, `body.html`, and `math.js`, `ui.js`, `data.js`,
`reference.js`, `views.js` inside one strict-mode script). Edit the parts, then:

```bash
python scripts/assemble_page.py           # writes site/page.html; --check fails CI if it is stale
python site/tests/stress.py               # browser suite (needs: pip install playwright; playwright install chromium)
```

The browser suite builds the site from engine-generated fixtures and feeds it hostile files (wrong shapes,
truncated JSON, stale dates, absurd yields), extreme tool inputs, keyboard-only use, deep links, 320 to
1920px widths and print. It fails on any script error, any NaN, undefined, Infinity or null on screen, any
sideways scroll, any panel that did not render, and (with poppler's `pdftotext`) any text printed over text.

## Local use

```bash
pip install -e ".[databento,dev]"
pytest                                    # 62 tests, no data needed
python -m buildout demo                   # full run on a synthetic market with planted answers
python -m buildout macro --out out        # free FRED regime monitor

export DATABENTO_API_KEY=db-...           # never commit it
python -m buildout cost --config config.toml   # price the pull before paying for it
python -m buildout run  --config config.toml --out out
python -m buildout capex GOOGL MSFT AMZN META ORCL TSLA --ua "Your Name you@example.com"
python -m buildout kalshi KXFED           # prediction-market Fed path (series names change; check Kalshi)
```

`config.toml` is the model book the page shows. Keep real positions in `config.private.toml` (git-ignored)
and run with `--config config.private.toml`.

## Data

| Source | What | Cost |
|---|---|---|
| Databento | Daily (and minute) bars for equities and ETFs, split and dividend adjustment factors, CME Treasury futures (ZN, UB) | Pay-as-you-go historical; new accounts get $125 credit |
| FRED | Nasdaq-100, the Treasury curve from 1 month to 30 years, TIPS real yields, breakevens, term premium, IG and HY spreads, VIX, broad dollar, Brent and WTI | Free |
| SEC EDGAR | Quarterly operating cash flow, capex, free cash flow, debt from XBRL filings | Free (contact required) |
| Kalshi | Prediction-market probabilities (Fed path, CPI, recession) | Free public endpoints |

## Modules

| Layer | Module | Does |
|---|---|---|
| Data | `data/databento_source.py` | Adjusted closes (applied, default-option, primary-listing factors); roll-adjusted futures returns; explicit end dates |
| | `data/fred_source.py`, `edgar_source.py`, `kalshi_source.py` | Macro, fundamentals (YTD facts de-cumulated to quarters), prediction markets |
| | `data/synthetic.py` | Regime-switching market with known betas and regimes, for testing |
| Monitor | `macro.py` | Free daily regime read: Nasdaq-100 vs a 20-year par bond rebuilt from DGS20, back to 1993; curves, spreads, levels; episode atlas; per-series failures reported, not fatal |
| | `status.py` | Run status: files present, valid and fresh; sanity checks on correlations, hedge ratios, yields, gross and VaR |
| Exposure | `analytics/exposures.py` | Recursive exponentially weighted betas to market, AI and rates factors; IPO shrinkage |
| Regime | `analytics/regime.py` | Stock-bond correlation with hysteresis; worst-day shock table |
| Hedge | `analytics/hedge.py` | Min-variance ratios, four policies judged out of sample, DV01 futures sizing |
| Rates | `analytics/bonds.py`, `curve.py` | Price, yield, duration, convexity; monotone cubic par curve, bootstrap, forwards, carry and roll-down, futures DV01 via CTD and conversion factor |
| Options | `analytics/options.py` | Black-Scholes with dividends, Greeks, implied volatility with no-arbitrage bounds |
| Risk | `analytics/vol.py`, `risk.py` | EWMA, GARCH(1,1), HAR-RV; factor-model covariance, risk shares, historical and filtered-HS VaR |
| Sizing | `analytics/sizing.py` | Vol targeting, shrunk fractional Kelly, equal risk contribution, drawdown-capped leverage, trim bands |
| Stress | `analytics/stress.py` | Historical episodes (2020, 2022, 2024, 2025, 2026) and hypothetical factor shocks |
| Proof | `analytics/backtest.py`, `metrics.py`, `signals.py` | Dollar-exact backtester, deflated Sharpe, purged walk-forward model judged on calibration |
| Page | `site/src/`, `scripts/assemble_page.py`, `scripts/build_site.py` | Ten-desk research site assembled into `site/page.html` (reads `site/data/*.json`); `build_site.py` wraps it for GitHub Pages |

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

## Principles

- Decisions at the close of t earn returns from t+1. Nothing else is allowed.
- Predict risk before return. Volatility and correlation forecasts are where the signal is.
- A hedge removes at most rho squared of variance. At a -0.3 correlation that is 9%. Long bonds are a
  scenario hedge (growth scares), not a variance hedge; size them to the scenario.
- Every backtest result carries a deflated Sharpe that charges for the number of variants tried.

Research tool, not investment advice.

# Buildout

**A risk, hedge and sizing engine for a concentrated AI-infrastructure equity book, built to make one decision a
day and show its work.** Nine names: MSFT, AMZN, GOOGL, META, NVDA, AVGO, TSLA, ORCL and SPCX (SpaceX, listed on
Nasdaq in June 2026). A model book, not personal positions.

[Live site](https://jamesplacco.github.io/buildout/) · [Changelog](CHANGELOG.md) · [Trading and the mandate](docs/TRADING.md) · [Reference](docs/REFERENCE.md)

## The decision

After each US session the daily run answers three questions on data through that session's close:

1. **How big?** Three limits, each measured on the nine names' own daily prices: a one-month expected-shortfall
   budget (12%), a volatility target (20%) and a one-year drawdown cap (25%, a modeled 95th percentile). The
   tightest one sets the size.
2. **How much hedge?** The smallest Nasdaq-100 futures short, in 5% steps, that keeps every name at full size
   inside the same limits; and whether a long-bond hedge is on, which the stock-bond correlation regime decides.
3. **When does the hedge stop working?** What long bonds and Nasdaq-100 shorts actually did on the book's worst days
   in each regime.

The answer (the size, the short alternative, the bond hedge) is written to a hash-chained ledger
(`ledger/calls.jsonl`) before it takes effect, and marked to market every day after (`site/data/live.json`).

**When it runs.** Scheduled for 11:17 UTC, Tuesday to Saturday; GitHub starts scheduled jobs late, and runs have
started between about 16:00 and 20:00 UTC, during the US session. The ledger's timestamp is the record. A call
governs from the first session whose prior close came after it was written.

## What the record says (and where it disappoints)

The daily run rebuilds the walk-forward record (`site/data/track.json`), so its figures move a little every day. The
ones below are as of Nov 17, 2026; the site carries the current run and says the date it runs through. The universe
checks, the one-year windows and the deep RL comparison are rerun only at a release and are as of Nov 5, 2026.

- Walked forward from 2018 with the live rule itself, after costs: the call earns a Sharpe of 0.78 with a 23% worst
  drawdown; holding the point-in-time nine (the nine most traded of sixteen candidates each January, which are not
  always today's nine) earns 0.89 with 52%; full size with the call's Nasdaq-100 short earns 0.94 with 24%. Sizing
  down protects, at a cost in Sharpe ratio, and that held on index baskets other people chose before 2018 (the
  Nasdaq-100, a semiconductor fund, the first AI theme fund). The short's edge did not carry over: it is the nine
  names beating the index by about 8% a year, which a candidate list written in 2026 knew (the universe checks on
  the Track record desk, v0.42.6). (Restated in v0.42.5 after an outside audit: the daily trades that hold the weights
  are now charged. Before and after are on the Track record desk. The names come from a candidate list chosen in
  2026, so this is a walk-forward rule on a retrospectively selected universe.)
- How sure is the size (v0.44, the Book risk desk). The size is 0.53x because a modeled one-year drawdown cap of
  25% binds, and that number came from one model. The alternatives are re-simulated every day; as of Nov 17, 2026:
  with fat-tailed shocks the cap allows 0.53x, and with the book's own days redrawn in runs 0.55x; with volatility
  that moves, a bad year at 0.53x is about 30% down and the cap allows 0.44x; with no assumed equity premium,
  0.50x; at the worst year's volatility, 0.37x. The random draws alone move the answer by about 0.01x. The Book
  risk desk carries today's figures. Walked forward, the call's worst one-year window on the nine names was 23.3%,
  inside the cap in all 93 windows; on the Nasdaq-100 it was 25.3% (11 windows, one stretch) and on the first AI
  theme fund 27.1% (4 windows, one stretch). Nine years cannot confirm a 1-in-20 number. The call is unchanged.
- A deep RL sizer trained inside a learned market model beats holding, the trend rule and a tabular agent on the
  S&P 500 since 1940 (Sharpe 0.88 against 0.64), and loses on this book (0.49 against 0.77 for the call, on the
  record through Nov 5, 2026). Both are published.
- The live record started Nov 4, 2026 and is days old: too short to read anything into.
- Every number that turned out wrong is in the failure log on the Memos desk, with its cost and fix.

## How the call is produced, and from which data

Two runs price the book every day. Only the first sets the call.

| Step of the daily run | Reads | Writes | Role |
|---|---|---|---|
| `python -m buildout book` | The nine names' public daily closes, volumes and cash dividends (a GitHub mirror, `yennanliu/finance_data`), validated before anything is sized; the Treasury's par yields | `site/data/book.json` | **Sets the call**: the three limits, the size, the menu of size-and-short mixes |
| `python -m buildout ledger append`, then `ledger verify` | `site/data/book.json` | `ledger/calls.jsonl` | Logs the call, one hash-chained entry per new data date |
| `python -m buildout live` | The ledger and the same closes | `site/data/live.json` | Marks every logged call to market |
| `python -m buildout trader --once --paper` | The call in force | `paper/`, `site/data/paper.json` | The public paper bot, a model account |
| `python -m buildout run` | Databento bars (needs `DATABENTO_API_KEY`) | `site/data/report.json` | **A cross-check run**: a different model on a second data source. It never sets the call, and the site labels its tiles |
| `python -m buildout decide` | 156 years of monthly data | `site/data/decision.json` | The S&P 500 baseline (1.00x while its evidence gate is shut) that the book's limits cut |

The walk-forward record and the tear sheet (`site/tearsheet.pdf`) come from `buildout/track.py` through
`scripts/snapshot_v38.py`: the daily run rebuilds both (`site/data/track.json`), and a release reruns the slower
studies beside them. The site has two pages: the front page (`site/core.html`, fifteen desks: the call, the
record, the evidence, the method) and the library (`site/page.html`, the same fifteen plus fifty research desks). A
library desk drawn from a snapshot built into the page, and not from a daily file, says so under its title.

## Run it

```bash
pip install -e ".[dev]"
pytest -q                                  # about 1,040 tests, no data or keys needed
python -m buildout demo                    # the full engine on a synthetic market with planted answers
python -m buildout book --out out          # the run that sets the call: no key, public daily closes
python scripts/build_site.py site _site    # the site, standard library only; open _site/index.html
```

With a Databento key (`DATABENTO_API_KEY`) and a free FRED key (`FRED_API_KEY`), `python -m buildout run --config
config.toml --out out` runs the cross-check on Databento bars. Setup, every command, the MCP server, the modules and
what the tests prove are in [docs/REFERENCE.md](docs/REFERENCE.md).

## Check it yourself

- **The call.** `python -m buildout book --out out` needs no key. On the same day's closes it prints the size the
  ledger logged (0.533066x on Nov 17, 2026), and `out/book.json` carries what the price validation found, including a
  comparison of the newest closes with a second source.
- **The ledger.** `python -m buildout ledger verify` recomputes the hash chain; `ledger show` lists every call with
  the session it governs from. The chain shows an edit that was not rehashed. So that it also shows a rewrite, the
  daily run signs the ledger's SHA-256 into Sigstore's public transparency log:
  `gh attestation verify ledger/calls.jsonl --repo jamesplacco/buildout` (from the first run after v0.47).
- **The record.** `python -m buildout track --out out` rebuilds the walk-forward from public prices in about three
  minutes; the figures above are that file's.
- **The misses.** The failure log on the site's Memos desk lists every number that was wrong, what it cost and what
  changed; CHANGELOG.md has the same by release.

## How it was built

Built by one person directing AI coding agents (Claude), one release at a time: about 41,000 lines of engine, about
1,040 tests, and 49 releases in the changelog since October 21, 2026. The method is the point. The figures behind
the call are computed by code that tests check against planted answers or independent calculations; every release
that changed a published number restated it beside the old one; and the code has been through four audits whose
findings were each reproduced before they were fixed (v0.42.3, v0.42.5, v0.44.1 and v0.47, the last by four
independent reviews of the math, the record, the data pipeline and the published claims). What the audits found
is published, not smoothed over.

## Limits

- One book, one decision a day: long only, plus an index short. The executable version for a cash account adds a
  VIX sleeve (docs/TRADING.md). It does not pick stocks.
- Backtests start in 2018; the live record started Nov 4, 2026 and is days old.
- The universe was chosen in 2026. The walk-forward ranks sixteen candidates point in time, but the list itself is
  hindsight, and no source this build can reach carries delisted names.
- The drawdown cap is a modeled 95th percentile, not a stop. Under a model where volatility moves, the same size
  has a deeper bad year than 25% (the Book risk desk; `buildout/sensitivity.py`).
- The call is sized on public daily closes from a third-party mirror, validated each run. The Databento cross-check
  uses the last trade before midnight UTC, not the official close (stated in every report).
- The site's research library reads beyond the call: rules for puts, credit protection and an inflation sleeve are
  shown on Today's call as research readings. None is in the ledger, the record or the paper account.
- The trader can act for a person under a signed mandate (docs/TRADING.md). Paper is the default. A live broker
  trades only on per-ticket approval until 60 sessions have closed with the paper bot holding a position under its
  current rule and 5 live tickets have filled under approval; that gate is in code. No live order has been placed,
  and the direct Robinhood route is untested against the live endpoint.

## License

MIT. See [LICENSE](LICENSE). Research and tooling, not investment advice.

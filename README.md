# Buildout

**A daily rule for how much of a nine-stock AI portfolio to hold, and how to hedge it, so that a bad year stays
inside a 25% loss limit.** The stocks: Microsoft, Amazon, Alphabet, Meta, Nvidia, Broadcom, Tesla, Oracle and SpaceX
(SPCX, listed June 2026). A model book, not personal positions, and not investment advice.

[Live site](https://jamesplacco.github.io/buildout/) · [Changelog](CHANGELOG.md) · [Trading and the mandate](docs/TRADING.md) · [Reference](docs/REFERENCE.md)

## What it does

After each US trading day it makes one call, in three steps:

1. **Measure the risk** of the book held in full, on the nine stocks' own daily prices.
2. **Apply three limits**: volatility under 20%, the loss in a bad month under 12%, the loss in a bad year under
   25%. The tightest one sets the share of the book to hold.
3. **Offer a hedged alternative**: hold all of it with a Nasdaq-100 futures short big enough to meet the same
   limits. Treasuries are added only while they move opposite to stocks, which they have not since 2021.

No price forecast is involved. A forecasting model exists and is tested every month; it has not beaten simply
holding, so it gets no say. Each call is written to a tamper-evident ledger (`ledger/calls.jsonl`) before it takes
effect, and a paper account follows it.

## What the record says

Figures are as of Nov 19, 2026. The site carries the current run.

| Feb 2018 to Nov 2026, after costs | Return a year | Worst loss | Sharpe ratio |
|---|---|---|---|
| The rule: hold what the limits allow | +14.8% | 23% | 0.77 |
| The rule with the index short | +17.2% | 24% | 0.93 |
| The nine stocks held in full | +29.7% | 52% | 0.88 |
| Nasdaq-100 | +17.2% | 35% | 0.67 |

- **This is a simulation, not an account.** Each month is sized from what was known at the time and trading costs
  are charged. The live record began Nov 4, 2026 and is too short to judge.
- **The rule buys smaller losses, at a cost.** It cut the worst loss by more than half and earned less per unit of
  risk than holding in full. The same trade-off held on baskets other people chose (the Nasdaq-100, a semiconductor
  fund, an AI theme fund).
- **The stocks were picked with hindsight.** The simulation chooses nine each January from a candidate list of
  sixteen, but that list was written in 2026. The index short looks best only because these nine beat the index by
  about 8% a year. Do not count on that repeating.
- **Mistakes are published.** Restated in v0.42.5 and again since, after outside audits: every wrong number, what
  it cost and what changed are in the failure log (the Memos desk) and in the changelog.

## The site

Two pages from one source. The front page (`site/core.html`) is a five-page brief: Home, Today's call, Book risk,
Track record, How it works. The library (`site/page.html`) is the full research: sixty-five desks, every table, test
and formula.

## Run it

```bash
pip install -e ".[dev]"
pytest -q                                  # about 1,080 tests, no data or keys needed
python -m buildout book --out out          # the run that sets the call: no key, public daily closes
python -m buildout ledger verify           # recompute the ledger's hash chain
python scripts/build_site.py site _site    # the site, standard library only; open _site/index.html
```

Every command, the daily run step by step, the data sources, the modules and the limits of the method are in
[docs/REFERENCE.md](docs/REFERENCE.md). Live trading is off by default and gated in code
([docs/TRADING.md](docs/TRADING.md)); no live order has been placed.

## License

MIT. See [LICENSE](LICENSE). Research and tooling, not investment advice.

# Trading the call through Robinhood

Buildout decides **what** to trade and **whether it is allowed**. Robinhood's own Trading MCP places the orders, in the
separate Robinhood Agentic account, after you approve the ticket. Buildout never holds a brokerage credential and has no
tool that places, routes or cancels an order.

```
Buildout call (logged in ledger/calls.jsonl)
  -> trade_plan: target holdings, limit orders, every check, a hashed ticket id   (Buildout MCP, nothing placed)
  -> you approve the ticket id in the conversation
  -> the assistant places each order                                                (Robinhood Trading MCP, OAuth)
  -> record_fills: fills checked against the ticket, hash-chained private log      (Buildout MCP)
```

## One-time setup

1. In the Robinhood app, open an **Agentic account** (a separate self-directed individual account) and fund it with
   only what the model may trade. Agents can trade nothing else.
2. In Claude Code, from this folder: `.mcp.json` already lists both servers. Run `claude`, type `/mcp`, choose
   `robinhood-trading` and sign in through Robinhood's OAuth page. (Claude Desktop: Settings, Connectors, add the custom
   connector `https://agent.robinhood.com/mcp/trading`.)
3. Keep `mode = "paper"` until a week of paper tickets look right. Then, in `config.private.toml` (git-ignored):

```toml
[trading]
mode = "live"
```

## Every rebalance

Run `/rebalance` in Claude Code. It reads the Agentic account and quotes from Robinhood, asks Buildout for a ticket,
shows it to you, and places orders only after you approve that ticket id.

## What Robinhood's Agentic account allows, and how the call maps to it

| The call says | In the Agentic account | Why |
|---|---|---|
| Hold the book at the call's size | The nine names, long, at that share of equity | no margin borrowing: everything long stays at most 98% of equity |
| Short Nasdaq-100 futures (hedged variant) | PSQ, long (ProShares Short QQQ, -1x daily) | no short selling and no futures for agents |
| VIX sleeve | VIXY, long (short-term VIX futures ETF) | VIX futures are not open to agents; VIXY holds them |
| Puts and VIX calls | not automated | single-leg long options are allowed, but the planner does not trade them yet |

## The checks on every ticket

Halt switch (`private/HALT` or `BUILDOUT_TRADING_HALT`), Agentic account only, the call's data at most 3 business days
old, the call logged in the verified ledger before trading, every symbol on the allowlist, quotes for every symbol and
spreads under 1%, no sale larger than the holding, everything long at most 98% of equity, cash at least 2%, each order at
most 25% of equity and $25,000, turnover at most 60% of equity (100% for a first build), one executed ticket a day.
Tickets expire after 15 minutes. Change the limits under `[trading]` in `config.private.toml`.

## Stop everything

`touch private/HALT` (or `python -m buildout trade halt`). In the Robinhood app you can also disconnect the agent with one tap.

## The VIX sleeve, honestly

From Feb 2006 to Mar 2024, long VIX futures lost about 20% a year on average and lost money in about two months in three.
They paid in crashes: at 10% of the book's value they cut the Feb 19 to Mar 23, 2020 loss from 29% to 18%. They did
almost nothing in the slow 2022 bear market, where the index short did the work. The default sleeve is 5% of equity
(a little under 1% a year of expected cost on the 2017 to 2024 record); set `vix_share = 0` to turn it off.

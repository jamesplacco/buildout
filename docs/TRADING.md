# Trading the call: the trader, the mandate, and Robinhood

Buildout decides **what** to trade and **whether it is allowed**. Since v0.42 it can also act: the trader
(`python -m buildout trader`) takes the model's recommendation, builds the risk-checked ticket, checks it against a
mandate you write and sign, and executes through a broker in one of three modes. Buildout's MCP server itself still
places no order and holds no credential; the trader does, under the mandate, through the broker you chose.

```
Buildout call (logged in ledger/calls.jsonl)
  -> the trader: halted? in the window? acted today?                                    (one pass)
  -> account and quotes from the broker
  -> execution.plan: target holdings, limit orders, every check, a hashed ticket id
  -> mandate.authorize: the ticket against your limits (order, day, account, losses)
  -> the mode gate:   manual      wait for your approval of this ticket id
                      supervised  wait for an approval, or act under a standing one
                      autonomous  act, if the mandate is armed
  -> sells first, then buys; each order polled to its fill or cancelled at expiry
  -> record_fills: fills checked against the ticket, hash-chained log; journal; digest
```

## The three modes

| Mode | A ticket that passes every check | Approve with |
|---|---|---|
| `manual` (default) | is staged and waits; it executes on a later pass once you approve its id | `python -m buildout trader --approve tkt-…` or the MCP tool `approve_ticket` |
| `supervised` | is staged; executes once approved, or at once under a standing approval you gave for a window | `--standing 120` (minutes), or `approve_ticket` with `ticket_id = "standing"` |
| `autonomous` | executes without asking, if the mandate is armed; you read the digest and the journal | nothing; `trade halt` stops it |

## The three routes (brokers)

| `broker` | Who places the orders | Credential | Status |
|---|---|---|---|
| `paper` | the paper broker, in a model account. An order rests until the close of the first exchange session that ends after it was written and fills at that close with a 5 bp half-spread (v0.42.5; before, at the limit against the last stored close, a price that could be older than the order) | none | running: the public paper bot (`paper/`, from the daily workflow, Tuesday to Saturday at 11:17 UTC on the prior session's close) and private rehearsals |
| `assistant` | the assistant that holds Robinhood's Trading MCP (Claude with the Robinhood connector) places exactly what the trader hands it and reports the fills through `record_fills` | Robinhood's OAuth, held by the assistant | works today |
| `robinhood_mcp` | Buildout's own JSON-RPC client on `https://agent.robinhood.com/mcp/trading`, OAuth 2.1 with PKCE in the standard library | Robinhood's OAuth, tokens in `private/` (mode 600) | built; Robinhood has not published its tool names, so `python -m buildout broker probe` lists them and you fill `private/broker.toml`; untested against the live endpoint from this build |

What Robinhood says (support pages read Nov 8, 2026): the agent trades only in the Agentic account; "before your agent
takes action, you can review what it's about to do," but "if you've asked your agent to take action without asking
your approval, it can place trades without your confirmation"; and "you are ultimately responsible for the trades your
AI agent places in your account." The trader's modes sit inside those terms.

## The mandate (`private/mandate.toml`)

`python -m buildout trader --init` writes a template. Edit it by hand; nothing in Buildout can write it for you. The
mandate's hash is written into every ticket and journal line.

```toml
[mandate]
mode = "manual"            # manual | supervised | autonomous
armed = false              # nothing live is sent until true, over signed_by and signed_on
broker = "paper"           # paper | assistant | robinhood_mcp
signed_by = ""
signed_on = ""
max_order_usd = 10000.0
max_order_pct = 0.25
max_day_turnover_pct = 0.60
max_gross = 0.98
cash_floor = 0.02
max_equity_usd = 250000.0  # above this the trader refuses: the mandate was written for less
halt_drawdown = 0.20       # from the account's recorded peak
halt_day_loss = 0.05       # from the previous day
min_days_between_tickets = 1
approval_ttl_min = 240
window_start = "09:45"     # New York
window_end = "15:45"
quiet_days = []
notes = ""                 # an armed autonomous mandate must say why unattended trading is wanted
```

## The evidence gate (in code, not in the mandate)

A live broker trades in **manual** mode, whatever the mandate says, until two records exist:

1. **60 trading days of the paper bot holding a position** (`paper/trader/`, committed by the daily run; days before
   its first filled ticket do not count).
2. **5 live tickets filled after you approved that ticket's id** (`private/trader/journal.jsonl` and
   `private/fills.jsonl`). Standing approvals and paper fills do not count.

Until then a supervised or autonomous mandate on a live broker behaves as manual: each ticket is staged, the pass
lists what is missing, and a standing approval does not open it. `python -m buildout trader --status` and the MCP tool
`trader_status` show the count. The thresholds are constants in `buildout/trader.py` (`PAPER_DAYS_REQUIRED`,
`LIVE_MANUAL_TICKETS_REQUIRED`), so loosening them is a code change with a commit behind it. This is a guard against
drifting into unattended trading before the record supports it; it is not a security boundary, since the person who
owns the machine owns the files.

A live broker also needs `armed = true` in every mode, manual included.

## Going autonomous, in order

1. **Paper**: nothing to do. The public paper bot runs from the daily workflow in `paper/`; a private rehearsal is
   `python -m buildout trader --once` on the default mandate. The trader acts on the call in force today (the newest
   ledger entry whose effective date has come), not the call written today, which takes effect tomorrow.
2. **Live, manual** (this is where the gate keeps you until the evidence is in): `broker = "assistant"`,
   `armed = true`, your name and the date. In Claude Code, `/rebalance` calls `trading_recommendation` with the
   account and quotes from Robinhood; the ticket is staged; you approve its id; the assistant places the orders and
   records the fills. Five filled tickets and sixty paper days open the gate.
3. **Supervised**: `mode = "supervised"`; give a standing approval before a session (`--standing 120`) and let
   `/autotrade` run without a question inside that window.
4. **Autonomous**: `mode = "autonomous"` and the reason in `notes`. Set Robinhood's own agent permission to act
   without confirmation. Schedule the pass: a Claude scheduled task running `/autotrade` each weekday at 10:00 New
   York (assistant route), or `launchd` on your Mac running `python -m buildout trader --once` (direct route;
   `deploy/com.buildout.trader.plist`). Read the digest daily.

Stop everything at any point with `python -m buildout trade halt` (writes `private/HALT`), the MCP tool
`trading_halt`, or the environment variable `BUILDOUT_TRADING_HALT=1`. Lift it with `trade resume`.

## One-time setup

1. In the Robinhood app, open an **Agentic account** (a separate self-directed individual account) and fund it with
   only what the model may trade. Agents can trade nothing else.
2. In Claude Code, from this folder: `.mcp.json` already lists both servers. Run `claude`, type `/mcp`, choose
   `robinhood-trading` and sign in through Robinhood's OAuth page. (Claude Desktop: Settings, Connectors, add the custom
   connector `https://agent.robinhood.com/mcp/trading`.)
3. `python -m buildout trader --init`, then edit and sign `private/mandate.toml` (above). `config.private.toml` keeps
   the planner's own terms (`[trading]`: variant, VIX share, collar, caps); `mode = "live"` there marks tickets executable.

## Every rebalance (assistant route)

Run `/rebalance` in Claude Code. It reads the Agentic account and quotes from Robinhood, asks Buildout for the
trader's pass, shows you the ticket and the mandate's verdict, and places orders only once the mandate allows it
(your approval of that ticket id in manual mode; a standing approval in supervised mode).

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
They paid in crashes: at 10% of the book's value they cut the Feb 19 to Mar 23, 2020 loss from 29% to 18%. On the book's own days the cost swings with the window (1.5 points of growth a year from 2017, none from 2018, which starts just before the February 2018 spike), so plan on the long-run carry. They did
almost nothing in the slow 2022 bear market, where the index short did the work. The default sleeve is 5% of equity
(a little under 1% a year of expected cost on the 2017 to 2024 record); set `vix_share = 0` to turn it off.

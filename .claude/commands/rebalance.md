---
description: Turn today's Buildout call into Robinhood orders, with a ticket the person approves first
---
Rebalance the Robinhood Agentic account to today's Buildout call. Follow these steps in order and stop at the first failure.

1. Call `buildout` `trading_status`. If `halted` is set, stop and say why.
2. From `robinhood-trading`, read the Agentic account only: equity (portfolio value), cash available to trade, and every position
   (symbol, quantity). Never read or trade any other account.
3. From `robinhood-trading`, get a quote (bid, ask, last) for MSFT, AMZN, GOOGL, META, NVDA, AVGO, TSLA, SPCX, ORCL, PSQ, VIXY and every
   symbol already held, and check each is tradable.
4. Call `buildout` `trade_plan` with that account and those quotes (add `variant` or `vix_share` only if the person asked).
5. Show the person the ticket: its id, mode, every order (seq, symbol, side, quantity, limit price, notional), the summary, and every check
   with its result. Say plainly if any check failed or if `execute` is false.
6. Place nothing unless all of these hold: `execute` is true, `all_checks_pass` is true, the ticket has not expired, and the person has
   replied approving this exact ticket id in this conversation. In paper mode, call `buildout` `paper_fill` instead and stop.
7. Place each order through `robinhood-trading` in `seq` order (sells first), as a limit order at `limit_price`, good for the day, for
   exactly `quantity`. Do not change a quantity, a price or a symbol. If Robinhood rejects an order, stop and report it; do not retry it at
   another price.
8. Read back each order's status and fills from `robinhood-trading` and call `buildout` `record_fills` with them. Report any issue it flags.

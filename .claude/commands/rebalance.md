---
description: One pass of Buildout's trader on the Robinhood Agentic account, under the mandate (manual or supervised: the ticket waits for approval)
---
Run one pass of Buildout's trader for the Robinhood Agentic account. Follow these steps in order and stop at the first failure.

1. Call `buildout` `trader_status`. If `halted` is set, or the mandate lists `problems`, stop and say why. Note the mandate's `mode`.
2. From `robinhood-trading`, read the Agentic account only: equity (portfolio value), cash available to trade, the account type, and
   every position (symbol, quantity). Never read or trade any other account.
3. From `robinhood-trading`, get a quote (bid, ask, last) for MSFT, AMZN, GOOGL, META, NVDA, AVGO, TSLA, SPCX, ORCL, PSQ, VIXY and every
   symbol already held.
4. Call `buildout` `trading_recommendation` with that account and those quotes. Show the person the recommendation (size, target weights,
   reasons), the ticket id, every order (symbol, side, quantity, limit), every planner check and the mandate's verdict (`pass.authorization`).
5. Read `pass.outcome`:
   - "staged, awaiting approval" (manual) or "awaiting approval or a standing approval" (supervised): tell the person the ticket id and stop.
     If they approve this exact id in this conversation, call `buildout` `approve_ticket` with it and their name, then start again at step 2.
   - "handed to the assistant": the mandate authorizes the orders in `pass.handoff`. Go to step 6.
   - anything else: report the reasons and stop. Do not work around a refusal.
6. Place each hand-off order through `robinhood-trading` in order (sells first), as a limit order at its limit, good for the day, for exactly
   its quantity, in the Agentic account. Change no quantity, price or symbol; add no order. If Robinhood rejects one, stop and report it.
7. Read back each order's fills from `robinhood-trading` and call `buildout` `record_fills` with the ticket id and the fills (symbol, side,
   quantity, price, order_id, status). Report any issue it flags, and the account's equity after.

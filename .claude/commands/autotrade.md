---
description: Buildout's trader without questions, for a scheduled run under an armed autonomous or standing-approved supervised mandate
---
Run Buildout's trader for the Robinhood Agentic account without asking the person anything. This is for a scheduled session under a mandate
that already authorizes the action (autonomous and armed, or supervised with a standing approval in force). Stop at the first failure and
write what happened in one short paragraph; never ask a question.

1. Call `buildout` `trader_status`. Stop if `halted` is set, if the mandate has `problems`, or if its `mode` is `manual` (a manual mandate
   needs a person; say so and stop).
2. From `robinhood-trading`, read the Agentic account only: equity, cash available to trade, account type, every position. Never any other
   account.
3. From `robinhood-trading`, quote MSFT, AMZN, GOOGL, META, NVDA, AVGO, TSLA, SPCX, ORCL, PSQ, VIXY and every symbol held.
4. Call `buildout` `trading_recommendation` with the account and quotes. If `pass.outcome` is not "handed to the assistant", report the
   outcome and its reasons and stop.
5. Place each order in `pass.handoff` through `robinhood-trading`, sells first, as a limit order at its limit, good for the day, for exactly
   its quantity, in the Agentic account. Change nothing; add nothing. If one is rejected, stop; do not retry at another price.
6. Read back the fills and call `buildout` `record_fills` with the ticket id and the fills. Report the fills, any issue flagged, and the
   equity after.

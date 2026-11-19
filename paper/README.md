# The paper bot's account

A model account of $100,000, run by Buildout's trader (`python -m buildout trader --once --paper`) from the daily
workflow, on the prior session's close. Scheduled for 11:17 UTC, Tuesday to Saturday; GitHub starts scheduled jobs late, and runs have started between about 16:00 and 20:00 UTC, during the US session. The ledger's timestamp is the record. A call governs from the first session whose prior close came after it was written.

The call in force is turned into a ticket and checked, and its orders are written. Since v0.47 the bot follows the
call: it rebalances when the whole book is more than 1% of equity away from the call's size, or any name is outside
its 2% band, and then brings every name to target, in whole shares rounded to the nearest (before, it checked only
each name's band, so it did not follow a change in the call's size). An order is planned on the call that governs
the session it is held through. Each order rests until the close of the first exchange session that ends
after it was written and fills at that close with a 5 basis point half-spread (market on close); the next pass
records the fill. So the decision comes before the order, the order before the price, and the price before the fill,
and each has its own timestamp. The ticket's limit is recorded but the paper fill does not depend on it.

Before v0.42.5 an order filled the instant it was written, at its limit against the last stored close. The first nine
fills (written Nov 11, 2026 at 19:54 UTC, priced on the Nov 10 close) were made that way: a price older than the
order. They are kept as recorded and marked on the page; an equity point dated before the account opened was moved
aside into `pre_inception_marks`, not deleted.

State here is the trader's own: tickets/, fills.jsonl (hash-chained), trader/journal.jsonl, trader/equity.jsonl,
paper_account.json. The page reads site/data/paper.json, a summary of this folder; a correction to the account is
listed there under `corrections` and shown on the Execution desk. It is a simulation convention, not evidence of an
achievable execution. It is a model account and holds no credential.

# The paper bot's account

A model account of $100,000, run by Buildout's trader (`python -m buildout trader --once --paper`) from the daily
workflow (Tuesday to Saturday at 11:17 UTC, on the prior session's close). The call in force is turned into a ticket
and checked, and its orders are written. Each order rests until the close of the first exchange session that ends
after it was written and fills at that close with a 5 basis point half-spread (market on close); the next pass
records the fill. So the decision comes before the order, the order before the price, and the price before the fill,
and each has its own timestamp. The ticket's limit is recorded but the paper fill does not depend on it.

Before v0.42.5 an order filled the instant it was written, at its limit against the last stored close. The first nine
fills (written Nov 11, 2026 at 19:54 UTC, priced on the Nov 10 close) were made that way: a price older than the
order. They are kept as recorded and marked on the page; an equity point dated before the account opened was moved
aside into `pre_inception_marks`, not deleted.

State here is the trader's own: tickets/, fills.jsonl (hash-chained), trader/journal.jsonl, trader/equity.jsonl,
paper_account.json. The page reads site/data/paper.json, a summary of this folder. It is a simulation convention, not
evidence of an achievable execution. It is not a personal account and holds no credential.

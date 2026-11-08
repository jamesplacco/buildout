# The paper bot's account

A model account of $100,000, run by Buildout's trader (`python -m buildout trader --once --paper`) in the daily
workflow every weekday morning, before the open: the call in force is turned into a ticket, checked, and filled at the
prior close plus a 5 basis point half-spread and the 10 bp limit collar. State here is the trader's own: tickets/,
fills.jsonl (hash-chained), trader/journal.jsonl, trader/equity.jsonl, paper_account.json. The page reads
site/data/paper.json, a summary of this folder. It is not a personal account and holds no credential.

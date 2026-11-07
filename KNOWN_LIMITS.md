# Known limits

Named defects in the receipts plugin, from an independent source/history audit of `803a04e`.
Status is honest per item: **open** means the defect is real and unfixed. Nothing here is claimed fixed
because a fix was attempted; it is fixed when a control that can fail proves it.

| # | Defect | Where | Status |
|---|---|---|---|
| R1 | Missing/evicted pre-state is substituted as "absent", so a post hook on an untouched file can record a mutation and the end hook emits `backed` while size and mtime never changed. A creation must not be certified without a captured before-state. | `receipts/ledger.py:85` | **repaired in `c22c103`** — pre-state unknown is no longer invented. Awaiting Codex's second-party recheck. |
| R2 | Development positives bypass the production binding. `judge.py:63` consumes sentence-final punctuation as part of an absolute path, so a real paired write is `backed` in backticks but `unbacked` as `I created /…/report.md.`. The acceptance harness also injects subject and scope counts that the real receipt path does not supply. | `receipts/judge.py:63`, `tests/test_acceptance.py:34,37`, `receipts/receipt.py:35-39` | partly fixed — README/metadata honesty cut applied; production-path binding **open** |
| R3 | Observations lose lifecycle, time and subject. A recorded deletion makes "exists" `backed` and an honest "is missing" `contradicted`; an error before a later repair becomes `later-error`; the lowest measurement anywhere in the evidence can contradict a different subject's perfect measurement. | `receipts/judge.py:178,191,232,249-255` | **repaired in `c22c103`** — lifecycle/order/subject preserved. Awaiting Codex's second-party recheck. |
| R4 | A listing command is treated as a successful absence observation. Listings are inferred from command strings with no result, exit status, depth or completeness check, so an existing file in a successful listing, a permission-denied listing, and merely printing a quoted `ls` can each produce `backed` for "missing". | `receipts/evidence.py:153-171`, `receipts/judge.py:190-209` | **repaired in `5193ff6`** — executed, observed, bounded listings. Awaiting Codex's second-party recheck. |
| R5 | Hedging alone grants `backed`. The hedge branch returns hedge-matches-scope unconditionally, so a hedged sentence with no search and no observation is backed. | `receipts/judge.py:173-175` | **repaired in `5193ff6`** — hedges are now observed, not assumed. Awaiting Codex's second-party recheck. |
| R6 | The acceptance bar was printed but not enforced: the CLI exited on `hits >= 7` alone, so a mutant with failed positive controls still exited 0. The bar was also computed inside a verbose-only block, so a non-verbose run never evaluated it. | `tests/test_acceptance.py` | **fixed** — full bar enforced in exit status, `>=2` positive controls required, proven with a mutant that exits 1 where it exited 0 before |
| R7 | The Day-3 "false-positive rate" is a verdict share without truth labels — it divides the plugin's own `unbacked`+`contradicted` by its own checkable verdicts and cannot distinguish a justified warning from a false alarm. | `scripts/gate_package.sh:89` | **fixed by renaming, not by obtaining labels** — the quantity is now `unbacked_claim_share` and the payload carries `not_a_false_positive_rate`, stating that nothing independently establishes that an unbacked verdict was wrong. Renaming is the honest fix: inventing truth labels would have made the number look like precision it has not earned. |
| R8 | The gate package builder can destroy its input: it runs an unrestricted `rm -rf "$OUT"` before any cleanliness check, including when `OUT` names the repo. Failed checks are logged but do not gate the final listing. | `scripts/gate_package.sh:17` | **repaired in `a9fcb5f`** — path resolved and refused for empty/root/the repo itself; verified repo-as-OUT and `/` refused. Awaiting Codex's second-party recheck. |

## What the audit did not do

It did not execute the destructive cases or the live-data package builder, and it did not rewrite
history. The eight exposed development cases pass 8/8; that is development credit, not held-out
validation. The private ten-case design remains unrun.

## How this file is kept honest

Each row names a locator and a status. When a repair lands, the row says so only after a control exists
that fails without the repair — the same rule R6 was fixed under.

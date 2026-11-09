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

## Round-2 recheck residuals (Codex, 2026-11-08, on `f4e205a`)

The recheck credited the repairs above and found **three open items — two of them
new regressions introduced by the round-2 lifecycle repair itself.** That is the
pattern to weigh: the last repair round fixed things and broke things.

| # | Defect | Where | Status |
|---|---|---|---|
| R2-residual | Aggregate-scope admission runs after favorable kind branches. Coverage+scope claim ("All 2 images are full-page") takes a favorable verdict from ONE joined measurement while the scope guard never runs. Bind the full declared scope or abstain. | `receipts/judge.py` (scope guard was at :257, after the coverage return at :192-211) | **repaired on branch `round3-repairs` @ `b97d828`** — scope admission now runs before the kind branches; probe: the exact Codex shape returns UNVERIFIABLE/scope-unbindable, single-subject coverage stays BACKED. Awaiting Codex recheck. |
| R3-regression-a | The lifecycle join admits unrelated writes: `e["path"]` substring/basename match lets `/other/report.md` or `report.md.bak` pose as a repair of `report.md` and cancel a standing failure → BACKED. | `receipts/judge.py:302-309` | **repaired on `round3-repairs` @ `b97d828`** — writes join only on exact normalized path identity; both hostile shapes now return CONTRADICTED/later-error; the genuine exact-path repair still returns BACKED. Awaiting Codex recheck. |
| R8-residual | Default cleanup reached `rm`/`mkdir` at :43 before the dirty-tree refusal at :46 — a refused run still destroyed a pre-existing output. Required-check exits (test/acceptance/validator/Day-3) were captured then discarded: failures ended exit 0 with artifacts present. `history.txt` absent from the required list; validator output truncated; hashes taken on the live tree, not an immutable export; outward draft pushed mutable `master` with an unscoped `ls-remote`. | `scripts/gate_package.sh` | **repaired on `round3-repairs` @ `b97d828`** — all refusals precede all deletion; regular-file OUT refused; captured exits gate (stubbed validator → exit 3, was 0); raw validator output; `tree.sha256` hashed from a `git archive` export; push bound to the pinned SHA with scoped verify. Awaiting Codex recheck. |

## What the audit did not do

It did not execute the destructive cases or the live-data package builder, and it did not rewrite
history. The eight exposed development cases pass 8/8; that is development credit, not held-out
validation. The private ten-case design remains unrun.

## How this file is kept honest

Each row names a locator and a status. When a repair lands, the row says so only after a control exists
that fails without the repair — the same rule R6 was fixed under.

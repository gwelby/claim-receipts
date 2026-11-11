# Known limits

Named defects in the claim-receipts plugin, found by independent source audits (Codex) of `803a04e`,
`f4e205a` and `fdb8f87`. Status is honest per item. A row says **repaired** only when a control that
fails without the repair exists in `tests/` and passes with it; **credited** means the auditor's
recheck confirmed it; **narrowed** means a favourable verdict was removed rather than made correct.

## Where this commit stands

The last audit (Codex, 2026-11-09, on `fdb8f87`) said **HOLD** and named six groups, C1 to C6. This
commit is the return for those six. It has **not** yet been rechecked by Codex. Until it is, every
"repaired" below is the author's claim with its control, not an auditor's credit.

## Earlier defects (R1–R8)

| # | Defect | Status |
|---|---|---|
| R1 | A missing or evicted pre-state was treated as "absent", so an untouched file could be certified as created. | **credited** by Codex on `fdb8f87` (native pre-state handling) |
| R2 | Sentence-final punctuation broke path binding; the acceptance harness injected scope counts the real path never supplies. | Ordinary period binding **credited**. Count injection remains a fixture-only path, kept separate from native results |
| R3 | Lifecycle, order and subject were lost; an unrelated write (`report.md.bak`, another folder's `report.md`) could pose as a repair. | Exact-path write join **credited** on `fdb8f87`. The same rule for **commands** is C3 below |
| R4 | A listing command was treated as a successful absence observation. | Bounded progress credited on `fdb8f87`; the remaining shapes are C2 below |
| R5 | Hedging alone earned `backed`. | Same as R4: C2 below |
| R6 | The acceptance bar was printed but not enforced. | Fixed earlier; enforcement of the added regressions is C4 below |
| R7 | The Day-3 ratio is a verdict share, not a false-positive rate. | **credited** (renamed `unbacked_claim_share`, carries `not_a_false_positive_rate`). No truth labels exist; it must not be quoted as precision |
| R8 | The package builder could destroy its input; failed checks did not gate. | Early refusals, required-check exits, raw validator logs, `history.txt`, pinned push: **credited** on `fdb8f87`. Immutable binding is C5 below |

## The return for Codex's HOLD on `fdb8f87`

| # | What the audit found | What this commit does | Control (in `tests/`, run by `make test`) |
|---|---|---|---|
| C1 | Counts covering the scope returned `backed` before the claim's property was judged: a 53% measurement with counts 2/2 was `backed`. | **Repaired.** Scope counts now only admit a claim; its kind is then judged. One failing member contradicts "all". **Narrowed:** a passing result from one judged subject cannot speak for the whole set, so it abstains (`scope-property-unbound`). The removed `scope-covered` verdict was used by no fixture or production path. | `test_judge_identity.py` |
| C2 | Native observation overstated what ran and what it covered: default `ls` omits dotfiles, a quoted `; ls` inside `printf` counted as a listing, a reader-truncated listing proved absence, `find` lost locations, repeated listings were merged, unrelated or failed commands backed a hedge, and an exact-path `read_file` lost its subject. | **Repaired**, all 15 of the audit's comparisons within bounds (6 of 15 before). Commands split only on unquoted separators; anything with `$( )`, backticks or unbalanced quotes is not a listing. A listing counts only in a small allowed form (one absolute path, a fixed set of `ls` flags, or `find ROOT [-maxdepth N] [-name P] [-print]`). Dotfiles need `-a`/`-A`. Cut output cannot prove absence. Entries keep full paths; the newest covering listing decides. A hedge needs a successful observation naming the exact subject path. **Narrowed:** `grep -r` omissions and `tree` output no longer prove absence; other `ls` flags, several paths, redirects or extra `find` options make a listing unable to prove absence. | `test_native_observation.py`, `test_transcript.py` |
| C3 | A successful command that only named the target (`check report.md.bak`, another folder's `report.md`, `printf` of the path) erased a recorded failure. | **Repaired.** A successful command repairs a recorded failure only if it is the identical failing command run again. **Narrowed:** a real repair checked with a *different* command (fails with `pytest`, passes with `python3`) now abstains (`repair-unbound`) instead of being backed. The exact-path write repair is unchanged. | `test_judge_identity.py` |
| C4 | The acceptance exit enforced the original quota but not the added regressions: two mutants scored 34/35 and exited 0. | **Repaired.** The original-eight rule (7/8 and both positives) is kept, and all 27 added regression cases are each required. "Honest work" counts every case expected `backed`, not names containing a word. The fixture is checked against its recorded hash (that record had been stale since `013dae4`). All three of the audit's mutants now exit 1. | `test_bar_mutants.py` |
| C5 | Package success was not bound to complete commit bytes: a failed or partial export, a missing checksum, or checks run on changed live files still ended 0. | **Repaired.** The file list comes from the pinned commit; export and hash failures abort; the export must match the commit's files exactly; the checks run inside that export and are re-verified after; at the end the tree, index and bundle must still equal the commit. **Output policy:** only the sanctioned `GATE_PACKAGE` folder is ever replaced; any other existing output path is refused (exit 2), empty or not, and a read error is never taken as "empty". | `test_gate_package_binding.py` |
| C6 | This file and the README did not match the audit. | This rewrite, and the README's limits section. | — |

## Hostile pre-check before the recheck (2026-11-10)

Before asking Codex to recheck, an independent attacker was set on this return. It found three
blocker-class defects (two of them regressions introduced by the return itself) and seven more.
All are now answered by abstention, each with a control in `tests/test_hostile_364be5d.py` or
`tests/test_judge_round2.py`; the attacker's own 42 attack cases all hold.

| Found | Now |
|---|---|
| Conflicting `ls` format flags (`-lC`, `-1x`) read a present file as absent | Two format flags together: the listing abstains. An `ls -l` row that is not the plain 9-field shape (device files, ISO dates, other locales, names with spaces) abstains |
| A symlinked root or subfolder, or `..` in a path, read a present file as absent | Any symlink from the listing root down to the claimed folder, or `..` in an operand: abstains. Symlinks are checked when the receipt is built, not when the listing ran |
| A relative-path hedge was backed by a same-named file elsewhere | A relative hedge subject never matches |
| A heredoc body, `&`, a redirect target, or a failure followed by `; true` / `\|\| true` counted as an observation | Heredocs, herestrings and a lone `&` abstain. A segment counts as succeeded only if no `;`, `\|\|` or `\|` follows it and no `\|\|` comes before it |
| An unscoped hedge was backed by any unrelated command | Unscoped hedges are backed only by an observe-tool call such as `web_search`; terminal commands and single-path reads no longer count |
| An "identical" re-run in another folder repaired a failure; a failure on a look-alike path accused | A failure counts only on the exact absolute path (or a path inside it), and only an identical re-run repairs it; other failures abstain (`failure-unbound`) |
| A coverage figure printed by `printf`/`cat`, matched by file name, or over "both" | Measurements from text-reproducing commands or inline code abstain; a measurement joins only on the exact absolute path; "both" and numerals over a set are aggregate scope and abstain unless the whole set is judged |
| A listing then a later `touch`, `rm` or `: >` of the target | A listing no longer speaks for a path that a later command names, or a folder above it, a glob, or a command that cannot be read |
| Day-3 counts could come from another session's receipt; a failed package looked complete | A named session whose receipt is missing, malformed, a symlink, or names another session fails the package; `RECEIPTS_ROOT` is honoured; the package records the receipt's path, sha256 and how it was chosen. With no session named, the newest receipt is still used and the package says so. A failed run leaves a `FAILED` marker and no `MANIFEST.md`; the marker is removed only as the last step of a successful run |

**Narrowed by this round** (a favourable verdict removed): unscoped hedges after terminal-only
evidence; coverage claims that name no file (production no longer judges them; the fixture passes
only because it injects the subject); a real measurement piped through `grep` or printed by
`python3 -c`; a real failure written with a relative path; any listing followed later in the session
by a `$( )` or subshell (it is treated as stale, which can be broad).

**Widened by this round:** a native `web_search` followed by an unscoped hedge is now `backed` on a
live session (the ledger keeps no row for it, so it is read from the session record). Without this,
original case-06 could pass only in the fixture. A search the host marked as an error backs nothing.

**Settled from Hermes's source** (v0.23.0 `model_tools.py` `_emit_post_tool_call_hook` and
`agent/display.py` `_detect_tool_failure`; read by the integrator, not run live, and not re-read by the
independent passes, which were kept out of the Hermes install): when a tool gives no status, Hermes
derives it, and a terminal command with a nonzero exit reaches the hook as `status: error`.

## Second independent pass (2026-11-11)

A second attacker, on a different model, then attacked the result. It found one more blocker and a set
of false verdicts, the worst of them false `contradicted` on honest work. All are answered, each with a
control in `tests/test_judge_round3.py`, `tests/test_fable_06ac15a_evidence.py` or
`tests/test_gate_package_binding.py`; the first attacker's 42 cases still hold.

| Found | Now |
|---|---|
| A heredoc-fed interpreter (`python3 - IMG <<EOF … print('coverage 100%')`) forged a coverage verdict | A measurement whose command cannot be segmented (heredoc, `$( )`, backticks, `&`) or runs inline code (`-c`, `-e`, `python3 -`, an interpreter reading stdin) is not admitted |
| `grep`, `diff`, `cmp`, `test`, `[` or `git diff --exit-code` exiting 1 was read as a failure: "Fixed app.py" was contradicted after `grep -c TODO app.py` found none | Exit 1 of those verbs is a result. In the lifecycle it abstains (`exit-is-result`). For a hedge, a single-segment `grep`/`rg` that ran and found nothing counts as an observation |
| A hedge about anything ("could not verify the layout") was contradicted because the file was written | `was-confirmable` needs existence wording in the hedge |
| "margins 5%" was read as page coverage | Each percentage belongs to its own clause; a clause naming a complement (margin, whitespace, blank, padding, border, dpi) is not a measurement |
| A path in `echo`/`printf` text, or inside inline code, bound a failure | A failure ties to the target only through whole path arguments of commands that actually ran |
| A `python3 -c` write of the target after a listing left absence backed | A segment running inline interpreter code stales every earlier listing |
| A `grep` pattern counted as an observed file; `[ -f T ]` after a listing staled it | Only grep/rg file operands count; `[` and `[[` are read-only |
| Package Day-3 counts could disagree with the receipt's own verdicts; files the checks added inside the export went unseen | Counts are recounted against the verdict list (and must sum to `judged`); the export is enumerated again after the checks. The checks run without writing bytecode, because the validator otherwise leaves `.pyc` files there |

**Narrowed by this round:** a real "not fixed" signal from `cmp golden T` or `test -s T` exiting 1 now
abstains instead of contradicting (the record keeps ok/error, not the exit code, so exit 1 and exit 2
cannot be told apart); a hedge that is not about existence is never `was-confirmable`; any interpreter
run with `-c`, `-e`, `-p` or `-r` style flags counts as inline code, even a harmless `bash -e script.sh`;
a measurement printed by a wrapped or stdin-fed interpreter is not admitted; "coverage 53% margins 0"
with no separator abstains.

**Widened by this round:** a listing followed by `[`/`[[` can back absence; a single-segment `grep`/`rg`
that exits 1 can back a hedge naming its file; "ink coverage 100%, margins 5%" is now `backed`.

**The Day-3 check is internal consistency only.** A receipt edited so that its counts and its verdict
list agree still passes; a receipt with no verdict list gets only the sum check.

## Codex's recheck of 2358d20 (2026-11-11)

Codex rechecked the return and credited the C1 scope, C4 acceptance-bar and C5 package repairs, the 15
native observation comparisons and the four command-alias comparisons. It held on three groups; the
first two had been disclosed here as open, and disclosure does not turn an active favourable verdict
into an abstention. All three now abstain, with Codex's own probe (eight cases, three of them positives
that must stay `backed`) adopted as `tests/test_codex_2358d20_residuals.py`; on 2358d20 it fails 5/8.

| Codex case | Now |
|---|---|
| R1: the same command text, run from another folder against a different `check.py`, counted as the failing check re-run | The ledger keeps the folder a terminal call ran in when the host passes one. A re-run repairs only with the same folder; when either folder is unknown, only if no operand is a relative path |
| R2: a listing, then `git checkout -- .` or `python3 build.py` restored or created the target without naming it | After a listing, any command that is neither known to only look (including read-only `git` subcommands) nor known to change only what it names (`touch`, `rm`, `mkdir`, `cp`, `mv`, …) stales it |
| R3: a coverage figure printed by a producer that then failed, or whose failure `; true` hid, counted | A measurement counts only from a call that succeeded (by its own status, or the hook's record of that exact command), uncut, with no `;`, `\|\|` or `\|` able to mask the producer |

**Narrowed by this round:** a genuine repair checked with a relative script (`python3 check.py
/x/app.py`) and no recorded folder abstains, which is the usual case on a live Hermes session, since its
terminal tool does not pass the folder to the hook; a listing followed by an arbitrary program
(`python3 -m py_compile OTHER`, `make`, `pytest`) abstains.

## Still open, named

- **Native case08 stays UNJUDGED** without subject injection, as the audit recorded.
- **Column `ls` output** with a name containing two spaces is not caught.
- **A scope word anywhere in a sentence makes it abstain.** "Fixed app.py; all tests pass" abstains
  (`scope-unbindable`) even with a recorded write, because "all" is read as a claim over a set.
- **An ALL-CAPS word in a hedge is taken as its subject.** "I could not verify the API key works" is
  scoped to `API` and cannot be backed; the same sentence without it can.
- **The fixture hash is checked against a record in the same commit.** It catches accidental drift
  between the fixture and its record, not a deliberate change to both.
- **Usefulness, measured by an independent pass on realistic synthetic sessions (2026-11-11):** about
  56% of genuine claims were backed (write-and-test 10/17, list-and-"missing" 10/19, read-and-hedge
  9/16); most of the rest abstain on shapes the plugin does not read (`2>/dev/null`, `| head`,
  `cd X && ls`, `find -type f`, `sed -n`). Abstaining is the intended failure; a false verdict is not.
- **The text-producer list is a denylist.** An unlisted program whose only job is to print
  "coverage 100%" would still be read as a measurement.
- **Day-3 counts are bound to a receipt, not to a plugin commit.** A receipt does not record which
  plugin commit judged it; `package_commit` says only which package carried the counts.
- **The package records a local path** (`source_receipt_path`, under the home folder). Review it before
  any package is shared.
- **The package bundle is created with `--all`.** Which refs go out is a disclosure decision for the release, not made here.
- **The outward readback** in the generated commands is anonymous `ls-remote` on one ref; no public read has been run.
- **The transcript join** was checked against Hermes's source and synthetic transcripts, not against a live Hermes host.
- **The Day-3 share** has no independent truth labels (R7).
- **No held-out validation.** The cases above are exposed development diagnostics, not an accuracy estimate.

## How this file is kept honest

Each row names its control. When a repair lands, the row says so only after a control exists that
fails without the repair. A narrowed branch is named as narrowed, with what it now does instead.

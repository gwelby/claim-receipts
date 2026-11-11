# Repair
*claim-receipts canonical definition*
*Status: DRAFT v0.1 — not yet audited*
*Checked against `6dc1938` plus its uncommitted working-tree changes (2026-11-11). Line numbers are for that tree.*
*Depends on: `ledger.md`, `capture.md`, `verdict.md`.*

---

**In one sentence:** A repair is later evidence that clears a recorded failure on a claim's subject,
and only two things count: a write to the exact same path, or the literally identical failing check
run again in the same recorded folder.

## Age 5

You tried to tie your shoe and it came undone. If you then tie *that same shoe* again, or try the
*same* knot again and it holds, the problem is fixed. Tying a different shoe does not fix this one.

## The definition

**When the check runs.** Only for a **completion** claim whose subject resolves to a path and whose
text contains a success word: `fixed`, `resolved`, `solved`, `now works`, `works now`, `working now`,
`is working`, `is fixed`.

**Walking the session.** The judge reads the session's writes and commands in the order they were
recorded.

- A command is **related** to the subject if its text contains the subject path or its file name
  anywhere. Unrelated commands are skipped.
- A related command that **failed**:
  - if no executed segment takes the subject's exact absolute path (or a path inside it) as a whole
    operand, it is an **unbound failure**. `echo`/`printf` text, quoted prose, a file name alone, or a
    look-alike path do not bind;
  - else, if a result verb runs in a segment the call's status speaks for (`grep egrep fgrep rg diff
    cmp test [ [[`, or `git diff` with `--exit-code`/`--quiet`/`--no-index`), it is a **result exit**:
    exit 1 there means "no match / differs / false", and the record cannot tell 1 from 2;
  - else it is a **standing failure**.
- A related command that **succeeded**, while a failure stands:
  - if it is the **same check** (below), the failure is **repaired**;
  - otherwise it is an **unbound success**: it names the subject but proves nothing about the
    failure.
- A **write** to the exact normalised subject path clears everything: the standing failure, any
  unbound success, any unbound failure, any result exit.

**The same check.** A later success is the failing check run again only when all of these hold:

1. **both calls recorded their folder, complete**, and the two folders are the same (after normalising);
   a folder the ledger flagged `cwd_cut`, or one stored at 1,000 characters or longer, never matches;
2. **neither command was cut** by the ledger: neither carries the ledger's `command_cut` flag, and
   neither stored command is 2,000 characters or longer;
3. **the two commands are equal character for character.** White space is not collapsed.

If either folder is unknown, no re-run repairs, however the command is written. `KNOWN_LIMITS.md`
states that Hermes's terminal tool does not pass the folder to the hook. On a live session, then, a
recorded failure is cleared only by a write to the exact path.

**Outcome**, in this order:

| State at the end | Verdict |
|------------------|---------|
| an unbound success after a failure | UNVERIFIABLE `repair-unbound` |
| a standing failure | CONTRADICTED `later-error` |
| an unbound failure | UNVERIFIABLE `failure-unbound` |
| a result exit | UNVERIFIABLE `exit-is-result` |
| none of these | the ordinary completion test: BACKED `written-this-session` if the file was written, and so on |

## What it is not

- **Not a different command that passes.** Failing under `pytest /x/app.py` and passing under
  `python3 /x/app.py` abstains (`repair-unbound`).
- **Not a write to a look-alike.** `/other/app.py` or `app.py.bak` does not repair `/x/app.py`.
- **Not proof the fix works.** A write to the exact path clears a failure without any check being run
  again. "Fixed `/x/app.py`" after a failing check and then a write to the file is BACKED.
  (Checked by running the judge on the current tree.)
- **Not checked for claims without success words.** "Created `/x/app.py`" ignores later failures.
- **Not available without a recorded folder.** The identical `python3 /x/check.py /x/app.py`, failing
  and then passing, with no folder recorded, abstains (`repair-unbound`). With both calls in `/w` it
  repairs. With one in `/w` and one in `/v` it abstains. (Checked by running the judge on the current
  tree.)

## In the code

| What | Where |
|------|-------|
| Lifecycle walk and outcomes | `receipts/judge.py:_judge_kind`, completion branch (L595–669) |
| Success words | `receipts/judge.py:SUCCESS` (L68) |
| Binding a failure to the target | `receipts/judge.py:_names_target` (L342), `_operand_paths` (L311) |
| Result verbs | `receipts/judge.py:_exit_may_be_result` (L378); `receipts/evidence.py:exit1_is_result` (L144), `EXIT1_RESULT_VERBS` (L139) |
| Same check | `receipts/judge.py:_same_check` (L462), `_LEDGER_COMMAND_CAP` (L486) |
| Ordered events, recorded folder, cut flag | `receipts/evidence.py:Evidence._ingest` (L1064); `receipts/ledger.py:post_tool_call` (L72) |

## Limits

- Project README, "What it does NOT establish": **A repair must be the same check run again.**
- `KNOWN_LIMITS.md`, "Earlier defects (R1–R8)", row **R3**; "The return for Codex's HOLD on
  `fdb8f87`", row **C3**.
- `KNOWN_LIMITS.md`, "Hostile pre-check before the recheck (2026-11-10)": the row on an "identical"
  re-run in another folder.
- `KNOWN_LIMITS.md`, "Second independent pass (2026-11-11)": the rows on `grep`/`diff`/`test` exit 1
  and on a path in `echo`/`printf` text; and its "Narrowed by this round" paragraph.
- `KNOWN_LIMITS.md`, "Codex's recheck of 2358d20 (2026-11-11)", row **R1**; "Codex's targeted recheck
  of 6a6aae3 (2026-11-11)", row **N1**; "Codex's targeted recheck of 6dc1938, and the definitions pass
  (2026-11-11)", rows **M1**, **M2**, **M3**, and the paragraph "Disclosed, not changed".
- A command is "related" by plain text containment, so a command that mentions the file name in any
  way is considered. Only the binding step decides whether it counts.

## Related terms

`verdict.md` (CONTRADICTED, UNVERIFIABLE) · `ledger.md` · `capture.md` · `WORD_KEY.md`

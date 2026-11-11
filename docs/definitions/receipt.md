# Receipt
*claim-receipts canonical definition*
*Status: DRAFT v0.1 — not yet audited*
*Checked against `6dc1938` plus its uncommitted working-tree changes (2026-11-11). Line numbers are for that tree.*
*Depends on: `capture.md`, `claim.md`, `verdict.md`.*

---

**In one sentence:** The receipt is the end-of-session artifact — one Markdown file and one JSON
file — that lists what the capture shows, a verdict with its reason for each judged claim, and how
many claims were found but could not be judged.

## Age 5

At the end of shopping you get a slip of paper. It says what you bought. This slip also says what you
*said* you bought, and whether the bag agrees, and which things it could not check.

## The definition

**When.** At session end. The `on_session_end` hook first appends the ledger's end marker, then builds
and writes the receipt. The two steps are independent; a failure in one does not stop the other.

**Where.** `<root>/receipts/<session>.md` and `<root>/receipts/<session>.json`, with `<root>` as in
`ledger.md`. The name is the full session id (else task id, else `unknown`), with `/` replaced by
`_`. Each write replaces the previous file of the same name.

**How it is built.**

1. Read the ledger and the transcript into the capture (`capture.md`).
2. Read the assistant prose and extract claims (`claim.md`).
3. Split claims into judgeable and unjudged.
4. Judge each judgeable claim (`verdict.md`).
5. Count.

**The JSON holds:** `session`, `generated` (time), `transcript_available` (whether any assistant text
was read), `evidence` (`files_mutated`, and counts of mutations, commands, listings, tool outputs),
`claims` (counts: `detected`, `judged`, `unjudged`, and one per verdict), `verdicts` (each with
`verdict`, `reason`, `detail`, `kind`, `claim`), and `unjudged_sample` (up to ten).

**The Markdown has three sections:**

1. **What the record shows** — files changed (first 25 listed), commands run, directories listed. If
   no assistant text was readable, it says so and says this is not a clean bill of health.
2. **Verdicts** — grouped CONTRADICTED, UNBACKED, BACKED, UNVERIFIABLE, at most 12 per group, each
   with its reason code and detail.
3. **What this receipt does NOT tell you** — how many claims were detected, judged and not judged; that
   it cannot say whether the work was good; and up to five unjudged claims.

## What it is not

- **Not the `/claim-receipts` command output.** That command shows evidence only (files changed and
  the last ten commands), and says no claim is judged there. It reads the session named in its
  argument, or else the most recently written ledger file.
- **Not signed or tamper-evident.** It is a plain file.
- **Not bound to a plugin version.** A receipt does not record which plugin commit judged it.
  (`KNOWN_LIMITS.md`, "Still open, named".)
- **Not the package or the Day-3 counts.** `scripts/gate_package.sh` builds those from a receipt.
- **Not a judgement of quality.** It says so in its own last section.

## In the code

| What | Where |
|------|-------|
| Hook order at session end | `__init__.py:_session_end` (L39) |
| Building the data | `receipts/receipt.py:build` (L26) |
| Rendering the Markdown | `receipts/receipt.py:render_md` (L69) |
| Writing both files | `receipts/receipt.py:write` (L133) |
| The evidence-only command | `__init__.py:_handle_slash` (L30); `receipts/claims.py:render_session_summary` (L31) |

## Limits

- **Only if the hook fires.** No `on_session_end`, no receipt.
- **Fail-open, and silent.** If writing fails, `write` returns `{"ok": false, …}` and nothing is
  raised. (Project README, "Safety".)
- **It stores claim text.** Each verdict keeps up to 300 characters of the assistant's sentence, and
  details can include command text and paths. (Project README, "Privacy — what is read and what is
  stored".)
- `KNOWN_LIMITS.md`, "Still open, named": **Day-3 counts are bound to a receipt, not to a plugin
  commit**; **The package records a local path**.
- `KNOWN_LIMITS.md`, "Second independent pass (2026-11-11)": **The Day-3 check is internal consistency
  only.**

## Related terms

`capture.md` · `verdict.md` · `abstention.md` · `ledger.md` · `WORD_KEY.md`

# Definitions — claim-receipts
*Canonical term definitions for the claim-receipts Hermes plugin*
*Format follows the family definition set (`/mnt/d/Fundamentals/definitions/`).*
*Checked against `6dc1938` plus its uncommitted working-tree changes (2026-11-11). Line numbers in "In the code" are for that tree and will drift.*

---

## Status

Every file starts unaudited. A file moves past DRAFT only after an independent reader has checked
each behavioural sentence against the code.

| File | Term | Status | Notes |
|------|------|--------|-------|
| `ledger.md` | Ledger | DRAFT v0.1 — not yet audited | The per-session JSONL the hooks append to |
| `capture.md` | Capture | DRAFT v0.1 — not yet audited | Ledger + session transcript; what the session can be held to |
| `claim.md` | Claim | DRAFT v0.1 — not yet audited | A sentence that matches a fixed pattern; kind, subject, scope flag |
| `observation.md` | Observation | DRAFT v0.1 — not yet audited | A captured sign the session looked at something; what a hedge needs |
| `listing.md` | Listing | DRAFT v0.1 — not yet audited | When a directory listing can prove absence, and when it goes stale |
| `measurement.md` | Measurement | DRAFT v0.1 — not yet audited | Coverage percentages read from command output |
| `verdict.md` | Verdict | DRAFT v0.1 — not yet audited | BACKED, UNBACKED, UNVERIFIABLE, CONTRADICTED — one section each |
| `abstention.md` | Abstention | DRAFT v0.1 — not yet audited | Why UNVERIFIABLE is first-class; unjudged vs unverifiable |
| `scope.md` | Scope | DRAFT v0.1 — not yet audited | "all", "both", counts: admission, not proof |
| `repair.md` | Repair | DRAFT v0.1 — not yet audited | A recorded failure later cleared, and the two ways that may happen |
| `receipt.md` | Receipt | DRAFT v0.1 — not yet audited | The end-of-session Markdown + JSON artifact |
| `WORD_KEY.md` | Reason codes | DRAFT v0.1 — not yet audited | Every reason code the judge can emit, with its line |

---

## Writing order (and reading order)

The record comes before the reading of it, and the reading before the judging.

1. **What was recorded:** `ledger.md`, then `capture.md`.
2. **What was said:** `claim.md`.
3. **What counts as having looked:** `observation.md`, `listing.md`, `measurement.md`.
4. **What the judge says:** `verdict.md`, then `abstention.md`.
5. **The two rules that most often surprise a reader:** `scope.md`, `repair.md`.
6. **What a person reads at the end:** `receipt.md`.
7. **Lookup table:** `WORD_KEY.md` — use it when a receipt shows a reason code you do not know.

---

## How to read a term file

Each term file has the same sections, in the same order:

| Section | What it gives you |
|---------|-------------------|
| Title, status line | The term, and whether anyone has checked this file yet |
| One-sentence definition | The whole idea in one line |
| **Age 5** | Two or three plain sentences. No code words. |
| **The definition** | The precise rule, as the code applies it today |
| **What it is not** | The confusions this term rules out |
| **In the code** | `file:function` locators (with line numbers for the tree named above) |
| **Limits** | The rows of `KNOWN_LIMITS.md` that bear on this term, named by section heading |
| **Related terms** | Where to go next |

Read "Age 5" to get the picture. Read "The definition" to get the rule. Read "What it is not"
before you repeat a verdict to anyone else.

---

## Ground rules for these files

- Every sentence about behaviour must be true of the code in the tree named above. When a file and the
  code disagree, the code wins and the file is wrong.
- Nothing here claims accuracy, coverage or validation. `KNOWN_LIMITS.md` says there is no held-out
  validation; these files do not say otherwise.
- Code verdicts are written in capitals (`BACKED`), as the code emits them. The project README writes
  them in lower case (`backed`). They are the same four words.
- Paths in "In the code" are relative to the plugin root (the folder that holds `plugin.yaml`).

---

## Sources

- Plugin code: `receipts/*.py`, `__init__.py`, `plugin.yaml`
- Project README: [`../../README.md`](../../README.md)
- Known limits: [`../../KNOWN_LIMITS.md`](../../KNOWN_LIMITS.md)

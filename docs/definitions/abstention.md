# Abstention
*claim-receipts canonical definition*
*Status: DRAFT v0.1 — not yet audited*
*Checked against `6dc1938` plus its uncommitted working-tree changes (2026-11-11). Line numbers are for that tree.*
*Depends on: `verdict.md`, `claim.md`.*

---

**In one sentence:** Abstention is the plugin declining to say "supported" or "refuted" when its
capture cannot decide, and it appears in two forms: the verdict `UNVERIFIABLE` with a reason, or a
claim left unjudged.

## Age 5

Sometimes the honest answer is "I can't tell". Saying "yes" when you can't tell is a fib, even if it
is a nice fib. The plugin is built to say "I can't tell" instead.

## The definition

**Two forms.**

| Form | What happens | Where it shows |
|------|--------------|----------------|
| **UNVERIFIABLE** | The claim is judged, and the judge returns UNVERIFIABLE with a reason code. | In the receipt's verdict list, last section. |
| **Unjudged** | The claim's subject cannot be located, so no verdict is given at all. | Counted in the receipt (`unjudged`); up to ten kept in the JSON, five shown in the Markdown. |

**Why UNVERIFIABLE is first-class.** It is one of the four verdicts, not an error or a gap. If the
plugin could only say BACKED or UNBACKED, every case it cannot decide would have to go into one of
them. Forcing it into BACKED would make the record lie in the flattering direction, which is the
failure the plugin exists to catch. (Project README, "Four verdicts per claim".) Forcing it into
UNBACKED or CONTRADICTED would accuse honest work.

**The rule the code follows.** When a shape is doubtful, the code is written to fall towards
abstaining:

- a command the splitter cannot segment gives no listing and no observation, and binds no failure;
- a doubtful path operand (`$VAR`, a glob, `~`, `..`) names nothing;
- an output that cannot be bound to exactly one call is not used;
- a favourable verdict that a rule cannot support is changed to UNVERIFIABLE (for example
  `scope-property-unbound`, `repair-unbound`).

`KNOWN_LIMITS.md` names each such change as **narrowed** ("a favourable verdict was removed rather
than made correct").

**The cost.** Abstaining is not free. `KNOWN_LIMITS.md` ("Still open, named", row **Usefulness**)
reports 50 realistic synthetic cases where the claim was true: 32 backed, the rest abstained, none
contradicted. Most abstentions were shapes the plugin does not read. It calls these exposed cases,
not an accuracy estimate, and states: "Abstaining is the intended failure; a false verdict is not."

## What it is not

- **Not a pass.** UNVERIFIABLE does not mean "probably fine".
- **Not a hidden fail.** It does not mean "probably false" either.
- **Not UNBACKED.** UNBACKED says the subject was located and nothing supports the claim.
  UNVERIFIABLE says the evidence present cannot decide.
- **Not always what happens when a subject is hard to read.** A hedge whose subject is relative —
  a bare name that did not resolve (`report.md`), a path with a folder (`docs/report.md`), or any
  `word/word` such as `read/write` — is UNBACKED (`hedge-unobserved`), not UNVERIFIABLE
  (`observation.md`).
- **Not a promise that every doubtful case abstains.** It is a design rule. Its exceptions are the
  open rows in `KNOWN_LIMITS.md`.

## In the code

| What | Where |
|------|-------|
| UNVERIFIABLE emissions | `receipts/judge.py` — see `WORD_KEY.md` for each line |
| Unjudged claims | `receipts/judge.py:judgeable` (L189); `receipts/receipt.py:build` (L26), fields `unjudged`, `unjudged_sample` |
| "None means abstain, never guess" | `receipts/evidence.py:_segments` (L198), docstring |
| How the receipt explains unjudged claims | `receipts/receipt.py:render_md` (L69), section "What this receipt does NOT tell you" |

## Limits

- Project README, "What it does NOT establish" (its opening paragraph: "Where the plugin cannot support
  a verdict it abstains").
- `KNOWN_LIMITS.md`, every "Narrowed by this round" paragraph.
- `KNOWN_LIMITS.md`, "Still open, named": the usefulness row; **A scope word anywhere in a sentence
  makes it abstain**.

## Related terms

`verdict.md` · `scope.md` · `repair.md` · `claim.md` · `receipt.md`

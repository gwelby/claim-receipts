# Verdict
*claim-receipts canonical definition*
*Status: DRAFT v0.1 — not yet audited*
*Checked against `6dc1938` plus its uncommitted working-tree changes (2026-11-11). Line numbers are for that tree.*
*Depends on: `claim.md`, `capture.md`. Related: `abstention.md`, `WORD_KEY.md`.*

---

**In one sentence:** A verdict is the judge's answer for one judged claim — `BACKED`, `UNBACKED`,
`UNVERIFIABLE` or `CONTRADICTED` — and it always comes with a reason code and a detail line.

## Age 5

You said "I cleaned my room". Mum looks in the notebook. Either it says you did (backed), it says
nothing about your room (unbacked), the notebook can't tell (unverifiable), or it says your toys are
still on the floor (contradicted).

## The definition

`judge(claim, evidence)` returns one `Verdict`: a verdict word, a reason code, and a detail string.
There is no fifth verdict. Finer distinctions are reason codes (`WORD_KEY.md`).

The order of checks, for one claim:

1. A **hedge** is judged first (`observation.md`).
2. A claim with the **scope flag** is handled next (`scope.md`). In production every such claim
   becomes `UNVERIFIABLE` (`scope-unbindable`).
3. Otherwise the claim's **kind** decides the branch: coverage, absence, currency, existence, then
   completion (which includes the failure check in `repair.md`).

Only judged claims get a verdict. Claims that are not judgeable are left **unjudged** (`claim.md`,
`abstention.md`).

A verdict compares a claim with the capture. It does not prove the claim true. Agreement with a
capture is not truth. (Project README, opening section.)

---

### BACKED

**Means:** the capture holds a specific item that supports this kind of claim.

| Kind | What backs it | Reason |
|------|---------------|--------|
| hedge | an observation of the absolute subject path, or for a hedge with no subject at all an observe-tool call | `hedge-matches-scope` |
| coverage | an admitted, joined measurement of 95% or more | `measurement-agrees` |
| absence | a recorded deletion of the path | `deleted-this-session` |
| absence | a qualifying listing whose captured output omits the name | `absence-established` |
| currency | no newer sibling on disk at session end, and a qualifying, still-current listing covers the claimed folder (see note; output not read) | `newest-in-scope` |
| existence | a certified write that left the file present | `written-this-session` |
| existence | the file is on disk at session end and a qualifying, still-current listing covers it (output not read) | `listed-this-session` |
| completion | a certified write that left the file present, and no standing failure | `written-this-session` |

**Note on currency.** "X is current" is read as a claim about X's *folder*. If X is a file, the
judge compares the folder that holds X with the other entries next to that folder, by modification
time on disk at session end. If X is itself a folder, it compares X with its siblings.

**What it is not.**

- Not truth, and not quality. The receipt itself says it cannot tell whether the work was good.
- **For a completion claim, BACKED means "the file was written".** "I verified `/x/app.py`" is
  BACKED by a write to `/x/app.py`, with no check run. A command never backs a completion claim;
  commands can only count against one (`later-error`).
- Not "approved". A BACKED hedge shows an attempt was made, not that the hedge is right.

---

### UNBACKED

**Means:** the judge could locate the claim's subject (or it is a hedge), found nothing that
supports it, and found nothing that directly conflicts with it. "Can't prove it."

| Kind | When | Reason |
|------|------|--------|
| hedge | no observation of the subject (always so for a relative subject, including a `word/word` in the sentence) | `hedge-unobserved` |
| existence | nothing on disk at the path at session end, no write this session, and no captured, still-current listing of its folder that omits the name | `artifact-missing` |
| completion | nothing on disk at the path at session end and no write this session | `artifact-missing` |
| scope | counts injected and the evidence count is below the claimed count (tests only) | `scope-narrower` |
| completion | no subject at all (only when `judge()` is called on a claim `judgeable()` would skip) | `no-evidence` |

**What it is not.**

- Not an accusation. It means "no trace found", not "the trace says otherwise". That is
  CONTRADICTED.
- Not "false". Work done outside the hooks leaves no trace (`capture.md`).

---

### UNVERIFIABLE

**Means:** the judge abstains. The claim was taken up for judging, but the capture cannot decide it
either way.

Reasons: `scope-unbindable`, `scope-property-unbound`, `outside-session`, `measurement-not-joined`,
`search-scope`, `listing-unobserved`, `unobserved-pre-state`, `repair-unbound`, `failure-unbound`,
`exit-is-result` (`WORD_KEY.md` explains each).

**What it is not.**

- **Not "an opinion, a judgement, a plan".** In the code, a sentence of opinion or plan usually
  matches no claim pattern and is never extracted. UNVERIFIABLE is given to claims of a checkable
  shape whose evidence is missing, out of scope, unbound, or ambiguous.
- Not a pass and not a fail. See `abstention.md`.
- Not the same as unjudged. An unjudged claim gets no verdict at all.

---

### CONTRADICTED

**Means:** the capture, or the disk at session end, holds an item that points the other way.
"Your agent said X; the evidence says not-X."

| Kind | When | Reason |
|------|------|--------|
| hedge | the hedge is about existence, and the session wrote the file | `was-confirmable` |
| coverage | the lowest joined measurement is below 95% | `measurement-disagrees` |
| absence | the session wrote the file and it was present afterwards | `artifact-present` |
| absence | a qualifying listing printed the name | `listed-present` |
| currency | a sibling on disk at session end is newer | `stale` |
| existence | the session deleted the file | `deleted-this-session` |
| existence | not on disk at session end, and a qualifying, still-current listing of its folder was captured and did not print the name | `artifact-missing` |
| completion (with success words) | the last bound command on the subject failed and was not repaired | `later-error` |

**What it is not.**

- Not a synonym for UNBACKED.
- Not proof of a lie. Some CONTRADICTED verdicts read the disk at session end (`stale`,
  `artifact-missing` for existence). A change made later by something outside the capture can cause
  them.
- Not available for every kind of claim. A completion claim without success words ("Created
  `/x/a.md`") can never be CONTRADICTED.

## In the code

| What | Where |
|------|-------|
| Verdict record | `receipts/judge.py:Verdict` (L203) |
| Entry point, hedge and scope | `receipts/judge.py:judge` (L212) |
| Kind branches | `receipts/judge.py:_judge_kind` (L489) |
| Which claims get judged | `receipts/judge.py:judgeable` (L189), `receipts/receipt.py:build` (L26) |
| Labels in the receipt | `receipts/receipt.py:render_md` (L69) |
| Every emission, line by line | `WORD_KEY.md` |

## Limits

- Project README, "Four verdicts per claim" (its table) and "What it does NOT establish".
- `KNOWN_LIMITS.md`, "Still open, named": **No held-out validation**; **The Day-3 share** has no truth
  labels; **Usefulness** (exposed synthetic cases where the claim was true; most that were not backed
  abstained; not an accuracy estimate).
- `KNOWN_LIMITS.md`, "Codex's targeted recheck of 6dc1938, and the definitions pass (2026-11-11)": the
  paragraph **"Disclosed, not changed"** (completion words are backed by a recorded write; a missing
  status counts as success).

## Related terms

`abstention.md` · `WORD_KEY.md` · `claim.md` · `scope.md` · `repair.md` · `listing.md` ·
`measurement.md` · `observation.md`

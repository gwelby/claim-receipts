# Scope
*claim-receipts canonical definition*
*Status: DRAFT v0.1 — not yet audited*
*Checked against `6dc1938` plus its uncommitted working-tree changes (2026-11-11). Line numbers are for that tree.*
*Depends on: `claim.md`, `verdict.md`. Related: `abstention.md`, `measurement.md`.*

---

**In one sentence:** Scope is the extent a claim asserts — "all", "every", "each", "entire", "whole",
"both", or for a coverage claim a count such as "two images" — and matching counts only admit such a
claim to judging; they never prove the claimed property.

## Age 5

"I ate all my peas" is bigger than "I ate a pea". Showing one eaten pea does not prove you ate all of
them. Counting the empty plate spots lets you start checking. It does not finish the check.

## The definition

**Setting the flag.** `extract_claims` sets `scope_all` when a sentence contains `all`, `every`,
`each`, `entire`, `whole` or `both` anywhere. For a coverage claim it is also set by a number or
number word followed by a word (`two images`, `3 pages`, `full-page at 300 dpi`), after paths are
removed so `page-2.png` does not count as "2 pages".

**Order.** A hedge is judged before scope. "I could not verify all of it" is a hedge, not an extent
claim.

**In production.** The receipt calls the judge without counts. So every judgeable claim with the
flag, of any kind except hedge, becomes **UNVERIFIABLE** (`scope-unbindable`). This includes:

- "Fixed `/x/app.py`; all tests pass." — even when the write is recorded;
- "`/q/p.png` fills the entire page." — `entire` is a scope word, so the coverage measurement is never
  consulted.

**With injected counts** (only the tests and the acceptance harness do this):

| Counts | Result |
|--------|--------|
| no claimed count, a claimed count of 0, or no evidence count | UNVERIFIABLE `scope-unbindable` |
| evidence count below claimed count | UNBACKED `scope-narrower` |
| evidence count covers claimed count | **admission only**: the kind is judged on the one resolved subject |
| … and that kind verdict is BACKED | UNVERIFIABLE `scope-property-unbound` (one member cannot speak for the set) |
| … and that kind verdict is anything else | that verdict stands (one failing member can contradict "all") |

**Admission versus proof.** "2 of 2 images were measured" says the set was reached. It says nothing
about whether each image has the claimed property. So counts can let a claim in; only judging each
member could prove it, and the judge judges one subject.

## What it is not

- **Not the scope of a listing.** `search-scope` is about which folder a listing covered
  (`listing.md`).
- **Not the "scope" in `hedge-matches-scope`.** There it means the hedge's subject (`observation.md`).
- **Not a reading of meaning.** "All" in "all right, done" sets the flag too.
- **Not a count the plugin computes in production.** No production path supplies counts.

## In the code

| What | Where |
|------|-------|
| Scope words | `receipts/judge.py:SCOPE` (L52) |
| Counts in coverage claims | `receipts/judge.py:COVERAGE_AGGREGATE` (L61) |
| Setting the flag | `receipts/judge.py:extract_claims` (L111) |
| Admission, then kind | `receipts/judge.py:judge` (L212), scope block (L245–271) |
| Production call, no counts | `receipts/receipt.py:build` (L26) |
| Callers that inject counts | `tests/test_acceptance.py`, `tests/test_judge_identity.py` |

## Limits

- Project README, "What it does NOT establish": **"All" is not proved by one.**
- `KNOWN_LIMITS.md`, "The return for Codex's HOLD on `fdb8f87`", row **C1** (it now states that "one failing
  member contradicts 'all'" holds only when counts are supplied).
- `KNOWN_LIMITS.md`, "Earlier defects (R1–R8)", row **R2**: count injection is a fixture-only path.
- `KNOWN_LIMITS.md`, "Hostile pre-check before the recheck (2026-11-10)": the row on "both" and
  numerals over a set.
- `KNOWN_LIMITS.md`, "Still open, named": **A scope word anywhere in a sentence makes it abstain.**

## Related terms

`claim.md` · `verdict.md` · `abstention.md` · `measurement.md`

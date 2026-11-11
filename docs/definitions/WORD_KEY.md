# The Word-Key — Reason Codes
*claim-receipts reason-code key*
*Status: DRAFT v0.1 — not yet audited*
*Checked against `6dc1938` plus its uncommitted working-tree changes (2026-11-11). Line numbers are for that tree.*

> A receipt line looks like `UNVERIFIABLE` · `search-scope` · *searched /x, outside its scope…*
> The first word is the verdict. The second is the reason. This file says what each reason means.

---

## How to use this file

Each entry has five parts:

1. **Say it** — how to read it aloud
2. **Verdict** — which verdict word it comes with (some reasons come with more than one)
3. **Means** — in plain words
4. **When you see it** — the situation that produces it
5. **Lives in** — `file:line` of every place it is emitted

**Read the verdict and the reason together.** Four reasons are shared: `outside-session` (six places,
always UNVERIFIABLE), `written-this-session` (two places, always BACKED), `deleted-this-session`
(BACKED for an absence claim, CONTRADICTED for an existence claim) and `artifact-missing`
(CONTRADICTED or UNBACKED).

**Where reasons come from.** Every reason is emitted in `receipts/judge.py`. `receipts/evidence.py`
emits no verdicts; it builds the evidence, and its `scope_report` writes the detail text for
`search-scope`.

**"Production"** below means the path a real session takes: `receipt.build` calls `judge()` on
judgeable claims, with no counts.

---

## Hedge reasons

### was-confirmable
- **Say:** "was confirmable"
- **Verdict:** CONTRADICTED
- **Means:** the session made the file, then said it could not confirm the file exists.
- **When you see it:** a hedge whose wording from the hedge phrase onward is about existence (exists,
  present, missing, on disk, was written/created/saved…), and the session's certified write left the
  subject present.
- **Lives in:** `receipts/judge.py:226`

### hedge-matches-scope
- **Say:** "hedge matches scope"
- **Verdict:** BACKED
- **Means:** the session really did look at the thing it says it could not verify.
- **When you see it:** a hedge with an absolute subject and an observation of that exact path; or a
  hedge with no subject at all (no path, no ALL-CAPS word, no `word/word`) and a successful
  observe-tool call such as `web_search` (`observation.md`).
- **Lives in:** `receipts/judge.py:232`

### hedge-unobserved
- **Say:** "hedge unobserved"
- **Verdict:** UNBACKED
- **Means:** "could not verify" asserts an attempt, and no attempt is in the capture.
- **When you see it:** no matching observation. Always the case for a relative subject: a bare name
  (`report.md`) or ALL-CAPS word that did not resolve, a path with a folder (`docs/report.md`), or any
  `word/word` in the sentence (`read/write`).
- **Lives in:** `receipts/judge.py:234`

---

## Scope reasons

### scope-unbindable
- **Say:** "scope unbindable"
- **Verdict:** UNVERIFIABLE
- **Means:** the claim asserts an extent (all, every, both, the entire page…) and no countable scope
  was bound.
- **When you see it:** in production, for every judgeable non-hedge claim with a scope word anywhere
  in the sentence (`scope.md`).
- **Lives in:** `receipts/judge.py:250`

### scope-narrower
- **Say:** "scope narrower"
- **Verdict:** UNBACKED
- **Means:** the claim covers more items than the evidence does.
- **When you see it:** only with injected counts (tests, acceptance harness). Not reached in production.
- **Lives in:** `receipts/judge.py:254`

### scope-property-unbound
- **Say:** "scope property unbound"
- **Verdict:** UNVERIFIABLE
- **Means:** the counts reach the whole set, but only one member was judged for the claimed property,
  so its favourable result cannot speak for all.
- **When you see it:** only with injected counts, when the single-subject verdict would have been
  BACKED. Not reached in production.
- **Lives in:** `receipts/judge.py:267`

---

## Coverage reasons

### outside-session (coverage)
- **Say:** "outside the session"
- **Verdict:** UNVERIFIABLE
- **Means:** no admitted measurement was taken in this session.
- **When you see it:** a coverage claim, and no percentage came from an admitted producer. The detail
  says how many quoted or printed percentage lines were refused, if any (`measurement.md`).
- **Lives in:** `receipts/judge.py:498`

### measurement-not-joined
- **Say:** "measurement not joined"
- **Verdict:** UNVERIFIABLE
- **Means:** measurements exist, but none is about this claim's file.
- **When you see it:** no measurement line or producing command names the subject's exact absolute
  path; or the claim has no absolute subject path at all.
- **Lives in:** `receipts/judge.py:512`

### measurement-disagrees
- **Say:** "measurement disagrees"
- **Verdict:** CONTRADICTED
- **Means:** a measurement of this file shows less than 95% coverage.
- **When you see it:** the lowest joined measurement is below 0.95. The detail quotes it.
- **Lives in:** `receipts/judge.py:519`

### measurement-agrees
- **Say:** "measurement agrees"
- **Verdict:** BACKED
- **Means:** every joined measurement of this file shows 95% coverage or more.
- **When you see it:** the lowest joined measurement is 0.95 or above.
- **Lives in:** `receipts/judge.py:521`

---

## Absence reasons

### artifact-present
- **Say:** "artifact present"
- **Verdict:** CONTRADICTED
- **Means:** the session wrote the file and then said it was absent.
- **When you see it:** an absence claim whose subject has a certified write that left it present.
- **Lives in:** `receipts/judge.py:527`

### deleted-this-session (absence)
- **Say:** "deleted this session"
- **Verdict:** BACKED
- **Means:** the file is absent because the session deleted it, as recorded by a write tool's hooks.
- **When you see it:** an absence claim whose subject's last certified change left it not existing.
- **Lives in:** `receipts/judge.py:529`

### search-scope
- **Say:** "search scope"
- **Verdict:** UNVERIFIABLE
- **Means:** no listing that can prove anything covers this path.
- **When you see it:** no listing ran; or the newest covering listing failed, was filtered or cut,
  reaches the path through a symbolic link; or the path is outside every listing's folder, depth or
  visible names, or a later command made the listing stale. The detail says which (`listing.md`).
- **Lives in:** `receipts/judge.py:534`

### listing-unobserved
- **Say:** "listing unobserved"
- **Verdict:** UNVERIFIABLE
- **Means:** a good listing covers the path, but its output was not captured, so nobody saw what it
  printed.
- **When you see it:** the listing's output could not be bound to exactly one captured output, or
  could not be parsed.
- **Lives in:** `receipts/judge.py:541`

### listed-present
- **Say:** "listed present"
- **Verdict:** CONTRADICTED
- **Means:** the listing printed the name the session said was absent.
- **When you see it:** the name appears among the entries printed directly under the claimed folder.
- **Lives in:** `receipts/judge.py:546`

### absence-established
- **Say:** "absence established"
- **Verdict:** BACKED
- **Means:** a narrow, complete, captured, current listing of the folder did not print the name.
- **When you see it:** every condition in `listing.md` holds, and the name is not in the entries.
- **Lives in:** `receipts/judge.py:548`

---

## Currency reasons

### outside-session (currency, no artifact)
- **Say:** "outside the session"
- **Verdict:** UNVERIFIABLE
- **Means:** no artifact was identified.
- **When you see it:** a currency claim with no resolved path. Not reached in production, where such a
  claim is left unjudged.
- **Lives in:** `receipts/judge.py:554`

### stale
- **Say:** "stale"
- **Verdict:** CONTRADICTED
- **Means:** something next to it is newer, so it is not the latest.
- **When you see it:** on disk at session end, an entry beside the folder that holds the claimed file
  (or, when the claim names a folder, an entry beside that folder) has a later modification time. The
  detail names up to three.
- **Lives in:** `receipts/judge.py:557`

### outside-session (currency, no listing)
- **Say:** "outside the session"
- **Verdict:** UNVERIFIABLE
- **Means:** no current listing covers the claimed folder, so "current" was never checked.
- **When you see it:** no newer sibling, but no qualifying listing covers the claimed folder, or the
  one that does was made stale by a later command (`listing.md`).
- **Lives in:** `receipts/judge.py:564`

### newest-in-scope
- **Say:** "newest in scope"
- **Verdict:** BACKED
- **Means:** nothing beside it is newer, and the session did look there.
- **When you see it:** no newer sibling on disk at session end, and a qualifying, still-current listing
  covers the claimed folder (the folder holding the claimed file). The listing's printed output is
  not read; the disk decides.
- **Lives in:** `receipts/judge.py:566`

---

## Existence reasons

### unobserved-pre-state
- **Say:** "unobserved pre-state"
- **Verdict:** UNVERIFIABLE
- **Means:** a write to this path was seen, but what was there before was never captured, so the write
  cannot be certified.
- **When you see it:** an existence claim on an absolute path that has an incomplete mutation
  (`ledger.md`).
- **Lives in:** `receipts/judge.py:573`

### written-this-session
- **Say:** "written this session"
- **Verdict:** BACKED
- **Means:** a certified write left the file present.
- **When you see it:** an existence claim (L577), or a completion claim with no standing failure,
  unbound success, unbound failure or result exit (L671). For completion words such as "verified" or
  "reviewed", this still only means the file was written.
- **Lives in:** `receipts/judge.py:577`, `receipts/judge.py:671`

### deleted-this-session (existence)
- **Say:** "deleted this session"
- **Verdict:** CONTRADICTED
- **Means:** the session said the file exists, but it deleted it.
- **When you see it:** an existence claim whose subject's last certified change left it not existing.
- **Lives in:** `receipts/judge.py:578`

### listed-this-session
- **Say:** "listed this session"
- **Verdict:** BACKED
- **Means:** the file is there, and the session looked in the place it is.
- **When you see it:** no write this session; the file is on disk at session end; a qualifying,
  still-current listing covers it. The listing's printed output is not read. A later command that may
  have changed the path (`make build`) turns this into `outside-session`.
- **Lives in:** `receipts/judge.py:582`

### outside-session (existence, untouched)
- **Say:** "outside the session"
- **Verdict:** UNVERIFIABLE
- **Means:** the file exists, but this session neither wrote it nor looked there.
- **When you see it:** the file is on disk at session end, with no write, and no qualifying listing
  covers it or the one that does is stale.
- **Lives in:** `receipts/judge.py:583`

### artifact-missing (existence, contradicted)
- **Say:** "artifact missing"
- **Verdict:** CONTRADICTED
- **Means:** the file is not there, and the session looked where it would be.
- **When you see it:** no write; not on disk at session end; a qualifying, still-current listing of its
  folder covers it, its output was captured, and the name is not among the entries it printed.
- **Lives in:** `receipts/judge.py:590`

### artifact-missing (existence, unbacked)
- **Say:** "artifact missing"
- **Verdict:** UNBACKED
- **Means:** the file is not there and nothing shows it ever was.
- **When you see it:** no write; not on disk at session end; and no captured, still-current listing of
  its folder shows the name missing (none ran, it is stale, or its output was not captured).
- **Lives in:** `receipts/judge.py:591`

### outside-session (existence, no artifact)
- **Say:** "outside the session"
- **Verdict:** UNVERIFIABLE
- **Means:** no artifact was identified.
- **When you see it:** an existence claim with no resolved path. Not reached in production.
- **Lives in:** `receipts/judge.py:593`

---

## Completion reasons

### repair-unbound
- **Say:** "repair unbound"
- **Verdict:** UNVERIFIABLE
- **Means:** a check on this file failed; a later command on it succeeded, but that is not proven to be
  the same check re-run, so the failure's standing is unknown.
- **When you see it:** a completion claim with a success word ("fixed"), after a bound failure, then a
  success that is a different command, or the same command with either folder unrecorded, the folders
  different, or either command cut by the ledger (`repair.md`). `KNOWN_LIMITS.md` states that
  Hermes's terminal tool does not pass the folder to the hook; if so, every re-run on a live session
  lands here.
- **Lives in:** `receipts/judge.py:653`

### later-error
- **Say:** "later error"
- **Verdict:** CONTRADICTED
- **Means:** the last check that named this exact file failed, and nothing repaired it.
- **When you see it:** a completion claim with a success word, and a standing bound failure.
- **Lives in:** `receipts/judge.py:658`

### failure-unbound
- **Say:** "failure unbound"
- **Verdict:** UNVERIFIABLE
- **Means:** a related command failed, but it does not name this exact file, so it neither counts
  against the claim nor can be ruled out.
- **When you see it:** the failing command mentions the file name but not as a whole absolute-path
  operand (a relative name, a look-alike, text in `echo`/`printf`).
- **Lives in:** `receipts/judge.py:661`

### exit-is-result
- **Say:** "exit is result"
- **Verdict:** UNVERIFIABLE
- **Means:** a check on this file returned non-zero, but for `grep`, `diff`, `cmp`, `test` that is an
  answer (no match, differs, false), not an error, and the record cannot tell which.
- **When you see it:** a bound failure where a result verb runs in a segment the call's status speaks
  for.
- **Lives in:** `receipts/judge.py:666`

### outside-session (completion)
- **Say:** "outside the session"
- **Verdict:** UNVERIFIABLE
- **Means:** the file exists, but the session did not write it.
- **When you see it:** a completion claim on a file that is on disk at session end with no certified
  write. Running a check on it does not change this.
- **Lives in:** `receipts/judge.py:673`

### no-evidence
- **Say:** "no evidence"
- **Verdict:** UNBACKED
- **Means:** no artifact the session touched.
- **When you see it:** a completion claim with no resolved path. Not reached in production, where such a
  claim is left unjudged.
- **Lives in:** `receipts/judge.py:676`

### artifact-missing (completion)
- **Say:** "artifact missing"
- **Verdict:** UNBACKED
- **Means:** nothing at that path and no write this session.
- **When you see it:** a completion claim on a path that is not on disk at session end and was not
  written.
- **Lives in:** `receipts/judge.py:677`

---

## Not a reason code: unjudged

A claim whose subject cannot be located gets **no verdict and no reason**. The receipt counts it as
`unjudged` and samples it. See `abstention.md`.

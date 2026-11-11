# Claim
*claim-receipts canonical definition*
*Status: DRAFT v0.1 — not yet audited*
*Checked against `6dc1938` plus its uncommitted working-tree changes (2026-11-11). Line numbers are for that tree.*
*Depends on: `capture.md`. Related: `verdict.md`, `scope.md`.*

---

**In one sentence:** A claim is one sentence of the assistant's own prose that matches one of the
plugin's fixed patterns, kept with its kind, its subject (when one can be read) and a flag that says
whether it asserts an extent.

## Age 5

When you say "I cleaned my room!", that is a claim. The plugin listens for a few kinds of sentence
like that. If you say it in a way it does not know, it does not hear it at all.

## The definition

**Where claims come from.** The assistant messages read from the transcript (`capture.md`).

**Splitting.** The text is split after `.`, `!` or `?` followed by white space, and at line breaks.
A piece is dropped if it is shorter than 8 characters, or contains `->`, `MUTATION`, or two or more
`|` (these are read as quoted reports or tables, not the agent's own claims).

**Kind.** The first pattern that matches decides the kind, in this order:

| Kind | Matches words such as |
|------|----------------------|
| `hedge` | could not confirm, cannot verify, unable to verify, not verified, unverified, no information |
| `coverage` | full-page, full-bleed, edge-to-edge, entire page, entire surface, 100% of the page, fills the page |
| `absence` | does not exist, never existed, no such file, not found, is missing, was missing, absent |
| `currency` | current, latest, newest, up to date, most recent |
| `existence` | exists, is there, present, already written, is written |
| `completion` | done, fixed, completed, finished, shipped, built, created, wrote, saved, generated, verified, passed, applied, patched, reviewed, checked, looked at, … |

A sentence that matches none of these is not a claim.

**Subject.** The first thing in the sentence that looks like a file:

- an absolute path with at least two parts (`/x/report.md`), or
- a bare file name ending in `.md .py .pdf .json .txt .png .csv .db .yaml .yml`.

Neither may follow directly after a letter, digit, `_`, `.`, `-` or `/`. If there is no such token,
the subject is the first ALL-CAPS word of three or more characters (`PROOF2`). Quotes, backticks and
trailing punctuation are stripped. A sentence may have no subject.

**Scope flag.** `scope_all` is set when the sentence contains `all`, `every`, `each`, `entire`,
`whole` or `both` anywhere. For a coverage claim it is also set by a count of things ("two images",
"3 pages"). See `scope.md`.

**One claim per sentence.** A repeated sentence is kept once. Claim text is cut to 300 characters.

**Judgeable or not.** Only some claims get a verdict:

- a `hedge` or `coverage` claim is always judged;
- any other claim is judged only if its subject **resolves** to a path:
  - an absolute path is used as written (normalised);
  - a relative path with a folder in it does not resolve;
  - a bare name resolves to a file the session wrote (a certified mutation) whose file name is
    exactly the subject (case is ignored). Among several, one the session wrote is preferred, then
    the shortest path. (In test fixtures the fixture filesystem is searched too.)

**A hedge's fallback scope.** A hedge with no subject is checked once more: if the sentence contains a
relative path with a folder (`docs/report.md`, `./x/y`), that becomes the hedge's scope. The match is
loose: any `word/word` that is not part of a URL counts, so `read/write` or `and/or` does too. See
`observation.md` for what this does to the verdict.

A claim that is not judged is **unjudged**: counted and sampled in the receipt, never given a verdict.

## What it is not

- **Not comprehension.** Detection is pattern matching. A paraphrase is missed.
- **Not the work the words describe.** "Verified", "reviewed", "checked" and "passed" are completion
  words. A completion claim is judged by whether the file was written, not by whether a review or a
  test happened (see `verdict.md`, BACKED).
- **Not every sentence with a file in it.** A sentence with a file but no claim word is ignored.
- **Not a fact.** A claim is what was said. The verdict is what the capture shows.
- **"Success" is not a separate kind.** Words like `fixed`, `resolved`, `now works`, `is fixed` only
  matter inside a completion claim, where they switch on the failure check in `repair.md`.

## In the code

| What | Where |
|------|-------|
| Claim record | `receipts/judge.py:Claim` (L93) |
| Relative path in a hedge | `receipts/judge.py:_REL_PATH` (L100), `_relative_path_in` (L103) |
| Patterns | `receipts/judge.py:HEDGE` (L34), `ABSENCE` (L39), `CURRENCY` (L43), `COMPLETION` (L45), `EXISTENCE` (L50), `SCOPE` (L52), `COVERAGE_AGGREGATE` (L61), `SUCCESS` (L68), `COVERAGE` (L71) |
| Subject patterns | `receipts/judge.py:PATHISH` (L78), `TOKENISH` (L79) |
| Splitting, kind, subject, flag | `receipts/judge.py:extract_claims` (L111) |
| Subject to path | `receipts/judge.py:resolve` (L160) |
| Judged or not | `receipts/judge.py:judgeable` (L189) |
| Where it is called | `receipts/receipt.py:build` (L26) |

## Limits

- Project README, "What it does NOT establish": **Only recognised claims are judged**, and **How a
  claim finds its file**.
- `KNOWN_LIMITS.md`, "Still open, named": **A scope word anywhere in a sentence makes it abstain**;
  **An ALL-CAPS word in a hedge is taken as its subject**.
- Bare names with other extensions (`app.js`, `run.sh`, `index.html`) are not subjects.
- A relative path with a folder (`docs/report.md`) is not read as a subject: the subject pattern
  skips it. A completion, existence, absence or currency claim about it is unjudged. A hedge about it
  is scoped to it and cannot be backed (`observation.md`).
- In production a bare name resolves only against files the session wrote with a captured
  before-state. A file it only read or listed does not resolve the name.
- Only the first file-like token is the subject. A sentence about two files is judged on the first.

## Related terms

`capture.md` · `verdict.md` · `scope.md` · `observation.md` · `repair.md` · `abstention.md`

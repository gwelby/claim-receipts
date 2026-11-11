# Capture
*claim-receipts canonical definition*
*Status: DRAFT v0.1 — not yet audited*
*Checked against `6dc1938` plus its uncommitted working-tree changes (2026-11-11). Line numbers are for that tree.*
*Depends on: `ledger.md`. Related: `observation.md`, `listing.md`, `measurement.md`.*

---

**In one sentence:** The capture is the evidence record a session can be held to: the ledger the
hooks wrote during the session, plus the session's own transcript, read from Hermes's store when the
session ends.

## Age 5

The capture is what the grown-up saw and wrote in the notebook, plus a tape of what everyone said.
If something happened while nobody was watching, it is not in the capture. That does not mean it
did not happen.

## The definition

The capture has two parts. They are joined into one `Evidence` object by `Evidence.from_session`.

**1. The ledger** (written during the session; see `ledger.md`). From it the plugin builds:

- **mutations** — certified writes: the path and its final "after" state;
- **incomplete mutations** — writes whose "before" was never captured; kept, never certified;
- **commands**, in order, each with a success flag; **failed commands**;
- **events** — writes and commands in one ordered stream, each command with its recorded folder and
  whether the ledger cut it (used by `repair.md`);
- **listings** — admitted directory listings found inside commands (`listing.md`);
- **observed segments** — commands led by a verb that looks at something (`observation.md`).

A record's `status` counts as success when it is missing, `"ok"` or `"success"`.

**2. The transcript** (read once, at session end, read-only). From Hermes's SQLite store
(`~/.hermes/state.db`, or `RECEIPTS_TRANSCRIPT_DB`), the plugin reads:

- **tool outputs** — the newest tool-result rows for the session, at most 600. Each output keeps at
  most 20,000 characters; a longer one is cut and marked `truncated`. A row is also marked
  `truncated` when the host's own text says it was cut. Reading stops after about 400,000 characters
  in total. Each output is joined to the call that made it through `tool_call_id`, which gives its
  `command` (for terminal calls) or `path` (for reads). An exit code and an error flag are taken from
  the JSON envelope when there is one.
- **assistant prose** — the session's assistant messages, newest 600, joined oldest first. This is
  where claims are found (`claim.md`). It is not evidence.

**Not part of the capture, but consulted.** When the receipt is built, some checks read the
filesystem as it is *then*: `stat()` of a claimed path, the entries of a folder (for "is this
current?"), and whether a path runs through a symbolic link. These describe the disk at session end,
not during the session.

## What it is not

- **Not everything the session did.** A file changed by a terminal command, by another process, or
  before the hooks loaded is not a mutation.
- **Not the truth.** A verdict compares a claim with the capture. Agreement with a capture is not
  truth. (Project README, opening section.)
- **Absence from the capture is not evidence of absence.** (Project README, "What it does NOT
  establish".)
- **Not authentication.** The capture does not show who or what made a call.
- **A path named in output is not a change.** Only a differing `stat()` across a write call is a
  mutation. (Project README, "The distinguishing rule".) Listing output is used, narrowly, to see
  which names a folder held (`listing.md`).

## In the code

| What | Where |
|------|-------|
| Joining ledger and transcript | `receipts/evidence.py:Evidence.from_session` (L1209) |
| Turning a ledger record into evidence | `receipts/evidence.py:Evidence._ingest` (L1064) |
| What counts as a successful status | `receipts/evidence.py:_ok` (L181) |
| Reading tool outputs and their calls | `receipts/transcript.py:read_tool_outputs` (L88), `_call_commands` (L40) |
| Reading assistant prose | `receipts/transcript.py:read_assistant_text` (L176) |
| Read limits | `receipts/transcript.py:MAX_MESSAGES`, `MAX_OUTPUT_CHARS`, `MAX_TOTAL_CHARS` (L22–24) |
| Live filesystem at receipt time | `receipts/evidence.py:Evidence.stat` (L768), `siblings_newer_than` (L790), `_is_link` (L863) |
| Fixture form (tests) | `receipts/evidence.py:Evidence.from_fixture` (L1225) |

## Limits

- Project README, "What it does NOT establish": **Capture is bounded by the hooks.**
- `KNOWN_LIMITS.md`, "Still open, named": **the transcript join** was checked against Hermes's source
  and synthetic transcripts, not against a live Hermes host.
- `KNOWN_LIMITS.md`, "Hostile pre-check before the recheck (2026-11-10)", paragraph **"Settled from
  Hermes's source"**: how a missing tool status is derived by Hermes was read from source, not run.
- A missing `status` is read as success by the code. If a host ever leaves status out for a failed
  call, that call counts as a success.
- The transcript limits (600 rows per query, 20,000 characters per output) mean a long session is not
  fully read. Anything beyond them is outside the capture.
- Fail-open: an unreadable store gives no tool outputs and no prose. The receipt then says no
  transcript was readable (`receipt.md`).

## Related terms

`ledger.md` · `observation.md` · `listing.md` · `measurement.md` · `claim.md` · `verdict.md`

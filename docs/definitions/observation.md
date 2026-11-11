# Observation
*claim-receipts canonical definition*
*Status: DRAFT v0.1 — not yet audited*
*Checked against `6dc1938` plus its uncommitted working-tree changes (2026-11-11). Line numbers are for that tree.*
*Depends on: `capture.md`, `listing.md`. Related: `verdict.md` (hedges).*

---

**In one sentence:** An observation is a captured sign that the session actually looked at a
particular thing — and a hedge ("I could not verify X") is backed only when such a look at X is in the
capture.

## Age 5

If you say "I looked for my shoe and could not find it", someone may ask: "Did you really look?"
An observation is the proof that you looked, and that you looked in the right place.

## The definition

Observations are used for one purpose: judging **hedge** claims (`claim.md`). The test is
`Evidence.has_observation(subject)`.

**A hedge with an absolute subject path** is observed when any one of these is in the capture:

1. **An observe command on that path.** A command segment that ran, led by one of `ls dir tree find
   grep rg cat head tail wc stat curl`, which takes the exact subject path as an operand, and which
   succeeded. "Succeeded" means: the record's status is success, no later `;`, `||` or `|` (and no
   earlier `||`) could have hidden a failure, and the transcript does not mark the call as failed. For `grep` and `rg` only
   file operands count, never the search pattern.
2. **A search that found nothing.** A command that is a single `grep` or `rg` segment, with the
   subject as a file operand, whose captured exit code for that exact call is `1` ("no match").
3. **A listing that saw it.** A successful listing that is complete, covers the subject, does not
   reach it through a symbolic link, and whose output was captured; or any successful listing whose
   captured output printed the subject at its exact location (`listing.md`).
4. **A native read of it.** A `read_file` call whose `path` argument is the subject, whose result was
   captured in the JSON envelope, with no error and an exit code of none or 0.

The match is on the exact normalised absolute path. A file with the same name elsewhere does not count.

**A hedge with a relative subject** is never observed and cannot be backed. Its verdict is UNBACKED
(`hedge-unobserved`). This covers:

- a bare name that did not resolve (`report.md`);
- an ALL-CAPS word that did not resolve (`API`);
- a relative path with a folder anywhere in the sentence (`docs/report.md`), and also any other
  `word/word` such as `read/write` or `and/or` (`claim.md`, "A hedge's fallback scope").

**A hedge with no subject at all** (no path, no ALL-CAPS word, no `word/word`) is observed only by an **observe tool**: a tool other than `terminal` and
`read_file` whose name has a part such as `search`, `find`, `grep`, `read`, `query`, `lookup`,
`fetch`, `scan`, `inspect` (`web_search` is the usual case), that the host did not mark as an error.
A terminal command or a file read does not back an unscoped hedge.

## What it is not

- **Not a change.** An observation shows a look, not work. It never backs a completion claim.
- **Not a mention.** A path printed by `echo`/`printf`, written inside quotes, or used as a `grep`
  pattern was not looked at.
- **Not a look at something else.** `cat /a/x.md` is no attempt at `/b/x.md`.
- **Not proof of the hedge's content.** A BACKED hedge means an attempt is in the capture. It does
  not mean the thing really could not be verified.

## In the code

| What | Where |
|------|-------|
| The test | `receipts/evidence.py:Evidence.has_observation` (L975) |
| Observe verbs and observe-tool words | `receipts/evidence.py:_OBSERVE_VERBS` (L56), `_OBSERVE_TOOL_WORDS` (L60), `_tool_observes` (L185) |
| Observe segments of a command | `receipts/evidence.py:_observe_operands` (L434), `_grep_files` (L460) |
| Status bound to a segment | `receipts/evidence.py:_status_bound` (L322) |
| Exit 1 as "searched, found nothing" | `receipts/evidence.py:exit1_is_result_cmd` (L161), `Evidence._exit_code` (L1043) |
| Native read | `receipts/evidence.py:Evidence._read_ok` (L1054) |
| Use in judging | `receipts/judge.py:judge` (L212), hedge branch (L220–236); `_relative_path_in` (L103) |

## Limits

- Project README, "What it does NOT establish": **A hedge needs its observation**; **Hedging alone
  earns nothing**.
- `KNOWN_LIMITS.md`, "The return for Codex's HOLD on `fdb8f87`", row **C2**.
- `KNOWN_LIMITS.md`, "Hostile pre-check before the recheck (2026-11-10)": the rows on a relative-path
  hedge and on an unscoped hedge backed by any command; and the paragraph "Widened by this round"
  (a native `web_search` backs an unscoped hedge).
- `KNOWN_LIMITS.md`, "Second independent pass (2026-11-11)": the rows on `grep` exit 1 and on a `grep`
  pattern counted as an observed file.
- `KNOWN_LIMITS.md`, "Still open, named": **An ALL-CAPS word in a hedge is taken as its subject.**
- `KNOWN_LIMITS.md`, "Codex's targeted recheck of 6dc1938, and the definitions pass (2026-11-11)": the
  row on a hedge naming a relative path with a folder.
- **A slash in ordinary words scopes a hedge.** "I could not verify the read/write layout" is scoped to
  `read/write` and comes back UNBACKED even after a `web_search`. Without the slash it would be
  BACKED. This is an unfavourable verdict, not an abstention. (Checked by running the judge on the
  current tree.)
- **Any `web_search` backs any unscoped hedge.** The search does not have to be about the hedge's
  topic.

## Related terms

`listing.md` · `verdict.md` (hedge reasons) · `claim.md` · `capture.md`

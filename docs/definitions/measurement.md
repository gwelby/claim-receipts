# Measurement
*claim-receipts canonical definition*
*Status: DRAFT v0.1 — not yet audited*
*Checked against `6dc1938` plus its uncommitted working-tree changes (2026-11-11). Line numbers are for that tree.*
*Depends on: `capture.md`. Related: `verdict.md` (coverage), `scope.md`.*

---

**In one sentence:** A measurement is a coverage percentage printed by a command that completed in the
session, in a clause that names what was measured; it is the only evidence that can back or
contradict a coverage claim such as "the image is full-page".

## Age 5

If you say "I coloured the whole page", someone can hold up a ruler and say "you coloured half".
The plugin never holds the ruler itself. It only reads what a ruler the session used said.

## The definition

### Taking a measurement

`Evidence.measured_fractions` reads each captured tool output and keeps a percentage only when all of
these hold:

1. **It is not a file body.** Outputs of `read_file`, `write_file` and `patch` are skipped.
2. **The producer completed.** The output's own status is success (exit code 0 in its envelope). If
   it has no status, the hook's record of the same call id must say success, and there must be
   exactly one such record. With no call id on either side, the command text may join only when
   there is exactly one output and one record of that command.
3. **The output was not cut.**
4. **The producing command is plain.** The splitter can segment it (no heredoc, `$( )`, backticks,
   lone `&`), only `&&` joins its segments (no `;`, `||`, `|`), and no segment runs inline
   interpreter code (`python3 -c`, `node -e`, `python3 -`, …).
5. **The line is a measurement line.** It is not a progress render (`45%|`, `|###|`, `it/s`,
   `Loading`, `ETA`, a line that is only a percentage). It names a measure word: `coverage`, `ink`,
   `bbox`, `filled`, `area`, `page fill`, `occupied`. It contains no `{`, `}`, `"` or `|`.
6. **The clause is about extent.** The line is split at `;` and `,`. A clause counts only if it names
   a measure word and no complement word: `margin(s)`, `whitespace`, `white space`, `blank`, `empty`,
   `bleed`, `padding`, `border(s)`, `gutter(s)`, `unused`, `free`, `dpi`, `ppi`.

Each percentage from 0 to 100 in such a clause becomes a fraction, kept with its line (up to 4,096
characters) and its command.

### Using a measurement

The coverage branch of the judge then:

1. **Admits only commands that are not text producers.** The command must exist and segment cleanly.
   No word anywhere in it may be the name of a program that reproduces text (`echo printf cat head
   tail sed awk grep cut sort tee jq xargs …`), and it may not run interpreter code inline (`-c`,
   `-e`, `--eval`, `-`, or a heredoc). If nothing is admitted: **UNVERIFIABLE**
   (`outside-session`).
2. **Joins on the exact subject.** If the line names absolute paths, one of them must be the claim's
   subject path. If the line names none, its command must name the subject path and no other path
   with the same extension. If nothing joins: **UNVERIFIABLE** (`measurement-not-joined`).
3. **Compares the lowest joined value with 0.95.** Below 0.95: **CONTRADICTED**
   (`measurement-disagrees`). At or above: **BACKED** (`measurement-agrees`).

## What it is not

- **Not something the plugin measures.** It reads a number a session command printed.
- **Not any percentage.** Progress bars, quoted text, file bodies, printed or echoed text, and
  margins are excluded.
- **Not the Day-3 ratio.** `unbacked_claim_share` is a share of verdicts, not a measurement and not a
  false-positive rate. It has no truth labels and must not be quoted as precision.
  (`KNOWN_LIMITS.md`, row **R7**.)
- **Not a measure of the plugin's accuracy.** There is no held-out validation. The usefulness figures
  in `KNOWN_LIMITS.md` come from synthetic sessions.
- **Not tuned.** The 0.95 cut-off is a fixed constant in `judge.py`.

## In the code

| What | Where |
|------|-------|
| Taking measurements | `receipts/evidence.py:Evidence.measured_fractions` (L1125) |
| Line length kept | `receipts/evidence.py:MEASURE_LINE_CAP` (L137) |
| Inline interpreter code | `receipts/evidence.py:_inline_code` (L98) |
| Text producers | `receipts/judge.py:_TEXT_PRODUCERS` (L401), `_text_producer` (L409) |
| Admitted producer | `receipts/judge.py:_admitted_producer` (L419) |
| Subject join | `receipts/judge.py:_measurement_names` (L434) |
| Coverage verdicts and the 0.95 cut-off | `receipts/judge.py:_judge_kind`, coverage branch (L492–521) |

## Limits

- `KNOWN_LIMITS.md`, "Hostile pre-check before the recheck (2026-11-10)": the row on a coverage figure
  printed by `printf`/`cat`, matched by file name, or over "both"; and "Narrowed by this round" (a
  real measurement piped through `grep` or printed by `python3 -c` abstains).
- `KNOWN_LIMITS.md`, "Second independent pass (2026-11-11)": the rows on a heredoc-fed interpreter
  and on "margins 5%".
- `KNOWN_LIMITS.md`, "Codex's recheck of 2358d20 (2026-11-11)", row **R3**; "Codex's targeted recheck
  of 6a6aae3 (2026-11-11)", row **N3**.
- `KNOWN_LIMITS.md`, "Still open, named": **The text-producer list is a denylist.** An unlisted
  program that only prints "coverage 100%" would still be read as a measurement.
- A coverage claim with a scope word or a count ("the entire page", "both images") never reaches the
  measurement in production. It abstains first (`scope.md`).

## Related terms

`verdict.md` · `scope.md` · `capture.md` · `WORD_KEY.md`

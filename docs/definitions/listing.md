# Listing
*claim-receipts canonical definition*
*Status: DRAFT v0.1 — not yet audited*
*Checked against `6dc1938` plus its uncommitted working-tree changes (2026-11-11). Line numbers are for that tree.*
*Depends on: `ledger.md`, `capture.md`. Related: `observation.md`, `verdict.md`.*

---

**In one sentence:** A listing is a recorded terminal command that enumerated one folder; it is the
only command evidence that can prove a name is absent, and only when it is narrow, successful,
complete, captured, the newest one, and not made stale by anything that ran after it.

## Age 5

To say "there is no cookie in the jar", you have to look in the jar. You have to look in the whole
jar, not just the top. And if someone could have put a cookie in after you looked, your look is
too old to count.

## The definition

### What counts as a listing

A listing is a command segment, led by `ls`, `dir`, `find`, `grep` (with `-r`/`-R`) or `tree`, in a
terminal command the plugin can split into segments. The splitter refuses — and so finds no listing —
when the command has unbalanced quotes, parentheses, backticks, `$( )`, a heredoc or herestring
(`<<`), or a lone `&`. A verb inside quotes (`printf 'x; ls /y'`) is not a listing.

### When a listing can prove absence

All of these must hold.

1. **It succeeded.** The record's status is success, and no later `;`, `||` or `|` (and no earlier
   `||`) could have hidden its failure.
2. **It is complete.**
   - Not piped (`|`) and not redirected (`>`, `<`).
   - `ls`/`dir`: only the short flags `1 a A l C x R t r S U h` and the long flags `--all`,
     `--almost-all`; and not two format flags (`l 1 C x`) at once.
   - `find`: only `-maxdepth N`, one `-name`/`-iname`, and `-print`.
   - `grep -r` is never complete: it prints matching files, so its silence proves nothing.
   - `tree` is never complete and its output is never read.
   - Exactly one operand, and it is a literal absolute path: no `$ \` * ? [ ] { } ~`, no `..`.
3. **It covers the path.** The path is inside the folder; within depth (`ls`: one level unless `-R`;
   `find`: `-maxdepth` or any depth); a dot-name only if `ls` had `-a`/`-A` or a long flag (`find`
   shows dot-names); and the name matches `find`'s `-name` pattern if one was given.
4. **It is the newest listing that covers the path.** An older listing is never used instead.
5. **Its output was captured and is its own.** Exactly one transcript output belongs to its call.
   Every other segment of the same command is silent (`cd true : export set unset umask`). The output
   is not marked failed and not cut.
6. **Its output can be read.** No error line (`ls: …`, `Permission denied`, `cannot open directory`).
   `ls -l` rows have the plain nine-field shape. Column output has no single-space gap (that would be
   a name with a space). No line is an absolute path.
7. **No symbolic link** lies between the folder and the path. This is checked on disk when the
   receipt is built, not when the listing ran.
8. **It is not stale** (below).

Then: if the name appears among the entries printed directly under the claimed folder, an absence
claim is **CONTRADICTED** (`listed-present`). If it does not, the absence claim is **BACKED**
(`absence-established`). If the listing covers the path but its output was not captured, the claim is
**UNVERIFIABLE** (`listing-unobserved`). If no listing qualifies, **UNVERIFIABLE** (`search-scope`).

### When a listing goes stale

A listing speaks for the moment it ran. It stops speaking for a path when something that ran
**after** it (a later record, or a later segment of the same command) may have changed that path:

- **A recorded write** to the path.
- **A bounded mutator** — `touch rm rmdir mkdir cp mv ln chmod chown truncate tee unlink` — that
  names the path or a folder above it by absolute path, has a relative operand sharing any name with
  the path's parts below the listed folder, or uses a glob or variable.
- **A redirect target** of any command (`: > T`) that does the same.
- **Anything else that is not known to only look** stales every earlier listing, for every path:
  any program not on the read-only list (`ls dir tree cat head tail wc stat grep rg cd true : echo
  printf pwd test file du df date whoami which find [ [[`), inline interpreter code (`python3 -c`,
  `bash -c`, `python3 -`), `find` with `-delete`/`-exec` and similar, every `git` command except
  `git [-C DIR] status` with a few harmless options, and any command the splitter refuses.

## What it is not

- **Not a snapshot of now.** It is a look at one moment. Staleness rules decide when it may still be
  used.
- **Not any command that mentions a folder.** Only the verbs and shapes above.
- **Not proof of absence everywhere.** Only inside its folder, depth and visible names.
- **Not the only thing used by existence and currency claims.** For those, the disk at session end is
  read first, and a listing that qualifies and is still current (not stale) is needed as well:
  - "`/q/x.md` exists" is BACKED (`listed-this-session`) when the file is on disk at session end and
    such a listing covers it. The listing's printed output is not read.
  - "`/q/x.md` exists" is CONTRADICTED (`artifact-missing`) only when the file is not on disk at
    session end and such a listing of `/q` was captured and did not print `x.md`. With the listing's
    output not captured, the same claim is UNBACKED.
  - "`/r/b/x.md` is the latest" is BACKED (`newest-in-scope`) when nothing beside `/r/b` is newer on
    disk and such a listing covers `/r/b`. The listing's printed output is not read.
  A later `make build` after the listing turns the BACKED cases into UNVERIFIABLE (`outside-session`).
  (Checked by running the judge on the current tree.)

## In the code

| What | Where |
|------|-------|
| Splitting a command | `receipts/evidence.py:_segments` (L198) |
| Listing shapes and completeness | `receipts/evidence.py:_listing_of` (L347), `_LS_OK_SHORT` (L38), `_LS_FORMAT_SHORT` (L44) |
| Listings in a command | `receipts/evidence.py:_listings_in` (L413) |
| Literal absolute operand | `receipts/evidence.py:_abs_operand` (L333) |
| The listing record | `receipts/evidence.py:Listing` (L587) |
| Coverage, depth, dot-names, staleness | `receipts/evidence.py:Listing.covers` (L608) |
| Newest covering listing | `receipts/evidence.py:Evidence._latest_covering` (L815) |
| A listing that can prove something | `receipts/evidence.py:Evidence.searched_for` (L848) |
| Symbolic links | `receipts/evidence.py:Evidence._through_symlink` (L871) |
| Output binding | `receipts/evidence.py:Evidence._bound_output` (L911) |
| Reading entries | `receipts/evidence.py:_parse_entries` (L667), `_ls_long_name` (L649), `Evidence.entries_of` (L961) |
| What may have changed a path | `receipts/evidence.py:_touches_in` (L514), `_touch_hits` (L569), `_READONLY_VERBS` (L70), `_BOUNDED_MUTATORS` (L499), `_git_status_only` (L506), `_inline_code` (L98) |
| Absence verdicts | `receipts/judge.py:_judge_kind`, absence branch (L524–549); existence (L570–593); currency (L552–567) |

## Limits

- Project README, "What it does NOT establish": **A listing proves absence only in a narrow form.**
- `KNOWN_LIMITS.md`, "Earlier defects (R1–R8)", row **R4**; "The return for Codex's HOLD on
  `fdb8f87`", row **C2**.
- `KNOWN_LIMITS.md`, "Hostile pre-check before the recheck (2026-11-10)": rows on conflicting `ls`
  flags, symbolic links, heredocs and `; true`, and a later `touch`/`rm`/`: >`; and "Narrowed by this
  round" (any later `$( )` or subshell stales a listing, which can be broad).
- `KNOWN_LIMITS.md`, "Codex's recheck of 2358d20 (2026-11-11)", row **R2**; "Codex's targeted recheck
  of 6a6aae3 (2026-11-11)", row **N2**.
- `KNOWN_LIMITS.md`, "Still open, named": **Column `ls` output** with a name containing two spaces is
  not caught.
- A change made outside any recorded call does not stale a listing. The plugin cannot see it.

## Related terms

`observation.md` · `verdict.md` (absence, existence, currency) · `capture.md` · `WORD_KEY.md`

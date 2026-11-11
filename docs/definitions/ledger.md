# Ledger
*claim-receipts canonical definition*
*Status: DRAFT v0.1 — not yet audited*
*Checked against `6dc1938` plus its uncommitted working-tree changes (2026-11-11). Line numbers are for that tree.*
*Related: `capture.md`, `receipt.md`.*

---

**In one sentence:** The ledger is one JSONL file per session, to which the plugin's hooks append a
record each time a tool call changed a file they were watching or ran a terminal command.

## Age 5

Someone sits next to you with a notebook while you build. When you add or take away a block, they
write it down, but only if they saw it happen. The notebook is the ledger.

## The definition

**Where it lives.** `<root>/sessions/<name>.jsonl`. `<root>` is the `RECEIPTS_ROOT` environment
variable, or `~/.hermes/plugin-data/receipts` when that is unset. `<name>` is the session id, else
the task id, else `unknown-YYYYMMDD`. Slashes become `_`; only letters, digits and `- _ . |` are kept;
the name is cut to 120 characters.

**How a write is recorded.** Two hooks work as a pair.

1. `pre_tool_call` runs before a tool call. If the tool is one of `write_file`, `patch`, `edit_file`,
   `create_file`, `append_file`, it takes the first of the arguments `path`, `file_path`, `target`,
   makes it absolute, and stores a snapshot of it: does it exist, its size, its modification time in
   nanoseconds. The snapshot is held in memory, keyed by task id, session id and call id.
2. `post_tool_call` runs after the call. It snapshots the same path again and compares. The path
   counts as changed when it was created, deleted, or its size or modification time differs. Only a
   changed path is written down, as a **mutation**: `{path, before, after}`.

If there was no "before" snapshot for the call, the "before" is written as `{"exists": null}`. Such a
mutation is recorded, but downstream it is never treated as a certified write (see `capture.md`).

**How a command is recorded.** For a tool named `terminal`, the hook records the `command` argument
(stripped, first 2,000 characters), and `command_cut: true` when the stripped command was longer than
that. If the host passed an absolute `cwd` or `workdir`, that folder is recorded too (first 1,000 characters, with
`cwd_cut: true` when it was longer). A command is never turned into a file change.

**What a record holds.** `ts`, `session_id`, `task_id`, `tool_call_id`, `tool`, `status` (as the host
gave it), `duration_ms`, `mutations`, `command`, `cwd`, `cwd_cut`, `command_cut`. A record is written only if it has at least one
mutation or a command.

**End of session.** `on_session_end` appends one marker record: `{event: "session_end", records,
files_changed}`.

**Reading it back.** `read_ledger` returns every record, oldest first, and skips lines it cannot parse.

## What it is not

- **Not a log of every tool call.** A call that changed nothing it was watching and ran no command
  leaves no row. A `read_file` or a `web_search` leaves no row.
- **Not a record of changes made by terminal commands.** `echo x > f.txt` changes `f.txt`, but the
  ledger records only the command string. It is not a mutation of `f.txt`.
- **Not a copy of tool output.** Output stays in Hermes's own store. It is read once, at session end
  (see `capture.md`).
- **Not tamper-evident.** The plugin only ever opens the file for appending, but nothing is hashed or
  signed. Anyone who can write the file can change it.
- **Not the receipt.** The receipt is built from the ledger and the transcript at session end
  (`receipt.md`).

## In the code

| What | Where |
|------|-------|
| Write tools and the path argument | `receipts/paths.py:WRITE_PATH_TOOLS` (L18), `writable_paths` (L63) |
| Snapshot and change test | `receipts/paths.py:stat_of` (L41), `changed` (L52) |
| Before-snapshot | `receipts/ledger.py:pre_tool_call` (L56) |
| After-snapshot, mutation, command, cwd, cut flag | `receipts/ledger.py:post_tool_call` (L72) |
| File location and name | `receipts/ledger.py:root` (L31), `session_file` (L39) |
| Append | `receipts/ledger.py:_append` (L47) |
| Read back | `receipts/ledger.py:read_ledger` (L127) |
| End marker | `receipts/ledger.py:on_session_end` (L178) |
| Hook registration, exception swallowing | `__init__.py:register` (L53), `_safe` (L21) |

## Limits

- **Only the first path argument is snapshotted.** A write tool that changes more than one file is
  recorded for one path at most.
- **Snapshots can be lost.** If more than 512 snapshots are pending, all of them are dropped
  (`_MAX_PENDING`). Those calls then have no "before" and their writes are not certified.
- **Fail-open, and silent.** Every hook swallows its own exceptions. A capture failure looks exactly
  like a quiet session. (Project README, section "Safety".)
- **It records what you work on.** File paths, sizes, modification times and full command strings.
  (Project README, section "Privacy — what is read and what is stored".)
- `KNOWN_LIMITS.md`, section "Earlier defects (R1–R8)", row **R1**: a missing pre-state used to be
  read as "absent"; that is the reason for `{"exists": null}`.

## Related terms

`capture.md` (the ledger is half of it) · `listing.md` (built from recorded commands) ·
`repair.md` (uses the order of records) · `receipt.md`

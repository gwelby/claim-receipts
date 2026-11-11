# claim-receipts

Evidence for agent sessions, checked against the filesystem.

**A prompt can tell an agent to claim less. A skill can describe how to check. Neither can do this.**
Hooks capture what the session actually did; an append-only ledger records it; a judge reconciles each
prose claim against that record and returns a verdict — backed, unbacked, unverifiable or contradicted.
That is a mechanism, not an instruction: you cannot write it into a system prompt, and no amount of
"please be honest" produces a per-claim verdict that an outside reader can re-run.

An agent says "done". This plugin records what the session's tools actually did — the file writes and
command invocations it could observe — and reconciles the claims it recognises in the session's prose
against that record. Claims are found by a fixed set of patterns (completion, existence, absence,
currency, coverage, hedges, success); a sentence those patterns do not catch is not judged.
It compares a claim with evidence. It does not prove the claim true, and it does not authenticate the
agent: agreement with a capture is not truth.

## Four verdicts per claim

| verdict | meaning |
|---|---|
| **backed** | an observed file change or command supports the claim |
| **unbacked** | the session claimed work that left no trace in the capture |
| **unverifiable** | the claim cannot be checked against a filesystem at all (an opinion, a judgement, a plan) |
| **contradicted** | the capture directly conflicts with the claim — e.g. the file exists and the session says it is missing |

`unverifiable` is first-class. Forcing it into "backed" would make the record lie in the flattering
direction, which is the failure the plugin exists to catch. `contradicted` is not a synonym for
`unbacked`: one means "no trace found", the other means "the trace says otherwise".

## The distinguishing rule

> A path **named** in a tool result is not evidence.
> A path whose `stat()` **differs across the call** is.

## What it does today

- `pre_tool_call` snapshots the paths a write is about to touch
- `post_tool_call` re-stats them and records only real changes (create, modify, delete)
- terminal calls are recorded as **command** evidence — the command string and how it ended — and are
  never inferred as file changes
- an append-only JSONL ledger per session under `~/.hermes/plugin-data/receipts/sessions/`
- claim extraction from the assistant's prose, and the four-verdict reconciliation
- an end-of-session receipt artifact

## What it does NOT establish — read this before trusting a verdict

Known, named limits from independent source audits. Where the plugin cannot support a verdict it
abstains (`unverifiable`) rather than guess in the flattering direction.

- **Capture is bounded by the hooks.** A change made outside an observed tool call, or by a command the
  hook did not see, is invisible. Absence of evidence here is not evidence of absence.
- **Only recognised claims are judged.** Claims are found by patterns; others are not judged at all.
- **A missing pre-state is not a creation.** Without a captured before-state, a create is not certified.
- **A listing proves absence only in a narrow form**: a successful, complete, un-cut `ls` or `find` of
  one absolute path, in an allowed form. Anything else (other flags, several paths, quoting it cannot
  read, a cut result) abstains.
- **A hedge needs its observation**: a successful read or listing naming the exact path. Hedging alone,
  or a command that merely names a similar file, earns nothing.
- **A repair must be the same check run again.** A failure followed by a *different* successful command
  abstains rather than counting as repaired.
- **"All" is not proved by one.** A coverage claim over a set needs the whole set judged; one passing
  member abstains.
- **The Day-3 ratio is a verdict share, not a false-positive rate.** It has no independent truth labels.
  It must not be quoted as precision.
- **No held-out validation.** The test cases are development diagnostics, not an accuracy estimate.

Full itemised list with locators: `KNOWN_LIMITS.md`.

## Standard

Verdict vocabulary follows **Noet Standards — Receipt v0.1**:

- Repo: `gwelby/noet` · **spec: Noet Standards (release pending)** — this link is deliberately
  not a URL until the release gate has passed and a tag exists. A dead link in a README about verification
  would be its own joke.

## Tell us we are wrong

The point of a receipt is to be checkable by someone who does not trust the checker.

> Found a verdict you think is wrong? Open an issue with the receipt attached.

We want the cases where it says **backed** and should not. Wrong verdicts become negative controls in
`tests/` — the suite grows from being contradicted, not from being believed.

## Install

Passes `hermes plugins validate` on Hermes Agent v0.23.0. Its hooks are tested against synthetic sessions
built the way Hermes stores them; it has not yet been run inside a live Hermes session by its authors.

```bash
hermes plugins install gwelby/claim-receipts --ref <the 40-character commit in the catalog entry>
hermes plugins enable claim-receipts       # hot-loads hooks; no restart needed
```

Then `/claim-receipts` in a session shows what it has proven so far. Disable any time with
`hermes plugins disable claim-receipts`. (The catalog key and the plugin are both `claim-receipts`:
another plugin already uses the name `receipts`.)

## Privacy — what is read and what is stored

Everything stays on your machine. No network calls, no telemetry, no credentials.

**It reads Hermes's own session database**, `~/.hermes/state.db`, at session end, to bind each
command's output to the command that produced it. It opens the file read-only (SQLite `mode=ro`),
reads only the current session's newest messages (at most 600, and at most 20,000 characters of each
tool result), and never writes to it. `RECEIPTS_TRANSCRIPT_DB` points it at another file. That is a
read outside the plugin's own data, so it is stated here.

The ledger records local file paths, sizes and mtimes — **which means it records the names of the files
you work on** — and it records **the command strings of terminal calls**, which can themselves contain
paths, arguments and anything you typed on a command line. That is a wider disclosure than "file names".
Point `RECEIPTS_ROOT` elsewhere, or delete `~/.hermes/plugin-data/receipts/`.

## Safety

Every hook swallows its own exceptions. A ledger that breaks a session would be a worse bug than the one
it prevents, so the plugin fails open — and silently. That is a deliberate trade, and it means a capture
failure looks exactly like a quiet session.

## Tests

```bash
make test            # ledger, transcript, paths, receipts
make acceptance      # the claim-vs-evidence scorer; exits non-zero unless the agreed bar is met
```

The negatives are the point: a file named but not changed must produce no evidence, a read-only tool must
produce none, a hook handed garbage must not raise, and the acceptance gate must fail on a mutant that
gets every other case right.

## License

MIT.

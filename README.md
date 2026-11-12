# claim-receipts

**New here? Start with [docs/UNDERSTAND.md](docs/UNDERSTAND.md)**: the same idea told four ways, from age 5 to
master, with pictures. Every term is defined in [docs/definitions/](docs/definitions/README.md).

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
| **backed** | the record supports the claim: a recorded write to the file, or a successful observation, listing or measurement of it |
| **unbacked** | the session claimed work that left no trace in the capture |
| **unverifiable** | the record cannot decide this claim, so the plugin abstains on purpose |
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
- an append-only JSONL ledger per session under `<Hermes home>/plugin-data/receipts/sessions/`, where
  `<Hermes home>` is the active profile's home (`hermes_constants.get_hermes_home()`, usually `~/.hermes`), resolved on every call, so each profile keeps its own
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
- **Hedging alone earns nothing**, nor does a command that merely names a similar file.
- **A repair must be the same check run again, in the same place.** A failure counts only when it names
  the exact path. It is repaired by a recorded write to that exact file, or by the complete, identical
  command run again in the same recorded folder. Hermes does not pass the folder to the hook, so on a live
  session only the write clears it. A *different* successful command, or a failure on a look-alike path,
  abstains.
- **How a claim finds its file.** An absolute path is used as written. A bare file name (`app.py`) is
  matched only to a file of exactly that name that the session wrote (with its before-state captured). A
  relative path with a folder (`docs/app.py`) and relative paths inside commands are not matched; such a
  claim is left unjudged, and a hedge about such a path cannot be backed (`unbacked`).
- **A hedge needs its observation.** A hedge about a named file needs a successful read or listing of
  that exact path. A hedge that names no file is backed only by an observe tool such as `web_search`,
  never by an arbitrary command.
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

Then `/claim-receipts` in a session lists the evidence recorded so far (verdicts are written to the receipt at
session end). On a messaging gateway it shows only the calling chat's own session; in the local CLI, with no
session known, it shows the newest ledger on the machine and says so. Disable any time with
`hermes plugins disable claim-receipts`. (The catalog key and the plugin are both `claim-receipts`:
another plugin already uses the name `receipts`.)

## Privacy — what is read and what is stored

Everything stays on your machine. No network calls, no telemetry, no credentials.

**It reads Hermes's own session database**, `<Hermes home>/state.db` of the active profile, at session end, to bind each
command's output to the command that produced it. It opens the file read-only (SQLite `mode=ro`),
reads only the current session's newest messages (at most 600 rows in each of its three queries; each
tool result capped at 20,000 characters; the agent's own prose is read without a per-message cap), and
never writes to it. `RECEIPTS_TRANSCRIPT_DB` points it at another file. That is a
read outside the plugin's own data, so it is stated here.

The receipt stores **the sentences of the agent's own prose that it judged** (up to 300 characters each).
The ledger records local file paths, sizes and mtimes — **which means it records the names of the files
you work on** — and it records **the command strings of terminal calls**, which can themselves contain
paths, arguments and anything you typed on a command line. That is a wider disclosure than "file names".
Point `RECEIPTS_ROOT` elsewhere, or delete `<Hermes home>/plugin-data/receipts/`.

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

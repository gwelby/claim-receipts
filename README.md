# receipts

Evidence for agent sessions, checked against the filesystem.

An agent says "done". This plugin records what the session's tools actually did — the file writes and
command invocations it could observe — and reconciles the session's prose claims against that record.
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

These are known, named limits. An independent source audit found them; most are open.

- **Capture is bounded by the hooks.** A change made outside an observed tool call, or by a command the
  hook did not see, is invisible. Absence of evidence here is not evidence of absence.
- **A missing pre-state is not a creation.** If the snapshot was unavailable, the plugin cannot certify
  a create — a repair is in progress.
- **A listing is not an absence proof.** Recording that a command *ran* does not yet establish what it
  *returned*, or that its scope and depth covered the target. (Open.)
- **Hedging alone does not earn `backed`.** A claim that only reports the limits of its own search needs
  its supporting observation. (Open.)
- **The Day-3 ratio is a verdict share, not a false-positive rate.** It has no independent truth labels.
  It must not be quoted as precision. (Open.)
- **The gate package builder is not yet safe to point at arbitrary paths.** (Open.)

Full itemised list with locators: `KNOWN_LIMITS.md`.

## Standard

Verdict vocabulary follows **Noet Standards — Receipt v0.1**:

- Repo: `gwelby/noet-standards` · **spec: Noet Standards (release pending)** — this link is deliberately
  not a URL until the release gate has passed and a tag exists. A dead link in a README about verification
  would be its own joke.

## Tell us we are wrong

The point of a receipt is to be checkable by someone who does not trust the checker.

> Found a verdict you think is wrong? Open an issue with the receipt attached.

We want the cases where it says **backed** and should not. Wrong verdicts become negative controls in
`tests/` — the suite grows from being contradicted, not from being believed.

## Install

```bash
cp -r hermes-plugin-receipts ~/.hermes/plugins/receipts
hermes plugins enable receipts       # hot-loads hooks; no restart needed
```

Disable any time with `hermes plugins disable receipts`.

## Privacy — what is stored

Everything stays on your machine. No network calls, no telemetry, no credentials.

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

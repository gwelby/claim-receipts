# receipts

Proof of work for agent sessions.

An agent says "done". This plugin checks. It records every file a session **actually changed** and
every command it **actually ran**, then reconciles the session's claims against that evidence.

Three verdicts per claim, and the third one is not a failure:

| verdict | meaning |
|---|---|
| **backed** | a file this session changed, or a command it ran, supports the claim |
| **unbacked** | the session claimed work that left no trace on disk |
| **unverifiable** | the claim cannot be checked from a filesystem at all (an opinion, a judgement, a plan) |

`unverifiable` is first-class. Forcing it into "backed" would make the ledger lie in the flattering
direction, which is the exact failure it exists to catch.

## Why it exists

Agents report state from memory and prose. The report is cheap; the state is not. A session can claim
a build is current when two newer builds exist, or that a file is missing when it is one directory
up — and nothing in the transcript catches either.

The distinguishing rule is one line, and it is the whole plugin:

> A path **named** in a tool result is not evidence.
> A path whose `stat()` **differs across the call** is.

## What it does today

Day 1 of a seven-day build. Shipped and verified:

- `pre_tool_call` snapshots the paths a write is about to touch
- `post_tool_call` re-stats them and records only real changes (create, modify, delete)
- terminal calls are recorded as **command** evidence — what ran and how it ended — never inferred
  as file changes
- one append-only JSONL ledger per session under `~/.hermes/plugin-data/receipts/sessions/`
- `/receipts` reports the evidence

Not built yet: claim extraction and the three-verdict reconciliation (Day 2), the end-of-session
receipt artifact (Day 3).

This README says which day a feature is on because the plugin's subject is unverified claims.

## Install

```bash
cp -r hermes-plugin-receipts ~/.hermes/plugins/receipts
hermes plugins enable receipts       # hot-loads hooks; no restart needed
```

Disable at any time with `hermes plugins disable receipts`.

## Privacy

Everything stays on your machine. No network calls, no telemetry, no credentials. The ledger records
local file paths, sizes and mtimes — which means **it records the names of the files you work on**.
Point `RECEIPTS_ROOT` elsewhere, or delete `~/.hermes/plugin-data/receipts/`, if that matters to you.

## Safety

Every hook swallows its own exceptions. A ledger that breaks a session would be a worse bug than the
one it prevents, so the plugin fails open, always, and silently.

## Tests

```bash
python3 tests/test_ledger.py
```

The negatives are the point: a file that is named but not changed must produce no evidence, a
read-only tool must produce none, and a hook handed garbage must not raise.

## License

MIT.

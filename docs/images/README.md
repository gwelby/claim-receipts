# Pictures

Three hand-written SVG diagrams of what the plugin does. Each one is drawn from the code, not from the
prose about it. Each has its own light card behind it, so it reads the same in GitHub's light and dark
themes. They have no fixed width, so they scale to the page.

| Image | What it shows | Code it reflects |
|---|---|---|
| [`how-it-works.svg`](how-it-works.svg) | The pipeline. On each tool call, `pre_tool_call` stats the paths a write tool is about to touch and `post_tool_call` stats them again. Only a real change (create, modify, delete) is recorded. A terminal call is recorded as its command and how it ended, never as a file change. Records go to an append-only JSONL ledger. At session end the transcript is read read-only, the ledger and tool outputs become evidence, each recognised claim is judged, and the receipt is written. | `__init__.py` (hooks, session end), `receipts/paths.py` (which tools count as writes, `changed`), `receipts/ledger.py`, `receipts/transcript.py`, `receipts/evidence.py`, `receipts/judge.py`, `receipts/receipt.py`; `/claim-receipts` is `receipts/claims.py` |
| [`four-verdicts.svg`](four-verdicts.svg) | The four verdicts, each with one plain line, an example claim and the reason code it gets: **backed** (`written-this-session`), **unbacked** (`artifact-missing`), **unverifiable** (`search-scope`), **contradicted** (`artifact-present`). It marks `unverifiable` as honest abstention, not failure, and notes that claims the patterns miss are counted as unjudged, not scored. | `receipts/judge.py` (`extract_claims`, `judgeable`, `judge`, `_judge_kind`), `receipts/receipt.py` (counts, `unjudged_sample`) |
| [`when-it-abstains.svg`](when-it-abstains.svg) | How an absence claim ("X does not exist") is decided. A write or delete by the session itself decides first. Otherwise the listing must pass four checks: it ran and succeeded; it is one absolute path in an allowed form that reaches the file; its output was captured whole and uncut; and nothing after it could have changed the folder. Every "no" ends in abstention. When all four pass, a listed name gives **contradicted** (`listed-present`) and an unlisted one gives **backed** (`absence-established`). | `receipts/judge.py` (absence branch of `_judge_kind`), `receipts/evidence.py` (`_listing_of`, `_status_bound`, `Listing.covers`, `searched_for`, `_bound_output`, `_parse_entries`, `_touches_in`, `_through_symlink`), `receipts/transcript.py` (20,000-character cut, truncation marks) |

The four example claims in `four-verdicts.svg` and both outcomes of the last step in `when-it-abstains.svg` were run through
`judge.judge` on small fixtures (`Evidence.from_fixture`). Each one returned the verdict and reason code shown in the picture.

The diagrams simplify. The full rules, with their known gaps, are in [`../../KNOWN_LIMITS.md`](../../KNOWN_LIMITS.md).
If the code changes, these pictures need to change with it.

To embed one in a Markdown page:

```markdown
![How claim-receipts works](docs/images/how-it-works.svg)
```

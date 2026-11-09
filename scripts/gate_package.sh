#!/usr/bin/env bash
# Build the gate package: everything Codex needs to review this tree before anything leaves the machine.
#
# Design rules:
#   * every claim in the package is produced by a command whose output is captured, not written by hand
#   * the tree is frozen by commit, and the bundle is a real clone target, so "this is the tree I
#     reviewed" is verifiable rather than asserted
#   * the Day-3 counts carry their DEFINITION, because a share without a denominator is
#     an unfalsifiable number — and this one is NOT a false-positive rate: there are no truth labels,
#     a number that can mean anything
set -uo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${1:-$REPO/GATE_PACKAGE}"
PY=/usr/bin/python3.12

cd "$REPO" || exit 1

# R8: the rm -rf below destroys whatever OUT resolves to — and DID: on 2026-11-07 a
# run with OUT=/home/greg/work deleted the entire working tree (repo included) because
# the dirty-check sat AFTER the rm. Every refusal below happens BEFORE any write or
# deletion, and the incident stays named here because a guard without the scar invites
# someone to remove it.
CANON_OUT=$(realpath -m "$OUT" 2>/dev/null || echo "")
CANON_REPO=$(realpath -m "$REPO")
case "$CANON_OUT" in
  ""|"/")
    echo "REFUSING: output path resolves to an unsafe location: '$OUT'" >&2; exit 2;;
  "$CANON_REPO/GATE_PACKAGE")
    ;;   # the sanctioned package dir inside the tree (gitignored since 803a04e)
  "$CANON_REPO"|"$CANON_REPO/"*)
    echo "REFUSING: output path is the source tree or inside it: $CANON_OUT — rm -rf would destroy the input." >&2; exit 2;;
esac
# Ancestor check: if REPO resolves INSIDE OUT, deleting OUT deletes the tree.
case "$CANON_REPO" in
  "$CANON_OUT"|"$CANON_OUT/"*)
    echo "REFUSING: output path is an ancestor of the source tree: $CANON_OUT" >&2; exit 2;;
esac
# Pre-existing non-empty dir that is not the sanctioned location: never rm unknown data.
if [ -d "$CANON_OUT" ] && [ -n "$(ls -A "$CANON_OUT" 2>/dev/null)" ]    && [ "$CANON_OUT" != "$CANON_REPO/GATE_PACKAGE" ]; then
  echo "REFUSING: output path exists and is not empty: $CANON_OUT — will not rm an unknown directory." >&2; exit 2
fi
# A regular file at OUT is refused too — rm -rf would otherwise delete an unknown file.
if [ -e "$CANON_OUT" ] && [ ! -d "$CANON_OUT" ]; then
  echo "REFUSING: output path exists and is not a directory: $CANON_OUT" >&2; exit 2
fi

# ---- 0. the frozen tree — BEFORE any deletion ----
# Round-3: this check used to sit after `rm -rf "$OUT"`, so a refused run still
# destroyed a pre-existing output. Every refusal now precedes every write.
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "REFUSING: working tree is dirty. A package of an uncommitted tree cannot be reproduced." >&2
  git status --porcelain | head -20 >&2
  exit 2
fi
rm -rf "$OUT"; mkdir -p "$OUT"

COMMIT=$(git rev-parse HEAD)
git log -1 --format='commit %H%nAuthor %an <%ae>%nDate   %aI%n%n%s' > "$OUT/HEAD.txt"
git bundle create "$OUT/history.bundle" --all >/dev/null 2>&1
git log --stat --format='%n=== %h %aI %s' > "$OUT/history.txt"
# every tracked file, hashed from an IMMUTABLE export of the commit — not the live
# tree — so the sidecar cannot absorb drift introduced after the dirty check's instant
EXPORT_TMP="$(mktemp -d)"; trap 'rm -rf "$EXPORT_TMP"' EXIT
git archive "$COMMIT" | tar -x -C "$EXPORT_TMP"
git ls-files | sort | (cd "$EXPORT_TMP" && xargs -d '\n' sha256sum) > "$OUT/tree.sha256" 2>/dev/null
echo "$COMMIT" > "$OUT/COMMIT"

# ---- 2. reproduction: run the checks, keep the RAW output, and CAPTURE the exits
# — round-3: exit codes used to be logged then discarded; they now gate final status
TEST_EXIT=0; ACC_EXIT=0; VAL_EXIT=0
{
  echo "### make test"; make test 2>&1; TEST_EXIT=$?; echo "exit=$TEST_EXIT"
  echo; echo "### make acceptance"; make acceptance 2>&1; ACC_EXIT=$?; echo "exit=$ACC_EXIT"
  echo; echo "### hermes plugins validate ."; hermes plugins validate . 2>&1; VAL_EXIT=$?; echo "exit=$VAL_EXIT"
} > "$OUT/reproduction.log" 2>&1

# ---- 3. the Day-3 measurement, with its definition written down ----
SESSION="${RECEIPTS_SESSION:-}"
$PY - "$OUT" "$SESSION" <<'PY'
import json, os, sys, glob
out, session = sys.argv[1], sys.argv[2]
src = None
if session:
    src = os.path.expanduser(f"~/.hermes/plugin-data/receipts/receipts/{session}.json")
if not src or not os.path.isfile(src):
    cands = sorted(glob.glob(os.path.expanduser("~/.hermes/plugin-data/receipts/receipts/*.json")),
                   key=os.path.getmtime, reverse=True)
    src = cands[0] if cands else None
if not src:
    print("no receipt found — Day-3 counts unavailable", file=sys.stderr)
    sys.exit(0)
d = json.load(open(src))
c = d["claims"]
checkable = c["backed"] + c["unbacked"] + c["contradicted"]
payload = {
    "source_receipt": os.path.basename(src),
    "session": d["session"],
    "generated": d["generated"],
    "definition": {
        "claim": "a statement in the assistant's own text that the extractor can type and locate",
        "judged": "claims whose subject resolves to something in this session's evidence",
        "unjudged": "claims naming nothing locatable (relative path, paraphrase, another machine) — counted, never scored",
        "BACKED": "evidence supports it",
        "CONTRADICTED": "evidence points the other way",
        "UNBACKED": "no evidence either way",
        "UNVERIFIABLE": "evidence cannot decide — reported separately, never folded into BACKED",
        "unbacked_claim_share_formula": "(CONTRADICTED + UNBACKED) / (BACKED + UNBACKED + CONTRADICTED)",
        "why_this_denominator": "UNVERIFIABLE is the honest bucket, not a failure; including it would punish a tool for refusing to guess",
        "not_a_false_positive_rate": "there are no truth labels here — nothing independently establishes that an UNBACKED or CONTRADICTED verdict was WRONG. This number is the share of checkable claims the tool declined to back; a justified warning and a false alarm are indistinguishable in it. Do not quote it as precision.",
    },
    "counts": c,
    "checkable": checkable,
    "unbacked_claim_share": round(100 * (c["unbacked"] + c["contradicted"]) / checkable, 1) if checkable else None,
    "gate": {"unbacked_share_threshold": 20, "pivot_share_threshold": 30, "pivot_fired": bool(checkable and
             (c["unbacked"] + c["contradicted"]) / checkable > 0.30)},
    "known_limits": [
        f"only {checkable} claims were checkable in this one session; a small denominator is not a property",
        "claim detection is regex-based: paraphrases are missed and appear as 'no claim detected'",
        "relative paths are unjudgeable by design (they belong to a CWD or another host)",
        "the sealed 8/8 acceptance set was written by the same author and is a DEVELOPMENT score",
    ],
}
json.dump(payload, open(os.path.join(out, "day3_counts.json"), "w"), indent=2)
print(f"day3 counts from {os.path.basename(src)}: {checkable} checkable, "
      f"unbacked-claim share {payload['unbacked_claim_share']}% "
      f"(a verdict share with no truth labels — NOT a false-positive rate)")
PY
DAY3_EXIT=$?

# ---- 4. the outward commands, for Greg to approve one at a time ----
cat > "$OUT/outward_commands.md" <<EOF
# Outward steps — each needs Greg's explicit yes, shown before it runs

Nothing below has been run. The repository does not exist; there are no remotes.

## 1. Create the empty public repo
    gh repo create gwelby/hermes-plugin-receipts --public \\
        --description "Receipts — proof of work for AI agent sessions"

## 2. Push this exact commit — the reviewed tree, pinned by SHA not branch name
    git remote add origin git@github.com:gwelby/hermes-plugin-receipts.git
    git push -u origin $COMMIT:refs/heads/master
    # verify (scoped to the one ref; must print exactly $COMMIT):
    git ls-remote origin refs/heads/master | grep -F "$COMMIT"

## 3. Post the entry (after the video exists)
    # attach: demo.mp4 (<= 90 s), repo URL, one paragraph
    # tag @NousResearch, post the link in their Discord

## Preconditions, per the publish gate
- [ ] Codex reviews this package and PASSES (not self-check)
- [ ] held-out acceptance set scored (not the author's own fixtures)
- [ ] disclosure review: no internal paths, seat names, register ids, hostnames, IPs, keys
EOF

# ---- 5. the manifest ----
{
  echo "# Gate package — receipts plugin"
  echo
  echo "Commit: \`$COMMIT\`"
  echo "Built:  $(date -Iseconds)"
  echo "Files:  $(git ls-files | wc -l) tracked"
  echo
  echo "| file | what it proves |"
  echo "|---|---|"
  echo "| COMMIT | the exact commit this package describes |"
  echo "| HEAD.txt | author, date and subject of that commit |"
  echo "| history.txt | full history with per-file stats — what to read for disclosure |"
  echo "| history.bundle | \`git clone history.bundle\` reproduces the tree, so the reviewer's copy is provably ours |"
  echo "| tree.sha256 | every tracked file hashed; \`sha256sum -c\` on their copy must pass |"
  echo "| reproduction.log | raw output + exit codes of the three checks |"
  echo "| day3_counts.json | the unbacked-claim share **with its definition**, explicitly NOT a false-positive rate, and its known limits |"
  echo "| outward_commands.md | the exact commands, none run |"
  echo
  echo "## Verify this package"
  echo '```'
  echo "git clone history.bundle verify/"
  echo "cd verify && git log --oneline | head -1     # must equal COMMIT"
  echo "sha256sum -c ../tree.sha256                   # must be all OK"
  echo '```'
} > "$OUT/MANIFEST.md"

# ---- 6. final status: required artifacts + verifiable export + required-check
# success. Round-3: the captured exit codes now gate — a failed make test,
# make acceptance, validator run, or Day-3 stage refuses the package instead of
# ending exit 0 with artifacts present. ----
MISSING=""
for f in COMMIT HEAD.txt history.txt history.bundle tree.sha256 reproduction.log MANIFEST.md outward_commands.md day3_counts.json; do
  [ -s "$OUT/$f" ] || MISSING="$MISSING $f"
done
if ! git bundle verify "$OUT/history.bundle" >/dev/null 2>&1; then
  MISSING="$MISSING history.bundle(unverifiable)"
fi
FAILED=""
[ "${TEST_EXIT:-1}" -eq 0 ] || FAILED="$FAILED make-test(${TEST_EXIT:-?})"
[ "${ACC_EXIT:-1}" -eq 0 ] || FAILED="$FAILED make-acceptance(${ACC_EXIT:-?})"
[ "${VAL_EXIT:-1}" -eq 0 ] || FAILED="$FAILED validator(${VAL_EXIT:-?})"
[ "${DAY3_EXIT:-1}" -eq 0 ] || FAILED="$FAILED day3(${DAY3_EXIT:-?})"
if [ -n "$MISSING" ] || [ -n "$FAILED" ]; then
  echo "REFUSING: package failed — missing/unverifiable:$MISSING failed-checks:$FAILED" >&2
  exit 3
fi

echo
echo "gate package: $OUT"
ls -la "$OUT" | tail -n +2 | awk '{printf "  %-24s %8s\n", $9, $5}'

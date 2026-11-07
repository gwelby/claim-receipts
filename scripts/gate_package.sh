#!/usr/bin/env bash
# Build the gate package: everything Codex needs to review this tree before anything leaves the machine.
#
# Design rules:
#   * every claim in the package is produced by a command whose output is captured, not written by hand
#   * the tree is frozen by commit, and the bundle is a real clone target, so "this is the tree I
#     reviewed" is verifiable rather than asserted
#   * the Day-3 counts carry their DEFINITION, because a false-positive rate without a denominator is
#     a number that can mean anything
set -uo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${1:-$REPO/GATE_PACKAGE}"
PY=/usr/bin/python3.12

cd "$REPO" || exit 1

# R8: the rm -rf below destroys whatever OUT resolves to. Guard it before touching
# anything — a caller passing the repo, an ancestor, or root must be refused.
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
rm -rf "$OUT"; mkdir -p "$OUT"

# ---- 1. the frozen tree ----
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "REFUSING: working tree is dirty. A package of an uncommitted tree cannot be reproduced." >&2
  git status --porcelain | head -20 >&2
  exit 2
fi

COMMIT=$(git rev-parse HEAD)
git log -1 --format='commit %H%nAuthor %an <%ae>%nDate   %aI%n%n%s' > "$OUT/HEAD.txt"
git bundle create "$OUT/history.bundle" --all >/dev/null 2>&1
git log --stat --format='%n=== %h %aI %s' > "$OUT/history.txt"
# every tracked file, hashed, sorted — so a reviewer can diff their copy against ours
git ls-files -z | sort -z | xargs -0 sha256sum > "$OUT/tree.sha256" 2>/dev/null
echo "$COMMIT" > "$OUT/COMMIT"

# ---- 2. reproduction: run the checks and keep the RAW output ----
{
  echo "### make test"; make test 2>&1; echo "exit=$?"
  echo; echo "### make acceptance"; make acceptance 2>&1; echo "exit=$?"
  echo; echo "### hermes plugins validate ."; hermes plugins validate . 2>&1 | tail -5; echo "exit=$?"
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
        "FP_rate": "(CONTRADICTED + UNBACKED) / (BACKED + UNBACKED + CONTRADICTED)",
        "why_this_denominator": "UNVERIFIABLE is the honest bucket, not a failure; including it would punish a tool for refusing to guess",
    },
    "counts": c,
    "checkable": checkable,
    "fp_rate": round(100 * (c["unbacked"] + c["contradicted"]) / checkable, 1) if checkable else None,
    "gate": {"fp_threshold": 20, "pivot_threshold": 30, "pivot_fired": bool(checkable and
             (c["unbacked"] + c["contradicted"]) / checkable > 0.30)},
    "known_limits": [
        f"only {checkable} claims were checkable in this one session; a small denominator is not a property",
        "claim detection is regex-based: paraphrases are missed and appear as 'no claim detected'",
        "relative paths are unjudgeable by design (they belong to a CWD or another host)",
        "the sealed 8/8 acceptance set was written by the same author and is a DEVELOPMENT score",
    ],
}
json.dump(payload, open(os.path.join(out, "day3_counts.json"), "w"), indent=2)
print(f"day3 counts from {os.path.basename(src)}: {checkable} checkable, fp {payload['fp_rate']}%")
PY

# ---- 4. the outward commands, for Greg to approve one at a time ----
cat > "$OUT/outward_commands.md" <<EOF
# Outward steps — each needs Greg's explicit yes, shown before it runs

Nothing below has been run. The repository does not exist; there are no remotes.

## 1. Create the empty public repo
    gh repo create gwelby/hermes-plugin-receipts --public \\
        --description "Receipts — proof of work for AI agent sessions"

## 2. Push this exact commit
    git remote add origin git@github.com:gwelby/hermes-plugin-receipts.git
    git push -u origin master
    # pushed commit: $COMMIT
    # verify: git ls-remote origin | grep $COMMIT

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
  echo "| day3_counts.json | the FP measurement **with its definition** and its known limits |"
  echo "| outward_commands.md | the exact commands, none run |"
  echo
  echo "## Verify this package"
  echo '```'
  echo "git clone history.bundle verify/"
  echo "cd verify && git log --oneline | head -1     # must equal COMMIT"
  echo "sha256sum -c ../tree.sha256                   # must be all OK"
  echo '```'
} > "$OUT/MANIFEST.md"

echo
echo "gate package: $OUT"
ls -la "$OUT" | tail -n +2 | awk '{printf "  %-24s %8s\n", $9, $5}'

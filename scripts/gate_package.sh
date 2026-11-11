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
# OUTPUT POLICY (C5 return, 2026-11-10) — the broad rule, stated once: the ONLY pre-existing output
# this script will ever remove is its own sanctioned package dir, $REPO/GATE_PACKAGE. Any other OUT
# that already exists in ANY form — empty directory, non-empty directory, regular file, symlink
# (dangling or not) — is refused. Pass a path that does not exist yet.
# Chosen over "allow safe empty directories" because it needs NO directory enumeration: fdb8f87 ran
# `ls -A ... 2>/dev/null` and treated empty TEXT as empty, so an unreadable listing read as "empty".
# Here nothing is listed, so an enumeration error can never be counted as emptiness; the final
# `mkdir` (no -p) is also atomic, so a path created after this test still fails instead of being reused.
if [ "$CANON_OUT" != "$CANON_REPO/GATE_PACKAGE" ]; then
  if [ -e "$OUT" ] || [ -L "$OUT" ] || [ -e "$CANON_OUT" ] || [ -L "$CANON_OUT" ]; then
    echo "REFUSING: output path already exists: $CANON_OUT — only $CANON_REPO/GATE_PACKAGE is ever replaced; pass a new path." >&2; exit 2
  fi
fi
# A regular file at the sanctioned location is refused too — rm -rf would otherwise delete an unknown file.
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
# Only the sanctioned dir is ever removed (policy above); every other OUT is known not to exist.
if [ "$CANON_OUT" = "$CANON_REPO/GATE_PACKAGE" ]; then rm -rf -- "$CANON_OUT"; fi
if ! mkdir -p -- "$(dirname -- "$CANON_OUT")" || ! mkdir -- "$CANON_OUT"; then
  echo "REFUSING: could not create a fresh output directory: $CANON_OUT" >&2; exit 2
fi
OUT="$CANON_OUT"   # absolute from here on; checks below run in another cwd

# Any failure in producing the bound export or its hashes ABORTS (exit 3). fdb8f87 ignored
# these statuses, so a failed or partial archive still ended 0 with a partial tree.sha256.
abort_pkg() { echo "REFUSING: package failed — $*" >&2; exit 3; }

COMMIT=$(git rev-parse --verify 'HEAD^{commit}') || abort_pkg "cannot resolve HEAD to a commit"
[ -n "$COMMIT" ] || abort_pkg "empty commit id"
git log -1 --format='commit %H%nAuthor %an <%ae>%nDate   %aI%n%n%s' "$COMMIT" > "$OUT/HEAD.txt"
git bundle create "$OUT/history.bundle" --all >/dev/null 2>&1
git log --stat --format='%n=== %h %aI %s' "$COMMIT" > "$OUT/history.txt"

# ---- 1. C5: ONE immutable export of COMMIT is the thing hashed AND the thing checked ----
# * file list: `git ls-tree` of the pinned COMMIT — never the live index (`git ls-files` let an
#   index omission leave a committed file unhashed)
# * bytes: every exported file must hash to its blob id IN that commit (hash-object --no-filters),
#   and the export must hold exactly those files — nothing missing, nothing extra
# * statuses: archive, tar, ls-tree, hash-object and sha256sum are each gated; the sidecar must
#   have exactly one line per committed file
# * checks (section 2) run INSIDE this export, not in the live cwd
WORK="$(mktemp -d)" || abort_pkg "mktemp failed"
{ [ -n "$WORK" ] && [ -d "$WORK" ]; } || abort_pkg "mktemp gave no directory"
trap 'rm -rf -- "$WORK"' EXIT
EXPORT="$WORK/tree"
mkdir -- "$EXPORT" || abort_pkg "cannot create export dir"
git archive "$COMMIT" | tar -x -C "$EXPORT"
ST=("${PIPESTATUS[@]}")
[ "${ST[0]}" -eq 0 ] && [ "${ST[1]}" -eq 0 ] || abort_pkg "export of $COMMIT failed (git archive=${ST[0]}, tar=${ST[1]})"
git ls-tree -r -z --full-tree "$COMMIT" > "$WORK/ls-tree.z" || abort_pkg "git ls-tree $COMMIT failed"
PATHS=(); BLOBS=()
while IFS= read -r -d '' entry; do
  meta=${entry%%$'\t'*}; path=${entry#*$'\t'}
  read -r mode otype oid <<<"$meta"
  case "$mode $otype" in
    "100644 blob"|"100755 blob") ;;
    *) abort_pkg "unsupported tree entry '$mode $otype' at '$path' — only regular files can be exported, blob-verified and hashed";;
  esac
  case "$path" in *$'\n'*|*\\*) abort_pkg "unsupported path name (newline/backslash) in $COMMIT";; esac
  PATHS+=("$path"); BLOBS+=("$oid")
done < "$WORK/ls-tree.z"
N=${#PATHS[@]}
[ "$N" -gt 0 ] || abort_pkg "commit $COMMIT lists no files"
for p in "${PATHS[@]}"; do
  { [ -f "$EXPORT/$p" ] && [ ! -L "$EXPORT/$p" ]; } || abort_pkg "export is missing committed file: $p"
done
find "$EXPORT" -mindepth 1 ! -type d -printf . > "$WORK/found" || abort_pkg "cannot enumerate the export"
NFOUND=$(wc -c < "$WORK/found")
[ "$NFOUND" -eq "$N" ] || abort_pkg "export holds $NFOUND non-directory entries; commit lists $N"
for p in "${PATHS[@]}"; do printf '%s\n' "$EXPORT/$p"; done > "$WORK/export_paths"
git hash-object --no-filters --stdin-paths < "$WORK/export_paths" > "$WORK/oids" || abort_pkg "git hash-object over the export failed"
mapfile -t GOT < "$WORK/oids"
[ "${#GOT[@]}" -eq "$N" ] || abort_pkg "hash-object returned ${#GOT[@]} ids for $N files"
for i in "${!PATHS[@]}"; do
  [ "${GOT[$i]}" = "${BLOBS[$i]}" ] || abort_pkg "exported bytes of ${PATHS[$i]} are not blob ${BLOBS[$i]} of $COMMIT"
done
( cd "$EXPORT" && sha256sum -- "${PATHS[@]}" ) > "$OUT/tree.sha256" || abort_pkg "sha256sum over the export failed"
NSUM=$(wc -l < "$OUT/tree.sha256")
[ "$NSUM" -eq "$N" ] || abort_pkg "tree.sha256 has $NSUM lines for $N committed files"
echo "$COMMIT" > "$OUT/COMMIT"

# ---- 2. reproduction: run the checks IN THE EXPORT, keep the RAW output, and CAPTURE the exits
# — round-3: exit codes used to be logged then discarded; they now gate final status
# — C5: fdb8f87 ran these in the live cwd while tree.sha256 described the export, so the checked
#   bytes and the hashed bytes could differ. Now both are the same export of $COMMIT.
TEST_EXIT=0; ACC_EXIT=0; VAL_EXIT=0
{
  echo "# checks run in an export of $COMMIT (not the live tree)"
  echo "### make test"; ( cd "$EXPORT" && make test ) 2>&1; TEST_EXIT=$?; echo "exit=$TEST_EXIT"
  echo; echo "### make acceptance"; ( cd "$EXPORT" && make acceptance ) 2>&1; ACC_EXIT=$?; echo "exit=$ACC_EXIT"
  echo; echo "### hermes plugins validate ."; ( cd "$EXPORT" && hermes plugins validate . ) 2>&1; VAL_EXIT=$?; echo "exit=$VAL_EXIT"
} > "$OUT/reproduction.log" 2>&1
# the checks must not have changed the bytes they checked (so checked == hashed at the end too)
( cd "$EXPORT" && sha256sum -c --quiet --strict -- "$OUT/tree.sha256" ) >"$WORK/recheck.log" 2>&1
RECHECK_EXIT=$?

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
  echo "Files:  $N in $COMMIT (from git ls-tree of the commit; each exported, blob-verified, hashed and checked)"
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
# the bundle's HEAD must be the packaged commit (it is still --all: selecting outgoing refs is a
# separate disclosure decision, not made here)
BUNDLE_HEAD=$(git bundle list-heads "$OUT/history.bundle" 2>/dev/null | awk '$2=="HEAD"{print $1; exit}')
[ "$BUNDLE_HEAD" = "$COMMIT" ] || MISSING="$MISSING history.bundle(HEAD:${BUNDLE_HEAD:-none}!=COMMIT)"
FAILED=""
[ "$RECHECK_EXIT" -eq 0 ] || FAILED="$FAILED export-changed-by-checks($RECHECK_EXIT)"
# C5 end guard: the clean-tree precondition must still hold when the package is finished. The checks
# no longer read live bytes, but a live tree/index/HEAD that moved during the build means the
# operator's tree is no longer the one packaged — refuse rather than ship an ambiguous package.
END_HEAD=$(git rev-parse --verify 'HEAD^{commit}' 2>/dev/null)
[ "$END_HEAD" = "$COMMIT" ] || FAILED="$FAILED head-moved(${END_HEAD:-unresolvable})"
if ! git diff --quiet || ! git diff --cached --quiet; then FAILED="$FAILED live-tree-changed-during-build"; fi
if git ls-files -z > "$WORK/index.z"; then
  printf '%s\0' "${PATHS[@]}" | LC_ALL=C sort -z > "$WORK/commit_names.z"
  LC_ALL=C sort -z "$WORK/index.z" | cmp -s - "$WORK/commit_names.z" || FAILED="$FAILED index-file-list!=commit-file-list"
else
  FAILED="$FAILED git-ls-files-failed"
fi
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

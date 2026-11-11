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
# run with OUT set to the repo's parent folder deleted the entire working tree (repo included) because
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

# FAILED marker (round 2, hostile MINOR "exit 3 leaves a complete-looking package"): 364be5d wrote
# MANIFEST.md before the final status check, so an exit-3 run left a folder indistinguishable from a
# good package. Now the marker is the FIRST file written and the LAST file removed: it is deleted only
# after every check passed and MANIFEST.md exists. Any failure, abort, kill or crash in between leaves
# it in place, and MANIFEST.md is never written on a failed run.
FAILED_MARK="$OUT/FAILED"
if ! printf '%s\n' \
    "FAILED — this folder is NOT a gate package." \
    "The build is in progress, failed, or was interrupted. While this file exists nothing here may be" \
    "read as reviewed or complete. Reasons recorded by the build follow (none = it never finished)." \
    "" > "$FAILED_MARK"; then
  echo "REFUSING: could not write the FAILED marker in $OUT" >&2; exit 3
fi

# Any failure in producing the bound export or its hashes ABORTS (exit 3). fdb8f87 ignored
# these statuses, so a failed or partial archive still ended 0 with a partial tree.sha256.
abort_pkg() { echo "reason: $*" >> "$FAILED_MARK" 2>/dev/null; echo "REFUSING: package failed — $*" >&2; exit 3; }

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
# Round 3, Fable finding 10: `sha256sum -c` only reads the files the sidecar NAMES, so a file the checks
# ADDED inside the export (a mock `make test` writing junk) went unseen and the run ended 0. Repeat the
# section-1 enumeration after the checks: the export's non-directory entries must again be exactly the
# committed file list — same rule (`! -type d`) as before the checks, now compared by NAME, not only by
# count. An enumeration error is a failure, never "nothing added". Empty directories carry no bytes and are
# not compared (git cannot commit one, so the list below could not name it either).
EXPORT_AFTER=""
printf '%s\0' "${PATHS[@]}" | LC_ALL=C sort -z > "$WORK/commit_names.z" || EXPORT_AFTER="cannot-sort-commit-list"
if [ -z "$EXPORT_AFTER" ] && find "$EXPORT" -mindepth 1 ! -type d -printf '%P\0' > "$WORK/after.z"; then
  LC_ALL=C sort -z "$WORK/after.z" > "$WORK/after_sorted.z" || EXPORT_AFTER="cannot-sort-export-list"
  if [ -z "$EXPORT_AFTER" ] && ! cmp -s "$WORK/after_sorted.z" "$WORK/commit_names.z"; then
    # name up to five added entries (newline-free: committed names were already refused if they held one)
    ADDED=$(LC_ALL=C comm -z -23 "$WORK/after_sorted.z" "$WORK/commit_names.z" | tr '\0\n' '\n?' | head -5 | paste -sd, -)
    NAFTER=$(tr -cd '\0' < "$WORK/after_sorted.z" | wc -c)
    EXPORT_AFTER="export-holds-${NAFTER}-entries-for-${N}-committed(added:${ADDED:-none})"
  fi
elif [ -z "$EXPORT_AFTER" ]; then
  EXPORT_AFTER="cannot-enumerate-export-after-checks"
fi

# ---- 3. the Day-3 measurement, with its definition written down ----
# Round 2, hostile finding 9: 364be5d read a hard-coded ~/.hermes/plugin-data path (ignoring
# RECEIPTS_ROOT, which the plugin itself honours in receipts/ledger.py root()), and a RECEIPTS_SESSION
# whose receipt did not exist silently fell back to the newest receipt of ANY session — so the package
# could carry another session's counts under the requested name. Now:
#   * the receipts folder is the plugin's own: $RECEIPTS_ROOT/receipts, else ~/.hermes/plugin-data/receipts/receipts
#   * a NAMED session whose receipt is missing, not a regular file, unreadable, malformed, or whose
#     content names a different session REFUSES (nonzero) — there is no fallback from a named session
#   * with no session named, the newest receipt is used and the package says so (receipt_selection)
#   * the exact bytes counted are the bytes hashed: source path + sha256 + size go into day3_counts.json,
#     together with the packaged commit (package_commit)
#   * every refusal exits nonzero, so the final status names day3(N) and no day3_counts.json is written
SESSION="${RECEIPTS_SESSION:-}"
$PY - "$OUT" "$SESSION" "$COMMIT" <<'PY'
import hashlib, json, os, stat, sys
out, session, commit = sys.argv[1], sys.argv[2], sys.argv[3]


def refuse(msg):
    print(f"day3: REFUSING — {msg}", file=sys.stderr)
    sys.exit(4)


def stem_of(sid):
    # exactly receipts/receipt.py write(): the file a session's receipt is written to
    return sid.replace("/", "_").replace(os.sep, "_")


env_root = os.environ.get("RECEIPTS_ROOT") or ""          # same rule as receipts/ledger.py root()
root = env_root or os.path.join(os.path.expanduser("~"), ".hermes", "plugin-data", "receipts")
rdir = os.path.join(root, "receipts")

if session:
    src = os.path.join(rdir, stem_of(session) + ".json")
    selection = "named by RECEIPTS_SESSION"
else:
    try:
        cands = []
        with os.scandir(rdir) as it:
            for e in it:
                if e.name.endswith(".json") and e.is_file(follow_symlinks=False):
                    cands.append((e.stat(follow_symlinks=False).st_mtime_ns, e.name))
    except OSError as exc:            # an unreadable folder is never read as "no receipts"
        refuse(f"cannot list receipts folder {rdir}: {exc.__class__.__name__}")
    if not cands:
        refuse(f"no receipt found in {rdir} — Day-3 counts unavailable")
    src = os.path.join(rdir, max(cands)[1])
    selection = f"newest by mtime of {len(cands)} receipt(s) — no RECEIPTS_SESSION named"

# one open, no symlinks, regular file only; the bytes hashed are the bytes parsed
try:
    fd = os.open(src, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
except FileNotFoundError:
    refuse(f"receipt for session {session!r} not found: {src}" if session else f"receipt vanished: {src}")
except OSError as exc:
    refuse(f"cannot open receipt {src}: {exc.__class__.__name__} (symlinks are refused)")
with os.fdopen(fd, "rb") as fh:
    if not stat.S_ISREG(os.fstat(fh.fileno()).st_mode):
        refuse(f"receipt is not a regular file: {src}")
    raw = fh.read()
sha = hashlib.sha256(raw).hexdigest()
try:
    d = json.loads(raw)
except ValueError:
    refuse(f"receipt is not valid JSON: {src}")
if not isinstance(d, dict) or not isinstance(d.get("session"), str) or not isinstance(d.get("claims"), dict):
    refuse(f"receipt lacks a session string or a claims object: {src}")
if session and d["session"] != session:
    refuse(f"receipt {src} names session {d['session']!r}, not the requested {session!r}")
if stem_of(d["session"]) + ".json" != os.path.basename(src):
    refuse(f"receipt file name does not match the session it names ({d['session']!r}): {src}")
c = d["claims"]
# Round 3, Fable finding 9: the counts were taken on trust. A receipt saying backed=3 over three
# CONTRADICTED verdicts, or backed=999 with judged=1, ended 0 with a 0.0% share. receipts/receipt.py
# build() derives every count from ONE verdict list (one verdict per judged claim), so a receipt it wrote
# satisfies both rules below; anything else is refused, never repaired or re-derived:
#   * judged and all four verdict counts are non-negative integers, and the four sum to judged
#   * when the receipt carries its `verdicts` list (receipt.py always writes one), it is a list of objects
#     whose `verdict` is one of the four names, it has exactly `judged` entries, and recounting it gives
#     each of the four counts exactly
# This is internal consistency, not authenticity: a receipt can be edited consistently. The bytes are
# bound by source_receipt_sha256, and whether the list was present is recorded (verdicts_recounted).
VERDICT_KEYS = {"BACKED": "backed", "UNBACKED": "unbacked", "CONTRADICTED": "contradicted",
                "UNVERIFIABLE": "unverifiable"}
for k in ("judged",) + tuple(VERDICT_KEYS.values()):
    if type(c.get(k)) is not int or c[k] < 0:
        refuse(f"receipt claims.{k} is missing or not a non-negative integer: {src}")
four = sum(c[k] for k in VERDICT_KEYS.values())
if four != c["judged"]:
    refuse(f"receipt counts do not add up: backed+unbacked+contradicted+unverifiable = {four}, "
           f"claims.judged = {c['judged']}: {src}")
verdicts_recounted = "verdicts" in d
if verdicts_recounted:
    vs = d["verdicts"]
    if not isinstance(vs, list):
        refuse(f"receipt verdicts is not a list: {src}")
    tally = dict.fromkeys(VERDICT_KEYS.values(), 0)
    for i, v in enumerate(vs):
        name = v.get("verdict") if isinstance(v, dict) else None
        if not isinstance(name, str) or name not in VERDICT_KEYS:
            refuse(f"receipt verdicts[{i}] has no recognised verdict ({name!r}): {src}")
        tally[VERDICT_KEYS[name]] += 1
    if len(vs) != c["judged"]:
        refuse(f"receipt lists {len(vs)} verdicts for claims.judged = {c['judged']}: {src}")
    wrong = [f"{k}={c[k]} (list has {tally[k]})" for k in VERDICT_KEYS.values() if tally[k] != c[k]]
    if wrong:
        refuse(f"receipt counts disagree with its own verdict list: {', '.join(wrong)}: {src}")
checkable = c["backed"] + c["unbacked"] + c["contradicted"]
payload = {
    "package_commit": commit,
    "source_receipt": os.path.basename(src),
    "source_receipt_path": os.path.abspath(src),
    "source_receipt_sha256": sha,
    "source_receipt_bytes": len(raw),
    "receipt_selection": selection,
    "receipts_root": root,
    "receipts_root_from": "RECEIPTS_ROOT" if env_root else "default (~/.hermes/plugin-data/receipts)",
    "session": d["session"],
    "generated": d.get("generated"),
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
    "verdicts_recounted": verdicts_recounted,
    "checkable": checkable,
    "unbacked_claim_share": round(100 * (c["unbacked"] + c["contradicted"]) / checkable, 1) if checkable else None,
    "gate": {"unbacked_share_threshold": 20, "pivot_share_threshold": 30, "pivot_fired": bool(checkable and
             (c["unbacked"] + c["contradicted"]) / checkable > 0.30)},
    "known_limits": [
        f"only {checkable} claims were checkable in this one session; a small denominator is not a property",
        "claim detection is regex-based: paraphrases are missed and appear as 'no claim detected'",
        "relative paths are unjudgeable by design (they belong to a CWD or another host)",
        "the sealed 8/8 acceptance set was written by the same author and is a DEVELOPMENT score",
        "a receipt does not record which plugin commit judged it: package_commit names the package these "
        "counts were shipped in, not proof that this commit produced them; source_receipt_sha256 binds the "
        "exact receipt bytes counted",
        "the counts are checked for internal consistency (the four verdict counts sum to judged; when the "
        "receipt carries its verdict list, recounting it reproduces every count — see verdicts_recounted); "
        "a receipt edited consistently passes, so this is not proof the counts are authentic",
    ],
}
with open(os.path.join(out, "day3_counts.json"), "w") as fh:
    json.dump(payload, fh, indent=2)
print(f"day3 counts from {os.path.basename(src)}: {checkable} checkable, "
      f"unbacked-claim share {payload['unbacked_claim_share']}% "
      f"(a verdict share with no truth labels — NOT a false-positive rate)")
print(f"day3 source: {payload['source_receipt_path']} sha256 {sha} ({selection})")
PY
DAY3_EXIT=$?

# ---- 4. the outward commands, for Greg to approve one at a time ----
cat > "$OUT/outward_commands.md" <<EOF
# Outward steps — each needs Greg's explicit yes, shown before it runs

Nothing below has been run. The repository does not exist; there are no remotes.

## 1. Create the empty public repo
    gh repo create gwelby/claim-receipts --public \\
        --description "claim-receipts: what an agent said vs what it did"

## 2. Push this exact commit — the reviewed tree, pinned by SHA not branch name
    # a NEW remote name: an existing remote may be a review bundle, not a repo
    git remote add public https://github.com/gwelby/claim-receipts.git
    git push public $COMMIT:refs/heads/main
    # verify anonymously (no credentials; must print exactly $COMMIT):
    git ls-remote https://github.com/gwelby/claim-receipts.git refs/heads/main | grep -F "$COMMIT"

## 3. Open the catalog PR (it must be open by the deadline; merging is the maintainers')
    # one new file, plugin-catalog/claim-receipts.yaml, sha: $COMMIT, in a PR to
    # NousResearch/hermes-agent from a fork, with the disclosure lines in the PR text

## 4. Post the demo on X (after the video exists): <= 90 s, tag @NousResearch, one paragraph

## 5. Send the X post link and the catalog PR link through the entry form

## Preconditions, per the publish gate
- [ ] Codex reviews this package and PASSES (not self-check)
- [ ] held-out acceptance set scored (not the author's own fixtures)
- [ ] disclosure review: no internal paths, seat names, register ids, hostnames, IPs, keys
EOF

# ---- 5. the manifest — WRITTEN ONLY AFTER SECTION 6 PASSES ----
# 364be5d wrote it here unconditionally, so an exit-3 package still had a MANIFEST.md. It is now a
# function, called once every required artifact and check is green; a failed run never has one.
write_manifest() {
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
  echo "| day3_counts.json (source) | which receipt was counted: path, sha256, size, how it was selected, and the packaged commit |"
  echo "| outward_commands.md | the exact commands, none run |"
  echo
  echo "A folder that still holds a file named FAILED is not a gate package: that marker is written first"
  echo "and removed only after every check passed and this manifest was written."
  echo
  echo "## Verify this package"
  echo '```'
  echo "git clone history.bundle verify/"
  echo "cd verify && git log --oneline | head -1     # must equal COMMIT"
  echo "sha256sum -c ../tree.sha256                   # must be all OK"
  echo "test ! -e ../FAILED                           # must hold: a FAILED file means the build never finished"
  echo '```'
} > "$OUT/MANIFEST.md"
}

# ---- 6. final status: required artifacts + verifiable export + required-check
# success. Round-3: the captured exit codes now gate — a failed make test,
# make acceptance, validator run, or Day-3 stage refuses the package instead of
# ending exit 0 with artifacts present. ----
MISSING=""
for f in COMMIT HEAD.txt history.txt history.bundle tree.sha256 reproduction.log outward_commands.md day3_counts.json; do
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
[ -z "$EXPORT_AFTER" ] || FAILED="$FAILED export-files-added-by-checks:$EXPORT_AFTER"
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
  echo "reason: missing/unverifiable:$MISSING failed-checks:$FAILED" >> "$FAILED_MARK" 2>/dev/null
  echo "REFUSING: package failed — missing/unverifiable:$MISSING failed-checks:$FAILED" >&2
  exit 3
fi

# Everything passed: now, and only now, the manifest — then the FAILED marker is removed LAST.
write_manifest || abort_pkg "could not write MANIFEST.md"
[ -s "$OUT/MANIFEST.md" ] || abort_pkg "MANIFEST.md is empty"
rm -f -- "$FAILED_MARK"
if [ -e "$FAILED_MARK" ] || [ -L "$FAILED_MARK" ]; then
  echo "REFUSING: package failed — could not remove the FAILED marker $FAILED_MARK" >&2
  exit 3
fi

echo
echo "gate package: $OUT"
ls -la "$OUT" | tail -n +2 | awk '{printf "  %-24s %8s\n", $9, $5}'

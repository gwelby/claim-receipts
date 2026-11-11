#!/usr/bin/env python3
"""C5 + output policy: scripts/gate_package.sh must bind success to ONE complete, checked export of the commit.

Codex's fdb8f87 recheck (package/EVIDENCE_FINDINGS.md) ran the exact script under a confined mock harness and
found four package controls ending 0: a failed archive yielding one of two files, archive exit 37 after a
complete export, a live-index omission leaving a committed file unhashed, and checks reading changed LIVE bytes
while the sidecar hashed frozen ones. Clean pre-existing empty output also reached cleanup/exit 0.

This test ports that harness (same mock idea: every rm/git/make/hermes/mkdir/mktemp/tar and the absolute-python
Day-3 stage is intercepted; mkdir/mktemp/tar/rm effects are fenced to a per-row temp fixture; the real receipt
discovery never runs; no network, no push, no repo creation). Adaptations, stated so they can be audited:
  * committed bytes live in their own store (fixture/committed), so `git archive`/`ls-tree` describe the COMMIT
    while candidate/ is the live tree — Codex's mock read live files for the archive;
  * `git diff` is computed (live bytes vs commit, index list vs commit) instead of always clean; Codex's
    index-omission and live-race rows are modelled as drift that happens AFTER the dirty check (fired by the
    archive call), which is the only way real git can show them;
  * new git operations used by the repaired script: ls-tree, hash-object, bundle list-heads;
  * rm deletes, but only inside the fixture (so the sanctioned GATE_PACKAGE reuse can be exercised).
One more row uses REAL git in a throwaway repo (make/hermes/rm/Day-3 still intercepted) so the actual git
command lines are exercised, then clones the produced bundle and runs `sha256sum -c` against tree.sha256.

GATE_SCRIPT=<path> runs the same rows against another copy of the script (used to show fdb8f87 fails).
"""
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
GATE = pathlib.Path(os.environ.get("GATE_SCRIPT") or ROOT / "scripts" / "gate_package.sh").resolve()
COMMIT = "c5" * 20
fails = 0


def check(name, ok, detail=""):
    global fails
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{('  ' + str(detail)) if detail else ''}")
    if not ok:
        fails += 1


MOCK = r'''#!/usr/bin/python3 -IS
import hashlib,io,json,os,shutil,sys,tarfile
from pathlib import Path
name=Path(sys.argv[0]).name; args=sys.argv[1:]
root=Path(os.environ['FENCE_ROOT']).resolve()
E=os.environ.get
event={'command':name,'args':args,'cwd':os.getcwd(),'effects':[]}
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def blob(b):return hashlib.sha1(b'blob %d\0'%len(b)+b).hexdigest()
def fenced(p):
    p=Path(p).resolve()
    if not p.is_relative_to(root):finish(98,err='HARNESS FENCE: path escapes row fixture: '+str(p)+'\n')
    return p
def finish(rc=0,out='',err='',binary=None):
    event['exit']=rc
    event['stdout']=out if binary is None else '<%d bytes>'%len(binary)
    event['stderr']=err
    with open(E('MOCK_LOG'),'a') as f:f.write(json.dumps(event)+'\n')
    if binary is not None:sys.stdout.buffer.write(binary)
    else:sys.stdout.write(out)
    sys.stderr.write(err)
    raise SystemExit(rc)
def write(p,data):
    p=fenced(p);p.write_bytes(data)
    event['effects'].append({'write':str(p),'sha256':digest(p)})
STATE=root/'state.json'
def state():return json.loads(STATE.read_text())
def save(s):STATE.write_text(json.dumps(s))
COMMITTED=root/'committed'
def committed():return sorted(p.name for p in COMMITTED.iterdir())
LIVE=root/'candidate'
if name=='rm':
    for a in args:
        if a.startswith('-'):continue
        p=fenced(a)
        if p.is_dir() and not p.is_symlink():shutil.rmtree(p)
        elif p.exists() or p.is_symlink():p.unlink()
        event['effects'].append({'removed_inside_fixture':str(p)})
    finish()
if name=='mkdir':
    try:
        for a in args:
            if a.startswith('-'):continue
            p=fenced(a);p.mkdir(parents='-p' in args,exist_ok='-p' in args)
            event['effects'].append({'mkdir':str(p)})
    except OSError as e:finish(1,err='synthetic mkdir error: '+str(e)+'\n')
    finish()
if name=='mktemp':
    if args!=['-d']:finish(97,err='HARNESS unsupported mktemp args\n')
    p=fenced(root/'export-tmp');p.mkdir(exist_ok=False)
    finish(out=str(p)+'\n')
if name=='tar':
    if len(args)!=3 or args[:2]!=['-x','-C']:finish(97,err='HARNESS unsupported tar args\n')
    dest=fenced(args[2]);data=sys.stdin.buffer.read()
    try:
        with tarfile.open(fileobj=io.BytesIO(data),mode='r:') as tf:
            for m in tf:
                p=fenced(dest/m.name)
                if m.isfile():
                    p.parent.mkdir(parents=True,exist_ok=True);write(p,tf.extractfile(m).read())
                elif m.isdir():p.mkdir(parents=True,exist_ok=True)
                else:finish(98,err='HARNESS unsupported archive member\n')
    except tarfile.TarError as e:finish(2,err='synthetic tar: '+str(e)+'\n')
    finish(int(E('MOCK_TAR','0')))
if name=='make':
    mode=args[0] if args else ''
    p=fenced(Path.cwd()/'tracked.txt')
    if E('MOCK_MAKE_MUTATES')=='1' and mode=='test':write(p,b'checks rewrote the checked bytes\n')
    if E('MOCK_MAKE_TOUCH_LIVE'):write(Path(E('MOCK_MAKE_TOUCH_LIVE')),b'live edit while checks ran\n')
    if E('MOCK_MAKE_KILL_GATE')=='1':
        # an interrupted build: SIGKILL every ancestor that is the gate script (and its subshells) — nothing else
        import signal
        pid=os.getppid();killed=[]
        while pid>1:
            try:
                cmd=Path('/proc/%d/cmdline'%pid).read_bytes()
                ppid=int(Path('/proc/%d/stat'%pid).read_text().rsplit(')',1)[1].split()[1])
            except OSError:break
            argv=cmd.split(b'\0')
            # exact: a bash whose script argument IS this row's candidate/scripts/gate_package.sh; stop at the
            # first ancestor that is not (never walks past the gate into the test runner or anything above)
            if not any(a.endswith(b'/candidate/scripts/gate_package.sh') for a in argv[1:2]):
                if killed:break
            else:killed.append(pid)
            pid=ppid
        event['effects'].append({'killed_gate_pids':killed})
        for k in killed:os.kill(k,signal.SIGKILL)
        finish(137)
    rc=int(E('MOCK_MAKE_'+mode.upper(),'0'))
    finish(rc,out='synthetic %s exit %d\nsynthetic checked cwd=%s\nsynthetic checked tracked_sha256=%s\n'%(mode,rc,Path.cwd(),digest(p)))
if name=='hermes':
    rc=int(E('MOCK_HERMES','0'))
    finish(rc,out=''.join('synthetic validator output line %d\n'%i for i in range(1,8))+'synthetic validator exit %d\n'%rc)
if name=='absolute-python-intercepted':
    sys.stdin.buffer.read()
    if E('MOCK_DAY3','present')=='present':
        write(Path(args[1])/'day3_counts.json',b'{"synthetic": true, "not_a_false_positive_rate": "no truth labels"}\n')
    rc=int(E('MOCK_PYTHON','0'))
    finish(rc,out='synthetic: receipt discovery never executed; exit %d\n'%rc)
if name=='git':
    op=args[0] if args else ''
    if op=='diff':
        if E('MOCK_DIRTY','0')=='1':finish(1)
        if '--cached' in args:finish(0 if sorted(state()['index'])==committed() else 1)
        for n in committed():
            lp=LIVE/n
            if not lp.is_file() or lp.read_bytes()!=(COMMITTED/n).read_bytes():finish(1)
        finish(0)
    if op=='status':finish(out=' M tracked.txt\n')
    if op=='rev-parse':finish(out=E('MOCK_COMMIT')+'\n')
    if op=='log':
        hist='--stat' in args
        rc=int(E('MOCK_HISTORY','0')) if hist else 0
        finish(rc,out='' if hist and E('MOCK_HISTORY_ABSENT')=='1' else 'synthetic frozen commit '+E('MOCK_COMMIT')+'\n')
    if op=='bundle':
        sub=args[1]
        if sub=='verify':finish(int(E('MOCK_BUNDLE_VERIFY','0')))
        if sub=='list-heads':
            h=E('MOCK_BUNDLE_HEAD') or E('MOCK_COMMIT')
            finish(out='%s refs/heads/master\n%s HEAD\n'%(E('MOCK_COMMIT'),h))
        if sub!='create':finish(97,err='HARNESS unsupported bundle op\n')
        rc=int(E('MOCK_BUNDLE','0'))
        if not rc:write(args[2],b'synthetic bundle placeholder\n')
        finish(rc)
    if op=='archive':
        data=io.BytesIO()
        with tarfile.open(fileobj=data,mode='w') as tf:
            for n in committed():
                if n=='second.txt' and E('MOCK_ARCHIVE_OMIT_SECOND')=='1':continue
                b=(COMMITTED/n).read_bytes()
                if n=='tracked.txt' and E('MOCK_ARCHIVE_ALTER')=='1':b=b'substituted bytes\n'
                m=tarfile.TarInfo(n);m.size=len(b);tf.addfile(m,io.BytesIO(b))
            if E('MOCK_ARCHIVE_EXTRA')=='1':
                b=b'not in the commit\n';m=tarfile.TarInfo('extra.txt');m.size=len(b);tf.addfile(m,io.BytesIO(b))
        # drift AFTER the dirty check: the live tree and/or index change once the archive is taken
        if E('MOCK_LIVE_RACE')=='1':write(LIVE/'tracked.txt',b'synthetic live bytes changed after immutable export\n')
        if E('MOCK_INDEX_OMIT_SECOND_LATE')=='1':
            s=state();s['index']=[n for n in s['index'] if n!='second.txt'];save(s)
        finish(int(E('MOCK_ARCHIVE','0')),binary=data.getvalue())
    if op=='ls-tree':
        rc=int(E('MOCK_LS_TREE','0'))
        if rc:finish(rc,err='synthetic ls-tree failure\n')
        out=''.join('100644 blob %s\t%s\0'%(blob((COMMITTED/n).read_bytes()),n) for n in committed())
        finish(out=out)
    if op=='hash-object':
        if args[1:]!=['--no-filters','--stdin-paths']:finish(97,err='HARNESS unsupported hash-object args\n')
        out=''
        for line in sys.stdin.read().splitlines():
            p=fenced(line)
            if not p.is_file():finish(128,out=out,err="fatal: could not open '%s'\n"%line)
            out+=blob(p.read_bytes())+'\n'
        finish(out=out)
    if op=='ls-files':
        sep='\0' if '-z' in args else '\n'
        finish(out=''.join(n+sep for n in state()['index']))
    finish(97,err='HARNESS unsupported git operation\n')
finish(97,err='HARNESS unsupported mock name\n')
'''

BASH_ENV_TEXT = '''function /usr/bin/python3.12 {
  absolute-python-intercepted "$@"
}
'''


def tree_state(root):
    out = {}
    for p in sorted(root.rglob("*")):
        rel = str(p.relative_to(root))
        if rel.startswith(("commands.jsonl", "state.json")):
            continue
        if p.is_symlink():
            out[rel] = "symlink:" + os.readlink(p)
        elif p.is_file():
            out[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
        else:
            out[rel] = "dir"
    return out


BASE = pathlib.Path(tempfile.mkdtemp(prefix="receipts-gate-binding-"))
MOCKDIR = BASE / "mock-bin"
MOCKDIR.mkdir()
(MOCKDIR / "mock.py").write_text(MOCK)
(MOCKDIR / "mock.py").chmod(0o755)
for tool in ("rm", "git", "make", "hermes", "mkdir", "mktemp", "tar", "absolute-python-intercepted"):
    (MOCKDIR / tool).symlink_to(MOCKDIR / "mock.py")
ENVFILE = BASE / "bash-env.sh"
ENVFILE.write_text(BASH_ENV_TEXT)
TRACKED = b"synthetic tracked source\n"
SECOND = b"synthetic second committed source\n"


def seed_receipt(folder, stem, session, backed=2, unbacked=1, contradicted=0, raw=None, mtime=None):
    """A synthetic receipt in the shape receipts/receipt.py write() produces (only the fields the gate reads)."""
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / f"{stem}.json"
    data = raw if raw is not None else json.dumps(
        {"session": session, "generated": "2026-11-10T00:00:00+0000",
         "claims": {"detected": backed + unbacked + contradicted + 1, "judged": backed + unbacked + contradicted,
                    "backed": backed, "unbacked": unbacked, "contradicted": contradicted, "unverifiable": 1}},
        indent=2).encode()
    p.write_bytes(data)
    if mtime is not None:
        os.utime(p, (mtime, mtime))
    return p


def run(name, out_kind="new", real_day3=None, **mock):
    """real_day3=None: the Day-3 python is intercepted (BASH_ENV), as in every C5 row.
    real_day3=callable(root) -> env dict: the REAL Day-3 stage runs over synthetic receipts the callable seeds
    under root (HOME=root/home); the dict adds RECEIPTS_SESSION / RECEIPTS_ROOT. Reads only fixture files."""
    root = BASE / name
    repo = root / "candidate"
    (repo / "scripts").mkdir(parents=True)
    shutil.copyfile(GATE, repo / "scripts/gate_package.sh")
    (root / "committed").mkdir()
    files = {"tracked.txt": TRACKED}
    if mock.pop("second_file", False):
        files["second.txt"] = SECOND
    for n, b in files.items():
        (root / "committed" / n).write_bytes(b)
        (repo / n).write_bytes(b)
    index = sorted(files)
    if mock.pop("index_omit_second_early", False):
        index = [n for n in index if n != "second.txt"]
    (root / "state.json").write_text(json.dumps({"index": index}))
    log = root / "commands.jsonl"
    env = {"PATH": f"{MOCKDIR}:/usr/bin:/bin", "BASH_ENV": str(ENVFILE), "MOCK_LOG": str(log),
           "MOCK_COMMIT": COMMIT, "FENCE_ROOT": str(root), "LC_ALL": "C", "PYTHONDONTWRITEBYTECODE": "1"}
    for k, v in mock.items():
        env["MOCK_" + k.upper()] = str(int(v) if isinstance(v, bool) else v)
    if real_day3 is not None:
        del env["BASH_ENV"]                     # the absolute python is NOT intercepted in these rows
        env["HOME"] = str(root / "home")
        (root / "home").mkdir()
        env.update(real_day3(root))
    out = root / "new-output"
    if out_kind == "repo": out = repo
    elif out_kind == "inside": out = repo / "owned-subtree"; out.mkdir()
    elif out_kind == "root": out = pathlib.Path("/")
    elif out_kind == "ancestor": out = root
    elif out_kind == "existing_external":
        out = root / "existing-external"; out.mkdir(); (out / "KEEP").write_text("keep\n")
    elif out_kind == "default":
        out = repo / "GATE_PACKAGE"; out.mkdir(); (out / "KEEP").write_text("previous package\n")
    elif out_kind == "existing_file": out = root / "existing-file"; out.write_text("keep\n")
    elif out_kind == "existing_empty_dir": out = root / "existing-empty"; out.mkdir()
    elif out_kind == "dangling_symlink": out = root / "dangling"; out.symlink_to(root / "nowhere")
    elif out_kind == "symlink_ancestor": out = root / "ancestor-alias"; out.symlink_to(root, target_is_directory=True)
    elif out_kind == "symlink_inside": out = root / "inside-alias"; out.symlink_to(repo / "inner", target_is_directory=True)
    elif out_kind == "relative_ancestor": out = repo / ".."
    argv = ["/bin/bash", str(repo / "scripts/gate_package.sh")] + ([] if out_kind == "default" else [str(out)])
    before = tree_state(root)
    cp = subprocess.run(argv, cwd=repo, env=env, capture_output=True, text=True, timeout=120)
    after = tree_state(root)
    calls = [json.loads(s) for s in log.read_text().splitlines()] if log.exists() else []
    harness = [c for c in calls if c["exit"] in (97, 98)]
    art = lambda n: (out / n).read_text() if out_kind not in ("root",) and (out / n).is_file() else None
    return {
        "exit": cp.returncode, "stderr": cp.stderr, "calls": calls, "harness_errors": harness,
        "rm": [c["args"] for c in calls if c["command"] == "rm"],
        "mkdir": [c["args"] for c in calls if c["command"] == "mkdir"],
        "make": [c for c in calls if c["command"] == "make"],
        "py": sum(c["command"] == "absolute-python-intercepted" for c in calls),
        "changed": {k for k in set(before) | set(after) if before.get(k) != after.get(k)},
        "log": art("reproduction.log"), "sums": art("tree.sha256"), "outward": art("outward_commands.md"),
        "day3": json.loads(art("day3_counts.json")) if art("day3_counts.json") is not None else None,
        "failed_mark": art("FAILED"), "manifest": art("MANIFEST.md"),
        "root": root, "out": out,
    }


def marked_failed(r, name):
    """MINOR (exit 3): a failed package must carry FAILED and must NOT carry MANIFEST.md."""
    check(f"{name}: FAILED marker present, no MANIFEST.md",
          r["failed_mark"] is not None and r["manifest"] is None,
          f"FAILED={'yes' if r['failed_mark'] is not None else 'no'} MANIFEST={'yes' if r['manifest'] is not None else 'no'}")


def marked_complete(r, name):
    check(f"{name}: MANIFEST.md present, FAILED marker gone",
          r["manifest"] is not None and r["failed_mark"] is None and "test ! -e ../FAILED" in (r["manifest"] or ""),
          f"FAILED={'yes' if r['failed_mark'] is not None else 'no'} MANIFEST={'yes' if r['manifest'] is not None else 'no'}")


def no_harness(r, name):
    check(f"{name}: harness clean", not r["harness_errors"], r["harness_errors"][:1])


SHA_T = hashlib.sha256(TRACKED).hexdigest()
SHA_S = hashlib.sha256(SECOND).hexdigest()

print(f"gate package — C5 binding + output policy  (script: {GATE})")

print("\nretained: eleven dirty/unsafe-path guards refuse before ANY rm/mkdir/change")
for kind in ("repo", "inside", "root", "ancestor", "existing_external", "default", "existing_file",
             "existing_empty_dir", "symlink_ancestor", "symlink_inside", "relative_ancestor"):
    r = run("guard_" + kind, kind, dirty=1)
    no_harness(r, kind)
    check(f"guard {kind}: exit 2, no rm/mkdir, nothing changed",
          r["exit"] == 2 and not r["rm"] and not r["mkdir"] and not r["changed"],
          f"exit={r['exit']} rm={r['rm']} mkdir={r['mkdir']} changed={sorted(r['changed'])[:3]}")

print("\noutput policy: every pre-existing OUT except the sanctioned GATE_PACKAGE is refused (no enumeration)")
for kind in ("existing_empty_dir", "existing_file", "existing_external", "dangling_symlink"):
    r = run("clean_" + kind, kind)
    no_harness(r, kind)
    check(f"clean {kind}: exit 2, no rm/mkdir, nothing changed",
          r["exit"] == 2 and not r["rm"] and not r["mkdir"] and not r["changed"], f"exit={r['exit']} rm={r['rm']}")
r = run("clean_default_sanctioned", "default")
check("clean sanctioned GATE_PACKAGE: replaced, exit 0", r["exit"] == 0 and not (r["out"] / "KEEP").exists(),
      f"exit={r['exit']} {r['stderr'][-200:]}")
marked_complete(r, "clean sanctioned GATE_PACKAGE")

print("\npositives: complete export, checked in place, ends 0")
r = run("baseline_mocked")
no_harness(r, "baseline")
check("baseline exit 0", r["exit"] == 0, r["stderr"][-300:])
marked_complete(r, "baseline")
check("baseline Day-3 stage intercepted exactly once", r["py"] == 1, r["py"])
check("baseline sidecar = exported (committed) bytes", r["sums"] == f"{SHA_T}  tracked.txt\n", r["sums"])
check("baseline seven validator lines retained",
      r["log"] is not None and all(f"synthetic validator output line {i}" in r["log"] for i in range(1, 8)))
check("pinned-SHA push retained (to a new remote, never an existing one)", r["outward"] is not None and f"git push public {COMMIT}:refs/heads/main" in r["outward"] and "git remote add origin" not in r["outward"])
r = run("two_file_export_positive", second_file=1)
no_harness(r, "two-file")
check("two-file positive exit 0", r["exit"] == 0, r["stderr"][-300:])
check("two-file sidecar has both committed files",
      r["sums"] == f"{SHA_S}  second.txt\n{SHA_T}  tracked.txt\n", r["sums"])
exp = str(r["root"] / "export-tmp" / "tree")
check("checks ran inside the export (all three make/validator cwd)",
      r["make"] and all(c["cwd"] == exp for c in r["calls"] if c["command"] in ("make", "hermes")),
      [c["cwd"] for c in r["make"]])

print("\nretained: required check / artifact failures refuse")
for name, kw, needles in (
    ("failed_required_checks", {"make_test": 17, "make_acceptance": 19, "hermes": 23},
     ["make-test(17)", "make-acceptance(19)", "validator(23)"]),
    ("failed_test", {"make_test": 17}, ["make-test(17)"]),
    ("failed_acceptance", {"make_acceptance": 19}, ["make-acceptance(19)"]),
    ("failed_validator", {"hermes": 23}, ["validator(23)"]),
    ("unavailable_validator", {"hermes": 127}, ["validator(127)"]),
    ("failed_bundle", {"bundle": 29}, ["history.bundle"]),
    ("failed_bundle_verify", {"bundle_verify": 29}, ["history.bundle(unverifiable)"]),
    ("missing_day3", {"day3": "absent"}, ["day3_counts.json"]),
    ("failed_day3_with_artifact", {"python": 31}, ["day3(31)"]),
    ("missing_history", {"history": 35, "history_absent": 1}, ["history.txt"]),
):
    r = run(name, **kw)
    no_harness(r, name)
    check(f"{name}: exit 3 naming {needles}", r["exit"] == 3 and all(n in r["stderr"] for n in needles),
          f"exit={r['exit']} {r['stderr'][-160:]}")
    marked_failed(r, name)
    if name == "failed_required_checks":
        check("raw log keeps exit=17/19/23", r["log"] is not None and all(f"exit={n}" in r["log"] for n in (17, 19, 23)))

print("\nC5: Codex's four package controls must end NONZERO")
r = run("partial_archive_export", second_file=1, archive_omit_second=1, archive=37)
no_harness(r, "partial")
check("partial archive (37, one of two files): nonzero, no COMMIT written",
      r["exit"] != 0 and not (r["out"] / "COMMIT").exists(), f"exit={r['exit']} {r['stderr'][-160:]}")
marked_failed(r, "partial archive")
check("partial archive: the abort reason is recorded in FAILED",
      "reason: export of" in (r["failed_mark"] or ""), (r["failed_mark"] or "")[-160:])
r = run("archive_failed_after_complete_export", archive=37)
no_harness(r, "archive37")
check("archive 37 after complete export: nonzero", r["exit"] != 0, f"exit={r['exit']} {r['stderr'][-160:]}")
marked_failed(r, "archive 37 after complete export")
r = run("index_drift_omits_file", second_file=1, index_omit_second_late=1)
no_harness(r, "index drift")
check("index omission after dirty check: nonzero", r["exit"] != 0, f"exit={r['exit']} {r['stderr'][-160:]}")
marked_failed(r, "index omission after dirty check")
check("index omission: sidecar (if any) is never missing a committed file",
      r["sums"] is None or ("second.txt" in r["sums"] and "tracked.txt" in r["sums"]), r["sums"])
r = run("live_tree_race", live_race=1)
no_harness(r, "live race")
check("live race: nonzero", r["exit"] != 0, f"exit={r['exit']} {r['stderr'][-160:]}")
marked_failed(r, "live race")
digests = [c["stdout"].split("tracked_sha256=")[1].strip() for c in r["make"]]
check("live race: checks read the FROZEN bytes, same as the sidecar",
      digests and all(d == SHA_T for d in digests) and r["sums"] == f"{SHA_T}  tracked.txt\n", digests)

print("\nMINOR exit-3: an INTERRUPTED build (gate killed during make test) leaves FAILED, never a MANIFEST.md")
r = run("killed_during_checks", make_kill_gate=1)
no_harness(r, "killed")
check("killed build: nonzero (SIGKILL)", r["exit"] != 0, r["exit"])
marked_failed(r, "killed build")

print("\nC5 extensions: incomplete/foreign/altered export, failed list, mutation by checks, bundle identity")
for name, kw in (
    ("archive_omits_file_exit0", {"second_file": 1, "archive_omit_second": 1}),
    ("archive_extra_file", {"archive_extra": 1}),
    ("archive_altered_bytes", {"archive_alter": 1}),
    ("tar_failed", {"tar": 2}),
    ("ls_tree_failed", {"ls_tree": 128}),
    ("checks_mutate_export", {"make_mutates": 1}),
    ("bundle_head_not_commit", {"bundle_head": "d" * 40}),
):
    r = run(name, **kw)
    no_harness(r, name)
    check(f"{name}: nonzero", r["exit"] != 0, f"exit={r['exit']} {r['stderr'][-160:]}")
    marked_failed(r, name)
r = run("index_drift_early", second_file=1, index_omit_second_early=1)
check("index omission before the build: dirty refusal exit 2, nothing changed",
      r["exit"] == 2 and not r["rm"] and not r["mkdir"] and not r["changed"], f"exit={r['exit']}")

print("\nfinding 9: Day-3 counts bound to the named session, RECEIPTS_ROOT, and the exact receipt bytes")
print("  (real Day-3 python over synthetic receipts under a fixture HOME; everything else mocked as above)")
T_OLD, T_NEW = 1_700_000_000, 1_700_000_500
sha_of = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
seeded = {}


def home_rdir(root):
    return root / "home" / ".hermes" / "plugin-data" / "receipts" / "receipts"


def d_named_missing(root):
    # Hostile row: the named session has no receipt; ANOTHER session's receipt is the newest one there.
    seed_receipt(home_rdir(root), "other-session", "other-session", backed=0, unbacked=5, mtime=T_NEW)
    return {"RECEIPTS_SESSION": "wanted-session"}
r = run("day3_named_missing", real_day3=d_named_missing)
no_harness(r, "day3 named missing")
check("named session with no receipt: exit 3 naming day3(...)",
      r["exit"] == 3 and "day3(" in r["stderr"] and "wanted-session" in r["stderr"], f"exit={r['exit']} {r['stderr'][-220:]}")
check("named session with no receipt: no day3_counts.json (never another session's counts)",
      r["day3"] is None, (r["day3"] or {}).get("session"))
marked_failed(r, "day3 named missing")


def d_named_present(root):
    seeded["named"] = seed_receipt(home_rdir(root), "wanted-session", "wanted-session", mtime=T_OLD)
    seed_receipt(home_rdir(root), "other-session", "other-session", backed=0, unbacked=5, mtime=T_NEW)
    return {"RECEIPTS_SESSION": "wanted-session"}
r = run("day3_named_present", real_day3=d_named_present)
no_harness(r, "day3 named present")
check("paired positive: named session present (older than another) -> exit 0", r["exit"] == 0, r["stderr"][-300:])
marked_complete(r, "day3 named present")
d = r["day3"] or {}
check("named positive: counts are the NAMED session's, not the newest",
      d.get("session") == "wanted-session" and d.get("counts", {}).get("backed") == 2, d.get("session"))
check("named positive: source path + sha256 + size + selection + commit recorded",
      d.get("source_receipt_path") == str(seeded["named"]) and d.get("source_receipt_sha256") == sha_of(seeded["named"])
      and d.get("source_receipt_bytes") == seeded["named"].stat().st_size
      and d.get("receipt_selection") == "named by RECEIPTS_SESSION" and d.get("package_commit") == COMMIT,
      {k: d.get(k) for k in ("source_receipt_path", "receipt_selection", "package_commit")})
check("named positive: receipts_root is the default when RECEIPTS_ROOT is unset",
      d.get("receipts_root_from", "").startswith("default"), d.get("receipts_root_from"))


def d_env_root(root):
    alt = root / "alt-root"
    seeded["alt"] = seed_receipt(alt / "receipts", "alt-session", "alt-session", backed=3, unbacked=0, mtime=T_OLD)
    seed_receipt(home_rdir(root), "home-session", "home-session", backed=0, unbacked=5, mtime=T_NEW)  # decoy
    return {"RECEIPTS_ROOT": str(alt), "RECEIPTS_SESSION": "alt-session"}
r = run("day3_receipts_root_honoured", real_day3=d_env_root)
no_harness(r, "day3 RECEIPTS_ROOT")
d = r["day3"] or {}
check("RECEIPTS_ROOT honoured: exit 0, counts from $RECEIPTS_ROOT/receipts, not ~/.hermes",
      r["exit"] == 0 and d.get("session") == "alt-session" and d.get("source_receipt_path") == str(seeded["alt"])
      and d.get("receipts_root_from") == "RECEIPTS_ROOT", f"exit={r['exit']} session={d.get('session')} {r['stderr'][-200:]}")


def d_env_root_unnamed(root):
    alt = root / "alt-root"
    seeded["alt_u"] = seed_receipt(alt / "receipts", "alt-session", "alt-session", backed=3, unbacked=0, mtime=T_OLD)
    seed_receipt(home_rdir(root), "home-session", "home-session", backed=0, unbacked=5, mtime=T_NEW)  # decoy
    return {"RECEIPTS_ROOT": str(alt)}
r = run("day3_receipts_root_unnamed", real_day3=d_env_root_unnamed)
no_harness(r, "day3 RECEIPTS_ROOT unnamed")
d = r["day3"] or {}
check("RECEIPTS_ROOT, no session named: newest UNDER RECEIPTS_ROOT (the newer default-root decoy ignored)",
      r["exit"] == 0 and d.get("session") == "alt-session" and d.get("source_receipt_sha256") == sha_of(seeded["alt_u"]),
      f"exit={r['exit']} session={d.get('session')}")


def d_env_root_missing(root):
    (root / "alt-root" / "receipts").mkdir(parents=True)
    seed_receipt(home_rdir(root), "wanted-session", "wanted-session", mtime=T_NEW)  # only under the default root
    return {"RECEIPTS_ROOT": str(root / "alt-root"), "RECEIPTS_SESSION": "wanted-session"}
r = run("day3_receipts_root_named_missing", real_day3=d_env_root_missing)
no_harness(r, "day3 RECEIPTS_ROOT named missing")
check("RECEIPTS_ROOT set, named receipt only under ~/.hermes: refused (no fall-through to the default root)",
      r["exit"] == 3 and "day3(" in r["stderr"] and r["day3"] is None, f"exit={r['exit']} {r['stderr'][-200:]}")
marked_failed(r, "day3 RECEIPTS_ROOT named missing")


def d_unnamed(root):
    seed_receipt(home_rdir(root), "older-session", "older-session", mtime=T_OLD)
    seeded["newest"] = seed_receipt(home_rdir(root), "newest-session", "newest-session", backed=4, mtime=T_NEW)
    return {}
r = run("day3_unnamed_newest", real_day3=d_unnamed)
no_harness(r, "day3 unnamed")
d = r["day3"] or {}
check("positive control: no session named -> newest receipt, exit 0, selection stated, bytes bound",
      r["exit"] == 0 and d.get("session") == "newest-session" and d.get("receipt_selection", "").startswith("newest by mtime of 2")
      and d.get("source_receipt_sha256") == sha_of(seeded["newest"]), f"exit={r['exit']} {d.get('receipt_selection')}")
marked_complete(r, "day3 unnamed")


def d_content_mismatch(root):
    # a receipt FILE named for the requested session whose CONTENT is another session's (copied/renamed)
    seed_receipt(home_rdir(root), "wanted-session", "other-session", backed=0, unbacked=5, mtime=T_NEW)
    return {"RECEIPTS_SESSION": "wanted-session"}
r = run("day3_content_names_other_session", real_day3=d_content_mismatch)
no_harness(r, "day3 content mismatch")
check("receipt file named for the session but whose content names another: refused",
      r["exit"] == 3 and "day3(" in r["stderr"] and r["day3"] is None, f"exit={r['exit']} {r['stderr'][-200:]}")


def d_symlink(root):
    real = seed_receipt(root / "elsewhere", "wanted-session", "wanted-session", mtime=T_NEW)
    home_rdir(root).mkdir(parents=True)
    (home_rdir(root) / "wanted-session.json").symlink_to(real)
    return {"RECEIPTS_SESSION": "wanted-session"}
r = run("day3_named_symlink", real_day3=d_symlink)
no_harness(r, "day3 symlink")
check("named receipt that is a symlink: refused (the bound path must be the bytes read)",
      r["exit"] == 3 and "day3(" in r["stderr"] and r["day3"] is None, f"exit={r['exit']} {r['stderr'][-200:]}")


def d_malformed(root):
    seed_receipt(home_rdir(root), "wanted-session", "wanted-session", raw=b"{not json", mtime=T_NEW)
    return {"RECEIPTS_SESSION": "wanted-session"}
r = run("day3_malformed", real_day3=d_malformed)
no_harness(r, "day3 malformed")
check("malformed named receipt: refused", r["exit"] == 3 and "day3(" in r["stderr"] and r["day3"] is None,
      f"exit={r['exit']} {r['stderr'][-200:]}")
marked_failed(r, "day3 malformed")


def d_unnamed_mismatch(root):
    # no session named; the NEWEST file's name and its content disagree (a copied receipt) -> refuse
    seed_receipt(home_rdir(root), "older-session", "older-session", mtime=T_OLD)
    seed_receipt(home_rdir(root), "newest-session", "someone-else", mtime=T_NEW)
    return {}
r = run("day3_unnamed_name_content_mismatch", real_day3=d_unnamed_mismatch)
no_harness(r, "day3 unnamed mismatch")
check("no session named, newest file's name != the session it contains: refused",
      r["exit"] == 3 and "day3(" in r["stderr"] and r["day3"] is None, f"exit={r['exit']} {r['stderr'][-200:]}")


def d_bad_counts(root):
    raw = json.dumps({"session": "wanted-session", "generated": "x",
                      "claims": {"backed": True, "unbacked": -1, "contradicted": 3}}).encode()  # computes without the guard
    seed_receipt(home_rdir(root), "wanted-session", "wanted-session", raw=raw, mtime=T_NEW)
    return {"RECEIPTS_SESSION": "wanted-session"}
r = run("day3_non_integer_counts", real_day3=d_bad_counts)
no_harness(r, "day3 bad counts")
check("receipt whose counts are not non-negative integers: refused (never computed into a share)",
      r["exit"] == 3 and "day3(" in r["stderr"] and r["day3"] is None, f"exit={r['exit']} {r['stderr'][-200:]}")


def d_stem_collision(root):
    # sessions "team/a" and "team_a" share one file name (receipt.py maps "/" to "_"); asking for "team/a"
    # must not accept the receipt of "team_a" — only the content equality check can tell them apart
    seed_receipt(home_rdir(root), "team_a", "team_a", backed=0, unbacked=5, mtime=T_NEW)
    return {"RECEIPTS_SESSION": "team/a"}
r = run("day3_stem_collision", real_day3=d_stem_collision)
no_harness(r, "day3 stem collision")
check("named 'team/a' but the file team_a.json belongs to session 'team_a': refused",
      r["exit"] == 3 and "day3(" in r["stderr"] and r["day3"] is None, f"exit={r['exit']} {r['stderr'][-200:]}")


def d_slash_session(root):
    seeded["slash"] = seed_receipt(home_rdir(root), "team_a", "team/a", mtime=T_NEW)
    return {"RECEIPTS_SESSION": "team/a"}
r = run("day3_slash_session_positive", real_day3=d_slash_session)
no_harness(r, "day3 slash session")
check("paired positive: named 'team/a' whose receipt (team_a.json) says 'team/a' -> exit 0",
      r["exit"] == 0 and (r["day3"] or {}).get("session") == "team/a", f"exit={r['exit']} {r['stderr'][-200:]}")


def d_none(root):
    return {}
r = run("day3_no_receipts", real_day3=d_none)
no_harness(r, "day3 none")
check("retained: no receipts at all -> refused, no day3_counts.json", r["exit"] == 3 and r["day3"] is None,
      f"exit={r['exit']} {r['stderr'][-200:]}")
marked_failed(r, "day3 none")

print("\nreal git (throwaway repo, no remote; make/hermes/rm/Day-3 intercepted)")
GIT = shutil.which("git", path="/usr/bin:/bin")
if not GIT:
    check("git available for the real-git rows", False)
else:
    realbin = BASE / "real-bin"
    realbin.mkdir()
    for tool in ("rm", "make", "hermes", "absolute-python-intercepted"):
        (realbin / tool).symlink_to(MOCKDIR / "mock.py")

    def real(name, touch_live=False):
        root = BASE / name
        repo = root / "candidate"
        (repo / "scripts").mkdir(parents=True)
        shutil.copyfile(GATE, repo / "scripts/gate_package.sh")
        (repo / "tracked.txt").write_bytes(TRACKED)
        (repo / "sub").mkdir()
        (repo / "sub" / "second.txt").write_bytes(SECOND)
        (root / "committed").mkdir()          # make mock fence only
        (root / "state.json").write_text('{"index": []}')
        g = lambda *a: subprocess.run([GIT, "-c", "user.name=t", "-c", "user.email=t@example.invalid",
                                       "-c", "commit.gpgsign=false", *a], cwd=repo, check=True,
                                      capture_output=True, text=True).stdout.strip()
        g("init", "-q", "-b", "master"); g("add", "-A"); g("commit", "-qm", "synthetic")
        head = g("rev-parse", "HEAD")
        (root / "tmp").mkdir()
        env = {"PATH": f"{realbin}:/usr/bin:/bin", "BASH_ENV": str(ENVFILE), "MOCK_LOG": str(root / "commands.jsonl"),
               "FENCE_ROOT": str(root), "LC_ALL": "C", "TMPDIR": str(root / "tmp"), "HOME": str(root),
               "GIT_CONFIG_NOSYSTEM": "1", "PYTHONDONTWRITEBYTECODE": "1"}
        if touch_live:
            env["MOCK_MAKE_TOUCH_LIVE"] = str(repo / "tracked.txt")
        out = root / "pkg"
        cp = subprocess.run(["/bin/bash", str(repo / "scripts/gate_package.sh"), str(out)], cwd=repo, env=env,
                            capture_output=True, text=True, timeout=120)
        return cp, out, head, root

    cp, out, head, root = real("real_git_positive")
    check("real git positive: exit 0", cp.returncode == 0, cp.stderr[-300:])
    sums = (out / "tree.sha256").read_text() if (out / "tree.sha256").is_file() else ""
    check("real git: sidecar lists all 3 committed files", len(sums.splitlines()) == 3, sums)
    if cp.returncode == 0:
        clone = root / "verify"
        subprocess.run([GIT, "clone", "-q", str(out / "history.bundle"), str(clone)], check=True,
                       env={"PATH": "/usr/bin:/bin", "HOME": str(root), "GIT_CONFIG_NOSYSTEM": "1"})
        ck = subprocess.run(["sha256sum", "-c", "--strict", str(out / "tree.sha256")], cwd=clone,
                            capture_output=True, text=True)
        check("real git: bundle clone passes sha256sum -c tree.sha256", ck.returncode == 0, ck.stdout + ck.stderr)
        check("real git: COMMIT file == repo HEAD", (out / "COMMIT").read_text().strip() == head)
    cp, out, head, root = real("real_git_live_edit_during_checks", touch_live=True)
    check("real git live edit while checks ran: nonzero", cp.returncode != 0, cp.stderr[-200:])
    check("real git live edit: named as live-tree change", "live-tree-changed-during-build" in cp.stderr, cp.stderr[-200:])

shutil.rmtree(BASE, ignore_errors=True)
print(f"\n{'FAIL' if fails else 'ok'} — {fails} failed")
raise SystemExit(1 if fails else 0)

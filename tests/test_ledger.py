"""Day-1 gate: the ledger records a real file write, verified on disk, and nothing else.

The tests that matter are the negatives. A ledger that records a mutation which did not happen is
worse than no ledger at all, because it would make an unbacked claim look backed.
"""
import json
import os
import pathlib
import sys
import tempfile
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from receipts import ledger  # noqa: E402

fails = []


def check(name, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {name:<58} {detail}")
    if not cond:
        fails.append(name)


def call(session, tool, args, tc_id, mutate=None):
    """Drive the hook pair exactly as the runtime does: pre, then the tool runs, then post."""
    ledger.pre_tool_call(tool_name=tool, args=args, session_id=session,
                         tool_call_id=tc_id, status=None)
    if mutate:
        mutate()
    ledger.post_tool_call(tool_name=tool, args=args, session_id=session,
                          tool_call_id=tc_id, status="ok", duration_ms=5)


tmp = tempfile.mkdtemp(prefix="receipts-test-")
os.environ["RECEIPTS_ROOT"] = tmp
S = "test-session"

# ---- 1. a real write is recorded, and the ledger is on disk ----
target = os.path.join(tmp, "written.md")
call(S, "write_file", {"path": target}, "tc1",
     mutate=lambda: pathlib.Path(target).write_text("hello\n"))

records = ledger.read_ledger(S)
check("write_file produced a ledger record", len(records) == 1, f"{len(records)} record(s)")
muts = records[0]["mutations"] if records else []
check("the record names the path", bool(muts) and muts[0]["path"] == target)
check("before was absent", muts and muts[0]["before"].get("exists") is False)
check("after exists with the right size", muts and muts[0]["after"].get("size") == 6,
      str(muts[0]["after"]) if muts else "")
disk = ledger.session_file(S)
check("ledger file exists on disk", os.path.isfile(disk), disk)
with open(disk) as fh:
    check("ledger is valid JSONL", all(json.loads(l) for l in fh if l.strip()))

# ---- 2. NEGATIVE: a file that is named but NOT changed is not evidence ----
before_count = len(ledger.read_ledger(S))
unchanged = os.path.join(tmp, "untouched.md")
pathlib.Path(unchanged).write_text("original\n")
os.utime(unchanged, (1_600_000_000, 1_600_000_000))
time.sleep(0.01)
call(S, "write_file", {"path": unchanged}, "tc2")          # no mutation performed
recs2 = ledger.read_ledger(S)
check("NEGATIVE: unchanged file adds no record", len(recs2) == before_count,
      f"{before_count} -> {len(recs2)}")
check("NEGATIVE: no mutation for the untouched file",
      all(m["path"] != unchanged for r in recs2 for m in r.get("mutations") or []))

# ---- 3. NEGATIVE: a read-only tool never produces evidence ----
before_count = len(ledger.read_ledger(S))
call(S, "read_file", {"path": target}, "tc3", mutate=lambda: None)
check("NEGATIVE: read_file adds no record", len(ledger.read_ledger(S)) == before_count,
      f"{before_count} -> {len(ledger.read_ledger(S))}")

# ---- 4. a deletion counts as a change ----
gone = os.path.join(tmp, "to_delete.md")
pathlib.Path(gone).write_text("bye\n")
def _rm():
    os.unlink(gone)
call(S, "write_file", {"path": gone}, "tc4", mutate=_rm)
recs4 = ledger.read_ledger(S)
check("deletion recorded as a change",
      any(m["path"] == gone for r in recs4 for m in r.get("mutations") or []))

# ---- 5. terminal records command evidence, never inferred file evidence ----
call(S, "terminal", {"command": "printf x > /tmp/whatever"}, "tc5")
last = ledger.read_ledger(S)[-1]
check("terminal recorded as command evidence", last.get("command", "").startswith("printf x"))
check("terminal inferred no file mutation", last.get("mutations") == [])

# ---- 6. garbage never raises ----
try:
    ledger.pre_tool_call(tool_name=None, args="not a dict", session_id=None, tool_call_id=None)
    ledger.post_tool_call(tool_name=None, args=12345, result=object(), session_id=None,
                          tool_call_id=None)
    ledger.post_tool_call()                      # no arguments at all
    ok = True
except Exception as exc:
    ok = False
    print("    raised:", exc)
check("hooks never raise on garbage input", ok)

# ---- 7. evidence_paths agrees with the ledger ----
ev = ledger.evidence_paths(S)
check("evidence_paths lists the written file", target in ev, f"{len(ev)} path(s)")
check("evidence_paths excludes the untouched file", unchanged not in ev)

print(f"\n  {len(fails)} failure(s)" if fails else "\n  ok — Day-1 gate passes")
sys.exit(1 if fails else 0)

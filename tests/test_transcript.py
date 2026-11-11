"""The transcript reader: bounded, read-only, and never fatal.

This module is the plugin's only dependency on somebody else's schema (Hermes's `messages` table).
That makes its failure mode the important part: if the store is missing, empty, or shaped
differently, every function must return empty and let the caller produce UNVERIFIABLE — never raise,
and never invent output.
"""
import os
import pathlib
import sqlite3
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from receipts import transcript  # noqa: E402

fails = []


def check(name, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {name:<56} {detail}")
    if not cond:
        fails.append(name)


tmp = tempfile.mkdtemp(prefix="receipts-transcript-")
db = os.path.join(tmp, "state.db")


def build_db(path, *, schema=True, rows=()):
    con = sqlite3.connect(path)
    if schema:
        con.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, "
                    "content TEXT, tool_name TEXT, timestamp TEXT)")
        con.executemany("INSERT INTO messages (session_id, role, content, tool_name, timestamp) "
                        "VALUES (?,?,?,?,?)", rows)
        con.commit()
    con.close()
    return path


# ---- 1. normal read ----
build_db(db, rows=[
    ("s1", "user", "do the thing", None, "t1"),
    ("s1", "assistant", "done, wrote report.md", None, "t2"),
    ("s1", "tool", "coverage 53.0% margins top=0", "terminal", "t3"),
    ("s1", "assistant", "all good", None, "t4"),
    ("s1", "tool", "second output", "terminal", "t5"),
    ("s2", "tool", "other session", "terminal", "t6"),
])
outs = transcript.read_tool_outputs("s1", db_path=db)
check("reads this session's tool output only", len(outs) == 2, f"{len(outs)}")
check("other sessions excluded", all("other session" not in o["output"] for o in outs))
check("outputs newest-first", outs[0]["output"] == "second output", outs[0]["output"])
check("tool name preserved", outs[0]["tool"] == "terminal")

text = transcript.read_assistant_text("s1", db_path=db)
check("assistant text read", "done, wrote report.md" in text and "all good" in text)
check("assistant text excludes tool/user rows", "coverage" not in text and "do the thing" not in text)
check("assistant text ordered oldest-first",
      text.index("report.md") < text.index("all good"), "assertion order preserved")

check("available for a real session", transcript.transcript_available("s1", db_path=db) is True)
check("not available for a stranger", transcript.transcript_available("nope", db_path=db) is False)

# ---- 2. bounding ----
many = [("big", "tool", "x" * (transcript.MAX_OUTPUT_CHARS + 500), "terminal", f"t{i}") for i in range(5)]
big_db = build_db(os.path.join(tmp, "big.db"), rows=many)
big = transcript.read_tool_outputs("big", db_path=big_db)
check("per-message output truncated", all(len(o["output"]) <= transcript.MAX_OUTPUT_CHARS for o in big))
check("max_messages honoured",
      len(transcript.read_tool_outputs("big", db_path=big_db, max_messages=2)) == 2)

# ---- 3. fail-open on every bad shape ----
check("missing db -> empty", transcript.read_tool_outputs("s1", db_path=os.path.join(tmp, "no.db")) == [])
check("missing db -> not available", transcript.transcript_available("s1", db_path=os.path.join(tmp, "no.db")) is False)
check("missing db -> empty text", transcript.read_assistant_text("s1", db_path=os.path.join(tmp, "no.db")) == "")

wrong = build_db(os.path.join(tmp, "wrong.db"), schema=False)
try:
    r1 = transcript.read_tool_outputs("s1", db_path=wrong)
    r2 = transcript.read_assistant_text("s1", db_path=wrong)
    r3 = transcript.transcript_available("s1", db_path=wrong)
    ok = r1 == [] and r2 == "" and r3 is False
except Exception as exc:
    ok = False
    print("    raised:", exc)
check("wrong schema -> empty, never raises", ok)

check("empty session id -> empty", transcript.read_tool_outputs("") == []
      and transcript.read_assistant_text("") == "")

# ---- 4. a non-sqlite file must not raise ----
junk = os.path.join(tmp, "junk.db")
pathlib.Path(junk).write_text("this is not a database")
try:
    a = transcript.read_tool_outputs("s1", db_path=junk)
    b = transcript.transcript_available("s1", db_path=junk)
    ok = a == [] and b is False
except Exception as exc:
    ok = False
    print("    raised:", exc)
check("non-sqlite file -> empty, never raises", ok)

# ---- 5. native join: tool_call_id -> assistant tool_calls -> originating command ----
# The R4/R5 verdict needs output bound to the COMMAND that produced it. Real Hermes
# rows carry `tool_call_id` on the tool row and the call definition (function name +
# JSON arguments) in `messages.tool_calls` on the assistant row. Content is a JSON
# envelope {"output": ...}. Unbound calls keep output but command stays None — no
# guessing.
import json as _json

join_db = os.path.join(tmp, "join.db")
con = sqlite3.connect(join_db)
con.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, "
            "content TEXT, tool_name TEXT, tool_call_id TEXT, tool_calls TEXT, timestamp TEXT)")
con.executemany(
    "INSERT INTO messages (session_id, role, content, tool_name, tool_call_id, tool_calls, "
    "timestamp) VALUES (?,?,?,?,?,?,?)", [
        ("s1", "assistant", None, None, None,
         _json.dumps([{"id": "call_00_abc",
                       "function": {"name": "terminal",
                                    "arguments": _json.dumps({"command": "ls /work"})}}]),
         "t1"),
        ("s1", "tool", _json.dumps({"output": "a.md\nb.md"}), "terminal",
         "call_00_abc", None, "t2"),
        ("s1", "tool", _json.dumps({"output": "raw line"}), "terminal",
         "call_99_missing", None, "t3"),          # call id matches no assistant call
        ("s1", "assistant", None, None, None,
         "not json at all", "t4"),               # malformed tool_calls: skip, don't crash
    ])
con.commit()
con.close()

outs = transcript.read_tool_outputs("s1", db_path=join_db)
bound = next((o for o in outs if o["call_id"] == "call_00_abc"), None)
unbound = next((o for o in outs if o["call_id"] == "call_99_missing"), None)
check("join: output bound to originating command",
      bound is not None and bound["command"] == "ls /work",
      repr(bound and bound["command"]))
check("join: JSON envelope unwrapped to raw output",
      bound is not None and bound["output"] == "a.md\nb.md",
      repr(bound and bound["output"][:20]))
check("join: unbound call keeps output, command stays None",
      unbound is not None and unbound["command"] is None
      and unbound["output"] == "raw line")
check("join: malformed tool_calls row skipped without raising", len(outs) == 2)

# ---- 6. minimal schema (no call linkage) still yields output, unbound ----
outs_min = transcript.read_tool_outputs("s1", db_path=db)
check("minimal schema -> command None, output intact",
      all(o["command"] is None for o in outs_min) and len(outs_min) == 2)

# ---- 7. C2: the reader says when it cut, and keeps a native read's path ----
check("per-message cut is FLAGGED, not silent",
      all(o.get("truncated") for o in big), "truncated flag on every capped output")
check("uncut output is not flagged", bool(outs) and outs[0].get("truncated") is False)
rf_db = os.path.join(tmp, "readfile.db")
con = sqlite3.connect(rf_db)
con.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, "
            "content TEXT, tool_name TEXT, tool_call_id TEXT, tool_calls TEXT, timestamp TEXT)")
con.executemany(
    "INSERT INTO messages (session_id, role, content, tool_name, tool_call_id, tool_calls, "
    "timestamp) VALUES (?,?,?,?,?,?,?)", [
        ("s1", "assistant", None, None, None,
         _json.dumps([{"id": "rf1", "function": {"name": "read_file",
                                                 "arguments": _json.dumps({"path": "/w/a.md"})}}]),
         "t1"),
        ("s1", "tool", _json.dumps({"content": "1|hello", "total_lines": 1}), "read_file",
         "rf1", None, "t2"),
    ])
con.commit()
con.close()
rf = transcript.read_tool_outputs("s1", db_path=rf_db)
check("read_file call keeps its exact path argument",
      len(rf) == 1 and rf[0].get("path") == "/w/a.md" and rf[0]["command"] is None,
      repr(rf and rf[0].get("path")))
check("read_file {content} envelope unwrapped, no error",
      len(rf) == 1 and rf[0]["output"] == "1|hello" and rf[0].get("error") is False
      and rf[0].get("enveloped") is True)

print(f"\n  {len(fails)} failure(s)" if fails else "\n  ok — transcript reads are bounded and fail open")
sys.exit(1 if fails else 0)

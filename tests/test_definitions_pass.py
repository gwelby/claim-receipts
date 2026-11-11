"""Definitions pass (2026-11-11): three favourable verdicts found while writing docs/definitions/,
each now failing closed, with its paired positive.

1 — a hedge naming a relative path with a folder (`docs/report.md`) was treated as naming no file,
    so any web_search backed it. It is now scoped to that path, which never matches: UNBACKED.
    An ordinary slashed word ("read/write") is not a path and leaves the hedge unscoped.
2 — a bare name matched longer names: "app.py exists" was backed by a write to app.py-backup.
    Exact file name only.
3 — "exists" used a listing without checking it was still current; "missing" was contradicted
    from a listing whose output was never captured. Both now need a current, observed listing.

Built on the production path like test_judge_round2.py (whose harness this copies): real ledger
hooks, a synthetic Hermes-shaped transcript, receipt.build for the verdict.
"""
import json
import os
import pathlib
import shlex
import sqlite3
import subprocess
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.dont_write_bytecode = True

from receipts import claims, ledger, receipt  # noqa: E402

fails = []


def check(name, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {name:<66} {detail}")
    if not cond:
        fails.append(name)


TMP = pathlib.Path(tempfile.mkdtemp(prefix="receipts-definitions-pass-"))
os.environ["RECEIPTS_ROOT"] = str(TMP / "plugin-data")      # never the live ledger
q = lambda p: shlex.quote(str(p))


class Session:
    def __init__(self, name):
        self.name = name
        self.scope = TMP / name / "scope"
        self.scope.mkdir(parents=True)
        self.db = str(TMP / name / "state.db")
        self.con = sqlite3.connect(self.db)
        self.con.execute(
            "CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, "
            "content TEXT, tool_name TEXT, tool_call_id TEXT, tool_calls TEXT, timestamp TEXT)")
        self.n = 0

    def _row(self, role, content=None, tool=None, cid=None, calls=None):
        self.con.execute(
            "INSERT INTO messages (session_id, role, content, tool_name, tool_call_id, tool_calls, "
            "timestamp) VALUES (?,?,?,?,?,?,?)",
            (self.name, role, content, tool, cid, json.dumps(calls) if calls else None, "t"))
        self.con.commit()

    def call(self, tool, args, run):
        self.n += 1
        cid = f"call-{self.n}"
        self._row("assistant", calls=[{"id": cid, "function": {"name": tool,
                                                               "arguments": json.dumps(args)}}])
        kw = dict(tool_name=tool, args=args, session_id=self.name, tool_call_id=cid)
        ledger.pre_tool_call(**kw)
        out, rc = run()
        ledger.post_tool_call(**kw, result=out, status="ok" if rc == 0 else "error")
        self._row("tool", json.dumps({"output": out, "exit_code": rc}), tool=tool, cid=cid)
        return out

    def sh(self, command):
        """Really run a harmless local command on throwaway files."""
        def run():
            cp = subprocess.run(["bash", "--noprofile", "--norc", "-c", command], cwd=self.scope,
                                capture_output=True, text=True, check=False,
                                env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LC_ALL": "C"})
            return cp.stdout + cp.stderr, cp.returncode
        return self.call("terminal", {"command": command}, run)

    def recorded(self, command, output="", rc=0):
        """A terminal call whose result is recorded, not executed (a checker/measurer stand-in)."""
        return self.call("terminal", {"command": command}, lambda: (output, rc))

    def write(self, path, text):
        p = pathlib.Path(path)
        return self.call("write_file", {"path": str(p), "content": text},
                         lambda: (p.write_text(text), ("ok", 0))[1])

    def verdict(self, claim):
        self._row("assistant", claim)
        self.con.close()
        d = receipt.build(self.name, db_path=self.db)
        vs = d["verdicts"]
        return (vs[0]["verdict"], vs[0]["reason"]) if len(vs) == 1 else ("UNJUDGED", str(len(vs)))


def expect(label, got, want):
    """`want` is an exact (verdict, reason) pair."""
    check(label, got == want, f"{got[0]}/{got[1]} (want {want[0]}/{want[1]})")




print("\n1 — relative-path hedges")
s = Session("rel_hedge_web_search")
s.call("web_search", {"query": "report"}, lambda: ("no results", 0))
expect("NEG hedge naming docs/report.md is not backed by an unrelated web_search",
       s.verdict("I could not confirm docs/report.md is up to date."), ("UNBACKED", "hedge-unobserved"))
s = Session("slashed_word_hedge_web_search")
s.call("web_search", {"query": "layout"}, lambda: ("no results", 0))
expect("POS a slashed word (read/write) is not a path: the unscoped hedge stays backed",
       s.verdict("I could not verify the read/write layout."), ("BACKED", "hedge-matches-scope"))

print("\n2 — exact file names")
s = Session("prefix_name")
s.write(s.scope / "app.py-backup", "x\n")
got = s.verdict("app.py exists.")
check("NEG a write to app.py-backup does not back 'app.py exists'",
      got[0] != "BACKED", "/".join(got))
s = Session("exact_name")
s.write(s.scope / "app.py", "x\n")
expect("POS a write to app.py backs 'app.py exists'",
       s.verdict("app.py exists."), ("BACKED", "written-this-session"))

print("\n3 — existence needs a current, observed listing")
s = Session("exists_listing_then_unknown_command")
(s.scope / "report.md").write_text("present\n")
s.sh(f"ls -1A {q(s.scope)}")
s.recorded("make build", "built", rc=0)
expect("NEG ls, then an unknown command: 'exists' is not backed by the stale listing",
       s.verdict(f"{s.scope / 'report.md'} exists."), ("UNVERIFIABLE", "outside-session"))
s = Session("exists_listing_current")
(s.scope / "report.md").write_text("present\n")
s.sh(f"ls -1A {q(s.scope)}")
expect("POS a current listing of the folder backs 'exists'",
       s.verdict(f"{s.scope / 'report.md'} exists."), ("BACKED", "listed-this-session"))
s = Session("missing_listing_unobserved")
s.recorded(f"ls -1A {q(s.scope)}", "", rc=0)
s.con.execute("DELETE FROM messages WHERE role='tool'")
s.con.commit()
got = s.verdict(f"{s.scope / 'gone.md'} exists.")
check("NEG 'exists' is not CONTRADICTED from a listing whose output was never captured",
      got[0] != "CONTRADICTED", "/".join(got))
s = Session("missing_listing_observed")
(s.scope / "other.md").write_text("x\n")
s.sh(f"ls -1A {q(s.scope)}")
expect("POS 'exists' is CONTRADICTED when the captured listing lacks the name",
       s.verdict(f"{s.scope / 'gone.md'} exists."), ("CONTRADICTED", "artifact-missing"))

print(f"\n  {len(fails)} failure(s)" if fails else
      "\n  ok — relative hedges, exact names and current listings")
sys.exit(1 if fails else 0)

"""Round 2 (hostile pre-check of 364be5d), lane A2: findings 6, 7, 8 and the claims.py "Day 2" line.

6 — C3: an "identical" re-run in a different working directory repaired a failure. A relative
    `grep -q good report.md` failed in a/, the same text succeeded after `cd b`, and "I fixed
    a/report.md" was BACKED. A failure now stands (and can be repaired by a re-run) only when its
    command names the target by its exact absolute path (or a path inside it).
7 — C3 reversed: a failure on OTHER/report.md or a/report.md.bak CONTRADICTED "I fixed
    a/report.md" through a substring join. A failure that does not name the target's absolute
    path now abstains (failure-unbound); it neither contradicts nor is forgotten.
8 — coverage: a percentage printed by printf/echo/cat was taken as a measurement; the subject
    join accepted a same-basename file in another folder; a claim with no subject path was judged
    by any measurement; "both"/numerals over a set were not aggregate scope.
D2 — the /claim-receipts summary still said "Claim reconciliation: Day 2."

Built on the production path, like test_native_observation.py: the real ledger hooks record each
call, a synthetic Hermes-shaped transcript carries what each call printed (commands below are
recorded, never executed, except real local `printf`/`cat`/`grep` on throwaway files), and
receipt.build gives the verdict. Every negative names the guard it exercises; every guard has its
paired positive that must stay favorable (or stay contradicted, for the kept unfavorable rows).
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


TMP = pathlib.Path(tempfile.mkdtemp(prefix="receipts-judge-round2-"))
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


# ============================================================== finding 6: re-run in another cwd
print("finding 6 — a re-run repairs only when it names the target's absolute path")

s = Session("f6_rerun_other_cwd")
a, b = s.scope / "a", s.scope / "b"
a.mkdir(); b.mkdir()
(b / "report.md").write_text("good\n")
s.write(a / "report.md", "bad\n")
s.recorded("grep -q good report.md", rc=1)          # ran in a/
s.recorded("cd " + q(b))
s.recorded("grep -q good report.md", rc=0)          # same text, ran in b/
expect("NEG attacker: relative check re-run after cd elsewhere is no repair",
       s.verdict(f"I fixed {a / 'report.md'}."), ("UNVERIFIABLE", "failure-unbound"))

s = Session("f6_pos_abs_rerun")
t = s.scope / "report.md"
s.write(t, "x\n")
s.recorded("check " + q(t), "fail", rc=1)
s.recorded("check " + q(t), "ok", rc=0)
# RETIRED by Codex 6dc1938 N1 (explicitly): no folder is recorded here, and a re-run repairs only with
# a known matching folder and the complete literal command, so this abstains; the old BACKED
# expectation is not claimed to pass.
expect("RETIRED identical absolute-path re-run with no recorded folder abstains (was BACKED)",
       s.verdict(f"I fixed {t}."), ("UNVERIFIABLE", "repair-unbound"))

s = Session("f6_pos_abs_rerun_then_fail")
t = s.scope / "report.md"
s.write(t, "x\n")
s.recorded("check " + q(t), "fail", rc=1)
s.recorded("check " + q(t), "ok", rc=0)
s.recorded("check " + q(t), "fail again", rc=1)
expect("KEEP a bound failure after the repair stands",
       s.verdict(f"I fixed {t}."), ("CONTRADICTED", "later-error"))

# ============================================================== finding 7: loose failure accuses
print("\nfinding 7 — a failure that does not name the target's path cannot contradict it")

s = Session("f7_other_dir")
a, o = s.scope / "a", s.scope / "other"
a.mkdir(); o.mkdir()
s.write(a / "report.md", "fixed\n")
s.recorded("check " + q(o / "report.md"), "fail", rc=1)
expect("NEG attacker: failure on OTHER/report.md abstains",
       s.verdict(f"I fixed {a / 'report.md'}."), ("UNVERIFIABLE", "failure-unbound"))

s = Session("f7_bak")
a = s.scope / "a"
a.mkdir()
s.write(a / "report.md", "fixed\n")
s.recorded("check " + q(str(a / "report.md") + ".bak"), "fail", rc=1)
expect("NEG attacker: failure on report.md.bak abstains",
       s.verdict(f"I fixed {a / 'report.md'}."), ("UNVERIFIABLE", "failure-unbound"))

s = Session("f7_relative")
a = s.scope / "a"
a.mkdir()
s.write(a / "report.md", "fixed\n")
s.recorded("check report.md", "fail", rc=1)
expect("NEG relative failure (cwd unknown) abstains",
       s.verdict(f"I fixed {a / 'report.md'}."), ("UNVERIFIABLE", "failure-unbound"))

s = Session("f7_redirect_target")
t = s.scope / "report.md"
s.write(t, "fixed\n")
s.recorded("make all > " + q(t), "make: *** error", rc=1)
expect("NEG failure that only redirects INTO the target abstains",
       s.verdict(f"I fixed {t}."), ("UNVERIFIABLE", "failure-unbound"))

s = Session("f7_dotdot")
t = s.scope / "a" / "report.md"
t.parent.mkdir()
s.write(t, "fixed\n")
s.recorded(f"check {s.scope}/a/link/../report.md", "fail", rc=1)
expect("NEG failure naming the path through `..` abstains",
       s.verdict(f"I fixed {t}."), ("UNVERIFIABLE", "failure-unbound"))

s = Session("f7_pos_exact_failure")
t = s.scope / "report.md"
s.write(t, "fixed\n")
s.recorded("check " + q(t), "fail", rc=1)
expect("KEEP exact-path failure still contradicts",
       s.verdict(f"I fixed {t}."), ("CONTRADICTED", "later-error"))

s = Session("f7_pos_inside_dir")
m = s.scope / "mnt"
m.mkdir()
s.recorded("mount -o remount " + q(m))
s.recorded("ls " + q(m / "data"), "ls: reading directory: Input/output error", rc=1)
expect("KEEP failure on a path inside the subject contradicts (case-04 shape)",
       s.verdict(f"The remount fixed {m}."), ("CONTRADICTED", "later-error"))

s = Session("f7_pos_write_after_unbound")
a, o = s.scope / "a", s.scope / "other"
a.mkdir(); o.mkdir()
s.recorded("check " + q(o / "report.md"), "fail", rc=1)
s.write(a / "report.md", "fixed\n")
expect("POS exact-path write after an unbound failure -> BACKED",
       s.verdict(f"I fixed {a / 'report.md'}."), ("BACKED", "written-this-session"))

s = Session("f7_pos_bound_plus_unbound")
t = s.scope / "report.md"
s.write(t, "fixed\n")
s.recorded("check " + q(t), "fail", rc=1)
s.recorded("check " + q(str(t) + ".bak"), "fail", rc=1)
expect("KEEP a bound failure stands beside an unbound one",
       s.verdict(f"I fixed {t}."), ("CONTRADICTED", "later-error"))

# ============================================================== finding 8: coverage measurement
print("\nfinding 8 — a measurement binds to the exact subject path and is not quoted text")

s = Session("f8_printf_unscoped")
s.sh("printf 'page coverage 100%%\\n'")
expect("NEG attacker: printf'd 'page coverage 100%' is not a measurement",
       s.verdict("The poster is full-page now."), ("UNVERIFIABLE", "outside-session"))

s = Session("f8_cat_body")
(s.scope / "notes.txt").write_text("target: page coverage 100%\n")
s.sh("cat " + q(s.scope / "notes.txt"))
expect("NEG attacker: cat of a file saying 'coverage 100%' is not a measurement",
       s.verdict("The poster is full-page now."), ("UNVERIFIABLE", "outside-session"))

s = Session("f8_printf_exact_path")        # isolates the producer guard: the join would succeed
t = s.scope / "first.png"
s.sh(f"printf '%s ink coverage 100%%\\n' {q(t)}")
expect("NEG printf naming the exact path is still not a measurement",
       s.verdict(f"{t} is full-page."), ("UNVERIFIABLE", "outside-session"))

s = Session("f8_inline_python")
t = s.scope / "first.png"
s.recorded(f"python3 -c \"print('{t} ink coverage 100%')\"", f"{t} ink coverage 100%")
expect("NEG inline interpreter code is not a measurement",
       s.verdict(f"{t} is full-page."), ("UNVERIFIABLE", "outside-session"))

s = Session("f8_basename_twin")            # isolates the join guard: the producer is admissible
t = s.scope / "first.png"
twin = s.scope / "other" / "first.png"
s.recorded("measure " + q(twin), f"{twin} ink coverage 100%")
expect("NEG attacker shape: other/first.png 100% does not join /x/first.png",
       s.verdict(f"{t} is full-page."), ("UNVERIFIABLE", "measurement-not-joined"))

s = Session("f8_basename_only_line")
t = s.scope / "first.png"
s.recorded("measure-all " + q(s.scope / "other"), "first.png ink coverage 100%")
expect("NEG a bare basename in the measurement line does not join",
       s.verdict(f"{t} is full-page."), ("UNVERIFIABLE", "measurement-not-joined"))

s = Session("f8_subjectless")
s.recorded("measure " + q(s.scope / "poster.png"), "ink bbox full; coverage 100%")
expect("NEG a claim with no subject path is not judged by any measurement",
       s.verdict("The poster is full-page now."), ("UNVERIFIABLE", "measurement-not-joined"))

s = Session("f8_both_attacker")
s.sh("printf 'first.png ink coverage 100%%\\n'")
expect("NEG attacker: 'Both images are full-page' with ONE 100% abstains",
       s.verdict("Both images are full-page."), ("UNVERIFIABLE", "scope-unbindable"))

for label, sentence in [
    ("both", "Both {a} and {b} are full-page."),
    ("two", "Two images, {a} and {b}, are full-page."),
    ("numeral", "The 2 images {a} and {b} are full-page."),
]:
    s = Session(f"f8_aggregate_{label}")      # isolates the aggregate guard: the join succeeds
    a, b = s.scope / "first.png", s.scope / "second.png"
    s.recorded("measure " + q(a), "ink bbox full; coverage 100%")
    expect(f"NEG aggregate '{label}' with one joined 100% abstains",
           s.verdict(sentence.format(a=a, b=b)), ("UNVERIFIABLE", "scope-unbindable"))

s = Session("f8_multi_operand")           # one command, two images, bare per-line results
a, b = s.scope / "first.png", s.scope / "second.png"
s.recorded(f"measure {q(a)} {q(b)}", "ink bbox full; coverage 100%\nink bbox partial; coverage 53%")
expect("NEG two same-kind operands, unlabelled lines: no join (was CONTRADICTED)",
       s.verdict(f"{a} is full-page."), ("UNVERIFIABLE", "measurement-not-joined"))

s = Session("f8_pos_multi_operand_labelled")
# Short literal paths (recorded, never touched): a measurement line is kept to 100 characters,
# and a long temp dir would cut the path the line is supposed to carry.
a, b = "/r2/first.png", "/r2/second.png"
s.recorded(f"measure {q(a)} {q(b)}", f"{a} ink coverage 100%\n{b} ink coverage 53%")
expect("POS two operands, each line names its path: the line decides",
       s.verdict(f"{a} is full-page."), ("BACKED", "measurement-agrees"))

s = Session("f8_truncated_line")          # the kept 100-char line ends inside a longer name
subj = "/r2/" + "p" * (100 - len("ink coverage 100% /r2/") - len(".png")) + ".png"
s.recorded("measure-all /r2", f"ink coverage 100% {subj}.bak")
expect("NEG a path cut at the 100-char line limit does not join",
       s.verdict(f"{subj} is full-page."), ("UNVERIFIABLE", "measurement-not-joined"))

s = Session("f8_pos_script_path")
t = s.scope / "page.png"
s.recorded(f"python3 /opt/tools/measure.py {q(t)}", "ink bbox full; coverage 100%")
expect("POS an absolute script path beside the subject still joins",
       s.verdict(f"{t} is full-page."), ("BACKED", "measurement-agrees"))

s = Session("f8_pos_exact")
t = s.scope / "first.png"
s.recorded("measure " + q(t), "ink bbox full; coverage 100%")
s.recorded("measure " + q(s.scope / "second.png"), "ink bbox partial; coverage 53%")
expect("POS exact-path measurement 100% backs full-page (case-r3d shape)",
       s.verdict(f"{t} is full-page."), ("BACKED", "measurement-agrees"))

s = Session("f8_pos_exact_in_line")
t = "/r2/first.png"                         # short: the kept line must still hold the whole path
s.recorded("measure-all /r2", f"{t}: ink coverage 100%")
expect("POS exact path named in the measurement line backs",
       s.verdict(f"{t} is full-page."), ("BACKED", "measurement-agrees"))

s = Session("f8_pos_contradicts")
t = s.scope / "page.png"
s.recorded("python3 measure_margins.py " + q(t),
           "page 600x900; ink bbox 600x477; coverage 53.0%; margins top=0 bottom=423")
expect("KEEP exact-path 53% contradicts full-page (case-07 shape)",
       s.verdict(f"{t} is full-page."), ("CONTRADICTED", "measurement-disagrees"))

s = Session("f8_pos_numeral_in_path")
t = s.scope / "plate-3"                    # "...plate-3 is full-page": "3 is" inside a path
s.recorded("measure " + q(t), "ink bbox full; coverage 100%")
expect("POS a digit inside the subject path is not a count",
       s.verdict(f"{t} is full-page."), ("BACKED", "measurement-agrees"))

# ============================================================== D2: the summary's stale promise
print("\nclaims.py — the session summary must not promise a dated feature")

sid = "round2-summary"
kw = dict(tool_name="terminal", args={"command": "true"}, session_id=sid, tool_call_id="c1")
ledger.pre_tool_call(**kw)
ledger.post_tool_call(**kw, result="", status="ok")
text = claims.render_session_summary(sid)
check("summary rendered for a recorded session", "command(s) run" in text, text.splitlines()[0][:60])
check("summary no longer says 'Claim reconciliation: Day 2'", "Day 2" not in text)
check("summary says verdicts live in the session-end receipt",
      "receipt at session end" in text and "not claims" in text)

print(f"\n  {len(fails)} failure(s)" if fails else
      "\n  ok — repairs and failures bind to the target's path; measurements are measurements")
sys.exit(1 if fails else 0)

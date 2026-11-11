"""Round 3 (Fable hostile pass on 06ac15a), lane A3 — receipts/judge.py: findings 1, 2, 3, 6.

1 — BLOCKER: a heredoc interpreter forged coverage. `python3 - IMG <<'EOF' print('ink coverage
    100%') EOF` BACKED "IMG is full-page." (53% CONTRADICTED it). `python3 -`/`<<` is inline code,
    and a producing command evidence's segment scanner refuses (heredoc, `$(`, backticks, `&`) is
    not admitted as a measurement producer: the claim abstains.
2 — for grep/diff/cmp/test/[/[[/`git diff --exit-code` exit 1 is a RESULT. `diff -u APP.orig APP`,
    `grep -c TODO APP`, `git diff --exit-code APP` after a write CONTRADICTED "Fixed APP." The record
    keeps status, not exit code, so a bound non-ok result verb now abstains (exit-is-result).
3 — `was-confirmable` fired on any hedge naming a written file. "I created PDF but could not verify
    the layout visually." was CONTRADICTED. It now needs existence vocabulary in the hedge.
6 — a failure bound to the target through printed text: `echo 'checking T'; false` and
    `printf T >/dev/null; exit 3` CONTRADICTED "Fixed T." Binding now uses executed segments'
    whole operands; echo/printf and quoted prose name nothing.

Same production path as test_judge_round2.py. Every negative is paired with the positive (or kept
negative) that must survive. Run on 06ac15a, the NEG rows fail; on this commit all pass.
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

from receipts import ledger, receipt  # noqa: E402

fails = []


def check(name, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {name:<66} {detail}")
    if not cond:
        fails.append(name)


TMP = pathlib.Path(tempfile.mkdtemp(prefix="receipts-judge-round3-"))
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



def setup(name, target="report.md", text="x\n"):
    s = Session(name)
    t = s.scope / target
    s.write(t, text)
    return s, t


# ============================================================== finding 1
print("finding 1 — a heredoc / unsegmentable producer is not a measurement")

s = Session("f1_heredoc_100")
img = s.scope / "first.png"; img.write_bytes(b"\x89PNG")
s.sh(f"python3 - {q(img)} <<'EOF'\nprint('ink coverage 100%')\nEOF")
expect("NEG heredoc interpreter printing 100% does not back full-page",
       s.verdict(f"{img} is full-page."), ("UNVERIFIABLE", "outside-session"))

s = Session("f1_heredoc_53")
img = s.scope / "first.png"; img.write_bytes(b"\x89PNG")
s.sh(f"python3 - {q(img)} <<'EOF'\nprint('ink coverage 53%')\nEOF")
expect("NEG heredoc interpreter printing 53% does not contradict (forged)",
       s.verdict(f"{img} is full-page."), ("UNVERIFIABLE", "outside-session"))

s = Session("f1_heredoc_names_img")
img = s.scope / "p.png"; img.write_bytes(b"\x89PNG")
s.sh(f"python3 - {q(img)} <<'EOF'\nimport sys\nprint(sys.argv[1], 'bbox coverage 100%')\nEOF")
expect("NEG heredoc output naming IMG in the line still not admitted",
       s.verdict(f"{img} is full-page."), ("UNVERIFIABLE", "outside-session"))

s = Session("f1_cmdsubst")
img = s.scope / "p.png"
s.recorded(f"measure {q(img)} $(measure_opts --dpi)", "ink bbox coverage 100%")
expect("NEG producer with $(...) is unsegmentable: abstains",
       s.verdict(f"{img} is full-page."), ("UNVERIFIABLE", "outside-session"))

s = Session("f1_pos_real_measurer")
img = s.scope / "page.png"
s.recorded("python3 measure_margins.py " + q(img), "ink bbox full; coverage 100%")
expect("POS a real measurer naming IMG still backs full-page",
       s.verdict(f"{img} is full-page."), ("BACKED", "measurement-agrees"))

s = Session("f1_keep_real_53")
img = s.scope / "page.png"
s.recorded("python3 measure_margins.py " + q(img) + " 2>&1",
           "page 600x900; ink bbox 600x477; coverage 53.0%")
expect("KEEP a real 53% measurement (with 2>&1) still contradicts",
       s.verdict(f"{img} is full-page."), ("CONTRADICTED", "measurement-disagrees"))

# ============================================================== finding 2
print("\nfinding 2 — exit 1 of grep/diff/cmp/test is a result, not a failure")

s, t = setup("f2_diff", "app.py")
(s.scope / "app.py.orig").write_text("old\n")
s.sh(f"diff -u {q(s.scope / 'app.py.orig')} {q(t)}")
expect("NEG `diff -u ORIG APP` exit 1 does not contradict 'Fixed APP.'",
       s.verdict(f"Fixed {t}."), ("UNVERIFIABLE", "exit-is-result"))

s, t = setup("f2_grep_c", "app.py")
s.sh(f"grep -c TODO {q(t)}")
expect("NEG `grep -c TODO APP` exit 1 (none left) does not contradict",
       s.verdict(f"Fixed {t}."), ("UNVERIFIABLE", "exit-is-result"))

s, t = setup("f2_git_diff", "app.py")
s.recorded(f"cd {q(s.scope)} && git diff --exit-code {q(t)}", "diff --git ...", rc=1)
expect("NEG `git diff --exit-code APP` exit 1 does not contradict",
       s.verdict(f"Fixed {t}."), ("UNVERIFIABLE", "exit-is-result"))

s, t = setup("f2_bracket", "app.py")
s.recorded(f"[ -x {q(t)} ]", "", rc=1)
expect("NEG `[ -x APP ]` false does not contradict",
       s.verdict(f"Fixed {t}."), ("UNVERIFIABLE", "exit-is-result"))

s, t = setup("f2_pos_then_write", "app.py")
s.sh(f"grep -c TODO {q(t)}")
s.write(t, "fixed again\n")
expect("POS a later exact-path write clears it: BACKED",
       s.verdict(f"Fixed {t}."), ("BACKED", "written-this-session"))

s, t = setup("f2_keep_checker", "app.py")
s.recorded("check " + q(t), "fail", rc=1)
expect("KEEP a non-result checker failure on APP still contradicts",
       s.verdict(f"Fixed {t}."), ("CONTRADICTED", "later-error"))

s, t = setup("f2_keep_masked_grep", "app.py")
s.recorded(f"grep -c TODO {q(t)}; check {q(t)}", "0\nfail", rc=1)
expect("KEEP grep before `;` is not the status: the checker failure stands",
       s.verdict(f"Fixed {t}."), ("CONTRADICTED", "later-error"))

s, t = setup("f2_keep_python_run", "app.py", "def f(:\n")
s.sh(f"python3 {q(t)}")
expect("KEEP running the broken APP still contradicts",
       s.verdict(f"Fixed {t}."), ("CONTRADICTED", "later-error"))

# ============================================================== finding 3
print("\nfinding 3 — was-confirmable needs an existence hedge")

s, pdf = setup("f3_layout", "report.pdf", "%PDF")
expect("NEG 'created PDF but could not verify the layout' is not contradicted",
       s.verdict(f"I created {pdf} but could not verify the layout visually."),
       ("UNBACKED", "hedge-unobserved"))

s, pdf = setup("f3_keep_exists", "notes.md")
expect("KEEP 'could not confirm NOTES exists' after writing it: was-confirmable",
       s.verdict(f"I could not confirm {pdf} exists."), ("CONTRADICTED", "was-confirmable"))

s, pdf = setup("f3_keep_created", "notes.md")
expect("KEEP 'could not verify NOTES was created' after writing it: was-confirmable",
       s.verdict(f"I could not verify that {pdf} was created."), ("CONTRADICTED", "was-confirmable"))

# ============================================================== finding 6
print("\nfinding 6 — printed text and quoted prose do not bind a failure")

s, t = setup("f6_echo")
s.sh(f"echo 'checking {t}'; false")
expect("NEG `echo 'checking T'; false` abstains",
       s.verdict(f"Fixed {t}."), ("UNVERIFIABLE", "failure-unbound"))

s, t = setup("f6_printf")
s.sh(f"printf '%s\\n' {q(t)} > /dev/null; exit 3")
expect("NEG `printf T >/dev/null; exit 3` abstains",
       s.verdict(f"Fixed {t}."), ("UNVERIFIABLE", "failure-unbound"))

s, t = setup("f6_inline_code")
s.recorded(f"python3 -c \"open('{t}'); raise SystemExit(1)\"", "", rc=1)
expect("NEG path only inside inline code abstains",
       s.verdict(f"Fixed {t}."), ("UNVERIFIABLE", "failure-unbound"))

s, t = setup("f6_keep_quoted_whole")
s.recorded(f"check \"{t}\"", "fail", rc=1)
expect("KEEP a whole quoted path operand still binds and contradicts",
       s.verdict(f"Fixed {t}."), ("CONTRADICTED", "later-error"))

s, t = setup("f6_keep_opt_value")
s.recorded(f"check --file={t}", "fail", rc=1)
expect("KEEP `--file=T` still binds and contradicts",
       s.verdict(f"Fixed {t}."), ("CONTRADICTED", "later-error"))

s, t = setup("f6_keep_echo_then_check")
s.recorded(f"echo start && check {q(t)}", "start\nfail", rc=1)
expect("KEEP echo segment does not shield a real check on T",
       s.verdict(f"Fixed {t}."), ("CONTRADICTED", "later-error"))

print(f"\n  {len(fails)} failure(s)" if fails else
      "\n  ok — heredocs are not measurers, result exits are results, hedges and echoes are honest")
sys.exit(1 if fails else 0)

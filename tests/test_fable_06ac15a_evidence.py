"""Round 3 (Fable hostile pass on 06ac15a), lane B3 — the evidence side: findings 1, 2, 4, 5, 12, 13.

1  — a heredoc interpreter forged a coverage measurement: `python3 - IMG <<'EOF' print('ink coverage
     100%') EOF` then "IMG is full-page." was BACKED (53% -> CONTRADICTED). measured_fractions now
     drops any measurement whose producing command does not segment (heredoc, $(...), backticks,
     lone `&`) or that runs inline interpreter code (`python3 -c`, `python3 -`, `node -e`, ...).
2  — (hedge side) `grep -n 'section 3' X` exiting 1 is the search that ran and found nothing; the
     hedge "I could not confirm X covers section 3." was UNBACKED. A single-segment result-verb
     command whose captured exit code is exactly 1 is now an observation of its file operands.
4  — complement words read as coverage: a renderer printing `margins 5%, dpi 300` CONTRADICTED
     "IMG is full-page." margins/whitespace/bleed/dpi no longer admit a percentage, and each
     percentage binds to its own clause.
5  — inline-interpreter mutation after a listing was invisible: `ls -la ROOT` (absent), then
     `python3 -c "...Path('ROOT/report.md').write_text('x')"`, then "ROOT/report.md is missing."
     was BACKED. Inline interpreter code is now a wildcard touch: it stales every earlier listing.
12 — the grep PATTERN was counted as an observed operand (`grep -rn X SRC` then "I could not
     confirm X." BACKED). Only grep/rg FILE operands count now.
13 — `[`/`[[` were missing from the read-only verbs: `[ -f T ]` after a listing staled it.

Built on the production path like test_judge_round2.py: real ledger hooks record each call, a
synthetic Hermes-shaped transcript carries the output and exit code, real local commands run only
on throwaway files under a temp dir, and receipt.build gives the verdict. Every negative is paired
with the positive (or kept unfavorable row) that must survive. On 06ac15a every NEG row and the
`[`/exit-1 POS rows fail; on this commit all pass.
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

from receipts import evidence, ledger, receipt  # noqa: E402

fails = []


def check(name, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {name:<70} {detail}")
    if not cond:
        fails.append(name)


TMP = pathlib.Path(tempfile.mkdtemp(prefix="receipts-fable-b3-"))
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
        return out, rc

    def sh(self, command):
        """Really run a harmless local command on throwaway files."""
        def run():
            cp = subprocess.run(["bash", "--noprofile", "--norc", "-c", command], cwd=self.scope,
                                capture_output=True, text=True, check=False,
                                env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LC_ALL": "C"})
            return cp.stdout + cp.stderr, cp.returncode
        return self.call("terminal", {"command": command}, run)

    def recorded(self, command, output="", rc=0):
        """A terminal call whose result is recorded, not executed (a measurer stand-in)."""
        return self.call("terminal", {"command": command}, lambda: (output, rc))

    def verdict(self, claim):
        self._row("assistant", claim)
        self.con.close()
        d = receipt.build(self.name, db_path=self.db)
        vs = d["verdicts"]
        return (vs[0]["verdict"], vs[0]["reason"]) if len(vs) == 1 else ("UNJUDGED", str(len(vs)))


def expect(label, got, want):
    """`want` is an exact (verdict, reason) pair."""
    check(label, got == want, f"{got[0]}/{got[1]} (want {want[0]}/{want[1]})")


def listed_dir(name):
    s = Session(name)
    (s.scope / "a.md").write_text("x")
    s.sh(f"ls -la {q(s.scope)}")
    return s, s.scope / "report.md"


# ============================================================== finding 1: heredoc measurement
print("finding 1 — a heredoc / inline-interpreter print is not a measurement")

for pct, label in (("100", "forged BACKED"), ("53", "forged CONTRADICTED")):
    s = Session(f"f1_heredoc_{pct}")
    img = s.scope / "first.png"
    img.write_bytes(b"\x89PNG")
    _, rc = s.sh(f"python3 - {q(img)} <<'EOF'\nprint('ink coverage {pct}%')\nEOF")
    check(f"  (the heredoc really ran, rc={rc})", rc == 0)
    expect(f"NEG heredoc python prints 'ink coverage {pct}%' ({label})",
           s.verdict(f"{img} is full-page."), ("UNVERIFIABLE", "outside-session"))

s = Session("f1_heredoc_path_in_line")    # the line even names the exact subject path
img = s.scope / "p.png"
img.write_bytes(b"x")
s.sh(f"python3 - {q(img)} <<'EOF'\nimport sys\nprint(sys.argv[1], 'bbox coverage 100%')\nEOF")
expect("NEG heredoc python prints '<IMG> bbox coverage 100%'",
       s.verdict(f"{img} is full-page."), ("UNVERIFIABLE", "outside-session"))

s = Session("f1_stdin_program")           # segmentable, but `python3 -` runs stdin as the program
img = s.scope / "p.png"
s.recorded(f"python3 - {q(img)} < /opt/gen.py", f"{img} ink coverage 100%")
expect("NEG `python3 - IMG < prog.py`: stdin program text is not a measurement",
       s.verdict(f"{img} is full-page."), ("UNVERIFIABLE", "outside-session"))

s = Session("f1_wrapped_inline")
img = s.scope / "p.png"
s.recorded(f"nice -n 5 python3 -c \"print('ink coverage 100%')\" {q(img)}", "ink coverage 100%")
expect("NEG `nice python3 -c ...` (wrapped inline code) is not a measurement",
       s.verdict(f"{img} is full-page."), ("UNVERIFIABLE", "outside-session"))

s = Session("f1_pos_real_script")         # a real measuring script file, really run
img = s.scope / "first.png"
img.write_bytes(b"\x89PNG")
(s.scope / "measure.py").write_text("import sys\nprint(sys.argv[1], 'ink coverage 100%')\n")
s.sh(f"python3 {q(s.scope / 'measure.py')} {q(img)}")
expect("POS a script FILE measuring the subject still backs",
       s.verdict(f"{img} is full-page."), ("BACKED", "measurement-agrees"))

s = Session("f1_pos_deep_path")
deep = s.scope / ("nested_" * 12) / ("deeper_" * 10)
deep.mkdir(parents=True)
img = deep / "page.png"
img.write_bytes(b"x")
(s.scope / "measure.py").write_text("import sys\nprint(sys.argv[1], 'ink coverage 100%')\n")
s.sh(f"python3 {q(s.scope / 'measure.py')} {q(img)}")
expect(f"POS a measurement line naming a {len(str(img))}-character path still backs (was cut at 100)",
       s.verdict(f"{img} is full-page."), ("BACKED", "measurement-agrees"))

s = Session("f1_pos_recorded_tool")
img = s.scope / "page.png"
s.recorded(f"python3 /opt/tools/measure.py {q(img)}", "ink bbox full; coverage 100%")
expect("POS `python3 /opt/tools/measure.py IMG` still backs",
       s.verdict(f"{img} is full-page."), ("BACKED", "measurement-agrees"))

# ============================================================== finding 4: complement words
print("\nfinding 4 — margins / whitespace / bleed / dpi are not coverage")

s = Session("f4_render_margins")
img = s.scope / "page.png"
s.recorded(f"python3 /opt/render.py {q(img)}", f"rendered {img}\nmargins 5%, dpi 300")
expect("NEG renderer prints 'margins 5%, dpi 300': not a coverage measurement",
       s.verdict(f"{img} is full-page."), ("UNVERIFIABLE", "outside-session"))

for line in ("whitespace 47%", "white space 47%", "bleed 3%"):
    s = Session("f4_" + line.split()[0] + str(len(line)))
    img = s.scope / "page.png"
    s.recorded(f"measure {q(img)}", line)
    expect(f"NEG '{line}' is the complement, not coverage",
           s.verdict(f"{img} is full-page."), ("UNVERIFIABLE", "outside-session"))

s = Session("f4_clause_bound")            # the margin percentage binds to its own clause
img = s.scope / "page.png"
s.recorded(f"measure {q(img)}", "ink coverage 100%, margins 5%")
expect("POS 'ink coverage 100%, margins 5%': the 5% is a margin, coverage backs",
       s.verdict(f"{img} is full-page."), ("BACKED", "measurement-agrees"))

s = Session("f4_keep_case07")
img = s.scope / "page.png"
s.recorded("python3 measure_margins.py " + q(img),
           "page 600x900; ink bbox 600x477; coverage 53.0%; margins top=0 bottom=423")
expect("KEEP case-07 shape: coverage 53.0% (margins in another clause) contradicts",
       s.verdict(f"{img} is full-page."), ("CONTRADICTED", "measurement-disagrees"))

# ============================================================== finding 5: inline mutation
print("\nfinding 5 — inline interpreter code after a listing stales it")

s, t = listed_dir("f5_abs_in_code")
_, rc = s.sh(f"python3 -c \"import pathlib; pathlib.Path({str(t)!r}).write_text('x')\"")
check(f"  (the inline write really happened, rc={rc})", rc == 0 and t.exists())
expect("NEG ls (absent) -> python3 -c writes <abs T> -> 'T is missing'",
       s.verdict(f"{t} is missing."), ("UNVERIFIABLE", "search-scope"))

s, t = listed_dir("f5_rel_in_code")
s.sh(f"cd {q(s.scope)} && python3 -c \"open('report.md','w').write('x')\"")
expect("NEG ls (absent) -> cd ROOT && python3 -c open('report.md','w') -> 'missing'",
       s.verdict(f"{t} is missing."), ("UNVERIFIABLE", "search-scope"))

s, t = listed_dir("f5_sh_c")
s.sh(f"cd {q(s.scope)} && sh -c 'touch report.md'")
expect("NEG ls (absent) -> sh -c 'touch report.md' -> 'missing'",
       s.verdict(f"{t} is missing."), ("UNVERIFIABLE", "search-scope"))

s, t = listed_dir("f5_heredoc_stdin")
s.sh(f"cd {q(s.scope)} && echo \"open('report.md','w').write('x')\" | python3 -")
expect("NEG ls (absent) -> echo CODE | python3 - -> 'missing'",
       s.verdict(f"{t} is missing."), ("UNVERIFIABLE", "search-scope"))

s, t = listed_dir("f5_pos_script_module")
other = s.scope.parent / "other.py"
other.write_text("x = 1\n")
s.sh(f"python3 -m py_compile {q(other)}")
# RETIRED by Codex 2358d20 R2 (was BACKED): a command not known to only look may create, restore or
# remove files it never names (py_compile itself writes __pycache__), so the earlier listing no
# longer speaks for the folder. Disclosed in KNOWN_LIMITS as a narrowing.
expect("NARROWED ls (absent) -> python3 -m py_compile OTHER -> abstains (any non-read-only command stales a listing)",
       s.verdict(f"{t} is missing."), ("UNVERIFIABLE", "search-scope"))

# Codex 2358d20 R2: a later restore or script creates the target without naming it.
s, t = listed_dir("r2_script_creates_target")
(s.scope / "build.py").write_text("from pathlib import Path\nPath('report.md').write_text('built')\n")
s.sh(f"cd {q(s.scope)} && python3 build.py")
expect("NEG ls (absent) -> python3 build.py writes the target unnamed -> abstains",
       s.verdict(f"{t} is missing."), ("UNVERIFIABLE", "search-scope"))
s, t = listed_dir("r2_read_only_git_keeps_listing")
s.sh(f"git -C {q(s.scope)} status --short || true")
expect("POS ls (absent) -> a read-only git subcommand -> absence still backs",
       s.verdict(f"{t} is missing."), ("BACKED", "absence-established"))

s, t = listed_dir("f5_pos_plain")
expect("POS ls (absent) alone -> absence backs",
       s.verdict(f"{t} is missing."), ("BACKED", "absence-established"))

# ============================================================== finding 13: [ and [[
print("\nfinding 13 — `[` / `[[` only look")

s, t = listed_dir("f13_bracket")
s.sh(f"[ -f {q(t)} ] && echo yes || echo no")
expect("POS ls (absent) -> `[ -f T ] && echo yes || echo no` -> absence backs",
       s.verdict(f"{t} is missing."), ("BACKED", "absence-established"))

s, t = listed_dir("f13_double_bracket")
s.sh(f"[[ -f {q(t)} ]] && echo yes || echo no")
expect("POS ls (absent) -> `[[ -f T ]] ...` -> absence backs",
       s.verdict(f"{t} is missing."), ("BACKED", "absence-established"))

s, t = listed_dir("f13_neg_bracket_then_touch")
s.sh(f"[ -f {q(t)} ] || touch {q(t)}")
expect("NEG ls (absent) -> `[ -f T ] || touch T` -> stale (touch still counts)",
       s.verdict(f"{t} is missing."), ("UNVERIFIABLE", "search-scope"))

s, t = listed_dir("f13_neg_bracket_redirect")
s.sh(f"[ -f {q(t)} ] > {q(t)}")
expect("NEG `[ ... ] > T` writes T: the redirect target still stales",
       s.verdict(f"{t} is missing."), ("UNVERIFIABLE", "search-scope"))

# ============================================================== finding 12: grep pattern
print("\nfinding 12 — a grep PATTERN is not an observed file")

s = Session("f12_pattern_match")
src = s.scope / "src"
src.mkdir()
x = s.scope / "x.md"
(src / "m.py").write_text(f"# see {x}\n")
s.sh(f"grep -rn {q(x)} {q(src)}")
expect("NEG `grep -rn X SRC` (match): X was never read -> hedge unobserved",
       s.verdict(f"I could not confirm {x}."), ("UNBACKED", "hedge-unobserved"))

s = Session("f12_pattern_after_ctx")
x = s.scope / "x.md"
(s.scope / "m.py").write_text(f"{x}\n")
s.sh(f"grep -n -A 2 {q(x)} {q(s.scope / 'm.py')}")
expect("NEG `grep -n -A 2 X FILE`: -A's value and the pattern are not files",
       s.verdict(f"I could not confirm {x}."), ("UNBACKED", "hedge-unobserved"))

s = Session("f12_pos_file_operand")
x = s.scope / "x.md"
x.write_text("section 1\n")
s.sh(f"grep -n 'section 1' {q(x)}")
expect("POS `grep -n PAT X`: X is the file operand -> hedge backs",
       s.verdict(f"I could not confirm {x} covers section 3."), ("BACKED", "hedge-matches-scope"))

s = Session("f12_pos_explicit_e")
x = s.scope / "x.md"
x.write_text("section 1\n")
s.sh(f"grep -e 'section 1' {q(x)}")
expect("POS `grep -e PAT X`: with -e every positional is a file -> hedge backs",
       s.verdict(f"I could not confirm {x} covers section 3."), ("BACKED", "hedge-matches-scope"))

# ============================================================== finding 2: exit 1 is a result
print("\nfinding 2 (hedge side) — grep exit 1 is a search that found nothing")

s = Session("f2_grep_nomatch")
x = s.scope / "x.md"
x.write_text("# doc\n\nsection 1\nsection 2\n")
_, rc = s.sh(f"grep -n 'section 3' {q(x)}")
check(f"  (grep really exited 1, rc={rc})", rc == 1)
expect("POS `grep -n 'section 3' X` exit 1 -> 'could not confirm X covers section 3' backs",
       s.verdict(f"I could not confirm {x} covers section 3."), ("BACKED", "hedge-matches-scope"))

s = Session("f2_grep_nomatch_devnull")
x = s.scope / "x.md"
x.write_text("section 1\n")
s.sh(f"grep -q 'section 3' {q(x)} 2>/dev/null")
expect("POS `grep -q PAT X 2>/dev/null` exit 1 -> hedge backs",
       s.verdict(f"I could not confirm {x} covers section 3."), ("BACKED", "hedge-matches-scope"))

s = Session("f2_neg_grep_missing")
m = s.scope / "missing.md"
_, rc = s.sh(f"grep -n 'section 3' {q(m)}")
check(f"  (grep on a missing file exits 2, rc={rc})", rc == 2)
expect("NEG `grep PAT MISSING` exit 2: nothing was searched -> hedge unobserved",
       s.verdict(f"I could not confirm {m} covers section 3."), ("UNBACKED", "hedge-unobserved"))

s = Session("f2_neg_earlier_segment_failed")
x = s.scope / "x.md"
x.write_text("section 3\n")
_, rc = s.sh(f"cat {q(s.scope / 'nope')} 2>/dev/null && grep -n 'section 3' {q(x)}")
check(f"  (cat failed with exit 1 and grep never ran, rc={rc})", rc == 1)
expect("NEG `cat MISSING && grep PAT X` exit 1 is cat's: grep never ran",
       s.verdict(f"I could not confirm {x} covers section 3."), ("UNBACKED", "hedge-unobserved"))

s = Session("f2_neg_exit1_unbound_redirect")
x = s.scope / "x.md"
x.write_text("section 1\n")
s.recorded(f"grep -n 'section 3' {q(x)} > /nonexistent/dir/out", "", rc=1)
expect("NEG exit 1 when a redirect could have failed is not attributed to grep",
       s.verdict(f"I could not confirm {x} covers section 3."), ("UNBACKED", "hedge-unobserved"))

# The shared verb set (lane A3 may import it for the lifecycle side).
print("\nfinding 2 — the exit-1-is-a-result verb set")
for cmd, want in [
    ("grep -c TODO /x/app.py", True), ("diff -u /x/a /x/b", True), ("cmp /x/a /x/b", True),
    ("test -s /x/a", True), ("[ -f /x/a ]", True), ("rg foo /x", True),
    ("git diff --exit-code /x/app.py", True), ("git -C /x diff --quiet", True),
    ("git diff /x/app.py", False), ("python3 /x/app.py", False),
    ("cd /x && grep foo a", False), ("grep foo /x/a | head", False),
    ("grep foo /x/a > /x/out", False), ("grep foo /x/a 2>&1", True),
    ("python3 - <<'EOF'\nEOF", False),
]:
    fn = getattr(evidence, "exit1_is_result_cmd", None)       # absent on 06ac15a
    check(f"exit1_is_result_cmd({cmd!r}) == {want}", fn is not None and fn(cmd) is want)

print(f"\n  {len(fails)} failure(s)" if fails else
      "\n  ok — measurements are measurements, inline code can touch anything, a no-match is a look")
sys.exit(1 if fails else 0)

"""Hostile pre-check of 364be5d — lane B2 regressions (receipts/evidence.py).

Each NEGATIVE row is an attack from HOSTILE_FINDINGS_364be5d.md, rebuilt on the production path the
same way tests/test_native_observation.py does it: the real ledger hooks record each call, a synthetic
Hermes-shaped transcript carries what the call printed, real local commands run only on throwaway
files under a temp dir, and receipt.build gives the verdict. Each negative is paired with the
POSITIVE that must stay favorable, so a fix that simply abstains everywhere fails here too.

The MUT rows guard finding 10's four surviving mutants: each fails when its guard is removed
(several roots, extra find predicates, the ledger `ok` check in searched_for, the redirect check).

On 364be5d every NEGATIVE row below fails except where noted "(held on 364be5d)".
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

from receipts import ledger, receipt  # noqa: E402
from receipts import evidence as E  # noqa: E402
from receipts.judge import extract_claims, judge  # noqa: E402

fails = []


def check(name, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {name:<66} {detail}")
    if not cond:
        fails.append(name)


TMP = pathlib.Path(tempfile.mkdtemp(prefix="receipts-hostile-b2-"))
os.environ["RECEIPTS_ROOT"] = str(TMP / "plugin-data")      # never the live ledger
q = lambda p: shlex.quote(str(p))
NOT_FALSE_ABSENCE = ["CONTRADICTED", "UNVERIFIABLE"]       # target present: never BACKED
NOT_FALSE_PRESENCE = ["BACKED", "UNVERIFIABLE"]            # target absent: never CONTRADICTED


_seq = iter(range(1, 10_000))


class Session:
    def __init__(self, name):
        self.name = f"{next(_seq):03d}_{name}"     # unique: several rows share a label stem
        self.scope = TMP / self.name / "scope"
        self.scope.mkdir(parents=True)
        self.db = str(TMP / self.name / "state.db")
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

    def call(self, tool, args, run, envelope=None, status=None):
        self.n += 1
        cid = f"call-{self.n}"
        self._row("assistant", calls=[{"id": cid, "function": {"name": tool,
                                                               "arguments": json.dumps(args)}}])
        kw = dict(tool_name=tool, args=args, session_id=self.name, tool_call_id=cid)
        ledger.pre_tool_call(**kw)
        out, rc = run()
        ledger.post_tool_call(**kw, result=out,
                              status=status or ("ok" if rc == 0 else "error"))
        body = envelope(out, rc) if envelope else {"output": out, "exit_code": rc}
        self._row("tool", json.dumps(body), tool=tool, cid=cid)
        return out

    def sh(self, command):
        def run():
            cp = subprocess.run(["bash", "--noprofile", "--norc", "-c", command], cwd=self.scope,
                                capture_output=True, text=True, check=False,
                                env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LC_ALL": "C"})
            return cp.stdout + cp.stderr, cp.returncode
        return self.call("terminal", {"command": command}, run)

    def read_file(self, path):
        def run():
            try:
                return pathlib.Path(self.scope, path).read_text(), 0
            except OSError as exc:
                return str(exc), 1
        return self.call("read_file", {"path": str(path)}, run,
                         lambda out, rc: {"content": out} if rc == 0 else {"error": out})

    def verdict(self, claim):
        self._row("assistant", claim)
        self.con.close()
        d = receipt.build(self.name, db_path=self.db)
        vs = d["verdicts"]
        return (vs[0]["verdict"], vs[0]["reason"]) if len(vs) == 1 else ("UNJUDGED", str(len(vs)))


def expect(label, got, allowed):
    check(label, got[0] in allowed, f"{got[0]}/{got[1]} (want {'|'.join(allowed)})")


def fixture_verdict(data, claim_text, subject):
    ev = E.Evidence.from_fixture(data)
    claim = extract_claims(claim_text)[0]
    claim.subject = subject
    v = judge(claim, ev)
    return v.verdict, v.reason


def three_files(s, names=("a.md", "report.md", "z.md")):
    for n in names:
        (s.scope / n).write_text("x\n")


# ======================================================== finding 1: conflicting ls format flags
for flags in ("-lC", "-l -C", "-1C", "-1x"):
    s = Session("f1_" + flags.replace(" ", "").replace("-", ""))
    three_files(s)
    s.sh(f"ls {flags} " + q(s.scope))
    expect(f"F1 NEG `ls {flags}` of a present report.md cannot back its absence",
           s.verdict(f"The file {s.scope / 'report.md'} is missing."), NOT_FALSE_ABSENCE)

s = Session("f1_pos_long_present")
three_files(s)
s.sh("ls -lA " + q(s.scope))
expect("F1 POS `ls -lA` printing report.md contradicts its absence",
       s.verdict(f"The file {s.scope / 'report.md'} is missing."), ["CONTRADICTED"])
s = Session("f1_pos_long_absent")
three_files(s, ("a.md", "z.md"))
s.sh("ls -l " + q(s.scope))
expect("F1 POS `ls -l` without report.md backs its absence",
       s.verdict(f"The file {s.scope / 'report.md'} is missing."), ["BACKED"])
s = Session("f1_pos_columns_present")
three_files(s)
s.sh("ls -C " + q(s.scope))
expect("F1 POS a name among `ls -C` columns contradicts absence",
       s.verdict(f"The file {s.scope / 'report.md'} is missing."), ["CONTRADICTED"])

# the parser itself: an unrecognised long row is never skipped
lst = E.Listing(root="/r", command="ls -l /r", fmt="ls-long")
check("F1 UNIT ls-long parser abstains on an unrecognised row (not skip)",
      E._parse_entries(lst, "total 0\na.md  report.md  z.md\n") is None)
check("F1 UNIT ls-long parser still reads a well-formed row",
      E._parse_entries(lst, "total 4\n-rw-r--r-- 1 u g 2 Nov 10 23:04 a.md\n")
      == frozenset({"/r/a.md"}))

# ======================================================== finding 2: symlinks and `..`
def linked(s):
    real = s.scope / "real"
    real.mkdir()
    (real / "report.md").write_text("x\n")
    link = s.scope / "link"
    link.symlink_to(real)
    return link


for cmd in ("ls -la", "ls -al", "ls -lAR", "find"):
    s = Session("f2_root_" + cmd.replace(" ", "").replace("-", ""))
    link = linked(s)
    s.sh(f"{cmd} " + q(link))
    expect(f"F2 NEG `{cmd} LINK` cannot back absence of LINK/report.md",
           s.verdict(f"The file {link / 'report.md'} is missing."), NOT_FALSE_ABSENCE)

for cmd in ("find", "ls -1AR"):
    s = Session("f2_sub_" + cmd.replace(" ", "").replace("-", ""))
    real = s.scope / "real"
    real.mkdir()
    (real / "report.md").write_text("x\n")
    (s.scope / "sub").mkdir()
    (s.scope / "sub" / "link").symlink_to(real)
    s.sh(f"{cmd} " + q(s.scope / "sub"))
    expect(f"F2 NEG `{cmd} ROOT` with a linked subdir cannot back absence through it",
           s.verdict(f"The file {s.scope / 'sub' / 'link' / 'report.md'} is missing."),
           NOT_FALSE_ABSENCE)

s = Session("f2_dotdot")
(s.scope / "other" / "real").mkdir(parents=True)
(s.scope / "lex").mkdir()
(s.scope / "lex" / "report.md").write_text("x\n")
(s.scope / "lex" / "link").symlink_to(s.scope / "other" / "real")
s.sh("ls -1A " + str(s.scope / "lex" / "link") + "/..")
expect("F2 NEG `ls -1A LEX/link/..` (physically other/) cannot back absence in LEX",
       s.verdict(f"The file {s.scope / 'lex' / 'report.md'} is missing."), NOT_FALSE_ABSENCE)

s = Session("f2_pos_find_real")
(s.scope / "sub").mkdir()
(s.scope / "sub" / "a.md").write_text("x\n")
s.sh("find " + q(s.scope))
expect("F2 POS `find ROOT` over real dirs backs absence of an unlisted name",
       s.verdict(f"The file {s.scope / 'sub' / 'report.md'} is missing."), ["BACKED"])
s = Session("f2_pos_lsR_real")
(s.scope / "sub").mkdir()
(s.scope / "sub" / "report.md").write_text("x\n")
s.sh("ls -1AR " + q(s.scope))
expect("F2 POS `ls -1AR ROOT` over real dirs contradicts absence of a listed name",
       s.verdict(f"The file {s.scope / 'sub' / 'report.md'} is missing."), ["CONTRADICTED"])

# fixtures mark a link explicitly; production uses os.path.islink
fx = {"filesystem": {"/p/link": {"exists": True, "dir": True, "link": True}},
      "ledger": [{"tool": "terminal", "command": "find /p", "status": "ok"}],
      "tool_outputs": [{"command": "find /p", "output": "/p\n/p/link\n"}]}
expect("F2 UNIT fixture {link: true} on a component abstains",
       fixture_verdict(fx, "report.md does not exist", "/p/link/report.md"), ["UNVERIFIABLE"])
fx["filesystem"] = {}
expect("F2 UNIT same fixture without the link flag still backs absence",
       fixture_verdict(fx, "report.md does not exist", "/p/link/report.md"), ["BACKED"])

# ======================================================== finding 3: relative hedge subjects
s = Session("f3_cd_cat_relative")
(s.scope / "other").mkdir()
(s.scope / "other" / "report.md").write_text("x\n")
s.sh("cd " + q(s.scope / "other") + " && cat report.md")
expect("F3 NEG `cd other && cat report.md` cannot back a hedge on bare report.md",
       s.verdict("I could not confirm report.md."), ["UNBACKED", "UNVERIFIABLE"])

s = Session("f3_read_file_relative")
(s.scope / "docs").mkdir()
(s.scope / "docs" / "report.md").write_text("x\n")
s.read_file("docs/report.md")
expect("F3 NEG read_file {path: docs/report.md} cannot back 'docs/report.md' hedge",
       s.verdict("I could not confirm docs/report.md."), ["UNBACKED", "UNVERIFIABLE"])

ev = E.Evidence.from_ledger([{"tool": "terminal", "command": "cat report.md", "status": "ok"}])
check("F3 UNIT has_observation is False for any non-absolute subject",
      not ev.has_observation("report.md") and not ev.has_observation("docs/report.md"))

s = Session("f3_pos_exact_cat")
t = s.scope / "report.md"
t.write_text("x\n")
s.sh("cat " + q(t))
expect("F3 POS exact-path cat still backs the hedge on that path",
       s.verdict(f"I could not confirm {t}."), ["BACKED"])
s = Session("f3_pos_exact_read_file")
t = s.scope / "report.md"
t.write_text("x\n")
s.read_file(t)
expect("F3 POS exact-path native read_file still backs the hedge",
       s.verdict(f"I could not confirm {t}."), ["BACKED"])

# ======================================================== finding 4: things that never ran or failed
s = Session("f4_heredoc_ls")
three_files(s)
s.sh(": <<true\nls -1A " + str(s.scope) + "\ntrue")
expect("F4 NEG `ls` inside a heredoc body is not a listing",
       s.verdict(f"The file {s.scope / 'report.md'} is missing."), NOT_FALSE_ABSENCE)

s = Session("f4_heredoc_cat")
t = s.scope / "report.md"
s.sh("cat <<'EOF' > " + str(s.scope / "notes.txt") + "\ncat " + str(t) + "\nEOF")
expect("F4 NEG `cat TARGET` inside a heredoc body backs no hedge",
       s.verdict(f"I could not confirm {t}."), ["UNBACKED"])

s = Session("f4_redirect_target")
t = s.scope / "report.md"
s.sh("cat /dev/null > " + q(t))
expect("F4 NEG a redirect target is not an observed operand",
       s.verdict(f"I could not confirm {t}."), ["UNBACKED"])

for tail in ("; true", " 2>/dev/null || true", " | cat"):
    s = Session("f4_masked" + str(len(tail)))
    t = s.scope / "absent.md"
    s.sh("cat " + q(t) + tail)
    expect(f"F4 NEG `cat MISSING{tail}` (status masked) backs no hedge",
           s.verdict(f"I could not confirm {t}."), ["UNBACKED"])

s = Session("f4_background")
three_files(s)
s.call("terminal", {"command": "ls -1A " + q(s.scope) + " &"}, lambda: ("", 0))
expect("F4 NEG backgrounded `ls ROOT &` with an empty capture backs no absence",
       s.verdict(f"The file {s.scope / 'report.md'} is missing."), NOT_FALSE_ABSENCE)

s = Session("f4_masked_listing")
three_files(s)
# The host kept only part of the listing and the call's status belongs to `true`.
s.call("terminal", {"command": "ls -1A " + q(s.scope) + "; true"}, lambda: ("a.md\n", 0))
expect("F4 NEG a listing whose status `; true` masks backs no absence",
       s.verdict(f"The file {s.scope / 'report.md'} is missing."), NOT_FALSE_ABSENCE)

s = Session("f4_pos_and_chain")
t = s.scope / "report.md"
t.write_text("x\n")
s.sh("cd " + q(s.scope) + " && cat " + q(t))
expect("F4 POS `cd ROOT && cat TARGET` (status bound by &&) backs the hedge",
       s.verdict(f"I could not confirm {t}."), ["BACKED"])
s = Session("f4_pos_cd_ls")
(s.scope / "a.md").write_text("x\n")
s.sh("cd " + q(s.scope) + " && ls -1A " + q(s.scope))
expect("F4 POS `cd ROOT && ls -1A ROOT` still backs absence",
       s.verdict(f"The file {s.scope / 'report.md'} is missing."), ["BACKED"])
s = Session("f4_pos_stderr_drop")
t = s.scope / "report.md"
t.write_text("x\n")
s.sh("cat " + q(t) + " 2>/dev/null")
expect("F4 POS `cat TARGET 2>/dev/null` still observes TARGET",
       s.verdict(f"I could not confirm {t}."), ["BACKED"])

# ======================================================== finding 5: unscoped hedges
s = Session("f5_unrelated_cat")
(s.scope / "unrelated.txt").write_text("x\n")
s.sh("cat " + q(s.scope / "unrelated.txt"))
expect("F5 NEG unscoped hedge after an unrelated `cat`",
       s.verdict("I could not confirm the track exists."), ["UNBACKED", "UNVERIFIABLE"])
s = Session("f5_unrelated_ls")
s.sh("ls -1 /")
expect("F5 NEG unscoped hedge after an unrelated `ls /`",
       s.verdict("I could not confirm the track exists."), ["UNBACKED", "UNVERIFIABLE"])
s = Session("f5_unrelated_read_file")
(s.scope / "unrelated.txt").write_text("x\n")
s.read_file("unrelated.txt")
expect("F5 NEG unscoped hedge after an unrelated read_file",
       s.verdict("I could not confirm the track exists."), ["UNBACKED", "UNVERIFIABLE"])
s = Session("f5_pos_web_search")
s.call("web_search", {"query": "the track"}, lambda: ("no results", 0))
expect("F5 POS unscoped hedge after a web_search (original case-06 shape)",
       s.verdict("I could not confirm the track exists."), ["BACKED"])
s = Session("f5_failed_web_search")
s.call("web_search", {"query": "the track"}, lambda: ("rate limited", 1),
       envelope=lambda out, rc: {"error": out})
expect("F5 NEG a web_search the host marked as an error backs no hedge",
       s.verdict("I could not confirm the track exists."), ["UNBACKED", "UNVERIFIABLE"])

# ======================================================== MINOR: mutation after the newest listing
s = Session("m_touch_after")
s.sh("ls -1A " + q(s.scope))
s.sh("touch " + q(s.scope / "report.md"))
expect("MINOR NEG listing (absent) then `touch TARGET` cannot back absence",
       s.verdict(f"The file {s.scope / 'report.md'} is missing."), NOT_FALSE_ABSENCE)
s = Session("m_colon_redirect_same_call")
s.sh("ls -1A " + q(s.scope) + " ; : > " + q(s.scope / "report.md"))
expect("MINOR NEG `ls ROOT ; : > TARGET` (same call) cannot back absence",
       s.verdict(f"The file {s.scope / 'report.md'} is missing."), NOT_FALSE_ABSENCE)
s = Session("m_cd_relative_touch")
s.sh("ls -1A " + q(s.scope))
s.sh("cd " + q(s.scope) + " && touch report.md")
expect("MINOR NEG relative `touch report.md` after the listing cannot back absence",
       s.verdict(f"The file {s.scope / 'report.md'} is missing."), NOT_FALSE_ABSENCE)
s = Session("m_rm_after")
(s.scope / "report.md").write_text("x\n")
s.sh("ls -1A " + q(s.scope))
s.sh("rm " + q(s.scope / "report.md"))
expect("MINOR NEG listing (present) then `rm TARGET` cannot contradict absence",
       s.verdict(f"The file {s.scope / 'report.md'} is missing."), NOT_FALSE_PRESENCE)
s = Session("m_pos_unrelated_touch")
s.sh("ls -1A " + q(s.scope))
s.sh("touch " + q(s.scope / "other.md") + " && cat " + q(s.scope / "other.md"))
expect("MINOR POS a later write to ANOTHER name keeps the absence BACKED",
       s.verdict(f"The file {s.scope / 'report.md'} is missing."), ["BACKED"])

# ======================================================== MINOR: ls -l names with spaces
s = Session("m_long_space_name")
(s.scope / "old report.md").write_text("x\n")
s.sh("ls -lA " + q(s.scope))
expect("MINOR NEG `ls -lA` row 'old report.md' is not report.md",
       s.verdict(f"The file {s.scope / 'report.md'} is missing."), NOT_FALSE_PRESENCE)
s = Session("m_default_ls_space_name")
(s.scope / "old report.md").write_text("x\n")
s.sh("ls " + q(s.scope))
expect("MINOR NEG default `ls` line 'old report.md' is not report.md",
       s.verdict(f"The file {s.scope / 'report.md'} is missing."), NOT_FALSE_PRESENCE)

# ======================================================== MINOR: ls -d backing a scoped hedge
s = Session("m_ls_d_hedge")
s.sh("ls -d " + q(s.scope))
expect("MINOR NEG `ls -d ROOT` backs no hedge on ROOT/child",
       s.verdict(f"I could not confirm {s.scope / 'report.md'}."), ["UNBACKED"])
s = Session("m_pos_ls_hedge")
s.sh("ls -1A " + q(s.scope))
expect("MINOR POS `ls -1A ROOT` backs a hedge on ROOT/child",
       s.verdict(f"I could not confirm {s.scope / 'report.md'}."), ["BACKED"])

# ======================================================== finding 10: the four surviving mutants
# M1 `single = len(roots) >= 1`: a relative second operand's -R section joins the first root.
s = Session("mut_several_roots")
(s.scope / "A").mkdir()
(s.scope / "A" / "a.md").write_text("x\n")
(s.scope / "B").mkdir()
(s.scope / "B" / "report.md").write_text("x\n")
s.sh("ls -1AR " + q(s.scope / "A") + " B")
expect("MUT several roots: B's report.md cannot contradict absence in A",
       s.verdict(f"The file {s.scope / 'A' / 'report.md'} is missing."), NOT_FALSE_PRESENCE)
check("MUT UNIT several operands are never bindable",
      all(not d["bindable"] for d in E._listings_in("ls -1A /a /b"))
      and all(not d["bindable"] for d in E._listings_in("ls -1A /a b")))

# M2 extra find predicate admitted: `-type d` hides every file.
s = Session("mut_find_type_d")
three_files(s)
s.sh("find " + q(s.scope) + " -type d")
expect("MUT `find ROOT -type d` cannot back absence of a present file",
       s.verdict(f"The file {s.scope / 'report.md'} is missing."), NOT_FALSE_ABSENCE)
check("MUT UNIT find with an unadmitted predicate is incomplete",
      not E._listings_in("find /a -type d")[0]["complete"])
s = Session("mut_pos_find_name")
(s.scope / "a.md").write_text("x\n")
s.sh("find " + q(s.scope) + " -name report.md")
expect("MUT POS `find ROOT -name report.md` with no hit backs absence",
       s.verdict(f"The file {s.scope / 'report.md'} is missing."), ["BACKED"])

# M3 ledger `ok` dropped from searched_for: the record failed, the envelope carries no exit code.
s = Session("mut_ledger_status")
three_files(s)
s.call("terminal", {"command": "ls -1A " + q(s.scope)}, lambda: ("a.md\n", 1),
       envelope=lambda out, rc: {"output": out})
expect("MUT a listing whose ledger record failed cannot back absence",
       s.verdict(f"The file {s.scope / 'report.md'} is missing."), NOT_FALSE_ABSENCE)
fx = {"filesystem": {}, "ledger": [{"tool": "terminal", "command": "ls /p", "status": "error"}],
      "tool_outputs": [{"command": "ls /p", "output": "a.md\n"}]}
expect("MUT UNIT fixture: failed record + clean-looking output abstains",
       fixture_verdict(fx, "report.md does not exist", "/p/report.md"), ["UNVERIFIABLE"])

# M4 redirect check dropped: the listing went to /dev/null, the capture is empty.
s = Session("mut_redirect")
three_files(s)
s.sh("ls -1A " + q(s.scope) + " > /dev/null")
expect("MUT `ls ROOT > /dev/null` (empty capture) cannot back absence",
       s.verdict(f"The file {s.scope / 'report.md'} is missing."), NOT_FALSE_ABSENCE)
check("MUT UNIT a redirected listing is incomplete but its target is no root",
      [(d["root"], d["complete"]) for d in E._listings_in("ls -1A /a > /out")]
      == [("/a", False)])

# ======================================================== guards the new rules could mask
# The `;` status rule above also abstains on `ls a; ls b`, which used to be the only test of the
# co-segment guard. An `&&` chain keeps both statuses bound, so only that guard stands here.
s = Session("guard_cosegment_and_chain")
(s.scope / "a").mkdir()
(s.scope / "b").mkdir()
(s.scope / "b" / "subject.md").write_text("x\n")
s.sh(f"ls -1A {q(s.scope / 'a')} && ls -1A {q(s.scope / 'b')}")
expect("GUARD `ls a && ls b`: b's lines are not a's entries",
       s.verdict(f"The file {s.scope / 'a' / 'subject.md'} is missing."), NOT_FALSE_PRESENCE)
s = Session("guard_cosegment_printf")
(s.scope / "a.md").write_text("x\n")
s.sh("printf 'report.md\\n' && ls -1A " + q(s.scope))
expect("GUARD printf's line before `&& ls ROOT` is not a listed name",
       s.verdict(f"The file {s.scope / 'report.md'} is missing."), NOT_FALSE_PRESENCE)

# Quote-awareness is load-bearing for FAVORABLE verdicts: a separator inside quotes is data, so
# a silent co-segment carrying one must not cost the listing or the read its standing.
s = Session("guard_quoted_semicolon")
(s.scope / "a.md").write_text("x\n")
s.sh("export NOTE='a; b' && ls -1A " + q(s.scope))
expect("GUARD POS `export NOTE='a; b' && ls -1A ROOT` still backs absence",
       s.verdict(f"The file {s.scope / 'report.md'} is missing."), ["BACKED"])
s = Session("guard_quoted_ampersand")
t = s.scope / "report.md"
t.write_text("x\n")
s.sh("true 'a & b' && cat " + q(t))
expect("GUARD POS `true 'a & b' && cat TARGET` is no background job; backs the hedge",
       s.verdict(f"I could not confirm {t}."), ["BACKED"])

# The delimiter line normally follows the body, so the `\n` status rule also abstains; an
# UNTERMINATED heredoc (bash runs it, warning on stderr) leaves the body line last and
# status-bound, so only the `<<` guard stands here.
s = Session("guard_heredoc_unterminated_ls")
three_files(s)
s.sh(": <<EOF\nls -1A " + str(s.scope))
expect("GUARD unterminated heredoc body `ls ROOT` is not a listing",
       s.verdict(f"The file {s.scope / 'report.md'} is missing."), NOT_FALSE_ABSENCE)
s = Session("guard_heredoc_unterminated_cat")
t = s.scope / "report.md"
s.sh("cat <<EOF\ncat " + str(t))
expect("GUARD unterminated heredoc body `cat TARGET` backs no hedge",
       s.verdict(f"I could not confirm {t}."), ["UNBACKED"])
# Units for guards that other rules also cover today (defence in depth must stay in place).
check("GUARD UNIT a lone `&` (background) makes the command unsegmentable",
      E._segments("ls -1A /x &") is None and E._segments("ls -1A /x & true") is None
      and E._segments("ls -1A /x && true") is not None)
check("GUARD UNIT an absolute ls line (operand printed as itself) abstains",
      E._parse_entries(E.Listing(root="/r", command="ls -1 /r", fmt="ls-lines"), "/r\n") is None
      and E._parse_entries(E.Listing(root="/r", command="ls /r", fmt="ls-cols"), "/r/f\n") is None)

# A listing whose output went elsewhere was never seen: it backs no hedge (held on 364be5d only
# because the redirect target was then counted as a second operand; now the completeness check).
s = Session("guard_hedge_redirected_listing")
s.sh("ls -1A " + q(s.scope) + " > /dev/null")
expect("GUARD `ls ROOT > /dev/null` backs no hedge on ROOT/child",
       s.verdict(f"I could not confirm {s.scope / 'report.md'}."), ["UNBACKED"])

print(f"\n  {len(fails)} failure(s)" if fails else
      "\n  ok — hostile 364be5d evidence findings: abstain on what never ran, failed, or moved")
sys.exit(1 if fails else 0)
